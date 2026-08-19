"""Fil d’actualités yfinance pour un symbole, complété par Finnhub."""

import time
from datetime import datetime

from config import NEWS_MAX_ITEMS, NEWS_MAX_TOTAL

from market_data.caches import NEWS_CACHE_SEC, _news_cache, _news_lock
from market_data.compat import yf
from market_data.helpers import classify_sentiment, format_age


def fetch_news(symbol: str, max_items: int = NEWS_MAX_ITEMS) -> list[dict]:
    """Fetch recent headlines for a symbol.

    Tries yfinance ``Ticker.news`` first. If that list is short (Yahoo often
    returns ~10 items) or empty, Finnhub ``/company-news`` fills the rest
    when ``FINNHUB_API_KEY`` is set. Duplicates are dropped by URL/title.

    The full pool (up to ``NEWS_MAX_TOTAL``) is cached ``NEWS_CACHE_SEC``
    seconds per symbol; ``max_items`` only slices that list so "show more"
    does not re-hit the network.
    """
    cap = max(0, min(int(max_items), NEWS_MAX_TOTAL))
    return _news_pool(symbol)[:cap]


def _news_pool(symbol: str) -> list[dict]:
    now = time.time()
    with _news_lock:
        cached = _news_cache.get(symbol)
        if cached is not None and (now - cached["ts"]) < NEWS_CACHE_SEC:
            return cached["data"]

    result = _fetch_news_uncached(symbol, NEWS_MAX_TOTAL)

    with _news_lock:
        _news_cache[symbol] = {"data": result, "ts": time.time()}
    return result


def _strip_ts(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in it.items() if k != "_ts"} for it in items]


def _merge_news(primary: list[dict], extra: list[dict], limit: int) -> list[dict]:
    """Keep ``primary`` intact; append unique ``extra`` rows; newest first."""
    seen_urls = {(it.get("url") or "").strip().lower() for it in primary if it.get("url")}
    seen_titles = {(it.get("title") or "").strip().lower() for it in primary if it.get("title")}
    merged = list(primary)
    for it in extra:
        if len(merged) >= limit:
            break
        url = (it.get("url") or "").strip().lower()
        title = (it.get("title") or "").strip().lower()
        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        merged.append(it)
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
    merged.sort(key=lambda row: int(row.get("_ts") or 0), reverse=True)
    return _strip_ts(merged[:limit])


def _fetch_news_uncached(symbol: str, max_items: int) -> list[dict]:
    yf_items = _fetch_yfinance_news(symbol, max_items)
    if len(yf_items) >= max_items:
        return _strip_ts(yf_items[:max_items])

    from market_data.finnhub import fetch_finnhub_news

    fh_items = fetch_finnhub_news(symbol, max_items)
    if not yf_items:
        return _strip_ts(fh_items)
    return _merge_news(yf_items, fh_items, max_items)


def _fetch_yfinance_news(symbol: str, max_items: int) -> list[dict]:
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
        items = []
        for item in raw_news[:max_items]:
            content = item.get("content", {})
            title = item.get("title", "")
            if not title and isinstance(content, dict):
                title = content.get("title", "")
            title = (title or "").strip()
            if not title:
                continue
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
                    "_ts": int(ts or 0),
                }
            )
        return items
    except Exception:
        return []
