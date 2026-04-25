import streamlit as st
import pandas as pd
import math
import holidays
from datetime import date, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="상하수도 공기산정", layout="wide")

# ── 비밀번호 로그인 ───────────────────────────────────────────
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

# ── 표준품셈 딕셔너리 ─────────────────────────────────────────
LABOR_RATES = {
    "준비공": {"규준틀 설치": {"unit":"개소","보통인부":0.5}},
    "굴착공": {
        "터파기(기계)": {"unit":"m³","특수작업원":0.02,"보통인부":0.03},
        "버력운반(기계)": {"unit":"m³","특수작업원":0.01,"보통인부":0.02},
    },
    "관부설공": {
        "관 부설·접합": {
            "200mm": {"unit":"m","배관공":0.45,"보통인부":0.35},
            "300mm": {"unit":"m","배관공":0.65,"보통인부":0.50},
        },
        "수압시험": {
            "200mm": {"unit":"m","배관공":0.02,"보통인부":0.02},
            "300mm": {"unit":"m","배관공":0.03,"보통인부":0.02},
        },
    },
    "되메우기공": {
        "모래기초 포설": {"unit":"m³","보통인부":0.35},
        "되메우기(기계다짐)": {"unit":"m³","특수작업원":0.02,"보통인부":0.10},
    },
    "포장복구공": {
        "보조기층 포설": {"unit":"m²","특수작업원":0.008,"보통인부":0.020},
        "아스콘포장": {"unit":"m²","특수작업원":0.010,"보통인부":0.025},
    },
}

KEYWORD_MAP = {
    "준비공":     ["규준","가시설","토류","교통"],
    "굴착공":     ["터파기","굴착"],
    "관부설공":   ["관 부설","관부설","배관","접합"],
    "되메우기공": ["모래","기초","되메우기","다짐"],
    "포장복구공": ["아스콘","포장","복구"],
    "맨홀공":     ["맨홀"],
}

HOLIDAYS_2025 = {1:3,2:2,3:1,4:0,5:2,6:1,7:0,8:1,9:3,10:2,11:0,12:1}
RAIN_DAYS_SEOUL = {1:0.0,2:0.0,3:0.0,4:0.0,5:0.2,6:0.6,7:7.1,8:7.7,9:0.0,10:0.0,11:0.0,12:0.0}
COLD_DAYS_SEOUL = {1:15.0,2:12.0,3:3.0,4:0.0,5:0.0,6:0.0,7:0.0,8:0.0,9:0.0,10:0.5,11:5.0,12:12.0}
HEAT_DAYS_SEOUL = {1:0.0,2:0.0,3:0.0,4:0.0,5:0.0,6:0.5,7:2.0,8:3.0,9:0.0,10:0.0,11:0.0,12:0.0}
WIND_DAYS_SEOUL = {1:1.0,2:0.5,3:0.5,4:0.5,5:0.0,6:0.0,7:0.5,8:0.5,9:0.5,10:0.5,11:0.5,12:1.0}
CITY_CORRECTION = {"서울":1.0,"인천":0.95,"수원":1.0,"부산":0.8,"대구":1.5,"광주":1.1,"대전":0.9}

