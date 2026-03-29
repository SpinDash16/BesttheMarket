"""Admin and subscriber API routes."""
import os
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from .database import Subscriber, WeeklyPick, SendLog, get_db, get_issue_number
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class SendRequest(BaseModel):
    strategy: Optional[str] = None  # None = send to all strategies


class SubscribeRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    strategy: Optional[str] = "sp3"


class SubscribeResponse(BaseModel):
    message: str
    unsubscribe_token: Optional[str] = None


# ─── Auth helper ──────────────────────────────────────────────────────────────

def require_admin(x_admin_secret: str = Header(None)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


# ─── Public routes ────────────────────────────────────────────────────────────

@router.post("/sp3subscribe", response_model=SubscribeResponse)
def subscribe(payload: SubscribeRequest, db: Session = Depends(get_db)):
    existing = db.query(Subscriber).filter(Subscriber.email == payload.email).first()
    if existing:
        if existing.is_active:
            return SubscribeResponse(message="You're already subscribed!")
        # Reactivate
        existing.is_active = True
        db.commit()
        return SubscribeResponse(
            message="Welcome back! You've been resubscribed.",
            unsubscribe_token=existing.unsubscribe_token,
        )

    sub = Subscriber(
        email=payload.email,
        name=payload.name,
        strategy=payload.strategy or "sp3",
        unsubscribe_token=str(uuid.uuid4()),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return SubscribeResponse(
        message="You're subscribed! Expect your first issue this Friday.",
        unsubscribe_token=sub.unsubscribe_token,
    )


@router.get("/unsubscribe/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    sub = db.query(Subscriber).filter(Subscriber.unsubscribe_token == token).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Token not found")
    sub.is_active = False
    db.commit()
    return HTMLResponse(
        "<html><body style='font-family:Georgia;padding:40px;background:#f5f3ee;'>"
        "<h2>You've been unsubscribed.</h2>"
        "<p>You won't receive any more S&P 3 Weekly emails.</p>"
        "</body></html>"
    )


# ─── Admin routes ─────────────────────────────────────────────────────────────

@router.get("/subscribers", dependencies=[Depends(require_admin)])
def list_subscribers(strategy: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Subscriber)
    if strategy:
        q = q.filter(Subscriber.strategy == strategy)
    subs = q.order_by(Subscriber.subscribed_at.desc()).all()
    return [
        {
            "id": s.id,
            "email": s.email,
            "name": s.name,
            "strategy": s.strategy,
            "subscribed_at": s.subscribed_at.isoformat() if s.subscribed_at else None,
            "is_active": s.is_active,
        }
        for s in subs
    ]


@router.get("/picks/history", dependencies=[Depends(require_admin)])
def picks_history(db: Session = Depends(get_db)):
    picks = (
        db.query(WeeklyPick)
        .order_by(WeeklyPick.week_date.desc(), WeeklyPick.rank)
        .limit(36)
        .all()
    )
    return [
        {
            "week_date": str(p.week_date),
            "rank": p.rank,
            "ticker": p.ticker,
            "name": p.name,
            "market_cap": p.market_cap,
            "sent_at": p.sent_at.isoformat() if p.sent_at else None,
        }
        for p in picks
    ]


@router.post("/send-preview", dependencies=[Depends(require_admin)])
async def trigger_preview(payload: SendRequest = SendRequest(), db: Session = Depends(get_db)):
    from .mailer import send_preview as do_send_preview

    strategy = payload.strategy or "sp3"

    if strategy == "sf":
        from .sf_fetcher import get_silicon_fund_picks
        from .sf_newsletter import generate_sf_newsletter
        picks = get_silicon_fund_picks(n=5)
        issue_number = get_issue_number(db)
        html = generate_sf_newsletter(picks=picks, week_date=date.today(), issue_number=issue_number)
        subject_picks = [{"ticker": p["ticker"], "rank": i+1} for i, p in enumerate(picks)]
    else:
        from .fetcher import get_top_n_sp500
        from .newsletter import generate_newsletter
        picks = get_top_n_sp500(n=3)
        issue_number = get_issue_number(db)
        html = generate_newsletter(picks=picks, week_date=date.today(), issue_number=issue_number)
        subject_picks = picks

    ok = do_send_preview(ADMIN_EMAIL, html, date.today(), subject_picks)
    if not ok:
        raise HTTPException(status_code=500, detail="Preview send failed — check RESEND_API_KEY and ADMIN_EMAIL")
    return {"status": "ok", "message": f"{strategy.upper()} preview sent to {ADMIN_EMAIL}"}


@router.post("/send-now", dependencies=[Depends(require_admin)])
async def trigger_send(payload: SendRequest = SendRequest(), db: Session = Depends(get_db)):
    from .fetcher import get_top_n_sp500
    from .newsletter import generate_newsletter
    from .mailer import send_to_all_subscribers
    from .database import WeeklyPick, get_issue_number

    picks = get_top_n_sp500(n=3)
    issue_number = get_issue_number(db)
    html = generate_newsletter(picks=picks, week_date=date.today(), issue_number=issue_number)
    result = send_to_all_subscribers(db, html, date.today(), picks, strategy=payload.strategy)
    label = payload.strategy.upper() if payload.strategy else "all strategies"
    return {"status": "ok", "message": f"Sent {result['sent']} emails to {label} subscribers ({result['failed']} failed)"}


@router.post("/admin/trigger-send", dependencies=[Depends(require_admin)])
async def admin_trigger_send(db: Session = Depends(get_db)):
    from .scheduler import weekly_send_job
    await weekly_send_job()
    return {"status": "ok", "message": "Weekly send job triggered manually"}


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, secret: str = "", db: Session = Depends(get_db)):
    if secret != ADMIN_SECRET:
        return HTMLResponse(
            "<html><body style='font-family:Georgia;padding:40px;background:#f5f3ee;'>"
            "<h2>Access denied.</h2><p>Include ?secret=YOUR_ADMIN_SECRET</p>"
            "</body></html>",
            status_code=403,
        )

    total = db.query(func.count(Subscriber.id)).filter(Subscriber.is_active == True).scalar() or 0
    strategy_counts = dict(
        db.query(Subscriber.strategy, func.count(Subscriber.id))
        .filter(Subscriber.is_active == True)
        .group_by(Subscriber.strategy)
        .all()
    )
    picks_history = (
        db.query(WeeklyPick)
        .order_by(WeeklyPick.week_date.desc(), WeeklyPick.rank)
        .limit(24)
        .all()
    )

    try:
        from .fetcher import get_top_n_sp500
        live_picks = get_top_n_sp500(3)
    except Exception:
        live_picks = []

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "total_subscribers": total,
            "strategy_counts": strategy_counts,
            "live_picks": live_picks,
            "picks_history": picks_history,
            "secret": secret,
        },
    )
