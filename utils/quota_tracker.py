import time
import os
import sqlite3
import threading
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

DB_DIR = "data"
DB_FILE = os.path.join(DB_DIR, "quota.db")


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_get_conn, "_local"):
        _get_conn._local = threading.local()
    conn: Optional[sqlite3.Connection] = getattr(_get_conn._local, "conn", None)
    if conn is None:
        os.makedirs(DB_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_FILE, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _get_conn._local.conn = conn
    return conn


_lock = threading.Lock()


def _init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quota_usage (
            provider   TEXT NOT NULL,
            quota_type TEXT NOT NULL,
            usage      INTEGER NOT NULL DEFAULT 0,
            reset_ts   REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (provider, quota_type)
        )
    """)
    conn.commit()


_init_db()


class QuotaTracker:
    def __init__(self):
        # Keep a reference so the module-level init runs
        _get_conn()

    # ── internal helpers ───────────────────────────────────────────

    @staticmethod
    def _ensure_provider_exists(conn: sqlite3.Connection, provider_name: str):
        for qt in ("daily", "monthly"):
            conn.execute(
                "INSERT OR IGNORE INTO quota_usage (provider, quota_type, usage, reset_ts) VALUES (?, ?, 0, 0)",
                (provider_name, qt),
            )
        conn.commit()

    @staticmethod
    def _check_and_reset_quota(conn: sqlite3.Connection, provider_name: str, quota_type: str):
        """Check if quota needs reset and reset if necessary. Must be called inside a lock."""
        QuotaTracker._ensure_provider_exists(conn, provider_name)

        row = conn.execute(
            "SELECT usage, reset_ts FROM quota_usage WHERE provider=? AND quota_type=?",
            (provider_name, quota_type),
        ).fetchone()

        now = time.time()
        last_reset = row[1] if row else 0

        needs_reset = False
        if quota_type == "daily":
            needs_reset = datetime.fromtimestamp(now).date() != datetime.fromtimestamp(last_reset).date()
        elif quota_type == "monthly":
            needs_reset = datetime.fromtimestamp(now).month != datetime.fromtimestamp(last_reset).month or \
                          datetime.fromtimestamp(now).year != datetime.fromtimestamp(last_reset).year

        if needs_reset:
            conn.execute(
                "UPDATE quota_usage SET usage=0, reset_ts=? WHERE provider=? AND quota_type=?",
                (now, provider_name, quota_type),
            )
            conn.commit()

    # ── public API (signatures unchanged) ──────────────────────────

    def can_use(self, provider_name: str, quota_type: str, limit: int) -> bool:
        """Check if provider can be used within quota limits"""
        with _lock:
            conn = _get_conn()
            self._check_and_reset_quota(conn, provider_name, quota_type)
            row = conn.execute(
                "SELECT usage FROM quota_usage WHERE provider=? AND quota_type=?",
                (provider_name, quota_type),
            ).fetchone()
            current_usage = row[0] if row else 0
            return current_usage < limit

    def record_usage(self, provider_name: str, quota_type: str, tokens_used: int):
        """Record token usage for a provider"""
        with _lock:
            conn = _get_conn()
            self._check_and_reset_quota(conn, provider_name, quota_type)
            conn.execute(
                "UPDATE quota_usage SET usage = usage + ? WHERE provider=? AND quota_type=?",
                (tokens_used, provider_name, quota_type),
            )
            conn.commit()
        logger.info(f"Recorded {tokens_used} tokens usage for {provider_name} ({quota_type})")

    def get_usage(self, provider_name: str, quota_type: str) -> int:
        """Get current usage for a provider"""
        with _lock:
            conn = _get_conn()
            self._check_and_reset_quota(conn, provider_name, quota_type)
            row = conn.execute(
                "SELECT usage FROM quota_usage WHERE provider=? AND quota_type=?",
                (provider_name, quota_type),
            ).fetchone()
            return row[0] if row else 0

    def get_status(self) -> Dict[str, Dict[str, int]]:
        """Get usage status for all providers"""
        with _lock:
            conn = _get_conn()
            # Touch every known provider to trigger resets
            rows = conn.execute("SELECT DISTINCT provider FROM quota_usage").fetchall()
            for (provider_name,) in rows:
                self._check_and_reset_quota(conn, provider_name, "daily")
                self._check_and_reset_quota(conn, provider_name, "monthly")

            status: Dict[str, Dict[str, int]] = {}
            all_rows = conn.execute("SELECT provider, quota_type, usage FROM quota_usage").fetchall()
            for provider, qt, usage in all_rows:
                if provider not in status:
                    status[provider] = {"daily": 0, "monthly": 0}
                status[provider][qt] = usage
            return status
