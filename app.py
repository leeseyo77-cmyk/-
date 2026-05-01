import streamlit as st
import pandas as pd
import math
import re
import holidays
import openpyxl
from datetime import date, timedelta
import plotly.express as px
import plotly.graph_objects as go
from labor_rates_2025 import get_excavation_labor_detail, get_pipe_labor
from daily_work_rates import calc_work_days

st.set_page_config(page_title="상하수도 공기산정", layout="wide")

# ── 로그인 ────────────────────────────────────────────────────
def check_password():
    if st.session_state.get("authenticated"):
        return True
    st.title("상하수도 관로공사 공기산정 시스템")
    st.markdown("---")
    st.subheader("로그인")
    pw = st.text_input("비밀번호를 입력하세요", type="password")
    if st.button("로그인"):
        if pw == "1234":
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    return False

if not check_password():
    st.stop()

# ══════════════════════════════════════════════════════════════
# [추가] 탭 간 상태 동기화용 초기값 세팅
# ══════════════════════════════════════════════════════════════
if "sync_proj" not in st.session_state:
    st.session_state.update({
        "sync_proj": "하수도공사", 
        "sync_city": "서울",
        "sync_prep": 60, 
        "sync_clean": 30,
        "sync_year": 2025, 
        "sync_month": 1,
        "sync_months": 6
    })

# ══════════════════════════════════════════════════════════════
# 공통 데이터
# ══════════════════════════════════════════════════════════════

KEYWORD_MAP_DETAIL = {
    "굴착공":   ["터파기","굴착","줄파기"],
    "토사운반": ["사토","운반-토사","잔토처리","소운반"],
    "관부설공": ["관 부설","관부설","PE다중벽관","고강성PVC","주철관","GRP관",
                 "유리섬유복합관","흄관","이중벽관","강관부설","콘크리트관"],
    "되메우기": ["되메우기","모래기초","모래,관기초"],
    "포장복구": ["아스팔트포장","아스콘포장","보조기층","콘크리트포장","포장복구"],
    "포장철거": ["포장 절단","포장절단","아스팔트포장 절단","포장 깨기","포장깨기"],
    "맨홀공":   ["맨홀","소형맨홀","PC맨홀","GRP맨홀"],
    "배수설비": ["배수설비","오수받이","우수받이","연결관"],
    "추진공":   ["추진공","관 추진","추진설비","갱구공","추진마감"],
    "시공검사": ["수압시험","CCTV","수밀시험"],
    "가시설공": ["가시설","안전난간","흙막이"],
    "교통관리": ["교통정리","신호수"],
    "지장물":   ["지장물보호"],
    "준비공":   ["규준틀","준비","측량"],
}

def map_group_detail(name):
    for group, keywords in KEYWORD_MAP_DETAIL.items():
        if any(kw in name for kw in keywords):
            return group
    return "기타"

# 장비기반 공종 (조수 = 장비 대수)
MACHINE_BASED = ["터파기","굴착","되메우기","모래기초","모래부설","모래,관기초"]

def is_machine_based(name):
    return any(kw in name for kw in MACHINE_BASED)

