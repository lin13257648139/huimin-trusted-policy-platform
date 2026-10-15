from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "evaluation" / "release_manifest.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _git(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _source_files() -> list[Path]:
    paths: list[Path] = []
    for directory in ("app", "scripts", "tests", "data/processed", "data/schemas"):
        paths.extend(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() not in {".pyc", ".pyo"}
        )
    for relative in (
        "pyproject.toml",
        "requirements.lock",
        "Dockerfile",
        "compose.yaml",
        ".env.example",
        "setup.ps1",
        "reproduce_phase12.ps1",
        "data/raw_official/provenance_manifest.json",
    ):
        path = ROOT / relative
        if path.is_file():
            paths.append(path)
    evaluation = ROOT / "data" / "evaluation"
    for pattern in ("*_benchmark.json", "*_benchmark.jsonl", "profile_extraction_benchmark.jsonl"):
        paths.extend(evaluation.glob(pattern))
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())


def main() -> None:
    from app.services.rule_engine import ENGINE_VERSION
    from app.version import APP_VERSION

    digest = hashlib.sha256()
    files = _source_files()
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    source_digest = digest.hexdigest()
    report = {
        "schema_version": "release-manifest/1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": APP_VERSION,
        "engine_version": ENGINE_VERSION,
        "release_id": f"v{APP_VERSION}+source.{source_digest[:12]}",
        "git_commit": commit,
        "git_dirty": bool(status) if status is not None else None,
        "source_tree_sha256": source_digest,
        "source_file_count": len(files),
        "claim_boundary": (
            "source_tree_sha256冻结本次代码与输入数据；git_dirty为true时不得称为干净Git发布，"
            "但报告仍可按源码树指纹复核。"
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"RELEASE_MANIFEST_OK release={report['release_id']} "
        f"files={len(files)} git_dirty={report['git_dirty']}"
    )


if __name__ == "__main__":
    main()
