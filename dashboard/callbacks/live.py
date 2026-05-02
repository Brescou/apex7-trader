"""APEX-7 — Live tab callbacks + tab routing (5 tabs; HEATMAP/LEADERBOARD removed)."""

from dash import Input, Output, State, ctx, html, no_update, MATCH
from dash.exceptions import PreventUpdate

from agents.shared.nodes import (
    _db_read,
    get_llm_degradation_status,
    get_runtime_mode,
    get_simulation_mode,
    set_paper_mode,
    set_simulation_mode,
)
from config import INITIAL_BALANCE
from core.data import Portfolio
from dashboard.controller import _controller_lock, _ctrl, _launch, _state
from dashboard.layout import (
    _EMOTIONS,
    _agent_eval_metrics,
    _analyst_body_children,
    _build_arb_card,
    _card_hdr_standard,
    _cycle,
    _emotion,
    _live_agent_eval_banner,
    _load_agent_memory,
    _log_entry_card,
    _macro_body_children,
    _mini_stat,
    _pos_card,
    _risk_body_children,
    _section_label,
    _sim_chip,
    _sparkline,
    _tech_body_children,
    _thinking,
)
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BLUE,
    BORDER,
    FONT,
    GREEN,
    ORANGE,
    PURPLE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    YELLOW,
    app,
)

_LLM_DEGRADATION_LABELS = {
    "circuit_breaker": "circuit breaker",
    "token_budget": "token budget",
}


def _mode_palette(mode: str) -> tuple[str, str, str]:
    """Return ``(label, color, css_class)`` for a given runtime mode."""
    mode = (mode or "live").lower()
    if mode == "sim":
        return "◈ SIMULATION", ORANGE, "badge-sim"
    if mode == "paper":
        return "◐ PAPER", BLUE, "badge-paper"
    return "◉ LIVE", GREEN, ""


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — TAB ROUTING
# ═══════════════════════════════════════════════════════════════════════════════


