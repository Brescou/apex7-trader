"""APEX-7 — UI helpers: cards, sparklines, DB loaders, agent card builders."""

import plotly.graph_objects as go
from dash import dcc, html

from core.data import Portfolio
from agents.shared.nodes import _db_read
from dashboard.layout.classify import _classify_v2
from dashboard.server import (
    BG_CARD,
    BG_HOVER,
    BLUE,
    BORDER,
    DEATH_THRESHOLD,
    FONT,
    GRAY,
    GREEN,
    INITIAL_BALANCE,
    ORANGE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    YELLOW,
)

# ═══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _section_label(text: str) -> html.Div:
    return html.Div(
        text,
        style={
            "fontSize": "9px",
            "fontWeight": "700",
            "letterSpacing": "0.18em",
            "color": TEXT_DIM,
            "textTransform": "uppercase",
            "borderBottom": f"1px solid {BORDER}",
            "paddingBottom": "6px",
            "marginBottom": "10px",
        },
    )


def _mini_stat(label: str, value: str, color: str = TEXT_MAIN) -> html.Div:
    return html.Div(
        [
            html.Div(label, style={"fontSize": "9px", "letterSpacing": "0.1em", "color": TEXT_DIM}),
            html.Div(
                value,
                style={"fontSize": "12px", "color": color, "fontWeight": "700", "marginTop": "2px"},
            ),
        ],
        style={
            "background": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderRadius": "3px",
            "padding": "8px 10px",
        },
    )


def _log_entry_card(entry: dict) -> html.Div:
    badge, color = _classify_v2(entry["message"], entry["level"])
    t = entry["time"][11:19]
    is_dim = badge in ("CYC", "MKT", "LOG")
    has_bg = color != BORDER

    sub_items = []
    msg = entry["message"]

    reasoning = ""
    if " — " in msg and badge in ("BUY", "SELL WIN", "SELL LOSS", "HOLD"):
        parts = msg.split(" — ", 1)
        msg = parts[0]
        reasoning = parts[1]

    if reasoning:
        sub_items.append(
            html.Div(
                f"→ {reasoning[:120]}",
                style={"fontSize": "10px", "color": TEXT_DIM, "marginTop": "3px"},
            )
        )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                badge,
                                style={
                                    "fontSize": "9px",
                                    "fontWeight": "700",
                                    "letterSpacing": "0.05em",
                                    "padding": "2px 6px",
                                    "borderRadius": "2px",
                                    "background": f"{color}22" if has_bg else f"{BORDER}44",
                                    "color": color if has_bg else TEXT_DIM,
                                    "marginRight": "8px",
                                    "flexShrink": "0",
                                },
                            ),
                            html.Span(
                                msg[:140],
                                style={
                                    "color": TEXT_DIM if is_dim else TEXT_MAIN,
                                    "fontSize": "11px",
                                    "flex": "1",
                                },
                            ),
                            html.Span(
                                t,
                                style={
                                    "color": TEXT_DIM,
                                    "fontSize": "9px",
                                    "marginLeft": "auto",
                                    "flexShrink": "0",
                                },
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                    *sub_items,
                ]
            ),
        ],
        style={
            "borderLeft": f"3px solid {color if has_bg else BORDER}",
            "background": f"{color}07" if has_bg else "transparent",
            "padding": "7px 10px",
            "marginBottom": "6px",
            "borderRadius": "0 3px 3px 0",
            "opacity": "0.35" if is_dim else "1",
        },
    )


