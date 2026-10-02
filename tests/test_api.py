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
            "/api/v1/screenings",
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
        assert len(payload["results"]) == 5
        stored = client.get(
            f"/api/v1/screenings/{payload['screening_id']}",
            headers={"X-Screening-Token": payload["screening_token"]},
        )
        assert stored.status_code == 200


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

