"""Tests for market cap fetcher."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.fetcher import format_market_cap, get_top_n_sp500, _rank_change


def test_format_market_cap_trillions():
    assert format_market_cap(4_600_000_000_000) == "$4.60T"


def test_format_market_cap_billions():
    assert format_market_cap(500_000_000_000) == "$500.00B"


def test_rank_change_up():
    prev = {"NVDA": 2}
    assert _rank_change("NVDA", 1, prev) == "up"


def test_rank_change_down():
    prev = {"AAPL": 1}
    assert _rank_change("AAPL", 2, prev) == "down"


def test_rank_change_unchanged():
    prev = {"GOOGL": 3}
    assert _rank_change("GOOGL", 3, prev) == "unchanged"


def test_rank_change_new():
    assert _rank_change("MSFT", 3, {}) == "new"


@patch("app.fetcher._fetch_via_yfinance")
@patch("app.fetcher._fetch_via_slickcharts")
def test_get_top_n_uses_fallback_when_both_fail(mock_slick, mock_yf, tmp_path, monkeypatch):
    mock_yf.return_value = None
    mock_slick.return_value = None
    monkeypatch.setattr("app.fetcher.CACHE_FILE", tmp_path / "cache.json")

    results = get_top_n_sp500(3)
    assert len(results) == 3
    assert results[0]["ticker"] == "NVDA"
    assert results[0]["rank"] == 1
    assert "market_cap_display" in results[0]


@patch("app.fetcher._fetch_via_yfinance")
def test_get_top_n_uses_yfinance_when_available(mock_yf, tmp_path, monkeypatch):
    mock_yf.return_value = [
        (1, "NVDA", "Nvidia Corporation", 4_600_000_000_000, "Semiconductors"),
        (2, "AAPL", "Apple Inc.", 4_020_000_000_000, "Consumer Electronics"),
        (3, "GOOGL", "Alphabet Inc.", 3_810_000_000_000, "Internet / AI"),
    ]
    monkeypatch.setattr("app.fetcher.CACHE_FILE", tmp_path / "cache.json")

    results = get_top_n_sp500(3)
    assert len(results) == 3
    assert results[1]["ticker"] == "AAPL"
    assert results[1]["market_cap_display"] == "$4.02T"


@patch("app.fetcher._fetch_via_yfinance")
def test_cache_is_written(mock_yf, tmp_path, monkeypatch):
    mock_yf.return_value = [
        (1, "NVDA", "Nvidia Corporation", 4_600_000_000_000, "Semiconductors"),
        (2, "AAPL", "Apple Inc.", 4_020_000_000_000, "Consumer Electronics"),
        (3, "GOOGL", "Alphabet Inc.", 3_810_000_000_000, "Internet / AI"),
    ]
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr("app.fetcher.CACHE_FILE", cache_file)

    get_top_n_sp500(3)
    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert data["date"] == str(date.today())
    assert len(data["picks"]) == 3


@patch("app.fetcher._fetch_via_yfinance")
def test_cache_is_used_same_day(mock_yf, tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr("app.fetcher.CACHE_FILE", cache_file)

    fixed_picks = [
        {"rank": 1, "ticker": "NVDA", "name": "Nvidia", "market_cap": 4_600_000_000_000,
         "market_cap_display": "$4.60T", "sector": "Tech", "rank_change": "unchanged"},
        {"rank": 2, "ticker": "AAPL", "name": "Apple", "market_cap": 4_020_000_000_000,
         "market_cap_display": "$4.02T", "sector": "Tech", "rank_change": "unchanged"},
        {"rank": 3, "ticker": "GOOGL", "name": "Alphabet", "market_cap": 3_810_000_000_000,
         "market_cap_display": "$3.81T", "sector": "Tech", "rank_change": "unchanged"},
    ]
    cache_file.write_text(json.dumps({"date": str(date.today()), "picks": fixed_picks}))

    results = get_top_n_sp500(3)
    mock_yf.assert_not_called()
    assert results[0]["ticker"] == "NVDA"
