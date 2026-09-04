# Frontier retry-policy alignment

> Audited 2026-09-03. This note records the retry boundaries, evidence, GAPs,
> and closure criteria for the accompanying implementation. It does not claim
> undocumented Claude Code internals or turn SIL search attempts into transport
> retries.

## Boundary map

| Boundary | Owner | Budget | Replay rule |
|---|---|---:|---|
| Main model call | `core.agent.loop._phases` + `core.llm.fallback` | `llm_max_retries` total attempts per model | Same model only; no retry after visible streamed output |
| Auxiliary/model-chain call | `core.llm.router.call_with_failover` | Same setting per supplied model | May traverse only an explicitly supplied/allowed chain |
| SDK transport | Provider adapter | 0 SDK retries | Disabled so SDK and GEODE budgets cannot multiply |
| Pre-execution connection | `core.agent.loop._provider_call` | One reconnect | Only before a provider response or tool execution |
| Local tool recovery | `core.agent.tool_executor` | Three recovery actions | Automatic re-execution only for read/public/persist-safe tools |
| MCP reconnect | `core.mcp.tool_runtime` | One reconnect | Only `readOnlyHint` or `idempotentHint`; otherwise outcome is unknown |
| Interrupted side effect | `core.memory.effect_receipts` | No blind retry | Replay a committed receipt; require reconciliation for prepared/uncertain work |
| SIL candidate proposal | `evolve.scaffold_search.campaign` | `--mc`, default 8 | Semantic re-proposal after invalid/repetitive candidates, not HTTP retry |
| SIL replicate/audit | Scaffold-search campaign | Frozen experiment K/N and worker timeout | Measurement sampling; retain attempt lineage rather than hide it as retry |

The runtime boundary therefore exists at three different semantic levels:
request recovery, effect-safe execution recovery, and search/evaluation
replication. They share evidence where useful but must not share one counter.

## Frontier evidence and decision

