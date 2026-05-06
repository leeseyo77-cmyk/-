import streamlit as st
import pandas as pd
import openpyxl
import math
import re
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

# 가이드라인 데이터 및 기상 데이터 import
try:
    from guideline_data import GUIDELINE_APPENDIX_FULL, GUIDELINE_APPENDIX
    from weather_data import HEAT_DAYS, REGIONS, get_heat_days_by_region, get_total_non_work_days
except ImportError:
    # 파일이 없을 경우 기본값 사용
    GUIDELINE_APPENDIX_FULL = {}
    GUIDELINE_APPENDIX = {}
    HEAT_DAYS = {}
    REGIONS = ["서울"]
    def get_heat_days_by_region(region, month=None):
        return 0.0
    def get_total_non_work_days(region, start, end):
        return 0.0

st.set_page_config(page_title="상하수도 공기산정", layout="wide", initial_sidebar_state="expanded")

# ══════════════════════════════════════════════════════════════
# 공종 키워드 매핑
# ══════════════════════════════════════════════════════════════
KEYWORD_MAP_DETAIL = {
    "포장복구": ["포장복구","아스팔트포장","아스팔트+콘크리트포장","콘크리트포장","보도포장","인도포장","보조기층","택코팅","프라임코팅","기층","표층","차선도색"],
    "굴착공": ["터파기","굴착","줄파기","착공","시굴","포장깨기","포장절단"],
    "관부설공": ["관 부설","관부설","PE다중벽관","고강성PVC","주철관","GRP관",
                 "유리섬유복합관","흄관","이중벽관","강관부설","콘크리트관"],
    "되메우기": ["되메우기","뒤채움","복토","성토"],
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
# 가이드라인 부록 데이터 (대폭 확장)
# ══════════════════════════════════════════════════════════════
GUIDELINE_APPENDIX = {
    # 포장공
    "아스팔트포장 절단": {"daily": 1000, "unit": "m"},
    "아스팔트포장깨기 (B.H0.4㎥)": {"daily": 515, "unit": "㎡"},
    "아스팔트포장깨기 (B.H0.7㎥)": {"daily": 1047, "unit": "㎡"},
    "콘크리트포장 절단": {"daily": 500, "unit": "m"},
    "콘크리트포장 깨기": {"daily": 300, "unit": "㎡"},
    
    # 터파기
    "터파기(토사:육상) B/H 0.4㎥": {"daily": 260, "unit": "㎥"},
    "터파기(토사:육상) B/H 0.7㎥": {"daily": 530, "unit": "㎥"},
    "터파기(암:육상) B/H 0.4㎥": {"daily": 130, "unit": "㎥"},
    "터파기(암:육상) B/H 0.7㎥": {"daily": 265, "unit": "㎥"},
    
    # 되메우기
    "되메우기(진동롤러) 2.5ton": {"daily": 600, "unit": "㎥"},
    "되메우기(진동롤러) 4.0ton": {"daily": 950, "unit": "㎥"},
    "되메우기(진동콤팩터)": {"daily": 400, "unit": "㎥"},
    
    # 관부설
    "관부설(D200)": {"daily": 5, "unit": "본/일"},
    "관부설(D300)": {"daily": 4, "unit": "본/일"},
    "관부설(D450)": {"daily": 3, "unit": "본/일"},
    "관부설(D600)": {"daily": 2.5, "unit": "본/일"},
    "관부설(D800)": {"daily": 2, "unit": "본/일"},
    "관부설(D1000)": {"daily": 1.5, "unit": "본/일"},
    "관부설(D1200)": {"daily": 1.2, "unit": "본/일"},
    
    # 맨홀공
    "원형맨홀 Φ1200": {"daily": 2.5, "unit": "개소/일"},
    "원형맨홀 Φ1500": {"daily": 2.5, "unit": "개소/일"},
    "각형맨홀 1800×2400": {"daily": 1.5, "unit": "개소/일"},
    "우수받이": {"daily": 5, "unit": "개소/일"},
    "조립식 PC맨홀": {"daily": 3, "unit": "개소/일"},
    "GRP맨홀": {"daily": 2, "unit": "개소/일"},
    
    # 배수설비
    "빗물받이": {"daily": 5, "unit": "개소/일"},
    "집수받이": {"daily": 4, "unit": "개소/일"},
    "우수토실": {"daily": 3, "unit": "개소/일"},
    "배수설비": {"daily": 4, "unit": "개소/일"},
    
    # 가시설공
    "조립식 간이 흙막이": {"daily": 50, "unit": "㎡/일"},
    "H-PILE 항타": {"daily": 8, "unit": "본/일"},
    
    # 기타
    "보조기층": {"daily": 500, "unit": "㎡/일"},
    "모래기초": {"daily": 400, "unit": "㎥/일"},
}

# ══════════════════════════════════════════════════════════════
# 표준품셈 노무량
# ══════════════════════════════════════════════════════════════
def get_excavation_labor(spec_str):
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

def get_pipe_labor(diameter):
    pipe_labor = {
        200: {"합계": 0.396},
        300: {"합계": 0.494},
        450: {"합계": 0.653},
        600: {"합계": 0.792},
        800: {"합계": 0.990},
        1000: {"합계": 1.188},
        1200: {"합계": 1.386},
    }
    closest = min(pipe_labor.keys(), key=lambda x: abs(x - diameter))
    return pipe_labor.get(closest, {"합계": 0.5})

def is_machine_based(name):
    return any(kw in name for kw in MACHINE_BASED)

def extract_diameter(spec_str):
    patterns = [r'D\s*[=＝]?\s*(\d+)',r'Φ\s*(\d+)',r'φ\s*(\d+)',
                r'(\d{2,4})\s*(?:mm|㎜)',r'[D=]?(\d{2,4})']
    for pat in patterns:
        m = re.search(pat, spec_str)
        if m:
            val = int(m.group(1))
            if 50 <= val <= 3000:
                return val
    return None

def calc_days_priority(name, spec, qty, crews=3):
    """
    우선순위:
    1. 가이드라인 부록
    2. 표준품셈 Man-day
    3. 단가산출근거 Q값
    """
    if not qty or qty <= 0:
        return 0, "-", "-"

    # 1순위: 가이드라인
    try:
        # 정확한 매칭 시도
        full_name = f"{name} {spec}".strip()
        
        # GUIDELINE_APPENDIX_FULL 우선 사용 (확장판)
        guideline_data = GUIDELINE_APPENDIX_FULL if GUIDELINE_APPENDIX_FULL else GUIDELINE_APPENDIX
        
        # 띄어쓰기 제거한 버전도 준비 (매칭 향상)
        full_name_no_space = full_name.replace(" ", "")
        name_no_space = name.replace(" ", "")
        
        for key, val in guideline_data.items():
            matched = False
            key_no_space = key.replace(" ", "")
            
            # 매칭 조건 (우선순위)
            # 1. 정확한 전체 매칭 (띄어쓰기 무시)
            if key_no_space == full_name_no_space or key_no_space == name_no_space:
                matched = True
            
            # 2. 가이드라인 키가 항목명에 포함 (띄어쓰기 무시)
            elif key_no_space in full_name_no_space or key_no_space in name_no_space:
                matched = True
            
            # 3. 항목명이 가이드라인 키에 포함 (띄어쓰기 무시)
            elif name_no_space in key_no_space:
                matched = True
            
            # 4. 원본 문자열 매칭 (띄어쓰기 있는 버전)
            elif key == full_name or key == name or key in full_name or key in name:
                matched = True
            
            if matched:
                base_daily = val.get("daily", 0)
                unit = val.get("unit", "")
                if base_daily > 0:
                    if is_machine_based(name):
                        days = math.ceil(qty / (base_daily * crews))
                        label = f"{base_daily}{unit}×{crews}대"
                    else:
                        days = math.ceil(qty / (base_daily * crews))
                        label = f"{base_daily}{unit}×{crews}조"
                    return days, label, "가이드라인"
        
        # 관부설 직경별 매칭
        if any(kw in name for kw in ["관 부설","관부설","고강성PVC","PE다중벽","이중벽관","주철관","GRP관"]):
            dia = extract_diameter(spec)
            if dia:
                pipe_rates = {200:5, 300:4, 450:3, 600:2.5, 800:2, 1000:1.5, 1200:1.2}
                closest = min(pipe_rates.keys(), key=lambda x: abs(x - dia))
                daily = pipe_rates[closest]
                days = math.ceil(qty / (daily * crews))
                return days, f"{daily}본/일×{crews}조", "가이드라인"
    except Exception:
        pass

    # 2순위: 표준품셈
    try:
        manday = 0
        if any(kw in name for kw in ["터파기","굴착","줄파기"]) and "운반" not in name:
            info = get_excavation_labor(spec)
            rate = info.get("인/m3")
            if rate:
                manday = rate * qty

        pipe_kws = ["관 부설","관부설","이중벽관","주철관","흄관","콘크리트관",
                    "GRP관","유리섬유복합관","파형강관","PE다중벽","고강성PVC","강관부설"]
        if any(kw in name for kw in pipe_kws) and not manday:
            dia = extract_diameter(spec)
            if dia:
                info = get_pipe_labor(dia)
                rate = info.get("합계")
                if rate:
                    manday = rate * qty

        if manday > 0:
            days = math.ceil(manday / (8 * crews))
            return days, f"{round(manday/qty,3)}인/단위×{crews}조", "표준품셈"
    except Exception:
        pass
    
    # 3순위: 단가산출근거
    try:
        if "dangagun_cache" in st.session_state:
            cache = st.session_state["dangagun_cache"]
            
            # 항목명 + 규격으로 매칭 시도
            full_name = f"{name} {spec}".strip()
            
            for cached_name, info in cache.items():
                # 정확한 매칭 우선
                if cached_name == full_name or cached_name in full_name or full_name in cached_name:
                    # hourly 값 (시간당)
                    if "hourly" in info:
                        hourly_val = info.get("hourly", 0)
                        unit = info.get("unit", "")
                        if hourly_val > 0:
                            daily_val = hourly_val * 8
                            days = math.ceil(qty / (daily_val * crews))
                            return days, f"{daily_val:.1f}{unit.replace('/Hr','/일')}×{crews}조", "단가산출근거"
                    
                    # daily 값 (1일 작업량)
                    elif "daily" in info:
                        daily_val = info.get("daily", 0)
                        unit = info.get("unit", "")
                        if daily_val > 0:
                            days = math.ceil(qty / (daily_val * crews))
                            return days, f"{daily_val:.1f}{unit}×{crews}조", "단가산출근거"
                
                # 항목명만으로도 매칭 시도
                if name in cached_name or cached_name in name:
                    if "hourly" in info:
                        hourly_val = info.get("hourly", 0)
                        unit = info.get("unit", "")
                        if hourly_val > 0:
                            daily_val = hourly_val * 8
                            days = math.ceil(qty / (daily_val * crews))
                            return days, f"{daily_val:.1f}{unit.replace('/Hr','/일')}×{crews}조", "단가산출근거"
                    
                    elif "daily" in info:
                        daily_val = info.get("daily", 0)
                        unit = info.get("unit", "")
                        if daily_val > 0:
                            days = math.ceil(qty / (daily_val * crews))
                            return days, f"{daily_val:.1f}{unit}×{crews}조", "단가산출근거"
    except Exception:
        pass

    return 0, "-", "-"

# ══════════════════════════════════════════════════════════════
# 비작업일수
# ══════════════════════════════════════════════════════════════
HOLIDAYS_DB = {
    2025:{1:8,2:4,3:7,4:4,5:6,6:6,7:4,8:6,9:4,10:9,11:5,12:5},
    2026:{1:5,2:7,3:6,4:4,5:7,6:5,7:4,8:7,9:7,10:7,11:5,12:5},
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

# ══════════════════════════════════════════════════════════════
# 엑셀 파서
# ══════════════════════════════════════════════════════════════
def parse_by_keyword(file):
    wb = openpyxl.load_workbook(file, data_only=True)  # read_only=False로 변경
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
    
    # ══════════════════════════════════════════════════════════════
    # 지구 경계 찾기 (로마숫자)
    # ══════════════════════════════════════════════════════════════
    districts = {}
    roman_nums = ['Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ']
    
    all_rows_raw = list(ws.iter_rows(min_row=1, values_only=False))
    
    for row_idx, row in enumerate(all_rows_raw):
        a_val = str(row[0].value or "").strip()
        b_val = str(row[1].value or "").strip() if len(row) > 1 else ""
        
        if a_val in roman_nums:
            districts[a_val] = {
                'name': b_val,
                'start_row': row_idx,
                'end_row': None
            }
    
    # 지구별 end_row 설정
    district_keys = sorted(districts.keys(), key=lambda x: roman_nums.index(x))
    for i, key in enumerate(district_keys):
        if i + 1 < len(district_keys):
            next_key = district_keys[i + 1]
            districts[key]['end_row'] = districts[next_key]['start_row'] - 1
        else:
            districts[key]['end_row'] = len(all_rows_raw) - 1
    
    col_info["districts"] = districts
    
    # ══════════════════════════════════════════════════════════════
    # 지구별 데이터 파싱
    # ══════════════════════════════════════════════════════════════
    results = []
    
    for district, info in districts.items():
        district_rows = all_rows_raw[info['start_row']:info['end_row']+1]
        
        for local_idx, row in enumerate(district_rows):
            row_idx = info['start_row'] + local_idx
            
            # values_only=False이므로 .value 접근
            gong_jong_val = row[0].value
            name_val = row[1].value if len(row) > 1 else None
            spec_val = row[2].value if len(row) > 2 else None
            qty_val = row[3].value if len(row) > 3 else None
            unit_val = row[4].value if len(row) > 4 else None
            
            gong_jong = str(gong_jong_val).strip() if gong_jong_val else ""
            name = str(name_val).strip() if name_val else ""
            spec = str(spec_val).strip() if spec_val else ""
            unit = str(unit_val).strip() if unit_val else ""
            
            if not name or any(skip in name for skip in SKIP_NAMES):
                continue
            
            try:
                qty = float(qty_val) if qty_val else 0
            except:
                qty = 0
            
            if qty <= 0:
                continue
            
            group = "기타"
            for grp, keywords in KEYWORD_MAP_DETAIL.items():
                if any(kw in name for kw in keywords):
                    group = grp
                    break
            
            if group == "관부설공" and any(ex in name for ex in PIPE_EXCLUDE):
                group = "기타"
            
            detail_spec = spec
            if not detail_spec and name:
                spec_match = re.search(r'\([^)]+\)', name)
                if spec_match:
                    detail_spec = spec_match.group(0)
            
            results.append({
                "row_idx": row_idx,
                "district": district,
                "district_name": info['name'],
                "gong_jong": gong_jong,
                "group": group,
                "name": name,
                "spec": detail_spec,
                "qty": qty,
                "unit": unit,
                "amount": row[5].value if len(row) > 5 else 0,
                "labor": row[6].value if len(row) > 6 else 0,
            })
    
    # 원본 순서로 정렬 (row_idx 기준)
    results.sort(key=lambda x: x["row_idx"])
    
    # 중복 제거 (전체 데이터 기준)
    merged = {}
    for r in results:
        key = (r["name"], r["spec"])
        if key not in merged:
            merged[key] = dict(r)
        else:
            merged[key]["qty"] = (merged[key].get("qty") or 0) + (r.get("qty") or 0)
            merged[key]["amount"] = (merged[key].get("amount") or 0) + (r.get("amount") or 0)
            merged[key]["labor"] = (merged[key].get("labor") or 0) + (r.get("labor") or 0)
    
    return list(merged.values()), col_info

# ══════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════
st.sidebar.header("⚙️ 기본 설정")
st.sidebar.markdown("""
<div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            padding: 20px; border-radius: 10px; margin-bottom: 20px;'>
    <h3 style='color: white; margin: 0 0 10px 0; font-size: 18px;'>🚧 공사 유형</h3>
    <p style='color: #e0e7ff; margin: 0; font-size: 14px;'>현재: <strong style='color: #fbbf24;'>하수관로</strong></p>
</div>
""", unsafe_allow_html=True)

st.sidebar.info("📅 **공사 시작일**은 TAB 4에서 설정")
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
# TAB 2
# ══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("📂 엑셀 내역서 자동 인식")
    st.caption("도급 설계내역서 업로드 → 계층 구조 자동 파싱")

    uploaded = st.file_uploader("설계내역서 엑셀 (.xlsx)", type=["xlsx","xls"])

    if uploaded:
        try:
            with st.spinner("파싱 중..."):
                all_rows, col_info = parse_by_keyword(uploaded)

            matched = [r for r in all_rows if r["group"] != "기타"]
            st.success(f"시트 **{col_info['시트명']}** | 인식 **{len(matched)}건**")

            if matched:
                st.markdown("---")
                
                wb = openpyxl.load_workbook(uploaded, data_only=True)
                ws = wb['설계내역서'] if '설계내역서' in wb.sheetnames else wb.active
                
                # 단가산출근거 캐싱 (개선: 다양한 패턴 인식)
                dangagun_cache = {}
                if '단가산출근거' in wb.sheetnames:
                    ws_danga = wb['단가산출근거']
                    current_item = None
                    
                    for row in ws_danga.iter_rows(min_row=1, values_only=True):
                        row_text = " ".join([str(c) for c in row if c])
                        
                        # 항목명 추출 (규격 포함)
                        if row[1] and "/" in str(row[1]):
                            item_text = str(row[1]).strip()
                            if "/" in item_text:
                                current_item = item_text.split("/")[0].strip()
                        
                        # Q 값 추출 (다양한 패턴)
                        if current_item and "Q =" in row_text:
                            # 패턴 1: Q = 숫자 단위/HR
                            match1 = re.search(r'Q\s*=\s*([\d.]+)\s*([^\s]+/HR)', row_text, re.IGNORECASE)
                            if match1:
                                hourly_val = float(match1.group(1))
                                unit = match1.group(2).replace("HR", "Hr").replace("hr", "Hr")
                                dangagun_cache[current_item] = {"hourly": hourly_val, "unit": unit}
                                continue
                            
                            # 패턴 2: Q = 숫자/일 /8 Hr = 숫자 단위/Hr
                            match2 = re.search(r'=\s*([\d.]+)\s*([^\s/]+)/Hr', row_text, re.IGNORECASE)
                            if match2:
                                hourly_val = float(match2.group(1))
                                unit = match2.group(2) + "/Hr"
                                dangagun_cache[current_item] = {"hourly": hourly_val, "unit": unit}
                                continue
                        
                        # 1세트 = N일 패턴
                        if current_item and "세트" in row_text and "일" in row_text:
                            match3 = re.search(r'(\d+)\s*세트\s*=\s*([\d.]+)\s*일', row_text)
                            if match3:
                                sets = float(match3.group(1))
                                days = float(match3.group(2))
                                # 1일 = sets/days 세트
                                daily_val = sets / days
                                dangagun_cache[current_item] = {"daily": daily_val, "unit": "세트/일"}
                                continue
                
                st.session_state["dangagun_cache"] = dangagun_cache
                
                if dangagun_cache:
                    st.info(f"✅ 단가산출근거에서 {len(dangagun_cache)}개 항목 Q값 추출")
                
                # 계층 구조 파싱
                hierarchy = []
                current_category = None
                current_sub_category = None
                seen_items = set()
                
                for row in ws.iter_rows(min_row=1, values_only=True):
                    gong_jong = str(row[0]).strip() if row[0] else ""
                    name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                    spec = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                    
                    if re.match(r'^\d+\.\d+\.\d+$', gong_jong):
                        # 같은 level이라도 name이 다르면 새로운 카테고리
                        if current_category:
                            if current_sub_category:
                                current_category['sub_categories'].append(current_sub_category)
                                current_sub_category = None
                            if current_category.get('items') or current_category.get('sub_categories'):
                                hierarchy.append(current_category)
                        
                        current_category = {
                            'level': gong_jong,
                            'name': name,
                            'items': [],
                            'sub_categories': []
                        }
                        current_sub_category = None
                        continue
                    
                    if re.match(r'^\d+\)$', gong_jong):
                        # 1), 2) 형태는 무조건 sub_category
                        if current_category:
                            if current_sub_category:
                                current_category['sub_categories'].append(current_sub_category)
                            current_sub_category = {
                                'level': gong_jong,
                                'name': name,
                                'items': []
                            }
                        continue
                    
                    if current_category and not gong_jong and name:
                        item_key = (name, spec)
                        if item_key not in seen_items:
                            for item in matched:
                                if item['name'] == name and item['spec'] == spec:
                                    if current_sub_category:
                                        current_sub_category['items'].append(item)
                                    else:
                                        current_category['items'].append(item)
                                    seen_items.add(item_key)
                                    break
                
                if current_category:
                    if current_sub_category:
                        current_category['sub_categories'].append(current_sub_category)
                    if current_category.get('items') or current_category.get('sub_categories'):
                        hierarchy.append(current_category)
                
                if hierarchy:
                    # 중간 번호 기준 그룹핑 (1.1.X, 1.2.X, 2.1.X... 구분)
                    major_groups = {}
                    seen_cats = {}  # 중복 제거용
                    
                    for cat in hierarchy:
                        level = cat['level']
                        name = cat['name']
                        
                        # 중복 체크 (level + name)
                        cat_key = f"{level}_{name}"
                        if cat_key in seen_cats:
                            continue
                        seen_cats[cat_key] = True
                        
                        # 중간 번호 추출 (1.1.X → "1.1")
                        parts = level.split('.')
                        if len(parts) >= 2:
                            major_key = f"{parts[0]}.{parts[1]}"  # "1.1", "1.2", "2.1" 등
                        else:
                            major_key = parts[0]
                        
                        if major_key not in major_groups:
                            major_groups[major_key] = []
                        major_groups[major_key].append(cat)
                    
                    # 각 그룹 내에서 번호 순서 정렬
                    for major_key in major_groups:
                        major_groups[major_key].sort(key=lambda x: tuple(int(p) for p in x['level'].split('.')))
                    
                    st.info(f"✅ {len(major_groups)}개 공종 그룹, {sum(len(v) for v in major_groups.values())}개 주공종 인식")
                    
                    # 그룹명 정의
                    major_names = {
                        "1.1": "🏗️ 하수관로공사",
                        "1.2": "🔧 관로 부대공사",
                        "2.1": "💧 배수설비공사",
                        "2.2": "⚙️ 기계설비",
                        "3.1": "⚡ 전기공사",
                    }
                    
                    # 탭 생성
                    sorted_keys = sorted(major_groups.keys(), key=lambda x: tuple(int(p) for p in x.split('.')))
                    tab_labels = [major_names.get(key, f"📁 {key}") for key in sorted_keys]
                    
                    major_tabs = st.tabs(tab_labels)
                    
                    all_crew_settings = {}
                    
                    for tab_idx, (major_key, major_tab) in enumerate(zip(sorted_keys, major_tabs)):
                        with major_tab:
                            cats_in_major = major_groups[major_key]
                            
                            st.markdown(f"### 🔧 투입조수 설정")
                            
                            if 'crew_by_main' not in st.session_state:
                                st.session_state['crew_by_main'] = {}
                            
                            cols = st.columns(min(len(cats_in_major), 4))
                            
                            for idx, cat in enumerate(cats_in_major):
                                cat_level = cat['level']
                                cat_name = cat['name']
                                cat_full = f"{cat_level} {cat_name}"
                                
                                default_crew = st.session_state['crew_by_main'].get(cat_full, 3)
                                
                                with cols[idx % len(cols)]:
                                    crew_val = st.number_input(
                                        f"{cat_full}(조)",
                                        min_value=1,
                                        max_value=30,
                                        value=default_crew,
                                        key=f"crew_{major_key.replace('.', '_')}_{idx}"
                                    )
                                    all_crew_settings[cat_name] = crew_val
                                    st.session_state['crew_by_main'][cat_full] = crew_val
                    
                    crew_settings = all_crew_settings
                    
                    st.markdown("---")
                    st.markdown("### 📊 공종별 작업일수 계산 결과")
                    
                    result_rows = []
                    
                    for cat in hierarchy:
                        cat_name = cat['name']
                        cat_level = cat['level']
                        cat_crew = crew_settings[cat_name]
                        
                        all_cat_items = list(cat.get('items', []))
                        for sub in cat.get('sub_categories', []):
                            all_cat_items.extend(sub.get('items', []))
                        
                        cat_total_days = sum(
                            calc_days_priority(item['name'], item.get('spec', ''), item.get('qty', 0), cat_crew)[0]
                            for item in all_cat_items
                        )
                        
                        if all_cat_items:
                            result_rows.append({
                                "level": cat_level,
                                "공종": f"{cat_level} {cat_name}",
                                "물량": f"{len(all_cat_items)}개 항목",
                                "투입조수": f"{cat_crew}조",
                                "작업일수(일)": int(cat_total_days),
                                "세부항목": all_cat_items,
                                "하위카테고리": cat.get('sub_categories', []),
                                "crew": cat_crew,
                                "major_key": '.'.join(cat_level.split('.')[:2])  # "1.1", "2.1" 등
                            })
                    
                    # 정렬
                    def sort_key(row):
                        level = row['level']
                        parts = level.split('.')
                        return tuple(int(p) for p in parts)
                    
                    result_rows_sorted = sorted(result_rows, key=sort_key)
                    max_days = max((r["작업일수(일)"] for r in result_rows_sorted), default=0)
                    
                    # 그룹별로 표시
                    grouped_results = {}
                    for row in result_rows_sorted:
                        major_key = row['major_key']
                        if major_key not in grouped_results:
                            grouped_results[major_key] = []
                        grouped_results[major_key].append(row)
                    
                    # 그룹명
                    group_names = {
                        "1.1": "🏗️ 하수관로공사",
                        "1.2": "🔧 관로 부대공사",
                        "2.1": "💧 배수설비공사",
                        "2.2": "⚙️ 기계설비",
                    }
                    
                    # 그룹별 expander
                    for major_key in sorted(grouped_results.keys(), key=lambda x: tuple(int(p) for p in x.split('.'))):
                        group_name = group_names.get(major_key, f"📁 {major_key}")
                        rows_in_group = grouped_results[major_key]
                        
                        with st.expander(f"**{group_name}** ({len(rows_in_group)}개 공종)", expanded=True):
                            for idx, row in enumerate(rows_in_group):
                                is_max = (row["작업일수(일)"] == max_days and max_days > 0)
                                
                                with st.expander(
                                    f"{'🔴' if is_max else '▶'} **{row['공종']}** - {row['작업일수(일)']}일 ({row['투입조수']})",
                                    expanded=False
                                ):
                                    # 하위 카테고리별 표시
                                    if row['하위카테고리']:
                                        for sub in row['하위카테고리']:
                                            sub_name = sub['name']
                                            sub_items = sub['items']
                                            sub_days = sum(
                                                calc_days_priority(item['name'], item.get('spec', ''), item.get('qty', 0), row['crew'])[0]
                                                for item in sub_items
                                            )
                                            
                                            st.markdown(f"#### {sub['level']} {sub_name} ({sub_days}일)")
                                            
                                            detail_items = []
                                            for item in sub_items:
                                                d, label, method = calc_days_priority(
                                                    item['name'],
                                                    item.get('spec', ''),
                                                    item.get('qty', 0),
                                                    row['crew']
                                                )
                                                detail_items.append({
                                                    "세부공종": item['name'],
                                                    "규격": item.get('spec', ''),
                                                    "수량": f"{item.get('qty', 0):,.1f}",
                                                    "단위": item.get('unit', ''),
                                                    "1일작업량": label,
                                                    "작업일수": int(d),
                                                    "출처": method
                                                })
                                            
                                            if detail_items:
                                                st.dataframe(
                                                    pd.DataFrame(detail_items),
                                                    hide_index=True,
                                                    use_container_width=True
                                                )
                                    
                                    # 직접 항목도 있으면 표시
                                    direct_items = [item for item in row['세부항목'] if item not in sum([sub['items'] for sub in row['하위카테고리']], [])]
                                    if direct_items:
                                        detail_items = []
                                        for item in direct_items:
                                            d, label, method = calc_days_priority(
                                                item['name'],
                                                item.get('spec', ''),
                                                item.get('qty', 0),
                                                row['crew']
                                            )
                                            detail_items.append({
                                                "세부공종": item['name'],
                                                "규격": item.get('spec', ''),
                                                "수량": f"{item.get('qty', 0):,.1f}",
                                                "단위": item.get('unit', ''),
                                                "1일작업량": label,
                                                "작업일수": int(d),
                                                "출처": method
                                            })
                                        
                                        if detail_items:
                                            st.dataframe(
                                                pd.DataFrame(detail_items),
                                                hide_index=True,
                                                use_container_width=True
                                            )
                    
                    ca, cb = st.columns(2)
                    ca.metric("🔴 주공정 (최장)", f"{max_days}일")
                    cb.metric("총 공종", f"{len(result_rows_sorted)}개")
                    
                    # session_state 저장
                    st.session_state["work_result"] = {
                        "rows": result_rows_sorted,
                        "hierarchy": hierarchy,
                        "crew_settings": crew_settings,
                    }
                    st.session_state["total_work_days"] = int(max_days)
                
                # ══════════════════════════════════════════════════════════════
                # 지구별 상세 섹션
                # ══════════════════════════════════════════════════════════════
                if col_info.get("districts"):
                    st.markdown("---")
                    st.markdown("## 📍 지구별 상세")
                    
                    # 지구별 데이터 그룹핑
                    district_data = {}
                    district_names = col_info["districts"]
                    
                    for item in matched:
                        district = item.get("district", "전체")
                        if district not in district_data:
                            district_data[district] = []
                        district_data[district].append(item)
                    
                    # 지구 선택
                    selected_district = st.selectbox(
                        "🏗️ 지구 선택",
                        options=list(district_data.keys()),
                        format_func=lambda x: f"{x}. {district_names.get(x, {}).get('name', x)}",
                        key="district_selector"
                    )
                    
                    selected_data = district_data[selected_district]
                    
                    st.markdown(f"### {selected_district}. {district_names.get(selected_district, {}).get('name', selected_district)}")
                    st.caption(f"총 {len(selected_data)}개 항목")
                    
                    # 공종별 그룹핑
                    group_names = {
                        "포장복구": "🛣️ 포장공",
                        "굴착공": "⛏️ 토공",
                        "관부설공": "🔧 관부설공",
                        "되메우기": "📦 되메우기",
                        "맨홀공": "🕳️ 구조물공",
                        "배수설비": "💧 배수설비",
                        "추진공": "🚇 추진공",
                        "기타": "📋 기타"
                    }
                    
                    grouped_by_type = {}
                    for item in selected_data:
                        group = item.get("group", "기타")
                        if group not in grouped_by_type:
                            grouped_by_type[group] = []
                        grouped_by_type[group].append(item)
                    
                    # 공종별 투입조수 설정
                    st.markdown("#### 🔧 투입조수 설정")
                    group_crews = {}
                    
                    cols = st.columns(4)
                    for idx, (group, items) in enumerate(grouped_by_type.items()):
                        with cols[idx % 4]:
                            crew = st.number_input(
                                f"{group_names.get(group, group)}",
                                min_value=1,
                                max_value=30,
                                value=3,
                                key=f"crew_{selected_district}_{group}"
                            )
                            group_crews[group] = crew
                    
                    st.markdown("---")
                    
                    # 공종별 표 표시
                    for group in ["포장복구", "맨홀공", "굴착공", "관부설공", "되메우기", "배수설비", "추진공", "기타"]:
                        if group not in grouped_by_type:
                            continue
                        
                        items = grouped_by_type[group]
                        crew = group_crews[group]
                        
                        with st.expander(f"{group_names.get(group, group)} ({len(items)}개 항목)", expanded=(group in ["포장복구", "맨홀공", "관부설공"])):
                            display_items = []
                            for item in items:
                                days, label, method = calc_days_priority(
                                    item["name"],
                                    item.get("spec", ""),
                                    item.get("qty", 0),
                                    crew
                                )
                                display_items.append({
                                    "공종": item["name"],
                                    "규격": item.get("spec", ""),
                                    "물량": item.get("qty", 0),
                                    "단위": item.get("unit", ""),
                                    "일당": label,
                                    "조수": crew,
                                    "일수": int(days)
                                })
                            
                            if display_items:
                                display_df = pd.DataFrame(display_items)
                                
                                st.dataframe(
                                    display_df,
                                    use_container_width=True,
                                    height=400,
                                    column_config={
                                        "공종": st.column_config.TextColumn("공종", width="large"),
                                        "규격": st.column_config.TextColumn("규격", width="large"),
                                        "물량": st.column_config.NumberColumn("물량", width="medium", format="%.1f"),
                                        "단위": st.column_config.TextColumn("단위", width="small"),
                                        "일당": st.column_config.TextColumn("일당", width="medium"),
                                        "조수": st.column_config.NumberColumn("조수", width="small"),
                                        "일수": st.column_config.NumberColumn("일수", width="small"),
                                    }
                                )
                                
                                total_days = sum(item["일수"] for item in display_items)
                                st.metric(f"{group_names.get(group, group)} 총 작업일수", f"{total_days}일")
                    
        except Exception as e:
            st.error(f"파싱 실패: {e}")
            import traceback
            st.code(traceback.format_exc())
    else:
        st.info("도급 설계내역서 엑셀을 업로드해주세요.")

# ══════════════════════════════════════════════════════════════
# TAB 1
# ══════════════════════════════════════════════════════════════
with tab1:
    st.subheader("📋 공기산정 요약")
    
    st.markdown("### ⚙️ 기본 설정")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        selected_region = st.selectbox(
            "🌍 공사 지역 선택",
            options=REGIONS,
            index=REGIONS.index("서울") if "서울" in REGIONS else 0,
            help="지역별 기상 데이터 (혹서기 비작업일수) 적용"
        )
        st.session_state["selected_region"] = selected_region
    
    with col2:
        st.metric("선택 지역", selected_region)
    
    with col3:
        if selected_region in HEAT_DAYS:
            annual_heat_days = HEAT_DAYS[selected_region].get("연간", 0)
            st.metric("연간 혹서기 일수", f"{annual_heat_days:.1f}일")
    
    st.markdown("---")
    
    if "work_result" in st.session_state:
        st.success("✅ TAB 2에서 계산 완료!")
        
        col_a, col_b, col_c = st.columns(3)
        total_work_days = st.session_state.get('total_work_days', 0)
        
        col_a.metric("💼 총 순작업일수", f"{total_work_days}일")
        col_b.metric("🌍 적용 지역", selected_region)
        
        # 작업 기간 동안 혹서기 일수 예상 (7-8월 기준)
        estimated_heat = get_total_non_work_days(selected_region, 7, 8)
        col_c.metric("🔥 여름철 혹서기", f"{estimated_heat:.1f}일")
        
        # 연간 혹서기 일수 가져오기
        annual_heat_days = HEAT_DAYS.get(selected_region, {}).get("연간", 0)
        
        st.info(f"""
        **📍 {selected_region} 지역 기상 정보**
        - 연간 혹서기 비작업일수: {annual_heat_days:.1f}일
        - 7-8월 혹서기: {estimated_heat:.1f}일
        - TAB 4에서 상세 공기 계산 가능
        """)
    else:
        st.warning("TAB 2에서 엑셀을 먼저 업로드해주세요.")

# ══════════════════════════════════════════════════════════════
# TAB 3
# ══════════════════════════════════════════════════════════════
with tab3:
    st.subheader("주요공종 CP 분석")
    work_result = st.session_state.get("work_result")
    if work_result:
        result_rows = work_result["rows"]
        
        display_data = []
        for r in result_rows:
            display_data.append({
                "공종": r["공종"],
                "물량": r["물량"],
                "투입조수": r["투입조수"],
                "작업일수(일)": r["작업일수(일)"]
            })
        
        df_cp = pd.DataFrame(display_data)
        df_cp = df_cp[df_cp["작업일수(일)"] > 0].copy()
        max_days = df_cp["작업일수(일)"].max() if len(df_cp) > 0 else 0

        def hl_cp(row):
            if row["작업일수(일)"] == max_days:
                return ["background-color:#3d0000;color:#ff6b6b"] * len(row)
            return [""] * len(row)

        st.dataframe(df_cp.style.apply(hl_cp, axis=1), hide_index=True, use_container_width=True)
        
        fig_bar = px.bar(df_cp, x="작업일수(일)", y="공종", orientation="h", text="작업일수(일)",
                         color="작업일수(일)", color_continuous_scale=["#27AE60","#F39C12","#E74C3C"])
        fig_bar.update_layout(height=350, showlegend=False, yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.warning("TAB 2에서 엑셀을 먼저 업로드해주세요.")

# ══════════════════════════════════════════════════════════════
# TAB 4
# ══════════════════════════════════════════════════════════════
with tab4:
    st.subheader("비작업일수 계산기")
    
    st.markdown("### ⚙️ 비작업일 조건 설정")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        include_rain = st.checkbox("🌧️ 강우일 포함", value=True)
    with col2:
        include_cold = st.checkbox("❄️ 한파일 포함 (영하 5도 이하)", value=False)
    with col3:
        include_dust = st.checkbox("😷 미세먼지 포함", value=False)
    
    st.markdown("---")
    
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
        
        st.info(f"""
        **적용된 조건:**
        - {'✅' if include_rain else '❌'} 강우일
        - {'✅' if include_cold else '❌'} 한파일 (영하 5도 이하)
        - {'✅' if include_dust else '❌'} 미세먼지
        """)

# ══════════════════════════════════════════════════════════════
# TAB 5
# ══════════════════════════════════════════════════════════════
with tab5:
    st.subheader("공기산정 보고서")
    if "work_result" not in st.session_state:
        st.warning("TAB 2에서 엑셀을 먼저 업로드해주세요.")
    else:
        st.info("📄 보고서 생성 기능은 추후 업데이트 예정입니다.")