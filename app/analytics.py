"""Historical performance analytics and risk calculations for S&P 3 strategy."""

from __future__ import annotations

import logging
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from bs4 import BeautifulSoup
import requests

import pandas as pd
import numpy as np
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session

from .database import AnalyticsSnapshot

logger = logging.getLogger(__name__)

# Constants
LOOKBACK_YEARS = 10  # 10-year lookback for reliable S&P 3 history
INITIAL_DATE = date(2016, 1, 1)  # Start from 2016 for 10-year history
WEEKLY_BUDGET = 100  # $100 per stock
RISK_FREE_RATE = 0.04  # 4% annual risk-free rate


def fetch_sp500_constituents_history() -> dict[date, set[str]]:
    """
    Scrape Wikipedia for historical S&P 500 constituent changes.

    Returns dict mapping date -> set of tickers that were in S&P 500 on that date.
    Uses the historical changes table from Wikipedia.
    """
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")

        # Find the tables
        tables = soup.find_all("table", {"class": "wikitable"})

        if len(tables) < 2:
            logger.warning(f"Could not find S&P 500 tables on Wikipedia (found {len(tables)})")
            return {}

        # Table 0: Current constituents
        # Table 1: Historical changes (Effective Date, Added, Removed, Reason)
        current_table = tables[0]
        changes_table = tables[1]

        # Get current constituents from the main table
        current_rows = current_table.find_all("tr")[1:]  # Skip header
        current_tickers = set()

        for row in current_rows:
            cols = row.find_all("td")
            if len(cols) >= 1:
                try:
                    # First column is the ticker symbol
                    ticker = cols[0].text.strip()
                    if ticker and len(ticker) > 0 and ticker[0].isalpha():
                        current_tickers.add(ticker)
                except Exception as e:
                    logger.debug(f"Error parsing current ticker: {e}")
                    continue

        logger.info(f"Found {len(current_tickers)} current S&P 500 constituents")

        # Parse historical changes
        rows = changes_table.find_all("tr")[1:]  # Skip header
        changes = []

        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 4:
                try:
                    # Format: Effective Date | Added | Removed | Reason
                    date_str = cols[0].text.strip()
                    added_text = cols[1].text.strip()
                    removed_text = cols[2].text.strip()

                    # Parse date
                    try:
                        change_date = pd.to_datetime(date_str).date()
                    except:
                        continue

                    # Parse added tickers
                    if added_text:
                        for ticker in added_text.split("\n"):
                            ticker = ticker.strip()
                            if ticker and ticker[0].isalpha():
                                changes.append({
                                    "date": change_date,
                                    "ticker": ticker,
                                    "added": True
                                })

                    # Parse removed tickers
                    if removed_text:
                        for ticker in removed_text.split("\n"):
                            ticker = ticker.strip()
                            if ticker and ticker[0].isalpha():
                                changes.append({
                                    "date": change_date,
                                    "ticker": ticker,
                                    "added": False
                                })

                except Exception as e:
                    logger.debug(f"Error parsing changes row: {e}")
                    continue

        logger.info(f"Scraped {len(current_tickers)} current S&P 500 constituents")
        logger.info(f"Found {len(changes)} historical changes")

        # Build timeline: start with current constituents, then apply changes backward
        constituent_timeline = {}

        # Work backward from today
        end_date = date.today()
        constituents = current_tickers.copy()

        # Sort changes by date, descending
        changes.sort(key=lambda x: x["date"], reverse=True)
        change_idx = 0

        # For each week in lookback period
        current = end_date
        while current >= INITIAL_DATE:
            # Apply any changes that happened on or after this date
            while change_idx < len(changes) and changes[change_idx]["date"] >= current:
                change = changes[change_idx]
                if change["added"]:
                    constituents.discard(change["ticker"])  # Reverse: remove additions
                else:
                    constituents.add(change["ticker"])  # Reverse: add removals
                change_idx += 1

            constituent_timeline[current] = constituents.copy()
            current -= timedelta(days=1)

        logger.info(f"Built constituent timeline with {len(constituent_timeline)} date points")
        return constituent_timeline

    except Exception as e:
        logger.error(f"Error fetching S&P 500 constituents: {e}")
        return {}


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
)
def get_shares_outstanding(ticker: str, date_obj: date) -> float:
    """
    Get shares outstanding for a ticker on a given date.
    Uses yfinance current shares outstanding as approximation.
    Includes retry logic for cloud environments.

    In a more complete implementation, this would pull from SEC filings
    for the most recent quarterly report before the given date.
    """
    try:
        t = yf.Ticker(ticker)
        shares = t.info.get("sharesOutstanding")

        if shares:
            return float(shares)

        logger.debug(f"Could not fetch shares outstanding for {ticker}")
        return None

    except Exception as e:
        logger.debug(f"Error fetching shares for {ticker}: {e}")
        raise  # Let retry decorator handle it


