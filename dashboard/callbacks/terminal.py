"""APEX-7 — Terminal tab callbacks (19 callbacks)."""

import math
import time

import dash
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from agents.shared.watchlist import add_to_watchlist, get_watchlist, remove_from_watchlist
from core.external_data import fetch_fear_greed, fetch_fred_latest
from dashboard.controller import _state
from market_data import (
    build_economic_calendar_rows,
    fetch_comparison,
    fetch_correlation_matrix,
    fetch_macro,
    fetch_news,
    fetch_ohlcv,
    fetch_sector_performance,
    fetch_sparkline,
    fetch_watchlist_prices,
    run_screener,
)
from dashboard.layout import _fmt_volume, _make_sparkline_fig, _watchlist_row
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BG_HOVER,
    BLUE,
    BORDER,
    FONT,
    GRAY,
    GREEN,
    ORANGE,
    PURPLE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    YELLOW,
    app,
)

# Local token not in server.py
BG_PANEL = "#0d1424"

_MACRO_KEYS = {"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}
_MACRO_BAR_EXTRA_CACHE_SEC = 60.0
_FEAR_GREED_GREEN_LIGHT = "#86efac"
_FEAR_GREED_GREEN_DARK = "#15803d"

# Dot color palette for symbol cards (by position)
_DOT_PALETTE = [YELLOW, BLUE, GREEN, PURPLE]


def _fear_greed_bar_bucket(score: int) -> tuple[str, str]:
    """Return (mood label, color) for CNN Fear & Greed score bands."""
    if score < 25:
        return ("Extreme Fear", RED)
    if score < 45:
        return ("Fear", ORANGE)
    if score <= 55:
        return ("Neutral", GRAY)
    if score <= 75:
        return ("Greed", _FEAR_GREED_GREEN_LIGHT)
    return ("Extreme Greed", _FEAR_GREED_GREEN_DARK)


def _fallback_active_symbol(symbol) -> str:
    if symbol:
        return symbol
    wl = get_watchlist()
    return wl[0] if wl else "AAPL"


def _mini_macro_chart(spark_data, chg):
    """80x28px sparkline for macro bar blocs."""
    if not spark_data:
        return html.Div(style={"height": "28px", "width": "80px"})
    prices = [d["price"] for d in spark_data[-5:]]
    color = GREEN if (chg is not None and chg > 0) else RED
    h = color.lstrip("#")
    r_c, g_c, b_c = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    fig = go.Figure(
        go.Scatter(
            y=prices,
            mode="lines",
            line=dict(color=color, width=1.5),
            fill="tozeroy",
            fillcolor=f"rgba({r_c},{g_c},{b_c},0.08)",
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        height=28,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": False, "staticPlot": True},
        style={"height": "28px", "width": "80px"},
    )


@app.callback(
    Output("macro-bar-content", "children"),
    Input("macro-interval", "n_intervals"),
    prevent_initial_call=False,
)
def _update_macro_bar(_):
    try:
        data = fetch_macro()
    except Exception:
        data = {}

    _lbl = {
        "fontSize": "10px",
        "color": TEXT_DIM,
        "letterSpacing": "2px",
        "textTransform": "uppercase",
        "display": "block",
    }
    _cell = {
        "flex": "1",
        "display": "flex",
        "flexDirection": "column",
        "alignItems": "center",
        "justifyContent": "center",
        "padding": "0 18px",
        "minWidth": "0",
    }

    bar_divs: list[html.Div] = []

    for key in ("VIX", "SPY", "DXY"):
        yf_sym = _MACRO_KEYS[key]
        d = data.get(key, {})
        price = d.get("price")
        chg = d.get("change_pct")
        dirn = d.get("direction", "flat")

        price_str = f"{float(price):.2f}" if price is not None else "—"

        if chg is None:
            chg_str = "—"
            chg_col = TEXT_DIM
        else:
            chg_f = float(chg)
            chg_col = GREEN if dirn == "up" else (RED if dirn == "down" else TEXT_DIM)
            arrow = "▲ " if dirn == "up" else ("▼ " if dirn == "down" else "")
            chg_str = f"{arrow}{chg_f:+.2f}%"

        try:
            spark = fetch_sparkline(yf_sym)
        except Exception:
            spark = []

        mini = _mini_macro_chart(spark, float(chg) if chg is not None else None)

        bar_divs.append(
            html.Div(
                [
                    html.Span(key, style=_lbl),
                    html.Div(
                        [
                            html.Span(
                                price_str,
                                style={
                                    "fontSize": "22px",
                                    "fontWeight": "bold",
                                    "color": TEXT_MAIN,
                                    "lineHeight": "1.1",
                                    "fontFamily": FONT,
                                },
                            ),
                            html.Span(
                                chg_str,
                                style={
                                    "fontSize": "12px",
                                    "color": chg_col,
                                    "marginLeft": "8px",
                                },
                            ),
                        ],
                        style={"display": "flex", "alignItems": "baseline"},
                    ),
                    mini,
                ],
                style=_cell,
            )
        )

    try:
        fg = fetch_fear_greed(max_cache_sec=_MACRO_BAR_EXTRA_CACHE_SEC)
    except Exception:
        fg = None
    if fg and fg.get("score") is not None:
        sc = int(fg["score"])
        mood, fg_col = _fear_greed_bar_bucket(sc)
        fg_main = f"F&G: {sc} ({mood})"
        fg_color = fg_col
    else:
        fg_main = "F&G: —"
        fg_color = TEXT_DIM

    bar_divs.append(
        html.Div(
            [
                html.Span("F&G", style=_lbl),
                html.Span(
                    fg_main,
                    style={
                        "fontSize": "17px",
                        "fontWeight": "bold",
                        "color": fg_color,
                        "fontFamily": FONT,
                    },
                ),
            ],
            style={**_cell, "padding": "0 14px"},
        )
    )

    try:
        fed_obs = fetch_fred_latest("FEDFUNDS", max_cache_sec=_MACRO_BAR_EXTRA_CACHE_SEC)
        y10_obs = fetch_fred_latest("DGS10", max_cache_sec=_MACRO_BAR_EXTRA_CACHE_SEC)
    except Exception:
        fed_obs = y10_obs = None

    fed_val = fed_obs.get("value") if fed_obs else None
    y10_val = y10_obs.get("value") if y10_obs else None
    fed_str = f"FED: {float(fed_val):.2f}%" if fed_val is not None else "FED: —"
    y10_str = f"10Y: {float(y10_val):.2f}%" if y10_val is not None else "10Y: —"

    bar_divs.append(
        html.Div(
            [
                html.Span("FED", style=_lbl),
                html.Span(
                    fed_str,
                    style={
                        "fontSize": "17px",
                        "fontWeight": "bold",
                        "color": TEXT_MAIN,
                        "fontFamily": FONT,
                    },
                ),
            ],
            style={**_cell, "padding": "0 14px"},
        )
    )
    bar_divs.append(
        html.Div(
            [
                html.Span("10Y", style=_lbl),
                html.Span(
                    y10_str,
                    style={
                        "fontSize": "17px",
                        "fontWeight": "bold",
                        "color": TEXT_MAIN,
                        "fontFamily": FONT,
                    },
                ),
            ],
            style={**_cell, "padding": "0 14px"},
        )
    )

    ts = data.get("updated_at", "")
    ts_el = html.Span(
        f"⏱ {ts}" if ts else "",
        style={
            "fontSize": "10px",
            "color": TEXT_DIM,
            "marginLeft": "auto",
            "paddingRight": "16px",
            "flexShrink": "0",
        },
    )

    n_cells = len(bar_divs)

    def _cell_with_right_rule(div: html.Div, idx: int) -> html.Div:
        st = dict(div.style) if isinstance(div.style, dict) else {}
        st["borderRight"] = f"1px solid {BORDER}" if idx < n_cells - 1 else "none"
        return html.Div(div.children, style=st)

    return [_cell_with_right_rule(d, i) for i, d in enumerate(bar_divs)] + [ts_el]


def _calendar_event_line(row: dict) -> str:
    """Single-line label for an economic calendar row (earnings vs macro)."""
    ed = row["event_date"]
    mon = ed.strftime("%b")
    day = ed.day
    if row.get("kind") == "earnings":
        sym = row.get("symbol") or "?"
        d = int(row["days_until"])
        unit = "1 day" if d == 1 else f"{d} days"
        return f"{sym} earnings in {unit} ⚠️"
    ev = row.get("event") or ""
    if ev == "FOMC":
        return f"FOMC meeting {mon} {day} 📌"
    return f"{ev} release {mon} {day} 📌"


def _calendar_badge(days: int) -> tuple[str, str | None]:
    """Return badge text and color (design token); empty string if no badge."""
    if days <= 7:
        return ("THIS WEEK", RED)
    if days <= 30:
        return ("THIS MONTH", YELLOW)
    return ("", None)


_SECTOR_HEAT_PERIODS = ["1d", "5d", "1mo"]
_SECTOR_HEAT_LABELS = {"1d": "1D", "5d": "1W", "1mo": "1MO"}


def _sector_heatmap_cell_colors(pct: float | None) -> tuple[str, str]:
    """Return (background, text) hex colors for a performance cell (Finviz-style)."""
    if pct is None:
        return (BG_DEEP, TEXT_DIM)
    if pct > 2:
        return ("#14532d", "#86efac")
    if pct > 0:
        return ("#16653459", "#bbf7d0")
    if pct == 0:
        return (BG_DEEP, TEXT_DIM)
    if pct >= -2:
        return ("#7f1d1d59", "#fecaca")
    return ("#7f1d1d", "#fca5a5")


@app.callback(
    Output("sector-rotation-content", "children"),
    Input("sector-heatmap-interval", "n_intervals"),
    prevent_initial_call=False,
)
def _update_sector_rotation(_):
    periods = _SECTOR_HEAT_PERIODS
    try:
        grid = fetch_sector_performance(periods)
    except Exception:
        grid = {}

    if not grid:
        return html.Div(
            "Sector data unavailable.",
            style={"fontSize": "11px", "color": TEXT_DIM, "padding": "6px 0"},
        )

    cell = {
        "fontSize": "11px",
        "fontFamily": FONT,
        "textAlign": "center",
        "padding": "8px 6px",
        "border": f"1px solid {BORDER}",
        "fontVariantNumeric": "tabular-nums",
    }
    head = {
        **cell,
        "fontSize": "9px",
        "color": TEXT_DIM,
        "letterSpacing": "0.12em",
        "fontWeight": "700",
        "background": BG_HOVER,
    }
    row_label = {
        **cell,
        "textAlign": "left",
        "color": TEXT_DIM,
        "fontSize": "10px",
        "background": BG_HOVER,
        "maxWidth": "102px",
    }

    header_cells = [
        html.Th("", style={**head, "minWidth": "96px"}),
        *[html.Th(_SECTOR_HEAT_LABELS[p], style=head) for p in periods],
    ]
    body_rows = []
    for sector, cols in grid.items():
        row_tds = [
            html.Td(sector, style=row_label),
        ]
        for p in periods:
            raw = cols.get(p)
            pct = float(raw) if raw is not None else None
            bg, fg = _sector_heatmap_cell_colors(pct)
            disp = "—" if pct is None else f"{pct:+.2f}%"
            row_tds.append(
                html.Td(
                    disp,
                    style={
                        **cell,
                        "background": bg,
                        "color": fg,
                        "fontWeight": "600",
                    },
                )
            )
        body_rows.append(html.Tr(row_tds))

    table = html.Table(
        [html.Thead(html.Tr(header_cells)), html.Tbody(body_rows)],
        style={
            "width": "100%",
            "borderCollapse": "collapse",
            "tableLayout": "fixed",
        },
    )
    return table


def _corr_matrix_cell_colors(val: float, i: int, j: int) -> tuple[str, str]:
    """Background and text hex for one correlation cell (heatmap + gray diagonal)."""
    if i == j:
        return (BG_HOVER, TEXT_DIM)
    if not math.isfinite(val):
        return (BG_DEEP, TEXT_DIM)
    if val > 0.8:
        return ("#7f1d1d8c", "#fecaca")
    if val >= 0.4:
        return ("#713f128c", "#fde047")
    return ("#14532d8c", "#86efac")


def _portfolio_all_pairs_correlated(matrix: list, n: int, *, threshold: float = 0.8) -> bool:
    """True iff every upper-triangle pair is strictly above ``threshold``."""
    if n < 2:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            try:
                v = float(matrix[i][j])
            except (IndexError, TypeError, ValueError):
                return False
            if not math.isfinite(v) or v <= threshold:
                return False
    return True


@app.callback(
    Output("correlation-matrix-warning", "children"),
    Output("correlation-matrix-content", "children"),
    Input("correlation-period-dropdown", "value"),
    Input("sector-heatmap-interval", "n_intervals"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=False,
)
def _update_correlation_matrix(period, _tick, wl_data):
    period = period or "3mo"
    wl = wl_data if isinstance(wl_data, list) and wl_data else get_watchlist()
    syms = [str(s).strip().upper() for s in wl if s][:10]

    empty_warn = html.Div()
    if len(syms) < 2:
        return (
            empty_warn,
            html.Div(
                "Add at least two symbols to the watchlist for a correlation grid.",
                style={"fontSize": "11px", "color": TEXT_DIM},
            ),
        )

    try:
        payload = fetch_correlation_matrix(syms, period=period)
    except Exception:
        payload = {"symbols": syms, "matrix": []}

    symbols = payload.get("symbols") or []
    mat = payload.get("matrix") or []
    if not mat or len(symbols) != len(mat):
        return (
            empty_warn,
            html.Div(
                "Could not compute correlations (insufficient data).",
                style={"fontSize": "11px", "color": TEXT_DIM},
            ),
        )

    n = len(symbols)
    warn = empty_warn
    if _portfolio_all_pairs_correlated(mat, n):
        warn = html.Div(
            "⚠️ Portfolio highly correlated — consider diversifying",
            style={
                "fontSize": "11px",
                "color": YELLOW,
                "fontWeight": "600",
                "padding": "6px 8px",
                "border": f"1px solid {YELLOW}",
                "borderRadius": "4px",
                "background": f"{YELLOW}14",
            },
        )

    cell_base = {
        "fontSize": "10px",
        "fontFamily": FONT,
        "textAlign": "center",
        "padding": "6px 4px",
        "border": f"1px solid {BORDER}",
        "fontVariantNumeric": "tabular-nums",
        "minWidth": "44px",
    }
    head = {
        **cell_base,
        "background": BG_HOVER,
        "color": TEXT_DIM,
        "fontSize": "9px",
        "fontWeight": "700",
    }

    header_cells = [html.Th("", style={**head, "minWidth": "52px"})] + [
        html.Th(s, style=head) for s in symbols
    ]
    body_rows = []
    for i, sym in enumerate(symbols):
        row_cells = [
            html.Td(
                sym,
                style={
                    **cell_base,
                    "textAlign": "left",
                    "color": TEXT_DIM,
                    "background": BG_HOVER,
                    "fontWeight": "600",
                },
            )
        ]
        for j in range(n):
            v = float(mat[i][j])
            bg, fg = _corr_matrix_cell_colors(v, i, j)
            row_cells.append(
                html.Td(
                    f"{v:.2f}",
                    style={**cell_base, "background": bg, "color": fg, "fontWeight": "600"},
                )
            )
        body_rows.append(html.Tr(row_cells))

    table = html.Table(
        [html.Thead(html.Tr(header_cells)), html.Tbody(body_rows)],
        style={
            "width": "100%",
            "borderCollapse": "collapse",
            "tableLayout": "fixed",
        },
    )
    return warn, table


@app.callback(
    Output("economic-calendar-content", "children"),
    Input("macro-interval", "n_intervals"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=False,
)
def _update_economic_calendar(_, wl_data):
    symbols = wl_data if isinstance(wl_data, list) and wl_data else get_watchlist()
    try:
        rows = build_economic_calendar_rows(symbols, horizon_days=120)
    except Exception:
        rows = []

    if not rows:
        return html.Div(
            "No upcoming events in the next 120 days.",
            style={"fontSize": "11px", "color": TEXT_DIM, "padding": "4px 0"},
        )

    out: list = []
    for row in rows:
        line = _calendar_event_line(row)
        badge_txt, badge_col = _calendar_badge(int(row["days_until"]))
        date_iso = row["event_date"].isoformat()
        badge_el = (
            html.Span(
                badge_txt,
                style={
                    "fontSize": "8px",
                    "marginLeft": "8px",
                    "padding": "2px 6px",
                    "borderRadius": "2px",
                    "border": f"1px solid {badge_col}",
                    "color": badge_col,
                    "letterSpacing": "0.1em",
                    "fontWeight": "600",
                },
            )
            if badge_txt
            else None
        )
        out.append(
            html.Div(
                [
                    html.Div(
                        date_iso,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_DIM,
                            "minWidth": "78px",
                            "flexShrink": "0",
                            "fontVariantNumeric": "tabular-nums",
                        },
                    ),
                    html.Div(
                        [html.Span(line, style={"fontSize": "11px", "color": TEXT_MAIN})]
                        + ([badge_el] if badge_el else []),
                        style={
                            "flex": "1",
                            "display": "flex",
                            "alignItems": "center",
                            "flexWrap": "wrap",
                            "gap": "4px",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "10px",
                    "padding": "8px 0",
                    "borderLeft": f"2px solid {BORDER}",
                    "paddingLeft": "12px",
                    "marginLeft": "2px",
                },
            )
        )
    return html.Div(out)


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


@app.callback(
    Output("watchlist-chips", "children"),
    Output("watchlist-table", "children"),
    Input("terminal-watchlist", "data"),
    Input("watchlist-interval", "n_intervals"),
    Input("terminal-active-symbol", "data"),
    Input("screener-active-store", "data"),
    Input("screener-results-store", "data"),
)
def _update_watchlist(watchlist, _, active_sym, screener_active, screener_results):
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
        return [], empty_card

    try:
        prices = fetch_watchlist_prices(wl)
    except Exception:
        prices = {}

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
        chg_col = GREEN if chg_pct >= 0 else RED
        dot_col = _DOT_PALETTE[i % len(_DOT_PALETTE)]
        active = sym == active_sym

        try:
            spark = fetch_sparkline(sym)
        except Exception:
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
                # RSI + MA20 + VOL row
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
                        "gap": "6px",
                        "marginTop": "6px",
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
    return [], card_grid


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
    Output("news-feed", "children"),
    Output("news-header", "children"),
    Input("terminal-active-symbol", "data"),
    Input("news-interval", "n_intervals"),
)
def _update_news(symbol, _):
    sym = _fallback_active_symbol(symbol)
    header = f"NEWS — {sym}"

    try:
        items = fetch_news(sym)
    except Exception:
        items = []

    if not items:
        return (
            html.Div(
                "No news available.",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "12px",
                    "fontStyle": "italic",
                    "textAlign": "center",
                    "padding": "20px",
                },
            ),
            header,
        )

    cards = []
    for item in items:
        sentiment = item.get("sentiment", "neutral")
        if sentiment == "positive":
            sent_col = GREEN
            sent_dot = "🟢"
        elif sentiment == "negative":
            sent_col = RED
            sent_dot = "🔴"
        else:
            sent_col = GRAY
            sent_dot = "⚪"

        title = item.get("title", "")
        source = item.get("source", "")
        age = item.get("age", "")
        url = item.get("url", "#")

        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(sent_dot, style={"marginRight": "6px", "fontSize": "10px"}),
                            html.A(
                                title,
                                href=url,
                                target="_blank",
                                style={
                                    "color": TEXT_MAIN,
                                    "fontSize": "12px",
                                    "fontWeight": "600",
                                    "textDecoration": "none",
                                    "lineHeight": "1.4",
                                    "fontFamily": FONT,
                                    "display": "-webkit-box",
                                    "WebkitLineClamp": "2",
                                    "WebkitBoxOrient": "vertical",
                                    "overflow": "hidden",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "alignItems": "flex-start",
                            "marginBottom": "4px",
                        },
                    ),
                    html.Div(
                        f"{source}  ·  {age}",
                        style={"fontSize": "10px", "color": TEXT_DIM, "marginTop": "2px"},
                    ),
                ],
                style={
                    "borderLeft": f"3px solid {sent_col}",
                    "background": BG_CARD,
                    "padding": "8px 10px",
                    "marginBottom": "3px",
                    "borderRadius": "0 4px 4px 0",
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "3px",
                },
            )
        )

    return html.Div(cards), header


