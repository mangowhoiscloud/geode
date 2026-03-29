# Plan: System Hardening

> Fix 20 design flaws from 4-system audit (HookSystem, SubAgent, TaskGraph, Scheduler-REPL).
> Scheduler becomes a daemon with full isolation from REPL.

## Phase 1: agentic_ref Race + Scheduler Daemon (C1)

**Root cause**: SharedServices holds a single `agentic_ref: list[Any]` that all modes share.
When scheduler calls `create_session(SCHEDULER)`, it overwrites `ref[0]`, corrupting REPL handlers.

**Fix**:
1. Remove `agentic_ref` from SharedServices
2. Add `_current_loop_ctx: ContextVar[AgenticLoop | None]` — per-thread loop reference
3. `create_session()` sets the ContextVar, tool handlers read it
4. Scheduler drain → SchedulerDaemon: separate thread with own lifecycle
5. REPL only receives completion notifications via queue, never shares loop

**Files**:
- `core/gateway/shared_services.py` — remove agentic_ref, add ContextVar
- `core/cli/tool_handlers.py` — read from ContextVar instead of closure ref
- `core/cli/__init__.py` — extract scheduler drain into SchedulerDaemon
- `core/cli/commands.py` — cmd_skill_invoke reads ContextVar

## Phase 2: Orchestration Locks (C2+C3+C4+H8)

**C2**: TaskGraph — add `threading.Lock` to `get_ready_tasks()`, `mark_running()`, `mark_completed()`
**C3**: IsolatedRunner — only release semaphore if actually acquired
**C4**: LaneQueue — track acquired sems separately from active tracking in `acquire_all()`
**H8**: TaskBridge — add `_evaluator_lock` to counter increment

**Files**:
- `core/orchestration/task_system.py` — add Lock
- `core/orchestration/isolated_execution.py` — guard semaphore release
- `core/orchestration/lane_queue.py` — fix acquire_all
- `core/orchestration/task_bridge.py` — add evaluator Lock

## Phase 3: SubAgent Safety (H1-H5)

**H1**: Thread zombie → log warning (full fix = subprocess-only, deferred to concurrency-redesign)
**H2**: Announce double-publish → move `announced` flag inside `_announce_lock`
**H3**: Announce orphan → add TTL-based auto-expiry (60s after completion)
**H4**: Env leak → whitelist `PATH`, `HOME`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ZHIPUAI_API_KEY`
**H5**: Thread mode denied_tools → filter handlers dict in `_execute_with_handler()`

**Files**:
- `core/agent/sub_agent.py` — H2, H3, H5
- `core/orchestration/isolated_execution.py` — H1, H4

## Phase 4: HookSystem Cleanup + Wiring (H6+H7+M1+M6)

**H6**: Remove 20+ truly orphan events. Keep events that ARE triggered + events with handlers.
**H7**: Add `TOOL_APPROVAL_GRANTED/DENIED` triggers in ToolExecutor HITL flow.
**M1**: Remove duplicate MODEL_SWITCHED registration in bootstrap.py.
**M6**: Add `HookEvent.SHUTDOWN` — triggered on session end for plugin cleanup.
**Wiring check**: Verify every registered handler has a matching trigger. Verify every trigger has ≥1 handler.

**Files**:
- `core/hooks/__init__.py` — prune orphan events, add SHUTDOWN
- `core/runtime_wiring/bootstrap.py` — remove duplicate, wire SHUTDOWN
- `core/agent/tool_executor.py` — add TOOL_APPROVAL triggers
- `tests/test_hooks.py` — update event count assertions

## Validation

5-persona + GAP Detective after all phases.

## Success Criteria

1. `agentic_ref` removed from SharedServices
2. Scheduler runs as daemon — no REPL state sharing
3. All TaskGraph/IsolatedRunner/LaneQueue operations are Lock-protected
4. Announce queue race-free (atomic flag)
5. Subprocess env whitelisted
6. No orphan HookEvents (every event either triggered or has handler)
7. MODEL_SWITCHED logged once, not twice
8. TOOL_APPROVAL triggers wired
9. 3369+ tests pass, 0 regressions
