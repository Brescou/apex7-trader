"""Tests for arbitrate_node deterministic filters: economist and geopolitician."""

import json
import os
import sqlite3
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.multi as multi_mod
from agents.multi import WEIGHTS, _route_arbitrate, arbitrate_node


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


def _llm_buy_response(symbol: str = "AAPL") -> str:
    """A well-formed LLM arbitration response that insists on BUY —
    exercising whether the deterministic dampers survive the LLM's own
    judgment, or are merely advisory in LIVE mode."""
    return json.dumps(
        {
            "action": "BUY",
            "symbol": symbol,
            "allocation_pct": 20,
            "confidence": 0.8,
            "reasoning": "Strong technical + fundamental signal.",
            "dissenting_agents": [],
            "consensus_level": "strong",
            "thoughts": "Conviction trade.",
            "emotion": "CONFIDENT",
            "market_intel": "",
        }
    )


class TestPostLLMVetoesInLiveMode:
    """The pre-LLM dampers only nudge the composite score the LLM sees as
    context — nothing stops the LLM from still emitting action=BUY at a
    healthy confidence. Only risk_score > 8 used to be re-checked after the
    LLM responded; geo/economic/correlation were purely advisory in LIVE
    mode even though they're hard filters in SIM/PAPER. These tests force
    the LLM branch (_no_llm_mode() == False) and mock _llm to always
    insist on BUY, then verify each veto still forces HOLD regardless.
    """

    @pytest.fixture(autouse=True)
    def _force_live_mode(self):
        saved_sim, saved_paper = multi_mod._sim_mode["enabled"], multi_mod._paper_mode["enabled"]
        multi_mod._sim_mode["enabled"] = False
        multi_mod._paper_mode["enabled"] = False
        yield
        multi_mod._sim_mode["enabled"] = saved_sim
        multi_mod._paper_mode["enabled"] = saved_paper

    def test_geo_risk_veto_overrides_llm_buy(self, tmp_db):
        with patch("agents.multi._llm", return_value=_llm_buy_response()):
            result = arbitrate_node(_make_state(geo_risk=9.0))
        assert result["decision"]["action"] == "HOLD"
        assert any("GEO RISK VETO" in m for m in _log_messages(result))

    def test_economic_headwind_veto_overrides_llm_buy(self, tmp_db):
        with patch("agents.multi._llm", return_value=_llm_buy_response()):
            result = arbitrate_node(_make_state(economic_score=-0.8))
        assert result["decision"]["action"] == "HOLD"
        assert any("ECONOMIC HEADWIND VETO" in m for m in _log_messages(result))

    def test_neutral_conditions_let_llm_buy_through(self, tmp_db):
        """Sanity check: the new vetoes must not fire on ordinary conditions —
        only extreme readings should override the LLM's own judgment."""
        with patch("agents.multi._llm", return_value=_llm_buy_response()):
            result = arbitrate_node(_make_state())
        assert result["decision"]["action"] == "BUY"
        assert not any("VETO" in m for m in _log_messages(result))

    def test_correlation_veto_overrides_llm_buy_on_correlated_symbol(self, tmp_db):
        state = _make_state()
        state["positions"] = {"MSFT": {"shares": 5.0, "avg_price": 300.0}}
        with patch("agents.multi._llm", return_value=_llm_buy_response("AAPL")):
            with patch("agents.multi._portfolio_correlation", return_value=0.9):
                result = arbitrate_node(state)
        assert result["decision"]["action"] == "HOLD"
        assert any("CORRELATION VETO" in m for m in _log_messages(result))


class TestPartialLLMResponseFallsBackToComposite:
    """validate_decision() runs the raw LLM JSON through a Pydantic model
    whose model_dump() always includes every field (symbol="", allocation_
    pct=0 for anything the LLM's JSON omitted) — arb.get(key, fallback)
    therefore never actually falls back, since the key is always present.
    A partial response (LLM forgot to repeat symbol/allocation_pct) must
    preserve the pre-LLM composite's values instead of silently blanking
    out an otherwise-valid BUY.
    """

    @pytest.fixture(autouse=True)
    def _force_live_mode(self):
        saved_sim, saved_paper = multi_mod._sim_mode["enabled"], multi_mod._paper_mode["enabled"]
        multi_mod._sim_mode["enabled"] = False
        multi_mod._paper_mode["enabled"] = False
        yield
        multi_mod._sim_mode["enabled"] = saved_sim
        multi_mod._paper_mode["enabled"] = saved_paper

    def test_missing_symbol_preserves_composite_symbol(self, tmp_db):
        partial = json.dumps({"action": "BUY", "confidence": 0.8, "reasoning": "ok"})
        with patch("agents.multi._llm", return_value=partial):
            result = arbitrate_node(_make_state())
        assert result["decision"]["action"] == "BUY"
        assert result["decision"]["symbol"] == "AAPL", (
            "a partial LLM JSON without 'symbol' must keep the pre-LLM composite's "
            f"target, not Pydantic's empty-string default: got {result['decision']['symbol']!r}"
        )

    def test_missing_allocation_pct_preserves_composite_allocation(self, tmp_db):
        partial = json.dumps({"action": "BUY", "symbol": "AAPL", "confidence": 0.8})
        with patch("agents.multi._llm", return_value=partial):
            result = arbitrate_node(_make_state())
        assert result["decision"]["allocation_pct"] > 0, (
            "a partial LLM JSON without 'allocation_pct' must keep the pre-LLM "
            "composite's sizing, not Pydantic's 0 default"
        )

    def test_explicit_symbol_from_llm_is_still_honored(self, tmp_db):
        """Sanity check: when the LLM *does* provide a symbol, it must win —
        the fallback must not swallow a legitimate override."""
        full = json.dumps({"action": "BUY", "symbol": "MSFT", "confidence": 0.8})
        with patch("agents.multi._llm", return_value=full):
            result = arbitrate_node(_make_state())
        assert result["decision"]["symbol"] == "MSFT"


