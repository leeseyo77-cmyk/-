# daily_work_rates.py
# 출처: 적정 공사기간 확보 가이드라인 부록1,2 (국토교통부, 2025.01.)
# 2025년 건설공사 표준품셈 3-2-4 터파기(기계) 기준
import math

# ══════════════════════════════════════════════════════════════
# 1. 터파기 1일 작업량 (굴착폭 × 토질 세분화)
# 기준: B/H 0.7㎥ 굴착기 1대, 8시간
# TypeⅠ: 일반, TypeⅡ: 도심지(지장물·가시설), TypeⅢ: 협소구간
# ══════════════════════════════════════════════════════════════
EXCAVATION_DAILY = {
    # (토질, 굴착폭) : 1일작업량(㎥)
    ("토사",   "B=1.5m미만"):    120,
    ("토사",   "B=1.5~2.5m"):   190,   # TypeⅢ
    ("토사",   "B=2.5~4.0m"):   300,   # TypeⅡ
    ("토사",   "B=4.0m이상"):   420,   # TypeⅡ
    ("토사",   "기본"):          300,   # 굴착폭 미명시 기본값

    ("용수토사","B=1.5m미만"):   90,    # TypeⅢ × 0.75
    ("용수토사","B=1.5~2.5m"):  143,   # TypeⅢ × 0.75
    ("용수토사","B=2.5~4.0m"):  225,   # TypeⅡ × 0.75
    ("용수토사","B=4.0m이상"):  315,   # TypeⅡ × 0.75
    ("용수토사","기본"):         225,

    ("혼합토사","B=2.5~4.0m"):  200,
    ("혼합토사","B=4.0m이상"):  280,
    ("혼합토사","기본"):         200,

    ("풍화암", "B=2.5~4.0m"):   35,
    ("풍화암", "B=4.0m이상"):   38,
    ("풍화암", "기본"):          35,

    ("연암",   "B=2.5~4.0m"):   28,
    ("연암",   "B=4.0m이상"):   30,
    ("연암",   "기본"):          28,

    ("보통암", "B=4.0m이상"):   19,
    ("보통암", "기본"):          19,

    ("경암",   "B=4.0m이상"):   14,
    ("경암",   "기본"):          14,
}

def parse_excavation_spec(name: str, spec: str) -> tuple:
    """
    공종명 + 규격에서 (토질, 굴착폭) 추출
    예) name="터파기(B=4.0m이상)", spec="(토사:기계90%+인력10%)"
        → ("토사", "B=4.0m이상")
    """
    combined = name + " " + spec

    # 토질 판별
    if "경암" in combined:
        soil = "경암"
    elif "보통암" in combined:
        soil = "보통암"
    elif "연암" in combined:
        soil = "연암"
    elif "풍화암" in combined:
        soil = "풍화암"
    elif "혼합" in combined or "자갈" in combined:
        soil = "혼합토사"
    elif "용수" in combined:
        soil = "용수토사"
    else:
        soil = "토사"

    # 굴착폭 판별
    if "1.5m미만" in combined or "1.5m이하" in combined:
        width = "B=1.5m미만"
    elif "1.5~2.5" in combined or "2.5m미만" in combined or "2.5이만" in combined:
        width = "B=1.5~2.5m"
    elif "2.5~4.0" in combined or "4.0m미만" in combined or "4.0이만" in combined:
        width = "B=2.5~4.0m"
    elif "4.0m이상" in combined or "4.0이상" in combined or "B=6.0" in combined:
        width = "B=4.0m이상"
    else:
        width = "기본"

    return soil, width

