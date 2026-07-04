"""Tests for agents/shared/schemas.py NaN handling in percentage/score clamps.

Covers the Review Finding: ``max(lo, min(hi, v))`` silently returns the
UPPER bound for a NaN input — every float comparison against NaN is False,
so ``min(hi, nan)`` keeps ``hi``, then ``max(lo, hi)`` keeps ``hi``. A
degraded/truncated LLM response with a NaN confidence or allocation_pct
was therefore turned into maximum fabricated conviction instead of being
rejected like any other invalid value.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.shared.schemas import (  # noqa: E402
    DecisionOutput,
    EconomistVote,
    GeoPoliticianVote,
    MacroVote,
    RiskVote,
    _clamp_pct,
    validate_decision,
    validate_economist_vote,
    validate_geo_vote,
    validate_macro_vote,
    validate_risk_vote,
)

NAN = float("nan")
INF = float("inf")


def test_clamp_pct_rejects_nan():
    assert _clamp_pct(NAN) == 0.0
    assert _clamp_pct(NAN, default=20.0) == 20.0


def test_clamp_pct_rejects_infinity():
    assert _clamp_pct(INF) == 0.0
    assert _clamp_pct(float("-inf")) == 0.0


def test_confidence_nan_defaults_instead_of_becoming_1():
    out = DecisionOutput(action="BUY", confidence=NAN)
    assert out.confidence == 0.5


def test_allocation_pct_nan_defaults_instead_of_becoming_100():
    out = DecisionOutput(action="BUY", allocation_pct=NAN)
    assert out.allocation_pct == 0.0


def test_validate_decision_with_nan_fields_end_to_end():
    raw = {"action": "BUY", "symbol": "NVDA", "confidence": NAN, "allocation_pct": NAN}
    out = validate_decision(raw)
    assert out["confidence"] == 0.5
    assert out["allocation_pct"] == 0.0


def test_risk_vote_var_1d_nan_defaults_to_zero():
    out = RiskVote(var_1d=NAN)
    assert out.var_1d == 0.0


def test_risk_vote_max_safe_allocation_nan_defaults():
    out = RiskVote(max_safe_allocation_pct=NAN)
    assert out.max_safe_allocation_pct == 20.0


def test_validate_risk_vote_nan_end_to_end():
    out = validate_risk_vote({"var_1d": NAN, "max_safe_allocation_pct": NAN})
    assert out["var_1d"] == 0.0
    assert out["max_safe_allocation_pct"] == 20.0


def test_macro_vote_score_nan_defaults_to_zero():
    out = MacroVote(macro_score=NAN)
    assert out.macro_score == 0.0


def test_validate_macro_vote_nan_end_to_end():
    out = validate_macro_vote({"macro_score": NAN})
    assert out["macro_score"] == 0.0


def test_economist_vote_score_nan_defaults_to_zero():
    out = EconomistVote(economic_score=NAN)
    assert out.economic_score == 0.0


def test_validate_economist_vote_nan_end_to_end():
    out = validate_economist_vote({"economic_score": NAN})
    assert out["economic_score"] == 0.0


def test_geopolitician_vote_score_nan_defaults_to_zero():
    out = GeoPoliticianVote(geo_score=NAN)
    assert out.geo_score == 0.0


def test_validate_geo_vote_nan_end_to_end():
    out = validate_geo_vote({"geo_score": NAN})
    assert out["geo_score"] == 0.0


def test_isnan_isinf_are_actually_exercised():
    """Sanity guard on the test itself: confirm Python's own min/max would
    have produced the wrong (upper-bound) answer without the isnan/isinf
    check, so this suite is testing something real.
    """
    assert max(0.0, min(100.0, NAN)) == 100.0
    assert math.isnan(NAN)
