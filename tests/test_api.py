"""Tests for the FastAPI backend (api/) — Review Finding #28.

Covers serializers, auth (REST + WebSocket), broadcaster connection
management, and route wiring. Route handlers are plain ``def`` (Batch C),
so most are exercised as direct Python calls rather than through a live
HTTP/WS cycle — this avoids spinning up ``dashboard.controller``'s real
background threads (see Batch F) and keeps these tests fast and hermetic.
Where the full app is exercised via ``TestClient``, ``start_controller`` is
always mocked for the same reason.
"""

import asyncio
import os
import sys
import threading
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.data import Portfolio

# ═══════════════════════════════════════════════════════════════════════════
# serializers.py
# ═══════════════════════════════════════════════════════════════════════════


def test_serialize_state_shape_and_values():
    from api.serializers import serialize_state

    p = Portfolio()
    p.cash = 800.0
    p.positions["AAPL"] = {
        "shares": 2.0,
        "avg_price": 100.0,
        "layers": 1,
        "opened_at": "2026-01-01T00:00:00",
    }
    p.last_prices = {"AAPL": 120.0}

    out = serialize_state(
        portfolio=p,
        cycle=3,
        thinking=False,
        mode="sim",
        votes=[{"agent": "technician", "action": "BUY"}],
        arb={"action": "BUY", "symbol": "AAPL"},
        consecutive_holds=0,
    )

    assert out["cash"] == 800.0
    assert out["cycle"] == 3
    assert out["mode"] == "sim"
    assert out["value"] == pytest.approx(800.0 + 2.0 * 120.0)
    assert out["votes"] == [{"agent": "technician", "action": "BUY"}]
    assert out["arbitration"] == {"action": "BUY", "symbol": "AAPL"}

    assert len(out["positions"]) == 1
    pos = out["positions"][0]
    assert pos["sym"] == "AAPL"
    assert pos["shares"] == 2.0
    assert pos["avgPrice"] == 100.0
    assert pos["lastPrice"] == 120.0
    assert pos["pnlPct"] == pytest.approx(20.0)


def test_serialize_state_survival_pct_is_clamped():
    from api.serializers import serialize_state
    from config import DEATH_THRESHOLD

    p = Portfolio()
    p.cash = DEATH_THRESHOLD - 40  # deep below death threshold
    out = serialize_state(
        portfolio=p, cycle=0, thinking=False, mode="live", votes=[], arb={}, consecutive_holds=0
    )
    assert 0 <= out["survivalPct"] <= 100


def test_serialize_state_empty_portfolio():
    from api.serializers import serialize_state

    p = Portfolio()
    out = serialize_state(
        portfolio=p, cycle=0, thinking=True, mode="paper", votes=[], arb={}, consecutive_holds=4
    )
    assert out["positions"] == []
    assert out["votes"] == []
    assert out["arbitration"] == {}
    assert out["thinking"] is True
    assert out["consecutiveHolds"] == 4
    assert out["isDead"] is False


def test_serialize_state_arb_none_becomes_empty_dict():
    """arb can legitimately be ``None`` (no arbitration has run yet)."""
    from api.serializers import serialize_state

    p = Portfolio()
    out = serialize_state(
        portfolio=p, cycle=0, thinking=False, mode="live", votes=[], arb=None, consecutive_holds=0
    )
    assert out["arbitration"] == {}


def test_serialize_state_sanitizes_nan_and_inf_to_none():
    """A NaN yfinance price must not produce invalid JSON (NaN/Infinity
    tokens) or crash json.dumps under Starlette's strict encoder.
    """
    import json

    from api.serializers import serialize_state

    p = Portfolio()
    p.positions["AAPL"] = {"shares": 1.0, "avg_price": 100.0}
    p.last_prices = {"AAPL": float("nan")}
    p.peak_value = float("inf")

    out = serialize_state(
        portfolio=p, cycle=0, thinking=False, mode="live", votes=[], arb={}, consecutive_holds=0
    )

    assert out["value"] is None
    assert out["positions"][0]["lastPrice"] is None
    assert out["positions"][0]["pnlPct"] is None
    assert out["peakValue"] is None
    # And the whole thing must actually be valid JSON.
    json.dumps(out)


