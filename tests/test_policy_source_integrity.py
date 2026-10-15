from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "processed" / "policy_source_catalog.csv"
MANIFEST = ROOT / "data" / "raw_official" / "provenance_manifest.json"


def test_gd004_points_to_current_policy_and_verified_appendix() -> None:
    with CATALOG.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {row["source_id"]: row for row in csv.DictReader(handle)}

    current = rows["GD-004"]
    appendix = rows["GD-004-A"]
    assert current["document_no"] == "粤民规字〔2025〕5号"
    assert current["local_file"].endswith(
        "13_广东省最低生活保障家庭经济状况核对和生活状况综合评估办法_2025.pdf"
    )
    assert "广东省民政厅关于广东省最低生活保障.pdf" not in current["local_file"]
    assert appendix["document_no"] == "粤民规字〔2025〕5号附件"

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = {item["source_id"]: item for item in manifest["sources"]}
    assert sources["GD-004"]["sha256"] == (
        "9c059af17ee9dd0f0ccaf7a7b97f988407639e3abb35695eb1cc950b19309990"  # pragma: allowlist secret
    )
    assert sources["GD-004-A"]["sha256"] == (
        "b4528b168cb32eb4b2ea54c1bbd6b7ed87c2858f252fec5bca51d1a46cfc081c"  # pragma: allowlist secret
    )
    assert sources["GD-004-A"]["parent_source_id"] == "GD-004"

    for source_id in ("GD-004", "GD-004-A"):
        path = ROOT / sources[source_id]["local_file"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sources[source_id]["sha256"]
