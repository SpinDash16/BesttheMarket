"""Newsletter HTML generator using Jinja2."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _next_friday(from_date: Optional[date] = None) -> str:
    d = from_date or date.today()
    days_ahead = (4 - d.weekday()) % 7  # 4 = Friday
    if days_ahead == 0:
        days_ahead = 7
    nf = d + timedelta(days=days_ahead)
    return nf.strftime("%b %-d, %Y")


def _format_week_date(d: date) -> str:
    return d.strftime("%B %-d, %Y")


def _build_thesis(pick: dict) -> str:
    """Generate a one-sentence analyst note for a pick."""
    theses = {
        "NVDA": (
            "First company in history to cross $4 trillion in market cap; "
            "AI GPU demand from hyperscalers shows no signs of slowing through 2027."
        ),
        "AAPL": (
            "Services revenue continues to expand margins while Apple Intelligence "
            "rollout drives the installed base of 2B+ devices deeper into the ecosystem."
        ),
        "GOOGL": (
            "Gemini AI integration across Search and Workspace is gaining traction while "
            "Google Cloud sustains double-digit growth, keeping Alphabet ahead of Microsoft."
        ),
        "MSFT": (
            "Azure AI growth and Copilot integration across Microsoft 365 are driving "
            "enterprise cloud expansion, keeping Microsoft within striking range of #3."
        ),
        "AMZN": (
            "AWS remains the dominant cloud platform while advertising revenue provides "
            "a high-margin diversification layer on top of its retail business."
        ),
        "META": (
            "Advertising platform recovery plus AI-driven engagement improvements are "
            "fueling revenue growth as the Reality Labs bet remains a long-term optionality."
        ),
    }
    return theses.get(
        pick["ticker"],
        f"{pick['name']} holds its position as one of the most valuable companies "
        "in the S&P 500 by market cap.",
    )


def generate_newsletter(
    picks: list[dict],
    week_date: date,
    issue_number: int,
    unsubscribe_token: str = "{{token}}",
    watchlist: Optional[list[dict]] = None,
    contribution_per_stock: int = 100,
) -> str:
    """Render the newsletter HTML for a given week's picks."""
    if watchlist is None:
        watchlist = []

    # Enrich picks with thesis
    enriched = []
    for p in picks:
        ep = dict(p)
        ep.setdefault("thesis", _build_thesis(p))
        enriched.append(ep)

    total_deploy = contribution_per_stock * len(picks)
    next_buy = _next_friday(week_date)
    formatted_date = _format_week_date(week_date)

    unsubscribe_url = f"https://sp3weekly.com/unsubscribe/{unsubscribe_token}"

    ctx = {
        "issue_number": issue_number,
        "week_date": formatted_date,
        "next_friday": next_buy,
        "picks": enriched,
        "watchlist": watchlist,
        "contribution_per_stock": contribution_per_stock,
        "total_weekly_deploy": total_deploy,
        "unsubscribe_url": unsubscribe_url,
        "ticker_line": " · ".join(
            f"#{p['rank']} {p['ticker']} {p['market_cap_display']}"
            for p in enriched
        ),
    }

    template = _env.get_template("newsletter.html")
    return template.render(**ctx)
