"""Database models and session management."""
import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Date, Integer, BigInteger,
    String, create_engine, event
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sp3.db")

# Support postgres in prod, sqlite in dev
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # "S&P 3 Weekly"
    slug = Column(String, unique=True, index=True, nullable=False)  # "sp3-weekly"
    description = Column(String, nullable=True)  # "Top 3 S&P 500 companies by market cap"
    landing_page = Column(String, nullable=False)  # "/landing" for S&P 3
    api_endpoint = Column(String, nullable=False)  # "/api/analytics" for S&P 3
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    unsubscribe_token = Column(String, unique=True, default=lambda: str(uuid.uuid4()))


class WeeklyPick(Base):
    __tablename__ = "weekly_picks"

    id = Column(Integer, primary_key=True, index=True)
    week_date = Column(Date, nullable=False)
    rank = Column(Integer, nullable=False)
    ticker = Column(String, nullable=False)
    name = Column(String, nullable=False)
    market_cap = Column(BigInteger, nullable=False)
    sent_at = Column(DateTime, nullable=True)


class SendLog(Base):
    __tablename__ = "send_logs"

    id = Column(Integer, primary_key=True, index=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    week_date = Column(Date, nullable=False)
    issue_number = Column(Integer, nullable=False)
    total_sent = Column(Integer, default=0)
    total_failed = Column(Integer, default=0)


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, default=date.today, index=True)

    # S&P 3 metrics
    sp3_total_return_pct = Column(Integer, default=0)
    sp3_annualized_return = Column(Integer, default=0)
    sp3_max_drawdown = Column(Integer, default=0)
    sp3_sharpe_ratio = Column(Integer, default=0)
    sp3_volatility = Column(Integer, default=0)
    sp3_position_value = Column(BigInteger, default=0)

    # S&P 500 metrics
    sp500_total_return_pct = Column(Integer, default=0)
    sp500_annualized_return = Column(Integer, default=0)
    sp500_max_drawdown = Column(Integer, default=0)
    sp500_sharpe_ratio = Column(Integer, default=0)
    sp500_volatility = Column(Integer, default=0)

    # Risk Grade
    risk_grade = Column(String, default="B")
    risk_description = Column(String, default="Moderate Risk")

    # Weekly chart data (JSON)
    weekly_chart_data = Column(String, nullable=True)

    # Current S&P 3 allocation (JSON with tickers and weights)
    current_allocation = Column(String, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    calculation_time_ms = Column(Integer, default=0)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_issue_number(db: Session) -> int:
    """Return the next issue number based on distinct week dates sent."""
    from sqlalchemy import func, distinct
    count = db.query(func.count(distinct(WeeklyPick.week_date))).scalar() or 0
    return count + 1
