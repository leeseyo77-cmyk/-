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
    GUIDELINE_LOADED = True
except ImportError as e:
    st.warning(f"⚠️ guideline_data.py: {e}")
    PAVEMENT = {}
    GUIDELINE_LOADED = False

try:
    from weather_data import REGION_MAPPING, get_total_non_work_days, get_monthly_breakdown
    WEATHER_LOADED = True
except ImportError as e:
    st.warning(f"⚠️ weather_data.py: {e}")
    REGION_MAPPING = {
        "서울": "서울", "경기": "경기", "인천": "인천", "강원": "강원",
        "충북": "충북", "충남": "충남", "대전": "대전", "세종": "세종",
        "전북": "전북", "전남": "전남", "광주": "광주", "경북": "경북",
        "경남": "경남", "대구": "대구", "울산": "울산", "부산": "부산", "제주": "제주"
    }
    def get_total_non_work_days(*args, **kwargs):
        return 0
    def get_monthly_breakdown(*args, **kwargs):
        return []
    WEATHER_LOADED = False

MODULES_LOADED = GUIDELINE_LOADED and WEATHER_LOADED

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

def extract_district_roman(num_val, name_val):
    """
    A열(번호)과 B열(공종명)에서 로마숫자 지구 추출
    
    패턴 1: A열에 "I", "II", "III" 등 (영문 로마숫자)
    패턴 2: A열에 "Ⅰ", "Ⅱ", "Ⅲ" 등 (유니코드 로마숫자)
    패턴 3: B열에 "Ⅰ. 제1지구" 형식
    
    Returns: "Ⅰ", "Ⅱ", "Ⅲ" 등 (유니코드로 통일)
    """
    # 영문 → 유니코드 로마숫자 변환
    ROMAN_MAP = {
        "I": "Ⅰ", "II": "Ⅱ", "III": "Ⅲ", "IV": "Ⅳ", "V": "Ⅴ",
        "VI": "Ⅵ", "VII": "Ⅶ", "VIII": "Ⅷ", "IX": "Ⅸ", "X": "Ⅹ"
    }
    
    # 패턴 1: A열에서 영문 로마숫자
    if isinstance(num_val, str):
        num_clean = num_val.strip().upper()
        if num_clean in ROMAN_MAP:
            return ROMAN_MAP[num_clean]
    
    # 패턴 2: A열에서 유니코드 로마숫자
    if isinstance(num_val, str):
        num_clean = num_val.strip()
        if num_clean in ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"]:
            return num_clean
    
    # 패턴 3: B열에서 "Ⅰ. 제1지구" 패턴
    if isinstance(name_val, str):
        roman_pattern = r'^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\.'
        match = re.match(roman_pattern, name_val.strip())
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
        
        # 로마숫자 지구 감지 (A열과 B열 모두 확인)
        district_roman = extract_district_roman(num_val, name_val)
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
        spec = node.get("spec", "")
        unit = node.get("unit", "")
        quantity = node.get("quantity", 0)
        daily_work = node.get("daily_work", 0)
        work_days = node["work_days"]
        work_type = node["work_type"]
        valid = node["valid"]
        
        # 상세 정보 구성
        details = []
        if spec:
            details.append(f"규격: {spec}")
        if unit:
            details.append(f"단위: {unit}")
        if quantity:
            try:
                qty_num = float(quantity)
                details.append(f"수량: {qty_num:,.0f}")
            except (ValueError, TypeError):
                details.append(f"수량: {quantity}")
        if daily_work:
            try:
                daily_num = float(daily_work)
                details.append(f"일일작업량: {daily_num:,.1f}")
            except (ValueError, TypeError):
                details.append(f"일일작업량: {daily_work}")
        
        detail_str = " | ".join(details) if details else ""
        
        # 유효하지 않은 항목 (daily < 1 또는 quantity <= 0)
        if not valid:
            if detail_str:
                st.markdown(
                    f"{indent}`{number}` {name} <span style='color:gray'>({detail_str}) - 제외됨</span>", 
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"{indent}`{number}` {name} <span style='color:gray'>(데이터 없음)</span>", 
                    unsafe_allow_html=True
                )
        else:
            # 유효한 항목
            labor = labor_dict.get(work_type, DEFAULT_LABOR.get(work_type, 5))
            adjusted_days = work_days / labor if labor > 0 else work_days
            
            # 공종 배지
            type_badge = {
                "토공": "🟤",
                "관로공": "🔵",
                "구조물공": "🟢",
                "포장공": "🟡",
                "부대공": "🟠",
                "기타": "⚪"
            }.get(work_type, "⚪")
            
            if detail_str:
                st.markdown(
                    f"{indent}**{number}** {name} {type_badge} | {detail_str} | **{work_days}일 → {adjusted_days:.1f}일** (투입: {labor}조)",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"{indent}**{number}** {name} {type_badge} | **{work_days}일 → {adjusted_days:.1f}일** (투입: {labor}조)",
                    unsafe_allow_html=True
                )
        
        # 하위 항목 재귀 렌더링
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
        import tempfile
        import os
        
        # Windows/Linux 호환 임시 디렉토리 사용
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, uploaded_file.name)
        
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        districts_data = parse_excel_tree(file_path)
        
        if not districts_data:
            st.error("❌ 지구 정보를 찾을 수 없습니다. 엑셀 형식을 확인해주세요.")
            
            # 디버그: 엑셀 내용 미리보기
            st.subheader("🔍 디버그 정보")
            
            try:
                wb = openpyxl.load_workbook(file_path, data_only=True)
                ws = wb.active
                
                st.write("**엑셀 첫 20줄:**")
                preview_data = []
                for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), 1):
                    if any(cell is not None for cell in row):
                        preview_data.append({
                            "줄": idx,
                            "A(번호)": row[0],
                            "B(공종명)": row[1],
                            "C(규격)": row[2] if len(row) > 2 else None,
                            "D(단위)": row[3] if len(row) > 3 else None,
                        })
                
                df_preview = pd.DataFrame(preview_data)
                st.dataframe(df_preview, use_container_width=True)
                
                st.info("💡 **로마숫자 지구 표기 확인:**\n- 'Ⅰ. 제1지구' 형식으로 되어있나요?\n- B열(공종명)에 로마숫자가 있나요?")
                
                wb.close()
            except Exception as e:
                st.error(f"미리보기 실패: {e}")
            
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
        
        # 표시 형식 선택
        view_mode = st.radio(
            "표시 형식",
            options=["테이블", "트리"],
            horizontal=True,
            help="테이블: 데이터 그리드 형식 | 트리: 계층 구조 형식"
        )
        
        if view_mode == "테이블":
            # 계층별 확장 가능한 테이블
            
            def render_node_table(node, depth=0):
                """
                노드를 확장 가능한 테이블 형태로 렌더링
                """
                work_type = node["work_type"]
                labor = district_data["labor"].get(work_type, DEFAULT_LABOR.get(work_type, 5))
                
                # 숫자 안전 변환
                try:
                    work_days_num = float(node["work_days"]) if node["work_days"] else 0
                except:
                    work_days_num = 0
                
                try:
                    quantity = float(node.get("quantity", 0)) if node.get("quantity") else 0
                except:
                    quantity = 0
                
                try:
                    daily_work = float(node.get("daily_work", 0)) if node.get("daily_work") else 0
                except:
                    daily_work = 0
                
                adjusted_days = work_days_num / labor if labor > 0 and work_days_num > 0 else work_days_num
                
                # 공종 배지
                type_badge = {
                    "토공": "🟤",
                    "관로공": "🔵",
                    "구조물공": "🟢",
                    "포장공": "🟡",
                    "부대공": "🟠",
                    "기타": "⚪"
                }.get(work_type, "⚪")
                
                # 노드 정보
                has_children = len(node["children"]) > 0
                
                # Expander 또는 일반 표시
                if has_children:
                    # 하위 항목이 있으면 확장 가능
                    with st.expander(
                        f"{type_badge} **{node['number']}** {node['name']} — {work_days_num:.0f}일 → {adjusted_days:.1f}일",
                        expanded=False
                    ):
                        # 현재 노드 상세 정보
                        info_cols = st.columns([1, 1, 1, 1])
                        with info_cols[0]:
                            st.caption("**규격**")
                            st.text(node.get("spec", "-") or "-")
                        with info_cols[1]:
                            st.caption("**수량**")
                            st.text(f"{quantity:,.0f} {node.get('unit', '')}" if quantity > 0 else "-")
                        with info_cols[2]:
                            st.caption("**일일작업량**")
                            st.text(f"{daily_work:,.1f}" if daily_work > 0 else "-")
                        with info_cols[3]:
                            st.caption("**투입조수**")
                            st.text(f"{labor}조")
                        
                        st.divider()
                        
                        # 하위 항목 테이블
                        children_data = []
                        for child in node["children"]:
                            child_work_type = child["work_type"]
                            child_labor = district_data["labor"].get(child_work_type, DEFAULT_LABOR.get(child_work_type, 5))
                            
                            try:
                                child_work_days = float(child["work_days"]) if child["work_days"] else 0
                            except:
                                child_work_days = 0
                            
                            try:
                                child_qty = float(child.get("quantity", 0)) if child.get("quantity") else 0
                            except:
                                child_qty = 0
                            
                            try:
                                child_daily = float(child.get("daily_work", 0)) if child.get("daily_work") else 0
                            except:
                                child_daily = 0
                            
                            child_adjusted = child_work_days / child_labor if child_labor > 0 and child_work_days > 0 else child_work_days
                            
                            children_data.append({
                                "번호": child["number"],
                                "공종명": child["name"],
                                "규격": child.get("spec", "") or "",
                                "단위": child.get("unit", "") or "",
                                "수량": child_qty,
                                "일일작업량": child_daily,
                                "원공기": child_work_days,
                                "투입조수": child_labor,
                                "조정공기": round(child_adjusted, 1),
                                "공종": child_work_type,
                                "하위": "📁" if len(child["children"]) > 0 else ""
                            })
                        
                        if children_data:
                            df_children = pd.DataFrame(children_data)
                            st.dataframe(
                                df_children,
                                use_container_width=True,
                                hide_index=True,
                                column_config={
                                    "번호": st.column_config.TextColumn("번호", width="small"),
                                    "공종명": st.column_config.TextColumn("공종명", width="medium"),
                                    "규격": st.column_config.TextColumn("규격", width="small"),
                                    "단위": st.column_config.TextColumn("단위", width="small"),
                                    "수량": st.column_config.NumberColumn("수량", format="%.0f"),
                                    "일일작업량": st.column_config.NumberColumn("일일작업량", format="%.1f"),
                                    "원공기": st.column_config.NumberColumn("원공기", format="%.0f"),
                                    "투입조수": st.column_config.NumberColumn("투입조수", format="%d조"),
                                    "조정공기": st.column_config.NumberColumn("조정공기", format="%.1f"),
                                    "공종": st.column_config.TextColumn("공종", width="small"),
                                    "하위": st.column_config.TextColumn("하위", width="small"),
                                }
                            )
                        
                        # 하위 항목 재귀 렌더링
                        for child in node["children"]:
                            if len(child["children"]) > 0:
                                render_node_table(child, depth + 1)
                else:
                    # 하위 항목 없으면 일반 표시
                    indent = "　" * depth
                    detail_parts = []
                    if node.get("spec"):
                        detail_parts.append(f"규격: {node['spec']}")
                    if quantity > 0:
                        detail_parts.append(f"수량: {quantity:,.0f} {node.get('unit', '')}")
                    if daily_work > 0:
                        detail_parts.append(f"일일작업량: {daily_work:,.1f}")
                    
                    detail_str = " | ".join(detail_parts) if detail_parts else ""
                    
                    st.markdown(
                        f"{indent}{type_badge} **{node['number']}** {node['name']} — "
                        f"{detail_str} — **{work_days_num:.0f}일 → {adjusted_days:.1f}일** (투입: {labor}조)"
                    )
            
            # 루트 노드들 렌더링
            for root_node in district_data["tree"]:
                render_node_table(root_node)
            
            # 전체 요약
            st.divider()
            st.subheader("📊 전체 요약")
            
            # 전체 데이터 수집
            all_items = []
            def collect_all(nodes):
                for node in nodes:
                    try:
                        wd = float(node["work_days"]) if node["work_days"] else 0
                    except:
                        wd = 0
                    all_items.append(wd)
                    if node["children"]:
                        collect_all(node["children"])
            
            collect_all(district_data["tree"])
            
            summary_cols = st.columns(3)
            with summary_cols[0]:
                st.metric("총 항목 수", f"{len(all_items)}개")
            with summary_cols[1]:
                st.metric("총 원공기", f"{sum(all_items):.0f}일")
            with summary_cols[2]:
                total_adjusted = calculate_total_days(district_data["tree"], district_data["labor"])
                st.metric("총 조정공기", f"{total_adjusted}일")
        
        else:
            # 트리 형식
            # render_tree(district_data["tree"], labor_dict=district_data["labor"])
    
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