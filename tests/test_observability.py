from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.repositories.database import Database
from app.services import observability


def test_observability_aggregates_latency_counters_and_alerts(monkeypatch) -> None:
    observability.reset_for_tests()
    monkeypatch.setattr(
        observability,
        "settings",
        SimpleNamespace(
            alert_request_p95_ms=100,
            alert_llm_p95_ms=200,
            alert_ocr_p95_ms=300,
            alert_queue_depth=1,
            alert_http_5xx_rate=0.1,
        ),
    )
    observability.increment("http.total", 10)
    observability.increment("http.status.503", 2)
    observability.increment("security.safety_gate_blocked")
    observability.observe("request_ms", 250)
    observability.observe("llm_ms", 210)
    observability.observe("ocr_ms", 50)
    report = observability.snapshot(workload={"outstanding": {"llm": 1, "document": 1}})
    assert report["latency_ms"]["request"]["p95"] == 250
    assert report["http_5xx_rate"] == 0.2
    assert {item["code"] for item in report["alerts"]} == {
        "REQUEST_P95_HIGH",
        "LLM_P95_HIGH",
        "QUEUE_DEPTH_HIGH",
        "HTTP_5XX_RATE_HIGH",
    }


def test_observability_api_requires_governance_auth(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "observability.db"))
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, demo_mode=False, admin_api_token="test-admin-token"),
    )
    with TestClient(main.app) as client:
        assert client.get("/api/v1/admin/observability").status_code == 403
        response = client.get(
            "/api/v1/admin/observability",
            headers={"X-Admin-Token": "test-admin-token"},
        )
    assert response.status_code == 200
    assert response.json()["schema_version"] == "observability/1.0"
    assert "workload" in response.json()


def test_empty_snapshot_and_json_formatter_defensive_paths() -> None:
    observability.reset_for_tests()
    empty = observability.snapshot()
    assert empty["http_5xx_rate"] == 0
    assert empty["queue_depth"] == 0
    assert empty["latency_ms"]["request"]["p95"] is None

    formatter = observability.JsonFormatter()
    record = logging.LogRecord("huimin.test", logging.ERROR, __file__, 1, "failed", (), None)
    assert '"event":"application_log"' in formatter.format(record)
    observability.configure_structured_logging()
    observability.configure_structured_logging()
