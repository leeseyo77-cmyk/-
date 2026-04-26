import streamlit as st
import pandas as pd
import math
import holidays
from datetime import date, timedelta
import plotly.express as px
import plotly.graph_objects as go
import openpyxl

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
    "굴착공":   ["터파기","굴착"],
    "토사운반": ["운반-토사","운반-풍화암","사토","소운반"],
    "관부설공": ["관 부설","관부설","PE다중벽관","고강성PVC","주철관접합","GRP관","유리섬유복합관"],
    "되메우기": ["되메우기","모래,관기초","모래기초"],
    "포장복구": ["아스팔트기층","아스팔트표층","콘크리트 표층","보조기층","포장절단","아스콘"],
    "맨홀공":   ["맨홀","GRP5호맨홀","PC맨홀","공기변실","이토변실","유량계실"],
    "시공검사": ["수압시험","CCTV","수밀시험"],
    "가시설공": ["가시설","안전난간","흙막이","줄파기"],
    "교통관리": ["교통정리","신호수"],
    "지장물":   ["지장물보호"],
    "부대공":   ["물푸기","관로경고테이프","표시못","품질관리"],
    "준비공":   ["규준틀","준비","측량"],
}

def map_group_detail(name):
    for group, keywords in KEYWORD_MAP_DETAIL.items():
        if any(kw in name for kw in keywords):
            return group
    return "기타"

CP_DEFINITION = [
    {
        "order": 1, "대공종": "토공", "cp_name": "터파기",
        "keywords": ["터파기","굴착"],
        "exclude":  ["운반","사토","소운반"],
        "color": "#378ADD",
        "reason": "굴착 완료 전 후속공종 착수 불가. 운반은 동시진행으로 CP 제외.",
    },
    {
        "order": 2, "대공종": "관로공", "cp_name": "관 부설접합",
        "keywords": ["관 부설","관부설","PE다중벽관","고강성PVC","주철관","GRP관","유리섬유복합관","흄관"],
        "exclude":  ["수압시험","CCTV","수밀시험"],
        "color": "#D85A30",
        "reason": "전체 공기의 핵심. 수압시험CCTV는 구간별 병행 가능하여 CP 제외.",
    },
    {
        "order": 3, "대공종": "배수설비공", "cp_name": "배수설비 설치",
        "keywords": ["배수설비","오수받이","우수받이","연결관","집수정","트렌치","측구"],
        "exclude":  [],
        "color": "#9B59B6",
        "reason": "간선 완료 후 연결. 개별 민원협의로 공기 지연 주요 원인.",
    },
    {
        "order": 4, "대공종": "구조물공", "cp_name": "맨홀 설치",
        "keywords": ["맨홀","PC맨홀","GRP맨홀","공기변실","이토실","유량계실"],
        "exclude":  [],
        "color": "#E67E22",
        "reason": "관로 부설 후 설치. 물량 많을수록 공기 영향 큼.",
    },
    {
        "order": 5, "대공종": "포장공", "cp_name": "보조기층아스콘포장",
        "keywords": ["보조기층","아스팔트","아스콘","콘크리트 표층","미끄럼방지"],
        "exclude":  ["포장절단","철거","텍코팅","프라임코팅"],
        "color": "#27AE60",
        "reason": "최종 복구공종. 포장절단은 선행 단순작업으로 CP 제외.",
    },
    {
        "order": 6, "대공종": "추진공", "cp_name": "추진관 설치",
        "keywords": ["추진","압입","비굴착","HDD","관추진"],
        "exclude":  [],
        "color": "#E74C3C",
        "reason": "도로철도 횡단 구간. 해당 구간 있을 경우 전체 공기 지배 가능.",
    },
]

def map_cp_group(name):
    for cp in CP_DEFINITION:
        if any(ex in name for ex in cp["exclude"]):
            continue
        if any(kw in name for kw in cp["keywords"]):
            return cp["대공종"]
    return None

HOLIDAYS_2025 = {1:3,2:2,3:1,4:0,5:2,6:1,7:0,8:1,9:3,10:2,11:0,12:1}
RAIN_DAYS_SEOUL = {1:0.0,2:0.0,3:0.0,4:0.0,5:0.2,6:0.6,7:7.1,8:7.7,9:0.0,10:0.0,11:0.0,12:0.0}
COLD_DAYS_SEOUL = {1:15.0,2:12.0,3:3.0,4:0.0,5:0.0,6:0.0,7:0.0,8:0.0,9:0.0,10:0.5,11:5.0,12:12.0}
HEAT_DAYS_SEOUL = {1:0.0,2:0.0,3:0.0,4:0.0,5:0.0,6:0.5,7:2.0,8:3.0,9:0.0,10:0.0,11:0.0,12:0.0}
WIND_DAYS_SEOUL = {1:1.0,2:0.5,3:0.5,4:0.5,5:0.0,6:0.0,7:0.5,8:0.5,9:0.5,10:0.5,11:0.5,12:1.0}
CITY_CORRECTION = {"서울":1.0,"인천":0.95,"수원":1.0,"부산":0.8,"대구":1.5,"광주":1.1,"대전":0.9}

MAJOR_WORKS = [
    {"no":"No.2",  "group":"굴착공",    "name":"터파기(B=6.0m이상)",                "spec":"토사,육상",       "qty":53227,"unit":"m3", "amount":325802467,  "labor":277259443,  "night":False},
    {"no":"No.4",  "group":"토사운반",   "name":"운반-토사(B=6.0m이상)(현장적치장)", "spec":"L=3.0km",        "qty":68435,"unit":"m3", "amount":537967535,  "labor":292354320,  "night":False},
    {"no":"No.10", "group":"토사운반",   "name":"사토(적치장사토장)",                "spec":"L=30km,토사",     "qty":87171,"unit":"m3", "amount":2279957505, "labor":1026264183, "night":False},
    {"no":"No.28", "group":"관부설공",   "name":"고강성PVC 이중벽관(직관)",          "spec":"200mm",          "qty":11857,"unit":"본", "amount":413050452,  "labor":392348130,  "night":False},
    {"no":"No.32", "group":"맨홀공",     "name":"조립식PC맨홀(원형1호)",             "spec":"H=1.7m",         "qty":1983, "unit":"개소","amount":1618326300,"labor":1203070236, "night":False},
    {"no":"No.31", "group":"시공검사",   "name":"하수관CCTV조사",                   "spec":"신설관",          "qty":77374,"unit":"M",  "amount":284426824,  "labor":230651894,  "night":False},
    {"no":"No.58", "group":"교통관리",   "name":"교통정리신호수",                   "spec":"2인1조",          "qty":2733, "unit":"일", "amount":928148664,  "labor":928148664,  "night":False},
    {"no":"No.63", "group":"가시설공",   "name":"가시설 안전난간 설치 및 철거",     "spec":"H1500x3000",      "qty":54029,"unit":"m",  "amount":1054159819, "labor":1033574770, "night":False},
    {"no":"No.52", "group":"지장물보호", "name":"지장물보호공",                     "spec":"D=100-400이하",   "qty":7872, "unit":"m",  "amount":463117632,  "labor":278479872,  "night":False},
    {"no":"No.91", "group":"굴착공",     "name":"터파기(B=6.0m이상)-야간",          "spec":"토사,육상",       "qty":6974, "unit":"m3", "amount":74482320,   "labor":68122032,   "night":True},
    {"no":"No.104","group":"관부설공",   "name":"PE다중벽관 접합 및 부설-야간",     "spec":"D250mm(직관)",    "qty":540,  "unit":"본", "amount":62745300,   "labor":61757640,   "night":True},
    {"no":"No.118","group":"맨홀공",     "name":"조립식PC맨홀(원형1호)-야간",       "spec":"H=1.76m",        "qty":134,  "unit":"개소","amount":180492238,  "labor":152431566,  "night":True},
]

