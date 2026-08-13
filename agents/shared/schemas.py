"""agents.shared.schemas — Pydantic validation for LLM decision outputs."""

import math

from pydantic import BaseModel, Field, field_validator

# ── Shared validators ────────────────────────────────────────────────────────


def _clamp_pct(v: float, default: float = 0.0) -> float:
    """Clamp a percentage value to [0, 100]. Used as a before-validator.

    NaN must be rejected explicitly: ``max(lo, min(hi, v))`` silently
    returns the UPPER bound for NaN (every comparison against NaN is False,
    so ``min(100.0, nan)`` keeps ``100.0``, then ``max(0.0, 100.0)`` keeps
    ``100.0``) — turning a value that should be treated as entirely
    invalid into the maximum allowed allocation instead of the default.
    """
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return max(0.0, min(100.0, v))


class _ActionConfidenceMixin(BaseModel):
    """Shared field validators for action + confidence across all vote schemas."""

    action: str = Field(default="HOLD")
    confidence: float = Field(default=0.5, ge=0, le=1.0)

    @field_validator("action", mode="before")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if not isinstance(v, str):
            return "HOLD"
        v = v.upper().strip()
        if v not in ("BUY", "SELL", "HOLD"):
            return "HOLD"
        return v

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.5
        if math.isnan(v) or math.isinf(v):
            return 0.5
        if v > 1.0:
            v = v / 100.0
        return max(0.0, min(1.0, v))


# ── Decision (arbitrate_node) ────────────────────────────────────────────────


class DecisionOutput(_ActionConfidenceMixin):
    """Validates the JSON output from ``arbitrate_node``."""

    symbol: str = Field(default="")
    allocation_pct: float = Field(default=0, ge=0, le=100)
    sell_pct: float = Field(default=100, ge=0, le=100)

    @field_validator("allocation_pct", "sell_pct", mode="before")
    @classmethod
    def clamp_pct(cls, v: float) -> float:
        return _clamp_pct(v)

    reasoning: str = Field(default="")
    thoughts: str = Field(default="")
    emotion: str = Field(default="CALM")
    market_intel: str = Field(default="")

    @field_validator("emotion", mode="before")
    @classmethod
    def validate_emotion(cls, v: str) -> str:
        valid = {"CALM", "FOCUSED", "EXCITED", "NERVOUS", "PANIC", "EUPHORIC", "DESPERATE"}
        if not isinstance(v, str) or v.upper() not in valid:
            return "CALM"
        return v.upper()

    @field_validator("symbol", mode="before")
    @classmethod
    def clean_symbol(cls, v: str) -> str:
        if not isinstance(v, str):
            return ""
        return v.strip().upper()


# ── Specialist votes ─────────────────────────────────────────────────────────


class TechVote(_ActionConfidenceMixin):
    """Validates technician agent vote."""

    agent: str = Field(default="technician")
    symbol: str = Field(default="")
    allocation_pct: float = Field(default=0, ge=0, le=100)
    reasoning: str = Field(default="")
    key_indicators: dict = Field(
        default_factory=lambda: {
            "rsi": 50.0,
            "macd": "neutral",
            "bb": "mid",
            "trend": "sideways",
        }
    )

    @field_validator("allocation_pct", mode="before")
    @classmethod
    def clamp_alloc(cls, v: float) -> float:
        return _clamp_pct(v)


class AnalystVote(_ActionConfidenceMixin):
    """Validates analyst agent vote."""

    agent: str = Field(default="analyst")
    symbol: str = Field(default="")
    allocation_pct: float = Field(default=0, ge=0, le=100)
    reasoning: str = Field(default="")
    catalysts: list[str] = Field(default_factory=list)
    sentiment_score: float = Field(default=0.0)

    @field_validator("allocation_pct", mode="before")
    @classmethod
    def clamp_alloc(cls, v: float) -> float:
        return _clamp_pct(v)


