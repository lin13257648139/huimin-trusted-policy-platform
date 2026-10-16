from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"
OUTPUT = ROOT / "data" / "evaluation" / "software_bill_of_materials.json"


def main() -> None:
    """Generate and validate a reproducible CycloneDX 1.6 SBOM from the lock file."""

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "cyclonedx_py",
        "requirements",
        str(LOCK),
        "--output-reproducible",
        "--validate",
        "--output-format",
        "JSON",
        "--spec-version",
        "1.6",
        "--output-file",
        str(OUTPUT),
    ]
    try:
        environment = os.environ.copy()
        # CycloneDX CLI follows the Windows ANSI code page unless UTF-8 mode is
        # explicit; requirements.lock intentionally contains a Chinese audit note.
        environment["PYTHONUTF8"] = "1"
        subprocess.run(command, cwd=ROOT, check=True, env=environment)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"CYCLONEDX_GENERATION_FAILED: {exc}") from exc
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    components = payload.get("components")
    if payload.get("bomFormat") != "CycloneDX" or payload.get("specVersion") != "1.6":
        raise SystemExit("CYCLONEDX_VALIDATION_FAILED: unexpected format or spec version")
    if not isinstance(components, list) or not components:
        raise SystemExit("CYCLONEDX_VALIDATION_FAILED: component inventory is empty")
    print(
        f"CYCLONEDX_SBOM_OK spec={payload['specVersion']} components={len(components)} "
        f"serial={payload.get('serialNumber')}"
    )


if __name__ == "__main__":
    main()