def get_top_3_sp500_on_date(
    date_obj,  # Can be pandas Timestamp or datetime.date
    prices_df: pd.DataFrame,
    constituent_timeline: dict[date, set[str]]
) -> list[str]:
    """
    Identify top 3 S&P 500 stocks by market cap on a given date.

    Only considers tickers that have price data available (mega-caps).
    Filters to stocks that were in S&P 500 on that date.

    Args:
        date_obj: The date to identify top 3 for (pandas Timestamp or datetime.date)
        prices_df: DataFrame with historical prices (index=date, columns=tickers)
        constituent_timeline: Dict mapping date -> set of tickers in S&P 500

    Returns:
        List of 3 ticker symbols (top by market cap), or None if insufficient data
    """
    # Convert pandas Timestamp to datetime.date for constituent timeline lookup
    if hasattr(date_obj, 'date'):
        date_for_constituents = date_obj.date()
    else:
        date_for_constituents = date_obj

    # Find closest date in constituent timeline (lookback to most recent)
    valid_dates = [d for d in constituent_timeline.keys() if d <= date_for_constituents]

    if not valid_dates:
        return None

    closest_date = max(valid_dates)
    constituents = constituent_timeline[closest_date]

    if not constituents:
        return None

    # Get price for this date (or closest available)
    # Convert date to pandas Timestamp for DataFrame indexing
    if isinstance(date_obj, date) and not hasattr(date_obj, 'time'):
        date_ts = pd.Timestamp(date_obj)
    else:
        date_ts = date_obj

    if date_ts in prices_df.index:
        price_row = prices_df.loc[date_ts]
    else:
        # Find nearest date
        closest_prices = prices_df[prices_df.index <= date_ts]
        if len(closest_prices) == 0:
            return None
        price_row = closest_prices.iloc[-1]

    # Calculate market caps for tickers we have price data for
    # Only consider tickers that are in S&P 500 AND have price data
    market_caps = {}

    for ticker in prices_df.columns:
        # Only use tickers that were in S&P 500 on this date
        if ticker not in constituents:
            continue

        try:
            price = price_row.get(ticker)
            if pd.isna(price) or price is None or price <= 0:
                continue

            shares = get_shares_outstanding(ticker, date_obj)
            if shares is None or shares <= 0:
                continue

            market_cap = price * shares
            market_caps[ticker] = market_cap

        except Exception as e:
            logger.debug(f"Error calculating market cap for {ticker}: {e}")
            continue

    if len(market_caps) < 3:
        logger.debug(
            f"Insufficient market cap data on {date_obj}: "
            f"only {len(market_caps)} stocks (available: {len(prices_df.columns)}, "
            f"in S&P 500: {len(constituents)})"
        )
        return None

    # Sort by market cap, return top 3
    sorted_tickers = sorted(market_caps.items(), key=lambda x: x[1], reverse=True)
    top_3 = [ticker for ticker, _ in sorted_tickers[:3]]

    return top_3


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
def _fetch_with_yfinance(tickers: list[str], start_date: date, end_date: date) -> pd.DataFrame:
    """
    Internal function to fetch prices from yfinance with retry logic.
    Retries up to 3 times with exponential backoff.
    """
    logger.info(f"Attempting to fetch {len(tickers)} tickers from yfinance...")
    data = yf.download(
        tickers,
        start=start_date,
        end=end_date,
        interval="1wk",
        progress=False,
    )

    # For single ticker, yfinance returns different structure
    if len(tickers) == 1:
        prices = data[["Close"]].copy()
        prices.columns = tickers
    else:
        prices = data["Close"].copy()

    # Forward fill any missing data
    prices = prices.ffill().dropna()
    return prices


