"""Silicon Fund — emerging tech stock fetcher with news-based ranking."""
from __future__ import annotations
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Curated universe of emerging & growth tech stocks
SILICON_FUND_UNIVERSE = [
    # AI & Chips
    ("NVDA", "Nvidia Corporation"),
    ("AMD", "Advanced Micro Devices"),
    ("SMCI", "Super Micro Computer"),
    ("ARM", "Arm Holdings"),
    ("INTC", "Intel Corporation"),
    # AI Software & Data
    ("PLTR", "Palantir Technologies"),
    ("AI", "C3.ai"),
    ("SNOW", "Snowflake"),
    ("DDOG", "Datadog"),
    # Cloud & Cybersecurity
    ("NET", "Cloudflare"),
    ("CRWD", "CrowdStrike"),
    ("ZS", "Zscaler"),
    ("PANW", "Palo Alto Networks"),
    ("OKTA", "Okta"),
    # EV & Clean Tech
    ("TSLA", "Tesla"),
    ("RIVN", "Rivian Automotive"),
    # Fintech & Crypto
    ("COIN", "Coinbase"),
    ("SQ", "Block"),
    ("HOOD", "Robinhood Markets"),
    # Quantum & Space
    ("IONQ", "IonQ"),
    ("RGTI", "Rigetti Computing"),
    ("RKLB", "Rocket Lab USA"),
    # Semiconductors
    ("AVGO", "Broadcom"),
    ("MRVL", "Marvell Technology"),
    ("QCOM", "Qualcomm"),
    # Big Tech (always in the headlines)
    ("META", "Meta Platforms"),
    ("MSFT", "Microsoft"),
    ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"),
]

# Brief context blurbs for known tickers used in newsletter insights
_INSIGHTS = {
    "NVDA": "Nvidia dominates the AI accelerator market with its H100 and Blackwell GPUs powering virtually every major AI data centre buildout.",
    "AMD": "AMD is gaining share in the AI chip market with its MI300X accelerator while its CPU business continues to take enterprise market share from Intel.",
    "PLTR": "Palantir's AI Platform (AIP) is winning enterprise and government contracts at a record pace, positioning it as the operating system for AI deployments.",
    "NET": "Cloudflare is rapidly expanding from CDN into a full AI-native networking and security platform, intercepting traffic at the edge for millions of businesses.",
    "CRWD": "CrowdStrike continues to consolidate the endpoint security market with its Falcon platform, benefiting from enterprise security consolidation trends.",
    "SNOW": "Snowflake's data cloud is becoming the default enterprise AI data layer, with partnerships across every major hyperscaler.",
    "DDOG": "Datadog is the de facto observability platform for cloud-native companies, expanding into AI observability as enterprises monitor their LLM workloads.",
    "TSLA": "Tesla remains the leading EV brand globally while its full self-driving (FSD) and robotaxi ambitions keep it at the intersection of AI and automotive.",
    "COIN": "Coinbase is the dominant US crypto exchange, benefiting from rising institutional adoption and the regulatory clarity emerging from Washington.",
    "SMCI": "Super Micro Computer is a key infrastructure beneficiary of AI server demand, supplying liquid-cooled rack systems to hyperscalers at record volumes.",
    "ARM": "Arm's CPU architecture powers over 99% of smartphones and is rapidly expanding into data centres, PCs, and AI edge devices.",
    "IONQ": "IonQ is a leading pure-play quantum computing company, recently winning key government contracts as quantum computing moves closer to practical applications.",
    "RKLB": "Rocket Lab is emerging as the #2 US launch provider with its Electron rocket while developing the larger Neutron vehicle to compete with SpaceX.",
    "META": "Meta's AI investments are paying off — its ad platform is the most profitable in mobile while Llama open-source models attract enterprise developers.",
    "MSFT": "Microsoft's Azure AI and Copilot products are the leading enterprise AI deployment platform, with OpenAI partnership giving it first-mover advantage.",
    "AVGO": "Broadcom is a direct AI infrastructure beneficiary — its custom AI chips for Google and Meta generate billions in revenue alongside its networking business.",
    "PANW": "Palo Alto Networks is platformizing enterprise cybersecurity, using AI to consolidate dozens of point solutions into one managed security platform.",
    "RIVN": "Rivian's partnership with Volkswagen Group provides a lifeline of capital and validation as it scales production of its R1 and commercial van platforms.",
    "QCOM": "Qualcomm is positioning its Snapdragon chips as the standard for on-device AI, targeting PC, automotive, and IoT markets beyond smartphones.",
}


