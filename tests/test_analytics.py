"""Tests for analytics module and /api/analytics endpoint."""

import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, AnalyticsSnapshot
from app.analytics import (
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_cagr,
    calculate_volatility,
    calculate_risk_grade,
    calculate_metrics,
)


# Test database setup
@pytest.fixture
def test_db():
    """Create an in-memory SQLite test database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    yield db
    db.close()


# Unit Tests

def test_sharpe_ratio_calculation():
    """Test Sharpe ratio calculation."""
    # Simple series with expected Sharpe ratio
    returns = pd.Series([0.01, 0.02, -0.01, 0.015, 0.005])
    sharpe = calculate_sharpe_ratio(returns)

    assert sharpe is not None
    assert isinstance(sharpe, (int, float))
    assert sharpe > -1  # Should be reasonable (not extremely negative)


def test_sharpe_ratio_zero_volatility():
    """Test Sharpe ratio with zero volatility (flat returns)."""
    returns = pd.Series([0.01, 0.01, 0.01, 0.01])
    sharpe = calculate_sharpe_ratio(returns)

    # Zero volatility should return None
    assert sharpe is None


def test_max_drawdown_calculation():
    """Test maximum drawdown calculation."""
    # Portfolio values: $1000 → $1200 → $900 → $1100
    # Max drawdown: (900-1200)/1200 = -25%
    portfolio_values = [1000, 1200, 900, 1100]
    max_dd = calculate_max_drawdown(portfolio_values)

    assert max_dd is not None
    assert 0.24 < max_dd < 0.26  # ~25%


def test_max_drawdown_no_decline():
    """Test max drawdown with only gains."""
    portfolio_values = [1000, 1100, 1200, 1300, 1400]
    max_dd = calculate_max_drawdown(portfolio_values)

    assert max_dd == 0.0  # No drawdown


def test_max_drawdown_only_decline():
    """Test max drawdown with only losses."""
    portfolio_values = [1000, 900, 800, 700]
    max_dd = calculate_max_drawdown(portfolio_values)

    # Peak is 1000, trough is 700: (700-1000)/1000 = -30%
    assert 0.29 < max_dd < 0.31


def test_cagr_calculation():
    """Test CAGR (Compound Annual Growth Rate) calculation."""
    # $1000 → $2000 over 1 year = 100% CAGR
    cagr = calculate_cagr(1000, 2000, 1)
    assert 0.99 < cagr < 1.01  # ~100%

    # $1000 → $1000 over 1 year = 0% CAGR
    cagr = calculate_cagr(1000, 1000, 1)
    assert -0.01 < cagr < 0.01  # ~0%

    # $1000 → $1100 over 1 year = 10% CAGR
    cagr = calculate_cagr(1000, 1100, 1)
    assert 0.09 < cagr < 0.11  # ~10%


def test_volatility_calculation():
    """Test annualized volatility calculation."""
    # Create a series with known volatility
    np.random.seed(42)
    values = np.cumsum(np.random.randn(100) * 10) + 1000
    volatility = calculate_volatility(list(values))

    assert volatility is not None
    assert volatility > 0
    assert isinstance(volatility, (int, float))


def test_risk_grade_low_risk():
    """Test risk grade calculation for low-risk scenario."""
    sp3_metrics = {
        "volatility": 0.10,  # 10% vol
        "max_drawdown": 0.15,  # 15% drawdown
    }
    sp500_metrics = {
        "volatility": 0.12,  # Higher vol
        "max_drawdown": 0.20,  # Higher drawdown
    }

    grade, desc = calculate_risk_grade(sp3_metrics, sp500_metrics)
    assert grade in ["A", "B", "C", "D", "F"]
    assert isinstance(desc, str)


def test_risk_grade_high_risk():
    """Test risk grade calculation for high-risk scenario."""
    sp3_metrics = {
        "volatility": 0.40,  # 40% vol
        "max_drawdown": 0.70,  # 70% drawdown
    }
    sp500_metrics = {
        "volatility": 0.12,  # Lower vol
        "max_drawdown": 0.20,  # Lower drawdown
    }

    grade, desc = calculate_risk_grade(sp3_metrics, sp500_metrics)
    assert grade in ["A", "B", "C", "D", "F"]
    # Higher risk should tend toward D or F
    assert grade in ["D", "F"]


def test_calculate_metrics():
    """Test metrics calculation from portfolio values."""
    total_invested = 1000
    portfolio_values = [1000, 1050, 1100, 1150, 1120, 1200]
    years = 1

    metrics = calculate_metrics(total_invested, portfolio_values, years)

    assert "total_return_pct" in metrics
    assert "annualized_return" in metrics
    assert "max_drawdown" in metrics
    assert "sharpe_ratio" in metrics
    assert "volatility" in metrics

    # Check ranges
    assert metrics["total_return_pct"] >= 0  # Positive returns in this example
    assert 0 <= metrics["max_drawdown"] <= 1  # Max drawdown between 0-100%
    assert -2 < metrics["sharpe_ratio"] < 3  # Reasonable Sharpe ratio range


def test_calculate_metrics_empty():
    """Test metrics with empty portfolio values."""
    metrics = calculate_metrics(1000, [], 1)

    assert metrics["total_return_pct"] == 0
    assert metrics["annualized_return"] == 0
    assert metrics["max_drawdown"] == 0


# Integration Tests

class TestAnalyticsEndpoint:
    """Test /api/analytics endpoint."""

    def test_analytics_endpoint_returns_data(self, test_client):
        """Test that /api/analytics returns valid JSON."""
        response = test_client.get("/api/analytics")
        assert response.status_code == 200

        data = response.json()
        assert "risk_grade" in data
        assert "risk_description" in data
        assert "sp3_total_return_pct" in data
        assert "sp500_total_return_pct" in data
        assert "chart_data" in data

    def test_analytics_response_structure(self, test_client):
        """Test that analytics response has correct structure."""
        response = test_client.get("/api/analytics")
        data = response.json()

        # Check risk grade
        assert data["risk_grade"] in ["A", "B", "C", "D", "F"]

        # Check chart data
        assert "dates" in data["chart_data"]
        assert "sp3_values" in data["chart_data"]
        assert "sp500_values" in data["chart_data"]
        assert len(data["chart_data"]["dates"]) > 0
        assert len(data["chart_data"]["sp3_values"]) > 0
        assert len(data["chart_data"]["sp500_values"]) > 0

        # Check metrics are numeric
        assert isinstance(data["sp3_total_return_pct"], (int, float))
        assert isinstance(data["sp3_sharpe_ratio"], (int, float))
        assert isinstance(data["sp500_total_return_pct"], (int, float))


class TestLandingPage:
    """Test landing page rendering."""

    def test_landing_page_loads(self, test_client):
        """Test that /landing page loads and contains expected content."""
        response = test_client.get("/landing")
        assert response.status_code == 200

        html = response.text
        assert "S&P 3" in html
        assert "Performance" in html or "Chart" in html
        assert "Risk" in html

    def test_home_page_serves_landing(self, test_client):
        """Test that / route serves landing page."""
        response = test_client.get("/")
        assert response.status_code == 200

        html = response.text
        assert "S&P 3" in html


class TestDatabaseStorage:
    """Test AnalyticsSnapshot database storage."""

    def test_snapshot_stored_in_db(self, test_db):
        """Test that analytics snapshot can be stored in database."""
        snapshot = AnalyticsSnapshot(
            snapshot_date=date.today(),
            sp3_total_return_pct=150.5,
            sp3_annualized_return=15.2,
            sp3_max_drawdown=0.25,
            sp3_sharpe_ratio=0.95,
            sp3_volatility=0.18,
            sp3_position_value=5000,
            sp500_total_return_pct=80.0,
            sp500_annualized_return=8.5,
            sp500_max_drawdown=0.35,
            sp500_sharpe_ratio=0.72,
            risk_grade="B",
            risk_description="Moderate Risk",
            weekly_chart_data='{"dates": [], "sp3_values": [], "sp500_values": []}',
        )

        test_db.add(snapshot)
        test_db.commit()

        # Retrieve
        retrieved = test_db.query(AnalyticsSnapshot).first()
        assert retrieved is not None
        assert retrieved.sp3_total_return_pct == 150.5
        assert retrieved.risk_grade == "B"


# Fixtures for test_client (used by integration tests)

@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    from fastapi.testclient import TestClient
    from app.main import app

    # Override database for tests
    from app.database import SessionLocal
    from app.database import engine as prod_engine, Base as ProdBase

    # Create test engine
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ProdBase.metadata.create_all(bind=test_engine)

    # Override dependency
    def override_get_db():
        TestingSessionLocal = sessionmaker(bind=test_engine)
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from app.main import get_db
    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    yield client

    # Cleanup
    app.dependency_overrides.clear()
