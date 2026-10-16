from __future__ import annotations

from pathlib import Path

from scripts.build_release_manifest import canonical_source_bytes


def test_text_fingerprint_is_stable_across_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "ok": true\n}\n')
    crlf.write_bytes(b'{\r\n  "ok": true\r\n}\r\n')
    assert canonical_source_bytes(lf) == canonical_source_bytes(crlf)


def test_binary_fingerprint_preserves_original_bytes(tmp_path: Path) -> None:
    payload = tmp_path / "evidence.pdf"
    payload.write_bytes(b"%PDF\r\nraw\r\n%%EOF")
    assert canonical_source_bytes(payload) == b"%PDF\r\nraw\r\n%%EOF"