@app.callback(
    Output("news-feed-content", "children"),
    Input("terminal-active-symbol", "data"),
    Input("news-interval", "n_intervals"),
    State("main-tabs", "value"),
)
def _update_news_content(symbol, _, active_tab):
    if active_tab != "terminal":
        return no_update
    sym = _fallback_active_symbol(symbol)

    try:
        items = fetch_news(sym)
    except Exception:
        items = []

    if not items:
        return html.Div(
            "No news available.",
            style={
                "color": TEXT_DIM,
                "fontSize": "12px",
                "fontStyle": "italic",
                "textAlign": "center",
                "padding": "20px",
            },
        )

    cards = []
    for item in items:
        sentiment = item.get("sentiment", "neutral")
        if sentiment == "positive":
            sent_dot = "🟢"
            border_col = GREEN
        elif sentiment == "negative":
            sent_dot = "🔴"
            border_col = RED
        else:
            sent_dot = "⚪"
            border_col = "#334155"

        title = item.get("title", "")
        source = item.get("source", "")
        age = item.get("age", "")
        url = item.get("url", "#")

        cards.append(
            html.Div(
                [
                    html.Div(
                        style={"display": "flex", "gap": "8px", "alignItems": "flex-start"},
                        children=[
                            html.Span(
                                sent_dot,
                                style={
                                    "fontSize": "10px",
                                    "marginTop": "2px",
                                    "flexShrink": "0",
                                },
                            ),
                            html.Div(
                                [
                                    html.A(
                                        title,
                                        href=url,
                                        target="_blank",
                                        style={
                                            "color": TEXT_MAIN,
                                            "textDecoration": "none",
                                            "fontSize": "12px",
                                            "lineHeight": "1.4",
                                            "display": "-webkit-box",
                                            "WebkitLineClamp": "2",
                                            "WebkitBoxOrient": "vertical",
                                            "overflow": "hidden",
                                        },
                                    ),
                                    html.Div(
                                        f"{source} · {age}",
                                        style={
                                            "color": TEXT_DIM,
                                            "fontSize": "10px",
                                            "marginTop": "2px",
                                        },
                                    ),
                                ]
                            ),
                        ],
                    )
                ],
                style={
                    "padding": "8px 10px",
                    "borderLeft": f"3px solid {border_col}",
                    "marginBottom": "3px",
                    "background": BG_CARD,
                    "borderRadius": "0 4px 4px 0",
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "3px",
                },
            )
        )

    return html.Div(cards)


