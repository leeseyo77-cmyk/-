# VERSION 3.0 - 지구별 분리 + 전체 TAB + 비작업일수 계산 수정본
import streamlit as st
import pandas as pd
import openpyxl
import re
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="상하수도 공기산정", layout="wide", initial_sidebar_state="expanded")

# ============================================================================
# 원본=
# ============================================================================
try:
    from guideline_data import PAVEMENT
    from weather_data import REGION_MAPPING, get_total_non_work_days, get_monthly_breakdown
    MODULES_LOADED = True
except ImportError as e:
    st.error(f"⚠️ 필수 모듈 로드 실패: {e}")
    st.error("weather_data.py와 guideline_data.py 파일을 확인해주세요.")
    MODULES_LOADED = False

# ============================================================================
# 상수 정의
# ============================================================================

VERSION = "3.0"

# 키워드 맵 (상세 분류용)
KEYWORD_MAP_DETAIL = {
    "토공": ["토공", "굴착", "되메우기", "성토", "절토", "터파기"],
    "관로공": ["관로공", "관거", "배관", "관 부설", "상수관로", "하수관로"],
    "구조물공": ["구조물", "맨홀", "우수받이", "집수정", "밸브", "배수로"],
    "포장공": ["포장", "아스팔트", "콘크리트포장", "보도블럭", "차도"],
    "부대공": ["부대공", "안전시설", "가설공사", "교통관리"],
    "기타": ["기타", "잡"]
}

# 공종별 표준 투입조수 (기본값)
DEFAULT_LABOR = {
    "토공": 5,
    "관로공": 8,
    "구조물공": 10,
    "포장공": 7,
    "부대공": 4,
    "기타": 3
}

# ============================================================================
# 유틸리티 함수
# ============================================================================

def extract_district_roman(text):
    """
    텍스트에서 로마숫자 지구 번호 추출
    예: "Ⅰ. 제1지구" → "Ⅰ"
    """
    if not isinstance(text, str):
        return None
    
    roman_pattern = r'^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\.'
    match = re.match(roman_pattern, text.strip())
    if match:
        return match.group(1)
    return None


def classify_work_type(name):
    """
    공종명으로 분류 (토공, 관로공, 구조물공, 포장공, 부대공, 기타)
    """
    if not isinstance(name, str):
        return "기타"
    
    name_clean = name.strip()
    
    for work_type, keywords in KEYWORD_MAP_DETAIL.items():
        for keyword in keywords:
            if keyword in name_clean:
                return work_type
    
    return "기타"


def is_valid_work_item(daily_work, quantity):
    """
    정상적인 작업 항목인지 검증
    - daily_work >= 1
    - quantity > 0
    """
    try:
        daily = float(daily_work) if daily_work is not None else 0
        qty = float(quantity) if quantity is not None else 0
        return daily >= 1.0 and qty > 0
    except (ValueError, TypeError):
        return False


# ============================================================================
# 엑셀 파싱 함수
# ============================================================================

