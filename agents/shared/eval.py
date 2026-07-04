"""Deferred ``was_correct`` resolution via ``pending_evaluations``."""

import logging
import math
from datetime import datetime

import yfinance as yf

from agents.shared.db import _db_read, _db_read_at, _db_write_at
from agents.shared.modes import get_runtime_mode, get_simulation_mode

logger = logging.getLogger("apex7")

EVAL_SIGNIFICANCE_PCT = 0.01  # 1% move required to declare a vote correct/wrong
_MAX_EVAL_RETRIES = 10  # abandon evaluation after this many consecutive price-fetch failures


def _get_db_path():
    """Delegate to ``agents.shared.db`` so tests can patch ``db._get_db_path`` reliably.

    A plain ``from agents.shared.db import _get_db_path`` binds this module's
    own copy of the function object at import time — ``monkeypatch.setattr``
    on ``agents.shared.db._get_db_path`` (e.g. the ``tmp_db`` fixture)
    wouldn't be visible here, and this function's writes would silently
    target the real project DB instead of the test's temp file.
    """
    from agents.shared import db as _db

    return _db._get_db_path()


def _fast_last_price(symbol: str) -> float | None:
    """Best-effort spot price via yfinance ``fast_info``; returns ``None`` on failure."""
    try:
        info = yf.Ticker(symbol).fast_info
    except Exception as exc:
        logger.warning("fast_info fetch failed for %s: %s", symbol, exc)
        return None
    raw = None
    try:
        raw = info.get("lastPrice")  # dict-like view (yfinance >=0.2.38)
    except Exception:
        raw = getattr(info, "last_price", None)
    if raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(price) or price <= 0:
        return None
    return price