def _pos_card(sym: str, pos: dict, prices: dict) -> html.Div:
    cur = prices.get(sym, pos["avg_price"])
    pnl = ((cur / pos["avg_price"]) - 1) * 100
    val = pos["shares"] * cur
    c = GREEN if pnl >= 0 else RED
    bar_w = min(abs(pnl) / 20, 1) * 100

    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        sym, style={"fontSize": "13px", "fontWeight": "700", "color": TEXT_MAIN}
                    ),
                    html.Span(
                        f"{pnl:+.2f}%", style={"fontSize": "12px", "fontWeight": "600", "color": c}
                    ),
                ],
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "baseline",
                },
            ),
            html.Div(
                [
                    html.Span(
                        f"{pos['shares']:.4f} sh", style={"color": TEXT_DIM, "fontSize": "10px"}
                    ),
                    html.Span(f"${val:.2f}", style={"color": TEXT_MAIN, "fontSize": "11px"}),
                ],
                style={"display": "flex", "justifyContent": "space-between", "marginTop": "4px"},
            ),
            html.Div(
                [
                    html.Span(
                        f"avg ${pos['avg_price']:.2f}", style={"color": TEXT_DIM, "fontSize": "9px"}
                    ),
                    html.Span(f"→ ${cur:.2f}", style={"color": TEXT_MAIN, "fontSize": "9px"}),
                ],
                style={"display": "flex", "justifyContent": "space-between", "marginTop": "2px"},
            ),
            html.Div(
                html.Div(
                    style={
                        "width": f"{bar_w}%",
                        "height": "100%",
                        "background": c,
                        "borderRadius": "1px",
                    }
                ),
                style={
                    "height": "2px",
                    "background": f"{c}22",
                    "marginTop": "7px",
                    "borderRadius": "1px",
                    "overflow": "hidden",
                },
            ),
        ],
        style={
            "background": f"{c}04",
            "border": f"1px solid {c}18",
            "borderLeft": f"2px solid {c}",
            "borderRadius": "3px",
            "padding": "9px 11px",
            "marginBottom": "7px",
        },
    )


def _sparkline(p: Portfolio) -> go.Figure:
    vh = p.value_history
    times = [v["time"] for v in vh]
    values = [v["value"] for v in vh]
    lc = RED if p.is_dead else GREEN
    fc = "239,68,68" if p.is_dead else "16,185,129"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=times,
            y=values,
            mode="lines",
            line=dict(color=lc, width=1.5, shape="spline", smoothing=0.4),
            fill="tozeroy",
            fillcolor=f"rgba({fc},0.06)",
        )
    )
    fig.add_hline(
        y=DEATH_THRESHOLD,
        line=dict(color=RED, dash="dot", width=1),
        annotation_text=f"${DEATH_THRESHOLD} DEATH",
        annotation_position="bottom right",
        annotation_font=dict(color=RED, size=8, family=FONT),
    )
    fig.add_hline(
        y=INITIAL_BALANCE,
        line=dict(color=BORDER, dash="dot", width=1),
        annotation_text=f"${INITIAL_BALANCE} START",
        annotation_position="top right",
        annotation_font=dict(color=TEXT_DIM, size=8, family=FONT),
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=TEXT_DIM, size=9),
        margin=dict(l=46, r=12, t=6, b=26),
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            showline=False,
            tickfont=dict(size=8, color=TEXT_DIM),
            tickformat="%H:%M",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            zeroline=False,
            showline=False,
            tickprefix="$",
            tickfont=dict(size=8, color=TEXT_DIM),
        ),
        height=200,
    )
    return fig


def _make_sparkline_fig(data: list) -> go.Figure:
    """Mini 1H sparkline for watchlist rows. No axes, no legend, height=40px."""
    fig = go.Figure()
    _empty_layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        height=40,
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    if not data:
        fig.update_layout(**_empty_layout)
        return fig
    prices = [d["price"] for d in data]
    first_open = data[0].get("open", prices[0])
    color = GREEN if prices[-1] >= first_open else RED
    fig.add_trace(
        go.Scatter(
            y=prices,
            mode="lines",
            line=dict(color=color, width=1.5),
        )
    )
    fig.update_layout(**_empty_layout)
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT EVAL METRICS (LIVE specialist cards + AGENTS tab)
# ═══════════════════════════════════════════════════════════════════════════════

_AGENT_EVAL_MIN_VOTES = 5


def _agent_eval_metrics(agent_rows: list[dict]) -> dict[str, int | float | bool]:
    """Votes évalués, win rate et flag calibration pour un agent (lignes agent_memory)."""
    total = len(agent_rows)
    evaluated = sum(1 for r in agent_rows if r.get("was_correct") in (0, 1, True, False, "0", "1"))
    correct = sum(1 for r in agent_rows if r.get("was_correct") in (1, True, "1"))
    win_rate_pct = (correct / evaluated * 100.0) if evaluated > 0 else 0.0
    market_validated = evaluated >= _AGENT_EVAL_MIN_VOTES
    return {
        "total": total,
        "evaluated": evaluated,
        "correct": correct,
        "win_rate_pct": win_rate_pct,
        "market_validated": market_validated,
    }


