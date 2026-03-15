"""APEX-7 — Dashboard package. Exposes create_app() factory."""

from dashboard.server import app, server
from dashboard import layout  # noqa: F401 — assigns app.layout
from dashboard import callbacks  # noqa: F401 — registers all callbacks


def create_app():
    return app


__all__ = ["app", "server", "create_app"]
