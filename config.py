from dotenv import load_dotenv
import os

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

WATCHLIST = [
    "AAPL",
    "MSFT",
    "GOOG",
    "AMZN",
    "TSLA",
]

INITIAL_BALANCE = 1000
DEATH_THRESHOLD = 50.0
MAX_POSITIONS = 3
MAX_ALLOC_PCT = 40
AGENT_INTERVAL = 30

SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").lower() == "true"
SIM_VOLATILITY  = float(os.getenv("SIM_VOLATILITY", "0.02"))   # 2% par défaut
SIM_DRIFT       = float(os.getenv("SIM_DRIFT", "0.0001"))       # léger biais haussier

AGENT_GRAPH = os.getenv("AGENT_GRAPH", "simple")
# "simple" → agent.py      (1 agent Claude Sonnet)
# "multi"  → agent_multi.py (4 agents spécialisés + arbitration)