def _live_agent_eval_banner(metrics: dict[str, int | float | bool]) -> html.Div:
    """Ligne compacte sous l'en-tête d'une carte agent LIVE (accuracy + badge calibration)."""
    wr = float(metrics["win_rate_pct"])
    evaluated = int(metrics["evaluated"])
    validated = bool(metrics["market_validated"])
    if validated:
        label = f"{wr:.0f}% · ✓ Market-validated"
        color = GREEN
    else:
        label = f"{wr:.0f}% · ⏳ calibrating ({evaluated}/{_AGENT_EVAL_MIN_VOTES})"
        color = ORANGE if evaluated > 0 else TEXT_DIM
    return html.Div(
        label,
        style={
            "fontSize": "9px",
            "color": color,
            "padding": "4px 0 6px",
            "borderBottom": f"1px solid {BORDER}",
            "marginBottom": "6px",
            "letterSpacing": "0.04em",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DB LOADERS
# ═══════════════════════════════════════════════════════════════════════════════


def _load_agent_memory() -> list[dict]:
    rows = _db_read(
        "SELECT id,timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source "
        "FROM agent_memory ORDER BY timestamp DESC LIMIT 1000"
    )
    cols = (
        "id",
        "timestamp",
        "agent_name",
        "symbol",
        "vote",
        "confidence",
        "was_correct",
        "lesson",
        "source",
    )
    return [dict(zip(cols, r)) for r in rows]


def _load_postmortem() -> list[dict]:
    rows = _db_read(
        "SELECT id,timestamp,symbol,buy_price,sell_price,pnl_pct,holding_hours,"
        "agents_correct,summary,source "
        "FROM postmortem ORDER BY timestamp DESC LIMIT 100"
    )
    cols = (
        "id",
        "timestamp",
        "symbol",
        "buy_price",
        "sell_price",
        "pnl_pct",
        "holding_hours",
        "agents_correct",
        "summary",
        "source",
    )
    return [dict(zip(cols, r)) for r in rows]


def _load_trades_db() -> list[dict]:
    rows = _db_read(
        "SELECT id,timestamp,symbol,action,price,amount_usd,shares,"
        "reasoning,confidence,emotion,portfolio_value_after,lesson,trace_id,source "
        "FROM trades ORDER BY timestamp DESC LIMIT 500"
    )
    cols = (
        "id",
        "timestamp",
        "symbol",
        "action",
        "price",
        "amount_usd",
        "shares",
        "reasoning",
        "confidence",
        "emotion",
        "portfolio_value_after",
        "lesson",
        "trace_id",
        "source",
    )
    return [dict(zip(cols, r)) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT CARD HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _conf_bar_inline(conf: float, color: str) -> html.Div:
    w = int(conf * 40)
    return html.Div(
        html.Div(
            style={"width": f"{w}px", "height": "100%", "background": color, "borderRadius": "1px"}
        ),
        style={
            "width": "40px",
            "height": "3px",
            "background": f"{color}22",
            "borderRadius": "1px",
            "overflow": "hidden",
            "flexShrink": "0",
        },
    )


def _action_chip(action: str) -> html.Span:
    c = {"BUY": BLUE, "SELL": RED, "HOLD": GRAY}.get(action.upper(), GRAY)
    return html.Span(
        action,
        style={
            "fontSize": "9px",
            "fontWeight": "700",
            "padding": "1px 5px",
            "borderRadius": "2px",
            "background": f"{c}22",
            "color": c,
            "marginRight": "6px",
            "flexShrink": "0",
        },
    )


def _sim_chip() -> html.Span:
    return html.Span(
        "SIM",
        style={
            "fontSize": "8px",
            "padding": "1px 4px",
            "borderRadius": "2px",
            "background": f"{ORANGE}33",
            "color": ORANGE,
            "marginLeft": "6px",
        },
    )


def _card_hdr_standard(
    icon: str,
    label: str,
    color: str,
    action: str,
    symbol: str,
    conf: float,
    is_sim: bool,
    sell_pct: float | None = None,
) -> list:
    children = [
        html.Span(
            f"{icon} {label}",
            style={
                "fontSize": "9px",
                "fontWeight": "700",
                "color": color,
                "marginRight": "10px",
                "flexShrink": "0",
            },
        ),
        _action_chip(action),
        html.Span(
            symbol or "—",
            style={
                "fontSize": "9px",
                "color": TEXT_MAIN,
                "flex": "1",
                "overflow": "hidden",
                "textOverflow": "ellipsis",
                "whiteSpace": "nowrap",
            },
        ),
    ]
    # Surface partial-exit recommendation for SELL votes (Review v5 Finding 6.3).
    if action.upper() == "SELL" and sell_pct is not None:
        try:
            sp = float(sell_pct)
        except (TypeError, ValueError):
            sp = 100.0
        if 0 < sp < 100:
            children.append(
                html.Span(
                    f"{sp:.0f}%",
                    title=f"Recommended exit: {sp:.0f}%",
                    style={
                        "fontSize": "8px",
                        "fontWeight": "700",
                        "color": RED,
                        "background": f"{RED}22",
                        "padding": "1px 4px",
                        "borderRadius": "2px",
                        "marginRight": "5px",
                        "flexShrink": "0",
                    },
                )
            )
    children.extend(
        [
            _conf_bar_inline(conf, color),
            html.Span(
                f"{conf:.0%}",
                style={
                    "fontSize": "9px",
                    "color": color,
                    "marginLeft": "5px",
                    "flexShrink": "0",
                },
            ),
        ]
    )
    if is_sim:
        children.append(_sim_chip())
    return children


def _body_style(color: str, expanded: bool) -> dict:
    return {
        "display": "block" if expanded else "none",
        "background": BG_CARD,
        "border": f"1px solid {color}18",
        "borderLeft": f"2px solid {color}",
        "borderTop": "none",
        "borderRadius": "0 0 3px 3px",
        "padding": "8px 10px",
    }


def _ind_cell(label: str, val: str, color: str = TEXT_MAIN) -> html.Div:
    return html.Div(
        [
            html.Div(
                label, style={"fontSize": "9px", "color": TEXT_DIM, "letterSpacing": "0.08em"}
            ),
            html.Div(
                val,
                style={"fontSize": "10px", "color": color, "fontWeight": "700", "marginTop": "2px"},
            ),
        ],
        style={"padding": "5px 7px", "background": f"{BLUE}08", "borderRadius": "2px"},
    )


def _tech_body_children(v: dict) -> list:
    ind = v.get("key_indicators", {})
    rsi_raw = ind.get("rsi", 50)
    macd = str(ind.get("macd", "—"))
    bb = str(ind.get("bb", "—"))
    trend = str(ind.get("trend", "—"))
    reasoning = v.get("reasoning", "")

    def _ind_color(s: str) -> str:
        sl = s.lower()
        if any(w in sl for w in ("bull", "up", "lower", "over")):
            return GREEN
        if any(w in sl for w in ("bear", "down", "upper")):
            return RED
        return TEXT_MAIN

    rsi_val = f"{float(rsi_raw):.1f}" if isinstance(rsi_raw, (int, float)) else str(rsi_raw)
    rsi_col = (
        RED
        if isinstance(rsi_raw, (int, float)) and rsi_raw < 35
        else (GREEN if isinstance(rsi_raw, (int, float)) and rsi_raw > 65 else TEXT_MAIN)
    )

    return [
        html.Div(
            reasoning,
            style={
                "fontSize": "11px",
                "color": TEXT_DIM,
                "fontStyle": "italic",
                "marginBottom": "8px",
                "lineHeight": "1.4",
            },
        ),
        html.Div(
            [
                _ind_cell("RSI", rsi_val, rsi_col),
                _ind_cell("MACD", macd, _ind_color(macd)),
                _ind_cell("BB", bb, _ind_color(bb)),
                _ind_cell("TREND", trend, _ind_color(trend)),
            ],
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "4px"},
        ),
    ]


def _sent_bar(score: float) -> html.Div:
    pct = (score + 1) / 2 * 100
    col = GREEN if score > 0.1 else (RED if score < -0.1 else GRAY)
    return html.Div(
        [
            html.Div(
                "SENTIMENT",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.1em",
                    "marginBottom": "4px",
                },
            ),
            html.Div(
                [
                    html.Div(
                        style={
                            "width": "100%",
                            "height": "100%",
                            "background": f"linear-gradient(to right, {RED}, {GRAY} 50%, {GREEN})",
                        }
                    ),
                    html.Div(
                        style={
                            "position": "absolute",
                            "top": "-3px",
                            "bottom": "-3px",
                            "left": f"{pct:.1f}%",
                            "width": "2px",
                            "background": col,
                            "borderRadius": "1px",
                            "transform": "translateX(-50%)",
                        }
                    ),
                ],
                style={
                    "position": "relative",
                    "height": "4px",
                    "borderRadius": "2px",
                    "overflow": "visible",
                    "marginBottom": "4px",
                },
            ),
            html.Div(
                f"{score:+.2f}", style={"fontSize": "10px", "color": col, "fontWeight": "700"}
            ),
        ]
    )


def _analyst_body_children(v: dict) -> list:
    reasoning = v.get("reasoning", "")
    sent_score = float(v.get("sentiment_score", 0.0))
    catalysts = v.get("catalysts", []) or []

    items: list = [
        html.Div(
            reasoning,
            style={
                "fontSize": "11px",
                "color": TEXT_DIM,
                "fontStyle": "italic",
                "marginBottom": "8px",
                "lineHeight": "1.4",
            },
        ),
        html.Div(_sent_bar(sent_score), style={"marginBottom": "7px" if catalysts else "0"}),
    ]
    for cat in catalysts[:2]:
        items.append(
            html.Div(
                f"→ {cat}",
                style={
                    "fontSize": "10px",
                    "color": TEXT_DIM,
                    "borderLeft": f"2px solid {GREEN}44",
                    "paddingLeft": "6px",
                    "marginBottom": "3px",
                },
            )
        )
    return items


def _risk_body_children(v: dict) -> list:
    reasoning = v.get("reasoning", "")
    risk_score = int(v.get("risk_score", 5))
    warnings = v.get("warnings", []) or []
    var_1d = float(v.get("var_1d", 0))
    exposure = float(v.get("portfolio_exposure_after", 0))
    score_col = GREEN if risk_score <= 3 else (ORANGE if risk_score <= 6 else RED)

    items: list = [
        html.Div(
            reasoning,
            style={
                "fontSize": "11px",
                "color": TEXT_DIM,
                "fontStyle": "italic",
                "marginBottom": "8px",
                "lineHeight": "1.4",
            },
        ),
        html.Div(
            [
                html.Div(
                    "RISK SCORE",
                    style={
                        "fontSize": "9px",
                        "color": TEXT_DIM,
                        "letterSpacing": "0.1em",
                    },
                ),
                html.Div(
                    f"{risk_score}/10",
                    style={
                        "fontSize": "22px",
                        "fontWeight": "700",
                        "color": score_col,
                        "lineHeight": "1",
                        "marginTop": "2px",
                    },
                ),
            ],
            style={"marginBottom": "7px"},
        ),
    ]
    for w in warnings:
        items.append(
            html.Div(
                f"\u26a0 {w}",
                style={
                    "fontSize": "10px",
                    "color": RED,
                    "marginBottom": "3px",
                },
            )
        )
    items.append(
        html.Div(
            [
                html.Span(
                    f"VaR 1d: ${var_1d:.0f}",
                    style={
                        "fontSize": "10px",
                        "color": TEXT_DIM,
                        "marginRight": "12px",
                    },
                ),
                html.Span(
                    f"Exposure: {exposure:.0f}%", style={"fontSize": "10px", "color": TEXT_DIM}
                ),
            ],
            style={"marginTop": "4px" if warnings else "0"},
        )
    )
    return items


def _macro_bar(score: float) -> html.Div:
    pct = (score + 1) / 2 * 100
    col = GREEN if score > 0.1 else (RED if score < -0.1 else GRAY)
    return html.Div(
        [
            html.Div(
                "MACRO SCORE",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.1em",
                    "marginBottom": "4px",
                },
            ),
            html.Div(
                [
                    html.Div(
                        style={
                            "width": "100%",
                            "height": "100%",
                            "background": f"linear-gradient(to right, {RED}, {GRAY} 50%, {GREEN})",
                        }
                    ),
                    html.Div(
                        style={
                            "position": "absolute",
                            "top": "-3px",
                            "bottom": "-3px",
                            "left": f"{pct:.1f}%",
                            "width": "2px",
                            "background": col,
                            "borderRadius": "1px",
                            "transform": "translateX(-50%)",
                        }
                    ),
                ],
                style={
                    "position": "relative",
                    "height": "4px",
                    "borderRadius": "2px",
                    "overflow": "visible",
                    "marginBottom": "4px",
                },
            ),
            html.Div(
                f"{score:+.2f}", style={"fontSize": "10px", "color": col, "fontWeight": "700"}
            ),
        ]
    )