class _PausingLock:
    """Wraps a real lock; pauses right after the FIRST ``__exit__`` (i.e.
    right after ``with portfolio._lock:`` releases it) so a test can force
    a concurrent mutation into the window between lock-release and
    serialize_state's later (unlocked) reads of position fields.
    """

    def __init__(self, real_lock):
        self._lock = real_lock
        self.released = threading.Event()
        self.resume = threading.Event()
        self._first = True

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exc):
        self._lock.release()
        if self._first:
            self._first = False
            self.released.set()
            self.resume.wait(timeout=2.0)


def test_serialize_state_snapshots_position_fields_before_reading_them():
    """serialize_state() must copy each position dict under portfolio._lock,
    not just the outer positions dict — Portfolio.buy()'s pyramid branch
    mutates avg_price/shares as separate in-place writes on the SAME dict
    object, so a shallow dict(portfolio.positions) copy still shares those
    inner dicts. Reading pos["shares"]/pos.get("avg_price") happens AFTER
    releasing the lock — a concurrent write landing in that window would
    leak into an in-progress snapshot (Review Finding).
    """
    from api.serializers import serialize_state

    p = Portfolio()
    p.positions["AAPL"] = {"shares": 1.0, "avg_price": 100.0, "layers": 1}
    p.last_prices = {"AAPL": 150.0}

    pausing_lock = _PausingLock(p._lock)
    p._lock = pausing_lock

    result: dict = {}

    def _run():
        result["out"] = serialize_state(
            portfolio=p,
            cycle=0,
            thinking=False,
            mode="live",
            votes=[],
            arb={},
            consecutive_holds=0,
        )

    t = threading.Thread(target=_run)
    t.start()
    assert pausing_lock.released.wait(timeout=2.0), "serialize_state never released the lock"

    # Simulate a concurrent BUY pyramid update landing in the window right
    # after serialize_state released the lock but before it finished
    # reading this position's fields.
    p.positions["AAPL"]["avg_price"] = 999.0
    p.positions["AAPL"]["shares"] = 42.0

    pausing_lock.resume.set()
    t.join(timeout=2.0)

    pos_out = result["out"]["positions"][0]
    assert pos_out["avgPrice"] == 100.0, (
        "must reflect the value at snapshot time, not a later concurrent "
        f"mutation — got {pos_out['avgPrice']}"
    )
    assert (
        pos_out["shares"] == 1.0
    ), f"must reflect the value at snapshot time — got {pos_out['shares']}"


@pytest.mark.parametrize(
    "value,expected_state",
    [
        (2000.0, "CONFIDENT"),
        (1200.0, "FOCUSED"),
        (800.0, "CAUTIOUS"),
        (300.0, "ANXIOUS"),
        (10.0, "DESPERATE"),
    ],
)
def test_derive_emotion_bands(value, expected_state):
    from api.serializers import _derive_emotion

    assert _derive_emotion(value)["state"] == expected_state


# ═══════════════════════════════════════════════════════════════════════════
# auth.py — REST dependency
# ═══════════════════════════════════════════════════════════════════════════


def test_require_auth_disabled_allows_no_credentials(monkeypatch):
    import config
    from api.auth import require_auth

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "")
    require_auth(credentials=None)  # must not raise


def test_require_auth_enabled_missing_credentials_rejected(monkeypatch):
    import config
    from fastapi import HTTPException

    from api.auth import require_auth

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret123")
    with pytest.raises(HTTPException) as exc:
        require_auth(credentials=None)
    assert exc.value.status_code == 401


def test_require_auth_enabled_wrong_token_rejected(monkeypatch):
    import config
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from api.auth import require_auth

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret123")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
    with pytest.raises(HTTPException) as exc:
        require_auth(credentials=creds)
    assert exc.value.status_code == 401


def test_require_auth_enabled_correct_token_allows(monkeypatch):
    import config
    from fastapi.security import HTTPAuthorizationCredentials

    from api.auth import require_auth

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret123")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret123")
    require_auth(credentials=creds)  # must not raise


# ═══════════════════════════════════════════════════════════════════════════
# auth.py — WebSocket handshake
# ═══════════════════════════════════════════════════════════════════════════


class _FakeWS:
    def __init__(self, origin: str | None = None, token: str = ""):
        self.headers = {"origin": origin} if origin else {}
        self.query_params = {"token": token} if token else {}


def test_ws_auth_ok_disabled_allows_no_token(monkeypatch):
    import config

    from api.auth import ws_auth_ok

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "")
    assert ws_auth_ok(_FakeWS()) is True


