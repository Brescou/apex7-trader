"""APEX-7 — CLI terminal callbacks. DMC Tabs handles nav routing."""

from __future__ import annotations

from datetime import datetime

from dash import Input, Output, State, callback, clientside_callback, ctx, html

from dashboard.server import (
    FONT,
    GREEN,
    ORANGE,
    TEXT_FAINT,
)


# ── CLI clock ─────────────────────────────────────────────────────────────────


@callback(
    Output("cli-clock", "children"),
    Input("tick", "n_intervals"),
)
def _cli_clock(n):
    return datetime.now().strftime("%H:%M:%S")


# ── SIM toggle → mode-radio ───────────────────────────────────────────────────


@callback(
    Output("mode-radio", "value"),
    Output("sim-toggle-btn", "style"),
    Output("sim-led", "style"),
    Output("sim-label", "children"),
    Input("sim-toggle-btn", "n_clicks"),
    State("mode-radio", "value"),
    prevent_initial_call=True,
)
def _sim_toggle(n_clicks, current_mode):
    if current_mode == "sim":
        new_mode = "live"
        btn_style = {
            "display": "flex",
            "alignItems": "center",
            "border": "1px solid #0f2535",
            "color": TEXT_FAINT,
            "background": "none",
            "fontFamily": FONT,
            "fontSize": "8px",
            "fontWeight": "700",
            "letterSpacing": "0.16em",
            "padding": "2px 9px",
            "cursor": "pointer",
            "transition": "all 0.2s",
        }
        led_style = {
            "width": "5px",
            "height": "5px",
            "borderRadius": "50%",
            "background": "#0f2535",
            "display": "inline-block",
            "marginRight": "4px",
        }
        label = "○ SIMULATION"
    else:
        new_mode = "sim"
        btn_style = {
            "display": "flex",
            "alignItems": "center",
            "border": "1px solid #b05010",
            "color": ORANGE,
            "background": "rgba(180,70,10,0.1)",
            "fontFamily": FONT,
            "fontSize": "8px",
            "fontWeight": "700",
            "letterSpacing": "0.16em",
            "padding": "2px 9px",
            "cursor": "pointer",
            "transition": "all 0.2s",
        }
        led_style = {
            "width": "5px",
            "height": "5px",
            "borderRadius": "50%",
            "background": ORANGE,
            "display": "inline-block",
            "marginRight": "4px",
            "animation": "blink 1.1s infinite",
        }
        label = "● SIMULATION"
    return new_mode, btn_style, led_style, label


# ── CLI hint buttons → fill input ─────────────────────────────────────────────


@callback(
    Output("cli-input", "value"),
    [Input(f"cli-hint-{i}", "n_clicks") for i in range(8)],
    prevent_initial_call=True,
)
def _cli_hint(*args):
    hints = [
        "help",
        "status",
        "positions",
        "portfolio",
        "agents",
        "buy AAPL 5",
        "sell TSLA 1",
        "clear",
    ]
    triggered = ctx.triggered_id
    if triggered and triggered.startswith("cli-hint-"):
        idx = int(triggered.split("-")[-1])
        return hints[idx]
    return ""


# ── CLI command parsing ───────────────────────────────────────────────────────


