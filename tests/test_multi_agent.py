"""Tests for arbitrate_node deterministic filters: economist and geopolitician."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.multi as multi_mod
from agents.multi import arbitrate_node


def _make_state(
    *,
    economic_score: float = 0.0,
    geo_risk: float = 3.0,
    risk_score: float = 3.0,
    macro_regime: str = "neutral",
    confidence: float = 0.8,
) -> dict:
    """Minimal MultiAgentState for arbitrate_node tests in SIM mode (no LLM)."""
    votes = [
        {
            "agent": "technician",
            "action": "BUY",
            "confidence": confidence,
            "symbol": "AAPL",
            "key_indicators": [],
            "sell_pct": 100,
        },
        {
            "agent": "analyst",
            "action": "BUY",
            "confidence": confidence,
            "symbol": "AAPL",
            "catalysts": [],
            "sentiment_score": 0.5,
        },
        {
            "agent": "risk_manager",
            "action": "HOLD",
            "confidence": 0.5,
            "risk_score": risk_score,
            "sizing_recommendation": "FULL",
            "max_safe_allocation_pct": 20,
            "var_1d": 0.01,
        },
        {
            "agent": "macro_watcher",
            "action": "HOLD",
            "confidence": 0.5,
            "market_regime": macro_regime,
            "macro_bias": "neutral",
            "macro_score": 0.0,
            "reasoning": "",
        },
        {
            "agent": "economist",
            "action": "HOLD",
            "confidence": 0.5,
            "economic_regime": "expansion",
            "economic_score": economic_score,
            "rate_trajectory": "pausing",
            "yield_curve": "normal",
            "inflation_regime": "moderate",
        },
        {
            "agent": "geopolitician",
            "action": "HOLD",
            "confidence": 0.5,
            "geopolitical_risk": geo_risk,
            "geo_bias": "neutral",
            "geo_score": 0.0,
        },
    ]
    return {
        "agent_votes": votes,
        "agent_role": "",
        "supervisor_brief": "",
        "tech_vote": None,
        "analyst_vote": None,
        "risk_vote": None,
        "macro_vote": None,
        "arbitration": None,
        "decision": None,
        "round": 1,
        "positions": {},
        "balance": 1000.0,
        "skip_research": True,
        "confidence": 0.0,
        "emotion": "CALM",
        "thoughts": "",
    }


def _log_messages(result: dict) -> list[str]:
    return [e["message"] for e in result.get("log", [])]


def _buy_score(result: dict) -> float:
    return float(result["arbitration"]["action_scores"]["BUY"])


@pytest.fixture(autouse=True)
def _reset_weights_cache(monkeypatch):
    """Reset the dynamic-weights cache so each test computes fresh static weights."""
    monkeypatch.setattr(multi_mod, "_cached_weights", None)
    monkeypatch.setattr(multi_mod, "_weights_computed_at", 0.0)


class TestEconomicHeadwindFilter:
    def test_fires_when_score_below_minus_half(self, tmp_db):
        result = arbitrate_node(_make_state(economic_score=-0.7))
        assert any("ECONOMIC HEADWIND" in m for m in _log_messages(result))

    def test_buy_score_dampened_by_60pct(self, tmp_db):
        neutral = arbitrate_node(_make_state(economic_score=0.0))
        headwind = arbitrate_node(_make_state(economic_score=-0.7))
        ratio = _buy_score(headwind) / _buy_score(neutral)
        assert abs(ratio - 0.6) < 0.01, f"expected 0.6× dampen, got {ratio:.4f}"

    def test_does_not_fire_at_threshold(self, tmp_db):
        result = arbitrate_node(_make_state(economic_score=-0.5))
        assert not any("ECONOMIC HEADWIND" in m for m in _log_messages(result))

    def test_fires_just_below_threshold(self, tmp_db):
        result = arbitrate_node(_make_state(economic_score=-0.51))
        assert any("ECONOMIC HEADWIND" in m for m in _log_messages(result))

    def test_positive_score_no_filter(self, tmp_db):
        result = arbitrate_node(_make_state(economic_score=0.8))
        assert not any("ECONOMIC HEADWIND" in m for m in _log_messages(result))


class TestGeoRiskFilter:
    def test_fires_when_risk_above_7(self, tmp_db):
        result = arbitrate_node(_make_state(geo_risk=9.0))
        assert any("GEO RISK HIGH" in m for m in _log_messages(result))

    def test_buy_score_dampened_by_50pct(self, tmp_db):
        neutral = arbitrate_node(_make_state(geo_risk=3.0))
        high_risk = arbitrate_node(_make_state(geo_risk=9.0))
        ratio = _buy_score(high_risk) / _buy_score(neutral)
        assert abs(ratio - 0.5) < 0.01, f"expected 0.5× dampen, got {ratio:.4f}"

    def test_does_not_fire_at_threshold(self, tmp_db):
        result = arbitrate_node(_make_state(geo_risk=7.0))
        assert not any("GEO RISK HIGH" in m for m in _log_messages(result))

    def test_fires_above_threshold(self, tmp_db):
        result = arbitrate_node(_make_state(geo_risk=7.1))
        assert any("GEO RISK HIGH" in m for m in _log_messages(result))

    def test_low_risk_no_filter(self, tmp_db):
        result = arbitrate_node(_make_state(geo_risk=2.0))
        assert not any("GEO RISK HIGH" in m for m in _log_messages(result))


class TestCombinedFilters:
    def test_economic_and_geo_compound_to_30pct(self, tmp_db):
        neutral = arbitrate_node(_make_state())
        combined = arbitrate_node(_make_state(economic_score=-0.7, geo_risk=9.0))
        ratio = _buy_score(combined) / _buy_score(neutral)
        assert abs(ratio - 0.3) < 0.01, f"expected 0.3× (0.6×0.5) dampen, got {ratio:.4f}"

    def test_both_log_messages_present(self, tmp_db):
        result = arbitrate_node(_make_state(economic_score=-0.7, geo_risk=9.0))
        msgs = _log_messages(result)
        assert any("ECONOMIC HEADWIND" in m for m in msgs)
        assert any("GEO RISK HIGH" in m for m in msgs)

    def test_combined_does_not_fire_at_boundaries(self, tmp_db):
        result = arbitrate_node(_make_state(economic_score=-0.5, geo_risk=7.0))
        msgs = _log_messages(result)
        assert not any("ECONOMIC HEADWIND" in m for m in msgs)
        assert not any("GEO RISK HIGH" in m for m in msgs)


class TestRiskVeto:
    def test_fires_when_risk_score_above_8(self, tmp_db):
        result = arbitrate_node(_make_state(risk_score=9.0))
        assert any("RISK VETO" in m for m in _log_messages(result))

    def test_buy_score_reduced_to_15pct(self, tmp_db):
        neutral = arbitrate_node(_make_state(risk_score=3.0))
        veto = arbitrate_node(_make_state(risk_score=9.0))
        ratio = _buy_score(veto) / _buy_score(neutral)
        assert abs(ratio - 0.15) < 0.01, f"expected 0.15× (RISK VETO), got {ratio:.4f}"

    def test_does_not_fire_at_exactly_8(self, tmp_db):
        result = arbitrate_node(_make_state(risk_score=8.0))
        assert not any("RISK VETO" in m for m in _log_messages(result))

    def test_fires_above_8(self, tmp_db):
        result = arbitrate_node(_make_state(risk_score=8.1))
        assert any("RISK VETO" in m for m in _log_messages(result))
