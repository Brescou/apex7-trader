"""APEX-7 — Log message classification."""

from dashboard.server import BLUE, BORDER, GRAY, GREEN, ORANGE, PURPLE, RED, YELLOW


def _classify_v2(msg: str, level: str) -> tuple[str, str]:
    """Returns (badge_label, color) with proper sell coloring based on profit."""
    if level == "critical":
        return "DEATH", "#ff2020"
    if level == "error":
        return "ERR", ORANGE
    if level == "warning":
        return "WARN", YELLOW
    if msg.startswith("BUY "):
        return "BUY", BLUE
    if msg.startswith("SELL "):
        return ("SELL WIN", GREEN) if "+" in msg else ("SELL LOSS", RED)
    if msg.startswith("HOLD "):
        return "HOLD", GRAY
    if msg.startswith("Skip "):
        return "SKIP", YELLOW
    if "Anthropic" in msg or "web search" in msg:
        return "AI", PURPLE
    if msg.startswith("Analysis:"):
        return "INTEL", PURPLE
    if msg.startswith(("[SIM][TECH]", "[PAPER][TECH]")) or msg.startswith("technician:"):
        return "TECH", BLUE
    if msg.startswith(("[SIM][ANLST]", "[PAPER][ANLST]")) or msg.startswith("analyst:"):
        return "ANLST", "#06b6d4"
    if msg.startswith(("[SIM][RISK]", "[PAPER][RISK]")) or msg.startswith("risk_manager:"):
        return "RISK", RED
    if msg.startswith(("[SIM][MACRO]", "[PAPER][MACRO]")) or msg.startswith("macro_watcher:"):
        return "MACRO", YELLOW
    if msg.startswith("supervisor:"):
        return "SUPV", PURPLE
    if msg.startswith("arbitrate:"):
        return "ARBIT", GREEN
    if msg.startswith("[PAPER]"):
        return "PAPER", BLUE
    if msg.startswith("[SIM]"):
        return "SIM", ORANGE
    if msg.startswith("=== CYCLE"):
        return "CYC", BORDER
    if msg.startswith(("Fetching", "Prices")):
        return "MKT", BORDER
    return "LOG", BORDER
