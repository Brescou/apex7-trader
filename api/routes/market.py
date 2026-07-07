"""APEX-7 — Market data REST routes (macro, watchlist, sectors, correlation).

Handlers are plain ``def`` (not ``async def``) on purpose: they call
yfinance/FRED/CNN under the hood, which are blocking network calls. FastAPI
runs sync route handlers in a threadpool automatically, so this keeps the
event loop (and the WebSocket broadcaster) responsive instead of freezing
the whole API for the duration of each fetch.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/macro")
def get_macro():
    """Normalized macro bar: VIX/SPY/DXY (yfinance) + F&G + FED funds + 10Y (FRED)."""
    out: dict = {}
    try:
        from market_data.macro import fetch_macro

        raw = fetch_macro()
        for label in ("VIX", "SPY", "DXY"):
            blk = raw.get(label) or {}
            price = blk.get("price")
            change_pct = blk.get("change_pct", 0.0) or 0.0
            out[label.lower()] = {
                "value": f"{price:,.2f}" if isinstance(price, (int, float)) else "—",
                "change": change_pct,
                "sub": f"{change_pct:+.2f}%" if isinstance(price, (int, float)) else "",
            }
    except Exception as e:
        out["error"] = str(e)

    try:
        from core.external_data import fetch_fear_greed

        fg = fetch_fear_greed()
        if fg:
            out["fear_greed"] = {"value": str(fg.get("score", "—")), "change": fg.get("label", "")}
    except Exception:
        pass

    try:
        from core.external_data import fetch_fred_latest

        fed = fetch_fred_latest("DFF")  # Effective Fed Funds Rate
        if fed and fed.get("value") is not None:
            out["fed_funds"] = {"value": f"{fed['value']:.2f}%", "change": ""}
        ten = fetch_fred_latest("DGS10")  # 10-Year Treasury
        if ten and ten.get("value") is not None:
            out["ten_year"] = {"value": f"{ten['value']:.2f}%", "change": ""}
    except Exception:
        pass

    return {"macro": out}


@router.get("/watchlist")
def get_watchlist_prices():
    """Watchlist quotes as a frontend-ready array (symbol injected, camelCase)."""
    try:
        from agents.shared.watchlist import get_watchlist
        from market_data.quotes import fetch_watchlist_prices

        symbols = get_watchlist()
        data = fetch_watchlist_prices(symbols)
        items = []
        for sym in symbols:
            q = data.get(sym) or {}
            items.append(
                {
                    "symbol": sym,
                    "price": q.get("price", 0) or 0,
                    "changePct": q.get("change_pct", 0) or 0,
                    "changeAbs": q.get("change_abs", 0) or 0,
                    "volume": q.get("volume", 0) or 0,
                    "rsi": q.get("rsi_14"),
                    "macdHist": q.get("macd_hist"),
                    "bbPos": q.get("bb_pos"),
                    "high52w": q.get("high_52w"),
                    "low52w": q.get("low_52w"),
                    "dayHigh": q.get("day_high"),
                    "dayLow": q.get("day_low"),
                    "aboveMa20": q.get("above_ma20"),
                }
            )
        return {"watchlist": items, "symbols": symbols}
    except Exception as e:
        return {"watchlist": [], "symbols": [], "error": str(e)}


@router.get("/sectors")
def get_sectors(period: str = "1mo"):
    """Sector performance as a frontend-ready array for the heatmap."""
    try:
        from market_data.sectors import fetch_sector_performance

        raw = fetch_sector_performance()
        items = []
        for name, periods in (raw or {}).items():
            if not isinstance(periods, dict):
                continue
            val = periods.get(period)
            if val is None:
                val = periods.get("1mo") or periods.get("5d") or 0
            val = round(float(val or 0), 2)
            items.append({"name": name, "change": val, "changePct": val})
        return {"sectors": items, "period": period}
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

        raw = fetch_news(symbol.upper())
        items = [
            {
                "title": n.get("title", ""),
                "publisher": n.get("source", "Unknown"),
                "link": n.get("url", ""),
                "time": n.get("age", ""),
                "sentiment": n.get("sentiment", ""),
            }
            for n in (raw or [])
        ]
        return {"news": items}
    except Exception as e:
        return {"news": [], "error": str(e)}


@router.get("/fundamentals/{symbol}")
def get_fundamentals(symbol: str):
    """Normalized fundamentals (camelCase) for the symbol detail panel."""
    try:
        from market_data.fundamentals import fetch_fundamentals

        d = fetch_fundamentals(symbol.upper()) or {}
        out = {
            "name": d.get("name"),
            "sector": d.get("sector"),
            "industry": d.get("industry"),
            "marketCap": d.get("market_cap"),
            "peRatio": d.get("pe_ratio"),
            "forwardPe": d.get("forward_pe"),
            "eps": d.get("eps"),
            "dividendYield": d.get("dividend_yield"),
            "beta": d.get("beta"),
            "high52w": d.get("fifty_two_week_high"),
            "low52w": d.get("fifty_two_week_low"),
        }
        return {"fundamentals": out}
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


@router.get("/chart/{symbol}")
def get_chart(symbol: str, period: str = "1mo"):
    """OHLCV daily bars for the given symbol and period (1d, 5d, 1mo, 3mo, 6mo, 1y)."""
    valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y"}
    if period not in valid_periods:
        period = "1mo"
    try:
        from market_data.charts import fetch_ohlcv

        bars = fetch_ohlcv(symbol.upper(), period=period)
        return {"symbol": symbol.upper(), "period": period, "bars": bars}
    except Exception as e:
        return {"symbol": symbol.upper(), "period": period, "bars": [], "error": str(e)}


@router.get("/calendar")
def get_calendar():
    """Economic calendar + earnings for the current watchlist (next 60 days)."""
    try:
        from agents.shared.watchlist import get_watchlist
        from market_data.economic_calendar import build_economic_calendar_rows

        symbols = get_watchlist()
        rows = build_economic_calendar_rows(symbols, horizon_days=60)
        out = []
        for r in rows:
            out.append(
                {
                    "kind": r.get("kind", "macro"),
                    "eventDate": str(r.get("event_date", "")),
                    "daysUntil": int(r.get("days_until", 0)),
                    "event": str(r.get("event", "")),
                    "symbol": str(r.get("symbol", "")),
                    "importance": str(r.get("importance", "medium")),
                }
            )
        return {"calendar": out}
    except Exception as e:
        return {"calendar": [], "error": str(e)}