_TABS = ["live", "analytics", "backtest", "agents", "terminal"]
_TAB_SHOW = {"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "block"}
_TAB_HIDE = {"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"}


@app.callback(
    Output("tab-live", "style"),
    Output("tab-analytics", "style"),
    Output("tab-backtest", "style"),
    Output("tab-agents", "style"),
    Output("tab-terminal", "style"),
    Input("main-tabs", "value"),
    prevent_initial_call=True,
)
def _show_tab(tab: str):
    return [_TAB_SHOW if t == tab else _TAB_HIDE for t in _TABS]


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — LIVE TAB
# ═══════════════════════════════════════════════════════════════════════════════


@app.callback(
    Output("mode-store", "data"),
    Input("mode-radio", "value"),
    prevent_initial_call=True,
)
def _toggle_mode(value: str) -> dict:
    """Switch between live / paper / sim. Mutually exclusive backend toggles."""
    mode = (value or "live").lower()
    if mode == "paper":
        set_paper_mode(True)
    elif mode == "sim":
        set_simulation_mode(True)
    else:
        # Live: clear both flags.
        set_paper_mode(False)
        set_simulation_mode(False)
    return {"mode": get_runtime_mode()}


@app.callback(
    Output("mode-badge", "children"),
    Output("mode-badge", "className"),
    Input("mode-store", "data"),
)
def _mode_badge(store: dict):
    mode = (store or {}).get("mode", get_runtime_mode())
    label, color, css_class = _mode_palette(mode)
    badge = html.Span(
        label,
        style={
            "fontSize": "10px",
            "fontWeight": "700",
            "letterSpacing": "0.12em",
            "color": color,
            "border": f"1px solid {color}44",
            "padding": "3px 10px",
            "borderRadius": "3px",
            "background": f"{color}11",
        },
    )
    return badge, css_class


@app.callback(
    Output("ctrl-store", "data"),
    [Input("btn-pause", "n_clicks"), Input("btn-step", "n_clicks"), Input("btn-reset", "n_clicks")],
    State("ctrl-store", "data"),
    prevent_initial_call=True,
)
def _controls(_, __, ___, store):
    triggered = ctx.triggered_id
    if triggered == "btn-pause":
        new = not store.get("paused", False)
        with _controller_lock:
            _ctrl["paused"] = new
        store["paused"] = new
    elif triggered == "btn-step":
        with _controller_lock:
            _ctrl["step"] = True
    elif triggered == "btn-reset":
        with _controller_lock:
            po = _state.get("portfolio")
        if po is None:
            raise PreventUpdate
        po.is_dead = True
        p = Portfolio()
        with _controller_lock:
            _state["portfolio"] = p
            _state["last_votes"] = []
            _state["last_arb"] = {}
            _state["last_error"] = None
            _state["_death_refresh_done"] = False
            _state["thread"] = _launch(p)
            _ctrl["paused"] = False
        store["paused"] = False
    return store


@app.callback(
    [
        Output("page-bg", "style"),
        Output("top-bar", "style"),
        Output("status-dot", "className"),
        Output("llm-degradation-banner", "children"),
        Output("agent-error-banner", "children"),
        Output("round-num", "children"),
        Output("btn-pause", "className"),
        Output("sec-portfolio", "children"),
        Output("sec-emotion", "children"),
        Output("sec-stats", "children"),
        Output("sec-positions", "children"),
        Output("chart-vals", "children"),
        Output("sparkline", "figure"),
        Output("activity-log", "children"),
        # Agent card headers
        Output("card-tech-hdr", "children"),
        Output("card-analyst-hdr", "children"),
        Output("card-risk-hdr", "children"),
        Output("card-macro-hdr", "children"),
        # Agent card bodies (children only — style handled by separate callback)
        Output("card-tech-body", "children"),
        Output("card-analyst-body", "children"),
        Output("card-risk-body", "children"),
        Output("card-macro-body", "children"),
        # Arbitration card
        Output("card-arb", "children"),
        # Agent cards panel visibility
        Output("sec-agent-cards", "style"),
        # Agent track records (LIVE tab, multi mode only)
        Output("live-track-records", "children"),
    ],
    [Input("tick", "n_intervals"), Input("ctrl-store", "data")],
    State("main-tabs", "value"),
)
def _refresh(_, store, active_tab):
    if active_tab != "live":
        return [no_update] * 24
    with _controller_lock:
        p = _state.get("portfolio")
        votes = _state.get("last_votes", [])
        arb = _state.get("last_arb", {})
        paused_ctrl = _ctrl.get("paused", False)
        death_done = _state.get("_death_refresh_done", False)
        last_err = _state.get("last_error")

    if p is None:
        raise PreventUpdate
    if p is not None and p.is_dead and not paused_ctrl and death_done:
        raise PreventUpdate
    # NOTE: ``p.last_prices`` read is atomic under CPython GIL (dict reference swap).
    # Not wrapped in ``_controller_lock`` during the multi-output callback; worst case
    # is one stale price frame per cycle.
    prices = p.last_prices
    total = p.total_value(prices)
    pnl = total - INITIAL_BALANCE
    pnl_pct = (pnl / INITIAL_BALANCE) * 100
    dead = p.is_dead
    degradation = get_llm_degradation_status()
    is_sim_mode = get_simulation_mode()
    llm_degraded_ui = bool(degradation.get("active")) and not is_sim_mode and not dead
    paused = store.get("paused", False)
    peak = p.peak_value
    dd = ((peak - total) / peak * 100) if peak > 0 else 0.0
    invested = max(total - p.cash, 0.0)
    cyc = _cycle(p)

    # Page + topbar background
    page_style = {
        "background": "#080002" if dead else BG_DEEP,
        "height": "100vh",
        "display": "flex",
        "flexDirection": "column",
        "fontFamily": FONT,
        "overflow": "hidden",
        "transition": "background 1s ease",
    }
    topbar_style = {
        "height": "48px",
        "flexShrink": "0",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
        "padding": "0 18px",
        "borderBottom": f"1px solid {'#3d0000' if dead else BORDER}",
        "background": BG_CARD,
        "transition": "border-color 1s ease",
    }

    # Status dot (+ LLM degradation when live — Finding 2.4)
    if dead:
        dot_cls = "dot dot-dead"
    elif llm_degraded_ui:
        dot_cls = "dot dot-degraded"
    elif _thinking(p):
        dot_cls = "dot dot-thinking"
    else:
        dot_cls = "dot dot-alive"

    if llm_degraded_ui:
        reason_key = degradation.get("reason") or "unknown"
        reason_label = _LLM_DEGRADATION_LABELS.get(str(reason_key), str(reason_key))
        llm_banner = html.Span(
            f"⚠ LLM blocked: {reason_label}",
            style={
                "fontSize": "9px",
                "color": ORANGE,
                "letterSpacing": "0.06em",
                "whiteSpace": "nowrap",
                "textOverflow": "ellipsis",
                "overflow": "hidden",
            },
        )
    else:
        llm_banner = html.Span()

    if last_err:
        agent_err_banner = html.Span(
            "⚠ Agent error",
            title=str(last_err)[:800],
            style={
                "fontSize": "9px",
                "color": RED,
                "letterSpacing": "0.06em",
                "whiteSpace": "nowrap",
                "textOverflow": "ellipsis",
                "overflow": "hidden",
            },
        )
    else:
        agent_err_banner = html.Span()

    pause_cls = "cbtn cbtn-pause on" if paused else "cbtn cbtn-pause"

    # ── DEATH STATE ──────────────────────────────────────────────────────────
    if dead:
        sec_portfolio = html.Div(
            [
                html.Div(
                    "💀",
                    className="skull-pulse",
                    style={
                        "fontSize": "36px",
                        "textAlign": "center",
                        "marginBottom": "14px",
                        "marginTop": "16px",
                    },
                ),
                html.Div(
                    "TERMINATED",
                    className="flicker",
                    style={
                        "fontSize": "16px",
                        "fontWeight": "700",
                        "color": RED,
                        "letterSpacing": "0.2em",
                        "textAlign": "center",
                        "marginBottom": "10px",
                    },
                ),
                html.Div(
                    f"Liquidated at round {cyc}",
                    style={
                        "fontSize": "11px",
                        "color": TEXT_DIM,
                        "textAlign": "center",
                        "marginBottom": "5px",
                    },
                ),
                html.Div(
                    f"Final P&L: {pnl:+.2f} ({pnl_pct:+.1f}%)",
                    style={
                        "fontSize": "12px",
                        "color": RED,
                        "textAlign": "center",
                    },
                ),
            ],
            style={"padding": "16px 14px"},
        )
        sec_emotion = sec_stats = sec_positions = html.Div()

    else:
        # ── PORTFOLIO VALUE ──
        if total < INITIAL_BALANCE * 0.7:
            vcol = RED
        elif total > INITIAL_BALANCE * 1.3:
            vcol = GREEN
        else:
            vcol = TEXT_MAIN

        fill_pct = min(max(total / (INITIAL_BALANCE * 2), 0), 1) * 100
        health_bar = html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            style={
                                "position": "absolute",
                                "inset": "0",
                                "borderRadius": "2px",
                                "background": f"linear-gradient(to right, {RED}, {BLUE} 50%, {GREEN})",
                            }
                        ),
                        html.Div(
                            style={
                                "position": "absolute",
                                "top": "0",
                                "right": "0",
                                "bottom": "0",
                                "width": f"{100 - fill_pct:.1f}%",
                                "background": BG_CARD,
                                "transition": "width .6s ease",
                            }
                        ),
                    ],
                    style={
                        "position": "relative",
                        "height": "3px",
                        "borderRadius": "2px",
                        "overflow": "hidden",
                        "background": BG_CARD,
                    },
                ),
                html.Div(
                    [
                        html.Span("💀 $0", style={"fontSize": "9px", "color": RED}),
                        html.Span(
                            f"${INITIAL_BALANCE:.0f}", style={"fontSize": "9px", "color": TEXT_DIM}
                        ),
                        html.Span(
                            f"${INITIAL_BALANCE * 2:.0f} 🎯",
                            style={"fontSize": "9px", "color": GREEN},
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "marginTop": "5px",
                    },
                ),
            ]
        )

        pnl_c = GREEN if pnl >= 0 else RED
        pnl_arrow = "▲" if pnl >= 0 else "▼"
        sec_portfolio = html.Div(
            [
                _section_label("PORTFOLIO VALUE"),
                html.Div(
                    f"${total:,.2f}",
                    style={
                        "fontSize": "28px",
                        "fontWeight": "700",
                        "color": vcol,
                        "letterSpacing": "-0.02em",
                        "lineHeight": "1",
                        "marginBottom": "5px",
                    },
                ),
                html.Div(
                    [
                        html.Span(pnl_arrow + " ", style={"color": pnl_c}),
                        html.Span(f"${abs(pnl):.2f} ({pnl_pct:+.2f}%)", style={"color": pnl_c}),
                    ],
                    style={"fontSize": "12px", "marginBottom": "14px"},
                ),
                health_bar,
            ]
        )

        # ── AGENT STATE ──
        em_key = _emotion(total)
        em = _EMOTIONS[em_key]
        thinking = _thinking(p)
        sec_emotion = html.Div(
            [
                _section_label("AGENT STATE"),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Span(
                                    em["icon"], style={"fontSize": "18px", "marginRight": "8px"}
                                ),
                                html.Span(
                                    em_key,
                                    style={
                                        "fontSize": "10px",
                                        "fontWeight": "700",
                                        "color": em["color"],
                                        "letterSpacing": "0.1em",
                                    },
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center"},
                        ),
                        (
                            html.Div(
                                "⟳ SEARCHING...",
                                style={
                                    "fontSize": "9px",
                                    "color": YELLOW,
                                    "letterSpacing": "0.08em",
                                },
                            )
                            if thinking
                            else html.Span()
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "marginBottom": "8px",
                    },
                ),
                html.Div(
                    em["quote"],
                    style={
                        "fontSize": "11px",
                        "color": TEXT_DIM,
                        "fontStyle": "italic",
                        "borderLeft": f"2px solid {em['color']}44",
                        "paddingLeft": "8px",
                    },
                ),
            ]
        )

        # ── METRICS ──
        dd_c = RED if dd > 20 else (YELLOW if dd > 10 else TEXT_DIM)
        sec_stats = html.Div(
            [
                _section_label("METRICS"),
                html.Div(
                    [
                        _mini_stat("CASH", f"${p.cash:.2f}", BLUE),
                        _mini_stat("INVESTED", f"${invested:.2f}", TEXT_MAIN),
                        _mini_stat("PEAK", f"${peak:.2f}", GREEN),
                        _mini_stat("DRAWDOWN", f"{dd:.1f}%", dd_c),
                    ],
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px"},
                ),
            ]
        )

        # ── POSITIONS ──
        cards = [_pos_card(sym, pos, prices) for sym, pos in list(p.positions.items())[:3]]
        sec_positions = html.Div(
            [
                _section_label(f"OPEN POSITIONS ({len(p.positions)}/3)"),
                *(
                    cards
                    if cards
                    else [
                        html.Div(
                            "— no open positions —",
                            style={
                                "color": TEXT_DIM,
                                "fontSize": "11px",
                                "textAlign": "center",
                                "padding": "16px 0",
                                "fontStyle": "italic",
                            },
                        )
                    ]
                ),
            ]
        )

    # ── RIGHT COLUMN ─────────────────────────────────────────────────────────

    def _val_block(lbl: str, val: float, c: str) -> html.Div:
        return html.Div(
            [
                html.Div(
                    lbl, style={"fontSize": "8px", "color": TEXT_DIM, "letterSpacing": "0.1em"}
                ),
                html.Div(
                    f"${val:.2f}", style={"fontSize": "12px", "color": c, "fontWeight": "600"}
                ),
            ],
            style={"textAlign": "right"},
        )

    chart_vals = html.Div(
        [
            _val_block("START", INITIAL_BALANCE, TEXT_DIM),
            _val_block("NOW", total, GREEN if total >= INITIAL_BALANCE else RED),
            _val_block("PEAK", peak, GREEN),
        ],
        style={"display": "flex", "gap": "16px"},
    )

    fig = _sparkline(p)

    log_entries = list(reversed(p.agent_log[-80:]))
    log_items = [_log_entry_card(e) for e in log_entries] or [
        html.Div(
            "— waiting for agent —",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "textAlign": "center",
                "padding": "28px",
                "fontStyle": "italic",
            },
        )
    ]

    # ── AGENT CARDS (multi-agent mode) ───────────────────────────────────────
    is_sim = get_simulation_mode()
    vote_map = {v.get("agent", ""): v for v in votes}

    _mem_ag: dict[str, list[dict]] = {}
    for r in _load_agent_memory():
        k = r.get("agent_name") or ""
        if k in ("technician", "analyst", "risk_manager", "macro_watcher"):
            _mem_ag.setdefault(k, []).append(r)

    _PLACEHOLDER_HDR = [html.Span("—", style={"fontSize": "9px", "color": TEXT_DIM})]
    _WAITING = [
        html.Div(
            "⟳ Waiting for first multi-agent cycle...",
            style={
                "color": TEXT_DIM,
                "fontSize": "10px",
                "fontStyle": "italic",
                "padding": "4px 0",
            },
        )
    ]

    if votes:
        tv = vote_map.get("technician", {})
        av = vote_map.get("analyst", {})
        rv = vote_map.get("risk_manager", {})
        mv = vote_map.get("macro_watcher", {})

        hdr_tech = _card_hdr_standard(
            "🔧",
            "TECH",
            BLUE,
            tv.get("action", "?"),
            tv.get("symbol", ""),
            float(tv.get("confidence", 0.5)),
            is_sim,
            sell_pct=tv.get("sell_pct"),
        )
        hdr_anlst = _card_hdr_standard(
            "📊",
            "ANLST",
            GREEN,
            av.get("action", "?"),
            av.get("symbol", ""),
            float(av.get("confidence", 0.5)),
            is_sim,
            sell_pct=av.get("sell_pct"),
        )
        sizing = rv.get("sizing_recommendation", "?")
        risk_s = rv.get("risk_score", "?")
        hdr_risk = [
            html.Span(
                "⚠️ RISK",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "color": ORANGE,
                    "marginRight": "10px",
                    "flexShrink": "0",
                },
            ),
            html.Span(str(sizing), style={"fontSize": "9px", "color": TEXT_MAIN, "flex": "1"}),
            html.Span(
                f"RISK {risk_s}/10", style={"fontSize": "9px", "color": ORANGE, "flexShrink": "0"}
            ),
            *([_sim_chip()] if is_sim else []),
        ]
        regime = mv.get("market_regime", "?")
        macro_bias = mv.get("macro_bias", "?")
        hdr_macro = [
            html.Span(
                "🌍 MACRO",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "color": PURPLE,
                    "marginRight": "10px",
                    "flexShrink": "0",
                },
            ),
            html.Span(str(regime), style={"fontSize": "9px", "color": TEXT_MAIN, "flex": "1"}),
            html.Span(
                str(macro_bias), style={"fontSize": "9px", "color": PURPLE, "flexShrink": "0"}
            ),
            *([_sim_chip()] if is_sim else []),
        ]

        body_tech = [
            _live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("technician", [])))
        ] + (_tech_body_children(tv) if tv else _WAITING)
        body_anlst = [_live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("analyst", [])))] + (
            _analyst_body_children(av) if av else _WAITING
        )
        body_risk = [
            _live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("risk_manager", [])))
        ] + (_risk_body_children(rv) if rv else _WAITING)
        body_macro = [
            _live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("macro_watcher", [])))
        ] + (_macro_body_children(mv) if mv else _WAITING)
        card_arb = _build_arb_card(arb)

    else:
        hdr_tech = _PLACEHOLDER_HDR
        hdr_anlst = _PLACEHOLDER_HDR
        hdr_risk = _PLACEHOLDER_HDR
        hdr_macro = _PLACEHOLDER_HDR
        body_tech = [
            _live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("technician", [])))
        ] + _WAITING
        body_anlst = [
            _live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("analyst", [])))
        ] + _WAITING
        body_risk = [
            _live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("risk_manager", [])))
        ] + _WAITING
        body_macro = [
            _live_agent_eval_banner(_agent_eval_metrics(_mem_ag.get("macro_watcher", [])))
        ] + _WAITING
        card_arb = _build_arb_card({})

    cards_style = {"padding": "0 14px 12px"}

    # ── LIVE TRACK RECORDS ───────────────────────────────────────────────────
    _TRACK_AGENTS = [
        ("technician", "TECH", BLUE),
        ("analyst", "ANLST", GREEN),
        ("risk_manager", "RISK", ORANGE),
        ("macro_watcher", "MACRO", PURPLE),
    ]
    _tr_rows = _db_read(
        "SELECT agent_name, was_correct FROM agent_memory "
        "WHERE agent_name IN ('technician','analyst','risk_manager','macro_watcher') "
        "ORDER BY timestamp DESC LIMIT 80"
    )
    _tr_by_agent: dict = {}
    for _an, _wc in _tr_rows:
        _tr_by_agent.setdefault(_an, []).append(_wc)
    badge_items = []
    for agent_key, agent_label, agent_color in _TRACK_AGENTS:
        rows = _tr_by_agent.get(agent_key, [])[:20]
        evaluated = sum(1 for wc in rows if wc in (0, 1, True, False))
        pending = len(rows) - evaluated
        if evaluated:
            correct = sum(1 for wc in rows if wc in (1, True))
            wr = correct / evaluated * 100
        else:
            wr = 0.0
        wr_col = GREEN if wr >= 60 else (ORANGE if wr >= 40 else RED)
        # Compact évaluation indicator: ⏳ when nothing has been resolved yet,
        # otherwise N pending (so users see weights are still warming up).
        if not rows:
            eval_chip = html.Span(
                "⏳ pending",
                style={"fontSize": "8px", "color": TEXT_DIM, "marginLeft": "5px"},
            )
        elif pending:
            eval_chip = html.Span(
                f"⏳ {pending}",
                title=f"{pending} vote(s) awaiting market evaluation",
                style={"fontSize": "8px", "color": ORANGE, "marginLeft": "5px"},
            )
        else:
            eval_chip = html.Span(
                "✓",
                title="All recent votes evaluated",
                style={"fontSize": "8px", "color": GREEN, "marginLeft": "5px"},
            )
        badge_items.append(
            html.Span(
                [
                    html.Span(
                        agent_label,
                        style={
                            "fontSize": "9px",
                            "fontWeight": "700",
                            "color": agent_color,
                            "marginRight": "3px",
                        },
                    ),
                    html.Span(f"{wr:.0f}%", style={"fontSize": "9px", "color": wr_col}),
                    eval_chip,
                ],
                style={
                    "background": f"{agent_color}11",
                    "border": f"1px solid {agent_color}33",
                    "borderRadius": "2px",
                    "padding": "2px 6px",
                    "marginRight": "5px",
                    "display": "inline-flex",
                    "alignItems": "center",
                },
            )
        )
    live_track = html.Div(
        [
            html.Div(
                "TRACK RECORDS",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "letterSpacing": "0.18em",
                    "color": TEXT_DIM,
                    "textTransform": "uppercase",
                    "borderBottom": f"1px solid {BORDER}",
                    "paddingBottom": "6px",
                    "marginBottom": "8px",
                },
            ),
            html.Div(badge_items, style={"display": "flex", "flexWrap": "wrap", "gap": "2px"}),
        ]
    )

    with _controller_lock:
        if dead:
            _state["_death_refresh_done"] = True
        else:
            _state["_death_refresh_done"] = False

    return (
        page_style,
        topbar_style,
        dot_cls,
        llm_banner,
        agent_err_banner,
        str(cyc) if cyc else "—",
        pause_cls,
        sec_portfolio,
        sec_emotion,
        sec_stats,
        sec_positions,
        chart_vals,
        fig,
        log_items,
        hdr_tech,
        hdr_anlst,
        hdr_risk,
        hdr_macro,
        body_tech,
        body_anlst,
        body_risk,
        body_macro,
        card_arb,
        cards_style,
        live_track,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — REASONING CARD TOGGLE (pattern-matching)
# ═══════════════════════════════════════════════════════════════════════════════


@app.callback(
    Output({"type": "reasoning-collapse", "index": MATCH}, "style"),
    Output({"type": "reasoning-toggle", "index": MATCH}, "children"),
    Input({"type": "reasoning-toggle", "index": MATCH}, "n_clicks"),
    State({"type": "reasoning-collapse", "index": MATCH}, "style"),
    prevent_initial_call=True,
)
def _toggle_reasoning(n_clicks, current_style):
    is_open = (current_style or {}).get("display") == "block"
    new_open = not is_open
    label = "▲ Collapse" if new_open else "▼ Reasoning"
    return {"display": "block" if new_open else "none"}, label