class RiskVote(BaseModel):
    """Validates risk_manager agent vote.

    Risk manager does not vote on direction — no action/confidence mixin.
    """

    agent: str = Field(default="risk_manager")
    risk_score: int = Field(default=5, ge=0, le=10)
    max_safe_allocation_pct: float = Field(default=20.0, ge=0, le=100)
    var_1d: float = Field(default=0.0, ge=0)
    portfolio_exposure_after: float = Field(default=0.0)
    sizing_recommendation: str = Field(default="HALF")
    reasoning: str = Field(default="")
    warnings: list[str] = Field(default_factory=list)

    @field_validator("sizing_recommendation", mode="before")
    @classmethod
    def validate_sizing(cls, v: str) -> str:
        valid = {"FULL", "HALF", "QUARTER", "SKIP"}
        if not isinstance(v, str) or v.upper() not in valid:
            return "HALF"
        return v.upper()

    @field_validator("risk_score", mode="before")
    @classmethod
    def clamp_risk_score(cls, v: int) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 5
        return max(0, min(10, v))

    @field_validator("max_safe_allocation_pct", mode="before")
    @classmethod
    def clamp_alloc(cls, v: float) -> float:
        return _clamp_pct(v, default=20.0)

    @field_validator("var_1d", mode="before")
    @classmethod
    def clamp_var(cls, v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.0
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return max(0.0, v)


class MacroVote(BaseModel):
    """Validates macro_watcher agent vote."""

    agent: str = Field(default="macro_watcher")
    market_regime: str = Field(default="transitional")
    macro_bias: str = Field(default="neutral")
    recommended_exposure: int = Field(default=50, ge=0, le=100)
    sector_rotation: str = Field(default="balanced")
    reasoning: str = Field(default="")
    macro_score: float = Field(default=0.0, ge=-1.0, le=1.0)

    @field_validator("market_regime", mode="before")
    @classmethod
    def validate_regime(cls, v: str) -> str:
        valid = {"risk-on", "risk-off", "transitional"}
        if not isinstance(v, str) or v.lower() not in valid:
            return "transitional"
        return v.lower()

    @field_validator("macro_bias", mode="before")
    @classmethod
    def validate_bias(cls, v: str) -> str:
        valid = {"bullish", "bearish", "neutral"}
        if not isinstance(v, str) or v.lower() not in valid:
            return "neutral"
        return v.lower()

    @field_validator("macro_score", mode="before")
    @classmethod
    def clamp_macro_score(cls, v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.0
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return max(-1.0, min(1.0, v))


class EconomistVote(BaseModel):
    """Validates economist agent vote — provides macro cycle context, no direction."""

    agent: str = Field(default="economist")
    economic_regime: str = Field(default="transitional")
    rate_trajectory: str = Field(default="pausing")
    yield_curve: str = Field(default="normal")
    inflation_regime: str = Field(default="moderate")
    economic_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    reasoning: str = Field(default="")

    @field_validator("economic_regime", mode="before")
    @classmethod
    def validate_regime(cls, v: str) -> str:
        valid = {"expansion", "slowdown", "recession", "recovery", "transitional"}
        if not isinstance(v, str) or v.lower() not in valid:
            return "transitional"
        return v.lower()

    @field_validator("rate_trajectory", mode="before")
    @classmethod
    def validate_rate(cls, v: str) -> str:
        valid = {"hiking", "pausing", "cutting"}
        if not isinstance(v, str) or v.lower() not in valid:
            return "pausing"
        return v.lower()

    @field_validator("yield_curve", mode="before")
    @classmethod
    def validate_curve(cls, v: str) -> str:
        valid = {"normal", "flat", "inverted"}
        if not isinstance(v, str) or v.lower() not in valid:
            return "normal"
        return v.lower()

    @field_validator("inflation_regime", mode="before")
    @classmethod
    def validate_inflation(cls, v: str) -> str:
        valid = {"high", "moderate", "low"}
        if not isinstance(v, str) or v.lower() not in valid:
            return "moderate"
        return v.lower()

    @field_validator("economic_score", mode="before")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.0
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return max(-1.0, min(1.0, v))


class GeoPoliticianVote(BaseModel):
    """Validates geopolitician agent vote — evaluates geopolitical risk, no direction."""

    agent: str = Field(default="geopolitician")
    geopolitical_risk: int = Field(default=3, ge=0, le=10)
    risk_regions: list[str] = Field(default_factory=list)
    affected_sectors: list[str] = Field(default_factory=list)
    geo_bias: str = Field(default="neutral")
    geo_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    reasoning: str = Field(default="")

    @field_validator("geopolitical_risk", mode="before")
    @classmethod
    def clamp_geo_risk(cls, v: int) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 3
        return max(0, min(10, v))

    @field_validator("geo_bias", mode="before")
    @classmethod
    def validate_bias(cls, v: str) -> str:
        valid = {"cautious", "neutral", "favorable"}
        if not isinstance(v, str) or v.lower() not in valid:
            return "neutral"
        return v.lower()

    @field_validator("geo_score", mode="before")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.0
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return max(-1.0, min(1.0, v))


# ── Validation helpers ───────────────────────────────────────────────────────


def validate_decision(raw: dict) -> dict:
    """Validate a raw LLM decision dict through Pydantic. Returns validated dict."""
    try:
        return DecisionOutput(**raw).model_dump()
    except Exception:
        return DecisionOutput().model_dump()


def validate_tech_vote(raw: dict) -> dict:
    """Validate a raw technician vote. Returns validated dict."""
    try:
        return TechVote(**raw).model_dump()
    except Exception:
        return TechVote().model_dump()


def validate_analyst_vote(raw: dict) -> dict:
    """Validate a raw analyst vote. Returns validated dict."""
    try:
        return AnalystVote(**raw).model_dump()
    except Exception:
        return AnalystVote().model_dump()


def validate_risk_vote(raw: dict) -> dict:
    """Validate a raw risk manager vote. Returns validated dict."""
    try:
        return RiskVote(**raw).model_dump()
    except Exception:
        return RiskVote().model_dump()


def validate_macro_vote(raw: dict) -> dict:
    """Validate a raw macro watcher vote. Returns validated dict."""
    try:
        return MacroVote(**raw).model_dump()
    except Exception:
        return MacroVote().model_dump()


def validate_economist_vote(raw: dict) -> dict:
    """Validate a raw economist vote. Returns validated dict."""
    try:
        return EconomistVote(**raw).model_dump()
    except Exception:
        return EconomistVote().model_dump()


def validate_geo_vote(raw: dict) -> dict:
    """Validate a raw geopolitician vote. Returns validated dict."""
    try:
        return GeoPoliticianVote(**raw).model_dump()
    except Exception:
        return GeoPoliticianVote().model_dump()
