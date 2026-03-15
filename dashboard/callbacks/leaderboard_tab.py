"""APEX-7 — Leaderboard tab callback."""

import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html

from leaderboard import Leaderboard
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
    app,
)


@app.callback(
    Output("lb-results", "children"),
    Input("btn-lb-run", "n_clicks"),
    State("lb-scenario", "value"),
    prevent_initial_call=True,
)
def _lb_run(n_clicks, scenario):
    if not n_clicks:
        return html.Div()

    lb = Leaderboard()
    rows = lb.run_all(scenario)

    agent_colors = [GREEN, BLUE, PURPLE, ORANGE, YELLOW, "#ec4899", "#14b8a6", RED]

    table_rows = []
    for i, row in enumerate(rows):
        rank = i + 1
        surv = (
            html.Span("✓ ALIVE", style={"color": GREEN})
            if row.get("survived")
            else html.Span("💀 DEAD", style={"color": RED})
        )
        col = agent_colors[i % len(agent_colors)]
        table_rows.append(
            html.Div(
                [
                    html.Span(
                        f"#{rank}",
                        style={
                            "color": TEXT_DIM,
                            "fontSize": "10px",
                            "width": "28px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        row["agent_id"],
                        style={
                            "color": col,
                            "fontWeight": "700",
                            "fontSize": "12px",
                            "width": "100px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"${row['final_value']:.2f}",
                        style={
                            "color": TEXT_MAIN,
                            "fontSize": "11px",
                            "width": "90px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"{row['return_pct']:+.1f}%",
                        style={
                            "color": GREEN if row["return_pct"] >= 0 else RED,
                            "fontWeight": "700",
                            "fontSize": "12px",
                            "width": "70px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"{row['sharpe']:.2f}",
                        style={
                            "color": BLUE,
                            "fontSize": "11px",
                            "width": "60px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"{row['win_rate']:.0f}%",
                        style={
                            "color": TEXT_MAIN,
                            "fontSize": "11px",
                            "width": "60px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"{row['max_drawdown']:.1f}%",
                        style={
                            "color": RED,
                            "fontSize": "11px",
                            "width": "70px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        str(row["trades"]),
                        style={
                            "color": TEXT_DIM,
                            "fontSize": "11px",
                            "width": "50px",
                            "flexShrink": "0",
                        },
                    ),
                    surv,
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px",
                    "padding": "8px 12px",
                    "border": f"1px solid {GREEN if rank == 1 else BORDER}",
                    "background": f"{GREEN}08" if rank == 1 else BG_CARD,
                    "borderRadius": "4px",
                    "marginBottom": "5px",
                    "fontFamily": FONT,
                },
            )
        )

    header_cols = [
        "#",
        "AGENT",
        "FINAL $",
        "RETURN",
        "SHARPE",
        "WIN RATE",
        "DRAWDOWN",
        "TRADES",
        "STATUS",
    ]
    header = html.Div(
        [
            html.Span(
                c,
                style={
                    "color": TEXT_DIM,
                    "fontSize": "9px",
                    "letterSpacing": "0.12em",
                    "width": w,
                    "flexShrink": "0",
                },
            )
            for c, w in zip(
                header_cols,
                ["28px", "100px", "90px", "70px", "60px", "60px", "70px", "50px", "auto"],
            )
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "gap": "8px",
            "padding": "6px 12px",
            "marginBottom": "6px",
            "borderBottom": f"1px solid {BORDER}",
        },
    )

    names = [r["agent_id"] for r in rows]
    returns = [r["return_pct"] for r in rows]
    bar_cols = [agent_colors[i % len(agent_colors)] for i in range(len(rows))]
    fig = go.Figure(
        go.Bar(
            x=names,
            y=returns,
            marker_color=bar_cols,
            text=[f"{r:+.1f}%" for r in returns],
            textposition="outside",
            textfont=dict(family=FONT, size=9),
        )
    )
    fig.add_hline(
        y=0,
        line=dict(color=GRAY, width=1, dash="dot"),
        annotation_text="breakeven",
        annotation_position="right",
        annotation_font=dict(color=GRAY, size=8, family=FONT),
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=40, r=20, t=30, b=60),
        height=280,
        showlegend=False,
        title=f"Agent Returns — {scenario}",
    )

    return html.Div(
        [
            header,
            html.Div(table_rows, style={"marginBottom": "16px"}),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ]
    )
