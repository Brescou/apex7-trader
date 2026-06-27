"""APEX-7 — Terminal tab — watchlist grid, screener, alerts, compare, CSV export."""

import json
import logging
import time

import dash
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from agents.shared.watchlist import add_to_watchlist, get_watchlist, remove_from_watchlist
from dashboard.controller import _state
from market_data import (
    fetch_sparkline,
    fetch_watchlist_prices,
    run_screener,
)
from dashboard.layout import _fmt_volume, _make_sparkline_fig, _watchlist_row
from dashboard.server import (
    BG_CARD,
    BG_HOVER,
    BLUE,
    BORDER,
    FONT,
    GREEN,
    ORANGE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    YELLOW,
    app,
)
from dashboard.callbacks.terminal._shared import (
    BG_PANEL,
    _DOT_PALETTE,
)

logger = logging.getLogger("apex7.terminal.watchlist")


@app.callback(
    Output("terminal-watchlist", "data"),
    Input("btn-watchlist-add", "n_clicks"),
    State("watchlist-add-input", "value"),
    prevent_initial_call=True,
)
def _add_symbol(_, symbol):
    if not symbol:
        return no_update
    sym = symbol.strip().upper()
    if not sym:
        return no_update
    if add_to_watchlist(sym, source="manual"):
        return get_watchlist()
    return no_update


