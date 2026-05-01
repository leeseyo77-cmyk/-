import streamlit as st
import pandas as pd
import openpyxl
import math
import re
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

st.set_page_config(page_title="상하수도 공기산정", layout="wide", initial_sidebar_state="expanded")

# ══════════════════════════════════════════════════════════════
# 공종 키워드 매핑
# ══════════════════════════════════════════════════════════════
KEYWORD_MAP_DETAIL = {
    "굴착공": ["터파기","굴착","줄파기","착공","시굴","포장깨기","포장절단","아스팔트"],
    "관부설공": ["관 부설","관부설","PE다중벽관","고강성PVC","주철관","GRP관",
                 "유리섬유복합관","흄관","이중벽관","강관부설","콘크리트관"],
    "되메우기": ["되메우기","뒤채움","복토","성토"],
    "포장복구": ["포장복구","아스팔트포장","콘크리트포장","보도포장","인도포장","포장"],
    "맨홀공": ["맨홀","우수받이","집수정","토실","슬라이딩"],
    "배수설비": ["배수설비","빗물받이"],
    "추진공": ["추진공","추진관","추진"],
}

SKIP_NAMES = [
    "남천지구","동부지구","신설오수관로","간선관로","지선관로",
    "순공사비","배수설비공사","토공","관로공","구조물공","포장공",
    "추진공","부대공","안전관리비","환경보전비","소계","합계","계",
]

PIPE_EXCLUDE = ["절단","이형관","하차비","단관","마감캡","추진관"]

MACHINE_BASED = ["터파기","굴착","되메우기","모래기초","모래부설","모래,관기초"]

# ══════════════════════════════════════════════════════════════
# 가이드라인 부록 데이터
# ══════════════════════════════════════════════════════════════
GUIDELINE_APPENDIX1 = {
    "아스팔트포장 절단": {"daily": 1000, "unit": "m"},
    "아스팔트포장깨기 (B.H0.4㎥)": {"daily": 515, "unit": "㎡"},
    "아스팔트포장깨기 (B.H0.7㎥)": {"daily": 1047, "unit": "㎡"},
    "터파기(토사:육상) B/H 0.4㎥": {"daily": 260, "unit": "㎥"},
    "터파기(토사:육상) B/H 0.7㎥": {"daily": 530, "unit": "㎥"},
    "터파기(암:육상) B/H 0.4㎥": {"daily": 130, "unit": "㎥"},
    "터파기(암:육상) B/H 0.7㎥": {"daily": 265, "unit": "㎥"},
    "되메우기(진동롤러) 2.5ton": {"daily": 600, "unit": "㎥"},
    "되메우기(진동롤러) 4.0ton": {"daily": 950, "unit": "㎥"},
}

GUIDELINE_APPENDIX2_PIPE = {
    200: {"daily": 5, "unit": "본/일"},
    300: {"daily": 4, "unit": "본/일"},
    450: {"daily": 3, "unit": "본/일"},
    600: {"daily": 2.5, "unit": "본/일"},
    800: {"daily": 2, "unit": "본/일"},
    1000: {"daily": 1.5, "unit": "본/일"},
    1200: {"daily": 1.2, "unit": "본/일"},
}

GUIDELINE_APPENDIX2_MANHOLE = {
    "원형맨홀 Φ1200": {"daily": 2.5, "unit": "개소/일"},
    "원형맨홀 Φ1500": {"daily": 2.5, "unit": "개소/일"},
    "각형맨홀 1800×2400": {"daily": 1.5, "unit": "개소/일"},
    "우수받이": {"daily": 5, "unit": "개소/일"},
}

# ══════════════════════════════════════════════════════════════
# 표준품셈 노무량 데이터
# ══════════════════════════════════════════════════════════════
def get_excavation_labor_detail(spec_str):
    """터파기 표준품셈 노무량"""
    labor_table = {
        0.4: {"인/m3": 0.130},
        0.7: {"인/m3": 0.085},
        1.0: {"인/m3": 0.070},
    }
    
    if "0.4" in spec_str or "B.H0.4" in spec_str or "B/H 0.4" in spec_str:
        return labor_table[0.4]
    elif "0.7" in spec_str or "B.H0.7" in spec_str or "B/H 0.7" in spec_str:
        return labor_table[0.7]
    elif "1.0" in spec_str or "B.H1.0" in spec_str or "B/H 1.0" in spec_str:
        return labor_table[1.0]
    
    return {"인/m3": 0.085}

