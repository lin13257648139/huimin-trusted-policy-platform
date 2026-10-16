from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.repositories.database import Database
from app.repositories.migrations import LATEST_SCHEMA_VERSION


def _safe_result() -> dict[str, object]:
    return {
        "safety_validation": {
            "safe": True,
            "blocked": False,
            "enforcement": {
                "api_publish": True,
                "persistence": True,
                "presentation": True,
                "print_export": True,
            },
        }
    }


def _save(database: Database, screening_id: str = "HM-DB-1") -> str:
    return database.save_screening(
        screening_id=screening_id,
        query_date="2026-10-16",
        district="天河区",
        policy_snapshot="snapshot-v1",
        request_payload={"user_statement": "敏感叙述"},
        result_payload=_safe_result(),
        retention_days=30,
    )


def test_legacy_database_upgrades_without_losing_rows(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE screenings (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, query_date TEXT NOT NULL,
                district TEXT NOT NULL, policy_snapshot TEXT NOT NULL,
                request_json TEXT NOT NULL, result_json TEXT NOT NULL
            );
            CREATE TABLE feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT, screening_id TEXT NOT NULL,
                helpful INTEGER NOT NULL, issue_type TEXT NOT NULL, comment TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                entity_id TEXT, details_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO screenings VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HM-LEGACY",
                datetime.now(UTC).isoformat(),
                "2026-10-16",
                "天河区",
                "old-snapshot",
                "{}",
                json.dumps(_safe_result()),
            ),
        )
    database = Database(path)
    database.initialize()
    assert database.schema_version == LATEST_SCHEMA_VERSION
    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(screenings)")}
        versions = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        row = connection.execute("SELECT policy_snapshot FROM screenings").fetchone()
    assert {"manage_token", "expires_at"} <= columns
    assert versions == LATEST_SCHEMA_VERSION
    assert row["policy_snapshot"] == "old-snapshot"


def test_backup_restore_round_trip_and_migration(tmp_path: Path) -> None:
    database = Database(tmp_path / "active.db")
    database.initialize()
    original_token = _save(database)
    backup = database.backup_to(tmp_path / "backups" / "snapshot.db")
    assert database.delete_screening("HM-DB-1", original_token) is True
    assert database.get_screening("HM-DB-1", original_token) is None

    database.restore_from(backup)
    assert database.schema_version == LATEST_SCHEMA_VERSION
    assert database.get_screening("HM-DB-1", original_token) == _safe_result()


def test_restore_rejects_missing_and_newer_database(tmp_path: Path) -> None:
    database = Database(tmp_path / "active.db")
    database.initialize()
    with pytest.raises(FileNotFoundError):
        database.restore_from(tmp_path / "missing.db")
    newer = tmp_path / "newer.db"
    with sqlite3.connect(newer) as connection:
        connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")
    with pytest.raises(ValueError, match="高于"):
        database.restore_from(newer)


def test_delete_and_expiry_cleanup_remove_feedback(tmp_path: Path) -> None:
    database = Database(tmp_path / "cleanup.db")
    database.initialize()
    token = _save(database, "HM-DELETE")
    assert database.save_feedback(
        {
            "screening_id": "HM-DELETE",
            "helpful": True,
            "issue_type": "helpful",
            "comment": None,
        }
    )
    assert database.delete_screening("HM-DELETE", "bad-token") is False
    assert database.delete_screening("HM-DELETE", token) is True

    _save(database, "HM-EXPIRED")
    expired = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE screenings SET expires_at = ? WHERE id = ?", (expired, "HM-EXPIRED")
        )
        connection.execute(
            "INSERT INTO feedback(screening_id, helpful, issue_type, created_at) "
            "VALUES (?, 1, 'helpful', ?)",
            ("HM-EXPIRED", datetime.now(UTC).isoformat()),
        )
    assert database.purge_expired(30) == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
        event = connection.execute(
            "SELECT event_type FROM audit_log WHERE event_type = 'retention.purged'"
        ).fetchone()
    assert event is not None


def test_migration_ledger_detects_newer_and_tampered_schemas(tmp_path: Path) -> None:
    newer = Database(tmp_path / "future.db")
    with sqlite3.connect(newer.path) as connection:
        connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="拒绝降级"):
        newer.initialize()

    tampered = Database(tmp_path / "tampered.db")
    tampered.initialize()
    with tampered.connect() as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1"
        )
    with pytest.raises(RuntimeError, match="校验和"):
        tampered.initialize()


def test_migration_handles_preexisting_new_columns_and_legacy_user_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pragma-only.db"
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations")
        connection.execute("PRAGMA user_version = 2")
    database.initialize()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 3
