"""Silicon Fund newsletter HTML generator."""
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
    days_ahead = (4 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (d + timedelta(days=days_ahead)).strftime("%b %-d, %Y")


def generate_sf_newsletter(
    picks: list[dict],
    week_date: date,
    issue_number: int,
    unsubscribe_token: str = "{{token}}",
) -> str:
    unsubscribe_url = f"https://bestingthemarket.com/unsubscribe/{unsubscribe_token}"
    ctx = {
        "issue_number":    issue_number,
        "week_date":       week_date.strftime("%B %-d, %Y"),
        "next_friday":     _next_friday(week_date),
        "picks":           picks,
        "unsubscribe_url": unsubscribe_url,
        "ticker_line":     " · ".join(p["ticker"] for p in picks),
    }
    template = _env.get_template("sf_newsletter.html")
    return template.render(**ctx)
