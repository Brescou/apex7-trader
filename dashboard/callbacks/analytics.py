"""APEX-7 — Analytics tab callback."""

import csv
import io
import statistics
from collections import Counter, defaultdict
from datetime import datetime

import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update
from dash.dash_table import DataTable

from agents.shared.nodes import _db_read_at, mode_db_path
from dashboard.layout import (
    _load_agent_memory,
    _load_postmortem,
    _load_prompt_version_stats,
    _load_trades_db,
)
from market_data import fetch_comparison
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
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
    _rgba,
    app,
)


def _analytics_postmortem_section(post: list[dict]) -> html.Div:
    """Bloc « Trade postmortem » — colonnes date, symbole, entrée, sortie, P&L, leçon."""
    pm_rows = []
    for pm in post[:12]:
        pnl = float(pm.get("pnl_pct") or 0.0)
        pnl_c = GREEN if pnl >= 0 else RED
        sym = pm.get("symbol") or "—"
        ts_raw = str(pm.get("timestamp") or "")[:19]
        date_s = ts_raw[:10] if len(ts_raw) >= 10 else "—"
        try:
            bp = float(pm.get("buy_price") or 0)
            entry_s = f"{bp:.2f}" if bp > 0 else "—"
        except (TypeError, ValueError):
            entry_s = "—"
        try:
            sp = float(pm.get("sell_price") or 0)
            exit_s = f"{sp:.2f}" if sp > 0 else "—"
        except (TypeError, ValueError):
            exit_s = "—"
        summary_txt = (pm.get("summary") or "")[:160]
        sym_chip = html.Span(
            sym,
            style={
                "fontSize": "9px",
                "fontWeight": "700",
                "color": BLUE,
                "background": f"{BLUE}11",
                "border": f"1px solid {BLUE}33",
                "borderRadius": "2px",
                "padding": "2px 6px",
                "flexShrink": "0",
            },
        )
        pm_rows.append(
            html.Div(
                [
                    html.Span(
                        date_s,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_DIM,
                            "width": "86px",
                            "flexShrink": "0",
                        },
                    ),
                    sym_chip,
                    html.Span(
                        entry_s,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_MAIN,
                            "width": "56px",
                            "flexShrink": "0",
                            "textAlign": "right",
                        },
                    ),
                    html.Span(
                        exit_s,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_MAIN,
                            "width": "56px",
                            "flexShrink": "0",
                            "textAlign": "right",
                        },
                    ),
                    html.Span(
                        f"{pnl:+.1f}%",
                        style={
                            "fontSize": "11px",
                            "color": pnl_c,
                            "fontWeight": "700",
                            "width": "52px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        summary_txt,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_DIM,
                            "flex": "1",
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                            "whiteSpace": "nowrap",
                            "minWidth": "80px",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "10px",
                    "padding": "7px 12px",
                    "background": BG_CARD,
                    "border": f"1px solid {BORDER}",
                    "borderLeft": f"2px solid {pnl_c}",
                    "borderRadius": "0 3px 3px 0",
                    "marginBottom": "4px",
                },
            )
        )

    hdr = html.Div(
        [
            html.Span(
                "DATE",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "86px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                "SYM",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "72px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                "ENTRY",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "56px",
                    "flexShrink": "0",
                    "textAlign": "right",
                },
            ),
            html.Span(
                "EXIT",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "56px",
                    "flexShrink": "0",
                    "textAlign": "right",
                },
            ),
            html.Span(
                "P&L",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "52px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                "LESSON",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "flex": "1",
                    "minWidth": "80px",
                },
            ),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "gap": "10px",
            "padding": "6px 12px",
            "marginBottom": "4px",
            "borderBottom": f"1px solid {BORDER}",
        },
    )

    body = (
        pm_rows
        if pm_rows
        else [
            html.Div(
                "No post-mortem data yet.",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "11px",
                    "fontStyle": "italic",
                    "padding": "12px",
                },
            )
        ]
    )

    return html.Div(
        [
            html.Div(
                "Trade postmortem",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "letterSpacing": "0.18em",
                    "color": TEXT_DIM,
                    "textTransform": "uppercase",
                    "borderBottom": f"1px solid {BORDER}",
                    "paddingBottom": "6px",
                    "marginBottom": "10px",
                    "marginTop": "28px",
                },
            ),
            hdr,
            html.Div(body),
        ]
    )


