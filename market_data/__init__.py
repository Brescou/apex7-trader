"""Données marché pour le terminal — aucun import depuis ``agents`` ou ``dashboard``.

API publique réexportée ici ; implémentation découpée sous-modules.
"""

from market_data.caches import EARNINGS_TTL, _earnings_cache
from market_data.charts import fetch_comparison, fetch_ohlcv, fetch_sparkline
from market_data.compat import yf
from market_data.correlation import fetch_correlation_matrix
from market_data.earnings import fetch_earnings_calendar, is_earnings_week
from market_data.economic_calendar import build_economic_calendar_rows
from market_data.finnhub import fetch_finnhub_quote, fetch_finnhub_quotes
from market_data.fundamentals import fetch_fundamentals, format_market_cap
from market_data.macro import fetch_macro
from market_data.news import fetch_news
from market_data.quotes import fetch_watchlist_prices
from market_data.screener import run_screener
from market_data.sectors import fetch_sector_performance

__all__ = [
    "build_economic_calendar_rows",
    "EARNINGS_TTL",
    "_earnings_cache",
    "fetch_comparison",
    "fetch_correlation_matrix",
    "fetch_earnings_calendar",
    "fetch_finnhub_quote",
    "fetch_finnhub_quotes",
    "fetch_fundamentals",
    "fetch_macro",
    "format_market_cap",
    "fetch_news",
    "fetch_ohlcv",
    "fetch_sector_performance",
    "fetch_sparkline",
    "fetch_watchlist_prices",
    "is_earnings_week",
    "run_screener",
    "yf",
]
