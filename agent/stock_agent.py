"""
Stock AI Agent - Unified analysis combining technical indicators + news sentiment.
Outputs clear BUY/HOLD/SELL recommendations with reasoning.
"""
import numpy as np
import pandas as pd
from typing import Optional

from data.collector import (
    get_us_stock_data, get_us_stock_info,
    get_korea_stock_data, get_korea_stock_info,
)
from analysis.technical import add_technical_indicators, generate_technical_signal
from analysis.news_analyzer import news_analyzer
from scanner.universe import universe as stock_universe


class StockAgent:
    """Combines chart analysis + news to produce final recommendations."""

    def __init__(self):
        pass

    def analyze_ticker(self, ticker: str, market: str = "auto") -> dict:
        """Full analysis: chart + news → unified recommendation."""
        if market == "auto":
            market = "us" if ticker.isalpha() else "korea"

        # --- 1. Fetch price data ---
        if market == "us":
            df = get_us_stock_data(ticker, period="6mo")
            info = get_us_stock_info(ticker)
        else:
            df = get_korea_stock_data(ticker, period_days=180)
            info = get_korea_stock_info(ticker)

        if df.empty:
            return {"error": f"{ticker} 데이터 없음"}

        name = info.get("name", ticker)
        # Override with Korean name if available
        if market == "korea":
            for s in stock_universe.get_all_kr():
                if s["ticker"] == ticker:
                    kr_name = s.get("name", "")
                    if kr_name:
                        name = kr_name
                    break

        # --- 2. Technical analysis ---
        df = add_technical_indicators(df)
        tech_signal = generate_technical_signal(df)
        entry_exit = self._analyze_entry_exit(df)

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        change_pct = ((latest["Close"] - prev["Close"]) / prev["Close"]) * 100
        price_data = {
            "price": round(latest["Close"], 2),
            "change": round(change_pct, 2),
            "high_20d": round(df["High"].tail(20).max(), 2),
            "low_20d": round(df["Low"].tail(20).min(), 2),
        }

        # --- 3. News analysis ---
        news_result = news_analyzer.analyze_ticker_news(ticker, market)
        tech_score = entry_exit.get("net_score", 0)  # -9 ~ +9
        news_score = news_result.get("overall_score", 0)  # negative ~ positive

        # --- 4. COMBINED DECISION ---
        decision = self._combine_decisions(
            ticker=ticker, name=name,
            tech_score=tech_score,
            tech_signal=tech_signal.get("signal", "HOLD"),
            news_overall=news_result.get("overall", "중립"),
            news_score=news_score,
            entry_exit=entry_exit,
        )

        return {
            "decision": decision,
            "ticker": ticker,
            "name": name,
            "market": market.upper(),
            "price_data": price_data,
            "technical": {
                "signal": tech_signal.get("signal", "HOLD"),
                "score": tech_signal.get("score", 0),
                "rsi": tech_signal.get("rsi", "N/A"),
                "macd": tech_signal.get("macd", "N/A"),
                "reasons": tech_signal.get("reasons", []),
            },
            "entry_exit": entry_exit,
            "news": news_result,
            "info": info,
        }

    def _combine_decisions(self, ticker: str, name: str,
                            tech_score: int, tech_signal: str,
                            news_overall: str, news_score: float,
                            entry_exit: dict) -> dict:
        """
        Weighted decision matrix:
          tech_score (-9~+9) + news_score (-3~+3 weighted to -6~+6)
          = final_score (-15~+15)
        """
        # Normalize news score to match technical scale
        news_weighted = news_score * 2  # Scale to roughly -6 ~ +6
        combined_score = tech_score + news_weighted

        # Clamp to -15 ~ +15
        combined_score = max(-15, min(15, combined_score))

        # Determine action
        if combined_score >= 8:
            action = "적극매수"
            reason = "chart+news 모두 강력 긍정"
        elif combined_score >= 4:
            action = "매수"
            reason = "chart+news 긍정적"
        elif combined_score >= 1:
            action = "관심매수"
            reason = "일부 긍정 신호"
        elif combined_score <= -8:
            action = "적극매도"
            reason = "chart+news 모두 부정적"
        elif combined_score <= -4:
            action = "매도"
            reason = "chart+news 부정적"
        elif combined_score <= -1:
            action = "관망/부분익절"
            reason = "일부 부정 신호"
        else:
            action = "관망"
            reason = "뚜렷한 신호 없음"

        # Confidence
        abs_score = abs(combined_score)
        if abs_score >= 10:
            conviction = "매우강함"
        elif abs_score >= 6:
            conviction = "강함"
        elif abs_score >= 3:
            conviction = "중간"
        else:
            conviction = "약함"

        # Detailed reasoning
        tech_summary = f"차트 {tech_signal} ({tech_score}점)"
        news_pct = max(0, min(100, int(((news_score + 3) / 6) * 100)))
        news_summary = f"뉴스 {news_overall} ({news_pct}%)"

        chart_vs_news = ""
        if tech_score >= 2 and news_score <= -1.5:
            chart_vs_news = "⚠️ 차트는 긍정적이나 뉴스가 부정적입니다. 뉴스 확인 후 신중한 접근 필요."
        elif tech_score <= -2 and news_score >= 1.5:
            chart_vs_news = "⚠️ 뉴스는 호재이나 차트가 약합니다. 추가 하락 가능성 대비."

        return {
            "action": action,
            "conviction": conviction,
            "combined_score": combined_score,
            "tech_score": tech_score,
            "news_score": news_score,
            "tech_summary": tech_summary,
            "news_summary": news_summary,
            "reason": reason,
            "chart_vs_news_conflict": chart_vs_news,
            "entry_exit_ref": {
                "entry_zone": entry_exit.get("entry_zone_text", "N/A"),
                "target": entry_exit.get("target_text", "N/A"),
                "stop_loss": entry_exit.get("stop_loss_text", "N/A"),
                "rr": entry_exit.get("risk_reward_ratio", "N/A"),
            },
        }

    def _analyze_entry_exit(self, df: pd.DataFrame) -> dict:
        """Entry zone, targets, stop-loss based on support/resistance + Fibonacci."""
        if df.empty or len(df) < 20:
            return {}

        close = df["Close"].values
        high = df["High"].values
        low = df["Low"].values
        latest_price = close[-1]

        recent_high = np.max(high[-20:])
        recent_low = np.min(low[-20:])
        fib_range = recent_high - recent_low

        fib_levels = {
            "0.236": recent_high - 0.236 * fib_range,
            "0.382": recent_high - 0.382 * fib_range,
            "0.500": recent_high - 0.500 * fib_range,
            "0.618": recent_high - 0.618 * fib_range,
            "0.786": recent_high - 0.786 * fib_range,
        }

        # Entry Zone
        current_rsi = df["RSI"].iloc[-1] if not pd.isna(df["RSI"].iloc[-1]) else 50
        entry_zone = []
        if current_rsi < 35:
            entry_zone.append(round(recent_low * 0.98, 2))
            entry_zone.append(round(fib_levels["0.618"], 2))
        elif current_rsi > 65:
            entry_zone.append(round(fib_levels["0.500"], 2))
            entry_zone.append(round(fib_levels["0.382"], 2))
        else:
            entry_zone.append(round(recent_low, 2))
            entry_zone.append(round(fib_levels["0.500"], 2))
        entry_zone = sorted(set(entry_zone))

        # Targets
        ext_range = recent_high - recent_low
        targets = [
            round(recent_high + 0.382 * ext_range, 2),
            round(recent_high + 0.618 * ext_range, 2),
            round(recent_high + 1.000 * ext_range, 2),
        ]

        # Stop Loss
        stop_loss = round(min(recent_low * 0.97, fib_levels["0.786"]), 2)

        # Risk/Reward
        best_entry = min(entry_zone) if entry_zone else latest_price
        risk = abs(latest_price - stop_loss) / latest_price * 100 if latest_price else 0
        reward = abs(targets[0] - best_entry) / best_entry * 100 if best_entry else 0
        rr = round(reward / risk, 2) if risk > 0 else 0

        # --- Scoring (multi-confirmation) ---
        buy_score = 0
        sell_score = 0

        if current_rsi < 35: buy_score += 2
        elif current_rsi < 40: buy_score += 1
        elif current_rsi > 65: sell_score += 2
        elif current_rsi > 60: sell_score += 1

        ma20 = df["MA20"].iloc[-1] if not pd.isna(df["MA20"].iloc[-1]) else 0
        ma50 = df["MA60"].iloc[-1] if not pd.isna(df["MA60"].iloc[-1]) else 0

        if latest_price < ma20 and latest_price < ma50:
            buy_score += 2
        elif latest_price < ma20:
            buy_score += 1
        if latest_price > ma20 * 1.1:
            sell_score += 2
        elif latest_price > ma20 * 1.05:
            sell_score += 1

        vol_ratio = df["Volume_ratio"].iloc[-1] if not pd.isna(df["Volume_ratio"].iloc[-1]) else 1
        if vol_ratio > 1.5 and close[-1] > close[-2]:
            buy_score += 1
        elif vol_ratio > 1.5 and close[-1] < close[-2]:
            sell_score += 1

        macd = df["MACD"].iloc[-1] if not pd.isna(df["MACD"].iloc[-1]) else 0
        macd_signal = df["MACD_signal"].iloc[-1] if not pd.isna(df["MACD_signal"].iloc[-1]) else 0
        macd_prev = df["MACD"].iloc[-2] if not pd.isna(df["MACD"].iloc[-2]) else 0
        if macd > macd_signal and macd > macd_prev: buy_score += 1
        elif macd < macd_signal and macd < macd_prev: sell_score += 1

        bb_lower = df["BB_lower"].iloc[-1] if not pd.isna(df["BB_lower"].iloc[-1]) else 0
        bb_upper = df["BB_upper"].iloc[-1] if not pd.isna(df["BB_upper"].iloc[-1]) else 0
        if bb_lower and latest_price <= bb_lower: buy_score += 2
        elif bb_upper and latest_price >= bb_upper: sell_score += 2

        if latest_price <= recent_low * 1.02: buy_score += 1
        if latest_price >= recent_high * 0.98: sell_score += 1

        net = buy_score - sell_score

        return {
            "net_score": net,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "entry_zone": entry_zone,
            "entry_zone_text": f"{min(entry_zone):,.0f} ~ {max(entry_zone):,.0f}" if len(entry_zone) > 1 else f"{entry_zone[0]:,.0f}",
            "targets": targets,
            "target_text": f"1차 {targets[0]:,.0f} / 2차 {targets[1]:,.0f} / 3차 {targets[2]:,.0f}",
            "stop_loss": round(stop_loss, 2),
            "stop_loss_text": f"{stop_loss:,.0f}",
            "risk_pct": round(risk, 1),
            "reward_pct": round(reward, 1),
            "risk_reward_ratio": rr,
            "support": round(recent_low, 2),
            "resistance": round(recent_high, 2),
            "fib_levels": {k: round(v, 2) for k, v in fib_levels.items()},
        }

    def analyze_alert(self, ticker: str, alert_type: str, alert_msg: str,
                      market: str = "auto") -> dict:
        """Quick analysis for scanner-triggered alerts."""
        result = self.analyze_ticker(ticker, market)
        if "error" in result:
            return result

        decision = result.get("decision", {})
        entry = decision.get("entry_exit_ref", {})

        # Conflict warning
        conflict = decision.get("chart_vs_news_conflict", "")

        msg = (
            f"[{alert_type.upper()}] {result['name']} ({ticker})\n"
            f"{alert_msg}\n"
            f"현재가: {result['price_data']['price']} ({result['price_data']['change']:+.2f}%)\n"
            f"\n"
            f"📊 차트: {decision.get('tech_summary', '')}\n"
            f"📰 뉴스: {decision.get('news_summary', '')}\n"
            f"⚖️ 종합: {decision.get('action', '관망')} (확신도: {decision.get('conviction', '')})\n"
        )

        if conflict:
            msg += f"\n{conflict}\n"

        msg += (
            f"\n💰 진입: {entry.get('entry_zone', 'N/A')}\n"
            f"🎯 목표: {entry.get('target', 'N/A')}\n"
            f"🛑 손절: {entry.get('stop_loss', 'N/A')}\n"
            f"⚖️ R/R: {entry.get('rr', 'N/A')}"
        )

        result["alert_summary"] = msg
        return result


agent = StockAgent()
