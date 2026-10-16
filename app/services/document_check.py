from __future__ import annotations

import hashlib
import io
import math
import warnings as warning_control
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

from app.config import settings
from app.domain.models import BenefitId, MaterialType
from app.services.ocr import OCRAnalysis, analyze_image_text

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
MATERIAL_HINTS = {
    "身份证": "identity",
    "户口": "household_register",
    "收入": "income",
    "工资": "income",
    "医疗": "medical_expense",
    "诊断": "medical_diagnosis",
    "学费": "education_expense",
    "居住": "residence",
    "授权": "verification_authorization",
}

MATERIAL_LABELS = {
    "identity": "身份类证明",
    "household_register": "户口簿或家庭成员证明",
    "income": "收入情况材料",
    "medical_expense": "医疗支出凭据",
    "medical_diagnosis": "诊断材料",
    "education_expense": "教育支出凭据",
    "residence": "居住证明",
    "verification_authorization": "家庭经济状况核对授权书",
}

BENEFIT_REQUIRED_TYPES = {
    "B001": ("identity", "verification_authorization"),
    "B002": ("identity", "verification_authorization", "income"),
    "B003": ("identity", "verification_authorization", "income"),
    "B004": ("identity", "verification_authorization", "income"),
    "B005": ("identity",),
}


class DocumentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentCheck:
    file_name: str
    file_size: int
    sha256_prefix: str
    detected_type: str
    detection_source: str
    classification_evidence: list[str]
    quality_score: int
    checks: list[dict[str, Any]]
    warnings: list[str]
    privacy: dict[str, Any]
    ocr: dict[str, Any]

    @property
    def page_count(self) -> int:
        for check in self.checks:
            if check.get("code") == "pdf_pages":
                return int(check["value"])
        return 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "file_size": self.file_size,
            "sha256_prefix": self.sha256_prefix,
            "detected_type": self.detected_type,
            "detection_source": self.detection_source,
            "classification_evidence": self.classification_evidence,
            "quality_score": self.quality_score,
            "checks": self.checks,
            "warnings": self.warnings,
            "privacy": self.privacy,
            "ocr": self.ocr,
        }


def _detect_material(
    filename: str, declared: str | None, ocr: OCRAnalysis
) -> tuple[str, str, list[str]]:
    if declared and declared != "auto":
        return declared, "user_declared", []
    if ocr.detected_type != "unknown":
        return ocr.detected_type, "ocr_content", ocr.keyword_hits
    for hint, kind in MATERIAL_HINTS.items():
        if hint in filename:
            return kind, "filename_hint", [hint]
    return "unknown", "unknown", []


def _check_image(
    content: bytes, *, max_image_pixels: int
) -> tuple[int, list[dict[str, Any]], list[str]]:
    try:
        with warning_control.catch_warnings():
            warning_control.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(content))
            width, height = probe.size
            if width * height > max_image_pixels:
                raise DocumentValidationError(
                    f"图片像素总量超过安全上限（{max_image_pixels}像素）"
                )
            probe.verify()
            image = Image.open(io.BytesIO(content)).convert("L")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DocumentValidationError("图片尺寸异常，已停止解析") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise DocumentValidationError("图片无法解析或文件已损坏") from exc

    width, height = image.size
    stat = ImageStat.Stat(image)
    brightness = float(stat.mean[0])
    contrast = float(stat.stddev[0])
    edges = image.filter(ImageFilter.FIND_EDGES)
    edge_strength = float(ImageStat.Stat(edges).mean[0])

    resolution_ok = width >= 900 and height >= 600
    # 文档通常具有大面积白底，因此曝光上限比自然图像更宽；
    # 边缘均值能在不引入OpenCV的情况下区分清晰文本与强高斯模糊。
    brightness_ok = 20 <= brightness <= 245
    contrast_ok = contrast >= 20
    sharpness_ok = edge_strength >= 4

    checks = [
        {"code": "resolution", "passed": resolution_ok, "value": f"{width}×{height}", "label": "分辨率"},
        {"code": "brightness", "passed": brightness_ok, "value": round(brightness, 1), "label": "曝光"},
        {"code": "contrast", "passed": contrast_ok, "value": round(contrast, 1), "label": "对比度"},
        {"code": "sharpness", "passed": sharpness_ok, "value": round(edge_strength, 1), "label": "边缘清晰度"},
    ]
    score = int(sum(25 for item in checks if item["passed"]))
    warnings = []
    if not resolution_ok:
        warnings.append("分辨率较低，建议重新拍摄并铺满画面。")
    if not brightness_ok:
        warnings.append("图片可能过暗或过曝。")
    if not contrast_ok:
        warnings.append("文字与背景对比度偏低。")
    if not sharpness_ok:
        warnings.append("图片可能模糊，请保持镜头稳定并重新拍摄。")
    return score, checks, warnings


