# Agentic Loop Progress Guard + CLI Operator UX

> [!NOTE]
> Historical liveness and operator-UX design. Current behavior is owned by code
> and tests; architecture residuals roll up to LOOP-003/004 and CAP-004/005 in
> the [architecture roadmap](../architecture/extensibility-roadmap.md). The
> metadata and proposed stages below are preserved as a 2026-06-30 snapshot.

Historical status: draft plan (2026-06-30)
Historical owner: scaffold session (`feature/loop-progress-ux-plan`)
Constraint: **Do not add a default round cap.** `DEFAULT_MAX_ROUNDS = 0`
remains the default because GEODE's inner runtime is intentionally an
unbounded `while(tool_use)` loop. This plan adds progress/liveness controls
inside that loop, not a global iteration ceiling.

## 1. Problem

The 2026-06-30 `geode serve` log showed a concrete stuck-loop pattern:

1. The model repeatedly searched `core/tools/definitions.json` with
   `grep_files`.
2. AgenticLoop emitted `Diversity forcing: grep_files called 5x`.
3. The model interpreted the weak hint as "use a different discovery tool" and
   switched to `check_status`.
4. `check_status({})` repeatedly returned successful status payloads, so the
   error-only convergence detector reset instead of terminating.
5. `Diversity forcing: check_status called 5x` fired, but it still only injected
   a hint. The loop continued.

The defect is not the lack of a round cap. It is that GEODE treats "tool call
succeeded" as progress. A successful repeated observation can be zero-progress,
and for discovery/status tools it can actively prevent completion.

## 2. Socratic Gate

| # | Question | Answer |
|---|----------|--------|
| Q1 | Does it already exist in code? | Partially. `ConvergenceDetector` catches repeated errors, and diversity forcing catches repeated tool names, but successful repeated results are not tracked. |
| Q2 | What breaks if we do not do this? | Long-running sessions can keep spending tokens and lane time on successful but redundant discovery/status calls. The CLI tells the operator "forcing alternative" even when the runtime only injected a hint. |
| Q3 | How do we measure the effect? | Add tests for repeated `check_status({})`, repeated `grep_files(...) -> check_status({})` escape loops, and allowed read/search repetition. Add trace metrics: signature hash, result fingerprint, repeat streak, no-progress termination reason. |
| Q4 | What is the simplest implementation? | Keep unlimited rounds. Add deterministic repeated-success tracking at the loop boundary. On repeated same signature/result, escalate from hint -> cooldown -> `repeated_success_no_progress` termination. |
| Q5 | Is this pattern in 3+ frontier systems? | Yes. OpenAI Agents SDK uses `max_turns` as an opt-out-able safety guard and tracing; LangGraph exposes recursion/remaining-step controls; AutoGen composes termination conditions; CrewAI exposes iteration/time/retry limits; OpenClaw/Hermes suggest policy-backed routing, compact indexes, and liveness surfaces. |

## 3. External Research Snapshot (2026-06)

### Official / framework sources

- **OpenAI Agents SDK**: agent runs continue until final output; `max_turns`
  raises `MaxTurnsExceeded`, and `max_turns=None` disables the limit. This
  supports GEODE's unlimited-default stance while showing that safety controls
  belong in runtime policy, not only in model behavior.
  Source: https://openai.github.io/openai-agents-python/running_agents/
- **OpenAI Function Calling**: the application owns tool execution and can set
  `parallel_tool_calls=false` to constrain tool-call shape. Tool loops are an
  application/runtime contract.
  Source: https://developers.openai.com/api/docs/guides/function-calling
- **OpenAI Agents tracing**: traces capture LLM generations, tool calls,
  handoffs, guardrails, and custom events, giving a precedent for adding
  repeated-result/no-progress telemetry.
  Source: https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md
- **Anthropic stop reasons**: `tool_use` is a continuation signal and
  `end_turn` is a natural stop signal. Runtimes must inspect stop reasons and
  decide what to do when the model keeps requesting tools.
  Source: https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons
- **LangGraph**: `GRAPH_RECURSION_LIMIT` means a graph hit max steps before a
  stop condition, often due to an infinite loop. LangGraph also exposes
  `RemainingSteps` for graceful degradation before the limit.
  Sources: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT,
  https://docs.langchain.com/oss/python/langgraph/graph-api
