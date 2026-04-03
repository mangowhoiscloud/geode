# GEODE Observability Report

> Audit date: 2026-04-03 (Session 56)
> Scope: All tracking, monitoring, logging, and metrics systems across `core/`

---

## System Inventory (17 systems)

| # | System | File | Storage | Hook Events |
|---|--------|------|---------|-------------|
| 1 | HookSystem | `hooks/system.py` | Memory (thread-safe) | 46 event types |
| 2 | SessionMetrics | `orchestration/metrics.py` | Memory | LLM_CALL_END, TOOL_RECOVERY_* |
| 3 | TokenTracker | `llm/token_tracker.py` | Memory + `~/.geode/usage/YYYY-MM.jsonl` + LangSmith | LLM_CALL_END |
| 4 | Termination Tracking | `agent/agentic_loop.py:156` | AgenticResult | SESSION_END, TURN_COMPLETE |
| 5 | RunLog | `orchestration/run_log.py` | `~/.geode/runs/{key}.jsonl` | NODE_* |
| 6 | SessionTranscript | `cli/transcript.py` | `~/.geode/journal/transcripts/{project}/{session}.jsonl` | — |
| 7 | LangSmith | `llm/token_tracker.py:321` | run_tree.extra["metrics"] | LLM_CALL_END |
| 8 | StuckDetection | `orchestration/stuck_detection.py` | Memory + monitor thread | NODE_ENTER/EXIT/ERROR |
| 9 | ContextMonitor | `orchestration/context_monitor.py` | Memory | CONTEXT_CRITICAL, CONTEXT_OVERFLOW_ACTION |
| 10 | ErrorRecovery | `agent/error_recovery.py` | Memory (RecoveryResult) | TOOL_RECOVERY_* |
| 11 | Gateway/IPC Events | `cli/ui/agentic_ui.py` | IPC stream | — |
| 12 | CostBudget | `agent/agentic_loop.py:204` | Instance var | SESSION_END |
| 13 | TimeBudget | `agent/agentic_loop.py:596` | monotonic clock | SESSION_END |
| 14 | ModelSwitching | `agent/agentic_loop.py:416` | Conversation message | MODEL_SWITCHED |
| 15 | SubAgent | `agent/sub_agent.py` | Announce queue | SUBAGENT_* |
| 16 | ProjectJournal | `memory/project_journal.py` | `~/.geode/projects/{id}/journal/` | — |
| 17 | UsageStore | `llm/usage_store.py` | `~/.geode/usage/YYYY-MM.jsonl` | — |

---

## 1. HookSystem — 46 Events

### Pipeline (3)
`PIPELINE_START` `PIPELINE_END` `PIPELINE_ERROR`

### Node (4)
`NODE_BOOTSTRAP` `NODE_ENTER` `NODE_EXIT` `NODE_ERROR`

### Analysis (3)
`ANALYST_COMPLETE` `EVALUATOR_COMPLETE` `SCORING_COMPLETE`

### Verification (2)
`VERIFICATION_PASS` `VERIFICATION_FAIL`

### Automation (7)
`DRIFT_DETECTED` `OUTCOME_COLLECTED` `MODEL_PROMOTED` `SNAPSHOT_CAPTURED` `TRIGGER_FIRED` `POST_ANALYSIS` `CONFIG_RELOADED`

### Memory (4)
`MEMORY_SAVED` `RULE_CREATED` `RULE_UPDATED` `RULE_DELETED`

### Prompt (1)
`PROMPT_ASSEMBLED`

### SubAgent (3)
`SUBAGENT_STARTED` `SUBAGENT_COMPLETED` `SUBAGENT_FAILED`

### Tool Recovery (3)
`TOOL_RECOVERY_ATTEMPTED` `TOOL_RECOVERY_SUCCEEDED` `TOOL_RECOVERY_FAILED`

### Agentic (1)
`TURN_COMPLETE`

### Context (2)
`CONTEXT_CRITICAL` `CONTEXT_OVERFLOW_ACTION`

### Session (2)
`SESSION_START` `SESSION_END`

### Model (1)
`MODEL_SWITCHED`

### LLM Call (4)
`LLM_CALL_START` `LLM_CALL_END` `LLM_CALL_FAILED` `LLM_CALL_RETRY`

### Tool Approval (3)
`TOOL_APPROVAL_REQUESTED` `TOOL_APPROVAL_GRANTED` `TOOL_APPROVAL_DENIED`

### Cross-Provider (1)
`FALLBACK_CROSS_PROVIDER`

### Infrastructure (3)
`PIPELINE_TIMEOUT` `SHUTDOWN_STARTED` `CONFIG_RELOADED`

### MCP (2)
`MCP_SERVER_CONNECTED` `MCP_SERVER_FAILED`

---

## 2. SessionMetrics

```
orchestration/metrics.py → HookSystem consumer
```

| Metric | Type | Source |
|--------|------|--------|
| p50/p95/mean/max latency | per-model float | LLM_CALL_END |
| LLM error rate | float | LLM_CALL_FAILED count / total |
| Tool success rate | float | tool_calls - tool_errors / total |
| Tool recoveries | int | TOOL_RECOVERY_SUCCEEDED |
| Rounds | int | round counter |
| Session elapsed | float | start_time delta |