_CSV_COLUMNS = [
    "id",
    "timestamp",
    "symbol",
    "action",
    "price",
    "amount_usd",
    "shares",
    "confidence",
    "emotion",
    "portfolio_value_after",
    "reasoning",
    "lesson",
    "trace_id",
    "source",
]


def _mode_trade_stats(mode: str) -> dict:
    """Compute headline stats for one runtime mode by reading its DB directly.

    Reads ``trades`` from ``trades.db`` / ``trades_paper.db`` regardless of the
    active mode (via ``_db_read_at``), so the panel can compare LIVE and PAPER
    side by side. Returns zeros when the DB does not exist yet.
    """
    rows = _db_read_at(
        mode_db_path(mode),
        "SELECT timestamp, symbol, action, price, shares, portfolio_value_after "
        "FROM trades ORDER BY timestamp ASC",
    )
    n_trades = len(rows)
    # Share-weighted running cost basis per symbol — a single float per
    # symbol (overwritten on every pyramided BUY, popped entirely on the
    # first SELL) mispriced pyramided positions and broke on a partial
    # sell_pct < 100 (the next SELL of the same, still-open position found
    # no matching entry left).
    open_shares: dict[str, float] = {}
    open_cost: dict[str, float] = {}
    pnls: list[float] = []
    last_value = 0.0
    for ts, symbol, action, price, shares, pv in rows:
        if pv not in (None, "", 0):
            try:
                last_value = float(pv)
            except (TypeError, ValueError):
                pass
        au = (action or "").upper()
        try:
            px = float(price)
        except (TypeError, ValueError):
            continue
        try:
            sh = float(shares or 0.0)
        except (TypeError, ValueError):
            sh = 0.0
        if au == "BUY":
            open_shares[symbol] = open_shares.get(symbol, 0.0) + sh
            open_cost[symbol] = open_cost.get(symbol, 0.0) + sh * px
        elif au == "SELL" and open_shares.get(symbol, 0.0) > 0:
            os_ = open_shares[symbol]
            oc_ = open_cost[symbol]
            avg_cost = oc_ / os_ if os_ > 0 else 0.0
            if avg_cost > 0:
                pnls.append((px - avg_cost) / avg_cost)
            sold = min(sh, os_) if sh > 0 else os_
            frac = sold / os_ if os_ > 0 else 1.0
            open_cost[symbol] = oc_ * (1 - frac)
            open_shares[symbol] = os_ - sold
            if open_shares[symbol] <= 1e-9:
                open_shares[symbol] = 0.0
                open_cost[symbol] = 0.0
    wins = sum(1 for p in pnls if p > 0)
    win_rate = (wins / len(pnls) * 100.0) if pnls else 0.0
    avg_pnl = (statistics.mean(pnls) * 100.0) if pnls else 0.0
    return {
        "n_trades": n_trades,
        "closed": len(pnls),
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "last_value": last_value,
    }


def _mode_stat_card(title: str, accent: str, stats: dict) -> html.Div:
    rows = [
        ("Portfolio", f"${stats['last_value']:.2f}" if stats["last_value"] else "—", TEXT_MAIN),
        ("Trades", str(stats["n_trades"]), TEXT_MAIN),
        ("Closed", str(stats["closed"]), TEXT_MAIN),
        (
            "Win rate",
            f"{stats['win_rate']:.1f}%",
            GREEN if stats["win_rate"] >= 50 else RED,
        ),
        (
            "Avg P&L",
            f"{stats['avg_pnl']:+.2f}%",
            GREEN if stats["avg_pnl"] >= 0 else RED,
        ),
    ]
    body = [
        html.Div(
            [
                html.Span(lbl, style={"fontSize": "10px", "color": TEXT_DIM}),
                html.Span(
                    val,
                    style={"fontSize": "12px", "fontWeight": "700", "color": col},
                ),
            ],
            style={
                "display": "flex",
                "justifyContent": "space-between",
                "padding": "5px 0",
                "borderBottom": f"1px solid {BORDER}",
            },
        )
        for lbl, val, col in rows
    ]
    return html.Div(
        [
            html.Div(
                title,
                style={
                    "fontSize": "10px",
                    "fontWeight": "700",
                    "letterSpacing": "0.14em",
                    "color": accent,
                    "marginBottom": "8px",
                },
            ),
            *body,
        ],
        style={
            "background": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderTop": f"2px solid {accent}",
            "borderRadius": "4px",
            "padding": "12px 14px",
        },
    )


