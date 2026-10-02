from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_PATH = ROOT / "app" / "data" / "evidence.json"
OCR_AUDIT_PATH = ROOT / "data" / "evaluation" / "evidence_quote_audit.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode_unicode_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"\\u([0-9a-fA-F]{4})", replace, value).replace(r"\/", "/")


def _normalize(value: str) -> str:
    value = _decode_unicode_escapes(value)
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("（", "(").replace("）", ")")
    value = value.replace("％", "%").replace("：", ":").replace("；", ";")
    return re.sub(r"[\s\u3000/]+", "", value)


def verify_evidence_quotes() -> dict[str, object]:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    audit_payload = json.loads(OCR_AUDIT_PATH.read_text(encoding="utf-8"))
    ocr_records = {
        (item["source_id"], int(item["page"])): item
        for item in audit_payload.get("records", [])
    }
    results: list[dict[str, object]] = []
    for item in evidence:
        local_file = item.get("local_file")
        quote = item.get("verbatim_quote")
        method = item.get("verification_method")
        locator = item.get("locator")
        errors: list[str] = []
        path = (ROOT / local_file).resolve() if local_file else None
        if not path or not path.is_relative_to(ROOT) or not path.is_file():
            errors.append("本地原件不存在或路径越界")
        elif _sha256(path) != item.get("source_sha256"):
            errors.append("本地原件SHA-256不匹配")
        if not quote or item.get("excerpt") != quote:
            errors.append("excerpt必须与逐字引文一致")
        if not item.get("plain_language_explanation"):
            errors.append("缺少通俗解释")
        if not locator:
            errors.append("缺少条款或页码定位")
        if not item.get("quote_verified") or not item.get("reviewed_at"):
            errors.append("缺少核验状态或日期")
        if path and path.is_file() and quote:
            if method == "normalized_text_match":
                source_text = path.read_text(encoding="utf-8", errors="replace")
                if _normalize(quote) not in _normalize(source_text):
                    errors.append("逐字引文未在规范化官方HTML中命中")
            elif method == "ocr_text_match":
                page_match = re.search(r"第(\d+)页", str(locator))
                page = int(page_match.group(1)) if page_match else -1
                record = ocr_records.get((item["source_id"], page))
                if not record:
                    errors.append("缺少指定页OCR核验记录")
                else:
                    if record.get("source_sha256") != item.get("source_sha256"):
                        errors.append("OCR记录与原件指纹不一致")
                    if _normalize(quote) not in _normalize(str(record.get("text", ""))):
                        errors.append("逐字引文未在OCR复核文本中命中")
            elif method == "visual_pdf_review":
                if not path.suffix.lower() == ".pdf" or not re.search(r"第\d+页", str(locator)):
                    errors.append("PDF人工可视复核必须提供页码")
            else:
                errors.append("未知或缺失的核验方法")
        results.append(
            {
                "evidence_id": item.get("evidence_id"),
                "passed": not errors,
                "method": method,
                "errors": errors,
            }
        )
    failed = [item for item in results if not item["passed"]]
    return {
        "passed": not failed,
        "total": len(results),
        "verified": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }


def main() -> None:
    report = verify_evidence_quotes()
    if not report["passed"]:
        for item in report["results"]:
            if not item["passed"]:
                print(f"EVIDENCE_QUOTE_FAIL {item['evidence_id']}: {'；'.join(item['errors'])}")
        raise SystemExit(1)
    print(
        "EVIDENCE_QUOTES_OK "
        f"verified={report['verified']}/{report['total']} methods=html+ocr+visual_pdf"
    )


if __name__ == "__main__":
    main()
