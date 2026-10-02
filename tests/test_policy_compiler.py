from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.models import PolicyCompileRequest
from app.repositories.database import Database
from app.services.policy_compiler import analyze_policy_impact, compile_policy


POLICY_TEXT = (
    "广州市最低生活保障办法。共同生活家庭成员人均月收入低于本市最低生活保障标准，"
    "且家庭财产状况符合规定的，可以申请最低生活保障。"
    "2027年最低生活保障标准调整为1400元/人/月。"
    "本通知自2027年8月1日起施行，有效期为1年。"
)


def _request() -> PolicyCompileRequest:
    return PolicyCompileRequest(
        source_id="GZ-TEST-2027",
        title="广州市最低生活保障测试政策",
        source_text=POLICY_TEXT,
        region="广州市",
        benefit_hint="B002",
        use_llm=False,
    )


def test_policy_compiler_extracts_temporal_rule_and_keeps_it_unpublished() -> None:
    result = compile_policy(_request())

    assert result.candidate.benefit_id == "B002"
    assert result.candidate.effective_from.isoformat() == "2027-08-01"
    assert result.candidate.effective_to.isoformat() == "2028-07-31"
    assert result.candidate.parameters["income_standard_monthly_per_capita"] == "1400.00"
    assert {item.field for item in result.candidate.conditions} >= {
        "per_capita_monthly_income",
        "assets_eligible",
        "member_scope_confirmed",
    }
    assert result.candidate.source_sha256
    assert result.publishable is False
    assert any("双人" in item for item in result.publish_blockers)
    assert result.version_diff["baseline_version"] == "v2026.08"


def test_policy_impact_reports_changed_synthetic_cases() -> None:
    result = compile_policy(_request())
    impact = analyze_policy_impact(result.candidate)

    assert impact.total_cases == 240
    assert impact.comparable_cases > 0
    assert impact.changed_cases > 0
    assert impact.changes_by_direction["newly_included"] > 0
    assert "真实群众数量" in impact.notes[0]


def test_policy_compiler_api_is_auditable(tmp_path: Path, monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "database", Database(tmp_path / "policy-compiler.db"))
    with TestClient(main.app) as client:
        compiled = client.post(
            "/api/v1/admin/policy/compile",
            json=_request().model_dump(mode="json"),
        )
        assert compiled.status_code == 200
        payload = compiled.json()
        assert payload["candidate"]["status"] == "draft_requires_dual_review"
        assert payload["publishable"] is False

        impact = client.post(
            "/api/v1/admin/policy/impact",
            json={"candidate": payload["candidate"]},
        )
        assert impact.status_code == 200
        assert impact.json()["total_cases"] == 240
