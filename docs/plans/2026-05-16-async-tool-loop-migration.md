# Plan: Async Tool And Agent Loop Migration

> Scope: convert GEODE's agent loop, tool execution, approval, hooks, IPC, and
> lane control from sync-wrapped execution to a first-class async runtime.

## Problem

GEODE already exposes `AgenticLoop.arun()`, but the execution path is not
fully async. Tool execution still goes through a synchronous `ToolExecutor`
wrapped by `asyncio.to_thread()`, approval uses blocking prompts and threading
locks, IPC uses a thread-per-client Unix socket server, and context compaction
calls `run_until_complete()` inside the loop path.

This creates four failure classes:

- Event-loop reentry risk during context compaction.
- Cancellation and timeout signals do not reliably reach tools.
- IPC approval can block handler threads while the agent loop is otherwise
  async.
- The runtime cannot cleanly share one concurrency model across REPL, IPC,
  daemon, scheduler, and sub-agent sessions.

The target shape is a single async runtime contract with sync compatibility
kept only at process boundaries.

## Socratic Gate

| # | Question | Answer |
|---|----------|--------|
| Q1 | Does it already exist in code? | Partially. `AgenticLoop.arun()` and provider calls are async, but tools, approval, hooks, IPC, MCP stdio, and lanes still have sync/blocking seams. |
| Q2 | What breaks if we don't do this? | Tool cancellation remains best-effort, compaction can re-enter a running loop, IPC approval can block, and gateway/session concurrency keeps relying on threads. |
| Q3 | How do we measure the effect? | Remove `to_thread(self._executor.execute)`, remove loop-local `run_until_complete`, add cancellation tests, compare IPC prompt/approval latency, and track legacy sync adapter usage. |
| Q4 | What is the simplest implementation? | Introduce async interfaces beside existing sync APIs, switch the main execution path to async, then retire sync wrappers category by category. |
| Q5 | Is this pattern in 3+ frontier systems? | Yes. Claude Code uses async loop/tool contracts; OpenClaw uses Promise-based lane tasks; Hermes shows the cost of sync-to-async bridges and why they should be compatibility only. |

## Design

### Reference Findings

- Claude Code: `runAgentLoop()` is async end-to-end. Streaming response
  processing uses async iteration, and tool dispatch returns a `Promise`.
- Claude Code tools: each tool receives a context containing working
  directory, session id, permission mode, sub-agent flag, and abort signal.
- OpenClaw: command lanes enqueue `() => Promise<unknown>` tasks, track active
  task ids, time out tasks with late rejection logging, and expose lane
  snapshots/drain state.
- Hermes: `_run_async()` exists because sync call sites need to invoke async
  tools. GEODE should avoid that as a core pattern; it is a compatibility
  fallback, not the target architecture.
- OpenAI Python SDK: the official SDK exposes `AsyncOpenAI` with the same API
  shape as the sync client; OpenAI PAYG and Codex OAuth routes should await
  SDK methods directly.
- Anthropic Python SDK: the official SDK supports async Claude API clients,
  including async `messages.create()` / streaming paths.
- Z.AI/GLM: official docs present GLM through OpenAI-compatible endpoints and
  Python SDK paths with async support, so GEODE's GLM route uses
  `AsyncOpenAI(base_url=...)` instead of a thread-wrapped sync OpenAI client.

### Target Runtime Shape

```python
class AsyncTool(Protocol):
    name: str

    async def execute(
        self,
        input: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        ...


@dataclass
class ToolContext:
    session_id: str
    cwd: Path
    permission_mode: str
    is_subagent: bool
    cancellation: asyncio.Event
    progress: AsyncEventSink | None = None
```

Canonical flow:

1. `AgenticLoop.arun()` owns the turn loop.
2. Provider call is awaited.
3. `ToolCallProcessor` awaits `ToolExecutor.aexecute()`.
4. `ToolExecutor.aexecute()` runs async approval, async hooks, async tool
   dispatch, and async MCP/sub-agent calls.
5. IPC, scheduler, and gateway sessions enqueue async lane tasks.
6. Sync wrappers remain only for direct CLI compatibility and legacy tools.

### Affected Files

