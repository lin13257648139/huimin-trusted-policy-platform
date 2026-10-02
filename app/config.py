from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.version import APP_VERSION


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_name: str = "惠民智导"
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
    upload_ttl_seconds: int = int(os.getenv("UPLOAD_TTL_SECONDS", "900"))
    data_retention_days: int = int(os.getenv("DATA_RETENTION_DAYS", "30"))
    admin_api_token: str | None = os.getenv("ADMIN_API_TOKEN")
    ai_mode: str = os.getenv(
        "AI_MODE",
        "ollama" if os.getenv("OLLAMA_ENABLED", "false").lower() == "true" else "deterministic",
    ).lower()
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
    ollama_embedding_model: str | None = (
        os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b") or None
    )
    # 4060 笔记本首次加载 4B 模型需要十余秒，预留冷启动与 JSON 约束生成时间。
    ollama_timeout_seconds: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "true").lower() == "true"
    policy_as_of: str = "2026-09-30"

    @property
    def ollama_enabled(self) -> bool:
        """Backward-compatible flag derived from the explicit runtime mode."""

        return self.ai_mode in {"ollama", "hybrid"}

    def validate_runtime(self) -> None:
        if self.ai_mode not in {"deterministic", "ollama", "hybrid"}:
            raise RuntimeError("AI_MODE必须为 deterministic、ollama 或 hybrid")
        if self.environment.lower() == "production" and not self.admin_api_token:
            raise RuntimeError("生产环境必须设置ADMIN_API_TOKEN，治理接口不允许无鉴权启动")

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

