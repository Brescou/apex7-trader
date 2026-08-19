from dotenv import load_dotenv
import os

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
# FRED (Federal Reserve Economic Data) — optional; improves reliability/limits.
FRED_API_KEY = os.getenv("FRED_API_KEY", "").strip()

# Finnhub — fallback quotes when the yfinance breaker is open, and company
# news when yfinance Ticker.news is empty. Unauthenticated calls 401.
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

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
MAX_PYRAMID_LAYERS = int(os.getenv("MAX_PYRAMID_LAYERS", "3"))
# LIVE/PAPER agent cadence. SIM stays at 3s in runtime.controller.
# 15 min keeps ~26 cycles in a 6.5h NYSE/TSX cash session (fits the 500k
# daily token budget better than 90s).
AGENT_INTERVAL = 900

SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").lower() == "true"
PAPER_MODE = os.getenv("PAPER_MODE", "false").lower() == "true"
SIM_VOLATILITY = float(os.getenv("SIM_VOLATILITY", "0.02"))  # 2% par défaut
SIM_DRIFT = float(os.getenv("SIM_DRIFT", "0.0001"))  # léger biais haussier

STOP_LOSS_PCT = 0.05

# Transaction costs — applied in Portfolio.buy/sell and backtest._simulate.
# COMMISSION_PCT: broker fee as fraction of trade notional (IB ~0.1% for stocks).
# SLIPPAGE_PCT: market impact / spread estimate (0.05% is conservative for large-caps).
COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "0.001"))
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", "0.0005"))

# ── Trade lifecycle guards (execute_node) ─────────────────────────────────────
TAKE_PROFIT_PCT = 0.10  # partial take-profit trigger: price ≥ avg_price × (1 + 10%)
TAKE_PROFIT_SELL_PCT = 50.0  # fraction of the position sold at take-profit
TIME_STOP_DAYS = 10  # exit positions held longer than N calendar days…
TIME_STOP_BAND_PCT = 0.02  # …when PnL is still within ±2% (stagnant)
MAX_DRAWDOWN_BLOCK_PCT = 0.20  # block new BUYs when drawdown from peak exceeds 20%
EARNINGS_BLOCK_DAYS = 2  # hard-block BUY when earnings are within N days

POSTMORTEM_HOUR = 22

# Number of trading days the market needs to move before evaluating an agent
# vote. Approximated as ``EVAL_HORIZON_CALENDAR_DAYS`` calendar days when
# scheduling ``pending_evaluations.eval_after_date``.
EVAL_HORIZON_DAYS = 5
EVAL_HORIZON_CALENDAR_DAYS = 7

MACRO_SYMBOLS = {"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}
MARKET_DATA_CACHE_SEC = 60
WATCHLIST_CACHE_SEC = 10
NEWS_MAX_ITEMS = 8  # page size (terminal NEWS "show more")
NEWS_MAX_TOTAL = 40  # hard cap per symbol (5 pages)

USE_LIVEFEED = os.getenv("USE_LIVEFEED", "true").lower() == "true"
PORTFOLIO_STATE_PATH = os.getenv("PORTFOLIO_STATE_PATH", "portfolio_state.json")
PORTFOLIO_SAVE_ENABLED = os.getenv("PORTFOLIO_SAVE_ENABLED", "true").lower() == "true"

# Discord webhook (optional — ``core.notifications``)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

# API auth (optional) — set DASHBOARD_PASSWORD to require a matching Bearer
# token on REST routes and a ?token= query param on the /ws handshake
# (``/health`` stays open for monitoring). See api/auth.py.
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
