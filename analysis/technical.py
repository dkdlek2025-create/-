import pandas as pd
import numpy as np


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add common technical indicators to price DataFrame."""
    if df.empty:
        return df

    df = df.copy()
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # Moving averages
    df["MA5"] = close.rolling(5).mean()
    df["MA20"] = close.rolling(20).mean()
    df["MA60"] = close.rolling(60).mean()
    df["MA120"] = close.rolling(120).mean()

    # Exponential moving averages
    df["EMA12"] = close.ewm(span=12).mean()
    df["EMA26"] = close.ewm(span=26).mean()

    # MACD
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_signal"] = df["MACD"].ewm(span=9).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    # RSI (14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    df["RSI"] = 100 - (100 / (1 + rs))

    # Bollinger Bands (20, 2)
    df["BB_middle"] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["BB_upper"] = df["BB_middle"] + 2 * bb_std
    df["BB_lower"] = df["BB_middle"] - 2 * bb_std

    # Stochastic %K (14,3)
    low_14 = low.rolling(14).min()
    high_14 = high.rolling(14).max()
    df["STOCH_K"] = 100 * ((close - low_14) / (high_14 - low_14 + 1e-10))
    df["STOCH_D"] = df["STOCH_K"].rolling(3).mean()

    # Volume indicators
    df["Volume_MA5"] = volume.rolling(5).mean()
    df["Volume_ratio"] = volume / (df["Volume_MA5"] + 1e-10)

    # Rate of Change
    df["ROC"] = close.pct_change(12) * 100

    # CCI (20)
    tp = (high + low + close) / 3
    df["CCI"] = (tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).std() + 1e-10)

    # ATR (14)
    tr = pd.concat([
        high - low,
        abs(high - close.shift(1)),
        abs(low - close.shift(1)),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()

    # OBV
    obv = (volume * (close.diff() > 0).astype(int) - volume * (close.diff() < 0).astype(int)).cumsum()
    df["OBV"] = obv

    return df


def generate_technical_signal(df: pd.DataFrame) -> dict:
    """Generate buy/sell signals based on technical indicators."""
    if df.empty or len(df) < 60:
        return {"signal": "HOLD", "score": 0, "details": "데이터 부족"}

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    reasons = []

    # MA crossover signal
    if not pd.isna(latest["MA5"]) and not pd.isna(latest["MA20"]):
        if latest["MA5"] > latest["MA20"] and prev["MA5"] <= prev["MA20"]:
            score += 15
            reasons.append("골든크로스(5일-20일)")
        elif latest["MA5"] < latest["MA20"] and prev["MA5"] >= prev["MA20"]:
            score -= 15
            reasons.append("데드크로스(5일-20일)")

    # RSI signal
    if not pd.isna(latest["RSI"]):
        if latest["RSI"] < 30:
            score += 20
            reasons.append(f"RSI 과매도({latest['RSI']:.1f})")
        elif latest["RSI"] > 70:
            score -= 20
            reasons.append(f"RSI 과매수({latest['RSI']:.1f})")
        elif latest["RSI"] < 40:
            score += 5
            reasons.append(f"RSI 저점({latest['RSI']:.1f})")
        elif latest["RSI"] > 60:
            score -= 5
            reasons.append(f"RSI 고점({latest['RSI']:.1f})")

    # MACD signal
    if not pd.isna(latest["MACD"]) and not pd.isna(latest["MACD_signal"]):
        if latest["MACD"] > latest["MACD_signal"] and prev["MACD"] <= prev["MACD_signal"]:
            score += 20
            reasons.append("MACD 골든크로스")
        elif latest["MACD"] < latest["MACD_signal"] and prev["MACD"] >= prev["MACD_signal"]:
            score -= 20
            reasons.append("MACD 데드크로스")

    # Bollinger Band signal
    if not pd.isna(latest["BB_lower"]) and not pd.isna(latest["BB_upper"]):
        if latest["Close"] <= latest["BB_lower"]:
            score += 15
            reasons.append("BB 하단 돌파 (과매도)")
        elif latest["Close"] >= latest["BB_upper"]:
            score -= 15
            reasons.append("BB 상단 돌파 (과매수)")

    # Volume signal
    if not pd.isna(latest["Volume_ratio"]):
        if latest["Volume_ratio"] > 1.5 and latest["Close"] > prev["Close"]:
            score += 10
            reasons.append("거래량 급증 + 상승")
        elif latest["Volume_ratio"] > 1.5 and latest["Close"] < prev["Close"]:
            score -= 10
            reasons.append("거래량 급증 + 하락")

    # CCI signal
    if not pd.isna(latest["CCI"]):
        if latest["CCI"] < -100:
            score += 10
        elif latest["CCI"] > 100:
            score -= 10

    # Stochastic signal
    if not pd.isna(latest["STOCH_K"]) and not pd.isna(latest["STOCH_D"]):
        if latest["STOCH_K"] < 20 and latest["STOCH_K"] > latest["STOCH_D"]:
            score += 10
            reasons.append("Stochastic 반등 신호")
        elif latest["STOCH_K"] > 80 and latest["STOCH_K"] < latest["STOCH_D"]:
            score -= 10
            reasons.append("Stochastic 하락 신호")

    # Determine signal
    if score >= 30:
        signal = "STRONG_BUY"
    elif score >= 15:
        signal = "BUY"
    elif score <= -30:
        signal = "STRONG_SELL"
    elif score <= -15:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "signal": signal,
        "score": score,
        "reasons": reasons,
        "latest_price": round(latest["Close"], 2),
        "rsi": round(latest["RSI"], 1) if not pd.isna(latest["RSI"]) else None,
        "macd": round(latest["MACD"], 2) if not pd.isna(latest["MACD"]) else None,
    }
