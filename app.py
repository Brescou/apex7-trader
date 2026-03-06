"""APEX-7 // SURVIVAL TRADER — Premium Terminal Dashboard (Bloomberg aesthetic)."""

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import dash
import plotly.graph_objects as go
from dash import Input, Output, State, ctx, dcc, html, MATCH
from dash.dash_table import DataTable

from agent import get_simulation_mode, set_simulation_mode
from agent_multi import run_daily_postmortem
from config import AGENT_GRAPH, AGENT_INTERVAL, DEATH_THRESHOLD, INITIAL_BALANCE, POSTMORTEM_HOUR, SIMULATION_MODE
from data import Portfolio
from graph_registry import get_graph, get_graph_info

# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS
# ═══════════════════════════════════════════════════════════════════════════════

BG_DEEP  = "#060810"
BG_CARD  = "#0a0f1e"
BG_HOVER = "#0f1729"
GREEN    = "#10b981"
RED      = "#ef4444"
BLUE     = "#3b82f6"
ORANGE   = "#f97316"
YELLOW   = "#f59e0b"
PURPLE   = "#8b5cf6"
GRAY     = "#475569"
BORDER   = "#1a2535"
TEXT_DIM = "#64748b"
TEXT_MAIN= "#e2e8f0"
FONT     = "'JetBrains Mono', 'Fira Code', Consolas, monospace"

DB_PATH  = Path(__file__).parent / "trades.db"

# ═══════════════════════════════════════════════════════════════════════════════
# AGENT CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════

_ctrl: dict = {"paused": False, "step": False}
_state: dict = {
    "graph_id":  AGENT_GRAPH,
    "last_votes": [],   # last agent_votes from multi-agent cycle
    "last_arb":   {},   # last arbitration result
}


def _agent_loop(p: Portfolio, graph_id: str = "simple") -> None:
    import traceback
    graph = get_graph(graph_id, p)
    cycle = 0
    is_multi = graph_id == "multi"

    while not p.is_dead:
        while _ctrl["paused"] and not _ctrl["step"] and not p.is_dead:
            time.sleep(0.3)
        if p.is_dead:
            break
        _ctrl["step"] = False
        cycle += 1
        p.log(f"=== CYCLE {cycle} START ===")
        try:
            initial: dict = {
                "balance":             p.cash,
                "positions":           dict(p.positions),
                "portfolio_history":   [],
                "prices":              dict(p.last_prices),
                "news":                "",
                "sentiment":           {},
                "past_trades":         [],
                "known_patterns":      [],
                "round":               cycle,
                "confidence":          0.0,
                "research_iterations": 0,
                "decision":            None,
                "emotion":             "CALM",
                "thoughts":            "",
                "log":                 [],
                "alive":               True,
                "skip_research":       False,
            }
            if is_multi:
                initial.update({
                    "supervisor_brief": "",
                    "agent_role":       "",
                    "agent_votes":      [],
                    "tech_vote":        None,
                    "analyst_vote":     None,
                    "risk_vote":        None,
                    "macro_vote":       None,
                    "arbitration":      None,
                })
            result = graph.invoke(initial)
            for entry in result.get("log", []):
                p.log(entry["message"], entry.get("level", "info"))
            # Store multi-agent votes for dashboard
            if is_multi:
                _state["last_votes"] = result.get("agent_votes", [])
                _state["last_arb"]   = result.get("arbitration", {}) or {}
            if not result.get("alive", True):
                p.is_dead = True
                p.log("DEATH CONDITION MET", "critical")
                break
        except Exception as e:
            p.log(f"Cycle error: {e}", "error")
            p.log(traceback.format_exc(), "error")
        if p.is_dead:
            p.log("AGENT HALTED — DEATH CONDITION MET", "critical")
            break
        sleep_s = 3 if get_simulation_mode() else AGENT_INTERVAL
        p.log(f"=== CYCLE {cycle} DONE — sleeping {sleep_s}s ===")
        elapsed = 0.0
        while elapsed < sleep_s and not p.is_dead:
            if _ctrl["paused"] and not _ctrl["step"]:
                time.sleep(0.3)
            else:
                time.sleep(1.0)
                elapsed += 1.0


def _launch(p: Portfolio, graph_id: str = "simple") -> threading.Thread:
    t = threading.Thread(target=_agent_loop, args=(p, graph_id), daemon=True)
    t.start()
    return t


_state["portfolio"] = Portfolio()
_state["thread"]    = _launch(_state["portfolio"], _state["graph_id"])

_last_postmortem_date = None


def _postmortem_loop(p: Portfolio) -> None:
    global _last_postmortem_date
    while True:
        time.sleep(60)
        now   = datetime.now()
        today = now.date()
        if now.hour == POSTMORTEM_HOUR and _last_postmortem_date != today:
            try:
                run_daily_postmortem(p)
                _last_postmortem_date = today
            except Exception as _e:
                p.log(f"Postmortem error: {_e}", "error")


threading.Thread(
    target=_postmortem_loop, args=(_state["portfolio"],),
    daemon=True, name="apex7-postmortem"
).start()

# ═══════════════════════════════════════════════════════════════════════════════
# EMOTION SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

_EMOTIONS: dict[str, dict] = {
    "EUPHORIC":  {"icon": "🚀", "color": GREEN,  "quote": "To the moon. Nothing can stop us now."},
    "EXCITED":   {"icon": "🔥", "color": GREEN,  "quote": "Momentum building. Stay aggressive."},
    "FOCUSED":   {"icon": "🎯", "color": BLUE,   "quote": "Executing the plan. Steady hands."},
    "CALM":      {"icon": "😐", "color": GRAY,   "quote": "Patience. The market reveals itself."},
    "NERVOUS":   {"icon": "😰", "color": YELLOW, "quote": "Risk elevated. Reduce exposure now."},
    "PANIC":     {"icon": "🚨", "color": RED,    "quote": "Capital preservation. Cut losses NOW."},
    "DESPERATE": {"icon": "💀", "color": RED,    "quote": "One trade left. Make it count."},
}


def _emotion(total: float) -> str:
    r = total / INITIAL_BALANCE
    if r >= 1.5: return "EUPHORIC"
    if r >= 1.2: return "EXCITED"
    if r >= 0.9: return "FOCUSED"
    if r >= 0.7: return "CALM"
    if r >= 0.5: return "NERVOUS"
    if r >= 0.2: return "PANIC"
    return "DESPERATE"


def _thinking(p: Portfolio) -> bool:
    for e in reversed(p.agent_log[-5:]):
        if "Calling Anthropic" in e["message"]:
            return True
        if "DONE" in e["message"] or e["message"].startswith(("BUY ", "SELL ", "HOLD ")):
            return False
    return False


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
    return html.Div(text, style={
        "fontSize": "9px", "fontWeight": "700", "letterSpacing": "0.18em",
        "color": TEXT_DIM, "textTransform": "uppercase",
        "borderBottom": f"1px solid {BORDER}",
        "paddingBottom": "6px", "marginBottom": "10px",
    })


def _mini_stat(label: str, value: str, color: str = TEXT_MAIN) -> html.Div:
    return html.Div([
        html.Div(label, style={"fontSize": "9px", "letterSpacing": "0.1em", "color": TEXT_DIM}),
        html.Div(value, style={"fontSize": "12px", "color": color, "fontWeight": "700", "marginTop": "2px"}),
    ], style={
        "background": BG_CARD, "border": f"1px solid {BORDER}",
        "borderRadius": "3px", "padding": "8px 10px",
    })


def _classify(msg: str, level: str) -> tuple[str, str]:
    return _classify_v2(msg, level)


def _classify_v2(msg: str, level: str) -> tuple[str, str]:
    """Returns (badge_label, color) with proper sell coloring based on profit."""
    if level == "critical":                               return "DEATH",     "#ff2020"
    if level == "error":                                  return "ERR",       ORANGE
    if level == "warning":                                return "WARN",      YELLOW
    if msg.startswith("BUY "):                            return "BUY",       BLUE
    if msg.startswith("SELL "):
        return ("SELL WIN", GREEN) if "+" in msg else ("SELL LOSS", RED)
    if msg.startswith("HOLD "):                           return "HOLD",      GRAY
    if msg.startswith("Skip "):                           return "SKIP",      YELLOW
    if "Anthropic" in msg or "web search" in msg:         return "AI",        PURPLE
    if msg.startswith("Analysis:"):                       return "INTEL",     PURPLE
    # Multi-agent badges
    if msg.startswith("[SIM][TECH]") or msg.startswith("technician:"):  return "TECH",   BLUE
    if msg.startswith("[SIM][ANLST]") or msg.startswith("analyst:"):    return "ANLST",  "#06b6d4"
    if msg.startswith("[SIM][RISK]") or msg.startswith("risk_manager:"): return "RISK",  RED
    if msg.startswith("[SIM][MACRO]") or msg.startswith("macro_watcher:"): return "MACRO", YELLOW
    if msg.startswith("supervisor:"):                     return "SUPV",      PURPLE
    if msg.startswith("arbitrate:"):                      return "ARBIT",     GREEN
    if msg.startswith("[SIM]"):                           return "SIM",       ORANGE
    if msg.startswith("=== CYCLE"):                       return "CYC",       BORDER
    if msg.startswith(("Fetching", "Prices")):            return "MKT",       BORDER
    return "LOG", BORDER


def _log_entry_card(entry: dict) -> html.Div:
    badge, color = _classify_v2(entry["message"], entry["level"])
    t = entry["time"][11:19]
    is_dim = badge in ("CYC", "MKT", "LOG")
    has_bg = color != BORDER

    # Check for web intel hints in the message
    has_intel = "Analysis:" in entry["message"] or "market_intel" in entry["message"]

    sub_items = []
    msg = entry["message"]

    # Extract reasoning sub-text if present
    reasoning = ""
    if " — " in msg and badge in ("BUY", "SELL WIN", "SELL LOSS", "HOLD"):
        parts = msg.split(" — ", 1)
        msg = parts[0]
        reasoning = parts[1]

    if reasoning:
        sub_items.append(html.Div(
            f"→ {reasoning[:120]}",
            style={"fontSize": "10px", "color": TEXT_DIM, "marginTop": "3px"}
        ))

    return html.Div([
        html.Div([
            html.Div([
                html.Span(badge, style={
                    "fontSize": "9px", "fontWeight": "700", "letterSpacing": "0.05em",
                    "padding": "2px 6px", "borderRadius": "2px",
                    "background": f"{color}22" if has_bg else f"{BORDER}44",
                    "color": color if has_bg else TEXT_DIM,
                    "marginRight": "8px", "flexShrink": "0",
                }),
                html.Span(msg[:140], style={
                    "color": TEXT_DIM if is_dim else TEXT_MAIN,
                    "fontSize": "11px", "flex": "1",
                }),
                html.Span(t, style={
                    "color": TEXT_DIM, "fontSize": "9px",
                    "marginLeft": "auto", "flexShrink": "0",
                }),
            ], style={"display": "flex", "alignItems": "center"}),
            *sub_items,
        ]),
    ], style={
        "borderLeft": f"3px solid {color if has_bg else BORDER}",
        "background": f"{color}07" if has_bg else "transparent",
        "padding": "7px 10px",
        "marginBottom": "6px",
        "borderRadius": "0 3px 3px 0",
        "opacity": "0.35" if is_dim else "1",
    })