def test_ws_auth_ok_disabled_still_rejects_bad_origin(monkeypatch):
    """Origin hijacking risk exists even with no password configured."""
    import config

    from api.auth import ws_auth_ok

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "")
    assert ws_auth_ok(_FakeWS(origin="http://evil.example")) is False


def test_ws_auth_ok_enabled_requires_matching_token(monkeypatch):
    import config

    from api.auth import ws_auth_ok

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret123")
    assert ws_auth_ok(_FakeWS(token="wrong")) is False
    assert ws_auth_ok(_FakeWS(token="secret123")) is True


def test_ws_auth_ok_enabled_allows_good_origin_with_token(monkeypatch):
    import config

    from api.auth import ws_auth_ok

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret123")
    assert ws_auth_ok(_FakeWS(origin="http://localhost:5173", token="secret123")) is True


# ═══════════════════════════════════════════════════════════════════════════
# broadcaster.py — ConnectionManager
# ═══════════════════════════════════════════════════════════════════════════


def _run(coro):
    return asyncio.run(coro)


def test_connection_manager_connect_and_broadcast():
    from api.broadcaster import ConnectionManager

    mgr = ConnectionManager()
    ws = AsyncMock()

    _run(mgr.connect(ws))
    ws.accept.assert_awaited_once()
    assert ws in mgr.active

    _run(mgr.broadcast({"type": "snapshot", "data": {"cash": 1.0}}))
    ws.send_text.assert_awaited_once()
    sent = ws.send_text.await_args.args[0]
    assert '"type": "snapshot"' in sent


def test_connection_manager_disconnect_removes_client():
    from api.broadcaster import ConnectionManager

    mgr = ConnectionManager()
    ws = AsyncMock()
    _run(mgr.connect(ws))
    mgr.disconnect(ws)
    assert ws not in mgr.active


def test_connection_manager_broadcast_drops_dead_sockets():
    """A socket whose send_text() raises is evicted, not left to raise again."""
    from api.broadcaster import ConnectionManager

    mgr = ConnectionManager()
    good, bad = AsyncMock(), AsyncMock()
    bad.send_text.side_effect = RuntimeError("connection closed")
    _run(mgr.connect(good))
    _run(mgr.connect(bad))

    _run(mgr.broadcast({"type": "ping"}))

    assert good in mgr.active
    assert bad not in mgr.active
    good.send_text.assert_awaited_once()


def test_broadcast_stalled_client_does_not_block_others():
    """A client whose send_text() never returns (e.g. a stalled TCP
    connection to a sleeping laptop) must not freeze delivery to every
    other connected client — broadcast() must send concurrently with a
    timeout, not sequentially awaiting each client in turn.
    """
    from api.broadcaster import ConnectionManager

    mgr = ConnectionManager()
    stalled, fast = AsyncMock(), AsyncMock()

    async def _never_returns(_data):
        await asyncio.sleep(3600)  # far longer than any reasonable test timeout

    stalled.send_text.side_effect = _never_returns

    _run(mgr.connect(stalled))
    _run(mgr.connect(fast))

    with patch("api.broadcaster._SEND_TIMEOUT_SEC", 0.2):
        _run(asyncio.wait_for(mgr.broadcast({"type": "ping"}), timeout=2.0))

    fast.send_text.assert_awaited_once()
    assert fast in mgr.active
    assert stalled not in mgr.active, "a timed-out client must be evicted, not left hanging"


def test_connection_manager_send_personal_disconnects_on_failure():
    from api.broadcaster import ConnectionManager

    mgr = ConnectionManager()
    ws = AsyncMock()
    ws.send_text.side_effect = RuntimeError("gone")
    _run(mgr.connect(ws))

    _run(mgr.send_personal(ws, {"type": "snapshot"}))
    assert ws not in mgr.active


# ═══════════════════════════════════════════════════════════════════════════
# routes/market.py — direct function calls (no HTTP cycle needed)
# ═══════════════════════════════════════════════════════════════════════════


