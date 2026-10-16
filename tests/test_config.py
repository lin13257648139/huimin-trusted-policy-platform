from __future__ import annotations

import pytest

from app.config import Settings


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
