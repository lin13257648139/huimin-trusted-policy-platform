from pathlib import Path

from scripts.static_security_policy import scan_file


def test_static_policy_detects_all_local_rules(tmp_path: Path) -> None:
    sample = tmp_path / "unsafe.py"
    sample.write_text(
        """
import pickle
import subprocess
import requests

eval('1 + 1')
subprocess.run(['cmd'], shell=True)
pickle.loads(b'data')
requests.get('https://example.invalid')
""",
        encoding="utf-8",
    )
    assert {item.rule_id for item in scan_file(sample)} == {
        "huimin-no-eval-exec",
        "huimin-no-shell-true",
        "huimin-no-unsafe-pickle",
        "huimin-http-must-have-timeout",
    }


def test_static_policy_accepts_timeout_and_safe_process(tmp_path: Path) -> None:
    sample = tmp_path / "safe.py"
    sample.write_text(
        "import subprocess\nimport httpx\nsubprocess.run(['tool'], check=True)\n"
        "httpx.get('https://example.invalid', timeout=5)\n",
        encoding="utf-8",
    )
    assert scan_file(sample) == []