# ── 작업일수 계산 (3단계 우선순위) ───────────────────────────
def calc_days_priority(name, spec, qty, crews):
    """
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
            unit       = wd.get("unit", "")
            if base_daily > 0:
                if is_machine_based(name):
                    days = math.ceil(qty / (base_daily * crews))
                    label = f"{base_daily}{unit}/일×{crews}대"
                else:
                    days = math.ceil(qty / (base_daily * crews))
                    label = f"{base_daily}{unit}/일×{crews}조"
                return days, label, "가이드라인"
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
            return days, f"{round(manday/qty,3)}인/단위×{crews}조", "표준품셈"
    except Exception:
        pass

    return 0, "-", "-"

def extract_diameter(spec_str):
    patterns = [r'D\s*[=＝]?\s*(\d+)',r'Φ\s*(\d+)',r'φ\s*(\d+)',
                r'(\d{2,4})\s*(?:mm|㎜)',r'(\d{2,4})']
    for pat in patterns:
        m = re.search(pat, spec_str)
        if m:
            val = int(m.group(1))
            if 50 <= val <= 3000:
                return val
    return None

# ── 비작업일수 데이터 ─────────────────────────────────────────
HOLIDAYS_DB = {
    2025:{1:8,2:4,3:7,4:4,5:6,6:6,7:4,8:6,9:4,10:9,11:5,12:5},
    2026:{1:5,2:7,3:6,4:4,5:7,6:5,7:4,8:7,9:7,10:7,11:5,12:5},
    2027:{1:6,2:7,3:5,4:4,5:7,6:4,7:4,8:6,9:7,10:8,11:4,12:6},
    2028:{1:9,2:4,3:5,4:5,5:6,6:5,7:5,8:5,9:4,10:10,11:4,12:6},
    2029:{1:5,2:7,3:5,4:5,5:7,6:5,7:5,8:5,9:8,10:6,11:4,12:6},
    2030:{1:5,2:7,3:6,4:4,5:6,6:6,7:4,8:5,9:8,10:6,11:4,12:6},
    2031:{1:8,2:4,3:7,4:4,5:6,6:6,7:4,8:6,9:5,10:8,11:5,12:5},
    2032:{1:5,2:8,3:5,4:4,5:7,6:4,7:4,8:6,9:7,10:8,11:4,12:6},
    2033:{1:7,2:6,3:5,4:4,5:7,6:5,7:5,8:5,9:7,10:7,11:4,12:5},
}
WEATHER_DB = {
    "rain5":{
        "서울":[0.5,1.1,1.7,3.7,4.4,5.2,7.2,8.4,3.6,3.0,3.3,1.4],
        "부산":[1.0,1.4,2.7,4.0,4.4,6.2,7.8,8.5,5.8,3.2,3.5,1.6],
        "대구":[0.3,0.8,1.7,3.0,3.9,5.0,7.2,7.6,3.9,2.0,2.3,0.7],
        "인천":[0.6,1.1,1.8,3.5,4.2,5.0,7.6,8.1,3.9,3.1,3.4,1.5],
        "광주":[1.0,1.7,3.0,4.5,5.1,6.8,8.7,8.4,5.5,3.4,4.0,1.7],
        "대전":[0.5,1.1,2.0,3.8,4.5,5.6,7.9,8.3,4.2,2.7,3.3,1.2],
        "울산":[1.0,1.4,2.5,4.0,4.6,6.1,7.2,8.2,5.4,3.0,3.3,1.6],
        "세종":[0.5,1.0,1.9,3.7,4.4,5.5,7.8,8.2,4.1,2.6,3.2,1.2],
        "수원":[0.5,1.1,1.8,3.6,4.3,5.2,7.4,8.2,3.7,3.0,3.3,1.4],
        "전주":[0.8,1.4,2.5,4.1,4.8,6.3,8.5,8.3,4.8,3.0,3.7,1.4],
        "청주":[0.5,1.0,1.9,3.6,4.3,5.5,7.9,8.3,4.0,2.5,3.2,1.1],
        "춘천":[0.5,1.0,1.9,3.6,4.5,5.7,7.5,8.4,4.0,2.8,3.1,1.2],
        "원주":[0.5,1.0,1.9,3.5,4.5,5.6,7.4,8.2,4.0,2.8,3.0,1.2],
        "강릉":[1.3,1.4,2.5,4.0,4.9,5.5,5.5,8.0,5.5,3.9,4.4,2.1],
        "제주":[3.0,3.2,5.1,6.7,7.0,8.2,9.0,9.6,7.9,6.0,6.1,3.8],
        "포항":[0.8,1.2,2.3,3.6,4.4,5.6,6.5,7.4,5.2,2.8,3.2,1.3],
        "안동":[0.3,0.8,1.6,3.0,3.8,5.0,7.0,7.4,3.9,2.0,2.4,0.8],
        "목포":[1.4,2.0,3.5,5.2,5.8,7.4,8.2,7.7,5.4,3.5,4.1,2.0],
        "여수":[1.4,1.9,3.5,5.3,5.8,7.8,8.6,8.1,5.9,3.5,4.0,2.0],
        "순천":[1.0,1.6,3.0,4.7,5.2,7.0,8.4,8.0,5.4,3.2,3.7,1.7],
        "군산":[0.9,1.4,2.5,4.2,4.8,6.5,8.3,8.0,5.0,3.2,3.6,1.5],
        "진주":[0.8,1.3,2.5,4.0,4.6,6.5,7.8,7.9,5.0,2.8,3.2,1.3],
        "창원":[1.0,1.5,2.7,4.2,4.8,6.5,7.5,7.9,5.4,3.0,3.4,1.5],
        "순창군":[1.7,1.9,3.7,4.7,4.0,6.1,9.4,8.2,5.2,3.1,3.3,2.5],
    },
    "cold":{
        "서울":[6.9,3.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.2,7.0],
        "부산":[0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1],
        "대구":[1.2,0.3,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.3],
        "인천":[5.7,2.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1,5.9],
        "광주":[0.8,0.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.8],
        "대전":[3.1,1.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,3.3],
        "울산":[0.3,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.4],
        "세종":[4.0,1.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1,4.2],
        "수원":[6.4,2.8,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1,6.6],
        "전주":[1.7,0.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.8],
        "청주":[3.5,1.3,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,3.7],
        "춘천":[11.5,6.1,0.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.6,11.8],
        "원주":[9.0,4.5,0.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.3,9.3],
        "강릉":[1.7,0.8,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.2],
        "제주":[0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0],
        "포항":[0.3,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.4],
        "안동":[5.2,2.2,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.2,5.5],
        "목포":[0.3,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.3],
        "여수":[0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1],
        "순천":[0.5,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.5],
        "군산":[2.2,0.7,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,2.3],
        "진주":[0.5,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.6],
        "창원":[0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.2],
        "순창군":[3.7,2.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,2.3],
    },
    "heat":{
        "서울":[0.0,0.0,0.0,0.0,0.0,0.0,1.9,2.4,0.0,0.0,0.0,0.0],
        "부산":[0.0,0.0,0.0,0.0,0.0,0.0,0.2,1.4,0.0,0.0,0.0,0.0],
        "대구":[0.0,0.0,0.0,0.0,0.0,0.1,2.8,5.4,0.0,0.0,0.0,0.0],
        "인천":[0.0,0.0,0.0,0.0,0.0,0.0,0.2,2.1,0.0,0.0,0.0,0.0],
        "광주":[0.0,0.0,0.0,0.0,0.0,0.0,4.0,6.5,0.0,0.0,0.0,0.0],
        "대전":[0.0,0.0,0.0,0.0,0.0,0.0,3.6,6.0,0.0,0.0,0.0,0.0],
        "울산":[0.0,0.0,0.0,0.0,0.0,0.0,1.9,2.7,0.0,0.0,0.0,0.0],
        "세종":[0.0,0.0,0.0,0.0,0.0,0.0,0.0,2.0,0.0,0.0,0.0,0.0],
        "수원":[0.0,0.0,0.0,0.0,0.0,0.0,2.7,4.4,0.0,0.0,0.0,0.0],
        "전주":[0.0,0.0,0.0,0.0,0.0,0.0,2.8,5.3,0.0,0.0,0.0,0.0],
        "청주":[0.0,0.0,0.0,0.0,0.0,0.0,1.1,3.1,0.0,0.0,0.0,0.0],
        "춘천":[0.0,0.0,0.0,0.0,0.0,0.0,2.4,2.4,0.0,0.0,0.0,0.0],
        "원주":[0.0,0.0,0.0,0.0,0.0,0.0,0.8,0.7,0.0,0.0,0.0,0.0],
        "강릉":[0.0,0.0,0.0,0.0,0.0,0.0,1.8,2.8,0.0,0.0,0.0,0.0],
        "제주":[0.0,0.0,0.0,0.0,0.0,0.0,2.2,3.0,0.0,0.0,0.0,0.0],
        "포항":[0.0,0.0,0.0,0.0,0.0,0.1,3.7,4.3,0.0,0.0,0.0,0.0],
        "안동":[0.0,0.0,0.0,0.0,0.0,0.0,1.2,3.4,0.0,0.0,0.0,0.0],
        "목포":[0.0,0.0,0.0,0.0,0.0,0.0,1.0,3.0,0.0,0.0,0.0,0.0],
        "여수":[0.0,0.0,0.0,0.0,0.0,0.0,0.2,0.4,0.0,0.0,0.0,0.0],
        "순천":[0.0,0.0,0.0,0.0,0.0,0.0,1.3,2.6,0.0,0.0,0.0,0.0],
        "군산":[0.0,0.0,0.0,0.0,0.0,0.0,1.7,4.0,0.0,0.0,0.0,0.0],
        "진주":[0.0,0.0,0.0,0.0,0.0,0.0,0.9,4.0,0.0,0.0,0.0,0.0],
        "창원":[0.0,0.0,0.0,0.0,0.0,0.0,4.3,5.4,0.0,0.0,0.0,0.0],
        "순창군":[0.0,0.0,0.0,0.0,0.0,0.1,8.4,11.2,0.3,0.0,0.0,0.0],
    },
    "wind":{
        "서울":[1.3,1.5,2.2,1.5,1.2,0.5,0.6,0.8,0.7,0.8,1.0,1.3],
        "부산":[2.2,2.2,3.1,2.4,1.8,1.0,1.4,1.6,1.9,1.8,2.1,2.3],
        "대구":[0.4,0.5,0.8,0.5,0.3,0.1,0.1,0.2,0.2,0.2,0.3,0.4],
        "인천":[2.1,2.3,2.9,2.1,1.5,0.7,0.8,1.0,1.1,1.2,1.7,2.1],
        "광주":[0.7,0.9,1.4,0.9,0.6,0.3,0.4,0.5,0.4,0.5,0.6,0.7],
        "대전":[0.5,0.7,1.1,0.8,0.5,0.2,0.2,0.3,0.3,0.3,0.4,0.5],
        "울산":[1.4,1.6,2.4,1.8,1.3,0.7,0.9,1.1,1.2,1.2,1.4,1.5],
        "세종":[0.5,0.7,1.0,0.7,0.5,0.2,0.2,0.3,0.3,0.3,0.4,0.5],
        "수원":[1.0,1.2,1.8,1.3,0.9,0.4,0.5,0.6,0.6,0.7,0.9,1.0],
        "전주":[0.7,0.9,1.5,1.0,0.7,0.3,0.4,0.5,0.4,0.5,0.6,0.7],
        "청주":[0.5,0.7,1.1,0.8,0.5,0.2,0.3,0.3,0.3,0.3,0.4,0.5],
        "춘천":[0.9,1.1,1.7,1.2,0.9,0.4,0.5,0.6,0.6,0.6,0.8,0.9],
        "원주":[0.7,0.9,1.4,1.0,0.7,0.3,0.4,0.5,0.5,0.5,0.6,0.7],
        "강릉":[2.5,2.7,3.6,2.8,2.1,1.1,1.3,1.5,1.8,2.0,2.4,2.6],
        "제주":[5.5,5.8,7.2,6.0,4.5,2.8,3.5,3.9,4.6,4.8,5.6,5.7],
        "포항":[1.5,1.7,2.6,2.0,1.5,0.8,1.0,1.2,1.3,1.3,1.5,1.6],
        "안동":[0.5,0.7,1.2,0.8,0.5,0.2,0.3,0.3,0.3,0.3,0.4,0.5],
        "목포":[3.0,3.3,4.5,3.5,2.6,1.4,1.7,1.9,2.3,2.5,3.0,3.1],
        "여수":[1.8,2.0,3.0,2.3,1.7,0.9,1.1,1.3,1.4,1.5,1.8,1.9],
        "순천":[0.6,0.8,1.3,0.9,0.6,0.3,0.4,0.5,0.4,0.5,0.6,0.6],
        "군산":[2.0,2.2,3.2,2.4,1.7,0.8,1.0,1.2,1.3,1.4,1.8,2.0],
        "진주":[0.6,0.8,1.3,0.9,0.6,0.3,0.4,0.5,0.5,0.5,0.6,0.6],
        "창원":[1.2,1.4,2.1,1.6,1.1,0.6,0.8,0.9,1.0,1.0,1.2,1.3],
        "순창군":[1.0,1.5,3.1,2.0,2.2,0.4,0.5,0.8,0.8,0.8,1.0,1.4],
    },
}
CITY_LIST = sorted(WEATHER_DB["rain5"].keys())
PREP_PERIOD = {
    "하수도공사":60,"상수도공사":60,"포장공사(신설)":50,
    "포장공사(수선)":60,"하천공사":40,"항만공사":40,
    "공동주택":45,"고속도로공사":180,"철도공사":90,
    "강교가설공사":90,"PC교량공사":70,"교량보수공사":60,"공동구공사":80,
}

# ── 공통 함수 ─────────────────────────────────────────────────
def get_work_end_date(start, work_days):
    kr_holidays = holidays.KR()
    RAIN = {1:2,2:2,3:3,4:4,5:5,6:7,7:11,8:10,9:6,10:3,11:3,12:2}
    current, worked = start, 0
    while worked < work_days:
        if current.weekday()==6 or current in kr_holidays or current.day%30<RAIN[current.month]:
            current += timedelta(days=1)
            continue
        worked += 1
        current += timedelta(days=1)
    return current - timedelta(days=1)

def fmt_ok(val):
    return f"{val/1e8:.1f}억"

# ── 엑셀 파서 ─────────────────────────────────────────────────
SKIP_NAMES = [
    "남천지구","동부지구","신설오수관로","간선관로","지선관로",
    "순공사비","배수설비공사","토공","관로공","구조물공","포장공",
    "추진공","부대공","안전관리비","환경보전비","소계","합계","계",
]

# 관부설 제외 항목 (절단, 이형관, 하차비는 작업일수 계산 제외)
PIPE_EXCLUDE = ["절단","이형관","하차비","단관","마감캡","추진관"]

def parse_by_keyword(file):
    """
    엑셀 내역서 파싱 (계층 구조 포함)
    반환: (results, hierarchy)
      results: 기존 형태 리스트
      hierarchy: 계층 구조 딕셔너리
    """
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    skip_sheets = ["목차","안내","INITIAL","초기","index"]
    priority    = ["설계내역서","내역서","공사비내역서"]
    target_sheet = None
    for p in priority:
        if p in wb.sheetnames:
            target_sheet = p; break
    if not target_sheet:
        for sname in wb.sheetnames:
            if any(sk in sname for sk in skip_sheets): continue
            if "내역" in sname: target_sheet = sname; break
    if not target_sheet:
        for sname in wb.sheetnames:
            if not any(sk in sname for sk in skip_sheets):
                target_sheet = sname; break
    if not target_sheet:
        target_sheet = wb.sheetnames[0]

    ws = wb[target_sheet]
    all_rows = list(ws.iter_rows(values_only=True))
    header_row_idx=None; name_col=1; qty_col=3; unit_col=4; amount_col=6; labor_col=8

    for i, row in enumerate(all_rows[:10]):
        row_strs = [str(c).strip() if c else "" for c in row]
        for j, cell in enumerate(row_strs):
            if cell in ["명      칭","명칭","공종명","품명","작업명"]:
                header_row_idx=i; name_col=j
            if cell in ["수   량","수량","물량"] and header_row_idx==i: qty_col=j
            if cell in ["단위","규격단위"] and header_row_idx==i: unit_col=j
        if header_row_idx is not None: break

    if header_row_idx is not None and header_row_idx+1 < len(all_rows):
        sub = [str(c).strip() if c else "" for c in all_rows[header_row_idx+1]]
        amt_cols = [j for j,c in enumerate(sub) if c in ["금    액","금액"]]
        if len(amt_cols)>=1: amount_col=amt_cols[0]
        if len(amt_cols)>=2: labor_col=amt_cols[1]

    data_start = (header_row_idx+2) if header_row_idx is not None else 4
    col_info = {
        "시트명":target_sheet,"헤더행":header_row_idx,
        "명칭컬럼":name_col,"수량컬럼":qty_col,"단위컬럼":unit_col,
        "금액컬럼":amount_col,"노무비컬럼":labor_col,"데이터시작":data_start,
    }

    results = []
    for row in all_rows[data_start:]:
        if not row or len(row)<=name_col: continue
        name = str(row[name_col]).strip() if row[name_col] else ""
        if not name or name=="None": continue
        code = str(row[0]).strip() if row[0] else ""
        if re.match(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]', code): continue
        if re.match(r'^\d+(\.\d+)*\.?\s*$', code): continue
        if re.match(r'^\s*\(\d+\)', code): continue
        if any(sk in name for sk in SKIP_NAMES): continue
        unit = str(row[unit_col]).strip() if unit_col<len(row) and row[unit_col] else ""
        if unit in ["식","1식","LS","ls","LOT","lot"]: continue
        try:    qty = float(row[qty_col]) if qty_col<len(row) and isinstance(row[qty_col],(int,float)) else None
        except: qty = None
        try:    amount = float(row[amount_col]) if amount_col<len(row) and isinstance(row[amount_col],(int,float)) else None
        except: amount = None
        try:    labor = float(row[labor_col]) if labor_col<len(row) and isinstance(row[labor_col],(int,float)) else None
        except: labor = None
        if (labor is None or labor==0) and amount is not None and amount>0: continue
        spec  = str(row[2]).strip() if len(row)>2 and row[2] else ""
        group = map_group_detail(name)

        # 관부설공 중 절단·이형관·하차비는 작업일수 계산 불필요 → 기타로 분류
        if group == "관부설공" and any(ex in name for ex in ["절단","이형관","하차비","단관","마감캡"]):
            group = "기타"

        # 규격 상세 정보 추출 (장비, 관경 등)
        detail_spec = spec
        if not detail_spec and name:
            # 이름에서 규격 추출 시도
            spec_match = re.search(r'\([^)]+\)', name)
            if spec_match:
                detail_spec = spec_match.group(0)

        results.append({
            "group":group,"name":name,"spec":detail_spec,
            "qty":qty,"unit":unit,"amount":amount,"labor":labor,
            "is_night":"-야간" in name,
        })

    wb.close()

    # 같은 공종명 합산
    merged = {}
    for r in results:
        key = (r["group"], r["name"].split("(")[0].strip())
        if key not in merged:
            merged[key] = dict(r)
            merged[key]["name"] = r["name"].split("(")[0].strip()
        else:
            merged[key]["qty"]    = (merged[key].get("qty")    or 0)+(r.get("qty")    or 0)
            merged[key]["amount"] = (merged[key].get("amount") or 0)+(r.get("amount") or 0)
            merged[key]["labor"]  = (merged[key].get("labor")  or 0)+(r.get("labor")  or 0)

    return list(merged.values()), col_info

# ══════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════
st.sidebar.header("⚙️ 기본 설정")

# 공사 유형 선택 배너
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

# 공사 유형 선택 (향후 확장용)
project_type = st.sidebar.selectbox(
    "공사 유형",
    ["하수관로", "하수처리시설 (준비중)", "하수관로+하수처리시설 (준비중)"],
    disabled=False,
    help="현재는 하수관로만 지원합니다. 다른 유형은 개발 중입니다."
)

# 안내 메시지 (착공일은 TAB 4에서 설정)
st.sidebar.info("📅 **공사 시작일**은\n\nTAB 4(비작업일수)에서 설정합니다.")

st.sidebar.markdown("---")

# 사용 가이드
st.sidebar.markdown("### 💡 사용 가이드")
st.sidebar.markdown("""
1️⃣ **TAB 1**: 공기산정 간편입력

