import streamlit as st

# ── 비밀번호 로그인 ───────────────────────────────────────────
def check_password():
    if st.session_state.get("authenticated"):
        return True

    st.title("상하수도 관로공사 공기산정 시스템")
    st.markdown("---")
    st.subheader("로그인")

    pw = st.text_input("비밀번호를 입력하세요", type="password")
    if st.button("로그인"):
        if pw == "1234":  # 나중에 변경하세요
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    return False

if not check_password():
    st.stop()
import pandas as pd
import math
import holidays
from datetime import date, timedelta

st.set_page_config(page_title="상하수도 공기산정", layout="wide")

st.title("상하수도 관로공사 공기산정 시스템")
st.markdown("---")

# ── 표준품셈 딕셔너리 ─────────────────────────────────────────
LABOR_RATES = {
    "준비공": {
        "규준틀 설치": {"unit": "개소", "보통인부": 0.5},
    },
    "굴착공": {
        "터파기(기계)": {"unit": "m³", "특수작업원": 0.02, "보통인부": 0.03},
        "버력운반(기계)": {"unit": "m³", "특수작업원": 0.01, "보통인부": 0.02},
    },
    "관부설공": {
        "관 부설·접합": {
            "200mm": {"unit": "m", "배관공": 0.45, "보통인부": 0.35},
            "300mm": {"unit": "m", "배관공": 0.65, "보통인부": 0.50},
        },
        "수압시험": {
            "200mm": {"unit": "m", "배관공": 0.02, "보통인부": 0.02},
            "300mm": {"unit": "m", "배관공": 0.03, "보통인부": 0.02},
        },
    },
    "되메우기공": {
        "모래기초 포설": {"unit": "m³", "보통인부": 0.35},
        "되메우기(기계다짐)": {"unit": "m³", "특수작업원": 0.02, "보통인부": 0.10},
    },
    "포장복구공": {
        "보조기층 포설": {"unit": "m²", "특수작업원": 0.008, "보통인부": 0.020},
        "아스콘포장":   {"unit": "m²", "특수작업원": 0.010, "보통인부": 0.025},
    },
}

# ── 기상청 통계 기반 월별 평균 우천일수 ──────────────────────
RAIN_DAYS_PER_MONTH = {
    1: 2, 2: 2, 3: 3, 4: 4,
    5: 5, 6: 7, 7: 11, 8: 10,
    9: 6, 10: 3, 11: 3, 12: 2
}

# ── 비작업일수 계산 함수 ──────────────────────────────────────
def calc_non_working_days(start_date, work_days):
    kr_holidays = holidays.KR()
    current = start_date
    worked = 0
    non_working = {"일요일": 0, "공휴일": 0, "기상장애": 0}

    while worked < work_days:
        if current.weekday() == 6:
            non_working["일요일"] += 1
            current += timedelta(days=1)
            continue
        if current in kr_holidays:
            non_working["공휴일"] += 1
            current += timedelta(days=1)
            continue
        rain_days_this_month = RAIN_DAYS_PER_MONTH[current.month]
        if current.day % 30 < rain_days_this_month:
            non_working["기상장애"] += 1
            current += timedelta(days=1)
            continue
        worked += 1
        current += timedelta(days=1)

    end_date = current - timedelta(days=1)
    calendar_days = (end_date - start_date).days + 1
    return {
        "종료일": end_date,
        "달력일수": calendar_days,
        "비작업일수": sum(non_working.values()),
        "상세": non_working
    }

# ── Man-day 계산 함수 ─────────────────────────────────────────
def calc_manday(rates, quantity):
    total = 0.0
    for k, v in rates.items():
        if k != "unit":
            total += v * quantity
    return round(total, 2)

def to_days(manday, workers):
    if workers <= 0:
        return 0
    return math.ceil(manday / workers)

