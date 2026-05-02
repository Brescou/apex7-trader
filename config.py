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
try:
    MAX_PYRAMID_LAYERS = max(1, int(os.getenv("MAX_PYRAMID_LAYERS", "3")))
except ValueError:
    MAX_PYRAMID_LAYERS = 3
AGENT_INTERVAL = 30

SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").lower() == "true"
SIM_VOLATILITY = float(os.getenv("SIM_VOLATILITY", "0.02"))  # 2% par défaut
SIM_DRIFT = float(os.getenv("SIM_DRIFT", "0.0001"))  # léger biais haussier

STOP_LOSS_PCT = 0.05

POSTMORTEM_HOUR = 22

# Number of trading days the market needs to move before evaluating an agent
# vote. Approximated as ``EVAL_HORIZON_CALENDAR_DAYS`` calendar days when
# scheduling ``pending_evaluations.eval_after_date``.
EVAL_HORIZON_DAYS = 5
EVAL_HORIZON_CALENDAR_DAYS = 7

MACRO_SYMBOLS = {"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}
MARKET_DATA_CACHE_SEC = 60
WATCHLIST_CACHE_SEC = 10
NEWS_MAX_ITEMS = 8

USE_LIVEFEED = os.getenv("USE_LIVEFEED", "true").lower() == "true"
PORTFOLIO_STATE_PATH = os.getenv("PORTFOLIO_STATE_PATH", "portfolio_state.json")
PORTFOLIO_SAVE_ENABLED = os.getenv("PORTFOLIO_SAVE_ENABLED", "true").lower() == "true"

# Discord webhook (optional — ``core.notifications``)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