def get_silicon_fund_picks(n: int = 5) -> list[dict]:
    """Return top N emerging tech stocks ranked by recent news volume + recency."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — returning placeholder picks")
        return _placeholder_picks(n)

    one_week_ago = time.time() - 7 * 24 * 3600
    scored: list[dict] = []

    for ticker, default_name in SILICON_FUND_UNIVERSE:
        try:
            t = yf.Ticker(ticker)
            news = t.news or []
            info = t.fast_info

            recent = [a for a in news if a.get("providerPublishTime", 0) > one_week_ago]
            if not recent:
                continue

            # Score = articles in last 7 days, weighted by recency
            score = sum(
                1 + (a.get("providerPublishTime", 0) - one_week_ago) / (7 * 24 * 3600)
                for a in recent
            )

            price = getattr(info, "last_price", None)
            prev  = getattr(info, "previous_close", None)
            pct   = round(((price - prev) / prev) * 100, 2) if price and prev and prev != 0 else None

            top = recent[0]
            scored.append({
                "ticker":        ticker,
                "name":          getattr(info, "short_name", None) or default_name,
                "price":         round(price, 2) if price else None,
                "price_display": f"${price:,.2f}" if price else "N/A",
                "pct_change":    pct,
                "pct_display":   f"{'+'  if pct and pct >= 0 else ''}{pct:.1f}%" if pct is not None else "N/A",
                "pct_positive":  pct is not None and pct >= 0,
                "news_count":    len(recent),
                "score":         score,
                "headline":      top.get("title", ""),
                "insight":       _INSIGHTS.get(ticker, f"{default_name} is generating significant market attention this week."),
                "source":        top.get("publisher", ""),
                "news_url":      top.get("link", ""),
            })
        except Exception as e:
            logger.warning(f"sf_fetcher: failed on {ticker}: {e}")
            continue

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:n]


def _placeholder_picks(n: int) -> list[dict]:
    samples = [
        {
            "ticker": "NVDA", "name": "Nvidia Corporation",
            "price": 875.40, "price_display": "$875.40",
            "pct_change": 3.2, "pct_display": "+3.2%", "pct_positive": True,
            "news_count": 14, "score": 14.0,
            "headline": "Nvidia Blackwell GPU shipments hit record levels as AI buildout accelerates",
            "insight": _INSIGHTS["NVDA"], "source": "Reuters", "news_url": "#",
        },
        {
            "ticker": "PLTR", "name": "Palantir Technologies",
            "price": 24.85, "price_display": "$24.85",
            "pct_change": 5.1, "pct_display": "+5.1%", "pct_positive": True,
            "news_count": 9, "score": 9.0,
            "headline": "Palantir wins major US Army AI contract extension worth $400M",
            "insight": _INSIGHTS["PLTR"], "source": "Bloomberg", "news_url": "#",
        },
        {
            "ticker": "CRWD", "name": "CrowdStrike",
            "price": 298.10, "price_display": "$298.10",
            "pct_change": -1.4, "pct_display": "-1.4%", "pct_positive": False,
            "news_count": 7, "score": 7.0,
            "headline": "CrowdStrike Falcon platform gains 500 new enterprise customers in Q1",
            "insight": _INSIGHTS["CRWD"], "source": "CNBC", "news_url": "#",
        },
    ]
    return samples[:n]