def _merge_page_ocr(pages: list[OCRAnalysis]) -> OCRAnalysis:
    enabled_pages = [item for item in pages if item.enabled]
    if not enabled_pages:
        warning = next((item.warning for item in pages if item.warning), "PDF逐页OCR未启用。")
        return OCRAnalysis(False, None, 0, None, "unknown", [], {}, None, warning)
    type_scores: Counter[str] = Counter()
    keyword_hits: list[str] = []
    fields: dict[str, list[str]] = {}
    score_sum = 0.0
    score_lines = 0
    page_hashes = []
    for item in enabled_pages:
        if item.detected_type != "unknown":
            type_scores[item.detected_type] += max(1, sum(len(v) for v in item.keyword_hits))
        keyword_hits.extend(item.keyword_hits)
        for key, values in item.extracted_fields.items():
            fields.setdefault(key, []).extend(values)
        if item.average_line_score is not None and item.line_count:
            score_sum += item.average_line_score * item.line_count
            score_lines += item.line_count
        if item.text_sha256_prefix:
            page_hashes.append(item.text_sha256_prefix)
    merged_fields = {
        key: list(dict.fromkeys(values))[:12] for key, values in fields.items()
    }
    detected_type = type_scores.most_common(1)[0][0] if type_scores else "unknown"
    digest = (
        hashlib.sha256("|".join(page_hashes).encode("ascii")).hexdigest()[:12]
        if page_hashes
        else None
    )
    return OCRAnalysis(
        True,
        "pypdfium2 + RapidOCR/ONNX Runtime",
        sum(item.line_count for item in enabled_pages),
        round(score_sum / score_lines, 4) if score_lines else None,
        detected_type,
        list(dict.fromkeys(keyword_hits)),
        merged_fields,
        digest,
        None if score_lines else "PDF各页均未识别到可靠文字，材料类型仍需人工确认。",
    )


def _check_pdf(
    content: bytes,
    *,
    max_image_pixels: int,
    max_pages: int,
    ocr_enabled: bool,
) -> tuple[int, list[dict[str, Any]], list[str], OCRAnalysis]:
    if not content.startswith(b"%PDF"):
        raise DocumentValidationError("文件扩展名为PDF，但内容不是有效PDF")
    document: Any | None = None
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(content)
        page_count = len(document)
        if page_count < 1:
            raise DocumentValidationError("PDF不包含可处理页面")
        if page_count > max_pages:
            raise DocumentValidationError(f"PDF页数超过安全上限（{max_pages}页）")
        page_analyses: list[OCRAnalysis] = []
        page_quality: list[int] = []
        for index in range(page_count):
            page = document[index]
            bitmap: Any | None = None
            try:
                width_points, height_points = page.get_size()
                page_area = width_points * height_points
                if not math.isfinite(page_area) or page_area <= 0:
                    raise DocumentValidationError("PDF页面尺寸无效")
                # PDFium renders at least one pixel per point at scale=1. Reject an
                # oversized MediaBox before allocating the bitmap; checking only the
                # rendered PIL image would be too late for a memory-exhaustion input.
                if page_area > max_image_pixels:
                    raise DocumentValidationError(
                        f"PDF页面像素总量超过安全上限（{max_image_pixels}）"
                    )
                scale = min(2.0, (max_image_pixels / page_area) ** 0.5)
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert("RGB")
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                rendered = buffer.getvalue()
                quality, _, _ = _check_image(rendered, max_image_pixels=max_image_pixels)
                page_quality.append(quality)
                page_analyses.append(analyze_image_text(rendered, enabled=ocr_enabled))
            finally:
                if bitmap is not None and hasattr(bitmap, "close"):
                    bitmap.close()
                page.close()
    except DocumentValidationError:
        raise
    except Exception as exc:
        raise DocumentValidationError(f"PDF无法安全解析：{type(exc).__name__}") from exc
    finally:
        if document is not None:
            document.close()
    eof_ok = b"%%EOF" in content[-2048:]
    checks = [
        {"code": "pdf_header", "passed": True, "value": "%PDF", "label": "PDF文件头"},
        {"code": "pdf_eof", "passed": eof_ok, "value": "found" if eof_ok else "missing", "label": "PDF完整性"},
        {"code": "pdf_pages", "passed": True, "value": page_count, "label": "PDF页数"},
        {
            "code": "pdf_page_quality",
            "passed": all(value >= 75 for value in page_quality),
            "value": round(sum(page_quality) / len(page_quality), 1),
            "label": "页面平均质量",
        },
    ]
    warnings = [] if eof_ok else ["PDF可能未完整写入，请重新导出。"]
    if any(value < 75 for value in page_quality):
        warnings.append("PDF中存在低质量页面，建议核对扫描清晰度。")
    return (
        min(100, round(sum(page_quality) / len(page_quality))) if eof_ok else 55,
        checks,
        warnings,
        _merge_page_ocr(page_analyses),
    )


