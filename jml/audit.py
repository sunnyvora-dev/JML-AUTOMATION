"""
Audit logging engine storing immutable JSONB operational records in PostgreSQL.
"""

import json
import logging
from typing import Any, Dict, List, Optional
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    psycopg2 = None
    RealDictCursor = None
    PSYCOPG2_AVAILABLE = False

logger = logging.getLogger(__name__)


class Audit:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._conn = None
        self._connect()

    def _connect(self):
        if not PSYCOPG2_AVAILABLE:
            logger.warning("psycopg2 module not installed. Falling back to in-memory audit log.")
            self._conn = None
            return
        try:
            self._conn = psycopg2.connect(self.database_url)
            self._conn.autocommit = True
            self._ensure_tables()
        except Exception as exc:
            logger.warning(f"Database connection warning: {exc}")
            self._conn = None

    def _ensure_tables(self):
        if not self._conn:
            return
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    event_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_username TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'jml-automation',
                    details JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_log_target_username ON audit_log(target_username);
                CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);

                CREATE TABLE IF NOT EXISTS processed_events (
                    event_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

    @staticmethod
    def _sanitize_details(details: Dict[str, Any]) -> Dict[str, Any]:
        """Strips potential sensitive key values before logging."""
        sanitized = {}
        for k, v in details.items():
            key_lower = k.lower()
            if any(secret_term in key_lower for secret_term in ["password", "secret", "token", "auth"]):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = Audit._sanitize_details(v)
            else:
                sanitized[k] = v
        return sanitized

    def log(
        self,
        event_id: str,
        action: str,
        username: str,
        status: str,
        details: Dict[str, Any],
        actor: str = "jml-automation",
    ) -> None:
        """Persists audit log entry to database."""
        clean_details = self._sanitize_details(details)
        if not self._conn:
            logger.info(f"AUDIT LOG [DB UNCONNECTED] {event_id} {action} {username} {status} {clean_details}")
            return

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (event_id, action, target_username, status, actor, details)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (event_id, action.upper(), username, status.upper(), actor, json.dumps(clean_details)),
            )

    def already_processed(self, event_id: str) -> bool:
        """Checks if event_id has already been processed (idempotency key check)."""
        if not self._conn:
            return False
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM processed_events WHERE event_id = %s", (event_id,))
            return cur.fetchone() is not None

    def mark_processed(self, event_id: str) -> None:
        """Marks event_id as processed."""
        if not self._conn:
            return
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO processed_events (event_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (event_id,),
            )

    def report(self, username: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Queries audit log records."""
        if not self._conn:
            return []

        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            if username:
                cur.execute(
                    """
                    SELECT id, ts, event_id, action, target_username, status, actor, details
                    FROM audit_log
                    WHERE target_username = %s
                    ORDER BY id DESC LIMIT %s
                    """,
                    (username, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, ts, event_id, action, target_username, status, actor, details
                    FROM audit_log
                    ORDER BY id DESC LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
