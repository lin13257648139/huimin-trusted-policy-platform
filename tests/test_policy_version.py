from datetime import date

from app.services.policy_version import select_policy_snapshot, temporary_policy_warning


def test_policy_switch_boundary() -> None:
    before = select_policy_snapshot(date(2026, 7, 31))
    after = select_policy_snapshot(date(2026, 8, 1))
    assert before.local_rule_available is True
    assert before.dibao_version == "穗民规字〔2023〕3号"
    assert before.snapshot_id == "gz-2026-07-31-v2023.06"
    assert after.local_rule_available is True
    assert after.dibao_version == "穗民规字〔2026〕3号"
    assert before.snapshot_id != after.snapshot_id


def test_query_before_verified_history_requires_review() -> None:
    before_history = select_policy_snapshot(date(2023, 5, 31))
    assert before_history.local_rule_available is False
    assert "未命中" in (before_history.warning or "")


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

