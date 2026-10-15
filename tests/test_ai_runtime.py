from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import ai_runtime
from app.services.ai_runtime import ModelRuntimeError


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _runtime_settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "ai_mode": "hybrid",
        "ollama_enabled": True,
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_model": "qwen3:4b-instruct",
        "ollama_embedding_model": "qwen3-embedding:0.6b",
        "ollama_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/model",
        "not-a-url",
        "http://user:secret@127.0.0.1:11434",  # pragma: allowlist secret
    ],
)
def test_request_json_rejects_unsafe_runtime_urls(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings(ollama_url=url))
    with pytest.raises(ModelRuntimeError, match="HTTP|用户名"):
        ai_runtime._request_json("/api/tags", None, timeout=1)


def test_request_json_uses_bounded_http_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())
    observed: dict[str, object] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        observed.update(url=request.full_url, method=request.method, timeout=timeout)
        return _Response(b'{"models": []}')

    monkeypatch.setattr(ai_runtime.urllib.request, "urlopen", fake_urlopen)
    assert ai_runtime._request_json("/api/tags", None, timeout=1.25) == {"models": []}
    assert observed == {
        "url": "http://127.0.0.1:11434/api/tags",
        "method": "GET",
        "timeout": 1.25,
    }


@pytest.mark.parametrize(
    ("body", "message"),
    [(b"not-json", "无效JSON"), (b"[]", "结构不符合约定")],
)
def test_request_json_rejects_invalid_response(
    monkeypatch: pytest.MonkeyPatch, body: bytes, message: str
) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())
    monkeypatch.setattr(
        ai_runtime.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(body),
    )
    with pytest.raises(ModelRuntimeError, match=message):
        ai_runtime._request_json("/api/tags", None, timeout=1)


def test_request_json_normalizes_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())

    def fail(*_args: object, **_kwargs: object) -> _Response:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(ai_runtime.urllib.request, "urlopen", fail)
    with pytest.raises(ModelRuntimeError, match="服务不可达"):
        ai_runtime._request_json("/api/tags", None, timeout=1)


def test_runtime_status_reports_installed_chat_and_embedding_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())
    monkeypatch.setattr(
        ai_runtime,
        "_request_json",
        lambda *_args, **_kwargs: {
            "models": [
                {
                    "name": "qwen3:4b-instruct",
                    "digest": "digest-1",
                    "size": 123,
                    "details": {"family": "qwen3"},
                },
                {"name": "qwen3-embedding:0.6b"},
            ]
        },
    )
    status = ai_runtime.ollama_runtime_status()
    assert status["reachable"] is True
    assert status["model_present"] is True
    assert status["embedding_model_present"] is True
    assert status["model_digest"] == "digest-1"
    assert status["active_provider"] == "ollama/qwen3:4b-instruct"


def test_runtime_status_preserves_safe_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())

    def fail(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise ModelRuntimeError("offline")

    monkeypatch.setattr(ai_runtime, "_request_json", fail)
    status = ai_runtime.ollama_runtime_status()
    assert status["reachable"] is False
    assert status["active_provider"] == "deterministic-safe-parser"
    assert status["reason"] == "offline"


def test_runtime_status_can_skip_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings(ollama_enabled=False))
    status = ai_runtime.ollama_runtime_status(probe=False)
    assert status["configured"] is False
    assert status["reachable"] is False


def test_chat_json_returns_auditable_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())
    captured: dict[str, Any] = {}

    def fake_request(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        captured.update(path=path, payload=payload, timeout=timeout)
        return {"message": {"content": json.dumps({"answer": "ok"})}}

    monkeypatch.setattr(ai_runtime, "_request_json", fake_request)
    result = ai_runtime.chat_json(
        system_prompt="system",
        user_prompt="user",
        json_schema={"type": "object"},
        purpose="test",
    )
    assert result.payload == {"answer": "ok"}
    assert result.provider == "ollama-json-schema"
    assert len(result.prompt_sha256) == 64
    assert len(result.response_sha256) == 64
    assert captured["path"] == "/api/chat"
    assert captured["payload"]["options"] == {"temperature": 0, "seed": 20261002}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": {"content": "not-json"}},
        {"message": {"content": "[]"}},
    ],
)
def test_chat_json_rejects_non_object_output(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())
    monkeypatch.setattr(ai_runtime, "_request_json", lambda *_args, **_kwargs: body)
    with pytest.raises(ModelRuntimeError, match="JSON对象"):
        ai_runtime.chat_json(
            system_prompt="system",
            user_prompt="user",
            json_schema={"type": "object"},
            purpose="test",
        )


def test_chat_json_requires_enabled_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings(ollama_enabled=False))
    with pytest.raises(ModelRuntimeError, match="AI_MODE"):
        ai_runtime.chat_json(
            system_prompt="system",
            user_prompt="user",
            json_schema={"type": "object"},
            purpose="test",
        )


def test_embed_texts_validates_and_returns_numeric_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())
    monkeypatch.setattr(
        ai_runtime,
        "_request_json",
        lambda *_args, **_kwargs: {"embeddings": [[1, "2.5"], [3.0, 4.0]]},
    )
    result = ai_runtime.embed_texts(["a", "b"])
    assert result.vectors == [[1.0, 2.5], [3.0, 4.0]]
    assert result.provider == "ollama-embedding"


@pytest.mark.parametrize(
    ("embeddings", "message"),
    [
        ([[1.0]], "数量"),
        ([[]], "空向量"),
        ([["bad"]], "非数值"),
        ([[float("inf")]], "非有限"),
    ],
)
def test_embed_texts_rejects_invalid_vectors(
    monkeypatch: pytest.MonkeyPatch, embeddings: object, message: str
) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings())
    monkeypatch.setattr(
        ai_runtime,
        "_request_json",
        lambda *_args, **_kwargs: {"embeddings": embeddings},
    )
    input_texts = ["a", "b"] if message == "数量" else ["a"]
    with pytest.raises(ModelRuntimeError, match=message):
        ai_runtime.embed_texts(input_texts)


@pytest.mark.parametrize(
    "settings_override",
    [
        {"ai_mode": "deterministic"},
        {"ollama_embedding_model": None},
    ],
)
def test_embed_texts_requires_hybrid_mode_and_model(
    monkeypatch: pytest.MonkeyPatch, settings_override: dict[str, object]
) -> None:
    monkeypatch.setattr(ai_runtime, "settings", _runtime_settings(**settings_override))
    with pytest.raises(ModelRuntimeError, match="混合检索"):
        ai_runtime.embed_texts(["a"])