def _fetch_with_pandas_datareader(tickers: list[str], start_date: date, end_date: date) -> pd.DataFrame:
    """
    Fallback function to fetch prices using pandas_datareader.
    Uses multiple data sources (Yahoo via pandas, more robust than direct yfinance).
    """
    try:
        import pandas_datareader as pdr
    except ImportError:
        logger.error("pandas_datareader not installed")
        raise

    logger.info(f"Fetching {len(tickers)} tickers from pandas_datareader (fallback)...")

    all_prices = {}
    for ticker in tickers:
        try:
            # pandas_datareader Yahoo backend
            data = pdr.data.get_data_yahoo(
                ticker,
                start=start_date,
                end=end_date,
            )
            # Convert to weekly
            data_weekly = data['Close'].resample('W').last()
            all_prices[ticker] = data_weekly
            logger.info(f"  ✓ {ticker}: {len(data_weekly)} weeks")
        except Exception as e:
            logger.warning(f"  ✗ {ticker}: {str(e)}")
            continue

    if not all_prices:
        raise ValueError("Failed to fetch any tickers from pandas_datareader")

    # Combine into single DataFrame
    prices = pd.DataFrame(all_prices)
    prices = prices.ffill().dropna()
    logger.info(f"✓ pandas_datareader: Fetched {len(prices)} weeks for {len(all_prices)} tickers")
    return prices


def _load_fixture_data() -> pd.DataFrame:
    """
    Load pre-calculated historical fixture data from JSON.
    Used as final fallback when live data sources fail.
    """
    import os

    fixture_path = Path(__file__).parent / "fixtures" / "historical_data.json"

    if not fixture_path.exists():
        logger.error(f"Fixture file not found at {fixture_path}")
        return None

    try:
        with open(fixture_path, 'r') as f:
            data = json.load(f)

        logger.info(f"✓ Loaded fixture data: {data['metadata']['weeks']} weeks")

        # Create DataFrame from fixture
        df = pd.DataFrame({
            'SPY': data['sp500_values'],  # Use SPY as proxy for S&P 500
        }, index=pd.to_datetime(data['dates']))

        return df
    except Exception as e:
        logger.error(f"Failed to load fixture data: {e}")
        return None


def fetch_historical_prices(
    tickers: list[str], start_date: date, end_date: date
) -> pd.DataFrame:
    """
    Fetch historical weekly prices with three-tier fallback strategy.

    1. Try yfinance with exponential backoff retries
    2. Fall back to pandas_datareader if yfinance fails
    3. Fall back to pre-calculated fixture if both live sources fail

    Returns DataFrame with columns like NVDA, AAPL, GOOGL (close prices).
    Index is DatetimeIndex with weekly frequency.
    """
    # Try yfinance first with retries
    try:
        logger.info(f"Primary: Fetching {len(tickers)} tickers with yfinance (with retries)...")
        prices = _fetch_with_yfinance(tickers, start_date, end_date)
        logger.info(f"✓ yfinance: Fetched {len(prices)} weeks of price data")
        return prices

    except Exception as e:
        logger.warning(f"yfinance failed after retries: {str(e)}")
        logger.info("Attempting fallback #1: pandas_datareader")

        try:
            prices = _fetch_with_pandas_datareader(tickers, start_date, end_date)
            logger.info(f"✓ pandas_datareader fallback successful: {len(prices)} weeks")
            return prices

        except Exception as e2:
            logger.error(f"pandas_datareader fallback also failed: {str(e2)}")
            logger.info("Attempting fallback #2: pre-calculated fixture data")

            # Try loading fixture as last resort
            fixture = _load_fixture_data()
            if fixture is not None:
                logger.warning("Using pre-calculated historical fixture (real data from past, not live)")
                return fixture

            # All sources failed
            logger.error(f"Original yfinance error: {str(e)}")
            raise ValueError(
                f"All data sources failed. yfinance: {str(e)[:100]}... "
                f"pandas_datareader: {str(e2)[:100]}... fixture: not available"
            )


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
)
def estimate_market_cap(ticker: str, price: float) -> float:
    """
    Estimate market cap for a ticker at a given price.

    Uses current shares outstanding from yfinance.info and multiplies by historical price.
    Note: This is an approximation since shares outstanding changes over time (splits, buybacks).
    Includes retry logic for cloud environments.
    """
    try:
        t = yf.Ticker(ticker)
        shares_outstanding = t.info.get("sharesOutstanding", None)

        if shares_outstanding is None:
            logger.debug(f"Could not fetch shares outstanding for {ticker}")
            return None

        market_cap = price * shares_outstanding
        return market_cap

    except Exception as e:
        logger.debug(f"Error estimating market cap for {ticker}: {e}")
        raise  # Let retry decorator handle it


