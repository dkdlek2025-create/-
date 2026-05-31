"""
News Analyzer - Collects news, classifies as good/bad, and generates summary.
No LLM required - keyword-based classification with scoring.
"""
import re
from datetime import datetime, timedelta
from typing import Optional
import requests as _requests
from data.news import get_us_news, get_korea_news


# 호재 (긍정) 키워드 - 각 키워드에 가중치
BULLISH_KEYWORDS = {
    # 실적/재무
    "어닝서프라이즈": 3, "실적호조": 3, "실적개선": 2, "매출증가": 2, "영업이익": 2,
    "순이익": 2, "흑자": 3, "배당확대": 2, "자사주매입": 2, "목표가상향": 2,
    # 사업/계약
    "대규모수주": 3, "신제품": 2, "기술개발": 1, "특허": 1, "글로벌진출": 2,
    "협력": 1, "파트너십": 2, "계약": 1, "승인": 2, "인증": 1,
    # 시장
    "신고가": 2, "반등": 2, "상승전환": 2, "회복": 2, "강세": 1,
    "낙관": 2, "긍정": 1, "기대": 1, "성장": 1, "호재": 3,
    "개선": 1, "확대": 1, "증가": 1,
    # 영어
    "beat": 2, "surge": 2, "upgrade": 2, "outperform": 2, "positive": 1,
    "growth": 1, "profit": 2, "record": 2, "bullish": 2, "buyback": 2,
    "dividend": 2, "partnership": 2, "approval": 2, "launch": 1,
    "expansion": 1, "strong": 1, "gain": 1, "rally": 2,
}

# 악재 (부정) 키워드
BEARISH_KEYWORDS = {
    # 실적/재무
    "어닝쇼크": 3, "실적부진": 3, "실적악화": 2, "매출감소": 2, "영업적자": 3,
    "순손실": 3, "적자전환": 3, "배당삭감": 2, "목표가하향": 2,
    # 사업/위기
    "소송": 2, "조사": 2, "벌금": 2, "리콜": 3, "규제": 2,
    "과징금": 2, "횡령": 3, "분식": 3, "감사의견": 2, "상폐": 3,
    "파업": 2, "인력감축": 1, "구조조정": 1,
    # 시장
    "신저가": 2, "추락": 2, "폭락": 3, "급락": 2, "하락전환": 2,
    "침체": 2, "위기": 2, "불안": 1, "우려": 2, "악재": 3,
    "리스크": 2, "부정적": 1, "악화": 2, "감소": 1, "하향": 1,
    # 영어
    "miss": 2, "decline": 2, "downgrade": 2, "underperform": 2, "negative": 1,
    "loss": 2, "crash": 3, "plunge": 2, "risk": 1, "lawsuit": 2,
    "investigation": 2, "recall": 3, "fine": 2, "regulatory": 2,
    "weak": 1, "fall": 1, "cut": 2, "worst": 2, "concern": 1,
}


