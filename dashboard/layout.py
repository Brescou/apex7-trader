"""APEX-7 — UI helpers, tab layouts, and app.layout assignment."""

import sqlite3

import plotly.graph_objects as go
from dash import dcc, html

from dashboard.controller import _state
from dashboard.server import (
    AGENT_GRAPH,
    BG_CARD,
    BG_DEEP,
    BG_HOVER,
    BLUE,
    BORDER,
    DB_PATH,
    DEATH_THRESHOLD,
    FONT,
    GRAY,
    GREEN,
    INITIAL_BALANCE,
    ORANGE,
    PURPLE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    WATCHLIST,
    YELLOW,
    app,
)
from agents.shared.nodes import get_simulation_mode
from core.data import Portfolio

# ═══════════════════════════════════════════════════════════════════════════════
# EMOTION SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

_EMOTIONS: dict[str, dict] = {
    "EUPHORIC": {"icon": "🚀", "color": GREEN, "quote": "To the moon. Nothing can stop us now."},
    "EXCITED": {"icon": "🔥", "color": GREEN, "quote": "Momentum building. Stay aggressive."},
    "FOCUSED": {"icon": "🎯", "color": BLUE, "quote": "Executing the plan. Steady hands."},
    "CALM": {"icon": "😐", "color": GRAY, "quote": "Patience. The market reveals itself."},
    "NERVOUS": {"icon": "😰", "color": YELLOW, "quote": "Risk elevated. Reduce exposure now."},
    "PANIC": {"icon": "🚨", "color": RED, "quote": "Capital preservation. Cut losses NOW."},
    "DESPERATE": {"icon": "💀", "color": RED, "quote": "One trade left. Make it count."},
}


def _emotion(total: float) -> str:
    r = total / INITIAL_BALANCE
    if r >= 1.5:
        return "EUPHORIC"
    if r >= 1.2:
        return "EXCITED"
    if r >= 0.9:
        return "FOCUSED"
    if r >= 0.7:
        return "CALM"
    if r >= 0.5:
        return "NERVOUS"
    if r >= 0.2:
        return "PANIC"
    return "DESPERATE"


def _thinking(p: Portfolio) -> bool:
    return _state.get("thinking", False)


def _cycle(p: Portfolio) -> int:
    for e in reversed(p.agent_log):
        if "=== CYCLE" in e["message"] and "START" in e["message"]:
            try:
                return int(e["message"].split("CYCLE")[1].split("START")[0].strip())
            except Exception:
                pass
    return 0


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


def _classify_v2(msg: str, level: str) -> tuple[str, str]:
    """Returns (badge_label, color) with proper sell coloring based on profit."""
    if level == "critical":
        return "DEATH", "#ff2020"
    if level == "error":
        return "ERR", ORANGE
    if level == "warning":
        return "WARN", YELLOW
    if msg.startswith("BUY "):
        return "BUY", BLUE
    if msg.startswith("SELL "):
        return ("SELL WIN", GREEN) if "+" in msg else ("SELL LOSS", RED)
    if msg.startswith("HOLD "):
        return "HOLD", GRAY
    if msg.startswith("Skip "):
        return "SKIP", YELLOW
    if "Anthropic" in msg or "web search" in msg:
        return "AI", PURPLE
    if msg.startswith("Analysis:"):
        return "INTEL", PURPLE
    if msg.startswith("[SIM][TECH]") or msg.startswith("technician:"):
        return "TECH", BLUE
    if msg.startswith("[SIM][ANLST]") or msg.startswith("analyst:"):
        return "ANLST", "#06b6d4"
    if msg.startswith("[SIM][RISK]") or msg.startswith("risk_manager:"):
        return "RISK", RED
    if msg.startswith("[SIM][MACRO]") or msg.startswith("macro_watcher:"):
        return "MACRO", YELLOW
    if msg.startswith("supervisor:"):
        return "SUPV", PURPLE
    if msg.startswith("arbitrate:"):
        return "ARBIT", GREEN
    if msg.startswith("[SIM]"):
        return "SIM", ORANGE
    if msg.startswith("=== CYCLE"):
        return "CYC", BORDER
    if msg.startswith(("Fetching", "Prices")):
        return "MKT", BORDER
    return "LOG", BORDER


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


def _load_agent_memory() -> list[dict]:
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT id,timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source "
            "FROM agent_memory ORDER BY timestamp DESC LIMIT 1000"
        ).fetchall()
        con.close()
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
    except Exception:
        return []


def _load_postmortem() -> list[dict]:
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT id,timestamp,symbol,buy_price,sell_price,pnl_pct,holding_hours,"
            "agents_correct,summary,source "
            "FROM postmortem ORDER BY timestamp DESC LIMIT 100"
        ).fetchall()
        con.close()
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
    except Exception:
        return []