# ════════════════════════════════════════════════════════════════
# 사이드바
# ════════════════════════════════════════════════════════════════
st.sidebar.header("기본 설정")
pipe_dia   = st.sidebar.selectbox("관경", ["200mm", "300mm"])
start_date = st.sidebar.date_input("착공 예정일", value=date.today())

st.sidebar.markdown("---")
st.sidebar.header("공종별 투입 인원 (명/일)")
st.sidebar.caption("각 공종에 투입되는 하루 인원수를 입력하세요.")

w_준비     = st.sidebar.number_input("준비공",     min_value=1, max_value=50, value=4)
w_굴착     = st.sidebar.number_input("굴착공",     min_value=1, max_value=50, value=6)
w_관부설   = st.sidebar.number_input("관부설공",   min_value=1, max_value=50, value=4)
w_되메우기 = st.sidebar.number_input("되메우기공", min_value=1, max_value=50, value=4)
w_포장     = st.sidebar.number_input("포장복구공", min_value=1, max_value=50, value=4)

st.sidebar.markdown("---")
st.sidebar.info(
    f"관경: **{pipe_dia}**\n\n"
    f"착공일: **{start_date}**\n\n"
    f"준비공: **{w_준비}명** | 굴착공: **{w_굴착}명**\n\n"
    f"관부설공: **{w_관부설}명** | 되메우기: **{w_되메우기}명**\n\n"
    f"포장복구: **{w_포장}명**"
)

# ════════════════════════════════════════════════════════════════
# 메인: 물량 입력
# ════════════════════════════════════════════════════════════════
st.subheader("공종별 물량 입력")
st.caption("엑셀 내역서 보면서 아래 5개 숫자만 입력하세요.")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**준비공**")
    q_준비 = st.number_input("규준틀 설치 (개소)", min_value=0.0, value=5.0, step=1.0)
    st.markdown("**굴착공**")
    q_터파기 = st.number_input("터파기 물량 (m³)", min_value=0.0, value=350.0, step=10.0)
    st.markdown("**관부설공**")
    q_관부설 = st.number_input("관 부설 연장 (m)", min_value=0.0, value=120.0, step=10.0)

with col2:
    st.markdown("**되메우기공**")
    q_되메우기 = st.number_input("되메우기 물량 (m³)", min_value=0.0, value=180.0, step=10.0)
    st.markdown("**포장복구공**")
    q_포장 = st.number_input("포장 면적 (m²)", min_value=0.0, value=60.0, step=5.0)

st.markdown("---")

# ════════════════════════════════════════════════════════════════
# 계산
# ════════════════════════════════════════════════════════════════
md_준비     = calc_manday(LABOR_RATES["준비공"]["규준틀 설치"], q_준비)
md_굴착     = (
    calc_manday(LABOR_RATES["굴착공"]["터파기(기계)"], q_터파기) +
    calc_manday(LABOR_RATES["굴착공"]["버력운반(기계)"], q_터파기)
)
md_관부설   = (
    calc_manday(LABOR_RATES["관부설공"]["관 부설·접합"][pipe_dia], q_관부설) +
    calc_manday(LABOR_RATES["관부설공"]["수압시험"][pipe_dia], q_관부설)
)
md_되메우기 = (
    calc_manday(LABOR_RATES["되메우기공"]["모래기초 포설"], q_되메우기) +
    calc_manday(LABOR_RATES["되메우기공"]["되메우기(기계다짐)"], q_되메우기)
)
md_포장     = (
    calc_manday(LABOR_RATES["포장복구공"]["보조기층 포설"], q_포장) +
    calc_manday(LABOR_RATES["포장복구공"]["아스콘포장"], q_포장)
)

d_준비     = to_days(md_준비,     w_준비)
d_굴착     = to_days(md_굴착,     w_굴착)
d_관부설   = to_days(md_관부설,   w_관부설)
d_되메우기 = to_days(md_되메우기, w_되메우기)
d_포장     = to_days(md_포장,     w_포장)
d_total    = d_준비 + d_굴착 + d_관부설 + d_되메우기 + d_포장