def calc_manday(rates, quantity):
    return round(sum(v*quantity for k,v in rates.items() if k!="unit"), 2)

def to_days(manday, workers):
    return math.ceil(manday/workers) if workers > 0 else 0

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

def parse_by_keyword(file):
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    target_sheet = None
    for sname in wb.sheetnames:
        if "내역" in sname or "공종" in sname:
            target_sheet = sname
            break
    if not target_sheet:
        target_sheet = wb.sheetnames[0]
    ws = wb[target_sheet]
    all_rows = list(ws.iter_rows(values_only=True))
    header_row_idx = None
    name_col = qty_col = unit_col = None
    for i, row in enumerate(all_rows):
        row_strs = [str(c).strip() if c else "" for c in row]
        for j, cell in enumerate(row_strs):
            if cell in ["공종명","품명","공종","작업명","명칭"]:
                header_row_idx = i
                name_col = j
        if header_row_idx is not None:
            row_strs = [str(c).strip() if c else "" for c in all_rows[header_row_idx]]
            for j, cell in enumerate(row_strs):
                if cell in ["수량","물량"]:     qty_col  = j
                if cell in ["단위","규격단위"]: unit_col = j
            break
    if name_col is None:  name_col  = 0
    if qty_col is None:   qty_col   = 2
    if unit_col is None:  unit_col  = 3
    amount_col = 5
    labor_col  = 9
    if header_row_idx is not None and header_row_idx+1 < len(all_rows):
        sub_row = [str(c).strip() if c else "" for c in all_rows[header_row_idx+1]]
        amt_candidates = [j for j,c in enumerate(sub_row) if c == "금액"]
        if len(amt_candidates) >= 1: amount_col = amt_candidates[0]
        if len(amt_candidates) >= 3: labor_col  = amt_candidates[2]
    data_start = (header_row_idx + 2) if header_row_idx is not None else 3
    col_info = {
        "시트명": target_sheet, "헤더행": header_row_idx,
        "공종명컬럼": name_col, "수량컬럼": qty_col,
        "단위컬럼": unit_col, "금액컬럼": amount_col,
        "노무비컬럼": labor_col, "데이터시작행": data_start,
    }
    results = []
    for row in all_rows[data_start:]:
        if not row or len(row) <= name_col:
            continue
        name = str(row[name_col]).strip() if row[name_col] else ""
        if not name or name in ["None","합계","소계","계",""]:
            continue
        unit_val = str(row[unit_col]).strip() if unit_col < len(row) and row[unit_col] else ""
        if unit_val in ["식","1식","LS","ls","LOT","lot"]:
            continue
        group = map_group_detail(name)
        try:    qty = float(row[qty_col]) if qty_col < len(row) and row[qty_col] else None
        except: qty = None
        unit = str(row[unit_col]).strip() if unit_col < len(row) and row[unit_col] else ""
        try:    amount = float(row[amount_col]) if amount_col < len(row) and row[amount_col] else None
        except: amount = None
        try:    labor = float(row[labor_col]) if labor_col < len(row) and row[labor_col] else None
        except: labor = None
        spec = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        results.append({
            "group": group, "name": name, "spec": spec,
            "qty": qty, "unit": unit, "amount": amount,
            "labor": labor, "is_night": "-야간" in name,
        })
    wb.close()

    # ── 같은 공종명(group+name 기준) 물량 합산 ───────────────
    merged = {}
    for r in results:
        key = (r["group"], r["name"].split("(")[0].strip())  # 규격 괄호 앞 공종명 기준
        if key not in merged:
            merged[key] = {
                "group":    r["group"],
                "name":     r["name"].split("(")[0].strip(),
                "spec":     "규격 합산",
                "qty":      r["qty"] if r["qty"] else 0.0,
                "unit":     r["unit"],
                "amount":   r["amount"] if r["amount"] else 0.0,
                "labor":    r["labor"] if r["labor"] else 0.0,
                "is_night": r["is_night"],
            }
        else:
            merged[key]["qty"]    = (merged[key]["qty"]    or 0) + (r["qty"]    or 0)
            merged[key]["amount"] = (merged[key]["amount"] or 0) + (r["amount"] or 0)
            merged[key]["labor"]  = (merged[key]["labor"]  or 0) + (r["labor"]  or 0)

    return list(merged.values()), col_info

# ── 사이드바 ──────────────────────────────────────────────────
st.sidebar.header("기본 설정")
pipe_dia   = st.sidebar.selectbox("관경", ["200mm","300mm"])
start_date = st.sidebar.date_input("착공 예정일", value=date.today())
st.sidebar.markdown("---")
st.sidebar.header("공종별 투입 인원 (명/일)")

if "workers" not in st.session_state:
    st.session_state.workers = {"준비공":4,"굴착공":6,"관부설공":4,"되메우기공":4,"포장복구공":4}

for 공종 in ["준비공","굴착공","관부설공","되메우기공","포장복구공"]:
    ca, cb, cc = st.sidebar.columns([1,2,1])
    with ca:
        if st.button("－", key=f"m_{공종}"):
            st.session_state.workers[공종] = max(1, st.session_state.workers[공종]-1)
    with cb:
        st.markdown(f"<div style='text-align:center;padding-top:6px'><b>{공종}</b><br>{st.session_state.workers[공종]}명</div>", unsafe_allow_html=True)
    with cc:
        if st.button("＋", key=f"p_{공종}"):
            st.session_state.workers[공종] = min(50, st.session_state.workers[공종]+1)

w = st.session_state.workers

st.title("상하수도 관로공사 공기산정 시스템")
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["📋 공기산정", "📂 엑셀 내역서 인식", "🔍 주요공종 CP 분석", "🌧 비작업일수 계산기"])

