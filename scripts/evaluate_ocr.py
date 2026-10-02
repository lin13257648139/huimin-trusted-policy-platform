from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.document_check import check_document  # noqa: E402
from app.services.ocr import ocr_runtime_available  # noqa: E402


def evaluate(directory: Path) -> dict[str, object]:
    if not ocr_runtime_available():
        raise SystemExit("OCR运行依赖未安装，不能生成OCR指标。")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    by_variant: dict[str, Counter[str]] = defaultdict(Counter)
    classification_correct = 0
    date_correct = 0
    date_total = 0
    amount_correct = 0
    amount_total = 0
    elapsed = []
    details = []
    for item in manifest:
        start = time.perf_counter()
        result = check_document(
            filename=item["file"],
            content=(directory / item["file"]).read_bytes(),
            declared_type="auto",
            max_bytes=8 * 1024 * 1024,
            ocr_enabled=True,
        )
        elapsed.append(time.perf_counter() - start)
        class_match = result.detected_type == item["material_type"]
        classification_correct += int(class_match)
        dates = result.ocr["extracted_fields"].get("date_candidates", [])
        amounts = result.ocr["extracted_fields"].get("amount_candidates", [])
        date_match = item["expected_date"] in dates
        date_total += 1
        date_correct += int(date_match)
        amount_match = None
        if item["expected_amount"]:
            amount_total += 1
            amount_match = item["expected_amount"] in amounts
            amount_correct += int(amount_match)
        by_variant[item["variant"]]["total"] += 1
        by_variant[item["variant"]]["classification_correct"] += int(class_match)
        details.append(
            {
                "case_id": item["case_id"],
                "variant": item["variant"],
                "expected_type": item["material_type"],
                "predicted_type": result.detected_type,
                "classification_match": class_match,
                "date_match": date_match,
                "amount_match": amount_match,
                "quality_score": result.quality_score,
                "ocr_line_count": result.ocr["line_count"],
            }
        )
    total = len(manifest)
    return {
        "benchmark_role": "synthetic_ocr_robustness_benchmark",
        "case_count": total,
        "classification_accuracy": round(classification_correct / total, 4),
        "date_candidate_recall": round(date_correct / date_total, 4),
        "amount_candidate_recall": round(amount_correct / amount_total, 4),
        "mean_seconds_per_image": round(statistics.mean(elapsed), 4),
        "by_variant": {
            name: {
                "cases": counts["total"],
                "classification_accuracy": round(
                    counts["classification_correct"] / counts["total"], 4
                ),
            }
            for name, counts in sorted(by_variant.items())
        },
        "details": details,
        "warning": "全部图片为程序生成的无真实信息材料；正式国赛必须增加独立模板和人工标注图片，不能把该结果写成真实材料准确率。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评测合成材料OCR内容分类与字段候选召回。")
    parser.add_argument(
        "--directory",
        type=Path,
        default=ROOT / "data" / "evaluation" / "ocr_synthetic",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.directory)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
