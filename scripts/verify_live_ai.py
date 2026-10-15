from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ai_runtime import (  # noqa: E402
    ModelRuntimeError,
    chat_json,
    embed_texts,
    ollama_runtime_status,
)
from app.version import APP_VERSION  # noqa: E402

OUTPUT = ROOT / "data" / "evaluation" / "live_ai_smoke_report.json"
SMOKE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status"],
    "properties": {"status": {"type": "string", "enum": ["ok"]}},
}


def main() -> None:
    runtime = ollama_runtime_status(probe=True)
    blockers = []
    if runtime.get("mode") != "hybrid":
        blockers.append("AI_MODE必须为hybrid")
    if not runtime.get("reachable"):
        blockers.append("Ollama服务不可达")
    if not runtime.get("model_present"):
        blockers.append("配置的对话模型未安装")
    if not runtime.get("embedding_model_present"):
        blockers.append("配置的向量模型未安装")
    if blockers:
        raise SystemExit("LIVE_AI_GATE_FAILED: " + "；".join(blockers))

    try:
        chat = chat_json(
            system_prompt="只返回符合JSON Schema的健康检查结果。",
            user_prompt='返回 {"status":"ok"}',
            json_schema=SMOKE_SCHEMA,
            purpose="competition-live-ai-smoke/v1",
        )
        embedding = embed_texts(["社会救助政策", "最低生活保障申请"])
    except ModelRuntimeError as exc:
        raise SystemExit(f"LIVE_AI_GATE_FAILED: {exc}") from exc
    if chat.payload != {"status": "ok"}:
        raise SystemExit("LIVE_AI_GATE_FAILED: 对话模型未返回约定负载")
    dimensions = {len(vector) for vector in embedding.vectors}
    if len(dimensions) != 1 or not dimensions or next(iter(dimensions)) <= 0:
        raise SystemExit("LIVE_AI_GATE_FAILED: 向量维度不一致或为空")
    if not all(math.isfinite(value) for vector in embedding.vectors for value in vector):
        raise SystemExit("LIVE_AI_GATE_FAILED: 向量包含非有限值")

    report = {
        "report_schema": "live-ai-smoke/1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": APP_VERSION,
        "runtime": runtime,
        "chat": {
            "provider": chat.provider,
            "model_id": chat.model_id,
            "latency_ms": chat.latency_ms,
            "prompt_sha256": chat.prompt_sha256,
            "response_sha256": chat.response_sha256,
            "schema_payload": chat.payload,
        },
        "embedding": {
            "provider": embedding.provider,
            "model_id": embedding.model_id,
            "latency_ms": embedding.latency_ms,
            "vectors": len(embedding.vectors),
            "dimensions": next(iter(dimensions)),
        },
        "claim_boundary": (
            "这只证明本机配置的对话与向量模型在该时间点完成真实推理；"
            "不代表业务准确率，完整指标仍以版本化AI评测报告为准。"
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "LIVE_AI_GATE_OK "
        f"chat={chat.model_id} embedding={embedding.model_id} dimensions={next(iter(dimensions))}"
    )


if __name__ == "__main__":
    main()
