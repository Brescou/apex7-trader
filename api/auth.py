"""APEX-7 — Optional shared-secret auth for the FastAPI stack.

Mirrors ``dashboard/server.py``'s gate: unset ``DASHBOARD_PASSWORD`` means no
auth (default localhost usage, matching the legacy Dash behavior). When set,
REST routes require a matching ``Authorization: Bearer <password>`` header.

The WebSocket handshake is a separate case — native browser WebSockets can't
set custom headers, so the shared secret travels as a ``?token=`` query
param instead. The Origin allow-list check on ``/ws`` is enforced
unconditionally (even with no password set): unlike ``fetch()``, a
WebSocket handshake isn't blocked by browser CORS, so any page could
otherwise open a connection and read the live portfolio stream
(Cross-Site WebSocket Hijacking).
"""

import hmac

from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# Same origins CORSMiddleware allows in api/main.py — the Vite dev server.
ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def _auth_enabled() -> bool:
    """Read the password at request time so env/test overrides take effect."""
    import config

    return bool(config.DASHBOARD_PASSWORD)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """FastAPI dependency: gate a REST route behind ``DASHBOARD_PASSWORD``."""
    import config

    if not _auth_enabled():
        return
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(supplied, config.DASHBOARD_PASSWORD):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")


def ws_auth_ok(ws: WebSocket) -> bool:
    """Validate a WebSocket handshake before accepting the connection."""
    import config

    origin = ws.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        return False
    if not _auth_enabled():
        return True
    token = ws.query_params.get("token", "")
    return hmac.compare_digest(token, config.DASHBOARD_PASSWORD)