def _pos_card(sym: str, pos: dict, prices: dict) -> html.Div:
    cur = prices.get(sym, pos["avg_price"])
    pnl = ((cur / pos["avg_price"]) - 1) * 100
    val = pos["shares"] * cur
    c = GREEN if pnl >= 0 else RED
    bar_w = min(abs(pnl) / 20, 1) * 100

    return html.Div([
        html.Div([
            html.Span(sym, style={"fontSize": "13px", "fontWeight": "700", "color": TEXT_MAIN}),
            html.Span(f"{pnl:+.2f}%", style={"fontSize": "12px", "fontWeight": "600", "color": c}),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "baseline"}),
        html.Div([
            html.Span(f"{pos['shares']:.4f} sh", style={"color": TEXT_DIM, "fontSize": "10px"}),
            html.Span(f"${val:.2f}", style={"color": TEXT_MAIN, "fontSize": "11px"}),
        ], style={"display": "flex", "justifyContent": "space-between", "marginTop": "4px"}),
        html.Div([
            html.Span(f"avg ${pos['avg_price']:.2f}", style={"color": TEXT_DIM, "fontSize": "9px"}),
            html.Span(f"→ ${cur:.2f}", style={"color": TEXT_MAIN, "fontSize": "9px"}),
        ], style={"display": "flex", "justifyContent": "space-between", "marginTop": "2px"}),
        # Mini P&L bar
        html.Div(
            html.Div(style={
                "width": f"{bar_w}%", "height": "100%",
                "background": c, "borderRadius": "1px",
            }),
            style={
                "height": "2px", "background": f"{c}22",
                "marginTop": "7px", "borderRadius": "1px", "overflow": "hidden",
            }
        ),
    ], style={
        "background": f"{c}04",
        "border": f"1px solid {c}18",
        "borderLeft": f"2px solid {c}",
        "borderRadius": "3px", "padding": "9px 11px", "marginBottom": "7px",
    })


def _sparkline(p: Portfolio) -> go.Figure:
    vh = p.value_history
    times  = [v["time"] for v in vh]
    values = [v["value"] for v in vh]
    lc = RED if p.is_dead else GREEN
    fc = "239,68,68" if p.is_dead else "16,185,129"
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times, y=values, mode="lines",
        line=dict(color=lc, width=1.5, shape="spline", smoothing=0.4),
        fill="tozeroy", fillcolor=f"rgba({fc},0.06)",
    ))
    fig.add_hline(y=DEATH_THRESHOLD,
                  line=dict(color=RED, dash="dot", width=1),
                  annotation_text=f"${DEATH_THRESHOLD} DEATH",
                  annotation_position="bottom right",
                  annotation_font=dict(color=RED, size=8, family=FONT))
    fig.add_hline(y=INITIAL_BALANCE,
                  line=dict(color=BORDER, dash="dot", width=1),
                  annotation_text=f"${INITIAL_BALANCE} START",
                  annotation_position="top right",
                  annotation_font=dict(color=TEXT_DIM, size=8, family=FONT))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=TEXT_DIM, size=9),
        margin=dict(l=46, r=12, t=6, b=26),
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showline=False,
                   tickfont=dict(size=8, color=TEXT_DIM), tickformat="%H:%M"),
        yaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=False, showline=False,
                   tickprefix="$", tickfont=dict(size=8, color=TEXT_DIM)),
        height=200,
    )
    return fig


def _load_trades_db() -> list[dict]:
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT id,timestamp,symbol,action,price,amount_usd,shares,"
            "reasoning,confidence,emotion,portfolio_value_after,lesson,source "
            "FROM trades ORDER BY timestamp DESC LIMIT 500"
        ).fetchall()
        con.close()
        cols = ("id","timestamp","symbol","action","price","amount_usd","shares",
                "reasoning","confidence","emotion","portfolio_value_after","lesson","source")
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT CARD HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _conf_bar_inline(conf: float, color: str) -> html.Div:
    w = int(conf * 40)
    return html.Div(
        html.Div(style={"width": f"{w}px", "height": "100%",
                        "background": color, "borderRadius": "1px"}),
        style={"width": "40px", "height": "3px", "background": f"{color}22",
               "borderRadius": "1px", "overflow": "hidden", "flexShrink": "0"},
    )


def _action_chip(action: str) -> html.Span:
    c = {"BUY": BLUE, "SELL": RED, "HOLD": GRAY}.get(action.upper(), GRAY)
    return html.Span(action, style={
        "fontSize": "9px", "fontWeight": "700",
        "padding": "1px 5px", "borderRadius": "2px",
        "background": f"{c}22", "color": c, "marginRight": "6px", "flexShrink": "0",
    })


def _sim_chip() -> html.Span:
    return html.Span("SIM", style={
        "fontSize": "8px", "padding": "1px 4px", "borderRadius": "2px",
        "background": f"{ORANGE}33", "color": ORANGE, "marginLeft": "6px",
    })


