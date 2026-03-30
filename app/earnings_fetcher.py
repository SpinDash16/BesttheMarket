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
            cal = t.calendar or {}
            dates = cal.get("Earnings Date", [])
            if not dates:
                continue

            # Grab the nearest upcoming date
            upcoming = [d for d in dates if isinstance(d, date) and today <= d <= cutoff]
            if not upcoming:
                continue

            earnings_date = min(upcoming)
            days_away = (earnings_date - today).days

            info = t.fast_info
            name = getattr(info, "short_name", None) or default_name

            results.append({
                "ticker":            ticker,
                "name":              name,
                "earnings_date":     earnings_date.isoformat(),
                "earnings_date_fmt": earnings_date.strftime("%b %-d, %Y"),
                "weekday":           earnings_date.strftime("%A"),
                "eps_estimate":      round(cal.get("Earnings Average", 0), 2) if cal.get("Earnings Average") else None,
                "eps_high":          round(cal.get("Earnings High", 0), 2) if cal.get("Earnings High") else None,
                "eps_low":           round(cal.get("Earnings Low", 0), 2) if cal.get("Earnings Low") else None,
                "revenue_estimate":  cal.get("Revenue Average"),
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
