# Kent Beck Phase 5 — Sonnet 4.6 실행 가이드

> **목표**: 핸들러 레지스트리 통합 + Executor 분해. ~70줄 감소. 행동 변경 0.
> **워크트리**: `.claude/worktrees/kent-beck-p5` (branch `feature/kent-beck-p5`)
> **소크라틱**: 5문 통과 (2026-03-26)

---

## Pre-flight

```bash
cd .claude/worktrees/kent-beck-p5
uv run ruff check core/ tests/ && uv run mypy core/ && uv run pytest tests/ -m "not live" -q
```

모두 통과 확인 후 진행. 실패 시 main 동기화 문제 — `git pull origin main` 후 재시도.

---

## Step 5A: Delegation Handler Registry (tool_handlers.py)

### 목표

3개 빌더 함수 (`_build_delegated_handlers`, `_build_profile_handlers`, `_build_signal_handlers`)의
13개 보일러플레이트 클로저를 **데이터 테이블 + 팩토리** 1개로 통합.

### 변경 파일

| 파일 | 액션 |
|------|------|
| `core/cli/tool_handlers.py` | 수정 (팩토리 추가, 3 함수 → 1 함수) |

### 현재 코드 (삭제 대상)

**`tool_handlers.py:886-997`** — 3개 빌더 함수, 각각 동일한 패턴:

```python
# lines 886-925: _build_delegated_handlers (5 handlers)
def _build_delegated_handlers() -> dict[str, Any]:
    def handle_web_fetch(**kwargs: Any) -> dict[str, Any]:
        from core.tools.web_tools import WebFetchTool
        return _safe_delegate(WebFetchTool, kwargs)
    # ... 4 more identical closures
    return {"web_fetch": handle_web_fetch, ...}

# lines 928-961: _build_profile_handlers (4 handlers)
# lines 964-997: _build_signal_handlers (4 handlers)
```

**총 112줄** (주석 헤더 포함) → 13개 핸들러, 모두 `_safe_delegate(ToolClass, kwargs)` 패턴.

### 교체 코드

**lines 886-997 전체를 다음으로 교체:**

```python
# ---------------------------------------------------------------------------
# Handler group: Delegated tools (registry-based)
# ---------------------------------------------------------------------------

# (module_path, class_name) — lazy import + _safe_delegate
_DELEGATED_TOOLS: dict[str, tuple[str, str]] = {
    # web / document / note
    "web_fetch": ("core.tools.web_tools", "WebFetchTool"),
    "general_web_search": ("core.tools.web_tools", "GeneralWebSearchTool"),
    "read_document": ("core.tools.document_tools", "ReadDocumentTool"),
    "note_save": ("core.tools.memory_tools", "NoteSaveTool"),
    "note_read": ("core.tools.memory_tools", "NoteReadTool"),
    # profile
    "profile_show": ("core.tools.profile_tools", "ProfileShowTool"),
    "profile_update": ("core.tools.profile_tools", "ProfileUpdateTool"),
    "profile_preference": ("core.tools.profile_tools", "ProfilePreferenceTool"),
    "profile_learn": ("core.tools.profile_tools", "ProfileLearnTool"),
    # signals
    "youtube_search": ("core.tools.signal_tools", "YouTubeSearchTool"),
    "reddit_sentiment": ("core.tools.signal_tools", "RedditSentimentTool"),
    "steam_info": ("core.tools.signal_tools", "SteamInfoTool"),
    "google_trends": ("core.tools.signal_tools", "GoogleTrendsTool"),
}


def _make_delegate_handler(
    module_path: str, class_name: str,
) -> Callable[..., dict[str, Any]]:
    """Create a handler that lazily imports *module_path* and delegates to *class_name*."""

    def _handler(**kwargs: Any) -> dict[str, Any]:
        import importlib

        mod = importlib.import_module(module_path)
        tool_cls = getattr(mod, class_name)
        return _safe_delegate(tool_cls, kwargs)

    return _handler


def _build_delegated_handlers() -> dict[str, Any]:
    """Build all delegated tool handlers from the registry table."""
    return {
        name: _make_delegate_handler(mod, cls)
        for name, (mod, cls) in _DELEGATED_TOOLS.items()
    }
```

**총 ~42줄** (주석 헤더 포함). 절감: **~70줄**.

### import 확인