def get_top_3_by_market_cap(prices_row: pd.Series, date: datetime) -> list[str]:
    """
    Identify top 3 tickers by estimated market cap from a row of prices.

    Args:
        prices_row: pd.Series with ticker symbols as index, prices as values
        date: Date for logging

    Returns:
        List of 3 ticker symbols, sorted by market cap (highest first)
    """
    market_caps = {}

    for ticker, price in prices_row.items():
        if pd.isna(price):
            continue

        market_cap = estimate_market_cap(ticker, price)
        if market_cap is not None:
            market_caps[ticker] = market_cap

    if len(market_caps) < 3:
        logger.warning(f"Not enough tickers with market cap data for {date}")
        return None

    # Sort by market cap descending, take top 3
    sorted_tickers = sorted(market_caps.items(), key=lambda x: x[1], reverse=True)
    top_3 = [ticker for ticker, _ in sorted_tickers[:3]]

    return top_3


def simulate_dca_portfolio(
    prices: pd.DataFrame,
    top_3_by_date: dict[str, list[str]],
    weekly_budget: float = WEEKLY_BUDGET,
) -> dict:
    """
    Simulate Dollar-Cost Averaging (DCA) into S&P 3 strategy.

    Each Friday, buy $100 of each of the top 3 stocks.

    Returns:
        {
            'portfolio_value': list of cumulative portfolio values over time,
            'shares_held': dict of ticker -> shares,
            'total_invested': total cash deployed,
            'dates': list of dates for chart,
            'cumulative_invested': list of cumulative cash invested per week,
            'weekly_values': list of weekly portfolio values,
        }
    """
    portfolio = {}  # ticker -> shares_held
    portfolio_values = []  # cumulative portfolio value over time
    cumulative_invested_values = []  # cumulative cash invested over time
    dates = []
    total_invested = 0

    for date, price_row in prices.iterrows():
        date_str = date.strftime("%Y-%m-%d")
        dates.append(date_str)

        # Get top 3 for this week
        top_3 = top_3_by_date.get(date_str)

        if top_3:
            for ticker in top_3:
                if pd.isna(price_row.get(ticker)):
                    continue

                price = price_row[ticker]
                shares_to_buy = weekly_budget / price

                if ticker not in portfolio:
                    portfolio[ticker] = 0

                portfolio[ticker] += shares_to_buy
                total_invested += weekly_budget

        # Calculate current portfolio value
        portfolio_value = 0
        for ticker, shares in portfolio.items():
            if ticker in price_row.index:
                current_price = price_row[ticker]
                if not pd.isna(current_price):
                    portfolio_value += shares * current_price

        portfolio_values.append(portfolio_value)
        cumulative_invested_values.append(total_invested)

    return {
        "portfolio_value": portfolio_values,
        "shares_held": portfolio,
        "total_invested": total_invested,
        "dates": dates,
        "cumulative_invested": cumulative_invested_values,
        "portfolio_values": portfolio_values,
    }