# ═══════════════════════════════════════════════════════════════
# TAB 1: 공기산정
# ═══════════════════════════════════════════════════════════════
with tab1:
    st.subheader("공종별 물량 입력")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**준비공**")
        q_준비 = st.number_input("규준틀 설치 (개소)", min_value=0.0, value=float(st.session_state.get("_q_준비", 5.0)), step=1.0)
        st.markdown("**굴착공**")
        q_터파기 = st.number_input("터파기 물량 (m3)", min_value=0.0, value=float(st.session_state.get("_q_터파기", 350.0)), step=10.0)
        st.markdown("**관부설공**")
        q_관부설 = st.number_input("관 부설 연장 (m)", min_value=0.0, value=float(st.session_state.get("_q_관부설", 120.0)), step=10.0)
    with col2:
        st.markdown("**되메우기공**")
        q_되메우기 = st.number_input("되메우기 물량 (m3)", min_value=0.0, value=float(st.session_state.get("_q_되메우기", 180.0)), step=10.0)
        st.markdown("**포장복구공**")
        q_포장 = st.number_input("포장 면적 (m2)", min_value=0.0, value=float(st.session_state.get("_q_포장", 60.0)), step=5.0)

    st.markdown("---")
    md_준비     = calc_manday(LABOR_RATES["준비공"]["규준틀 설치"], q_준비)
    md_굴착     = calc_manday(LABOR_RATES["굴착공"]["터파기(기계)"], q_터파기) + calc_manday(LABOR_RATES["굴착공"]["버력운반(기계)"], q_터파기)
    md_관부설   = calc_manday(LABOR_RATES["관부설공"]["관 부설접합"][pipe_dia], q_관부설) + calc_manday(LABOR_RATES["관부설공"]["수압시험"][pipe_dia], q_관부설)
    md_되메우기 = calc_manday(LABOR_RATES["되메우기공"]["모래기초 포설"], q_되메우기) + calc_manday(LABOR_RATES["되메우기공"]["되메우기(기계다짐)"], q_되메우기)
    md_포장     = calc_manday(LABOR_RATES["포장복구공"]["보조기층 포설"], q_포장) + calc_manday(LABOR_RATES["포장복구공"]["아스콘포장"], q_포장)

    d_준비     = to_days(md_준비,     w["준비공"])
    d_굴착     = to_days(md_굴착,     w["굴착공"])
    d_관부설   = to_days(md_관부설,   w["관부설공"])
    d_되메우기 = to_days(md_되메우기, w["되메우기공"])
    d_포장     = to_days(md_포장,     w["포장복구공"])
    d_total    = d_준비 + d_굴착 + d_관부설 + d_되메우기 + d_포장

    st.subheader("공기산정 결과")
    result_df = pd.DataFrame({
        "대공종":         ["준비공","굴착공","관부설공","되메우기공","포장복구공"],
        "투입인원 (명)":  [w["준비공"],w["굴착공"],w["관부설공"],w["되메우기공"],w["포장복구공"]],
        "Man-day (인일)": [md_준비,md_굴착,md_관부설,md_되메우기,md_포장],
        "작업일수 (일)":  [d_준비,d_굴착,d_관부설,d_되메우기,d_포장],
        "크리티컬패스":   ["🔴","🔴","🔴","🔴","🔴"],
    })
    st.dataframe(
        result_df.style.apply(lambda r: ["background-color:#3d0000;color:#ff6b6b"]*len(r), axis=1),
        hide_index=True, use_container_width=True
    )

    st.markdown("---")
    st.subheader("공기 요약")
    ca, cb, cc, cd = st.columns(4)
    ca.metric("순 작업일수", f"{d_total}일")
    cb.metric("총 Man-day",  f"{round(md_준비+md_굴착+md_관부설+md_되메우기+md_포장,1)}인일")
    cc.metric("관경", pipe_dia)
    cd.metric("착공일", str(start_date))

    st.markdown("---")
    st.subheader("조수 시나리오 비교")
    scenarios = []
    for label, factor in [("절반",0.5),("현재",1.0),("1.5배",1.5),("2배",2.0)]:
        sw = {k: max(1, round(v*factor)) for k,v in w.items()}
        sd = sum([to_days(md_준비,sw["준비공"]), to_days(md_굴착,sw["굴착공"]),
                  to_days(md_관부설,sw["관부설공"]), to_days(md_되메우기,sw["되메우기공"]),
                  to_days(md_포장,sw["포장복구공"])])
        end = get_work_end_date(start_date, sd)
        scenarios.append({
            "시나리오": label,
            "준비공": sw["준비공"], "굴착공": sw["굴착공"],
            "관부설공": sw["관부설공"], "되메우기": sw["되메우기공"], "포장복구": sw["포장복구공"],
            "순작업일수": sd, "준공예정일": end.strftime("%Y-%m-%d")
        })
    st.dataframe(pd.DataFrame(scenarios), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("간트차트")
    s1=start_date;           e1=get_work_end_date(s1, d_준비)
    s2=e1+timedelta(days=1); e2=get_work_end_date(s2, d_굴착)
    s3=e2+timedelta(days=1); e3=get_work_end_date(s3, d_관부설)
    s4=e3+timedelta(days=1); e4=get_work_end_date(s4, d_되메우기)
    s5=e4+timedelta(days=1); e5=get_work_end_date(s5, d_포장)
    gantt = pd.DataFrame([
        dict(Task="준비공",    Start=str(s1),Finish=str(e1),인원=f"{w['준비공']}명",    작업일=f"{d_준비}일"),
        dict(Task="굴착공",    Start=str(s2),Finish=str(e2),인원=f"{w['굴착공']}명",    작업일=f"{d_굴착}일"),
        dict(Task="관부설공",  Start=str(s3),Finish=str(e3),인원=f"{w['관부설공']}명",  작업일=f"{d_관부설}일"),
        dict(Task="되메우기공",Start=str(s4),Finish=str(e4),인원=f"{w['되메우기공']}명",작업일=f"{d_되메우기}일"),
        dict(Task="포장복구공",Start=str(s5),Finish=str(e5),인원=f"{w['포장복구공']}명",작업일=f"{d_포장}일"),
    ])
    colors = {"준비공":"#5DCAA5","굴착공":"#378ADD","관부설공":"#D85A30","되메우기공":"#EF9F27","포장복구공":"#7F77DD"}
    fig = px.timeline(gantt, x_start="Start", x_end="Finish", y="Task", color="Task",
                      color_discrete_map=colors, hover_data={"인원":True,"작업일":True,"Task":False})
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=350, showlegend=False, margin=dict(l=10,r=10,t=30,b=10))
    fig.update_traces(marker_line_color="red", marker_line_width=2)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(pd.DataFrame({
        "공종":    ["준비공","굴착공","관부설공","되메우기공","포장복구공"],
        "착수일":  [str(s1),str(s2),str(s3),str(s4),str(s5)],
        "완료일":  [str(e1),str(e2),str(e3),str(e4),str(e5)],
        "작업일수":[f"{d_준비}일",f"{d_굴착}일",f"{d_관부설}일",f"{d_되메우기}일",f"{d_포장}일"],
    }), hide_index=True, use_container_width=True)