def _load_trades_db() -> list[dict]:
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT id,timestamp,symbol,action,price,amount_usd,shares,"
            "reasoning,confidence,emotion,portfolio_value_after,lesson,source "
            "FROM trades ORDER BY timestamp DESC LIMIT 500"
        ).fetchall()
        con.close()
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
            "source",
        )
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []


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
    icon: str, label: str, color: str, action: str, symbol: str, conf: float, is_sim: bool
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
    reasoning = arb.get("reasoning", "")
    dissenting = arb.get("dissenting_agents", []) or []
    thoughts = arb.get("thoughts", "")
    action_c = {"BUY": BLUE, "SELL": RED, "HOLD": GRAY}.get(action, GRAY)

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
                html.Span(f"{alloc_pct:.0f}%", style={"fontSize": "10px", "color": TEXT_DIM}),
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


# ═══════════════════════════════════════════════════════════════════════════════
# TAB CONTENT LAYOUTS (static skeletons — filled by callbacks)
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_live() -> html.Div:
    return html.Div(
        [
            # Left column
            html.Div(
                [
                    html.Div(id="sec-portfolio", style={"padding": "16px 14px 0"}),
                    html.Div(id="sec-emotion", style={"padding": "0 14px 12px"}),
                    html.Div(id="sec-graph", style={"padding": "0 14px 12px"}),
                    # ── AGENT CARDS PANEL (multi-agent mode) ─────────────────────
                    html.Div(
                        [
                            # TECHNICIAN
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Div(
                                                id="card-tech-hdr",
                                                style={
                                                    "display": "flex",
                                                    "alignItems": "center",
                                                    "flex": "1",
                                                    "overflow": "hidden",
                                                },
                                            ),
                                            html.Button(
                                                "▼ Reasoning",
                                                id={"type": "reasoning-toggle", "index": "tech"},
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": "none",
                                                    "color": TEXT_DIM,
                                                    "fontFamily": FONT,
                                                    "fontSize": "9px",
                                                    "cursor": "pointer",
                                                    "letterSpacing": "0.05em",
                                                    "flexShrink": "0",
                                                    "padding": "0 0 0 8px",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "alignItems": "center",
                                            "background": f"{BLUE}0a",
                                            "border": f"1px solid {BLUE}22",
                                            "borderLeft": f"2px solid {BLUE}",
                                            "borderRadius": "3px",
                                            "padding": "7px 9px",
                                        },
                                    ),
                                    html.Div(
                                        html.Div(
                                            id="card-tech-body",
                                            style={
                                                "background": BG_CARD,
                                                "border": f"1px solid {BLUE}18",
                                                "borderLeft": f"2px solid {BLUE}",
                                                "borderTop": "none",
                                                "borderRadius": "0 0 3px 3px",
                                                "padding": "8px 10px",
                                            },
                                        ),
                                        id={"type": "reasoning-collapse", "index": "tech"},
                                        style={"display": "none"},
                                    ),
                                ],
                                style={"marginBottom": "5px"},
                            ),
                            # ANALYST
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Div(
                                                id="card-analyst-hdr",
                                                style={
                                                    "display": "flex",
                                                    "alignItems": "center",
                                                    "flex": "1",
                                                    "overflow": "hidden",
                                                },
                                            ),
                                            html.Button(
                                                "▼ Reasoning",
                                                id={"type": "reasoning-toggle", "index": "analyst"},
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": "none",
                                                    "color": TEXT_DIM,
                                                    "fontFamily": FONT,
                                                    "fontSize": "9px",
                                                    "cursor": "pointer",
                                                    "letterSpacing": "0.05em",
                                                    "flexShrink": "0",
                                                    "padding": "0 0 0 8px",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "alignItems": "center",
                                            "background": f"{GREEN}0a",
                                            "border": f"1px solid {GREEN}22",
                                            "borderLeft": f"2px solid {GREEN}",
                                            "borderRadius": "3px",
                                            "padding": "7px 9px",
                                        },
                                    ),
                                    html.Div(
                                        html.Div(
                                            id="card-analyst-body",
                                            style={
                                                "background": BG_CARD,
                                                "border": f"1px solid {GREEN}18",
                                                "borderLeft": f"2px solid {GREEN}",
                                                "borderTop": "none",
                                                "borderRadius": "0 0 3px 3px",
                                                "padding": "8px 10px",
                                            },
                                        ),
                                        id={"type": "reasoning-collapse", "index": "analyst"},
                                        style={"display": "none"},
                                    ),
                                ],
                                style={"marginBottom": "5px"},
                            ),
                            # RISK MANAGER
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Div(
                                                id="card-risk-hdr",
                                                style={
                                                    "display": "flex",
                                                    "alignItems": "center",
                                                    "flex": "1",
                                                    "overflow": "hidden",
                                                },
                                            ),
                                            html.Button(
                                                "▼ Reasoning",
                                                id={"type": "reasoning-toggle", "index": "risk"},
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": "none",
                                                    "color": TEXT_DIM,
                                                    "fontFamily": FONT,
                                                    "fontSize": "9px",
                                                    "cursor": "pointer",
                                                    "letterSpacing": "0.05em",
                                                    "flexShrink": "0",
                                                    "padding": "0 0 0 8px",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "alignItems": "center",
                                            "background": f"{ORANGE}0a",
                                            "border": f"1px solid {ORANGE}22",
                                            "borderLeft": f"2px solid {ORANGE}",
                                            "borderRadius": "3px",
                                            "padding": "7px 9px",
                                        },
                                    ),
                                    html.Div(
                                        html.Div(
                                            id="card-risk-body",
                                            style={
                                                "background": BG_CARD,
                                                "border": f"1px solid {ORANGE}18",
                                                "borderLeft": f"2px solid {ORANGE}",
                                                "borderTop": "none",
                                                "borderRadius": "0 0 3px 3px",
                                                "padding": "8px 10px",
                                            },
                                        ),
                                        id={"type": "reasoning-collapse", "index": "risk"},
                                        style={"display": "none"},
                                    ),
                                ],
                                style={"marginBottom": "5px"},
                            ),
                            # MACRO WATCHER
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Div(
                                                id="card-macro-hdr",
                                                style={
                                                    "display": "flex",
                                                    "alignItems": "center",
                                                    "flex": "1",
                                                    "overflow": "hidden",
                                                },
                                            ),
                                            html.Button(
                                                "▼ Reasoning",
                                                id={"type": "reasoning-toggle", "index": "macro"},
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": "none",
                                                    "color": TEXT_DIM,
                                                    "fontFamily": FONT,
                                                    "fontSize": "9px",
                                                    "cursor": "pointer",
                                                    "letterSpacing": "0.05em",
                                                    "flexShrink": "0",
                                                    "padding": "0 0 0 8px",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "alignItems": "center",
                                            "background": f"{PURPLE}0a",
                                            "border": f"1px solid {PURPLE}22",
                                            "borderLeft": f"2px solid {PURPLE}",
                                            "borderRadius": "3px",
                                            "padding": "7px 9px",
                                        },
                                    ),
                                    html.Div(
                                        html.Div(
                                            id="card-macro-body",
                                            style={
                                                "background": BG_CARD,
                                                "border": f"1px solid {PURPLE}18",
                                                "borderLeft": f"2px solid {PURPLE}",
                                                "borderTop": "none",
                                                "borderRadius": "0 0 3px 3px",
                                                "padding": "8px 10px",
                                            },
                                        ),
                                        id={"type": "reasoning-collapse", "index": "macro"},
                                        style={"display": "none"},
                                    ),
                                ],
                                style={"marginBottom": "5px"},
                            ),
                            # ARBITRATION — always visible
                            html.Div(id="card-arb"),
                        ],
                        id="sec-agent-cards",
                        style={"padding": "0 14px 12px"},
                    ),
                    html.Div(id="live-track-records", style={"padding": "0 14px 8px"}),
                    html.Div(id="sec-stats", style={"padding": "0 14px 12px"}),
                    html.Div(id="sec-positions", style={"padding": "0 14px 12px"}),
                ],
                style={
                    "width": "280px",
                    "minWidth": "280px",
                    "flexShrink": "0",
                    "borderRight": f"1px solid {BORDER}",
                    "overflowY": "auto",
                    "height": "100%",
                },
            ),
            # Right column
            html.Div(
                [
                    # Equity curve
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span(
                                                "EQUITY CURVE",
                                                style={
                                                    "fontSize": "9px",
                                                    "fontWeight": "700",
                                                    "letterSpacing": "0.18em",
                                                    "color": TEXT_DIM,
                                                },
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        id="chart-vals", style={"display": "flex", "gap": "18px"}
                                    ),
                                ],
                                style={
                                    "display": "flex",
                                    "justifyContent": "space-between",
                                    "alignItems": "center",
                                    "marginBottom": "4px",
                                },
                            ),
                            dcc.Graph(
                                id="sparkline",
                                config={"displayModeBar": False},
                                style={"height": "200px"},
                            ),
                        ],
                        style={
                            "padding": "14px 16px 0",
                            "borderBottom": f"1px solid {BORDER}",
                            "flexShrink": "0",
                        },
                    ),
                    # Activity log
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span(
                                        "ACTIVITY LOG",
                                        style={
                                            "fontSize": "9px",
                                            "fontWeight": "700",
                                            "letterSpacing": "0.18em",
                                            "color": TEXT_DIM,
                                        },
                                    ),
                                    html.Span(
                                        "NEWEST FIRST",
                                        style={
                                            "fontSize": "8px",
                                            "color": TEXT_DIM,
                                            "letterSpacing": "0.1em",
                                            "opacity": "0.5",
                                        },
                                    ),
                                ],
                                style={
                                    "display": "flex",
                                    "justifyContent": "space-between",
                                    "padding": "10px 14px 8px",
                                    "borderBottom": f"1px solid {BORDER}",
                                },
                            ),
                            html.Div(
                                id="activity-log",
                                style={
                                    "flex": "1",
                                    "overflowY": "auto",
                                    "padding": "8px 14px",
                                    "display": "flex",
                                    "flexDirection": "column",
                                },
                            ),
                        ],
                        style={
                            "flex": "1",
                            "display": "flex",
                            "flexDirection": "column",
                            "minHeight": "0",
                        },
                    ),
                ],
                style={
                    "flex": "1",
                    "minWidth": "0",
                    "display": "flex",
                    "flexDirection": "column",
                    "height": "100%",
                },
            ),
        ],
        style={
            "display": "flex",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


def _tab_analytics() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        "⟳ REFRESH",
                        id="btn-analytics-refresh",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {BORDER}",
                            "color": TEXT_DIM,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "4px 12px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                ],
                style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER}"},
            ),
            html.Div(
                id="analytics-content",
                style={
                    "flex": "1",
                    "overflowY": "auto",
                    "padding": "16px",
                },
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


def _tab_backtest() -> html.Div:
    _input_style = {
        "background": BG_DEEP,
        "border": f"1px solid {BORDER}",
        "color": TEXT_MAIN,
        "fontFamily": FONT,
        "fontSize": "11px",
        "padding": "5px 9px",
        "borderRadius": "3px",
        "outline": "none",
        "width": "100px",
    }
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                "SYMBOL",
                                style={
                                    "fontSize": "9px",
                                    "color": TEXT_DIM,
                                    "letterSpacing": "0.1em",
                                    "marginBottom": "3px",
                                },
                            ),
                            dcc.Input(
                                id="backtest-symbol",
                                type="text",
                                placeholder="AAPL",
                                value="AAPL",
                                debounce=True,
                                style=_input_style,
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Div(
                                "PERIOD",
                                style={
                                    "fontSize": "9px",
                                    "color": TEXT_DIM,
                                    "letterSpacing": "0.1em",
                                    "marginBottom": "3px",
                                },
                            ),
                            dcc.Dropdown(
                                id="backtest-period",
                                options=[
                                    {"label": p, "value": p} for p in ["1mo", "3mo", "6mo", "1y"]
                                ],
                                value="6mo",
                                clearable=False,
                                style={
                                    "width": "100px",
                                    "background": BG_CARD,
                                    "color": TEXT_MAIN,
                                    "fontFamily": FONT,
                                    "fontSize": "11px",
                                },
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Div(
                                "STRATEGY",
                                style={
                                    "fontSize": "9px",
                                    "color": TEXT_DIM,
                                    "letterSpacing": "0.1em",
                                    "marginBottom": "3px",
                                },
                            ),
                            dcc.RadioItems(
                                id="backtest-strategy",
                                options=[
                                    {"label": " SIMPLE", "value": "simple"},
                                    {"label": " MULTI", "value": "multi"},
                                ],
                                value="simple",
                                inline=True,
                                style={
                                    "fontSize": "11px",
                                    "color": TEXT_MAIN,
                                    "display": "flex",
                                    "gap": "12px",
                                    "alignItems": "center",
                                },
                                labelStyle={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "4px",
                                    "cursor": "pointer",
                                },
                            ),
                        ]
                    ),
                    html.Button(
                        "▶ RUN BACKTEST",
                        id="btn-backtest-run",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {GREEN}",
                            "color": GREEN,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "6px 16px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                            "alignSelf": "flex-end",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "16px",
                    "alignItems": "flex-end",
                    "padding": "12px 16px",
                    "borderBottom": f"1px solid {BORDER}",
                    "flexShrink": "0",
                },
            ),
            dcc.Loading(
                id="bt-loading",
                children=html.Div(id="bt-results", style={"padding": "16px", "overflowY": "auto"}),
                color=GREEN,
                style={"flex": "1"},
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
        },
    )