- **AutoGen**: termination conditions are stateful, reset per run, and can be
  composed. Built-ins include message-count, text mention, token usage, timeout,
  handoff, source match, external trigger, stop-message, and function-call
  termination.
  Source: https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/termination.html
- **CrewAI**: production agent configs expose `max_iter`, execution time, retry,
  and rate controls. GEODE should not copy the default cap, but the policy axis
  is convergent.
  Source: https://docs.crewai.com/v1.15.0/en/concepts/agents

### Hermes / OpenClaw references

- **Hermes Agent** publishes `/llms.txt` and `/llms-full.txt`: a compact index
  and a full dump. For GEODE, this maps directly to a tool-catalog digest that
  prevents the model from repeatedly grepping `definitions.json`.
  Source: https://hermes-agent.nousresearch.com/docs/
- **Hermes tips** emphasize giving project context up front and using
  `AGENTS.md`/lazy-loaded local guidance. That supports compact, high-signal
  tool catalog context instead of repeated discovery calls.
  Source: https://hermes-agent.nousresearch.com/docs/guides/tips
- **OpenClaw** multi-agent routing separates agents, workspaces, state dirs, and
  session history. The relevant pattern for GEODE is not a round cap; it is
  gateway/lane/session ownership and observable liveness.
  Source: https://docs.openclaw.ai/concepts/multi-agent
- **OpenClaw policy** frames policy as a conformance layer over existing config.
  GEODE should similarly treat repeat limits as tool policy metadata, not
  prompt prose.
  Source: https://docs.openclaw.ai/cli/policy
- **OpenClaw lane issue #48488** describes a stuck lane when a queued task never
  settles. GEODE should add lane/task liveness surfaces so a no-progress loop
  does not silently occupy the daemon.
  Source: https://github.com/openclaw/openclaw/issues/48488

### Production / observability sources (non-normative, useful signals)

- 2026 observability guides increasingly treat tool-call correctness, trace
  cost, looping branches, and runtime guardrails as first-class metrics.
  Sources: https://www.augmentcode.com/guides/ai-agent-monitoring,
  https://www.arthur.ai/column/evaluating-ai-agents-in-production,
  https://coralogix.com/ai-blog/agentic-ai-observability/
- 2026 "loop engineering" writeups converge on explicit termination logic,
  verifiable goals, token/cost budgets, and no-progress detection. These are
  useful framing sources, but the implementation should be grounded in official
  framework behavior and GEODE's logs/tests.
  Sources: https://happycapy.ai/blog/loop-engineering-ai-agents,
  https://blogs.oracle.com/developers/the-agent-loop-decoded-three-levels-every-agent-engineer-must-know

## 4. Design

### 4.1 Policy Principle

Keep GEODE's inner loop unbounded by default:

```python
DEFAULT_MAX_ROUNDS = 0
```

Add **progress-bounded execution**, not round-bounded execution:

- A model may continue as long as tool observations add new evidence or state.
- Repeating the same successful observation is no longer progress.
- Repeated no-progress observations escalate deterministically.

### 4.2 Repeated-Success Detector

Track a compact observation record per tool result:

| Field | Purpose |
|---|---|
| `tool_name` | Exact tool called. |
| `args_fingerprint` | Stable hash of normalized arguments. |
| `result_fingerprint` | Stable hash of normalized successful result. |
| `status_kind` | `success`, `error`, `denied`, `partial`, `empty`, `unknown`. |
| `progress_kind` | Tool-policy hint: `status`, `catalog`, `read`, `search`, `write`, `external_action`, `compute`. |
| `same_signature_streak` | Same tool + same args. |
| `same_result_streak` | Same tool + same args + same result. |

Normalization rules:

- JSON/dict results: sorted keys, remove unstable timing fields where safe.
- Strings: trim whitespace, cap/hash long payloads.
- Tool args: sort keys and omit transient fields only when tool policy marks
  them transient.

Escalation ladder:

| Streak | Action |
|---:|---|
| 2 | Add a precise hint: "same result as previous; do not call again unless you have a new hypothesis." |
| 3 | Apply exact-signature cooldown for low-progress tools. |
| 4 | Emit `duplicate_tool_result` / `tool_signature_cooldown` UI event. |
| 5 | Terminate with `repeated_success_no_progress`, summarizing what was already known. |

