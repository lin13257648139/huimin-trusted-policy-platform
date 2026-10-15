from datetime import date

from app.services.policy_version import select_policy_snapshot, temporary_policy_warning
from app.services.rule_registry import get_rule_for_date


def test_policy_switch_boundary() -> None:
    before = select_policy_snapshot(date(2026, 7, 31))
    after = select_policy_snapshot(date(2026, 8, 1))
    assert before.local_rule_available is True
    assert before.dibao_version == "穗民规字〔2023〕3号"
    assert before.snapshot_id == "gz-2026-07-31-v2026.01"
    assert after.local_rule_available is True
    assert after.dibao_version == "穗民规字〔2026〕3号"
    assert before.snapshot_id != after.snapshot_id


def test_query_before_verified_history_requires_review() -> None:
    before_history = select_policy_snapshot(date(2023, 5, 31))
    assert before_history.local_rule_available is False
    assert "未命中" in (before_history.warning or "")


def test_2023_to_2025_history_never_reuses_2026_amount() -> None:
    historical = get_rule_for_date("B002", date(2025, 12, 31))
    assert historical is not None
    assert historical.version == "v2023.06"
    assert historical.manual_review_required is True
    assert "income_standard_monthly_per_capita" not in historical.parameters

    snapshot = select_policy_snapshot(date(2025, 12, 31))
    assert snapshot.local_rule_available is False
    assert "不会套用2026年标准" in (snapshot.warning or "")


def test_2026_amount_has_its_own_effective_window() -> None:
    transition = get_rule_for_date("B002", date(2026, 1, 1))
    assert transition is not None
    assert transition.version == "v2026.01"
    assert transition.parameters["income_standard_monthly_per_capita"] == 1327
    assert transition.manual_review_required is False


def test_future_policy_requires_review() -> None:
    future = select_policy_snapshot(date(2027, 8, 1))
    assert future.local_rule_available is False
    assert "超出" in (future.warning or "")


def test_temporary_policy_expiry_guard() -> None:
    assert temporary_policy_warning(date(2026, 10, 1)) is None
    assert temporary_policy_warning(date(2029, 11, 5)) is None
    assert "30天" in (temporary_policy_warning(date(2029, 11, 6)) or "")
    assert "30天" in (temporary_policy_warning(date(2029, 12, 6)) or "")
    assert "不能自动判断" in (temporary_policy_warning(date(2029, 12, 7)) or "")

