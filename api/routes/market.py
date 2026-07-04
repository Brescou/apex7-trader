"""APEX-7 — Market data REST routes (macro, watchlist, sectors, correlation).

Handlers are plain ``def`` (not ``async def``) on purpose: they call
yfinance/FRED/CNN under the hood, which are blocking network calls. FastAPI
runs sync route handlers in a threadpool automatically, so this keeps the
event loop (and the WebSocket broadcaster) responsive instead of freezing
the whole API for the duration of each fetch.
"""

from fastapi import APIRouter

router = APIRouter()

_MACRO_KEY_MAP = {"VIX": "vix", "SPY": "spy", "DXY": "dxy"}


@router.get("/macro")
def get_macro():
    try:
        from market_data.macro import fetch_macro

        raw = fetch_macro()
        macro: dict = {}
        for key, item in raw.items():
            if key == "updated_at" or not isinstance(item, dict):
                continue
            out_key = _MACRO_KEY_MAP.get(key, key.lower())
            price = item.get("price")
            change_pct = item.get("change_pct", 0.0) or 0.0
            macro[out_key] = {
                "value": f"{price:.2f}" if price is not None else "—",
                "change": change_pct,
                "sub": f"{change_pct:+.2f}%" if price is not None else "",
            }
        return {"macro": macro}
    except Exception as e:
        return {"macro": {}, "error": str(e)}


@router.get("/watchlist")
def get_watchlist_prices():
    try:
        from agents.shared.watchlist import get_watchlist
        from market_data.quotes import fetch_watchlist_prices

        symbols = get_watchlist()
        raw = fetch_watchlist_prices(symbols)
        watchlist = {
            sym: {
                "symbol": sym,
                "price": q.get("price"),
                "change": q.get("change_abs", 0.0),
                "changePct": q.get("change_pct", 0.0),
                "rsi": q.get("rsi_14"),
                "macdHist": q.get("macd_hist"),
                "volume": q.get("volume"),
            }
            for sym, q in raw.items()
        }
        return {"watchlist": watchlist, "symbols": symbols}
    except Exception as e:
        return {"watchlist": {}, "symbols": [], "error": str(e)}


@router.get("/sectors")
def get_sectors(period: str = "1d"):
    try:
        from market_data.sectors import fetch_sector_performance

        raw = fetch_sector_performance()
        sectors = [
            {
                "name": name,
                "change": periods.get(period) or 0.0,
                "changePct": periods.get(period) or 0.0,
            }
            for name, periods in raw.items()
        ]
        return {"sectors": sectors}
    except Exception as e:
        return {"sectors": [], "error": str(e)}


@router.get("/correlation")
def get_correlation():
    try:
        from agents.shared.watchlist import get_watchlist
        from market_data.correlation import fetch_correlation_matrix

        symbols = get_watchlist()[:8]
        data = fetch_correlation_matrix(symbols)
        return {"correlation": data, "symbols": symbols}
    except Exception as e:
        return {"correlation": {}, "symbols": [], "error": str(e)}


@router.get("/sparkline/{symbol}")
def get_sparkline(symbol: str):
    try:
        from market_data.charts import fetch_sparkline

        rows = fetch_sparkline(symbol.upper())
        points = [{"t": r["time"], "v": r["price"]} for r in rows]
        return {"sparkline": points}
    except Exception as e:
        return {"sparkline": [], "error": str(e)}


@router.get("/news/{symbol}")
def get_news(symbol: str):
    try:
        from market_data.news import fetch_news

        items = fetch_news(symbol)
        return {"news": items}
    except Exception as e:
        return {"news": [], "error": str(e)}


@router.get("/fundamentals/{symbol}")
def get_fundamentals(symbol: str):
    try:
        from market_data.fundamentals import fetch_fundamentals

        data = fetch_fundamentals(symbol)
        return {"fundamentals": data}
    except Exception as e:
        return {"fundamentals": {}, "error": str(e)}


@router.get("/fear-greed")
def get_fear_greed():
    try:
        from core.external_data import fetch_fear_greed

        data = fetch_fear_greed()
        return {"fearGreed": data}
    except Exception as e:
        return {"fearGreed": None, "error": str(e)}
