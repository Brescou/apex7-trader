"""Tests for the optional dashboard auth gate (DASHBOARD_PASSWORD)."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSWORD = "s3cret-test"


@pytest.fixture
def client(monkeypatch):
    """Flask test client with auth enabled (password monkeypatched).

    ``create_app()`` calls ``start_controller()`` — a real Portfolio + a live
    agent thread pointed at the real project ``trades_sim.db``. Mocked so
    this only exercises the auth gate, not a background trading loop.
    """
    import config

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", PASSWORD)
    from dashboard import create_app

    with patch("dashboard.controller.start_controller"):
        app = create_app()
    with app.server.test_client() as c:
        yield c


@pytest.fixture
def open_client(monkeypatch):
    """Flask test client with auth disabled (no password configured)."""
    import config

    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "")
    from dashboard import create_app

    with patch("dashboard.controller.start_controller"):
        app = create_app()
    with app.server.test_client() as c:
        yield c


def test_auth_disabled_serves_dashboard(open_client):
    resp = open_client.get("/")
    assert resp.status_code == 200


def test_auth_disabled_login_redirects_home(open_client):
    resp = open_client.get("/login")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_unauthenticated_get_redirects_to_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_health_stays_open_without_auth(client):
    resp = client.get("/health")
    # 200 (alive) or 503 (no portfolio yet) — but never a login redirect.
    assert resp.status_code in (200, 503)
    assert resp.get_json() is not None


def test_unauthenticated_dash_xhr_gets_401(client):
    resp = client.post("/_dash-update-component", json={})
    assert resp.status_code == 401


def test_wrong_password_rejected(client):
    resp = client.post("/login", data={"password": "wrong"})
    assert resp.status_code == 401
    assert b"Invalid password" in resp.data
    # still locked out
    assert client.get("/").status_code == 302


def test_non_ascii_password_does_not_crash_login(monkeypatch):
    """hmac.compare_digest on two `str` raises TypeError for non-ASCII
    content — DASHBOARD_PASSWORD containing e.g. accented characters must
    not turn every /login POST into an unhandled 500 (Review Finding).
    """
    import config

    non_ascii_password = "Sécurité2026!"
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", non_ascii_password)
    from dashboard import create_app

    with patch("dashboard.controller.start_controller"):
        app = create_app()
    with app.server.test_client() as c:
        wrong = c.post("/login", data={"password": "wrong"})
        assert wrong.status_code == 401

        correct = c.post("/login", data={"password": non_ascii_password})
        assert correct.status_code == 302
        assert c.get("/").status_code == 200


def test_login_logout_flow(client):
    resp = client.post("/login", data={"password": PASSWORD})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200

    resp = client.get("/logout")
    assert resp.status_code == 302
    assert client.get("/").status_code == 302  # locked out again