### 4.3 Tool Policy Metadata

Add optional metadata to `core/tools/definitions.json`.

```json
{
  "repeat_policy": {
    "progress_kind": "status",
    "same_result_limit": 2,
    "cooldown_rounds": 3,
    "terminate_after": 5,
    "idempotent": true
  }
}
```

Initial policy classes:

| Class | Examples | Default policy |
|---|---|---|
| `status` | `check_status`, `show_help` | Strict. Same args/result twice is enough to steer; repeated status is no-progress. |
| `catalog` | future `tool_catalog_digest` | Strict but useful once per turn. |
| `read` | `read_document` | Same path/hash can be repeated sparingly, but repeated identical result is no-progress. |
| `search` | `grep_files`, `general_web_search` | Allow more repetition if args differ; same query/result is no-progress. |
| `write` | `write_file`, `edit_file` | Duplicate intent requires HITL/idempotency semantics. |
| `external_action` | notifications/calendar/send tools | Duplicate intent should be blocked unless explicitly approved. |

### 4.4 Hermes-Style Tool Catalog Digest

Create a compact tool index analogous to `/llms.txt`:

- name
- category
- one-line purpose
- cost tier
- always-loaded/deferred status
- repeat policy summary

This separates "what tools exist?" from `check_status`. `check_status` should
return runtime health, model/auth, MCP activity, and daemon status; it should not
be the model's primary tool-catalog discovery path.

### 4.5 CLI Operator UX

Add operator-visible states for unbounded loops:

- `duplicate_tool_result`: same tool/signature/result repeated.
- `tool_signature_cooldown`: exact action temporarily blocked.
- `repeated_success_no_progress`: loop stopped because it was no longer gaining
  evidence.
- `semantic_progress_stalled`: future broader progress detector, not required
  for the first PR.

Correct existing wording:

- Current text: `Diversity: {tool} called {count}x — forcing alternative`
- Better text before hard enforcement: `Repeated tool: {tool} called {count}x — hinting alternative`
- Once cooldown/termination exists, show the actual runtime decision.

Improve HITL approval display:

- full operation label
- file/path or external target
- diff/preview where available
- timeout countdown
- explicit decision result: approved once, approved always, denied, timed out

Improve `geode status`:

- daemon PID and socket
- active sessions
- lane occupancy
- current run elapsed time
- current round
- last tool
- last progress event
- stuck/no-progress age

## 5. PR Stack

### PR 1 — Successful No-Progress Guard

**Goal:** stop repeated successful observations from becoming infinite loops.

Affected files:

| File | Change |
|---|---|
| `core/agent/convergence.py` | Add repeated-success observation tracking. |
| `core/agent/loop/agent_loop.py` | Invoke detector after tool results; terminate with `repeated_success_no_progress` when threshold is hit. |
| `core/ui/agentic_ui/events.py` | Add event emitters for duplicate result / no-progress termination. |
| `core/ui/event_renderer.py` | Render the new events. |
| `tests/core/agent/test_convergence_detector.py` | Unit tests for success repetition. |
| `tests/core/agent/test_autonomous_safety.py` | End-to-end loop guard tests. |

Acceptance:

- Repeated `check_status({})` cannot loop forever.
- Repeated `grep_files(...)` followed by repeated `check_status({})` cannot
  bypass the guard.
- Existing error convergence behavior is unchanged.
- `DEFAULT_MAX_ROUNDS = 0` remains unchanged.

### PR 2 — CLI Operator UX for Loop Control

**Goal:** make unbounded-loop state visible and steerable.

Affected files:

| File | Change |
|---|---|
| `core/ui/event_renderer.py` | Accurate repeated-tool/no-progress language. |
| `core/cli/ipc_client.py` | Richer approval panel and decision echo. |
| `core/cli/commands/lifecycle.py` | Extend `geode status` operator dashboard. |
| `core/cli/commands/_state.py` | Group `/help` by operational area. |

Acceptance:

- UI never claims a hard force when only a hint was injected.
- Approval UI shows enough detail to make a decision.
- Status shows enough runtime/lane information to diagnose a stuck turn.
- Non-TTY output remains clean.