@app.callback(
    Output("terminal-watchlist", "data", allow_duplicate=True),
    Input({"type": "watchlist-remove", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _remove_symbol(n_clicks_list):
    if not any(n_clicks_list):
        return no_update
    sym = ctx.triggered_id["index"]
    open_syms = frozenset()
    port = _state.get("portfolio")
    if port is not None:
        with port._lock:
            open_syms = frozenset(port.positions.keys())
    if remove_from_watchlist(sym, open_symbols=open_syms):
        return get_watchlist()
    return no_update


@app.callback(
    Output("compare-symbols", "options"),
    Output("compare-symbols", "value"),
    Input("terminal-watchlist", "data"),
    Input("watchlist-interval", "n_intervals"),
    State("compare-symbols", "value"),
    prevent_initial_call=False,
)
def _sync_compare_checklist(_watchlist, _n_interval, cur_vals):
    """Options follow SQLite watchlist (``get_watchlist``), not layout-time snapshot."""
    syms = get_watchlist()
    opts = [{"label": s, "value": s} for s in syms]
    allowed = set(syms)
    val = [v for v in (cur_vals or []) if v in allowed]
    return opts, val


def _watchlist_render_signature(
    wl: list,
    prices: dict,
    active_sym,
    is_screener_active: bool,
    screener_matched: set,
) -> str:
    """Stable signature of everything the watchlist grid renders.

    Used to skip the expensive 20-card rebuild when nothing visible has
    changed between ``watchlist-interval`` ticks (Sprint 3 perf). Prices are
    rounded to the same precision they are displayed at so sub-cent jitter
    that never reaches the screen does not force a rebuild.
    """
    rows = []
    for sym in wl:
        d = prices.get(sym, {})
        rows.append(
            (
                sym,
                round(float(d.get("price", 0) or 0), 2),
                round(float(d.get("change_pct", 0) or 0), 2),
                round(float(d.get("change_abs", 0) or 0), 2),
                d.get("rsi_14"),
                d.get("above_ma20"),
                d.get("volume", 0),
                d.get("macd_hist", 0.0),
                d.get("bb_pos", "mid"),
                d.get("high_52w"),
                d.get("low_52w"),
                d.get("day_high"),
                d.get("day_low"),
            )
        )
    return json.dumps(
        [list(wl), active_sym, is_screener_active, sorted(screener_matched), rows],
        default=str,
        sort_keys=True,
    )


@app.callback(
    Output("watchlist-chips", "children"),
    Output("watchlist-table", "children"),
    Output("watchlist-render-sig", "data"),
    Input("terminal-watchlist", "data"),
    Input("watchlist-interval", "n_intervals"),
    Input("terminal-active-symbol", "data"),
    Input("screener-active-store", "data"),
    Input("screener-results-store", "data"),
    State("watchlist-render-sig", "data"),
)
def _update_watchlist(watchlist, _, active_sym, screener_active, screener_results, prev_sig):
    wl = watchlist or []
    screener_matched = set(screener_results or [])
    is_screener_active = bool(screener_active)

    if not wl:
        empty_card = html.Div(
            "No symbols. Add one above.",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "fontStyle": "italic",
                "padding": "10px",
            },
        )
        return [], empty_card, None

    try:
        prices = fetch_watchlist_prices(wl)
    except Exception as exc:
        logger.warning("watchlist grid: fetch_watchlist_prices failed: %s", exc)
        prices = {}

    # Skip the rebuild when no displayed field has moved since last tick.
    sig = _watchlist_render_signature(wl, prices, active_sym, is_screener_active, screener_matched)
    if prev_sig is not None and sig == prev_sig:
        return no_update, no_update, no_update

    # Build 2-column symbol card grid
    cards = []
    for i, sym in enumerate(wl):
        d = prices.get(sym, {})
        chg_pct = d.get("change_pct", 0.0) or 0.0
        chg_abs = d.get("change_abs", 0.0) or 0.0
        price = d.get("price", 0.0) or 0.0
        rsi = d.get("rsi_14")
        above = d.get("above_ma20", None)
        volume = d.get("volume", 0)
        high_52w = d.get("high_52w")
        low_52w = d.get("low_52w")
        day_high = d.get("day_high")
        day_low = d.get("day_low")
        chg_col = GREEN if chg_pct >= 0 else RED
        dot_col = _DOT_PALETTE[i % len(_DOT_PALETTE)]
        active = sym == active_sym

        try:
            spark = fetch_sparkline(sym)
        except Exception as exc:
            logger.debug("watchlist grid: sparkline failed for %s: %s", sym, exc)
            spark = []

        # RSI badge
        if rsi is not None:
            try:
                rsi_f = float(rsi)
                if rsi_f < 30:
                    rsi_badge = html.Span(
                        f"RSI {rsi_f:.0f} oversold",
                        style={
                            "fontSize": "10px",
                            "color": GREEN,
                            "background": "rgba(16,185,129,0.12)",
                            "border": "1px solid rgba(16,185,129,0.3)",
                            "padding": "1px 6px",
                            "borderRadius": "2px",
                        },
                    )
                elif rsi_f > 70:
                    rsi_badge = html.Span(
                        f"RSI {rsi_f:.0f} overbought",
                        style={
                            "fontSize": "10px",
                            "color": RED,
                            "background": "rgba(239,68,68,0.12)",
                            "border": "1px solid rgba(239,68,68,0.3)",
                            "padding": "1px 6px",
                            "borderRadius": "2px",
                        },
                    )
                else:
                    rsi_badge = html.Span(
                        f"RSI {rsi_f:.0f}",
                        style={"fontSize": "10px", "color": TEXT_DIM},
                    )
            except (TypeError, ValueError):
                rsi_badge = html.Span("RSI —", style={"fontSize": "10px", "color": TEXT_DIM})
        else:
            rsi_badge = html.Span("RSI —", style={"fontSize": "10px", "color": TEXT_DIM})

        # MA20 indicator
        if above is True:
            ma20_label = "▲"
            ma20_col = GREEN
        elif above is False:
            ma20_label = "▼"
            ma20_col = RED
        else:
            ma20_label = "—"
            ma20_col = TEXT_DIM

        # MACD histogram badge (sign drives bullish/bearish color)
        macd_hist = d.get("macd_hist", 0.0) or 0.0
        macd_col = GREEN if macd_hist > 0 else (RED if macd_hist < 0 else TEXT_DIM)
        macd_badge = html.Span(
            f"MACD {macd_hist:+.2f}",
            style={"fontSize": "10px", "color": macd_col, "marginLeft": "8px"},
        )

        # Bollinger position badge (upper/lower/mid)
        bb_pos = d.get("bb_pos", "mid")
        bb_col = RED if bb_pos == "upper" else (GREEN if bb_pos == "lower" else TEXT_DIM)
        bb_badge = html.Span(
            f"BB {bb_pos}",
            style={"fontSize": "10px", "color": bb_col, "marginLeft": "8px"},
        )

        # Card border: white if active, YELLOW if screener match, else BORDER
        if active:
            border_color = "#ffffff"
        elif is_screener_active and sym in screener_matched:
            border_color = YELLOW
        else:
            border_color = BORDER

        # Screener no-match: fade out
        card_opacity = (
            "0.3" if (is_screener_active and sym not in screener_matched and not active) else "1"
        )

        card = html.Div(
            [
                # Header row: dot + symbol + remove button
                html.Div(
                    [
                        html.Span(
                            "●",
                            style={
                                "color": dot_col,
                                "marginRight": "6px",
                                "fontSize": "10px",
                            },
                        ),
                        html.Span(
                            sym,
                            style={
                                "fontSize": "13px",
                                "fontWeight": "bold",
                                "color": TEXT_MAIN,
                                "letterSpacing": "0.5px",
                                "flex": "1",
                            },
                        ),
                        html.Button(
                            "×",
                            id={"type": "watchlist-remove", "index": sym},
                            n_clicks=0,
                            style={
                                "background": "transparent",
                                "border": "none",
                                "color": TEXT_DIM,
                                "cursor": "pointer",
                                "fontSize": "14px",
                                "padding": "0",
                                "fontFamily": FONT,
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "marginBottom": "6px",
                    },
                ),
                # Price + change row
                html.Div(
                    [
                        html.Span(
                            f"${price:.2f}",
                            style={
                                "fontSize": "22px",
                                "fontWeight": "bold",
                                "color": TEXT_MAIN,
                                "marginRight": "8px",
                            },
                        ),
                        html.Span(
                            f"{'▲' if chg_pct >= 0 else '▼'} {chg_pct:+.2f}%",
                            style={
                                "fontSize": "12px",
                                "fontWeight": "700",
                                "color": chg_col,
                            },
                        ),
                        html.Span(
                            f" {chg_abs:+.2f}",
                            style={"fontSize": "11px", "color": TEXT_DIM, "marginLeft": "4px"},
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "baseline",
                        "marginTop": "6px",
                        "marginBottom": "6px",
                    },
                ),
                # 52w high/low + day range row
                html.Div(
                    [
                        html.Span(
                            f"52W H: ${high_52w:.2f}" if high_52w is not None else "52W H: —",
                            style={"fontSize": "9px", "color": GREEN},
                        ),
                        html.Span(
                            f"L: ${low_52w:.2f}" if low_52w is not None else "L: —",
                            style={"fontSize": "9px", "color": RED, "marginLeft": "6px"},
                        ),
                        html.Span(
                            "·",
                            style={"fontSize": "9px", "color": TEXT_DIM, "marginLeft": "6px"},
                        ),
                        html.Span(
                            f"Day H: ${day_high:.2f}" if day_high is not None else "Day H: —",
                            style={"fontSize": "9px", "color": TEXT_DIM, "marginLeft": "6px"},
                        ),
                        html.Span(
                            f"L: ${day_low:.2f}" if day_low is not None else "L: —",
                            style={"fontSize": "9px", "color": TEXT_DIM, "marginLeft": "4px"},
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "marginTop": "4px",
                        "marginBottom": "2px",
                    },
                ),
                # RSI + MA20 + MACD + BB + VOL row
                html.Div(
                    [
                        rsi_badge,
                        html.Span(
                            f"MA20 {ma20_label}",
                            style={
                                "fontSize": "10px",
                                "color": ma20_col,
                                "marginLeft": "8px",
                            },
                        ),
                        macd_badge,
                        bb_badge,
                        html.Span(
                            f"VOL {_fmt_volume(volume)}",
                            style={
                                "fontSize": "10px",
                                "color": TEXT_DIM,
                                "marginLeft": "8px",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "flexWrap": "wrap",
                        "gap": "6px",
                        "marginTop": "4px",
                        "marginBottom": "6px",
                    },
                ),
                # Sparkline
                dcc.Graph(
                    figure=_make_sparkline_fig(spark or []),
                    config={"displayModeBar": False},
                    style={"height": "32px", "margin": "0"},
                ),
                # Invisible click overlay button
                html.Button(
                    "",
                    id={"type": "watchlist-row-btn", "index": sym},
                    n_clicks=0,
                    style={
                        "position": "absolute",
                        "inset": "0",
                        "background": "transparent",
                        "border": "none",
                        "cursor": "pointer",
                        "width": "100%",
                        "height": "100%",
                    },
                ),
            ],
            style={
                "position": "relative",
                "background": BG_CARD,
                "border": f"1px solid {border_color}",
                "borderRadius": "4px",
                "padding": "12px",
                "cursor": "pointer",
                "transition": "border-color 0.15s ease",
                "opacity": card_opacity,
            },
        )
        cards.append(card)

    card_grid = html.Div(
        cards,
        style={
            "display": "grid",
            "gridTemplateColumns": "1fr 1fr",
            "gap": "8px",
        },
    )

    # Chips output is hidden but must be a list for the callback
    return [], card_grid, sig


@app.callback(
    Output("terminal-active-symbol", "data"),
    Input({"type": "watchlist-row-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_symbol(n_clicks_list):
    if not any(n_clicks_list):
        return dash.no_update
    return ctx.triggered_id["index"]


@app.callback(
    Output("screener-results", "children"),
    Output("screener-results-store", "data"),
    Output("screener-active-store", "data"),
    Input("btn-screener-run", "n_clicks"),
    State("terminal-watchlist", "data"),
    State("screener-rsi", "value"),
    State("screener-chg-min", "value"),
    State("screener-chg-max", "value"),
    State("screener-flags", "value"),
    State("screener-pe-max", "value"),
    State("screener-beta-max", "value"),
    State("screener-mktcap-min", "value"),
    State("screener-sort", "value"),
    prevent_initial_call=True,
)
def _run_screener(
    _, watchlist, rsi_range, chg_min, chg_max, flags, pe_max, beta_max, mktcap_min, sort_by
):
    wl = watchlist or []
    if not wl:
        return (
            html.Div(
                "No symbols to screen.",
                style={"color": TEXT_DIM, "fontSize": "11px", "padding": "8px"},
            ),
            [],
            False,
        )

    rsi_min = (rsi_range or [0, 100])[0]
    rsi_max = (rsi_range or [0, 100])[1]

    filters: dict = {
        "rsi_min": rsi_min,
        "rsi_max": rsi_max,
        "sort_by": sort_by or "change_pct",
        "sort_desc": True,
    }
    if chg_min is not None:
        try:
            filters["change_pct_min"] = float(chg_min)
        except (TypeError, ValueError):
            pass
    if chg_max is not None:
        try:
            filters["change_pct_max"] = float(chg_max)
        except (TypeError, ValueError):
            pass
    flags = flags or []
    if "above_ma20" in flags:
        filters["above_ma20"] = True
    if "high_volume" in flags:
        filters["volume_min"] = 1_000_000
    if pe_max is not None:
        try:
            filters["pe_max"] = float(pe_max)
        except (TypeError, ValueError):
            pass
    if beta_max is not None:
        try:
            filters["beta_max"] = float(beta_max)
        except (TypeError, ValueError):
            pass
    if mktcap_min is not None:
        try:
            # Input is in $B; convert to raw value
            filters["mktcap_min"] = float(mktcap_min) * 1e9
        except (TypeError, ValueError):
            pass

    try:
        results = run_screener(wl, filters)
    except Exception as exc:
        logger.warning("screener: run_screener failed: %s", exc)
        results = []

    if not results:
        return (
            html.Div(
                "No symbols match the current filters.",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "11px",
                    "fontStyle": "italic",
                    "padding": "8px",
                },
            ),
            [],
            False,
        )

    matched_syms = [item.get("symbol", "") for item in results]
    rows = []
    for item in results:
        sym = item.get("symbol", "")
        rows.append(_watchlist_row(sym, item, False))

    return (
        html.Div(
            rows,
            style={
                "background": BG_PANEL,
                "border": f"1px solid {BORDER}",
                "borderRadius": "4px",
                "padding": "12px",
            },
        ),
        matched_syms,
        True,
    )


@app.callback(
    Output("screener-active-store", "data", allow_duplicate=True),
    Output("screener-results-store", "data", allow_duplicate=True),
    Input("btn-screener-clear", "n_clicks"),
    prevent_initial_call=True,
)
def _clear_screener(_):
    return False, []


@app.callback(
    Output("compare-panel", "style"),
    Input("btn-compare", "n_clicks"),
    State("compare-panel", "style"),
    prevent_initial_call=True,
)
def _toggle_compare(n, style):
    is_open = (style or {}).get("display") != "none"
    if is_open:
        return {"display": "none"}
    return {
        "display": "block",
        "marginBottom": "12px",
        "background": BG_HOVER,
        "border": f"1px solid {BORDER}",
        "borderRadius": "4px",
        "padding": "12px 14px",
    }


@app.callback(
    Output("csv-download", "data"),
    Input("btn-export-csv", "n_clicks"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=True,
)
def _export_csv(n, watchlist):
    if not n or not watchlist:
        return dash.no_update
    import csv as _csv
    import io
    from datetime import date as _date

    wl = watchlist or []
    try:
        prices = fetch_watchlist_prices(wl)
    except Exception as exc:
        logger.warning("csv export: fetch_watchlist_prices failed: %s", exc)
        prices = {}

    rows = []
    for sym in wl:
        d = prices.get(sym, {})
        rows.append(
            {
                "symbol": sym,
                "price": d.get("price", ""),
                "change_pct": d.get("change_pct", ""),
                "rsi_14": d.get("rsi_14", ""),
                "volume": d.get("volume", ""),
                "timestamp": _date.today().isoformat(),
            }
        )

    buf = io.StringIO()
    writer = _csv.DictWriter(
        buf, fieldnames=["symbol", "price", "change_pct", "rsi_14", "volume", "timestamp"]
    )
    writer.writeheader()
    writer.writerows(rows)
    filename = f"apex7_watchlist_{_date.today().isoformat()}.csv"
    return {"content": buf.getvalue(), "filename": filename}


@app.callback(
    Output("price-alerts-store", "data"),
    Input("btn-set-alert", "n_clicks"),
    State("alert-symbol-input", "value"),
    State("alert-direction-dropdown", "value"),
    State("alert-price-input", "value"),
    State("price-alerts-store", "data"),
    prevent_initial_call=True,
)
def _set_alert(_, sym, direction, price, alerts):
    if not sym or price is None:
        return alerts or []
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return alerts or []
    entry = {
        "symbol": sym.strip().upper(),
        "direction": direction or "above",
        "price": price_f,
        "id": int(time.time() * 1000),
    }
    return (alerts or []) + [entry]


@app.callback(
    Output("price-alerts-store", "data", allow_duplicate=True),
    Input({"type": "alert-remove-btn", "index": ALL}, "n_clicks"),
    State("price-alerts-store", "data"),
    prevent_initial_call=True,
)
def _remove_alert(n_clicks_list, alerts):
    if not any(n_clicks_list):
        return alerts or []
    alert_id = ctx.triggered_id["index"]
    return [a for a in (alerts or []) if a.get("id") != alert_id]


@app.callback(
    Output("alerts-list", "children"),
    Output("alert-banner", "children"),
    Output("alert-banner", "style"),
    Input("check-alerts-interval", "n_intervals"),
    State("price-alerts-store", "data"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=False,
)
def _check_alerts(_, alerts, watchlist):
    alerts = alerts or []
    if not alerts:
        empty = html.Div(
            "No alerts set.",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "fontStyle": "italic",
                "padding": "6px 0",
            },
        )
        return empty, html.Span(), {"display": "none"}

    all_syms = list({a["symbol"] for a in alerts} | set(watchlist or []))
    try:
        prices = fetch_watchlist_prices(all_syms)
    except Exception as exc:
        logger.warning("alerts: fetch_watchlist_prices failed: %s", exc)
        prices = {}

    triggered = []
    list_items = []
    for a in alerts:
        sym = a["symbol"]
        cur = (prices.get(sym) or {}).get("price")
        fired = False
        if cur is not None:
            if a["direction"] == "above" and cur >= a["price"]:
                fired = True
            elif a["direction"] == "below" and cur <= a["price"]:
                fired = True
        if fired:
            triggered.append(a)

        dir_col = GREEN if a["direction"] == "above" else RED
        # Alert chip: BG_CARD background, YELLOW left border always
        list_items.append(
            html.Div(
                [
                    html.Span(
                        sym,
                        style={
                            "fontSize": "10px",
                            "fontWeight": "700",
                            "color": BLUE,
                            "width": "55px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        a["direction"].upper(),
                        style={
                            "fontSize": "9px",
                            "color": dir_col,
                            "width": "45px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"${a['price']:.2f}",
                        style={
                            "fontSize": "11px",
                            "color": TEXT_MAIN,
                            "flex": "1",
                        },
                    ),
                    (
                        html.Span(
                            "FIRED",
                            style={"fontSize": "9px", "color": ORANGE, "marginRight": "8px"},
                        )
                        if fired
                        else html.Span()
                    ),
                    html.Button(
                        "×",
                        id={"type": "alert-remove-btn", "index": a["id"]},
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": "none",
                            "color": TEXT_DIM,
                            "cursor": "pointer",
                            "fontSize": "14px",
                            "padding": "0",
                            "fontFamily": FONT,
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px",
                    "padding": "4px 8px",
                    "background": BG_CARD,
                    "borderLeft": f"3px solid {YELLOW}",
                    "borderRadius": "0 2px 2px 0",
                    "marginBottom": "3px",
                },
            )
        )

    # Technical alerts: auto-detect RSI extremes and volume spikes
    tech_alerts = []
    all_syms_wl = list(set(watchlist or []))
    if all_syms_wl:
        try:
            wl_prices = fetch_watchlist_prices(all_syms_wl)
            for sym, d in wl_prices.items():
                if d.get("price") is None:
                    continue
                rsi_v = d.get("rsi_14")
                if rsi_v is not None:
                    try:
                        rsi_f = float(rsi_v)
                        if rsi_f <= 25:
                            tech_alerts.append(
                                html.Div(
                                    f"⬇ {sym}: RSI {rsi_f:.0f} — EXTREME OVERSOLD",
                                    style={
                                        "fontSize": "10px",
                                        "color": GREEN,
                                        "padding": "2px 0",
                                    },
                                )
                            )
                        elif rsi_f >= 75:
                            tech_alerts.append(
                                html.Div(
                                    f"⬆ {sym}: RSI {rsi_f:.0f} — EXTREME OVERBOUGHT",
                                    style={
                                        "fontSize": "10px",
                                        "color": RED,
                                        "padding": "2px 0",
                                    },
                                )
                            )
                    except (TypeError, ValueError):
                        pass
        except Exception as exc:
            logger.debug("tech alerts: fetch failed: %s", exc)

    if tech_alerts:
        list_items.append(
            html.Div(
                [
                    html.Div(
                        "TECHNICAL",
                        style={
                            "fontSize": "8px",
                            "color": TEXT_DIM,
                            "letterSpacing": "0.12em",
                            "fontWeight": "700",
                            "marginBottom": "4px",
                            "marginTop": "8px",
                        },
                    )
                ]
                + tech_alerts,
                style={
                    "padding": "4px 8px",
                    "background": BG_CARD,
                    "borderLeft": f"3px solid {YELLOW}",
                    "borderRadius": "0 2px 2px 0",
                },
            )
        )

    if triggered:
        names = ", ".join(
            f"{a['symbol']} {a['direction'].upper()} ${a['price']:.2f}" for a in triggered[:3]
        )
        banner_children = html.Div(
            [
                html.Span(
                    "ALERT: ", style={"fontWeight": "700", "color": ORANGE, "marginRight": "4px"}
                ),
                html.Span(names, style={"color": TEXT_MAIN}),
            ],
            style={"fontSize": "11px"},
        )
        banner_style = {
            "display": "block",
            "background": f"{ORANGE}18",
            "border": f"1px solid {ORANGE}44",
            "borderRadius": "3px",
            "padding": "7px 10px",
            "marginBottom": "8px",
        }
    else:
        banner_children = html.Span()
        banner_style = {"display": "none"}

    return html.Div(list_items), banner_children, banner_style