`Callable`이 이미 파일 상단에 import 되어 있는지 확인:

```bash
grep "from collections.abc import Callable" core/cli/tool_handlers.py
# 또는
grep "from typing import.*Callable" core/cli/tool_handlers.py
```

없으면 파일 상단 import 블록에 추가:

```python
from collections.abc import Callable
```

### _build_tool_handlers 호출 정리

**`tool_handlers.py:1183-1185`** 현재:

```python
    handlers.update(_build_delegated_handlers())
    handlers.update(_build_profile_handlers())
    handlers.update(_build_signal_handlers())
```

→ 교체:

```python
    handlers.update(_build_delegated_handlers())
```

(`_build_profile_handlers`, `_build_signal_handlers` 호출 2줄 삭제)

### 검증

```bash
cd .claude/worktrees/kent-beck-p5
uv run ruff check core/cli/tool_handlers.py
uv run mypy core/cli/tool_handlers.py
uv run pytest tests/ -m "not live" -q -x
```

### 커밋

```bash
git add core/cli/tool_handlers.py
git commit -m "refactor: delegation handler registry — 13 closures → data table + factory

Kent Beck Phase 5A: _build_delegated/profile/signal_handlers 3함수를
_DELEGATED_TOOLS 레지스트리 + _make_delegate_handler 팩토리로 통합.
행동 변경 없음, lazy import 유지.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Step 5B: _execute_single 분해 (tool_executor.py)

### 목표

86줄 모놀리스 `_execute_single`(10 책임)을 **오케스트레이터 + 2 서브메서드**로 분해.
총 줄 수는 비슷하지만 각 메서드가 단일 책임을 갖게 됨.

### 변경 파일

| 파일 | 액션 |
|------|------|
| `core/agent/tool_executor.py` | 수정 (2 메서드 추출) |

### 현재 코드 분석

**`tool_executor.py:605-690`** `_execute_single` 86줄, 10 책임:

```
L614-617: 변수 선언 + 로그
L619-633: 실행 or 복구 (failure count 체크 → recovery 또는 정상 실행)
L634-639: 실패 추적 (consecutive_failures 갱신)
L641-650: clarification 가드
L652-655: 결과 로그 (op_logger)
L657-664: transcript 기록
L666-672: tool_log append
L674-678: token guard
L680-690: JSON 직렬화 + return dict
```

### 추출 1: `_record_tool_activity`

**lines 652-672를 추출** (결과 로깅 + transcript + tool_log):

```python
def _record_tool_activity(
    self,
    tool_name: str,
    tool_input: dict[str, Any],
    result: Any,
    visible: bool,
) -> None:
    """Log result, record transcript events, and append to tool_log."""
    # Progressive log: show tool result summary (skip if already logged)
    if isinstance(result, dict):
        skip_log = result.get("skipped") or result.get("recovery_attempted")
        if not skip_log:
            self._op_logger.log_tool_result(tool_name, result, visible=visible)

    # Transcript: tool_call + tool_result events
    if self._transcript is not None:
        self._transcript.record_tool_call(tool_name, tool_input)
        status = "error" if isinstance(result, dict) and result.get("error") else "ok"
        summary = ""
        if isinstance(result, dict):
            summary = str(result.get("summary", result.get("error", "")))
        self._transcript.record_tool_result(tool_name, status, summary)

    self._tool_log.append(
        {
            "tool": tool_name,
            "input": tool_input,
            "result": result,
        }
    )
```

### 추출 2: `_serialize_tool_result`

**lines 674-690을 추출** (token guard + JSON serialize + return):

```python
def _serialize_tool_result(
    self, result: Any, block_id: str,
) -> dict[str, Any]:
    """Apply token guard and serialize result as JSON for LLM consumption."""
    # Token guard: truncate oversized results to prevent context explosion
    if isinstance(result, dict):
        model_limit = _compute_model_tool_limit(self._model) if self._model else 0
        result = _guard_tool_result(result, max_tokens=model_limit or None)

    # Serialize result as JSON for LLM (not Python repr)
    try:
        content = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        content = str(result)

    return {
        "type": "tool_result",
        "tool_use_id": block_id,
        "content": content,
    }