# ══════════════════════════════════════════════════════════════
# 2. 기타 공종 1일 작업량
# ══════════════════════════════════════════════════════════════
DAILY_WORK = {
    # ── 포장 깨기/절단 ────────────────────────────────────────
    "아스팔트포장절단":     {"daily":600,  "unit":"m",   "crews":5, "hours":8, "condition":"커터기"},
    "아스팔트포장깨기":     {"daily":54,   "unit":"㎥",  "crews":5, "hours":8, "condition":"B.H0.7㎥+대형브레이카"},
    "콘크리트포장절단":     {"daily":600,  "unit":"m",   "crews":5, "hours":8, "condition":"커터기"},
    "콘크리트포장깨기":     {"daily":54,   "unit":"㎥",  "crews":5, "hours":8, "condition":"B.H0.7㎥+대형브레이카"},

    # ── 되메우기·모래기초 ─────────────────────────────────────
    "되메우기_관상단_토사": {"daily":79,   "unit":"㎥",  "crews":5, "hours":8, "condition":"B/H+진동롤러"},
    "되메우기_관주위_토사": {"daily":42,   "unit":"㎥",  "crews":5, "hours":8, "condition":"B/H+램머"},
    "모래부설다짐":         {"daily":79,   "unit":"㎥",  "crews":5, "hours":8, "condition":"물다짐"},

    # ── 관 부설 (PE다중벽관/고강성PVC) ────────────────────────
    "PE관_D150":  {"daily":7,  "unit":"개소","crews":3,"hours":8,"condition":"D150mm×6.0m"},
    "PE관_D200":  {"daily":5,  "unit":"개소","crews":3,"hours":8,"condition":"D200mm×6.0m"},
    "PE관_D250":  {"daily":4,  "unit":"개소","crews":3,"hours":8,"condition":"D250mm×6.0m"},
    "PE관_D300":  {"daily":4,  "unit":"개소","crews":3,"hours":8,"condition":"D300mm×6.0m"},
    "PE관_D350":  {"daily":3,  "unit":"개소","crews":3,"hours":8,"condition":"D350mm×6.0m"},
    "PE관_D400":  {"daily":3,  "unit":"개소","crews":3,"hours":8,"condition":"D400mm×6.0m"},
    "PE관_D450":  {"daily":2,  "unit":"개소","crews":3,"hours":8,"condition":"D450mm×6.0m"},
    "PE관_D500":  {"daily":2,  "unit":"개소","crews":3,"hours":8,"condition":"D500mm×6.0m"},

    # ── 흄관/RC관 부설 ────────────────────────────────────────
    "흄관_D250":  {"daily":43, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D300":  {"daily":43, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D350":  {"daily":43, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D400":  {"daily":43, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D450":  {"daily":43, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D500":  {"daily":43, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D600":  {"daily":32, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D700":  {"daily":26, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D800":  {"daily":20, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D900":  {"daily":16, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D1000": {"daily":14, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},
    "흄관_D1200": {"daily":10, "unit":"m","crews":3,"hours":8,"condition":"소켓접합"},

    # ── 맨홀 설치 ─────────────────────────────────────────────
    "소형맨홀_D600":   {"daily":8.16,"unit":"개소","crews":5,"hours":8,"condition":"하부구체+상판"},
    "PC맨홀1호_D900":  {"daily":8.16,"unit":"개소","crews":3,"hours":8,"condition":"하부구체+상판"},
    "PC맨홀2호_D1200": {"daily":5.0, "unit":"개소","crews":3,"hours":8,"condition":"하부구체+상판"},
    "PC맨홀3호_D1500": {"daily":4.0, "unit":"개소","crews":3,"hours":8,"condition":"하부구체+상판"},

    # ── 배수설비 ──────────────────────────────────────────────
    "오수받이설치": {"daily":4, "unit":"개소","crews":3,"hours":8,"condition":"소형구조물"},
    "배수설비":     {"daily":4, "unit":"개소","crews":3,"hours":8,"condition":"연결관 포함"},

    # ── 포장복구 ──────────────────────────────────────────────
    "보조기층포설": {"daily":800,"unit":"㎡","crews":5,"hours":8,"condition":"기계포설"},
    "아스콘포장":   {"daily":600,"unit":"㎡","crews":5,"hours":8,"condition":"기계시공"},
    "콘크리트포장": {"daily":400,"unit":"㎡","crews":5,"hours":8,"condition":"기계시공"},

    # ── 가시설 ────────────────────────────────────────────────
    "가시설흙막이": {"daily":28, "unit":"m", "crews":5,"hours":8,"condition":"조립식 간이흙막이"},

    # ── 추진공 ────────────────────────────────────────────────
    "강관압입추진_D450": {"daily":8,"unit":"m","crews":1,"hours":8,"condition":"D450mm 토사"},
    "강관압입추진_D600": {"daily":6,"unit":"m","crews":1,"hours":8,"condition":"D600mm 토사"},
    "강관압입추진_D800": {"daily":5,"unit":"m","crews":1,"hours":8,"condition":"D800mm 토사"},
}

# ── 공종명 키워드 → DAILY_WORK 키 매핑 ───────────────────────
WORK_KEY_MAP = [
    # 포장 깨기/절단
    (["아스팔트포장절단","포장절단","포장 절단"], [], "아스팔트포장절단"),
    (["아스팔트포장깨기","포장깨기","포장 깨기"], [], "아스팔트포장깨기"),
    (["콘크리트포장절단"],                        [], "콘크리트포장절단"),
    (["콘크리트포장깨기"],                        [], "콘크리트포장깨기"),

    # 되메우기
    (["되메우기"], ["관주위","관 주위","모래"],    "되메우기_관주위_토사"),
    (["모래부설","모래기초","모래,관기초"],        [], "모래부설다짐"),
    (["되메우기"],                                [], "되메우기_관상단_토사"),

    # PE관/고강성PVC - 관경별
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D500","500mm","Φ500"], "PE관_D500"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D450","450mm","Φ450"], "PE관_D450"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D400","400mm","Φ400"], "PE관_D400"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D350","350mm","Φ350"], "PE관_D350"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D300","300mm","Φ300"], "PE관_D300"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D250","250mm","Φ250"], "PE관_D250"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D200","200mm","Φ200"], "PE관_D200"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], ["D150","150mm","Φ150"], "PE관_D150"),
    (["PE다중벽","이중벽","고강성PVC","PE관"], [],                      "PE관_D200"),

    # 흄관/RC관 - 관경별
    (["흄관","RC관","원심력"], ["D1200","1200mm"], "흄관_D1200"),
    (["흄관","RC관","원심력"], ["D1000","1000mm"], "흄관_D1000"),
    (["흄관","RC관","원심력"], ["D900","900mm"],   "흄관_D900"),
    (["흄관","RC관","원심력"], ["D800","800mm"],   "흄관_D800"),
    (["흄관","RC관","원심력"], ["D700","700mm"],   "흄관_D700"),
    (["흄관","RC관","원심력"], ["D600","600mm"],   "흄관_D600"),
    (["흄관","RC관","원심력"], ["D500","500mm"],   "흄관_D500"),
    (["흄관","RC관","원심력"], ["D450","450mm"],   "흄관_D450"),
    (["흄관","RC관","원심력"], ["D400","400mm"],   "흄관_D400"),
    (["흄관","RC관","원심력"], ["D350","350mm"],   "흄관_D350"),
    (["흄관","RC관","원심력"], ["D300","300mm"],   "흄관_D300"),
    (["흄관","RC관","원심력"], ["D250","250mm"],   "흄관_D250"),
    (["흄관","RC관","원심력"], [],                 "흄관_D300"),

    # 맨홀
    (["소형맨홀","D600맨홀"],           [],                         "소형맨홀_D600"),
    (["맨홀"], ["D1500","1500mm","3호"], "PC맨홀3호_D1500"),
    (["맨홀"], ["D1200","1200mm","2호"], "PC맨홀2호_D1200"),
    (["맨홀"], [],                       "PC맨홀1호_D900"),

    # 배수설비
    (["오수받이"],  [], "오수받이설치"),
    (["배수설비"],  [], "배수설비"),

    # 포장복구
    (["보조기층"],  [], "보조기층포설"),
    (["아스콘포장","아스팔트포장","아스팔트표층","아스팔트기층"], [], "아스콘포장"),
    (["콘크리트포장","콘크리트표층"], [], "콘크리트포장"),

    # 가시설
    (["가시설","흙막이","안전난간"], [], "가시설흙막이"),

    # 추진공
    (["추진","강관압입"], ["D800","800mm"], "강관압입추진_D800"),
    (["추진","강관압입"], ["D600","600mm"], "강관압입추진_D600"),
    (["추진","강관압입"], [],               "강관압입추진_D450"),
]

def get_work_key(name: str, spec: str):
    for name_kws, spec_kws, key in WORK_KEY_MAP:
        if not any(kw in name for kw in name_kws):
            continue
        if spec_kws and not any(kw in (name+spec) for kw in spec_kws):
            continue
        return key
    return None

def calc_work_days(name: str, spec: str, qty: float,
                   crews: int = None, hours: int = 8) -> dict:
    """
    작업일수 계산
    터파기는 굴착폭+토질 조합으로 세분화
    나머지는 DAILY_WORK 딕셔너리 사용
    """
    if not qty or qty <= 0:
        return None

    combined = name + " " + spec

    # ── 터파기 특별 처리 ──────────────────────────────────────
    if any(kw in name for kw in ["터파기","굴착"]) and "운반" not in name:
        soil, width = parse_excavation_spec(name, spec)
        daily = EXCAVATION_DAILY.get((soil, width))

        # 해당 조합 없으면 기본값
        if not daily:
            daily = EXCAVATION_DAILY.get((soil, "기본"), 300)

        default_crews = 5  # 굴착기 1대 + 덤프 등 5인 기준
        actual_crews  = crews if crews else default_crews
        daily_total   = daily * actual_crews / default_crews
        work_days     = qty / daily if daily > 0 else 0

        condition_str = f"{soil}, {width}, 1일{daily}㎥"

        return {
            "key":           f"터파기_{soil}_{width}",
            "daily":         daily,
            "unit":          "㎥",
            "crews":         actual_crews,
            "hours":         hours,
            "condition":     condition_str,
            "qty":           qty,
            "work_days":     round(work_days, 2),
            "work_days_ceil":math.ceil(work_days),
            "soil":          soil,
            "width":         width,
        }

    # ── 일반 공종 ─────────────────────────────────────────────
    key = get_work_key(name, spec)
    if not key:
        return None

    info = DAILY_WORK[key].copy()
    if crews:
        info["crews"] = crews

    daily_total = info["daily"] * info["crews"]
    work_days   = qty / daily_total if daily_total > 0 else 0

    info["key"]            = key
    info["qty"]            = qty
    info["work_days"]      = round(work_days, 2)
    info["work_days_ceil"] = math.ceil(work_days)
    return info


if __name__ == "__main__":
    print("=== 터파기 굴착폭×토질 세분화 테스트 ===")
    tests = [
        ("터파기(B=1.5~2.5m이만)", "(토사:기계90%+인력10%)",   724),
        ("터파기(B=2.5~4.0m이만)", "(토사:기계90%+인력10%)",  5651),
        ("터파기(B=4.0m이상)",     "(토사:기계90%+인력10%)", 16025),
        ("터파기(B=2.5~4.0m이만)", "(용수토사:기계90%+인력10%)",  85),
        ("터파기(B=4.0m이상)",     "(용수토사:기계90%+인력10%)",3253),
        ("터파기(B=2.5~4.0m이만)", "(연암,대형브레이카)",        113),
        ("터파기(B=4.0m이상)",     "(연암,대형브레이카)",         315),
    ]
    total_days = 0
    for name, spec, qty in tests:
        r = calc_work_days(name, spec, qty)
        if r:
            print(f"  {name:25s} {spec:25s} {qty:>6,}㎥ → {r['work_days_ceil']:>4}일 "
                  f"(1일:{r['daily']}㎥, {r['soil']}, {r['width']})")
            total_days += r["work_days_ceil"]
        else:
            print(f"  {name} → 매핑없음")
    print(f"\n  터파기 총 작업일수: {total_days}일")

    print("\n=== 기타 공종 테스트 ===")
    tests2 = [
        ("조립식PC맨홀",    "D900,하부구체+상판", 502),
        ("되메우기 및 다짐","관상단,토사",       17563),
        ("보조기층 포설",   "t=20cm",           10000),
        ("아스콘포장",      "t=7cm",            10000),
    ]
    for name, spec, qty in tests2:
        r = calc_work_days(name, spec, qty)
        if r:
            print(f"  {name:20s} {qty:>6,} → {r['work_days_ceil']:>4}일")