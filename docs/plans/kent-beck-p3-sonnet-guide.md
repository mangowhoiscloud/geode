# Kent Beck Phase 3 — CLI God Object 분해 (Sonnet 실행 가이드)

> 이 플랜은 Sonnet이 순차적으로 실행할 수 있도록 각 단계의 정확한 파일/라인/코드를 명시합니다.
> 워크트리: `.claude/worktrees/kent-beck-p3` (이미 할당됨, `feature/kent-beck-p3` 브랜치)

## 전제 조건
- Phase 1 (#462), Phase 2 (#463) 머지 완료
- `cli/__init__.py` 현재 1798줄
- 모든 변경은 워크트리에서 수행

---

## Step 3A: _ResultCache + 세션 상태 → session_state.py

### 새 파일 생성: `core/cli/session_state.py`

`core/cli/__init__.py`의 **108-221줄**을 새 파일로 이동:

```python
"""Session state management — ContextVars, ResultCache, accessors.

Extracted from cli/__init__.py to reduce God Object (Kent Beck Phase 3).
"""

from __future__ import annotations

import json as _json
import logging
import threading
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

log = logging.getLogger(__name__)

# Thread-safe singletons for REPL session via contextvars
_search_engine_ctx: ContextVar[Any] = ContextVar("search_engine", default=None)
_readiness_ctx: ContextVar[Any] = ContextVar("readiness", default=None)
_scheduler_service_ctx: ContextVar[Any] = ContextVar("scheduler_service", default=None)

# Multi-IP LRU analysis result cache
_RESULT_CACHE_DIR = Path(".geode/result_cache")
_RESULT_CACHE_MAX = 8


class _ResultCache:
    # ... (lines 122-185 그대로 복사)


_result_cache = _ResultCache()


def _get_search_engine():
    # ... (lines 190-196 그대로 복사, IPSearchEngine lazy import)


def _get_readiness():
    # ... (lines 199-201)


def _set_readiness(report):
    # ... (lines 204-206)


def _get_last_result():
    # ... (lines 209-215)


def _set_last_result(result):
    # ... (lines 218-220)
```

**주의**: `IPSearchEngine`과 `ReadinessReport` import는 lazy로 유지 (TYPE_CHECKING 또는 함수 내부 import).

### `cli/__init__.py` 수정

108-221줄 블록을 다음으로 교체:

```python
from core.cli.session_state import (
    _get_last_result,
    _get_readiness,
    _get_search_engine,
    _readiness_ctx,
    _result_cache,
    _scheduler_service_ctx,
    _search_engine_ctx,
    _set_last_result,
    _set_readiness,
)
```

### 검증
- `_scheduler_service_ctx`가 `__init__.py`에서 직접 사용되는지 grep으로 확인
- `_result_cache`가 `__init__.py`에서 직접 참조되는지 확인
- 예상 줄 감소: ~115줄

---

## Step 3B: cmd_schedule → cmd_schedule.py

### 새 파일 생성: `core/cli/cmd_schedule.py`

`core/cli/commands.py`의 `cmd_schedule()` 함수 (729-917줄, 188줄)를 추출.

```python
"""Schedule command — extracted from commands.py (Kent Beck Phase 3)."""

from __future__ import annotations
# cmd_schedule에 필요한 import만 가져옴
```

### `commands.py` 수정

```python
from core.cli.cmd_schedule import cmd_schedule as cmd_schedule  # re-export
```

기존 `COMMAND_MAP`에서 `cmd_schedule` 참조는 re-export로 자동 해결.

### 검증
- `cmd_schedule`가 `COMMAND_MAP`에 있는지 확인
- 다른 곳에서 `from core.cli.commands import cmd_schedule` 하는 곳 grep
- 예상 줄 감소: ~190줄 commands.py에서

---

## Step 3C: (선택) _handle_command → command_dispatch.py

**규모가 크므로 시간이 부족하면 3A + 3B만으로 PR 올려도 됩니다.**

### 새 파일 생성: `core/cli/command_dispatch.py`

`core/cli/__init__.py`의 `_handle_command()` (356-549줄, 195줄) + `_handle_memory_action()` (567-694줄, 129줄) 추출.

### `cli/__init__.py` 수정

```python
from core.cli.command_dispatch import _handle_command, _handle_memory_action
```

### 주의사항
- `_handle_command`는 많은 lazy import (`cmd_key`, `cmd_model`, `cmd_auth` 등)를 내부에서 사용
- 이 함수의 인자가 `skill_registry`, `mcp_manager`를 받으므로 시그니처 그대로 유지
- `console`, `_get_readiness`, `_set_readiness` 등을 import해야 함

### 검증
- 예상 줄 감소: ~325줄 __init__.py에서

---

## 품질 게이트 (매 Step 후)

```bash
cd /Users/mango/workspace/geode/.claude/worktrees/kent-beck-p3
uv run ruff check core/ tests/
uv run ruff format --check core/ tests/
uv run mypy core/
uv run python -m pytest tests/ -m "not live" -q  # 3224+ pass
```

## 커밋 + PR

```bash
cd /Users/mango/workspace/geode/.claude/worktrees/kent-beck-p3
git add core/cli/session_state.py core/cli/__init__.py core/cli/commands.py core/cli/cmd_schedule.py
# (command_dispatch.py도 포함 시)
git commit -m "refactor: Phase 3 — CLI God Object 분해 (session_state + cmd_schedule 추출)

_ResultCache + 세션 상태 → session_state.py (~115줄 추출)
cmd_schedule → cmd_schedule.py (~190줄 추출)
행동 변경 없음. re-export로 하위 호환.

품질 게이트: lint 0, type 0, 3224+ passed.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

git push -u origin feature/kent-beck-p3
gh pr create --base main --title "refactor: Kent Beck Phase 3 — CLI God Object 분해" --body "$(cat <<'EOF'
## Summary
- _ResultCache + 세션 상태 → session_state.py (~115줄 추출)
- cmd_schedule → cmd_schedule.py (~190줄 추출)

## Why
Kent Beck Rule 2 (Reveals Intent). cli/__init__.py 1798줄 God Object에서
세션 상태와 스케줄 커맨드를 독립 모듈로 분리.

## Test plan
- [x] lint 0, format clean
- [x] type 0
- [x] 3224+ passed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
"
```

CI 통과 후: `gh pr merge <PR번호> --squash`
