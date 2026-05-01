"""APEX-7 — Heatmap tab callback."""

import datetime as _dt
from collections import defaultdict

import plotly.graph_objects as go
from dash import Input, Output, dcc, html

from agents.shared.nodes import _db_read
from config import WATCHLIST as _WL
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BORDER,
    FONT,
    GREEN,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    app,
)


@app.callback(
    Output("heatmap-content", "children"),
    Output("heatmap-updated", "children"),
    Input("btn-heatmap-refresh", "n_clicks"),
    prevent_initial_call=False,
)
def _heatmap_refresh(_):
    _plotly_theme = dict(
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=50, r=20, t=40, b=50),
    )
    _colorscale = [[0.0, RED], [0.5, BORDER], [1.0, GREEN]]

    now_str = _dt.datetime.now().strftime("%H:%M:%S")

    rows = _db_read(
        "SELECT timestamp, symbol, action, price, amount_usd FROM trades "
        "WHERE action IN ('BUY','SELL') ORDER BY timestamp ASC"
    )

    if not rows:
        empty = html.Div(
            "No trade data yet. Run the agent first.",
            style={
                "color": TEXT_DIM,
                "fontSize": "12px",
                "fontStyle": "italic",
                "padding": "20px",
            },
        )
        return empty, f"Updated {now_str}"

    # ── Build buy lookup: most recent BUY price per symbol ───────────────────
    buys_by_sym: dict[str, list[tuple]] = defaultdict(list)
    sell_rows = []
    for ts, sym, action, price, amount_usd in rows:
        if action == "BUY":
            buys_by_sym[sym].append((ts, float(price) if price else 0.0))
        elif action == "SELL":
            sell_rows.append(
                (ts, sym, float(price) if price else 0.0, float(amount_usd) if amount_usd else 0.0)
            )

    # ── Heatmap 1: Quand trader — hour x weekday win rate ────────────────────
    WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    HOURS = list(range(9, 17))

    slot_wins: dict[tuple, int] = defaultdict(int)
    slot_total: dict[tuple, int] = defaultdict(int)

    for ts, sym, sell_price, _ in sell_rows:
        try:
            dt = _dt.datetime.fromisoformat(str(ts)[:19])
            dow = dt.weekday()
            hr = dt.hour
            if dow > 4 or hr < 9 or hr > 16:
                continue
            buy_entries = [(t, p) for t, p in buys_by_sym[sym] if t < ts]
            if buy_entries:
                buy_price = buy_entries[-1][1]
                pnl = (sell_price - buy_price) / buy_price if buy_price > 0 else 0.0
            else:
                pnl = 0.0
            key = (dow, hr)
            slot_total[key] += 1
            if pnl > 0:
                slot_wins[key] += 1
        except Exception:
            pass

    z1 = []
    text1 = []
    for dow in range(5):
        row_z, row_t = [], []
        for hr in HOURS:
            key = (dow, hr)
            total = slot_total.get(key, 0)
            wins = slot_wins.get(key, 0)
            wr = (wins / total * 100) if total > 0 else 0.0
            row_z.append(wr)
            row_t.append(f"{wins}/{total} trades<br>{wr:.0f}% win rate")
        z1.append(row_z)
        text1.append(row_t)

    fig1 = go.Figure(
        go.Heatmap(
            z=z1,
            x=[f"{h}h" for h in HOURS],
            y=WEEKDAYS,
            colorscale=_colorscale,
            zmin=0,
            zmax=100,
            text=text1,
            hovertemplate="%{y} %{x}<br>%{text}<extra></extra>",
            colorbar=dict(
                title=dict(text="Win %", font=dict(family=FONT, size=9, color=TEXT_DIM)),
                tickfont=dict(family=FONT, size=8, color=TEXT_DIM),
                thickness=8,
                len=0.8,
            ),
        )
    )
    fig1.update_layout(
        title=dict(
            text="Quand trader — Win Rate % par slot horaire",
            font=dict(family=FONT, size=11, color=TEXT_MAIN),
        ),
        height=280,
        **_plotly_theme,
    )

    # ── Heatmap 2: Quoi trader — symbol x action avg P&L ────────────────────
    SYMBOLS = list({sym for _, sym, _, _ in sell_rows} | set(buys_by_sym.keys()))
    SYMBOLS = [s for s in _WL if s in SYMBOLS] + [s for s in SYMBOLS if s not in _WL]
    if not SYMBOLS:
        SYMBOLS = _WL

    ACTIONS = ["BUY", "SELL"]
    pnl_sums: dict[tuple, float] = defaultdict(float)
    pnl_counts: dict[tuple, int] = defaultdict(int)
    trade_counts: dict[tuple, int] = defaultdict(int)

    for ts, sym, sell_price, _ in sell_rows:
        buy_entries = [(t, p) for t, p in buys_by_sym[sym] if t < ts]
        if buy_entries:
            buy_price = buy_entries[-1][1]
            pnl_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0.0
        else:
            pnl_pct = 0.0
        pnl_sums[(sym, "SELL")] += pnl_pct
        pnl_counts[(sym, "SELL")] += 1
        trade_counts[(sym, "SELL")] += 1

    for sym, entries in buys_by_sym.items():
        trade_counts[(sym, "BUY")] = len(entries)

    z2 = []
    text2 = []
    for sym in SYMBOLS:
        row_z, row_t = [], []
        for act in ACTIONS:
            key = (sym, act)
            n = trade_counts.get(key, 0)
            if act == "SELL" and pnl_counts.get(key, 0) > 0:
                avg = pnl_sums[key] / pnl_counts[key]
                row_z.append(avg)
                row_t.append(f"{sym} {act}: {avg:+.1f}% avg ({n} trades)")
            else:
                row_z.append(0.0)
                row_t.append(f"{sym} {act}: {n} trades (entry — P&L at close)")
        z2.append(row_z)
        text2.append(row_t)

    fig2 = go.Figure(
        go.Heatmap(
            z=z2,
            x=ACTIONS,
            y=SYMBOLS,
            colorscale=_colorscale,
            zmin=-20,
            zmax=20,
            text=text2,
            hovertemplate="%{text}<extra></extra>",
            colorbar=dict(
                title=dict(text="Avg P&L %", font=dict(family=FONT, size=9, color=TEXT_DIM)),
                tickfont=dict(family=FONT, size=8, color=TEXT_DIM),
                thickness=8,
                len=0.8,
            ),
        )
    )
    fig2.update_layout(
        title=dict(
            text="Quoi trader — Avg P&L % par symbole/action",
            font=dict(family=FONT, size=11, color=TEXT_MAIN),
        ),
        height=280,
        **_plotly_theme,
    )

    charts_row = html.Div(
        [
            dcc.Graph(figure=fig1, config={"displayModeBar": False}),
            dcc.Graph(figure=fig2, config={"displayModeBar": False}),
        ],
        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"},
    )

    total_sells = len(sell_rows)
    wins_total = sum(slot_wins.values())
    overall_wr = (wins_total / total_sells * 100) if total_sells > 0 else 0.0

    summary = html.Div(
        [
            html.Span(
                f"Total SELL trades: {total_sells}",
                style={
                    "fontSize": "10px",
                    "color": TEXT_DIM,
                    "marginRight": "20px",
                },
            ),
            html.Span(
                f"Overall win rate: {overall_wr:.1f}%",
                style={
                    "fontSize": "10px",
                    "color": GREEN if overall_wr >= 50 else RED,
                    "fontWeight": "700",
                },
            ),
        ],
        style={"marginTop": "12px"},
    )

    return html.Div([charts_row, summary]), f"Updated {now_str}"
