# Durable effect admission in agent runtimes

Date: 2026-09-01

## Decision

GEODE keeps planning and tool selection nondeterministic, but makes the
accepted external-effect boundary crash-explicit. The contract is:

> Durable effect admission with duplicate suppression and explicit uncertain
> outcomes.

This is not generic external exactly-once. Exactly-once requires the receipt
and the external mutation to commit in one authority, or a provider that
atomically enforces the same idempotency key. GEODE cannot impose that contract
on arbitrary MCP servers, shell commands, email providers, or deployment APIs.

## Frontier comparison

| Runtime | Recovery boundary | Duplicate/effect handling | Public limitation |
|---|---|---|---|
| Claude Code | Transcript resume; checkpoints for direct Write/Edit changes | Permission and sandbox before effects; deferred tool calls retain call ID and input before execution | Bash, remote API, database, and deployment effects are outside checkpoint rollback; no generic durable effect receipt |
| Codex CLI (`2f0a5d5`) | Rollout reconstruction and append-oriented recorder | Central retry is limited to sandbox-denial escalation; irreversible usage-reset has a dedicated caller idempotency key | Generic tool calls carry correlation `call_id`, not a general external-effect commit protocol |
| Prime Agent (`9f5edc1`) | Persistent session/worker journal | `clientId + commandId`: completed returns stored result; pending becomes `command_result_uncertain` and is not replayed | Transport duplicate suppression does not deduplicate a semantically repeated action issued under a new command ID |
| OpenClaw (`9b123e2`) | SQLite admission, recovery claims, and delivery queues | Read/search/list allowlist may replay; ambiguous mutation/send requires provider reconciliation; messaging keeps durable intent/receipt/tombstone state | Generic `ToolEffectReceipt` is process-local; durable guarantees are domain-specific |
| LangGraph | Checkpointed task results | Completed task results replay; incomplete tasks may run again, so API operations need idempotency keys or result lookup | Checkpointing alone does not make effects exactly-once |
| Temporal | Deterministic workflow history plus Activities | Activity completion is durable, but a worker can die after the effect and before completion is recorded; sink idempotency is required | An Activity may execute more than once even though one completion is observed |

Primary sources:

