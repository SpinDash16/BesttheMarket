"""
S&P 3 Strategy Analyzer — Python port of sp3-analyzer/main.js

Strategy:
  - Every Friday, invest $X into each of the current top-3
    S&P 500 stocks by market cap (= $3X total/week)
  - Compare vs. investing $3X/week into SPY

Data:
  - CSV files in ./data/ (MacroTrends weekly adjusted close)
  - TOP3_PERIODS defines which stocks were in the top 3 each week
"""

import logging
import json
from datetime import datetime, timedelta, date
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────
# Mirrors TOP3_PERIODS from sp3-analyzer/main.js exactly
TOP3_PERIODS = [
    {"from": "1996-03-15", "to": "1997-06-27", "stocks": ["GE",   "MSFT", "XOM"]},
    {"from": "1997-07-04", "to": "1999-06-25", "stocks": ["MSFT", "GE",   "XOM"]},
    {"from": "1999-07-02", "to": "2001-09-28", "stocks": ["MSFT", "CSCO", "GE"]},
    {"from": "2001-10-05", "to": "2004-12-31", "stocks": ["MSFT", "GE",   "XOM"]},
    {"from": "2005-01-07", "to": "2009-12-25", "stocks": ["XOM",  "GE",   "MSFT"]},
    {"from": "2010-01-01", "to": "2012-03-30", "stocks": ["XOM",  "AAPL", "MSFT"]},
    {"from": "2012-04-06", "to": "2014-01-31", "stocks": ["AAPL", "XOM",  "GOOGL"]},
    {"from": "2014-02-07", "to": "2019-12-27", "stocks": ["AAPL", "GOOGL","MSFT"]},
    {"from": "2020-01-03", "to": "2022-12-30", "stocks": ["AAPL", "MSFT", "AMZN"]},
    {"from": "2023-01-06", "to": "2024-05-31", "stocks": ["AAPL", "MSFT", "GOOGL"]},
    {"from": "2024-06-07", "to": "2026-03-13", "stocks": ["AAPL", "MSFT", "NVDA"]},
]

ALL_SP3_TICKERS = list(dict.fromkeys(t for p in TOP3_PERIODS for t in p["stocks"]))
ALL_TICKERS = ALL_SP3_TICKERS + ["SPY"]


def get_top3(ymd: str) -> list[str]:
    """Return the top-3 tickers for a given 'YYYY-MM-DD' string."""
    for period in TOP3_PERIODS:
        if period["from"] <= ymd <= period["to"]:
            return period["stocks"]
    return []


def load_csv(ticker: str, csv_dir: Path) -> dict:
    """
    Load one CSV file and return a dict: 'YYYY-MM-DD' -> price (float).
    Mirrors loadCSV() in main.js — finds the 'date,' header line and
    parses from there, preferring 'adj close' over 'close'.
    """
    csv_path = csv_dir / f"MacroTrends_Data_Download_{ticker}.csv"

    if not csv_path.exists():
        logger.warning(f"CSV not found: {csv_path}")
        return {}

    try:
        raw = csv_path.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()

        # Find the header line starting with 'date,' (case-insensitive)
        header_idx = next(
            (i for i, l in enumerate(lines) if l.strip().lower().startswith("date,")),
            None,
        )
        if header_idx is None:
            logger.error(f"{ticker}: could not find 'date,' header")
            return {}

        clean_text = "\n".join(lines[header_idx:])
        df = pd.read_csv(pd.io.common.StringIO(clean_text))

        headers = list(df.columns)

        def find_col(pattern):
            import re
            return next((h for h in headers if re.search(pattern, h, re.I)), None)

        date_col  = find_col(r"^date$")
        adj_col   = find_col(r"adj.*close")
        close_col = find_col(r"^close$")
        price_col = adj_col or close_col

        if not date_col or not price_col:
            logger.error(f"{ticker}: missing date or close column. Cols: {headers}")
            return {}

        price_map = {}
        for _, row in df.iterrows():
            raw_date  = str(row[date_col]).strip()
            raw_price = str(row[price_col]).strip().replace(",", "")
            if not raw_date or not raw_price:
                continue
            try:
                dt = pd.to_datetime(raw_date)
                price = float(raw_price)
                if price > 0:
                    price_map[dt.strftime("%Y-%m-%d")] = price
            except Exception:
                continue

        logger.info(f"  Loaded {len(price_map)} price points for {ticker}")
        return price_map

    except Exception as e:
        logger.error(f"Error loading CSV for {ticker}: {e}")
        return {}


