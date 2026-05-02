"""Unit tests for ``core.external_data`` (HTTP mocked)."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _clear_external_caches() -> None:
    import core.external_data as ed

    ed._macro_indicators_cache["data"] = None
    ed._macro_indicators_cache["ts"] = 0.0
    ed._fred_series_cache.clear()
    ed._fear_greed_cache["data"] = None
    ed._fear_greed_cache["ts"] = 0.0


def _mock_httpx_client(response_json: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = response_json
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_fetch_fred_latest_parses_observation() -> None:
    _clear_external_caches()
    from core.external_data import fetch_fred_latest

    mock_client = _mock_httpx_client({"observations": [{"date": "2026-01-15", "value": "4.25"}]})
    with patch("core.external_data.httpx.Client", return_value=mock_client):
        out = fetch_fred_latest("DGS10", api_key="test_key")
    assert out == {"value": 4.25, "date": "2026-01-15"}
    url = mock_client.get.call_args[0][0]
    assert "api_key=test_key" in url


def test_fetch_fred_latest_dot_value_returns_none() -> None:
    _clear_external_caches()
    from core.external_data import fetch_fred_latest

    mock_client = _mock_httpx_client({"observations": [{"date": "2026-01-15", "value": "."}]})
    with patch("core.external_data.httpx.Client", return_value=mock_client):
        assert fetch_fred_latest("X") is None


def test_fetch_fear_greed_parses() -> None:
    _clear_external_caches()
    from core.external_data import fetch_fear_greed

    mock_client = _mock_httpx_client({"fear_and_greed": {"score": 42.7, "rating": "Fear"}})
    with patch("core.external_data.httpx.Client", return_value=mock_client):
        out = fetch_fear_greed()
    assert out == {"score": 43, "label": "Fear"}


def test_fetch_macro_indicators_uses_bundle_cache() -> None:
    _clear_external_caches()
    from core import external_data as ed

    calls = {"n": 0}

    def fake_latest(sid: str, api_key: str = "") -> dict | None:
        calls["n"] += 1
        return {"value": float(calls["n"]), "date": "2026-01-01"}

    with patch.object(ed, "fetch_fred_latest", side_effect=fake_latest):
        a = ed.fetch_macro_indicators()
        b = ed.fetch_macro_indicators()
    assert a == b
    # One build: 5 series + bundle cache on second call skips rebuild... actually
    # first call invokes fetch_fred_latest 5 times, second uses bundle so 5 total
    assert calls["n"] == 5