def _macro_body_children(v: dict) -> list:
    reasoning = v.get("reasoning", "")
    macro_score = float(v.get("macro_score", 0.0))
    regime = v.get("market_regime", "transitional")
    regime_col = GREEN if regime == "risk-on" else (RED if regime == "risk-off" else ORANGE)

    return [
        html.Div(
            reasoning,
            style={
                "fontSize": "11px",
                "color": TEXT_DIM,
                "fontStyle": "italic",
                "marginBottom": "8px",
                "lineHeight": "1.4",
            },
        ),
        html.Div(_macro_bar(macro_score), style={"marginBottom": "8px"}),
        html.Span(
            regime,
            style={
                "fontSize": "9px",
                "fontWeight": "700",
                "padding": "2px 7px",
                "borderRadius": "2px",
                "background": f"{regime_col}22",
                "color": regime_col,
            },
        ),
    ]


def _arb_card_children(arb: dict) -> list:
    if not arb:
        return [
            html.Div(
                "⟳ Waiting for arbitration...",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "11px",
                    "textAlign": "center",
                    "padding": "12px 0",
                    "fontStyle": "italic",
                },
            )
        ]

    consensus = arb.get("consensus_level", "")
    cons_col = GREEN if consensus == "strong" else (YELLOW if consensus == "moderate" else RED)
    action = arb.get("action", "HOLD")
    symbol = arb.get("symbol", "")
    alloc_pct = float(arb.get("allocation_pct", 0))
    sell_pct = float(arb.get("sell_pct", 100))
    reasoning = arb.get("reasoning", "")
    dissenting = arb.get("dissenting_agents", []) or []
    thoughts = arb.get("thoughts", "")
    action_c = {"BUY": BLUE, "SELL": RED, "HOLD": GRAY}.get(action, GRAY)
    # SELL → exit %, else allocation % (BUY/HOLD).
    pct_label = "EXIT" if action == "SELL" else "ALLOC"
    pct_value = sell_pct if action == "SELL" else alloc_pct

    cons_style = {
        "fontSize": "9px",
        "fontWeight": "700",
        "padding": "2px 7px",
        "borderRadius": "2px",
        "background": f"{cons_col}22",
        "color": cons_col,
    }

    items: list = [
        html.Div(
            [
                html.Span(
                    "CONSENSUS",
                    style={
                        "fontSize": "8px",
                        "color": TEXT_DIM,
                        "letterSpacing": "0.12em",
                        "marginRight": "6px",
                    },
                ),
                html.Span(consensus.upper() if consensus else "—", style=cons_style),
            ],
            style={"display": "flex", "alignItems": "center", "marginBottom": "8px"},
        ),
        html.Div(
            [
                html.Span(
                    action,
                    style={
                        "fontSize": "12px",
                        "fontWeight": "700",
                        "color": action_c,
                        "marginRight": "8px",
                    },
                ),
                html.Span(
                    symbol or "—",
                    style={
                        "fontSize": "12px",
                        "color": TEXT_MAIN,
                        "marginRight": "8px",
                    },
                ),
                html.Span(
                    pct_label,
                    style={
                        "fontSize": "8px",
                        "color": TEXT_DIM,
                        "letterSpacing": "0.1em",
                        "marginRight": "3px",
                    },
                ),
                html.Span(
                    f"{pct_value:.0f}%",
                    style={
                        "fontSize": "10px",
                        "color": action_c if action == "SELL" else TEXT_DIM,
                        "fontWeight": "700" if action == "SELL" else "400",
                    },
                ),
            ],
            style={"display": "flex", "alignItems": "baseline", "marginBottom": "7px"},
        ),
        html.Div(
            reasoning,
            style={
                "fontSize": "11px",
                "color": TEXT_MAIN,
                "lineHeight": "1.4",
                "marginBottom": "6px" if (dissenting or thoughts) else "0",
            },
        ),
    ]
    for d in dissenting:
        items.append(
            html.Div(
                f"\u26a0 {d.upper()} disagrees",
                style={
                    "fontSize": "10px",
                    "color": ORANGE,
                    "marginBottom": "3px",
                },
            )
        )
    if thoughts:
        items.append(
            html.Div(
                f"Internal: {thoughts}",
                style={
                    "fontSize": "10px",
                    "color": TEXT_DIM,
                    "fontStyle": "italic",
                    "borderLeft": f"2px solid {GRAY}33",
                    "paddingLeft": "6px",
                    "marginTop": "5px",
                },
            )
        )
    return items


