"""
Opportunity Finder - Two-pass scanner:
  Pass 1: Quick-scan ALL stocks (3000+) → filter anomalies
  Pass 2: Full chart+news analysis on candidates → only winners
"""
import time
from datetime import datetime
import database as db
from typing import Optional
import pandas as pd
import numpy as np

from scanner.universe import universe
from agent.stock_agent import agent
from data.collector import get_us_stock_data, get_korea_stock_data
from analysis.technical import add_technical_indicators, generate_technical_signal


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
        """Pass 1: Quick scan all Korean stocks for basic anomalies."""
        kr_stocks = universe.get_all_kr(top_n=top_n)
        candidates = []

        # Filter tickers with dots (yfinance can't handle them)
        kr_stocks = [s for s in kr_stocks if "." not in s["ticker"]]
        total = len(kr_stocks)
        print(f"  [Pass 1] 한국 {total}개 종목 퀵스캔...")

        if not kr_stocks:
            return candidates

        # Convert to yfinance tickers (append .KS / .KQ)
        ticker_map = {}
        for s in kr_stocks:
            raw = s["ticker"]
            suffix = ".KQ" if s.get("market") == "KOSDAQ" else ".KS"
            ticker_map[raw + suffix] = raw

        yf_tickers = list(ticker_map.keys())
        import requests, yfinance as yf
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        yf._session = session

        # Chunked batch download (yfinance fails with >100 tickers in one call)
        chunk_size = 50
        for i in range(0, len(yf_tickers), chunk_size):
            chunk = yf_tickers[i:i + chunk_size]
            try:
                df = yf.download(
                    chunk, period="5d", interval="1d",
                    group_by="ticker", progress=False, auto_adjust=True,
                    timeout=30
                )
                if df.empty or df.isna().all().all():
                    continue
            except Exception:
                continue

            for yf_t in chunk:
                try:
                    raw_t = ticker_map[yf_t]
                    s = next((x for x in kr_stocks if x["ticker"] == raw_t), {})
                    if isinstance(df.columns, pd.MultiIndex):
                        if yf_t not in df.columns.levels[0]:
                            continue
                        close = df.xs(yf_t, level=0, axis=1)["Close"].dropna()
                        vol = df.xs(yf_t, level=0, axis=1)["Volume"].dropna()
                    else:
                        close = df["Close"].dropna()
                        vol = df["Volume"].dropna()

                    if len(close) < 3:
                        continue

                    latest_price = close.iloc[-1]
                    prev_price = close.iloc[-2]
                    change = ((latest_price - prev_price) / prev_price) * 100

                    vol_latest = vol.iloc[-1] if not vol.empty else 0
                    vol_avg = vol.tail(5).mean() if len(vol) >= 5 else vol_latest
                    vol_ratio = vol_latest / vol_avg if vol_avg > 0 else 1

                    # Quick RSI
                    delta_close = close.diff()
                    gain = delta_close.where(delta_close > 0, 0).rolling(14).mean()
                    loss = (-delta_close).where(delta_close < 0, 0).rolling(14).mean()
                    rs = gain / (loss + 1e-10)
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi_val = rsi_series.iloc[-1] if not rsi_series.empty else 50

                    if abs(change) >= 4 or vol_ratio >= 2.0 or rsi_val <= 32 or rsi_val >= 68:
                        candidates.append({
                            "ticker": raw_t,
                            "name": s.get("name", raw_t),
                            "market": "korea",
                            "change": round(change, 1),
                            "volume_ratio": round(vol_ratio, 1),
                            "rsi": round(rsi_val, 1),
                            "latest_price": round(latest_price, 0),
                        })
                except Exception:
                    continue

        print(f"  [Pass 1] 한국 {len(candidates)}개 후보 발견")
        return candidates

    def _quick_scan_us(self, top_n: int = 0) -> list[dict]:
        """Pass 1: Quick scan all US stocks."""
        us_stocks = universe.get_all_us(top_n=top_n)
        us_stocks = [s for s in us_stocks if "." not in s["ticker"]]
        candidates = []
        total = len(us_stocks)
        print(f"  [Pass 1] 미국 {total}개 종목 퀵스캔...")

        import yfinance as yf
        import requests
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        yf._session = session

        tickers_list = [s["ticker"] for s in us_stocks]

        # Chunked batch download
        chunk_size = 50
        for i in range(0, len(tickers_list), chunk_size):
            chunk = tickers_list[i:i + chunk_size]
            try:
                df = yf.download(
                    chunk, period="5d", interval="1d",
                    group_by="ticker", progress=False, auto_adjust=True,
                    timeout=30
                )
                if df.empty:
                    continue
            except Exception:
                continue

            for ticker in chunk:
                s = next((x for x in us_stocks if x["ticker"] == ticker), {})
                try:
                    if isinstance(df.columns, pd.MultiIndex):
                        if ticker not in df.columns.levels[0]:
                            continue
                        close = df.xs(ticker, level=0, axis=1)["Close"].dropna()
                        vol = df.xs(ticker, level=0, axis=1)["Volume"].dropna()
                    else:
                        close = df["Close"].dropna()
                        vol = df["Volume"].dropna()

                    if len(close) < 3:
                        continue

                    latest_price = close.iloc[-1]
                    prev_price = close.iloc[-2]
                    change = ((latest_price - prev_price) / prev_price) * 100

                    vol_latest = vol.iloc[-1] if not vol.empty else 0
                    vol_avg = vol.tail(5).mean() if len(vol) >= 5 else vol_latest
                    vol_ratio = vol_latest / vol_avg if vol_avg > 0 else 1

                    delta_close = close.diff()
                    gain = delta_close.where(delta_close > 0, 0).rolling(14).mean()
                    loss = (-delta_close).where(delta_close < 0, 0).rolling(14).mean()
                    rs = gain / (loss + 1e-10)
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi_val = rsi_series.iloc[-1] if not rsi_series.empty else 50

                    if abs(change) >= 4 or vol_ratio >= 2.0 or rsi_val <= 32 or rsi_val >= 68:
                        candidates.append({
                            "ticker": ticker,
                            "name": s.get("name", ticker),
                            "market": "us",
                            "change": round(change, 1),
                            "volume_ratio": round(vol_ratio, 1),
                            "rsi": round(rsi_val, 1),
                            "latest_price": round(latest_price, 2),
                        })
                except Exception:
                    continue

        print(f"  [Pass 1] 미국 {len(candidates)}개 후보 발견")
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
            print("  Pass 1 결과 없음")
            return []

        # Sort by absolute change (most interesting first)
        all_candidates.sort(key=lambda x: abs(x.get("change", 0)), reverse=True)

        # Limit Pass 2 candidates (max 40 to keep it fast)
        pass2_candidates = all_candidates[:40]
        print(f"  [Pass 2] {len(pass2_candidates)}개 딥 분석 중...")

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
                    print(f"    분석 진행: {i+1}/{len(pass2_candidates)}")

            except Exception:
                continue

        # Sort by combined score descending
        opportunities.sort(key=lambda o: o.score, reverse=True)
        top = opportunities[:max_results]
        elapsed = time.time() - start_time

        print(f"  [OK] {len(opportunities)}개 기회 발견 (소요시간: {elapsed:.0f}초)")
        print(f"  {'-'*40}")

        for opp in top:
            print(f"  {opp.name} ({opp.ticker}) | {opp.action} | 점수 {opp.score:+.0f}")

        # Save to DB if requested
        if save_db and scan_id:
            try:
                db.save_opportunities(scan_id, opportunities)
            except Exception as e:
                print(f"  DB save error: {e}")
            try:
                db.save_scan_end(scan_id, len(all_candidates), len(opportunities))
            except Exception as e:
                print(f"  DB end error: {e}")

        return top


# Singleton
finder = OpportunityFinder()
