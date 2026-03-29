"""Email sending via Resend API."""
from __future__ import annotations
import logging
import os
import time
from datetime import date
from typing import Optional

import resend
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from .database import Subscriber, WeeklyPick
from datetime import datetime

load_dotenv()

logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "S&P 3 Weekly <sp3weekly@yourdomain.com>")
REPLY_TO = os.getenv("REPLY_TO", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

BATCH_SIZE = 50
BATCH_DELAY = 1.0  # seconds between batches


def _build_subject(picks: list[dict], week_date: date, strategy: Optional[str] = None) -> str:
    tickers = " · ".join(p["ticker"] for p in picks[:3])
    date_str = week_date.strftime("%b %-d")
    if strategy == "sf":
        return f"The Silicon Fund: {tickers} — Week of {date_str}"
    return f"S&P 3 Weekly: {tickers} — Week of {date_str}"


def send_newsletter(
    subscriber_email: str,
    subscriber_name: Optional[str],
    html_content: str,
    week_date: date,
    picks: list[dict],
    strategy: Optional[str] = None,
) -> bool:
    subject = _build_subject(picks, week_date, strategy)
    params = {
        "from": FROM_EMAIL,
        "to": [subscriber_email],
        "subject": subject,
        "html": html_content,
    }
    if REPLY_TO:
        params["reply_to"] = REPLY_TO

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resend.Emails.send(params)
            logger.info(f"Sent to {subscriber_email}")
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"Retry {attempt+1} for {subscriber_email}: {e}. Waiting {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"Failed to send to {subscriber_email}: {e}")
                return False
    return False


def send_to_all_subscribers(
    db: Session,
    html_template: str,
    week_date: date,
    picks: list[dict],
    strategy: Optional[str] = None,
) -> dict:
    """Send personalized newsletters to active subscribers, optionally filtered by strategy."""
    q = db.query(Subscriber).filter(Subscriber.is_active == True)
    if strategy:
        q = q.filter(Subscriber.strategy == strategy)
    subscribers = q.all()

    sent_count = 0
    failed_count = 0
    errors = []

    for i in range(0, len(subscribers), BATCH_SIZE):
        batch = subscribers[i : i + BATCH_SIZE]
        for sub in batch:
            # Personalize unsubscribe URL
            personal_html = html_template.replace(
                "{{token}}", sub.unsubscribe_token
            ).replace(
                "https://sp3weekly.com/unsubscribe/{{token}}",
                f"https://sp3weekly.com/unsubscribe/{sub.unsubscribe_token}",
            )
            ok = send_newsletter(
                sub.email, sub.name, personal_html, week_date, picks, strategy=strategy
            )
            if ok:
                sent_count += 1
            else:
                failed_count += 1
                errors.append(sub.email)

        if i + BATCH_SIZE < len(subscribers):
            time.sleep(BATCH_DELAY)

    # Mark sent_at on WeeklyPick records for this week
    db.query(WeeklyPick).filter(
        WeeklyPick.week_date == week_date,
        WeeklyPick.sent_at == None,
    ).update({"sent_at": datetime.utcnow()})
    db.commit()

    return {"sent": sent_count, "failed": failed_count, "errors": errors}


def send_pdf_preview(admin_email: str, subject: str, filename: str, pdf_b64: str) -> bool:
    """Send a PDF newsletter as an attachment preview to the admin."""
    params = {
        "from": FROM_EMAIL,
        "to": [admin_email],
        "subject": f"[PREVIEW] {subject}",
        "html": f"<p>Preview of <strong>{filename}</strong>. See attached PDF.</p>",
        "attachments": [{"filename": filename, "content": pdf_b64}],
    }
    if REPLY_TO:
        params["reply_to"] = REPLY_TO
    try:
        resend.Emails.send(params)
        logger.info(f"PDF preview sent to {admin_email}")
        return True
    except Exception as e:
        logger.error(f"PDF preview send failed: {e}")
        return False


def send_pdf_to_subscribers(
    db: Session,
    subject: str,
    filename: str,
    pdf_b64: str,
    strategy: Optional[str] = None,
) -> dict:
    """Send a PDF newsletter attachment to active subscribers."""
    q = db.query(Subscriber).filter(Subscriber.is_active == True)
    if strategy:
        q = q.filter(Subscriber.strategy == strategy)
    subscribers = q.all()

    sent_count = 0
    failed_count = 0
    errors = []

    for i in range(0, len(subscribers), BATCH_SIZE):
        batch = subscribers[i : i + BATCH_SIZE]
        for sub in batch:
            params = {
                "from": FROM_EMAIL,
                "to": [sub.email],
                "subject": subject,
                "html": f"<p>This week's newsletter is attached as a PDF. See <strong>{filename}</strong>.</p>"
                        f"<p style='font-size:12px;color:#999;'>"
                        f"<a href='https://bestingthemarket.com/unsubscribe/{sub.unsubscribe_token}'>Unsubscribe</a></p>",
                "attachments": [{"filename": filename, "content": pdf_b64}],
            }
            if REPLY_TO:
                params["reply_to"] = REPLY_TO
            try:
                resend.Emails.send(params)
                sent_count += 1
                logger.info(f"PDF sent to {sub.email}")
            except Exception as e:
                failed_count += 1
                errors.append(sub.email)
                logger.error(f"PDF send failed for {sub.email}: {e}")

        if i + BATCH_SIZE < len(subscribers):
            time.sleep(BATCH_DELAY)

    return {"sent": sent_count, "failed": failed_count, "errors": errors}


def send_preview(admin_email: str, html_content: str, week_date: date, picks: list[dict], strategy: Optional[str] = None) -> bool:
    subject = "[PREVIEW] " + _build_subject(picks, week_date, strategy)
    params = {
        "from": FROM_EMAIL,
        "to": [admin_email],
        "subject": subject,
        "html": html_content,
    }
    if REPLY_TO:
        params["reply_to"] = REPLY_TO
    try:
        resend.Emails.send(params)
        logger.info(f"Preview sent to {admin_email}")
        return True
    except Exception as e:
        logger.error(f"Preview send failed: {e}")
        return False