| File | Change |
|------|--------|
| `core/agent/loop/agent_loop.py` | Canonical AgenticLoop implementation; former `loop.py` implementation. |
| `core/agent/loop/loop.py` | Backward-compatible import shim only. |
| `core/tools/base.py` | Add async tool protocol and tool context. |
| `core/agent/tool_executor/executor.py` | Add canonical `aexecute()` path; keep `execute()` as compatibility wrapper. |
| `core/agent/tool_executor/processor.py` | Replace `to_thread(execute)` with `await aexecute()`. |
| `core/agent/context_manager.py` | Make overflow check/recovery async; remove `run_until_complete()`. |
| `core/agent/approval.py` | Add async approval APIs and shared sync/async approval serialization. |
| `core/hooks/system.py` | Add async trigger modes while preserving sync hooks. |
| `core/orchestration/lane_queue.py` or `async_lane_queue.py` | Add async lane queue with snapshots, timeout, drain, and reset. |
| `core/server/ipc_server/` | Move Unix socket server to `asyncio.start_unix_server`. |
| `core/mcp/stdio_client.py` | Add async stdio client path. |

### Alternatives Considered

- Keep wrapping sync tools in `asyncio.to_thread()`.
  - Rejected because cancellation, approval, and IPC still remain blocking
    concepts. This is only acceptable as a legacy adapter.
- Convert only `AgenticLoop.run()` callers to `arun()`.
  - Rejected because the main blocker is below the loop, in tool/approval/hook
    dispatch.
- Rewrite IPC first.
  - Rejected for the first PR because tool execution and context compaction are
    smaller and unblock the core runtime semantics.

## Implementation Checklist

- [x] Rename canonical loop file to `core/agent/loop/agent_loop.py`.
- [x] Keep `core/agent/loop/loop.py` as a compatibility shim.
- [x] Add `AsyncTool`, `ToolContext`, and `ToolExecutor.aexecute()`.
- [x] Switch `ToolCallProcessor` to await `aexecute()`.
- [x] Make context overflow checks and aggressive recovery async.
- [x] Add async hook trigger APIs.
- [x] Add async approval APIs.
- [x] Add async IPC server path.
- [x] Add async lane queue.
- [x] Convert MCP and bash tools to async first.
- [x] Convert AgenticLoop lifecycle/finalization hooks on `arun()` to async.
- [x] Convert AgenticLoop usage/cost and model-switch observability on `arun()`
  to async.
- [x] Route IPC prompt execution through async daemon lanes and
  `AgenticLoop.arun()`.
- [x] Add IPC guard tests that fail if daemon prompt execution uses sync
  `AgenticLoop.run()` or `LaneQueue.acquire_all()`.
- [x] Move IPC UI/session state from thread-local-only storage to
  contextvar-backed local storage and remove the async prompt UI lock.
- [x] Remove `AgenticLoop.run()` after migrating production internal callers.
- [x] Add async MCP helper methods for calendar, notification, and signal
  fallback adapters.
- [x] Move adaptive error recovery retries to the async executor path.
- [x] Add async tool executor contextvar injection for async-native nodes.
- [x] Convert plugin signal tools to tool-local `aexecute()` MCP paths.
- [x] Convert remaining built-in tool categories to tool-local async wrappers
  or async-native adapter calls.
- [x] Add async `generate_with_tools()` provider boundary contracts.
- [x] Convert provider async tool-use internals to await async executors.
- [x] Route container-injected sync LLM tool callable through provider async
  tool-use as a sync process/node boundary.
- [x] Remove sync tool-executor contextvar injection and migrate tool-augmented
  nodes to `get_async_tool_executor()`.
- [x] Remove sync LLM tool callable injection (`get_llm_tool()` /
  `LLMToolCallable`) after migrating tool-augmented nodes.
- [x] Migrate CLI/delegated handler direct tool-object calls to `aexecute()`.
- [x] Convert OpenAI/Anthropic/GLM async provider calls to native async SDK
  clients before removing sync facades.
- [ ] Remove legacy sync provider/tool facades after downstream callers migrate.
- [x] Add broader source guards for non-IPC async services.

## Sync Tool/MCP Migration Matrix

