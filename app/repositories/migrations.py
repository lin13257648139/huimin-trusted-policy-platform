from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

MigrationOperation = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    operation: MigrationOperation

    @property
    def checksum(self) -> str:
        payload = f"{self.version}:{self.name}".encode()
        return hashlib.sha256(payload).hexdigest()


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}  # nosec B608


def _v1_initial_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS screenings (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            query_date TEXT NOT NULL,
            district TEXT NOT NULL,
            policy_snapshot TEXT NOT NULL,
            request_json TEXT NOT NULL,
            result_json TEXT NOT NULL
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
    )


def _v2_retention_and_tokens(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "screenings")
    if "manage_token" not in columns:
        connection.execute("ALTER TABLE screenings ADD COLUMN manage_token TEXT")
    if "expires_at" not in columns:
        connection.execute("ALTER TABLE screenings ADD COLUMN expires_at TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_screenings_expires_at ON screenings(expires_at)"
    )


def _v3_feedback_lookup(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_screening_id ON feedback(screening_id)"
    )


MIGRATIONS = (
    Migration(1, "initial-schema", _v1_initial_schema),
    Migration(2, "retention-and-management-tokens", _v2_retention_and_tokens),
    Migration(3, "feedback-screening-index", _v3_feedback_lookup),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def run_migrations(connection: sqlite3.Connection) -> int:
    """Upgrade a fresh or legacy database and leave an auditable migration ledger."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > LATEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库版本{current}高于程序支持的{LATEST_SCHEMA_VERSION}，拒绝降级打开"
        )

    applied = {
        int(row[0]): (str(row[1]), str(row[2]))
        for row in connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchall()
    }
    for migration in MIGRATIONS:
        if migration.version in applied:
            recorded_name, recorded_checksum = applied[migration.version]
            if (recorded_name, recorded_checksum) != (migration.name, migration.checksum):
                raise RuntimeError(f"数据库迁移{migration.version}的登记校验和不一致")
            continue
        if migration.version <= current:
            # 兼容早期仅使用PRAGMA user_version、尚无迁移台账的数据库。
            connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.checksum),
            )
            continue
        migration.operation(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
            (migration.version, migration.name, migration.checksum),
        )
        connection.execute(f"PRAGMA user_version = {migration.version}")  # nosec B608
        current = migration.version
    return current
