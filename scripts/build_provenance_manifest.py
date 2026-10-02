from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "processed" / "policy_source_catalog.csv"
OUTPUT = ROOT / "data" / "raw_official" / "provenance_manifest.json"
PAGE_LOCATORS = {
    "GD-002": {
        "pdf_pages": "12-18",
        "note": "官方附件为广东省政府公报2022年第7期合刊；指定页为本项目使用的完整政策正文。",
    }
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    with CATALOG.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    sources = []
    for row in rows:
        raw_path = row.get("local_file", "").strip()
        resolved = (CATALOG.parent / raw_path).resolve() if raw_path else None
        in_project = bool(resolved and resolved.is_relative_to(ROOT))
        exists = bool(in_project and resolved and resolved.is_file())
        item = {
                "source_id": row["source_id"],
                "priority": row["priority"],
                "source_url": row["source_url"],
                "status": row["status_as_of_2026-09-29"],
                "local_file": resolved.relative_to(ROOT).as_posix() if exists and resolved else None,
                "availability": "snapshotted" if exists else "online_only",
                "bytes": resolved.stat().st_size if exists and resolved else None,
                "sha256": _sha256(resolved) if exists and resolved else None,
            }
        if row["source_id"] in PAGE_LOCATORS:
            item["locator"] = PAGE_LOCATORS[row["source_id"]]
        sources.append(item)
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog": "data/processed/policy_source_catalog.csv",
        "catalog_sha256": _sha256(CATALOG),
        "path_policy": "all paths are project-relative; no personal absolute path is stored",
        "sources": sources,
    }
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    missing_p0 = [item["source_id"] for item in sources if item["priority"] == "P0" and not item["sha256"]]
    if missing_p0:
        raise SystemExit(f"P0来源缺少本地原件：{missing_p0}")
    print(f"PROVENANCE_OK sources={len(sources)} snapshotted={sum(bool(item['sha256']) for item in sources)}")


if __name__ == "__main__":
    main()
