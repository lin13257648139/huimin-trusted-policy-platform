import pytest
from pydantic import ValidationError

from app.domain.models import GuidanceDraft, HouseholdProfile, ParseProfileRequest


@pytest.mark.parametrize(
    "factory",
    [
        lambda: HouseholdProfile(household_size=1, city="广州市", district="不存在区"),
        lambda: GuidanceDraft(city="广州市", district="不存在区"),
        lambda: ParseProfileRequest(text="我们需要帮助", district="不存在区"),
    ],
)
def test_guangzhou_district_is_a_closed_enumeration(factory: object) -> None:
    with pytest.raises(ValidationError, match="广州市行政区"):
        factory()  # type: ignore[operator]


def test_out_of_scope_city_can_still_be_rejected_by_rule_engine() -> None:
    profile = HouseholdProfile(household_size=1, city="佛山市", district="禅城区")
    assert profile.city == "佛山市"


def test_profile_validation_rejects_contradictory_event_and_deduction() -> None:
    with pytest.raises(ValidationError, match="urgent_event必须为true"):
        HouseholdProfile(
            household_size=1,
            district="天河区",
            urgent_event=False,
            urgent_event_date="2026-10-01",
        )
    with pytest.raises(ValidationError, match="月扣减额异常"):
        HouseholdProfile(
            household_size=1,
            district="天河区",
            monthly_income_total=100,
            deductible_monthly_total=301,
        )


def test_profile_nullable_income_and_city_normalization() -> None:
    profile = HouseholdProfile(household_size=2, city="广州", district="天河区")
    assert profile.city == "广州市"
    assert profile.adjusted_monthly_income is None
    assert profile.per_capita_monthly_income is None


def test_guidance_skips_are_deduplicated_and_closed() -> None:
    draft = GuidanceDraft(skipped_fields=["district", "district"])
    assert draft.skipped_fields == ["district"]
    with pytest.raises(ValidationError, match="未知跳过字段"):
        GuidanceDraft(skipped_fields=["unsupported"])


def test_parse_profile_accepts_unspecified_and_valid_districts() -> None:
    assert ParseProfileRequest(text="需要申请救助", district=None).district is None
    assert ParseProfileRequest(text="需要申请救助", district="天河区").district == "天河区"
