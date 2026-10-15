from __future__ import annotations

import json
import math
import os
import platform
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEMO_MODE", "true")

from fastapi.testclient import TestClient

import app.main as main
from app.repositories.database import Database

OUTPUT = ROOT / "data" / "evaluation" / "api_performance_report.json"
RUNS = 25


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index], 3)


def measure(name: str, action: Callable[[], object], threshold_ms: float) -> dict[str, object]:
    durations: list[float] = []
    errors: list[str] = []
    action()  # warm caches and lazy imports; not included in timing
    for _ in range(RUNS):
        started = perf_counter()
        try:
            response = action()
            status_code = getattr(response, "status_code", 500)
            if status_code >= 400:
                errors.append(f"HTTP {status_code}")
        except Exception as exc:  # pragma: no cover - benchmark diagnostic
            errors.append(type(exc).__name__)
        durations.append((perf_counter() - started) * 1000)
    p95 = percentile(durations, 0.95)
    return {
        "name": name,
        "runs": RUNS,
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": p95,
        "max_ms": round(max(durations), 3),
        "threshold_ms": threshold_ms,
        "errors": errors,
        "passed": not errors and p95 <= threshold_ms,
    }


def main_benchmark() -> None:
    profile = {
        "query_date": "2026-09-30",
        "city": "广州市",
        "district": "天河区",
        "household_size": 3,
        "is_local_hukou": True,
        "member_scope_confirmed": True,
        "monthly_income_total": 3200,
        "deductible_monthly_total": 0,
        "assets_eligible": True,
        "urgent_event": False,
    }
    with tempfile.TemporaryDirectory(prefix="huimin-benchmark-") as temp_dir:
        main.database = Database(Path(temp_dir) / "benchmark.db")
        with TestClient(main.app) as client:
            results = [
                measure("health", lambda: client.get("/api/health"), 250),
                measure(
                    "system_readiness",
                    lambda: client.get("/api/v1/system/readiness"),
                    750,
                ),
                measure(
                    "active_question",
                    lambda: client.post(
                        "/api/v1/guidance/next-question",
                        json={"query_date": "2026-09-30", "district": "天河区"},
                    ),
                    500,
                ),
                measure(
                    "evidence_search",
                    lambda: client.get(
                        "/api/v1/evidence/search",
                        params={"q": "最低生活保障", "limit": 6},
                    ),
                    750,
                ),
                measure(
                    "screening",
                    lambda: client.post("/api/v1/screenings", json=profile),
                    1500,
                ),
            ]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": main.settings.app_version,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "not-reported",
            "mode": "FastAPI TestClient, warm-cache, isolated temporary SQLite",
        },
        "runs_per_endpoint": RUNS,
        "passed": all(item["passed"] for item in results),
        "results": results,
        "claim_boundary": (
            "本报告仅证明当前机器上的工程响应时间与无错误运行，"
            "不代表生产并发能力，也不代表业务准确率。"
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit("API_PERFORMANCE_CHECK_FAILED")


if __name__ == "__main__":
    main_benchmark()