nw = calc_non_working_days(start_date, d_total)

# ════════════════════════════════════════════════════════════════
# 결과 출력
# ════════════════════════════════════════════════════════════════
st.subheader("공기산정 결과")

result_df = pd.DataFrame({
    "대공종":         ["준비공", "굴착공", "관부설공", "되메우기공", "포장복구공"],
    "투입인원 (명)":  [w_준비, w_굴착, w_관부설, w_되메우기, w_포장],
    "Man-day (인일)": [md_준비, md_굴착, md_관부설, md_되메우기, md_포장],
    "작업일수 (일)":  [d_준비, d_굴착, d_관부설, d_되메우기, d_포장],
    "크리티컬패스":   ["O", "O", "O", "O", "O"],
})

st.dataframe(result_df, hide_index=True, use_container_width=True)

st.markdown("---")
st.subheader("공기 요약")

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("순 작업일수", f"{d_total} 일")
col_b.metric("비작업일수",  f"{nw['비작업일수']} 일")
col_c.metric("달력 공기",   f"{nw['달력일수']} 일")
col_d.metric("준공 예정일", f"{nw['종료일'].strftime('%Y-%m-%d')}")

st.markdown("---")
st.subheader("비작업일수 상세")

nw_df = pd.DataFrame({
    "구분":     ["일요일", "공휴일", "기상장애일", "합계"],
    "일수 (일)": [
        nw["상세"]["일요일"],
        nw["상세"]["공휴일"],
        nw["상세"]["기상장애"],
        nw["비작업일수"]
    ]
})

st.dataframe(nw_df, hide_index=True, use_container_width=True)
st.caption("기상장애일: 기상청 통계 기반 월별 평균 우천일수 적용 (서울 기준)")

# ── 조수 조정 시나리오 비교 ───────────────────────────────────
st.markdown("---")
st.subheader("조수 조정 시나리오 비교")
st.caption("현재 설정 기준으로 인원을 늘리거나 줄였을 때 공기 변화를 비교합니다.")

scenarios = []
for label, factor in [("절반 인원", 0.5), ("현재 인원", 1.0), ("1.5배 인원", 1.5), ("2배 인원", 2.0)]:
    sw = {
        "준비공":     max(1, round(w_준비     * factor)),
        "굴착공":     max(1, round(w_굴착     * factor)),
        "관부설공":   max(1, round(w_관부설   * factor)),
        "되메우기공": max(1, round(w_되메우기 * factor)),
        "포장복구공": max(1, round(w_포장     * factor)),
    }
    sd = (
        to_days(md_준비,     sw["준비공"]) +
        to_days(md_굴착,     sw["굴착공"]) +
        to_days(md_관부설,   sw["관부설공"]) +
        to_days(md_되메우기, sw["되메우기공"]) +
        to_days(md_포장,     sw["포장복구공"])
    )
    snw = calc_non_working_days(start_date, sd)
    scenarios.append({
        "시나리오":    label,
        "준비공 (명)":     sw["준비공"],
        "굴착공 (명)":     sw["굴착공"],
        "관부설공 (명)":   sw["관부설공"],
        "되메우기 (명)":   sw["되메우기공"],
        "포장복구 (명)":   sw["포장복구공"],
        "순작업일수 (일)": sd,
        "달력공기 (일)":   snw["달력일수"],
        "준공예정일":      snw["종료일"].strftime("%Y-%m-%d"),
    })

scenario_df = pd.DataFrame(scenarios)
st.dataframe(scenario_df, hide_index=True, use_container_width=True)
# ── 간트차트 ──────────────────────────────────────────────────
import plotly.figure_factory as ff
import plotly.express as px

st.markdown("---")
st.subheader("간트차트")

