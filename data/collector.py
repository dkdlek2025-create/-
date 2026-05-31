import json
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import yfinance as yf
import requests

# Configure yfinance global session with timeout + User-Agent
_yf_session = requests.Session()
_yf_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
_yf_session.timeout = 30
yf._session = _yf_session


def _kr_ticker_to_yf(ticker: str) -> str:
    """Convert Korean ticker (005930) to yfinance format (005930.KS)."""
    t = ticker.strip()
    if "." in t:
        return t
    return f"{t}.KS"


def get_us_stock_data(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """Fetch US stock data: direct API (more reliable than yfinance on cloud)."""
    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 180)
    # Try yfinance as first fallback
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        if not df.empty:
            df.reset_index(inplace=True)
            df["ticker"] = ticker
            df["market"] = "US"
            return df
    except Exception:
        pass
    # Direct Yahoo Finance chart API
    df = _fetch_yahoo_chart(ticker, range_days=period_days)
    if not df.empty:
        df["ticker"] = ticker
        df["market"] = "US"
        return df
    return pd.DataFrame()


def get_us_stock_info(ticker: str) -> dict:
    """Fetch US stock info: universe cache first, then direct API."""
    from scanner.universe import universe as _universe
    for s in _universe.get_all_us():
        if s["ticker"] == ticker.upper():
            return {
                "ticker": ticker,
                "name": s.get("name", ticker),
                "sector": s.get("sector", ""),
                "industry": s.get("industry", ""),
                "market_cap": 0, "pe_ratio": 0, "dividend_yield": 0,
                "eps": 0, "high_52w": 0, "low_52w": 0, "volume_avg": 0,
            }
    return {"ticker": ticker, "name": ""}


def _fetch_yahoo_chart(yf_ticker: str, range_days: int = 180) -> pd.DataFrame:
    """
    Fetch stock data directly from Yahoo Finance chart API with retry.
    More reliable than yfinance for cloud servers.
    """
    import time as _time
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}?range={range_days}d&interval=1d",
        f"https://query2.finance.yahoo.com/v8/finance/chart/{yf_ticker}?range={range_days}d&interval=1d",
    ]
    for attempt in range(3):
        for url in urls:
            try:
                r = session.get(url, timeout=30)
                if r.status_code == 429:
                    _time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                data = r.json()
                result = data.get("chart", {}).get("result", [None])[0]
                if not result:
                    continue
                timestamps = result.get("timestamp", [])
                quotes = result.get("indicators", {}).get("quote", [{}])[0]
                adjclose = result.get("indicators", {}).get("adjclose", [{}])[0]
                if not timestamps or not quotes:
                    continue
                ohlcv = {
                    "Date": [datetime.fromtimestamp(ts) for ts in timestamps],
                    "Open": quotes.get("open", []),
                    "High": quotes.get("high", []),
                    "Low": quotes.get("low", []),
                    "Close": adjclose.get("adjclose", quotes.get("close", [])),
                    "Volume": quotes.get("volume", []),
                }
                df = pd.DataFrame(ohlcv)
                df.dropna(subset=["Close"], inplace=True)
                if not df.empty:
                    return df
            except Exception:
                continue
        _time.sleep(1)
    return pd.DataFrame()


def get_korea_stock_data(ticker: str, period_days: int = 180) -> pd.DataFrame:
    """Fetch Korean stock data: direct API (more reliable on cloud)."""
    yf_ticker = _kr_ticker_to_yf(ticker)
    # Direct Yahoo Finance chart API
    df = _fetch_yahoo_chart(yf_ticker, range_days=period_days)
    if not df.empty:
        df["ticker"] = ticker
        df["market"] = "KR"
        return df
    return pd.DataFrame()


def get_korea_stock_info(ticker: str) -> dict:
    """Fetch Korean stock info from universe cache."""
    from scanner.universe import universe as _universe
    for s in _universe.get_all_kr():
        if s["ticker"] == ticker:
            return {
                "ticker": ticker,
                "name": s.get("name", ticker),
                "sector": s.get("sector", ""),
                "industry": s.get("industry", ""),
                "market": s.get("market", "KOSPI"),
            }
    return {"ticker": ticker, "name": ""}



