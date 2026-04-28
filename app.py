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

LABOR_RATES = {
    "준비공": {"규준틀 설치": {"unit":"개소","보통인부":0.5}},
    "굴착공": {
        "터파기(기계)":   {"unit":"m3","특수작업원":0.02,"보통인부":0.03},
        "버력운반(기계)": {"unit":"m3","특수작업원":0.01,"보통인부":0.02},
    },
    "관부설공": {
        "관 부설접합": {
            "200mm": {"unit":"m","배관공":0.45,"보통인부":0.35},
            "300mm": {"unit":"m","배관공":0.65,"보통인부":0.50},
        },
        "수압시험": {
            "200mm": {"unit":"m","배관공":0.02,"보통인부":0.02},
            "300mm": {"unit":"m","배관공":0.03,"보통인부":0.02},
        },
    },
    "되메우기공": {
        "모래기초 포설":      {"unit":"m3","보통인부":0.35},
        "되메우기(기계다짐)": {"unit":"m3","특수작업원":0.02,"보통인부":0.10},
    },
    "포장복구공": {
        "보조기층 포설": {"unit":"m2","특수작업원":0.008,"보통인부":0.020},
        "아스콘포장":    {"unit":"m2","특수작업원":0.010,"보통인부":0.025},
    },
}

KEYWORD_MAP_DETAIL = {
    "굴착공":   ["터파기","굴착","줄파기"],
    "토사운반": ["사토","운반-토사","잔토처리","소운반"],
    "관부설공": ["관 부설","관부설","PE다중벽관","고강성PVC","주철관","GRP관",
                 "유리섬유복합관","흄관","이중벽관","강관부설","콘크리트관"],
    "되메우기": ["되메우기","모래기초","모래,관기초"],
    "포장복구": ["아스팔트포장","아스콘포장","보조기층","콘크리트포장","포장 복구","포장복구"],
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

CP_DEFINITION = [
    {"order":1,"대공종":"토공","cp_name":"터파기",
     "keywords":["터파기","굴착","줄파기"],"exclude":["운반","사토","잔토"],
     "color":"#378ADD","reason":"굴착 완료 전 후속공종 착수 불가."},
    {"order":2,"대공종":"관로공","cp_name":"관 부설접합",
     "keywords":["관 부설","관부설","PE다중벽관","고강성PVC","주철관","GRP관","흄관","이중벽관","강관부설"],
     "exclude":["수압시험","CCTV","수밀시험"],
     "color":"#D85A30","reason":"전체 공기의 핵심."},
    {"order":3,"대공종":"배수설비공","cp_name":"배수설비 설치",
     "keywords":["배수설비","오수받이","우수받이","연결관"],"exclude":[],
     "color":"#9B59B6","reason":"간선 완료 후 연결."},
    {"order":4,"대공종":"구조물공","cp_name":"맨홀 설치",
     "keywords":["맨홀","PC맨홀","GRP맨홀","소형맨홀"],"exclude":[],
     "color":"#E67E22","reason":"관로 부설 후 설치."},
    {"order":5,"대공종":"포장공","cp_name":"보조기층아스콘",
     "keywords":["보조기층","아스팔트포장","아스콘포장","콘크리트포장"],
     "exclude":["절단","철거","텍코팅","프라임코팅","깨기"],
     "color":"#27AE60","reason":"최종 복구공종."},
    {"order":6,"대공종":"추진공","cp_name":"추진관 설치",
     "keywords":["추진공","관 추진","추진설비","갱구공"],"exclude":[],
     "color":"#E74C3C","reason":"도로철도 횡단 구간."},
]

def map_cp_group(name):
    for cp in CP_DEFINITION:
        if any(ex in name for ex in cp["exclude"]):
            continue
        if any(kw in name for kw in cp["keywords"]):
            return cp["대공종"]
    return None

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

MAJOR_WORKS = [
    {"no":"No.2", "group":"굴착공","name":"터파기(B=6.0m이상)","spec":"토사,육상","qty":53227,"unit":"m3","amount":325802467,"labor":277259443,"night":False},
    {"no":"No.4", "group":"토사운반","name":"운반-토사(현장적치장)","spec":"L=3.0km","qty":68435,"unit":"m3","amount":537967535,"labor":292354320,"night":False},
    {"no":"No.10","group":"토사운반","name":"사토(적치장사토장)","spec":"L=30km","qty":87171,"unit":"m3","amount":2279957505,"labor":1026264183,"night":False},
    {"no":"No.28","group":"관부설공","name":"고강성PVC 이중벽관(직관)","spec":"200mm","qty":11857,"unit":"본","amount":413050452,"labor":392348130,"night":False},
    {"no":"No.32","group":"맨홀공","name":"조립식PC맨홀(원형1호)","spec":"H=1.7m","qty":1983,"unit":"개소","amount":1618326300,"labor":1203070236,"night":False},
    {"no":"No.31","group":"시공검사","name":"하수관CCTV조사","spec":"신설관","qty":77374,"unit":"M","amount":284426824,"labor":230651894,"night":False},
    {"no":"No.58","group":"교통관리","name":"교통정리신호수","spec":"2인1조","qty":2733,"unit":"일","amount":928148664,"labor":928148664,"night":False},
    {"no":"No.63","group":"가시설공","name":"가시설 안전난간 설치 및 철거","spec":"H1500x3000","qty":54029,"unit":"m","amount":1054159819,"labor":1033574770,"night":False},
    {"no":"No.52","group":"지장물보호","name":"지장물보호공","spec":"D=100-400이하","qty":7872,"unit":"m","amount":463117632,"labor":278479872,"night":False},
    {"no":"No.91","group":"굴착공","name":"터파기(B=6.0m이상)-야간","spec":"토사,육상","qty":6974,"unit":"m3","amount":74482320,"labor":68122032,"night":True},
    {"no":"No.104","group":"관부설공","name":"PE다중벽관 접합 및 부설-야간","spec":"D250mm","qty":540,"unit":"본","amount":62745300,"labor":61757640,"night":True},
    {"no":"No.118","group":"맨홀공","name":"조립식PC맨홀(원형1호)-야간","spec":"H=1.76m","qty":134,"unit":"개소","amount":180492238,"labor":152431566,"night":True},
]

# 굴착기·되메우기 기준 공종 (조수 = 장비대수)
MACHINE_BASED_GROUPS = ["터파기","굴착","되메우기","모래기초","모래부설","모래,관기초"]

def calc_manday(rates, quantity):
    return round(sum(v*quantity for k,v in rates.items() if k!="unit"), 2)

def to_days(manday, workers):
    return math.ceil(manday/workers) if workers>0 else 0

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

def is_machine_based(name):
    return any(kw in name for kw in MACHINE_BASED_GROUPS)

def calc_days_with_crew(name, spec, qty, crews):
    """조수(장비대수) 반영한 작업일수 계산"""
    wd_info = calc_work_days(name, spec, qty, crews=crews)
    if not wd_info:
        return 0, "-"
    base_daily = wd_info.get("daily", 0)
    unit       = wd_info.get("unit", "")
    if base_daily <= 0:
        return 0, "-"
    # 장비기반 공종: 1일작업량 × 조수(장비대수)
    if is_machine_based(name):
        days = math.ceil(qty / (base_daily * crews)) if crews > 0 else 0
        label = f"{base_daily}{unit}/일×{crews}대"
    else:
        days = wd_info.get("work_days_ceil", 0)
        label = f"{base_daily}{unit}/일×{crews}조"
    return days, label

def apply_labor_rate(item):
    try:
        name = str(item.get("name") or "")
        spec = str(item.get("spec") or "")
        qty  = float(item.get("qty") or 0)

        item.setdefault("manday", 0)
        item.setdefault("labor_rate", None)
        item.setdefault("labor_unit", "")
        item.setdefault("soil_info", "")
        item.setdefault("work_days", 0)
        item.setdefault("daily_prod", "")
        item.setdefault("crews", 0)
        item.setdefault("work_key", "")
        item.setdefault("condition", "")

        def labor_fallback(unit_str="인/개소"):
            labor = float(item.get("labor") or 0)
            if labor > 0 and qty > 0:
                item["manday"]    = round(labor / 380000, 1)
                item["soil_info"] = f"노무비역산({unit_str})"

        try:
            wd = calc_work_days(name, spec, qty)
            if wd and isinstance(wd, dict):
                item["work_days"]  = wd.get("work_days_ceil", 0)
                item["daily_prod"] = f"{wd.get('daily','')}{wd.get('unit','')}/일"
                item["crews"]      = wd.get("crews", 0)
                item["work_key"]   = wd.get("key", "")
                item["condition"]  = wd.get("condition", "")
        except Exception:
            pass

        if any(kw in name for kw in ["터파기","굴착","줄파기"]) and "운반" not in name:
            try:
                info = get_excavation_labor_detail(spec)
                if info and isinstance(info, dict):
                    rate = info.get("인/m3")
                    if rate and qty:
                        item["manday"]     = round(float(rate) * qty, 1)
                        item["labor_rate"] = rate
                        item["labor_unit"] = "인/m3"
                        item["soil_info"]  = f"{info.get('토질','')}"
            except Exception:
                labor_fallback("인/m3")
            return item

        pipe_kws = ["관 부설","관부설","이중벽관","주철관","흄관","콘크리트관",
                    "GRP관","유리섬유복합관","파형강관","PE다중벽","고강성PVC","강관부설"]
        if any(kw in name for kw in pipe_kws):
            try:
                dia = extract_diameter(spec)
                if dia:
                    info = get_pipe_labor(name, dia, "A")
                    if info and isinstance(info, dict):
                        rate = info.get("합계")
                        if rate and qty:
                            item["manday"]     = round(float(rate) * qty, 1)
                            item["labor_rate"] = rate
                            item["labor_unit"] = "인/본"
                            item["soil_info"]  = f"D={dia}mm"
                else:
                    labor_fallback("인/본")
            except Exception:
                labor_fallback("인/본")
            return item

        if any(kw in name for kw in ["맨홀"]):
            labor_fallback("인/개소")
            return item
        if any(kw in name for kw in ["되메우기","모래기초","모래,관기초","모래부설"]):
            labor_fallback("인/m3")
            return item
        if any(kw in name for kw in ["아스팔트포장","아스콘포장","보조기층","콘크리트포장","포장복구","포장깨기","포장절단"]):
            labor_fallback("인/m2")
            return item
        if any(kw in name for kw in ["배수설비","오수받이","우수받이","연결관"]):
            labor_fallback("인/개소")
            return item
        labor_fallback("인/일")
    except Exception:
        pass
    return item

SKIP_NAMES = [
    "남천지구","동부지구","신설오수관로","간선관로","지선관로",
    "순공사비","배수설비공사","토공","관로공","구조물공","포장공",
    "추진공","부대공","안전관리비","환경보전비","소계","합계","계",
]

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
        results.append({
            "group":group,"name":name,"spec":spec,
            "qty":qty,"unit":unit,"amount":amount,"labor":labor,
            "is_night":"-야간" in name,
            "manday":0,"labor_rate":None,"labor_unit":"","soil_info":"",
            "work_days":0,"daily_prod":"","crews":0,"work_key":"","condition":"",
        })

    wb.close()
    results = [apply_labor_rate(r) for r in results]

    merged = {}
    for r in results:
        key = (r["group"], r["name"].split("(")[0].strip())
        if key not in merged:
            merged[key] = dict(r)
            merged[key]["name"] = r["name"].split("(")[0].strip()
        else:
            merged[key]["qty"]       = (merged[key].get("qty")       or 0)+(r.get("qty")       or 0)
            merged[key]["amount"]    = (merged[key].get("amount")    or 0)+(r.get("amount")    or 0)
            merged[key]["labor"]     = (merged[key].get("labor")     or 0)+(r.get("labor")     or 0)
            merged[key]["manday"]    = (merged[key].get("manday")    or 0)+(r.get("manday")    or 0)
            merged[key]["work_days"] = (merged[key].get("work_days") or 0)+(r.get("work_days") or 0)

    return list(merged.values()), col_info

# ── 사이드바 ──────────────────────────────────────────────────
st.sidebar.header("기본 설정")
start_date = st.sidebar.date_input("착공 예정일", value=date.today())
st.sidebar.markdown("---")
st.sidebar.caption("공종별 투입 조수는 엑셀 내역서 인식 탭에서 설정하세요.")

if "workers" not in st.session_state:
    st.session_state.workers = {"준비공":4,"굴착공":6,"관부설공":4,"되메우기공":4,"포장복구공":4}
w = st.session_state.workers

st.title("상하수도 관로공사 공기산정 시스템")
st.markdown("---")

# TAB 이동 처리
if st.session_state.get("goto_tab1"):
    st.session_state["goto_tab1"] = False
    st.query_params["tab"] = "공기산정"

tab1,tab2,tab3,tab4 = st.tabs(["📋 공기산정","📂 엑셀 내역서 인식","🔍 주요공종 CP 분석","🌧 비작업일수 계산기"])

# ══════════════════════════════════════════════════════════════
# TAB 1
# ══════════════════════════════════════════════════════════════
with tab1:
    st.subheader("공종별 물량 입력")
    pipe_dia = st.selectbox("관경 선택", ["200mm","300mm"], key="tab1_pipe")

    col1,col2 = st.columns(2)
    with col1:
        st.markdown("**준비공**")
        q_준비 = st.number_input("규준틀 설치 (개소)",min_value=0.0,value=float(st.session_state.get("_q_준비",5.0)),step=1.0)
        st.markdown("**굴착공**")
        q_터파기 = st.number_input("터파기 물량 (m3)",min_value=0.0,value=float(st.session_state.get("_q_터파기",350.0)),step=10.0)
        st.markdown("**관부설공**")
        q_관부설 = st.number_input("관 부설 연장 (m)",min_value=0.0,value=float(st.session_state.get("_q_관부설",120.0)),step=10.0)
    with col2:
        st.markdown("**되메우기공**")
        q_되메우기 = st.number_input("되메우기 물량 (m3)",min_value=0.0,value=float(st.session_state.get("_q_되메우기",180.0)),step=10.0)
        st.markdown("**포장복구공**")
        q_포장 = st.number_input("포장 면적 (m2)",min_value=0.0,value=float(st.session_state.get("_q_포장",60.0)),step=5.0)

    st.markdown("---")
    md_준비     = calc_manday(LABOR_RATES["준비공"]["규준틀 설치"],q_준비)
    md_굴착     = calc_manday(LABOR_RATES["굴착공"]["터파기(기계)"],q_터파기)+calc_manday(LABOR_RATES["굴착공"]["버력운반(기계)"],q_터파기)
    md_관부설   = calc_manday(LABOR_RATES["관부설공"]["관 부설접합"][pipe_dia],q_관부설)+calc_manday(LABOR_RATES["관부설공"]["수압시험"][pipe_dia],q_관부설)
    md_되메우기 = calc_manday(LABOR_RATES["되메우기공"]["모래기초 포설"],q_되메우기)+calc_manday(LABOR_RATES["되메우기공"]["되메우기(기계다짐)"],q_되메우기)
    md_포장     = calc_manday(LABOR_RATES["포장복구공"]["보조기층 포설"],q_포장)+calc_manday(LABOR_RATES["포장복구공"]["아스콘포장"],q_포장)

    d_준비=to_days(md_준비,w["준비공"]); d_굴착=to_days(md_굴착,w["굴착공"])
    d_관부설=to_days(md_관부설,w["관부설공"]); d_되메우기=to_days(md_되메우기,w["되메우기공"])
    d_포장=to_days(md_포장,w["포장복구공"]); d_total=d_준비+d_굴착+d_관부설+d_되메우기+d_포장

    st.subheader("공기산정 결과")
    result_df=pd.DataFrame({
        "대공종":["준비공","굴착공","관부설공","되메우기공","포장복구공"],
        "투입인원(명)":[w["준비공"],w["굴착공"],w["관부설공"],w["되메우기공"],w["포장복구공"]],
        "Man-day(인일)":[round(md_준비,1),round(md_굴착,1),round(md_관부설,1),round(md_되메우기,1),round(md_포장,1)],
        "작업일수(일)":[d_준비,d_굴착,d_관부설,d_되메우기,d_포장],
        "CP":["🔴","🔴","🔴","🔴","🔴"],
    })
    st.dataframe(result_df.style.apply(lambda r:["background-color:#3d0000;color:#ff6b6b"]*len(r),axis=1),
                 hide_index=True,use_container_width=True)

    st.markdown("---")
    ca,cb,cc,cd=st.columns(4)
    ca.metric("순 작업일수",f"{d_total}일")
    cb.metric("총 Man-day",f"{round(md_준비+md_굴착+md_관부설+md_되메우기+md_포장,1)}인일")
    cc.metric("관경",pipe_dia); cd.metric("착공일",str(start_date))

    st.markdown("---")
    st.subheader("조수 시나리오 비교")
    scenarios=[]
    for label,factor in [("절반",0.5),("현재",1.0),("1.5배",1.5),("2배",2.0)]:
        sw={k:max(1,round(v*factor)) for k,v in w.items()}
        sd=sum([to_days(md_준비,sw["준비공"]),to_days(md_굴착,sw["굴착공"]),
                to_days(md_관부설,sw["관부설공"]),to_days(md_되메우기,sw["되메우기공"]),
                to_days(md_포장,sw["포장복구공"])])
        end=get_work_end_date(start_date,sd)
        scenarios.append({"시나리오":label,"준비공":sw["준비공"],"굴착공":sw["굴착공"],
                          "관부설공":sw["관부설공"],"되메우기":sw["되메우기공"],"포장복구":sw["포장복구공"],
                          "순작업일수":sd,"준공예정일":end.strftime("%Y-%m-%d")})
    st.dataframe(pd.DataFrame(scenarios),hide_index=True,use_container_width=True)

    st.markdown("---")
    st.subheader("간트차트")
    s1=start_date;           e1=get_work_end_date(s1,d_준비)
    s2=e1+timedelta(days=1); e2=get_work_end_date(s2,d_굴착)
    s3=e2+timedelta(days=1); e3=get_work_end_date(s3,d_관부설)
    s4=e3+timedelta(days=1); e4=get_work_end_date(s4,d_되메우기)
    s5=e4+timedelta(days=1); e5=get_work_end_date(s5,d_포장)
    gantt=pd.DataFrame([
        dict(Task="준비공",    Start=str(s1),Finish=str(e1),인원=f"{w['준비공']}명",작업일=f"{d_준비}일"),
        dict(Task="굴착공",    Start=str(s2),Finish=str(e2),인원=f"{w['굴착공']}명",작업일=f"{d_굴착}일"),
        dict(Task="관부설공",  Start=str(s3),Finish=str(e3),인원=f"{w['관부설공']}명",작업일=f"{d_관부설}일"),
        dict(Task="되메우기공",Start=str(s4),Finish=str(e4),인원=f"{w['되메우기공']}명",작업일=f"{d_되메우기}일"),
        dict(Task="포장복구공",Start=str(s5),Finish=str(e5),인원=f"{w['포장복구공']}명",작업일=f"{d_포장}일"),
    ])
    colors={"준비공":"#5DCAA5","굴착공":"#378ADD","관부설공":"#D85A30","되메우기공":"#EF9F27","포장복구공":"#7F77DD"}
    fig=px.timeline(gantt,x_start="Start",x_end="Finish",y="Task",color="Task",
                    color_discrete_map=colors,hover_data={"인원":True,"작업일":True,"Task":False})
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=350,showlegend=False,margin=dict(l=10,r=10,t=30,b=10))
    fig.update_traces(marker_line_color="red",marker_line_width=2)
    st.plotly_chart(fig,use_container_width=True)
    st.dataframe(pd.DataFrame({
        "공종":["준비공","굴착공","관부설공","되메우기공","포장복구공"],
        "착수일":[str(s1),str(s2),str(s3),str(s4),str(s5)],
        "완료일":[str(e1),str(e2),str(e3),str(e4),str(e5)],
        "작업일수":[f"{d_준비}일",f"{d_굴착}일",f"{d_관부설}일",f"{d_되메우기}일",f"{d_포장}일"],
    }),hide_index=True,use_container_width=True)

