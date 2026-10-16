import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.services.document_check import (
    DocumentValidationError,
    check_document,
    check_document_package,
)
from app.services.ocr import classify_ocr_text, ocr_runtime_available

ROOT = Path(__file__).resolve().parents[1]


def make_image() -> bytes:
    image = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(image)
    for row in range(20):
        draw.text((80, 60 + row * 30), f"DEMO DOCUMENT LINE {row}", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_is_not_persisted_to_business_storage() -> None:
    result = check_document(
        filename="医疗支出凭据.png",
        content=make_image(),
        declared_type="auto",
        max_bytes=8 * 1024 * 1024,
        ocr_enabled=False,
    )
    assert result.detected_type == "medical_expense"
    assert result.privacy["stored"] is False
    assert result.privacy["business_storage"] is False
    assert result.privacy["transient_upload_handling"] == "multipart_spooled_temporary_file"
    assert "未写入磁盘" not in result.privacy["message"]
    assert len(result.checks) == 4


def test_blur_reduces_quality_score() -> None:
    clear = make_image()
    image = Image.open(io.BytesIO(clear)).filter(ImageFilter.GaussianBlur(radius=7))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    clear_result = check_document(
        filename="清晰.png",
        content=clear,
        declared_type="auto",
        max_bytes=8 * 1024 * 1024,
        ocr_enabled=False,
    )
    blurred_result = check_document(
        filename="模糊.png",
        content=buffer.getvalue(),
        declared_type="auto",
        max_bytes=8 * 1024 * 1024,
        ocr_enabled=False,
    )
    assert clear_result.quality_score > blurred_result.quality_score


def test_fake_pdf_is_rejected() -> None:
    with pytest.raises(DocumentValidationError):
        check_document(
            filename="材料.pdf",
            content=b"not-a-pdf",
            declared_type="auto",
            max_bytes=8 * 1024 * 1024,
            ocr_enabled=False,
        )


def test_pdf_is_rendered_page_by_page_without_persisting_text() -> None:
    image = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 80), "DEMO PDF DOCUMENT 2026-09-15 3000.00", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    result = check_document(
        filename="合成材料.pdf",
        content=buffer.getvalue(),
        declared_type="auto",
        max_bytes=8 * 1024 * 1024,
        ocr_enabled=False,
    )
    page_check = next(item for item in result.checks if item["code"] == "pdf_pages")
    assert page_check["value"] == 1
    assert result.privacy["stored"] is False
    assert "text" not in result.ocr


def test_oversized_pdf_page_is_rejected_before_bitmap_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"page_closed": False, "document_closed": False}

    class FakePage:
        def get_size(self) -> tuple[float, float]:
            return (100_000.0, 100_000.0)

        def render(self, *, scale: float) -> None:
            raise AssertionError(f"oversized page must not render at scale {scale}")

        def close(self) -> None:
            state["page_closed"] = True

    class FakeDocument:
        def __init__(self, _content: bytes) -> None:
            self.page = FakePage()

        def __len__(self) -> int:
            return 1

        def __getitem__(self, _index: int) -> FakePage:
            return self.page

        def close(self) -> None:
            state["document_closed"] = True

    monkeypatch.setitem(
        sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=FakeDocument)
    )
    with pytest.raises(DocumentValidationError, match="像素总量超过安全上限"):
        check_document(
            filename="恶意超大页面.pdf",
            content=b"%PDF-fake\n%%EOF",
            declared_type="auto",
            max_bytes=1024,
            max_image_pixels=40_000_000,
            ocr_enabled=False,
        )
    assert state == {"page_closed": True, "document_closed": True}


def test_disallowed_extension_is_rejected() -> None:
    with pytest.raises(DocumentValidationError):
        check_document(
            filename="script.exe",
            content=b"MZ",
            declared_type="auto",
            max_bytes=8 * 1024 * 1024,
            ocr_enabled=False,
        )


def test_unknown_declared_material_type_is_rejected() -> None:
    with pytest.raises(DocumentValidationError, match="材料类型"):
        check_document(
            filename="材料.png",
            content=b"not-needed",
            declared_type="arbitrary_type",
            max_bytes=1024,
            ocr_enabled=False,
        )


def test_unknown_package_benefit_id_is_rejected() -> None:
    with pytest.raises(DocumentValidationError, match="事项编号"):
        check_document_package(benefit_id="B999", documents=[])


def test_ocr_text_classification_uses_content_keywords() -> None:
    material_type, keywords = classify_ocr_text("医疗收费票据 费用合计 30000.00元")
    assert material_type == "medical_expense"
    assert "费用合计" in keywords


@pytest.mark.skipif(not ocr_runtime_available(), reason="OCR optional runtime is not installed")
def test_installed_ocr_classifies_renamed_demo_by_content() -> None:
    content = (ROOT / "demo_assets" / "合成_医疗支出凭据_清晰.png").read_bytes()
    result = check_document(
        filename="完全无提示的文件.png",
        content=content,
        declared_type="auto",
        max_bytes=8 * 1024 * 1024,
        ocr_enabled=True,
    )
    assert result.detected_type == "medical_expense"
    assert result.detection_source == "ocr_content"
    assert result.ocr["enabled"] is True
    assert result.ocr["line_count"] >= 5
    assert "医疗支出凭据" in result.classification_evidence
    assert result.ocr["extracted_fields"]["amount_candidates"]
    assert "2026-09-15" in result.ocr["extracted_fields"]["date_candidates"]
    assert "text" not in result.ocr