# ═══════════════════════════════════════════════════════════════
# TAB 2: 엑셀 내역서 인식
# ═══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("엑셀 내역서 자동 인식")
    st.caption("키워드 기반으로 주요공종을 자동 탐지합니다. 1식 항목은 자동 제외됩니다.")

    uploaded = st.file_uploader("내역서 엑셀 파일 업로드 (.xlsx)", type=["xlsx","xls"])

    if uploaded:
        try:
            with st.spinner("파싱 중..."):
                all_rows, col_info = parse_by_keyword(uploaded)

            matched   = [r for r in all_rows if r["group"] != "기타" and r["qty"] is not None]
            unmatched = [r for r in all_rows if r["group"] == "기타"  and r["qty"] is not None]

            st.success(f"시트 {col_info['시트명']} 파싱 완료 | 인식 {len(matched)}건 | 미인식 {len(unmatched)}건")

            with st.expander("컬럼 탐색 결과 확인"):
                st.json(col_info)

            st.markdown("---")

            if matched:
                df_matched = pd.DataFrame(matched)
                df_matched["금액(억원)"]   = (df_matched["amount"].fillna(0)/1e8).round(2)
                df_matched["노무비(억원)"] = (df_matched["labor"].fillna(0)/1e8).round(2)
                df_matched["주야간"]       = df_matched["is_night"].map({True:"야간",False:"주간"})
                df_matched = df_matched.sort_values("금액(억원)", ascending=False).reset_index(drop=True)

                ca,cb,cc,cd = st.columns(4)
                ca.metric("인식된 공종", f"{len(matched)}건")
                cb.metric("총 금액",     f"{df_matched['금액(억원)'].sum():.1f}억")
                cc.metric("총 노무비",   f"{df_matched['노무비(억원)'].sum():.1f}억")
                cd.metric("야간공종",    f"{df_matched['is_night'].sum()}건")

                st.markdown("#### 인식된 공종 목록")
                all_groups = sorted(df_matched["group"].unique().tolist())
                sel_groups = st.multiselect("공종그룹 필터", all_groups, default=all_groups, key="tab2_filter")
                filtered_m = df_matched[df_matched["group"].isin(sel_groups)]
                show_df = filtered_m[["group","name","spec","qty","unit","금액(억원)","노무비(억원)","주야간"]].copy()
                show_df.columns = ["공종그룹","공종명","규격","수량","단위","금액(억원)","노무비(억원)","주야간"]
                top10 = set(filtered_m.nlargest(10,"금액(억원)").index)

                def hl_m(row):
                    return ["background-color:#3a3000;color:#FFD700"]*len(row) if row.name in top10 else [""]*len(row)

                st.dataframe(show_df.style.apply(hl_m, axis=1), hide_index=True, use_container_width=True, height=400)

            if unmatched:
                st.markdown("---")
                st.markdown(f"#### 미인식 항목 ({len(unmatched)}건) — 수동 선택")
                공종목록 = ["(선택안함)"] + list(KEYWORD_MAP_DETAIL.keys()) + ["기타"]
                manual_mapped = []
                for idx, item in enumerate(unmatched[:30]):
                    ca,cb,cc,cd,ce = st.columns([3,1,1,1,2])
                    ca.markdown(f"<span style='color:#FFA500'>{item['name'][:30]}</span>", unsafe_allow_html=True)
                    cb.write(item.get("spec","")[:10])
                    cc.write(str(item["qty"]) if item["qty"] else "-")
                    cd.write(item["unit"])
                    sel = ce.selectbox("공종", 공종목록, key=f"manual_{idx}")
                    if sel != "(선택안함)":
                        manual_mapped.append({**item, "group": sel})
                if len(unmatched) > 30:
                    st.caption(f"... 외 {len(unmatched)-30}건 더 있음")
                if manual_mapped:
                    matched = matched + manual_mapped

            st.markdown("---")
            if matched and st.button("인식 물량을 공기산정에 적용", type="primary"):
                df_apply = pd.DataFrame(matched)
                grp_qty  = df_apply.groupby("group")["qty"].sum()
                st.session_state["_q_준비"]     = float(grp_qty.get("준비공",   5.0))
                st.session_state["_q_터파기"]   = float(grp_qty.get("굴착공",   350.0))
                st.session_state["_q_관부설"]   = float(grp_qty.get("관부설공", 120.0))
                st.session_state["_q_되메우기"] = float(grp_qty.get("되메우기", 180.0))
                st.session_state["_q_포장"]     = float(grp_qty.get("포장복구", 60.0))
                st.success(f"""공기산정 탭에 아래 물량이 적용됩니다.
- 준비공: {grp_qty.get('준비공',0):.0f}
- 굴착공: {grp_qty.get('굴착공',0):.0f} m3
- 관부설공: {grp_qty.get('관부설공',0):.0f} m
- 되메우기: {grp_qty.get('되메우기',0):.0f} m3
- 포장복구: {grp_qty.get('포장복구',0):.0f} m2""")

        except Exception as e:
            st.error(f"파싱 오류: {e}")
            st.markdown("**파일 구조 확인 (첫 4행)**")
            try:
                wb2 = openpyxl.load_workbook(uploaded, read_only=True, data_only=True)
                ws2 = wb2[wb2.sheetnames[0]]
                preview = []
                for row in ws2.iter_rows(min_row=1, max_row=4, values_only=True):
                    preview.append([str(c)[:15] if c is not None else "" for c in list(row)[:15]])
                wb2.close()
                prev_df = pd.DataFrame(preview, index=["1행","2행","3행","4행"])
                prev_df.columns = [f"col{i}" for i in range(len(prev_df.columns))]
                st.dataframe(prev_df, use_container_width=True)
            except Exception as e2:
                st.error(f"미리보기 실패: {e2}")
    else:
        st.info("내역서 엑셀 파일을 업로드해주세요.")