def _decision_history_section(mem: list[dict]) -> html.Div:
    """Filterable/sortable replay of agent votes (``agent_memory``).

    Native Dash filtering lets the user slice by agent, symbol, vote, source,
    or date. ``was_correct`` is shown as ✓ / ✗ / ⏳ (pending evaluation).
    """
    cols = [
        {"name": c, "id": c}
        for c in ["timestamp", "agent_name", "symbol", "vote", "confidence", "result", "source"]
    ]
    data = []
    for m in mem:
        wc = m.get("was_correct")
        result = "⏳" if wc is None else ("✓" if wc else "✗")
        conf = m.get("confidence")
        data.append(
            {
                "timestamp": str(m.get("timestamp", ""))[:19],
                "agent_name": m.get("agent_name", ""),
                "symbol": m.get("symbol", ""),
                "vote": m.get("vote", ""),
                "confidence": f"{float(conf):.0%}" if isinstance(conf, (int, float)) else "",
                "result": result,
                "source": m.get("source", ""),
            }
        )

    table = DataTable(
        columns=cols,
        data=data,
        page_size=15,
        sort_action="native",
        filter_action="native",
        style_table={
            "background": BG_DEEP,
            "border": f"1px solid {BORDER}",
            "borderRadius": "4px",
            "overflowX": "auto",
        },
        style_header={
            "background": BG_CARD,
            "color": PURPLE,
            "fontSize": "10px",
            "fontFamily": FONT,
            "fontWeight": "700",
            "letterSpacing": "0.1em",
            "border": f"1px solid {BORDER}",
        },
        style_cell={
            "background": BG_DEEP,
            "color": TEXT_MAIN,
            "fontSize": "11px",
            "fontFamily": FONT,
            "borderBottom": f"1px solid {BORDER}",
            "padding": "6px 10px",
            "textAlign": "left",
        },
        style_data_conditional=[
            {"if": {"filter_query": '{vote} = "BUY"'}, "background": f"{BLUE}12"},
            {"if": {"filter_query": '{vote} = "SELL"'}, "background": f"{RED}12"},
            {"if": {"filter_query": '{result} = "✓"'}, "color": GREEN},
            {"if": {"filter_query": '{result} = "✗"'}, "color": RED},
        ],
    )

    return html.Div(
        [
            html.Div(
                "Decision history",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "letterSpacing": "0.18em",
                    "color": TEXT_DIM,
                    "textTransform": "uppercase",
                    "borderBottom": f"1px solid {BORDER}",
                    "paddingBottom": "6px",
                    "marginBottom": "10px",
                    "marginTop": "28px",
                },
            ),
            table,
        ]
    )


# Below this many evaluated trades, win-rate differences between prompt
# versions are statistical noise — the card shows a warning chip instead of
# letting a 3-trade sample look like a verdict.
_AB_MIN_EVALUATED = 30

_AB_ACCENTS = [GREEN, BLUE, PURPLE, ORANGE, YELLOW]


