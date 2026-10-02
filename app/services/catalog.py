from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

from app.config import BASE_DIR, settings
from app.domain.models import Evidence, Office, PolicySource


@lru_cache(maxsize=1)
def load_evidence() -> dict[str, Evidence]:
    path = BASE_DIR / "app" / "data" / "evidence.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {item["evidence_id"]: Evidence.model_validate(item) for item in payload}


@lru_cache(maxsize=1)
def load_offices() -> list[Office]:
    path = settings.processed_data_dir / "office_directory_seed.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [Office.model_validate(row) for row in csv.DictReader(handle)]


@lru_cache(maxsize=1)
def load_policy_sources() -> list[PolicySource]:
    path = settings.processed_data_dir / "policy_source_catalog.csv"
    sources: list[PolicySource] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sources.append(
                PolicySource(
                    source_id=row["source_id"],
                    scope=row["scope"],
                    topic=row["topic"],
                    title=row["title"],
                    issuer=row["issuer"],
                    document_no=row.get("document_no") or None,
                    published_date=row.get("published_date") or None,
                    effective_from=row.get("effective_from") or None,
                    effective_to=row.get("effective_to") or None,
                    status=row["status_as_of_2026-09-29"],
                    source_url=row["source_url"],
                    priority=row["priority"],
                    usage_note=row["usage_note"],
                )
            )
    return sources


def evidence_for(*evidence_ids: str) -> list[Evidence]:
    catalog = load_evidence()
    return [catalog[item] for item in evidence_ids if item in catalog]

