from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: Path
    line: int
    message: str


def _call_name(node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def scan_file(path: Path) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [Finding("parse-error", path, 1, str(exc))]
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in {"eval", "exec", "builtins.eval", "builtins.exec"}:
            findings.append(
                Finding("huimin-no-eval-exec", path, node.lineno, "dynamic eval/exec")
            )
        if name.startswith("subprocess.") and any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        ):
            findings.append(
                Finding("huimin-no-shell-true", path, node.lineno, "subprocess shell=True")
            )
        if name in {"pickle.load", "pickle.loads"}:
            findings.append(
                Finding("huimin-no-unsafe-pickle", path, node.lineno, "unsafe pickle load")
            )
        http_methods = {
            f"{library}.{method}"
            for library in ("requests", "httpx")
            for method in ("get", "post", "put", "patch", "delete", "request", "stream")
        }
        if name in http_methods and not any(
            keyword.arg == "timeout" for keyword in node.keywords
        ):
            findings.append(
                Finding(
                    "huimin-http-must-have-timeout",
                    path,
                    node.lineno,
                    "external HTTP call without explicit timeout",
                )
            )
    return findings


def scan_paths(paths: list[Path]) -> list[Finding]:
    files: list[Path] = []
    for path in paths:
        files.extend(path.rglob("*.py") if path.is_dir() else [path])
    return [finding for path in sorted(set(files)) for finding in scan_file(path)]


def main() -> None:
    targets = [Path(argument) for argument in sys.argv[1:]] or [Path("app"), Path("scripts")]
    findings = scan_paths(targets)
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.rule_id}: {finding.message}")
    if findings:
        raise SystemExit(f"STATIC_SECURITY_POLICY_FAILED findings={len(findings)}")
    print(f"STATIC_SECURITY_POLICY_OK targets={len(targets)} findings=0")


if __name__ == "__main__":
    main()
