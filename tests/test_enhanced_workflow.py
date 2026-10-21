import io
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.repositories.database import Database


def _valid_demo_pdf() -> bytes:
    image = Image.new("RGB", (1200, 800), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle((45, 45, 1155, 755), outline="black", width=4)
    for row in range(18):
        y = 75 + row * 36
        draw.text((80, y), f"SYNTHETIC MATERIAL LINE {row:02d}", fill="black")
        draw.line((340, y + 8, 1080, y + 8), fill="black", width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    return buffer.getvalue()


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
        response = client.post("/api/v1/screenings?persist=true", json=_profile(statement))
        assert response.status_code == 200
        payload = response.json()
        assert payload["recommended_office"]["region"] == "天河区"
        assert payload["screening_token"]
        assert payload["persisted"] is True
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

        comment_without_consent = client.post(
            "/api/v1/feedback",
            headers={"X-Screening-Token": payload["screening_token"]},
            json={
                "screening_id": payload["screening_id"],
                "helpful": False,
                "issue_type": "usability",
                "comment": "按钮说明不够清楚",
            },
        )
        assert comment_without_consent.status_code == 400
        comment_with_consent = client.post(
            "/api/v1/feedback",
            headers={"X-Screening-Token": payload["screening_token"]},
            json={
                "screening_id": payload["screening_id"],
                "helpful": False,
                "issue_type": "usability",
                "comment": "按钮说明不够清楚",
                "consent_to_store_comment": True,
            },
        )
        assert comment_with_consent.status_code == 201

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


def test_screening_is_stateless_by_default(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    temporary_database = Database(tmp_path / "screening-stateless.db")
    monkeypatch.setattr(main, "database", temporary_database)
    with TestClient(main.app) as client:
        response = client.post("/api/v1/screenings", json=_profile())
        assert response.status_code == 200
        payload = response.json()
        assert payload["persisted"] is False
        assert payload["screening_token"] is None
        assert payload["data_retention_days"] == 0
        with temporary_database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM screenings").fetchone()[0] == 0


def test_material_package_precheck_detects_minimum_set(
    tmp_path: Path, monkeypatch
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "package.db"))
    pdf = _valid_demo_pdf()
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
        dashboard = response.json()
        registry = dashboard["rule_registry"]
        assert registry["registry_sha256_prefix"]
        assert registry["control_summary"]["total"] >= 5
        assert len(registry["rules"]) >= 8
        assessment = dashboard["living_assessment_model"]
        assert assessment["registry_version"] == "2025.11-second-edition.1"
        assert assessment["effective_from"] == "2026-01-01"
        assert assessment["registry_sha256_prefix"]
        assert "不可自动替代" in assessment["automation_boundary"]
        relations = dashboard["benefit_relation_registry"]
        assert relations["registry_version"] == "2026.10.21.1"
        assert relations["relationship_count"] == 5
        assert relations["registry_sha256_prefix"]
        assert "不会" in relations["routing_boundary"]
        historical_manual = [
            item
            for item in registry["rules"]
            if item["version"] in {"v2023.06", "v2022.08"}
        ]
        assert len(historical_manual) == 2
        assert all(item["manual_review_required"] for item in historical_manual)
        assert sum(rule["benefit_id"] == "B002" for rule in registry["rules"]) == 3


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
