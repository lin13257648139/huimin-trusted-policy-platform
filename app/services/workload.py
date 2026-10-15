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


_EXECUTORS = {
    "llm": ThreadPoolExecutor(
        max_workers=settings.max_llm_workers,
        thread_name_prefix="huimin-llm",
    ),
    "document": ThreadPoolExecutor(
        max_workers=settings.max_document_workers,
        thread_name_prefix="huimin-document",
    ),
}
_OUTSTANDING = {"llm": 0, "document": 0}
_CAPACITY = {
    "llm": BoundedSemaphore(settings.max_work_queue),
    "document": BoundedSemaphore(settings.max_work_queue),
}
_LOCK = Lock()


def _reserve(kind: WorkloadKind) -> None:
    if not _CAPACITY[kind].acquire(blocking=False):
        raise WorkloadBusyError(f"{kind}任务队列已满，请稍后重试")
    with _LOCK:
        _OUTSTANDING[kind] += 1


def _release(kind: WorkloadKind) -> None:
    with _LOCK:
        _OUTSTANDING[kind] = max(0, _OUTSTANDING[kind] - 1)
    _CAPACITY[kind].release()


async def run_bounded(
    kind: WorkloadKind,
    function: Callable[..., T],
    *args: Any,
    timeout: float,
    **kwargs: Any,
) -> T:
    """Run blocking AI/document work outside the event loop with hard bounds."""

    _reserve(kind)
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_EXECUTORS[kind], partial(function, *args, **kwargs))
    future.add_done_callback(lambda _: _release(kind))
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except TimeoutError as exc:
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
    }