### PR 3 — Tool Policy Metadata

**Goal:** move repeat behavior out of prompt prose and into structured tool
metadata.

Affected files:

| File | Change |
|---|---|
| `core/tools/definitions.json` | Add optional `repeat_policy` blocks. |
| `core/tools/base.py` or loader | Parse/validate repeat policy with backward compatibility. |
| `core/agent/convergence.py` | Use metadata thresholds instead of hard-coded tool names where available. |
| tests under `tests/core/tools/` | Schema/loader coverage. |

Acceptance:

- Missing `repeat_policy` is backward-compatible.
- `check_status` and status/catalog tools get strict defaults.
- read/search tools are not over-blocked.

### PR 4 — Hermes-Style Tool Catalog Digest

**Goal:** remove the incentive to grep `definitions.json` during live turns.

Affected files:

| File | Change |
|---|---|
| `core/cli/tool_handlers/system.py` or new tool handler | Add `tool_catalog_digest` / `check_tool_catalog`. |
| `core/tools/definitions.json` | Register catalog tool and narrow `check_status` description. |
| `core/llm/tool_defer.py` | Decide whether catalog digest is always-loaded. |
| `core/llm/prompts/router.md` | Optional, only if tests show routing needs a prompt nudge. Prompt hash update required if touched. |

Acceptance:

- "What tools are available?" routes to the catalog digest.
- "Is the daemon/MCP/auth healthy?" routes to `check_status`.
- No repeated `grep_files(core/tools/definitions.json)` is needed for normal
  tool discovery.

## 6. Alternatives Considered

### Add a default `max_rounds`

Rejected. GEODE explicitly uses unlimited rounds by default. A default cap
would prevent runaway loops but would also regress legitimate long-running
agentic work. The right guard is "no progress", not "many rounds".

### Prompt-only fix

Rejected as insufficient. Tool descriptions already tell the model not to call
`check_status` for model info, yet live logs show repetition. Runtime policy must
enforce the contract.

### Make diversity forcing a hard stop immediately

Rejected as too coarse. Some tools can repeat legitimately with different args
or changing external state. The guard should fingerprint signature/result and
apply policy per tool class.

### Hide `check_status`

Rejected. It is a valid health tool. The issue is conflating health status with
tool catalog discovery and treating repeated success as progress.

## 7. Implementation Checklist

- [ ] PR 1: repeated-success detector
- [ ] PR 1: no-progress termination reason and UI event
- [ ] PR 1: regression tests for `check_status` and `grep_files -> check_status`
- [ ] PR 2: accurate CLI event wording
- [ ] PR 2: approval panel detail/decision echo
- [ ] PR 2: operator dashboard fields
- [ ] PR 3: repeat policy schema and loader
- [ ] PR 3: metadata for strict status/catalog tools
- [ ] PR 4: tool catalog digest
- [ ] PR 4: route/catalog tests
- [ ] CHANGELOG entry for each functional PR

## 8. Verification

Targeted first:

```bash
uv run pytest tests/core/agent/test_convergence_detector.py
uv run pytest tests/core/agent/test_autonomous_safety.py
uv run pytest tests/core/tools/test_tool_category_tagging.py
uv run pytest tests/core/ui/test_event_schema_v2.py
uv run pytest tests/core/ui/test_agentic_ui.py
```

Then broad gates:

```bash
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/ -m "not live"
```

Manual/live checks:

```bash
geode serve
geode status
tail -f ~/.geode/logs/serve.log
```

Scenarios:

- Ask for MCP/tool status once; verify exactly one status/catalog call.
- Ask for tool list; verify catalog digest, not repeated `grep_files`.
- Simulate repeated `check_status({})`; verify no-progress termination.
- Approve a write operation; verify approval UI and daemon log agree.

## 9. Notes for Reviewers

- This plan intentionally preserves GEODE's unlimited-round contract.
- New termination reasons should be observable, not hidden inside a generic
  `forced_text`.
- Prompt changes should be avoided in PR 1/2. If PR 4 touches prompts, update
  `_PINNED_HASHES` in the same commit.
- Do not mix the tool catalog digest with MCP health. They answer different
  operator/model questions.