| Area | Current sync shape | Async support / replacement | Priority | Migration status |
|------|--------------------|-----------------------------|----------|------------------|
| Agent loop facade | `AgenticLoop.run()` previously wrapped `asyncio.run(arun())`. | Canonical API is `await AgenticLoop.arun()`. | P0 | Removed as a breaking-change debt payoff; source guards prevent production/internal reintroduction. |
| Bash tool | Legacy `execute()` existed. | Native `BashTool.aexecute()` is used by `ToolExecutor.aexecute()`. | P0 | Done. |
| MCP manager/client | `MCPServerManager.call_tool()` and stdio `call_tool()`. | `MCPServerManager.acall_tool()` and stdio `acall_tool()` exist. | P0 | Agent tool execution uses async MCP calls. |
| MCP calendar adapters | `BaseCalendarAdapter.*` call `manager.call_tool()`. | `ais_available`, `alist_events`, `acreate_event`, `adelete_event`, `alist_calendars` call `manager.acall_tool()`. | P1 | First adapter slice migrated; sync API retained for compatibility. |
| MCP notification adapters | `send_message()` calls `manager.call_tool()`. | `asend_message()` calls `manager.acall_tool()`. | P1 | First adapter slice migrated; sync API retained for compatibility. |
| MCP signal helpers | `try_mcp_signal()` and `SteamMCPSignalAdapter.fetch_signals()` call sync MCP paths. | `try_mcp_signal_async()` and `SteamMCPSignalAdapter.afetch_signals()` call `acall_tool()`. `MCPClientBase.acall_tool()` provides a compatibility wrapper for legacy clients. | P1 | Helper/adapter slice migrated; plugin signal tools now expose `aexecute()` and use async MCP helper paths. |
| Adaptive error recovery | Recovery retries previously ran `recover()` in `asyncio.to_thread()` and called `ToolExecutor.execute()`. | `ErrorRecoveryStrategy.arecover()` now awaits `ToolExecutor.aexecute()` for retry, alternative, and fallback strategies. | P1 | Canonical `ToolCallProcessor` recovery path migrated; sync `recover()` retained for compatibility tests/callers. |
| Filesystem tools | `GlobTool`, `GrepTool`, `Read/Edit/Write` execute through sync file APIs. | Tool-local `aexecute()` quarantines scans/writes with explicit `asyncio.to_thread()`. | P1 | Migrated to explicit tool-local async wrappers. |
| Web tools | `WebFetchTool`, `GeneralWebSearchTool`, `WebSearchTool`, jobs search are sync. | Tool-local `aexecute()` quarantines blocking HTTP/provider clients with explicit `asyncio.to_thread()`. | P1 | Migrated to explicit tool-local async wrappers; future improvement is native async HTTP/provider clients. |
| Memory/profile tools | Memory, rule, note, profile tools call sync local stores. | Tool-local `aexecute()` quarantines local store/file IO with explicit `asyncio.to_thread()`. | P2 | Migrated to explicit tool-local async wrappers. |
| Calendar tool objects | `CalendarListEventsTool`, `CalendarCreateEventTool`, scheduler sync tool call sync calendar port. | `aexecute()` now prefers async calendar port methods; scheduler sync bridge is quarantined with tool-local `asyncio.to_thread()`. | P2 | Migrated. |
| Output/report tools | Report, JSON export, notification tool are sync. | `SendNotificationTool.aexecute()` prefers `asend_message`; report/export use tool-local async wrappers for CPU/file IO. | P2 | Migrated. |
| Data/plugin tools | Cortex, MonoLake, analyst/evaluator, signal tools are sync. | Signal tools use async MCP helpers; remaining fixture/stub tools use tool-local async wrappers. | P2 | Migrated. |
| `ToolRegistry.execute()` | Direct sync execution of registered `Tool` objects. | `ToolRegistry.aexecute()` prefers tool-local `aexecute()`; sync-only fallback remains deprecated for third-party compatibility. | P2 | Built-in tools migrated; sync fallback now emits `DeprecationWarning`. |
| Runtime tool executor injection | Runtime/container default tool executors called `ToolRegistry.execute()` directly and exposed `get_tool_executor()`. | Runtime now injects only `get_async_tool_executor()`; sync executor contextvar was removed. | P1 | Direct runtime/container `registry.execute()` calls removed; tool-augmented nodes migrated to async executor injection. |
| Provider tool-use contract | `generate_with_tools()` provider APIs accepted sync `tool_executor` callables. | `agenerate_with_tools()` and `call_llm_with_tools_async()` now run await-native provider loops and await async tool executors; OpenAI/Codex use `AsyncOpenAI`, Anthropic uses `AsyncAnthropic`, and GLM uses OpenAI-compatible `AsyncOpenAI(base_url=...)`. | P1 | Async provider internals migrated to native async SDK clients; sync `generate_with_tools()` remains only as compatibility surface pending downstream caller migration. |
| Container LLM tool injection | `make_tool_executor()` called `llm_adapter.generate_with_tools()` and used a sync registry fallback. | Sync injected callable now runs `llm_adapter.agenerate_with_tools()` at the sync node boundary and defaults to async registry execution. | P1 | Runtime injection no longer depends on provider sync internals. |
| LLM tool callable contextvar | `set_llm_callable(tool_fn=...)`, `get_llm_tool()`, and `LLMToolCallable` exposed a sync tool-use callable. | Tool-augmented nodes call `call_llm_with_tools_async()` directly. | P1 | Removed. |
| Tool-augmented plugin nodes | Analyst/evaluator/synthesizer/scoring/BiasBuster paths read sync `get_tool_executor()` or sync `get_llm_tool()`. | Nodes now call `call_llm_with_tools_async()` and `get_async_tool_executor()` from their sync node boundary. | P1 | Production node paths migrated. |
| CLI/delegated tool handlers | Delegated, calendar, computer-use, memory, and signal fallback handlers called tool-object `execute()` directly. | Handlers now call tool-object `aexecute()` at CLI/node boundaries. | P2 | Production CLI handler slice migrated. |
| Legacy lane facade | `LaneQueue.acquire_all()` sync context manager. | `LaneQueue.acquire_all_async()` exists. | P1 | IPC daemon migrated; remaining sync services classified as process-edge debt. |

