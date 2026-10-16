from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.version import APP_VERSION
from scripts.build_release_manifest import source_fingerprint
from scripts.verify_evidence_quotes import verify_evidence_quotes


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fail(message: str) -> None:
    raise SystemExit(f"PROJECT_CHECK_FAILED: {message}")


def main() -> None:
    expected = [
        ROOT / "data" / "processed" / "policy_source_catalog.csv",
        ROOT / "data" / "processed" / "benefit_catalog_seed.csv",
        ROOT / "data" / "processed" / "office_directory_seed.csv",
        ROOT / "data" / "schemas" / "household_profile_schema.json",
        ROOT / "data" / "schemas" / "policy_rule_schema.json",
        ROOT / "data" / "raw_official" / "provenance_manifest.json",
        ROOT / "app" / "data" / "evidence.json",
        ROOT / "app" / "static" / "manifest.webmanifest",
        ROOT / "app" / "static" / "sw.js",
        ROOT / "app" / "services" / "readiness.py",
        ROOT / "data" / "evaluation" / "evidence_quote_audit.json",
        ROOT / "data" / "evaluation" / "dependency_vulnerability_report.json",
        ROOT / "requirements.lock",
        ROOT / ".env.example",
        ROOT / "data" / "processed" / "living_assessment_registry.json",
        ROOT / "data" / "processed" / "benefit_relation_registry.json",
        ROOT / "data" / "evaluation" / "release_manifest.json",
        ROOT / "data" / "processed" / "policy_evidence_inventory.json",
        ROOT / "data" / "evaluation" / "stage2_split_manifest.json",
        ROOT / "data" / "ml" / "intent_dataset.json",
        ROOT / "data" / "evaluation" / "profile_extraction_benchmark.jsonl",
        ROOT / "data" / "evaluation" / "retrieval_benchmark.json",
        ROOT / "data" / "evaluation" / "policy_compiler_real_benchmark.jsonl",
        ROOT / "data" / "evaluation" / "high_risk_safety_benchmark.jsonl",
        ROOT / "data" / "evaluation" / "ocr_synthetic" / "manifest.json",
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in expected if not path.exists()]
    if missing:
        _fail(f"缺少文件：{missing}")

    stage4_expected = {
        "model_lock": ROOT / "models.lock.json",
        "node_lock": ROOT / "package-lock.json",
        "sbom": ROOT / "data" / "evaluation" / "software_bill_of_materials.json",
        "coverage": ROOT / "data" / "evaluation" / "coverage_report.json",
    }
    missing_stage4 = [name for name, path in stage4_expected.items() if not path.is_file()]
    if missing_stage4:
        _fail(f"第四阶段工程证据缺失：{missing_stage4}")
    model_lock = json.loads(stage4_expected["model_lock"].read_text(encoding="utf-8"))
    locked_chat = model_lock.get("models", {}).get("chat", {})
    locked_embedding = model_lock.get("models", {}).get("embedding", {})
    for role, locked in (("chat", locked_chat), ("embedding", locked_embedding)):
        if not re.fullmatch(r"[0-9a-f]{64}", str(locked.get("digest", ""))):
            _fail(f"{role}模型锁缺少有效SHA-256摘要")
    if locked_chat.get("name") != settings.ollama_model:
        _fail("对话模型名称与models.lock.json不一致")
    if locked_embedding.get("name") != settings.ollama_embedding_model:
        _fail("向量模型名称与models.lock.json不一致")
    node_lock = json.loads(stage4_expected["node_lock"].read_text(encoding="utf-8"))
    if node_lock.get("lockfileVersion") != 3:
        _fail("package-lock.json必须使用lockfileVersion 3")
    sbom = json.loads(stage4_expected["sbom"].read_text(encoding="utf-8"))
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        _fail("SBOM不是经验证的CycloneDX 1.6格式")
    if len(sbom.get("components", [])) < 40:
        _fail("CycloneDX SBOM组件覆盖不足")
    coverage = json.loads(stage4_expected["coverage"].read_text(encoding="utf-8"))
    normalized_coverage = {
        name.replace("\\", "/"): value for name, value in coverage.get("files", {}).items()
    }

    def branch_rate(summary: dict[str, object]) -> float:
        return int(summary["covered_branches"]) / int(summary["num_branches"])

    coverage_targets = {
        "app/services/policy_compiler.py": 0.85,
        "app/main.py": 0.85,
    }
    for module, target in coverage_targets.items():
        summary = normalized_coverage.get(module, {}).get("summary")
        if not isinstance(summary, dict) or branch_rate(summary) < target:
            _fail(f"核心模块分支覆盖率未达标：{module}")
    if branch_rate(coverage["totals"]) < 0.90:
        _fail("总体分支覆盖率未达到90%")

    for path in [
        expected[3], expected[4], expected[5], expected[6], expected[7],
        expected[10], expected[11], expected[14], expected[15], expected[16], expected[17],
        expected[18], expected[19], expected[21], expected[24],
    ]:
        with path.open("r", encoding="utf-8-sig") as handle:
            json.load(handle)

    vulnerability_report = json.loads(expected[11].read_text(encoding="utf-8"))
    audited_dependencies = vulnerability_report.get("dependencies", [])
    known_vulnerabilities = [
        {"name": item.get("name"), "vulns": item.get("vulns")}
        for item in audited_dependencies
        if item.get("vulns")
    ]
    if len(audited_dependencies) < 40:
        _fail("依赖漏洞扫描报告缺失或覆盖不足")
    if known_vulnerabilities:
        _fail(f"依赖漏洞扫描发现已知漏洞：{known_vulnerabilities}")

    release_manifest = json.loads(expected[16].read_text(encoding="utf-8"))
    if release_manifest.get("app_version") != APP_VERSION:
        _fail("发布清单版本与app.version不一致")
    if not re.fullmatch(r"[0-9a-f]{64}", release_manifest.get("source_tree_sha256", "")):
        _fail("发布清单缺少有效源码树指纹")
    actual_source_digest, actual_source_files = source_fingerprint()
    if release_manifest.get("source_tree_sha256") != actual_source_digest:
        _fail("发布清单源码树指纹已过期，请针对当前代码重新生成评测证据")
    binding = release_manifest.get("source_binding") or {}
    if binding.get("source_tree_sha256") != actual_source_digest:
        _fail("发布清单source_binding与当前源码树不一致")
    if binding.get("source_file_count") != len(actual_source_files):
        _fail("发布清单source_binding文件数量不一致")
    expected_release_metadata = {
        "release_id": release_manifest.get("release_id"),
        "source_tree_sha256": actual_source_digest,
    }
    stamped_reports = [
        path
        for path in (ROOT / "data" / "evaluation").glob("*_report.json")
        if path.name != "coverage_report.json"
    ]
    stamped_reports.append(ROOT / "data" / "evaluation" / "dataset_governance_manifest.json")
    for report_path in stamped_reports:
        payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
        metadata = payload.get("release_metadata") or {}
        for key, expected_value in expected_release_metadata.items():
            if metadata.get(key) != expected_value:
                _fail(f"评测报告未绑定当前发布证据：{report_path.name} ({key})")

    catalog_path = expected[0]
    with catalog_path.open("r", encoding="utf-8-sig", newline="") as handle:
        sources = list(csv.DictReader(handle))
    urls = [row["source_url"] for row in sources]
    if len(urls) != len(set(urls)):
        _fail("政策来源URL存在重复")
    if not all(url.startswith("https://") for url in urls):
        _fail("政策来源必须使用HTTPS")

    manifest = json.loads(expected[5].read_text(encoding="utf-8"))
    if manifest.get("catalog_sha256") != _sha256(catalog_path):
        _fail("政策目录已变化但来源指纹清单未更新")
    manifest_rows = {item["source_id"]: item for item in manifest.get("sources", [])}
    if set(manifest_rows) != {row["source_id"] for row in sources}:
        _fail("来源指纹清单与政策目录编号不一致")
    for source_id, item in manifest_rows.items():
        local = item.get("local_file")
        if item.get("priority") == "P0" and not local:
            _fail(f"P0来源{source_id}缺少本地快照")
        if not local:
            continue
        path = (ROOT / local).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            _fail(f"来源{source_id}的本地路径越界或不存在")
        if _sha256(path) != item.get("sha256"):
            _fail(f"来源{source_id}原件指纹不匹配")

    evidence_report = verify_evidence_quotes()
    if not evidence_report["passed"]:
        failures = [
            item["evidence_id"]
            for item in evidence_report["results"]
            if not item["passed"]
        ]
        _fail(f"逐字证据核验失败：{failures}")

    assessment_registry = json.loads(expected[14].read_text(encoding="utf-8"))
    evidence_payload = json.loads(expected[6].read_text(encoding="utf-8"))
    evidence_ids = {item["evidence_id"] for item in evidence_payload}
    missing_assessment_evidence = set(assessment_registry.get("evidence", {}).values()) - evidence_ids
    if missing_assessment_evidence:
        _fail(f"综合评估登记表引用了不存在的证据：{sorted(missing_assessment_evidence)}")

    relation_registry = json.loads(expected[15].read_text(encoding="utf-8"))
    relation_evidence = {
        evidence_id
        for relation in relation_registry.get("relationships", [])
        for evidence_id in relation.get("evidence_ids", [])
    }
    missing_relation_evidence = relation_evidence - evidence_ids
    if missing_relation_evidence:
        _fail(f"事项关系登记表引用了不存在的证据：{sorted(missing_relation_evidence)}")
    relation_ids = [
        item.get("relation_id") for item in relation_registry.get("relationships", [])
    ]
    if not relation_ids or len(relation_ids) != len(set(relation_ids)):
        _fail("事项关系登记表为空或relation_id重复")

    inventory = json.loads(expected[17].read_text(encoding="utf-8"))
    inventory_rows = inventory.get("files", [])
    inventory_names = [item.get("file_name") for item in inventory_rows]
    actual_pdf_names = sorted(path.name for path in (ROOT / "政策证据包").glob("*.pdf"))
    if len(inventory_names) != len(set(inventory_names)):
        _fail("政策证据包清单存在重复文件名")
    if sorted(inventory_names) != actual_pdf_names:
        missing_inventory = sorted(set(actual_pdf_names) - set(inventory_names))
        missing_files = sorted(set(inventory_names) - set(actual_pdf_names))
        _fail(f"政策PDF未闭环分类：未登记={missing_inventory}，文件缺失={missing_files}")
    known_source_ids = {row["source_id"] for row in sources}
    allowed_classifications = {
        "catalog_primary", "catalog_duplicate_snapshot", "official_supporting",
        "superseded_legacy", "out_of_scope_context",
    }
    for item in inventory_rows:
        if item.get("classification") not in allowed_classifications:
            _fail(f"政策PDF分类无效：{item.get('file_name')}")
        linked = set(item.get("source_ids", []))
        if not linked or linked - known_source_ids:
            _fail(f"政策PDF关联未知或空来源编号：{item.get('file_name')}")

    stage2 = json.loads(expected[18].read_text(encoding="utf-8"))
    requirements = stage2.get("requirements", {})
    if not requirements or not all(requirements.values()):
        _fail(f"第二阶段冻结集验收未全部通过：{requirements}")
    for dataset in stage2.get("datasets", []):
        dataset_path = (ROOT / str(dataset.get("path", ""))).resolve()
        if not dataset_path.is_relative_to(ROOT) or not dataset_path.is_file():
            _fail(f"第二阶段数据集缺失或路径越界：{dataset.get('path')}")
        if _sha256(dataset_path) != dataset.get("sha256"):
            _fail(f"第二阶段数据集冻结哈希失配：{dataset.get('path')}")
    policy_rows = [
        json.loads(line)
        for line in expected[22].read_text(encoding="utf-8").splitlines()
        if line
    ]
    development_sources = {
        row["source_id"] for row in policy_rows if row.get("split") == "development"
    }
    final_sources = {
        row["source_id"] for row in policy_rows if row.get("split") == "frozen_final_test"
    }
    if development_sources & final_sources:
        _fail("Policy2Rule开发集和冻结最终集存在政策文件泄漏")
    ocr_rows = json.loads(expected[24].read_text(encoding="utf-8"))
    if len(ocr_rows) < 100 or len({row.get("layout") for row in ocr_rows}) < 10:
        _fail("OCR冻结集不足100张或少于10种版式")
    missing_ocr = [
        row.get("file")
        for row in ocr_rows
        if not (expected[24].parent / str(row.get("file", ""))).is_file()
    ]
    if missing_ocr:
        _fail(f"OCR冻结集图片缺失：{missing_ocr[:5]}")

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    index_html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    service_worker = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")
    if f'version = "{APP_VERSION}"' not in pyproject:
        _fail("pyproject版本与app.version不一致")
    if f"?v={APP_VERSION}" not in index_html or f"huimin-shell-v{APP_VERSION}" not in service_worker:
        _fail("前端缓存版本与app.version不一致")

    setup_text = (ROOT / "setup.ps1").read_text(encoding="utf-8-sig")
    if re.search(r"[A-Za-z]:\\Users\\", setup_text, flags=re.IGNORECASE):
        _fail("setup.ps1包含个人绝对路径")
    for path in (ROOT / "data" / "evaluation").glob("*.json"):
        text = path.read_text(encoding="utf-8-sig")
        if re.search(r"[A-Za-z]:\\\\Users\\\\", text, flags=re.IGNORECASE):
            _fail(f"评测报告泄露个人绝对路径：{path.name}")

    print(
        "PROJECT_CHECK_OK "
        f"version={APP_VERSION} sources={len(sources)} provenance={len(manifest_rows)} "
        f"evidence_quotes={evidence_report['verified']}/{evidence_report['total']} "
        f"stage2_policy_final={sum(row.get('split') == 'frozen_final_test' for row in policy_rows)} "
        f"stage2_ocr={len(ocr_rows)} "
        f"locked_dependencies={sum(1 for line in expected[12].read_text(encoding='utf-8').splitlines() if '==' in line)} "
        f"audited_dependencies={len(audited_dependencies)}"
    )


if __name__ == "__main__":
    main()
