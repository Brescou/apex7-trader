"""Integration tests for APEX-7 with deterministic LLM mocks.

Run with:  uv run pytest tests/test_integration.py -v
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["SIMULATION_MODE"] = "true"
os.environ["PORTFOLIO_SAVE_ENABLED"] = "false"
os.environ["USE_LIVEFEED"] = "false"


MOCK_ANALYZE_RESPONSE = json.dumps(
    {
        "thoughts": "RSI is low, momentum building. Good entry point.",
        "emotion": "FOCUSED",
        "action": "BUY",
        "symbol": "AAPL",
        "allocation_pct": 20,
        "sell_pct": 0,
        "reasoning": "RSI oversold at 28, strong support at 180",
        "confidence": 0.82,
        "market_intel": "Tech sector showing strength",
    }
)

MOCK_HOLD_RESPONSE = json.dumps(
    {
        "thoughts": "No clear setup. Sitting on hands.",
        "emotion": "CALM",
        "action": "HOLD",
        "symbol": "",
        "allocation_pct": 0,
        "sell_pct": 0,
        "reasoning": "Market is choppy, no edge",
        "confidence": 0.55,
        "market_intel": "Mixed signals",
    }
)

MOCK_SELL_RESPONSE = json.dumps(
    {
        "thoughts": "Target hit, locking in profits.",
        "emotion": "EXCITED",
        "action": "SELL",
        "symbol": "AAPL",
        "allocation_pct": 0,
        "sell_pct": 100,
        "reasoning": "RSI overbought at 78, resistance at 195",
        "confidence": 0.85,
        "market_intel": "Taking profits before earnings",
    }
)


def _mock_llm_factory(response_text: str):
    """Create a mock for _llm that returns a fixed response."""

    def mock_llm(client, model, messages, system="", max_tokens=1024, web_search=False):
        return response_text

    return mock_llm


def test_simple_graph_buy_flow():
    """Test the simple graph with a mocked BUY decision."""
    from agents.simple import build_graph
    from agents.shared.nodes import _sim_mode
    from core.data import Portfolio

    _sim_mode["enabled"] = False

    p = Portfolio()
    g = build_graph(p)

    initial = {
        "balance": p.cash,
        "positions": dict(p.positions),
        "portfolio_history": [],
        "prices": {"AAPL": 185.0, "MSFT": 415.0, "GOOG": 165.0, "AMZN": 185.0, "TSLA": 250.0},
        "news": "AAPL showing strong momentum",
        "sentiment": {"AAPL": 0.5, "MSFT": 0.1},
        "past_trades": [],
        "known_patterns": [],
        "round": 1,
        "confidence": 0.0,
        "research_iterations": 0,
        "decision": None,
        "emotion": "CALM",
        "thoughts": "",
        "log": [],
        "alive": True,
        "skip_research": True,
    }

    with patch("agents.shared.nodes._llm", side_effect=_mock_llm_factory(MOCK_ANALYZE_RESPONSE)):
        result = g.invoke(initial)

    assert result is not None
    assert result["alive"] is True
    assert len(result["log"]) > 0
    assert "AAPL" in p.positions, "Expected BUY to create AAPL position"

    _sim_mode["enabled"] = True


def test_simple_graph_hold_flow():
    """Test the simple graph with a mocked HOLD decision."""
    from agents.simple import build_graph
    from agents.shared.nodes import _sim_mode
    from core.data import Portfolio

    _sim_mode["enabled"] = False

    p = Portfolio()
    g = build_graph(p)

    initial = {
        "balance": p.cash,
        "positions": dict(p.positions),
        "portfolio_history": [],
        "prices": {"AAPL": 185.0, "MSFT": 415.0, "GOOG": 165.0, "AMZN": 185.0, "TSLA": 250.0},
        "news": "Market is flat",
        "sentiment": {"AAPL": 0.0},
        "past_trades": [],
        "known_patterns": [],
        "round": 1,
        "confidence": 0.0,
        "research_iterations": 0,
        "decision": None,
        "emotion": "CALM",
        "thoughts": "",
        "log": [],
        "alive": True,
        "skip_research": True,
    }

    with patch("agents.shared.nodes._llm", side_effect=_mock_llm_factory(MOCK_HOLD_RESPONSE)):
        result = g.invoke(initial)

    assert result is not None
    assert result["alive"] is True
    assert len(p.positions) == 0, "HOLD should not create any position"
    assert p.cash == 1000.0, "HOLD should not change cash"

    _sim_mode["enabled"] = True


def test_schema_validation_invalid_input():
    """Test that DecisionOutput handles invalid/malformed LLM output gracefully."""
    from agents.shared.schemas import validate_decision

    malformed = {"action": "YOLO", "confidence": 150, "symbol": "aapl"}
    result = validate_decision(malformed)

    assert (
        result["action"] == "HOLD"
    ), f"Invalid action should default to HOLD, got {result['action']}"
    assert (
        result["confidence"] == 1.0
    ), f"Confidence 150 should clamp to 1.0, got {result['confidence']}"
    assert result["symbol"] == "AAPL", f"Symbol should be uppercased, got {result['symbol']}"


def test_schema_validation_empty_input():
    """Test that DecisionOutput handles empty dict."""
    from agents.shared.schemas import validate_decision

    result = validate_decision({})

    assert result["action"] == "HOLD"
    assert result["confidence"] == 0.5
    assert result["symbol"] == ""
    assert result["emotion"] == "CALM"


def test_tech_vote_validation():
    """Test TechVote Pydantic validation for malformed LLM output."""
    from agents.shared.schemas import validate_tech_vote

    malformed = {"action": "YOLO", "confidence": 200, "symbol": "msft", "allocation_pct": 150}
    result = validate_tech_vote(malformed)

    assert result["action"] == "HOLD"
    assert result["confidence"] == 1.0
    assert result["agent"] == "technician"
    assert "key_indicators" in result


def test_analyst_vote_validation():
    """Test AnalystVote Pydantic validation."""
    from agents.shared.schemas import validate_analyst_vote

    result = validate_analyst_vote({})
    assert result["action"] == "HOLD"
    assert result["agent"] == "analyst"
    assert isinstance(result["catalysts"], list)
    assert result["sentiment_score"] == 0.0


def test_risk_vote_validation():
    """Test RiskVote Pydantic validation with out-of-range values."""
    from agents.shared.schemas import validate_risk_vote

    malformed = {"risk_score": 15, "sizing_recommendation": "MEGA", "max_safe_allocation_pct": 200}
    result = validate_risk_vote(malformed)

    assert result["risk_score"] == 10
    assert result["sizing_recommendation"] == "HALF"
    assert result["agent"] == "risk_manager"


def test_macro_vote_validation():
    """Test MacroVote Pydantic validation."""
    from agents.shared.schemas import validate_macro_vote

    malformed = {"market_regime": "crash", "macro_bias": "yolo", "macro_score": 5.0}
    result = validate_macro_vote(malformed)

    assert result["market_regime"] == "transitional"
    assert result["macro_bias"] == "neutral"
    assert result["macro_score"] == 1.0
    assert result["agent"] == "macro_watcher"


def test_rsi_canonical():
    """Test that the canonical RSI implementation returns expected values."""
    import pandas as pd

    from core.indicators import rsi

    assert rsi([]) == 50.0
    assert rsi([100.0] * 5) == 50.0

    prices_up = [100.0 + i for i in range(20)]
    assert rsi(prices_up) == 100.0
    assert rsi(pd.Series(prices_up)) == rsi(prices_up)

    prices_down = [100.0 - i for i in range(20)]
    assert rsi(prices_down) == 0.0

    prices_mixed = [
        100.0,
        101.0,
        99.0,
        102.0,
        98.0,
        103.0,
        97.0,
        104.0,
        96.0,
        105.0,
        95.0,
        106.0,
        94.0,
        107.0,
        93.0,
        108.0,
    ]
    result = rsi(prices_mixed)
    assert 30.0 < result < 70.0, f"Mixed prices RSI should be near 50, got {result}"


def test_db_write_helper(tmp_db):
    """Test that _db_write handles operations correctly via the trades schema."""
    import sqlite3

    from agents.shared.nodes import _db_write, _get_db_path

    db_path = _get_db_path()
    assert str(tmp_db) == str(db_path)

    success = _db_write(
        "INSERT INTO patterns (timestamp, pattern) VALUES (?,?)",
        ("2026-01-01T00:00:00", "__test_pattern__"),
    )
    assert success, "_db_write should return True on success"

    con = sqlite3.connect(db_path)
    row = con.execute("SELECT pattern FROM patterns WHERE pattern='__test_pattern__'").fetchone()
    con.close()
    assert row is not None, "Pattern should exist in DB"
    assert row[0] == "__test_pattern__"

    _db_write(
        "DELETE FROM patterns WHERE pattern=?",
        ("__test_pattern__",),
    )


def test_db_read_helper(tmp_db):
    """Test that _db_read returns results correctly."""
    from agents.shared.nodes import _db_read, _db_write

    _db_write(
        "INSERT INTO patterns (timestamp, pattern) VALUES (?,?)",
        ("2026-01-01T00:00:00", "__test_read__"),
    )

    rows = _db_read("SELECT pattern FROM patterns WHERE pattern=?", ("__test_read__",))
    assert len(rows) == 1
    assert rows[0][0] == "__test_read__"

    _db_write("DELETE FROM patterns WHERE pattern=?", ("__test_read__",))


def test_ensure_db_idempotent(tmp_db):
    """Test that _ensure_db can be called multiple times safely."""
    from agents.shared.nodes import _ensure_db

    _ensure_db()
    _ensure_db()


def test_simulation_mode_toggle():
    """Test that simulation mode can be toggled.

    Mocks ``_write_env_var`` so toggling does not mutate the developer's ``.env``
    (Finding 5.2).
    """
    from agents.shared.nodes import get_simulation_mode, set_simulation_mode

    original = get_simulation_mode()
    with patch("agents.shared.nodes._write_env_var"):
        try:
            set_simulation_mode(True)
            assert get_simulation_mode() is True

            set_simulation_mode(False)
            assert get_simulation_mode() is False
        finally:
            set_simulation_mode(original)


def test_token_counter_daily_reset():
    """Test that the token counter resets daily."""
    from agents.shared.nodes import _maybe_reset_token_counter, _token_counter

    _token_counter["input"] = 999
    _token_counter["output"] = 888
    _token_counter["reset_date"] = "2020-01-01"

    _maybe_reset_token_counter()

    assert _token_counter["input"] == 0
    assert _token_counter["output"] == 0
    assert _token_counter["reset_date"] != "2020-01-01"
