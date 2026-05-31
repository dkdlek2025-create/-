"""
Fuzzy company name → ticker search.
Handles typos, spacing, partial matches for both Korean and English.
"""
import difflib
import re
from scanner.universe import universe


class CompanySearcher:
    """Search stocks by company name with fuzzy matching."""

    def __init__(self):
        self._all_stocks = None

    @property
    def all_stocks(self) -> list[dict]:
        if self._all_stocks is None:
            self._all_stocks = universe.get_ticker_list("all")
        return self._all_stocks

    def _normalize(self, text: str) -> str:
        """Normalize: lowercase, remove spaces."""
        text = text.lower().strip()
        text = re.sub(r'\s+', '', text)  # remove all spaces
        return text

    def _score_match(self, query: str, name: str, ticker: str) -> float:
        """
        Score how well a query matches a stock.
        Returns 0~100 score.
        """
        q = self._normalize(query)
        n = self._normalize(name)
        t = self._normalize(ticker)

        # Exact match (highest)
        if q == n or q == t:
            return 100

        # Korean: check character-by-character overlap
        # (handles typos like 삼성전자 → 샘성전자)
        if all('\uac00' <= c <= '\ud7a3' for c in q):
            # Korean query - count matching chars
            matches = sum(1 for c in q if c in n)
            ratio = matches / max(len(q), len(n)) * 100 if n else 0
            return ratio

        # English: use difflib
        ratio = difflib.SequenceMatcher(None, q, n).ratio()
        ratio_ticker = difflib.SequenceMatcher(None, q, t).ratio()
        return max(ratio, ratio_ticker) * 100

    def search(self, query: str, top_n: int = 5) -> list[dict]:
        """Search stocks by company name. Returns list of {ticker, name, market, score}."""
        query = query.strip()
        if not query:
            return []

        # 1. Direct ticker match first
        q_upper = query.upper()
        for s in self.all_stocks:
            if s["ticker"] == q_upper:
                return [{
                    "ticker": s["ticker"],
                    "name": s.get("name", s["ticker"]),
                    "market": s.get("market_type", "us" if s["ticker"].isalpha() else "korea"),
                    "score": 100,
                    "match_type": "ticker_exact",
                }]

        # 2. Fuzzy score all stocks
        scored = []
        for s in self.all_stocks:
            name = s.get("name", "")
            score = self._score_match(query, name, s["ticker"])
            if score >= 30:  # threshold
                scored.append({
                    "ticker": s["ticker"],
                    "name": name,
                    "market": s.get("market_type", "us" if s["ticker"].isalpha() else "korea"),
                    "score": round(score, 1),
                    "match_type": "fuzzy",
                })

        # Score break: if clear winner, return it
        if scored:
            scored.sort(key=lambda x: x["score"], reverse=True)
            best = scored[0]
            # If top score is significantly higher than rest, auto-select
            if len(scored) == 1 or best["score"] >= scored[1]["score"] + 20:
                return [best]
            # Otherwise return top N for user to choose
            return scored[:top_n]

        # 3. Fallback: substring search
        q_lower = query.lower()
        q_norm = self._normalize(query)
        results = []
        for s in self.all_stocks:
            name = s.get("name", "")
            if q_lower in name.lower() or q_norm in self._normalize(name):
                results.append({
                    "ticker": s["ticker"],
                    "name": name,
                    "market": s.get("market_type", "us" if s["ticker"].isalpha() else "korea"),
                    "score": 50,
                    "match_type": "substring",
                })
        return results[:top_n]

    def search_one(self, query: str) -> dict:
        """Search and auto-select the best match. Returns single result or error dict."""
        results = self.search(query, top_n=3)
        if not results:
            return {"error": f"'{query}'와(과) 일치하는 종목을 찾을 수 없습니다."}
        if len(results) == 1:
            return results[0]
        # Multiple results: return the best match
        return results[0]

    def format_choices(self, results: list[dict]) -> str:
        """Format multiple matches for user to choose."""
        lines = [f"'{results[0].get('_query', '')}' 검색 결과:"]
        for i, r in enumerate(results, 1):
            flag = "🇺🇸" if r["market"] == "us" else "🇰🇷"
            lines.append(f"{i}. {flag} {r['name']} ({r['ticker']})")
        lines.append("\n번호나 티커를 입력하세요.")
        return "\n".join(lines)


searcher = CompanySearcher()