def _translate_to_korean(text: str) -> str:
    """Translate English text to Korean using Google Translate (free)."""
    if not text:
        return text
    # Detect if translation is needed: more English chars than Korean
    en = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    kr = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    if kr > en or en < 5:
        return text  # Already Korean or too short
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": "ko", "dt": "t", "q": text[:1000]}
        r = _requests.get(url, params=params, timeout=10,
                          headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        result = r.json()
        if result and result[0] and result[0][0]:
            return result[0][0][0] or text
    except Exception:
        pass
    return text


class NewsAnalyzer:
    """Collects news, classifies 호재/악재, generates summary."""

    def __init__(self):
        pass

    def _classify_headline(self, title: str) -> dict:
        """Classify a single news headline."""
        if not title:
            return {"class": "neutral", "score": 0, "key_reason": ""}

        title_lower = title.lower()
        score = 0
        reasons = []

        for keyword, weight in BULLISH_KEYWORDS.items():
            if keyword in title_lower:
                score += weight
                reasons.append(f"{keyword}(+{weight})")

        for keyword, weight in BEARISH_KEYWORDS.items():
            if keyword in title_lower:
                score -= weight
                reasons.append(f"{keyword}({weight})")

        if score >= 2:
            classification = "호재"
        elif score <= -2:
            classification = "악재"
        else:
            classification = "중립"

        return {
            "class": classification,
            "score": score,
            "key_reason": ", ".join(reasons[:3]) if reasons else "",
        }

    def analyze_ticker_news(self, ticker: str, market: str = "auto",
                            max_results: int = 8) -> dict:
        """Fetch and analyze news for a ticker."""
        if market == "auto":
            market = "us" if ticker.isalpha() else "korea"

        if market == "us":
            items = get_us_news(ticker, max_results)
        else:
            items = get_korea_news(ticker, max_results)

        if not items:
            return {
                "ticker": ticker,
                "news_count": 0,
                "headlines": [],
                "summary": "관련 뉴스 없음",
                "overall": "중립",
                "overall_score": 0,
                "bullish_count": 0,
                "bearish_count": 0,
            }

        # Classify each headline
        classified = []
        total_score = 0
        for item in items:
            result = self._classify_headline(item["title"])
            item["class"] = result["class"]
            item["class_score"] = result["score"]
            item["key_reason"] = result["key_reason"]
            classified.append(item)
            total_score += result["score"]

        bullish_count = sum(1 for c in classified if c["class"] == "호재")
        bearish_count = sum(1 for c in classified if c["class"] == "악재")

        # Overall assessment
        avg_score = total_score / len(classified) if classified else 0

        if avg_score >= 1.5:
            overall = "호재"
            summary = self._generate_summary(classified, bullish_count, bearish_count, "positive")
        elif avg_score <= -1.5:
            overall = "악재"
            summary = self._generate_summary(classified, bullish_count, bearish_count, "negative")
        else:
            overall = "중립"
            summary = self._generate_summary(classified, bullish_count, bearish_count, "neutral")

        # 호재/악재 각각 요약 텍스트
        bullish_items = sorted(
            [h for h in classified if h["class"] == "호재"],
            key=lambda x: x["class_score"], reverse=True
        )
        bearish_items = sorted(
            [h for h in classified if h["class"] == "악재"],
            key=lambda x: x["class_score"], reverse=True
        )

        bullish_summary = " / ".join([h["title"] for h in bullish_items[:2]]) if bullish_items else "없음"
        bearish_summary = " / ".join([h["title"] for h in bearish_items[:2]]) if bearish_items else "없음"

        # Convert to percentage: 0~100% (50% = neutral)
        score_pct = max(0, min(100, int(((avg_score + 3) / 6) * 100)))

        # Translate English titles to Korean (US stocks)
        if market == "us":
            for h in classified:
                h["original_title"] = h["title"]
                h["title"] = _translate_to_korean(h["title"])
            if bullish_summary and bullish_summary != "없음":
                bullish_summary = _translate_to_korean(bullish_summary[:200])
            if bearish_summary and bearish_summary != "없음":
                bearish_summary = _translate_to_korean(bearish_summary[:200])

        return {
            "ticker": ticker,
            "news_count": len(classified),
            "headlines": classified[:5],
            "summary": summary,
            "overall": overall,
            "overall_score": round(avg_score, 1),
            "overall_score_pct": score_pct,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "bullish_summary": bullish_summary,
            "bearish_summary": bearish_summary,
        }

    def _generate_summary(self, headlines: list, bullish: int, bearish: int,
                          direction: str) -> str:
        """Generate a concise Korean news summary."""
        total = len(headlines)
        if total == 0:
            return "관련 뉴스 없음"

        if direction == "positive":
            # Pick the most bullish headlines
            good = [h for h in headlines if h["class"] == "호재"]
            top = sorted(good, key=lambda x: x["class_score"], reverse=True)[:2]
            points = [h["title"] for h in top]
            return (
                f"📰 뉴스 요약: {bullish}/{total}건 호재\n"
                f"→ {', '.join(points[:2])}"
            )

        elif direction == "negative":
            bad = [h for h in headlines if h["class"] == "악재"]
            top = sorted(bad, key=lambda x: x["class_score"], reverse=True)[:2]
            points = [h["title"] for h in top]
            return (
                f"📰 뉴스 요약: {bearish}/{total}건 악재\n"
                f"→ {', '.join(points[:2])}"
            )

        else:
            # Mixed or neutral - show top positive and top negative
            good = [h for h in headlines if h["class"] == "호재"]
            bad = [h for h in headlines if h["class"] == "악재"]
            lines = []
            if good:
                lines.append(f"호재: {good[0]['title']}")
            if bad:
                lines.append(f"악재: {bad[0]['title']}")
            return (
                f"📰 뉴스 요약: 호재 {bullish} / 악재 {bearish} / 중립 {total-bullish-bearish}\n"
                f"→ {' / '.join(lines[:2])}" if lines else "→ 특별한 재료 없음"
            )


news_analyzer = NewsAnalyzer()
