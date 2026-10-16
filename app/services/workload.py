from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import BoundedSemaphore, Lock
from typing import Any, Literal, TypeVar

from app.config import settings

T = TypeVar("T")
WorkloadKind = Literal["llm", "document"]


class WorkloadBusyError(RuntimeError):
    """Raised before submission when the bounded queue is already full."""


class WorkloadTimeoutError(TimeoutError):
    """Raised when a bounded background task exceeds its request budget."""


_EXECUTORS: dict[WorkloadKind, ThreadPoolExecutor] = {}
_OUTSTANDING = {"llm": 0, "document": 0}
_CAPACITY: dict[WorkloadKind, BoundedSemaphore] = {}
_METRICS = {
    "submitted": {"llm": 0, "document": 0},
    "completed": {"llm": 0, "document": 0},
    "rejected": {"llm": 0, "document": 0},
    "timed_out": {"llm": 0, "document": 0},
    "cancel_succeeded": {"llm": 0, "document": 0},
}
_LOCK = Lock()


def start_workloads() -> None:
    """Create fresh executors for an application lifespan or direct async use."""

    with _LOCK:
        if _EXECUTORS:
            return
        _EXECUTORS.update(
            {
                "llm": ThreadPoolExecutor(
                    max_workers=settings.max_llm_workers,
                    thread_name_prefix="huimin-llm",
                ),
                "document": ThreadPoolExecutor(
                    max_workers=settings.max_document_workers,
                    thread_name_prefix="huimin-document",
                ),
            }
        )
        _CAPACITY.update(
            {
                "llm": BoundedSemaphore(settings.max_work_queue),
                "document": BoundedSemaphore(settings.max_work_queue),
            }
        )


def shutdown_workloads(*, wait: bool) -> None:
    """Stop accepting work and cancel tasks that have not started yet."""

    with _LOCK:
        executors = list(_EXECUTORS.values())
        _EXECUTORS.clear()
        _CAPACITY.clear()
    for executor in executors:
        executor.shutdown(wait=wait, cancel_futures=True)


def _reserve(
    kind: WorkloadKind,
) -> tuple[ThreadPoolExecutor, BoundedSemaphore]:
    start_workloads()
    with _LOCK:
        executor = _EXECUTORS[kind]
        capacity = _CAPACITY[kind]
        if not capacity.acquire(blocking=False):
            _METRICS["rejected"][kind] += 1
            raise WorkloadBusyError(f"{kind}任务队列已满，请稍后重试")
        _OUTSTANDING[kind] += 1
        _METRICS["submitted"][kind] += 1
    return executor, capacity


def _release(kind: WorkloadKind, capacity: BoundedSemaphore) -> None:
    with _LOCK:
        _OUTSTANDING[kind] = max(0, _OUTSTANDING[kind] - 1)
        _METRICS["completed"][kind] += 1
    capacity.release()


async def run_bounded(
    kind: WorkloadKind,
    function: Callable[..., T],
    *args: Any,
    timeout: float,
    **kwargs: Any,
) -> T:
    """Run blocking AI/document work outside the event loop with hard bounds."""

    executor, capacity = _reserve(kind)
    loop = asyncio.get_running_loop()
    try:
        future = loop.run_in_executor(executor, partial(function, *args, **kwargs))
    except RuntimeError:
        _release(kind, capacity)
        raise
    future.add_done_callback(lambda _: _release(kind, capacity))
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except TimeoutError as exc:
        cancelled = future.cancel()
        with _LOCK:
            _METRICS["timed_out"][kind] += 1
            if cancelled:
                _METRICS["cancel_succeeded"][kind] += 1
        raise WorkloadTimeoutError(f"{kind}任务超过{timeout:g}秒限制") from exc


def workload_status() -> dict[str, object]:
    with _LOCK:
        outstanding = dict(_OUTSTANDING)
    return {
        "outstanding": outstanding,
        "workers": {
            "llm": settings.max_llm_workers,
            "document": settings.max_document_workers,
        },
        "queue_limit_per_kind": settings.max_work_queue,
        "executor_running": bool(_EXECUTORS),
        "metrics": {
            name: dict(values) for name, values in _METRICS.items()
        },
        "timeout_semantics": (
            "超时会取消尚未开始的任务；已开始的线程调用受底层超时约束，完成后释放容量。"
        ),
    }
