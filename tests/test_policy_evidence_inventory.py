import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_policy_pdf_is_classified_once_and_links_known_sources() -> None:
    inventory = json.loads(
        (ROOT / "data" / "processed" / "policy_evidence_inventory.json").read_text(
            encoding="utf-8"
        )
    )
    entries = inventory["files"]
    names = [item["file_name"] for item in entries]
    actual = sorted(path.name for path in (ROOT / "政策证据包").glob("*.pdf"))
    assert len(names) == len(set(names))
    assert sorted(names) == actual
    allowed = {
        "catalog_primary",
        "catalog_duplicate_snapshot",
        "official_supporting",
        "superseded_legacy",
        "out_of_scope_context",
    }
    assert {item["classification"] for item in entries} <= allowed
    with (ROOT / "data" / "processed" / "policy_source_catalog.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as stream:
        source_ids = {row["source_id"] for row in csv.DictReader(stream)}
    assert all(item["source_ids"] for item in entries)
    assert not {
        source_id
        for item in entries
        for source_id in item["source_ids"]
        if source_id not in source_ids
    }