## Verification

Initial rename and planning PR:

```bash
uv run pytest tests/test_agentic_loop.py tests/test_model_drift_health.py tests/plugins/petri_audit/test_skeleton.py -q
uv run ruff check core/agent/loop plugins/petri_audit/targets/geode_target.py
```

Core async execution PR:

```bash
uv run pytest tests/test_agentic_loop.py tests/test_parallel_approval.py tests/test_context_manager.py -q
uv run pytest tests/test_phase3_ipc.py tests/test_command_registry.py -q
uv run ruff check core/agent core/tools core/hooks core/orchestration core/server
uv run mypy core/agent core/tools core/hooks
```

Current breaking-change slice:

```bash
uv run pytest tests/test_agentic_loop.py tests/test_autonomous_safety.py \
  tests/test_scheduler_serve.py tests/test_worker.py tests/test_calendar_adapters.py \
  tests/test_notification_adapters.py tests/test_signal_tools_mcp.py \
  tests/test_signal_liveification.py -q
uv run pytest tests/test_agentic_loop.py tests/test_autonomous_safety.py \
  tests/test_context_manager.py tests/test_hooks.py tests/test_hitl_level.py \
  tests/test_parallel_approval.py tests/test_tool_executor_spinner.py \
  tests/test_phase3_ipc.py tests/test_agentic_ui.py tests/test_oauth_browser.py \
  tests/test_event_schema_v2.py tests/test_graceful_drain.py tests/test_lane_queue.py \
  tests/test_gateway.py tests/test_bash_tool.py tests/test_mcp_lifecycle.py \
  tests/test_calendar_adapters.py tests/test_notification_adapters.py \
  tests/test_signal_tools_mcp.py tests/test_signal_liveification.py \
  tests/test_scheduler_serve.py tests/test_worker.py tests/test_model_drift_health.py \
  tests/plugins/petri_audit/test_skeleton.py -q
uv run ruff check core/agent/loop/agent_loop.py core/agent/worker.py \
  core/cli/bootstrap.py core/cli/scheduler_drain.py core/cli/typer_serve.py \
  core/cli/commands/skills.py core/server/ipc_server/poller.py core/mcp/base.py \
  core/mcp/base_calendar.py core/mcp/base_notification.py core/mcp/steam_adapter.py \
  core/mcp/utils.py tests/test_agentic_loop.py tests/test_scheduler_serve.py \
  tests/test_worker.py tests/test_calendar_adapters.py tests/test_notification_adapters.py \
  tests/test_signal_tools_mcp.py tests/test_signal_liveification.py \
  tests/test_autonomous_safety.py tests/_live_audit_runner.py tests/test_e2e_live_llm.py
uv run mypy core/agent/loop/agent_loop.py core/agent/worker.py core/cli/bootstrap.py \
  core/cli/scheduler_drain.py core/cli/typer_serve.py core/cli/commands/skills.py \
  core/server/ipc_server/poller.py core/mcp/base.py core/mcp/base_calendar.py \
  core/mcp/base_notification.py core/mcp/steam_adapter.py core/mcp/utils.py

uv run pytest tests/test_tool_use.py tests/test_llm_port.py tests/test_ports.py \
  tests/test_e2e.py -q
uv run ruff check core/llm core/wiring tests/test_tool_use.py tests/test_llm_port.py \
  tests/test_ports.py tests/test_e2e.py
uv run mypy core/llm core/wiring
```

