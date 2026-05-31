"""
Universe Manager - Fetches and caches full stock listings for KRX and US markets.
"""
from datetime import datetime, timedelta
from pathlib import Path
import json
import requests


CACHE_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR.mkdir(exist_ok=True)


# Fallback list of major Korean stocks (top by market cap/trading volume)
FALLBACK_KR_STOCKS = [
    {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
    {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI"},
    {"ticker": "005380", "name": "현대차", "market": "KOSPI"},
    {"ticker": "207940", "name": "삼성바이오로직스", "market": "KOSPI"},
    {"ticker": "005490", "name": "POSCO홀딩스", "market": "KOSPI"},
    {"ticker": "068270", "name": "셀트리온", "market": "KOSPI"},
    {"ticker": "105560", "name": "KB금융", "market": "KOSPI"},
    {"ticker": "055550", "name": "신한지주", "market": "KOSPI"},
    {"ticker": "035420", "name": "NAVER", "market": "KOSPI"},
    {"ticker": "000270", "name": "기아", "market": "KOSPI"},
    {"ticker": "051910", "name": "LG화학", "market": "KOSPI"},
    {"ticker": "006400", "name": "삼성SDI", "market": "KOSPI"},
    {"ticker": "028260", "name": "삼성물산", "market": "KOSPI"},
    {"ticker": "012330", "name": "현대모비스", "market": "KOSPI"},
    {"ticker": "035720", "name": "카카오", "market": "KOSPI"},
    {"ticker": "066570", "name": "LG전자", "market": "KOSPI"},
    {"ticker": "003670", "name": "포스코퓨처엠", "market": "KOSPI"},
    {"ticker": "323410", "name": "카카오뱅크", "market": "KOSPI"},
    {"ticker": "247540", "name": "에코프로비엠", "market": "KOSPI"},
    {"ticker": "086520", "name": "에코프로", "market": "KOSPI"},
    {"ticker": "003550", "name": "LG", "market": "KOSPI"},
    {"ticker": "018260", "name": "삼성에스디에스", "market": "KOSPI"},
    {"ticker": "034730", "name": "SK", "market": "KOSPI"},
    {"ticker": "015760", "name": "한국전력", "market": "KOSPI"},
    {"ticker": "033780", "name": "KT&G", "market": "KOSPI"},
    {"ticker": "086790", "name": "하나금융지주", "market": "KOSPI"},
    {"ticker": "138040", "name": "메리츠금융지주", "market": "KOSPI"},
    {"ticker": "329180", "name": "HD현대중공업", "market": "KOSPI"},
    {"ticker": "009540", "name": "HD한국조선해양", "market": "KOSPI"},
    {"ticker": "010140", "name": "삼성중공업", "market": "KOSPI"},
    {"ticker": "042660", "name": "한화오션", "market": "KOSPI"},
    {"ticker": "259960", "name": "크래프톤", "market": "KOSPI"},
    {"ticker": "352820", "name": "하이브", "market": "KOSPI"},
    {"ticker": "402340", "name": "SK스퀘어", "market": "KOSPI"},
    {"ticker": "034020", "name": "두산에너빌리티", "market": "KOSPI"},
    {"ticker": "021240", "name": "코웨이", "market": "KOSPI"},
    {"ticker": "096770", "name": "SK이노베이션", "market": "KOSPI"},
    {"ticker": "011200", "name": "HMM", "market": "KOSPI"},
    {"ticker": "000810", "name": "삼성화재", "market": "KOSPI"},
    {"ticker": "032830", "name": "삼성생명", "market": "KOSPI"},
    {"ticker": "030200", "name": "KT", "market": "KOSPI"},
    {"ticker": "017670", "name": "SK텔레콤", "market": "KOSPI"},
    {"ticker": "316140", "name": "우리금융지주", "market": "KOSPI"},
    {"ticker": "024110", "name": "기업은행", "market": "KOSPI"},
    {"ticker": "180640", "name": "한진칼", "market": "KOSPI"},
    {"ticker": "004020", "name": "현대제철", "market": "KOSPI"},
    {"ticker": "010950", "name": "S-Oil", "market": "KOSPI"},
    {"ticker": "011070", "name": "LG이노텍", "market": "KOSPI"},
    {"ticker": "326030", "name": "SK바이오팜", "market": "KOSPI"},
    {"ticker": "097950", "name": "CJ제일제당", "market": "KOSPI"},
    {"ticker": "004990", "name": "롯데지주", "market": "KOSPI"},
    # KOSDAQ majors
    {"ticker": "403870", "name": "HPSP", "market": "KOSDAQ"},
    {"ticker": "277810", "name": "레인보우로보틱스", "market": "KOSDAQ"},
    {"ticker": "196170", "name": "알테오젠", "market": "KOSDAQ"},
    {"ticker": "263750", "name": "펄어비스", "market": "KOSDAQ"},
    {"ticker": "170920", "name": "엘앤에프", "market": "KOSDAQ"},
    {"ticker": "293490", "name": "카카오게임즈", "market": "KOSDAQ"},
    {"ticker": "263720", "name": "더블유게임즈", "market": "KOSDAQ"},
    {"ticker": "095340", "name": "ISC", "market": "KOSDAQ"},
    {"ticker": "214150", "name": "클래시스", "market": "KOSDAQ"},
    {"ticker": "318000", "name": "HLB", "market": "KOSDAQ"},
    {"ticker": "144510", "name": "지씨셀", "market": "KOSDAQ"},
    {"ticker": "094170", "name": "동운아나텍", "market": "KOSDAQ"},
    {"ticker": "046970", "name": "우리로", "market": "KOSDAQ"},
    {"ticker": "228760", "name": "에이티세미콘", "market": "KOSDAQ"},
    {"ticker": "089890", "name": "코세스", "market": "KOSDAQ"},
    {"ticker": "106190", "name": "하이텍팜", "market": "KOSDAQ"},
    {"ticker": "237690", "name": "에스티팜", "market": "KOSDAQ"},
    {"ticker": "084110", "name": "휴온스", "market": "KOSDAQ"},
    {"ticker": "041510", "name": "에스엠", "market": "KOSDAQ"},
    {"ticker": "078600", "name": "아이티센", "market": "KOSDAQ"},
]


class UniverseManager:
    """Manages the full list of tradable stocks for both markets."""

    def __init__(self):
        self._krx_cache: list[dict] = []
        self._sp500_cache: list[dict] = []
        self._last_fetch: dict[str, datetime] = {}
        self._cache_ttl = timedelta(hours=6)

    def _is_cache_valid(self, market: str) -> bool:
        """Check if cached data is still fresh."""
        cache_file = CACHE_DIR / f"universe_{market}.json"
        if not cache_file.exists():
            return False
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        return datetime.now() - mtime < self._cache_ttl

    def _load_cache(self, market: str) -> list[dict]:
        cache_file = CACHE_DIR / f"universe_{market}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        return []

    def _save_cache(self, market: str, data: list[dict]):
        cache_file = CACHE_DIR / f"universe_{market}.json"
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def get_krx_list(self, force_refresh: bool = False) -> list[dict]:
        """Get all KRX (KOSPI + KOSDAQ) stock tickers."""
        if not force_refresh and self._is_cache_valid("krx"):
            return self._load_cache("krx")

        stocks = []
        # Method 1: Pre-cached universe file (generated by _fetch_krx.py using Python 3.11 + FinanceDataReader)
        cache_file = CACHE_DIR / "universe_krx.json"
        if cache_file.exists():
            stocks = json.loads(cache_file.read_text(encoding="utf-8"))
            print(f"  KRX {len(stocks)}개 종목 로드 (캐시 파일)")

        # Method 2: KRX API (requests)
        if not stocks:
            try:
                headers = {"User-Agent": "Mozilla/5.0", "Referer": "http://data.krx.co.kr/"}
                data = {
                    "bld": "dbms/MDC/STAT/standard/MDCSTAT01901",
                    "locale": "ko_KR",
                    "mktId": "ALL",
                    "share": "1",
                    "csvxls_isNo": "false",
                    "name": "fileDown",
                    "url": "dbms/MDC/STAT/standard/MDCSTAT01901",
                }
                resp = requests.post(
                    "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                    data=data, headers=headers, timeout=15
                )
                if resp.status_code == 200:
                    result = resp.json()
                    for item in result.get("output", []):
                        stocks.append({
                            "ticker": item.get("short_code", item.get("isu_cd", "")).strip(),
                            "name": item.get("isu_abbr", item.get("isu_nm", "")).strip(),
                            "market": "KOSPI" if item.get("mkt_typ", "") in ("STU", "1") else "KOSDAQ",
                            "sector": "",
                            "industry": "",
                        })
                    print(f"  KRX API: {len(stocks)}개 종목 로드")
            except Exception as e:
                print(f"  KRX API error: {e}")

        # Method 3: FinanceDataReader (Python 3.11+ only)
        if not stocks:
            try:
                import FinanceDataReader as fdr
                df = fdr.StockListing("KRX")
                for _, row in df.iterrows():
                    stocks.append({
                        "ticker": row["Code"],
                        "name": row.get("Name", ""),
                        "market": row.get("Market", ""),
                        "sector": row.get("Sector", ""),
                        "industry": row.get("Industry", ""),
                    })
                print(f"  KRX {len(stocks)}개 종목 로드 완료")
            except ImportError:
                print("  FinanceDataReader not available")
            except Exception as e:
                print(f"  FinanceDataReader error: {e}")

        # Method 4: Fallback list
        if not stocks:
            stocks = FALLBACK_KR_STOCKS
            print(f"  Using fallback list: {len(stocks)} stocks")

        if stocks:
            self._save_cache("krx", stocks)
        return stocks

    def get_sp500_list(self, force_refresh: bool = False) -> list[dict]:
        """Get S&P 500 stock tickers."""
        if not force_refresh and self._is_cache_valid("sp500"):
            return self._load_cache("sp500")

        stocks = []
        # Method 1: Wikipedia HTML table scraping via requests
        try:
            import re
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                headers=headers, timeout=15
            )
            if resp.status_code == 200:
                m = re.search(
                    r'<table[^>]*id="constituents"[^>]*>(.*?)</table>',
                    resp.text, re.DOTALL
                )
                if m:
                    table_html = m.group(0)
                    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
                    for row in rows[1:]:  # skip header
                        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
                        if len(cells) >= 2:
                            ticker = re.sub(r"<[^>]+>", "", cells[0]).strip()
                            name = re.sub(r"<[^>]+>", "", cells[1]).strip()
                            sector = re.sub(r"<[^>]+>", "", cells[2]).strip() if len(cells) > 2 else ""
                            industry = re.sub(r"<[^>]+>", "", cells[3]).strip() if len(cells) > 3 else ""
                            if ticker:
                                stocks.append({
                                    "ticker": ticker, "name": name,
                                    "sector": sector, "industry": industry,
                                })
                    if stocks:
                        print(f"  S&P 500 {len(stocks)}개 종목 로드 완료")
        except Exception as e:
            print(f"  Wikipedia scraping error: {e}")

        # Method 2: Manual minimal set
        if not stocks:
            stocks = [{"ticker": t, "name": t} for t in [
                "AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","BRK-B","JPM","V",
                "JNJ","WMT","MA","PG","UNH","DIS","HD","BAC","VZ","ADBE",
                "CRM","NFLX","KO","PEP","NKE","MRK","ABT","TMO","ACN","DHR",
                "CSCO","CMCSA","PFE","T","ABBV","COST","CVX","WFC","TMUS","LLY",
                "AMD","INTC","QCOM","AVGO","TXN","HON","IBM","MMM","BA","CAT",
            ]]
            print(f"  Using minimal US list: {len(stocks)} stocks")

        if stocks:
            self._save_cache("sp500", stocks)
        return stocks

    def get_all_us(self, top_n: int = 0) -> list[dict]:
        """Get US stocks to scan (S&P 500 + major ones). Limit to top_n if > 0."""
        sp500 = self.get_sp500_list()
        return sp500[:top_n] if top_n > 0 else sp500

    def get_all_kr(self, top_n: int = 0) -> list[dict]:
        """Get Korean stocks to scan. Exclude KONEX (too illiquid). Limit to top_n if > 0."""
        krx = self.get_krx_list()
        krx = [s for s in krx if s.get("market") in ("KOSPI", "KOSDAQ")]
        return krx[:top_n] if top_n > 0 else krx

    def get_ticker_list(self, market: str = "all", top_n: int = 0) -> list[dict]:
        """Get flat list of all tickers to scan."""
        result = []
        if market in ("all", "us"):
            for s in self.get_all_us(top_n=top_n):
                s["market_type"] = "us"
                result.append(s)
        if market in ("all", "korea"):
            for s in self.get_all_kr(top_n=top_n):
                s["market_type"] = "korea"
                result.append(s)
        return result

    def search_by_name(self, keyword: str, market: str = "all") -> list[dict]:
        """Search stocks by name keyword."""
        results = []
        stocks = self.get_ticker_list(market)
        for s in stocks:
            if keyword.lower() in s.get("name", "").lower():
                results.append(s)
        return results[:20]


universe = UniverseManager()