Output: `summary() -> dict` with nested `llm.by_model` breakdown.

---

## 3. TokenTracker — Cost Tracking

```
llm/token_tracker.py → ContextVar singleton
```

**Per-call:** `record(model, input, output, cache_creation, cache_read)`

**Accumulator:** `LLMUsageAccumulator` — session totals (input, output, cache, cost_usd)

**Persistence:**
- `~/.geode/usage/YYYY-MM.jsonl` — monthly JSONL via UsageStore
- LangSmith `run_tree.extra["metrics"]` — if env vars set

**Pricing:** 8 Anthropic + 5 OpenAI + 4 ZhipuAI models with cache pricing.

---

## 4. Termination Reasons — Exit Path Tracking

```
agent/agentic_loop.py:156 → AgenticResult.termination_reason
```

| Reason | Trigger | Line |
|--------|---------|------|
| `natural` | LLM stop_reason="end_turn" | normal |
| `forced_text` | wrap-up N rounds before max | pre-max |
| `max_rounds` | hit max_rounds limit | limit |
| `time_budget_expired` | elapsed >= time_budget_s | :596 |
| `llm_error` | non-retryable API error | :763, :888 |
| `context_exhausted` | context window full post-recovery | :640, :703, :748 |
| `cost_budget_exceeded` | cost >= cost_budget | :939 |
| `user_cancelled` | Ctrl+C | :674 |
| `billing_error` | API auth/billing failure | :555, :666 |
| `convergence_detected` | stuck/repeat detection | :984 |
| `unknown` | default | :156 |

Emitted via `SESSION_END` + `TURN_COMPLETE` hooks.

---

## 5. RunLog — Execution History

```
orchestration/run_log.py → JSONL per session_key
```

**Entry:** `{session_key, event, node, status, duration_ms, metadata, timestamp, run_id}`

**Storage:** `~/.geode/runs/{session_key}.jsonl` — auto-prune at 2MB / 2000 lines.

---

## 6. SessionTranscript — Conversation Record

```
cli/transcript.py → JSONL per session
```

**Events:** session_start, session_end, user_message, assistant_message, tool_call, tool_result, vault_save, cost, error, subagent_start, subagent_complete

**Storage:** `~/.geode/journal/transcripts/{project}/{session_id}.jsonl` — auto-truncate at 5MB.

---

## 7. Context Monitor

```
orchestration/context_monitor.py
```

| Threshold | Action |
|-----------|--------|
| 80% (WARNING) | Log warning |
| 95% (CRITICAL) | Fire `CONTEXT_CRITICAL` → auto compress |
| 200K ceiling | Prevent rate limit pool boundary crossing |

**Compression chain:** `summarize_tool_results` → `adaptive_prune` → `prune_oldest_messages`

---

## 8. Error Recovery Chain

```
agent/error_recovery.py
```

`RETRY → ALTERNATIVE → FALLBACK → ESCALATE`

**Tracked:** RecoveryResult (recovered, attempts[], strategy_used, duration_ms)

**Excluded tools:** run_bash, memory_save, note_save, set_api_key, manage_auth

---

## 9. IPC Event Stream (Thin Client)

| Event | Payload |
|-------|---------|
| `tool_start` | name, duration_s |
| `tool_end` | name, duration_s, summary |
| `tokens` | in, out, model, cost |
| `thinking_start/end` | — |
| `round_start` | round_num |
| `context_event` | event, pct_used, action |
| `subagent_*` | task_id, status, duration_s |
| `model_switched` | from, to, reason |
| `turn_end` | termination_reason, rounds, tool_count |

---

## 10. Persistent Storage Map

```
~/.geode/
├── usage/YYYY-MM.jsonl              # TokenTracker (monthly cost)
├── runs/{session_key}.jsonl         # RunLog (pipeline execution)
├── projects/{id}/journal/
│   ├── runs.jsonl                   # ProjectJournal
│   ├── costs.jsonl                  # per-call cost records
│   ├── errors.jsonl                 # error records
│   └── learned.md                   # learned patterns
├── journal/transcripts/
│   └── {project}/{session_id}.jsonl # SessionTranscript
└── snapshots/                       # SnapshotManager (pipeline state)
```

---

## Known Gaps

| # | Gap | Impact | Severity |
|---|-----|--------|----------|
| 1 | Context compression effectiveness not tracked | Can't measure summarize/prune quality | Medium |
| 2 | No per-tool cost accumulation | Can't identify expensive tool patterns | Low |
| 3 | Retry count not in termination reason | Silent retry exhaustion | Low |
| 4 | Parallel tool batch metrics missing | Can't optimize tool parallelism | Low |
| 5 | Sub-agent resource consumption not tracked | No CPU/memory/context budget per sub-agent | Low |
| 6 | MCP server ongoing health not monitored | Only connect/fail, no latency histogram | Low |
| 7 | Cross-provider fallback latency delta missing | Can't measure failover cost | Low |
