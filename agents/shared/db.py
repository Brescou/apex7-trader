"""SQLite persistence — schema, paths, centralized reads/writes."""

import logging
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.modes import _paper_mode, _sim_mode

logger = logging.getLogger("apex7")

_DB_ROOT = Path(__file__).parent.parent.parent
DB_PATH = _DB_ROOT / "trades.db"  # kept for backward compat


def _get_db_path() -> Path:
    """Return the DB path based on the current mode (paper > sim > live)."""
    if _paper_mode["enabled"]:
        return _DB_ROOT / "trades_paper.db"
    if _sim_mode["enabled"]:
        return _DB_ROOT / "trades_sim.db"
    return _DB_ROOT / "trades.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp             TEXT,
    symbol                TEXT,
    action                TEXT,
    price                 REAL,
    amount_usd            REAL,
    shares                REAL,
    reasoning             TEXT,
    confidence            REAL,
    emotion               TEXT,
    portfolio_value_after REAL,
    lesson                TEXT,
    trace_id              TEXT,
    source                TEXT DEFAULT 'live',
    prompt_version        TEXT,
    sell_pct              REAL
);
CREATE TABLE IF NOT EXISTS patterns (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    pattern   TEXT
);
CREATE TABLE IF NOT EXISTS agent_memory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT,
    agent_name   TEXT,
    symbol       TEXT,
    vote         TEXT,
    confidence   REAL,
    was_correct  INTEGER,
    lesson       TEXT,
    source       TEXT DEFAULT 'simulation',
    trace_id     TEXT
);
-- The matching index ``idx_agent_memory_trace`` is created in the
-- ``_init_db`` soft-migration block so it tolerates older DBs that
-- still need the ALTER TABLE first.
CREATE TABLE IF NOT EXISTS postmortem (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT,
    symbol          TEXT,
    buy_price       REAL,
    sell_price      REAL,
    pnl_pct         REAL,
    holding_hours   REAL,
    agents_correct  TEXT,
    summary         TEXT,
    source          TEXT DEFAULT 'simulation'
);
CREATE TABLE IF NOT EXISTS pending_evaluations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        INTEGER NOT NULL,
    trace_id        TEXT,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    entry_date      TEXT NOT NULL,
    eval_after_date TEXT NOT NULL,
    evaluated       INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    source   TEXT DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS cycle_states (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    cycle_num   INTEGER,
    source      TEXT DEFAULT 'live',
    state_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_eval_due
    ON pending_evaluations (evaluated, eval_after_date);
"""


_db_init_lock = threading.Lock()
# Keyed by resolved DB path so a thread initializing one path (e.g. the project
# DBs) never marks a different path (e.g. a test tmp DB) as initialized.
_db_initialized_paths: set[str] = set()


def _seed_watchlist_if_empty(con: sqlite3.Connection) -> None:
    """Insert default tickers once per DB file when the watchlist table is empty."""
    try:
        row = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()
        if row and row[0] > 0:
            return
    except sqlite3.OperationalError:
        return
    from config import WATCHLIST as _default_symbols

    ts = datetime.now(timezone.utc).isoformat()
    for sym in _default_symbols:
        con.execute(
            "INSERT INTO watchlist (symbol, added_at, source) VALUES (?,?,?)",
            (sym, ts, "seed"),
        )


def _init_db() -> None:
    """Create tables and set WAL mode for project DBs, or a single test path."""
    primary = Path(_get_db_path())
    project_live = _DB_ROOT / "trades.db"
    project_sim = _DB_ROOT / "trades_sim.db"
    project_paper = _DB_ROOT / "trades_paper.db"
    project_dbs = [project_live, project_sim, project_paper]
    try:
        resolved_primary = primary.resolve()
        project_paths = {p.resolve() for p in project_dbs}
        db_files = project_dbs if resolved_primary in project_paths else [primary]
    except OSError:
        db_files = project_dbs if primary in set(project_dbs) else [primary]
    for db_file in db_files:
        with closing(sqlite3.connect(db_file)) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=5000")
            con.executescript(_SCHEMA)
            _seed_watchlist_if_empty(con)
            con.commit()
            try:
                con.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'live'")
                con.commit()
            except sqlite3.OperationalError:
                pass
            try:
                con.execute("ALTER TABLE trades ADD COLUMN trace_id TEXT")
                con.commit()
            except sqlite3.OperationalError:
                pass
            try:
                con.execute("ALTER TABLE trades ADD COLUMN prompt_version TEXT")
                con.commit()
            except sqlite3.OperationalError:
                pass
            try:
                con.execute("ALTER TABLE trades ADD COLUMN sell_pct REAL")
                con.commit()
            except sqlite3.OperationalError:
                pass
            try:
                con.execute("ALTER TABLE agent_memory ADD COLUMN trace_id TEXT")
                con.commit()
            except sqlite3.OperationalError:
                pass
            try:
                con.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_memory_trace "
                    "ON agent_memory (trace_id)"
                )
                con.commit()
            except sqlite3.OperationalError:
                pass
            try:
                con.execute(
                    "ALTER TABLE pending_evaluations ADD COLUMN retry_count INTEGER DEFAULT 0"
                )
                con.commit()
            except sqlite3.OperationalError:
                pass
            try:
                con.execute("ALTER TABLE agent_memory ADD COLUMN eval_pct_change REAL")
                con.commit()
            except sqlite3.OperationalError:
                pass


def _ensure_db() -> None:
    """Lazy DB initialisation — called on first write/read, not at import time."""
    path = str(_get_db_path())
    if path in _db_initialized_paths:
        return
    with _db_init_lock:
        if path in _db_initialized_paths:
            return
        _init_db()
        _db_initialized_paths.add(path)


def _db_write(query: str, params: tuple, *, retries: int = 3) -> bool:
    """Centralized SQLite write with retries and logging.

    WAL mode is set once by ``_init_db()`` — no need to repeat per-write.
    """
    _ensure_db()
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(_get_db_path(), timeout=5)) as con:
                con.execute(query, params)
                con.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite write failed: %s (query=%s)", e, query[:80])
            return False
        except Exception as e:
            logger.error("SQLite unexpected error: %s", e)
            return False
    return False


def _db_write_returning_id(query: str, params: tuple, *, retries: int = 3) -> int | None:
    """Run a single INSERT and return ``cursor.lastrowid`` (None on failure)."""
    _ensure_db()
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(_get_db_path(), timeout=5)) as con:
                cur = con.execute(query, params)
                con.commit()
                return cur.lastrowid
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite write failed: %s (query=%s)", e, query[:80])
            return None
        except Exception as e:
            logger.error("SQLite unexpected error: %s", e)
            return None
    return None


def _db_write_multi(queries: list[tuple[str, tuple]], *, retries: int = 3) -> bool:
    """Write multiple queries in a single transaction."""
    _ensure_db()
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(_get_db_path(), timeout=5)) as con:
                for query, params in queries:
                    con.execute(query, params)
                con.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite multi-write failed: %s", e)
            return False
        except Exception as e:
            logger.error("SQLite unexpected error: %s", e)
            return False
    return False


def mode_db_path(mode: str) -> Path:
    """Resolve the SQLite file for a given runtime mode label.

    ``mode`` is one of ``"live"`` / ``"paper"`` / ``"sim"``. Lets the
    analytics panel read a specific mode's DB regardless of the active mode (e.g.
    the LIVE-vs-PAPER comparison panel). Unknown labels fall back to live.
    """
    return {
        "live": _DB_ROOT / "trades.db",
        "paper": _DB_ROOT / "trades_paper.db",
        "sim": _DB_ROOT / "trades_sim.db",
    }.get(mode, _DB_ROOT / "trades.db")


def _db_write_at(db_path, query: str, params: tuple, *, retries: int = 3) -> bool:
    """Write to an explicit DB file — mirrors :func:`_db_read_at`.

    Unlike :func:`_db_write`, this does **not** re-resolve ``_get_db_path()``
    on every call. Callers that need several related reads/writes to land in
    the *same* file regardless of a runtime mode switch happening mid-way
    (e.g. ``evaluate_pending_trades`` iterating many rows) should resolve
    the path once and route every operation in that batch through this
    function instead of :func:`_db_write` / :func:`_db_read`.
    """
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(db_path, timeout=5)) as con:
                con.execute(query, params)
                con.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite write failed: %s (query=%s)", e, query[:80])
            return False
        except Exception as e:
            logger.error("SQLite unexpected error: %s", e)
            return False
    return False


def _db_read_at(db_path, query: str, params: tuple = (), *, retries: int = 3) -> list:
    """Read from an explicit DB file (returns ``[]`` if the file is missing).

    Unlike :func:`_db_read`, this does **not** route through
    ``_get_db_path()`` / ``_ensure_db()`` — it reads whatever path is given
    and never creates it. Used for cross-mode reads (LIVE vs PAPER) where the
    target DB may not exist yet.
    """
    p = Path(db_path)
    if not p.exists():
        return []
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(p, timeout=5)) as con:
                con.execute("PRAGMA busy_timeout=5000")
                return con.execute(query, params).fetchall()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite read failed: %s (query=%s)", e, query[:80])
            return []
        except Exception as e:
            logger.error("SQLite read failed: %s (query=%s)", e, query[:80])
            return []
    return []


def _db_read(query: str, params: tuple = (), *, retries: int = 3) -> list:
    """Centralized SQLite read — sim/live path, WAL from ``_init_db``, busy_timeout, retries."""
    _ensure_db()
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(_get_db_path(), timeout=5)) as con:
                con.execute("PRAGMA busy_timeout=5000")
                return con.execute(query, params).fetchall()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite read failed: %s (query=%s)", e, query[:80])
            return []
        except Exception as e:
            logger.error("SQLite read failed: %s (query=%s)", e, query[:80])
            return []
    return []
