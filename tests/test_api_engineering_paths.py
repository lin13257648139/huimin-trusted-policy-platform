from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.repositories.database import Database
from app.services.workload import WorkloadBusyError, WorkloadTimeoutError


def test_static_spa_and_filtered_catalog_paths(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "catalog.db"))
    with TestClient(main.app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.headers["cache-control"] == "no-cache"
        assert client.get("/static/js/app.js").status_code == 200
        assert client.get("/static/js/app.js").headers.get("cache-control") != "no-store"
        assert client.get("/route-that-belongs-to-the-spa").status_code == 200
        assert client.get("/manifest.webmanifest").status_code == 200

        city_fallback = client.get("/api/v1/offices?district=不存在区")
        assert city_fallback.status_code == 200
        assert city_fallback.json()[0]["region"] == "广州市"
        assert len(client.get("/api/v1/offices").json()) >= 12
        filtered = client.get("/api/v1/policies?topic=最低生活保障")
        assert filtered.status_code == 200
        assert filtered.json()
        assert client.get("/api/v1/policies").status_code == 200


def test_upload_middleware_rejects_invalid_and_oversized_lengths(
    tmp_path: Path, monkeypatch
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "limits.db"))
    with TestClient(main.app) as client:
        invalid = client.post(
            "/api/v1/documents/precheck",
            content=b"x",
            headers={"content-length": "invalid", "content-type": "application/octet-stream"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"]["code"] == "INVALID_CONTENT_LENGTH"
        oversized = client.post(
            "/api/v1/documents/package-precheck",
            content=b"x",
            headers={
                "content-length": str(
                    main.settings.max_package_bytes
                    + main.settings.multipart_overhead_bytes
                    + 1
                ),
                "content-type": "application/octet-stream",
            },
        )
        assert oversized.status_code == 413


def test_document_endpoints_require_consent(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "consent.db"))
    with TestClient(main.app) as client:
        single = client.post(
            "/api/v1/documents/precheck",
            files={"file": ("sample.png", b"not-an-image", "image/png")},
            data={"consent": "false"},
        )
        package = client.post(
            "/api/v1/documents/package-precheck",
            files=[("files", ("sample.png", b"not-an-image", "image/png"))],
            data={"consent": "false", "benefit_id": "B002"},
        )
    assert single.status_code == 400
    assert package.status_code == 400


@pytest.mark.parametrize(
    ("failure", "status"),
    [(WorkloadBusyError("busy"), 503), (WorkloadTimeoutError("slow"), 504)],
)
def test_workload_failures_map_to_retryable_http_status(monkeypatch, failure, status) -> None:
    import app.main as main

    async def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(main, "run_bounded", fail)
    with pytest.raises(HTTPException) as captured:
        asyncio.run(main._run_workload("llm", lambda: None, timeout=1))
    assert captured.value.status_code == status


def test_feedback_handles_storage_race(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    database = Database(tmp_path / "feedback-race.db")
    monkeypatch.setattr(main, "database", database)
    with TestClient(main.app) as client:
        monkeypatch.setattr(database, "screening_token_valid", lambda *_args: True)
        monkeypatch.setattr(database, "save_feedback", lambda *_args: False)
        response = client.post(
            "/api/v1/feedback",
            headers={"X-Screening-Token": "valid-before-race"},
            json={
                "screening_id": "HM-RACE",
                "helpful": False,
                "issue_type": "other",
                "comment": None,
                "consent_to_store_comment": False,
            },
        )
    assert response.status_code == 404
