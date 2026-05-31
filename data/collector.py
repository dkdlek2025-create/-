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
    """Fetch US stock data via yfinance."""
    stock = yf.Ticker(ticker)
    df = stock.history(period=period, interval=interval)
    if df.empty:
        return pd.DataFrame()
    df.reset_index(inplace=True)
    df["ticker"] = ticker
    df["market"] = "US"
    return df


def get_us_stock_info(ticker: str) -> dict:
    """Fetch US stock fundamental info."""
    stock = yf.Ticker(ticker)
    info = stock.info
    return {
        "ticker": ticker,
        "name": info.get("longName", info.get("shortName", "")),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "market_cap": info.get("marketCap", 0),
        "pe_ratio": info.get("trailingPE", 0),
        "dividend_yield": info.get("dividendYield", 0),
        "eps": info.get("trailingEps", 0),
        "high_52w": info.get("fiftyTwoWeekHigh", 0),
        "low_52w": info.get("fiftyTwoWeekLow", 0),
        "volume_avg": info.get("averageVolume", 0),
    }


def _fetch_yahoo_chart(yf_ticker: str, range_days: int = 180) -> pd.DataFrame:
    """
    Fetch stock data directly from Yahoo Finance chart API.
    More reliable than yfinance for non-US markets on cloud servers.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}?range={range_days}d&interval=1d"
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        result = data.get("chart", {}).get("result", [None])[0]
        if not result:
            return pd.DataFrame()
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        adjclose = result.get("indicators", {}).get("adjclose", [{}])[0]
        if not timestamps or not quotes:
            return pd.DataFrame()
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
        return df
    except Exception:
        return pd.DataFrame()


def get_korea_stock_data(ticker: str, period_days: int = 180) -> pd.DataFrame:
    """Fetch Korean stock data: try yfinance first, fall back to direct API."""
    yf_ticker = _kr_ticker_to_yf(ticker)

    # Try yfinance first (fast, works locally)
    try:
        stock = yf.Ticker(yf_ticker)
        df = stock.history(period=f"{period_days}d")
        if not df.empty:
            df.reset_index(inplace=True)
            df["ticker"] = ticker
            df["market"] = "KR"
            return df
    except Exception:
        pass

    # Fallback: direct Yahoo Finance chart API
    df = _fetch_yahoo_chart(yf_ticker, range_days=period_days)
    if not df.empty:
        df["ticker"] = ticker
        df["market"] = "KR"
        return df

    return pd.DataFrame()


def get_korea_stock_info(ticker: str) -> dict:
    """Fetch Korean stock basic info via yfinance or direct API."""
    yf_ticker = _kr_ticker_to_yf(ticker)
    try:
        stock = yf.Ticker(yf_ticker)
        info = stock.info
        return {
            "ticker": ticker,
            "name": info.get("longName", info.get("shortName", "")),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market": info.get("market", "KOSPI"),
        }
    except Exception:
        pass

    # Fallback: direct API for basic info
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}?range=1d&interval=1d"
        r = session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
        return {
            "ticker": ticker,
            "name": meta.get("symbol", ticker),
            "sector": "",
            "industry": "",
            "market": meta.get("exchangeName", "KOSPI"),
        }
    except Exception:
        return {"ticker": ticker, "name": ""}



