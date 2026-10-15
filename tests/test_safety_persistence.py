from datetime import UTC, date, datetime, timedelta

import pytest

from app.repositories.database import Database


def _save(database: Database, safety_validation: dict) -> None:
    database.save_screening(
        screening_id="HM-SAFETYTEST",
        query_date=date(2026, 9, 30).isoformat(),
        district="天河区",
        policy_snapshot="test-snapshot",
        request_payload={"household_size": 1},
        result_payload={"safety_validation": safety_validation},
        retention_days=30,
    )


@pytest.mark.parametrize(
    "safety_validation",
    [
        {},
        {"safe": False, "blocked": True},
        {"safe": True, "blocked": False},
        {
            "safe": True,
            "blocked": False,
            "enforcement": {
                "api_publish": True,
                "persistence": False,
                "presentation": True,
                "print_export": True,
            },
        },
    ],
)
def test_database_rejects_result_without_complete_safety_release(
    tmp_path, safety_validation
) -> None:
    database = Database(tmp_path / "safety.db")
    database.initialize()

    with pytest.raises(ValueError, match="安全门未明确放行"):
        _save(database, safety_validation)

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM screenings").fetchone()[0] == 0


def test_database_accepts_only_complete_safety_release(tmp_path) -> None:
    database = Database(tmp_path / "safety-pass.db")
    database.initialize()
    _save(
        database,
        {
            "safe": True,
            "blocked": False,
            "enforcement": {
                "api_publish": True,
                "persistence": True,
                "presentation": True,
                "print_export": True,
            },
        },
    )

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM screenings").fetchone()[0] == 1


def test_expired_record_cannot_be_read_or_receive_feedback(tmp_path) -> None:
    database = Database(tmp_path / "expired.db")
    database.initialize()
    token = database.save_screening(
        screening_id="HM-EXPIRED",
        query_date=date(2026, 9, 30).isoformat(),
        district="天河区",
        policy_snapshot="test-snapshot",
        request_payload={"household_size": 1},
        result_payload={
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
        },
        retention_days=30,
    )
    expired_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE screenings SET expires_at = ? WHERE id = ?",
            (expired_at, "HM-EXPIRED"),
        )

    assert database.screening_token_valid("HM-EXPIRED", token) is False
    assert database.get_screening("HM-EXPIRED", token) is None
    assert (
        database.save_feedback(
            {
                "screening_id": "HM-EXPIRED",
                "helpful": False,
                "issue_type": "other",
                "comment": "should not persist",
            }
        )
        is False
    )


def test_retention_purges_old_audit_entries(tmp_path) -> None:
    database = Database(tmp_path / "audit-retention.db")
    database.initialize()
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    database.record_audit_event("old.event", entity_id=None, details={"count": 1})
    with database.connect() as connection:
        connection.execute("UPDATE audit_log SET created_at = ?", (old,))

    database.purge_expired(30)

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