def check_document(
    *,
    filename: str,
    content: bytes,
    declared_type: str | None,
    max_bytes: int,
    max_image_pixels: int = 40_000_000,
    ocr_enabled: bool | None = None,
) -> DocumentCheck:
    if declared_type not in {None, *(item.value for item in MaterialType)}:
        raise DocumentValidationError("材料类型不在允许枚举中")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentValidationError("仅支持JPG、PNG、WEBP和PDF文件")
    if not content:
        raise DocumentValidationError("文件内容为空")
    if len(content) > max_bytes:
        raise DocumentValidationError(f"文件超过{max_bytes // 1024 // 1024}MB限制")

    if suffix == ".pdf":
        score, checks, warnings, ocr = _check_pdf(
            content,
            max_image_pixels=max_image_pixels,
            max_pages=settings.max_pdf_pages,
            ocr_enabled=settings.ocr_enabled if ocr_enabled is None else ocr_enabled,
        )
    else:
        score, checks, warnings = _check_image(content, max_image_pixels=max_image_pixels)
        ocr = analyze_image_text(
            content,
            enabled=settings.ocr_enabled if ocr_enabled is None else ocr_enabled,
        )

    detected_type, detection_source, evidence = _detect_material(filename, declared_type, ocr)
    filename_type = next(
        (kind for hint, kind in MATERIAL_HINTS.items() if hint in filename), "unknown"
    )
    if ocr.warning:
        warnings.append(ocr.warning)
    if ocr.enabled and ocr.line_count:
        warnings.append("OCR仅用于内容分类与字段预检，识别文字和金额必须由人工对照原件。")
    if (
        ocr.detected_type != "unknown"
        and filename_type != "unknown"
        and ocr.detected_type != filename_type
    ):
        warnings.append("文件名提示与OCR内容分类不一致，请人工确认材料类型。")

    return DocumentCheck(
        file_name=Path(filename).name,
        file_size=len(content),
        sha256_prefix=hashlib.sha256(content).hexdigest()[:12],
        detected_type=detected_type,
        detection_source=detection_source,
        classification_evidence=evidence,
        quality_score=score,
        checks=checks,
        warnings=warnings,
        privacy={
            "stored": False,
            "message": "文件仅在内存中完成本次质量预检，未写入磁盘。",
        },
        ocr=ocr.as_dict(),
    )


def check_document_package(
    *, benefit_id: str, documents: list[DocumentCheck]
) -> dict[str, Any]:
    if benefit_id not in {item.value for item in BenefitId}:
        raise DocumentValidationError("事项编号不在允许枚举中")
    required = BENEFIT_REQUIRED_TYPES[benefit_id]
    detected = [item.detected_type for item in documents if item.detected_type != "unknown"]
    detected_set = set(detected)
    missing = [item for item in required if item not in detected_set]
    duplicates = sorted({item for item in detected if detected.count(item) > 1})
    hashes: dict[str, list[str]] = {}
    for document in documents:
        hashes.setdefault(document.sha256_prefix, []).append(document.file_name)
    exact_duplicates = [names for names in hashes.values() if len(names) > 1]
    low_quality = [item.file_name for item in documents if item.quality_score < 75]
    dates: dict[str, list[str]] = {}
    amounts: dict[str, list[str]] = {}
    for document in documents:
        extracted = document.ocr.get("extracted_fields") or {}
        for value in extracted.get("date_candidates", []):
            dates.setdefault(value, []).append(document.file_name)
        for value in extracted.get("amount_candidates", []):
            amounts.setdefault(value, []).append(document.file_name)
    consistency_flags = []
    if len(dates) > 1:
        consistency_flags.append(
            {
                "code": "multiple_dates",
                "severity": "review",
                "message": "材料包识别到多个日期候选，请人工核对是否属于同一申请事项。",
                "values": dates,
            }
        )
    if len(amounts) > 1:
        consistency_flags.append(
            {
                "code": "multiple_amounts",
                "severity": "review",
                "message": "材料包识别到多个金额候选，请人工核对合计口径和票据对应关系。",
                "values": amounts,
            }
        )
    return {
        "benefit_id": benefit_id,
        "files_checked": len(documents),
        "total_bytes": sum(item.file_size for item in documents),
        "total_pages": sum(item.page_count for item in documents),
        "documents": [item.as_dict() for item in documents],
        "required_materials": [MATERIAL_LABELS[item] for item in required],
        "detected_materials": [MATERIAL_LABELS.get(item, item) for item in sorted(detected_set)],
        "missing_recommended": [MATERIAL_LABELS[item] for item in missing],
        "duplicate_types": [MATERIAL_LABELS.get(item, item) for item in duplicates],
        "exact_duplicate_files": exact_duplicates,
        "low_quality_files": low_quality,
        "consistency_flags": consistency_flags,
        "ready_for_manual_review": not missing and not low_quality,
        "disclaimer": "这里只检查材料包是否便于提交前人工复核，不认定材料真实有效或必然齐全。",
    }