def get_pipe_labor(name, diameter, grade="A"):
    """관 부설 표준품셈 노무량"""
    pipe_labor = {
        200: {"보통인부": 0.264, "특별인부": 0.066, "배관공": 0.066, "합계": 0.396},
        300: {"보통인부": 0.330, "특별인부": 0.082, "배관공": 0.082, "합계": 0.494},
        450: {"보통인부": 0.435, "특별인부": 0.109, "배관공": 0.109, "합계": 0.653},
        600: {"보통인부": 0.528, "특별인부": 0.132, "배관공": 0.132, "합계": 0.792},
        800: {"보통인부": 0.660, "특별인부": 0.165, "배관공": 0.165, "합계": 0.990},
        1000: {"보통인부": 0.792, "특별인부": 0.198, "배관공": 0.198, "합계": 1.188},
        1200: {"보통인부": 0.924, "특별인부": 0.231, "배관공": 0.231, "합계": 1.386},
    }
    
    closest = min(pipe_labor.keys(), key=lambda x: abs(x - diameter))
    return pipe_labor.get(closest, {"합계": 0.5})

# ══════════════════════════════════════════════════════════════
# 유틸리티 함수
# ══════════════════════════════════════════════════════════════
def is_machine_based(name):
    """장비 기반 공종 여부"""
    return any(kw in name for kw in MACHINE_BASED)

def extract_diameter(spec_str):
    """규격에서 관경 추출"""
    patterns = [r'D\s*[=＝]?\s*(\d+)',r'Φ\s*(\d+)',r'φ\s*(\d+)',
                r'(\d{2,4})\s*(?:mm|㎜)',r'[D=]?(\d{2,4})']
    for pat in patterns:
        m = re.search(pat, spec_str)
        if m:
            val = int(m.group(1))
            if 50 <= val <= 3000:
                return val
    return None

def calc_work_days(name, spec, qty, crews=3):
    """가이드라인 부록 1일 작업량 조회"""
    # 부록1 체크
    for key, val in GUIDELINE_APPENDIX1.items():
        if key in name or key in spec:
            return val
    
    # 부록2 - 관 부설
    if any(kw in name for kw in ["관 부설","관부설","고강성PVC","PE다중벽","이중벽관"]):
        dia = extract_diameter(spec)
        if dia:
            closest = min(GUIDELINE_APPENDIX2_PIPE.keys(), key=lambda x: abs(x - dia))
            return GUIDELINE_APPENDIX2_PIPE[closest]
    
    # 부록2 - 맨홀
    for key, val in GUIDELINE_APPENDIX2_MANHOLE.items():
        if key in name:
            return val
    
    return None

def extract_q_from_dangagun(uploaded_file, item_name):
    """
    단가산출근거 시트에서 시간당 작업량(Q) 추출
    반환: {"hourly": 250, "unit": "m³/Hr"} 또는 None
    """
    try:
        wb = openpyxl.load_workbook(uploaded_file, data_only=True)
        
        if '단가산출근거' not in wb.sheetnames:
            return None
        
        ws = wb['단가산출근거']
        
        # 항목명으로 해당 섹션 찾기
        found_section = False
        
        for row in ws.iter_rows(min_row=1, values_only=True):
            row_text = " ".join([str(c) for c in row if c])
            
            # 공종명이 포함된 행 찾기
            if item_name in row_text:
                found_section = True
            
            # Q 값 찾기 (섹션을 찾은 후 100줄 이내)
            if found_section and "Q =" in row_text:
                # 패턴 1: Q = 2000 m³/일 /8 Hr = 250.00 m³/Hr
                match1 = re.search(r'=\s*([\d.]+)\s*([^/\s]+/Hr)', row_text, re.IGNORECASE)
                if match1:
                    hourly_val = float(match1.group(1))
                    unit = match1.group(2).replace("HR", "Hr").replace("hr", "Hr")
                    return {"hourly": hourly_val, "unit": unit}
                
                # 패턴 2: Q = 숫자 단위
                match2 = re.search(r'Q\s*=\s*([\d.]+)\s*([^\s]+)', row_text)
                if match2:
                    hourly_val = float(match2.group(1))
                    unit = match2.group(2)
                    return {"hourly": hourly_val, "unit": unit}
        
        return None
        
    except Exception:
        return None