```

### _execute_single 최종 형태

추출 후 **~40줄** 오케스트레이터:

```python
async def _execute_single(self, block: Any) -> dict[str, Any]:
    """Execute a single tool_use block and return its processed result dict."""
    tool_name = block.name
    tool_input: dict[str, Any] = block.input

    log.info("ToolCallProcessor: tool_use %s(%s)", tool_name, tool_input)

    # Check consecutive failure count
    fail_count = self._consecutive_failures.get(tool_name, 0)

    if fail_count >= self.MAX_CONSECUTIVE_FAILURES:
        result = await self._attempt_recovery(tool_name, tool_input, fail_count)
        visible = self._op_logger.log_tool_call(tool_name, tool_input)
        self._op_logger.log_tool_result(tool_name, result, visible=visible)
    else:
        visible = self._op_logger.log_tool_call(tool_name, tool_input)
        result = await asyncio.to_thread(self._executor.execute, tool_name, tool_input)

    # Track consecutive failures
    if isinstance(result, dict) and result.get("error"):
        if not result.get("recovery_attempted"):
            self._consecutive_failures[tool_name] = fail_count + 1
    else:
        self._consecutive_failures[tool_name] = 0

    # Track clarification rounds to prevent infinite loops
    if isinstance(result, dict) and result.get("clarification_needed"):
        self._clarification_count += 1
        if self._clarification_count > self.MAX_CLARIFICATION_ROUNDS:
            result = {
                "error": (
                    "Too many clarification attempts. "
                    "Please provide all required parameters."
                ),
                "max_clarifications_exceeded": True,
            }

    self._record_tool_activity(tool_name, tool_input, result, visible)
    return self._serialize_tool_result(result, block.id)
```

### 배치 순서

1. `_execute_single` 메서드 **위에** `_record_tool_activity`와 `_serialize_tool_result`를 추가
2. `_execute_single` 본문에서 lines 652-690을 삭제하고 2줄 호출로 교체

### 검증

```bash
cd .claude/worktrees/kent-beck-p5
uv run ruff check core/agent/tool_executor.py
uv run mypy core/agent/tool_executor.py
uv run pytest tests/ -m "not live" -q -x
```

### 커밋

```bash
git add core/agent/tool_executor.py
git commit -m "refactor: _execute_single 분해 — record + serialize 서브메서드 추출

Kent Beck Phase 5B: 86줄 모놀리스를 40줄 오케스트레이터 +
_record_tool_activity + _serialize_tool_result로 분해.
행동 변경 없음, 단일 책임 원칙 적용.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Final: E2E + 품질 게이트

```bash
cd .claude/worktrees/kent-beck-p5
uv run ruff check core/ tests/        # 0 errors
uv run ruff format --check core/ tests/  # clean
uv run mypy core/                      # 0 errors
uv run pytest tests/ -m "not live" -q  # 3224+ pass
uv run geode analyze "Cowboy Bebop" --dry-run  # A (68.4)
```

---

## 체크리스트

- [ ] Step 5A: `_DELEGATED_TOOLS` 레지스트리 + `_make_delegate_handler` 팩토리
- [ ] Step 5A: `_build_profile_handlers`, `_build_signal_handlers` 삭제
- [ ] Step 5A: `_build_tool_handlers` 호출 2줄 삭제
- [ ] Step 5A: lint/type/test 통과 → 커밋
- [ ] Step 5B: `_record_tool_activity` 추출
- [ ] Step 5B: `_serialize_tool_result` 추출
- [ ] Step 5B: `_execute_single` 본문 축소 (86→~40줄)
- [ ] Step 5B: lint/type/test 통과 → 커밋
- [ ] E2E dry-run 검증 A (68.4)
- [ ] PR 생성: feature/kent-beck-p5 → main

## 위험 요소

| 위험 | 완화 |
|------|------|
| `_make_delegate_handler`가 importlib 사용 → 기존 직접 import와 동작 차이? | 없음. 기존도 함수 내 lazy import. importlib.import_module은 동일 메커니즘 |
| `_DELEGATED_TOOLS`에서 오타 | 13개 핸들러 모두 기존 테스트에서 커버됨 (tools/ 개별 테스트) |
| `_record_tool_activity`에서 `visible` 인자 누락 | 시그니처에 명시. mypy가 잡아줌 |
| 다른 워크트리(task-tools)와 충돌 | tool_handlers.py 수정 범위 겹침 가능. 먼저 머지하는 쪽이 우선, 후속은 rebase |