def _prompt_version_card(stats: dict, accent: str) -> html.Div:
    """One card per prompt version — volumes, confidence, validated win rate."""
    evaluated = int(stats.get("evaluated") or 0)
    wins = int(stats.get("wins") or 0)
    win_rate = (wins / evaluated * 100.0) if evaluated else None
    conf = stats.get("avg_confidence")
    first = str(stats.get("first_trade") or "")[:10]
    last = str(stats.get("last_trade") or "")[:10]
    period = f"{first} → {last}" if first else "—"

    rows = [
        ("Trades", f"{stats['n_trades']} ({stats['buys']}B / {stats['sells']}S)", TEXT_MAIN),
        ("Avg confidence", f"{float(conf):.0%}" if conf is not None else "—", TEXT_MAIN),
        ("Evaluated", str(evaluated), TEXT_MAIN),
        (
            "Validated win rate",
            f"{win_rate:.1f}%" if win_rate is not None else "⏳",
            (GREEN if win_rate >= 50 else RED) if win_rate is not None else TEXT_DIM,
        ),
        ("Period", period, TEXT_DIM),
    ]
    body = [
        html.Div(
            [
                html.Span(lbl, style={"fontSize": "10px", "color": TEXT_DIM}),
                html.Span(val, style={"fontSize": "12px", "fontWeight": "700", "color": col}),
            ],
            style={
                "display": "flex",
                "justifyContent": "space-between",
                "padding": "5px 0",
                "borderBottom": f"1px solid {BORDER}",
            },
        )
        for lbl, val, col in rows
    ]
    children = [
        html.Div(
            str(stats.get("version") or "—"),
            style={
                "fontSize": "10px",
                "fontWeight": "700",
                "letterSpacing": "0.14em",
                "color": accent,
                "marginBottom": "8px",
            },
        ),
        *body,
    ]
    if evaluated < _AB_MIN_EVALUATED:
        children.append(
            html.Div(
                f"⚠ n = {evaluated} < {_AB_MIN_EVALUATED} — non significatif",
                style={
                    "fontSize": "9px",
                    "color": ORANGE,
                    "marginTop": "8px",
                    "letterSpacing": "0.06em",
                },
            )
        )
    return html.Div(
        children,
        style={
            "background": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderTop": f"2px solid {accent}",
            "borderRadius": "4px",
            "padding": "12px 14px",
        },
    )


def _prompt_versions_section() -> html.Div:
    """A/B prompt comparison — outcome stats grouped by ``prompt_version``.

    Every trade persists the ``PROMPT_VERSION`` active when it was taken, so
    bumping it in ``agents/shared/prompts.py`` after a prompt change starts a
    new comparable series in the same DB. The win rate shown is the
    market-validated ``was_correct`` share resolved by
    ``evaluate_pending_trades`` — not the arbitration consensus.
    """
    stats = _load_prompt_version_stats()
    if not stats:
        body: list = [
            html.Div(
                "No prompt-version data yet.",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "11px",
                    "fontStyle": "italic",
                    "padding": "12px",
                },
            )
        ]
    else:
        cards = [
            _prompt_version_card(s, _AB_ACCENTS[i % len(_AB_ACCENTS)]) for i, s in enumerate(stats)
        ]
        body = [
            html.Div(
                cards,
                style={
                    "display": "grid",
                    "gridTemplateColumns": f"repeat({min(len(cards), 4)}, 1fr)",
                    "gap": "12px",
                },
            )
        ]
        if len(stats) == 1:
            body.append(
                html.Div(
                    "Une seule version en base — bump PROMPT_VERSION dans "
                    "agents/shared/prompts.py après un changement de prompt "
                    "pour démarrer une série comparable.",
                    style={"fontSize": "10px", "color": TEXT_DIM, "marginTop": "8px"},
                )
            )

    return html.Div(
        [
            html.Div(
                "Prompt versions (A/B)",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "letterSpacing": "0.18em",
                    "color": TEXT_DIM,
                    "textTransform": "uppercase",
                    "borderBottom": f"1px solid {BORDER}",
                    "paddingBottom": "6px",
                    "marginBottom": "10px",
                    "marginTop": "28px",
                },
            ),
            *body,
        ]
    )


def _live_paper_comparison_section() -> html.Div:
    """Side-by-side LIVE vs PAPER headline stats (reads both DBs directly)."""
    live = _mode_trade_stats("live")
    paper = _mode_trade_stats("paper")
    return html.Div(
        [
            html.Div(
                "Live vs Paper",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "letterSpacing": "0.18em",
                    "color": TEXT_DIM,
                    "textTransform": "uppercase",
                    "borderBottom": f"1px solid {BORDER}",
                    "paddingBottom": "6px",
                    "marginBottom": "10px",
                    "marginTop": "28px",
                },
            ),
            html.Div(
                [
                    _mode_stat_card("LIVE", GREEN, live),
                    _mode_stat_card("PAPER", BLUE, paper),
                ],
                style={
                    "display": "grid",
                    "gridTemplateColumns": "1fr 1fr",
                    "gap": "12px",
                },
            ),
        ]
    )