def calc_days_priority(name, spec, qty, crews=3):
    """
    작업일수 계산 우선순위
    1순위: 가이드라인 부록1,2 1일작업량
    2순위: 표준품셈 Man-day
    3순위: 노무비 역산
    반환: (작업일수, 1일작업량라벨, 계산방식)
    """
    if not qty or qty <= 0:
        return 0, "-", "-"

    # ── 1순위: 가이드라인 1일작업량 ──────────────────────────
    try:
        wd = calc_work_days(name, spec, qty, crews=crews)
        if wd and isinstance(wd, dict):
            base_daily = wd.get("daily", 0)
            unit = wd.get("unit", "")
            if base_daily > 0:
                if is_machine_based(name):
                    days = math.ceil(qty / (base_daily * crews))
                    label = f"{base_daily}{unit}/일×{crews}대"
                else:
                    days = math.ceil(qty / (base_daily * crews))
                    label = f"{base_daily}{unit}/일×{crews}조"
                return days, label, "가이드라인 부록"
    except Exception:
        pass

    # ── 2순위: 표준품셈 Man-day ───────────────────────────────
    try:
        manday = 0
        # 터파기
        if any(kw in name for kw in ["터파기","굴착","줄파기"]) and "운반" not in name:
            info = get_excavation_labor_detail(spec)
            rate = info.get("인/m3") if info else None
            if rate:
                manday = rate * qty

        # 관 부설
        pipe_kws = ["관 부설","관부설","이중벽관","주철관","흄관","콘크리트관",
                    "GRP관","유리섬유복합관","파형강관","PE다중벽","고강성PVC","강관부설"]
        if any(kw in name for kw in pipe_kws) and not manday:
            dia = extract_diameter(spec)
            if dia:
                info = get_pipe_labor(name, dia, "A")
                rate = info.get("합계") if info and isinstance(info, dict) else None
                if rate:
                    manday = rate * qty

        if manday > 0:
            days = math.ceil(manday / (8 * crews))
            return days, f"{round(manday/qty,3)}인/단위×{crews}조", "표준품셈 Man-day"
    except Exception:
        pass
    
    # ── 3순위: 단가산출근거 시간당 작업량(Q) ──────────────────
    try:
        if "dangagun_cache" in st.session_state:
            cache = st.session_state["dangagun_cache"]
            
            # 항목명으로 캐시에서 찾기
            for cached_name, info in cache.items():
                if cached_name in name or name in cached_name:
                    hourly_val = info.get("hourly", 0)
                    unit = info.get("unit", "")
                    
                    if hourly_val > 0:
                        # 1일 작업량 = 시간당 × 8시간
                        daily_val = hourly_val * 8
                        days = math.ceil(qty / (daily_val * crews))
                        return days, f"{daily_val:.1f}{unit.replace('/Hr','/일')}×{crews}조", "단가산출근거"
    except Exception:
        pass

    return 0, "-", "-"

# ══════════════════════════════════════════════════════════════
# 비작업일수 데이터 및 함수
# ══════════════════════════════════════════════════════════════
HOLIDAYS_DB = {
    2025:{1:8,2:4,3:7,4:4,5:6,6:6,7:4,8:6,9:4,10:9,11:5,12:5},
    2026:{1:5,2:7,3:6,4:4,5:7,6:5,7:4,8:7,9:7,10:7,11:5,12:5},
    2027:{1:6,2:7,3:5,4:4,5:7,6:4,7:4,8:6,9:7,10:8,11:4,12:6},
    2028:{1:9,2:4,3:5,4:5,5:6,6:5,7:5,8:5,9:4,10:10,11:4,12:6},
    2029:{1:5,2:7,3:5,4:5,5:7,6:5,7:5,8:5,9:8,10:6,11:4,12:6},
    2030:{1:5,2:7,3:6,4:4,5:6,6:6,7:4,8:5,9:8,10:6,11:4,12:6},
}

