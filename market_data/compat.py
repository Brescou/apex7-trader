"""Import yfinance unique pour tout le package — les tests patchent ``market_data.yf``."""

import yfinance as yf

__all__ = ["yf"]
