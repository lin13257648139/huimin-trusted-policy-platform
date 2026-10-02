from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class JsonModelResult:
    payload: dict[str, Any]
    provider: str
    model_id: str
    latency_ms: int
    prompt_sha256: str
    response_sha256: str


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model_id: str
    latency_ms: int


class ModelRuntimeError(RuntimeError):
    """Expected local-model failures that must trigger a visible safe fallback."""


def _request_json(path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.ollama_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelRuntimeError(f"本地模型服务不可达：{type(exc).__name__}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelRuntimeError("本地模型服务返回了无效JSON") from exc
    if not isinstance(decoded, dict):
        raise ModelRuntimeError("本地模型服务返回结构不符合约定")
    return decoded


def ollama_runtime_status(*, probe: bool = True) -> dict[str, Any]:
    configured = settings.ollama_enabled
    status: dict[str, Any] = {
        "mode": settings.ai_mode,
        "configured": configured,
        "reachable": False,
        "chat_model": settings.ollama_model if configured else None,
        "embedding_model": settings.ollama_embedding_model,
        "active_provider": "deterministic-safe-parser",
        "reason": "AI_MODE未启用本地模型",
    }
    if not configured or not probe:
        return status
    try:
        payload = _request_json("/api/tags", None, timeout=min(settings.ollama_timeout_seconds, 1.2))
        model_rows = [item for item in payload.get("models", []) if isinstance(item, dict)]
        installed = {str(item.get("name", "")) for item in model_rows}
        aliases = installed | {name.split(":", 1)[0] for name in installed}
        wanted = settings.ollama_model
        model_present = wanted in aliases or wanted.split(":", 1)[0] in aliases
        selected = next(
            (
                item
                for item in model_rows
                if str(item.get("name", "")) == wanted
                or str(item.get("name", "")).split(":", 1)[0] == wanted.split(":", 1)[0]
            ),
            None,
        )
        embedding_wanted = settings.ollama_embedding_model
        embedding_present = bool(
            embedding_wanted
            and (
                embedding_wanted in aliases
                or embedding_wanted.split(":", 1)[0] in aliases
            )
        )
        status.update(
            {
                "reachable": True,
                "model_present": model_present,
                "embedding_model_present": embedding_present,
                "model_digest": selected.get("digest") if selected else None,
                "model_size_bytes": selected.get("size") if selected else None,
                "model_details": selected.get("details") if selected else None,
                "active_provider": (
                    f"ollama/{wanted}" if model_present else "deterministic-safe-parser"
                ),
                "reason": None if model_present else "服务可达，但配置的对话模型未安装",
            }
        )
    except ModelRuntimeError as exc:
        status["reason"] = str(exc)
    return status


def chat_json(
    *,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict[str, Any],
    purpose: str,
) -> JsonModelResult:
    if not settings.ollama_enabled:
        raise ModelRuntimeError("AI_MODE未启用本地模型")
    combined = f"{purpose}\n{system_prompt}\n{user_prompt}"
    prompt_sha256 = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    request_payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": json_schema,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0, "seed": 20261002},
    }
    started = time.perf_counter()
    body = _request_json("/api/chat", request_payload, timeout=settings.ollama_timeout_seconds)
    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        raw = body["message"]["content"]
        parsed = json.loads(raw)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ModelRuntimeError("模型未返回符合约定的JSON对象") from exc
    if not isinstance(parsed, dict):
        raise ModelRuntimeError("模型输出不是JSON对象")
    raw_bytes = json.dumps(parsed, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return JsonModelResult(
        payload=parsed,
        provider="ollama-json-schema",
        model_id=settings.ollama_model,
        latency_ms=latency_ms,
        prompt_sha256=prompt_sha256,
        response_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def embed_texts(texts: list[str]) -> EmbeddingResult:
    model = settings.ollama_embedding_model
    if settings.ai_mode != "hybrid" or not model:
        raise ModelRuntimeError("未配置混合检索所需的OLLAMA_EMBED_MODEL")
    started = time.perf_counter()
    body = _request_json(
        "/api/embed",
        {"model": model, "input": texts, "truncate": True},
        timeout=settings.ollama_timeout_seconds,
    )
    vectors = body.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise ModelRuntimeError("向量模型返回数量与输入不一致")
    validated: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise ModelRuntimeError("向量模型返回了空向量")
        try:
            numeric = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise ModelRuntimeError("向量模型返回了非数值向量") from exc
        if not all(math.isfinite(value) for value in numeric):
            raise ModelRuntimeError("向量模型返回了非有限数值")
        validated.append(numeric)
    return EmbeddingResult(
        vectors=validated,
        provider="ollama-embedding",
        model_id=model,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