Code-quality gap / missing / duplication gate:

```bash
# Missing async hand-offs in the migrated path
rg -n "run_until_complete|asyncio\\.run\\(|trigger\\(|trigger_with_result\\(|trigger_interceptor\\(|call_tool\\(|\\.execute\\(|acquire_all\\(|recv\\(" \
  core/agent core/hooks core/server/ipc_server core/orchestration core/mcp core/tools -g '*.py'

# Async API surface audit
rg -n "async def|def .*_async|aexecute|acall_tool|acquire_all_async|trigger_.*async" \
  core/agent core/hooks core/server/ipc_server core/orchestration core/mcp core/tools -g '*.py'

# Quality smells to classify as intentional compatibility, existing debt, or fix-now
rg -n "TODO|FIXME|type: ignore|except Exception|Any" \
  core/agent core/hooks core/server/ipc_server core/orchestration core/mcp core/tools -g '*.py'
```

Current classification:

- Intentional compatibility: legacy sync tool and provider facades remain only
  for external/direct sync callers; built-in canonical execution uses async
  entrypoints.
- Fixed-now gaps: context overflow hooks and tool-result-offload hooks now use
  async hook APIs; approval serialization no longer stores an event-loop-bound
  `asyncio.Lock`; `AgenticLoop.arun()` now awaits user-input interception,
  session start, LLM retry/failure, final session/turn/reasoning hooks, usage
  cost hooks, and model-switch hooks; IPC prompt execution now uses
  `LaneQueue.acquire_all_async()` and `AgenticLoop.arun()`; IPC UI bindings
  are contextvar-backed and can run concurrently under lane control; production
  CLI/worker/gateway/scheduler callers no longer call `AgenticLoop.run()`;
  MCP calendar/notification/signal helper layers now expose async alternatives;
  adaptive error recovery awaits `ErrorRecoveryStrategy.arecover()`; runtime
  tool injection provides an async executor contextvar; plugin signal tools now
  expose `aexecute()`; built-in file/web/document/jobs/memory/profile/data/
  report/export/calendar-scheduler/computer-use tools now expose tool-local
  `aexecute()`; `AgenticLoop.run()` has been removed.
- Remaining debt: sync compatibility boundaries still exist for direct
  `ToolExecutor.execute()`, `ToolRegistry.execute()`, preserved MCP sync APIs,
  and public sync provider `generate_with_tools()` facades.
- Verification gap scan: executable `AgenticLoop.run(...)` hits are removed
  from the codebase. Remaining `run_until_complete()` / `asyncio.run()` hits
  are process-lifecycle or explicit sync-boundary bridges. Remaining executable
  `call_tool(...)` hits are preserved MCP sync APIs and direct sync service
  boundaries.

## Debt Ledger

The remaining debt is deliberately kept at compatibility boundaries, not in the
canonical `AgenticLoop.arun()` path.