# ── 샘플 주요공종 데이터 ──────────────────────────────────────
MAJOR_WORKS = [
    {"no":"No.2",  "group":"굴착공",   "name":"터파기(B=6.0m이상)",                    "spec":"토사,육상",            "qty":53227, "unit":"m3",  "amount":325802467,  "labor":277259443,  "night":False},
    {"no":"No.4",  "group":"토사운반",  "name":"운반-토사(B=6.0m이상)(현장→적치장)",    "spec":"L=3.0km,DT15.0TON",   "qty":68435, "unit":"m3",  "amount":537967535,  "labor":292354320,  "night":False},
    {"no":"No.10", "group":"토사운반",  "name":"사토(적치장→사토장)",                   "spec":"L=30km,토사",          "qty":87171, "unit":"m3",  "amount":2279957505, "labor":1026264183, "night":False},
    {"no":"No.28", "group":"관부설공",  "name":"고강성PVC 이중벽관(직관)",              "spec":"￠200mm",              "qty":11857, "unit":"본",  "amount":413050452,  "labor":392348130,  "night":False},
    {"no":"No.32", "group":"맨홀공",    "name":"조립식PC맨홀(원형1호)",                 "spec":"H=1.7m",               "qty":1983,  "unit":"개소", "amount":1618326300, "labor":1203070236, "night":False},
    {"no":"No.31", "group":"시공검사",  "name":"하수관CCTV조사",                        "spec":"신설관",               "qty":77374, "unit":"M",   "amount":284426824,  "labor":230651894,  "night":False},
    {"no":"No.58", "group":"교통관리",  "name":"교통정리신호수",                        "spec":"2인1조",               "qty":2733,  "unit":"일",  "amount":928148664,  "labor":928148664,  "night":False},
    {"no":"No.63", "group":"가시설공",  "name":"가시설 안전난간 설치 및 철거",          "spec":"H1500×3000",           "qty":54029, "unit":"m",   "amount":1054159819, "labor":1033574770, "night":False},
    {"no":"No.52", "group":"지장물보호","name":"지장물보호공",                          "spec":"D=100~400이하",        "qty":7872,  "unit":"m",   "amount":463117632,  "labor":278479872,  "night":False},
    {"no":"No.91", "group":"굴착공",    "name":"터파기(B=6.0m이상)-야간",               "spec":"토사,육상",            "qty":6974,  "unit":"m3",  "amount":74482320,   "labor":68122032,   "night":True},
    {"no":"No.104","group":"관부설공",  "name":"PE다중벽관 접합 및 부설-야간",          "spec":"D250mm(직관)",         "qty":540,   "unit":"본",  "amount":62745300,   "labor":61757640,   "night":True},
    {"no":"No.118","group":"맨홀공",    "name":"조립식PC맨홀(원형1호)-야간",            "spec":"H=1.76m",              "qty":134,   "unit":"개소", "amount":180492238,  "labor":152431566,  "night":True},
]

# ── 공통 함수 ─────────────────────────────────────────────────
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
            current += timedelta(days=1); continue
        worked += 1; current += timedelta(days=1)
    return current - timedelta(days=1)

def fmt_억(val):
    return f"{val/1e8:.1f}억"

# ═══════════════════════════════════════════════════════════════
# 사이드바
# ═══════════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════════
# 탭 구성
# ═══════════════════════════════════════════════════════════════
st.title("상하수도 관로공사 공기산정 시스템")
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["📋 공기산정", "📂 엑셀 내역서 인식", "🔍 주요공종 분석", "🌧 비작업일수 계산기"])

