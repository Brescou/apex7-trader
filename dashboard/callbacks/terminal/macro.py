"""APEX-7 — Terminal tab — macro bar, sector rotation, correlation matrix, economic calendar."""

import logging
import math

import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html

from agents.shared.watchlist import get_watchlist
from core.external_data import fetch_fear_greed, fetch_fred_latest
from market_data import (
    build_economic_calendar_rows,
    fetch_correlation_matrix,
    fetch_macro,
    fetch_ohlcv,
    fetch_sector_performance,
    fetch_sparkline,
)
from dashboard.server import (
    BG_DEEP,
    BG_HOVER,
    BORDER,
    FONT,
    GRAY,
    GREEN,
    ORANGE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    YELLOW,
    app,
)
from dashboard.callbacks.terminal._shared import (
    _FEAR_GREED_GREEN_DARK,
    _FEAR_GREED_GREEN_LIGHT,
    _MACRO_BAR_EXTRA_CACHE_SEC,
    _MACRO_KEYS,
)

logger = logging.getLogger("apex7.terminal.macro")


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
    except Exception as exc:
        logger.warning("macro bar: fetch_macro failed: %s", exc)
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
        except Exception as exc:
            logger.debug("macro bar: sparkline failed for %s: %s", yf_sym, exc)
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
    except Exception as exc:
        logger.warning("macro bar: fear & greed fetch failed: %s", exc)
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

    # Extra macro symbols: Gold (GLD), Oil (USO), EUR/USD (EURUSD=X)
    _EXTRA_TICKERS = [("GOLD", "GLD"), ("OIL", "USO"), ("EUR/USD", "EURUSD=X")]
    for label, sym in _EXTRA_TICKERS:
        try:
            ohlcv = fetch_ohlcv(sym, period="5d")
            if ohlcv and len(ohlcv) >= 2:
                price = ohlcv[-1]["close"]
                prev = ohlcv[-2]["close"]
                chg = round((price - prev) / prev * 100, 2) if prev else 0.0
                dirn = "up" if chg > 0.05 else ("down" if chg < -0.05 else "flat")
                price_str = f"{price:.2f}" if label != "EUR/USD" else f"{price:.4f}"
                arrow = "▲ " if dirn == "up" else ("▼ " if dirn == "down" else "")
                chg_col = GREEN if dirn == "up" else (RED if dirn == "down" else TEXT_DIM)
                chg_str = f"{arrow}{chg:+.2f}%"
            else:
                price_str = "—"
                chg_str = "—"
                chg_col = TEXT_DIM
        except Exception as exc:
            logger.debug("macro bar: extra ticker %s failed: %s", sym, exc)
            price_str = "—"
            chg_str = "—"
            chg_col = TEXT_DIM

        bar_divs.append(
            html.Div(
                [
                    html.Span(label, style=_lbl),
                    html.Div(
                        [
                            html.Span(
                                price_str,
                                style={
                                    "fontSize": "18px",
                                    "fontWeight": "bold",
                                    "color": TEXT_MAIN,
                                    "lineHeight": "1.1",
                                    "fontFamily": FONT,
                                },
                            ),
                            html.Span(
                                chg_str,
                                style={"fontSize": "11px", "color": chg_col, "marginLeft": "6px"},
                            ),
                        ],
                        style={"display": "flex", "alignItems": "baseline"},
                    ),
                ],
                style={**_cell, "padding": "0 12px"},
            )
        )

    try:
        fed_obs = fetch_fred_latest("FEDFUNDS", max_cache_sec=_MACRO_BAR_EXTRA_CACHE_SEC)
        y10_obs = fetch_fred_latest("DGS10", max_cache_sec=_MACRO_BAR_EXTRA_CACHE_SEC)
        y2_obs = fetch_fred_latest("DGS2", max_cache_sec=_MACRO_BAR_EXTRA_CACHE_SEC)
    except Exception as exc:
        logger.warning("macro bar: FRED fetch failed: %s", exc)
        fed_obs = y10_obs = y2_obs = None

    fed_val = fed_obs.get("value") if fed_obs else None
    y10_val = y10_obs.get("value") if y10_obs else None
    y2_val = y2_obs.get("value") if y2_obs else None
    fed_str = f"{float(fed_val):.2f}%" if fed_val is not None else "—"
    y10_str = f"{float(y10_val):.2f}%" if y10_val is not None else "—"

    # 10Y-2Y spread: positive = normal curve, negative = inverted
    if y10_val is not None and y2_val is not None:
        spread = float(y10_val) - float(y2_val)
        spread_col = GREEN if spread > 0 else RED
        spread_str = f"{spread:+.2f}%"
    else:
        spread = None
        spread_col = TEXT_DIM
        spread_str = "—"

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
    bar_divs.append(
        html.Div(
            [
                html.Span("SPREAD", style=_lbl),
                html.Span(
                    spread_str,
                    style={
                        "fontSize": "15px",
                        "fontWeight": "bold",
                        "color": spread_col,
                        "fontFamily": FONT,
                    },
                ),
                html.Span(
                    "10Y-2Y",
                    style={"fontSize": "9px", "color": TEXT_DIM, "marginTop": "2px"},
                ),
            ],
            style={
                **_cell,
                "padding": "0 10px",
                "alignItems": "center",
                "gap": "1px",
            },
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


_IMPORTANCE_COLORS = {
    "high": RED,
    "medium": YELLOW,
    "low": GRAY,
}


def _calendar_event_label(row: dict) -> str:
    """Single-line label for an economic calendar row (earnings vs macro)."""
    ed = row["event_date"]
    mon = ed.strftime("%b")
    day = ed.day
    if row.get("kind") == "earnings":
        sym = row.get("symbol") or "?"
        d = int(row["days_until"])
        unit = "1 day" if d == 1 else f"{d} days"
        return f"{sym} earnings in {unit}"
    ev = row.get("event") or ""
    if ev == "FOMC":
        return f"FOMC meeting — {mon} {day}"
    return f"{ev} release — {mon} {day}"


# keep the old name as an alias so other code that imports it still works
def _calendar_event_line(row: dict) -> str:
    return _calendar_event_label(row)


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
    except Exception as exc:
        logger.warning("sector rotation: fetch_sector_performance failed: %s", exc)
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
    except Exception as exc:
        logger.warning("correlation matrix: fetch failed for %s: %s", syms, exc)
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
    except Exception as exc:
        logger.warning("economic calendar: build rows failed: %s", exc)
        rows = []

    if not rows:
        return html.Div(
            "No upcoming events in the next 120 days.",
            style={"fontSize": "11px", "color": TEXT_DIM, "padding": "4px 0"},
        )

    out: list = []
    for row in rows:
        label = _calendar_event_label(row)
        days = int(row["days_until"])
        badge_txt, badge_col = _calendar_badge(days)
        date_iso = row["event_date"].isoformat()
        importance = (row.get("importance") or "medium").lower()
        imp_col = _IMPORTANCE_COLORS.get(importance, GRAY)

        # Optional time string (macro events only)
        time_str = row.get("time") or ""
        prev_val = row.get("previous")
        exp_val = row.get("expected")

        badge_el = (
            html.Span(
                badge_txt,
                style={
                    "fontSize": "8px",
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

        # Importance dot (●)
        imp_dot = html.Span(
            "●",
            style={
                "fontSize": "7px",
                "color": imp_col,
                "marginRight": "6px",
                "flexShrink": "0",
            },
        )

        # Previous / Expected line (macro events only)
        prev_exp_parts = []
        if prev_val is not None:
            prev_exp_parts.append(f"Prev: {prev_val}")
        if exp_val is not None:
            prev_exp_parts.append(f"Exp: {exp_val}")
        prev_exp_el = (
            html.Span(
                "  ·  ".join(prev_exp_parts),
                style={"fontSize": "9px", "color": TEXT_DIM, "marginLeft": "4px"},
            )
            if prev_exp_parts
            else None
        )

        date_line = html.Div(
            date_iso + (f"  {time_str}" if time_str else ""),
            style={
                "fontSize": "10px",
                "color": TEXT_DIM,
                "minWidth": "80px",
                "flexShrink": "0",
                "fontVariantNumeric": "tabular-nums",
            },
        )

        out.append(
            html.Div(
                [
                    date_line,
                    html.Div(
                        [
                            imp_dot,
                            html.Span(label, style={"fontSize": "11px", "color": TEXT_MAIN}),
                        ]
                        + ([prev_exp_el] if prev_exp_el else [])
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
                    "padding": "7px 0",
                    "borderLeft": f"2px solid {imp_col}",
                    "paddingLeft": "12px",
                    "marginLeft": "2px",
                },
            )
        )
    return html.Div(out)