class TestSimPaperResearchGateBypass:
    """In SIM/PAPER only technician (0.28) + analyst (0.32) feed the
    composite confidence score — max 0.60, structurally below the 0.72
    research gate even at unanimous max confidence. Without a mode-aware
    bypass, _route_arbitrate always sent SIM/PAPER into research(), whose
    sim_research() no-op just overwrites the real composite confidence with
    a flat 0.75 on every single cycle (Review Finding).
    """

    def test_static_weights_cap_composite_confidence_below_gate(self):
        """Structural proof of the bug: technician + analyst weights alone
        can never reach the 0.72 research gate."""
        assert WEIGHTS["technician"] + WEIGHTS["analyst"] < 0.72

    def test_sim_mode_bypasses_research_despite_low_confidence(self, tmp_db):
        state = {"confidence": 0.4, "research_iterations": 0, "skip_research": False}
        assert multi_mod._sim_mode["enabled"] is True
        assert _route_arbitrate(state) == "risk_check"

    def test_paper_mode_bypasses_research_despite_low_confidence(self, tmp_db):
        state = {"confidence": 0.4, "research_iterations": 0, "skip_research": False}
        saved_sim, saved_paper = multi_mod._sim_mode["enabled"], multi_mod._paper_mode["enabled"]
        multi_mod._sim_mode["enabled"] = False
        multi_mod._paper_mode["enabled"] = True
        try:
            assert _route_arbitrate(state) == "risk_check"
        finally:
            multi_mod._sim_mode["enabled"] = saved_sim
            multi_mod._paper_mode["enabled"] = saved_paper

    def test_live_mode_still_gates_on_confidence(self, tmp_db):
        """Sanity check: LIVE mode (real LLM research available) keeps the
        original confidence-gated routing untouched."""
        state = {"confidence": 0.4, "research_iterations": 0, "skip_research": False}
        saved_sim, saved_paper = multi_mod._sim_mode["enabled"], multi_mod._paper_mode["enabled"]
        multi_mod._sim_mode["enabled"] = False
        multi_mod._paper_mode["enabled"] = False
        try:
            assert _route_arbitrate(state) == "research"
        finally:
            multi_mod._sim_mode["enabled"] = saved_sim
            multi_mod._paper_mode["enabled"] = saved_paper


class TestSlowAgentCacheHitStillRecordsVote:
    """economist/geopolitician cache a vote for _SLOW_AGENT_TTL_SEC (15 min
    default) to avoid a redundant LLM call every ~90s agent cycle — but a
    cache HIT still bypassed _emit_vote() entirely, so almost every cycle
    (all but the rare cache-miss ones) left no agent_memory row at all for
    these two agents. was_correct/accuracy tracking and dynamic-weight
    blending silently under-counted their real participation (Review
    Finding).
    """

    @pytest.fixture(autouse=True)
    def _force_live_mode_and_fresh_cache(self, monkeypatch):
        saved_sim, saved_paper = multi_mod._sim_mode["enabled"], multi_mod._paper_mode["enabled"]
        multi_mod._sim_mode["enabled"] = False
        multi_mod._paper_mode["enabled"] = False
        monkeypatch.setattr(multi_mod, "_slow_agent_cache", {})
        yield
        multi_mod._sim_mode["enabled"] = saved_sim
        multi_mod._paper_mode["enabled"] = saved_paper

    def test_economist_cache_hit_records_agent_memory_row(self, tmp_db):
        cached_vote = {
            "agent": "economist",
            "action": "HOLD",
            "symbol": "",
            "confidence": 0.6,
            "economic_regime": "expansion",
            "economic_score": 0.2,
        }
        multi_mod._set_cached_vote("economist", cached_vote)

        state = {"round": 1, "positions": {}, "supervisor_brief": "", "macro_indicators": {}}
        result = multi_mod.economist_node(state)
        assert result["economist_vote"] == cached_vote

        with sqlite3.connect(str(tmp_db)) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM agent_memory WHERE agent_name='economist'"
            ).fetchone()[0]
        assert count == 1, "cache-hit vote must still be recorded in agent_memory"

    def test_geopolitician_cache_hit_records_agent_memory_row(self, tmp_db):
        cached_vote = {
            "agent": "geopolitician",
            "action": "HOLD",
            "symbol": "",
            "confidence": 0.6,
            "geopolitical_risk": 3,
            "geo_score": 0.0,
        }
        multi_mod._set_cached_vote("geopolitician", cached_vote)

        state = {"round": 1, "positions": {}, "supervisor_brief": "", "news": ""}
        result = multi_mod.geopolitician_node(state)
        assert result["geo_vote"] == cached_vote

        with sqlite3.connect(str(tmp_db)) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM agent_memory WHERE agent_name='geopolitician'"
            ).fetchone()[0]
        assert count == 1, "cache-hit vote must still be recorded in agent_memory"