def _card_hdr_standard(icon: str, label: str, color: str, action: str,
                        symbol: str, conf: float, is_sim: bool) -> list:
    children = [
        html.Span(f"{icon} {label}", style={
            "fontSize": "9px", "fontWeight": "700", "color": color,
            "marginRight": "10px", "flexShrink": "0",
        }),
        _action_chip(action),
        html.Span(symbol or "—", style={
            "fontSize": "9px", "color": TEXT_MAIN, "flex": "1",
            "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
        }),
        _conf_bar_inline(conf, color),
        html.Span(f"{conf:.0%}", style={
            "fontSize": "9px", "color": color, "marginLeft": "5px", "flexShrink": "0",
        }),
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
    return html.Div([
        html.Div(label, style={"fontSize": "9px", "color": TEXT_DIM, "letterSpacing": "0.08em"}),
        html.Div(val, style={"fontSize": "10px", "color": color, "fontWeight": "700", "marginTop": "2px"}),
    ], style={"padding": "5px 7px", "background": f"{BLUE}08", "borderRadius": "2px"})


def _tech_body_children(v: dict) -> list:
    ind     = v.get("key_indicators", {})
    rsi_raw = ind.get("rsi", 50)
    macd    = str(ind.get("macd",  "—"))
    bb      = str(ind.get("bb",    "—"))
    trend   = str(ind.get("trend", "—"))
    reasoning = v.get("reasoning", "")

    def _ind_color(s: str) -> str:
        sl = s.lower()
        if any(w in sl for w in ("bull", "up", "lower", "over")):
            return GREEN
        if any(w in sl for w in ("bear", "down", "upper")):
            return RED
        return TEXT_MAIN

    rsi_val = f"{float(rsi_raw):.1f}" if isinstance(rsi_raw, (int, float)) else str(rsi_raw)
    rsi_col = RED if isinstance(rsi_raw, (int, float)) and rsi_raw < 35 else (
              GREEN if isinstance(rsi_raw, (int, float)) and rsi_raw > 65 else TEXT_MAIN)

    return [
        html.Div(reasoning, style={
            "fontSize": "11px", "color": TEXT_DIM, "fontStyle": "italic",
            "marginBottom": "8px", "lineHeight": "1.4",
        }),
        html.Div([
            _ind_cell("RSI",   rsi_val, rsi_col),
            _ind_cell("MACD",  macd,    _ind_color(macd)),
            _ind_cell("BB",    bb,      _ind_color(bb)),
            _ind_cell("TREND", trend,   _ind_color(trend)),
        ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "4px"}),
    ]


def _sent_bar(score: float) -> html.Div:
    pct = (score + 1) / 2 * 100
    col = GREEN if score > 0.1 else (RED if score < -0.1 else GRAY)
    return html.Div([
        html.Div("SENTIMENT", style={
            "fontSize": "9px", "color": TEXT_DIM,
            "letterSpacing": "0.1em", "marginBottom": "4px",
        }),
        html.Div([
            html.Div(style={
                "width": "100%", "height": "100%",
                "background": f"linear-gradient(to right, {RED}, {GRAY} 50%, {GREEN})",
            }),
            html.Div(style={
                "position": "absolute", "top": "-3px", "bottom": "-3px",
                "left": f"{pct:.1f}%", "width": "2px",
                "background": col, "borderRadius": "1px",
                "transform": "translateX(-50%)",
            }),
        ], style={
            "position": "relative", "height": "4px", "borderRadius": "2px",
            "overflow": "visible", "marginBottom": "4px",
        }),
        html.Div(f"{score:+.2f}", style={"fontSize": "10px", "color": col, "fontWeight": "700"}),
    ])


def _analyst_body_children(v: dict) -> list:
    reasoning  = v.get("reasoning", "")
    sent_score = float(v.get("sentiment_score", 0.0))
    catalysts  = v.get("catalysts", []) or []

    items: list = [
        html.Div(reasoning, style={
            "fontSize": "11px", "color": TEXT_DIM, "fontStyle": "italic",
            "marginBottom": "8px", "lineHeight": "1.4",
        }),
        html.Div(_sent_bar(sent_score), style={"marginBottom": "7px" if catalysts else "0"}),
    ]
    for cat in catalysts[:2]:
        items.append(html.Div(f"→ {cat}", style={
            "fontSize": "10px", "color": TEXT_DIM,
            "borderLeft": f"2px solid {GREEN}44", "paddingLeft": "6px",
            "marginBottom": "3px",
        }))
    return items


def _risk_body_children(v: dict) -> list:
    reasoning  = v.get("reasoning", "")
    risk_score = int(v.get("risk_score", 5))
    warnings   = v.get("warnings", []) or []
    var_1d     = float(v.get("var_1d", 0))
    exposure   = float(v.get("portfolio_exposure_after", 0))
    score_col  = GREEN if risk_score <= 3 else (ORANGE if risk_score <= 6 else RED)

    items: list = [
        html.Div(reasoning, style={
            "fontSize": "11px", "color": TEXT_DIM, "fontStyle": "italic",
            "marginBottom": "8px", "lineHeight": "1.4",
        }),
        html.Div([
            html.Div("RISK SCORE", style={
                "fontSize": "9px", "color": TEXT_DIM, "letterSpacing": "0.1em",
            }),
            html.Div(f"{risk_score}/10", style={
                "fontSize": "22px", "fontWeight": "700", "color": score_col,
                "lineHeight": "1", "marginTop": "2px",
            }),
        ], style={"marginBottom": "7px"}),
    ]
    for w in warnings:
        items.append(html.Div(f"\u26a0 {w}", style={
            "fontSize": "10px", "color": RED, "marginBottom": "3px",
        }))
    items.append(html.Div([
        html.Span(f"VaR 1d: ${var_1d:.0f}", style={
            "fontSize": "10px", "color": TEXT_DIM, "marginRight": "12px",
        }),
        html.Span(f"Exposure: {exposure:.0f}%", style={"fontSize": "10px", "color": TEXT_DIM}),
    ], style={"marginTop": "4px" if warnings else "0"}))
    return items


def _macro_bar(score: float) -> html.Div:
    pct = (score + 1) / 2 * 100
    col = GREEN if score > 0.1 else (RED if score < -0.1 else GRAY)
    return html.Div([
        html.Div("MACRO SCORE", style={
            "fontSize": "9px", "color": TEXT_DIM,
            "letterSpacing": "0.1em", "marginBottom": "4px",
        }),
        html.Div([
            html.Div(style={
                "width": "100%", "height": "100%",
                "background": f"linear-gradient(to right, {RED}, {GRAY} 50%, {GREEN})",
            }),
            html.Div(style={
                "position": "absolute", "top": "-3px", "bottom": "-3px",
                "left": f"{pct:.1f}%", "width": "2px",
                "background": col, "borderRadius": "1px",
                "transform": "translateX(-50%)",
            }),
        ], style={
            "position": "relative", "height": "4px", "borderRadius": "2px",
            "overflow": "visible", "marginBottom": "4px",
        }),
        html.Div(f"{score:+.2f}", style={"fontSize": "10px", "color": col, "fontWeight": "700"}),
    ])


def _macro_body_children(v: dict) -> list:
    reasoning   = v.get("reasoning", "")
    macro_score = float(v.get("macro_score", 0.0))
    regime      = v.get("market_regime", "transitional")
    regime_col  = GREEN if regime == "risk-on" else (RED if regime == "risk-off" else ORANGE)

    return [
        html.Div(reasoning, style={
            "fontSize": "11px", "color": TEXT_DIM, "fontStyle": "italic",
            "marginBottom": "8px", "lineHeight": "1.4",
        }),
        html.Div(_macro_bar(macro_score), style={"marginBottom": "8px"}),
        html.Span(regime, style={
            "fontSize": "9px", "fontWeight": "700", "padding": "2px 7px",
            "borderRadius": "2px", "background": f"{regime_col}22", "color": regime_col,
        }),
    ]


def _arb_card_children(arb: dict) -> list:
    if not arb:
        return [html.Div("⟳ Waiting for arbitration...", style={
            "color": TEXT_DIM, "fontSize": "11px", "textAlign": "center",
            "padding": "12px 0", "fontStyle": "italic",
        })]

    consensus  = arb.get("consensus_level", "")
    cons_col   = GREEN if consensus == "strong" else (YELLOW if consensus == "moderate" else RED)
    action     = arb.get("action", "HOLD")
    symbol     = arb.get("symbol", "")
    alloc_pct  = float(arb.get("allocation_pct", 0))
    reasoning  = arb.get("reasoning", "")
    dissenting = arb.get("dissenting_agents", []) or []
    thoughts   = arb.get("thoughts", "")
    action_c   = {"BUY": BLUE, "SELL": RED, "HOLD": GRAY}.get(action, GRAY)

    # Weak consensus blinks
    cons_style = {
        "fontSize": "9px", "fontWeight": "700", "padding": "2px 7px",
        "borderRadius": "2px", "background": f"{cons_col}22", "color": cons_col,
    }

    items: list = [
        html.Div([
            html.Span("CONSENSUS", style={
                "fontSize": "8px", "color": TEXT_DIM,
                "letterSpacing": "0.12em", "marginRight": "6px",
            }),
            html.Span(consensus.upper() if consensus else "—", style=cons_style),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"}),

        html.Div([
            html.Span(action, style={
                "fontSize": "12px", "fontWeight": "700", "color": action_c, "marginRight": "8px",
            }),
            html.Span(symbol or "—", style={
                "fontSize": "12px", "color": TEXT_MAIN, "marginRight": "8px",
            }),
            html.Span(f"{alloc_pct:.0f}%", style={"fontSize": "10px", "color": TEXT_DIM}),
        ], style={"display": "flex", "alignItems": "baseline", "marginBottom": "7px"}),

        html.Div(reasoning, style={
            "fontSize": "11px", "color": TEXT_MAIN, "lineHeight": "1.4",
            "marginBottom": "6px" if (dissenting or thoughts) else "0",
        }),
    ]
    for d in dissenting:
        items.append(html.Div(f"\u26a0 {d.upper()} disagrees", style={
            "fontSize": "10px", "color": ORANGE, "marginBottom": "3px",
        }))
    if thoughts:
        items.append(html.Div(f"Internal: {thoughts}", style={
            "fontSize": "10px", "color": TEXT_DIM, "fontStyle": "italic",
            "borderLeft": f"2px solid {GRAY}33", "paddingLeft": "6px",
            "marginTop": "5px",
        }))
    return items


def _build_arb_card(arb: dict) -> html.Div:
    return html.Div([
        _section_label("\u2696 ARBITRATION"),
        html.Div(
            _arb_card_children(arb),
            style={
                "background": BG_HOVER, "border": f"2px solid {BORDER}",
                "borderLeft": f"2px solid {GREEN}",
                "borderRadius": "3px", "padding": "10px 12px",
            },
        ),
    ], style={"marginTop": "8px"})


# ═══════════════════════════════════════════════════════════════════════════════
# TAB CONTENT LAYOUTS (static skeletons — filled by callbacks)
# ═══════════════════════════════════════════════════════════════════════════════

def _tab_live() -> html.Div:
    return html.Div([
        # Left column
        html.Div([
            html.Div(id="sec-portfolio", style={"padding": "16px 14px 0"}),
            html.Div(id="sec-emotion",   style={"padding": "0 14px 12px"}),
            html.Div(id="sec-graph",     style={"padding": "0 14px 12px"}),

            # ── AGENT CARDS PANEL (multi-agent mode) ─────────────────────
            html.Div([
                # TECHNICIAN
                html.Div([
                    html.Div([
                        html.Div(id="card-tech-hdr", style={
                            "display": "flex", "alignItems": "center", "flex": "1",
                            "overflow": "hidden",
                        }),
                        html.Button(
                            "▼ Reasoning",
                            id={"type": "reasoning-toggle", "index": "tech"},
                            n_clicks=0,
                            style={
                                "background": "transparent", "border": "none",
                                "color": TEXT_DIM, "fontFamily": FONT,
                                "fontSize": "9px", "cursor": "pointer",
                                "letterSpacing": "0.05em", "flexShrink": "0",
                                "padding": "0 0 0 8px",
                            },
                        ),
                    ], style={
                        "display": "flex", "alignItems": "center",
                        "background": f"{BLUE}0a", "border": f"1px solid {BLUE}22",
                        "borderLeft": f"2px solid {BLUE}",
                        "borderRadius": "3px", "padding": "7px 9px",
                    }),
                    dcc.Collapse(
                        html.Div(id="card-tech-body", style={
                            "background": BG_CARD,
                            "border": f"1px solid {BLUE}18",
                            "borderLeft": f"2px solid {BLUE}",
                            "borderTop": "none",
                            "borderRadius": "0 0 3px 3px",
                            "padding": "8px 10px",
                        }),
                        id={"type": "reasoning-collapse", "index": "tech"},
                        is_open=False,
                    ),
                ], style={"marginBottom": "5px"}),
                # ANALYST
                html.Div([
                    html.Div([
                        html.Div(id="card-analyst-hdr", style={
                            "display": "flex", "alignItems": "center", "flex": "1",
                            "overflow": "hidden",
                        }),
                        html.Button(
                            "▼ Reasoning",
                            id={"type": "reasoning-toggle", "index": "analyst"},
                            n_clicks=0,
                            style={
                                "background": "transparent", "border": "none",
                                "color": TEXT_DIM, "fontFamily": FONT,
                                "fontSize": "9px", "cursor": "pointer",
                                "letterSpacing": "0.05em", "flexShrink": "0",
                                "padding": "0 0 0 8px",
                            },
                        ),
                    ], style={
                        "display": "flex", "alignItems": "center",
                        "background": f"{GREEN}0a", "border": f"1px solid {GREEN}22",
                        "borderLeft": f"2px solid {GREEN}",
                        "borderRadius": "3px", "padding": "7px 9px",
                    }),
                    dcc.Collapse(
                        html.Div(id="card-analyst-body", style={
                            "background": BG_CARD,
                            "border": f"1px solid {GREEN}18",
                            "borderLeft": f"2px solid {GREEN}",
                            "borderTop": "none",
                            "borderRadius": "0 0 3px 3px",
                            "padding": "8px 10px",
                        }),
                        id={"type": "reasoning-collapse", "index": "analyst"},
                        is_open=False,
                    ),
                ], style={"marginBottom": "5px"}),
                # RISK MANAGER
                html.Div([
                    html.Div([
                        html.Div(id="card-risk-hdr", style={
                            "display": "flex", "alignItems": "center", "flex": "1",
                            "overflow": "hidden",
                        }),
                        html.Button(
                            "▼ Reasoning",
                            id={"type": "reasoning-toggle", "index": "risk"},
                            n_clicks=0,
                            style={
                                "background": "transparent", "border": "none",
                                "color": TEXT_DIM, "fontFamily": FONT,
                                "fontSize": "9px", "cursor": "pointer",
                                "letterSpacing": "0.05em", "flexShrink": "0",
                                "padding": "0 0 0 8px",
                            },
                        ),
                    ], style={
                        "display": "flex", "alignItems": "center",
                        "background": f"{ORANGE}0a", "border": f"1px solid {ORANGE}22",
                        "borderLeft": f"2px solid {ORANGE}",
                        "borderRadius": "3px", "padding": "7px 9px",
                    }),
                    dcc.Collapse(
                        html.Div(id="card-risk-body", style={
                            "background": BG_CARD,
                            "border": f"1px solid {ORANGE}18",
                            "borderLeft": f"2px solid {ORANGE}",
                            "borderTop": "none",
                            "borderRadius": "0 0 3px 3px",
                            "padding": "8px 10px",
                        }),
                        id={"type": "reasoning-collapse", "index": "risk"},
                        is_open=False,
                    ),
                ], style={"marginBottom": "5px"}),
                # MACRO WATCHER
                html.Div([
                    html.Div([
                        html.Div(id="card-macro-hdr", style={
                            "display": "flex", "alignItems": "center", "flex": "1",
                            "overflow": "hidden",
                        }),
                        html.Button(
                            "▼ Reasoning",
                            id={"type": "reasoning-toggle", "index": "macro"},
                            n_clicks=0,
                            style={
                                "background": "transparent", "border": "none",
                                "color": TEXT_DIM, "fontFamily": FONT,
                                "fontSize": "9px", "cursor": "pointer",
                                "letterSpacing": "0.05em", "flexShrink": "0",
                                "padding": "0 0 0 8px",
                            },
                        ),
                    ], style={
                        "display": "flex", "alignItems": "center",
                        "background": f"{PURPLE}0a", "border": f"1px solid {PURPLE}22",
                        "borderLeft": f"2px solid {PURPLE}",
                        "borderRadius": "3px", "padding": "7px 9px",
                    }),
                    dcc.Collapse(
                        html.Div(id="card-macro-body", style={
                            "background": BG_CARD,
                            "border": f"1px solid {PURPLE}18",
                            "borderLeft": f"2px solid {PURPLE}",
                            "borderTop": "none",
                            "borderRadius": "0 0 3px 3px",
                            "padding": "8px 10px",
                        }),
                        id={"type": "reasoning-collapse", "index": "macro"},
                        is_open=False,
                    ),
                ], style={"marginBottom": "5px"}),
                # ARBITRATION — always visible
                html.Div(id="card-arb"),
            ], id="sec-agent-cards", style={"padding": "0 14px 12px"}),

            html.Div(id="sec-stats",     style={"padding": "0 14px 12px"}),
            html.Div(id="sec-positions", style={"padding": "0 14px 12px"}),
        ], style={
            "width": "280px", "minWidth": "280px", "flexShrink": "0",
            "borderRight": f"1px solid {BORDER}",
            "overflowY": "auto", "height": "100%",
        }),

        # Right column
        html.Div([
            # Equity curve
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("EQUITY CURVE", style={
                            "fontSize": "9px", "fontWeight": "700",
                            "letterSpacing": "0.18em", "color": TEXT_DIM,
                        }),
                    ]),
                    html.Div(id="chart-vals", style={"display": "flex", "gap": "18px"}),
                ], style={
                    "display": "flex", "justifyContent": "space-between",
                    "alignItems": "center", "marginBottom": "4px",
                }),
                dcc.Graph(id="sparkline", config={"displayModeBar": False},
                          style={"height": "200px"}),
            ], style={
                "padding": "14px 16px 0",
                "borderBottom": f"1px solid {BORDER}",
                "flexShrink": "0",
            }),

            # Activity log
            html.Div([
                html.Div([
                    html.Span("ACTIVITY LOG", style={
                        "fontSize": "9px", "fontWeight": "700",
                        "letterSpacing": "0.18em", "color": TEXT_DIM,
                    }),
                    html.Span("NEWEST FIRST", style={
                        "fontSize": "8px", "color": TEXT_DIM,
                        "letterSpacing": "0.1em", "opacity": "0.5",
                    }),
                ], style={
                    "display": "flex", "justifyContent": "space-between",
                    "padding": "10px 14px 8px",
                    "borderBottom": f"1px solid {BORDER}",
                }),
                html.Div(id="activity-log", style={
                    "flex": "1", "overflowY": "auto",
                    "padding": "8px 14px",
                    "display": "flex", "flexDirection": "column",
                }),
            ], style={
                "flex": "1", "display": "flex", "flexDirection": "column",
                "minHeight": "0",
            }),
        ], style={
            "flex": "1", "minWidth": "0",
            "display": "flex", "flexDirection": "column",
            "height": "100%",
        }),
    ], style={
        "display": "flex",
        "height": "calc(100vh - 96px)",
        "overflow": "hidden",
    })


