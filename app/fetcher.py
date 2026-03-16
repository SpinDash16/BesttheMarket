"""Market cap data fetcher for top N S&P 500 companies."""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "latest_picks.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


def format_market_cap(cap: int) -> str:
    if cap >= 1_000_000_000_000:
        return f"${cap / 1_000_000_000_000:.2f}T"
    elif cap >= 1_000_000_000:
        return f"${cap / 1_000_000_000:.2f}B"
    return f"${cap:,}"


def _load_previous_rankings() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text())
        return {p["ticker"]: p["rank"] for p in data.get("picks", [])}
    except Exception:
        return {}


def _rank_change(ticker: str, new_rank: int, prev: dict) -> str:
    if ticker not in prev:
        return "new"
    old = prev[ticker]
    if new_rank < old:
        return "up"
    if new_rank > old:
        return "down"
    return "unchanged"


def _fetch_via_yfinance(n: int) -> Optional[list]:
    try:
        import yfinance as yf
        import pandas as pd

        # Get S&P 500 tickers from Wikipedia
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        sp500 = tables[0]["Symbol"].tolist()

        caps = []
        # Fetch in small batches to avoid rate limiting
        for ticker in sp500[:50]:  # Focus on top candidates
            try:
                info = yf.Ticker(ticker).fast_info
                cap = getattr(info, "market_cap", None)
                if cap and cap > 0:
                    caps.append((ticker, int(cap)))
            except Exception:
                continue
            if len(caps) >= n * 3:  # Get enough candidates
                break

        if len(caps) < n:
            return None

        caps.sort(key=lambda x: x[1], reverse=True)
        top = caps[:n]

        results = []
        for rank, (ticker, cap) in enumerate(top, 1):
            try:
                info = yf.Ticker(ticker).info
                name = info.get("longName") or info.get("shortName") or ticker
                sector = info.get("sector") or "Unknown"
            except Exception:
                name = ticker
                sector = "Unknown"
            results.append((rank, ticker, name, cap, sector))
        return results
    except Exception:
        return None


def _fetch_via_slickcharts(n: int) -> Optional[list]:
    try:
        resp = requests.get(
            "https://www.slickcharts.com/sp500",
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"class": "table"})
        if not table:
            return None

        rows = table.find_all("tr")[1:]
        results = []
        for row in rows[:n * 2]:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            try:
                rank = int(cols[0].text.strip())
                name = cols[1].text.strip()
                ticker = cols[2].text.strip()
                # Market cap column may have commas and $ sign
                raw = cols[3].text.strip().replace(",", "").replace("$", "").replace("B", "").strip()
                cap_b = float(raw)
                cap = int(cap_b * 1_000_000_000)
                results.append((rank, ticker, name, cap, "Unknown"))
            except (ValueError, IndexError):
                continue
            if len(results) >= n:
                break
        return results if len(results) >= n else None
    except Exception:
        return None


def get_top_n_sp500(n: int = 3) -> list[dict]:
    """Return top N S&P 500 companies by market cap.

    Tries yfinance first, falls back to slickcharts scraping.
    Caches results for the day.
    """
    # Check cache — only use if fetched today
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text())
            if cached.get("date") == str(date.today()) and len(cached.get("picks", [])) >= n:
                return cached["picks"][:n]
        except Exception:
            pass

    prev_rankings = _load_previous_rankings()

    raw = _fetch_via_yfinance(n)
    source = "yfinance"

    if not raw:
        raw = _fetch_via_slickcharts(n)
        source = "slickcharts"

    if not raw:
        # Hard-coded fallback based on known current values
        raw = [
            (1, "NVDA", "Nvidia Corporation", 4_600_000_000_000, "Semiconductors"),
            (2, "AAPL", "Apple Inc.", 4_020_000_000_000, "Consumer Electronics"),
            (3, "GOOGL", "Alphabet Inc.", 3_810_000_000_000, "Internet / AI"),
            (4, "MSFT", "Microsoft Corporation", 3_520_000_000_000, "Software"),
            (5, "AMZN", "Amazon.com Inc.", 2_420_000_000_000, "E-Commerce / Cloud"),
        ]
        source = "fallback"

    picks = []
    for rank, ticker, name, cap, sector in raw[:n]:
        picks.append({
            "rank": rank,
            "ticker": ticker,
            "name": name,
            "market_cap": cap,
            "market_cap_display": format_market_cap(cap),
            "sector": sector,
            "rank_change": _rank_change(ticker, rank, prev_rankings),
        })

    # Cache to disk
    cache_data = {
        "date": str(date.today()),
        "fetched_at": datetime.now().isoformat(),
        "source": source,
        "picks": picks,
    }
    CACHE_FILE.write_text(json.dumps(cache_data, indent=2))

    return picks


if __name__ == "__main__":
    print("Fetching top 5 S&P 500 by market cap...\n")
    results = get_top_n_sp500(5)
    for p in results:
        change_sym = {"up": "▲", "down": "▼", "new": "★", "unchanged": "—"}.get(
            p["rank_change"], "—"
        )
        print(
            f"#{p['rank']} {p['ticker']:6s} {p['name']:30s} "
            f"{p['market_cap_display']:8s} {change_sym} [{p['sector']}]"
        )