RAIN = {1:0,2:1,3:2,4:3,5:4,6:6,7:8,8:7,9:5,10:3,11:2,12:1}

def get_kr_holidays(year):
    m = HOLIDAYS_DB.get(year, {})
    holidays = set()
    for month, count in m.items():
        for day in range(1, count + 1):
            try:
                holidays.add(datetime(year, month, day).date())
            except:
                pass
    return holidays

def calc_completion_date(start, work_days):
    current, worked = start, 0
    kr_holidays = get_kr_holidays(start.year) | get_kr_holidays(start.year + 1)
    while worked < work_days:
        if current.weekday() == 6 or current in kr_holidays or current.day % 30 < RAIN[current.month]:
            current += timedelta(days=1)
            continue
        worked += 1
        current += timedelta(days=1)
    return current - timedelta(days=1)

def fmt_ok(val):
    return f"{val/1e8:.1f}억"

# ══════════════════════════════════════════════════════════════
# 엑셀 파서
# ══════════════════════════════════════════════════════════════
def parse_by_keyword(file):
    """엑셀 내역서 파싱"""
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    skip_sheets = ["목차","안내","INITIAL","초기","index"]
    priority = ["설계내역서","내역서","공사비내역서"]
    target_sheet = None
    
    for p in priority:
        if p in wb.sheetnames:
            target_sheet = p
            break
    if not target_sheet:
        for sname in wb.sheetnames:
            if any(sk in sname for sk in skip_sheets):
                continue
            if "내역" in sname:
                target_sheet = sname
                break
    if not target_sheet:
        for sname in wb.sheetnames:
            if not any(sk in sname for sk in skip_sheets):
                target_sheet = sname
                break
    if not target_sheet:
        target_sheet = wb.sheetnames[0]

    ws = wb[target_sheet]
    
    col_info = {"시트명": target_sheet}
    header_row = None
    
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=30, values_only=True), 1):
        row_str = " ".join([str(c) for c in row if c])
        if any(k in row_str for k in ["공종","품명","세부품명","명칭","내역"]):
            header_row = row_idx
            break
    
    if not header_row:
        header_row = 1
    
    col_info["헤더행"] = header_row
    
    all_rows = list(ws.iter_rows(min_row=header_row, values_only=True))
    if not all_rows:
        return [], col_info
    
    results = []
    
    for row in all_rows[1:]:
        if not row or all(c is None for c in row):
            continue
        
        # 기본 추출
        gong_jong = str(row[0]).strip() if row[0] else ""
        name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        spec = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        qty = row[3] if len(row) > 3 else 0
        unit = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        
        # 스킵 조건
        if not name or any(skip in name for skip in SKIP_NAMES):
            continue
        
        try:
            qty = float(qty) if qty else 0
        except:
            qty = 0
        
        if qty <= 0:
            continue
        
        # 공종 분류
        group = "기타"
        for grp, keywords in KEYWORD_MAP_DETAIL.items():
            if any(kw in name for kw in keywords):
                group = grp
                break
        
        # 관부설공 중 절단·이형관·하차비는 작업일수 계산 불필요 → 기타로 분류
        if group == "관부설공" and any(ex in name for ex in PIPE_EXCLUDE):
            group = "기타"
        
        # 상세 규격 추출
        detail_spec = spec
        if not detail_spec and name:
            spec_match = re.search(r'\([^)]+\)', name)
            if spec_match:
                detail_spec = spec_match.group(0)
        
        results.append({
            "gong_jong": gong_jong,
            "group": group,
            "name": name,
            "spec": detail_spec,
            "qty": qty,
            "unit": unit,
            "amount": row[5] if len(row) > 5 else 0,
            "labor": row[6] if len(row) > 6 else 0,
            "is_night": "-야간" in name,
        })
    
    # 중복 제거 (같은 name+spec 합산)
    merged = {}
    for r in results:
        key = (r["name"], r["spec"])
        if key not in merged:
            merged[key] = dict(r)
            merged[key]["name"] = r["name"].split("(")[0].strip()
        else:
            merged[key]["qty"] = (merged[key].get("qty") or 0) + (r.get("qty") or 0)
            merged[key]["amount"] = (merged[key].get("amount") or 0) + (r.get("amount") or 0)
            merged[key]["labor"] = (merged[key].get("labor") or 0) + (r.get("labor") or 0)
    
    return list(merged.values()), col_info

