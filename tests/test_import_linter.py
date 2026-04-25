"""Bug class B2 + B8 — process binding 강제 (정적 import 검증).

``pyproject.toml`` 의 ``[tool.importlinter]`` contracts 가 다음을 강제한다:

  1. core.cli ↛ core.server, core.channels (CLI 가 daemon 의존 금지)
  2. core.agent ↛ core.cli, core.server (agent loop 은 process-pure)
  3. core.server ↛ core.cli (server 는 agent 만 host, CLI 모름)
  4. core.channels ↛ core.cli, core.server, core.agent (외부 IO 추상화 순수)

Pre-v0.52 결함이었던 "/login oauth ... 가 daemon RPC 로 가서 OAuth UI 안 보임"
같은 process binding 위반은 PR 단계에서 lint-imports 로 즉시 차단된다.

이 테스트가 RED → 새 import 가 process boundary 를 위반함. ignore_imports 로
임시 등록하지 말고 (a) 모듈을 올바른 디렉토리로 이동하거나 (b) 의존을 인터페이스
경유로 뒤집을 것.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


def test_lint_imports_passes() -> None:
    """``uv run lint-imports`` invariant — 4 contracts 모두 통과해야 한다."""
    if shutil.which("lint-imports") is None and shutil.which("uv") is None:
        pytest.skip("import-linter not available in this environment")

    # `uv run` 환경에서 호출. CI 와 동일 명령.
    uv_path = shutil.which("uv") or "/usr/bin/uv"
    result = subprocess.run(  # noqa: S603 — fixed args, dev tool
        [uv_path, "run", "lint-imports"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "import-linter contracts violated. Either move the module to the right "
        "process boundary, or invert the dependency through an interface in "
        "core.shared/.\n\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