# ═══════════════════════════════════════════════════════════════
# TAB 1: 공기산정
# ═══════════════════════════════════════════════════════════════
with col1:
        st.markdown("**준비공**")
        q_준비 = st.number_input("규준틀 설치 (개소)", min_value=0.0,
            value=float(st.session_state.get("_q_준비", 5.0)), step=1.0)
        st.markdown("**굴착공**")
        q_터파기 = st.number_input("터파기 물량 (m³)", min_value=0.0,
            value=float(st.session_state.get("_q_터파기", 350.0)), step=10.0)
        st.markdown("**관부설공**")
        q_관부설 = st.number_input("관 부설 연장 (m)", min_value=0.0,
            value=float(st.session_state.get("_q_관부설", 120.0)), step=10.0)
    with col2:
        st.markdown("**되메우기공**")
        q_되메우기 = st.number_input("되메우기 물량 (m³)", min_value=0.0,
            value=float(st.session_state.get("_q_되메우기", 180.0)), step=10.0)
        st.markdown("**포장복구공**")
        q_포장 = st.number_input("포장 면적 (m²)", min_value=0.0,
            value=float(st.session_state.get("_q_포장", 60.0)), step=5.0)

    st.markdown("---")

    md_준비     = calc_manday(LABOR_RATES["준비공"]["규준틀 설치"], q_준비)
    md_굴착     = calc_manday(LABOR_RATES["굴착공"]["터파기(기계)"], q_터파기) + calc_manday(LABOR_RATES["굴착공"]["버력운반(기계)"], q_터파기)
    md_관부설   = calc_manday(LABOR_RATES["관부설공"]["관 부설·접합"][pipe_dia], q_관부설) + calc_manday(LABOR_RATES["관부설공"]["수압시험"][pipe_dia], q_관부설)
    md_되메우기 = calc_manday(LABOR_RATES["되메우기공"]["모래기초 포설"], q_되메우기) + calc_manday(LABOR_RATES["되메우기공"]["되메우기(기계다짐)"], q_되메우기)
    md_포장     = calc_manday(LABOR_RATES["포장복구공"]["보조기층 포설"], q_포장) + calc_manday(LABOR_RATES["포장복구공"]["아스콘포장"], q_포장)

    d_준비     = to_days(md_준비,     w["준비공"])
    d_굴착     = to_days(md_굴착,     w["굴착공"])
    d_관부설   = to_days(md_관부설,   w["관부설공"])
    d_되메우기 = to_days(md_되메우기, w["되메우기공"])
    d_포장     = to_days(md_포장,     w["포장복구공"])
    d_total    = d_준비+d_굴착+d_관부설+d_되메우기+d_포장

    st.subheader("공기산정 결과")
    st.caption("🔴 전체 공종이 크리티컬 패스 (순차 FS 관계)")

    result_df = pd.DataFrame({
        "대공종":         ["준비공","굴착공","관부설공","되메우기공","포장복구공"],
        "투입인원 (명)":  [w["준비공"],w["굴착공"],w["관부설공"],w["되메우기공"],w["포장복구공"]],
        "Man-day (인일)": [md_준비,md_굴착,md_관부설,md_되메우기,md_포장],
        "작업일수 (일)":  [d_준비,d_굴착,d_관부설,d_되메우기,d_포장],
        "크리티컬패스":   ["🔴","🔴","🔴","🔴","🔴"],
    })
    st.dataframe(result_df.style.apply(lambda r: ["background-color:#3d0000;color:#ff6b6b"]*len(r), axis=1),
                 hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("공기 요약")
    ca,cb,cc,cd = st.columns(4)
    ca.metric("순 작업일수", f"{d_total}일")
    cb.metric("총 Man-day",  f"{round(md_준비+md_굴착+md_관부설+md_되메우기+md_포장,1)}인일")
    cc.metric("관경", pipe_dia)
    cd.metric("착공일", str(start_date))

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
    st.dataframe(pd.DataFrame(scenarios), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("간트차트")
    s1=start_date; e1=get_work_end_date(s1,d_준비)
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
    }), hide_index=True, use_container_width=True)

