import feedparser


def get_us_news(ticker: str, max_results: int = 10) -> list[dict]:
    """Fetch US stock news via Yahoo Finance RSS."""
    news_items = []

    try:
        feed = feedparser.parse(f"https://finance.yahoo.com/rss/headline?s={ticker}")
        for entry in feed.entries[:max_results]:
            news_items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": "Yahoo Finance",
                "ticker": ticker,
            })
    except Exception:
        pass

    try:
        search_url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(search_url)
        for entry in feed.entries[:max_results]:
            news_items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": "Google News",
                "ticker": ticker,
            })
    except Exception:
        pass

    return news_items[:max_results]


def get_korea_news(ticker: str, max_results: int = 10) -> list[dict]:
    """Fetch Korean stock news from Google News RSS (Korean edition)."""
    news_items = []
    try:
        feed = feedparser.parse(
            f"https://news.google.com/rss/search?q={ticker}+주식&hl=ko&gl=KR&ceid=KR:ko"
        )
        for entry in feed.entries[:max_results]:
            news_items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": "Google News",
                "ticker": ticker,
            })
    except Exception:
        pass

    return news_items


def get_news_for_tickers(tickers: list[str], market: str = "all") -> dict[str, list[dict]]:
    """Fetch news for multiple tickers."""
    result = {}
    for ticker in tickers:
        if market in ("all", "us"):
            us_news = get_us_news(ticker)
            if us_news:
                result[ticker] = us_news
        if market in ("all", "korea"):
            kr_news = get_korea_news(ticker)
            if kr_news:
                if ticker in result:
                    result[ticker].extend(kr_news)
                else:
                    result[ticker] = kr_news
    return result
