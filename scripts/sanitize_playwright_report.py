from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "data" / "evaluation" / "browser_e2e_report.json"
DEFAULT_SPEC = ROOT / "tests" / "e2e" / "platform.spec.js"


def _flatten_specs(suites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for suite in suites:
        specs.extend(suite.get("specs", []))
        specs.extend(_flatten_specs(suite.get("suites", [])))
    return specs


def _source_titles(spec_path: Path) -> list[str]:
    source = spec_path.read_text(encoding="utf-8")
    return re.findall(r'^\s*test\("([^"]+)"\s*,', source, flags=re.MULTILINE)


def sanitize(report_path: Path, spec_path: Path) -> dict[str, Any]:
    raw = json.loads(report_path.read_text(encoding="utf-8-sig"))
    specs = _flatten_specs(raw.get("suites", []))
    source_titles = _source_titles(spec_path)
    if len(specs) != len(source_titles):
        raise ValueError(
            f"Playwright结果数({len(specs)})与测试源码标题数({len(source_titles)})不一致"
        )

    tests: list[dict[str, Any]] = []
    for spec, title in zip(specs, source_titles, strict=True):
        runs = [result for test in spec.get("tests", []) for result in test.get("results", [])]
        final_run = runs[-1] if runs else {}
        tests.append(
            {
                "title": title,
                "file": Path(str(spec.get("file", "platform.spec.js"))).name,
                "line": spec.get("line"),
                "status": final_run.get("status", "unknown"),
                "duration_ms": final_run.get("duration", 0),
                "retry": final_run.get("retry", 0),
            }
        )

    stats = raw.get("stats", {})
    return {
        "schema_version": "playwright-e2e-summary/1.0",
        "runner": "Playwright",
        "scope": "本项目真实浏览器端到端回归；不等同于真人可用性试点",
        "started_at": stats.get("startTime"),
        "duration_ms": stats.get("duration", 0),
        "summary": {
            "expected": stats.get("expected", 0),
            "unexpected": stats.get("unexpected", 0),
            "flaky": stats.get("flaky", 0),
            "skipped": stats.get("skipped", 0),
        },
        "tests": tests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="移除Playwright原始报告中的环境变量和本机路径")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    args = parser.parse_args()
    payload = sanitize(args.report, args.spec)
    args.report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = payload["summary"]
    print(
        "PLAYWRIGHT_REPORT_SANITIZED "
        f"expected={summary['expected']} unexpected={summary['unexpected']} "
        f"tests={len(payload['tests'])}"
    )


if __name__ == "__main__":
    main()
