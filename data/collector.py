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


def get_korea_stock_data(ticker: str, period_days: int = 90) -> pd.DataFrame:
    """Fetch Korean stock data via yfinance."""
    try:
        yf_ticker = _kr_ticker_to_yf(ticker)
        stock = yf.Ticker(yf_ticker)
        df = stock.history(period=f"{period_days}d")
        if df.empty:
            return pd.DataFrame()
        df.reset_index(inplace=True)
        df["ticker"] = ticker
        df["market"] = "KR"
        df.rename(columns={
            "Open": "Open", "High": "High", "Low": "Low",
            "Close": "Close", "Volume": "Volume",
        }, inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


def get_korea_stock_info(ticker: str) -> dict:
    """Fetch Korean stock basic info via yfinance."""
    try:
        yf_ticker = _kr_ticker_to_yf(ticker)
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
        return {"ticker": ticker, "name": ""}