# ══════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════
st.sidebar.header("⚙️ 기본 설정")

st.sidebar.markdown("""
<div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            padding: 20px; 
            border-radius: 10px; 
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
    <h3 style='color: white; margin: 0 0 10px 0; font-size: 18px;'>🚧 공사 유형 선택</h3>
    <p style='color: #e0e7ff; margin: 0; font-size: 14px;'>현재: <strong style='color: #fbbf24;'>하수관로</strong></p>
    <p style='color: #9ca3af; margin: 5px 0 0 0; font-size: 11px;'>※ 향후 하수처리시설, 복합공사 추가 예정</p>
</div>
""", unsafe_allow_html=True)

project_type = st.sidebar.selectbox(
    "공사 유형",
    ["하수관로", "하수처리시설 (준비중)", "하수관로+하수처리시설 (준비중)"],
    disabled=False,
    help="현재는 하수관로만 지원합니다. 다른 유형은 개발 중입니다."
)

st.sidebar.info("📅 **공사 시작일**은\n\nTAB 4(비작업일수)에서 설정합니다.")
st.sidebar.markdown("---")

# ══════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════
st.title("상하수도 관로공사 공기산정 시스템")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 공기산정",
    "📂 엑셀 내역서 인식",
    "🔍 주요공종 CP 분석",
    "🌧 비작업일수 계산기",
    "📄 공기산정 보고서"
])