@app.callback(
    Output("analytics-csv-download", "data"),
    Input("btn-analytics-export", "n_clicks"),
    prevent_initial_call=True,
)
def _export_trades_csv(_n):
    """Export the full trade history (current DB / mode) as a CSV download."""
    trades = _load_trades_db()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for t in trades:
        writer.writerow({k: t.get(k, "") for k in _CSV_COLUMNS})
    fname = f"apex7_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return dcc.send_string(buf.getvalue(), fname)


def _equity_benchmark_figure(trades: list[dict], theme: dict) -> go.Figure:
    """Equity curve from ``portfolio_value_after`` with an SPY benchmark overlay.

    The SPY series (normalized-to-100 by ``fetch_comparison``) is rescaled to
    the portfolio's starting value so both lines start at the same level. SPY
    is fetched fail-silent — if unavailable (offline / yfinance error) only the
    equity curve is drawn.
    """
    pts = [
        (str(t.get("timestamp"))[:19], float(t["portfolio_value_after"]))
        for t in sorted(trades, key=lambda x: str(x.get("timestamp", "")))
        if t.get("portfolio_value_after") not in (None, "", 0)
    ]
    fig = go.Figure()
    if not pts:
        fig.update_layout(title="Equity Curve vs SPY", height=260, **theme)
        return fig

    eq_x = [p[0] for p in pts]
    eq_y = [p[1] for p in pts]
    base = eq_y[0]

    fig.add_trace(
        go.Scatter(
            x=eq_x,
            y=eq_y,
            mode="lines",
            name="APEX-7",
            line=dict(color=GREEN, width=1.8),
            fill="tozeroy",
            fillcolor=_rgba(GREEN, 0.08),
        )
    )

    try:
        spy = fetch_comparison(["SPY"], period="3mo").get("SPY", [])
    except Exception:
        spy = []
    if spy and base > 0:
        spy_x = [d["date"] for d in spy]
        spy_y = [d["value"] / 100.0 * base for d in spy]
        fig.add_trace(
            go.Scatter(
                x=spy_x,
                y=spy_y,
                mode="lines",
                name="SPY (rescaled)",
                line=dict(color=BLUE, width=1.4, dash="dot"),
            )
        )

    fig.update_layout(
        title="Equity Curve vs SPY",
        height=260,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        **theme,
    )
    return fig


