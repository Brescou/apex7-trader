"""Tests for ``_llm`` circuit breaker and rate-limit handling (Finding 5.3)."""

import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import httpx
import pytest

import agents.shared.nodes as nodes
from agents.shared.nodes import _llm


def _api_status_error(status: int = 500) -> anthropic.APIStatusError:
    """Build a minimal APIStatusError for tests."""
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req)
    return anthropic.APIStatusError("server error", response=resp, body=None)


def _rate_limit_error(retry_after: str = "30") -> anthropic.RateLimitError:
    """Build a RateLimitError with ``Retry-After`` header."""
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(
        429,
        request=req,
        headers={"Retry-After": retry_after},
    )
    return anthropic.RateLimitError("rate limited", response=resp, body=None)


def _success_response(text: str = "ok") -> SimpleNamespace:
    """Minimal Anthropic-like message response for the non-tool path."""
    block = SimpleNamespace(text=text, type="text")
    return SimpleNamespace(
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        content=[block],
    )


@pytest.fixture(autouse=True)
def reset_llm_guard_state():
    """Isolate circuit breaker / token counter between tests."""
    nodes._circuit_breaker["consecutive_failures"] = 0
    nodes._circuit_breaker["paused_until"] = 0.0
    nodes._token_counter["input"] = 0
    nodes._token_counter["output"] = 0
    nodes._token_counter["reset_date"] = ""
    nodes._clear_llm_degradation()
    yield
    nodes._circuit_breaker["consecutive_failures"] = 0
    nodes._circuit_breaker["paused_until"] = 0.0
    nodes._clear_llm_degradation()


def test_breaker_opens_after_3_failures():
    """Three APIStatusError responses open the breaker and set ``paused_until`` in the future."""
    client = MagicMock()
    client.messages.create.side_effect = _api_status_error()

    for _ in range(3):
        assert _llm(client, "claude", [{"role": "user", "content": "x"}]) == ""

    assert nodes._circuit_breaker["consecutive_failures"] == 3
    assert nodes._circuit_breaker["paused_until"] > time.time()
    assert client.messages.create.call_count == 3


def test_breaker_returns_empty_when_open():
    """When the breaker is open, ``_llm`` returns "" without calling the API."""
    nodes._circuit_breaker["consecutive_failures"] = 3
    nodes._circuit_breaker["paused_until"] = nodes.time.time() + 3600.0

    client = MagicMock()
    out = _llm(client, "claude", [{"role": "user", "content": "x"}])

    assert out == ""
    client.messages.create.assert_not_called()


def test_breaker_closes_after_pause():
    """After ``paused_until``, the next call resets failures and a successful response clears state."""
    nodes._circuit_breaker["consecutive_failures"] = 3
    nodes._circuit_breaker["paused_until"] = 1000.0

    client = MagicMock()
    client.messages.create.return_value = _success_response("recovered")

    fixed_now = 5000.0
    with patch("agents.shared.nodes.time.time", return_value=fixed_now):
        out = _llm(client, "claude", [{"role": "user", "content": "x"}])

    assert out == "recovered"
    assert nodes._circuit_breaker["consecutive_failures"] == 0
    assert client.messages.create.call_count == 1


def test_rate_limit_respects_retry_after():
    """RateLimitError uses ``Retry-After`` seconds for ``paused_until``."""
    client = MagicMock()
    client.messages.create.side_effect = _rate_limit_error("30")

    fixed_now = 10_000.0
    with patch("agents.shared.nodes.time.time", return_value=fixed_now):
        assert _llm(client, "claude", [{"role": "user", "content": "x"}]) == ""

    assert nodes._circuit_breaker["paused_until"] == pytest.approx(fixed_now + 30.0)


def test_first_429_blocks_subsequent_calls():
    """First 429 forces full threshold; next call is blocked until pause elapses."""
    client = MagicMock()
    client.messages.create.side_effect = _rate_limit_error("30")
    t0 = 10_000.0
    with patch("agents.shared.nodes.time.time", return_value=t0):
        assert _llm(client, "claude", [{"role": "user", "content": "x"}]) == ""

    assert nodes._circuit_breaker["consecutive_failures"] == nodes._CIRCUIT_BREAKER_THRESHOLD

    with patch("agents.shared.nodes.time.time", return_value=t0 + 5.0):
        assert _llm(client, "claude", [{"role": "user", "content": "x"}]) == ""

    assert client.messages.create.call_count == 1

    client.messages.create.side_effect = None
    client.messages.create.return_value = _success_response("ok")
    with patch("agents.shared.nodes.time.time", return_value=t0 + 31.0):
        assert _llm(client, "claude", [{"role": "user", "content": "x"}]) == "ok"

    assert client.messages.create.call_count == 2


def test_keyboard_interrupt_not_caught():
    """``KeyboardInterrupt`` must propagate (not swallowed by generic handlers)."""
    client = MagicMock()
    client.messages.create.side_effect = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        _llm(client, "claude", [{"role": "user", "content": "x"}])
