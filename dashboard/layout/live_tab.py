"""APEX-7 — Live tab layout (Apex7.html design reference)."""

from dash import dcc, html

from dashboard.server import (
    BG_BASE,
    BG_CARD,
    BLUE,
    BORDER,
    BORDER_INNER,
    FONT,
    GREEN,
    ORANGE,
    PURPLE,
    TEXT_FAINT,
    TEXT_GHOST,
)

_SIDE_W = "165px"


def _section(label: str, children, pip_color: str = GREEN, border_top: bool = True) -> html.Div:
    return html.Div(
        style={
            "borderBottom": f"1px solid {BORDER_INNER}",
            "padding": "6px 8px",
        },
        children=[
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "5px",
                    "marginBottom": "4px",
                },
                children=[
                    html.Div(
                        className="sec-pip",
                        style={"background": pip_color},
                    ),
                    html.Span(
                        label,
                        className="sec-ttl",
                    ),
                ],
            ),
            *([children] if not isinstance(children, list) else children),
        ],
    )


def _agent_card(
    card_id: str,
    hdr_id: str,
    body_id: str,
    toggle_id: dict,
    collapse_id: dict,
    border_color: str,
    bg_color: str,
) -> html.Div:
    return html.Div(
        style={"marginBottom": "4px"},
        children=[
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "background": f"{bg_color}0a",
                    "border": f"1px solid {bg_color}22",
                    "borderLeft": f"2px solid {bg_color}",
                    "padding": "5px 7px",
                },
                children=[
                    html.Div(
                        id=hdr_id,
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "flex": "1",
                            "overflow": "hidden",
                        },
                    ),
                    html.Button(
                        "▼",
                        id=toggle_id,
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": "none",
                            "color": TEXT_FAINT,
                            "fontFamily": FONT,
                            "fontSize": "8px",
                            "cursor": "pointer",
                            "flexShrink": "0",
                            "padding": "0 0 0 6px",
                        },
                    ),
                ],
            ),
            html.Div(
                html.Div(
                    id=body_id,
                    style={
                        "background": BG_CARD,
                        "border": f"1px solid {bg_color}18",
                        "borderLeft": f"2px solid {bg_color}",
                        "borderTop": "none",
                        "padding": "6px 8px",
                    },
                ),
                id=collapse_id,
                style={"display": "none"},
            ),
        ],
    )


