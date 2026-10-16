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


def source_files() -> list[Path]:
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
        "requirements-quality.txt",
        "Dockerfile",
        "compose.yaml",
        ".env.example",
        ".semgrep.yml",
        "README.md",
        "SECURITY.md",
        "REPRODUCIBILITY.md",
        "MODEL_LICENSES.md",
        "setup.ps1",
        "start.ps1",
        "start-ai-runtime.ps1",
        "reproduce_phase12.ps1",
        ".github/workflows/ci.yml",
        "data/raw_official/provenance_manifest.json",
    ):
        path = ROOT / relative
        if path.is_file():
            paths.append(path)
    evaluation = ROOT / "data" / "evaluation"
    for pattern in ("*_benchmark.json", "*_benchmark.jsonl", "profile_extraction_benchmark.jsonl"):
        paths.extend(evaluation.glob(pattern))
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())


def source_fingerprint() -> tuple[str, list[Path]]:
    digest = hashlib.sha256()
    files = source_files()
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), files


def _source_inputs_dirty(files: list[Path], status: str | None) -> bool | None:
    if status is None:
        return None
    source_paths = {path.relative_to(ROOT).as_posix() for path in files}
    for line in status.splitlines():
        changed = line[3:].strip().replace("\\", "/")
        if " -> " in changed:
            changed = changed.split(" -> ", 1)[1]
        if changed in source_paths:
            return True
    return False


def main() -> None:
    from app.services.rule_engine import ENGINE_VERSION
    from app.version import APP_VERSION

    source_digest, files = source_fingerprint()
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    source_dirty = _source_inputs_dirty(files, status)
    report = {
        "schema_version": "release-manifest/2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": APP_VERSION,
        "engine_version": ENGINE_VERSION,
        "release_id": f"v{APP_VERSION}+source.{source_digest[:12]}",
        "git_commit": commit,
        "git_dirty": bool(status) if status is not None else None,
        "source_tree_sha256": source_digest,
        "source_file_count": len(files),
        "source_binding": {
            "code_commit": commit,
            "source_inputs_dirty": source_dirty,
            "source_tree_sha256": source_digest,
            "source_file_count": len(files),
            "scope": "代码、测试、评测输入、运行和安全配置；生成的评测报告不参与自指纹",
        },
        "artifact_binding": {
            "reports_generated_from_source_sha256": source_digest,
            "evidence_commit": None,
            "note": "报告提交后可由正式发布流程填入证据提交；源码绑定以内容指纹为准。",
        },
        "claim_boundary": (
            "source_tree_sha256冻结代码、测试、评测输入和运行配置，评测报告本身不参与"
            "自指纹；source_inputs_dirty必须为false后才可称为代码提交已冻结。"
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"RELEASE_MANIFEST_OK release={report['release_id']} "
        f"files={len(files)} source_inputs_dirty={source_dirty} git_dirty={report['git_dirty']}"
    )


if __name__ == "__main__":
    main()
