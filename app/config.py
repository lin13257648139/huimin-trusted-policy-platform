from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.version import APP_VERSION

BASE_DIR = Path(__file__).resolve().parent.parent


def _model_lock(role: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads((BASE_DIR / "models.lock.json").read_text(encoding="utf-8"))
        model = payload["models"][role]
        return str(model["name"]), str(model["digest"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, None


_LOCKED_CHAT_NAME, _LOCKED_CHAT_DIGEST = _model_lock("chat")
_LOCKED_EMBED_NAME, _LOCKED_EMBED_DIGEST = _model_lock("embedding")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _policy_as_of() -> str:
    """Use the latest recorded evidence review date unless explicitly overridden."""

    configured = os.getenv("POLICY_AS_OF", "").strip()
    if configured:
        return configured
    evidence_path = BASE_DIR / "app" / "data" / "evidence.json"
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        reviewed = [item.get("reviewed_at") for item in payload if item.get("reviewed_at")]
        if reviewed:
            return max(reviewed)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return "2026-09-30"


@dataclass(frozen=True)
class Settings:
    app_name: str = "惠民智导可信政策智能平台"
    app_version: str = APP_VERSION
    environment: str = os.getenv("APP_ENV", "development")
    database_path: Path = Path(
        os.getenv("DATABASE_PATH", str(BASE_DIR / "storage" / "huimin.db"))
    )
    upload_dir: Path = Path(
        os.getenv("UPLOAD_DIR", str(BASE_DIR / "storage" / "uploads"))
    )
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
    max_image_pixels: int = int(os.getenv("MAX_IMAGE_PIXELS", "40000000"))
    max_package_files: int = int(os.getenv("MAX_PACKAGE_FILES", "12"))
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", "12"))
    max_package_bytes: int = int(os.getenv("MAX_PACKAGE_BYTES", str(32 * 1024 * 1024)))
    max_package_pages: int = int(os.getenv("MAX_PACKAGE_PAGES", "36"))
    multipart_overhead_bytes: int = int(
        os.getenv("MULTIPART_OVERHEAD_BYTES", str(1024 * 1024))
    )
    document_timeout_seconds: float = float(os.getenv("DOCUMENT_TIMEOUT_SECONDS", "30"))
    package_timeout_seconds: float = float(os.getenv("PACKAGE_TIMEOUT_SECONDS", "60"))
    max_llm_workers: int = int(os.getenv("MAX_LLM_WORKERS", "2"))
    max_document_workers: int = int(os.getenv("MAX_DOCUMENT_WORKERS", "2"))
    max_work_queue: int = int(os.getenv("MAX_WORK_QUEUE", "16"))
    upload_ttl_seconds: int = int(os.getenv("UPLOAD_TTL_SECONDS", "900"))
    data_retention_days: int = int(os.getenv("DATA_RETENTION_DAYS", "30"))
    admin_api_token: str | None = os.getenv("ADMIN_API_TOKEN")
    demo_mode: bool = _env_bool("DEMO_MODE")
    ai_mode: str = os.getenv(
        "AI_MODE",
        "ollama" if os.getenv("OLLAMA_ENABLED", "false").lower() == "true" else "deterministic",
    ).lower()
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    allow_remote_ollama: bool = _env_bool("ALLOW_REMOTE_OLLAMA")
    ollama_model: str = os.getenv("OLLAMA_MODEL", _LOCKED_CHAT_NAME or "qwen3:4b-instruct")
    ollama_model_digest: str | None = os.getenv("OLLAMA_MODEL_DIGEST", _LOCKED_CHAT_DIGEST or "") or None
    ollama_embedding_model: str | None = (
        os.getenv("OLLAMA_EMBED_MODEL", _LOCKED_EMBED_NAME or "qwen3-embedding:0.6b") or None
    )
    ollama_embedding_model_digest: str | None = (
        os.getenv("OLLAMA_EMBED_MODEL_DIGEST", _LOCKED_EMBED_DIGEST or "") or None
    )
    # 4060 笔记本首次加载 4B 模型需要十余秒，预留冷启动与 JSON 约束生成时间。
    ollama_timeout_seconds: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "true").lower() == "true"
    policy_as_of: str = _policy_as_of()
    alert_request_p95_ms: float = float(os.getenv("ALERT_REQUEST_P95_MS", "2000"))
    alert_llm_p95_ms: float = float(os.getenv("ALERT_LLM_P95_MS", "10000"))
    alert_ocr_p95_ms: float = float(os.getenv("ALERT_OCR_P95_MS", "15000"))
    alert_queue_depth: int = int(os.getenv("ALERT_QUEUE_DEPTH", "12"))
    alert_http_5xx_rate: float = float(os.getenv("ALERT_HTTP_5XX_RATE", "0.05"))

    @property
    def ollama_enabled(self) -> bool:
        """Backward-compatible flag derived from the explicit runtime mode."""

        return self.ai_mode in {"ollama", "hybrid"}

    def validate_runtime(self) -> None:
        if self.ai_mode not in {"deterministic", "ollama", "hybrid"}:
            raise RuntimeError("AI_MODE必须为 deterministic、ollama 或 hybrid")
        if not self.demo_mode and not self.admin_api_token:
            raise RuntimeError(
                "非演示模式必须设置ADMIN_API_TOKEN；本地展示请显式设置DEMO_MODE=true"
            )
        if self.environment.lower() == "production" and self.demo_mode:
            raise RuntimeError("生产环境禁止启用DEMO_MODE")
        positive_limits = {
            "MAX_UPLOAD_BYTES": self.max_upload_bytes,
            "MAX_IMAGE_PIXELS": self.max_image_pixels,
            "MAX_PACKAGE_FILES": self.max_package_files,
            "MAX_PDF_PAGES": self.max_pdf_pages,
            "MAX_PACKAGE_BYTES": self.max_package_bytes,
            "MAX_PACKAGE_PAGES": self.max_package_pages,
            "MULTIPART_OVERHEAD_BYTES": self.multipart_overhead_bytes,
            "MAX_LLM_WORKERS": self.max_llm_workers,
            "MAX_DOCUMENT_WORKERS": self.max_document_workers,
            "MAX_WORK_QUEUE": self.max_work_queue,
        }
        invalid = [name for name, value in positive_limits.items() if value <= 0]
        if invalid:
            raise RuntimeError(f"资源限制必须为正数：{', '.join(invalid)}")
        if self.max_package_bytes < self.max_upload_bytes:
            raise RuntimeError("MAX_PACKAGE_BYTES不得小于MAX_UPLOAD_BYTES")
        for name, digest in {
            "OLLAMA_MODEL_DIGEST": self.ollama_model_digest,
            "OLLAMA_EMBED_MODEL_DIGEST": self.ollama_embedding_model_digest,
        }.items():
            if digest and (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower())):
                raise RuntimeError(f"{name}必须是64位十六进制SHA-256摘要")
        if not 0 < self.alert_http_5xx_rate <= 1:
            raise RuntimeError("ALERT_HTTP_5XX_RATE必须在0和1之间")

    @property
    def static_dir(self) -> Path:
        return BASE_DIR / "app" / "static"

    @property
    def processed_data_dir(self) -> Path:
        return BASE_DIR / "data" / "processed"

    @property
    def rule_registry_path(self) -> Path:
        return self.processed_data_dir / "rule_registry.json"


settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)

