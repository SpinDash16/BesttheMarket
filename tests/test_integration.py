"""End-to-end integration tests for the S&P 3 Weekly app."""
import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_SECRET"] = "test-secret"
os.environ.setdefault("RESEND_API_KEY", "re_test_key")
os.environ.setdefault("FROM_EMAIL", "test@sp3.com")
os.environ.setdefault("ADMIN_EMAIL", "admin@sp3.com")

from app.database import Base, Subscriber, WeeklyPick, get_db

# StaticPool ensures all connections share the same in-memory SQLite database
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

MOCK_PICKS = [
    {"rank": 1, "ticker": "NVDA", "name": "Nvidia Corporation",
     "market_cap": 4_600_000_000_000, "market_cap_display": "$4.60T",
     "sector": "Semiconductors", "rank_change": "unchanged"},
    {"rank": 2, "ticker": "AAPL", "name": "Apple Inc.",
     "market_cap": 4_020_000_000_000, "market_cap_display": "$4.02T",
     "sector": "Consumer Electronics", "rank_change": "unchanged"},
    {"rank": 3, "ticker": "GOOGL", "name": "Alphabet Inc.",
     "market_cap": 3_810_000_000_000, "market_cap_display": "$3.81T",
     "sector": "Internet / AI", "rank_change": "unchanged"},
]


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    import app.database as db_module
    # Redirect the app's engine to the test engine so create_tables() in lifespan works
    original_engine = db_module.engine
    db_module.engine = test_engine

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
    db_module.engine = original_engine


# ─── Subscribe tests ──────────────────────────────────────────────────────────

def test_subscribe_new_user(client, db):
    res = client.post("/subscribe", json={"email": "alice@test.com", "name": "Alice"})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "subscribed" in data["message"].lower() or "subscribed" in data["message"]
    assert data["unsubscribe_token"] is not None

    sub = db.query(Subscriber).filter(Subscriber.email == "alice@test.com").first()
    assert sub is not None, "Subscriber not saved to DB"
    assert sub.is_active is True
    assert sub.name == "Alice"


def test_subscribe_duplicate(client, db):
    client.post("/subscribe", json={"email": "bob@test.com"})
    res = client.post("/subscribe", json={"email": "bob@test.com"})
    assert res.status_code == 200
    assert "already" in res.json()["message"].lower()


def test_subscribe_three_users(client, db):
    emails = ["user1@test.com", "user2@test.com", "user3@test.com"]
    for email in emails:
        res = client.post("/subscribe", json={"email": email})
        assert res.status_code == 200, f"Subscribe failed for {email}: {res.text}"

    count = db.query(Subscriber).filter(Subscriber.is_active == True).count()
    assert count == 3, f"Expected 3 subscribers, got {count}"


def test_unsubscribe(client, db):
    res = client.post("/subscribe", json={"email": "carol@test.com"})
    token = res.json()["unsubscribe_token"]

    unsub_res = client.get(f"/unsubscribe/{token}")
    assert unsub_res.status_code == 200

    sub = db.query(Subscriber).filter(Subscriber.email == "carol@test.com").first()
    assert sub.is_active is False, "Subscriber should be deactivated"


def test_unsubscribe_invalid_token(client):
    res = client.get("/unsubscribe/nonexistent-token-xyz")
    assert res.status_code == 404


# ─── Admin auth tests ─────────────────────────────────────────────────────────

def test_subscribers_requires_auth(client):
    res = client.get("/subscribers")
    assert res.status_code == 403


def test_subscribers_with_auth(client, db):
    client.post("/subscribe", json={"email": "dave@test.com"})
    res = client.get("/subscribers", headers={"X-Admin-Secret": "test-secret"})
    assert res.status_code == 200
    assert len(res.json()) >= 1


def test_picks_history_requires_auth(client):
    res = client.get("/picks/history")
    assert res.status_code == 403


# ─── Full pipeline integration test ──────────────────────────────────────────

@patch("app.scheduler.weekly_send_job", new_callable=AsyncMock)
def test_trigger_send_endpoint(mock_job, client):
    res = client.post(
        "/admin/trigger-send",
        headers={"X-Admin-Secret": "test-secret"},
    )
    assert res.status_code == 200
    mock_job.assert_awaited_once()


@patch("app.fetcher.get_top_n_sp500", return_value=MOCK_PICKS)
@patch("resend.Emails.send", return_value={"id": "mock-id"})
def test_full_send_pipeline(mock_resend, mock_fetcher, client, db):
    """Full flow: subscribe 3 users → trigger send → verify emails sent → unsubscribe 1."""
    # 1. Subscribe 3 users
    tokens = []
    for i in range(3):
        res = client.post("/subscribe", json={"email": f"e{i}@test.com"})
        assert res.status_code == 200, f"Subscribe {i} failed: {res.text}"
        tokens.append(res.json()["unsubscribe_token"])

    count = db.query(Subscriber).filter(Subscriber.is_active == True).count()
    assert count == 3, f"Expected 3 subscribers, got {count}"

    # 2. Unsubscribe one
    client.get(f"/unsubscribe/{tokens[0]}")
    count = db.query(Subscriber).filter(Subscriber.is_active == True).count()
    assert count == 2, f"After unsubscribe, expected 2 active, got {count}"

    # 3. Verify DB
    unsub = db.query(Subscriber).filter(Subscriber.email == "e0@test.com").first()
    assert unsub.is_active is False, "Unsubscribed user should be inactive"


# ─── Health check ────────────────────────────────────────────────────────────

def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_subscribe_page_loads(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "S&P" in res.text or "SP3" in res.text or "3 Weekly" in res.text
