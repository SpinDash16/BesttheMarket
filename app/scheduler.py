"""APScheduler Friday cron job for automated weekly sends."""
import logging
import logging.handlers
import os
from datetime import date
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("sp3.scheduler")
logger.setLevel(logging.INFO)

_handler = logging.handlers.RotatingFileHandler(
    LOGS_DIR / "sends.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_handler)
logger.addHandler(logging.StreamHandler())

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")


async def weekly_send_job():
    """Run the full weekly send pipeline."""
    from .database import SessionLocal, WeeklyPick, get_issue_number
    from .fetcher import get_top_n_sp500
    from .newsletter import generate_newsletter
    from .mailer import send_to_all_subscribers, send_preview

    logger.info("=== Weekly S&P 3 send job starting ===")
    db = SessionLocal()
    today = date.today()

    try:
        # 1. Fetch picks
        try:
            picks = get_top_n_sp500(n=3)
            logger.info(f"Picks fetched: {[p['ticker'] for p in picks]}")
        except Exception as e:
            logger.error(f"Fetcher failed: {e}")
            if ADMIN_EMAIL:
                from .mailer import send_preview
                send_preview(
                    ADMIN_EMAIL,
                    f"<p>S&P 3 Weekly send failed — fetcher error: {e}</p>",
                    today,
                    [],
                )
            return

        # 2. Determine issue number
        issue_number = get_issue_number(db)

        # 3. Save picks to DB
        for pick in picks:
            db.add(WeeklyPick(
                week_date=today,
                rank=pick["rank"],
                ticker=pick["ticker"],
                name=pick["name"],
                market_cap=pick["market_cap"],
            ))
        db.commit()

        # 4. Build watchlist (ranks 4-6)
        try:
            all_picks = get_top_n_sp500(n=6)
            watchlist = [
                {"ticker": p["ticker"], "name": p["name"],
                 "market_cap_display": p["market_cap_display"],
                 "note": f"#{p['rank']} — ${p['market_cap_display']}"}
                for p in all_picks[3:]
            ]
        except Exception:
            watchlist = []

        # 5. Generate HTML
        html = generate_newsletter(
            picks=picks,
            week_date=today,
            issue_number=issue_number,
            watchlist=watchlist,
        )

        # 6. Send to all subscribers
        result = send_to_all_subscribers(db, html, today, picks)
        logger.info(
            f"Send complete — sent: {result['sent']}, failed: {result['failed']}"
        )
        if result["errors"]:
            logger.warning(f"Failed addresses: {result['errors']}")

    except Exception as e:
        logger.exception(f"Unexpected error in weekly_send_job: {e}")
    finally:
        db.close()


async def daily_analytics_refresh_job():
    """Run daily analytics snapshot refresh (15-year backtest)."""
    from .database import SessionLocal
    from .analytics import refresh_analytics_snapshot

    logger.info("=== Daily analytics refresh starting ===")
    db = SessionLocal()
    try:
        refresh_analytics_snapshot(db)
        logger.info("✓ Daily analytics refresh complete")
    except Exception as e:
        logger.error(f"✗ Analytics refresh failed: {e}", exc_info=True)
    finally:
        db.close()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="America/New_York")

    # Friday 6 AM: Weekly send job
    scheduler.add_job(
        weekly_send_job,
        CronTrigger(day_of_week="fri", hour=6, minute=0, timezone="America/New_York"),
        id="weekly_send",
        name="S&P 3 Weekly Friday Send",
        replace_existing=True,
    )

    # Daily 8 AM: Analytics refresh
    scheduler.add_job(
        daily_analytics_refresh_job,
        CronTrigger(hour=8, minute=0, timezone="America/New_York"),
        id="daily_analytics",
        name="Daily Analytics Snapshot Refresh",
        replace_existing=True,
    )

    return scheduler
