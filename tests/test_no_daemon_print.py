"""Bug class B1 — daemon-side native I/O 금지.

OAuth device-code flow가 IPC 모드에서 안 보이던 v0.51.0 버그(`oauth_login.py`
9개 print)와 동일 패턴이 재발하지 않도록 강제한다.

규칙: ``DAEMON_DIRS`` 안의 .py 파일은 native ``print()`` / ``input()`` /
``rich.console.Console()`` 직접 인스턴스화 금지. 사용해야 한다면 같은 줄에
``# allow-direct-io: <reason>`` 주석 필요.

이 테스트가 RED → daemon에서 실행되는 코드가 thin client에 도달 못 하는
출력을 만들고 있다. 즉시 IPC event 또는 ``ui/agentic_ui.py`` 의 ``emit_*``
로 전환해야 한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# v0.52.x phase 0 시점에는 cli/, gateway/, runtime_wiring/ 가 아직 daemon-side
# 코드를 포함하므로 검사 대상 추가. phase 진행하며 정리되면 목록 갱신.
DAEMON_DIRS = [
    "core/agent",
    "core/auth",
    "core/automation",
    "core/gateway",  # phase 4에서 server/, channels/ 로 분해 후 제거
    "core/hooks",
    "core/lifecycle",  # phase 1 — runtime_wiring/ rename 결과
    "core/llm",
    "core/mcp",
    "core/memory",
    "core/orchestration",
    "core/skills",
    "core/tools",
    "core/verification",
]
# Phase 4 이후 추가될 예정:
#   "core/server", "core/channels", "core/scheduler"
# Phase 5 이후:
#   "core/config"


_FORBIDDEN_CALL_NAMES = {
    "print": "native print() — use ui.agentic_ui.emit_* or logging",
    "input": "native input() — use IPC confirm event or thin-client gate",
}

# Allow tools/scripts that explicitly opt out via line comment.
_ALLOW_RE = re.compile(r"#\s*allow-direct-io")
# Inline `Console()` instantiation pattern — easier to spot via regex than AST
# because of the rich.console.Console attribute chain.
_DIRECT_CONSOLE_RE = re.compile(r"\brich\.console\.Console\s*\(\s*\)")
# Bare `Console()` after `from rich.console import Console` — also bad.
_BARE_CONSOLE_RE = re.compile(r"^\s*[A-Za-z_]\w*\s*=\s*Console\s*\(\s*\)")

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _line_is_allowed(text_lines: list[str], lineno: int) -> bool:
    """A violating line carries a `# allow-direct-io: <reason>` annotation."""
    if 1 <= lineno <= len(text_lines):
        return bool(_ALLOW_RE.search(text_lines[lineno - 1]))
    return False


def _scan(dir_path: Path) -> list[str]:
    """AST-walk every .py — match real call sites only, not docstring examples."""
    violations: list[str] = []
    for path in sorted(dir_path.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError):
            continue
        text_lines = text.splitlines()
        rel = path.relative_to(_REPO_ROOT)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Direct call: print(...), input(...)
                if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALL_NAMES:
                    if _line_is_allowed(text_lines, node.lineno):
                        continue
                    violations.append(
                        f"{rel}:{node.lineno} — {_FORBIDDEN_CALL_NAMES[func.id]}"
                    )

        # Regex pass for `Console()` patterns (AST overkill for attr chains)
        for ln, line in enumerate(text_lines, 1):
            if _line_is_allowed(text_lines, ln):
                continue
            if _DIRECT_CONSOLE_RE.search(line) or _BARE_CONSOLE_RE.match(line):
                violations.append(
                    f"{rel}:{ln} — direct Console() — use core.ui.console or emit_*"
                )
    return violations


def test_daemon_modules_avoid_native_io() -> None:
    all_violations: list[str] = []
    for d in DAEMON_DIRS:
        dir_path = _REPO_ROOT / d
        if not dir_path.exists():
            continue
        all_violations.extend(_scan(dir_path))
    assert not all_violations, (
        "Daemon-side modules contain native print()/input()/Console() — these never reach "
        "thin-client REPL via IPC. Convert to emit_* events in core.ui.agentic_ui or annotate "
        "with `# allow-direct-io: <reason>`.\n\n" + "\n".join(all_violations)
    )
