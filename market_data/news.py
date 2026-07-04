"""Fil d’actualités yfinance pour un symbole."""

import time
from datetime import datetime

from config import NEWS_MAX_ITEMS

from market_data.caches import NEWS_CACHE_SEC, _news_cache, _news_lock
from market_data.compat import yf
from market_data.helpers import classify_sentiment, format_age


def fetch_news(symbol: str, max_items: int = NEWS_MAX_ITEMS) -> list[dict]:
    """
    Fetch recent headlines for a symbol via yfinance Ticker.news.
    Returns title, source, age, url, sentiment.

    Cached ``NEWS_CACHE_SEC`` seconds per (symbol, max_items) — unlike every
    other market_data fetcher this used to hit yfinance on every call, and
    two Dash callbacks driven by the same "news-interval" fire back-to-back
    for the same symbol each tick (Review Finding).
    """
    cache_key = f"{symbol}|{max_items}"
    now = time.time()
    with _news_lock:
        cached = _news_cache.get(cache_key)
        if cached is not None and (now - cached["ts"]) < NEWS_CACHE_SEC:
            return cached["data"]

    result = _fetch_news_uncached(symbol, max_items)

    with _news_lock:
        _news_cache[cache_key] = {"data": result, "ts": time.time()}
    return result


def _fetch_news_uncached(symbol: str, max_items: int) -> list[dict]:
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
        items = []
        for item in raw_news[:max_items]:
            content = item.get("content", {})
            title = item.get("title", "")
            if not title and isinstance(content, dict):
                title = content.get("title", "")
            if isinstance(content, dict):
                source = content.get("provider", {}).get(
                    "displayName", item.get("publisher", "Unknown")
                )
                url = content.get("canonicalUrl", {}).get("url", item.get("link", ""))
                pub_time = content.get("pubDate", "")
                if pub_time:
                    try:
                        dt = datetime.fromisoformat(pub_time.replace("Z", "+00:00"))
                        ts = int(dt.timestamp())
                    except Exception:
                        ts = item.get("providerPublishTime", 0)
                else:
                    ts = item.get("providerPublishTime", 0)
            else:
                source = item.get("publisher", "Unknown")
                url = item.get("link", "")
                ts = item.get("providerPublishTime", 0)

            items.append(
                {
                    "title": title,
                    "source": source,
                    "age": format_age(ts),
                    "url": url,
                    "sentiment": classify_sentiment(title),
                }
            )
        return items
    except Exception:
        return []