def parse_excel_tree(file_path):
    """
    엑셀을 트리 구조로 파싱 (지구별 분리)
    
    Returns:
        dict: {
            "Ⅰ": {"name": "제1지구", "tree": [...], "labor": {...}},
            "Ⅱ": {"name": "제2지구", "tree": [...], "labor": {...}},
            ...
        }
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active
    
    districts = {}
    current_district = None
    current_tree = []
    
    # 계층 스택 (depth별 최근 노드 추적)
    stack = {}
    
    for row in ws.iter_rows(min_row=2, values_only=False):
        # A열: 번호, B열: 공종명, C열: 규격, D열: 단위, E열: 수량, F열: 일일작업량, G열: 소요일수
        num_cell = row[0]
        name_cell = row[1]
        spec_cell = row[2] if len(row) > 2 else None
        unit_cell = row[3] if len(row) > 3 else None
        qty_cell = row[4] if len(row) > 4 else None
        daily_cell = row[5] if len(row) > 5 else None
        days_cell = row[6] if len(row) > 6 else None
        
        num_val = num_cell.value if num_cell else None
        name_val = name_cell.value if name_cell else None
        
        if not name_val:
            continue
        
        # 로마숫자 지구 감지
        district_roman = extract_district_roman(str(name_val))
        if district_roman:
            # 새 지구 시작
            if current_district and current_tree:
                # 이전 지구 저장
                if current_district not in districts:
                    districts[current_district] = {
                        "name": districts.get(current_district, {}).get("name", f"제{current_district}지구"),
                        "tree": [],
                        "labor": DEFAULT_LABOR.copy()
                    }
                districts[current_district]["tree"] = current_tree
            
            current_district = district_roman
            current_tree = []
            stack = {}
            
            if current_district not in districts:
                districts[current_district] = {
                    "name": str(name_val).replace(f"{district_roman}.", "").strip(),
                    "tree": [],
                    "labor": DEFAULT_LABOR.copy()
                }
            continue
        
        # 지구가 설정되지 않은 경우 스킵
        if current_district is None:
            continue
        
        # 번호 체계로 depth 계산
        depth = 0
        num_str = str(num_val).strip() if num_val else ""
        
        if re.match(r'^\d+$', num_str):  # "1", "2" → depth 0
            depth = 0
        elif re.match(r'^\d+\.\d+$', num_str):  # "1.1", "1.2" → depth 1
            depth = 1
        elif re.match(r'^\d+\.\d+\.\d+$', num_str):  # "1.1.1" → depth 2
            depth = 2
        elif re.match(r'^\d+\)$', num_str):  # "1)", "2)" → depth 3
            depth = 3
        elif re.match(r'^\(\d+\)$', num_str):  # "(1)", "(2)" → depth 4
            depth = 4
        
        # 데이터 추출
        spec = spec_cell.value if spec_cell else ""
        unit = unit_cell.value if unit_cell else ""
        quantity = qty_cell.value if qty_cell else 0
        daily_work = daily_cell.value if daily_cell else 0
        work_days = days_cell.value if days_cell else 0
        
        # 노드 생성
        node = {
            "number": num_str,
            "name": str(name_val),
            "spec": spec,
            "unit": unit,
            "quantity": quantity,
            "daily_work": daily_work,
            "work_days": work_days,
            "depth": depth,
            "children": [],
            "work_type": classify_work_type(str(name_val)),
            "valid": is_valid_work_item(daily_work, quantity)
        }
        
        # 트리 구조 연결
        if depth == 0:
            current_tree.append(node)
            stack[depth] = node
        else:
            parent_depth = depth - 1
            if parent_depth in stack:
                stack[parent_depth]["children"].append(node)
            else:
                # 부모를 찾을 수 없으면 루트에 추가
                current_tree.append(node)
            stack[depth] = node
    
    # 마지막 지구 저장
    if current_district and current_tree:
        if current_district not in districts:
            districts[current_district] = {
                "name": f"제{current_district}지구",
                "tree": [],
                "labor": DEFAULT_LABOR.copy()
            }
        districts[current_district]["tree"] = current_tree
    
    wb.close()
    return districts


def calculate_total_days(tree, labor_dict):
    """
    트리에서 총 공기 계산 (병렬 작업 고려)
    """
    total_days = 0
    
    def traverse(nodes):
        nonlocal total_days
        for node in nodes:
            if node["valid"]:
                work_type = node["work_type"]
                labor = labor_dict.get(work_type, DEFAULT_LABOR.get(work_type, 5))
                days = node["work_days"] / labor if labor > 0 else node["work_days"]
                total_days += days
            
            if node["children"]:
                traverse(node["children"])
    
    traverse(tree)
    return int(total_days)


# ============================================================================
# UI 렌더링 함수
# ============================================================================

def render_tree(tree, depth=0, labor_dict=None):
    """
    트리를 계층적으로 표시 (Streamlit)
    """
    if labor_dict is None:
        labor_dict = DEFAULT_LABOR
    
    for node in tree:
        indent = "　" * depth
        number = node["number"]
        name = node["name"]
        work_days = node["work_days"]
        work_type = node["work_type"]
        valid = node["valid"]
        
        # 유효하지 않은 항목은 회색으로
        if not valid:
            st.markdown(f"{indent}`{number}` {name} <span style='color:gray'>({work_days}일 - 제외됨)</span>", unsafe_allow_html=True)
        else:
            labor = labor_dict.get(work_type, DEFAULT_LABOR.get(work_type, 5))
            adjusted_days = work_days / labor if labor > 0 else work_days
            st.markdown(f"{indent}**{number}** {name} ({work_days}일 → {adjusted_days:.1f}일, 투입: {labor}조)")
        
        if node["children"]:
            render_tree(node["children"], depth + 1, labor_dict)


# ============================================================================
# 메인 앱
# ============================================================================

def main():
    st.title("🏗️ 상하수도 공사 공기산정")
    st.caption(f"VERSION {VERSION}")
    
    # 사이드바: 파일 업로드
    with st.sidebar:
        st.header("⚙️ 기본 설정")
        
        uploaded_file = st.file_uploader(
            "📂 공사 유형",
            type=["xlsx"],
            help="200MB per file • XLSX"
        )
        
        st.info("💡 원액셀서 액셀 파일을 업로드하세요!")
    
    # 파일 업로드 전
    if uploaded_file is None:
        st.warning("👈 원액셀서 액셀 파일을 먼저 업로드하세요!")
        return
    
    # 파일 저장 및 파싱
    try:
        file_path = f"/tmp/{uploaded_file.name}"
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        districts_data = parse_excel_tree(file_path)
        
        if not districts_data:
            st.error("❌ 지구 정보를 찾을 수 없습니다. 엑셀 형식을 확인해주세요.")
            return
        
        st.success(f"✅ {len(districts_data)}개 지구 파싱 완료!")
        
    except Exception as e:
        st.error(f"❌ 파일 파싱 중 오류 발생: {e}")
        return
    
    # TAB 구성
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 개요",
        "📂 지구별 상세",
        "📊 종합 요약",
        "☂️ 비작업일수 계산기",
        "📅 공정표"
    ])
    
    # ========================================================================
    # TAB 1: 개요
    # ========================================================================
    with tab1:
        st.header("📋 공기산정 요약")
        
        st.subheader("🌍 지구 선택")
        district_names = {k: v["name"] for k, v in districts_data.items()}
        selected_district_key = st.selectbox(
            "지역 지역 선택",
            options=list(district_names.keys()),
            format_func=lambda x: f"{x}. {district_names[x]}"
        )
        
        selected_data = districts_data[selected_district_key]
        
        st.subheader("⚙️ 기본 설정")
        
        col1, col2 = st.columns(2)
        with col1:
            region_name = st.selectbox(
                "공사 지역 선택",
                options=list(REGION_MAPPING.keys()) if MODULES_LOADED else ["서울"],
                index=0
            )
        
        with col2:
            start_date = st.date_input(
                "공사 시작일",
                value=datetime(2026, 12, 25)
            )
        
        # 투입조수 설정
        st.subheader("👷 투입조수 설정")
        labor_dict = selected_data["labor"].copy()
        
        cols = st.columns(3)
        for idx, (work_type, default_val) in enumerate(DEFAULT_LABOR.items()):
            with cols[idx % 3]:
                labor_dict[work_type] = st.number_input(
                    f"{work_type}",
                    min_value=1,
                    max_value=50,
                    value=labor_dict.get(work_type, default_val),
                    step=1,
                    key=f"labor_{selected_district_key}_{work_type}"
                )
        
        # 순공기 계산
        pure_days = calculate_total_days(selected_data["tree"], labor_dict)
        
        # 비작업일수 계산
        if MODULES_LOADED:
            end_date = start_date + timedelta(days=pure_days)
            non_work_days = get_total_non_work_days(region_name, start_date, end_date)
        else:
            non_work_days = 0
        
        total_days = pure_days + non_work_days
        final_end_date = start_date + timedelta(days=total_days)
        
        # 결과 표시
        st.divider()
        st.subheader("📊 산정 결과")
        
        metric_cols = st.columns(4)
        with metric_cols[0]:
            st.metric("순공기", f"{pure_days}일")
        with metric_cols[1]:
            st.metric("비작업일수", f"{non_work_days}일")
        with metric_cols[2]:
            st.metric("총 공기", f"{total_days}일")
        with metric_cols[3]:
            st.metric("예상 완공일", final_end_date.strftime("%y.%m.%d"))
    
    # ========================================================================
    # TAB 2: 지구별 상세
    # ========================================================================
    with tab2:
        st.header("📂 지구별 상세 내역")
        
        tab_district = st.selectbox(
            "지구 선택",
            options=list(district_names.keys()),
            format_func=lambda x: f"{x}. {district_names[x]}",
            key="tab2_district"
        )
        
        district_data = districts_data[tab_district]
        
        st.subheader(f"{tab_district}. {district_data['name']}")
        
        # 트리 표시
        render_tree(district_data["tree"], labor_dict=district_data["labor"])
    
    # ========================================================================
    # TAB 3: 종합 요약
    # ========================================================================
    with tab3:
        st.header("📊 종합 요약")
        
        summary_data = []
        for district_key, district_info in districts_data.items():
            days = calculate_total_days(district_info["tree"], district_info["labor"])
            summary_data.append({
                "지구": f"{district_key}. {district_info['name']}",
                "순공기": days
            })
        
        df_summary = pd.DataFrame(summary_data)
        st.dataframe(df_summary, use_container_width=True, hide_index=True)
        
        st.metric("전체 순공기 합계", f"{df_summary['순공기'].sum()}일")
    
    # ========================================================================
    # TAB 4: 비작업일수 계산기
    # ========================================================================
    with tab4:
        st.header("☂️ 비작업일수 계산기")
        
        if not MODULES_LOADED:
            st.error("weather_data.py 모듈을 로드할 수 없어 비작업일수 계산 기능을 사용할 수 없습니다.")
            return
        
        st.markdown("""
        공사 기간 중 기후 조건에 따른 비작업일수를 계산합니다.
        - **강우일**: 일 강수량 기준 작업 불가일
        - **한랭일**: 일 최저기온 -10°C 이하
        - **폭염일**: 일 최고기온 33°C 이상
        """)
        
        # 기본 설정
        col1, col2 = st.columns(2)
        
        with col1:
            calc_start_date = st.date_input(
                "공사 시작일",
                value=datetime(2026, 12, 25),
                help="공사가 시작되는 날짜를 선택하세요",
                key="calc_start_date"
            )
        
        with col2:
            calc_region = st.selectbox(
                "지역 선택",
                options=list(REGION_MAPPING.keys()),
                index=0,
                help="공사 지역을 선택하세요",
                key="calc_region"
            )
        
        work_days_input = st.number_input(
            "순공기(작업일수)",
            min_value=1,
            max_value=10000,
            value=1200,
            step=10,
            help="실제 작업이 필요한 일수를 입력하세요"
        )
        
        # 기후 조건 체크박스
        st.subheader("🌦️ 기후 조건 선택")
        st.caption("제외할 기후 조건을 선택하세요")
        
        col_a, col_b, col_c = st.columns(3)
        
        with col_a:
            check_rain = st.checkbox(
                "💧 강우일 제외", 
                value=True,
                help="강수량 기준 작업 불가일을 포함합니다"
            )
        
        with col_b:
            check_cold = st.checkbox(
                "❄️ 한랭일 제외", 
                value=True,
                help="일 최저기온 -10°C 이하인 날을 포함합니다"
            )
        
        with col_c:
            check_hot = st.checkbox(
                "🌡️ 폭염일 제외", 
                value=True,
                help="일 최고기온 33°C 이상인 날을 포함합니다"
            )
        
        st.divider()
        
        # 계산 버튼
        if st.button("🔢 비작업일수 계산", type="primary", use_container_width=True):
            try:
                # 종료일 계산
                calc_end_date = calc_start_date + timedelta(days=work_days_input)
                
                # 비작업일수 계산
                non_work_days = get_total_non_work_days(
                    calc_region, 
                    calc_start_date, 
                    calc_end_date,
                    check_rain=check_rain,
                    check_cold=check_cold,
                    check_hot=check_hot
                )
                
                # 실제 총공기
                total_calc_days = work_days_input + non_work_days
                actual_end_date = calc_start_date + timedelta(days=total_calc_days)
                
                # 결과 표시
                st.success(f"✅ 계산 완료!")
                
                # 메트릭 표시
                metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
                
                with metric_col1:
                    st.metric(
                        label="순공기",
                        value=f"{work_days_input:,}일",
                        help="실제 작업일수"
                    )
                
                with metric_col2:
                    st.metric(
                        label="비작업일수",
                        value=f"{non_work_days:,}일",
                        delta=f"{(non_work_days/work_days_input*100):.1f}%",
                        help="기후 조건으로 인한 작업 불가일"
                    )
                
                with metric_col3:
                    st.metric(
                        label="총 공기",
                        value=f"{total_calc_days:,}일",
                        help="순공기 + 비작업일수"
                    )
                
                with metric_col4:
                    st.metric(
                        label="예상 완공일",
                        value=actual_end_date.strftime('%y.%m.%d'),
                        help="공사 종료 예정일"
                    )
                
                # 상세 정보
                st.info(f"""
                📅 **공사 기간**: {calc_start_date.strftime('%Y년 %m월 %d일')} ~ {actual_end_date.strftime('%Y년 %m월 %d일')}  
                📍 **지역**: {calc_region}  
                🌦️ **적용 조건**: {'강우일' if check_rain else ''} {'한랭일' if check_cold else ''} {'폭염일' if check_hot else ''}
                """)
                
                # 월별 상세 내역
                st.subheader("📊 월별 비작업일수 상세")
                
                monthly_data = get_monthly_breakdown(
                    calc_region,
                    calc_start_date,
                    calc_end_date,
                    check_rain=check_rain,
                    check_cold=check_cold,
                    check_hot=check_hot
                )
                
                if monthly_data:
                    df_monthly = pd.DataFrame(monthly_data)
                    df_monthly.columns = ["월", "강우일", "한랭일", "폭염일", "합계"]
                    
                    st.dataframe(
                        df_monthly,
                        use_container_width=True,
                        hide_index=True
                    )
                
            except Exception as e:
                st.error(f"❌ 계산 중 오류 발생")
                st.error(f"오류 내용: {str(e)}")
                st.info("날짜와 지역을 다시 확인해주세요.")
    
    # ========================================================================
    # TAB 5: 공정표
    # ========================================================================
    with tab5:
        st.header("📅 공정표")
        st.info("🚧 공정표 기능은 개발 중입니다.")


if __name__ == "__main__":
    main()