class TestSimTechnicianSellsMostOverbought:
    """sim_technician's SELL branch must pick the MOST overbought held
    position (highest RSI = strongest reversal signal) — it previously
    used min(), copy-pasted from the oversold/BUY branch below it where the
    lowest RSI is the strongest signal, so it picked whichever holding was
    barely past the overbought threshold instead of the one most in need
    of exiting (Review Finding).
    """

    def test_picks_highest_rsi_among_overbought_holdings(self, monkeypatch, tmp_db):
        monkeypatch.setattr(multi_mod, "_rsi", lambda series: series[-1])
        monkeypatch.setattr(multi_mod, "get_watchlist", lambda: ["AAPL", "MSFT", "GOOG"])
        monkeypatch.setattr(
            multi_mod,
            "_sim_price_history",
            {"AAPL": [70.0], "MSFT": [95.0], "GOOG": [50.0]},
        )

        state = {
            "prices": {"AAPL": 100.0, "MSFT": 200.0, "GOOG": 150.0},
            "positions": {
                "AAPL": {"shares": 1.0, "avg_price": 90.0},
                "MSFT": {"shares": 1.0, "avg_price": 150.0},
            },
        }
        result = multi_mod.sim_technician(state)

        assert result["tech_vote"]["action"] == "SELL"
        assert result["tech_vote"]["symbol"] == "MSFT", (
            "must sell the most overbought holding (MSFT, RSI=95), not AAPL "
            f"(RSI=70) which is only barely over the threshold — got "
            f"{result['tech_vote']['symbol']!r}"
        )


class TestArbitratePromptWrapsVotesAsUntrusted:
    """analyst_node/geopolitician_node run with web_search=True — their
    free-text vote fields (reasoning, catalysts, risk_regions, ...) can
    echo content from a fetched web page, including a page crafted to look
    like an instruction. The votes JSON spliced into arbitrate_node's own
    LLM call must be wrapped in <untrusted_external_data> tags — the same
    treatment raw news text already gets elsewhere — and the arbitrate
    system prompt must carry UNTRUSTED_DATA_NOTICE, or a successful
    injection during a specialist's web_search call propagates unmarked
    into the arbitration LLM's own context (Review Finding — the news
    wrapping fix's remaining gap).
    """

    @pytest.fixture(autouse=True)
    def _force_live_mode(self):
        saved_sim, saved_paper = multi_mod._sim_mode["enabled"], multi_mod._paper_mode["enabled"]
        multi_mod._sim_mode["enabled"] = False
        multi_mod._paper_mode["enabled"] = False
        yield
        multi_mod._sim_mode["enabled"] = saved_sim
        multi_mod._paper_mode["enabled"] = saved_paper

    def test_votes_summary_is_wrapped_in_untrusted_tags(self, tmp_db):
        with patch("agents.multi._llm", return_value=_llm_buy_response()) as mock_llm:
            arbitrate_node(_make_state())

        user_content = mock_llm.call_args.args[2][0]["content"]
        assert '<untrusted_external_data source="agent_votes">' in user_content
        assert "</untrusted_external_data>" in user_content

        system_arg = mock_llm.call_args.kwargs["system"]
        assert "<untrusted_external_data>" in system_arg, (
            "arbitrate's own system prompt must instruct the model to treat "
            "wrapped content as data, not instructions"
        )


def test_route_to_agents_fans_out_to_all_six_specialists():
    """_route_to_agents() must Send to all 6 specialists — economist and
    geopolitician are the 5th/6th, added after the original 4; a coverage
    gap here would let either be silently dropped from the fan-out with no
    test catching it (Review Finding)."""
    sends = multi_mod._route_to_agents({})
    targets = {s.node for s in sends}
    assert targets == {
        "technician",
        "analyst",
        "risk_manager",
        "macro_watcher",
        "economist",
        "geopolitician",
    }
    assert len(sends) == 6, "each specialist must be targeted exactly once"
