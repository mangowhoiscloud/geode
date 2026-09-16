# Conversation Compaction

`ContextWindowManager` owns token-pressure decisions and public compaction
checkpoints. `core/orchestration/compaction.py` owns the text-summary transform;
`ContextBudgetPolicy` owns model-derived thresholds. The current provider/source
selects the summarizer through the existing adapter dispatch. A summary is not
a verified task result, a tool receipt, or a higher-priority instruction.

## Current contract

| Input / owner | Decision and output | Regression |
|---|---|---|
| Turn preparation → request preparation | Message count alone does not discard history. Before a model request, the existing token-pressure check selects maintenance or hard recovery. `ConversationContext.max_turns` remains a separate history-retention limit. | [Turn retention](../../tests/core/agent/test_agentic_loop.py) |
| `ContextWindowManager` → `PreCompact` | Soft compaction can be deferred. Failed/no-op soft compaction preserves the input messages; an explicit hard boundary may still prune. Earlier observation masking is separate and is not rolled back. | [Pressure and failure paths](../../tests/core/agent/test_context_manager.py) |
| `find_safe_boundary` → summary head / recent tail | Retained results retain their preceding calls, including parallel and non-adjacent results. Newly retained messages can extend the boundary again. Malformed orphan results do not invent a preceding call. | [Boundary and OpenAI parallel results](../../tests/core/orchestration/test_compaction_phases.py) |
| Text summarizer → context artifact → message replacement | When a session ID exists, persist the summary artifact before replacing in-memory messages. Summary or persistence failure is surfaced to the context owner, which retains the original list. `PostCompact` follows successful replacement. | [Persistence failure](../../tests/core/orchestration/test_compaction_phases.py), [public checkpoint](../../tests/core/agent/test_context_manager.py) |

The durable summary artifact is not a full replacement-history checkpoint.
Full conversation recovery still belongs to `SessionCheckpoint`; these stores
are not one atomic transaction. System instructions continue to be assembled
separately by `core/agent/system_prompt.py` and are not reconstructed from the
summary. Provider tool-pair repair remains a compatibility operation, not proof
that missing tool output was recovered.

## Codex comparison, pinned 2026-09-17

Source: OpenAI Codex main at
[`43354d0f61c1bda3eff26decaf13276bb57039e7`](https://github.com/openai/codex/commit/43354d0f61c1bda3eff26decaf13276bb57039e7)
(commit time 2026-09-16). This is source-level comparison plus deterministic
GEODE regressions, not a comparative model benchmark.

| Upstream direction | GEODE decision |
|---|---|
| [Pre-turn token-pressure gate](https://github.com/openai/codex/blob/43354d0f61c1bda3eff26decaf13276bb57039e7/codex-rs/core/src/session/turn.rs#L1242-L1271) | Remove the duplicate 30-message early-prune rule; reuse GEODE's existing pressure owner. |
| [Distinct pre-turn/manual and mid-turn initial context](https://github.com/openai/codex/blob/43354d0f61c1bda3eff26decaf13276bb57039e7/codex-rs/core/src/compact.rs#L60-L90) | Preserve the separate GEODE system-prompt owner. Do not copy Codex world-state machinery or claim identical message ordering. |
| [Preserve actual user messages](https://github.com/openai/codex/blob/43354d0f61c1bda3eff26decaf13276bb57039e7/codex-rs/core/src/compact.rs#L554-L580) | Prevent unnecessary early history loss and lost tool-result pairs. GEODE still uses a structured text summary plus recent messages, not Codex's user-message retention format. |
| [Session-owned replacement history](https://github.com/openai/codex/blob/43354d0f61c1bda3eff26decaf13276bb57039e7/codex-rs/core/src/session/mod.rs#L4006-L4079) | Preserve failed soft compaction instead of falling through to deletion. Crash/resume parity needs a separate full-history checkpoint experiment. |

## Remaining differences

- **Async model downshift:** the switch now awaits compaction on the previous
  model/provider/source before mutating the target route. A failed or deferred
  soft operation retains the old model and history; resume restores the
  checkpoint model without re-summarizing its authoritative history.
- **Manual commands:** `/compact` and `manage_context(action="compact")` share
  the async `ContextWindowManager` owner. They report `changed`, `unchanged`,
  `deferred`, `failed`, or `unsupported`; `/compact --prune` (and legacy
  `force=true`) is the explicit lossful path. Successful changes are written
  through the existing strict session checkpoint before `PostCompact` is sent.
- **Failure classes:** summary dispatch preserves billing, unavailable,
  transient, empty-output, and persistence failures. Only classifier-confirmed
  context-overflow causes retry with smaller input; other failures make one
  bounded attempt and leave history intact.
- **Native compaction:** the pinned Codex source gates remote V2 by provider
  capability and requires a completed response containing exactly one
  [Compaction output](https://github.com/openai/codex/blob/43354d0f61c1bda3eff26decaf13276bb57039e7/codex-rs/core/src/compact_remote_v2.rs#L437-L489).
  The public [Responses compaction contract](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide#compaction)
  also carries opaque encrypted state. Neither establishes that GEODE's
  subscription backend accepts the same operation. Native support needs an
  adapter capability, preserved opaque items through request/checkpoint/replay,
  and an authorized end-to-end probe. Do not substitute text for encrypted state
  or fall back to a billable provider implicitly.

These differences are not closed by the current text-compaction fixes. No live
provider call or native-compaction equivalence is claimed here.
