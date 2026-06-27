"""Filtre type screener sur les cotations watchlist."""

from market_data.quotes import fetch_watchlist_prices


def run_screener(symbols: list[str], filters: dict) -> list[dict]:
    """
    Filter symbols from the watchlist by the given criteria.
    Reuses fetch_watchlist_prices() — no extra network calls for price filters.
    filters keys:
      Price/technical: rsi_min, rsi_max, change_pct_min, change_pct_max, above_ma20, volume_min
      Fundamental: pe_max, beta_max, mktcap_min (triggers fetch_fundamentals per symbol)
      Sort: sort_by ("change_pct" | "rsi" | "volume" | "pe" | "beta"), sort_desc (bool)
    """
    prices = fetch_watchlist_prices(symbols)

    needs_fundamentals = any(k in filters for k in ("pe_max", "beta_max", "mktcap_min"))
    fundamentals: dict = {}
    if needs_fundamentals:
        try:
            from market_data.fundamentals import fetch_fundamentals

            for sym in symbols:
                try:
                    fundamentals[sym] = fetch_fundamentals(sym)
                except Exception:
                    fundamentals[sym] = {}
        except Exception:
            pass

    results = []
    for sym, data in prices.items():
        if data.get("price") is None:
            continue
        rsi = data.get("rsi_14", 50.0)
        if "rsi_min" in filters and rsi < filters["rsi_min"]:
            continue
        if "rsi_max" in filters and rsi > filters["rsi_max"]:
            continue
        if "change_pct_min" in filters and data["change_pct"] < filters["change_pct_min"]:
            continue
        if "change_pct_max" in filters and data["change_pct"] > filters["change_pct_max"]:
            continue
        if "above_ma20" in filters and data["above_ma20"] != filters["above_ma20"]:
            continue
        if "volume_min" in filters and data["volume"] < filters["volume_min"]:
            continue

        fund = fundamentals.get(sym, {})
        pe = fund.get("pe_ratio")
        beta = fund.get("beta")
        mktcap = fund.get("market_cap")

        if "pe_max" in filters and pe is not None:
            try:
                if float(pe) > filters["pe_max"]:
                    continue
            except (TypeError, ValueError):
                pass

        if "beta_max" in filters and beta is not None:
            try:
                if float(beta) > filters["beta_max"]:
                    continue
            except (TypeError, ValueError):
                pass

        if "mktcap_min" in filters and mktcap is not None:
            try:
                if float(mktcap) < filters["mktcap_min"]:
                    continue
            except (TypeError, ValueError):
                pass

        row = {"symbol": sym, **data}
        if fund:
            row["pe_ratio"] = pe
            row["beta"] = beta
            row["market_cap"] = mktcap
        results.append(row)

    sort_by = filters.get("sort_by", "change_pct")
    sort_desc = filters.get("sort_desc", True)

    def _sort_key(item):
        v = item.get(sort_by)
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    results.sort(key=_sort_key, reverse=sort_desc)
    return results