# ══════════════════════════════════════════════════════════════
# TAB 2: 엑셀 내역서 인식 (내역서 기반 계층 구조)
# ══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("📂 엑셀 내역서 자동 인식 (내역서 기반)")
    st.caption("도급 설계내역서 업로드 → 계층 구조 자동 파싱 → 공종별 투입조수 조정")

    uploaded = st.file_uploader("설계내역서 엑셀 (.xlsx)", type=["xlsx","xls"])

    if uploaded:
        try:
            with st.spinner("파싱 중..."):
                all_rows, col_info = parse_by_keyword(uploaded)

            matched = [r for r in all_rows if r["group"] != "기타" and r["qty"] is not None]
            unmatched = [r for r in all_rows if r["group"] == "기타" and r["qty"] is not None]

            st.success(f"시트 **{col_info['시트명']}** | 인식 **{len(matched)}건** | 미인식 **{len(unmatched)}건**")

            if matched:
                st.markdown("---")
                st.subheader("📂 내역서 기반 공종 분류")
                
                # 계층 구조 파싱 (원본 엑셀에서)
                wb = openpyxl.load_workbook(uploaded, data_only=True)
                ws = wb['설계내역서'] if '설계내역서' in wb.sheetnames else wb.active
                
                # 단가산출근거 시트에서 Q 값 캐싱
                dangagun_cache = {}
                if '단가산출근거' in wb.sheetnames:
                    ws_danga = wb['단가산출근거']
                    current_item = None
                    
                    for row in ws_danga.iter_rows(min_row=1, values_only=True):
                        row_text = " ".join([str(c) for c in row if c])
                        
                        # 항목명 추출 (두 번째 열에서)
                        if row[1] and "/" in str(row[1]):
                            item_text = str(row[1]).strip()
                            # "품명 / 단위" 형태에서 품명 추출
                            if "/" in item_text:
                                current_item = item_text.split("/")[0].strip()
                        
                        # Q 값 추출
                        if current_item and "Q =" in row_text:
                            match = re.search(r'=\s*([\d.]+)\s*([^/\s]+/Hr)', row_text, re.IGNORECASE)
                            if match:
                                hourly_val = float(match.group(1))
                                unit = match.group(2).replace("HR", "Hr")
                                dangagun_cache[current_item] = {"hourly": hourly_val, "unit": unit}
                
                # 캐시를 session_state에 저장
                st.session_state["dangagun_cache"] = dangagun_cache
                
                hierarchy = []
                current_category = None
                seen_items = set()  # 중복 방지
                
                for row in ws.iter_rows(min_row=1, values_only=True):
                    gong_jong = str(row[0]).strip() if row[0] else ""
                    name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                    spec = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                    
                    # 1.1.1, 1.1.2 형태 인식
                    if re.match(r'^\d+\.\d+\.\d+$', gong_jong):
                        if current_category and current_category.get('items'):
                            hierarchy.append(current_category)
                        
                        current_category = {
                            'level': gong_jong,
                            'name': name,
                            'items': []
                        }
                        continue
                    
                    # 세부 항목 추가 (중복 체크)
                    if current_category and not gong_jong and name:
                        item_key = (name, spec)
                        if item_key not in seen_items:
                            for item in matched:
                                if item['name'] == name and item['spec'] == spec:
                                    current_category['items'].append(item)
                                    seen_items.add(item_key)
                                    break
                
                # 마지막 카테고리 추가
                if current_category and current_category.get('items'):
                    hierarchy.append(current_category)
                
                if hierarchy:
                    st.info(f"✅ {len(hierarchy)}개 공종 자동 인식: " + ", ".join([f"{h['level']} {h['name']}" for h in hierarchy[:5]]))
                    
                    # 투입조수 설정
                    st.markdown("### 🔧 공종별 투입조수 설정")
                    
                    if 'crew_by_category' not in st.session_state:
                        st.session_state['crew_by_category'] = {}
                    
                    # 공종명별로 그룹핑 (같은 이름이면 조수 공유)
                    unique_categories = {}
                    for cat in hierarchy:
                        cat_name = cat['name']
                        if cat_name not in unique_categories:
                            unique_categories[cat_name] = []
                        unique_categories[cat_name].append(cat)
                    
                    crew_settings = {}
                    cols = st.columns(min(len(unique_categories), 4))
                    
                    for idx, (cat_name, cat_list) in enumerate(unique_categories.items()):
                        default_crew = st.session_state['crew_by_category'].get(cat_name, 3)
                        
                        with cols[idx % len(cols)]:
                            crew_val = st.number_input(
                                f"{cat_name}(조)",
                                min_value=1,
                                max_value=30,
                                value=default_crew,
                                key=f"crew_cat_{cat_name.replace(' ', '_')}"
                            )
                            crew_settings[cat_name] = crew_val
                            st.session_state['crew_by_category'][cat_name] = crew_val
                    
                    # 작업일수 계산
                    st.markdown("---")
                    st.markdown("### 📊 공종별 작업일수 계산 결과")
                    
                    result_rows = []
                    
                    for cat in hierarchy:
                        cat_name = cat['name']
                        cat_level = cat['level']
                        cat_crew = crew_settings[cat_name]
                        cat_items = cat['items']
                        
                        cat_total_days = 0
                        
                        for item in cat_items:
                            d, label, method = calc_days_priority(
                                item['name'],
                                item.get('spec', ''),
                                item.get('qty', 0),
                                cat_crew
                            )
                            cat_total_days += d
                        
                        result_rows.append({
                            "공종": f"{cat_level} {cat_name}",
                            "물량": f"{len(cat_items)}개 항목",
                            "단위": "-",
                            "1일작업량": "-",
                            "투입조수": f"{cat_crew}조",
                            "작업일수(일)": int(cat_total_days),
                            "계산방식": f"{len(cat_items)}개 항목 합계"
                        })
                    
                    # 결과 테이블
                    result_rows_sorted = sorted(result_rows, key=lambda x: x["작업일수(일)"], reverse=True)
                    max_days = max((r["작업일수(일)"] for r in result_rows_sorted), default=0)
                    total_wd = max_days
                    
                    total_row = {
                        "공종": "[ 합  계 ]",
                        "물량": "-",
                        "단위": "-",
                        "1일작업량": "-",
                        "투입조수": "-",
                        "작업일수(일)": total_wd,
                        "계산방식": "병렬작업 반영"
                    }
                    display_rows = result_rows_sorted + [total_row]
                    
                    def hl_result(row):
                        if row["공종"] == "[ 합  계 ]":
                            return ["background-color:#1a1a3a;color:#7F77DD;font-weight:bold"] * len(row)
                        if row["작업일수(일)"] == max_days and max_days > 0:
                            return ["background-color:#3d0000;color:#ff6b6b"] * len(row)
                        return [""] * len(row)
                    
                    st.dataframe(
                        pd.DataFrame(display_rows).style.apply(hl_result, axis=1),
                        hide_index=True,
                        use_container_width=True
                    )
                    st.caption("🔴 최장 작업일수 = 주공정(크리티컬패스) | 🔵 합계")
                    
                    main_grp = next((r["공종"] for r in result_rows_sorted if r["작업일수(일)"] == max_days), "")
                    ca, cb, cc = st.columns(3)
                    ca.metric("🔴 주공정 (최장)", f"{max_days}일", delta=main_grp)
                    cb.metric("총 순작업일수", f"{total_wd}일")
                    cc.metric("산출 공종", f"{len(result_rows)}개")
                    
                    # 폴더 탐색기 스타일 상세 보기
                    st.markdown("---")
                    st.markdown("### 📂 공종별 세부 항목 (폴더 탐색기 스타일)")
                    
                    for cat in hierarchy:
                        cat_name = cat['name']
                        cat_level = cat['level']
                        cat_crew = crew_settings[cat_name]
                        cat_items = cat['items']
                        
                        cat_total_days = sum(
                            calc_days_priority(item['name'], item.get('spec', ''), item.get('qty', 0), cat_crew)[0]
                            for item in cat_items
                        )
                        
                        with st.expander(
                            f"▶ **{cat_level} {cat_name}** ({cat_total_days}일, {cat_crew}조) [{len(cat_items)}개 항목]",
                            expanded=False
                        ):
                            detail_items = []
                            for item in cat_items:
                                d, label, method = calc_days_priority(
                                    item['name'],
                                    item.get('spec', ''),
                                    item.get('qty', 0),
                                    cat_crew
                                )
                                
                                source = ""
                                if "가이드라인" in method or "부록" in method:
                                    source = "가이드라인"
                                elif "표준품셈" in method or "Man-day" in method:
                                    source = "표준품셈"
                                elif "노무비" in method:
                                    source = "노무비"
                                
                                detail_items.append({
                                    "세부공종": item['name'],
                                    "규격": item.get('spec', ''),
                                    "수량": f"{item.get('qty', 0):,.1f}",
                                    "단위": item.get('unit', ''),
                                    "1일작업량": label,
                                    "작업일수": int(d),
                                    "출처": source
                                })
                            
                            if detail_items:
                                df_items = pd.DataFrame(detail_items)
                                st.dataframe(
                                    df_items,
                                    hide_index=True,
                                    use_container_width=True,
                                    height=min(400, len(detail_items) * 35 + 38)
                                )
                                
                                col_a, col_b, col_c = st.columns(3)
                                with col_a:
                                    st.metric("📦 세부 항목", f"{len(detail_items)}개")
                                with col_b:
                                    st.metric("⏱️ 총 작업일수", f"{sum(int(i['작업일수']) for i in detail_items)}일")
                                with col_c:
                                    st.metric("👷 투입조수", f"{cat_crew}조")
                    
                    # session_state에 저장
                    st.session_state["work_result"] = {
                        "rows": result_rows,
                        "hierarchy": hierarchy,
                        "crew_settings": crew_settings,
                        "matched": matched,
                    }
                    st.session_state["has_excel_data"] = True
                    st.session_state["total_work_days"] = int(total_wd)
                
                else:
                    st.warning("⚠️ 내역서에서 계층 구조(1.1.1, 1.1.2...)를 찾을 수 없습니다.")
                    
        except Exception as e:
            st.error(f"파싱 실패: {e}")
            import traceback
            st.code(traceback.format_exc())
    else:
        st.info("도급(사급) 설계내역서 엑셀을 업로드해주세요.")