| Debt | Why it exists | Risk | Next reduction |
|------|---------------|------|----------------|
| Legacy sync tool APIs remain | Direct CLI/tests and third-party callers still call `Tool.execute()`, `ToolExecutor.execute()`, and `ToolRegistry.execute()`. | Sync callers are supported only at process/direct-call edges. Async canonical path should not depend on them. | Keep source guards around canonical paths; remove public sync APIs in the next breaking pass after provider contracts migrate. |
| Sync-only third-party tool fallback remains | External registered tools may not yet implement `aexecute()`. | Generic fallback isolates work in a thread but cannot provide cooperative cancellation inside tool bodies. | Built-ins now implement `aexecute()`; fallback emits `DeprecationWarning` to make remaining cases visible. |
| `LaneQueue.acquire_all()` remains beside `acquire_all_async()` | Gateway and legacy callers still use the sync context manager. | Mixed APIs are safe because they share the same semaphore capacity, but code review must classify which boundary a caller belongs to. | Migrate async services to `acquire_all_async()`; leave `acquire_all()` for direct sync entrypoints only. |
| Public sync provider facades remain | `ClaudeAdapter.generate_with_tools()` and `OpenAIAdapter.generate_with_tools()` are still exposed for direct sync callers and tests. | Canonical async paths no longer depend on sync provider internals, but the public API is still broader than the target contract. | Migrate/retire sync direct callers, then remove the sync `generate_with_tools()` methods in the breaking pass. |

## Next Progress Attachment

Next slice target: remove public sync provider/tool facades now that provider
async internals use native async SDK clients, then continue shrinking legacy
sync service callers.

Role split:

- Direct REPL: owns local terminal interaction, prompt input, and local command
  rendering. It should call async runtime code directly from one top-level event
  loop when running without `geode serve`.
- IPC thin client: owns transport, terminal capability reporting, local command
  shortcuts, and event rendering. It should not execute the agent loop itself.
- IPC daemon: owns shared services, session state, approval relay, lane
  admission, and `AgenticLoop.arun()` execution.

Completed in this slice:

1. Added an async daemon prompt runner that performs lane admission with
   `LaneQueue.acquire_all_async()` and awaits `AgenticLoop.arun()`.
2. Routed `_handle_client_async()` to that runner instead of
   `_run_prompt_streaming()` worker-thread execution.
3. Preserved the existing sync `_run_prompt_streaming()` as a compatibility
   fallback for legacy sync callers.
4. Added regression tests proving IPC prompt execution does not call
   `AgenticLoop.run()` and does not use sync `LaneQueue.acquire_all()`.
5. Moved console/session-meter/IPC-writer local state to contextvar-backed
   storage and added a two-prompt concurrency test for IPC UI isolation.

Next implementation steps:

1. Convert scheduler non-isolated REPL injection to call `await arun()` from the
   direct REPL event loop once direct REPL mode has an explicit top-level async
   runner.
2. Remove public sync provider `generate_with_tools()` facades after direct
   callers migrate to `agenerate_with_tools()`.
3. Remove direct sync tool APIs after downstream callers migrate.

Full migration gate:

```bash
uv run pytest tests/ -m "not live"
uv run lint-imports
```

## Follow-up Hygiene Track

Prompt/context cleanup should run as a separate track so async regressions are
easy to isolate.

- Inventory runtime skills and remove or disable unused/duplicated entries.
- Reduce overlong Markdown context that is injected every turn.
- Split sandwich-injected context by role.
- Encode role-fit blocks as XML, aligned with the existing
  `<dynamic_context>` convention.
- Measure `PromptAssembler.assemble()` size before and after cleanup.

Candidate XML envelope:

```xml
<runtime_identity>
  ...
</runtime_identity>
<project_policy>
  ...
</project_policy>
<available_skills>
  ...
</available_skills>
<session_context>
  ...
</session_context>
<tooling_context>
  ...
</tooling_context>
```

## References

- Claude Code: async agent loop, async tool dispatch, abort signal in tool
  context.
- OpenClaw: Promise-based command lanes, active task snapshots, lane drain.
- Hermes Agent: sync-to-async bridge costs, persistent loop workaround, and
  explicit startup discovery to avoid event-loop freezes.
