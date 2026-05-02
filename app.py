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
GUIDELINE_APPENDIX = {
    "아스팔트포장 절단": {"daily": 1000, "unit": "m"},
    "아스팔트포장깨기 (B.H0.4㎥)": {"daily": 515, "unit": "㎡"},
    "아스팔트포장깨기 (B.H0.7㎥)": {"daily": 1047, "unit": "㎡"},
    "터파기(토사:육상) B/H 0.4㎥": {"daily": 260, "unit": "㎥"},
    "터파기(토사:육상) B/H 0.7㎥": {"daily": 530, "unit": "㎥"},
    "터파기(암:육상) B/H 0.4㎥": {"daily": 130, "unit": "㎥"},
    "터파기(암:육상) B/H 0.7㎥": {"daily": 265, "unit": "㎥"},
    "되메우기(진동롤러) 2.5ton": {"daily": 600, "unit": "㎥"},
    "되메우기(진동롤러) 4.0ton": {"daily": 950, "unit": "㎥"},
    "관부설(D200)": {"daily": 5, "unit": "본/일"},
    "관부설(D300)": {"daily": 4, "unit": "본/일"},
    "관부설(D450)": {"daily": 3, "unit": "본/일"},
    "관부설(D600)": {"daily": 2.5, "unit": "본/일"},
    "관부설(D800)": {"daily": 2, "unit": "본/일"},
    "관부설(D1000)": {"daily": 1.5, "unit": "본/일"},
    "관부설(D1200)": {"daily": 1.2, "unit": "본/일"},
    "원형맨홀 Φ1200": {"daily": 2.5, "unit": "개소/일"},
    "원형맨홀 Φ1500": {"daily": 2.5, "unit": "개소/일"},
    "각형맨홀 1800×2400": {"daily": 1.5, "unit": "개소/일"},
    "우수받이": {"daily": 5, "unit": "개소/일"},
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
    1. 가이드라인 부록 1일 작업량
    2. 표준품셈 Man-day
    3. 단가산출근거 Q값
    """
    if not qty or qty <= 0:
        return 0, "-", "-"

    # 1순위: 가이드라인 부록
    try:
        for key, val in GUIDELINE_APPENDIX.items():
            if key in name or key in spec:
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
        
        # 관부설 직경별
        if any(kw in name for kw in ["관 부설","관부설","고강성PVC","PE다중벽","이중벽관"]):
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
            for cached_name, info in cache.items():
                if cached_name in name or name in cached_name:
                    hourly_val = info.get("hourly", 0)
                    unit = info.get("unit", "")
                    if hourly_val > 0:
                        daily_val = hourly_val * 8
                        days = math.ceil(qty / (daily_val * crews))
                        return days, f"{daily_val:.1f}{unit.replace('/Hr','/일')}×{crews}조", "단가산출근거"
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
        
        gong_jong = str(row[0]).strip() if row[0] else ""
        name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        spec = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        qty = row[3] if len(row) > 3 else 0
        unit = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        
        if not name or any(skip in name for skip in SKIP_NAMES):
            continue
        
        try:
            qty = float(qty) if qty else 0
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
            "gong_jong": gong_jong,
            "group": group,
            "name": name,
            "spec": detail_spec,
            "qty": qty,
            "unit": unit,
            "amount": row[5] if len(row) > 5 else 0,
            "labor": row[6] if len(row) > 6 else 0,
        })
    
    # 중복 제거
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
                
                # 단가산출근거 캐싱
                dangagun_cache = {}
                if '단가산출근거' in wb.sheetnames:
                    ws_danga = wb['단가산출근거']
                    current_item = None
                    for row in ws_danga.iter_rows(min_row=1, values_only=True):
                        row_text = " ".join([str(c) for c in row if c])
                        if row[1] and "/" in str(row[1]):
                            item_text = str(row[1]).strip()
                            if "/" in item_text:
                                current_item = item_text.split("/")[0].strip()
                        if current_item and "Q =" in row_text:
                            match = re.search(r'=\s*([\d.]+)\s*([^\s]+/HR)', row_text, re.IGNORECASE)
                            if match:
                                hourly_val = float(match.group(1))
                                unit = match.group(2).replace("HR", "Hr")
                                dangagun_cache[current_item] = {"hourly": hourly_val, "unit": unit}
                
                st.session_state["dangagun_cache"] = dangagun_cache
                
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
                    
                    if re.match(r'^\d+\)$', gong_jong) and current_category:
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
                    st.info(f"✅ {len(hierarchy)}개 주공종 인식")
                    
                    # 투입조수 설정 (주공종만, 중복 제거)
                    st.markdown("### 🔧 주공종 투입조수 설정")
                    
                    if 'crew_by_main' not in st.session_state:
                        st.session_state['crew_by_main'] = {}
                    
                    # 같은 이름 중복 제거
                    unique_main_cats = {}
                    for cat in hierarchy:
                        cat_name = cat['name']
                        if cat_name not in unique_main_cats:
                            unique_main_cats[cat_name] = cat
                    
                    crew_settings = {}
                    cols = st.columns(min(len(unique_main_cats), 4))
                    
                    for idx, (cat_name, cat) in enumerate(unique_main_cats.items()):
                        default_crew = st.session_state['crew_by_main'].get(cat_name, 3)
                        
                        with cols[idx % len(cols)]:
                            crew_val = st.number_input(
                                f"{cat_name}(조)",
                                min_value=1,
                                max_value=30,
                                value=default_crew,
                                key=f"crew_main_{cat_name.replace(' ', '_')}"
                            )
                            crew_settings[cat_name] = crew_val
                            st.session_state['crew_by_main'][cat_name] = crew_val
                    
                    st.markdown("---")
                    st.markdown("### 📊 공종별 작업일수 계산 결과")
                    
                    result_rows = []
                    
                    for cat in hierarchy:
                        cat_name = cat['name']
                        cat_level = cat['level']
                        cat_crew = crew_settings[cat_name]
                        
                        # 모든 항목 수집 (직접 항목 + 하위 카테고리 항목)
                        all_cat_items = list(cat.get('items', []))
                        for sub in cat.get('sub_categories', []):
                            all_cat_items.extend(sub.get('items', []))
                        
                        # 총 작업일수 계산
                        cat_total_days = sum(
                            calc_days_priority(item['name'], item.get('spec', ''), item.get('qty', 0), cat_crew)[0]
                            for item in all_cat_items
                        )
                        
                        if all_cat_items:
                            result_rows.append({
                                "공종": f"{cat_level} {cat_name}",
                                "물량": f"{len(all_cat_items)}개 항목",
                                "투입조수": f"{cat_crew}조",
                                "작업일수(일)": int(cat_total_days),
                            })
                    
                    # 결과 테이블
                    result_rows_sorted = sorted(result_rows, key=lambda x: x["작업일수(일)"], reverse=True)
                    max_days = max((r["작업일수(일)"] for r in result_rows_sorted), default=0)
                    
                    total_row = {
                        "공종": "[ 합  계 ]",
                        "물량": "-",
                        "투입조수": "-",
                        "작업일수(일)": max_days,
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
                    
                    ca, cb = st.columns(2)
                    ca.metric("🔴 주공정 (최장)", f"{max_days}일")
                    cb.metric("총 공종", f"{len(result_rows)}개")
                    
                    # session_state 저장
                    st.session_state["work_result"] = {
                        "rows": result_rows,
                        "hierarchy": hierarchy,
                        "crew_settings": crew_settings,
                    }
                    st.session_state["total_work_days"] = int(max_days)
                    
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
    st.subheader("공기산정")
    if "work_result" in st.session_state:
        st.success("✅ TAB 2에서 계산 완료!")
        st.metric("총 순작업일수", f"{st.session_state.get('total_work_days', 0)}일")
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
        df_cp = pd.DataFrame(result_rows)
        df_cp = df_cp[df_cp["작업일수(일)"] > 0].copy()
        df_cp = df_cp.sort_values("작업일수(일)", ascending=False).reset_index(drop=True)
        df_cp.index += 1
        max_days = df_cp["작업일수(일)"].max() if len(df_cp) > 0 else 0

        def hl_cp(row):
            if row["작업일수(일)"] == max_days:
                return ["background-color:#3d0000;color:#ff6b6b"] * len(row)
            return [""] * len(row)

        st.dataframe(df_cp.style.apply(hl_cp, axis=1), hide_index=False, use_container_width=True)
        
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
# TAB 5
# ══════════════════════════════════════════════════════════════
with tab5:
    st.subheader("공기산정 보고서")
    if "work_result" not in st.session_state:
        st.warning("TAB 2에서 엑셀을 먼저 업로드해주세요.")
    else:
        st.info("📄 보고서 생성 기능은 추후 업데이트 예정입니다.")