def calculate_sharpe_ratio(returns_series: pd.Series, risk_free_rate: float = RISK_FREE_RATE) -> float:
    """
    Calculate annualized Sharpe ratio.

    Sharpe Ratio = (Mean Return - Risk Free Rate) / Std Dev of Returns
    """
    if len(returns_series) < 2:
        return None

    excess_return = returns_series.mean() - risk_free_rate / 52  # Weekly risk-free rate
    volatility = returns_series.std()

    if volatility == 0:
        return None

    sharpe = excess_return / volatility * np.sqrt(52)  # Annualize (52 weeks/year)
    return sharpe


def calculate_max_drawdown(portfolio_values: list[float]) -> float:
    """
    Calculate maximum drawdown as a percentage.

    Max Drawdown = (Trough Value - Peak Value) / Peak Value
    """
    if len(portfolio_values) < 2:
        return None

    peak = portfolio_values[0]
    max_drawdown = 0

    for value in portfolio_values:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak
        max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown


def calculate_cagr(initial_value: float, final_value: float, years: float) -> float:
    """
    Calculate Compound Annual Growth Rate (CAGR).

    CAGR = (Ending Value / Beginning Value)^(1/years) - 1
    """
    if initial_value <= 0 or years <= 0:
        return None

    cagr = (final_value / initial_value) ** (1 / years) - 1
    return cagr


def calculate_volatility(portfolio_values: list[float]) -> float:
    """
    Calculate annualized volatility from portfolio values.
    """
    if len(portfolio_values) < 2:
        return None

    # Calculate weekly returns
    returns = pd.Series(portfolio_values).pct_change().dropna()

    if len(returns) == 0:
        return None

    # Annualize (52 weeks/year)
    volatility = returns.std() * np.sqrt(52)
    return volatility


def calculate_risk_grade(sp3_metrics: dict, sp500_metrics: dict) -> tuple[str, str]:
    """
    Calculate risk grade (A-F) and description.

    Weighted components:
    - Volatility score (40%): relative to S&P 500
    - Concentration penalty (35%): holding only 3 stocks
    - Drawdown score (20%): relative severity
    - Correlation score (5%): market correlation

    Returns:
        (grade: str, description: str)
    """
    volatility_ratio = sp3_metrics.get("volatility", 0) / max(sp500_metrics.get("volatility", 1), 0.01)
    volatility_score = (1 - min(volatility_ratio, 1)) * 40  # Better if lower vol

    concentration_penalty = 35  # Inherent penalty for 3-stock concentration

    drawdown_ratio = sp3_metrics.get("max_drawdown", 0) / max(sp500_metrics.get("max_drawdown", 0.01), 0.01)
    drawdown_score = (1 - min(drawdown_ratio, 1)) * 20  # Better if lower drawdown

    correlation_score = 5  # Assume ~90% correlation (minor adjustment)

    total_score = volatility_score - concentration_penalty + drawdown_score + correlation_score
    total_score = max(0, min(100, total_score))  # Clamp 0-100

    if total_score >= 85:
        grade, desc = "A", "Low Risk"
    elif total_score >= 70:
        grade, desc = "B", "Moderate Risk"
    elif total_score >= 55:
        grade, desc = "C", "Medium Risk"
    elif total_score >= 40:
        grade, desc = "D", "Higher Risk"
    else:
        grade, desc = "F", "Very High Risk"

    return grade, desc