# ══════════════════════════════════════════════════════════════
# TAB 2
# ══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("엑셀 내역서 자동 인식")
    st.caption("도급 설계내역서 업로드 → 키워드 탐지 → 1일작업량 기준 작업일수 산출")

    uploaded = st.file_uploader("설계내역서 엑셀 (.xlsx)", type=["xlsx","xls"])

    if uploaded:
        try:
            with st.spinner("파싱 및 품셈 적용 중..."):
                all_rows, col_info = parse_by_keyword(uploaded)

            matched   = [r for r in all_rows if r["group"]!="기타" and r["qty"] is not None]
            unmatched = [r for r in all_rows if r["group"]=="기타"  and r["qty"] is not None]

            st.success(f"시트 **{col_info['시트명']}** 파싱 완료 | 인식 **{len(matched)}건** | 미인식 **{len(unmatched)}건**")

            with st.expander("컬럼 탐색 결과"):
                st.json(col_info)

            if matched:
                df_m = pd.DataFrame(matched)
                df_m["금액(억원)"]   = (df_m["amount"].fillna(0)/1e8).round(2)
                df_m["노무비(억원)"] = (df_m["labor"].fillna(0)/1e8).round(2)
                df_m["주야간"]       = df_m["is_night"].map({True:"🌙야간",False:"☀️주간"})
                df_m["작업일수"]     = df_m["work_days"].apply(lambda x: f"{int(x)}일" if x else "")
                df_m["1일작업량"]    = df_m["daily_prod"]
                df_m["Man-day"]      = df_m["manday"].apply(lambda x: round(x,1) if x else "")
                df_m["토질/관경"]    = df_m["soil_info"]

                ca,cb,cc,cd,ce = st.columns(5)
                ca.metric("인식 공종",f"{len(matched)}건")
                cb.metric("총 금액",f"{df_m['금액(억원)'].sum():.1f}억")
                cc.metric("총 노무비",f"{df_m['노무비(억원)'].sum():.1f}억")
                cd.metric("작업일수 산출",f"{(df_m['work_days']>0).sum()}건")
                ce.metric("야간공종",f"{df_m['is_night'].sum()}건")

                st.markdown("#### 인식된 공종 목록 (작업일수 내림차순)")
                all_groups = sorted(df_m["group"].unique().tolist())
                sel = st.multiselect("공종그룹 필터",all_groups,default=all_groups,key="t2f")
                df_m_sorted = df_m[df_m["group"].isin(sel)].copy()
                df_m_sorted["_sort"] = df_m_sorted["work_days"].fillna(0)
                df_m_sorted = df_m_sorted.sort_values("_sort",ascending=False).reset_index(drop=True)

                show_df = df_m_sorted[["group","name","spec","qty","unit",
                                       "작업일수","1일작업량",
                                       "Man-day","토질/관경",
                                       "금액(억원)","노무비(억원)","주야간"]].copy()
                show_df.columns = ["공종그룹","공종명","규격","수량","단위",
                                   "작업일수","1일작업량",
                                   "Man-day(인일)","토질/관경",
                                   "금액(억원)","노무비(억원)","주야간"]

                top10 = set(range(min(10, len(show_df))))
                def hl(row):
                    return ["background-color:#1a3a1a;color:#4CAF50"]*len(row) if row.name in top10 else [""]*len(row)
                st.dataframe(show_df.style.apply(hl,axis=1),
                             hide_index=True,use_container_width=True,height=420)
                st.caption("🟢 작업일수 상위 10개 강조 (CP 후보)")

            if unmatched:
                st.markdown("---")
                st.markdown(f"#### 미인식 항목 ({len(unmatched)}건)")
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
                        item["group"]=sel2
                        item=apply_labor_rate(item)
                        manual.append(item)
                if len(unmatched)>30:
                    st.caption(f"... 외 {len(unmatched)-30}건 더 있음")
                if manual:
                    matched=matched+manual

            # ── 공종별 작업일수 산출 ──────────────────────────
            st.markdown("---")
            st.subheader("공종별 작업일수 산출")
            st.caption("가이드라인 부록1,2 기준 | 조수 변경 시 즉시 재계산 | 작업일수 내림차순")

            if matched:
                df_md = pd.DataFrame(matched)
                md_summary={}
                for _, row in df_md.iterrows():
                    grp = row.get("group","기타")
                    md_summary[grp] = md_summary.get(grp,0)+(row.get("manday",0) or 0)

                grp_qty = df_md.groupby("group").agg(
                    물량=("qty","sum"), 단위=("unit","first")
                ).reset_index()
                grp_qty_dict = {r["group"]:(r["물량"],r["단위"]) for _,r in grp_qty.iterrows()}

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
                            value=defaults_map.get(grp,3),key=f"crew_{grp}"
                        )

                result_rows=[]
                for grp in target_groups:
                    md   = md_summary.get(grp,0)
                    wrk  = crew.get(grp,3)
                    days_from_md = math.ceil(md/wrk) if md>0 else 0

                    grp_items = [r for r in matched if r.get("group")==grp]
                    days_from_wd = 0
                    daily_repr   = "-"

                    for item in grp_items:
                        item_qty  = item.get("qty") or 0
                        item_name = item.get("name","")
                        item_spec = item.get("spec","")
                        d, label  = calc_days_with_crew(item_name, item_spec, item_qty, wrk)
                        days_from_wd += d
                        if daily_repr == "-" and label != "-":
                            daily_repr = label

                    final_days = int(days_from_wd) if days_from_wd > 0 else days_from_md
                    qty_val, unit_val = grp_qty_dict.get(grp,(0,""))

                    result_rows.append({
                        "공종":         grp,
                        "물량":         f"{qty_val:,.0f}" if qty_val else "-",
                        "단위":         unit_val,
                        "1일작업량":    daily_repr,
                        "투입조수":     f"{wrk}조",
                        "작업일수(일)": final_days,
                        "비고": "✅ 1일기준" if days_from_wd>0 else ("✅ Man-day" if md>0 else "⚠️ 없음"),
                    })

                result_rows_sorted = sorted(result_rows, key=lambda x: -x["작업일수(일)"])
                max_days = max((r["작업일수(일)"] for r in result_rows_sorted), default=0)
                total_wd = sum(r["작업일수(일)"] for r in result_rows)

                # 합계 행
                total_row = {
                    "공종":"[ 합  계 ]","물량":"-","단위":"-",
                    "1일작업량":"-","투입조수":"-",
                    "작업일수(일)":total_wd,"비고":"",
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
                    hide_index=True, use_container_width=True
                )
                st.caption("🔴 최장 작업일수 = 주공정(크리티컬패스) | 🔵 합계")

                main_grp = max((r for r in result_rows_sorted if r["작업일수(일)"]==max_days),
                               key=lambda x: x["작업일수(일)"], default={"공종":""})
                ca,cb,cc = st.columns(3)
                ca.metric("🔴 주공정 (최장)", f"{max_days}일", delta=main_grp["공종"])
                cb.metric("총 순작업일수",    f"{total_wd}일")
                cc.metric("산출 공종",        f"{sum(1 for r in result_rows if r['작업일수(일)']>0)}개")

                st.markdown("---")
                if st.button("공기산정 탭에 물량 적용", type="primary"):
                    df_a = pd.DataFrame(matched)
                    gq   = df_a.groupby("group")["qty"].sum()
                    st.session_state["_q_준비"]     = float(gq.get("준비공",   5.0))
                    st.session_state["_q_터파기"]   = float(gq.get("굴착공",   350.0))
                    st.session_state["_q_관부설"]   = float(gq.get("관부설공", 120.0))
                    st.session_state["_q_되메우기"] = float(gq.get("되메우기", 180.0))
                    st.session_state["_q_포장"]     = float(gq.get("포장복구", 60.0))
                    st.session_state.workers["굴착공"]     = crew.get("굴착공",  5)
                    st.session_state.workers["관부설공"]   = crew.get("관부설공",3)
                    st.session_state.workers["되메우기공"] = crew.get("되메우기",5)
                    st.session_state.workers["포장복구공"] = crew.get("포장복구",5)
                    st.success("✅ 적용 완료! 공기산정 탭으로 이동하세요.")
                    st.info("👆 상단의 **📋 공기산정** 탭을 클릭하거나, 키보드 **Home** 키를 누르면 상단으로 이동합니다.")
                    # 페이지 맨 위에 빈 앵커 배치 후 st.rerun으로 자동 이동
                    if st.button("⬆️ 공기산정 탭으로 이동", type="secondary"):
                        st.session_state["goto_tab1"] = True
                        st.rerun()

        except Exception as e:
            st.error(f"파싱 오류: {e}")
            st.markdown("**파일 구조 확인 (첫 4행)**")
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
# TAB 3
# ══════════════════════════════════════════════════════════════
with tab3:
    df_mw = pd.DataFrame(MAJOR_WORKS)
    df_mw["labor_ratio"] = df_mw["labor"]/df_mw["amount"]
    df_mw["cp_group"]    = df_mw["name"].apply(map_cp_group)
    df_mw["is_cp"]       = df_mw["cp_group"].notna()
    df_cp     = df_mw[df_mw["is_cp"]].copy()
    df_non_cp = df_mw[~df_mw["is_cp"]].copy()

    st.subheader("주요공종 CP 분석")
    ca,cb,cc,cd=st.columns(4)
    ca.metric("전체 주요공종",f"{len(df_mw)}건")
    cb.metric("CP 공종",f"{len(df_cp)}건")
    cc.metric("총 CP 노무비",fmt_ok(df_cp["labor"].sum()) if len(df_cp)>0 else "0억")
    cd.metric("야간 CP",f"{int(df_cp['night'].sum())}건" if len(df_cp)>0 else "0건")

    st.markdown("---")
    st.markdown("#### 크리티컬패스 흐름")
    cp_cols=st.columns(len(CP_DEFINITION))
    for i,cp in enumerate(CP_DEFINITION):
        with cp_cols[i]:
            gd=df_cp[df_cp["cp_group"]==cp["대공종"]] if len(df_cp)>0 else pd.DataFrame()
            hd=len(gd)>0
            bc=cp["color"] if hd else "#555"
            st.markdown(f"""
<div style='border:2px solid {bc};border-radius:8px;padding:8px;text-align:center;
opacity:{"1.0" if hd else "0.4"};margin:2px'>
<div style='font-size:11px;color:{bc};font-weight:bold'>{cp["order"]}순위</div>
<div style='font-size:13px;font-weight:bold'>{cp["대공종"]}</div>
<div style='font-size:10px;color:#aaa'>{cp["cp_name"]}</div>
<div style='font-size:10px;color:{"#4CAF50" if hd else "#888"}'>{"데이터 있음" if hd else "샘플 없음"}</div>
</div>""",unsafe_allow_html=True)

    st.markdown("---")
    left,right=st.columns([2,1])

    with left:
        st.markdown("#### CP 공종 상위 10개 (노무비 기준)")
        if len(df_cp)>0:
            dcs=df_cp.copy()
            dcs["금액(억원)"]  =(dcs["amount"]/1e8).round(2)
            dcs["노무비(억원)"]=(dcs["labor"]/1e8).round(2)
            dcs["노무비율"]    =(dcs["labor_ratio"]*100).round(1).astype(str)+"%"
            dcs["주야간"]      =dcs["night"].map({True:"야간",False:"주간"})
            dcs["노무집약"]    =dcs["labor_ratio"].apply(lambda x:"🔥" if x>=0.8 else "")
            t10=dcs.nlargest(10,"노무비(억원)").reset_index(drop=True)
            t10.index+=1
            sc=t10[["cp_group","name","spec","qty","unit","금액(억원)","노무비(억원)","노무비율","주야간","노무집약"]].copy()
            sc.columns=["CP그룹","공종명","규격","수량","단위","금액(억원)","노무비(억원)","노무비율","주야간","노무집약"]
            st.dataframe(sc,hide_index=False,use_container_width=True,height=380)

            with st.expander(f"비CP 제외 공종 ({len(df_non_cp)}건)"):
                if len(df_non_cp)>0:
                    dns=df_non_cp[["group","name","spec","qty","unit"]].copy()
                    dns.columns=["공종그룹","공종명","규격","수량","단위"]
                    st.dataframe(dns,hide_index=True,use_container_width=True)

        st.markdown("---")
        if len(df_cp)>0:
            cd2=df_cp.copy()
            cd2["노무비(억원)"]=(cd2["labor"]/1e8).round(2)
            cd2["공종명단축"]=cd2["name"].str[:15]
            fb=px.bar(cd2.nlargest(10,"노무비(억원)"),x="노무비(억원)",y="공종명단축",
                      color="cp_group",color_discrete_map={cp["대공종"]:cp["color"] for cp in CP_DEFINITION},
                      orientation="h",text="노무비(억원)")
            fb.update_layout(height=350,showlegend=True,margin=dict(l=10,r=10,t=20,b=10),yaxis=dict(autorange="reversed"))
            fb.update_traces(textposition="outside")
            st.plotly_chart(fb,use_container_width=True)

    with right:
        st.markdown("#### CP 선정 기준")
        for cp in CP_DEFINITION:
            gd=df_cp[df_cp["cp_group"]==cp["대공종"]] if len(df_cp)>0 else pd.DataFrame()
            hd=len(gd)>0
            with st.expander(f'{"🔴" if hd else "⚪"} {cp["order"]}. {cp["대공종"]}'):
                st.markdown(f"**근거:** {cp['reason']}")
                st.markdown(f"**키워드:** {', '.join(cp['keywords'][:4])}")
                if cp["exclude"]: st.markdown(f"**제외:** {', '.join(cp['exclude'])}")
                if hd: st.markdown(f"**데이터:** {len(gd)}건 | {fmt_ok(gd['labor'].sum())}")

        st.markdown("---")
        if len(df_mw)>0:
            cl=df_cp["labor"].sum() if len(df_cp)>0 else 0
            nl=df_non_cp["labor"].sum() if len(df_non_cp)>0 else 0
            fd=go.Figure(go.Pie(labels=["CP","비CP"],values=[cl,nl],hole=0.55,
                                marker_colors=["#E74C3C","#555"],textinfo="label+percent",textfont_size=11))
            fd.update_layout(height=240,margin=dict(l=0,r=0,t=10,b=0),showlegend=False)
            st.plotly_chart(fd,use_container_width=True)

        if len(df_cp)>0:
            gs=df_cp.groupby("cp_group")["labor"].sum().reset_index()
            fd2=go.Figure(go.Pie(labels=gs["cp_group"],values=gs["labor"],hole=0.55,
                                 textinfo="label+percent",textfont_size=10))
            fd2.update_layout(height=240,margin=dict(l=0,r=0,t=10,b=0),showlegend=False)
            st.plotly_chart(fd2,use_container_width=True)