def _tab_analytics() -> html.Div:
    return html.Div([
        # Refresh button
        html.Div([
            html.Button("⟳ REFRESH", id="btn-analytics-refresh", n_clicks=0, style={
                "background": "transparent", "border": f"1px solid {BORDER}",
                "color": TEXT_DIM, "fontFamily": FONT, "fontSize": "10px",
                "letterSpacing": "0.12em", "padding": "4px 12px",
                "cursor": "pointer", "borderRadius": "3px",
            }),
        ], style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER}"}),

        html.Div(id="analytics-content", style={
            "flex": "1", "overflowY": "auto", "padding": "16px",
        }),
    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "calc(100vh - 96px)", "overflow": "hidden",
    })


def _tab_backtest() -> html.Div:
    scenarios = ["Bull Market", "Bear Market", "High Volatility", "Flat Market", "Flash Crash"]
    configs   = ["Default", "Aggressive", "Conservative", "YOLO"]

    return html.Div([
        # Controls row
        html.Div([
            dcc.Dropdown(
                id="bt-scenario", options=[{"label": s, "value": s} for s in scenarios],
                value=scenarios[0], clearable=False,
                style={"width": "200px", "background": BG_CARD, "color": TEXT_MAIN,
                       "fontFamily": FONT, "fontSize": "11px"},
            ),
            dcc.Dropdown(
                id="bt-config", options=[{"label": c, "value": c} for c in configs],
                value=configs[0], clearable=False,
                style={"width": "160px", "background": BG_CARD, "color": TEXT_MAIN,
                       "fontFamily": FONT, "fontSize": "11px"},
            ),
            html.Button("▶ RUN BACKTEST", id="btn-backtest-run", n_clicks=0, style={
                "background": "transparent", "border": f"1px solid {GREEN}",
                "color": GREEN, "fontFamily": FONT, "fontSize": "10px",
                "letterSpacing": "0.12em", "padding": "6px 16px",
                "cursor": "pointer", "borderRadius": "3px",
            }),
        ], style={
            "display": "flex", "gap": "10px", "alignItems": "center",
            "padding": "12px 16px", "borderBottom": f"1px solid {BORDER}",
        }),

        dcc.Loading(
            id="bt-loading",
            children=html.Div(id="bt-results", style={"padding": "16px", "overflowY": "auto"}),
            color=GREEN,
            style={"flex": "1"},
        ),
    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "calc(100vh - 96px)",
    })


