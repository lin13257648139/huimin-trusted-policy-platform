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

from app.version import APP_VERSION
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
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in expected if not path.exists()]
    if missing:
        _fail(f"缺少文件：{missing}")

    for path in [
        expected[3], expected[4], expected[5], expected[6], expected[7],
        expected[10], expected[11], expected[14], expected[15], expected[16], expected[17],
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
        f"locked_dependencies={sum(1 for line in expected[12].read_text(encoding='utf-8').splitlines() if '==' in line)} "
        f"audited_dependencies={len(audited_dependencies)}"
    )


if __name__ == "__main__":
    main()