# ══════════════════════════════════════════════════════════════
# TAB 1: 공기산정
# ══════════════════════════════════════════════════════════════
with tab1:
    st.subheader("공기산정")
    st.info("TAB 2에서 엑셀을 업로드하면 자동으로 공기가 계산됩니다.")
    
    if "work_result" in st.session_state:
        work_result = st.session_state["work_result"]
        st.success("✅ TAB 2에서 계산된 결과가 있습니다!")
        st.metric("총 순작업일수", f"{st.session_state.get('total_work_days', 0)}일")
    else:
        st.warning("TAB 2에서 엑셀을 먼저 업로드해주세요.")

# ══════════════════════════════════════════════════════════════
# TAB 3: CP 분석
# ══════════════════════════════════════════════════════════════
with tab3:
    st.subheader("주요공종 CP 분석")

    work_result = st.session_state.get("work_result")

    if work_result:
        result_rows = work_result["rows"]
        df_cp = pd.DataFrame(result_rows)
        df_cp = df_cp[df_cp["작업일수(일)"] > 0].copy()
        df_cp = df_cp.sort_values("작업일수(일)", ascending=False).reset_index(drop=True)
        df_cp.index += 1

        max_days = df_cp["작업일수(일)"].max() if len(df_cp) > 0 else 0

        def hl_cp(row):
            if row["작업일수(일)"] == max_days:
                return ["background-color:#3d0000;color:#ff6b6b"] * len(row)
            return [""] * len(row)

        st.markdown("#### 작업일수 기준 CP 순위")
        st.dataframe(
            df_cp[["공종","물량","단위","1일작업량","투입조수","작업일수(일)","계산방식"]].style.apply(hl_cp, axis=1),
            hide_index=False,
            use_container_width=True
        )

        st.markdown("---")
        st.markdown("#### 공종별 작업일수 시각화")
        
        fig_bar = px.bar(
            df_cp, x="작업일수(일)", y="공종",
            orientation="h", text="작업일수(일)",
            color="작업일수(일)",
            color_continuous_scale=["#27AE60","#F39C12","#E74C3C"],
        )
        fig_bar.update_layout(height=350, showlegend=False,
                              yaxis=dict(autorange="reversed"),
                              margin=dict(l=10,r=10,t=20,b=10))
        fig_bar.update_traces(textposition="outside")
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.warning("TAB 2에서 엑셀을 먼저 업로드해주세요.")