# ═══════════════════════════════════════════════════════════════
# TAB 2: 엑셀 내역서 인식
# ═══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("엑셀 내역서 자동 인식")
    st.caption("내역서 엑셀을 업로드하면 키워드로 주요공종을 자동 탐지합니다.")

    # ── 키워드 매핑 ───────────────────────────────────────────
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

    # ── 핵심 파싱 함수 (키워드 중심) ─────────────────────────
    def parse_by_keyword(file):
        import openpyxl
        wb = openpyxl.load_workbook(file, read_only=True, data_only=True)

        # 시트 자동 선택
        target_sheet = None
        for sname in wb.sheetnames:
            if "내역" in sname or "공종" in sname:
                target_sheet = sname
                break
        if not target_sheet:
            target_sheet = wb.sheetnames[0]

        ws = wb[target_sheet]
        all_rows = list(ws.iter_rows(values_only=True))

        # ── 헤더 행 자동 탐색 ─────────────────────────────────
        # "공종명" 또는 "품명" 이 들어있는 행을 헤더로 판단
        header_row_idx = None
        name_col = qty_col = unit_col = amount_col = labor_col = None

        for i, row in enumerate(all_rows):
            row_strs = [str(c).strip() if c else "" for c in row]
            for j, cell in enumerate(row_strs):
                if cell in ["공종명","품명","공종","작업명","명칭"]:
                    header_row_idx = i
                    name_col = j
            if header_row_idx is not None:
                # 같은 행에서 다른 컬럼 탐색
                row_strs = [str(c).strip() if c else "" for c in all_rows[header_row_idx]]
                for j, cell in enumerate(row_strs):
                    if cell in ["수량","물량"]:       qty_col    = j
                    if cell in ["단위","규격단위"]:   unit_col   = j
                # 금액/노무비는 고정 인덱스 우선 사용
                break

        # 헤더를 못찾으면 고정 인덱스 사용
        if name_col is None:   name_col   = 0
        if qty_col is None:    qty_col    = 2
        if unit_col is None:   unit_col   = 3

        # 금액/노무비: 헤더 다음 행에서 "금액" 위치 탐색
        amount_col = 5   # 기본값
        labor_col  = 9   # 기본값

        if header_row_idx is not None and header_row_idx+1 < len(all_rows):
            sub_row = [str(c).strip() if c else "" for c in all_rows[header_row_idx+1]]
            amt_candidates  = [j for j,c in enumerate(sub_row) if c == "금액"]
            if len(amt_candidates) >= 1: amount_col = amt_candidates[0]
            if len(amt_candidates) >= 3: labor_col  = amt_candidates[2]

        # ── 데이터 시작 행 결정 ───────────────────────────────
        data_start = (header_row_idx + 2) if header_row_idx is not None else 3

        results = []
        for row in all_rows[data_start:]:
            if not row or len(row) <= name_col:
                continue

            name = str(row[name_col]).strip() if row[name_col] else ""
            if not name or name == "None":
                continue

            # 빈 행·합계 행 제외
            if name in ["합계","소계","계","None",""]:
                continue

            # 키워드 매핑
            group = map_group_detail(name)

            # 수량
            try:    qty = float(row[qty_col]) if qty_col < len(row) and row[qty_col] else None
            except: qty = None

            # 단위
            unit = str(row[unit_col]).strip() if unit_col < len(row) and row[unit_col] else ""

            # 금액
            try:    amount = float(row[amount_col]) if amount_col < len(row) and row[amount_col] else None
            except: amount = None

            # 노무비
            try:    labor = float(row[labor_col]) if labor_col < len(row) and row[labor_col] else None
            except: labor = None

            # 규격
            spec = str(row[1]).strip() if len(row) > 1 and row[1] else ""

            # 야간 여부
            is_night = "-야간" in name

            results.append({
                "group":    group,
                "name":     name,
                "spec":     spec,
                "qty":      qty,
                "unit":     unit,
                "amount":   amount,
                "labor":    labor,
                "is_night": is_night,
            })

        wb.close()
        return results, target_sheet, {
            "header_row": header_row_idx,
            "name_col":   name_col,
            "qty_col":    qty_col,
            "unit_col":   unit_col,
            "amount_col": amount_col,
            "labor_col":  labor_col,
            "data_start": data_start,
        }

    # ── 파일 업로드 ───────────────────────────────────────────
    uploaded = st.file_uploader("내역서 엑셀 파일 업로드 (.xlsx)", type=["xlsx","xls"])

    if uploaded:
        try:
            with st.spinner("파싱 중..."):
                all_rows, sheet_name, col_info = parse_by_keyword(uploaded)

            # 기타 제외하고 인식된 것만
            matched   = [r for r in all_rows if r["group"] != "기타" and r["qty"] is not None]
            unmatched = [r for r in all_rows if r["group"] == "기타" and r["qty"] is not None]

            st.success(f"✅ 시트 **{sheet_name}** 파싱 완료 | 인식 **{len(matched)}건** | 미인식 **{len(unmatched)}건**")

            # 컬럼 탐색 결과 표시
            with st.expander("🔧 컬럼 탐색 결과 (문제 있으면 확인)"):
                st.json(col_info)

            st.markdown("---")

            # ── 인식된 항목 ───────────────────────────────────
            if matched:
                df_matched = pd.DataFrame(matched)
                df_matched["금액(억원)"]  = (df_matched["amount"].fillna(0)/1e8).round(2)
                df_matched["노무비(억원)"] = (df_matched["labor"].fillna(0)/1e8).round(2)
                df_matched["주야간"]       = df_matched["is_night"].map({True:"🌙야간",False:"☀️주간"})
                df_matched = df_matched.sort_values("금액(억원)", ascending=False).reset_index(drop=True)

                # 요약 카드
                ca,cb,cc,cd = st.columns(4)
                ca.metric("인식된 공종",  f"{len(matched)}건")
                cb.metric("총 금액",      f"{df_matched['금액(억원)'].sum():.1f}억")
                cc.metric("총 노무비",    f"{df_matched['노무비(억원)'].sum():.1f}억")
                cd.metric("야간공종",     f"{df_matched['is_night'].sum()}건")

                st.markdown("#### ✅ 인식된 공종 목록")

                # 공종그룹 필터
                all_groups = sorted(df_matched["group"].unique().tolist())
                sel_groups = st.multiselect("공종그룹 필터", all_groups, default=all_groups, key="tab2_filter")
                filtered_matched = df_matched[df_matched["group"].isin(sel_groups)]

                show_df = filtered_matched[["group","name","spec","qty","unit","금액(억원)","노무비(억원)","주야간"]].copy()
                show_df.columns = ["공종그룹","공종명","규격","수량","단위","금액(억원)","노무비(억원)","주야간"]

                # 상위 10개 강조
                top10 = set(filtered_matched.nlargest(10,"금액(억원)").index)
                def hl_matched(row):
                    if row.name in top10:
                        return ["background-color:#3a3000;color:#FFD700"]*len(row)
                    return [""]*len(row)

                st.dataframe(
                    show_df.style.apply(hl_matched, axis=1),
                    hide_index=True, use_container_width=True, height=400
                )

            # ── 미인식 항목 수동 매핑 ─────────────────────────
            if unmatched:
                st.markdown("---")
                st.markdown(f"#### ⚠️ 미인식 항목 ({len(unmatched)}건) — 수동 선택")
                st.caption("아래 항목은 키워드로 매핑되지 않았습니다. 공종을 직접 선택해주세요.")

                공종목록 = ["(선택안함)"] + list(KEYWORD_MAP_DETAIL.keys()) + ["기타"]
                manual_mapped = []

                # 최대 30개만 표시
                for idx, item in enumerate(unmatched[:30]):
                    ca, cb, cc, cd, ce = st.columns([3,1,1,1,2])
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
                    st.info(f"수동 매핑 {len(manual_mapped)}건 추가됨")

            # ── 공기산정 적용 ─────────────────────────────────
            st.markdown("---")
            if matched and st.button("✅ 인식 물량을 공기산정에 적용", type="primary"):
                df_apply = pd.DataFrame(matched)

                # 그룹별 물량 합산
                grp_qty = df_apply.groupby("group")["qty"].sum()

                # session_state에 직접 저장 (widget key 우회)
                st.session_state["_q_준비"]     = float(grp_qty.get("준비공",   5.0))
                st.session_state["_q_터파기"]   = float(grp_qty.get("굴착공",   350.0))
                st.session_state["_q_관부설"]   = float(grp_qty.get("관부설공", 120.0))
                st.session_state["_q_되메우기"] = float(grp_qty.get("되메우기", 180.0))
                st.session_state["_q_포장"]     = float(grp_qty.get("포장복구", 60.0))

                st.success(f"""
                ✅ 공기산정 탭에 아래 물량이 적용됩니다.
                - 준비공: {grp_qty.get('준비공',0):.0f}
                - 굴착공: {grp_qty.get('굴착공',0):.0f} m³
                - 관부설공: {grp_qty.get('관부설공',0):.0f} m
                - 되메우기: {grp_qty.get('되메우기',0):.0f} m³
                - 포장복구: {grp_qty.get('포장복구',0):.0f} m²
                """)

        except Exception as e:
            st.error(f"파싱 오류: {e}")
            st.markdown("---")
            st.markdown("**🔍 파일 구조 확인 (첫 4행)**")
            try:
                import openpyxl
                wb2 = openpyxl.load_workbook(uploaded, read_only=True, data_only=True)
                ws2 = wb2[wb2.sheetnames[0]]
                preview = []
                for row in ws2.iter_rows(min_row=1, max_row=4, values_only=True):
                    preview.append([str(c)[:15] if c is not None else "" for c in list(row)[:15]])
                wb2.close()
                prev_df = pd.DataFrame(preview, index=["1행","2행","3행","4행"])
                prev_df.columns = [f"col{i}" for i in range(len(prev_df.columns))]
                st.dataframe(prev_df, use_container_width=True)
                st.info("위 구조를 캡처해서 알려주시면 컬럼 인덱스를 맞춰드릴게요.")
            except Exception as e2:
                st.error(f"미리보기 실패: {e2}")
    else:
        st.info("내역서 엑셀 파일을 업로드해주세요.")
        st.markdown("""
        **지원 형식:**
        - 공종명 컬럼이 있는 모든 내역서 엑셀
        - 컬럼명 자동 탐색 (공종명/품명/공종/작업명)
        - 키워드 기반 자동 매핑 (터파기→굴착공, 관부설→관부설공 등)
        - 미인식 항목은 수동으로 공종 선택 가능
        """)

