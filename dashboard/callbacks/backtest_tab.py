"""APEX-7 — Backtest tab callback."""

import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html

from config import INITIAL_BALANCE
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BLUE,
    BORDER,
    FONT,
    GRAY,
    GREEN,
    ORANGE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    YELLOW,
    _rgba,
    app,
)


@app.callback(
    Output("bt-results", "children"),
    Input("btn-backtest-run", "n_clicks"),
    [
        State("backtest-symbol", "value"),
        State("backtest-period", "value"),
        State("backtest-strategy", "value"),
    ],
    prevent_initial_call=True,
)
def _backtest_run(n_clicks, symbol, period, strategy):
    if not n_clicks:
        return html.Div()

    from core.backtest import run_backtest as _run_backtest

    try:
        result = _run_backtest(
            symbol=(symbol or "AAPL").strip().upper(),
            period=period or "6mo",
            strategy=strategy or "simple",
        )
    except Exception as e:
        return html.Div(
            f"Backtest error: {e}",
            style={"color": RED, "fontSize": "12px", "padding": "20px", "fontStyle": "italic"},
        )

    sym = result.get("symbol", symbol or "AAPL")
    per = result.get("period", period or "6mo")
    strat = result.get("strategy", strategy or "simple")
    ret_pct = float(result.get("total_return_pct", 0.0))
    vs_bench = float(result.get("vs_benchmark", 0.0))
    win_rate = float(result.get("win_rate", 0.0))
    drawdown = float(result.get("max_drawdown_pct", 0.0))
    sharpe = float(result.get("sharpe_ratio", 0.0))
    n_trades = int(result.get("n_trades", 0))
    bench_pct = float(result.get("benchmark_return_pct", 0.0))
    equity = result.get("equity_curve", [INITIAL_BALANCE])
    trades = result.get("trades", [])

    # ── KPI row (5 metrics) ──────────────────────────────────────────────────
    kpis = [
        ("TOTAL RETURN", f"{ret_pct:+.1f}%", GREEN if ret_pct >= 0 else RED),
        ("VS BENCHMARK", f"{vs_bench:+.1f}%", GREEN if vs_bench >= 0 else RED),
        ("WIN RATE", f"{win_rate:.1f}%", GREEN if win_rate >= 50 else ORANGE),
        ("MAX DRAWDOWN", f"{drawdown:.1f}%", RED),
        ("SHARPE RATIO", f"{sharpe:.2f}", BLUE),
    ]
    kpi_row = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        lbl,
                        style={
                            "fontSize": "9px",
                            "color": TEXT_DIM,
                            "letterSpacing": "0.1em",
                            "marginBottom": "4px",
                        },
                    ),
                    html.Div(val, style={"fontSize": "16px", "fontWeight": "700", "color": col}),
                ],
                style={
                    "background": BG_CARD,
                    "border": f"1px solid {BORDER}",
                    "borderRadius": "4px",
                    "padding": "12px 14px",
                },
            )
            for lbl, val, col in kpis
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(5, 1fr)",
            "gap": "8px",
            "marginBottom": "16px",
        },
    )

    # ── Equity curve with benchmark + trade markers ───────────────────────────
    xs = list(range(len(equity)))

    bench_end = INITIAL_BALANCE * (1 + bench_pct / 100)
    bench_xs = [0, len(equity) - 1] if len(equity) > 1 else [0, 1]
    bench_ys = [INITIAL_BALANCE, bench_end]

    buy_xs, buy_ys, buy_dates = [], [], []
    sell_xs, sell_ys, sell_dates = [], [], []

    buy_idx_map: dict[str, int] = {}
    _bar = 0
    for t in trades:
        _bar += 1
        ei = min(_bar, len(equity) - 1)
        date_str = t.get("date", "")
        action = t.get("action", "")
        price = float(t.get("price", 0.0))
        eq_val = equity[ei]
        if action == "BUY":
            buy_xs.append(ei)
            buy_ys.append(eq_val)
            buy_dates.append(f"{date_str} BUY @ ${price:.2f}")
            buy_idx_map[date_str] = ei
        elif action == "SELL":
            sell_xs.append(ei)
            sell_ys.append(eq_val)
            sell_dates.append(f"{date_str} SELL @ ${price:.2f}")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=equity,
            mode="lines",
            name=sym,
            line=dict(color=GREEN, width=2),
            fill="tozeroy",
            fillcolor=_rgba(GREEN, 0.05),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=bench_xs,
            y=bench_ys,
            mode="lines",
            name="SPY",
            line=dict(color=YELLOW, width=1, dash="dot"),
        )
    )
    if buy_xs:
        fig.add_trace(
            go.Scatter(
                x=buy_xs,
                y=buy_ys,
                mode="markers",
                name="BUY",
                marker=dict(
                    symbol="triangle-up", size=10, color=GREEN, line=dict(color=GREEN, width=1)
                ),
                text=buy_dates,
                hovertemplate="%{text}<extra></extra>",
            )
        )
    if sell_xs:
        fig.add_trace(
            go.Scatter(
                x=sell_xs,
                y=sell_ys,
                mode="markers",
                name="SELL",
                marker=dict(
                    symbol="triangle-down", size=10, color=RED, line=dict(color=RED, width=1)
                ),
                text=sell_dates,
                hovertemplate="%{text}<extra></extra>",
            )
        )
    fig.update_layout(
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=50, r=20, t=36, b=40),
        height=320,
        legend=dict(
            x=0, y=1, bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, size=9, color=TEXT_DIM)
        ),
        title=dict(
            text=f"{sym} — {per} — {strat.upper()}", font=dict(family=FONT, size=11, color=TEXT_DIM)
        ),
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=8, color=TEXT_DIM)),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            zeroline=False,
            tickprefix="$",
            tickfont=dict(size=8, color=TEXT_DIM),
        ),
    )

    # ── Trade log table ───────────────────────────────────────────────────────
    _tbl_hdr_style = {
        "display": "grid",
        "gridTemplateColumns": "100px 70px 80px 80px 80px 80px",
        "gap": "0",
        "padding": "5px 10px",
        "borderBottom": f"1px solid {BORDER}",
        "fontSize": "9px",
        "color": TEXT_DIM,
        "letterSpacing": "0.1em",
        "fontWeight": "700",
    }
    tbl_header = html.Div(
        [
            html.Span("DATE"),
            html.Span("ACTION"),
            html.Span("PRICE"),
            html.Span("SHARES"),
            html.Span("P&L $"),
            html.Span("P&L %"),
        ],
        style=_tbl_hdr_style,
    )

    tbl_rows = []
    _buy_price: dict[str, float] = {}
    _buy_shares: dict[str, float] = {}
    total_pnl = 0.0

    for t in trades:
        action = t.get("action", "")
        date_str = t.get("date", "—")
        price = float(t.get("price", 0.0))
        sym_t = t.get("symbol", sym)

        if action == "BUY":
            shares = (INITIAL_BALANCE * 0.95) / price if price > 0 else 0.0
            _buy_price[sym_t] = price
            _buy_shares[sym_t] = shares
            pnl_usd = 0.0
            pnl_pct = 0.0
            row_bg = f"{BLUE}0f"
            action_col = BLUE
        elif action == "SELL":
            bp = _buy_price.pop(sym_t, price)
            shares = _buy_shares.pop(sym_t, 0.0)
            pnl_pct = ((price - bp) / bp * 100) if bp > 0 else 0.0
            pnl_usd = shares * (price - bp)
            total_pnl += pnl_usd
            row_bg = f"{GREEN}0f" if pnl_usd >= 0 else f"{RED}0f"
            action_col = RED
        else:
            shares = pnl_usd = pnl_pct = 0.0
            row_bg = "transparent"
            action_col = GRAY

        pnl_col = GREEN if pnl_usd >= 0 else RED
        tbl_rows.append(
            html.Div(
                [
                    html.Span(date_str, style={"fontSize": "10px", "color": TEXT_DIM}),
                    html.Span(
                        action, style={"fontSize": "10px", "fontWeight": "700", "color": action_col}
                    ),
                    html.Span(f"${price:.2f}", style={"fontSize": "10px", "color": TEXT_MAIN}),
                    html.Span(f"{shares:.4f}", style={"fontSize": "10px", "color": TEXT_DIM}),
                    html.Span(
                        f"{pnl_usd:+.2f}" if action == "SELL" else "—",
                        style={
                            "fontSize": "10px",
                            "color": pnl_col if action == "SELL" else TEXT_DIM,
                            "fontWeight": "700" if action == "SELL" else "400",
                        },
                    ),
                    html.Span(
                        f"{pnl_pct:+.2f}%" if action == "SELL" else "—",
                        style={
                            "fontSize": "10px",
                            "color": pnl_col if action == "SELL" else TEXT_DIM,
                        },
                    ),
                ],
                style={
                    "display": "grid",
                    "gridTemplateColumns": "100px 70px 80px 80px 80px 80px",
                    "gap": "0",
                    "padding": "6px 10px",
                    "background": row_bg,
                    "borderBottom": f"1px solid {BORDER}22",
                    "alignItems": "center",
                },
            )
        )

    totals_row = html.Div(
        [
            html.Span("TOTAL", style={"fontSize": "10px", "fontWeight": "700", "color": TEXT_DIM}),
            html.Span(f"{n_trades} trades", style={"fontSize": "10px", "color": TEXT_DIM}),
            html.Span(""),
            html.Span(""),
            html.Span(
                f"{total_pnl:+.2f}",
                style={
                    "fontSize": "10px",
                    "fontWeight": "700",
                    "color": GREEN if total_pnl >= 0 else RED,
                },
            ),
            html.Span(
                f"{ret_pct:+.1f}%",
                style={
                    "fontSize": "10px",
                    "fontWeight": "700",
                    "color": GREEN if ret_pct >= 0 else RED,
                },
            ),
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "100px 70px 80px 80px 80px 80px",
            "gap": "0",
            "padding": "6px 10px",
            "borderTop": f"1px solid {BORDER}",
            "background": BG_CARD,
            "alignItems": "center",
        },
    )

    trade_table = html.Div(
        [
            html.Div(
                "TRADE LOG",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "letterSpacing": "0.18em",
                    "color": TEXT_DIM,
                    "textTransform": "uppercase",
                    "borderBottom": f"1px solid {BORDER}",
                    "paddingBottom": "6px",
                    "marginBottom": "0",
                    "padding": "10px 10px 6px",
                },
            ),
            tbl_header,
            html.Div(
                tbl_rows
                if tbl_rows
                else [
                    html.Div(
                        "No trades executed.",
                        style={
                            "color": TEXT_DIM,
                            "fontSize": "11px",
                            "fontStyle": "italic",
                            "padding": "12px 10px",
                        },
                    ),
                ]
            ),
            totals_row,
        ],
        style={
            "background": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderRadius": "4px",
            "overflow": "hidden",
            "marginTop": "16px",
        },
    )

    return html.Div([kpi_row, dcc.Graph(figure=fig, config={"displayModeBar": False}), trade_table])