@app.callback(
    Output("chart-overlay-content", "children"),
    Input("terminal-active-symbol", "data"),
    State("main-tabs", "value"),
)
def _update_chart_overlay(symbol, active_tab):
    if active_tab != "terminal" or not symbol:
        return no_update

    data = fetch_ohlcv(symbol, period="1mo")
    if not data:
        return html.Div(
            f"No data for {symbol}",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "padding": "12px",
            },
        )

    closes = [d["close"] for d in data]
    dates = [d["date"] for d in data]
    color = GREEN if closes[-1] >= closes[0] else RED
    max_idx = closes.index(max(closes))
    min_idx = closes.index(min(closes))

    h = color.lstrip("#")
    r_c, g_c, b_c = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=closes,
            mode="lines",
            line=dict(color=color, width=1.5),
            fill="tozeroy",
            fillcolor=f"rgba({r_c},{g_c},{b_c},0.06)",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[dates[max_idx]],
            y=[closes[max_idx]],
            mode="markers+text",
            marker=dict(color=YELLOW, size=5),
            text=[f"${closes[max_idx]:.2f}"],
            textposition="top center",
            textfont=dict(size=9, color=YELLOW),
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[dates[min_idx]],
            y=[closes[min_idx]],
            mode="markers+text",
            marker=dict(color=RED, size=5),
            text=[f"${closes[min_idx]:.2f}"],
            textposition="bottom center",
            textfont=dict(size=9, color=RED),
            showlegend=False,
        )
    )
    fig.update_layout(
        title=dict(
            text=f"{symbol} — 1mo",
            font=dict(size=11, color=TEXT_DIM),
            x=0,
        ),
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_CARD,
        margin=dict(l=8, r=8, t=32, b=24),
        height=200,
        showlegend=False,
        xaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            tickfont=dict(size=9, color=TEXT_DIM),
            showline=False,
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            tickfont=dict(size=9, color=TEXT_DIM),
            tickprefix="$",
            showline=False,
            zeroline=False,
        ),
    )
    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": False},
        style={"height": "200px"},
    )


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
    prevent_initial_call=True,
)
def _run_screener(_, watchlist, rsi_range, chg_min, chg_max, flags):
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

    filters: dict = {"rsi_min": rsi_min, "rsi_max": rsi_max}
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

    try:
        results = run_screener(wl, filters)
    except Exception:
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
    Output("compare-chart", "figure"),
    Input("compare-period", "value"),
    Input("compare-symbols", "value"),
    prevent_initial_call=False,
)
def _update_comparison(period, symbols):
    if not symbols:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor=BG_DEEP,
            plot_bgcolor=BG_CARD,
            font=dict(family=FONT, color=TEXT_MAIN, size=10),
            margin=dict(l=40, r=20, t=30, b=40),
            height=260,
            xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=8, color=TEXT_DIM)),
            yaxis=dict(
                showgrid=True,
                gridcolor=BORDER,
                zeroline=False,
                tickfont=dict(size=8, color=TEXT_DIM),
            ),
            annotations=[
                dict(
                    text="Select symbols above to compare",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(family=FONT, size=11, color=TEXT_DIM),
                )
            ],
        )
        return fig

    try:
        data = fetch_comparison(symbols, period or "1mo")
    except Exception:
        data = {}

    palette = [BLUE, PURPLE, GREEN, RED, ORANGE]
    fig = go.Figure()
    for i, sym in enumerate(symbols):
        series = data.get(sym, [])
        if not series:
            continue
        col = palette[i % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=[p["date"] for p in series],
                y=[p["value"] for p in series],
                mode="lines",
                name=sym,
                line=dict(color=col, width=1.5),
            )
        )
    fig.update_layout(
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=40, r=20, t=30, b=40),
        height=260,
        showlegend=True,
        legend=dict(
            x=0, y=1, bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, size=9, color=TEXT_DIM)
        ),
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=8, color=TEXT_DIM)),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            zeroline=False,
            tickfont=dict(size=8, color=TEXT_DIM),
            title=dict(text="Normalized (base=100)", font=dict(size=8, color=TEXT_DIM)),
        ),
    )
    return fig


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
    except Exception:
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
    except Exception:
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