def evaluate_pending_trades(now: datetime | None = None) -> int:
    """Resolve due ``pending_evaluations`` against the current market price.

    For each row whose ``eval_after_date`` is in the past:
      * fetch the current price via yfinance ``fast_info``;
      * compare to ``entry_price`` (BUY → price up, SELL → price down);
      * mark ``agent_memory.was_correct`` (1/0/NULL inconclusive) for every
        vote sharing the same ``trace_id``;
      * flip ``pending_evaluations.evaluated`` to ``1``.

    Skips rows when the spot price cannot be fetched — they will be retried
    on the next call.

    Returns the number of evaluations that actually completed.
    """
    when_dt = now or datetime.now()
    when = when_dt.isoformat()
    # Resolved once and reused for every read/write below (via _db_write_at /
    # _db_read_at) instead of the mode-dependent _db_write / _db_read, which
    # re-resolve _get_db_path() on every call. Without this, a mode switch
    # mid-loop (e.g. the UI toggling LIVE -> PAPER while this function is
    # still iterating due rows) could route later rows' UPDATEs to a
    # different DB file than the SELECT that produced them, silently
    # orphaning pending_evaluations/agent_memory rows in the wrong file.
    db_path = _get_db_path()
    rows = _db_read(
        "SELECT id, trade_id, trace_id, symbol, action, entry_price, "
        "entry_date, eval_after_date FROM pending_evaluations "
        "WHERE evaluated = 0 AND eval_after_date <= ? "
        "ORDER BY eval_after_date ASC",
        (when,),
    )
    if not rows:
        return 0

    completed = 0
    for row in rows:
        pe_id, _trade_id, trace_id, symbol, action, entry_price, entry_date, _eval_after = row
        action_u = (action or "HOLD").upper()
        if action_u not in ("BUY", "SELL"):
            _db_write_at(
                db_path,
                "UPDATE pending_evaluations SET evaluated = 1 WHERE id = ?",
                (pe_id,),
            )
            continue

        current_price = _fast_last_price(symbol)
        if current_price is None:
            _db_write_at(
                db_path,
                "UPDATE pending_evaluations "
                "SET retry_count = COALESCE(retry_count, 0) + 1 WHERE id = ?",
                (pe_id,),
            )
            count_row = _db_read_at(
                db_path, "SELECT retry_count FROM pending_evaluations WHERE id = ?", (pe_id,)
            )
            retry_count = int(count_row[0][0]) if count_row else 0
            if retry_count >= _MAX_EVAL_RETRIES:
                logger.warning(
                    "evaluate_pending_trades: abandoning %s %s after %d retries (no spot price)",
                    symbol,
                    action_u,
                    retry_count,
                )
                _db_write_at(
                    db_path, "UPDATE pending_evaluations SET evaluated = 1 WHERE id = ?", (pe_id,)
                )
            else:
                logger.info(
                    "evaluate_pending_trades: skip %s %s (no spot price, retry %d/%d)",
                    symbol,
                    action_u,
                    retry_count,
                    _MAX_EVAL_RETRIES,
                )
            continue

        try:
            entry = float(entry_price)
        except (TypeError, ValueError):
            entry = 0.0
        if entry <= 0:
            _db_write_at(
                db_path,
                "UPDATE pending_evaluations SET evaluated = 1 WHERE id = ?",
                (pe_id,),
            )
            continue

        pct_change = (current_price - entry) / entry
        if action_u == "BUY":
            if pct_change > EVAL_SIGNIFICANCE_PCT:
                was_correct: int | None = 1
            elif pct_change < -EVAL_SIGNIFICANCE_PCT:
                was_correct = 0
            else:
                was_correct = None
        else:  # SELL
            if pct_change < -EVAL_SIGNIFICANCE_PCT:
                was_correct = 1
            elif pct_change > EVAL_SIGNIFICANCE_PCT:
                was_correct = 0
            else:
                was_correct = None

        if trace_id:
            # Only score votes that actually agreed with the executed trade's
            # direction AND symbol — a dissenting agent (opposite action, or a
            # BUY/SELL on a different symbol the arbitrator didn't act on)
            # must stay NULL, not inherit the winning direction's verdict.
            # risk_manager and macro_watcher always vote HOLD — leaving their
            # rows NULL keeps ``_compute_dynamic_weights`` from blending in
            # noise (Review v5 Finding 4.4).
            # eval_pct_change stores |move| so dynamic-weight computation can
            # give larger moves more signal (magnitude-weighted accuracy).
            wrote_verdict = _db_write_at(
                db_path,
                "UPDATE agent_memory SET was_correct = ?, eval_pct_change = ? "
                "WHERE trace_id = ? AND was_correct IS NULL "
                "AND vote = ? AND symbol = ?",
                (was_correct, abs(pct_change), trace_id, action_u, symbol),
            )
            if not wrote_verdict:
                # Don't mark ``evaluated`` — the verdict never landed in
                # agent_memory, so retrying next tick is the only way it
                # isn't silently lost forever.
                logger.error(
                    "evaluate_pending_trades: failed to persist was_correct "
                    "for trace_id=%s symbol=%s — will retry",
                    trace_id,
                    symbol,
                )
                continue
        _db_write_at(
            db_path,
            "UPDATE pending_evaluations SET evaluated = 1 WHERE id = ?",
            (pe_id,),
        )

        try:
            ed_norm = str(entry_date).replace("Z", "+00:00")
            ed_parsed = datetime.fromisoformat(ed_norm)
            if ed_parsed.tzinfo:
                ed_parsed = ed_parsed.replace(tzinfo=None)
            days_held = max(0, (when_dt.date() - ed_parsed.date()).days)
        except (ValueError, TypeError):
            days_held = 0

        logger.info(
            "Evaluated %s %s @ %.4f → %.4f (%+.1f%%) → was_correct=%s",
            symbol,
            action_u,
            entry,
            current_price,
            pct_change * 100,
            "None" if was_correct is None else str(was_correct),
        )
        if not get_simulation_mode():
            try:
                from core.notifications import alert_evaluation

                if was_correct == 1:
                    ac_bool: bool | None = True
                elif was_correct == 0:
                    ac_bool = False
                else:
                    ac_bool = None
                alert_evaluation(
                    symbol=str(symbol),
                    action=action_u,
                    entry_price=entry,
                    current_price=float(current_price),
                    pct_change=pct_change,
                    was_correct=ac_bool,
                    days_held=days_held,
                    mode=(get_runtime_mode() or "live").upper(),
                )
            except Exception:
                pass
        completed += 1

    return completed