# ═══════════════════════════════════════════════════════════════
# TAB 3: 주요공종 분석
# ═══════════════════════════════════════════════════════════════
with tab3:
    df_mw = pd.DataFrame(MAJOR_WORKS)
    df_mw["labor_ratio"] = df_mw["labor"] / df_mw["amount"]

    # 요약 카드
    total_amount = df_mw["amount"].sum()
    total_labor  = df_mw["labor"].sum()
    night_count  = df_mw["night"].sum()
    ca,cb,cc,cd = st.columns(4)
    ca.metric("주요공정 총계",   f"{len(df_mw)}건")
    cb.metric("총 금액",         fmt_억(total_amount))
    cc.metric("총 노무비",       fmt_억(total_labor))
    cd.metric("야간공종",        f"{night_count}건")

    st.markdown("---")

    # 3개 컬럼 레이아웃
    left, mid, right = st.columns([1,3,1.5])

    # ── 좌측: 필터 패널 ───────────────────────────────────────
    with left:
        st.markdown("#### 🔍 필터")
        show_day   = st.checkbox("주간공종", value=True)
        show_night = st.checkbox("야간공종", value=True)
        st.markdown("**공종그룹**")
        all_groups = df_mw["group"].unique().tolist()

        if st.button("전체선택"):
            for g in all_groups: st.session_state[f"grp_{g}"] = True
        if st.button("전체해제"):
            for g in all_groups: st.session_state[f"grp_{g}"] = False

        selected_groups = []
        for g in all_groups:
            if g not in st.session_state: st.session_state[f"grp_{g}"] = True
            checked = st.checkbox(g, value=st.session_state.get(f"grp_{g}", True), key=f"grp_{g}")
            if checked: selected_groups.append(g)

        search = st.text_input("공종명 검색", placeholder="키워드 입력...")

    # ── 필터 적용 ─────────────────────────────────────────────
    filtered = df_mw.copy()
    if not show_day:   filtered = filtered[filtered["night"]==True]
    if not show_night: filtered = filtered[filtered["night"]==False]
    filtered = filtered[filtered["group"].isin(selected_groups)]
    if search: filtered = filtered[filtered["name"].str.contains(search, na=False)]

    # ── 중앙: 주요공종 테이블 ─────────────────────────────────
    with mid:
        st.markdown("#### 📋 주요공종 테이블")

        # 정렬
        sort_col = st.selectbox("정렬 기준", ["금액(억원)","노무비(억원)","수량"], index=0)

        display_df = filtered.copy()
        display_df["금액(억원)"]  = (display_df["amount"]/1e8).round(1)
        display_df["노무비(억원)"]= (display_df["labor"]/1e8).round(1)
        display_df["주야간"]      = display_df["night"].map({True:"🌙야간",False:"☀️주간"})
        display_df["노무집약"]    = display_df["labor_ratio"].apply(lambda x: "🔥노무집약" if x>=0.8 else "")

        sort_map = {"금액(억원)":"금액(억원)","노무비(억원)":"노무비(억원)","수량":"qty"}
        display_df = display_df.sort_values(sort_map[sort_col], ascending=False).reset_index(drop=True)

        show_df = display_df[["no","group","name","spec","qty","unit","금액(억원)","노무비(억원)","주야간","노무집약"]].copy()
        show_df.columns = ["No","공종그룹","공종명","규격","수량","단위","금액(억원)","노무비(억원)","주야간","노무집약"]

        # 금액 상위 10개 강조
        top10_idx = set(display_df.nlargest(10,"금액(억원)").index)

        def highlight_rows(row):
            idx = row.name
            if idx in top10_idx:
                return ["background-color:#3a3000;color:#FFD700"] * len(row)
            return [""] * len(row)

        # 페이지네이션
        PAGE_SIZE = 30
        total_pages = max(1, math.ceil(len(show_df)/PAGE_SIZE))
        page = st.number_input("페이지", min_value=1, max_value=total_pages, value=1, step=1)
        paged_df = show_df.iloc[(page-1)*PAGE_SIZE : page*PAGE_SIZE]

        st.dataframe(
            paged_df.style.apply(highlight_rows, axis=1),
            hide_index=True, use_container_width=True, height=500
        )
        st.caption(f"총 {len(show_df)}건 | {page}/{total_pages} 페이지 | 🟡 금액 상위 10개 강조")

    # ── 우측: CP 후보 분석 + 도넛차트 ────────────────────────
    with right:
        st.markdown("#### 🥧 공종그룹별 금액 비중")
        grp_sum = df_mw.groupby("group")["amount"].sum().reset_index()
        fig_donut = go.Figure(go.Pie(
            labels=grp_sum["group"],
            values=grp_sum["amount"],
            hole=0.5,
            textinfo="label+percent",
            textfont_size=10,
        ))
        fig_donut.update_layout(height=280, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
        st.plotly_chart(fig_donut, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 🔴 크리티컬패스 후보")

        # 기준1: 노무비 상위 5
        top5_labor = df_mw.nlargest(5,"labor")[["no","group","name","labor"]]

        st.markdown("**기준1: 노무비 상위 5개**")
        for _,r in top5_labor.iterrows():
            st.markdown(f"- `{r['no']}` {r['name'][:18]}… **{fmt_억(r['labor'])}**")

        st.markdown("**기준2: 필수 선후행 순서**")
        cp_order = ["굴착공","관부설공","맨홀공","되메우기공","포장복구공"]
        for i,g in enumerate(cp_order):
            arrow = "→ " if i>0 else ""
            st.markdown(f"{arrow}**{g}**")

        st.markdown("---")
        st.markdown("**예상 공기 계산**")
        cp_groups = df_mw[df_mw["group"].isin(["굴착공","관부설공","맨홀공"])].copy()
        for _,r in cp_groups.iterrows():
            조수 = st.number_input(f"{r['name'][:12]}… 조수(명)", min_value=1, max_value=30, value=4, key=f"cp_{r['no']}")
            md_est = r["labor"]/180000  # 일노무단가 가정
            days_est = math.ceil(md_est/조수)
            st.caption(f"  예상 공기: 약 {days_est}일")

        if st.button("📋 공기산정 탭으로 이동"):
            st.info("공기산정 탭을 클릭해서 이동해주세요.")

# ═══════════════════════════════════════════════════════════════
# TAB 4: 비작업일수 계산기
# ═══════════════════════════════════════════════════════════════
with tab4:
    st.subheader("비작업일수 계산기 (가이드라인 기준)")
    col1,col2 = st.columns(2)
    with col1:
        start_year  = st.selectbox("공사 시작 연도", [2024,2025,2026], index=1)
        start_month = st.selectbox("공사 시작 월", list(range(1,13)), index=2, format_func=lambda x:f"{x}월")
        duration_months = st.number_input("공사 기간 (개월)", min_value=1, max_value=60, value=6)
        city = st.selectbox("공사 지역", list(CITY_CORRECTION.keys()))
    with col2:
        st.markdown("**기상 조건**")
        use_rain = st.checkbox("강우 (5mm 이상)", value=True)
        use_cold = st.checkbox("동절기 (0℃ 이하)", value=True)
        use_heat = st.checkbox("혹서기 (35℃ 이상)", value=False)
        use_wind = st.checkbox("강풍 (15m/s 이상)", value=False)
        prep_days    = st.number_input("준비기간 (일)", value=60, min_value=0)
        cleanup_days = st.number_input("정리기간 (일)", value=30, min_value=0)

    st.markdown("---")
    corr = CITY_CORRECTION.get(city,1.0)
    rows=[]; total_applied=0

    for i in range(int(duration_months)):
        m=((start_month-1+i)%12)+1
        A=0.0
        if use_rain: A+=RAIN_DAYS_SEOUL[m]*corr
        if use_cold: A+=COLD_DAYS_SEOUL[m]*corr
        if use_heat: A+=HEAT_DAYS_SEOUL[m]*corr
        if use_wind: A+=WIND_DAYS_SEOUL[m]*corr
        B=HOLIDAYS_2025.get(m,0)
        C=round(A*B/30,0)
        non_work=A+B-C
        applied=max(8.0,non_work)
        total_applied+=applied
        rows.append({"월":f"{m}월","기상비작업일(A)":round(A,1),"법정공휴일(B)":B,
                     "중복일수(C)":int(C),"비작업일수":round(non_work,1),"적용일수":round(applied,1)})

    nw_df=pd.DataFrame(rows)
    total_row=pd.DataFrame([{"월":"합계","기상비작업일(A)":round(nw_df["기상비작업일(A)"].sum(),1),
                              "법정공휴일(B)":nw_df["법정공휴일(B)"].sum(),"중복일수(C)":nw_df["중복일수(C)"].sum(),
                              "비작업일수":round(nw_df["비작업일수"].sum(),1),"적용일수":round(total_applied,1)}])
    st.dataframe(pd.concat([nw_df,total_row],ignore_index=True), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("총 공사기간 산출")
    total_duration = d_total + int(total_applied) + prep_days + cleanup_days
    ca,cb,cc,cd,ce = st.columns(5)
    ca.metric("순 작업일수", f"{d_total}일")
    cb.metric("비작업일수",  f"{int(total_applied)}일")
    cc.metric("준비기간",    f"{prep_days}일")
    cd.metric("정리기간",    f"{cleanup_days}일")
    ce.metric("총 공사기간", f"{total_duration}일", delta=f"약 {round(total_duration/30,1)}개월")

    st.info(f"""
    **총 공사기간 = {d_total}일(작업) + {int(total_applied)}일(비작업) + {prep_days}일(준비) + {cleanup_days}일(정리) = {total_duration}일 (약 {round(total_duration/30,1)}개월)**
    """)