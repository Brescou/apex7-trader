"""Anthropic clients, ``_llm`` helper, token budget, and circuit breaker."""

import logging
import threading
import time
from datetime import date
from typing import Any

import anthropic
import httpx

from config import ANTHROPIC_API_KEY

logger = logging.getLogger("apex7")

SONNET_ID = "claude-sonnet-4-5"
HAIKU_ID = "claude-haiku-4-5-20251001"

_API_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
sonnet = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=_API_TIMEOUT)
haiku = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=_API_TIMEOUT)

# Lock ordering (always acquire in this order to prevent deadlocks):
# 1. _circuit_breaker_lock
# 2. _token_counter_lock (RLock — re-entrant for nested budget checks)
# 3. _degradation_lock (via _set_llm_degradation / get_llm_degradation_status)
# 4. _live_price_history_lock (RSI seed flag + history; lowest contention) — in nodes

_token_counter: dict = {"input": 0, "output": 0, "max_daily": 500_000, "reset_date": ""}
_token_counter_lock = threading.RLock()
_circuit_breaker: dict = {"consecutive_failures": 0, "paused_until": 0.0}
_circuit_breaker_lock = threading.Lock()
_CIRCUIT_BREAKER_THRESHOLD = 3
_CIRCUIT_BREAKER_PAUSE = 300  # 5 minutes

_degradation_status: dict[str, Any] = {"active": False, "reason": None}
_degradation_lock = threading.Lock()


def get_llm_degradation_status() -> dict[str, Any]:
    """Return a copy of the LLM degradation flag (token budget / circuit breaker).

    Thread-safe; safe to call from the dashboard callback thread.
    """
    with _degradation_lock:
        return {
            "active": bool(_degradation_status["active"]),
            "reason": _degradation_status["reason"],
        }


def _set_llm_degradation(reason: str) -> None:
    """Mark LLM as degraded (empty response path)."""
    with _degradation_lock:
        _degradation_status["active"] = True
        _degradation_status["reason"] = reason


def _clear_llm_degradation() -> None:
    """Clear degradation after a successful API response."""
    with _degradation_lock:
        _degradation_status["active"] = False
        _degradation_status["reason"] = None


def _retry_after_seconds(exc: anthropic.RateLimitError) -> float:
    """Parse ``Retry-After`` (seconds); fall back to standard pause on missing/invalid."""
    try:
        hdr = exc.response.headers.get("retry-after") or exc.response.headers.get("Retry-After")
        if hdr is not None and str(hdr).strip() != "":
            return max(float(str(hdr).strip()), 1.0)
    except (TypeError, ValueError, AttributeError):
        pass
    return float(_CIRCUIT_BREAKER_PAUSE)


def _reset_token_counter_if_new_day() -> None:
    """Reset daily token counts at date change. Caller must hold ``_token_counter_lock``."""
    today = date.today().isoformat()
    if _token_counter["reset_date"] != today:
        _token_counter["input"] = 0
        _token_counter["output"] = 0
        _token_counter["reset_date"] = today


def _maybe_reset_token_counter() -> None:
    """Reset the daily token counter at midnight.

    Safe under nested ``_token_counter_lock`` (same thread) thanks to ``RLock``.
    """
    with _token_counter_lock:
        _reset_token_counter_if_new_day()


def _llm(
    client: anthropic.Anthropic,
    model: str,
    messages: list,
    system: str = "",
    max_tokens: int = 1024,
    web_search: bool = False,
) -> str:
    """Single LLM call or agentic web-search loop with budget cap and circuit breaker."""
    with _token_counter_lock:
        _reset_token_counter_if_new_day()
        total_tokens = _token_counter["input"] + _token_counter["output"]
        if total_tokens > _token_counter["max_daily"]:
            logger.critical(
                "Daily token budget exceeded (%d tokens) — skipping LLM call", total_tokens
            )
            _set_llm_degradation("token_budget")
            return ""

    # Circuit breaker check
    now = time.time()
    with _circuit_breaker_lock:
        if _circuit_breaker["consecutive_failures"] >= _CIRCUIT_BREAKER_THRESHOLD:
            if now < _circuit_breaker["paused_until"]:
                logger.warning(
                    "Circuit breaker OPEN — skipping LLM call (resumes in %.0fs)",
                    _circuit_breaker["paused_until"] - now,
                )
                _set_llm_degradation("circuit_breaker")
                return ""
            _circuit_breaker["consecutive_failures"] = 0
            logger.info("Circuit breaker CLOSED — resuming LLM calls")

    tools = [{"type": "web_search_20250305", "name": "web_search"}] if web_search else []
    msgs = list(messages)
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    resp = None
    try:
        for _ in range(8):
            resp = client.messages.create(**kwargs)
            # Track token usage
            if hasattr(resp, "usage"):
                with _token_counter_lock:
                    _reset_token_counter_if_new_day()
                    _token_counter["input"] += resp.usage.input_tokens
                    _token_counter["output"] += resp.usage.output_tokens
            if resp.stop_reason == "end_turn" or not tools:
                break
            if resp.stop_reason == "tool_use":
                msgs = msgs + [{"role": "assistant", "content": resp.content}]
                results = [
                    {"type": "tool_result", "tool_use_id": b.id, "content": ""}
                    for b in resp.content
                    if b.type == "tool_use"
                ]
                msgs = msgs + [{"role": "user", "content": results}]
                kwargs["messages"] = msgs
            else:
                break
        # Success — reset circuit breaker (degradation cleared after resp check)
        with _circuit_breaker_lock:
            _circuit_breaker["consecutive_failures"] = 0
    except KeyboardInterrupt:
        raise
    except anthropic.RateLimitError as e:
        wait_s = _retry_after_seconds(e)
        with _circuit_breaker_lock:
            _circuit_breaker["paused_until"] = time.time() + wait_s
            _circuit_breaker["consecutive_failures"] = _CIRCUIT_BREAKER_THRESHOLD
        logger.warning(
            "Rate-limited — circuit breaker forced open for %.0fs",
            wait_s,
        )
        try:
            from core.notifications import alert_circuit_breaker

            alert_circuit_breaker("Rate limited", int(max(wait_s, 1.0)))
        except Exception:
            pass
        _set_llm_degradation("circuit_breaker")
        return ""
    except (anthropic.APIStatusError, anthropic.APITimeoutError, httpx.TimeoutException) as e:
        with _circuit_breaker_lock:
            _circuit_breaker["consecutive_failures"] += 1
            n = _circuit_breaker["consecutive_failures"]
            if n >= _CIRCUIT_BREAKER_THRESHOLD:
                _circuit_breaker["paused_until"] = time.time() + _CIRCUIT_BREAKER_PAUSE
        if n >= _CIRCUIT_BREAKER_THRESHOLD:
            logger.error(
                "Circuit breaker OPEN after %d failures — pausing for %ds: %s",
                _CIRCUIT_BREAKER_THRESHOLD,
                _CIRCUIT_BREAKER_PAUSE,
                e,
            )
        else:
            logger.error(
                "API error — failure %d/%d: %s",
                n,
                _CIRCUIT_BREAKER_THRESHOLD,
                e,
            )
        _set_llm_degradation("circuit_breaker")
        return ""

    if resp is None:
        _set_llm_degradation("circuit_breaker")
        return ""
    _clear_llm_degradation()
    return next((b.text for b in resp.content if hasattr(b, "text") and b.text), "")
