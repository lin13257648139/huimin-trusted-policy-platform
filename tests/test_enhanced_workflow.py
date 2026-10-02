import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.repositories.database import Database


def _profile(statement: str = "不要把这段自由叙述写入数据库") -> dict[str, object]:
    return {
        "query_date": "2026-09-29",
        "city": "广州市",
        "district": "天河区",
        "household_size": 3,
        "is_local_hukou": True,
        "member_scope_confirmed": True,
        "monthly_income_total": 3200,
        "deductible_monthly_total": 0,
        "assets_eligible": True,
        "urgent_event": False,
        "user_statement": statement,
    }


def test_active_question_prioritizes_location_then_urgent_risk(
    tmp_path: Path, monkeypatch
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "guidance.db"))
    with TestClient(main.app) as client:
        first = client.post(
            "/api/v1/guidance/next-question",
            json={"query_date": "2026-09-29"},
        )
        assert first.status_code == 200
        assert first.json()["next_question"]["field_id"] == "district"

        second = client.post(
            "/api/v1/guidance/next-question",
            json={"query_date": "2026-09-29", "district": "天河区"},
        )
        assert second.status_code == 200
        assert second.json()["next_question"]["field_id"] == "urgent_event"
        assert second.json()["next_question"]["expected_unknown_reduction"] >= 1

        skipped = client.post(
            "/api/v1/guidance/next-question",
            json={
                "query_date": "2026-09-29",
                "district": "天河区",
                "skipped_fields": ["urgent_event"],
            },
        )
        assert skipped.status_code == 200
        assert skipped.json()["next_question"]["field_id"] != "urgent_event"


def test_screening_returns_office_and_user_can_delete_record(
    tmp_path: Path, monkeypatch
) -> None:
    import app.main as main

    temporary_database = Database(tmp_path / "screening-delete.db")
    monkeypatch.setattr(main, "database", temporary_database)
    statement = "不要把这段自由叙述写入数据库"
    with TestClient(main.app) as client:
        response = client.post("/api/v1/screenings", json=_profile(statement))
        assert response.status_code == 200
        payload = response.json()
        assert payload["recommended_office"]["region"] == "天河区"
        assert payload["screening_token"]
        assert payload["data_retention_days"] > 0

        with temporary_database.connect() as connection:
            row = connection.execute(
                "SELECT request_json, manage_token FROM screenings WHERE id = ?",
                (payload["screening_id"],),
            ).fetchone()
            stored = row["request_json"]
        assert statement not in stored
        assert json.loads(stored)["user_statement"] is None
        assert row["manage_token"] != payload["screening_token"]

        assert client.get(f"/api/v1/screenings/{payload['screening_id']}").status_code == 403
        assert (
            client.post(
                "/api/v1/feedback",
                json={"screening_id": payload["screening_id"], "helpful": True},
            ).status_code
            == 403
        )
        feedback = client.post(
            "/api/v1/feedback",
            headers={"X-Screening-Token": payload["screening_token"]},
            json={"screening_id": payload["screening_id"], "helpful": True},
        )
        assert feedback.status_code == 201

        forbidden = client.delete(f"/api/v1/screenings/{payload['screening_id']}")
        assert forbidden.status_code == 403
        deleted = client.delete(
            f"/api/v1/screenings/{payload['screening_id']}",
            headers={"X-Screening-Token": payload["screening_token"]},
        )
        assert deleted.status_code == 200
        assert (
            client.get(
                f"/api/v1/screenings/{payload['screening_id']}",
                headers={"X-Screening-Token": payload["screening_token"]},
            ).status_code
            == 403
        )


def test_material_package_precheck_detects_minimum_set(
    tmp_path: Path, monkeypatch
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "package.db"))
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    files = [
        ("files", ("身份证.pdf", pdf, "application/pdf")),
        ("files", ("核对授权书.pdf", pdf, "application/pdf")),
        ("files", ("收入证明.pdf", pdf, "application/pdf")),
    ]
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/documents/package-precheck",
            files=files,
            data={"benefit_id": "B002", "consent": "true"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["files_checked"] == 3
        assert payload["missing_recommended"] == []
        assert payload["ready_for_manual_review"] is True
        assert all(document["privacy"]["stored"] is False for document in payload["documents"])


def test_admin_reports_verifiable_governance_controls(
    tmp_path: Path, monkeypatch
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "admin.db"))
    with TestClient(main.app) as client:
        response = client.get("/api/v1/admin/dashboard")
        assert response.status_code == 200
        registry = response.json()["rule_registry"]
        assert registry["registry_sha256_prefix"]
        assert registry["control_summary"]["total"] >= 5
        assert len(registry["rules"]) == 6
        assert sum(rule["benefit_id"] == "B002" for rule in registry["rules"]) == 2


def test_existing_database_is_migrated_before_expiry_index(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE screenings (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, query_date TEXT NOT NULL,
            district TEXT NOT NULL, policy_snapshot TEXT NOT NULL,
            request_json TEXT NOT NULL, result_json TEXT NOT NULL
            )"""
        )
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(screenings)")}
        indexes = {row["name"] for row in connection.execute("PRAGMA index_list(screenings)")}
    assert {"manage_token", "expires_at"} <= columns
    assert "idx_screenings_expires_at" in indexes
