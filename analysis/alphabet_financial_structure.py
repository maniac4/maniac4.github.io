#!/usr/bin/env python3
"""
알파벳(Alphabet Inc., GOOGL) 재무 구조 분석기
==========================================

SEC EDGAR 공시자료(10-K XBRL 데이터)를 받아 연도별 재무 구조를 분석한다.

데이터 출처
  - SEC XBRL Company Facts API
    https://data.sec.gov/api/xbrl/companyfacts/CIK0001652044.json
  - 알파벳 CIK: 0001652044

분석 항목
  1. 자본 구조   : 부채비율, 자기자본비율, 차입금/자본, 순현금
  2. 유동성      : 유동비율, 당좌비율, 현금비율
  3. 수익성      : 매출총이익률, 영업이익률, 순이익률, ROE, ROA
  4. 현금흐름    : 영업현금흐름, 설비투자(CapEx), 잉여현금흐름(FCF), 주주환원율
  5. 자산 구성   : 현금성자산 / 유형자산 / 기타 비중

사용법
  # SEC는 연락처가 담긴 User-Agent를 요구한다
  export SEC_USER_AGENT="홍길동 your-email@example.com"
  python alphabet_financial_structure.py                # 최근 5개 회계연도
  python alphabet_financial_structure.py --years 8      # 최근 8개 회계연도
  python alphabet_financial_structure.py --offline      # 내장 참고 데이터로 실행
  python alphabet_financial_structure.py --out result   # 결과 저장 폴더 지정

출력
  <out>/alphabet_raw.csv     : 공시에서 추출한 원자료 (USD 백만)
  <out>/alphabet_ratios.csv  : 계산된 재무비율
  <out>/alphabet_structure.png : 차트 (matplotlib 설치 시)

필요 패키지: pandas, requests (차트는 matplotlib 선택)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

CIK = "0001652044"
COMPANY_FACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"

# ---------------------------------------------------------------------------
# 1. 추출할 계정과목 정의
#    key: 내부 이름, value: (설명, 기간/시점 구분, 후보 US-GAAP 태그 목록)
#    - "duration": 손익·현금흐름 항목 (1년 기간값)
#    - "instant" : 재무상태표 항목 (기말 시점값)
#    태그는 연도마다 바뀔 수 있어 앞에서부터 차례로 시도해 합친다.
# ---------------------------------------------------------------------------
ITEMS: dict[str, tuple[str, str, list[str]]] = {
    # 손익계산서
    "revenue":          ("매출액", "duration", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]),
    "cost_of_revenue":  ("매출원가", "duration", ["CostOfRevenue", "CostOfGoodsAndServicesSold"]),
    "operating_income": ("영업이익", "duration", ["OperatingIncomeLoss"]),
    "net_income":       ("당기순이익", "duration", ["NetIncomeLoss"]),
    # 재무상태표
    "total_assets":        ("자산총계", "instant", ["Assets"]),
    "current_assets":      ("유동자산", "instant", ["AssetsCurrent"]),
    "total_liabilities":   ("부채총계", "instant", ["Liabilities"]),
    "current_liabilities": ("유동부채", "instant", ["LiabilitiesCurrent"]),
    "equity":              ("자본총계", "instant", ["StockholdersEquity"]),
    "cash":                ("현금및현금성자산", "instant", ["CashAndCashEquivalentsAtCarryingValue"]),
    "marketable_sec":      ("단기 유가증권", "instant", ["MarketableSecuritiesCurrent",
                                                         "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]),
    "receivables":         ("매출채권", "instant", ["AccountsReceivableNetCurrent"]),
    "ppe":                 ("유형자산(순액)", "instant", ["PropertyPlantAndEquipmentNet"]),
    "long_term_debt":      ("장기차입금", "instant", ["LongTermDebtNoncurrent", "LongTermDebt"]),
    "retained_earnings":   ("이익잉여금", "instant", ["RetainedEarningsAccumulatedDeficit"]),
    # 현금흐름표
    "ocf":        ("영업활동현금흐름", "duration", ["NetCashProvidedByUsedInOperatingActivities"]),
    "capex":      ("설비투자(CapEx)", "duration", ["PaymentsToAcquirePropertyPlantAndEquipment",
                                                   "PaymentsToAcquireProductiveAssets"]),
    "buybacks":   ("자사주 매입", "duration", ["PaymentsForRepurchaseOfCommonStock"]),
    "dividends":  ("배당금 지급", "duration", ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]),
}

# ---------------------------------------------------------------------------
# 오프라인용 참고 데이터 (USD 백만, 알파벳 10-K 기준 요약)
#   네트워크가 막혀 있거나 --offline 옵션일 때 사용한다.
#   실제 분석 전에는 반드시 SEC 원문(10-K)과 대조할 것.
# ---------------------------------------------------------------------------
OFFLINE_DATA = {
    2021: dict(revenue=257637, cost_of_revenue=110939, operating_income=78714, net_income=76033,
               total_assets=359268, current_assets=188143, total_liabilities=107633,
               current_liabilities=64254, equity=251635, cash=20945, marketable_sec=118704,
               receivables=39304, ppe=110558, long_term_debt=14817, retained_earnings=191484,
               ocf=91652, capex=24640, buybacks=50274, dividends=0),
    2022: dict(revenue=282836, cost_of_revenue=126203, operating_income=74842, net_income=59972,
               total_assets=365264, current_assets=164795, total_liabilities=109120,
               current_liabilities=69300, equity=256144, cash=21879, marketable_sec=91883,
               receivables=40258, ppe=112668, long_term_debt=14701, retained_earnings=195563,
               ocf=91495, capex=31485, buybacks=59296, dividends=0),
    2023: dict(revenue=307394, cost_of_revenue=133332, operating_income=84293, net_income=73795,
               total_assets=402392, current_assets=171530, total_liabilities=119013,
               current_liabilities=81814, equity=283379, cash=24048, marketable_sec=86868,
               receivables=47964, ppe=134345, long_term_debt=13253, retained_earnings=211247,
               ocf=101746, capex=32251, buybacks=61504, dividends=0),
    2024: dict(revenue=350018, cost_of_revenue=146306, operating_income=112390, net_income=100118,
               total_assets=450256, current_assets=163711, total_liabilities=125172,
               current_liabilities=89122, equity=325084, cash=23466, marketable_sec=72191,
               receivables=52340, ppe=171036, long_term_debt=10883, retained_earnings=245084,
               ocf=125299, capex=52535, buybacks=62222, dividends=7363),
}


# ---------------------------------------------------------------------------
# 2. 공시 데이터 수집
# ---------------------------------------------------------------------------
def fetch_company_facts(user_agent: str, cache: Path | None = None) -> dict:
    """SEC Company Facts JSON을 내려받는다. cache 경로가 있으면 재사용한다."""
    if cache and cache.exists():
        return json.loads(cache.read_text())

    import requests

    resp = requests.get(COMPANY_FACTS_URL, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
    return data


def _annual_series(facts: dict, tag: str, kind: str) -> pd.Series:
    """한 태그에서 10-K 연간 값만 뽑아 {회계연도: 값(USD 백만)} 시리즈로 만든다."""
    node = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not node or "USD" not in node.get("units", {}):
        return pd.Series(dtype="float64")

    rows = []
    for f in node["units"]["USD"]:
        if not str(f.get("form", "")).startswith("10-K"):
            continue
        end = pd.Timestamp(f["end"])
        if kind == "duration":
            if "start" not in f:
                continue
            days = (end - pd.Timestamp(f["start"])).days
            if not 350 <= days <= 380:          # 분기·누적 값 제외, 1년치만
                continue
        rows.append({"year": end.year, "end": end, "filed": f["filed"], "val": f["val"]})

    if not rows:
        return pd.Series(dtype="float64")

    df = pd.DataFrame(rows)
    # 알파벳 회계연도는 12월 31일 결산. 같은 연도 값이 여러 공시에 있으면 가장 최근 공시(정정 반영)를 쓴다.
    df = df[df["end"].dt.month == 12]
    df = df.sort_values("filed").drop_duplicates("year", keep="last")
    return df.set_index("year")["val"] / 1e6


def extract_annual_data(facts: dict) -> pd.DataFrame:
    """정의된 모든 계정을 연도별 표(행=연도, 열=계정)로 정리한다."""
    columns = {}
    for key, (_, kind, tags) in ITEMS.items():
        series = pd.Series(dtype="float64")
        for tag in tags:                       # 앞 태그 우선, 빈 연도는 뒤 태그로 보충
            s = _annual_series(facts, tag, kind)
            series = series.combine_first(s) if not series.empty else s
        columns[key] = series
    df = pd.DataFrame(columns).sort_index()
    df.index.name = "fiscal_year"
    # 배당·자사주 매입이 없는 해는 태그 자체가 없으므로 0으로 처리
    for k in ("dividends", "buybacks"):
        df[k] = df[k].fillna(0)
    return df


# ---------------------------------------------------------------------------
# 3. 재무비율 계산
# ---------------------------------------------------------------------------
def compute_ratios(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw
    r = pd.DataFrame(index=d.index)

    avg_equity = (d["equity"] + d["equity"].shift(1)) / 2
    avg_assets = (d["total_assets"] + d["total_assets"].shift(1)) / 2
    cash_like = d["cash"] + d["marketable_sec"]
    fcf = d["ocf"] - d["capex"]
    shareholder_return = d["buybacks"] + d["dividends"]

    # 자본 구조
    r["부채비율(%)"] = d["total_liabilities"] / d["equity"] * 100
    r["자기자본비율(%)"] = d["equity"] / d["total_assets"] * 100
    r["차입금/자본(%)"] = d["long_term_debt"] / d["equity"] * 100
    r["순현금(백만$)"] = cash_like - d["long_term_debt"]
    r["이익잉여금/자본(%)"] = d["retained_earnings"] / d["equity"] * 100

    # 유동성
    r["유동비율(%)"] = d["current_assets"] / d["current_liabilities"] * 100
    r["당좌비율(%)"] = (cash_like + d["receivables"]) / d["current_liabilities"] * 100
    r["현금비율(%)"] = cash_like / d["current_liabilities"] * 100

    # 수익성
    r["매출성장률(%)"] = d["revenue"].pct_change() * 100
    r["매출총이익률(%)"] = (d["revenue"] - d["cost_of_revenue"]) / d["revenue"] * 100
    r["영업이익률(%)"] = d["operating_income"] / d["revenue"] * 100
    r["순이익률(%)"] = d["net_income"] / d["revenue"] * 100
    r["ROE(%)"] = d["net_income"] / avg_equity * 100
    r["ROA(%)"] = d["net_income"] / avg_assets * 100
    r["총자산회전율(회)"] = d["revenue"] / avg_assets

    # 현금흐름
    r["잉여현금흐름(백만$)"] = fcf
    r["FCF마진(%)"] = fcf / d["revenue"] * 100
    r["CapEx/매출(%)"] = d["capex"] / d["revenue"] * 100
    r["CapEx/영업현금흐름(%)"] = d["capex"] / d["ocf"] * 100
    r["현금전환율(OCF/순이익)"] = d["ocf"] / d["net_income"]
    r["주주환원/FCF(%)"] = shareholder_return / fcf * 100

    # 자산 구성
    r["현금성자산 비중(%)"] = cash_like / d["total_assets"] * 100
    r["유형자산 비중(%)"] = d["ppe"] / d["total_assets"] * 100
    r["기타자산 비중(%)"] = 100 - r["현금성자산 비중(%)"] - r["유형자산 비중(%)"]

    return r


# ---------------------------------------------------------------------------
# 4. 해석 요약
# ---------------------------------------------------------------------------
def _trend(series: pd.Series, unit: str = "%p") -> str:
    s = series.dropna()
    if len(s) < 2:
        return ""
    diff = s.iloc[-1] - s.iloc[0]
    arrow = "▲" if diff > 0 else "▼" if diff < 0 else "―"
    return f"({s.index[0]}→{s.index[-1]} {arrow}{abs(diff):.1f}{unit})"


def summarize(raw: pd.DataFrame, ratios: pd.DataFrame) -> str:
    y = ratios.index.max()
    r, d = ratios.loc[y], raw.loc[y]
    lines = [f"■ 알파벳 재무 구조 요약 (FY{y}, 단위: USD 백만)", ""]

    lines.append("[자본 구조]")
    lines.append(f"  부채비율 {r['부채비율(%)']:.1f}%  {_trend(ratios['부채비율(%)'])}")
    lines.append(f"  자기자본비율 {r['자기자본비율(%)']:.1f}%")
    lines.append(f"  장기차입금 {d['long_term_debt']:,.0f} vs 현금+유가증권 {d['cash'] + d['marketable_sec']:,.0f}"
                 f" → 순현금 {r['순현금(백만$)']:,.0f}")
    verdict = ("차입 의존도가 매우 낮은 '순현금' 구조" if r["순현금(백만$)"] > 0
               else "차입금이 현금성자산을 웃도는 '순차입' 구조")
    lines.append(f"  → {verdict}")

    lines.append("\n[유동성]")
    lines.append(f"  유동비율 {r['유동비율(%)']:.0f}%  {_trend(ratios['유동비율(%)'])}")
    lines.append(f"  현금비율 {r['현금비율(%)']:.0f}%")

    lines.append("\n[수익성]")
    lines.append(f"  매출 {d['revenue']:,.0f} (성장률 {r['매출성장률(%)']:.1f}%)")
    lines.append(f"  영업이익률 {r['영업이익률(%)']:.1f}%  {_trend(ratios['영업이익률(%)'])}")
    lines.append(f"  ROE {r['ROE(%)']:.1f}%, ROA {r['ROA(%)']:.1f}%")

    lines.append("\n[현금흐름·투자]")
    lines.append(f"  영업현금흐름 {d['ocf']:,.0f}, CapEx {d['capex']:,.0f}, FCF {r['잉여현금흐름(백만$)']:,.0f}")
    lines.append(f"  CapEx/매출 {r['CapEx/매출(%)']:.1f}%  {_trend(ratios['CapEx/매출(%)'])}")
    lines.append(f"  주주환원(자사주+배당) / FCF {r['주주환원/FCF(%)']:.0f}%")

    lines.append("\n[자산 구성]")
    lines.append(f"  현금성 {r['현금성자산 비중(%)']:.1f}% / 유형자산 {r['유형자산 비중(%)']:.1f}%"
                 f" / 기타 {r['기타자산 비중(%)']:.1f}%")
    ppe_trend = ratios["유형자산 비중(%)"].dropna()
    if len(ppe_trend) >= 2 and ppe_trend.iloc[-1] > ppe_trend.iloc[0]:
        lines.append("  → 현금성 자산이 줄고 유형자산(데이터센터·AI 인프라) 비중이 커지는 추세")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. 차트
# ---------------------------------------------------------------------------
def plot(raw: pd.DataFrame, ratios: pd.DataFrame, path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    years = [str(y) for y in raw.index]
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle("Alphabet Inc. - Financial Structure (SEC 10-K)", fontsize=14, fontweight="bold")

    # (1) 자본 구조: 부채 vs 자본
    a = ax[0, 0]
    a.bar(years, raw["equity"] / 1e3, label="Equity", color="#4C78A8")
    a.bar(years, raw["total_liabilities"] / 1e3, bottom=raw["equity"] / 1e3, label="Liabilities", color="#F58518")
    a.set_title("Capital structure (USD bn)")
    a.legend()

    # (2) 자산 구성
    a = ax[0, 1]
    cash_like = (raw["cash"] + raw["marketable_sec"]) / 1e3
    ppe = raw["ppe"] / 1e3
    other = raw["total_assets"] / 1e3 - cash_like - ppe
    a.bar(years, cash_like, label="Cash + securities", color="#54A24B")
    a.bar(years, ppe, bottom=cash_like, label="PP&E", color="#B279A2")
    a.bar(years, other, bottom=cash_like + ppe, label="Other", color="#BAB0AC")
    a.set_title("Asset composition (USD bn)")
    a.legend()

    # (3) 수익성
    a = ax[1, 0]
    for col, lab in [("매출총이익률(%)", "Gross margin"), ("영업이익률(%)", "Operating margin"),
                     ("순이익률(%)", "Net margin"), ("ROE(%)", "ROE")]:
        a.plot(years, ratios[col], marker="o", label=lab)
    a.set_title("Profitability (%)")
    a.legend()
    a.grid(alpha=0.3)

    # (4) 현금흐름
    a = ax[1, 1]
    x = range(len(years))
    w = 0.27
    a.bar([i - w for i in x], raw["ocf"] / 1e3, w, label="Operating CF", color="#4C78A8")
    a.bar(list(x), raw["capex"] / 1e3, w, label="CapEx", color="#E45756")
    a.bar([i + w for i in x], (raw["buybacks"] + raw["dividends"]) / 1e3, w,
          label="Buybacks + dividends", color="#72B7B2")
    a.set_xticks(list(x), years)
    a.set_title("Cash flow & capital allocation (USD bn)")
    a.legend()

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


# ---------------------------------------------------------------------------
# 실행부
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description="SEC 공시 기반 알파벳 재무 구조 분석")
    p.add_argument("--years", type=int, default=5, help="분석할 최근 회계연도 수 (기본 5)")
    p.add_argument("--offline", action="store_true", help="내장 참고 데이터 사용 (네트워크 불필요)")
    p.add_argument("--out", default="output", help="결과 저장 폴더 (기본 ./output)")
    p.add_argument("--refresh", action="store_true", help="캐시를 무시하고 SEC에서 다시 받기")
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = "SEC EDGAR XBRL (10-K)"

    if args.offline:
        raw, source = pd.DataFrame.from_dict(OFFLINE_DATA, orient="index"), "내장 참고 데이터"
    else:
        ua = os.environ.get("SEC_USER_AGENT", "financial-analysis-script admin@example.com")
        cache = out / f"companyfacts_{CIK}.json"
        if args.refresh and cache.exists():
            cache.unlink()
        try:
            raw = extract_annual_data(fetch_company_facts(ua, cache))
        except Exception as e:  # 네트워크 차단 등
            print(f"[경고] SEC 데이터 수집 실패: {e}\n       내장 참고 데이터로 대체합니다.\n", file=sys.stderr)
            raw, source = pd.DataFrame.from_dict(OFFLINE_DATA, orient="index"), "내장 참고 데이터"

    raw.index.name = "fiscal_year"
    raw = raw.dropna(subset=["revenue", "total_assets"])
    # ROE·성장률 계산을 위해 1년 더 가져온 뒤 마지막에 잘라낸다
    raw = raw.tail(args.years + 1)
    ratios = compute_ratios(raw).tail(args.years)
    raw = raw.tail(args.years)

    raw.round(0).to_csv(out / "alphabet_raw.csv", encoding="utf-8-sig")
    ratios.round(2).to_csv(out / "alphabet_ratios.csv", encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    print(f"데이터 출처: {source}  (분석일 {date.today()})\n")
    print("=== 원자료 (USD 백만) ===")
    print(raw.rename(columns={k: v[0] for k, v in ITEMS.items()}).T.map(lambda v: f"{v:,.0f}"))
    print("\n=== 재무비율 ===")
    print(ratios.T.round(1))
    print()
    print(summarize(raw, ratios))

    saved = ["alphabet_raw.csv", "alphabet_ratios.csv"]
    if plot(raw, ratios, out / "alphabet_structure.png"):
        saved.append("alphabet_structure.png")
    print(f"\n저장 완료: {', '.join(str(out / f) for f in saved)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