def lookup_price(price_map: dict, ymd: str):
    """
    Mirrors lookupPrice() in main.js.
    Returns the price for `ymd`, or looks back up to 4 calendar days
    (to handle Fridays that are market holidays).
    """
    if ymd in price_map:
        return price_map[ymd]
    dt = datetime.strptime(ymd, "%Y-%m-%d")
    for i in range(1, 5):
        key = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        if key in price_map:
            return price_map[key]
    return None


def generate_fridays(start: date, end: date) -> list[date]:
    """Generate all Fridays from start to end inclusive."""
    fridays = []
    d = start
    while d.weekday() != 4:      # 4 = Friday
        d += timedelta(days=1)
    while d <= end:
        fridays.append(d)
        d += timedelta(days=7)
    return fridays


def run_calculations(price_maps: dict, weekly_per_stock: float, fridays: list) -> dict:
    """
    Mirrors runCalculations() in main.js exactly.
    """
    weekly_total = weekly_per_stock * 3

    sp3_shares = {t: 0.0 for t in ALL_SP3_TICKERS}
    spy_shares = 0.0

    rows = []
    chart_labels       = []
    sp3_values         = []
    spy_values         = []
    contributed_values = []

    total_contributed  = 0.0
    chart_contributed  = 0.0

    for i, friday in enumerate(fridays):
        ymd   = friday.strftime("%Y-%m-%d")
        top3  = get_top3(ymd)

        # Prices for all SP3 tickers
        prices = {t: lookup_price(price_maps[t], ymd) for t in ALL_SP3_TICKERS}
        spy_price = lookup_price(price_maps["SPY"], ymd)

        # ── S&P 3: buy $weekly_per_stock of each top-3 stock ──
        for ticker in top3:
            price = prices.get(ticker)
            if price and price > 0:
                bought = weekly_per_stock / price
                sp3_shares[ticker] += bought
                total_contributed  += weekly_per_stock

        # ── SPY: buy $weekly_total of SPY ─────────────────────
        if spy_price and spy_price > 0:
            spy_shares += weekly_total / spy_price

        chart_contributed += weekly_total

        # ── Current portfolio values ───────────────────────────
        sp3_val = sum(
            sp3_shares[t] * prices[t]
            for t in ALL_SP3_TICKERS
            if prices.get(t) and sp3_shares[t] > 0
        )
        spy_val = spy_shares * spy_price if spy_price else 0.0

        # Chart: every 4th Friday (~monthly) + last row — mirrors JS
        if i % 4 == 0 or i == len(fridays) - 1:
            label = friday.strftime("%b %Y")   # e.g. "Mar 2024"
            chart_labels.append(label)
            sp3_values.append(round(sp3_val, 2))
            spy_values.append(round(spy_val, 2))
            contributed_values.append(round(chart_contributed, 2))

        rows.append({
            "date":   ymd,
            "top3":   top3,
            "sp3Val": sp3_val,
            "spyVal": spy_val,
        })

    # Use SPY side as clean "total contributed" (same logic as JS)
    spy_contributed = len(fridays) * weekly_total

    sp3_final = rows[-1]["sp3Val"] if rows else 0.0
    spy_final = rows[-1]["spyVal"] if rows else 0.0

    return {
        "chart_labels":       chart_labels,
        "sp3_values":         sp3_values,
        "spy_values":         spy_values,
        "contributed_values": contributed_values,
        "sp3_final":          sp3_final,
        "spy_final":          spy_final,
        "total_contributed":  spy_contributed,
        "sp3_shares":         dict(sp3_shares),
        "spy_shares":         spy_shares,
        "rows":               rows,
    }