def _tab_live() -> html.Div:
    return html.Div(
        style={
            "display": "flex",
            "height": "calc(100vh - 60px)",
            "overflow": "hidden",
        },
        children=[
            # ── LEFT SIDEBAR ─────────────────────────────────────────────────
            html.Div(
                style={
                    "width": _SIDE_W,
                    "minWidth": _SIDE_W,
                    "flexShrink": "0",
                    "borderRight": f"1px solid {BORDER}",
                    "display": "flex",
                    "flexDirection": "column",
                    "overflowY": "auto",
                    "background": BG_BASE,
                },
                children=[
                    # PORTFOLIO VALUE
                    html.Div(
                        id="sec-portfolio",
                        style={"padding": "8px", "borderBottom": f"1px solid {BORDER_INNER}"},
                    ),
                    # EMOTION / STATUS
                    html.Div(
                        id="sec-emotion",
                        style={"padding": "6px 8px", "borderBottom": f"1px solid {BORDER_INNER}"},
                    ),
                    # AGENT STATE section label + cards
                    html.Div(
                        style={"borderBottom": f"1px solid {BORDER_INNER}", "padding": "6px 8px"},
                        children=[
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "5px",
                                    "marginBottom": "5px",
                                },
                                children=[
                                    html.Div(className="sec-pip", style={"background": BLUE}),
                                    html.Span("AGENTS", className="sec-ttl"),
                                ],
                            ),
                            html.Div(
                                id="sec-agent-cards",
                                children=[
                                    _agent_card(
                                        "tech",
                                        "card-tech-hdr",
                                        "card-tech-body",
                                        {"type": "reasoning-toggle", "index": "tech"},
                                        {"type": "reasoning-collapse", "index": "tech"},
                                        BLUE,
                                        BLUE,
                                    ),
                                    _agent_card(
                                        "analyst",
                                        "card-analyst-hdr",
                                        "card-analyst-body",
                                        {"type": "reasoning-toggle", "index": "analyst"},
                                        {"type": "reasoning-collapse", "index": "analyst"},
                                        GREEN,
                                        GREEN,
                                    ),
                                    _agent_card(
                                        "risk",
                                        "card-risk-hdr",
                                        "card-risk-body",
                                        {"type": "reasoning-toggle", "index": "risk"},
                                        {"type": "reasoning-collapse", "index": "risk"},
                                        ORANGE,
                                        ORANGE,
                                    ),
                                    _agent_card(
                                        "macro",
                                        "card-macro-hdr",
                                        "card-macro-body",
                                        {"type": "reasoning-toggle", "index": "macro"},
                                        {"type": "reasoning-collapse", "index": "macro"},
                                        PURPLE,
                                        PURPLE,
                                    ),
                                    # ARBITRATION
                                    html.Div(id="card-arb"),
                                ],
                            ),
                        ],
                    ),
                    # TRADE RECORDS
                    html.Div(
                        id="live-track-records",
                        style={"padding": "6px 8px", "borderBottom": f"1px solid {BORDER_INNER}"},
                    ),
                    # STATS (balance, drawdown, etc.)
                    html.Div(
                        id="sec-stats",
                        style={"padding": "6px 8px", "borderBottom": f"1px solid {BORDER_INNER}"},
                    ),
                    # OPEN POSITIONS
                    html.Div(
                        id="sec-positions",
                        style={"padding": "6px 8px", "flex": "1"},
                    ),
                ],
            ),
            # ── MAIN (chart + log) ───────────────────────────────────────────
            html.Div(
                style={
                    "flex": "1",
                    "minWidth": "0",
                    "display": "flex",
                    "flexDirection": "column",
                    "height": "100%",
                },
                children=[
                    # Equity curve section
                    html.Div(
                        style={
                            "flexShrink": "0",
                            "borderBottom": f"1px solid {BORDER}",
                        },
                        children=[
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "space-between",
                                    "padding": "4px 8px",
                                    "borderBottom": f"1px solid {BORDER_INNER}",
                                },
                                children=[
                                    html.Div(
                                        style={
                                            "display": "flex",
                                            "alignItems": "center",
                                            "gap": "5px",
                                        },
                                        children=[
                                            html.Div(className="sec-pip"),
                                            html.Span("EQUITY CURVE", className="sec-ttl"),
                                        ],
                                    ),
                                    html.Div(
                                        id="chart-vals", style={"display": "flex", "gap": "14px"}
                                    ),
                                ],
                            ),
                            dcc.Graph(
                                id="sparkline",
                                config={"displayModeBar": False},
                                style={"height": "144px"},
                            ),
                        ],
                    ),
                    # Activity log section
                    html.Div(
                        style={
                            "flex": "1",
                            "display": "flex",
                            "flexDirection": "column",
                            "minHeight": "0",
                        },
                        children=[
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "space-between",
                                    "padding": "4px 8px",
                                    "borderBottom": f"1px solid {BORDER_INNER}",
                                    "flexShrink": "0",
                                },
                                children=[
                                    html.Div(
                                        style={
                                            "display": "flex",
                                            "alignItems": "center",
                                            "gap": "5px",
                                        },
                                        children=[
                                            html.Div(
                                                className="sec-pip",
                                                style={"background": GREEN},
                                            ),
                                            html.Span("ACTIVITY LOG", className="sec-ttl"),
                                        ],
                                    ),
                                    html.Span(
                                        "NEWEST FIRST",
                                        style={
                                            "fontSize": "7px",
                                            "color": TEXT_GHOST,
                                            "letterSpacing": "0.1em",
                                        },
                                    ),
                                ],
                            ),
                            html.Div(
                                id="activity-log",
                                style={
                                    "flex": "1",
                                    "overflowY": "auto",
                                    "padding": "2px 0",
                                },
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