2️⃣ **TAB 2**: 엑셀 내역서 인식 & 부록1

3️⃣ **TAB 3**: CP 분석

4️⃣ **TAB 4**: 비작업일수 & 총 공기
""")

st.sidebar.markdown("---")
st.sidebar.caption("💼 상하수도 관로공사 전문 공기산정 시스템 v2.0")

# start_date는 TAB 4에서 설정하므로 여기서는 제거
# (TAB 4의 착공일 입력을 활용)
start_date = date.today()  # 기본값만 설정

st.title("상하수도 관로공사 공기산정 시스템")
st.markdown("---")

tab1,tab2,tab3,tab4,tab5 = st.tabs([
    "📋 공기산정",
    "📂 엑셀 내역서 인식",
    "🔍 주요공종 CP 분석",
    "🌧 비작업일수 계산기",
    "📄 공기산정 보고서"
])

# ══════════════════════════════════════════════════════════════
# TAB 2: 엑셀 내역서 인식 (먼저 정의 - TAB1이 결과 사용)
# ══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("📂 엑셀 내역서 자동 인식 (내역서 기반)")
    st.caption("도급 설계내역서 업로드 → 계층 구조 자동 파싱 → 공종별 투입조수 조정")

    uploaded = st.file_uploader("설계내역서 엑셀 (.xlsx)", type=["xlsx","xls"])

    if uploaded:
        try:
            with st.spinner("파싱 중..."):
                all_rows, col_info = parse_by_keyword(uploaded)

            matched   = [r for r in all_rows if r["group"]!="기타" and r["qty"] is not None]
            unmatched = [r for r in all_rows if r["group"]=="기타"  and r["qty"] is not None]

            st.success(f"시트 **{col_info['시트명']}** | 인식 **{len(matched)}건** | 미인식 **{len(unmatched)}건**")

            if matched:
                st.markdown("---")
                st.subheader("📂 내역서 기반 공종 분류")
                
                import re
                import openpyxl
                
                # 원본 엑셀에서 계층 구조 파싱
                hierarchy = []
                current_category = None
                
                wb = openpyxl.load_workbook(uploaded, data_only=True)
                ws = wb['설계내역서'] if '설계내역서' in wb.sheetnames else wb.active
                
                for row in ws.iter_rows(min_row=1, values_only=True):
                    gong_jong = str(row[0]).strip() if row[0] else ""
                    name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                    
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
                    
                    # 세부 항목 추가
                    if current_category and not gong_jong and name:
                        for item in matched:
                            if item['name'] == name:
                                current_category['items'].append(item)
                                break
                
                # 마지막 카테고리 추가
                if current_category and current_category.get('items'):
                    hierarchy.append(current_category)
                
                if hierarchy:
                    st.info(f"✅ {len(hierarchy)}개 공종 자동 인식: " + ", ".join([f"{h['level']} {h['name']}" for h in hierarchy]))
                    
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
                            "투입조수(조)": cat_crew,
                            "작업일수(일)": int(cat_total_days),
                            "계산방식": f"{len(cat_items)}개 항목 합계"
                        })
                    
                    result_rows_sorted = sorted(result_rows, key=lambda x: x["작업일수(일)"], reverse=True)
                    max_days = max((r["작업일수(일)"] for r in result_rows_sorted), default=0)
                    total_wd = max_days
                    
                    total_row = {
                        "공종": "[ 합  계 ]",
                        "물량": "-",
                        "단위": "-",
                        "1일작업량": "-",
                        "투입조수(조)": "-",
                        "작업일수(일)": total_wd,
                        "계산방식": "병렬작업 반영"
                    }
                    display_rows = result_rows_sorted + [total_row]
                    
                    def hl_result(row):
                        if row["공종"] == "[ 합  계 ]":
                            return ["background-color:#1a1a3a;color:#7F77DD;font-weight:bold"]*len(row)
                        if row["작업일수(일)"] == max_days and max_days > 0:
                            return ["background-color:#3d0000;color:#ff6b6b"]*len(row)
                        return [""]*len(row)
                    
                    st.dataframe(
                        pd.DataFrame(display_rows).style.apply(hl_result, axis=1),
                        hide_index=True,
                        use_container_width=True
                    )
                    st.caption("🔴 최장 작업일수 = 주공정(크리티컬패스) | 🔵 합계")
                    
                    main_grp = next((r["공종"] for r in result_rows_sorted if r["작업일수(일)"]==max_days), "")
                    ca, cb, cc = st.columns(3)
                    ca.metric("🔴 주공정 (최장)", f"{max_days}일", delta=main_grp)
                    cb.metric("총 순작업일수", f"{total_wd}일")
                    cc.metric("산출 공종", f"{len(result_rows)}개")
                    
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
            st.error(f"미리보기 실패: {e}")
    else:
        st.info("도급(사급) 설계내역서 엑셀을 업로드해주세요.")

with tab3:
    st.subheader("주요공종 CP 분석")

    work_result = st.session_state.get("work_result")

    if work_result:
        result_rows = work_result["rows"]
        df_cp = pd.DataFrame(result_rows)
        df_cp = df_cp[df_cp["작업일수(일)"]>0].copy()
        df_cp = df_cp.sort_values("작업일수(일)", ascending=False).reset_index(drop=True)
        df_cp.index += 1

        max_days = df_cp["작업일수(일)"].max() if len(df_cp)>0 else 0

        def hl_cp(row):
            if row["작업일수(일)"] == max_days:
                return ["background-color:#3d0000;color:#ff6b6b"]*len(row)
            return [""]*len(row)

        st.markdown("#### 작업일수 기준 CP 순위")
        st.dataframe(
            df_cp[["공종","물량","단위","1일작업량","투입조수","작업일수(일)","계산방식"]].style.apply(hl_cp, axis=1),
            use_container_width=True
        )

        # 바차트
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

        # CP 흐름도
        st.markdown("#### 크리티컬패스 흐름")
        CP_FLOW = ["굴착공","관부설공","맨홀공","배수설비","되메우기","포장복구","추진공"]
        flow_cols = st.columns(len(CP_FLOW))
        cp_dict = {r["공종"]: r for r in result_rows}
        colors_flow = {
            "굴착공":"#378ADD","관부설공":"#D85A30","맨홀공":"#E67E22",
            "배수설비":"#9B59B6","되메우기":"#EF9F27","포장복구":"#27AE60","추진공":"#E74C3C"
        }
        for i, grp in enumerate(CP_FLOW):
            with flow_cols[i]:
                r = cp_dict.get(grp, {})
                days = r.get("작업일수(일)", 0)
                bc = colors_flow.get(grp, "#555")
                is_main = days == max_days and days > 0
                st.markdown(f"""
