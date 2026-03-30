"""Earnings calendar fetcher — upcoming earnings for our tracked universe."""
from __future__ import annotations
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Combined universe: SF tickers + key SP500 names
EARNINGS_UNIVERSE = [
    # AI & Chips
    ("NVDA", "Nvidia"),
    ("AMD",  "Advanced Micro Devices"),
    ("INTC", "Intel"),
    ("ARM",  "Arm Holdings"),
    ("SMCI", "Super Micro Computer"),
    ("AVGO", "Broadcom"),
    ("QCOM", "Qualcomm"),
    ("MRVL", "Marvell Technology"),
    # AI Software & Cloud
    ("PLTR", "Palantir"),
    ("SNOW", "Snowflake"),
    ("DDOG", "Datadog"),
    ("AI",   "C3.ai"),
    # Cybersecurity
    ("CRWD", "CrowdStrike"),
    ("NET",  "Cloudflare"),
    ("ZS",   "Zscaler"),
    ("PANW", "Palo Alto Networks"),
    ("OKTA", "Okta"),
    # Big Tech
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("GOOGL","Alphabet"),
    ("AMZN", "Amazon"),
    ("META", "Meta"),
    ("TSLA", "Tesla"),
    # Fintech & Crypto
    ("COIN", "Coinbase"),
    ("SQ",   "Block"),
    ("HOOD", "Robinhood"),
    # EV & Space
    ("RIVN", "Rivian"),
    ("RKLB", "Rocket Lab"),
    # Quantum
    ("IONQ", "IonQ"),
    ("RGTI", "Rigetti Computing"),
]


def get_upcoming_earnings(weeks_ahead: int = 6) -> list[dict]:
    """
    Return earnings events for the universe occurring within the next `weeks_ahead` weeks,
    sorted by date ascending. Each entry is a dict with:
        ticker, name, earnings_date, eps_estimate, revenue_estimate, days_away
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available — returning empty earnings list")
        return []

    today = date.today()
    cutoff = today + timedelta(weeks=weeks_ahead)
    results: list[dict] = []

    for ticker, default_name in EARNINGS_UNIVERSE:
        try:
            t = yf.Ticker(ticker)

            # earnings_dates returns a DataFrame indexed by datetime with upcoming rows first
            ed = t.earnings_dates
            if ed is None or ed.empty:
                continue

            # Normalize index to date objects
            upcoming = []
            for idx in ed.index:
                try:
                    d = idx.date() if hasattr(idx, "date") else idx
                    if today <= d <= cutoff:
                        upcoming.append((d, ed.loc[idx]))
                except Exception:
                    continue

            if not upcoming:
                continue

            earnings_date, row = min(upcoming, key=lambda x: x[0])
            days_away = (earnings_date - today).days

            info = t.fast_info
            name = getattr(info, "short_name", None) or default_name

            eps_est = row.get("EPS Estimate") if hasattr(row, "get") else getattr(row, "EPS Estimate", None)
            try:
                eps_est = round(float(eps_est), 2) if eps_est is not None and str(eps_est) != "nan" else None
            except Exception:
                eps_est = None

            results.append({
                "ticker":            ticker,
                "name":              name,
                "earnings_date":     earnings_date.isoformat(),
                "earnings_date_fmt": earnings_date.strftime("%b %-d, %Y"),
                "weekday":           earnings_date.strftime("%A"),
                "eps_estimate":      eps_est,
                "eps_high":          None,
                "eps_low":           None,
                "revenue_estimate":  None,
                "days_away":         days_away,
            })
        except Exception as e:
            logger.warning(f"earnings_fetcher: failed on {ticker}: {type(e).__name__}: {e}")
            continue

    results.sort(key=lambda x: x["earnings_date"])
    if not results:
        logger.error("earnings_fetcher: returned 0 results — possible IP block or API change")
    return results


def _fmt_revenue(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    if val >= 1e6:
        return f"${val/1e6:.0f}M"
    return f"${val:,.0f}"
