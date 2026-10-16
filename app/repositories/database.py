from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS screenings (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    query_date TEXT NOT NULL,
    district TEXT NOT NULL,
    policy_snapshot TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    manage_token TEXT,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_id TEXT NOT NULL,
    helpful INTEGER NOT NULL,
    issue_type TEXT NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(screening_id) REFERENCES screenings(id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_screenings_created_at ON screenings(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(screenings)").fetchall()
            }
            if "manage_token" not in columns:
                connection.execute("ALTER TABLE screenings ADD COLUMN manage_token TEXT")
            if "expires_at" not in columns:
                connection.execute("ALTER TABLE screenings ADD COLUMN expires_at TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_screenings_expires_at ON screenings(expires_at)"
            )

    def purge_expired(self, retention_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM screenings WHERE (expires_at IS NOT NULL AND expires_at < ?) "
                "OR (expires_at IS NULL AND created_at < ?)",
                (now, cutoff),
            ).fetchall()
            identifiers = [row["id"] for row in rows]
            if identifiers:
                placeholders = ",".join("?" for _ in identifiers)
                connection.execute(
                    # Placeholder count is derived only from the internal row count;
                    # all identifiers remain bound parameters.
                    f"DELETE FROM feedback WHERE screening_id IN ({placeholders})",  # nosec B608
                    identifiers,
                )
                connection.execute(
                    f"DELETE FROM screenings WHERE id IN ({placeholders})",  # nosec B608
                    identifiers,
                )
                connection.execute(
                    "INSERT INTO audit_log(event_type, entity_id, details_json, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "retention.purged",
                        None,
                        json.dumps({"count": len(identifiers)}),
                        now,
                    ),
                )
            connection.execute("DELETE FROM audit_log WHERE created_at < ?", (cutoff,))
        return len(identifiers)

    def save_screening(
        self,
        *,
        screening_id: str,
        query_date: str,
        district: str,
        policy_snapshot: str,
        request_payload: dict[str, Any],
        result_payload: dict[str, Any],
        retention_days: int,
    ) -> str:
        safety = result_payload.get("safety_validation")
        enforcement = safety.get("enforcement") if isinstance(safety, dict) else None
        required_actions = ("api_publish", "persistence", "presentation", "print_export")
        if (
            not isinstance(safety, dict)
            or safety.get("safe") is not True
            or safety.get("blocked") is not False
            or not isinstance(enforcement, dict)
            or not all(enforcement.get(action) is True for action in required_actions)
        ):
            raise ValueError("安全门未明确放行，禁止保存预筛结果")
        safe_request = dict(request_payload)
        if safe_request.get("user_statement"):
            safe_request["user_statement"] = "[已脱敏，不落库]"
        created_at = datetime.now(UTC).isoformat()
        expires_at = (
            datetime.now(UTC) + timedelta(days=retention_days)
        ).isoformat()
        manage_token = secrets.token_urlsafe(24)
        stored_token = hashlib.sha256(manage_token.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO screenings
                (id, created_at, query_date, district, policy_snapshot, request_json, result_json,
                 manage_token, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    screening_id,
                    created_at,
                    query_date,
                    district,
                    policy_snapshot,
                    json.dumps(safe_request, ensure_ascii=False),
                    json.dumps(result_payload, ensure_ascii=False),
                    stored_token,
                    expires_at,
                ),
            )
            connection.execute(
                "INSERT INTO audit_log(event_type, entity_id, details_json, created_at) VALUES (?, ?, ?, ?)",
                ("screening.created", screening_id, json.dumps({"district": district}), created_at),
            )
        return manage_token

    def record_audit_event(
        self, event_type: str, *, entity_id: str | None, details: dict[str, Any]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit_log(event_type, entity_id, details_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    event_type,
                    entity_id,
                    json.dumps(details, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

    @staticmethod
    def _token_matches(stored_token: str | None, supplied_token: str) -> bool:
        if not stored_token:
            return False
        supplied_hash = hashlib.sha256(supplied_token.encode("utf-8")).hexdigest()
        return secrets.compare_digest(stored_token, supplied_hash) or secrets.compare_digest(
            stored_token, supplied_token
        )

    def screening_token_valid(self, screening_id: str, manage_token: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT manage_token FROM screenings WHERE id = ? "
                "AND (expires_at IS NULL OR expires_at >= ?)",
                (screening_id, now),
            ).fetchone()
        return bool(row and self._token_matches(row["manage_token"], manage_token))

    def get_screening(self, screening_id: str, manage_token: str) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json, manage_token FROM screenings WHERE id = ? "
                "AND (expires_at IS NULL OR expires_at >= ?)",
                (screening_id, now),
            ).fetchone()
        if not row or not self._token_matches(row["manage_token"], manage_token):
            return None
        return json.loads(row["result_json"])

    def save_feedback(self, payload: dict[str, Any]) -> bool:
        created_at = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM screenings WHERE id = ? "
                "AND (expires_at IS NULL OR expires_at >= ?)",
                (payload["screening_id"], created_at),
            ).fetchone()
            if not exists:
                return False
            connection.execute(
                """
                INSERT INTO feedback(screening_id, helpful, issue_type, comment, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload["screening_id"],
                    1 if payload["helpful"] else 0,
                    payload["issue_type"],
                    payload.get("comment"),
                    created_at,
                ),
            )
        return True

    def delete_screening(self, screening_id: str, manage_token: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT manage_token FROM screenings WHERE id = ?", (screening_id,)
            ).fetchone()
            if row is None or not row["manage_token"]:
                return False
            # 兼容升级前已生成的少量本地演示记录；新记录只保存令牌哈希。
            if not self._token_matches(row["manage_token"], manage_token):
                return False
            connection.execute("DELETE FROM feedback WHERE screening_id = ?", (screening_id,))
            connection.execute("DELETE FROM screenings WHERE id = ?", (screening_id,))
            connection.execute(
                "INSERT INTO audit_log(event_type, entity_id, details_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    "screening.deleted",
                    screening_id,
                    json.dumps({"requested_by": "screening_token"}),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return True

    def dashboard_stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            screenings = connection.execute("SELECT COUNT(*) AS count FROM screenings").fetchone()["count"]
            feedback = connection.execute("SELECT COUNT(*) AS count FROM feedback").fetchone()["count"]
            helpful = connection.execute(
                "SELECT COUNT(*) AS count FROM feedback WHERE helpful = 1"
            ).fetchone()["count"]
            recent = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, created_at, district, query_date, policy_snapshot
                    FROM screenings ORDER BY created_at DESC LIMIT 8
                    """
                ).fetchall()
            ]
        return {
            "screenings": screenings,
            "feedback": feedback,
            "helpful_rate": round(helpful / feedback * 100, 1) if feedback else None,
            "recent": recent,
        }