def test_get_watchlist_prices_translates_contract(monkeypatch):
    """Backend snake_case must come out as a frontend-ready array of
    camelCase WatchlistItem objects (symbol injected per row).
    """
    from api.routes import market

    monkeypatch.setattr("agents.shared.watchlist.get_watchlist", lambda: ["AAPL"])
    monkeypatch.setattr(
        "market_data.quotes.fetch_watchlist_prices",
        lambda syms: {
            "AAPL": {
                "price": 150.5,
                "change_pct": 1.2,
                "change_abs": 1.8,
                "rsi_14": 55.0,
                "macd_hist": 0.1,
                "volume": 1000,
            }
        },
    )
    out = market.get_watchlist_prices()
    assert isinstance(out["watchlist"], list)
    row = next(r for r in out["watchlist"] if r["symbol"] == "AAPL")
    assert row["symbol"] == "AAPL"
    assert row["price"] == 150.5
    assert row["changePct"] == 1.2
    assert row["changeAbs"] == 1.8
    assert row["rsi"] == 55.0
    assert row["macdHist"] == 0.1


def test_get_watchlist_prices_error_returns_empty_shape(monkeypatch):
    monkeypatch.setattr(
        "agents.shared.watchlist.get_watchlist",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    from api.routes import market

    out = market.get_watchlist_prices()
    assert out["watchlist"] == []
    assert out["symbols"] == []
    assert "error" in out


def test_get_sectors_flattens_dict_of_dicts(monkeypatch):
    monkeypatch.setattr(
        "market_data.sectors.fetch_sector_performance",
        lambda: {"Tech": {"1d": 1.5, "5d": 3.0}, "Energy": {"1d": -0.5, "5d": 1.0}},
    )
    from api.routes import market

    out = market.get_sectors(period="1d")
    assert isinstance(out["sectors"], list)
    names = {s["name"] for s in out["sectors"]}
    assert names == {"Tech", "Energy"}
    tech = next(s for s in out["sectors"] if s["name"] == "Tech")
    assert tech["changePct"] == 1.5


def test_get_macro_translates_uppercase_keys(monkeypatch):
    monkeypatch.setattr(
        "market_data.macro.fetch_macro",
        lambda: {
            "VIX": {"price": 15.2, "change_pct": -1.1, "direction": "down"},
            "updated_at": "12:00:00",
        },
    )
    from api.routes import market

    out = market.get_macro()
    assert "vix" in out["macro"]
    assert out["macro"]["vix"]["value"] == "15.20"
    assert out["macro"]["vix"]["change"] == -1.1
    assert "updated_at" not in out["macro"]


def test_get_correlation_passes_through(monkeypatch):
    monkeypatch.setattr("agents.shared.watchlist.get_watchlist", lambda: ["AAPL", "MSFT"])
    monkeypatch.setattr(
        "market_data.correlation.fetch_correlation_matrix",
        lambda syms, **kw: {"symbols": syms, "matrix": [[1.0, 0.5], [0.5, 1.0]]},
    )
    from api.routes import market

    out = market.get_correlation()
    assert out["correlation"]["symbols"] == ["AAPL", "MSFT"]
    assert out["correlation"]["matrix"] == [[1.0, 0.5], [0.5, 1.0]]


def test_get_sparkline_translates_to_equity_points(monkeypatch):
    monkeypatch.setattr(
        "market_data.charts.fetch_sparkline",
        lambda sym: [
            {"time": "14:00", "price": 182.5, "open": 181.0},
            {"time": "15:00", "price": 183.1, "open": 182.5},
        ],
    )
    from api.routes import market

    out = market.get_sparkline("aapl")
    assert out["sparkline"] == [{"t": "14:00", "v": 182.5}, {"t": "15:00", "v": 183.1}]


def test_get_sparkline_error_returns_empty_list(monkeypatch):
    monkeypatch.setattr(
        "market_data.charts.fetch_sparkline",
        lambda sym: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    from api.routes import market

    out = market.get_sparkline("AAPL")
    assert out["sparkline"] == []
    assert "error" in out


# ═══════════════════════════════════════════════════════════════════════════
# routes/portfolio.py
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def _clean_controller_state():
    """Save/restore dashboard.controller._state around a test that pokes it."""
    from dashboard.controller import _state

    saved = dict(_state)
    yield _state
    _state.clear()
    _state.update(saved)


def test_get_portfolio_503_when_not_started(_clean_controller_state):
    from api.routes.portfolio import get_portfolio
    from fastapi import HTTPException

    _clean_controller_state["portfolio"] = None
    with pytest.raises(HTTPException) as exc:
        get_portfolio()
    assert exc.value.status_code == 503


def test_get_portfolio_200_when_started(_clean_controller_state):
    from api.routes.portfolio import get_portfolio

    p = Portfolio()
    _clean_controller_state["portfolio"] = p
    _clean_controller_state["last_votes"] = []
    _clean_controller_state["last_arb"] = {}
    _clean_controller_state["thinking"] = False
    _clean_controller_state["consecutive_holds"] = 0

    out = get_portfolio()
    assert out["cash"] == p.cash
    assert out["mode"] in ("live", "paper", "sim")


def test_get_portfolio_reads_live_mode_not_stale_ctrl(_clean_controller_state):
    """_ctrl["mode"] is only refreshed once per agent cycle — a mode switch
    via POST /api/control/mode must be visible immediately, not only after
    the next cycle starts (or never, while paused/dead).
    """
    from agents.shared import modes as modes_mod
    from api.routes.portfolio import get_portfolio
    from dashboard.controller import _ctrl

    p = Portfolio()
    _clean_controller_state["portfolio"] = p
    _clean_controller_state["last_votes"] = []
    _clean_controller_state["last_arb"] = {}
    _clean_controller_state["thinking"] = False
    _clean_controller_state["consecutive_holds"] = 0

    saved_ctrl_mode = _ctrl.get("mode")
    saved_sim, saved_paper = modes_mod._sim_mode["enabled"], modes_mod._paper_mode["enabled"]
    try:
        _ctrl["mode"] = "live"  # stale value a paused/dead agent loop never updated
        modes_mod._sim_mode["enabled"] = True
        modes_mod._paper_mode["enabled"] = False

        out = get_portfolio()
        assert out["mode"] == "sim"
    finally:
        _ctrl["mode"] = saved_ctrl_mode
        modes_mod._sim_mode["enabled"] = saved_sim
        modes_mod._paper_mode["enabled"] = saved_paper


def test_get_trades_reversed(_clean_controller_state):
    from api.routes.portfolio import get_trades

    p = Portfolio()
    p.trade_history = [{"action": "BUY", "symbol": "A"}, {"action": "SELL", "symbol": "B"}]
    _clean_controller_state["portfolio"] = p

    out = get_trades()
    assert out["trades"][0]["symbol"] == "B"  # most recent first
    assert out["trades"][1]["symbol"] == "A"


def test_get_analytics_column_mapping(tmp_db):
    """Regression guard for the postmortem/agent_memory column-name bugs
    fixed in Batch C — this must actually read the real schema columns.
    """
    from agents.shared.db import _db_write
    from api.routes.portfolio import get_analytics

    _db_write(
        "INSERT INTO postmortem "
        "(timestamp, symbol, buy_price, sell_price, pnl_pct, holding_hours, summary) "
        "VALUES (?,?,?,?,?,?,?)",
        ("2026-01-01T00:00:00", "AAPL", 100.0, 110.0, 10.0, 48.0, "held two days"),
    )
    for _ in range(5):
        _db_write(
            "INSERT INTO agent_memory (timestamp, agent_name, symbol, vote, confidence, was_correct) "
            "VALUES (?,?,?,?,?,?)",
            ("2026-01-01T00:00:00", "technician", "AAPL", "BUY", 0.8, 1),
        )

    out = get_analytics()
    assert len(out["postmortems"]) == 1
    pm = out["postmortems"][0]
    assert pm["sym"] == "AAPL"
    assert pm["entryPrice"] == 100.0
    assert pm["exitPrice"] == 110.0
    assert pm["holdDays"] == 2.0  # 48 holding_hours -> 2 days

    acc = next(a for a in out["agentAccuracy"] if a["role"] == "technician")
    assert acc["total"] == 5
    assert acc["accuracy"] == 100.0
    assert acc["validated"] is True  # >= 5 evaluated votes


# ═══════════════════════════════════════════════════════════════════════════
# routes/control.py
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def _reset_ctrl_paused():
    from dashboard.controller import _ctrl

    saved = _ctrl.get("paused", False)
    yield
    _ctrl["paused"] = saved


def test_set_mode_sim(monkeypatch):
    from agents.shared import modes as modes_mod
    from api.routes.control import ModeRequest, set_mode

    monkeypatch.setattr(modes_mod, "_write_env_var", lambda *a, **kw: None)
    modes_mod._sim_mode["enabled"] = False
    modes_mod._paper_mode["enabled"] = False
    try:
        out = set_mode(ModeRequest(mode="sim"))
        assert out == {"ok": True, "mode": "sim"}
        assert modes_mod._sim_mode["enabled"] is True
    finally:
        modes_mod._sim_mode["enabled"] = True
        modes_mod._paper_mode["enabled"] = False


def test_set_mode_unknown_returns_error():
    from api.routes.control import ModeRequest, set_mode

    out = set_mode(ModeRequest(mode="bogus"))
    assert out["ok"] is False
    assert "Unknown mode" in out["error"]


def test_pause_resume_toggle_ctrl_state(_reset_ctrl_paused):
    from api.routes.control import pause, resume
    from dashboard.controller import _ctrl

    out = pause()
    assert out == {"ok": True, "paused": True}
    assert _ctrl["paused"] is True

    out = resume()
    assert out == {"ok": True, "paused": False}
    assert _ctrl["paused"] is False


def test_get_watchlist_route(monkeypatch):
    monkeypatch.setattr("agents.shared.watchlist.get_watchlist", lambda: ["AAPL", "MSFT"])
    from api.routes.control import get_watchlist

    assert get_watchlist() == {"watchlist": ["AAPL", "MSFT"]}


def test_add_to_watchlist_route_delegates(monkeypatch):
    monkeypatch.setattr("agents.shared.watchlist.add_to_watchlist", lambda sym: True)
    from api.routes.control import WatchlistRequest, add_to_watchlist

    out = add_to_watchlist(WatchlistRequest(symbol="nvda"))
    assert out == {"ok": True, "symbol": "NVDA"}


def test_remove_from_watchlist_route_delegates(monkeypatch):
    monkeypatch.setattr("agents.shared.watchlist.remove_from_watchlist", lambda sym: False)
    from api.routes.control import WatchlistRequest, remove_from_watchlist

    out = remove_from_watchlist(WatchlistRequest(symbol="tsla"))
    assert out == {"ok": False, "symbol": "TSLA"}


# ═══════════════════════════════════════════════════════════════════════════
# main.py — app wiring + auth gate, end-to-end via TestClient
# ═══════════════════════════════════════════════════════════════════════════


def test_health_exempt_from_auth(monkeypatch, _clean_controller_state):
    """/health must be reachable without auth. start_controller is mocked
    (no real agent thread), so a live Portfolio is seeded explicitly rather
    than relying on whatever another test happened to leave in the shared
    controller state — otherwise this passes or fails based on test order.
    """
    import config

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret123")
    from fastapi.testclient import TestClient

    import api.main

    _clean_controller_state["portfolio"] = Portfolio()

    with patch("dashboard.controller.start_controller"):
        with TestClient(api.main.app) as client:
            resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["mode"] in ("live", "paper", "sim")


def test_health_returns_503_when_portfolio_dead(_clean_controller_state):
    """The FastAPI /health must fail its HTTP status (not just the body's
    "status" field) when the portfolio has died. A monitoring probe
    using `curl -f` never notices a dead agent if this always returns 200.
    """
    from api.main import health

    p = Portfolio()
    p.is_dead = True
    _clean_controller_state["portfolio"] = p

    response = health()
    assert response.status_code == 503
    import json

    body = json.loads(bytes(response.body))
    assert body["status"] == "dead"
    assert body["agent_alive"] is False


def test_health_returns_200_when_portfolio_alive(_clean_controller_state):
    from api.main import health

    p = Portfolio()
    _clean_controller_state["portfolio"] = p

    response = health()
    assert response.status_code == 200


def test_rest_routes_require_auth_when_enabled(monkeypatch):
    import config

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret123")
    from fastapi.testclient import TestClient

    import api.main

    with patch("dashboard.controller.start_controller"):
        with TestClient(api.main.app) as client:
            no_auth = client.get("/api/control/watchlist")
            wrong_auth = client.get(
                "/api/control/watchlist", headers={"Authorization": "Bearer wrong"}
            )
            right_auth = client.get(
                "/api/control/watchlist", headers={"Authorization": "Bearer secret123"}
            )
    assert no_auth.status_code == 401
    assert wrong_auth.status_code == 401
    assert right_auth.status_code == 200


def test_rest_routes_open_when_auth_disabled(monkeypatch):
    import config

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "")
    from fastapi.testclient import TestClient

    import api.main

    with patch("dashboard.controller.start_controller"):
        with TestClient(api.main.app) as client:
            resp = client.get("/api/control/watchlist")
    assert resp.status_code == 200
