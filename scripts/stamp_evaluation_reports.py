from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALUATION = ROOT / "data" / "evaluation"
RELEASE = EVALUATION / "release_manifest.json"


def main() -> None:
    release = json.loads(RELEASE.read_text(encoding="utf-8"))
    metadata = {
        key: release[key]
        for key in (
            "release_id",
            "app_version",
            "engine_version",
            "git_commit",
            "git_dirty",
            "source_tree_sha256",
        )
    }
    stamped = 0
    for path in sorted(EVALUATION.glob("*_report.json")):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            continue
        payload["app_version"] = release["app_version"]
        payload["engine_version"] = release["engine_version"]
        payload["release_metadata"] = metadata
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stamped += 1
    governance = EVALUATION / "dataset_governance_manifest.json"
    if governance.is_file():
        payload = json.loads(governance.read_text(encoding="utf-8"))
        payload["release_metadata"] = metadata
        governance.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"REPORT_STAMP_OK reports={stamped} release={release['release_id']}")


if __name__ == "__main__":
    main()
