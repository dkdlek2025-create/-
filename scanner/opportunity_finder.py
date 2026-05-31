"""
Opportunity Finder - Two-pass scanner:
  Pass 1: Quick-scan ALL stocks (3000+) → filter anomalies
  Pass 2: Full chart+news analysis on candidates → only winners
"""
import time
import logging
from datetime import datetime
import database as db
from typing import Optional
import pandas as pd
import numpy as np

from scanner.universe import universe
from agent.stock_agent import agent
from data.collector import get_us_stock_data, get_korea_stock_data
from analysis.technical import add_technical_indicators, generate_technical_signal

logger = logging.getLogger(__name__)


class Opportunity:
    """A filtered opportunity that passed both chart + news filters."""

    def __init__(self, ticker: str, name: str, market: str,
                 combined_action: str, combined_score: int,
                 conviction: str, tech_score: int, news_score: float,
                 reason: str, entry_zone: str, entry_zone_list: list,
                 target: str, targets_list: list,
                 stop_loss: str, stop_loss_val: float,
                 rr: float, current_price: float,
                 news_summary: str, news_score_pct: int = 50,
                 news_bullish: str = "", news_bearish: str = "",
                 conflict_warning: str = ""):
        self.ticker = ticker
        self.name = name
        self.market = market
        self.action = combined_action
        self.score = combined_score
        self.conviction = conviction
        self.tech_score = tech_score
        self.news_score = news_score
        self.news_score_pct = news_score_pct
        self.news_bullish = news_bullish
        self.news_bearish = news_bearish
        self.reason = reason
        self.entry_zone = entry_zone
        self.entry_zone_list = entry_zone_list
        self.target = target
        self.targets_list = targets_list
        self.stop_loss = stop_loss
        self.stop_loss_val = stop_loss_val
        self.rr = rr
        self.current_price = current_price
        self.news_summary = news_summary
        self.conflict = conflict_warning
        self.timestamp = datetime.now()

    @property
    def score_pct(self) -> int:
        """Convert -15~+15 score to 0~100%."""
        return int(((self.score + 15) / 30) * 100)

    @property
    def entry_advice(self) -> str:
        """When to enter."""
        if self.score_pct >= 70:
            return f"지금 즉시 진입 가능 (추천 {self.score_pct}%)"
        elif self.score_pct >= 50:
            return f"진입구간({self.entry_zone}) 도달시 분할 매수"
        elif self.score_pct >= 30:
            return f"관망 권장, 추가 하락시 {self.entry_zone} 구간 진입 고려"
        return "진입 비추천, 보유중이면 매도 고려"

    @property
    def exit_advice(self) -> str:
        """When to sell with staged exit plan."""
        if not self.targets_list or len(self.targets_list) < 3:
            return "목표가 정보 없음"
        t1, t2, t3 = self.targets_list[0], self.targets_list[1], self.targets_list[2]
        return (
            f"1차 {t1:,} 도달 → 50% 익절\n"
            f"2차 {t2:,} 도달 → 30% 추가 익절 (총 80%)\n"
            f"3차 {t3:,} 도달 → 나머지 20% 익절 (완전 청산)"
        )

    @property
    def stop_advice(self) -> str:
        """When to cut losses."""
        return f"{self.stop_loss} 이하 하락시 즉시 손절 (손실률 {self.stop_loss_pct:.1f}% 이내)"

    @property
    def stop_loss_pct(self) -> float:
        if self.current_price and self.current_price > 0 and self.stop_loss_val and self.stop_loss_val > 0:
            return abs((self.current_price - self.stop_loss_val) / self.current_price * 100)
        return 0

    def to_telegram_msg(self) -> str:
        """Format as clear actionable Telegram message."""
        market_flag = "🇺🇸" if self.market == "us" else "🇰🇷"

        # Progress bar style
        bar_len = 10
        filled = int(self.score_pct / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        action_emoji = {"적극매수": "🟢🟢", "매수": "🟢", "관심매수": "✅",
                        "관망": "⚪", "관망/부분익절": "🔶", "매도": "🔴", "적극매도": "🔴🔴"}

        msg = (
            f"{market_flag} {self.name} ({self.ticker})\n"
            f"\n"
            f"📊 추천 강도: {self.score_pct}%\n"
            f"  {bar} ({self.score_pct}%)\n"
            f"  차트 {self.tech_score:+d} | 뉴스 {self.news_score_pct}% | 종합 {self.score:+.0f}/15\n"
            f"\n"
            f"⚖️ 판정: {action_emoji.get(self.action, '')} {self.action}\n"
            f"📌 근거: {self.reason}\n"
            f"\n"
            f"🔥 실행 가이드\n"
            f"────────────────\n"
            f"✅ 진입: {self.entry_advice}\n"
            f"💰 구간: {self.entry_zone}\n"
            f"\n"
            f"🏁 익절:\n{self.exit_advice}\n"
            f"\n"
            f"🛑 손절: {self.stop_advice}\n"
            f"⚖️ R/R 비율: {self.rr}\n"
        )

        if self.news_summary:
            msg += f"\n📰 뉴스: {self.news_score_pct}%"
            if self.news_bullish and self.news_bullish != "없음":
                msg += f"\n  🟢 호재: {self.news_bullish[:60]}"
            if self.news_bearish and self.news_bearish != "없음":
                msg += f"\n  🔴 악재: {self.news_bearish[:60]}"

        if self.conflict:
            msg += f"\n⚠️ {self.conflict}"

        return msg


class OpportunityFinder:
    """
    Scans entire market universe and returns only high-quality opportunities.
    
    Pass 1 (Quick Scan): Check ~3000 stocks for basic anomaly
    Pass 2 (Deep Scan): Full chart + news analysis on ~50 candidates
    Final Filter: Only return those with positive combined scores
    """

    def __init__(self):
        self._quick_cache: dict = {}

    def clear_cache(self):
        self._quick_cache.clear()

    def _quick_scan_korea(self, top_n: int = 0) -> list[dict]:
        """Pass 1: Quick scan Korean stocks via parallel Yahoo Finance API."""
        limit = top_n or 300
        kr_stocks = universe.get_all_kr(top_n=limit)
        kr_stocks = [s for s in kr_stocks if "." not in s["ticker"]]
        logger.info(f"KR scan: {len(kr_stocks)} stocks (top {limit})")
        if not kr_stocks:
            return []

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from data.collector import _fetch_yahoo_chart
        import threading

        candidates = []
        lock = threading.Lock()

        def _scan_one(stock: dict) -> None:
            raw_t = stock["ticker"]
            suffix = ".KQ" if stock.get("market") == "KOSDAQ" else ".KS"
            try:
                df = _fetch_yahoo_chart(raw_t + suffix, range_days=5)
                if len(df) < 3:
                    return
                close = df["Close"]
                vol = df["Volume"]
                latest = close.iloc[-1]
                prev = close.iloc[-2]
                change = ((latest - prev) / prev) * 100
                vol_latest = vol.iloc[-1] if not vol.empty else 0
                vol_avg = vol.tail(5).mean() if len(vol) >= 5 else vol_latest
                vol_ratio = vol_latest / vol_avg if vol_avg > 0 else 1
                delta = close.diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta).where(delta < 0, 0).rolling(14).mean()
                rs = gain / (loss + 1e-10)
                rsi_series = 100 - (100 / (1 + rs))
                rsi_val = rsi_series.iloc[-1] if not rsi_series.empty else 50
                if abs(change) >= 4 or vol_ratio >= 2.0 or rsi_val <= 32 or rsi_val >= 68:
                    with lock:
                        candidates.append({
                            "ticker": raw_t,
                            "name": stock.get("name", raw_t),
                            "market": "korea",
                            "change": round(change, 1),
                            "volume_ratio": round(vol_ratio, 1),
                            "rsi": round(rsi_val, 1),
                            "latest_price": round(latest, 0),
                        })
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(_scan_one, s) for s in kr_stocks]
            for i, f in enumerate(as_completed(futures)):
                f.result()
                if (i + 1) % 100 == 0:
                    logger.info(f"  KR pass1: {i+1}/{len(kr_stocks)}")

        logger.info(f"KR pass1: {len(candidates)} candidates")
        return candidates

    def _quick_scan_us(self, top_n: int = 0) -> list[dict]:
        """Pass 1: Quick scan US stocks via parallel Yahoo Finance API."""
        limit = top_n or 503
        us_stocks = universe.get_all_us(top_n=limit)
        us_stocks = [s for s in us_stocks if "." not in s["ticker"]]
        logger.info(f"US scan: {len(us_stocks)} stocks (top {limit})")
        if not us_stocks:
            return []

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from data.collector import _fetch_yahoo_chart
        import threading

        candidates = []
        lock = threading.Lock()

        def _scan_one(stock: dict) -> None:
            ticker = stock["ticker"]
            try:
                df = _fetch_yahoo_chart(ticker, range_days=5)
                if len(df) < 3:
                    return
                close = df["Close"]
                vol = df["Volume"]
                latest = close.iloc[-1]
                prev = close.iloc[-2]
                change = ((latest - prev) / prev) * 100
                vol_latest = vol.iloc[-1] if not vol.empty else 0
                vol_avg = vol.tail(5).mean() if len(vol) >= 5 else vol_latest
                vol_ratio = vol_latest / vol_avg if vol_avg > 0 else 1
                delta = close.diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta).where(delta < 0, 0).rolling(14).mean()
                rs = gain / (loss + 1e-10)
                rsi_series = 100 - (100 / (1 + rs))
                rsi_val = rsi_series.iloc[-1] if not rsi_series.empty else 50
                if abs(change) >= 4 or vol_ratio >= 2.0 or rsi_val <= 32 or rsi_val >= 68:
                    with lock:
                        candidates.append({
                            "ticker": ticker,
                            "name": stock.get("name", ticker),
                            "market": "us",
                            "change": round(change, 1),
                            "volume_ratio": round(vol_ratio, 1),
                            "rsi": round(rsi_val, 1),
                            "latest_price": round(latest, 2),
                        })
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(_scan_one, s) for s in us_stocks]
            for i, f in enumerate(as_completed(futures)):
                f.result()
                if (i + 1) % 100 == 0:
                    logger.info(f"  US pass1: {i+1}/{len(us_stocks)}")

        logger.info(f"US pass1: {len(candidates)} candidates")
        return candidates

    def _is_worth_telling(self, combined_score: int, action: str,
                           conviction: str, news_score: float) -> bool:
        """Final filter: is this worth pushing to the user?"""
        # Must be at least 관심매수 with 중간 conviction
        if action in ("적극매수", "매수"):
            return True
        if action == "관심매수" and conviction in ("강함", "매우강함"):
            return True
        if action == "관심매수" and news_score >= 1.0:
            return True
        # 적극매도/매도도 알려줄까? → 일단 제외 (유저가 원하는 건 좋은 종목)
        return False

    def find_opportunities(self, market: str = "all",
                           max_results: int = 5,
                           save_db: bool = False,
                           top_n: int = 0) -> list[Opportunity]:
        """
        Main entry point: find the best opportunities right now.
        market: "all", "korea", "us"
        max_results: max opportunities to return
        save_db: save scan results to database
        top_n: limit stocks to scan (0 = all)
        """
        start_time = time.time()
        opportunities = []
        scan_id = db.save_scan_start() if save_db else None

        # === PASS 1: Quick Scan ===
        all_candidates = []
        if market in ("all", "korea"):
            all_candidates.extend(self._quick_scan_korea(top_n=top_n))
        if market in ("all", "us"):
            all_candidates.extend(self._quick_scan_us(top_n=top_n))

        if not all_candidates:
            logger.warning("Pass 1: 0 candidates")
            return []

        # Sort by absolute change (most interesting first)
        all_candidates.sort(key=lambda x: abs(x.get("change", 0)), reverse=True)

        # Limit Pass 2 candidates (max 40 to keep it fast)
        pass2_candidates = all_candidates[:15]
        logger.info(f"Pass 2: analyzing {len(pass2_candidates)} candidates")

        # === PASS 2: Full Analysis ===
        for i, c in enumerate(pass2_candidates):
            try:
                result = agent.analyze_ticker(c["ticker"], c["market"])
                if "error" in result:
                    continue

                dec = result.get("decision", {})
                action = dec.get("action", "관망")
                conviction = dec.get("conviction", "")
                combined_score = dec.get("combined_score", 0)
                news_score = dec.get("news_score", 0)

                # === FINAL FILTER ===
                if not self._is_worth_telling(combined_score, action, conviction, news_score):
                    continue

                entry = result.get("entry_exit", {})
                news = result.get("news", {})

                targets = entry.get("targets", [0, 0, 0])
                stop_loss_val = entry.get("stop_loss", 0)
                current_price = result.get("price_data", {}).get("price", 0)

                opp = Opportunity(
                    ticker=c["ticker"],
                    name=result.get("name", c["ticker"]),
                    market=c["market"],
                    combined_action=action,
                    combined_score=combined_score,
                    conviction=conviction,
                    tech_score=dec.get("tech_score", 0),
                    news_score=news_score,
                    reason=dec.get("reason", ""),
                    entry_zone=entry.get("entry_zone_text", "N/A"),
                    entry_zone_list=entry.get("entry_zone", []),
                    target=entry.get("target_text", "N/A"),
                    targets_list=targets,
                    stop_loss=entry.get("stop_loss_text", "N/A"),
                    stop_loss_val=stop_loss_val,
                    rr=entry.get("risk_reward_ratio", 0),
                    current_price=current_price,
                    news_summary=news.get("summary", ""),
                    news_score_pct=news.get("overall_score_pct", 50),
                    news_bullish=news.get("bullish_summary", ""),
                    news_bearish=news.get("bearish_summary", ""),
                    conflict_warning=dec.get("chart_vs_news_conflict", ""),
                )
                opportunities.append(opp)

                if (i + 1) % 10 == 0:
                    logger.info(f"  pass2: {i+1}/{len(pass2_candidates)}")

            except Exception:
                continue

        # Sort by combined score descending
        opportunities.sort(key=lambda o: o.score, reverse=True)
        top = opportunities[:max_results]
        elapsed = time.time() - start_time

        logger.info(f"Done: {len(opportunities)} opportunities in {elapsed:.0f}s")
        for opp in top:
            logger.info(f"  {opp.name} ({opp.ticker}) | {opp.action} | score {opp.score:+.0f}")

        # Save to DB if requested
        if save_db and scan_id:
            try:
                db.save_opportunities(scan_id, opportunities)
            except Exception as e:
                logger.error(f"DB save error: {e}")
            try:
                db.save_scan_end(scan_id, len(all_candidates), len(opportunities))
            except Exception as e:
                logger.error(f"DB end error: {e}")

        return top


# Singleton
finder = OpportunityFinder()