- [Claude Code checkpoint limits](https://code.claude.com/docs/en/checkpointing#limitations),
  [session resume](https://code.claude.com/docs/en/sessions#what-a-resumed-session-restores),
  and [deferred tools](https://code.claude.com/docs/en/hooks#defer-a-tool-call-for-later)
- [Codex tool orchestration](https://github.com/openai/codex/blob/2f0a5d5516c566e40b7abefea5f3c1f81fcd64bd/codex-rs/core/src/tools/orchestrator.rs#L305-L499),
  [rollout reconstruction](https://github.com/openai/codex/blob/2f0a5d5516c566e40b7abefea5f3c1f81fcd64bd/codex-rs/core/src/session/rollout_reconstruction.rs#L123-L163),
  and [usage-reset idempotency](https://github.com/openai/codex/blob/2f0a5d5516c566e40b7abefea5f3c1f81fcd64bd/codex-rs/app-server/src/request_processors/account_processor/rate_limit_resets.rs#L45-L94)
- [Prime Agent daemon contract](https://github.com/PrimeIntellect-ai/prime-agent/blob/9f5edc192cfe3d4737205a2f551d2b6b6e34fe09/packages/coding-agent/docs/daemon.md#L133-L150),
  [command journal](https://github.com/PrimeIntellect-ai/prime-agent/blob/9f5edc192cfe3d4737205a2f551d2b6b6e34fe09/packages/coding-agent/src/modes/daemon/command-recovery-journal.ts#L44-L125),
  and [technical report](https://arxiv.org/abs/2608.23552)
- [OpenClaw restart recovery](https://github.com/openclaw/openclaw/blob/9b123e263448b9d0cb673768ffb8b9ac185acdac/docs/gateway/restart-recovery.md#L88-L149),
  [replay-safe allowlist](https://github.com/openclaw/openclaw/blob/9b123e263448b9d0cb673768ffb8b9ac185acdac/src/agents/tool-replay-safety.ts#L1-L86),
  and [delivery reconciliation](https://github.com/openclaw/openclaw/blob/9b123e263448b9d0cb673768ffb8b9ac185acdac/src/infra/outbound/delivery-queue-recovery.ts#L719-L793)
- [LangGraph durable execution](https://docs.langchain.com/oss/python/langgraph/functional-api)
  and [Temporal Activity idempotency](https://docs.temporal.io/activity-definition#idempotency)

## Research grounding

| Work | Applicable lesson | GEODE consequence |
|---|---|---|
| RIFL, SOSP 2015 | Exactly-once RPC needs a unique request ID, durable completion record, retry rendezvous, and metadata GC; mutation and completion record must share an atomic authority | GEODE supplies ID/receipt/rendezvous/retention locally, but does not claim sink-level exactly-once |
| AWS Builders' Library | The caller supplies an intent token; argument hashes cannot distinguish a retry from an intentional duplicate request; same token with different parameters is a conflict | `operation_id` and argument fingerprint remain separate; a changed request under one ID is rejected |
| CapLease, arXiv:2608.01710 v1 | Approval tokens alone do not stop semantic replay under a new tool-call ID; canonical action, execution budget, commit protocol, and an idempotent sink are needed | Current receipts cover repeated logical operations, not semantic dedupe across newly issued operation IDs |
| Sagas, SIGMOD 1987 | Compensation is a new business effect, not rollback | No generic `compensate()` interface; add one only for a tool with a real verified inverse |

Sources: [RIFL](https://web.stanford.edu/~ouster/cgi-bin/papers/rifl.pdf),
[Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/),
[CapLease](https://arxiv.org/abs/2608.01710), and
[Sagas](https://doi.org/10.1145/38713.38742).

## GEODE contract

```text
model/tool caller
  -> checkpoint {provider call ID -> independent logical operation_id, step_id}
  -> SQLite admission before terminal dispatch
       new       -> dispatch once
       committed -> replay bounded PostToolUse-final result
       conflict  -> reject before dispatch
       prepared  -> outcome_uncertain; never auto-replay
  -> commit final receipt -> append balanced tool call/result
  -> strict checkpoint before auxiliary reflection or the next model request
```

- The rail applies to `MUTATE`, `COMMUNICATE`, and `ADMINISTRATIVE`.
- Agent-loop effect dispatch requires the existing session checkpoint
  authority. The assistant call strictly checkpoints the logical operation and
  sampling-step IDs before admission. Restart recovers only through that anchor;
  the provider call ID merely pairs tool use with tool result. Failed pending or
  balanced SQLite message writes stop the loop.
- `READ` remains retryable. Arbitrary `EXECUTE` keeps approval/sandbox
  controls and receives no exactly-once promise.
- Arguments are not stored in receipts. Non-personal calls retain a SHA-256
  fingerprint only for same-ID conflict detection. Personal calls store no
  content digest, so direct same-ID re-admission cannot prove equality and is
  rejected. Checkpoint-anchored restart recovery still uses the operation ID,
  step, call, and tool identity; results use the existing omission marker.
- Committed receipts are retained for 30 days and capped at 2,000 rows.
  Unresolved receipts are never silently dropped; admission fails closed at
  500 unresolved rows until an operator reconciles them.
- An unresolved older step blocks new effects in that session. Operators use
  `geode session effects` and `geode session resolve-effect` only after checking
  the external system. Both `applied` and `not-applied` become durable terminal
  reconciliation results; no automatic compensation or resend is inferred.
- A committed receipt suppresses only reuse of the same logical operation ID.
  The same real-world action issued under a new ID is a new intent unless a
  domain adapter supplies provider idempotency or reconciliation.

## Deliberate non-goals

- deterministic model trajectories;
- a workflow engine, two-phase commit coordinator, or generic saga layer;
- argument-hash-only semantic deduplication;
- blind retries of uncertain effects;
- a generic exactly-once claim for Bash, MCP, email, calendar, payment, or
  deployment systems.