| System (audit pin) | Observed policy | GEODE decision |
|---|---|---|
| [Codex `RetryPolicy`](https://github.com/openai/codex/blob/1281778e3273ab8e28c700ba84f5f12115e0ddc0/codex-rs/codex-client/src/retry.rs) | Provider-neutral 429/5xx/transport classification, exponential backoff with jitter, and retry telemetry | Keep GEODE's shared policy/taxonomy/telemetry owner |
| [OpenClaw retry contract](https://github.com/openclaw/openclaw/blob/89b5174bac4d77ff833bdcaa4e51d2feeeccffb4/docs/concepts/retry.md) | Current HTTP step only; 408/409/429/5xx, server delay, 60-second cap, and separate durable delivery recovery | Adopt wire semantics and preserve GEODE's durable effect boundary |
| [Prime Agent settings](https://github.com/PrimeIntellect-ai/prime-agent/blob/cd10724fe02bbe9a18592737de17c8101710bf73/packages/coding-agent/docs/settings.md#retry) | Agent retry defaults to three with 2/4/8-second backoff; SDK timeout/retry and 60-second provider-delay cap are independently configurable | Align the default count and cap, but keep SDK retries at zero to prevent multiplicative attempts |
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python/blob/370ee927ca8a8d3b5d4f907555e890b2df685786/src/anthropic/_base_client.py) | Parses `retry-after-ms`, numeric/date `Retry-After`, honors `x-should-retry`, and retries 408/409/429/5xx | Reproduce this small wire contract in GEODE's existing app-owned retry path |

Claude Code's complete runtime retry implementation is not public. The
Anthropic SDK is evidence for API-call behavior, not evidence for hidden
Claude Code session or tool-replay policy.

## GAP ledger

| GAP | Before | Resolution | Status |
|---|---|---|---|
| RETRY-GAP-01 | Main `AgenticLoop` hard-coded five attempts while auxiliary/provider/SIL calls read the documented default of three | Main loop snapshots `settings.llm_max_retries`; Pydantic rejects values below one | Closed |
| RETRY-GAP-02 | Disabling SDK retries also dropped standard retryable 408/409 responses | Shared classifier maps 408 to timeout and 409 to server | Closed |
| RETRY-GAP-03 | Local backoff ignored `retry-after-ms`, numeric/date `Retry-After`, and `x-should-retry: false` | Shared delay resolver uses the server value as a lower bound and fails fast above 60 seconds or on a veto | Closed |
| RETRY-GAP-04 | Interactive 429 ended immediately although billing exhaustion was already classified separately | Transient rate limits retry with jitter; structured billing remains terminal | Closed |
| RETRY-GAP-05 | Public config described a generic “retry count” and did not expose runtime/effect/SIL boundaries | EN/KO provider and config references now state total attempts and replay limits | Closed |
| RETRY-GAP-06 | No retry-specific wall-clock budget below the session time budget | Do not add one without latency/availability evidence; attempts and 60-second server-delay cap remain bounded | Deferred, evidence-gated |
| RETRY-GAP-07 | Successful context compaction reset the failure counter and could bypass the configured total-attempt limit | Compaction remains available after the second failure but no longer resets or extends the call budget | Closed |
| RETRY-GAP-08 | The shared runner emitted a retry event and provider compatibility path slept after the final failed attempt | Exhaustion now exits before telemetry or delay; every retry event guarantees a following call | Closed |
| RETRY-GAP-09 | The effort-surface probe copied a five-attempt, deterministic backoff loop | Probe calls the same configured interactive policy runner as the runtime | Closed |
| RETRY-GAP-10 | A logging bridge reported hard-coded SDK attempt `1/2` even though every built-in SDK client sets `max_retries=0` | Deleted the dead bridge and its tests; app-owned telemetry is the only retry signal | Closed |
| RETRY-GAP-11 | Wrapped auth/request/status errors, large attempt exponents, negative delay settings, and malformed Slack delays had inconsistent edge handling | Cause-chain classification, capped overflow-safe backoff, settings validation, and Slack's safe one-second parse fallback are regression-pinned | Closed |
| RETRY-GAP-12 | Public product/runtime copy still claimed first-retry cross-provider switching, a removed CircuitBreaker, a deleted sync helper, countdown UI, and the dead `retry_wait` emitter | Re-grounded both docs surfaces in the actual policy and removed the unused emitter while retaining protocol-side legacy event rendering | Closed |

## Exhaustive boundary disposition

The source audit searched retry/backoff/attempt loops across `core/`, `evals/`,
`evolve/`, and `scripts/`. The following numeric policies remain intentionally
local because they do not represent interchangeable LLM transport retries:

| Boundary | Why it remains local |
|---|---|
| Adapter capability dispatch: one reconnect | Web search/text capabilities have no outer AgenticLoop retry and must not change adapter or model |
| Strict evaluator: one connection retry, three empty-output attempts | Pre-tool infrastructure handling; semantic failures must remain observable to the benchmark |
| MCP: one reconnect | Requires `readOnlyHint` or `idempotentHint`; effect safety, not provider availability, owns the decision |
| Slack Web API: three 429 retries; Socket Mode reconnect loop | Slack's `Retry-After` and gateway lifecycle are external-service contracts, including delays above 60 seconds |
| Tool recovery: three strategies | Re-execution is gated by tool effect class and uses a separate execution-attempt lineage |
| Context summary: two smaller-input repairs | Repairs context overflow by changing summary input; it is not an identical wire retry |
| SQLite schema initialization: eight short lock attempts | Local lock contention during one process initialization, capped at 250 ms |
| SIL `--mc`: eight proposals | Semantic candidate re-proposal with experiment lineage, never hidden HTTP recovery |
| GEO extractor/verifier: two schema repairs plus one connection retry | Frozen evaluator procedure; changing it would change the measurement contract |
| tau2/Crucible sealed runs: zero in-run retries | Benchmark validity requires a new external attempt lineage after infrastructure failure |
| Public distribution verification | CLI-configurable polling of eventually consistent registries, not runtime execution |

## Preserved invariants

- Default routing fallback chains remain empty. Interactive recovery never
  silently changes the selected model or provider.
- Authentication, bad request, billing, context overflow, and post-output
  stream interruption remain terminal. A positive provider header cannot
  override these safety classifications.
- A server delay above 60 seconds is surfaced instead of making the CLI appear
  hung. Operators can explicitly switch a model/provider.
- Current side-effect receipts supersede the older missing-receipt audit:
  committed work can replay its result, while uncertain work cannot execute
  again without reconciliation.
- Historical SIL commits `f157317c8` (`retry_escape`) and `0f958c840`
  (`error_retry_gate`) were unmerged prompt/search experiments. They did not
  define the current HTTP retry budget and are not restored.
- The provider compatibility wrapper and `StreamProgress` have no in-tree
  production caller, but remain as an established import surface. They now
  delegate to the canonical runner and do not own a second retry algorithm.

## Verification contract

- Characterize 408/409, transient 429, jitter, millisecond/numeric/date server
  delays, long-delay/veto fail-stop, setting validation, and main-loop setting
  ownership.
- Preserve billing/request-fatal tests, stream replay protection, fallback
  strictness, effect-receipt recovery, and MCP idempotency gates.
- Run targeted tests first, then repository ruff, formatting, mypy,
  import-lint, full non-live pytest, generated-site checks, and `geode version`.
- No live provider call is required: this changes retry decisions after a
  deterministic provider error, not request/response payload compatibility.
