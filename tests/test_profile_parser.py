from datetime import date

from app.domain.models import ParseProfileRequest
from app.services.profile_parser import parse_profile


def test_chinese_narrative_extracts_only_explicit_facts() -> None:
    result = parse_profile(
        ParseProfileRequest(
            text="广州天河区三口之家，家庭月收入3200元，住院医疗花费3万元，基本生活困难。",
            query_date=date(2026, 9, 29),
        )
    )
    assert result.fields["district"] == "天河区"
    assert result.fields["household_size"] == 3
    assert result.fields["monthly_income_total"] == "3200.00"
    assert result.fields["medical_expenses_12m"] == "30000.00"
    assert "assets_eligible" in result.missing_fields


def test_parser_does_not_invent_income() -> None:
    result = parse_profile(
        ParseProfileRequest(text="我们住在番禺区，最近遇到困难。", query_date=date(2026, 9, 29))
    )
    assert result.fields["district"] == "番禺区"
    assert "monthly_income_total" not in result.fields

