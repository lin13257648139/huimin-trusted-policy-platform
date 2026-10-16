from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import readiness, rule_registry
from app.services.rule_registry import RegisteredRule


def _rule(version: str, start: date, end: date | None = None) -> RegisteredRule:
    return RegisteredRule(
        benefit_id="B002",
        name="最低生活保障",
        version=version,
        document_no=None,
        effective_from=start,
        effective_to=end,
        status="verified",
        source_ids=("TEST",),
        parameters={},
        manual_review_required=False,
    )


def test_registry_errors_are_explicit(tmp_path: Path, monkeypatch) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        rule_registry,
        "settings",
        SimpleNamespace(rule_registry_path=invalid),
    )
    rule_registry.load_rule_registry.cache_clear()
    with pytest.raises(ValueError, match="缺少字段"):
        rule_registry.load_rule_registry()
    rule_registry.load_rule_registry.cache_clear()


def test_registry_lookup_overlap_and_missing_parameter(monkeypatch) -> None:
    rules = [
        _rule("v1", date(2026, 1, 1), date(2026, 12, 31)),
        _rule("v2", date(2026, 6, 1), None),
    ]
    monkeypatch.setattr(rule_registry, "rules_for_benefit", lambda _benefit: rules)
    assert rule_registry.get_rule("B002").version == "v2"
    with pytest.raises(ValueError, match="重叠"):
        rule_registry.get_rule_for_date("B002", date(2026, 7, 1))
    monkeypatch.setattr(rule_registry, "rules_for_benefit", lambda _benefit: [])
    with pytest.raises(KeyError, match="未登记"):
        rule_registry.get_rule("UNKNOWN")
    monkeypatch.setattr(rule_registry, "get_rule", lambda _benefit: rules[0])
    with pytest.raises(KeyError, match="缺少参数"):
        rule_registry.decimal_parameter("B002", "missing")


def test_readiness_helpers_cover_missing_and_warning_states(tmp_path: Path) -> None:
    assert readiness._line_count(tmp_path / "missing.jsonl") == 0
    data = tmp_path / "items.jsonl"
    data.write_text("one\n\n two\n", encoding="utf-8")
    assert readiness._line_count(data) == 2
    assert readiness._check("x", "label", False, "detail", critical=False)["status"] == "warn"
    assert readiness._check("x", "label", False, "detail", critical=True)["status"] == "fail"


def test_readiness_provenance_handles_missing_invalid_and_malformed_files(
    tmp_path: Path, monkeypatch
) -> None:
    processed = tmp_path / "data" / "processed"
    raw = tmp_path / "data" / "raw_official"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    catalog = processed / "policy_source_catalog.csv"
    catalog.write_text("source_id,priority\nS1,P0\n", encoding="utf-8")
    registry = processed / "rule_registry.json"
    registry.write_text('{"rules": []}', encoding="utf-8")
    provenance = raw / "provenance_manifest.json"
    monkeypatch.setattr(readiness, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        readiness,
        "settings",
        SimpleNamespace(
            rule_registry_path=registry,
            ocr_enabled=False,
            admin_api_token="token",
            demo_mode=False,
            policy_as_of="2026-10-16",
            app_version="test",
        ),
    )
    monkeypatch.setattr(readiness, "load_policy_sources", lambda: [])
    monkeypatch.setattr(readiness, "load_evidence", lambda: {})
    monkeypatch.setattr(readiness, "load_offices", lambda: [])
    monkeypatch.setattr(readiness, "ocr_runtime_available", lambda: False)
    monkeypatch.setattr(
        readiness,
        "ollama_runtime_status",
        lambda: {"reachable": False, "model_present": False, "reason": "disabled", "chat_model": None},
    )
    monkeypatch.setattr(
        readiness,
        "get_intent_classifier",
        lambda: SimpleNamespace(model_version="test-intent"),
    )

    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    provenance.write_text(
        json.dumps(
            {
                "catalog_sha256": digest,
                "sources": [{"source_id": "S1", "sha256": "abc"}],
            }
        ),
        encoding="utf-8",
    )
    first_report = readiness.build_readiness_report()
    source_check = next(
        item for item in first_report["checks"] if item["id"] == "source_provenance"
    )
    assert source_check["status"] == "pass"

    provenance.write_text(
        json.dumps(
            {
                "catalog_sha256": digest,
                "sources": [
                    {"source_id": "S1", "sha256": "abc", "local_file": "missing.pdf"}
                ],
            }
        ),
        encoding="utf-8",
    )
    report = readiness.build_readiness_report()
    source_check = next(item for item in report["checks"] if item["id"] == "source_provenance")
    assert source_check["status"] == "fail"

    provenance.write_text("not-json", encoding="utf-8")
    report = readiness.build_readiness_report()
    source_check = next(item for item in report["checks"] if item["id"] == "source_provenance")
    assert "无法解析" in source_check["detail"]
