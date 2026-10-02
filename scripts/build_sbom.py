from __future__ import annotations

import importlib.metadata
import json
import platform
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"
OUTPUT = ROOT / "data" / "evaluation" / "software_bill_of_materials.json"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)")


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main() -> None:
    requested: list[dict[str, object]] = []
    missing: list[str] = []
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line.strip())
        if not match:
            continue
        name, locked_version = match.groups()
        try:
            distribution = importlib.metadata.distribution(name)
            installed_version = distribution.version
            license_value = distribution.metadata.get("License") or "not-declared"
            homepage = distribution.metadata.get("Home-page") or "not-declared"
        except importlib.metadata.PackageNotFoundError:
            installed_version = None
            license_value = "not-installed"
            homepage = "not-installed"
            missing.append(name)
        requested.append(
            {
                "name": normalized(name),
                "locked_version": locked_version,
                "installed_version": installed_version,
                "version_matches": installed_version == locked_version,
                "license_declared": license_value,
                "homepage": homepage,
                "purl": f"pkg:pypi/{normalized(name)}@{locked_version}",
            }
        )
    report = {
        "bom_format": "project-internal CycloneDX-inspired inventory",
        "spec_note": "不是CycloneDX官方验证输出；用于依赖追溯与赛前许可证复核。",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "source": "requirements.lock",
        "component_count": len(requested),
        "all_installed": not missing,
        "all_versions_match": all(item["version_matches"] for item in requested),
        "missing": missing,
        "components": requested,
        "review_required": (
            "提交/部署前人工复核各依赖许可证全文、模型许可证及数据来源授权；"
            "包元数据中的License字段可能为空或不规范。"
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    matched = sum(bool(item["version_matches"]) for item in requested)
    print(
        f"SBOM_OK components={len(requested)} installed={len(requested) - len(missing)} "
        f"version_matches={matched}"
    )
    if missing:
        raise SystemExit(f"SBOM_MISSING_DEPENDENCIES: {missing}")


if __name__ == "__main__":
    main()
