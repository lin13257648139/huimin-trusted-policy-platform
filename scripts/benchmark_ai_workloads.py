from __future__ import annotations

import asyncio
import ctypes
import io
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data" / "evaluation" / "ai_workload_pressure_report.json"
OCR_DIRECTORY = ROOT / "data" / "evaluation" / "ocr_synthetic"
CONCURRENCY_LEVELS = (1, 3, 5, 10)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _single_process_rss_bytes(pid: int) -> int | None:
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        process = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid)
        if not process:
            return None
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        try:
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                process, ctypes.byref(counters), counters.cb
            )
            return int(counters.WorkingSetSize) if ok else None
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    status = Path(f"/proc/{pid}/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return None


def _windows_process_tree(root_pid: int) -> set[int]:
    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        return {root_pid}
    parent_by_pid: dict[int, int] = {}
    entry = ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            parent_by_pid[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    result = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parent_by_pid.items():
            if parent in result and pid not in result:
                result.add(pid)
                changed = True
    return result


def _rss_bytes(pid: int) -> int | None:
    process_ids = _windows_process_tree(pid) if sys.platform == "win32" else {pid}
    values = [
        value
        for process_id in process_ids
        if (value := _single_process_rss_bytes(process_id)) is not None
    ]
    return sum(values) if values else None


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, int((len(ordered) - 1) * ratio + 0.999999))
    return round(ordered[index], 3)


def _pdf_payload(images: list[bytes]) -> bytes:
    pages = [Image.open(io.BytesIO(content)).convert("RGB") for content in images]
    buffer = io.BytesIO()
    pages[0].save(buffer, format="PDF", save_all=True, append_images=pages[1:])
    for page in pages:
        page.close()
    return buffer.getvalue()


async def _wait_until_ready(base_url: str, process: subprocess.Popen[bytes]) -> None:
    async with httpx.AsyncClient(timeout=1.0) as client:
        for _ in range(300):
            if process.poll() is not None:
                raise RuntimeError(f"uvicorn提前退出，退出码={process.returncode}")
            try:
                response = await client.get(f"{base_url}/api/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise RuntimeError("uvicorn在30秒内未就绪")


async def _memory_sampler(pid: int, stop: asyncio.Event, samples: list[int]) -> None:
    while not stop.is_set():
        value = _rss_bytes(pid)
        if value is not None:
            samples.append(value)
        await asyncio.sleep(0.1)


async def _request_workload(
    client: httpx.AsyncClient,
    base_url: str,
    workload: str,
    index: int,
    image: bytes,
    pdf: bytes,
    package_images: list[bytes],
) -> tuple[int | None, bool, str | None]:
    try:
        if workload == "llm_profile":
            response = await client.post(
                f"{base_url}/api/v1/profile/parse",
                json={
                    "query_date": "2026-09-30",
                    "text": (
                        f"我住在广州天河区，家里{index % 4 + 1}人，家庭每月总收入"
                        f"{2100 + index * 17}元，共同生活家庭成员已经确认。"
                    ),
                },
            )
            route_ok = response.status_code != 200 or response.json().get("mode") == "llm_assisted"
        elif workload == "hybrid_retrieval":
            response = await client.get(
                f"{base_url}/api/v1/evidence/search",
                params={"q": "广州最低生活保障收入财产条件", "limit": 5},
            )
            retriever = response.json().get("retriever", {}) if response.status_code == 200 else {}
            route_ok = response.status_code != 200 or (
                retriever.get("semantic_enabled") is True
                and str(retriever.get("name", "")).startswith("rrf(")
            )
        elif workload == "image_ocr":
            response = await client.post(
                f"{base_url}/api/v1/documents/precheck",
                data={"material_type": "auto", "consent": "true"},
                files={"file": (f"image-{index}.png", image, "image/png")},
            )
            route_ok = response.status_code != 200 or response.json().get("ocr", {}).get("enabled") is True
        elif workload == "multipage_pdf":
            response = await client.post(
                f"{base_url}/api/v1/documents/precheck",
                data={"material_type": "auto", "consent": "true"},
                files={"file": (f"pages-{index}.pdf", pdf, "application/pdf")},
            )
            route_ok = response.status_code != 200 or response.json().get("ocr", {}).get("enabled") is True
        elif workload == "material_package":
            files = [
                ("files", (f"package-{index}-{part}.png", content, "image/png"))
                for part, content in enumerate(package_images, start=1)
            ]
            response = await client.post(
                f"{base_url}/api/v1/documents/package-precheck",
                data={"benefit_id": "B002", "consent": "true"},
                files=files,
            )
            route_ok = response.status_code != 200 or bool(response.json().get("documents"))
        else:
            raise ValueError(workload)
        return response.status_code, route_ok, None
    except Exception as exc:  # pragma: no cover - benchmark diagnostics
        return None, False, type(exc).__name__


async def _run_level(
    client: httpx.AsyncClient,
    base_url: str,
    process_pid: int,
    workload: str,
    concurrency: int,
    image: bytes,
    pdf: bytes,
    package_images: list[bytes],
) -> dict[str, Any]:
    request_count = max(3, concurrency)
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: Counter[int] = Counter()
    exceptions: Counter[str] = Counter()
    route_violations = 0
    memory_samples: list[int] = []
    stop = asyncio.Event()
    sampler = asyncio.create_task(_memory_sampler(process_pid, stop, memory_samples))

    async def one(index: int) -> None:
        nonlocal route_violations
        async with semaphore:
            started = time.perf_counter()
            status, route_ok, error = await _request_workload(
                client, base_url, workload, index, image, pdf, package_images
            )
            latencies.append((time.perf_counter() - started) * 1000)
            if status is not None:
                statuses[status] += 1
            if error:
                exceptions[error] += 1
            route_violations += int(not route_ok)

    started = time.perf_counter()
    try:
        await asyncio.gather(*(one(index) for index in range(request_count)))
    finally:
        stop.set()
        await sampler
    elapsed = time.perf_counter() - started
    rejected = statuses[503]
    timeouts = statuses[504] + exceptions["ReadTimeout"] + exceptions["PoolTimeout"]
    errors = request_count - statuses[200]
    return {
        "concurrency": concurrency,
        "requests": request_count,
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "max_ms": round(max(latencies), 3) if latencies else None,
        "throughput_rps": round(request_count / elapsed, 3),
        "http_status_counts": {str(key): value for key, value in sorted(statuses.items())},
        "exception_counts": dict(exceptions),
        "error_rate": round(errors / request_count, 4),
        "queue_rejection_rate": round(rejected / request_count, 4),
        "timeout_rate": round(timeouts / request_count, 4),
        "route_validation_failures": route_violations,
        "server_rss_peak_mb": (
            round(max(memory_samples) / 1024 / 1024, 3) if memory_samples else None
        ),
    }


async def _timeout_recovery_probe() -> dict[str, Any]:
    from app.services.workload import (
        WorkloadTimeoutError,
        run_bounded,
        shutdown_workloads,
        start_workloads,
        workload_status,
    )

    def slow() -> str:
        time.sleep(0.15)
        return "slow-finished"

    start_workloads()
    timeout_observed = False
    try:
        try:
            await run_bounded("document", slow, timeout=0.01)
        except WorkloadTimeoutError:
            timeout_observed = True
        for _ in range(100):
            if workload_status()["outstanding"]["document"] == 0:
                break
            await asyncio.sleep(0.01)
        fast_result = await run_bounded(
            "document", lambda: "recovered", timeout=1.0
        )
        status = workload_status()
        return {
            "timeout_observed": timeout_observed,
            "capacity_released": status["outstanding"]["document"] == 0,
            "subsequent_task_succeeded": fast_result == "recovered",
            "counters": {
                "outstanding": status["outstanding"]["document"],
                "submitted": status["metrics"]["submitted"]["document"],
                "completed": status["metrics"]["completed"]["document"],
                "timed_out": status["metrics"]["timed_out"]["document"],
                "cancel_succeeded": status["metrics"]["cancel_succeeded"][
                    "document"
                ],
            },
        }
    finally:
        shutdown_workloads(wait=True)


async def benchmark() -> dict[str, Any]:
    manifest = json.loads((OCR_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    package_images = [
        (OCR_DIRECTORY / manifest[index]["file"]).read_bytes() for index in (0, 10, 20)
    ]
    image = package_images[0]
    pdf = _pdf_payload(package_images)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="huimin-ai-pressure-") as temporary:
        environment = os.environ.copy()
        environment.update(
            {
                "DATABASE_PATH": str(Path(temporary) / "pressure.db"),
                "UPLOAD_DIR": str(Path(temporary) / "uploads"),
                "AI_MODE": "hybrid",
                "APP_ENV": "benchmark",
                "DEMO_MODE": "true",
                "MAX_LLM_WORKERS": "2",
                "MAX_DOCUMENT_WORKERS": "2",
                "MAX_WORK_QUEUE": "16",
                "DOCUMENT_TIMEOUT_SECONDS": "120",
                "PACKAGE_TIMEOUT_SECONDS": "360",
            }
        )
        process = subprocess.Popen(
            [
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
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            await _wait_until_ready(base_url, process)
            timeout = httpx.Timeout(420.0, connect=10.0)
            limits = httpx.Limits(max_connections=24, max_keepalive_connections=12)
            async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                metadata = (await client.get(f"{base_url}/api/v1/metadata")).json()
                runtime = metadata["ai_runtime"]
                if not (
                    runtime.get("reachable")
                    and runtime.get("model_present")
                    and runtime.get("embedding_model_present")
                ):
                    raise RuntimeError(f"本地LLM或嵌入模型未就绪：{runtime}")
                results: dict[str, list[dict[str, Any]]] = {}
                for workload in (
                    "llm_profile",
                    "hybrid_retrieval",
                    "image_ocr",
                    "multipage_pdf",
                    "material_package",
                ):
                    results[workload] = []
                    for concurrency in CONCURRENCY_LEVELS:
                        results[workload].append(
                            await _run_level(
                                client,
                                base_url,
                                process.pid,
                                workload,
                                concurrency,
                                image,
                                pdf,
                                package_images,
                            )
                        )
                final_metadata = (await client.get(f"{base_url}/api/v1/metadata")).json()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    recovery = await _timeout_recovery_probe()
    return {
        "report_schema": "real-ai-workload-pressure/1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "not-reported",
            "server": "single-process uvicorn over loopback HTTP",
            "ai_mode": "hybrid",
            "llm_workers": 2,
            "document_workers": 2,
            "queue_capacity": 16,
        },
        "ai_runtime": runtime,
        "concurrency_levels": list(CONCURRENCY_LEVELS),
        "results": results,
        "timeout_recovery": recovery,
        "final_workload_counters": final_metadata["bounded_workloads"],
        "claim_boundary": [
            "这是当前机器、回环HTTP和本地Ollama的端到端工程压力测试，不代表公网生产容量。",
            "server_rss_peak_mb只统计FastAPI服务进程RSS；独立Ollama进程及GPU显存未计入。",
            "测试材料为程序生成且不含真实个人信息。",
            "队列拒绝和超时是容量治理信号，不得删除或改写为成功请求。",
        ],
    }


def main() -> None:
    report = asyncio.run(benchmark())
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total_requests = sum(
        item["requests"]
        for levels in report["results"].values()
        for item in levels
    )
    print(
        "REAL_AI_PRESSURE_OK "
        f"requests={total_requests} workloads={len(report['results'])} "
        f"timeout_recovered={report['timeout_recovery']['subsequent_task_succeeded']}"
    )


if __name__ == "__main__":
    main()
