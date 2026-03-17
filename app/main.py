"""FastAPI application entry point."""
from contextlib import asynccontextmanager
import logging
import os
import json
from datetime import datetime

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from .database import create_tables, SessionLocal, Strategy
    create_tables()
    logger.info("Database tables created/verified")

    # Initialize default strategies
    db = SessionLocal()
    try:
        sp3_exists = db.query(Strategy).filter(Strategy.slug == "sp3-weekly").first()
        if not sp3_exists:
            sp3_strategy = Strategy(
                name="S&P 3 Weekly",
                slug="sp3-weekly",
                description="Invest in the top 3 S&P 500 companies by market cap. $100 per stock, every Friday.",
                landing_page="/sp3",
                api_endpoint="/api/analytics",
                is_active=True
            )
            db.add(sp3_strategy)
            db.commit()
            logger.info("S&P 3 Weekly strategy initialized")
    finally:
        db.close()

    from .scheduler import create_scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started — Friday 6AM ET job registered")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(
    title="S&P 3 Weekly",
    description="Automated newsletter for the S&P 3 investment strategy",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include routers
from .admin import router as admin_router
app.include_router(admin_router)


# Pydantic models
class ChartData(BaseModel):
    dates: list[str]
    sp3_values: list[float]
    sp500_values: list[float]
    principal_values: list[float]


class AllocationItem(BaseModel):
    ticker: str
    weight: float
    value: float
    shares: float


class AnalyticsResponse(BaseModel):
    risk_grade: str
    risk_description: str
    sp3_total_return_pct: float
    sp3_annualized_return: float
    sp3_max_drawdown: float
    sp3_sharpe_ratio: float
    sp3_volatility: float
    sp3_position_value: int
    sp500_total_return_pct: float
    sp500_annualized_return: float
    sp500_max_drawdown: float
    sp500_sharpe_ratio: float
    sp500_volatility: float
    chart_data: ChartData
    current_allocation: list[AllocationItem]
    last_updated: str


class StrategyResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str
    landing_page: str
    api_endpoint: str
    is_active: bool


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/analytics", response_model=AnalyticsResponse)
def get_analytics(db: Session = Depends(lambda: __import__('sqlalchemy.orm', fromlist=['sessionmaker']).sessionmaker(bind=__import__('app.database', fromlist=['engine']).engine)())):
    """Get latest cached analytics snapshot."""
    from .database import AnalyticsSnapshot, SessionLocal, get_db
    from .analytics import refresh_analytics_snapshot
    from datetime import date

    db = SessionLocal()
    try:
        # Get latest snapshot
        snapshot = (
            db.query(AnalyticsSnapshot)
            .order_by(AnalyticsSnapshot.snapshot_date.desc())
            .first()
        )

        # If missing or stale, recalculate
        if not snapshot or (date.today() - snapshot.snapshot_date).days > 0:
            logger.info("Analytics snapshot stale or missing, recalculating...")
            try:
                refresh_analytics_snapshot(db)
                snapshot = (
                    db.query(AnalyticsSnapshot)
                    .order_by(AnalyticsSnapshot.snapshot_date.desc())
                    .first()
                )
            except Exception as e:
                logger.error(f"Failed to refresh analytics: {str(e)}")
                # Try to return the last available snapshot even if stale
                snapshot = (
                    db.query(AnalyticsSnapshot)
                    .order_by(AnalyticsSnapshot.snapshot_date.desc())
                    .first()
                )
                if not snapshot:
                    # No fallback data available - return transparent error
                    logger.error("No analytics data available and calculation failed")
                    return JSONResponse(
                        status_code=503,
                        content={
                            "error": "Analytics data temporarily unavailable",
                            "message": "We're calculating your historical performance data from real market data. This process takes a few minutes on first run. Please refresh in a moment.",
                            "hint": "The analytics endpoint is fetching 10 years of historical S&P 500 price data and computing the S&P 3 strategy performance."
                        }
                    )
                # Return old data with warning
                logger.warning("Returning stale analytics snapshot due to calculation failure")

        if not snapshot:
            return JSONResponse(
                status_code=503,
                content={"error": "Analytics data unavailable"}
            )

        # Parse chart data
        chart_data = json.loads(snapshot.weekly_chart_data or "{}")

        # Parse allocation data
        allocation_raw = json.loads(snapshot.current_allocation or "[]")
        allocation = [
            AllocationItem(
                ticker=item["ticker"],
                weight=item["weight"],
                value=item.get("value", 0),
                shares=item.get("shares", 0)
            )
            for item in allocation_raw
        ]

        return AnalyticsResponse(
            risk_grade=snapshot.risk_grade,
            risk_description=snapshot.risk_description,
            sp3_total_return_pct=snapshot.sp3_total_return_pct,
            sp3_annualized_return=snapshot.sp3_annualized_return,
            sp3_max_drawdown=snapshot.sp3_max_drawdown,
            sp3_sharpe_ratio=snapshot.sp3_sharpe_ratio,
            sp3_volatility=snapshot.sp3_volatility,
            sp3_position_value=snapshot.sp3_position_value,
            sp500_total_return_pct=snapshot.sp500_total_return_pct,
            sp500_annualized_return=snapshot.sp500_annualized_return,
            sp500_max_drawdown=snapshot.sp500_max_drawdown,
            sp500_sharpe_ratio=snapshot.sp500_sharpe_ratio,
            sp500_volatility=snapshot.sp500_volatility or 0.0,
            chart_data=ChartData(
                dates=chart_data.get("dates", []),
                sp3_values=chart_data.get("sp3_values", []),
                sp500_values=chart_data.get("sp500_values", []),
                principal_values=chart_data.get("principal_values", []),
            ),
            current_allocation=allocation,
            last_updated=snapshot.created_at.isoformat(),
        )
    finally:
        db.close()


@app.get("/api/strategies", response_model=list[StrategyResponse])
def get_strategies(db: Session = Depends(lambda: __import__('sqlalchemy.orm', fromlist=['sessionmaker']).sessionmaker(bind=__import__('app.database', fromlist=['engine']).engine)())):
    """Get all available strategies."""
    from .database import Strategy
    strategies = db.query(Strategy).all()
    db.close()
    return strategies


@app.get("/sp3", response_class=HTMLResponse)
def sp3_page(request: Request):
    """S&P 3 Weekly strategy page with explanation, performance analysis, and risk grade."""
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/subscribe", response_class=HTMLResponse)
def subscribe_page(request: Request):
    """Subscription form page."""
    return templates.TemplateResponse("subscribe.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
def home_page(request: Request):
    """Home page with strategy cards."""
    return templates.TemplateResponse("home.html", {"request": request})
