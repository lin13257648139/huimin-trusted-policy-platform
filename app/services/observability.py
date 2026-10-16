from __future__ import annotations

import json
import logging
import sys
from collections import Counter, deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from app.config import settings

_MAX_SAMPLES = 2_000
_LOCK = Lock()
_COUNTERS: Counter[str] = Counter()
_DURATIONS: dict[str, deque[float]] = {
    "request_ms": deque(maxlen=_MAX_SAMPLES),
    "llm_ms": deque(maxlen=_MAX_SAMPLES),
    "ocr_ms": deque(maxlen=_MAX_SAMPLES),
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "application_log"),
            "message": record.getMessage(),
        }
        for field in ("method", "path", "status", "duration_ms", "request_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_structured_logging() -> None:
    logger = logging.getLogger("huimin")
    if any(getattr(handler, "_huimin_json", False) for handler in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._huimin_json = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def increment(name: str, amount: int = 1) -> None:
    with _LOCK:
        _COUNTERS[name] += amount


def observe(name: str, duration_ms: float) -> None:
    with _LOCK:
        samples = _DURATIONS.setdefault(name, deque(maxlen=_MAX_SAMPLES))
        samples.append(max(0.0, float(duration_ms)))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return round(ordered[index], 2)


def snapshot(*, workload: dict[str, object] | None = None) -> dict[str, object]:
    with _LOCK:
        counters = dict(_COUNTERS)
        durations = {name: list(values) for name, values in _DURATIONS.items()}
    request_total = counters.get("http.total", 0)
    server_errors = sum(
        value
        for name, value in counters.items()
        if name.startswith("http.status.5")
    )
    request_p95 = _percentile(durations.get("request_ms", []), 0.95)
    llm_p95 = _percentile(durations.get("llm_ms", []), 0.95)
    ocr_p95 = _percentile(durations.get("ocr_ms", []), 0.95)
    queue_depth = 0
    if workload:
        outstanding = workload.get("outstanding", {})
        if isinstance(outstanding, dict):
            queue_depth = sum(int(value) for value in outstanding.values())
    error_rate = round(server_errors / request_total, 6) if request_total else 0.0
    thresholds = {
        "request_p95_ms": settings.alert_request_p95_ms,
        "llm_p95_ms": settings.alert_llm_p95_ms,
        "ocr_p95_ms": settings.alert_ocr_p95_ms,
        "queue_depth": settings.alert_queue_depth,
        "http_5xx_rate": settings.alert_http_5xx_rate,
    }
    alerts = []
    checks = (
        ("REQUEST_P95_HIGH", request_p95, settings.alert_request_p95_ms),
        ("LLM_P95_HIGH", llm_p95, settings.alert_llm_p95_ms),
        ("OCR_P95_HIGH", ocr_p95, settings.alert_ocr_p95_ms),
        ("QUEUE_DEPTH_HIGH", queue_depth, settings.alert_queue_depth),
        ("HTTP_5XX_RATE_HIGH", error_rate, settings.alert_http_5xx_rate),
    )
    for code, value, threshold in checks:
        if value is not None and value > threshold:
            alerts.append({"code": code, "value": value, "threshold": threshold})
    return {
        "schema_version": "observability/1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "counters": counters,
        "latency_ms": {
            name.removesuffix("_ms"): {
                "count": len(values),
                "p50": _percentile(values, 0.5),
                "p95": _percentile(values, 0.95),
            }
            for name, values in durations.items()
        },
        "queue_depth": queue_depth,
        "http_5xx_rate": error_rate,
        "thresholds": thresholds,
        "alerts": alerts,
    }


def reset_for_tests() -> None:
    with _LOCK:
        _COUNTERS.clear()
        for values in _DURATIONS.values():
            values.clear()
