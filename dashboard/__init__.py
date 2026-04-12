"""APEX-7 — Dashboard package. Exposes create_app() factory."""

from dashboard.server import app, server

_app_initialized = False


def create_app():
    """Build Dash layout, register callbacks, and start the agent controller once."""
    global _app_initialized
    if not _app_initialized:
        from dashboard.controller import start_controller

        start_controller()
        import dashboard.layout  # noqa: F401 — assigns app.layout
        import dashboard.callbacks  # noqa: F401 — registers all callbacks

        _app_initialized = True
    return app


__all__ = ["app", "server", "create_app"]
