"""APEX-7 — dashboard package.

Holds the agent-loop/Portfolio-state machinery (``dashboard.controller``)
shared between the FastAPI backend (``api/``) and the postmortem thread.
The Dash-based UI (layout/callbacks/server) was removed in favor of the
FastAPI + React stack (``api/`` + ``frontend/``).
"""
