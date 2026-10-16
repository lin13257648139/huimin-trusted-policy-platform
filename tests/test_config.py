from __future__ import annotations

import pytest

from app.config import Settings, _model_lock, _policy_as_of


def test_runtime_rejects_non_positive_resource_limit() -> None:
    configured = Settings(demo_mode=True, max_work_queue=0)
    with pytest.raises(RuntimeError, match="MAX_WORK_QUEUE"):
        configured.validate_runtime()


def test_runtime_rejects_package_limit_smaller_than_single_file_limit() -> None:
    configured = Settings(
        demo_mode=True,
        max_upload_bytes=8 * 1024 * 1024,
        max_package_bytes=4 * 1024 * 1024,
    )
    with pytest.raises(RuntimeError, match="MAX_PACKAGE_BYTES"):
        configured.validate_runtime()


@pytest.mark.parametrize(
    ("configured", "message"),
    [
        (Settings(demo_mode=True, ai_mode="unsupported"), "AI_MODE"),
        (Settings(demo_mode=False, admin_api_token=None), "ADMIN_API_TOKEN"),
        (Settings(environment="production", demo_mode=True), "生产环境"),
        (Settings(demo_mode=True, ollama_model_digest="bad"), "SHA-256"),
        (Settings(demo_mode=True, alert_http_5xx_rate=0), "ALERT_HTTP_5XX_RATE"),
    ],
)
def test_runtime_rejects_unsafe_configuration(configured: Settings, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        configured.validate_runtime()


def test_model_lock_and_policy_date_have_safe_fallbacks(monkeypatch) -> None:
    import app.config as config

    monkeypatch.setattr(config, "BASE_DIR", config.BASE_DIR / "does-not-exist")
    assert _model_lock("missing-role") == (None, None)
    monkeypatch.setenv("POLICY_AS_OF", "2026-10-01")
    assert _policy_as_of() == "2026-10-01"