def refresh_analytics_snapshot(db: Session) -> None:
    """
    Refresh analytics snapshot: full backtest, metrics, risk grade, chart data.

    This is the main entry point for daily refresh.
    """
    logger.info("Starting analytics snapshot refresh...")
    start_time = datetime.utcnow()

    try:
        # 1. Fetch historical S&P 500 constituents
        logger.info("Fetching historical S&P 500 constituents...")
        constituent_timeline = fetch_sp500_constituents_history()

        if not constituent_timeline:
            raise ValueError("Failed to fetch S&P 500 constituent history")

        # 2. Get current S&P 500 constituents (most reliable ticker source)
        # Note: Wikipedia constituent_timeline uses company names, which don't map 1-to-1 to tickers
        # So we use current S&P 500 constituents which have proper ticker symbols
        # This is acceptable because we're doing a retrospective backtest with current companies
        end_date = date.today()
        start_date = end_date - timedelta(days=365 * LOOKBACK_YEARS)

        # Get current S&P 500 (most recent date in timeline has current constituents)
        latest_date = max(constituent_timeline.keys())
        constituents_names = constituent_timeline[latest_date]

        # Fetch price data for what we have - these are the tickers we can reliably get
        # Start with common mega-cap tickers and expand from there
        tickers_to_fetch = [
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "JNJ",
            "V", "WMT", "JPM", "PG", "KO", "INTC", "HD", "DIS", "MCD", "VZ",
            "BA", "UNH", "XOM", "PFE", "CSCO", "IBM", "ORCL", "QCOM", "LMT",
            "AXP", "RTX", "SO", "NEE", "ABT", "CVX", "PM", "MRK", "GE", "SPY"
        ]
        logger.info(f"Fetching prices for {len(tickers_to_fetch)} major S&P 500 stocks...")

        # 3. Fetch historical prices
        prices = fetch_historical_prices(tickers_to_fetch, start_date, end_date)

        if len(prices) == 0:
            raise ValueError("Failed to fetch historical prices")

        logger.info(f"Fetched {len(prices)} weeks of price data")

        # 4. Pre-fetch shares outstanding for all tickers (cache for performance)
        logger.info("Pre-fetching shares outstanding for all tickers...")
        shares_cache = {}
        for ticker in tickers_to_fetch:
            shares = get_shares_outstanding(ticker, date.today())
            if shares:
                shares_cache[ticker] = shares
        logger.info(f"Cached shares for {len(shares_cache)} tickers")

        # 4b. Build top_3_by_date: for each Friday, identify top 3 by market cap
        logger.info("Building top 3 stocks by market cap for each Friday...")
        top_3_by_date = {}
        invalid_weeks = 0

        for date_index in prices.index:
            date_str = date_index.strftime("%Y-%m-%d")

            # Convert to date for constituent lookup
            if hasattr(date_index, 'date'):
                date_obj_date = date_index.date()
            else:
                date_obj_date = date_index

            # Find constituents on this date
            valid_dates = [d for d in constituent_timeline.keys() if d <= date_obj_date]
            if not valid_dates:
                invalid_weeks += 1
                continue

            constituents = constituent_timeline[max(valid_dates)]

            # Get price for this date (or closest available)
            if date_index in prices.index:
                price_row = prices.loc[date_index]
            else:
                closest_prices = prices[prices.index <= date_index]
                if len(closest_prices) == 0:
                    invalid_weeks += 1
                    continue
                price_row = closest_prices.iloc[-1]

            # Calculate market caps using cached shares
            market_caps = {}
            for ticker in prices.columns:
                # Only use tickers in S&P 500 and with cached shares
                if ticker not in constituents or ticker not in shares_cache:
                    continue

                try:
                    price = price_row.get(ticker)
                    if pd.isna(price) or price is None or price <= 0:
                        continue

                    shares = shares_cache[ticker]
                    market_cap = price * shares
                    market_caps[ticker] = market_cap

                except Exception as e:
                    logger.debug(f"Error with {ticker}: {e}")
                    continue

            # Get top 3
            if len(market_caps) >= 3:
                sorted_tickers = sorted(market_caps.items(), key=lambda x: x[1], reverse=True)
                top_3 = [ticker for ticker, _ in sorted_tickers[:3]]
                top_3_by_date[date_str] = top_3
            else:
                invalid_weeks += 1

        logger.info(
            f"✓ Identified top 3 for {len(top_3_by_date)} weeks "
            f"({invalid_weeks} weeks with insufficient data)"
        )

        # 3. Simulate S&P 3 DCA portfolio
        sp3_result = simulate_dca_portfolio(prices, top_3_by_date, WEEKLY_BUDGET)

        # 4. Simulate S&P 500 DCA (SPY)
        spy_prices = fetch_historical_prices(["SPY"], start_date, end_date)
        spy_dca_result = simulate_dca_portfolio_single(spy_prices, WEEKLY_BUDGET * 3)

        # 5. Calculate metrics
        sp3_metrics = calculate_metrics(
            sp3_result["total_invested"],
            sp3_result["portfolio_values"],
            LOOKBACK_YEARS,
        )

        sp500_metrics = calculate_metrics(
            spy_dca_result["total_invested"],
            spy_dca_result["portfolio_values"],
            LOOKBACK_YEARS,
        )

        # 6. Calculate risk grade
        risk_grade, risk_desc = calculate_risk_grade(sp3_metrics, sp500_metrics)

        # 7. Build chart data — align both series to SPY dates
        spy_dates = spy_dca_result["dates"]
        spy_values = [float(v) for v in spy_dca_result["portfolio_values"]]
        spy_principal = [float(v) for v in spy_dca_result["cumulative_invested"]]

        # Build a lookup for SP3 values by date
        sp3_date_to_value = dict(zip(sp3_result["dates"], sp3_result["portfolio_values"]))

        # Align SP3 to SPY dates using forward-fill
        aligned_sp3 = []
        last_sp3_value = 0.0
        for d in spy_dates:
            if d in sp3_date_to_value:
                last_sp3_value = float(sp3_date_to_value[d])
            aligned_sp3.append(last_sp3_value)

        chart_data = {
            "dates": spy_dates,
            "sp3_values": aligned_sp3,
            "sp500_values": spy_values,
            "principal_values": spy_principal,
        }

        # 7b. Calculate portfolio allocation from accumulated shares (15-year history)
        # This shows all stocks accumulated from DCA into top 3 each week
        today_date = date.today()

        # Get most recent prices
        if pd.Timestamp(today_date) in prices.index:
            price_row = prices.loc[pd.Timestamp(today_date)]
        else:
            # Use most recent available
            recent_prices = prices[prices.index <= pd.Timestamp(today_date)]
            if len(recent_prices) > 0:
                price_row = recent_prices.iloc[-1]
            else:
                price_row = None

        allocation_data = []
        if price_row is not None and sp3_result.get("shares_held"):
            # Calculate current market value of all accumulated positions
            position_values = []
            total_portfolio_value = 0

            for ticker, shares in sp3_result["shares_held"].items():
                try:
                    price = price_row.get(ticker)
                    if price and not pd.isna(price) and price > 0:
                        position_value = shares * price
                        total_portfolio_value += position_value
                        position_values.append({
                            "ticker": ticker,
                            "shares": shares,
                            "price": price,
                            "value": position_value,
                        })
                except Exception as e:
                    logger.debug(f"Error calculating position for {ticker}: {e}")

            # Sort by value descending
            position_values.sort(key=lambda x: x["value"], reverse=True)

            # Build allocation data for top positions (cap at 20 for pie chart)
            if total_portfolio_value > 0:
                for pos in position_values[:20]:
                    weight = (pos["value"] / total_portfolio_value) * 100
                    allocation_data.append({
                        "ticker": pos["ticker"],
                        "weight": round(weight, 1),
                        "value": round(pos["value"], 2),
                        "shares": round(pos["shares"], 4),
                    })
                    logger.info(f"  {pos['ticker']}: {weight:.1f}% (${pos['value']:,.0f}, {pos['shares']:.0f} shares)")

        # 8. Store in database
        snapshot = AnalyticsSnapshot(
            snapshot_date=date.today(),
            sp3_total_return_pct=sp3_metrics["total_return_pct"],
            sp3_annualized_return=sp3_metrics["annualized_return"],
            sp3_max_drawdown=sp3_metrics["max_drawdown"],
            sp3_sharpe_ratio=sp3_metrics["sharpe_ratio"],
            sp3_volatility=sp3_metrics["volatility"],
            sp3_position_value=int(sp3_result["portfolio_values"][-1]) if sp3_result["portfolio_values"] else 0,
            sp500_total_return_pct=sp500_metrics["total_return_pct"],
            sp500_annualized_return=sp500_metrics["annualized_return"],
            sp500_max_drawdown=sp500_metrics["max_drawdown"],
            sp500_sharpe_ratio=sp500_metrics["sharpe_ratio"],
            sp500_volatility=sp500_metrics["volatility"],
            risk_grade=risk_grade,
            risk_description=risk_desc,
            weekly_chart_data=json.dumps(chart_data),
            current_allocation=json.dumps(allocation_data),
            calculation_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
        )

        # Delete old snapshots (keep only last 30 days)
        cutoff_date = date.today() - timedelta(days=30)
        db.query(AnalyticsSnapshot).filter(AnalyticsSnapshot.snapshot_date < cutoff_date).delete()

        db.add(snapshot)
        db.commit()

        elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.info(f"✓ Analytics snapshot refreshed in {elapsed_ms:.0f}ms")

    except Exception as e:
        logger.error(f"✗ Analytics refresh failed: {e}", exc_info=True)
        db.rollback()
        raise