def _parse_cli_command(raw: str) -> list[html.Div]:
    parts = raw.strip().lower().split()
    if not parts:
        return []
    cmd = parts[0]

    def _line(src: str, sc: str, body) -> html.Div:
        return html.Div(
            className="cli-line",
            children=[
                html.Span(datetime.now().strftime("%H:%M:%S"), className="cli-ts"),
                html.Span(f"[{src}]", className=f"cli-src {sc}"),
                html.Span(body, className="cli-body"),
            ],
        )

    if cmd == "help":
        return [
            _line(
                "SYS",
                "tc-c",
                html.Span(
                    [
                        "Available commands: ",
                        html.Span(
                            "help · status · positions · portfolio · agents"
                            " · buy [SYM] [QTY] · sell [SYM] [QTY] · clear",
                            style={"color": GREEN},
                        ),
                    ]
                ),
            ),
        ]

    if cmd == "status":
        try:
            from agents.shared.nodes import get_runtime_mode
            from dashboard.controller import _controller_lock, _ctrl

            with _controller_lock:
                cycle = _ctrl.get("cycle", 0)
            mode = get_runtime_mode()
            return [
                _line(
                    "SYS",
                    "tc-c",
                    html.Span(
                        [
                            html.Span("system_status:", style={"color": "#6a9aaa"}),
                            " RUNNING | cycle=",
                            html.Span(str(cycle), style={"color": "#d8b860"}),
                            " | mode=",
                            html.Span(mode.upper(), style={"color": GREEN}),
                        ]
                    ),
                ),
            ]
        except Exception:
            return [_line("SYS", "tc-c", "status: running")]

    if cmd == "positions":
        try:
            from dashboard.controller import _controller_lock, _state

            with _controller_lock:
                p = _state.get("portfolio")
            if p and p.positions:
                lines = [
                    _line(
                        "SYS",
                        "tc-c",
                        html.Span(
                            [
                                html.Span("open_positions:", style={"color": "#6a9aaa"}),
                                f" {len(p.positions)} position(s)",
                            ]
                        ),
                    )
                ]
                for sym, pos in p.positions.items():
                    sh = float(pos.get("shares", 0))
                    avg = float(pos.get("avg_price", pos.get("avg_cost", 0)))
                    cur = float(p.last_prices.get(sym) or avg)
                    pnl = (cur - avg) / avg * 100 if avg else 0
                    color = GREEN if pnl >= 0 else "#ff4060"
                    lines.append(
                        _line(
                            "SYS",
                            "tc-c",
                            html.Span(
                                [
                                    f"  {sym} · {sh:.4f}sh · avg=${avg:.2f} · cur=${cur:.2f} · ",
                                    html.Span(
                                        f"{'+'if pnl>=0 else ''}{pnl:.1f}%",
                                        style={"color": color},
                                    ),
                                ]
                            ),
                        )
                    )
                return lines
            return [_line("SYS", "tc-c", "open_positions: none")]
        except Exception as e:
            return [_line("SYS", "tc-d", f"error: {e}")]

    if cmd == "portfolio":
        try:
            from dashboard.controller import _controller_lock, _state

            with _controller_lock:
                p = _state.get("portfolio")
            if p:
                val = p.portfolio_value()
                cash = float(p.cash)
                invested = val - cash
                pnl = val - 1000
                color = GREEN if pnl >= 0 else "#ff4060"
                return [
                    _line(
                        "SYS",
                        "tc-c",
                        html.Span(
                            [
                                html.Span("portfolio:", style={"color": "#6a9aaa"}),
                                " total=",
                                html.Span(f"${val:,.2f}", style={"color": GREEN}),
                                " | cash=",
                                html.Span(f"${cash:,.2f}", style={"color": "#6a9aaa"}),
                                " | invested=",
                                html.Span(f"${invested:,.2f}", style={"color": "#e08030"}),
                            ]
                        ),
                    ),
                    _line(
                        "SYS",
                        "tc-c",
                        html.Span(
                            [
                                "  P&L: ",
                                html.Span(
                                    f"{'+'if pnl>=0 else ''}{pnl:+.2f}",
                                    style={"color": color},
                                ),
                            ]
                        ),
                    ),
                ]
            return [_line("SYS", "tc-c", "portfolio: no data")]
        except Exception as e:
            return [_line("SYS", "tc-d", f"error: {e}")]

    if cmd == "agents":
        return [
            _line(
                "SYS",
                "tc-c",
                html.Span(
                    [
                        html.Span("agents:", style={"color": "#6a9aaa"}),
                        " 4 specialists + arbitrator",
                    ]
                ),
            ),
            _line(
                "SYS",
                "tc-c",
                html.Span(
                    [
                        "  ● ",
                        html.Span("[TECHNICAL]", style={"color": "#3090ff"}),
                        "  ● ",
                        html.Span("[FUNDAMENTAL]", style={"color": "#00dda0"}),
                        "  ● ",
                        html.Span("[RISK_MGR]", style={"color": "#e08030"}),
                        "  ● ",
                        html.Span("[MACRO]", style={"color": "#9070d0"}),
                        "  ● ",
                        html.Span("[ARBITRAGE]", style={"color": "#a0c4cc"}),
                    ]
                ),
            ),
        ]

    if cmd in ("buy", "sell"):
        sym = (parts[1] if len(parts) > 1 else "???").upper()
        qty = parts[2] if len(parts) > 2 else "1"
        return [
            _line(
                "EXE",
                "tc-r",
                html.Span(
                    [
                        html.Span("[EXECUTOR]", style={"color": "#ff4060"}),
                        f" {cmd.upper()} {sym} {qty}sh @ MARKET — submitted",
                    ]
                ),
            ),
            _line(
                "BRK",
                "tc-c",
                html.Span(
                    [
                        html.Span("[BROKER]", style={"color": "#28b0b0"}),
                        " order accepted — awaiting fill...",
                    ]
                ),
            ),
        ]

    return [
        _line(
            "SYS",
            "tc-d",
            html.Span(
                [
                    f"Unknown command: '{cmd}'. Type ",
                    html.Span("help", style={"color": GREEN}),
                    " for available commands.",
                ]
            ),
        ),
    ]


