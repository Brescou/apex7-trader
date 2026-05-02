"""APEX-7 — Agents tab callback."""

import datetime as _dt

import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update

from dashboard.layout.helpers import _agent_eval_metrics, _load_agent_memory, _load_postmortem
from dashboard.server import (
    BG_CARD,
    BLUE,
    BORDER,
    GREEN,
    ORANGE,
    PURPLE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    _rgba,
    app,
)


@app.callback(
    Output("agents-content", "children"),
    [Input("agents-tick", "n_intervals"), Input("btn-agents-refresh", "n_clicks")],
    State("main-tabs", "value"),
    prevent_initial_call=False,
)
def _agents_refresh(_, __, active_tab):
    if active_tab != "agents":
        return no_update
    # ``_load_*`` go through ``_db_read``/``_get_db_path`` so this tab
    # automatically follows the active mode (live/paper/sim).
    mem = _load_agent_memory()
    post = _load_postmortem()

    _AGENT_DEFS = [
        {"key": "technician", "label": "Technician", "badge": "TECH", "color": BLUE},
        {"key": "analyst", "label": "Analyst", "badge": "ANLST", "color": GREEN},
        {"key": "risk_manager", "label": "Risk Mgr", "badge": "RISK", "color": ORANGE},
        {"key": "macro_watcher", "label": "Macro", "badge": "MACRO", "color": PURPLE},
    ]

    # ── Section 1: Agent performance table ───────────────────────────────────
    def _win_rate_bar(wr: float, color: str) -> html.Div:
        bar_color = GREEN if wr >= 60 else (ORANGE if wr >= 40 else RED)
        return html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            style={
                                "width": f"{wr:.0f}%",
                                "height": "100%",
                                "background": bar_color,
                                "borderRadius": "1px",
                                "transition": "width .4s ease",
                            }
                        ),
                    ],
                    style={
                        "width": "80px",
                        "height": "4px",
                        "background": f"{bar_color}22",
                        "borderRadius": "1px",
                        "overflow": "hidden",
                        "flexShrink": "0",
                    },
                ),
                html.Span(
                    f"{wr:.0f}%",
                    style={
                        "fontSize": "10px",
                        "color": bar_color,
                        "fontWeight": "700",
                        "marginLeft": "6px",
                        "flexShrink": "0",
                    },
                ),
            ],
            style={"display": "flex", "alignItems": "center"},
        )

    hdr_cols = ["AGENT", "VOTES", "EVAL", "STATUS", "WIN RATE", "AVG CONF", "TREND 7J"]
    hdr_widths = ["120px", "55px", "65px", "130px", "140px", "70px", "1fr"]
    table_hdr = html.Div(
        [
            html.Span(
                c,
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": w,
                    "flexShrink": "0" if w != "1fr" else "1",
                },
            )
            for c, w in zip(hdr_cols, hdr_widths)
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "gap": "8px",
            "padding": "6px 12px",
            "marginBottom": "4px",
            "borderBottom": f"1px solid {BORDER}",
        },
    )

    _MIN_EVALUATED = 5

    def _eval_status_badge(evaluated: int) -> html.Span:
        """Calibrating (⏳) until ``_MIN_EVALUATED`` evaluated votes, then market-validated (✓)."""
        if evaluated < _MIN_EVALUATED:
            label, color = "⏳ Calibrating", ORANGE
        else:
            label, color = "✓ Market-validated", GREEN
        return html.Span(
            label,
            style={
                "fontSize": "9px",
                "fontWeight": "700",
                "color": color,
                "background": f"{color}11",
                "border": f"1px solid {color}33",
                "borderRadius": "2px",
                "padding": "2px 6px",
                "letterSpacing": "0.05em",
            },
        )

    table_rows = []
    for ag in _AGENT_DEFS:
        key = ag["key"]
        col = ag["color"]
        rows = [r for r in mem if r.get("agent_name") == key]
        m = _agent_eval_metrics(rows)
        total = int(m["total"])
        evaluated = int(m["evaluated"])
        wr = float(m["win_rate_pct"])
        confs = [float(r["confidence"]) for r in rows if r.get("confidence") is not None]
        avg_c = (sum(confs) / len(confs)) if confs else 0.0

        today = _dt.date.today()
        day_wins: dict[int, int] = {}
        day_total: dict[int, int] = {}
        for r in rows:
            try:
                d = _dt.date.fromisoformat(str(r["timestamp"])[:10])
                delta = (today - d).days
                if 0 <= delta < 7:
                    day_total[delta] = day_total.get(delta, 0) + 1
                    if r.get("was_correct") in (1, True, "1"):
                        day_wins[delta] = day_wins.get(delta, 0) + 1
            except Exception:
                pass
        trend_y = [
            (day_wins.get(d, 0) / day_total[d] * 100) if d in day_total else 0.0
            for d in range(6, -1, -1)
        ]
        spark_col = (
            GREEN if (trend_y[-1] >= 60 if any(v > 0 for v in trend_y) else True) else ORANGE
        )
        spark_fig = go.Figure(
            go.Scatter(
                x=list(range(7)),
                y=trend_y,
                mode="lines",
                line=dict(color=spark_col, width=1.5),
                fill="tozeroy",
                fillcolor=_rgba(spark_col, 0.09),
            )
        )
        spark_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            height=36,
            showlegend=False,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False, range=[0, 105]),
        )

        agent_chip = html.Span(
            [
                html.Span(
                    ag["badge"],
                    style={
                        "fontSize": "9px",
                        "fontWeight": "700",
                        "color": col,
                        "marginRight": "5px",
                    },
                ),
                html.Span(ag["label"], style={"fontSize": "10px", "color": TEXT_MAIN}),
            ],
            style={
                "background": f"{col}0f",
                "border": f"1px solid {col}33",
                "borderRadius": "3px",
                "padding": "3px 7px",
                "display": "inline-flex",
                "alignItems": "center",
            },
        )

        table_rows.append(
            html.Div(
                [
                    html.Div(agent_chip, style={"width": "120px", "flexShrink": "0"}),
                    html.Span(
                        str(total),
                        style={
                            "fontSize": "11px",
                            "color": TEXT_DIM,
                            "width": "55px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"{evaluated}/{total}",
                        title=f"{total - evaluated} pending evaluation",
                        style={
                            "fontSize": "11px",
                            "color": TEXT_MAIN if evaluated > 0 else TEXT_DIM,
                            "width": "65px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Div(
                        _eval_status_badge(evaluated),
                        style={"width": "130px", "flexShrink": "0"},
                    ),
                    html.Div(_win_rate_bar(wr, col), style={"width": "140px", "flexShrink": "0"}),
                    html.Span(
                        f"{avg_c:.0%}",
                        style={
                            "fontSize": "11px",
                            "color": TEXT_MAIN,
                            "width": "70px",
                            "flexShrink": "0",
                        },
                    ),
                    dcc.Graph(
                        figure=spark_fig,
                        config={"displayModeBar": False},
                        style={"flex": "1", "minWidth": "80px", "height": "36px"},
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px",
                    "padding": "8px 12px",
                    "background": BG_CARD,
                    "border": f"1px solid {BORDER}",
                    "borderRadius": "3px",
                    "marginBottom": "4px",
                },
            )
        )

    agents_section = html.Div(
        [
            html.Div(
                "PERFORMANCE PAR AGENT",
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
            table_hdr,
            html.Div(
                table_rows
                if table_rows
                else [
                    html.Div(
                        "No agent memory data yet. Run in multi-agent mode.",
                        style={
                            "color": TEXT_DIM,
                            "fontSize": "11px",
                            "fontStyle": "italic",
                            "padding": "12px",
                        },
                    )
                ]
            ),
        ],
        style={"marginBottom": "24px"},
    )

    # ── Section 2: Post-mortems récents ──────────────────────────────────────
    pm_rows = []
    for pm in post[:5]:
        pnl = float(pm.get("pnl_pct") or 0.0)
        pnl_c = GREEN if pnl >= 0 else RED
        sym = pm.get("symbol") or "—"
        hrs = pm.get("holding_hours")
        hrs_s = f"{float(hrs):.1f}h" if hrs is not None else "—"
        summary_txt = (pm.get("summary") or "")[:120]
        win_badge = html.Span(
            "WIN" if pnl >= 0 else "LOSS",
            style={
                "fontSize": "9px",
                "fontWeight": "700",
                "padding": "2px 6px",
                "borderRadius": "2px",
                "background": f"{pnl_c}22",
                "color": pnl_c,
                "flexShrink": "0",
            },
        )
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
                    sym_chip,
                    html.Span(
                        f"{pnl:+.1f}%",
                        style={
                            "fontSize": "11px",
                            "color": pnl_c,
                            "fontWeight": "700",
                            "width": "55px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        hrs_s,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_DIM,
                            "width": "40px",
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
                        },
                    ),
                    win_badge,
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

    postmortem_section = html.Div(
        [
            html.Div(
                "POST-MORTEMS RECENTS",
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
            html.Div(
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
            ),
        ]
    )

    return html.Div([agents_section, postmortem_section])
