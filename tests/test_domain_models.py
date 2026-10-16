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