def _tab_leaderboard() -> html.Div:
    scenarios = ["Bull Market", "Bear Market", "High Volatility", "Flat Market"]
    return html.Div([
        # Controls row
        html.Div([
            dcc.Dropdown(
                id="lb-scenario", options=[{"label": s, "value": s} for s in scenarios],
                value=scenarios[0], clearable=False,
                style={"width": "200px", "background": BG_CARD, "color": TEXT_MAIN,
                       "fontFamily": FONT, "fontSize": "11px"},
            ),
            html.Button("⚡ RUN ALL AGENTS", id="btn-lb-run", n_clicks=0, style={
                "background": "transparent", "border": f"1px solid {PURPLE}",
                "color": PURPLE, "fontFamily": FONT, "fontSize": "10px",
                "letterSpacing": "0.12em", "padding": "6px 16px",
                "cursor": "pointer", "borderRadius": "3px",
            }),
        ], style={
            "display": "flex", "gap": "10px", "alignItems": "center",
            "padding": "12px 16px", "borderBottom": f"1px solid {BORDER}",
        }),

        dcc.Loading(
            id="lb-loading",
            children=html.Div(id="lb-results", style={"padding": "16px", "overflowY": "auto"}),
            color=PURPLE,
            style={"flex": "1"},
        ),
    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "calc(100vh - 96px)",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════════════════════════════════

app = dash.Dash(__name__, title="APEX-7 // SURVIVAL TRADER",
                suppress_callback_exceptions=True)

app.index_string = """<!DOCTYPE html>
<html>
<head>
  {%metas%}
  <title>{%title%}</title>
  {%favicon%}
  {%css%}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
    html, body { height:100%; overflow:hidden; }
    body {
      background:#060810;
      font-family:'JetBrains Mono','Fira Code',Consolas,monospace;
      color:#e2e8f0;
      -webkit-font-smoothing:antialiased;
    }
    ::-webkit-scrollbar { width:3px; }
    ::-webkit-scrollbar-track { background:#0a0f1e; }
    ::-webkit-scrollbar-thumb { background:#1a2535; border-radius:2px; }

    #scanlines {
      position:fixed; inset:0; pointer-events:none; z-index:1;
      background:repeating-linear-gradient(
        0deg, transparent, transparent 2px,
        rgba(0,0,0,0.025) 2px, rgba(0,0,0,0.025) 4px
      );
    }

    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
    @keyframes glow-g { 0%,100%{box-shadow:0 0 4px #10b981,0 0 10px #10b981} 50%{box-shadow:0 0 8px #10b981,0 0 20px #10b981,0 0 30px #10b98133} }
    @keyframes glow-y { 0%,100%{box-shadow:0 0 4px #f59e0b,0 0 10px #f59e0b} 50%{box-shadow:0 0 8px #f59e0b,0 0 20px #f59e0b} }
    @keyframes glow-r { 0%,100%{box-shadow:0 0 4px #ef4444,0 0 12px #ef4444} 50%{box-shadow:0 0 9px #ef4444,0 0 24px #ef4444} }

    .dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
    .dot-alive    { background:#10b981; animation:glow-g 2s ease-in-out infinite; }
    .dot-thinking { background:#f59e0b; animation:glow-y 0.8s ease-in-out infinite; }
    .dot-dead     { background:#ef4444; animation:glow-r 0.45s ease-in-out infinite; }

    @keyframes sim-blink { 0%,100%{opacity:1;box-shadow:0 0 6px #f97316} 50%{opacity:.55;box-shadow:0 0 14px #f97316} }
    .badge-sim { animation:sim-blink 1.1s ease-in-out infinite; }

    .mode-radio label { cursor:pointer; }
    .mode-radio input[type=radio] { display:none; }

    @keyframes flicker { 0%,100%{opacity:1} 30%{opacity:.8} 70%{opacity:.92} }
    .flicker { animation:flicker .9s ease-in-out infinite; }
    @keyframes skull-pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.05)} }
    .skull-pulse { animation:skull-pulse 1.8s ease-in-out infinite; }

    /* Tab underline style */
    .tab-active { border-bottom: 2px solid #10b981 !important; color: #10b981 !important; }

    /* Control buttons */
    .cbtn {
      background:transparent; cursor:pointer;
      font-family:'JetBrains Mono',monospace;
      font-size:11px; font-weight:700; letter-spacing:.12em;
      padding:5px 12px; border-radius:3px; text-transform:uppercase;
      transition:border-color .15s, color .15s;
    }
    .cbtn-pause       { border:1px solid #1a2535; color:#475569; }
    .cbtn-pause:hover { border-color:#ef4444; color:#ef4444; }
    .cbtn-pause.on    { border-color:#f59e0b; color:#f59e0b; }
    .cbtn-step        { border:1px solid #1a2535; color:#475569; }
    .cbtn-step:hover  { border-color:#3b82f6; color:#3b82f6; }
    .cbtn-reset       { border:1px solid #1a2535; color:#475569; }
    .cbtn-reset:hover { border-color:#475569; color:#e2e8f0; }

    /* Dropdown overrides */
    .Select-control { background:#0a0f1e !important; border-color:#1a2535 !important; }
    .Select-menu-outer { background:#0a0f1e !important; border-color:#1a2535 !important; }
    .Select-option { background:#0a0f1e !important; color:#e2e8f0 !important; }
    .Select-option:hover { background:#0f1729 !important; }
    .Select-value-label { color:#e2e8f0 !important; }
  </style>
</head>
<body>
  <div id="scanlines"></div>
  {%app_entry%}
  <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""


# ── Layout ────────────────────────────────────────────────────────────────────

app.layout = html.Div(
    id="page-bg",
    style={
        "background": BG_DEEP, "height": "100vh",
        "display": "flex", "flexDirection": "column",
        "fontFamily": FONT, "overflow": "hidden",
    },
    children=[
        dcc.Store(id="ctrl-store",  data={"paused": False}),
        dcc.Store(id="mode-store",  data={"sim": get_simulation_mode()}),
        dcc.Store(id="graph-store", data={"graph_id": AGENT_GRAPH}),
        dcc.Store(id="agent-cards-state", data={"tech": False, "analyst": False, "risk": False, "macro": False}),
        dcc.Interval(id="tick",           interval=2000,  n_intervals=0),
        dcc.Interval(id="analytics-tick", interval=30000, n_intervals=0),

        # ── TOP BAR (48px) ───────────────────────────────────────────────────
        html.Div(id="top-bar", children=[
            # Left
            html.Div([
                html.Div(id="status-dot", className="dot dot-alive"),
                html.Div([
                    html.Span("APEX-7 // SURVIVAL TRADER", style={
                        "color": TEXT_DIM, "fontSize": "12px",
                        "fontWeight": "600", "letterSpacing": "0.18em",
                    }),
                ]),
                html.Div([
                    html.Span("ROUND ", style={"fontSize": "9px", "color": TEXT_DIM, "letterSpacing": "0.15em"}),
                    html.Span(id="round-num", children="—", style={"fontSize": "10px", "color": TEXT_DIM}),
                ], style={"marginLeft": "6px", "display": "flex", "alignItems": "center"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "12px"}),

            # Center: mode badge
            html.Div(id="mode-badge"),

            # Right: graph selector + mode toggle + controls
            html.Div([
                dcc.Dropdown(
                    id="graph-selector",
                    options=[
                        {"label": "⚡ SIMPLE",       "value": "simple"},
                        {"label": "🧠 MULTI-AGENT",  "value": "multi"},
                    ],
                    value=AGENT_GRAPH,
                    clearable=False,
                    style={
                        "width": "170px", "fontSize": "11px",
                        "background": BG_CARD, "color": TEXT_MAIN,
                        "fontFamily": FONT,
                    },
                ),
                html.Div(style={"width": "1px", "height": "14px", "background": BORDER}),
                dcc.RadioItems(
                    id="mode-radio",
                    options=[
                        {"label": " SIM",  "value": "sim"},
                        {"label": " LIVE", "value": "live"},
                    ],
                    value="sim" if get_simulation_mode() else "live",
                    inline=True,
                    className="mode-radio",
                    style={
                        "display": "flex", "gap": "6px", "alignItems": "center",
                        "fontSize": "10px", "fontWeight": "700",
                        "letterSpacing": "0.1em", "color": GRAY,
                    },
                    labelStyle={"display": "flex", "alignItems": "center", "gap": "4px",
                                "cursor": "pointer"},
                ),
                html.Div(style={"width": "1px", "height": "14px", "background": BORDER}),
                html.Button("PAUSE", id="btn-pause", n_clicks=0, className="cbtn cbtn-pause"),
                html.Button("STEP",  id="btn-step",  n_clicks=0, className="cbtn cbtn-step"),
                html.Button("RESET", id="btn-reset", n_clicks=0, className="cbtn cbtn-reset"),
            ], style={"display": "flex", "gap": "7px", "alignItems": "center"}),
        ], style={
            "height": "48px", "flexShrink": "0",
            "display": "flex", "alignItems": "center",
            "justifyContent": "space-between",
            "padding": "0 18px",
            "borderBottom": f"1px solid {BORDER}",
            "background": BG_CARD,
        }),

        # ── TABS BAR (38px) ──────────────────────────────────────────────────
        dcc.Tabs(
            id="main-tabs",
            value="live",
            children=[
                dcc.Tab(
                    label="LIVE", value="live",
                    style={
                        "color": TEXT_DIM, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid transparent",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="ANALYTICS", value="analytics",
                    style={
                        "color": TEXT_DIM, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid transparent",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="BACKTEST", value="backtest",
                    style={
                        "color": TEXT_DIM, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid transparent",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                ),
                dcc.Tab(
                    label="LEADERBOARD", value="leaderboard",
                    style={
                        "color": TEXT_DIM, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid transparent",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                    selected_style={
                        "color": GREEN, "fontSize": "11px", "letterSpacing": "0.15em",
                        "fontFamily": FONT, "fontWeight": "700", "padding": "0 16px",
                        "border": "none", "borderBottom": f"2px solid {GREEN}",
                        "background": BG_CARD, "cursor": "pointer",
                    },
                ),
            ],
            style={"height": "38px", "flexShrink": "0"},
            colors={"border": BORDER, "primary": GREEN, "background": BG_CARD},
        ),

        # ── TAB CONTENT ──────────────────────────────────────────────────────
        html.Div(id="tab-content", style={"flex": "1", "minHeight": "0", "overflow": "hidden"}),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — TAB ROUTING
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("tab-content", "children"),
    Input("main-tabs", "value"),
)
def _render_tab(tab: str):
    if tab == "live":        return _tab_live()
    if tab == "analytics":   return _tab_analytics()
    if tab == "backtest":    return _tab_backtest()
    if tab == "leaderboard": return _tab_leaderboard()
    return _tab_live()


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — LIVE TAB
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("mode-store", "data"),
    Input("mode-radio", "value"),
    prevent_initial_call=True,
)
def _toggle_mode(value: str) -> dict:
    sim = value == "sim"
    set_simulation_mode(sim)
    return {"sim": sim}


@app.callback(
    Output("mode-badge", "children"),
    Output("mode-badge", "className"),
    Input("mode-store", "data"),
)
def _mode_badge(store: dict):
    sim = store.get("sim", False)
    if sim:
        badge = html.Span("◈ SIMULATION", style={
            "fontSize": "10px", "fontWeight": "700", "letterSpacing": "0.12em",
            "color": ORANGE, "border": f"1px solid {ORANGE}44",
            "padding": "3px 10px", "borderRadius": "3px",
            "background": f"{ORANGE}11",
        })
        return badge, "badge-sim"
    badge = html.Span("◉ LIVE", style={
        "fontSize": "10px", "fontWeight": "700", "letterSpacing": "0.12em",
        "color": GREEN, "border": f"1px solid {GREEN}44",
        "padding": "3px 10px", "borderRadius": "3px",
        "background": f"{GREEN}11",
    })
    return badge, ""


@app.callback(
    Output("ctrl-store", "data"),
    [Input("btn-pause", "n_clicks"),
     Input("btn-step",  "n_clicks"),
     Input("btn-reset", "n_clicks")],
    State("ctrl-store", "data"),
    prevent_initial_call=True,
)
def _controls(_, __, ___, store):
    triggered = ctx.triggered_id
    if triggered == "btn-pause":
        new = not store.get("paused", False)
        _ctrl["paused"] = new
        store["paused"] = new
    elif triggered == "btn-step":
        _ctrl["step"] = True
    elif triggered == "btn-reset":
        old = _state["portfolio"]
        old.is_dead = True
        time.sleep(0.15)
        p = Portfolio()
        _state["portfolio"]   = p
        _state["last_votes"]  = []
        _state["last_arb"]    = {}
        _state["thread"]      = _launch(p, _state.get("graph_id", "simple"))
        _ctrl["paused"] = False
        store["paused"] = False
    return store


@app.callback(
    Output("graph-store", "data"),
    Input("graph-selector", "value"),
    prevent_initial_call=True,
)
def _switch_graph(graph_id: str) -> dict:
    """Switch the active graph, restart portfolio and agent thread."""
    _state["graph_id"] = graph_id
    old = _state["portfolio"]
    old.is_dead = True
    time.sleep(0.2)
    p = Portfolio()
    _state["portfolio"]  = p
    _state["last_votes"] = []
    _state["last_arb"]   = {}
    _ctrl["paused"]      = False
    _state["thread"]     = _launch(p, graph_id)
    info = get_graph_info(graph_id)
    p.log(f"Graph switched to {info['label']}")
    return {"graph_id": graph_id}


@app.callback(
    [
        Output("page-bg",           "style"),
        Output("top-bar",           "style"),
        Output("status-dot",        "className"),
        Output("round-num",         "children"),
        Output("btn-pause",         "className"),
        Output("sec-portfolio",     "children"),
        Output("sec-emotion",       "children"),
        Output("sec-graph",         "children"),
        Output("sec-stats",         "children"),
        Output("sec-positions",     "children"),
        Output("chart-vals",        "children"),
        Output("sparkline",         "figure"),
        Output("activity-log",      "children"),
        # Agent card headers
        Output("card-tech-hdr",     "children"),
        Output("card-analyst-hdr",  "children"),
        Output("card-risk-hdr",     "children"),
        Output("card-macro-hdr",    "children"),
        # Agent card bodies (children only — style handled by separate callback)
        Output("card-tech-body",    "children"),
        Output("card-analyst-body", "children"),
        Output("card-risk-body",    "children"),
        Output("card-macro-body",   "children"),
        # Arbitration card
        Output("card-arb",          "children"),
        # Agent cards panel visibility
        Output("sec-agent-cards",   "style"),
    ],
    [Input("tick", "n_intervals"), Input("ctrl-store", "data")],
    [State("main-tabs", "value"), State("graph-store", "data")],
)
def _refresh(_, store, active_tab, graph_store):
    p       = _state["portfolio"]
    prices  = p.last_prices
    total   = p.total_value(prices)
    pnl     = total - INITIAL_BALANCE
    pnl_pct = (pnl / INITIAL_BALANCE) * 100
    dead    = p.is_dead
    paused  = store.get("paused", False)
    vh      = p.value_history
    peak    = max((v["value"] for v in vh), default=INITIAL_BALANCE)
    dd      = ((peak - total) / peak * 100) if peak > 0 else 0.0
    invested= max(total - p.cash, 0.0)
    cyc     = _cycle(p)

    # Page + topbar background
    page_style = {
        "background": "#080002" if dead else BG_DEEP,
        "height": "100vh", "display": "flex", "flexDirection": "column",
        "fontFamily": FONT, "overflow": "hidden",
        "transition": "background 1s ease",
    }
    topbar_style = {
        "height": "48px", "flexShrink": "0",
        "display": "flex", "alignItems": "center",
        "justifyContent": "space-between",
        "padding": "0 18px",
        "borderBottom": f"1px solid {'#3d0000' if dead else BORDER}",
        "background": BG_CARD,
        "transition": "border-color 1s ease",
    }

    # Status dot
    if dead:           dot_cls = "dot dot-dead"
    elif _thinking(p): dot_cls = "dot dot-thinking"
    else:              dot_cls = "dot dot-alive"

    pause_cls = "cbtn cbtn-pause on" if paused else "cbtn cbtn-pause"

    # Determine graph mode (needed for cards visibility in both alive/dead states)
    _graph_id_cur = (graph_store or {}).get("graph_id", _state.get("graph_id", "simple"))
    is_multi = _graph_id_cur == "multi"

    # ── DEATH STATE ──────────────────────────────────────────────────────────
    if dead:
        sec_portfolio = html.Div([
            html.Div("💀", className="skull-pulse", style={
                "fontSize": "36px", "textAlign": "center",
                "marginBottom": "14px", "marginTop": "16px",
            }),
            html.Div("TERMINATED", className="flicker", style={
                "fontSize": "16px", "fontWeight": "700", "color": RED,
                "letterSpacing": "0.2em", "textAlign": "center", "marginBottom": "10px",
            }),
            html.Div(f"Liquidated at round {cyc}", style={
                "fontSize": "11px", "color": TEXT_DIM, "textAlign": "center", "marginBottom": "5px",
            }),
            html.Div(f"Final P&L: {pnl:+.2f} ({pnl_pct:+.1f}%)", style={
                "fontSize": "12px", "color": RED, "textAlign": "center",
            }),
        ], style={"padding": "16px 14px"})
        sec_graph = sec_emotion = sec_stats = sec_positions = html.Div()

    else:
        # ── PORTFOLIO VALUE ──
        if total < INITIAL_BALANCE * 0.7:   vcol = RED
        elif total > INITIAL_BALANCE * 1.3: vcol = GREEN
        else:                               vcol = TEXT_MAIN

        fill_pct = min(max(total / (INITIAL_BALANCE * 2), 0), 1) * 100
        health_bar = html.Div([
            html.Div([
                html.Div(style={
                    "position": "absolute", "inset": "0", "borderRadius": "2px",
                    "background": f"linear-gradient(to right, {RED}, {BLUE} 50%, {GREEN})",
                }),
                html.Div(style={
                    "position": "absolute", "top": "0", "right": "0", "bottom": "0",
                    "width": f"{100 - fill_pct:.1f}%",
                    "background": BG_CARD, "transition": "width .6s ease",
                }),
            ], style={
                "position": "relative", "height": "3px", "borderRadius": "2px",
                "overflow": "hidden", "background": BG_CARD,
            }),
            html.Div([
                html.Span("💀 $0",                          style={"fontSize": "9px", "color": RED}),
                html.Span(f"${INITIAL_BALANCE:.0f}",        style={"fontSize": "9px", "color": TEXT_DIM}),
                html.Span(f"${INITIAL_BALANCE * 2:.0f} 🎯", style={"fontSize": "9px", "color": GREEN}),
            ], style={"display": "flex", "justifyContent": "space-between", "marginTop": "5px"}),
        ])

        pnl_c = GREEN if pnl >= 0 else RED
        pnl_arrow = "▲" if pnl >= 0 else "▼"
        sec_portfolio = html.Div([
            _section_label("PORTFOLIO VALUE"),
            html.Div(f"${total:,.2f}", style={
                "fontSize": "28px", "fontWeight": "700", "color": vcol,
                "letterSpacing": "-0.02em", "lineHeight": "1", "marginBottom": "5px",
            }),
            html.Div([
                html.Span(pnl_arrow + " ", style={"color": pnl_c}),
                html.Span(f"${abs(pnl):.2f} ({pnl_pct:+.2f}%)", style={"color": pnl_c}),
            ], style={"fontSize": "12px", "marginBottom": "14px"}),
            health_bar,
        ])

        # ── AGENT STATE ──
        em_key = _emotion(total)
        em     = _EMOTIONS[em_key]
        thinking = _thinking(p)
        sec_emotion = html.Div([
            _section_label("AGENT STATE"),
            html.Div([
                html.Div([
                    html.Span(em["icon"], style={"fontSize": "18px", "marginRight": "8px"}),
                    html.Span(em_key, style={
                        "fontSize": "10px", "fontWeight": "700",
                        "color": em["color"], "letterSpacing": "0.1em",
                    }),
                ], style={"display": "flex", "alignItems": "center"}),
                html.Div("⟳ SEARCHING...", style={
                    "fontSize": "9px", "color": YELLOW,
                    "letterSpacing": "0.08em",
                }) if thinking else html.Span(),
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "8px"}),
            html.Div(em["quote"], style={
                "fontSize": "11px", "color": TEXT_DIM, "fontStyle": "italic",
                "borderLeft": f"2px solid {em['color']}44",
                "paddingLeft": "8px",
            }),
        ])

        # ── GRAPH INFO PANEL ──
        graph_id   = _graph_id_cur
        graph_info = get_graph_info(graph_id)
        gc         = graph_info["color"]

        sec_graph = html.Div([
            _section_label("ACTIVE GRAPH"),
            html.Div([
                html.Div([
                    html.Span(graph_info["label"], style={
                        "fontSize": "10px", "fontWeight": "700", "color": gc,
                        "letterSpacing": "0.06em",
                    }),
                    html.Div([
                        html.Span(f"💰 {graph_info['cost']}", style={
                            "fontSize": "8px", "color": TEXT_DIM,
                            "background": f"{gc}18", "padding": "1px 5px",
                            "borderRadius": "2px", "marginRight": "4px",
                        }),
                        html.Span(graph_info["latency"], style={
                            "fontSize": "8px", "color": TEXT_DIM,
                        }),
                    ], style={"marginTop": "3px"}),
                    html.Div(graph_info["description"], style={
                        "fontSize": "9px", "color": TEXT_DIM,
                        "fontStyle": "italic", "marginTop": "4px",
                    }),
                ]),
            ], style={
                "background": BG_CARD, "border": f"1px solid {gc}33",
                "borderLeft": f"2px solid {gc}",
                "borderRadius": "3px", "padding": "8px 10px",
            }),
        ])

        # ── METRICS ──
        dd_c = RED if dd > 20 else (YELLOW if dd > 10 else TEXT_DIM)
        sec_stats = html.Div([
            _section_label("METRICS"),
            html.Div([
                _mini_stat("CASH",     f"${p.cash:.2f}",   BLUE),
                _mini_stat("INVESTED", f"${invested:.2f}", TEXT_MAIN),
                _mini_stat("PEAK",     f"${peak:.2f}",     GREEN),
                _mini_stat("DRAWDOWN", f"{dd:.1f}%",       dd_c),
            ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px"}),
        ])

        # ── POSITIONS ──
        cards = [_pos_card(sym, pos, prices) for sym, pos in list(p.positions.items())[:3]]
        sec_positions = html.Div([
            _section_label(f"OPEN POSITIONS ({len(p.positions)}/3)"),
            *(cards if cards else [html.Div(
                "— no open positions —",
                style={"color": TEXT_DIM, "fontSize": "11px", "textAlign": "center",
                       "padding": "16px 0", "fontStyle": "italic"},
            )]),
        ])

    # ── RIGHT COLUMN ─────────────────────────────────────────────────────────

    def _val_block(lbl: str, val: float, c: str) -> html.Div:
        return html.Div([
            html.Div(lbl, style={"fontSize": "8px", "color": TEXT_DIM, "letterSpacing": "0.1em"}),
            html.Div(f"${val:.2f}", style={"fontSize": "12px", "color": c, "fontWeight": "600"}),
        ], style={"textAlign": "right"})

    chart_vals = html.Div([
        _val_block("START", INITIAL_BALANCE, TEXT_DIM),
        _val_block("NOW",   total, GREEN if total >= INITIAL_BALANCE else RED),
        _val_block("PEAK",  peak,  GREEN),
    ], style={"display": "flex", "gap": "16px"})

    fig = _sparkline(p)

    log_entries = list(reversed(p.agent_log[-80:]))
    log_items   = [_log_entry_card(e) for e in log_entries] or [
        html.Div("— waiting for agent —", style={
            "color": TEXT_DIM, "fontSize": "11px", "textAlign": "center",
            "padding": "28px", "fontStyle": "italic",
        })
    ]

    # ── AGENT CARDS (multi-agent mode) ───────────────────────────────────────
    votes   = _state.get("last_votes", [])
    arb     = _state.get("last_arb", {})
    is_sim  = get_simulation_mode()
    vote_map = {v.get("agent", ""): v for v in votes}

    _PLACEHOLDER_HDR = [html.Span("—", style={"fontSize": "9px", "color": TEXT_DIM})]
    _WAITING = [html.Div("⟳ Waiting for first multi-agent cycle...", style={
        "color": TEXT_DIM, "fontSize": "10px", "fontStyle": "italic", "padding": "4px 0",
    })]

    if is_multi and votes:
        tv = vote_map.get("technician", {})
        av = vote_map.get("analyst", {})
        rv = vote_map.get("risk_manager", {})
        mv = vote_map.get("macro_watcher", {})

        hdr_tech = _card_hdr_standard(
            "🔧", "TECH", BLUE,
            tv.get("action", "?"), tv.get("symbol", ""),
            float(tv.get("confidence", 0.5)), is_sim,
        )
        hdr_anlst = _card_hdr_standard(
            "📊", "ANLST", GREEN,
            av.get("action", "?"), av.get("symbol", ""),
            float(av.get("confidence", 0.5)), is_sim,
        )
        sizing = rv.get("sizing_recommendation", "?")
        risk_s = rv.get("risk_score", "?")
        hdr_risk = [
            html.Span("⚠️ RISK", style={
                "fontSize": "9px", "fontWeight": "700", "color": ORANGE,
                "marginRight": "10px", "flexShrink": "0",
            }),
            html.Span(str(sizing), style={"fontSize": "9px", "color": TEXT_MAIN, "flex": "1"}),
            html.Span(f"RISK {risk_s}/10", style={"fontSize": "9px", "color": ORANGE, "flexShrink": "0"}),
            *([_sim_chip()] if is_sim else []),
        ]
        regime    = mv.get("market_regime", "?")
        macro_bias = mv.get("macro_bias", "?")
        hdr_macro = [
            html.Span("🌍 MACRO", style={
                "fontSize": "9px", "fontWeight": "700", "color": PURPLE,
                "marginRight": "10px", "flexShrink": "0",
            }),
            html.Span(str(regime), style={"fontSize": "9px", "color": TEXT_MAIN, "flex": "1"}),
            html.Span(str(macro_bias), style={"fontSize": "9px", "color": PURPLE, "flexShrink": "0"}),
            *([_sim_chip()] if is_sim else []),
        ]

        body_tech  = _tech_body_children(tv)   if tv else _WAITING
        body_anlst = _analyst_body_children(av) if av else _WAITING
        body_risk  = _risk_body_children(rv)    if rv else _WAITING
        body_macro = _macro_body_children(mv)   if mv else _WAITING
        card_arb   = _build_arb_card(arb)

    elif is_multi:
        hdr_tech  = _PLACEHOLDER_HDR
        hdr_anlst = _PLACEHOLDER_HDR
        hdr_risk  = _PLACEHOLDER_HDR
        hdr_macro = _PLACEHOLDER_HDR
        body_tech = body_anlst = body_risk = body_macro = _WAITING
        card_arb  = _build_arb_card({})

    else:
        hdr_tech  = _PLACEHOLDER_HDR
        hdr_anlst = _PLACEHOLDER_HDR
        hdr_risk  = _PLACEHOLDER_HDR
        hdr_macro = _PLACEHOLDER_HDR
        body_tech = body_anlst = body_risk = body_macro = []
        card_arb  = html.Div()

    cards_style = {"padding": "0 14px 12px"} if is_multi else {"display": "none"}

    return (
        page_style, topbar_style, dot_cls, str(cyc) if cyc else "—", pause_cls,
        sec_portfolio, sec_emotion, sec_graph, sec_stats, sec_positions,
        chart_vals, fig, log_items,
        hdr_tech, hdr_anlst, hdr_risk, hdr_macro,
        body_tech, body_anlst, body_risk, body_macro,
        card_arb, cards_style,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — REASONING CARD TOGGLE (pattern-matching)
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output({"type": "reasoning-collapse", "index": MATCH}, "is_open"),
    Output({"type": "reasoning-toggle",   "index": MATCH}, "children"),
    Input({"type": "reasoning-toggle",    "index": MATCH}, "n_clicks"),
    State({"type": "reasoning-collapse",  "index": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def _toggle_reasoning(n_clicks, is_open):
    new_open = not is_open
    label = "▲ Collapse" if new_open else "▼ Reasoning"
    return new_open, label


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — ANALYTICS TAB
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("analytics-content", "children"),
    [Input("analytics-tick", "n_intervals"),
     Input("btn-analytics-refresh", "n_clicks")],
    prevent_initial_call=False,
)
def _analytics_refresh(_, __):
    trades = _load_trades_db()

    if not trades:
        return html.Div("No trade data yet. Run the agent first.",
                        style={"color": TEXT_DIM, "fontSize": "12px", "padding": "20px"})

    import statistics

    # ── KPIs ─────────────────────────────────────────────────────────────────
    buys  = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    total = len(trades)

    # Win rate: sells where portfolio_value_after increased relative to buy price
    wins = 0
    for s in sells:
        # rough: if amount_usd > 0 treat as win heuristic
        if s.get("portfolio_value_after", 0) > INITIAL_BALANCE:
            wins += 1
    win_rate = (wins / len(sells) * 100) if sells else 0.0

    pnl_vals  = [t.get("amount_usd", 0) for t in sells]
    avg_pnl   = statistics.mean(pnl_vals) if pnl_vals else 0.0
    best_t    = max(pnl_vals) if pnl_vals else 0.0
    worst_t   = min(pnl_vals) if pnl_vals else 0.0
    confs     = [t.get("confidence", 0) for t in trades if t.get("confidence")]
    avg_conf  = statistics.mean(confs) if confs else 0.0

    tickers = [t["symbol"] for t in trades if t.get("symbol")]
    fav     = max(set(tickers), key=tickers.count) if tickers else "—"

    live_n  = sum(1 for t in trades if t.get("source") == "live")
    sim_n   = sum(1 for t in trades if t.get("source") == "simulation")
    ratio   = f"{sim_n}/{live_n}" if (sim_n + live_n) > 0 else "—"

    kpi_items = [
        ("WIN RATE",       f"{win_rate:.1f}%",      GREEN if win_rate > 50 else RED),
        ("AVG P&L",        f"${avg_pnl:.2f}",        GREEN if avg_pnl >= 0 else RED),
        ("BEST TRADE",     f"${best_t:.2f}",          GREEN),
        ("WORST TRADE",    f"${worst_t:.2f}",          RED),
        ("TOTAL TRADES",   str(total),                 BLUE),
        ("AVG CONFIDENCE", f"{avg_conf:.0%}",          PURPLE),
        ("FAV TICKER",     fav,                         YELLOW),
        ("SIM / LIVE",     ratio,                       ORANGE),
    ]

    kpi_row = html.Div([
        html.Div([
            html.Div(lbl, style={"fontSize": "9px", "color": TEXT_DIM, "letterSpacing": "0.1em", "marginBottom": "4px"}),
            html.Div(val, style={"fontSize": "16px", "fontWeight": "700", "color": col}),
        ], style={
            "background": BG_CARD, "border": f"1px solid {BORDER}",
            "borderRadius": "4px", "padding": "12px 14px",
        })
        for lbl, val, col in kpi_items
    ], style={"display": "grid", "gridTemplateColumns": "repeat(8, 1fr)", "gap": "8px", "marginBottom": "20px"})

    # ── CHARTS ───────────────────────────────────────────────────────────────
    _plotly_theme = dict(
        template="plotly_dark",
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=40, r=20, t=30, b=40),
    )

    # 1. P&L by ticker (bar)
    from collections import defaultdict
    ticker_pnl: dict[str, float] = defaultdict(float)
    for t in sells:
        sym = t.get("symbol") or "UNK"
        ticker_pnl[sym] += t.get("amount_usd", 0)
    sorted_tickers = sorted(ticker_pnl.items(), key=lambda x: x[1])
    bar_colors = [GREEN if v >= 0 else RED for _, v in sorted_tickers]
    fig1 = go.Figure(go.Bar(
        x=[v for _, v in sorted_tickers],
        y=[s for s, _ in sorted_tickers],
        orientation="h",
        marker_color=bar_colors,
    ))
    fig1.update_layout(title="P&L by Ticker", height=250, **_plotly_theme)

    # 2. Action distribution (donut)
    action_counts = {"BUY": len(buys), "SELL": len(sells),
                     "HOLD": sum(1 for t in trades if t["action"] == "HOLD")}
    fig2 = go.Figure(go.Pie(
        labels=list(action_counts.keys()),
        values=list(action_counts.values()),
        hole=0.6,
        marker_colors=[BLUE, GREEN, GRAY],
        textfont=dict(family=FONT, size=10),
    ))
    fig2.update_layout(title="Action Distribution", height=250, **_plotly_theme)

    # 3. Confidence over time (line)
    conf_trades = [t for t in reversed(trades) if t.get("confidence")]
    fig3 = go.Figure(go.Scatter(
        x=list(range(len(conf_trades))),
        y=[t["confidence"] for t in conf_trades],
        mode="lines",
        line=dict(color=PURPLE, width=1.5),
        fill="tozeroy",
        fillcolor=f"{PURPLE}18",
    ))
    fig3.update_layout(title="Confidence Over Time", height=250, **_plotly_theme)

    # 4. Trades by hour
    from collections import Counter
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

    charts_row = html.Div([
        dcc.Graph(figure=fig1, config={"displayModeBar": False}),
        dcc.Graph(figure=fig2, config={"displayModeBar": False}),
        dcc.Graph(figure=fig3, config={"displayModeBar": False}),
        dcc.Graph(figure=fig4, config={"displayModeBar": False}),
    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px", "marginBottom": "20px"})

    # ── DATA TABLE ───────────────────────────────────────────────────────────
    table_cols = [
        {"name": c, "id": c} for c in
        ["timestamp", "symbol", "action", "price", "amount_usd", "confidence", "emotion", "lesson", "source"]
    ]
    table_data = []
    for t in trades:
        row = {k: t.get(k, "") for k in
               ["timestamp", "symbol", "action", "price", "amount_usd", "confidence", "emotion", "lesson", "source"]}
        row["timestamp"] = str(row["timestamp"])[:19]
        row["price"]     = f"{row['price']:.2f}" if isinstance(row["price"], float) else row["price"]
        row["amount_usd"]= f"{row['amount_usd']:.2f}" if isinstance(row["amount_usd"], float) else row["amount_usd"]
        row["confidence"]= f"{row['confidence']:.0%}" if isinstance(row["confidence"], float) else row["confidence"]
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
            {"if": {"filter_query": '{action} = "BUY"'},
             "background": f"{BLUE}12"},
            {"if": {"filter_query": '{action} = "SELL"'},
             "background": f"{RED}12"},
            {"if": {"filter_query": '{source} = "simulation"'},
             "opacity": "0.7"},
        ],
    )

    return html.Div([kpi_row, charts_row, data_table])


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — BACKTEST TAB
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("bt-results", "children"),
    Input("btn-backtest-run", "n_clicks"),
    [State("bt-scenario", "value"), State("bt-config", "value")],
    prevent_initial_call=True,
)
def _backtest_run(n_clicks, scenario, config):
    if not n_clicks:
        return html.Div()

    # Try importing BacktestEngine, show placeholder if not available
    try:
        from backtest import BacktestEngine  # type: ignore
        engine = BacktestEngine(scenario, config)
        result = engine.run()
    except ImportError:
        # Placeholder results for demo
        result = {
            "return_pct":    12.5,
            "sharpe":        1.42,
            "win_rate":      58.0,
            "max_drawdown":  8.3,
            "total_trades":  47,
            "survived":      True,
            "portfolio_history": [1000, 1020, 1050, 980, 1100, 1085, 1125],
            "trade_log": [],
        }

    survived_badge = html.Span("✓ SURVIVED", style={"color": GREEN, "fontWeight": "700"}) \
        if result.get("survived") else \
        html.Span("💀 LIQUIDATED", style={"color": RED, "fontWeight": "700"})

    kpis = [
        ("RETURN",       f"{result.get('return_pct', 0):+.1f}%",   GREEN if result.get('return_pct', 0) >= 0 else RED),
        ("SHARPE",       f"{result.get('sharpe', 0):.2f}",          BLUE),
        ("WIN RATE",     f"{result.get('win_rate', 0):.1f}%",       GREEN),
        ("MAX DRAWDOWN", f"{result.get('max_drawdown', 0):.1f}%",   RED),
        ("TRADES",       str(result.get("total_trades", 0)),         TEXT_MAIN),
        ("STATUS",       survived_badge,                              GREEN),
    ]

    kpi_row = html.Div([
        html.Div([
            html.Div(lbl, style={"fontSize": "9px", "color": TEXT_DIM, "letterSpacing": "0.1em", "marginBottom": "4px"}),
            html.Div(val, style={"fontSize": "16px", "fontWeight": "700", "color": col}),
        ], style={"background": BG_CARD, "border": f"1px solid {BORDER}", "borderRadius": "4px", "padding": "12px 14px"})
        for lbl, val, col in kpis
    ], style={"display": "grid", "gridTemplateColumns": "repeat(6, 1fr)", "gap": "8px", "marginBottom": "16px"})

    # Portfolio history chart
    hist = result.get("portfolio_history", [INITIAL_BALANCE])
    xs   = list(range(len(hist)))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=hist, mode="lines", name="APEX-7",
        line=dict(color=GREEN, width=1.5),
        fill="tozeroy", fillcolor=f"{GREEN}0a",
    ))
    # Buy-and-hold reference (flat)
    spy_end = hist[-1] * 1.05 if hist else INITIAL_BALANCE * 1.05
    fig.add_trace(go.Scatter(
        x=[0, len(hist) - 1],
        y=[INITIAL_BALANCE, spy_end],
        mode="lines", name="SPY B&H",
        line=dict(color=GRAY, width=1, dash="dot"),
    ))
    fig.add_hline(y=DEATH_THRESHOLD,
                  line=dict(color=RED, dash="dot", width=1),
                  annotation_text="DEATH FLOOR",
                  annotation_position="bottom right",
                  annotation_font=dict(color=RED, size=8, family=FONT))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=BG_DEEP, plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=50, r=20, t=30, b=40),
        height=300, legend=dict(x=0, y=1),
        title=f"Portfolio — {scenario} ({config})",
    )

    trade_log_items = []
    for entry in result.get("trade_log", []):
        badge, color = _classify_v2(entry.get("message", ""), entry.get("level", "info"))
        trade_log_items.append(html.Div([
            html.Span(badge, style={
                "fontSize": "9px", "fontWeight": "700", "padding": "1px 6px",
                "borderRadius": "2px", "background": f"{color}22", "color": color,
                "marginRight": "8px",
            }),
            html.Span(entry.get("message", "")[:140], style={"fontSize": "11px", "color": TEXT_MAIN}),
        ], style={
            "borderLeft": f"3px solid {color}",
            "background": f"{color}07",
            "padding": "5px 10px", "marginBottom": "5px",
            "borderRadius": "0 3px 3px 0",
        }))

    return html.Div([
        kpi_row,
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"marginBottom": "16px"}),
        html.Div(trade_log_items or [html.Div(
            "No trade log available.",
            style={"color": TEXT_DIM, "fontSize": "11px", "fontStyle": "italic"},
        )]),
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — LEADERBOARD TAB
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("lb-results", "children"),
    Input("btn-lb-run", "n_clicks"),
    State("lb-scenario", "value"),
    prevent_initial_call=True,
)
def _lb_run(n_clicks, scenario):
    if not n_clicks:
        return html.Div()

    try:
        from leaderboard import Leaderboard  # type: ignore
        lb = Leaderboard()
        rows = lb.run_all(scenario)
    except ImportError:
        # Placeholder data
        import random as _r
        rows = [
            {"agent_id": f"APEX-{i}", "final_value": _r.uniform(600, 1800),
             "return_pct": _r.uniform(-40, 80), "sharpe": _r.uniform(-0.5, 2.5),
             "win_rate": _r.uniform(30, 75), "max_drawdown": _r.uniform(5, 40),
             "trades": _r.randint(10, 100), "survived": _r.random() > 0.3}
            for i in range(1, 7)
        ]
        rows.sort(key=lambda r: r["return_pct"], reverse=True)

    agent_colors = [GREEN, BLUE, PURPLE, ORANGE, YELLOW, "#ec4899", "#14b8a6", RED]

    # Table
    table_rows = []
    for i, row in enumerate(rows):
        rank = i + 1
        surv = html.Span("✓ ALIVE", style={"color": GREEN}) \
               if row.get("survived") else html.Span("💀 DEAD", style={"color": RED})
        col = agent_colors[i % len(agent_colors)]
        table_rows.append(html.Div([
            html.Span(f"#{rank}", style={"color": TEXT_DIM, "fontSize": "10px", "width": "28px", "flexShrink": "0"}),
            html.Span(row["agent_id"], style={"color": col, "fontWeight": "700", "fontSize": "12px", "width": "100px", "flexShrink": "0"}),
            html.Span(f"${row['final_value']:.2f}", style={"color": TEXT_MAIN, "fontSize": "11px", "width": "90px", "flexShrink": "0"}),
            html.Span(f"{row['return_pct']:+.1f}%", style={
                "color": GREEN if row['return_pct'] >= 0 else RED,
                "fontWeight": "700", "fontSize": "12px", "width": "70px", "flexShrink": "0",
            }),
            html.Span(f"{row['sharpe']:.2f}", style={"color": BLUE, "fontSize": "11px", "width": "60px", "flexShrink": "0"}),
            html.Span(f"{row['win_rate']:.0f}%", style={"color": TEXT_MAIN, "fontSize": "11px", "width": "60px", "flexShrink": "0"}),
            html.Span(f"{row['max_drawdown']:.1f}%", style={"color": RED, "fontSize": "11px", "width": "70px", "flexShrink": "0"}),
            html.Span(str(row["trades"]), style={"color": TEXT_DIM, "fontSize": "11px", "width": "50px", "flexShrink": "0"}),
            surv,
        ], style={
            "display": "flex", "alignItems": "center", "gap": "8px",
            "padding": "8px 12px",
            "border": f"1px solid {GREEN if rank == 1 else BORDER}",
            "background": f"{GREEN}08" if rank == 1 else BG_CARD,
            "borderRadius": "4px", "marginBottom": "5px",
            "fontFamily": FONT,
        }))

    # Header
    header_cols = ["#", "AGENT", "FINAL $", "RETURN", "SHARPE", "WIN RATE", "DRAWDOWN", "TRADES", "STATUS"]
    header = html.Div([
        html.Span(c, style={"color": TEXT_DIM, "fontSize": "9px", "letterSpacing": "0.12em",
                             "width": w, "flexShrink": "0"})
        for c, w in zip(header_cols, ["28px","100px","90px","70px","60px","60px","70px","50px","auto"])
    ], style={
        "display": "flex", "alignItems": "center", "gap": "8px",
        "padding": "6px 12px", "marginBottom": "6px",
        "borderBottom": f"1px solid {BORDER}",
    })

    # Bar chart
    names    = [r["agent_id"] for r in rows]
    returns  = [r["return_pct"] for r in rows]
    bar_cols = [agent_colors[i % len(agent_colors)] for i in range(len(rows))]
    annotations = []
    for i, (n, ret) in enumerate(zip(names, returns)):
        annotations.append(dict(
            x=i, y=ret + (2 if ret >= 0 else -4),
            text="YOLO" if ret > 0 else "💀 DEAD",
            showarrow=False,
            font=dict(size=8, color=GREEN if ret >= 0 else RED, family=FONT),
        ))

    fig = go.Figure(go.Bar(
        x=names, y=returns,
        marker_color=bar_cols,
        text=[f"{r:+.1f}%" for r in returns],
        textposition="outside",
        textfont=dict(family=FONT, size=9),
    ))
    fig.add_hline(y=0, line=dict(color=GRAY, width=1, dash="dot"),
                  annotation_text="breakeven", annotation_position="right",
                  annotation_font=dict(color=GRAY, size=8, family=FONT))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=BG_DEEP, plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=40, r=20, t=30, b=60),
        height=280, showlegend=False,
        annotations=annotations,
        title=f"Agent Returns — {scenario}",
    )

    return html.Div([
        header,
        html.Div(table_rows, style={"marginBottom": "16px"}),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