@app.callback(
    Output("analytics-content", "children"),
    [Input("analytics-tick", "n_intervals"), Input("btn-analytics-refresh", "n_clicks")],
    State("main-tabs", "value"),
    prevent_initial_call=False,
)
def _analytics_refresh(_, __, active_tab):
    if active_tab != "analytics":
        return no_update
    trades = _load_trades_db()
    post = _load_postmortem()
    pm_section = _analytics_postmortem_section(post)
    compare_section = _live_paper_comparison_section()
    prompt_section = _prompt_versions_section()
    history_section = _decision_history_section(_load_agent_memory())

    if not trades:
        return html.Div(
            [
                html.Div(
                    "No trade data yet. Run the agent first.",
                    style={"color": TEXT_DIM, "fontSize": "12px", "padding": "20px"},
                ),
                compare_section,
                prompt_section,
                history_section,
                pm_section,
            ],
            style={"display": "flex", "flexDirection": "column"},
        )

    # ── KPIs ─────────────────────────────────────────────────────────────────
    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    total = len(trades)

    # Win rate: for each SELL, find the most recent prior BUY of the same symbol
    pnl_vals: list[float] = []
    ticker_pnl: dict[str, float] = defaultdict(float)
    for s in sells:
        sym = s.get("symbol")
        sell_price = s.get("price", 0.0)
        sell_ts = s.get("timestamp", "")
        prior_buys = [
            b for b in buys if b.get("symbol") == sym and b.get("timestamp", "") <= sell_ts
        ]
        if prior_buys and sell_price > 0:
            # _load_trades_db() orders rows DESC (most recent first), so
            # prior_buys[0] is the most recent BUY before this SELL —
            # prior_buys[-1] would be the OLDEST BUY of the symbol's whole
            # history instead, mispairing every SELL against the wrong entry.
            buy_price = prior_buys[0].get("price", sell_price)
            if buy_price > 0:
                pnl_vals.append((sell_price - buy_price) / buy_price)
                # Real dollar P&L (shares sold x price delta) — reuses the
                # same buy/sell pairing above. "P&L by Ticker" used to sum
                # each SELL's gross amount_usd (cash received, always
                # positive) instead of gain/loss, so a losing trade always
                # rendered as a green bar (Review Finding).
                shares_sold = float(s.get("shares", 0) or 0)
                ticker_pnl[sym or "UNK"] += shares_sold * (sell_price - buy_price)
    wins = sum(1 for p in pnl_vals if p > 0)
    win_rate = (wins / len(pnl_vals) * 100) if pnl_vals else 0.0
    avg_pnl = statistics.mean(pnl_vals) * 100 if pnl_vals else 0.0
    best_t = max(pnl_vals) if pnl_vals else 0.0
    worst_t = min(pnl_vals) if pnl_vals else 0.0
    confs = [t.get("confidence", 0) for t in trades if t.get("confidence")]
    avg_conf = statistics.mean(confs) if confs else 0.0

    tickers = [t["symbol"] for t in trades if t.get("symbol")]
    fav = max(set(tickers), key=tickers.count) if tickers else "—"

    live_n = sum(1 for t in trades if t.get("source") == "live")
    sim_n = sum(1 for t in trades if t.get("source") == "simulation")
    ratio = f"{sim_n}/{live_n}" if (sim_n + live_n) > 0 else "—"

    kpi_items = [
        ("WIN RATE", f"{win_rate:.1f}%", GREEN if win_rate > 50 else RED),
        ("AVG P&L", f"{avg_pnl:+.2f}%", GREEN if avg_pnl >= 0 else RED),
        ("BEST TRADE", f"{best_t * 100:+.2f}%", GREEN),
        ("WORST TRADE", f"{worst_t * 100:+.2f}%", RED),
        ("TOTAL TRADES", str(total), BLUE),
        ("AVG CONFIDENCE", f"{avg_conf:.0%}", PURPLE),
        ("FAV TICKER", fav, YELLOW),
        ("SIM / LIVE", ratio, ORANGE),
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
            for lbl, val, col in kpi_items
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(8, 1fr)",
            "gap": "8px",
            "marginBottom": "20px",
        },
    )

    # ── CHARTS ───────────────────────────────────────────────────────────────
    _plotly_theme = dict(
        template="plotly_dark",
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=40, r=20, t=30, b=40),
    )

    # 1. P&L by ticker (bar) — ticker_pnl (real gain/loss) computed above,
    # alongside pnl_vals, from the same buy/sell pairing.
    sorted_tickers = sorted(ticker_pnl.items(), key=lambda x: x[1])
    bar_colors = [GREEN if v >= 0 else RED for _, v in sorted_tickers]
    fig1 = go.Figure(
        go.Bar(
            x=[v for _, v in sorted_tickers],
            y=[s for s, _ in sorted_tickers],
            orientation="h",
            marker_color=bar_colors,
        )
    )
    fig1.update_layout(title="P&L by Ticker", height=250, **_plotly_theme)

    # 2. Action distribution (donut)
    action_counts = {
        "BUY": len(buys),
        "SELL": len(sells),
        "HOLD": sum(1 for t in trades if t["action"] == "HOLD"),
    }
    fig2 = go.Figure(
        go.Pie(
            labels=list(action_counts.keys()),
            values=list(action_counts.values()),
            hole=0.6,
            marker_colors=[BLUE, GREEN, GRAY],
            textfont=dict(family=FONT, size=10),
        )
    )
    fig2.update_layout(title="Action Distribution", height=250, **_plotly_theme)

    # 3. Confidence over time (line)
    conf_trades = [t for t in reversed(trades) if t.get("confidence")]
    fig3 = go.Figure(
        go.Scatter(
            x=list(range(len(conf_trades))),
            y=[t["confidence"] for t in conf_trades],
            mode="lines",
            line=dict(color=PURPLE, width=1.5),
            fill="tozeroy",
            fillcolor=_rgba(PURPLE, 0.09),
        )
    )
    fig3.update_layout(title="Confidence Over Time", height=250, **_plotly_theme)

    # 4. Trades by hour
    hours = Counter()
    for t in trades:
        try:
            h = int(t["timestamp"][11:13])
            hours[h] += 1
        except Exception:
            pass
    hour_x = list(range(24))
    hour_y = [hours.get(h, 0) for h in hour_x]
    fig4 = go.Figure(go.Bar(x=hour_x, y=hour_y, marker_color=BLUE))
    fig4.update_layout(title="Trades by Hour", height=250, **_plotly_theme)

    equity_fig = _equity_benchmark_figure(trades, _plotly_theme)
    equity_row = html.Div(
        dcc.Graph(figure=equity_fig, config={"displayModeBar": False}),
        style={"marginBottom": "12px"},
    )

    charts_row = html.Div(
        [
            dcc.Graph(figure=fig1, config={"displayModeBar": False}),
            dcc.Graph(figure=fig2, config={"displayModeBar": False}),
            dcc.Graph(figure=fig3, config={"displayModeBar": False}),
            dcc.Graph(figure=fig4, config={"displayModeBar": False}),
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "1fr 1fr",
            "gap": "12px",
            "marginBottom": "20px",
        },
    )

    # ── DATA TABLE ───────────────────────────────────────────────────────────
    table_cols = [
        {"name": c, "id": c}
        for c in [
            "timestamp",
            "symbol",
            "action",
            "price",
            "amount_usd",
            "confidence",
            "emotion",
            "lesson",
            "source",
        ]
    ]
    table_data = []
    for t in trades:
        row = {
            k: t.get(k, "")
            for k in [
                "timestamp",
                "symbol",
                "action",
                "price",
                "amount_usd",
                "confidence",
                "emotion",
                "lesson",
                "source",
            ]
        }
        row["timestamp"] = str(row["timestamp"])[:19]
        row["price"] = f"{row['price']:.2f}" if isinstance(row["price"], float) else row["price"]
        row["amount_usd"] = (
            f"{row['amount_usd']:.2f}"
            if isinstance(row["amount_usd"], float)
            else row["amount_usd"]
        )
        row["confidence"] = (
            f"{row['confidence']:.0%}"
            if isinstance(row["confidence"], float)
            else row["confidence"]
        )
        table_data.append(row)

    data_table = DataTable(
        columns=table_cols,
        data=table_data,
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_table={
            "background": BG_DEEP,
            "border": f"1px solid {BORDER}",
            "borderRadius": "4px",
            "overflowX": "auto",
        },
        style_header={
            "background": BG_CARD,
            "color": GREEN,
            "fontSize": "10px",
            "fontFamily": FONT,
            "fontWeight": "700",
            "letterSpacing": "0.1em",
            "border": f"1px solid {BORDER}",
        },
        style_cell={
            "background": BG_DEEP,
            "color": TEXT_MAIN,
            "fontSize": "11px",
            "fontFamily": FONT,
            "borderBottom": f"1px solid {BORDER}",
            "padding": "6px 10px",
            "whiteSpace": "normal",
            "textOverflow": "ellipsis",
            "maxWidth": "200px",
        },
        style_data_conditional=[
            {"if": {"filter_query": '{action} = "BUY"'}, "background": f"{BLUE}12"},
            {"if": {"filter_query": '{action} = "SELL"'}, "background": f"{RED}12"},
            {"if": {"filter_query": '{source} = "simulation"'}, "opacity": "0.7"},
        ],
    )

    return html.Div(
        [
            kpi_row,
            equity_row,
            charts_row,
            data_table,
            compare_section,
            prompt_section,
            history_section,
            pm_section,
        ]
    )