# ═══════════════════════════════════════════════════════════════
# TAB 3: 주요공종 CP 분석
# ═══════════════════════════════════════════════════════════════
with tab3:
    df_mw = pd.DataFrame(MAJOR_WORKS)
    df_mw["labor_ratio"] = df_mw["labor"] / df_mw["amount"]
    df_mw["cp_group"]    = df_mw["name"].apply(map_cp_group)
    df_mw["is_cp"]       = df_mw["cp_group"].notna()
    df_cp     = df_mw[df_mw["is_cp"]].copy()
    df_non_cp = df_mw[~df_mw["is_cp"]].copy()

    st.subheader("주요공종 CP 분석")
    st.caption("하수관로 사업 기준 크리티컬패스 자동 선정 | 운반·수압시험 등 비CP 공종 제외")

    ca,cb,cc,cd = st.columns(4)
    ca.metric("전체 주요공종", f"{len(df_mw)}건")
    cb.metric("CP 공종",       f"{len(df_cp)}건")
    cc.metric("총 CP 노무비",  fmt_ok(df_cp["labor"].sum()) if len(df_cp)>0 else "0억")
    cd.metric("야간 CP 공종",  f"{int(df_cp['night'].sum())}건" if len(df_cp)>0 else "0건")

    st.markdown("---")
    st.markdown("#### 크리티컬패스 흐름")
    cp_cols = st.columns(len(CP_DEFINITION))
    for i, cp in enumerate(CP_DEFINITION):
        with cp_cols[i]:
            grp_data = df_cp[df_cp["cp_group"]==cp["대공종"]] if len(df_cp)>0 else pd.DataFrame()
            has_data = len(grp_data) > 0
            bc = cp["color"] if has_data else "#555"
            op = "1.0" if has_data else "0.4"
            badge = "데이터 있음" if has_data else "샘플 없음"
            st.markdown(f"""
<div style='border:2px solid {bc};border-radius:8px;padding:8px;text-align:center;opacity:{op};margin:2px'>
<div style='font-size:11px;color:{bc};font-weight:bold'>{cp["order"]}순위</div>
<div style='font-size:13px;font-weight:bold'>{cp["대공종"]}</div>
<div style='font-size:10px;color:#aaa'>{cp["cp_name"]}</div>
<div style='font-size:10px;color:{"#4CAF50" if has_data else "#888"}'>{badge}</div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    left, right = st.columns([2,1])

    with left:
        st.markdown("#### CP 공종 상위 10개 (노무비 기준)")
        st.caption("운반·사토·수압시험·CCTV·포장절단 등 비CP 공종 자동 제외")

        if len(df_cp) > 0:
            df_cp_show = df_cp.copy()
            df_cp_show["금액(억원)"]   = (df_cp_show["amount"]/1e8).round(2)
            df_cp_show["노무비(억원)"] = (df_cp_show["labor"]/1e8).round(2)
            df_cp_show["노무비율"]     = (df_cp_show["labor_ratio"]*100).round(1).astype(str) + "%"
            df_cp_show["주야간"]       = df_cp_show["night"].map({True:"야간",False:"주간"})
            df_cp_show["노무집약"]     = df_cp_show["labor_ratio"].apply(lambda x: "🔥" if x>=0.8 else "")
            top10_cp = df_cp_show.nlargest(10,"노무비(억원)").reset_index(drop=True)
            top10_cp.index = top10_cp.index + 1
            show_top10 = top10_cp[["cp_group","name","spec","qty","unit","금액(억원)","노무비(억원)","노무비율","주야간","노무집약"]].copy()
            show_top10.columns = ["CP그룹","공종명","규격","수량","단위","금액(억원)","노무비(억원)","노무비율","주야간","노무집약"]
            st.dataframe(show_top10, hide_index=False, use_container_width=True, height=380)

            with st.expander(f"비CP 제외 공종 ({len(df_non_cp)}건) — 운반·수압시험 등"):
                if len(df_non_cp) > 0:
                    df_non_show = df_non_cp[["group","name","spec","qty","unit"]].copy()
                    df_non_show.columns = ["공종그룹","공종명","규격","수량","단위"]
                    st.dataframe(df_non_show, hide_index=True, use_container_width=True)
                    st.caption("이 공종들은 CP와 병행 진행되거나 CP에 종속되어 전체 공기에 영향 없음")
        else:
            st.info("샘플 데이터에 해당 CP 공종이 없습니다.")

        st.markdown("---")
        st.markdown("#### CP 공종 노무비 비교")
        if len(df_cp) > 0:
            chart_df = df_cp.copy()
            chart_df["노무비(억원)"] = (chart_df["labor"]/1e8).round(2)
            chart_df["공종명단축"]   = chart_df["name"].str[:15]
            fig_bar = px.bar(
                chart_df.nlargest(10,"노무비(억원)"),
                x="노무비(억원)", y="공종명단축", color="cp_group",
                color_discrete_map={cp["대공종"]:cp["color"] for cp in CP_DEFINITION},
                orientation="h", text="노무비(억원)",
                labels={"cp_group":"CP그룹","공종명단축":"공종명"},
            )
            fig_bar.update_layout(height=350, showlegend=True, margin=dict(l=10,r=10,t=20,b=10), yaxis=dict(autorange="reversed"))
            fig_bar.update_traces(textposition="outside")
            st.plotly_chart(fig_bar, use_container_width=True)

    with right:
        st.markdown("#### CP 선정 기준")
        for cp in CP_DEFINITION:
            grp_data = df_cp[df_cp["cp_group"]==cp["대공종"]] if len(df_cp)>0 else pd.DataFrame()
            has_data = len(grp_data) > 0
            with st.expander(f'{"🔴" if has_data else "⚪"} {cp["order"]}. {cp["대공종"]}'):
                st.markdown(f"**CP 근거:** {cp['reason']}")
                st.markdown(f"**인식 키워드:** {', '.join(cp['keywords'][:4])}")
                if cp["exclude"]:
                    st.markdown(f"**제외 키워드:** {', '.join(cp['exclude'])}")
                if has_data:
                    st.markdown(f"**데이터:** {len(grp_data)}건 | 노무비 {fmt_ok(grp_data['labor'].sum())}")

        st.markdown("---")
        st.markdown("#### CP vs 비CP 노무비")
        if len(df_mw) > 0:
            cp_labor    = df_cp["labor"].sum() if len(df_cp)>0 else 0
            noncp_labor = df_non_cp["labor"].sum() if len(df_non_cp)>0 else 0
            fig_d = go.Figure(go.Pie(
                labels=["CP 공종","비CP 공종"],
                values=[cp_labor, noncp_labor],
                hole=0.55,
                marker_colors=["#E74C3C","#555"],
                textinfo="label+percent",
                textfont_size=11,
            ))
            fig_d.update_layout(height=250, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            st.plotly_chart(fig_d, use_container_width=True)

        if len(df_cp) > 0:
            st.markdown("#### CP 공종그룹별 노무비")
            grp_sum = df_cp.groupby("cp_group")["labor"].sum().reset_index()
            fig_d2 = go.Figure(go.Pie(
                labels=grp_sum["cp_group"], values=grp_sum["labor"],
                hole=0.55, textinfo="label+percent", textfont_size=10,
            ))
            fig_d2.update_layout(height=250, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            st.plotly_chart(fig_d2, use_container_width=True)

# ═══════════════════════════════════════════════════════════════
# TAB 4: 비작업일수 계산기
# ═══════════════════════════════════════════════════════════════
with tab4:
    st.subheader("비작업일수 계산기 (가이드라인 기준)")
    st.caption("국토교통부 적정 공사기간 확보 가이드라인 (2025.01.) 기준 | 전국 96개 지점 기상데이터 적용")

    # ── 법정공휴일 (2025~2033년) ──────────────────────────────
    HOLIDAYS_DB = {
        2025: {1:8,  2:4,  3:7,  4:4,  5:6,  6:6,  7:4,  8:6,  9:4,  10:9,  11:5,  12:5},
        2026: {1:5,  2:7,  3:6,  4:4,  5:7,  6:5,  7:4,  8:7,  9:7,  10:7,  11:5,  12:5},
        2027: {1:6,  2:7,  3:5,  4:4,  5:7,  6:4,  7:4,  8:6,  9:7,  10:8,  11:4,  12:6},
        2028: {1:9,  2:4,  3:5,  4:5,  5:6,  6:5,  7:5,  8:5,  9:4,  10:10, 11:4,  12:6},
        2029: {1:5,  2:7,  3:5,  4:5,  5:7,  6:5,  7:5,  8:5,  9:8,  10:6,  11:4,  12:6},
        2030: {1:5,  2:7,  3:6,  4:4,  5:6,  6:6,  7:4,  8:5,  9:8,  10:6,  11:4,  12:6},
        2031: {1:8,  2:4,  3:7,  4:4,  5:6,  6:6,  7:4,  8:6,  9:5,  10:8,  11:5,  12:5},
        2032: {1:5,  2:8,  3:5,  4:4,  5:7,  6:4,  7:4,  8:6,  9:7,  10:8,  11:4,  12:6},
        2033: {1:7,  2:6,  3:5,  4:4,  5:7,  6:5,  7:5,  8:5,  9:7,  10:7,  11:4,  12:5},
    }

    # ── 전국 주요 도시 기상 비작업일수 (2014~2023 평균) ───────
    # 구조: [1월,2월,3월,4월,5월,6월,7월,8월,9월,10월,11월,12월]
    WEATHER_DB = {
        # 강우 5mm 이상
        "rain5": {
            "서울":   [0.5,1.1,1.7,3.7,4.4,5.2,7.2,8.4,3.6,3.0,3.3,1.4],
            "부산":   [1.0,1.4,2.7,4.0,4.4,6.2,7.8,8.5,5.8,3.2,3.5,1.6],
            "대구":   [0.3,0.8,1.7,3.0,3.9,5.0,7.2,7.6,3.9,2.0,2.3,0.7],
            "인천":   [0.6,1.1,1.8,3.5,4.2,5.0,7.6,8.1,3.9,3.1,3.4,1.5],
            "광주":   [1.0,1.7,3.0,4.5,5.1,6.8,8.7,8.4,5.5,3.4,4.0,1.7],
            "대전":   [0.5,1.1,2.0,3.8,4.5,5.6,7.9,8.3,4.2,2.7,3.3,1.2],
            "울산":   [1.0,1.4,2.5,4.0,4.6,6.1,7.2,8.2,5.4,3.0,3.3,1.6],
            "세종":   [0.5,1.0,1.9,3.7,4.4,5.5,7.8,8.2,4.1,2.6,3.2,1.2],
            "수원":   [0.5,1.1,1.8,3.6,4.3,5.2,7.4,8.2,3.7,3.0,3.3,1.4],
            "전주":   [0.8,1.4,2.5,4.1,4.8,6.3,8.5,8.3,4.8,3.0,3.7,1.4],
            "청주":   [0.5,1.0,1.9,3.6,4.3,5.5,7.9,8.3,4.0,2.5,3.2,1.1],
            "춘천":   [0.5,1.0,1.9,3.6,4.5,5.7,7.5,8.4,4.0,2.8,3.1,1.2],
            "원주":   [0.5,1.0,1.9,3.5,4.5,5.6,7.4,8.2,4.0,2.8,3.0,1.2],
            "강릉":   [1.3,1.4,2.5,4.0,4.9,5.5,5.5,8.0,5.5,3.9,4.4,2.1],
            "제주":   [3.0,3.2,5.1,6.7,7.0,8.2,9.0,9.6,7.9,6.0,6.1,3.8],
            "포항":   [0.8,1.2,2.3,3.6,4.4,5.6,6.5,7.4,5.2,2.8,3.2,1.3],
            "안동":   [0.3,0.8,1.6,3.0,3.8,5.0,7.0,7.4,3.9,2.0,2.4,0.8],
            "목포":   [1.4,2.0,3.5,5.2,5.8,7.4,8.2,7.7,5.4,3.5,4.1,2.0],
            "여수":   [1.4,1.9,3.5,5.3,5.8,7.8,8.6,8.1,5.9,3.5,4.0,2.0],
            "순천":   [1.0,1.6,3.0,4.7,5.2,7.0,8.4,8.0,5.4,3.2,3.7,1.7],
            "군산":   [0.9,1.4,2.5,4.2,4.8,6.5,8.3,8.0,5.0,3.2,3.6,1.5],
            "진주":   [0.8,1.3,2.5,4.0,4.6,6.5,7.8,7.9,5.0,2.8,3.2,1.3],
            "창원":   [1.0,1.5,2.7,4.2,4.8,6.5,7.5,7.9,5.4,3.0,3.4,1.5],
            "순창군": [1.7,1.9,3.7,4.7,4.0,6.1,9.4,8.2,5.2,3.1,3.3,2.5],
        },
        # 동절기 (일최고기온 0도이하 또는 신적설5cm이상)
        "cold": {
            "서울":   [6.9,3.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.2,7.0],
            "부산":   [0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1],
            "대구":   [1.2,0.3,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.3],
            "인천":   [5.7,2.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1,5.9],
            "광주":   [0.8,0.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.8],
            "대전":   [3.1,1.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,3.3],
            "울산":   [0.3,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.4],
            "세종":   [4.0,1.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1,4.2],
            "수원":   [6.4,2.8,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1,6.6],
            "전주":   [1.7,0.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.8],
            "청주":   [3.5,1.3,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,3.7],
            "춘천":   [11.5,6.1,0.5,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.6,11.8],
            "원주":   [9.0,4.5,0.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.3,9.3],
            "강릉":   [1.7,0.8,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.2],
            "제주":   [0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0],
            "포항":   [0.3,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.4],
            "안동":   [5.2,2.2,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.2,5.5],
            "목포":   [0.3,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.3],
            "여수":   [0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.1],
            "순천":   [0.5,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.5],
            "군산":   [2.2,0.7,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,2.3],
            "진주":   [0.5,0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.6],
            "창원":   [0.1,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.2],
            "순창군": [3.7,2.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,2.3],
        },
        # 혹서기 (35도 이상)
        "heat": {
            "서울":   [0.0,0.0,0.0,0.0,0.0,0.0,1.9,2.4,0.0,0.0,0.0,0.0],
            "부산":   [0.0,0.0,0.0,0.0,0.0,0.0,0.2,1.4,0.0,0.0,0.0,0.0],
            "대구":   [0.0,0.0,0.0,0.0,0.0,0.1,2.8,5.4,0.0,0.0,0.0,0.0],
            "인천":   [0.0,0.0,0.0,0.0,0.0,0.0,0.2,2.1,0.0,0.0,0.0,0.0],
            "광주":   [0.0,0.0,0.0,0.0,0.0,0.0,4.0,6.5,0.0,0.0,0.0,0.0],
            "대전":   [0.0,0.0,0.0,0.0,0.0,0.0,3.6,6.0,0.0,0.0,0.0,0.0],
            "울산":   [0.0,0.0,0.0,0.0,0.0,0.0,1.9,2.7,0.0,0.0,0.0,0.0],
            "세종":   [0.0,0.0,0.0,0.0,0.0,0.0,0.0,2.0,0.0,0.0,0.0,0.0],
            "수원":   [0.0,0.0,0.0,0.0,0.0,0.0,2.7,4.4,0.0,0.0,0.0,0.0],
            "전주":   [0.0,0.0,0.0,0.0,0.0,0.0,2.8,5.3,0.0,0.0,0.0,0.0],
            "청주":   [0.0,0.0,0.0,0.0,0.0,0.0,1.1,3.1,0.0,0.0,0.0,0.0],
            "춘천":   [0.0,0.0,0.0,0.0,0.0,0.0,2.4,2.4,0.0,0.0,0.0,0.0],
            "원주":   [0.0,0.0,0.0,0.0,0.0,0.0,0.8,0.7,0.0,0.0,0.0,0.0],
            "강릉":   [0.0,0.0,0.0,0.0,0.0,0.0,1.8,2.8,0.0,0.0,0.0,0.0],
            "제주":   [0.0,0.0,0.0,0.0,0.0,0.0,2.2,3.0,0.0,0.0,0.0,0.0],
            "포항":   [0.0,0.0,0.0,0.0,0.0,0.1,3.7,4.3,0.0,0.0,0.0,0.0],
            "안동":   [0.0,0.0,0.0,0.0,0.0,0.0,1.2,3.4,0.0,0.0,0.0,0.0],
            "목포":   [0.0,0.0,0.0,0.0,0.0,0.0,1.0,3.0,0.0,0.0,0.0,0.0],
            "여수":   [0.0,0.0,0.0,0.0,0.0,0.0,0.2,0.4,0.0,0.0,0.0,0.0],
            "순천":   [0.0,0.0,0.0,0.0,0.0,0.0,1.3,2.6,0.0,0.0,0.0,0.0],
            "군산":   [0.0,0.0,0.0,0.0,0.0,0.0,1.7,4.0,0.0,0.0,0.0,0.0],
            "진주":   [0.0,0.0,0.0,0.0,0.0,0.0,0.9,4.0,0.0,0.0,0.0,0.0],
            "창원":   [0.0,0.0,0.0,0.0,0.0,0.0,4.3,5.4,0.0,0.0,0.0,0.0],
            "순창군": [0.0,0.0,0.0,0.0,0.0,0.1,8.4,11.2,0.3,0.0,0.0,0.0],
        },
        # 강풍 (15m/s 이상)
        "wind": {
            "서울":   [1.3,1.5,2.2,1.5,1.2,0.5,0.6,0.8,0.7,0.8,1.0,1.3],
            "부산":   [2.2,2.2,3.1,2.4,1.8,1.0,1.4,1.6,1.9,1.8,2.1,2.3],
            "대구":   [0.4,0.5,0.8,0.5,0.3,0.1,0.1,0.2,0.2,0.2,0.3,0.4],
            "인천":   [2.1,2.3,2.9,2.1,1.5,0.7,0.8,1.0,1.1,1.2,1.7,2.1],
            "광주":   [0.7,0.9,1.4,0.9,0.6,0.3,0.4,0.5,0.4,0.5,0.6,0.7],
            "대전":   [0.5,0.7,1.1,0.8,0.5,0.2,0.2,0.3,0.3,0.3,0.4,0.5],
            "울산":   [1.4,1.6,2.4,1.8,1.3,0.7,0.9,1.1,1.2,1.2,1.4,1.5],
            "세종":   [0.5,0.7,1.0,0.7,0.5,0.2,0.2,0.3,0.3,0.3,0.4,0.5],
            "수원":   [1.0,1.2,1.8,1.3,0.9,0.4,0.5,0.6,0.6,0.7,0.9,1.0],
            "전주":   [0.7,0.9,1.5,1.0,0.7,0.3,0.4,0.5,0.4,0.5,0.6,0.7],
            "청주":   [0.5,0.7,1.1,0.8,0.5,0.2,0.3,0.3,0.3,0.3,0.4,0.5],
            "춘천":   [0.9,1.1,1.7,1.2,0.9,0.4,0.5,0.6,0.6,0.6,0.8,0.9],
            "원주":   [0.7,0.9,1.4,1.0,0.7,0.3,0.4,0.5,0.5,0.5,0.6,0.7],
            "강릉":   [2.5,2.7,3.6,2.8,2.1,1.1,1.3,1.5,1.8,2.0,2.4,2.6],
            "제주":   [5.5,5.8,7.2,6.0,4.5,2.8,3.5,3.9,4.6,4.8,5.6,5.7],
            "포항":   [1.5,1.7,2.6,2.0,1.5,0.8,1.0,1.2,1.3,1.3,1.5,1.6],
            "안동":   [0.5,0.7,1.2,0.8,0.5,0.2,0.3,0.3,0.3,0.3,0.4,0.5],
            "목포":   [3.0,3.3,4.5,3.5,2.6,1.4,1.7,1.9,2.3,2.5,3.0,3.1],
            "여수":   [1.8,2.0,3.0,2.3,1.7,0.9,1.1,1.3,1.4,1.5,1.8,1.9],
            "순천":   [0.6,0.8,1.3,0.9,0.6,0.3,0.4,0.5,0.4,0.5,0.6,0.6],
            "군산":   [2.0,2.2,3.2,2.4,1.7,0.8,1.0,1.2,1.3,1.4,1.8,2.0],
            "진주":   [0.6,0.8,1.3,0.9,0.6,0.3,0.4,0.5,0.5,0.5,0.6,0.6],
            "창원":   [1.2,1.4,2.1,1.6,1.1,0.6,0.8,0.9,1.0,1.0,1.2,1.3],
            "순창군": [1.0,1.5,3.1,2.0,2.2,0.4,0.5,0.8,0.8,0.8,1.0,1.4],
        },
    }

    CITY_LIST = sorted(WEATHER_DB["rain5"].keys())
    PREP_PERIOD = {
        "하수도공사": 60, "상수도공사": 60, "포장공사(신설)": 50,
        "포장공사(수선)": 60, "하천공사": 40, "항만공사": 40,
        "공동주택": 45, "고속도로공사": 180, "철도공사": 90,
        "강교가설공사": 90, "PC교량공사": 70, "교량보수공사": 60,
        "공동구공사": 80,
    }

    col1, col2 = st.columns(2)
    with col1:
        proj_type   = st.selectbox("공사 종류", list(PREP_PERIOD.keys()), index=0)
        start_year  = st.selectbox("착공 연도", list(range(2025, 2034)), index=0)
        start_month = st.selectbox("착공 월", list(range(1,13)), index=0, format_func=lambda x: f"{x}월")
        duration_months = st.number_input("작업 개월수", min_value=1, max_value=60, value=6)
        city        = st.selectbox("공사 지역", CITY_LIST, index=CITY_LIST.index("서울") if "서울" in CITY_LIST else 0)

    with col2:
        st.markdown("**기상 조건 선택**")
        use_rain = st.checkbox("강우 (일강수량 5mm 이상)", value=True)
        use_cold = st.checkbox("동절기 (일최고기온 0도 이하 또는 신적설 5cm)", value=True)
        use_heat = st.checkbox("혹서기 (일최고기온 35도 이상)", value=False)
        use_wind = st.checkbox("강풍 (일최대순간풍속 15m/s 이상)", value=False)
        st.markdown("---")
        prep_days    = st.number_input("준비기간 (일)", value=PREP_PERIOD.get(proj_type, 60), min_value=0)
        cleanup_days = st.number_input("정리기간 (일)", value=20, min_value=0)
        st.caption("정리기간 기본값: 20일 (가이드라인 기준)")

    st.markdown("---")

    # ── 월별 비작업일수 계산 ─────────────────────────────────
    rows_nw = []
    total_applied = 0.0

    for i in range(int(duration_months)):
        cur_month = ((start_month - 1 + i) % 12) + 1
        cur_year  = start_year + (start_month - 1 + i) // 12

        # A: 기상 비작업일수
        A = 0.0
        rain_data = WEATHER_DB["rain5"].get(city, {})
        cold_data = WEATHER_DB["cold"].get(city, {})
        heat_data = WEATHER_DB["heat"].get(city, {})
        wind_data = WEATHER_DB["wind"].get(city, {})

        if use_rain and rain_data: A += rain_data[cur_month - 1]
        if use_cold and cold_data: A += cold_data[cur_month - 1]
        if use_heat and heat_data: A += heat_data[cur_month - 1]
        if use_wind and wind_data: A += wind_data[cur_month - 1]

        # B: 법정공휴일
        year_holidays = HOLIDAYS_DB.get(cur_year, HOLIDAYS_DB[2025])
        B = year_holidays.get(cur_month, 5)

        # C: 중복일수
        calendar_days = 30
        C = round(A * B / calendar_days, 0)

        # 비작업일수
        non_work = round(A + B - C, 1)

        # 주40시간 기준 월 최소 8일
        applied = max(8.0, non_work)
        total_applied += applied

        rows_nw.append({
            "연월":          f"{cur_year}년 {cur_month}월",
            "기상비작업일(A)": round(A, 1),
            "법정공휴일(B)":   B,
            "중복일수(C)":     int(C),
            "비작업일수":      non_work,
            "적용일수":        round(applied, 1),
            "비고":           "최소8일적용" if applied > non_work else "",
        })

    nw_df = pd.DataFrame(rows_nw)
    total_row = pd.DataFrame([{
        "연월": "합계",
        "기상비작업일(A)": round(nw_df["기상비작업일(A)"].sum(), 1),
        "법정공휴일(B)":   nw_df["법정공휴일(B)"].sum(),
        "중복일수(C)":     nw_df["중복일수(C)"].sum(),
        "비작업일수":      round(nw_df["비작업일수"].sum(), 1),
        "적용일수":        round(total_applied, 1),
        "비고":           "",
    }])

    st.dataframe(
        pd.concat([nw_df, total_row], ignore_index=True),
        hide_index=True, use_container_width=True
    )

    st.markdown("---")
    st.subheader("총 공사기간 산출")
    st.caption("공사기간 = 준비기간 + 비작업일수 + 작업일수 + 정리기간 (가이드라인 2.6조)")

    total_duration = prep_days + int(total_applied) + d_total + cleanup_days

    ca,cb,cc,cd,ce = st.columns(5)
    ca.metric("준비기간",    f"{prep_days}일")
    cb.metric("비작업일수",  f"{int(total_applied)}일")
    cc.metric("순 작업일수", f"{d_total}일")
    cd.metric("정리기간",    f"{cleanup_days}일")
    ce.metric("총 공사기간", f"{total_duration}일", delta=f"약 {round(total_duration/30,1)}개월")

    # 세부 내역
    st.info(f"""
**총 공사기간 산출 내역**
- 준비기간: {prep_days}일 ({proj_type} 기준)
- 비작업일수: {int(total_applied)}일 (가이드라인 기준, 월 최소 8일 적용)
- 순 작업일수: {d_total}일 (공기산정 탭 결과)
- 정리기간: {cleanup_days}일
- **합계: {total_duration}일 (약 {round(total_duration/30,1)}개월 = 약 {round(total_duration/365,1)}년)**
    """)

    # 월별 비작업일수 차트
    st.markdown("#### 월별 비작업일수 분포")
    fig_nw = px.bar(
        nw_df, x="연월", y=["기상비작업일(A)","법정공휴일(B)"],
        barmode="stack",
        color_discrete_map={"기상비작업일(A)":"#378ADD","법정공휴일(B)":"#E67E22"},
        labels={"value":"일수","variable":"구분"},
    )
    fig_nw.add_scatter(x=nw_df["연월"], y=nw_df["적용일수"],
                       mode="lines+markers", name="적용일수",
                       line=dict(color="red", width=2))
    fig_nw.update_layout(height=320, margin=dict(l=10,r=10,t=20,b=10))
    st.plotly_chart(fig_nw, use_container_width=True)
    st.caption(f"지역: {city} | 기상데이터: 2014~2023년 10개년 평균 | 출처: 국토교통부 가이드라인(2025.01.)")