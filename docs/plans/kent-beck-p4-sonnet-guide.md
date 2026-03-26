# Kent Beck Phase 4 — runtime.py + agentic_loop.py 추출 (Sonnet 실행 가이드)

> Phase 3 완료 후 실행. 워크트리 새로 할당 필요.

## Step 4A: _build_automation 훅 와이어링 추출

### 현재 상태
`core/runtime.py`의 `GeodeRuntime._build_automation()` (574-791줄, 211줄).
이 중 훅 와이어링이 ~115줄 (665-777줄).

### 작업
1. 같은 파일 내에 `_wire_automation_hooks()` 함수 추출:

```python
@staticmethod
def _wire_automation_hooks(
    hooks: HookSystemPort,
    *,
    snapshot_manager: Any,
    drift_detector: Any,
    trigger_manager: Any,
    outcome_tracker: Any,
    session_key: str,
    ip_name: str,
    project_memory: Any,
) -> None:
    """Wire L4.5 automation event handlers to the hook system."""
    # 665-777줄의 hook registration 코드를 여기로 이동
```

2. `_build_automation()` 끝에서 호출:
```python
cls._wire_automation_hooks(
    hooks,
    snapshot_manager=snapshot_manager,
    drift_detector=drift_detector,
    ...
)
```

### 검증
- `_build_automation()` 211줄 → ~100줄
- 품질 게이트 4종 통과

---

## Step 4B: MCP 어댑터 빌더 제네릭화

### 현재 상태
`_build_signal_adapter()` (852-898줄), `_build_notification_adapter()` (900-941줄), `_build_calendar_adapter()` (943-986줄) — 3곳 동일 패턴.

### 작업
1. 제네릭 헬퍼 추출:

```python
@staticmethod
def _build_mcp_composite_adapter(
    adapter_configs: list[tuple[type, str, str]],  # (AdapterClass, mcp_server, tool_prefix)
    composite_class: type,
    setter_fn: Callable,
    plugin_name: str,
) -> None:
    """Generic MCP composite adapter builder."""
    try:
        from core.mcp.manager import get_mcp_manager
        manager = get_mcp_manager()
    except Exception:
        _register_plugin(plugin_name, lambda: None)
        return

    adapters = []
    for cls, server, prefix in adapter_configs:
        try:
            adapters.append(cls(mcp_manager=manager))
        except Exception:
            pass

    if adapters:
        composite = composite_class(adapters)
        if composite.is_available():
            setter_fn(composite)
            log.info("Plugin %s: %d adapters", plugin_name, len(adapters))
```

2. 3곳을 헬퍼 호출로 교체:
```python
cls._build_mcp_composite_adapter(
    adapter_configs=[
        (YouTubeMCPSignalAdapter, "youtube", "youtube"),
        (RedditMCPSignalAdapter, "reddit", "reddit"),
        ...
    ],
    composite_class=CompositeSignalAdapter,
    setter_fn=set_signal_adapter,
    plugin_name="signal_adapter",
)
```

### 검증
- 3개 메서드 각 ~45줄 → 각 ~10줄 호출
- 품질 게이트 통과

---

## Step 4C: arun() 결과 생성 중복 제거

### 현재 상태
`core/agent/agentic_loop.py`의 `arun()` (349-567줄).
결과 생성 패턴이 3곳에서 반복:

```python
# 패턴 (natural end, convergence break, max rounds)
result = AgenticResult(text=..., tool_calls=..., rounds=...)
if self._transcript:
    self._transcript.record_result(...)
self._save_checkpoint(...)
return result
```

### 작업
1. `_make_result()` 헬퍼 메서드 추출:

```python
def _make_result(
    self,
    text: str,
    tool_calls: list,
    rounds: int,
    reason: str,
    error: str | None = None,
) -> AgenticResult:
    """Build AgenticResult + transcript + checkpoint (DRY)."""
    result = AgenticResult(text=text, tool_calls=tool_calls, rounds=rounds)
    if self._transcript:
        self._transcript.record_result(result, reason=reason)
    self._save_checkpoint(result)
    return result
```

2. 3곳을 `self._make_result(...)` 호출로 교체.

### 검증
- `arun()` ~60줄 감소
- 품질 게이트 통과

---

## 워크트리 할당

```bash
git fetch origin
git worktree add .claude/worktrees/kent-beck-p4 -b feature/kent-beck-p4 origin/main
echo "session=$(date -Iseconds) task_id=kent-beck-p4" > .claude/worktrees/kent-beck-p4/.owner
```

## 커밋 + PR

```bash
cd /Users/mango/workspace/geode/.claude/worktrees/kent-beck-p4
git add core/runtime.py core/agent/agentic_loop.py
git commit -m "refactor: Phase 4 — runtime 훅 추출 + MCP 팩토리 + arun 결과 DRY

_wire_automation_hooks() 추출 (~115줄 → 별도 메서드)
MCP 어댑터 빌더 제네릭화 (3곳 → 1 헬퍼)
_make_result() 추출 (3곳 결과 생성 → 1 메서드)

행동 변경 없음. 품질 게이트: lint 0, type 0, 3224+ passed.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

git push -u origin feature/kent-beck-p4
gh pr create --base main --title "refactor: Kent Beck Phase 4 — runtime + agentic_loop 추출" --body "$(cat <<'EOF'
## Summary
- _wire_automation_hooks() 추출 (runtime.py ~115줄 감소)
- MCP 어댑터 빌더 제네릭화 (3곳 → 1 헬퍼, ~90줄 감소)
- _make_result() 추출 (agentic_loop.py ~60줄 감소)

## Why
Kent Beck Rule 3 (No Duplication) + Rule 2 (Reveals Intent).
_build_automation 211줄 → ~100줄, MCP 빌더 3x → 1 헬퍼.

## Test plan
- [x] lint 0, format clean, type 0
- [x] 3224+ passed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
"
```

## 칸반 갱신 (main에서)

Phase 3 Done + Phase 4 Done 후:
```bash
# progress.md에서 In Progress → Done 이동
# Backlog에서 kent-beck-p3, kent-beck-p4 strikethrough
```

## 최종 동기화

```bash
cd /Users/mango/workspace/geode
git worktree remove --force .claude/worktrees/kent-beck-p4
git stash && git pull origin main && git stash pop
uv sync
kill $(pgrep -f "geode serve") 2>/dev/null
sleep 1
uv run geode serve &
```