def calc_cagr(final_value: float, total_contributed: float, years: float) -> float:
    """Mirrors calcCAGR() in main.js."""
    if not total_contributed or not final_value or years <= 0:
        return 0.0
    return (pow(final_value / total_contributed, 1 / years) - 1) * 100


def run_backtest(
    start_date: date = date(1996, 3, 13),
    end_date:   date = date(2026, 3, 13),
    weekly_per_stock: float = 100.0,
    csv_dir: Path = None,
) -> dict:
    """
    Run the full backtest and return results matching the JS analyzer output.
    weekly_per_stock: $ per stock per week ($100 default -> $300/week total)
    """
    if csv_dir is None:
        csv_dir = Path(__file__).parent / "data"

    weekly_total = weekly_per_stock * 3

    logger.info(f"Starting backtest: {start_date} to {end_date}  (${weekly_per_stock:.0f}/stock/week)")

    price_maps = {ticker: load_csv(ticker, csv_dir) for ticker in ALL_TICKERS}
    fridays    = generate_fridays(start_date, end_date)
    result     = run_calculations(price_maps, weekly_per_stock, fridays)

    years = (end_date - start_date).days / 365.25
    sp3_return_pct = (result["sp3_final"] - result["total_contributed"]) / result["total_contributed"] * 100 if result["total_contributed"] else 0
    spy_return_pct = (result["spy_final"]  - result["total_contributed"]) / result["total_contributed"] * 100 if result["total_contributed"] else 0
    sp3_cagr = calc_cagr(result["sp3_final"], result["total_contributed"], years)
    spy_cagr = calc_cagr(result["spy_final"],  result["total_contributed"], years)

    logger.info(f"S&P 3: {sp3_return_pct:+.1f}%  CAGR {sp3_cagr:.2f}%  Final ${result['sp3_final']:,.0f}")
    logger.info(f"SPY:   {spy_return_pct:+.1f}%  CAGR {spy_cagr:.2f}%  Final ${result['spy_final']:,.0f}")
    logger.info(f"Contributed: ${result['total_contributed']:,.0f}  over {len(fridays)} weeks")

    return {
        "chart_labels":       result["chart_labels"],
        "sp3_values":         result["sp3_values"],
        "spy_values":         result["spy_values"],
        "contributed_values": result["contributed_values"],
        "sp3_final":          result["sp3_final"],
        "spy_final":          result["spy_final"],
        "total_contributed":  result["total_contributed"],
        "sp3_return_pct":     round(sp3_return_pct, 2),
        "spy_return_pct":     round(spy_return_pct, 2),
        "sp3_cagr":           round(sp3_cagr, 2),
        "spy_cagr":           round(spy_cagr, 2),
        "years":              round(years, 1),
        "weeks":              len(fridays),
        "chart_points":       len(result["chart_labels"]),
        "weekly_per_stock":   weekly_per_stock,
        "weekly_total":       weekly_total,
        "sp3_shares":         result["sp3_shares"],
        "spy_shares":         result["spy_shares"],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = run_backtest()
    print(f"\nS&P 3:  ${r['sp3_final']:>14,.2f}   ({r['sp3_return_pct']:+.1f}%  CAGR {r['sp3_cagr']:.2f}%)")
    print(f"SPY:    ${r['spy_final']:>14,.2f}   ({r['spy_return_pct']:+.1f}%  CAGR {r['spy_cagr']:.2f}%)")
    print(f"Invested: ${r['total_contributed']:>12,.2f}")
    print(f"Weeks: {r['weeks']}   Years: {r['years']}   Chart pts: {r['chart_points']}")
