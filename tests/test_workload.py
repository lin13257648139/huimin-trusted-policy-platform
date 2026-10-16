from __future__ import annotations

import asyncio
import time

import pytest

from app.services.workload import (
    WorkloadTimeoutError,
    run_bounded,
    shutdown_workloads,
    workload_status,
)


def test_timed_out_running_task_eventually_releases_capacity() -> None:
    shutdown_workloads(wait=True)

    def slow_call() -> str:
        time.sleep(0.08)
        return "slow"

    async def exercise() -> None:
        with pytest.raises(WorkloadTimeoutError):
            await run_bounded("llm", slow_call, timeout=0.005)
        assert workload_status()["metrics"]["timed_out"]["llm"] >= 1
        await asyncio.sleep(0.12)
        assert workload_status()["outstanding"]["llm"] == 0
        assert await run_bounded("llm", lambda: "recovered", timeout=1) == "recovered"

    try:
        asyncio.run(exercise())
    finally:
        shutdown_workloads(wait=True)


def test_executor_can_restart_after_lifespan_shutdown() -> None:
    shutdown_workloads(wait=True)
    assert workload_status()["executor_running"] is False
    assert asyncio.run(run_bounded("document", lambda: 42, timeout=1)) == 42
    assert workload_status()["executor_running"] is True
    shutdown_workloads(wait=True)
    assert workload_status()["executor_running"] is False
