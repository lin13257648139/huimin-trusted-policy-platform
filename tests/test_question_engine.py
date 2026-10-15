from app.domain.models import GuidanceDraft
from app.services.question_engine import next_guidance_question


def _answer_until_done(draft_data: dict[str, object]) -> list[str]:
    asked: list[str] = []
    for _ in range(20):
        response = next_guidance_question(GuidanceDraft.model_validate(draft_data))
        if response.next_question is None:
            return asked
        field = response.next_question.field_id
        asked.append(field)
        if field == "district":
            draft_data[field] = "天河区"
        elif field == "household_size":
            draft_data[field] = 3
        else:
            raise AssertionError(f"unexpected unanswered field: {field}")
    raise AssertionError("question loop did not terminate")


def test_false_asset_and_no_urgent_event_prune_resolved_branches() -> None:
    draft = {
        "urgent_event": False,
        "assets_eligible": False,
        "query_date": "2026-09-30",
    }
    asked = _answer_until_done(draft)
    assert set(asked) == {"district", "household_size"}
    response = next_guidance_question(GuidanceDraft.model_validate(draft))
    assert response.candidate_benefits == []


def test_zero_rigid_expense_prunes_only_rigid_expense_matter() -> None:
    draft = GuidanceDraft(
        district="天河区",
        household_size=3,
        urgent_event=False,
        rigid_expenses_12m=0,
    )
    response = next_guidance_question(draft)
    assert "刚性支出困难家庭认定" not in response.candidate_benefits
    assert "最低生活保障" in response.candidate_benefits


def test_dynamic_strategy_asks_decisive_guard_before_sensitive_income() -> None:
    first = next_guidance_question(GuidanceDraft())
    assert first.next_question is not None
    assert first.next_question.field_id == "district"
    second = next_guidance_question(GuidanceDraft(district="天河区"))
    assert second.next_question is not None
    assert second.next_question.field_id == "urgent_event"