<div style='border:2px solid {bc};border-radius:8px;padding:6px;text-align:center;
opacity:{"1.0" if days>0 else "0.3"}'>
<div style='font-size:11px;color:{bc};font-weight:bold'>{grp}</div>
<div style='font-size:16px;font-weight:bold;color:{"#ff6b6b" if is_main else "white"}'>{days}일</div>
<div style='font-size:10px;color:#aaa'>{r.get("투입조수","-")}</div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("📂 엑셀 내역서 인식 탭에서 내역서를 업로드하면 CP 분석이 표시됩니다.")

# ══════════════════════════════════════════════════════════════
# TAB 4: 비작업일수
# ══════════════════════════════════════════════════════════════
with tab4:
    st.subheader("비작업일수 계산기 (가이드라인 기준)")
    st.caption("국토교통부 적정 공사기간 확보 가이드라인 (2025.01.)")

    col1,col2=st.columns(2)
    with col1:
        proj_type       = st.selectbox("공사 종류",list(PREP_PERIOD.keys()), key="sync_proj")
        start_year      = st.selectbox("착공 연도",list(range(2025,2034)), key="sync_year")
        start_month     = st.selectbox("착공 월",list(range(1,13)),format_func=lambda x:f"{x}월", key="sync_month")
        duration_months = st.number_input("작업 개월수",min_value=1,max_value=60, key="sync_months")
        city            = st.selectbox("공사 지역",CITY_LIST, key="sync_city")
    with col2:
        st.markdown("**기상 조건**")
        use_rain=st.checkbox("강우 (5mm 이상)",value=True)
        use_cold=st.checkbox("동절기 (0도 이하)",value=True)
        use_heat=st.checkbox("혹서기 (35도 이상)",value=False)
        use_wind=st.checkbox("강풍 (15m/s 이상)",value=False)
        prep_days    = st.number_input("준비기간 (일)",value=60,min_value=0)
        cleanup_days = st.number_input("정리기간 (일)",value=30,min_value=0)

    st.markdown("---")
    corr_rows=[]; total_applied=0.0
    for i in range(int(duration_months)):
        cm=((start_month-1+i)%12)+1
        cy=start_year+(start_month-1+i)//12
        A=0.0
        if use_rain: A+=WEATHER_DB["rain5"].get(city,[0]*12)[cm-1]
        if use_cold: A+=WEATHER_DB["cold"].get(city,[0]*12)[cm-1]
        if use_heat: A+=WEATHER_DB["heat"].get(city,[0]*12)[cm-1]
        if use_wind: A+=WEATHER_DB["wind"].get(city,[0]*12)[cm-1]
        B=HOLIDAYS_DB.get(cy,HOLIDAYS_DB[2025]).get(cm,5)
        C=round(A*B/30,0)
        non_work=round(A+B-C,1)
        applied=max(8.0,non_work)
        total_applied+=applied
        corr_rows.append({
            "연월":f"{cy}년 {cm}월",
            "기상비작업일(A)":round(A,1),
            "법정공휴일(B)":B,
            "중복일수(C)":int(C),
            "비작업일수":non_work,
            "적용일수":round(applied,1),
            "비고":"최소8일" if applied>non_work else ""
        })

    nw_df=pd.DataFrame(corr_rows)
    tr=pd.DataFrame([{
        "연월":"합계",
        "기상비작업일(A)":round(nw_df["기상비작업일(A)"].sum(),1),
        "법정공휴일(B)":nw_df["법정공휴일(B)"].sum(),
        "중복일수(C)":nw_df["중복일수(C)"].sum(),
        "비작업일수":round(nw_df["비작업일수"].sum(),1),
        "적용일수":round(total_applied,1),
        "비고":""
    }])
    st.dataframe(pd.concat([nw_df,tr],ignore_index=True),hide_index=True,use_container_width=True)

    st.markdown("---")
    st.subheader("총 공사기간 산출")
    st.caption("공사기간 = 준비기간 + 비작업일수 + 작업일수 + 정리기간")

    work_result = st.session_state.get("work_result")
    total_work  = sum(r["작업일수(일)"] for r in work_result["rows"]) if work_result else 0
    total_dur   = prep_days + int(total_applied) + total_work + cleanup_days

    ca,cb,cc,cd,ce = st.columns(5)
    ca.metric("준비기간",    f"{prep_days}일")
    cb.metric("비작업일수",  f"{int(total_applied)}일")
    cc.metric("순 작업일수", f"{total_work}일")
    cd.metric("정리기간",    f"{cleanup_days}일")
    ce.metric("총 공사기간", f"{total_dur}일", delta=f"약 {round(total_dur/30,1)}개월")
    st.info(f"**{prep_days}일(준비) + {int(total_applied)}일(비작업) + {total_work}일(작업) + {cleanup_days}일(정리) = {total_dur}일**")

    fn=px.bar(nw_df,x="연월",y=["기상비작업일(A)","법정공휴일(B)"],barmode="stack",
              color_discrete_map={"기상비작업일(A)":"#378ADD","법정공휴일(B)":"#E67E22"})
    fn.add_scatter(x=nw_df["연월"],y=nw_df["적용일수"],mode="lines+markers",name="적용일수",
                   line=dict(color="red",width=2))
    fn.update_layout(height=300,margin=dict(l=10,r=10,t=20,b=10))
    st.plotly_chart(fn,use_container_width=True)
    st.caption(f"지역: {city} | 2014~2023년 10개년 평균 | 출처: 국토교통부 가이드라인(2025.01.)")