def simulate_dca_portfolio_single(
    prices_df: pd.DataFrame, weekly_budget: float = WEEKLY_BUDGET
) -> dict:
    """
    Simplified DCA simulation for single ticker (SPY).
    Tracks cumulative shares and calculates portfolio value based on current price.
    """
    logger.info(f"[SPY DCA] Starting simulation with {len(prices_df)} weeks, budget=${weekly_budget}/week")
    logger.info(f"[SPY DCA] DataFrame shape: {prices_df.shape}, columns: {prices_df.columns.tolist()}")
    if len(prices_df) > 0:
        logger.info(f"[SPY DCA] First price row: {dict(prices_df.iloc[0])}")
        logger.info(f"[SPY DCA] Last price row: {dict(prices_df.iloc[-1])}")

    total_shares = 0.0
    portfolio_values = []
    cumulative_invested_values = []
    dates = []
    total_invested = 0

    for idx, (date, price_row) in enumerate(prices_df.iterrows()):
        date_str = date.strftime("%Y-%m-%d")
        dates.append(date_str)

        # Get current price (price_row is a Series with ticker as index)
        current_price = None
        if len(price_row) > 0:
            # For single ticker DataFrame, price_row has one element
            current_price = float(price_row.iloc[0])

        if current_price is not None and not pd.isna(current_price) and current_price > 0:
            # Buy this week
            shares_to_buy = weekly_budget / current_price
            total_shares += shares_to_buy
            total_invested += weekly_budget

            # Calculate portfolio value
            portfolio_value = total_shares * current_price

            if idx < 3 or idx >= len(prices_df) - 3:
                logger.info(f"[SPY DCA] Week {idx} ({date_str}): price=${current_price:.2f}, bought {shares_to_buy:.4f} shares, total_shares={total_shares:.4f}, portfolio_value=${portfolio_value:.2f}")
        else:
            # Use previous value if price is missing
            portfolio_value = portfolio_values[-1] if portfolio_values else 0
            logger.warning(f"[SPY DCA] Week {idx} ({date_str}): Invalid price={current_price}, using previous value=${portfolio_value:.2f}")

        portfolio_values.append(portfolio_value)
        cumulative_invested_values.append(total_invested)

    logger.info(f"[SPY DCA] Simulation complete: {len(portfolio_values)} weeks, final value=${portfolio_values[-1]:.2f}, total invested=${total_invested:.2f}")

    return {
        "portfolio_values": portfolio_values,
        "dates": dates,
        "total_invested": total_invested,
        "cumulative_invested": cumulative_invested_values,
    }


def calculate_metrics(total_invested: float, portfolio_values: list[float], years: float) -> dict:
    """
    Calculate performance metrics from portfolio values.
    """
    if len(portfolio_values) == 0 or portfolio_values[-1] <= 0:
        return {
            "total_return_pct": 0,
            "annualized_return": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "volatility": 0,
        }

    final_value = portfolio_values[-1]
    total_return = final_value - total_invested
    total_return_pct = (total_return / total_invested * 100) if total_invested > 0 else 0

    def safe_val(v):
        """Convert None/NaN to 0."""
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return 0.0
        return float(v)

    annualized_return = safe_val(calculate_cagr(total_invested, final_value, years))
    max_drawdown = safe_val(calculate_max_drawdown(portfolio_values))
    volatility = safe_val(calculate_volatility(portfolio_values))
    sharpe = safe_val(calculate_sharpe_ratio(pd.Series(portfolio_values).pct_change().dropna()))

    return {
        "total_return_pct": total_return_pct,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "volatility": volatility,
    }