# ══════════════════════════════════════════════════════════════
# TAB 4
# ══════════════════════════════════════════════════════════════
with tab4:
    st.subheader("비작업일수 계산기 (가이드라인 기준)")
    st.caption("국토교통부 적정 공사기간 확보 가이드라인 (2025.01.) | 전국 24개 도시 기상데이터")

    col1,col2=st.columns(2)
    with col1:
        proj_type       = st.selectbox("공사 종류",list(PREP_PERIOD.keys()),index=0)
        start_year      = st.selectbox("착공 연도",list(range(2025,2034)),index=0)
        start_month     = st.selectbox("착공 월",list(range(1,13)),index=0,format_func=lambda x:f"{x}월")
        duration_months = st.number_input("작업 개월수",min_value=1,max_value=60,value=6)
        city            = st.selectbox("공사 지역",CITY_LIST,index=CITY_LIST.index("서울") if "서울" in CITY_LIST else 0)
    with col2:
        st.markdown("**기상 조건**")
        use_rain=st.checkbox("강우 (5mm 이상)",value=True)
        use_cold=st.checkbox("동절기 (0도 이하)",value=True)
        use_heat=st.checkbox("혹서기 (35도 이상)",value=False)
        use_wind=st.checkbox("강풍 (15m/s 이상)",value=False)
        prep_days    = st.number_input("준비기간 (일)",value=PREP_PERIOD.get(proj_type,60),min_value=0)
        cleanup_days = st.number_input("정리기간 (일)",value=20,min_value=0)

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
        corr_rows.append({"연월":f"{cy}년 {cm}월","기상비작업일(A)":round(A,1),
                          "법정공휴일(B)":B,"중복일수(C)":int(C),
                          "비작업일수":non_work,"적용일수":round(applied,1),
                          "비고":"최소8일" if applied>non_work else ""})

    nw_df=pd.DataFrame(corr_rows)
    tr=pd.DataFrame([{"연월":"합계","기상비작업일(A)":round(nw_df["기상비작업일(A)"].sum(),1),
                       "법정공휴일(B)":nw_df["법정공휴일(B)"].sum(),"중복일수(C)":nw_df["중복일수(C)"].sum(),
                       "비작업일수":round(nw_df["비작업일수"].sum(),1),"적용일수":round(total_applied,1),"비고":""}])
    st.dataframe(pd.concat([nw_df,tr],ignore_index=True),hide_index=True,use_container_width=True)

    st.markdown("---")
    st.subheader("총 공사기간 산출")
    total_dur=prep_days+int(total_applied)+d_total+cleanup_days
    ca,cb,cc,cd,ce=st.columns(5)
    ca.metric("준비기간",f"{prep_days}일")
    cb.metric("비작업일수",f"{int(total_applied)}일")
    cc.metric("순 작업일수",f"{d_total}일")
    cd.metric("정리기간",f"{cleanup_days}일")
    ce.metric("총 공사기간",f"{total_dur}일",delta=f"약 {round(total_dur/30,1)}개월")
    st.info(f"**{prep_days}일(준비) + {int(total_applied)}일(비작업) + {d_total}일(작업) + {cleanup_days}일(정리) = {total_dur}일 (약 {round(total_dur/30,1)}개월)**")

    fn=px.bar(nw_df,x="연월",y=["기상비작업일(A)","법정공휴일(B)"],barmode="stack",
              color_discrete_map={"기상비작업일(A)":"#378ADD","법정공휴일(B)":"#E67E22"})
    fn.add_scatter(x=nw_df["연월"],y=nw_df["적용일수"],mode="lines+markers",name="적용일수",
                   line=dict(color="red",width=2))
    fn.update_layout(height=300,margin=dict(l=10,r=10,t=20,b=10))
    st.plotly_chart(fn,use_container_width=True)
    st.caption(f"지역: {city} | 2014~2023년 10개년 평균 | 출처: 국토교통부 가이드라인(2025.01.)")