# ══════════════════════════════════════════════════════════════
# TAB 5: 공기산정 보고서 생성
# ══════════════════════════════════════════════════════════════
with tab5:
    st.subheader("📄 공기산정 근거 보고서")
    st.caption("계산된 데이터를 바탕으로 공기산정 검토서를 자동 생성합니다.")
    
    # 프로젝트 정보 입력
    with st.expander("📝 프로젝트 정보 입력", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            project_name = st.text_input("공사명", value="○○지구 하수관로 정비사업", 
                                         help="예: 지북지구 하수관로 정비사업")
            project_location = st.text_input("공사 위치", value="서울특별시", 
                                            help="예: 충청남도 보령시")
        with col2:
            project_type_report = st.selectbox("공사 구분", 
                                              ["기본 및 실시설계", "실시설계", "설계용역"])
            contractor = st.text_input("발주처", value="○○시청", 
                                      help="예: 보령시")
    
    st.markdown("---")
    
    # 데이터 확인
    st.markdown("### 📊 보고서에 포함될 데이터")
    
    col1, col2, col3 = st.columns(3)
    
    # TAB 2 데이터 확인
    has_excel_data = st.session_state.get("has_excel_data", False)
    with col1:
        if has_excel_data:
            st.success("✅ 공종별 작업일수")
            total_work_days = st.session_state.get("total_work_days", 0)
            st.metric("총 작업일수", f"{total_work_days}일")
        else:
            st.warning("⚠️ TAB 2에서 내역서를 업로드하세요")
    
    # TAB 4 데이터 확인
    work_result = st.session_state.get("work_result")
    has_work_data = work_result is not None and len(work_result.get("rows", [])) > 0
    
    with col2:
        if has_work_data:
            st.success("✅ 비작업일수 계산")
            total_work  = sum(r["작업일수(일)"] for r in work_result["rows"])
            st.metric("총 작업일수", f"{total_work}일")
        else:
            st.warning("⚠️ TAB 4에서 비작업일수를 계산하세요")
    
    # 투입조수 정보
    with col3:
        if has_excel_data or has_work_data:
            st.success("✅ 투입조수 설정")
            st.caption("공종별 투입조수 반영됨")
        else:
            st.info("ℹ️ 투입조수 정보 대기 중")
    
    st.markdown("---")
    
    # 보고서 생성 버튼
    if st.button("📥 공기산정 보고서 생성", type="primary", use_container_width=True):
        if not has_excel_data and not has_work_data:
            st.error("❌ TAB 2에서 내역서를 먼저 업로드하거나 TAB 4에서 작업일수를 계산하세요!")
        else:
            with st.spinner("📊 보고서를 생성하는 중입니다..."):
                try:
                    # 엑셀 보고서 생성
                    from openpyxl import Workbook
                    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
                    from datetime import datetime
                    import io
                    
                    wb = Workbook()
                    
                    # 시트 1: 표지
                    ws_cover = wb.active
                    ws_cover.title = "표지"
                    
                    ws_cover.merge_cells('A5:J5')
                    ws_cover['A5'] = project_name
                    ws_cover['A5'].font = Font(size=20, bold=True)
                    ws_cover['A5'].alignment = Alignment(horizontal='center', vertical='center')
                    
                    ws_cover.merge_cells('A7:J7')
                    ws_cover['A7'] = "공사기간 산정 검토서(첨부자료)"
                    ws_cover['A7'].font = Font(size=16, bold=True)
                    ws_cover['A7'].alignment = Alignment(horizontal='center', vertical='center')
                    
                    ws_cover.merge_cells('A10:J10')
                    ws_cover['A10'] = datetime.now().strftime("%Y년 %m월")
                    ws_cover['A10'].font = Font(size=14)
                    ws_cover['A10'].alignment = Alignment(horizontal='center', vertical='center')
                    
                    ws_cover.row_dimensions[5].height = 40
                    ws_cover.row_dimensions[7].height = 30
                    
                    # 시트 2: 공사기간 산정
                    ws_summary = wb.create_sheet("2. 공사기간 산정")
                    
                    row = 1
                    ws_summary[f'A{row}'] = "2. 공사기간 산정"
                    ws_summary[f'A{row}'].font = Font(size=14, bold=True)
                    row += 2
                    
                    # 작업일수 계산
                    if has_work_data:
                        total_work_days_final = sum(r["작업일수(일)"] for r in work_result["rows"])
                    else:
                        total_work_days_final = st.session_state.get("total_work_days", 0)
                    
                    # 2.1 준비기간
                    ws_summary[f'B{row}'] = "2.1 준비기간"
                    ws_summary[f'B{row}'].font = Font(size=12, bold=True)
                    row += 1
                    prep_days = st.session_state.get("sync_prep", 60)
                    ws_summary[f'C{row}'] = "준비기간"
                    ws_summary[f'H{row}'] = prep_days
                    ws_summary[f'I{row}'] = "일"
                    row += 2
                    
                    # 2.2 순작업일수
                    ws_summary[f'B{row}'] = "2.2 순작업일수"
                    ws_summary[f'B{row}'].font = Font(size=12, bold=True)
                    row += 1
                    ws_summary[f'C{row}'] = "공종별 작업일수 합계"
                    ws_summary[f'H{row}'] = total_work_days_final
                    ws_summary[f'I{row}'] = "일"
                    row += 2
                    
                    # 2.3 정리기간
                    ws_summary[f'B{row}'] = "2.3 정리기간"
                    ws_summary[f'B{row}'].font = Font(size=12, bold=True)
                    row += 1
                    clean_days = st.session_state.get("sync_clean", 30)
                    ws_summary[f'C{row}'] = "정리기간"
                    ws_summary[f'H{row}'] = clean_days
                    ws_summary[f'I{row}'] = "일"
                    row += 2
                    
                    # 2.4 총 공사기간
                    ws_summary[f'B{row}'] = "2.4 총 공사기간"
                    ws_summary[f'B{row}'].font = Font(size=12, bold=True, color="FF0000")
                    row += 1
                    total_days = prep_days + total_work_days_final + clean_days
                    ws_summary[f'C{row}'] = "총 공사기간"
                    ws_summary[f'H{row}'] = total_days
                    ws_summary[f'I{row}'] = "일"
                    ws_summary[f'H{row}'].font = Font(bold=True, size=12, color="FF0000")
                    
                    # 시트 3: 부록1. 작업일수 산정
                    ws_detail = wb.create_sheet("부록1. 작업일수 산정")
                    
                    ws_detail['A1'] = "◈ 부록1. 작업일수 산정"
                    ws_detail['A1'].font = Font(size=14, bold=True)
                    ws_detail.merge_cells('A1:K1')
                    
                    headers = ["공종", "세부공종", "규격", "수량", "단위", "1일작업량", "투입조수", "작업일수", "비고"]
                    for col_idx, header in enumerate(headers, 1):
                        cell = ws_detail.cell(row=3, column=col_idx)
                        cell.value = header
                        cell.font = Font(bold=True)
                        cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
                        cell.alignment = Alignment(horizontal='center', vertical='center')
                        cell.border = Border(
                            left=Side(style='thin'),
                            right=Side(style='thin'),
                            top=Side(style='thin'),
                            bottom=Side(style='thin')
                        )
                    
                    # 데이터 삽입 (규격별 상세)
                    row_idx = 4
                    if "detail_rows" in st.session_state and st.session_state["detail_rows"]:
                        # TAB 2에서 생성한 규격별 상세 데이터 사용
                        detail_data = st.session_state["detail_rows"]
                        
                        for item in detail_data:
                            # 공종 헤더인 경우
                            if item.get("공종") and not item.get("세부공종"):
                                cell = ws_detail.cell(row=row_idx, column=1)
                                cell.value = item["공종"]
                                cell.font = Font(bold=True, size=11)
                                cell.fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
                                cell.alignment = Alignment(horizontal='center', vertical='center')
                                
                                # 투입조수는 별도 셀에
                                ws_detail.cell(row=row_idx, column=7).value = item.get("투입조수", "")
                                
                                # 테두리
                                for col in range(1, 10):
                                    ws_detail.cell(row=row_idx, column=col).border = Border(
                                        left=Side(style='thin'),
                                        right=Side(style='thin'),
                                        top=Side(style='thin'),
                                        bottom=Side(style='thin')
                                    )
                            else:
                                # 세부 항목
                                ws_detail.cell(row=row_idx, column=1).value = ""
                                ws_detail.cell(row=row_idx, column=2).value = item.get("세부공종", "")
                                ws_detail.cell(row=row_idx, column=3).value = item.get("규격", "")
                                
                                # 수량을 숫자로 변환
                                qty_str = item.get("수량", "")
                                try:
                                    qty_val = float(str(qty_str).replace(",", "")) if qty_str else 0
                                except:
                                    qty_val = qty_str
                                    
                                ws_detail.cell(row=row_idx, column=4).value = qty_val
                                ws_detail.cell(row=row_idx, column=5).value = item.get("단위", "")
                                ws_detail.cell(row=row_idx, column=6).value = item.get("1일작업량", "")
                                ws_detail.cell(row=row_idx, column=7).value = item.get("투입조수", "")
                                
                                # 작업일수를 숫자로 변환
                                days_val = item.get("작업일수", 0)
                                try:
                                    days_val = int(days_val) if days_val else 0
                                except:
                                    days_val = 0
                                    
                                ws_detail.cell(row=row_idx, column=8).value = days_val
                                ws_detail.cell(row=row_idx, column=9).value = item.get("출처", "")
                                
                                # 테두리
                                for col in range(1, 10):
                                    ws_detail.cell(row=row_idx, column=col).border = Border(
                                        left=Side(style='thin'),
                                        right=Side(style='thin'),
                                        top=Side(style='thin'),
                                        bottom=Side(style='thin')
                                    )
                            
                            row_idx += 1
                            
                    elif has_work_data:
                        # work_result 사용 (기존 방식)
                        for item in work_result["rows"]:
                            ws_detail.cell(row=row_idx, column=1).value = item.get("공종", "")
                            ws_detail.cell(row=row_idx, column=2).value = ""
                            ws_detail.cell(row=row_idx, column=3).value = ""
                            ws_detail.cell(row=row_idx, column=4).value = item.get("물량", 0)
                            ws_detail.cell(row=row_idx, column=5).value = item.get("단위", "")
                            ws_detail.cell(row=row_idx, column=6).value = item.get("1일작업량", "")
                            ws_detail.cell(row=row_idx, column=7).value = item.get("투입조수(조)", "")
                            ws_detail.cell(row=row_idx, column=8).value = item.get("작업일수(일)", 0)
                            ws_detail.cell(row=row_idx, column=9).value = item.get("계산방식", "")
                            row_idx += 1
                    
                    # 열 너비 조정
                    ws_detail.column_dimensions['A'].width = 15
                    ws_detail.column_dimensions['B'].width = 30
                    ws_detail.column_dimensions['C'].width = 25
                    ws_detail.column_dimensions['D'].width = 12
                    ws_detail.column_dimensions['E'].width = 8
                    ws_detail.column_dimensions['F'].width = 20
                    ws_detail.column_dimensions['G'].width = 12
                    ws_detail.column_dimensions['H'].width = 12
                    ws_detail.column_dimensions['I'].width = 15
                    
                    # 파일 저장 및 다운로드
                    buffer = io.BytesIO()
                    wb.save(buffer)
                    buffer.seek(0)
                    
                    filename = f"공사기간_산정_검토서_{datetime.now().strftime('%Y%m%d')}.xlsx"
                    
                    st.success("✅ 보고서가 생성되었습니다!")
                    
                    st.download_button(
                        label="📥 보고서 다운로드",
                        data=buffer,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                    
                except Exception as e:
                    st.error(f"❌ 보고서 생성 중 오류가 발생했습니다: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
    
    # 안내사항
    st.markdown("---")
    st.info("""
    ### 📌 사용 방법
    1. **TAB 2**에서 내역서를 업로드하고 공종별 작업일수를 계산하세요
    2. 투입조수를 조정하세요 (선택사항)
    3. **TAB 4**에서 비작업일수를 계산하세요 (선택사항)
    4. 프로젝트 정보를 입력하고 **보고서 생성** 버튼을 클릭하세요
    
    ### 📄 보고서 구성
    - **표지**: 공사명, 작성일
    - **공사기간 산정**: 준비기간, 작업일수, 비작업일수, 정리기간, 총 공사기간
    - **부록1**: 공종별 상세 작업일수 산정 내역
    """)