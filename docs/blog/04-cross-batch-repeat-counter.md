# 터미널 폭주 방지 — 순차 도구 호출의 Cross-Batch Repeat Counter

> Date: 2026-03-30 | Author: geode-team | Tags: CLI, UX, event-rendering, tool-tracker, ANSI

## 목차
1. 문제: 같은 도구가 19번 찍힌다
2. 원인 분석: Batch 단위 렌더링의 한계
3. Repeat Counter 설계
4. 상태 머신: onset → accumulate → flush
5. 정리

---

## 1. 문제: 같은 도구가 19번 찍힌다

AgenticLoop가 "현재 상태를 점검하라"는 요청을 받으면, 여러 라운드에 걸쳐 `check_status`, `memory_search`, `task_list`를 반복 호출합니다. 각 호출은 독립된 tool_start → tool_end 배치입니다.

```
  ✓ check_status → ok (0.2s)
  ✢ claude-opus-4-6 · ↓47.8k ↑148 · $0.2425
  ✓ check_status → ok (0.2s)
  ✢ claude-opus-4-6 · ↓48.1k ↑152 · $0.2430
  ✓ memory_search → # GEODE Project Memory... (0.2s)
  ✢ claude-opus-4-6 · ↓48.5k ↑160 · $0.2445
  ✓ memory_search → # GEODE Project Memory... (0.2s)
  ... (19회 반복)
```

도구 이름, 결과, 토큰 사용량이 모두 같은데 19줄이 찍힙니다. 정보량은 제로에 가깝지만 터미널 스크롤은 빠르게 소진됩니다.

## 2. 원인 분석: Batch 단위 렌더링의 한계

GEODE의 tool 렌더링은 `ToolCallTracker`(배치 내)와 `EventRenderer`(배치 간)로 나뉩니다.

**ToolCallTracker**: 하나의 배치 안에서 병렬 도구를 spinner + in-place update로 렌더링합니다. v0.38.0에서 batch clearing을 추가하여 이전 배치의 잔상(stale line)은 해결했습니다.

```python
# core/cli/ui/tool_tracker.py — on_tool_start()
if not self._running and self._tools and all(t["done"] for t in self._tools):
    self._tools.clear()
    self._line_count = 0
```

> 이 수정으로 `sequentialthinking`의 중복 spinner 문제는 해결됐지만, **각 배치가 완료된 후 독립적으로 출력되는 문제**는 남았습니다. 배치 1의 `✓ check_status`와 배치 2의 `✓ check_status`는 별개의 완료 라인입니다.

**EventRenderer**: 배치 간 이벤트(tool_start/end, tokens, thinking)를 순차 처리합니다. "이전 배치와 같은 도구가 다시 시작됐다"는 인지가 없었습니다.

## 3. Repeat Counter 설계

핵심 아이디어: **단일 도구 배치가 연속되면, 중간 이벤트를 억제하고 최종 요약만 출력합니다.**

Before:
```
  ✓ memory_search → ok (0.2s)
  ✢ claude-opus-4-6 · ↓48.1k ↑152
  ✓ memory_search → ok (0.2s)
  ✢ claude-opus-4-6 · ↓48.5k ↑160
  ✓ memory_search → ok (0.2s)
```

After:
```
  ✓ memory_search ×3 → ok (0.6s)
```

억제 대상 이벤트:

```python
# core/cli/ui/event_renderer.py
_REPEAT_SUPPRESSIBLE = frozenset(
    {"tool_start", "tool_end", "tokens", "thinking_start", "thinking_end", "round_start"}
)
```

> `tokens` 이벤트도 억제합니다. 반복 호출 사이의 토큰 사용량은 개별적으로 의미가 없으며, turn_end에서 합산 요약이 출력되기 때문입니다.

## 4. 상태 머신: onset → accumulate → flush

repeat counter는 3단계 상태 전이로 동작합니다.

