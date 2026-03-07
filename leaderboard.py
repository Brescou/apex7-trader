"""Leaderboard — runs BacktestEngine for 4 agent configurations and ranks them."""

from backtest import BacktestEngine
from config import INITIAL_BALANCE, MAX_ALLOC_PCT


_AGENTS: list[dict] = [
    {"agent_id": "CONSERVATIVE", "max_alloc_pct": 15},
    {"agent_id": "BALANCED",     "max_alloc_pct": 25},
    {"agent_id": "AGGRESSIVE",   "max_alloc_pct": 40},
    {"agent_id": "APEX-7",       "max_alloc_pct": MAX_ALLOC_PCT},
]


class Leaderboard:
    def run_all(self, scenario: str) -> list[dict]:
        results = []
        for agent in _AGENTS:
            config = {"max_alloc_pct": agent["max_alloc_pct"]}
            r = BacktestEngine(scenario, config).run(80)
            final_value = INITIAL_BALANCE * (1 + r["return_pct"] / 100)
            results.append({
                "agent_id":    agent["agent_id"],
                "final_value": final_value,
                "return_pct":  r["return_pct"],
                "sharpe":      r["sharpe"],
                "win_rate":    r["win_rate"],
                "max_drawdown": r["max_drawdown"],
                "trades":      r["trades_count"],
                "survived":    r["survived"],
            })
        results.sort(key=lambda x: x["return_pct"], reverse=True)
        return results
