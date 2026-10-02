from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from PIL import Image


OCR_MATERIAL_HINTS = {
    "identity": ("居民身份证", "公民身份号码", "身份证"),
    "household_register": ("居民户口簿", "常住人口登记", "户口簿", "户主"),
    "income": ("收入证明", "工资收入", "薪资", "工资"),
    "medical_expense": ("医疗支出凭据", "医疗收费", "费用合计", "医保结算", "住院费用"),
    "medical_diagnosis": ("诊断证明", "疾病诊断", "出院诊断", "临床诊断"),
    "education_expense": ("教育收费", "学费", "学校缴费", "教育支出"),
    "residence": ("广东省居住证", "居住证", "连续居住", "居住地址"),
    "verification_authorization": ("家庭经济状况核对授权", "核对授权书", "经济状况核对"),
}


@dataclass(frozen=True)
class OCRAnalysis:
    enabled: bool
    provider: str | None
    line_count: int
    average_line_score: float | None
    detected_type: str
    keyword_hits: list[str]
    extracted_fields: dict[str, list[str]]
    text_sha256_prefix: str | None
    warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "line_count": self.line_count,
            "average_line_score": self.average_line_score,
            "detected_type": self.detected_type,
            "keyword_hits": self.keyword_hits,
            "extracted_fields": self.extracted_fields,
            "text_sha256_prefix": self.text_sha256_prefix,
            "warning": self.warning,
            "privacy_note": "仅返回材料类型、命中词和非身份字段；完整OCR文本不保存、不返回。",
        }


def ocr_runtime_available() -> bool:
    return bool(importlib.util.find_spec("rapidocr") and importlib.util.find_spec("onnxruntime"))


@lru_cache(maxsize=1)
def _engine():
    from rapidocr import RapidOCR

    return RapidOCR()


_OCR_LOCK = threading.Lock()


def classify_ocr_text(text: str) -> tuple[str, list[str]]:
    scores: list[tuple[int, str, list[str]]] = []
    compact = re.sub(r"\s+", "", text)
    for material_type, keywords in OCR_MATERIAL_HINTS.items():
        hits = [keyword for keyword in keywords if keyword in compact]
        scores.append((sum(len(keyword) for keyword in hits), material_type, hits))
    score, material_type, hits = max(scores, default=(0, "unknown", []))
    return (material_type, hits) if score else ("unknown", [])


def _safe_fields(text: str) -> dict[str, list[str]]:
    dates = []
    for pattern in (
        r"(?:19|20)\d{2}[-/.年](?:1[0-2]|0?[1-9])[-/.月](?:3[01]|[12]\d|0?[1-9])日?",
        r"(?:19|20)\d{6}",
    ):
        dates.extend(re.findall(pattern, text))
    amounts = re.findall(r"(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s*元", text)
    return {
        "date_candidates": list(dict.fromkeys(dates))[:6],
        "amount_candidates": list(dict.fromkeys(value.replace(" ", "") for value in amounts))[:6],
    }


def analyze_image_text(content: bytes, *, enabled: bool) -> OCRAnalysis:
    if not enabled:
        return OCRAnalysis(False, None, 0, None, "unknown", [], {}, None, "OCR已由配置关闭。")
    if not ocr_runtime_available():
        return OCRAnalysis(
            False,
            None,
            0,
            None,
            "unknown",
            [],
            {},
            None,
            "未安装RapidOCR与ONNX Runtime，已降级为文件名分类。",
        )
    try:
        import numpy as np

        with Image.open(io.BytesIO(content)) as source:
            image = np.asarray(source.convert("RGB"))
        with _OCR_LOCK:
            output = _engine()(image)
        texts = [str(value).strip() for value in (output.txts or ()) if str(value).strip()]
        scores = [float(value) for value in (output.scores or ())]
        joined = "\n".join(texts)
        detected_type, keyword_hits = classify_ocr_text(joined)
        average = round(sum(scores) / len(scores), 4) if scores else None
        return OCRAnalysis(
            True,
            "RapidOCR/ONNX Runtime",
            len(texts),
            average,
            detected_type,
            keyword_hits,
            _safe_fields(joined),
            hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12] if joined else None,
            None if texts else "未识别到可靠文字，材料类型仍需人工确认。",
        )
    except Exception as exc:  # OCR失败不应中断导办主流程
        return OCRAnalysis(
            False,
            "RapidOCR/ONNX Runtime",
            0,
            None,
            "unknown",
            [],
            {},
            None,
            f"OCR处理失败，已安全降级：{type(exc).__name__}",
        )