def _build_arb_card(arb: dict) -> html.Div:
    return html.Div(
        [
            _section_label("\u2696 ARBITRATION"),
            html.Div(
                _arb_card_children(arb),
                style={
                    "background": BG_HOVER,
                    "border": f"2px solid {BORDER}",
                    "borderLeft": f"2px solid {GREEN}",
                    "borderRadius": "3px",
                    "padding": "10px 12px",
                },
            ),
        ],
        style={"marginTop": "8px"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TERMINAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _fmt_volume(v) -> str:
    """Format volume as 45.2M, 1.2B, etc."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(int(v))


def _watchlist_row(sym: str, data: dict, active: bool, spark_data: list | None = None) -> html.Div:
    chg_pct = data.get("change_pct", 0.0) or 0.0
    chg_abs = data.get("change_abs", 0.0) or 0.0
    price = data.get("price", 0.0) or 0.0
    rsi = data.get("rsi_14")
    above = data.get("above_ma20", None)
    volume = data.get("volume", 0)
    sym_col = GREEN if chg_pct >= 0 else RED
    chg_col = GREEN if chg_pct >= 0 else RED

    if rsi is not None:
        try:
            rsi_f = float(rsi)
            rsi_col = RED if rsi_f > 70 else (GREEN if rsi_f < 30 else TEXT_DIM)
            rsi_el = html.Span(
                f"{rsi_f:.0f}",
                style={
                    "fontSize": "10px",
                    "fontWeight": "700",
                    "color": rsi_col,
                    "background": f"{rsi_col}22",
                    "padding": "1px 5px",
                    "borderRadius": "2px",
                },
            )
        except (TypeError, ValueError):
            rsi_el = html.Span("—", style={"color": TEXT_DIM, "fontSize": "10px"})
    else:
        rsi_el = html.Span("—", style={"color": TEXT_DIM, "fontSize": "10px"})

    if above is True:
        ma20_el = html.Span("▲", style={"color": GREEN, "fontSize": "12px"})
    elif above is False:
        ma20_el = html.Span("▼", style={"color": RED, "fontSize": "12px"})
    else:
        ma20_el = html.Span("—", style={"color": TEXT_DIM, "fontSize": "10px"})

    row_bg = f"{BLUE}08" if active else "transparent"
    row_border = f"1px solid {BLUE}44" if active else "1px solid transparent"

    return html.Div(
        [
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
            html.Span(
                sym,
                style={
                    "fontSize": "11px",
                    "fontWeight": "700",
                    "color": sym_col,
                    "width": "80px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                f"{price:.2f}",
                style={"fontSize": "11px", "color": TEXT_MAIN, "width": "80px", "flexShrink": "0"},
            ),
            html.Span(
                f"{chg_pct:+.2f}%",
                style={
                    "fontSize": "11px",
                    "color": chg_col,
                    "fontWeight": "700",
                    "width": "70px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                f"{chg_abs:+.2f}",
                style={"fontSize": "11px", "color": chg_col, "width": "70px", "flexShrink": "0"},
            ),
            html.Div(rsi_el, style={"width": "55px", "flexShrink": "0"}),
            html.Div(ma20_el, style={"width": "60px", "flexShrink": "0"}),
            html.Span(
                _fmt_volume(volume),
                style={"fontSize": "10px", "color": TEXT_DIM, "width": "80px", "flexShrink": "0"},
            ),
            html.Div(
                dcc.Graph(
                    figure=_make_sparkline_fig(spark_data or []),
                    config={"displayModeBar": False},
                    style={"height": "40px", "width": "88px"},
                ),
                style={"width": "90px", "flexShrink": "0"},
            ),
        ],
        style={
            "position": "relative",
            "display": "grid",
            "gridTemplateColumns": "80px 80px 70px 70px 55px 60px 80px 90px",
            "gap": "0",
            "padding": "7px 10px",
            "background": row_bg,
            "border": row_border,
            "borderRadius": "2px",
            "marginBottom": "2px",
            "alignItems": "center",
        },
    )
