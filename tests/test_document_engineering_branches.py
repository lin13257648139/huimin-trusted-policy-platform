from __future__ import annotations

from app.services.document_check import (
    DocumentCheck,
    DocumentValidationError,
    _detect_material,
    _merge_page_ocr,
    check_document,
    check_document_package,
)
from app.services.ocr import OCRAnalysis


def _ocr(
    *,
    enabled: bool = True,
    detected_type: str = "unknown",
    score: float | None = None,
    line_count: int = 0,
    digest: str | None = None,
    fields: dict[str, list[str]] | None = None,
    warning: str | None = None,
) -> OCRAnalysis:
    return OCRAnalysis(
        enabled,
        "test" if enabled else None,
        line_count,
        score,
        detected_type,
        ["收入证明"] if detected_type != "unknown" else [],
        fields or {},
        digest,
        warning,
    )


def _document(
    name: str,
    material: str,
    digest: str,
    *,
    score: int = 100,
    fields: dict[str, list[str]] | None = None,
    pages: int | None = None,
) -> DocumentCheck:
    checks = [] if pages is None else [{"code": "pdf_pages", "value": pages}]
    return DocumentCheck(
        file_name=name,
        file_size=10,
        sha256_prefix=digest,
        detected_type=material,
        detection_source="test",
        classification_evidence=[],
        quality_score=score,
        checks=checks,
        warnings=[],
        privacy={},
        ocr={"extracted_fields": fields or {}},
    )


def test_material_detection_priority_and_page_count() -> None:
    assert _detect_material("x.png", "income", _ocr())[:2] == (
        "income",
        "user_declared",
    )
    assert _detect_material("x.png", None, _ocr(detected_type="income"))[:2] == (
        "income",
        "ocr_content",
    )
    assert _detect_material("收入证明.png", None, _ocr())[:2] == (
        "income",
        "filename_hint",
    )
    assert _detect_material("x.png", None, _ocr())[:2] == ("unknown", "unknown")
    assert _document("x.pdf", "income", "a", pages=3).page_count == 3
    assert _document("x.png", "income", "a").page_count == 1


def test_pdf_ocr_merge_handles_disabled_scored_and_empty_pages() -> None:
    disabled = _merge_page_ocr([_ocr(enabled=False, warning="disabled")])
    assert disabled.enabled is False
    assert disabled.warning == "disabled"
    merged = _merge_page_ocr(
        [
            _ocr(
                detected_type="income",
                score=0.9,
                line_count=2,
                digest="abc",
                fields={"date_candidates": ["2026-01-01"]},
            ),
            _ocr(enabled=True),
        ]
    )
    assert merged.detected_type == "income"
    assert merged.average_line_score == 0.9
    assert merged.text_sha256_prefix is not None
    empty = _merge_page_ocr([_ocr(enabled=True)])
    assert empty.detected_type == "unknown"
    assert empty.warning is not None


def test_document_input_guards_reject_bad_enums_extensions_and_sizes() -> None:
    cases = [
        {"filename": "x.png", "content": b"x", "declared_type": "bad", "max_bytes": 10},
        {"filename": "x.exe", "content": b"x", "declared_type": None, "max_bytes": 10},
        {"filename": "x.png", "content": b"", "declared_type": None, "max_bytes": 10},
        {"filename": "x.png", "content": b"xx", "declared_type": None, "max_bytes": 1},
    ]
    for values in cases:
        try:
            check_document(**values)
        except DocumentValidationError:
            pass
        else:
            raise AssertionError("invalid document must be rejected")


def test_package_reports_duplicates_quality_and_cross_document_inconsistency() -> None:
    first = _document(
        "a.png",
        "income",
        "same",
        score=50,
        fields={"date_candidates": ["2026-01-01"], "amount_candidates": ["100元"]},
    )
    second = _document(
        "b.png",
        "income",
        "same",
        fields={"date_candidates": ["2026-02-01"], "amount_candidates": ["200元"]},
    )
    report = check_document_package(benefit_id="B002", documents=[first, second])
    assert report["duplicate_types"] == ["收入情况材料"]
    assert report["exact_duplicate_files"] == [["a.png", "b.png"]]
    assert report["low_quality_files"] == ["a.png"]
    assert {item["code"] for item in report["consistency_flags"]} == {
        "multiple_dates",
        "multiple_amounts",
    }
    try:
        check_document_package(benefit_id="UNKNOWN", documents=[])
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("unknown benefit must be rejected")
