"""APEX-7 — Live tab layout with DMC v2 components."""

import dash_mantine_components as dmc
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

_SIDE_W = "200px"


def _agent_card(
    hdr_id: str,
    body_id: str,
    toggle_id: dict,
    collapse_id: dict,
    bg_color: str,
) -> html.Div:
    return html.Div(
        style={"marginBottom": "3px"},
        children=[
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "background": f"{bg_color}0a",
                    "border": f"1px solid {bg_color}22",
                    "borderLeft": f"2px solid {bg_color}",
                    "padding": "4px 7px",
                    "cursor": "pointer",
                },
                children=[
                    html.Div(
                        id=hdr_id,
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "flex": "1",
                            "overflow": "hidden",
                            "minWidth": "0",
                        },
                    ),
                    html.Button(
                        "▼ Reasoning",
                        id=toggle_id,
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": "none",
                            "color": TEXT_FAINT,
                            "fontFamily": FONT,
                            "fontSize": "7px",
                            "cursor": "pointer",
                            "flexShrink": "0",
                            "padding": "0 0 0 6px",
                            "letterSpacing": "0.1em",
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
                        "padding": "5px 7px",
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
            "height": "calc(100vh - 30px)",
            "overflow": "hidden",
        },
        children=[
            # ── LEFT SIDEBAR (200px) ──────────────────────────────────────────
            html.Div(
                style={
                    "width": _SIDE_W,
                    "minWidth": _SIDE_W,
                    "flexShrink": "0",
                    "borderRight": f"1px solid {BORDER}",
                    "background": BG_BASE,
                    "display": "flex",
                    "flexDirection": "column",
                    "overflow": "hidden",
                },
                children=[
                    dmc.ScrollArea(
                        style={"flex": "1"},
                        children=[
                            # PORTFOLIO VALUE
                            html.Div(
                                id="sec-portfolio",
                                style={
                                    "padding": "8px",
                                    "borderBottom": f"1px solid {BORDER_INNER}",
                                },
                            ),
                            # AGENT STATE / EMOTION
                            html.Div(
                                id="sec-emotion",
                                style={
                                    "padding": "6px 8px",
                                    "borderBottom": f"1px solid {BORDER_INNER}",
                                },
                            ),
                            # AGENTS section
                            html.Div(
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
                                            "marginBottom": "5px",
                                        },
                                        children=[
                                            html.Div(
                                                className="sec-pip",
                                                style={"background": BLUE},
                                            ),
                                            html.Span("AGENTS", className="sec-ttl"),
                                        ],
                                    ),
                                    html.Div(
                                        id="sec-agent-cards",
                                        children=[
                                            _agent_card(
                                                "card-tech-hdr",
                                                "card-tech-body",
                                                {"type": "reasoning-toggle", "index": "tech"},
                                                {"type": "reasoning-collapse", "index": "tech"},
                                                BLUE,
                                            ),
                                            _agent_card(
                                                "card-analyst-hdr",
                                                "card-analyst-body",
                                                {"type": "reasoning-toggle", "index": "analyst"},
                                                {"type": "reasoning-collapse", "index": "analyst"},
                                                GREEN,
                                            ),
                                            _agent_card(
                                                "card-risk-hdr",
                                                "card-risk-body",
                                                {"type": "reasoning-toggle", "index": "risk"},
                                                {"type": "reasoning-collapse", "index": "risk"},
                                                ORANGE,
                                            ),
                                            _agent_card(
                                                "card-macro-hdr",
                                                "card-macro-body",
                                                {"type": "reasoning-toggle", "index": "macro"},
                                                {"type": "reasoning-collapse", "index": "macro"},
                                                PURPLE,
                                            ),
                                            html.Div(id="card-arb"),
                                        ],
                                    ),
                                ],
                            ),
                            # TRACK RECORDS
                            html.Div(
                                id="live-track-records",
                                style={
                                    "padding": "6px 8px",
                                    "borderBottom": f"1px solid {BORDER_INNER}",
                                },
                            ),
                            # METRICS
                            html.Div(
                                id="sec-stats",
                                style={
                                    "padding": "6px 8px",
                                    "borderBottom": f"1px solid {BORDER_INNER}",
                                },
                            ),
                            # OPEN POSITIONS
                            html.Div(
                                id="sec-positions",
                                style={"padding": "6px 8px"},
                            ),
                        ],
                    ),
                ],
            ),
            # ── MAIN AREA (chart + log) ───────────────────────────────────────
            html.Div(
                style={
                    "flex": "1",
                    "minWidth": "0",
                    "display": "flex",
                    "flexDirection": "column",
                    "height": "100%",
                },
                children=[
                    # Equity curve
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
                                        id="chart-vals",
                                        style={"display": "flex", "gap": "14px"},
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
                    # Activity log
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
                            dmc.ScrollArea(
                                id="activity-log",
                                style={"flex": "1"},
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