def _tab_heatmap() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        "⟳ REFRESH",
                        id="btn-heatmap-refresh",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {BORDER}",
                            "color": TEXT_DIM,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "4px 12px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                    html.Span(
                        id="heatmap-updated",
                        style={
                            "fontSize": "9px",
                            "color": TEXT_DIM,
                            "marginLeft": "12px",
                            "letterSpacing": "0.08em",
                        },
                    ),
                ],
                style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER}"},
            ),
            html.Div(
                id="heatmap-content",
                style={
                    "flex": "1",
                    "overflowY": "auto",
                    "padding": "16px",
                },
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


def _tab_agents() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        "⟳ REFRESH",
                        id="btn-agents-refresh",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {BORDER}",
                            "color": TEXT_DIM,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "4px 12px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                ],
                style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER}"},
            ),
            html.Div(
                id="agents-content",
                style={
                    "flex": "1",
                    "overflowY": "auto",
                    "padding": "16px",
                },
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


def _tab_leaderboard() -> html.Div:
    scenarios = ["Bull Market", "Bear Market", "High Volatility", "Flat Market"]
    return html.Div(
        [
            html.Div(
                [
                    dcc.Dropdown(
                        id="lb-scenario",
                        options=[{"label": s, "value": s} for s in scenarios],
                        value=scenarios[0],
                        clearable=False,
                        style={
                            "width": "200px",
                            "background": BG_CARD,
                            "color": TEXT_MAIN,
                            "fontFamily": FONT,
                            "fontSize": "11px",
                        },
                    ),
                    html.Button(
                        "⚡ RUN ALL AGENTS",
                        id="btn-lb-run",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {PURPLE}",
                            "color": PURPLE,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "6px 16px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "10px",
                    "alignItems": "center",
                    "padding": "12px 16px",
                    "borderBottom": f"1px solid {BORDER}",
                },
            ),
            dcc.Loading(
                id="lb-loading",
                children=html.Div(id="lb-results", style={"padding": "16px", "overflowY": "auto"}),
                color=PURPLE,
                style={"flex": "1"},
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
        },
    )


def _tab_terminal() -> html.Div:
    _input_style = {
        "background": BG_DEEP,
        "border": f"1px solid {BORDER}",
        "color": TEXT_MAIN,
        "fontFamily": FONT,
        "fontSize": "11px",
        "padding": "5px 9px",
        "borderRadius": "3px",
        "outline": "none",
        "width": "140px",
    }
    _btn_style = {
        "background": "transparent",
        "border": f"1px solid {GREEN}",
        "color": GREEN,
        "fontFamily": FONT,
        "fontSize": "10px",
        "letterSpacing": "0.1em",
        "padding": "5px 12px",
        "cursor": "pointer",
        "borderRadius": "3px",
        "flexShrink": "0",
    }
    _alert_input_style = {
        "background": BG_DEEP,
        "border": f"1px solid {BORDER}",
        "color": TEXT_MAIN,
        "fontFamily": FONT,
        "fontSize": "11px",
        "padding": "5px 9px",
        "borderRadius": "3px",
        "outline": "none",
        "width": "90px",
    }
    return html.Div(
        [
            # ── A) Macro Header Bar (64px, full width) ────────────────────────────
            html.Div(
                [
                    html.Div(
                        id="macro-bar-content",
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "0",
                            "flex": "1",
                        },
                    ),
                ],
                style={
                    "background": BG_HOVER,
                    "borderBottom": f"1px solid {BORDER}",
                    "padding": "0 18px",
                    "height": "64px",
                    "display": "flex",
                    "alignItems": "center",
                    "flexShrink": "0",
                },
            ),
            # ── B) 2-column layout (65% / 35%) ───────────────────────────────────
            html.Div(
                [
                    # Left column (65%)
                    html.Div(
                        [
                            # C) Watchlist header + ADD input + card grid
                            html.Div(
                                [
                                    _section_label("WATCHLIST"),
                                    html.Div(
                                        [
                                            dcc.Input(
                                                id="watchlist-add-input",
                                                placeholder="Symbol (e.g. NVDA)",
                                                debounce=False,
                                                style=_input_style,
                                            ),
                                            html.Button(
                                                "ADD",
                                                id="btn-watchlist-add",
                                                n_clicks=0,
                                                style=_btn_style,
                                            ),
                                            html.Button(
                                                "COMPARE",
                                                id="btn-compare",
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": f"1px solid {BLUE}",
                                                    "color": BLUE,
                                                    "fontFamily": FONT,
                                                    "fontSize": "10px",
                                                    "letterSpacing": "0.1em",
                                                    "padding": "5px 10px",
                                                    "cursor": "pointer",
                                                    "borderRadius": "3px",
                                                    "flexShrink": "0",
                                                },
                                            ),
                                            html.Button(
                                                "CSV",
                                                id="btn-export-csv",
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": f"1px solid {BORDER}",
                                                    "color": TEXT_DIM,
                                                    "fontFamily": FONT,
                                                    "fontSize": "10px",
                                                    "letterSpacing": "0.1em",
                                                    "padding": "5px 10px",
                                                    "cursor": "pointer",
                                                    "borderRadius": "3px",
                                                    "flexShrink": "0",
                                                },
                                            ),
                                            dcc.Download(id="csv-download"),
                                        ],
                                        style={
                                            "display": "flex",
                                            "gap": "8px",
                                            "marginBottom": "10px",
                                            "alignItems": "center",
                                            "flexWrap": "wrap",
                                        },
                                    ),
                                    # Hidden backward-compat chips output
                                    html.Div(id="watchlist-chips", style={"display": "none"}),
                                    # Compare panel (toggled by _toggle_compare callback)
                                    html.Div(
                                        id="compare-panel",
                                        style={"display": "none"},
                                        children=[
                                            html.Div(
                                                [
                                                    html.Div(
                                                        [
                                                            html.Div(
                                                                "SYMBOLS",
                                                                style={
                                                                    "fontSize": "9px",
                                                                    "color": TEXT_DIM,
                                                                    "letterSpacing": "0.1em",
                                                                    "marginBottom": "4px",
                                                                },
                                                            ),
                                                            dcc.Checklist(
                                                                id="compare-symbols",
                                                                options=[
                                                                    {"label": f" {s}", "value": s}
                                                                    for s in WATCHLIST
                                                                ],
                                                                value=[],
                                                                inline=True,
                                                                style={
                                                                    "fontSize": "11px",
                                                                    "color": TEXT_MAIN,
                                                                    "display": "flex",
                                                                    "flexWrap": "wrap",
                                                                    "gap": "8px",
                                                                },
                                                                labelStyle={
                                                                    "display": "flex",
                                                                    "alignItems": "center",
                                                                    "gap": "3px",
                                                                    "cursor": "pointer",
                                                                },
                                                            ),
                                                        ],
                                                        style={"flex": "1"},
                                                    ),
                                                    html.Div(
                                                        [
                                                            html.Div(
                                                                "PERIOD",
                                                                style={
                                                                    "fontSize": "9px",
                                                                    "color": TEXT_DIM,
                                                                    "letterSpacing": "0.1em",
                                                                    "marginBottom": "4px",
                                                                },
                                                            ),
                                                            dcc.Dropdown(
                                                                id="compare-period",
                                                                options=[
                                                                    {"label": p, "value": p}
                                                                    for p in [
                                                                        "1d",
                                                                        "5d",
                                                                        "1mo",
                                                                        "3mo",
                                                                    ]
                                                                ],
                                                                value="1mo",
                                                                clearable=False,
                                                                style={
                                                                    "width": "80px",
                                                                    "background": BG_CARD,
                                                                    "color": TEXT_MAIN,
                                                                    "fontFamily": FONT,
                                                                    "fontSize": "11px",
                                                                },
                                                            ),
                                                        ]
                                                    ),
                                                ],
                                                style={
                                                    "display": "flex",
                                                    "gap": "16px",
                                                    "alignItems": "flex-start",
                                                    "marginBottom": "8px",
                                                },
                                            ),
                                            dcc.Graph(
                                                id="compare-chart",
                                                config={"displayModeBar": False},
                                                style={"height": "260px"},
                                            ),
                                        ],
                                    ),
                                    # Symbol card grid (2-col) — populated by _update_watchlist
                                    html.Div(id="watchlist-table"),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                    "marginBottom": "12px",
                                },
                            ),
                            # D) Screener bar
                            html.Div(
                                [
                                    _section_label("SCREENER"),
                                    html.Div(
                                        [
                                            html.Div(
                                                "RSI RANGE",
                                                style={
                                                    "fontSize": "9px",
                                                    "color": TEXT_DIM,
                                                    "letterSpacing": "0.1em",
                                                    "marginBottom": "4px",
                                                },
                                            ),
                                            dcc.RangeSlider(
                                                id="screener-rsi",
                                                min=0,
                                                max=100,
                                                step=1,
                                                value=[30, 70],
                                                marks={
                                                    0: "0",
                                                    30: "30",
                                                    50: "50",
                                                    70: "70",
                                                    100: "100",
                                                },
                                                tooltip={
                                                    "placement": "bottom",
                                                    "always_visible": False,
                                                },
                                            ),
                                        ],
                                        style={"marginBottom": "12px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Div(
                                                        "CHG% MIN",
                                                        style={
                                                            "fontSize": "9px",
                                                            "color": TEXT_DIM,
                                                            "marginBottom": "3px",
                                                        },
                                                    ),
                                                    dcc.Input(
                                                        id="screener-chg-min",
                                                        type="number",
                                                        placeholder="-5",
                                                        style={**_input_style, "width": "80px"},
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                [
                                                    html.Div(
                                                        "CHG% MAX",
                                                        style={
                                                            "fontSize": "9px",
                                                            "color": TEXT_DIM,
                                                            "marginBottom": "3px",
                                                        },
                                                    ),
                                                    dcc.Input(
                                                        id="screener-chg-max",
                                                        type="number",
                                                        placeholder="5",
                                                        style={**_input_style, "width": "80px"},
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                [
                                                    dcc.Checklist(
                                                        id="screener-flags",
                                                        options=[
                                                            {
                                                                "label": " Above MA20",
                                                                "value": "above_ma20",
                                                            },
                                                            {
                                                                "label": " Vol > 1M",
                                                                "value": "high_volume",
                                                            },
                                                        ],
                                                        value=[],
                                                        style={
                                                            "fontSize": "11px",
                                                            "color": TEXT_MAIN,
                                                            "display": "flex",
                                                            "flexDirection": "column",
                                                            "gap": "4px",
                                                        },
                                                        labelStyle={
                                                            "display": "flex",
                                                            "alignItems": "center",
                                                            "gap": "4px",
                                                            "cursor": "pointer",
                                                        },
                                                    ),
                                                ],
                                                style={"display": "flex", "alignItems": "center"},
                                            ),
                                            html.Button(
                                                "RUN SCREENER",
                                                id="btn-screener-run",
                                                n_clicks=0,
                                                style={
                                                    **_btn_style,
                                                    "border": f"1px solid {PURPLE}",
                                                    "color": PURPLE,
                                                    "letterSpacing": "0.12em",
                                                    "padding": "6px 14px",
                                                },
                                            ),
                                            html.Button(
                                                "CLEAR",
                                                id="btn-screener-clear",
                                                n_clicks=0,
                                                style={
                                                    **_btn_style,
                                                    "border": f"1px solid {BORDER}",
                                                    "color": TEXT_DIM,
                                                    "letterSpacing": "0.12em",
                                                    "padding": "6px 10px",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "gap": "16px",
                                            "alignItems": "flex-end",
                                            "marginBottom": "12px",
                                        },
                                    ),
                                    html.Div(id="screener-results"),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                },
                            ),
                            # E) Price Alerts — compact one-line input row
                            html.Div(
                                [
                                    _section_label("PRICE ALERTS"),
                                    html.Div(id="alert-banner", style={"display": "none"}),
                                    html.Div(
                                        [
                                            dcc.Input(
                                                id="alert-symbol-input",
                                                placeholder="Symbol",
                                                debounce=False,
                                                style=_alert_input_style,
                                            ),
                                            dcc.Dropdown(
                                                id="alert-direction-dropdown",
                                                options=[
                                                    {"label": "ABOVE", "value": "above"},
                                                    {"label": "BELOW", "value": "below"},
                                                ],
                                                value="above",
                                                clearable=False,
                                                style={
                                                    "width": "95px",
                                                    "background": BG_CARD,
                                                    "color": TEXT_MAIN,
                                                    "fontFamily": FONT,
                                                    "fontSize": "11px",
                                                },
                                            ),
                                            dcc.Input(
                                                id="alert-price-input",
                                                type="number",
                                                placeholder="$190.00",
                                                debounce=False,
                                                style=_alert_input_style,
                                            ),
                                            html.Button(
                                                "SET",
                                                id="btn-set-alert",
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": f"1px solid {GREEN}",
                                                    "color": GREEN,
                                                    "fontFamily": FONT,
                                                    "fontSize": "10px",
                                                    "letterSpacing": "0.1em",
                                                    "padding": "5px 10px",
                                                    "cursor": "pointer",
                                                    "borderRadius": "3px",
                                                    "flexShrink": "0",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "gap": "6px",
                                            "marginBottom": "10px",
                                            "alignItems": "center",
                                            "flexWrap": "nowrap",
                                        },
                                    ),
                                    html.Div(id="alerts-list"),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                    "marginTop": "12px",
                                },
                            ),
                        ],
                        style={
                            "width": "65%",
                            "paddingRight": "10px",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                    ),
                    # Right column (35%)
                    html.Div(
                        [
                            # News feed
                            html.Div(
                                [
                                    html.Div(
                                        id="news-header",
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
                                    ),
                                    # Primary news slot (new)
                                    html.Div(
                                        id="news-feed-content",
                                        style={"maxHeight": "340px", "overflowY": "auto"},
                                    ),
                                    # Legacy slot kept hidden for backward compat
                                    html.Div(id="news-feed", style={"display": "none"}),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                    "marginBottom": "12px",
                                },
                            ),
                            # Chart overlay (1mo OHLCV)
                            html.Div(
                                [html.Div(id="chart-overlay-content")],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "0",
                                    "overflow": "hidden",
                                },
                            ),
                        ],
                        style={
                            "width": "35%",
                            "paddingLeft": "10px",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "flex": "1",
                    "padding": "14px 16px",
                    "overflowY": "auto",
                    "minHeight": "0",
                },
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# APP LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

app.layout = html.Div(
    id="page-bg",
    style={
        "background": BG_DEEP,
        "height": "100vh",
        "display": "flex",
        "flexDirection": "column",
        "fontFamily": FONT,
        "overflow": "hidden",
    },
    children=[
        dcc.Store(id="ctrl-store", data={"paused": False}),
        dcc.Store(id="mode-store", data={"sim": get_simulation_mode()}),
        dcc.Store(id="graph-store", data={"graph_id": AGENT_GRAPH}),
        dcc.Store(
            id="agent-cards-state",
            data={"tech": False, "analyst": False, "risk": False, "macro": False},
        ),
        dcc.Interval(id="tick", interval=2000, n_intervals=0),
        dcc.Interval(id="analytics-tick", interval=30000, n_intervals=0),
        dcc.Interval(id="agents-tick", interval=60000, n_intervals=0),
        dcc.Interval(id="macro-interval", interval=60000, n_intervals=0),
        dcc.Interval(id="watchlist-interval", interval=10000, n_intervals=0),
        dcc.Interval(id="news-interval", interval=120000, n_intervals=0),
        dcc.Store(id="terminal-watchlist", data=list(WATCHLIST)),
        dcc.Store(id="terminal-active-symbol", data=WATCHLIST[0] if WATCHLIST else "AAPL"),
        dcc.Store(id="price-alerts-store", data=[]),
        dcc.Store(id="screener-results-store", data=[]),
        dcc.Store(id="screener-active-store", data=False),
        dcc.Interval(id="check-alerts-interval", interval=10000, n_intervals=0),
        # ── TOP BAR (48px) ───────────────────────────────────────────────────
        html.Div(
            id="top-bar",
            children=[
                html.Div(
                    [
                        html.Div(id="status-dot", className="dot dot-alive"),
                        html.Div(
                            [
                                html.Span(
                                    "APEX-7 // SURVIVAL TRADER",
                                    style={
                                        "color": TEXT_DIM,
                                        "fontSize": "12px",
                                        "fontWeight": "600",
                                        "letterSpacing": "0.18em",
                                    },
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Span(
                                    "ROUND ",
                                    style={
                                        "fontSize": "9px",
                                        "color": TEXT_DIM,
                                        "letterSpacing": "0.15em",
                                    },
                                ),
                                html.Span(
                                    id="round-num",
                                    children="—",
                                    style={"fontSize": "10px", "color": TEXT_DIM},
                                ),
                            ],
                            style={"marginLeft": "6px", "display": "flex", "alignItems": "center"},
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center", "gap": "12px"},
                ),
                html.Div(id="mode-badge"),
                html.Div(
                    [
                        dcc.Dropdown(
                            id="graph-selector",
                            options=[
                                {"label": "⚡ SIMPLE", "value": "simple"},
                                {"label": "🧠 MULTI-AGENT", "value": "multi"},
                            ],
                            value=AGENT_GRAPH,
                            clearable=False,
                            style={
                                "width": "170px",
                                "fontSize": "11px",
                                "background": BG_CARD,
                                "color": TEXT_MAIN,
                                "fontFamily": FONT,
                            },
                        ),
                        html.Div(style={"width": "1px", "height": "14px", "background": BORDER}),
                        dcc.RadioItems(
                            id="mode-radio",
                            options=[
                                {"label": " SIM", "value": "sim"},
                                {"label": " LIVE", "value": "live"},
                            ],
                            value="sim" if get_simulation_mode() else "live",
                            inline=True,
                            className="mode-radio",
                            style={
                                "display": "flex",
                                "gap": "6px",
                                "alignItems": "center",
                                "fontSize": "10px",
                                "fontWeight": "700",
                                "letterSpacing": "0.1em",
                                "color": GRAY,
                            },
                            labelStyle={
                                "display": "flex",
                                "alignItems": "center",
                                "gap": "4px",
                                "cursor": "pointer",
                            },
                        ),
                        html.Div(style={"width": "1px", "height": "14px", "background": BORDER}),
                        html.Button(
                            "PAUSE", id="btn-pause", n_clicks=0, className="cbtn cbtn-pause"
                        ),
                        html.Button("STEP", id="btn-step", n_clicks=0, className="cbtn cbtn-step"),
                        html.Button(
                            "RESET", id="btn-reset", n_clicks=0, className="cbtn cbtn-reset"
                        ),
                    ],
                    style={"display": "flex", "gap": "7px", "alignItems": "center"},
                ),
            ],
            style={
                "height": "48px",
                "flexShrink": "0",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "space-between",
                "padding": "0 18px",
                "borderBottom": f"1px solid {BORDER}",
                "background": BG_CARD,
            },
        ),
        # ── TABS BAR (38px) ──────────────────────────────────────────────────
        dcc.Tabs(
            id="main-tabs",
            value="live",
            children=[
                dcc.Tab(
                    label="LIVE",
                    value="live",
                    style={
                        "color": TEXT_DIM,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": "2px solid transparent",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="ANALYTICS",
                    value="analytics",
                    style={
                        "color": TEXT_DIM,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": "2px solid transparent",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="BACKTEST",
                    value="backtest",
                    style={
                        "color": TEXT_DIM,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": "2px solid transparent",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="LEADERBOARD",
                    value="leaderboard",
                    style={
                        "color": TEXT_DIM,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": "2px solid transparent",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="HEATMAP",
                    value="heatmap",
                    style={
                        "color": TEXT_DIM,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": "2px solid transparent",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="AGENTS",
                    value="agents",
                    style={
                        "color": TEXT_DIM,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": "2px solid transparent",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="TERMINAL",
                    value="terminal",
                    style={
                        "color": TEXT_DIM,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": "2px solid transparent",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                    selected_style={
                        "color": BLUE,
                        "fontSize": "11px",
                        "letterSpacing": "0.15em",
                        "fontFamily": FONT,
                        "fontWeight": "700",
                        "padding": "0 16px",
                        "border": "none",
                        "borderBottom": f"2px solid {BLUE}",
                        "background": BG_CARD,
                        "cursor": "pointer",
                    },
                ),
            ],
            style={"height": "38px", "flexShrink": "0"},
            colors={"border": BORDER, "primary": GREEN, "background": BG_CARD},
        ),
        # ── TAB CONTENT (static — all tabs in DOM, visibility toggled) ──────
        html.Div(
            id="tab-live",
            children=_tab_live(),
            style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "block"},
        ),
        html.Div(
            id="tab-analytics",
            children=_tab_analytics(),
            style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
        ),
        html.Div(
            id="tab-backtest",
            children=_tab_backtest(),
            style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
        ),
        html.Div(
            id="tab-leaderboard",
            children=_tab_leaderboard(),
            style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
        ),
        html.Div(
            id="tab-heatmap",
            children=_tab_heatmap(),
            style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
        ),
        html.Div(
            id="tab-agents",
            children=_tab_agents(),
            style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
        ),
        html.Div(
            id="tab-terminal",
            children=_tab_terminal(),
            style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
        ),
    ],
)