```
                    ┌──────────────────────┐
 tool_end           │                      │
 (single batch) ──► │  _last_batch_tool    │
                    │  = tool_name         │
                    └──────────┬───────────┘
                               │
                    tool_start (same name)
                               │
                    ┌──────────▼───────────┐
                    │  _in_repeat = True   │ ◄─── tool_end (same name)
                    │  accumulate          │      _repeat_count += 1
                    │  count, dur, summary │      _repeat_dur += dur
                    └──────────┬───────────┘
                               │
                    tool_start (different) / stop()
                               │
                    ┌──────────▼───────────┐
                    │  _flush_repeat()     │
                    │  emit: ✓ tool ×N     │
                    └──────────────────────┘
```

**Onset**: `_handle_tool_end`에서 단일 도구 배치(배치 크기 1)가 완료되면 `_last_batch_tool`을 기록합니다.

```python
# core/cli/ui/event_renderer.py — _handle_tool_end
if all_done:
    if is_single:
        self._last_batch_tool = name
        self._repeat_count = 1
        self._repeat_dur = float(str(dur)) if dur else 0.0
        self._repeat_summary = str(event.get("summary", "ok"))
    else:
        self._last_batch_tool = ""  # 병렬 배치는 repeat 대상 아님
```

> 병렬 배치(2개 이상 도구)는 repeat 대상이 아닙니다. `web_search` + `read_file`이 동시에 끝나는 배치와, 같은 조합의 다음 배치를 같다고 볼 수 없기 때문입니다.

**Accumulate**: 다음 `tool_start`에서 같은 이름이면 repeat 모드 진입. 이벤트를 억제하고 카운터만 증가합니다.

```python
# core/cli/ui/event_renderer.py — _handle_tool_start
if self._last_batch_tool and name == self._last_batch_tool:
    self._in_repeat = True
    self._repeat_name = name
    return  # suppress this tool_start
```

**Flush**: 다른 도구가 시작되거나, `stop()`이 호출되면 누적된 요약을 출력합니다.

```python
# core/cli/ui/event_renderer.py
def _flush_repeat(self) -> None:
    if not self._in_repeat:
        return
    name = self._repeat_name
    count = self._repeat_count
    dur = self._repeat_dur
    summary = self._repeat_summary
    self._in_repeat = False
    self._repeat_name = ""
    self._last_batch_tool = ""
    if count <= 1:
        return
    dur_str = f" ({dur:.1f}s)" if dur > 0 else ""
    self._out.write(f"  \033[32m\u2713 {name}\033[0m \u00d7{count} \u2192 {summary}{dur_str}\n")
    self._out.flush()
```

> `count <= 1`이면 출력하지 않습니다. 첫 번째 호출은 이미 ToolCallTracker에 의해 정상 렌더링됐기 때문입니다. 2번째부터가 repeat입니다.

## 5. 정리

| 항목 | Before | After |
|------|--------|-------|
| `check_status` ×11 | 11줄 + 11 tokens 줄 = 22줄 | 1줄: `✓ check_status ×11 → ok (1.1s)` |
| `memory_search` ×19 | 19줄 + 19 tokens 줄 = 38줄 | 1줄: `✓ memory_search ×19 → ok (3.8s)` |
| 병렬 배치 (3 tools) | 3줄 (정상) | 3줄 (변경 없음) |
| `delegate_task` ×5 | 5줄 개별 표시 | 1줄: `✓ delegate_task ×5 → ok (12.3s)` |

**동작하지 않는 경우** (의도적):
- 병렬 배치: `_last_batch_tool = ""`으로 리셋
- 다른 도구 끼어들기: flush 후 정상 렌더링
- 첫 번째 호출: 정상 출력 (repeat는 2번째부터)

**테스트 6건**: sequential repeat 진입, flush 출력 확인, 다른 도구 flush 트리거, 병렬 배치 미트리거, stop() flush, tokens 억제.