# ── CLI submit → append output + update history ────────────────────────────────


@callback(
    Output("cli-output", "children"),
    Output("cli-input", "value", allow_duplicate=True),
    Output("cli-history-store", "data"),
    Output("cli-history-pos", "data"),
    Input("cli-input", "n_submit"),
    State("cli-input", "value"),
    State("cli-output", "children"),
    State("cli-history-store", "data"),
    prevent_initial_call=True,
)
def _cli_submit(n_submit, cmd_raw, current_lines, history):
    if not cmd_raw or not cmd_raw.strip():
        return current_lines, "", history, -1

    cmd = cmd_raw.strip()
    if current_lines is None:
        current_lines = []

    if cmd.lower() == "clear":
        return [], "", history, -1

    new_history = list(history or [])
    if not new_history or new_history[-1] != cmd:
        new_history.append(cmd)
    if len(new_history) > 100:
        new_history = new_history[-100:]

    echo = html.Div(
        className="cli-line",
        children=[
            html.Span(datetime.now().strftime("%H:%M:%S"), className="cli-ts"),
            html.Span("[USR]", className="cli-src tc-g"),
            html.Span(
                html.Span([html.Span("$ ", style={"color": GREEN}), cmd]),
                className="cli-body",
            ),
        ],
    )

    response_lines = _parse_cli_command(cmd)
    new_lines = list(current_lines) + [echo] + response_lines
    if len(new_lines) > 500:
        new_lines = new_lines[-500:]

    return new_lines, "", new_history, -1


# ── CLI ↑↓ history navigation (clientside) ────────────────────────────────────

clientside_callback(
    """
    function(event, currentVal, history, pos) {
        if (!event || !event.key) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        var key = event.key;
        if (key !== 'ArrowUp' && key !== 'ArrowDown') {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        if (!history || history.length === 0) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        var newPos;
        if (key === 'ArrowUp') {
            newPos = Math.min(pos + 1, history.length - 1);
        } else {
            newPos = Math.max(pos - 1, -1);
        }
        var cmd = newPos === -1 ? '' : history[history.length - 1 - newPos];
        return [cmd || '', newPos];
    }
    """,
    Output("cli-input", "value", allow_duplicate=True),
    Output("cli-history-pos", "data"),
    Input("cli-keyboard-event", "data"),
    State("cli-input", "value"),
    State("cli-history-store", "data"),
    State("cli-history-pos", "data"),
    prevent_initial_call=True,
)
