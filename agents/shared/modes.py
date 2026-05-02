"""Runtime mode toggles (live / paper / sim) and ``.env`` persistence."""

import logging
from pathlib import Path

from config import SIMULATION_MODE

logger = logging.getLogger("apex7")

# Three mutually-exclusive operating modes:
#   * LIVE  : real prices + LLM decisions + ``trades.db``
#   * PAPER : real prices + rule-based decisions (no LLM) + ``trades_paper.db``
#   * SIM   : random-walk prices + rule-based decisions + ``trades_sim.db``
_sim_mode: dict = {"enabled": SIMULATION_MODE}
_paper_mode: dict = {"enabled": False}


def _no_llm_mode() -> bool:
    """Decisions are rule-based — no Anthropic call (sim or paper)."""
    return _sim_mode["enabled"] or _paper_mode["enabled"]


def _write_env_var(key: str, value: str) -> None:
    """Persist mode flags to project ``.env`` (best-effort)."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    try:
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n")
    except Exception as e:
        logger.warning("Failed to write %s to .env: %s", key, e)


def set_simulation_mode(enabled: bool) -> None:
    """Enable simulation mode. Disables paper mode (mutually exclusive)."""
    _sim_mode["enabled"] = enabled
    if enabled:
        _paper_mode["enabled"] = False
        _write_env_var("PAPER_MODE", "false")
    _write_env_var("SIMULATION_MODE", "true" if enabled else "false")


def get_simulation_mode() -> bool:
    return _sim_mode["enabled"]


def set_paper_mode(enabled: bool) -> None:
    """Enable paper trading. Disables simulation mode (mutually exclusive)."""
    _paper_mode["enabled"] = enabled
    if enabled:
        _sim_mode["enabled"] = False
        _write_env_var("SIMULATION_MODE", "false")
    _write_env_var("PAPER_MODE", "true" if enabled else "false")


def get_paper_mode() -> bool:
    return _paper_mode["enabled"]


def get_runtime_mode() -> str:
    """Return the active mode label: ``'paper'``, ``'sim'``, or ``'live'``."""
    if _paper_mode["enabled"]:
        return "paper"
    if _sim_mode["enabled"]:
        return "sim"
    return "live"
