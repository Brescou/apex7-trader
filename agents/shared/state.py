"""agents.shared.state — TypedDict definitions for the multi-agent graph.

``AgentState`` defines the core fields shared by all nodes; ``MultiAgentState``
extends it with multi-agent-specific fields (votes, supervisor brief, arbitration).
"""

import operator
from typing import Annotated, List, Optional, TypedDict


class AgentState(TypedDict):
    # Portfolio
    balance: float
    positions: dict  # {symbol: {shares, avg_price}}
    portfolio_history: Annotated[List[float], operator.add]

    # Market data
    prices: dict  # {symbol: float}
    news: str
    sentiment: dict  # {symbol: float -1..1}
    macro_indicators: dict  # FRED bundle from ``core.external_data``
    fear_greed: dict | None  # CNN Fear & Greed or None on failure
    earnings_calendar: dict  # per-symbol next earnings from ``market_data``

    # Memory
    past_trades: List[dict]
    known_patterns: List[str]

    # Agent
    round: int
    confidence: float
    research_iterations: int
    decision: Optional[dict]
    emotion: str
    thoughts: str

    # Logs
    log: Annotated[List[dict], operator.add]

    # Control
    alive: bool
    skip_research: bool


class MultiAgentState(TypedDict):
    # ── Core portfolio (mirrors AgentState) ──────────────────────────────────
    balance: float
    positions: dict
    portfolio_history: Annotated[List[float], operator.add]
    prices: dict
    news: str
    sentiment: dict
    macro_indicators: dict
    fear_greed: dict | None
    earnings_calendar: dict
    past_trades: List[dict]
    known_patterns: List[str]
    round: int
    confidence: float
    research_iterations: int
    decision: Optional[dict]
    emotion: str
    thoughts: str
    log: Annotated[List[dict], operator.add]
    alive: bool
    skip_research: bool
    # ── Multi-agent specific ──────────────────────────────────────────────────
    supervisor_brief: str
    agent_role: str
    agent_votes: Annotated[List[dict], operator.add]
    tech_vote: Optional[dict]
    analyst_vote: Optional[dict]
    risk_vote: Optional[dict]
    macro_vote: Optional[dict]
    arbitration: Optional[dict]