# ══════════════════════════════════════════════════════════════
# TAB 4: 비작업일수 계산기
# ══════════════════════════════════════════════════════════════
with tab4:
    st.subheader("비작업일수 계산기")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        start_date = st.date_input("착공일", datetime.now().date())
    
    with col_b:
        work_days = st.number_input("순작업일수", min_value=1, max_value=3650, 
                                     value=st.session_state.get("total_work_days", 100))
    
    if st.button("공기 계산", type="primary"):
        completion = calc_completion_date(start_date, work_days)
        total_days = (completion - start_date).days + 1
        non_work_days = total_days - work_days
        
        st.success(f"✅ 준공일: **{completion.strftime('%Y년 %m월 %d일')}**")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("총 공사기간", f"{total_days}일")
        col2.metric("순작업일수", f"{work_days}일")
        col3.metric("비작업일수", f"{non_work_days}일")

# ══════════════════════════════════════════════════════════════
# TAB 5: 보고서 생성
# ══════════════════════════════════════════════════════════════
with tab5:
    st.subheader("공기산정 보고서")
    
    if "work_result" not in st.session_state:
        st.warning("TAB 2에서 엑셀을 먼저 업로드해주세요.")
    else:
        st.info("📄 보고서 생성 기능은 추후 업데이트 예정입니다.")