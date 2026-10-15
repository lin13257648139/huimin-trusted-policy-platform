import json
from pathlib import Path

from app.domain.models import HouseholdProfile

ROOT = Path(__file__).resolve().parents[1]


def test_household_profile_does_not_default_silence_to_no_event() -> None:
    profile = HouseholdProfile(household_size=1)
    assert profile.urgent_event is None


def test_json_schema_allows_explicit_unknown_urgent_event() -> None:
    schema = json.loads(
        (ROOT / "data" / "schemas" / "household_profile_schema.json").read_text(
            encoding="utf-8"
        )
    )
    exists = schema["properties"]["urgent_event"]["properties"]["exists"]
    assert exists["type"] == ["boolean", "null"]
    assert "不得" in exists["description"]
