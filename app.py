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

        results.append({
            "group":group,"name":name,"spec":spec,
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
st.sidebar.header("기본 설정")
start_date = st.sidebar.date_input("착공 예정일", value=date.today())
st.sidebar.markdown("---")
st.sidebar.caption("내역서를 업로드하면 공기산정 탭에 자동 반영됩니다.")

st.title("상하수도 관로공사 공기산정 시스템")
st.markdown("---")

tab1,tab2,tab3,tab4 = st.tabs([
    "📋 공기산정",
    "📂 엑셀 내역서 인식",
    "🔍 주요공종 CP 분석",
    "🌧 비작업일수 계산기"
])

# ══════════════════════════════════════════════════════════════
# TAB 2: 엑셀 내역서 인식 (먼저 정의 - TAB1이 결과 사용)
# ══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("엑셀 내역서 자동 인식")
    st.caption("도급 설계내역서 업로드 → 1순위:가이드라인 1일작업량 / 2순위:표준품셈 → 작업일수 산출")

    uploaded = st.file_uploader("설계내역서 엑셀 (.xlsx)", type=["xlsx","xls"])

    if uploaded:
        try:
            with st.spinner("파싱 중..."):
                all_rows, col_info = parse_by_keyword(uploaded)

            matched   = [r for r in all_rows if r["group"]!="기타" and r["qty"] is not None]
            unmatched = [r for r in all_rows if r["group"]=="기타"  and r["qty"] is not None]

            st.success(f"시트 **{col_info['시트명']}** | 인식 **{len(matched)}건** | 미인식 **{len(unmatched)}건**")

            with st.expander("컬럼 탐색 결과"):
                st.json(col_info)

            if matched:
                df_m = pd.DataFrame(matched)
                df_m["금액(억원)"]   = (df_m["amount"].fillna(0)/1e8).round(2)
                df_m["노무비(억원)"] = (df_m["labor"].fillna(0)/1e8).round(2)
                df_m["주야간"]       = df_m["is_night"].map({True:"🌙야간",False:"☀️주간"})

                ca,cb,cc,cd = st.columns(4)
                ca.metric("인식 공종",f"{len(matched)}건")
                cb.metric("총 금액",f"{df_m['금액(억원)'].sum():.1f}억")
                cc.metric("총 노무비",f"{df_m['노무비(억원)'].sum():.1f}억")
                cd.metric("야간공종",f"{df_m['is_night'].sum()}건")

                # 인식 결과 테이블
                all_groups = sorted(df_m["group"].unique().tolist())
                sel = st.multiselect("공종그룹 필터",all_groups,default=all_groups,key="t2f")
                fm = df_m[df_m["group"].isin(sel)].copy()
                fm_show = fm[["group","name","spec","qty","unit","금액(억원)","노무비(억원)","주야간"]].copy()
                fm_show.columns = ["공종그룹","공종명","규격","수량","단위","금액(억원)","노무비(억원)","주야간"]
                st.dataframe(fm_show, hide_index=True, use_container_width=True, height=300)

            if unmatched:
                st.markdown("---")
                with st.expander(f"⚠️ 미인식 항목 수동 분류하기 ({len(unmatched)}건) - 클릭하여 펼치기"):
                    st.caption("인식되지 않은 항목을 수동으로 공종 그룹에 매핑할 수 있습니다.")
                    공종목록 = ["(선택안함)"]+list(KEYWORD_MAP_DETAIL.keys())+["기타"]
                    manual=[]
                    for idx,item in enumerate(unmatched[:30]):
                        ca,cb,cc,cd,ce=st.columns([3,1,1,1,2])
                        ca.markdown(f"<span style='color:#FFA500'>{item['name'][:30]}</span>",unsafe_allow_html=True)
                        cb.write(item.get("spec","")[:10])
                        cc.write(str(item["qty"]) if item["qty"] else "-")
                        cd.write(item["unit"])
                        sel2=ce.selectbox("공종",공종목록,key=f"mn_{idx}")
                        if sel2!="(선택안함)":
                            manual.append({**item,"group":sel2})
                    if len(unmatched)>30:
                        st.caption(f"... 외 {len(unmatched)-30}건 더 있음")
                    if manual:
                        matched=matched+manual

            # ── 조수 설정 + 작업일수 계산 ────────────────────
            st.markdown("---")
            st.subheader("공종별 작업일수 산출")
            st.caption("1순위: 가이드라인 부록1,2 1일작업량 | 2순위: 표준품셈 Man-day | 작업일수 내림차순")

            if matched:
                df_md = pd.DataFrame(matched)
                grp_qty = df_md.groupby("group").agg(
                    물량=("qty","sum"), 단위=("unit","first")
                ).reset_index()
                grp_qty_dict = {r["group"]:(r["물량"],r["단위"]) for _,r in grp_qty.iterrows()}

                # 조수 설정
                st.markdown("**공종별 투입 조수 설정**")
                target_groups = ["굴착공","관부설공","되메우기","포장복구","맨홀공","배수설비","추진공"]
                defaults_map  = {"굴착공":5,"관부설공":3,"되메우기":5,"포장복구":5,
                                 "맨홀공":3,"배수설비":3,"추진공":1}
                crew_cols = st.columns(len(target_groups))
                crew={}
                for i,grp in enumerate(target_groups):
                    with crew_cols[i]:
                        crew[grp] = st.number_input(
                            f"{grp}(조)",min_value=1,max_value=30,
                            value=st.session_state.get(f"crew_{grp}", defaults_map.get(grp,3)),
                            key=f"crew_{grp}"
                        )

                # 공종별 작업일수 계산
                result_rows=[]
                for grp in target_groups:
                    wrk = crew.get(grp,3)
                    grp_items = [r for r in matched if r.get("group")==grp]

                    total_days = 0
                    daily_repr = "-"
                    method     = "-"

                    for item in grp_items:
                        item_qty  = item.get("qty") or 0
                        item_name = item.get("name","")
                        item_spec = item.get("spec","")

                        d, label, m = calc_days_priority(item_name, item_spec, item_qty, wrk)
                        total_days += d
                        if daily_repr == "-" and label != "-":
                            daily_repr = label
                            method = m

                    qty_val, unit_val = grp_qty_dict.get(grp,(0,""))

                    result_rows.append({
                        "공종":         grp,
                        "물량":         f"{qty_val:,.0f}" if qty_val else "-",
                        "단위":         unit_val,
                        "1일작업량":    daily_repr,
                        "투입조수":     f"{wrk}조",
                        "작업일수(일)": int(total_days),
                        "계산방식":     method,
                    })

                result_rows_sorted = sorted(result_rows, key=lambda x: -x["작업일수(일)"])
                max_days = max((r["작업일수(일)"] for r in result_rows_sorted), default=0)
                total_wd = max_days  # 관로 선형공사 병행시공 반영 (주공정이 곧 총 작업일수)

                # 합계행
                total_row = {"공종":"[ 합  계 ]","물량":"-","단위":"-",
                             "1일작업량":"-","투입조수":"-",
                             "작업일수(일)":total_wd,"계산방식":""}
                display_rows = result_rows_sorted + [total_row]

                def hl_result(row):
                    if row["공종"] == "[ 합  계 ]":
                        return ["background-color:#1a1a3a;color:#7F77DD;font-weight:bold"]*len(row)
                    if row["작업일수(일)"] == max_days and max_days > 0:
                        return ["background-color:#3d0000;color:#ff6b6b"]*len(row)
                    return [""]*len(row)

                st.dataframe(
                    pd.DataFrame(display_rows).style.apply(hl_result, axis=1),
                    hide_index=True, use_container_width=True
                )
                st.caption("🔴 최장 작업일수 = 주공정(크리티컬패스) | 🔵 합계")

                main_grp = next((r["공종"] for r in result_rows_sorted if r["작업일수(일)"]==max_days), "")
                ca,cb,cc = st.columns(3)
                ca.metric("🔴 주공정 (최장)", f"{max_days}일", delta=main_grp)
                cb.metric("총 순작업일수",    f"{total_wd}일")
                cc.metric("산출 공종",        f"{sum(1 for r in result_rows if r['작업일수(일)']>0)}개")

                # session_state에 결과 저장 → TAB1에서 사용
                st.session_state["work_result"] = {
                    "rows":    result_rows,
                    "crew":    crew,
                    "matched": matched,
                }

                st.markdown("---")
                st.success("✅ 위 결과가 자동으로 공기산정 탭에 반영됩니다.")
                st.markdown("""
<div style='background-color:#1a2a1a;border:1px solid #4CAF50;border-radius:8px;
padding:16px;text-align:center;margin-top:8px'>
<div style='font-size:18px;margin-bottom:8px'>
👆 상단의 <b style='color:#5DCAA5'>📋 공기산정</b> 탭을 클릭하세요
</div>
<div style='font-size:13px;color:#aaa'>키보드 <b>Home</b> 키 → 상단 이동 후 탭 클릭</div>
</div>
""", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"파싱 오류: {e}")
            try:
                wb2=openpyxl.load_workbook(uploaded,read_only=True,data_only=True)
                ws2=wb2[wb2.sheetnames[0]]
                prev=[]
                for row in ws2.iter_rows(min_row=1,max_row=4,values_only=True):
                    prev.append([str(c)[:15] if c is not None else "" for c in list(row)[:15]])
                wb2.close()
                pf=pd.DataFrame(prev,index=["1행","2행","3행","4행"])
                pf.columns=[f"col{i}" for i in range(len(pf.columns))]
                st.dataframe(pf,use_container_width=True)
            except Exception as e2:
                st.error(f"미리보기 실패: {e2}")
    else:
        st.info("도급(사급) 설계내역서 엑셀을 업로드해주세요.")

# ══════════════════════════════════════════════════════════════
# TAB 1: 공기산정 (TAB2 결과 사용)
# ══════════════════════════════════════════════════════════════
with tab1:
    st.subheader("공기산정 결과")

    work_result = st.session_state.get("work_result")

    if work_result:
        # ── TAB2 결과 사용 ────────────────────────────────────
        result_rows = work_result["rows"]
        crew        = work_result["crew"]

        st.caption("📂 엑셀 내역서 기반 | 1순위:가이드라인 1일작업량 / 2순위:표준품셈")

        # 공종 순서 (CP 순)
        CP_ORDER = ["굴착공","관부설공","되메우기","맨홀공","포장복구","배수설비","추진공"]
        rows_ordered = sorted(result_rows,
                              key=lambda x: CP_ORDER.index(x["공종"]) if x["공종"] in CP_ORDER else 99)

        max_days = max((r["작업일수(일)"] for r in result_rows), default=0)

        def hl_tab1(row):
            if row["작업일수(일)"] == max_days and max_days > 0:
                return ["background-color:#3d0000;color:#ff6b6b"]*len(row)
            return [""]*len(row)

        st.dataframe(
            pd.DataFrame(rows_ordered).style.apply(hl_tab1, axis=1),
            hide_index=True, use_container_width=True
        )

        total_wd = max_days  # 관로 선형공사 병행시공 반영
        main_grp = next((r["공종"] for r in sorted(result_rows, key=lambda x:-x["작업일수(일)"]) if r["작업일수(일)"]==max_days), "")
        ca,cb,cc = st.columns(3)
        ca.metric("🔴 주공정 (최장)", f"{max_days}일", delta=main_grp)
        cb.metric("총 순작업일수",    f"{total_wd}일")
        cc.metric("착공 예정일",      str(start_date))

        st.markdown("---")
        st.subheader("예정공정표")
        st.caption("하수관로 시공 특성 반영 | 굴착·관부설·되메우기 동시진행 | S-curve 포함")

        # ── 하수관로 공정 그룹화 ─────────────────────────────
        # Group 1: 연동공종 (굴착+관부설+되메우기 = 같은 기간)
        # Group 2: 병행공종 (맨홀 = 관부설과 동시)
        # Group 3: 후속공종 (배수설비 = 관부설 완료 후)
        # Group 4: 마지막공종 (포장복구 = 전체 완료 후)
        # 추진공: 독립 (관부설 전 선행)

        result_dict = {r["공종"]: r for r in result_rows}

        def get_days(grp):
            return result_dict.get(grp, {}).get("작업일수(일)", 0)

        # 주공정 기간 = 굴착·관부설·되메우기 중 최대값 (동시진행이므로)
        main_days = max(
            get_days("굴착공"),
            get_days("관부설공"),
            get_days("되메우기"),
        )

        # 추진공: 관부설 전 선행
        추진_days = get_days("추진공")
        추진_start = start_date
        추진_end   = get_work_end_date(추진_start, 추진_days) if 추진_days > 0 else start_date

        # 주공정 시작일 (추진공 완료 후)
        main_start = 추진_end + timedelta(days=1) if 추진_days > 0 else start_date
        main_end   = get_work_end_date(main_start, main_days) if main_days > 0 else main_start

        # 맨홀: 주공정과 동시
        맨홀_start = main_start
        맨홀_end   = get_work_end_date(맨홀_start, get_days("맨홀공")) if get_days("맨홀공") > 0 else main_end

        # 배수설비: 주공정 완료 후
        배수_days  = get_days("배수설비")
        배수_start = main_end + timedelta(days=1) if 배수_days > 0 else main_end
        배수_end   = get_work_end_date(배수_start, 배수_days) if 배수_days > 0 else 배수_start

        # 포장복구: 배수설비 완료 후
        포장_days  = get_days("포장복구")
        포장_start = 배수_end + timedelta(days=1) if 포장_days > 0 else 배수_end
        포장_end   = get_work_end_date(포장_start, 포장_days) if 포장_days > 0 else 포장_start

        준공_date = max(main_end, 맨홀_end, 배수_end, 포장_end)

        # ── 공정표 데이터 구성 ───────────────────────────────
        schedule = []

        if 추진_days > 0:
            schedule.append({
                "공종":"추진공", "그룹":"선행공종",
                "Start":str(추진_start), "Finish":str(추진_end),
                "작업일수":추진_days,
                "투입조수":result_dict.get("추진공",{}).get("투입조수","-"),
                "1일작업량":result_dict.get("추진공",{}).get("1일작업량","-"),
                "비고":"선행"
            })

        # 연동공종 (굴착·관부설·되메우기)
        for grp, label in [("굴착공","연동"),("관부설공","연동"),("되메우기","연동")]:
            d = get_days(grp)
            if d > 0:
                end = get_work_end_date(main_start, d)
                schedule.append({
                    "공종":grp, "그룹":"연동공종(동시진행)",
                    "Start":str(main_start), "Finish":str(end),
                    "작업일수":d,
                    "투입조수":result_dict.get(grp,{}).get("투입조수","-"),
                    "1일작업량":result_dict.get(grp,{}).get("1일작업량","-"),
                    "비고":"매일 동시진행"
                })

        if get_days("맨홀공") > 0:
            schedule.append({
                "공종":"맨홀공", "그룹":"병행공종",
                "Start":str(맨홀_start), "Finish":str(맨홀_end),
                "작업일수":get_days("맨홀공"),
                "투입조수":result_dict.get("맨홀공",{}).get("투입조수","-"),
                "1일작업량":result_dict.get("맨홀공",{}).get("1일작업량","-"),
                "비고":"관부설과 병행"
            })

        if 배수_days > 0:
            schedule.append({
                "공종":"배수설비", "그룹":"후속공종",
                "Start":str(배수_start), "Finish":str(배수_end),
                "작업일수":배수_days,
                "투입조수":result_dict.get("배수설비",{}).get("투입조수","-"),
                "1일작업량":result_dict.get("배수설비",{}).get("1일작업량","-"),
                "비고":"관부설 완료 후"
            })

        if 포장_days > 0:
            schedule.append({
                "공종":"포장복구", "그룹":"마무리공종",
                "Start":str(포장_start), "Finish":str(포장_end),
                "작업일수":포장_days,
                "투입조수":result_dict.get("포장복구",{}).get("투입조수","-"),
                "1일작업량":result_dict.get("포장복구",{}).get("1일작업량","-"),
                "비고":"전체 완료 후 일괄"
            })

        if schedule:
            sch_df = pd.DataFrame(schedule)

            # ── 예정공정표 바차트 ──────────────────────────────
            color_map = {
                "선행공종":      "#E74C3C",
                "연동공종(동시진행)":"#378ADD",
                "병행공종":      "#E67E22",
                "후속공종":      "#9B59B6",
                "마무리공종":    "#27AE60",
            }
            fig_sch = px.timeline(
                sch_df,
                x_start="Start", x_end="Finish", y="공종",
                color="그룹",
                color_discrete_map=color_map,
                hover_data={"작업일수":True,"투입조수":True,"1일작업량":True,"비고":True,"그룹":False},
                title=""
            )
            fig_sch.update_yaxes(autorange="reversed", title="")
            fig_sch.update_xaxes(title="", dtick="M1",
                                 tickformat="%y.%m", tickangle=0)
            fig_sch.update_layout(
                height=350,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(l=10,r=10,t=40,b=10),
            )
            fig_sch.update_traces(marker_line_color="white", marker_line_width=1)

            # 준공선 표시 (timeline은 timestamp ms 단위로 변환 필요)
            준공_ts = pd.Timestamp(str(준공_date)).value / 1e6
            fig_sch.add_vline(
                x=준공_ts, line_dash="dash",
                line_color="red", line_width=2,
                annotation_text=f"준공 {준공_date}",
                annotation_position="top right"
            )
            st.plotly_chart(fig_sch, use_container_width=True)

            # ── 공정표 상세 테이블 ────────────────────────────
            tbl = sch_df[["공종","작업일수","Start","Finish","투입조수","1일작업량","비고"]].copy()
            tbl.columns = ["공종","작업일수(일)","착수일","완료일","투입조수","1일작업량","비고"]

            def hl_sch(row):
                if "연동" in str(row.get("비고","")):
                    return ["background-color:#1a2a3a;color:#378ADD"]*len(row)
                if "일괄" in str(row.get("비고","")):
                    return ["background-color:#1a3a1a;color:#27AE60"]*len(row)
                return [""]*len(row)

            st.dataframe(
                tbl.style.apply(hl_sch, axis=1),
                hide_index=True, use_container_width=True
            )

            # ── S-curve ───────────────────────────────────────
            st.markdown("#### 공정률 S-Curve")
            st.caption("연동공종 기준 월별 누적 공정률")

            # 전체 공사 기간을 월별로 나눠서 공정률 계산
            total_days_all = (준공_date - start_date).days + 1
            if total_days_all > 0:
                # 월별 날짜 리스트 생성
                months = []
                cur = start_date.replace(day=1)
                while cur <= 준공_date:
                    months.append(cur)
                    if cur.month == 12:
                        cur = cur.replace(year=cur.year+1, month=1)
                    else:
                        cur = cur.replace(month=cur.month+1)
                months.append(준공_date)

                # 각 공종의 일별 공정 기여도 계산
                scurve_data = []
                for month_end in months:
                    completed_days = 0
                    total_work     = 0
                    for row in schedule:
                        s = date.fromisoformat(row["Start"])
                        e = date.fromisoformat(row["Finish"])
                        d = row["작업일수"]
                        total_work += d
                        # 해당 월까지 완료된 작업일수
                        if month_end >= e:
                            completed_days += d
                        elif month_end >= s:
                            ratio = (month_end - s).days / max((e-s).days,1)
                            completed_days += d * ratio

                    progress = round(completed_days / total_work * 100, 1) if total_work > 0 else 0
                    scurve_data.append({
                        "날짜":    str(month_end),
                        "누적공정률(%)": min(progress, 100.0)
                    })

                sc_df = pd.DataFrame(scurve_data)
                fig_sc = go.Figure()
                fig_sc.add_trace(go.Scatter(
                    x=sc_df["날짜"], y=sc_df["누적공정률(%)"],
                    mode="lines+markers",
                    name="계획공정률",
                    line=dict(color="#378ADD", width=3),
                    marker=dict(size=6),
                    fill="tozeroy",
                    fillcolor="rgba(55,138,221,0.15)"
                ))
                fig_sc.add_hline(y=100, line_dash="dash",
                                 line_color="red", line_width=1,
                                 annotation_text="100%")
                fig_sc.update_layout(
                    height=280,
                    xaxis_title="",
                    yaxis_title="누적 공정률 (%)",
                    yaxis=dict(range=[0,110], ticksuffix="%"),
                    xaxis=dict(tickformat="%y.%m", tickangle=0),
                    margin=dict(l=10,r=10,t=20,b=10),
                    showlegend=False,
                )
                st.plotly_chart(fig_sc, use_container_width=True)

            # 공사기간 요약
            total_cal_days = (준공_date - start_date).days + 1
            st.info(f"""
**착공: {start_date} → 준공: {준공_date}**
순작업일수 {total_wd}일 | 달력일수 {total_cal_days}일 (약 {round(total_cal_days/30,1)}개월)
연동공종(굴착·관부설·되메우기) {main_days}일 → 포장복구 후 준공
            """)

        st.markdown("---")
        st.subheader("총 공사기간 산출")
        st.caption("💡 공사기간 = 준비기간 + 비작업일수 + 순작업일수 + 정리기간 (비작업일수 탭과 연동됨)")

        # 탭 4(비작업일수 계산기)에서 설정한 값을 그대로 물려받음
        t1_proj   = st.session_state.sync_proj
        t1_prep   = st.session_state.sync_prep
        t1_cleanup= st.session_state.sync_clean
        t1_city   = st.session_state.sync_city
        t1_months = st.session_state.sync_months
        t1_year   = st.session_state.sync_year
        t1_month  = st.session_state.sync_month
        st.info(f"📍 **산출 기준 (🌧비작업일수 탭과 연동됨):** {t1_proj} | {t1_city} | {t1_year}년 {t1_month}월 착공 | 작업 {t1_months}개월")

        # 비작업일수 자동 계산
        t1_nonwork = 0.0
        for i in range(int(t1_months)):
            cm = ((t1_month-1+i)%12)+1
            cy = t1_year+(t1_month-1+i)//12
            A  = (WEATHER_DB["rain5"].get(t1_city,[0]*12)[cm-1] +
                  WEATHER_DB["cold"].get(t1_city,[0]*12)[cm-1])
            B  = HOLIDAYS_DB.get(cy, HOLIDAYS_DB[2025]).get(cm, 5)
            C  = round(A*B/30, 0)
            t1_nonwork += max(8.0, round(A+B-C, 1))

        t1_total = t1_prep + int(t1_nonwork) + total_wd + t1_cleanup

        ca,cb,cc,cd,ce = st.columns(5)
        ca.metric("준비기간",    f"{t1_prep}일")
        cb.metric("비작업일수",  f"{int(t1_nonwork)}일",
                  help="강우+동절기 기준, 월 최소 8일 적용")
        cc.metric("순 작업일수", f"{total_wd}일")
        cd.metric("정리기간",    f"{t1_cleanup}일")
        ce.metric("총 공사기간", f"{t1_total}일",
                  delta=f"약 {round(t1_total/30,1)}개월")

        st.info(f"**{t1_prep}일(준비) + {int(t1_nonwork)}일(비작업) + {total_wd}일(작업) + {t1_cleanup}일(정리) = {t1_total}일 (약 {round(t1_total/30,1)}개월)**")
        st.caption(f"비작업일수: {t1_city} 기준, 강우(5mm이상)+동절기(0도이하) 적용 | 상세 설정은 🌧 비작업일수 계산기 탭 참고")

        st.markdown("---")
        st.info("💡 조수를 바꾸려면 **📂 엑셀 내역서 인식** 탭에서 조수를 수정하세요.")

    else:
        # ── 내역서 없을 때 수동 입력 ─────────────────────────
        st.info("📂 엑셀 내역서 인식 탭에서 내역서를 업로드하면 자동으로 공기가 산정됩니다.")
        st.markdown("---")
        st.markdown("#### 수동 입력 (내역서 없을 때)")
        pipe_dia = st.selectbox("관경", ["200mm","300mm"])

        LABOR_RATES = {
            "굴착공":   {"터파기(기계)":{"unit":"m3","특수작업원":0.02,"보통인부":0.03}},
            "관부설공": {"관 부설접합":{"200mm":{"unit":"m","배관공":0.45,"보통인부":0.35},
                                        "300mm":{"unit":"m","배관공":0.65,"보통인부":0.50}}},
            "되메우기공":{"되메우기(기계다짐)":{"unit":"m3","특수작업원":0.02,"보통인부":0.10}},
            "포장복구공":{"아스콘포장":{"unit":"m2","특수작업원":0.010,"보통인부":0.025}},
        }

        col1,col2 = st.columns(2)
        with col1:
            q_터파기  = st.number_input("터파기 물량 (m3)", min_value=0.0, value=350.0, step=10.0)
            q_관부설  = st.number_input("관 부설 연장 (m)",  min_value=0.0, value=120.0, step=10.0)
        with col2:
            q_되메우기 = st.number_input("되메우기 물량 (m3)", min_value=0.0, value=180.0, step=10.0)
            q_포장     = st.number_input("포장 면적 (m2)",      min_value=0.0, value=60.0,  step=5.0)

        c1,c2,c3,c4 = st.columns(4)
        w_굴착    = c1.number_input("굴착공(조)", min_value=1, value=5)
        w_관부설  = c2.number_input("관부설공(조)", min_value=1, value=3)
        w_되메우기= c3.number_input("되메우기(조)", min_value=1, value=5)
        w_포장    = c4.number_input("포장복구(조)", min_value=1, value=5)

        # 1일작업량 기준 계산
        d_굴착    = math.ceil(q_터파기  / (420 * w_굴착))    if q_터파기  else 0
        d_관부설  = math.ceil(q_관부설  / (5   * w_관부설))  if q_관부설  else 0
        d_되메우기= math.ceil(q_되메우기 / (316 * w_되메우기)) if q_되메우기 else 0
        d_포장    = math.ceil(q_포장    / (600 * w_포장))    if q_포장    else 0
        d_total   = max(d_굴착, d_관부설, d_되메우기, d_포장)

        manual_rows = [
            {"공종":"굴착공",  "물량":f"{q_터파기:,.0f}","단위":"m3","1일작업량":f"420m3/일×{w_굴착}대","투입조수":f"{w_굴착}조","작업일수(일)":d_굴착},
            {"공종":"관부설공","물량":f"{q_관부설:,.0f}","단위":"m", "1일작업량":f"5개소/일×{w_관부설}조","투입조수":f"{w_관부설}조","작업일수(일)":d_관부설},
            {"공종":"되메우기","물량":f"{q_되메우기:,.0f}","단위":"m3","1일작업량":f"316m3/일×{w_되메우기}대","투입조수":f"{w_되메우기}조","작업일수(일)":d_되메우기},
            {"공종":"포장복구","물량":f"{q_포장:,.0f}","단위":"m2","1일작업량":f"600m2/일×{w_포장}조","투입조수":f"{w_포장}조","작업일수(일)":d_포장},
        ]
        st.dataframe(pd.DataFrame(manual_rows), hide_index=True, use_container_width=True)

        ca,cb = st.columns(2)
        ca.metric("총 순작업일수", f"{d_total}일")
        cb.metric("착공일", str(start_date))

        # 수동 간트차트
        gantt_m = []
        colors_m = {"굴착공":"#378ADD","관부설공":"#D85A30","되메우기":"#EF9F27","포장복구":"#27AE60"}
        for r in manual_rows:
            if r["작업일수(일)"] > 0:
                end = get_work_end_date(start_date, r["작업일수(일)"])
                gantt_m.append({"Task":r["공종"],"Start":str(start_date),"Finish":str(end)})
        if gantt_m:
            fig2 = px.timeline(pd.DataFrame(gantt_m), x_start="Start", x_end="Finish",
                               y="Task", color="Task", color_discrete_map=colors_m)
            fig2.update_yaxes(autorange="reversed")
            fig2.update_layout(height=300, showlegend=False, margin=dict(l=10,r=10,t=20,b=10))
            fig2.update_traces(marker_line_color="red", marker_line_width=2)
            st.plotly_chart(fig2, use_container_width=True)

    # ══════════════════════════════════════════════════════════════
    # 부록1 형태: 공종별 상세 작업일수 산정 테이블
    # ══════════════════════════════════════════════════════════════
    st.markdown("---")
    st.subheader("📊 부록1. 공종별 상세 작업일수 산정")
    st.caption("국토교통부 가이드라인 및 건설공사 표준품셈 기준 1일 작업량")
    
    # 데이터 구조: [공종대분류, 세부공종, 규격/조건, 시간당작업량, 단위, 출처, 비고]
    appendix_data = [
        # 1. 토공
        ["1. 토공", "터파기", "BH 0.12㎥+인력(10%)", 13.48, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.20㎥+인력(10%)", 22.46, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.40㎥+인력(10%)", 44.93, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.70㎥", 48.02, "㎥/hr", "일위대가", ""],
        ["", "기계터파기", "보통토사, 5m 이하(용수)", 48.02, "㎥/hr", "표준품셈", ""],
        ["", "되메우기 및 다짐(관상단)", "BH 0.12㎥+인력+콤펙터", 2.68, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.20㎥+인력+콤펙터", 22.68, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.40㎥+인력+콤펙터", 45.36, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.70㎥+콤펙터", 72.77, "㎥/hr", "일위대가", ""],
        ["", "되메우기 및 다짐(관주위)", "BH 0.12+인력(10%)+램머80kg", 13.16, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.20+인력(10%)+램머80kg", 22.68, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.40+인력(10%)+램머80kg", 45.36, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.70+램머80kg", 72.77, "㎥/hr", "일위대가", ""],
        ["", "모래부설", "BH 0.12㎥+인력(10%)", 18.53, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.20㎥+인력(10%)", 30.89, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.40㎥+인력(10%)+콤펙터", 42.12, "㎥/hr", "일위대가", ""],
        ["", "", "BH 0.70㎥+콤펙터", 81.08, "㎥/hr", "일위대가", ""],
        ["", "잡석치환", "150mm 이하", 39.29, "㎥/hr", "표준품셈", ""],
        ["", "토사 운반", "L=10km(현장→사토장)-DT24", 14.05, "㎥/hr", "표준품셈", "운반"],
        ["", "", "L=10km(현장→사토장)-DT24", 64.03, "㎥/hr", "표준품셈", "상차"],
        
        # 2. 관로공
        ["2. 관로공", "내충격PVC관 부설 및 접합", "D100mm(직관-편수)", 2.50, "개소/hr", "표준품셈 6-4-2", "배관공 기준"],
        ["", "", "D150mm(직관-편수)", 2.08, "개소/hr", "표준품셈 6-4-2", "배관공 기준"],
        ["", "", "D200mm(직관-편수)", 1.39, "개소/hr", "표준품셈 6-4-2", "배관공 기준"],
        ["", "", "D250mm(직관-편수)", 1.25, "개소/hr", "표준품셈 6-4-2", "배관공 기준"],
        ["", "", "D300mm(직관-편수)", 1.11, "개소/hr", "표준품셈 6-4-2", "배관공 기준"],
        ["", "주철관(타이튼) 부설", "D150mm", 2.00, "개소/hr", "표준품셈 6-2-1", "배관공 기준"],
        ["", "", "D200mm", 1.50, "개소/hr", "표준품셈 6-2-1", "배관공 기준"],
        ["", "", "D250mm", 1.25, "개소/hr", "표준품셈 6-2-1", "배관공 기준"],
        ["", "", "D300mm", 1.13, "개소/hr", "표준품셈 6-2-1", "배관공 기준"],
        ["", "원심력철근콘크리트관", "D300mm(소켓)", 1.88, "개소/hr", "표준품셈 6-6-1", "배관공 기준"],
        ["", "", "D400mm(소켓)", 1.38, "개소/hr", "표준품셈 6-6-1", "배관공 기준"],
        ["", "", "D500mm(소켓)", 1.00, "개소/hr", "표준품셈 6-6-1", "배관공 기준"],
        ["", "", "D600mm(소켓)", 0.81, "개소/hr", "표준품셈 6-6-1", "배관공 기준"],
        ["", "", "D800mm(소켓)", 0.63, "개소/hr", "표준품셈 6-6-1", "배관공 기준"],
        ["", "", "D1000mm(소켓)", 0.56, "개소/hr", "표준품셈 6-6-1", "배관공 기준"],
        
        # 3. 부대공
        ["3. 부대공", "조립식PC맨홀", "D900(1호-하부구체+상판)", 1.02, "개소/hr", "표준품셈", "3인조 기준"],
        ["", "", "D1200(2호-하부구체+상판)", 0.63, "개소/hr", "표준품셈", "3인조 기준"],
        ["", "", "D1500(3호-하부구체+상판)", 0.50, "개소/hr", "표준품셈", "3인조 기준"],
        ["", "소형맨홀", "D600(하부구체+상판)", 1.02, "개소/hr", "표준품셈", "5인조 기준"],
        ["", "오수받이 설치", "300×500×400(H)", 0.50, "개소/hr", "표준품셈", ""],
        ["", "배수설비", "연결관 포함", 0.50, "개소/hr", "표준품셈", ""],
        
        # 4. 포장공
        ["4. 포장공", "아스팔트포장 절단", "커터기", 75.00, "m/hr", "표준품셈", "5인조 기준"],
        ["", "아스팔트포장 깨기", "BH0.7㎥+대형브레이카", 6.75, "㎥/hr", "표준품셈", "5인조 기준"],
        ["", "콘크리트포장 절단", "커터기", 75.00, "m/hr", "표준품셈", "5인조 기준"],
        ["", "콘크리트포장 깨기", "BH0.7㎥+대형브레이카", 6.75, "㎥/hr", "표준품셈", "5인조 기준"],
        ["", "보조기층 포설", "기계포설", 100.00, "㎡/hr", "표준품셈", "5인조 기준"],
        ["", "아스콘포장", "기계시공", 75.00, "㎡/hr", "표준품셈", "5인조 기준"],
        ["", "콘크리트포장", "기계시공", 50.00, "㎡/hr", "표준품셈", "5인조 기준"],
        
        # 5. 가시설공
        ["5. 가시설공", "가시설 흙막이", "조립식 간이흙막이", 3.50, "m/hr", "표준품셈", "5인조 기준"],
        ["", "안전난간", "조립식", 5.00, "m/hr", "표준품셈", ""],
        
        # 6. 추진공
        ["6. 추진공", "강관압입추진", "D450mm(토사)", 1.00, "m/hr", "표준품셈", "1조 기준"],
        ["", "", "D600mm(토사)", 0.75, "m/hr", "표준품셈", "1조 기준"],
        ["", "", "D800mm(토사)", 0.63, "m/hr", "표준품셈", "1조 기준"],
    ]
    
    # DataFrame 생성
    df_appendix = pd.DataFrame(appendix_data, columns=[
        "공종대분류", "세부공종", "규격/조건", "시간당작업량", "단위", "출처", "비고"
    ])
    
    # 1일작업량 계산 (8시간 기준)
    df_appendix["1일작업량"] = df_appendix["시간당작업량"] * 8
    df_appendix["1일작업량"] = df_appendix["1일작업량"].round(2)
    
    # 표시용 재정렬
    df_display = df_appendix[["공종대분류", "세부공종", "규격/조건", "시간당작업량", "1일작업량", "단위", "출처", "비고"]].copy()
    
    # 필터 옵션
    col1, col2 = st.columns([1, 3])
    with col1:
        filter_category = st.selectbox(
            "공종 필터",
            ["전체"] + list(df_appendix["공종대분류"].unique())
        )
    
    # 필터 적용
    if filter_category != "전체":
        df_display = df_display[df_display["공종대분류"] == filter_category]
    
    # 스타일 적용 함수
    def highlight_category(row):
        if row["공종대분류"] and row["공종대분류"].strip():
            return ["background-color: #2c3e50; color: white; font-weight: bold"] * len(row)
        return [""] * len(row)
    
    # 테이블 표시
    st.dataframe(
        df_display.style.apply(highlight_category, axis=1),
        hide_index=True,
        use_container_width=True,
        height=600
    )
    
    # 다운로드 버튼
    csv_data = df_display.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="📥 부록1 테이블 CSV 다운로드",
        data=csv_data,
        file_name="부록1_공종별_작업일수_산정.csv",
        mime="text/csv"
    )
    
    st.info("💡 **활용 팁**: 위 테이블은 각 공종별 표준 작업량입니다. 실제 현장 조건(토질, 지장물, 장비 규격 등)에 따라 보정이 필요합니다.")

# ══════════════════════════════════════════════════════════════
# TAB 3: CP 분석
# ══════════════════════════════════════════════════════════════
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
