from __future__ import annotations

import asyncio
import json
import math
import os
import platform
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "evaluation" / "http_concurrency_report.json"
CONCURRENCY_LEVELS = (1, 5, 10, 20, 30)
REQUESTS_PER_LEVEL = 60


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index], 3)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


async def wait_until_ready(base_url: str, process: subprocess.Popen[bytes]) -> None:
    async with httpx.AsyncClient(timeout=1.0) as client:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f"uvicorn提前退出，退出码={process.returncode}")
            try:
                response = await client.get(f"{base_url}/api/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise RuntimeError("uvicorn在10秒内未就绪")


async def run_level(base_url: str, concurrency: int) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    durations: list[float] = []
    errors: list[str] = []
    paths = (
        "/api/health",
        "/api/v1/evidence/search?q=%E6%9C%80%E4%BD%8E%E7%94%9F%E6%B4%BB%E4%BF%9D%E9%9A%9C&limit=6",
        "/api/v1/system/readiness",
    )

    async with httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=40)) as client:

        async def one(index: int) -> None:
            async with semaphore:
                started = perf_counter()
                try:
                    response = await client.get(
                        f"{base_url}{paths[index % len(paths)]}", timeout=15.0
                    )
                    if response.status_code != 200:
                        errors.append(f"HTTP {response.status_code}")
                except Exception as exc:  # pragma: no cover - diagnostic path
                    errors.append(type(exc).__name__)
                finally:
                    durations.append((perf_counter() - started) * 1000)

        started = perf_counter()
        await asyncio.gather(*(one(index) for index in range(REQUESTS_PER_LEVEL)))
        elapsed = perf_counter() - started
    p95 = percentile(durations, 0.95)
    return {
        "concurrency": concurrency,
        "requests": REQUESTS_PER_LEVEL,
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": p95,
        "max_ms": round(max(durations), 3),
        "throughput_rps": round(REQUESTS_PER_LEVEL / elapsed, 2),
        "errors": len(errors),
        "error_types": sorted(set(errors)),
        "passed": not errors and p95 <= 1500,
    }


async def benchmark() -> dict[str, Any]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="huimin-http-benchmark-") as temp_dir:
        temp = Path(temp_dir)
        environment = os.environ.copy()
        environment.update(
            {
                "DATABASE_PATH": str(temp / "benchmark.db"),
                "UPLOAD_DIR": str(temp / "uploads"),
                "AI_MODE": "deterministic",
                "APP_ENV": "benchmark",
                "DEMO_MODE": "true",
                # This benchmark measures HTTP latency rather than overload rejection.
                # Queue saturation and Retry-After semantics have separate tests.
                "MAX_WORK_QUEUE": "64",
            }
        )
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            await wait_until_ready(base_url, process)
            async with httpx.AsyncClient(timeout=5.0) as client:
                for path in ("/api/health", "/api/v1/system/readiness"):
                    await client.get(f"{base_url}{path}")
            results = [await run_level(base_url, level) for level in CONCURRENCY_LEVELS]
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "not-reported",
            "server": "single-process uvicorn over loopback HTTP",
            "mode": "deterministic; isolated temporary SQLite; warm cache",
            "max_work_queue": 64,
        },
        "workload": {
            "levels": list(CONCURRENCY_LEVELS),
            "requests_per_level": REQUESTS_PER_LEVEL,
            "endpoints": ["health", "evidence search", "readiness"],
        },
        "passed": all(item["passed"] for item in results),
        "results": results,
        "claim_boundary": (
            "本报告是当前机器单进程、回环网络、只读混合接口的工程基准；"
            "不代表公网生产容量，也不代表包含大模型生成或文件OCR的端到端延迟。"
        ),
    }


def main() -> None:
    report = asyncio.run(benchmark())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "HTTP_CONCURRENCY_OK "
        + " ".join(
            f"c{item['concurrency']}={item['throughput_rps']}rps/p95:{item['p95_ms']}ms"
            for item in report["results"]
        )
    )
    if not report["passed"]:
        raise SystemExit("HTTP_CONCURRENCY_CHECK_FAILED")


if __name__ == "__main__":
    main()
