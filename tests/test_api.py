import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.repositories.database import Database


def test_health_and_screening_api(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    temporary_database = Database(tmp_path / "test.db")
    monkeypatch.setattr(main, "database", temporary_database)
    with TestClient(main.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["service_id"] == "huimin-guide"

        response = client.post(
            "/api/v1/screenings?persist=true",
            json={
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
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["screening_id"].startswith("HM-")
        assert payload["combination_plan_version"] == "2026.10.15.1"
        assert len(payload["results"]) == 5
        rigid = next(item for item in payload["results"] if item["benefit_id"] == "B004")
        assert rigid["plan_role"] == "alternative"
        assert any(
            relation["relation_id"] == "REL-B002-B004"
            for relation in rigid["plan_relations"]
        )
        stored = client.get(
            f"/api/v1/screenings/{payload['screening_id']}",
            headers={"X-Screening-Token": payload["screening_token"]},
        )
        assert stored.status_code == 200
        assert stored.json()["combination_plan_version"] == "2026.10.15.1"


def test_screening_api_keeps_omitted_urgent_event_unknown(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "test-unknown.db"))
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/screenings",
            json={
                "query_date": "2026-09-29",
                "city": "广州市",
                "district": "天河区",
                "household_size": 3,
                "is_local_hukou": True,
                "member_scope_confirmed": True,
                "monthly_income_total": 3200,
                "assets_eligible": True,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["profile_summary"]["urgent_event"] is None
        temporary = next(item for item in payload["results"] if item["benefit_id"] == "B005")
        event = next(item for item in temporary["conditions"] if item["code"] == "urgent_event")
        assert event["state"] == "unknown"
        assert temporary["status"] == "incomplete"


def test_safety_failure_returns_422_without_saving_result(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    temporary_database = Database(tmp_path / "test-safety-block.db")
    monkeypatch.setattr(main, "database", temporary_database)

    def reject_output(*_args, **_kwargs):
        return {
            "safe": False,
            "blocked": True,
            "failed_check_ids": ["decision_boundary"],
            "checks": [],
            "enforcement": {
                "api_publish": False,
                "persistence": False,
                "presentation": False,
                "print_export": False,
            },
        }

    monkeypatch.setattr(main, "validate_screening_output", reject_output)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/screenings",
            json={
                "query_date": "2026-09-29",
                "district": "天河区",
                "household_size": 3,
                "is_local_hukou": True,
                "member_scope_confirmed": True,
                "monthly_income_total": 3200,
                "assets_eligible": True,
                "urgent_event": False,
            },
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "SAFETY_GATE_BLOCKED"
        assert detail["failed_check_ids"] == ["decision_boundary"]
        assert "results" not in response.json()

        with temporary_database.connect() as connection:
            saved = connection.execute("SELECT COUNT(*) FROM screenings").fetchone()[0]
            audit = connection.execute(
                "SELECT details_json FROM audit_log WHERE event_type = ?",
                ("screening.safety_blocked",),
            ).fetchone()
        assert saved == 0
        assert json.loads(audit["details_json"])["failed_check_ids"] == ["decision_boundary"]


def test_api_refuses_legacy_stored_result_marked_unsafe(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    temporary_database = Database(tmp_path / "test-stored-safety-block.db")
    monkeypatch.setattr(main, "database", temporary_database)
    with TestClient(main.app) as client:
        with temporary_database.connect() as connection:
            connection.execute(
                """
                INSERT INTO screenings
                (id, created_at, query_date, district, policy_snapshot, request_json,
                 result_json, manage_token, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "HM-UNSAFEOLD",
                    "2026-09-30T00:00:00+00:00",
                    "2026-09-30",
                    "天河区",
                    "legacy",
                    "{}",
                    json.dumps(
                        {
                            "safety_validation": {
                                "safe": False,
                                "blocked": True,
                                "failed_check_ids": ["verbatim_evidence"],
                            }
                        }
                    ),
                    "legacy-token",
                    "2099-01-01T00:00:00+00:00",
                ),
            )

        response = client.get(
            "/api/v1/screenings/HM-UNSAFEOLD",
            headers={"X-Screening-Token": "legacy-token"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "STORED_RESULT_SAFETY_BLOCKED"
        assert "results" not in response.json()


def test_document_endpoint_requires_consent(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "test-consent.db"))
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/documents/precheck",
            files={"file": ("材料.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
            data={"material_type": "auto", "consent": "false"},
        )
        assert response.status_code == 400


def test_living_assessment_api_returns_auditable_calculation(
    tmp_path: Path, monkeypatch
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "test-assessment.db"))
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/assessments/living-conditions",
            json={
                "query_date": "2026-09-30",
                "household_member_count": 3,
                "wage_income_monthly_avg": 3600,
                "operating_income_monthly_avg": 0,
                "property_income_monthly_avg": 0,
                "transfer_income_monthly_avg": 0,
                "employment_cost_claimed": 600,
                "laborer_count": 1,
                "six_month_average_confirmed": True,
                "labor_income_assessment_complete": True,
                "member_adjustments": {"preschool": 1},
                "member_nonstack_confirmed": True,
                "obligor_information_complete": True,
                "no_usable_owned_housing": False,
                "counted_motorcycles": 0,
                "counted_electric_bicycles": 1,
                "vehicle_exclusions_confirmed": True,
                "verification_report_available": True,
                "in_home_assessment_completed": True,
                "investigator_confirmed": True,
                "household_confirmed": True,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["calculation_status"] == "calculated"
        assert payload["assessed_per_capita_d"] == "0.59"
        assert payload["threshold_comparison"] == "below_1d"
        assert payload["official_process_complete"] is True
        assert "E-GD-004-A-FORMULA" in payload["evidence_ids"]
        assert "不是低保审批结论" in payload["decision_boundary"]


def test_static_javascript_has_executable_mime_type(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "test-static.db"))
    with TestClient(main.app) as client:
        response = client.get("/static/js/app.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
        assert response.headers["x-content-type-options"] == "nosniff"


def test_readiness_request_tracing_and_offline_shell(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "test-readiness.db"))
    with TestClient(main.app) as client:
        response = client.get(
            "/api/v1/system/readiness",
            headers={"X-Request-ID": "competition-smoke-001"},
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"] == "competition-smoke-001"
        assert response.headers["server-timing"].startswith("app;dur=")
        payload = response.json()
        assert payload["ready"] is True
        assert payload["summary"]["failed"] == 0
        assert {"policy_catalog", "rule_registry", "synthetic_regression"} <= {
            item["id"] for item in payload["checks"]
        }
        assert "准确率" in payload["claim_boundary"]

        worker = client.get("/sw.js")
        assert worker.status_code == 200
        assert worker.headers["service-worker-allowed"] == "/"
        assert worker.headers["content-type"].startswith("application/javascript")

