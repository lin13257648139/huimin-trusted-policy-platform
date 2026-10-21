from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, settings
from app.services.ai_runtime import ollama_runtime_status
from app.services.catalog import load_evidence, load_offices, load_policy_sources
from app.services.intent_classifier import get_intent_classifier
from app.services.ocr import ocr_runtime_available


def _check(
    identifier: str,
    label: str,
    passed: bool,
    detail: str,
    *,
    critical: bool = True,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "label": label,
        "status": "pass" if passed else ("fail" if critical else "warn"),
        "critical": critical,
        "detail": detail,
    }


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as stream:
        return sum(1 for line in stream if line.strip())


def _release_binding_status() -> tuple[bool, str]:
    """Verify that the displayed evidence manifest matches the current source tree."""

    manifest_path = BASE_DIR / "data" / "evaluation" / "release_manifest.json"
    if not manifest_path.is_file():
        return False, "源码绑定清单缺失"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        from scripts.build_release_manifest import source_fingerprint

        current_digest, current_files = source_fingerprint()
        bound_digest = manifest.get("source_tree_sha256")
        source_binding = manifest.get("source_binding") or {}
        clean_when_bound = source_binding.get("source_inputs_dirty") is False
        matches = bound_digest == current_digest and clean_when_bound
        if matches:
            return True, f"源码指纹 {current_digest[:12]} 已绑定 {len(current_files)} 个输入文件"
        state = "生成时源码未冻结" if not clean_when_bound else "当前源码已变化"
        return (
            False,
            f"{state}：清单 {str(bound_digest)[:12] or '缺失'}，当前 {current_digest[:12]}；请重跑评测并生成清单",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False, "源码绑定清单无法解析或无法计算当前源码指纹"


def build_readiness_report() -> dict[str, Any]:
    """Return a reproducible, non-sensitive deployment readiness snapshot.

    The report verifies files and loaded records that the running application
    actually uses.  It deliberately avoids outcome/accuracy claims.
    """

    sources = load_policy_sources()
    evidence = load_evidence()
    offices = load_offices()
    registry_path = settings.rule_registry_path
    registry_bytes = registry_path.read_bytes() if registry_path.is_file() else b""
    try:
        registry = json.loads(registry_bytes.decode("utf-8")) if registry_bytes else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        registry = {}
    rules = registry.get("rules") if isinstance(registry, dict) else None
    rule_count = len(rules) if isinstance(rules, list) else 0

    synthetic_path = BASE_DIR / "data" / "processed" / "synthetic_conformance_cases.jsonl"
    synthetic_count = _line_count(synthetic_path)
    evaluation_paths = [
        BASE_DIR / "data" / "evaluation" / "retrieval_report.json",
        BASE_DIR / "data" / "evaluation" / "policy_qa_report.json",
        BASE_DIR / "data" / "evaluation" / "policy_qa_live_report.json",
        BASE_DIR / "data" / "evaluation" / "policy_compiler_report.json",
        BASE_DIR / "data" / "evaluation" / "policy_compiler_real_report.json",
        BASE_DIR / "data" / "evaluation" / "ai_pipeline_report.json",
        BASE_DIR / "data" / "evaluation" / "evidence_quote_audit.json",
        BASE_DIR / "data" / "evaluation" / "active_question_report.json",
        BASE_DIR / "data" / "evaluation" / "active_question_traces.jsonl",
        BASE_DIR / "data" / "evaluation" / "ablation_report.json",
        BASE_DIR / "data" / "evaluation" / "http_concurrency_report.json",
        BASE_DIR / "data" / "evaluation" / "ai_workload_pressure_report.json",
        BASE_DIR / "data" / "evaluation" / "software_bill_of_materials.json",
        BASE_DIR / "data" / "evaluation" / "dataset_governance_manifest.json",
        BASE_DIR / "data" / "evaluation" / "stage2_split_manifest.json",
        BASE_DIR / "data" / "evaluation" / "high_risk_safety_report.json",
        BASE_DIR / "data" / "evaluation" / "dependency_vulnerability_report.json",
        BASE_DIR / "data" / "evaluation" / "release_manifest.json",
        BASE_DIR / "data" / "evaluation" / "pytest_junit.xml",
        BASE_DIR / "data" / "evaluation" / "browser_e2e_report.json",
    ]
    evaluation_count = sum(path.is_file() and path.stat().st_size > 0 for path in evaluation_paths)
    release_binding_ok, release_binding_detail = _release_binding_status()
    ocr_available = settings.ocr_enabled and ocr_runtime_available()
    provenance_path = BASE_DIR / "data" / "raw_official" / "provenance_manifest.json"
    provenance_ok = False
    provenance_detail = "来源指纹清单缺失"
    if provenance_path.is_file():
        try:
            manifest = json.loads(provenance_path.read_text(encoding="utf-8"))
            catalog_path = BASE_DIR / "data" / "processed" / "policy_source_catalog.csv"
            with catalog_path.open("r", encoding="utf-8-sig", newline="") as handle:
                catalog_rows = list(csv.DictReader(handle))
            manifest_rows = {
                item["source_id"]: item
                for item in manifest.get("sources", [])
                if isinstance(item, dict)
            }
            p0_ids = {row["source_id"] for row in catalog_rows if row["priority"] == "P0"}
            verified_p0 = {
                source_id for source_id in p0_ids if manifest_rows.get(source_id, {}).get("sha256")
            }
            catalog_digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
            invalid_files = []
            for source_id, item in manifest_rows.items():
                local_file = item.get("local_file")
                if not local_file:
                    continue
                local_path = (BASE_DIR / local_file).resolve()
                if (
                    not local_path.is_relative_to(BASE_DIR)
                    or not local_path.is_file()
                    or hashlib.sha256(local_path.read_bytes()).hexdigest() != item.get("sha256")
                ):
                    invalid_files.append(source_id)
            provenance_ok = (
                manifest.get("catalog_sha256") == catalog_digest
                and verified_p0 == p0_ids
                and len(manifest_rows) == len(catalog_rows)
                and not invalid_files
            )
            provenance_detail = (
                f"{len(manifest_rows)}份来源已登记，P0原件指纹 {len(verified_p0)}/{len(p0_ids)}，"
                f"失配 {len(invalid_files)}"
            )
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            provenance_detail = "来源指纹清单无法解析或与目录不一致"
    ai_status = ollama_runtime_status()
    intent_model = get_intent_classifier().model_version
    quote_complete = [
        item
        for item in evidence.values()
        if item.quote_verified
        and item.verbatim_quote
        and item.excerpt == item.verbatim_quote
        and item.plain_language_explanation
        and item.locator
        and item.local_file
        and item.source_sha256
        and item.verification_method
        and item.reviewed_at
    ]

    checks = [
        _check(
            "source_provenance",
            "政策原件与指纹",
            provenance_ok,
            provenance_detail,
        ),
        _check(
            "policy_catalog",
            "官方政策目录",
            len(sources) >= 10,
            f"已加载 {len(sources)} 份来源",
        ),
        _check(
            "evidence_fragments",
            "政策证据片段",
            len(evidence) >= 10,
            f"已加载 {len(evidence)} 条可检索证据",
        ),
        _check(
            "evidence_quote_integrity",
            "逐字引文与解释分离",
            len(quote_complete) == len(evidence) and len(evidence) >= 10,
            f"{len(quote_complete)}/{len(evidence)} 条证据具备原文、解释、定位、原件指纹和复核记录",
        ),
        _check(
            "office_directory",
            "属地服务窗口",
            len(offices) >= 12,
            f"已加载 {len(offices)} 条市区窗口记录",
        ),
        _check(
            "rule_registry",
            "时态规则登记表",
            rule_count >= 6 and bool(registry_bytes),
            (
                f"登记 {rule_count} 个规则版本，指纹 "
                f"{hashlib.sha256(registry_bytes).hexdigest()[:12] if registry_bytes else '缺失'}"
            ),
        ),
        _check(
            "synthetic_regression",
            "合成边界回归集",
            synthetic_count >= 200,
            f"检测到 {synthetic_count} 个可复现实验案例",
        ),
        _check(
            "evaluation_artifacts",
            "离线评测产物",
            evaluation_count == len(evaluation_paths),
            f"{evaluation_count}/{len(evaluation_paths)} 份关键评测产物可用",
            critical=False,
        ),
        _check(
            "release_evidence_binding",
            "评测与源码绑定",
            release_binding_ok,
            release_binding_detail,
            critical=True,
        ),
        _check(
            "local_ocr",
            "本地OCR运行时",
            ocr_available,
            "RapidOCR/ONNX Runtime可用" if ocr_available else "OCR关闭或运行依赖不可用，可安全降级",
            critical=False,
        ),
        _check(
            "intent_classifier",
            "本地意图分类模型",
            bool(intent_model),
            f"{intent_model}已加载；仅用于事项排序",
            critical=False,
        ),
        _check(
            "local_language_model",
            "本地语言模型",
            bool(ai_status["reachable"] and ai_status.get("model_present")),
            (
                f"{ai_status.get('chat_model')}可用"
                if ai_status["reachable"] and ai_status.get("model_present")
                else f"安全降级：{ai_status['reason']}"
            ),
            critical=False,
        ),
        _check(
            "admin_access",
            "治理接口访问控制",
            bool(settings.admin_api_token) or settings.demo_mode,
            (
                "鉴权模式：已配置管理员令牌"
                if not settings.demo_mode
                else "显式演示模式：治理接口免令牌；生产环境禁止此模式"
            ),
            critical=True,
        ),
    ]
    failed = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "status": "blocked" if failed else ("ready_with_warnings" if warnings else "ready"),
        "ready": not failed,
        "checked_at": datetime.now(UTC).isoformat(),
        "policy_as_of": settings.policy_as_of,
        "app_version": settings.app_version,
        "summary": {
            "passed": sum(item["status"] == "pass" for item in checks),
            "warnings": len(warnings),
            "failed": len(failed),
            "total": len(checks),
        },
        "checks": checks,
        "claim_boundary": "就绪度只证明运行依赖和数据资产可用，不代表真实业务准确率。",
    }
