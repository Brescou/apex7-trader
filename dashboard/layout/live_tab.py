"""APEX-7 — Live tab layout skeleton."""

from dash import dcc, html

from dashboard.server import (
    BG_CARD,
    BLUE,
    BORDER,
    FONT,
    GREEN,
    ORANGE,
    PURPLE,
    TEXT_DIM,
)


def _tab_live() -> html.Div:
    return html.Div(
        [
            # Left column
            html.Div(
                [
                    html.Div(id="sec-portfolio", style={"padding": "16px 14px 0"}),
                    html.Div(id="sec-emotion", style={"padding": "0 14px 12px"}),
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
