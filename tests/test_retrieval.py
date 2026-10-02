from app.services.retrieval import search_evidence
from app.services.retrieval import search_evidence_result


def test_multi_term_query_filters_single_common_word_noise() -> None:
    results = search_evidence("临时救助", limit=10)
    assert results
    assert all(item["match_coverage"] >= 0.5 for item in results)
    assert results[0]["evidence"]["source_id"] == "GZ-005"
    assert all("隐私" not in item["evidence"]["excerpt"] for item in results)


def test_evidence_separates_verbatim_quote_from_explanation() -> None:
    results = search_evidence("最低生活保障家庭收入财产", limit=5)
    assert results
    for item in results:
        evidence = item["evidence"]
        assert evidence["verbatim_quote"]
        assert evidence["plain_language_explanation"]
        assert evidence["locator"]
        assert evidence["source_sha256"]


def test_short_policy_term_still_returns_evidence() -> None:
    results = search_evidence("低保", limit=5)
    assert results


def test_natural_language_material_question_is_not_filtered_out() -> None:
    results = search_evidence("申请低保一般要准备什么材料", limit=3)
    assert results
    assert results[0]["evidence"]["evidence_id"] == "E-GZ-001-MATERIALS"


def test_natural_language_deadline_question_ranks_deadline_first() -> None:
    results = search_evidence("低保办理通常需要多少个工作日", limit=3)
    assert results[0]["evidence"]["evidence_id"] == "E-GZ-001-DEADLINE"
    assert any(item["evidence"]["source_id"].startswith("GZ-") for item in results)


def test_temporal_retrieval_switches_old_and_new_policy() -> None:
    historical = search_evidence_result("最低生活保障辅助指标", as_of=__import__("datetime").date(2026, 7, 31), limit=10)
    current = search_evidence_result("最低生活保障辅助指标", as_of=__import__("datetime").date(2026, 9, 30), limit=10)
    historical_ids = {item["evidence"]["evidence_id"] for item in historical["items"]}
    current_ids = {item["evidence"]["evidence_id"] for item in current["items"]}
    assert "E-GZ-009-ASSET" in historical_ids
    assert "E-GZ-009-ASSET" not in current_ids
    assert historical["temporal_filter"]["enabled"] is True


def test_out_of_scope_query_returns_explicit_no_answer() -> None:
    result = search_evidence_result("量子计算卫星轨道参数", limit=5)
    assert result["items"] == []
    assert result["answerability"]["supported"] is False
    assert result["answerability"]["reason"]