# 공종별 시작일/종료일 계산 (달력 기반)
def get_work_end_date(start, work_days):
    """작업일수만큼 진행했을 때 종료일 반환 (비작업일 제외)"""
    kr_holidays = holidays.KR()
    current = start
    worked = 0
    while worked < work_days:
        if current.weekday() == 6:
            current += timedelta(days=1)
            continue
        if current in kr_holidays:
            current += timedelta(days=1)
            continue
        rain_days_this_month = RAIN_DAYS_PER_MONTH[current.month]
        if current.day % 30 < rain_days_this_month:
            current += timedelta(days=1)
            continue
        worked += 1
        current += timedelta(days=1)
    return current - timedelta(days=1)

# 각 공종 시작일/종료일 순차 계산
s1 = start_date
e1 = get_work_end_date(s1, d_준비)

s2 = e1 + timedelta(days=1)
e2 = get_work_end_date(s2, d_굴착)

s3 = e2 + timedelta(days=1)
e3 = get_work_end_date(s3, d_관부설)

s4 = e3 + timedelta(days=1)
e4 = get_work_end_date(s4, d_되메우기)

s5 = e4 + timedelta(days=1)
e5 = get_work_end_date(s5, d_포장)

# 간트 데이터
gantt_data = [
    dict(Task="준비공",     Start=str(s1), Finish=str(e1), 인원=f"{w_준비}명",     작업일=f"{d_준비}일"),
    dict(Task="굴착공",     Start=str(s2), Finish=str(e2), 인원=f"{w_굴착}명",     작업일=f"{d_굴착}일"),
    dict(Task="관부설공",   Start=str(s3), Finish=str(e3), 인원=f"{w_관부설}명",   작업일=f"{d_관부설}일"),
    dict(Task="되메우기공", Start=str(s4), Finish=str(e4), 인원=f"{w_되메우기}명", 작업일=f"{d_되메우기}일"),
    dict(Task="포장복구공", Start=str(s5), Finish=str(e5), 인원=f"{w_포장}명",     작업일=f"{d_포장}일"),
]

colors = {
    "준비공":     "#5DCAA5",
    "굴착공":     "#378ADD",
    "관부설공":   "#D85A30",
    "되메우기공": "#EF9F27",
    "포장복구공": "#7F77DD",
}

fig = px.timeline(
    pd.DataFrame(gantt_data),
    x_start="Start",
    x_end="Finish",
    y="Task",
    color="Task",
    color_discrete_map=colors,
    hover_data={"인원": True, "작업일": True, "Task": False},
    labels={"Task": "공종"},
)

fig.update_yaxes(autorange="reversed")
fig.update_layout(
    height=350,
    showlegend=False,
    xaxis_title="날짜",
    yaxis_title="",
    margin=dict(l=10, r=10, t=30, b=10),
    xaxis=dict(
        tickformat="%m/%d",
        dtick="M1",
        ticklabelmode="period",
    ),
)

# 크리티컬 패스 표시 (모든 공종이 크리티컬)
fig.update_traces(
    marker_line_color="red",
    marker_line_width=2,
)

st.plotly_chart(fig, use_container_width=True)
st.caption("빨간 테두리 = 크리티컬 패스 공종 | 모든 공종이 순차 연결되어 전체가 크리티컬 패스입니다.")

# ── 공종별 일정 상세 ──────────────────────────────────────────
st.subheader("공종별 일정 상세")

schedule_df = pd.DataFrame({
    "공종":       ["준비공", "굴착공", "관부설공", "되메우기공", "포장복구공"],
    "착수일":     [str(s1), str(s2), str(s3), str(s4), str(s5)],
    "완료일":     [str(e1), str(e2), str(e3), str(e4), str(e5)],
    "투입인원":   [f"{w_준비}명", f"{w_굴착}명", f"{w_관부설}명", f"{w_되메우기}명", f"{w_포장}명"],
    "작업일수":   [f"{d_준비}일", f"{d_굴착}일", f"{d_관부설}일", f"{d_되메우기}일", f"{d_포장}일"],
})

st.dataframe(schedule_df, hide_index=True, use_container_width=True)
