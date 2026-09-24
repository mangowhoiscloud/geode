# Conversation Compaction

`ContextWindowManager` owns context maintenance and public compaction
checkpoints. `core/orchestration/compaction.py` owns the text-summary transform;
`ContextBudgetPolicy` resolves planning limits for the selected model, provider,
source and requested output. The selected route also supplies the summarizer.
A summary is historical context, not a verified task result, tool receipt or
higher-priority instruction.

The September 25 changes are Unreleased. The
[research and counterexample record](../research/context-compaction-recovery-20260925.md)
separates source evidence, local behavior and unverified provider acceptance.

## Request admission and recovery

- `ModelCatalogSpec` distinguishes provider catalogue values, bundled client
  defaults and unknown-route fallbacks. API metadata does not establish a
  subscription account's limits. OpenRouter endpoint limits are not inferred
  from a similarly named direct-provider model.
- The effective prompt budget uses the selected window, known input cap and
  provider-specific requested output reserve. Codex omits the Platform output
  parameter; its local reserve is a planning default. The estimator includes
  system instructions, actual tool schemas and replayed provider content.
  Opaque bytes and images remain estimates, not server token counts.
- The retained `absolute_ceiling_tokens=200000` field is a **soft local
  maintenance preference**, not a universal input cap or rate-limit-pool rule.
  Crossing it alone does not authorize emergency pruning. The existing
  model-size warning bands and critical boundary remain separate.
- The shared root/auxiliary request path resolves the effective route after
  request middleware and tool allowlists. It performs one mutable maintenance
  check only if the request retains the caller's conversation. A middleware-owned
  replacement receives a read-only fit check; failure cannot compact unrelated
  original history. The final check before adapter execution does not repeat
  `PreCompact` or summarize another time.
- A classifier-confirmed provider overflow reaches bounded recovery even when
  the local estimate is low. Recovery uses an explicit operation outcome;
  equal message counts do not prove failure. A changed caller-history candidate is retried,
  and an accepted response clears the consecutive recovery counter. Neither
  a local estimate nor `changed` proves that the server accepts the next request.

## History, hooks and persistence

| Boundary / owner | Contract | Regression owner |
|---|---|---|
| Request preparation → context owner | Message count alone does not discard history. One physical request has at most one effectful preventive pressure check; direct auxiliary calls retain admission. | [Recovery dispatch](../../tests/core/agent/test_context_recovery.py) |
| `ContextWindowManager` → `PreCompact` | Only `keep_recent` may be rewritten; identity, counts, trigger and `hard` are read-only. Invalid mixed rewrites are rejected in full and audited. `defer` stops soft summary, not an explicit hard boundary. Earlier observation masking is a separate operation. | [Public hook decisions](../../tests/core/hooks/test_public_hooks.py) |
| Summary head / recent tail | Preserve causal tool-call/result pairs and the latest explicitly marked original user input. Ordinary synthetic user-role messages do not acquire that provenance. Repeated compaction does not duplicate the retained original. | [Compaction boundaries](../../tests/core/orchestration/test_compaction_phases.py), [input provenance](../../tests/core/agent/test_conversation.py) |
| Pending summary → candidate | Retain newly appended messages and their causal tail; reject a candidate if its summarized prefix was edited or replaced. The manager prevents nested compaction from committing another summary. | [Compaction phases](../../tests/core/orchestration/test_compaction_phases.py), [context manager](../../tests/core/agent/test_context_manager.py) |
| Artifact → live replacement → optional caller checkpoint | Persist the summary artifact first when a session ID is available. Replace messages, run the caller's supplied commit callback, then emit `PostCompact`. A failed callback restores the original live list; an already written artifact can remain. | [Persistence failure](../../tests/core/orchestration/test_compaction_phases.py), [context manager](../../tests/core/agent/test_context_manager.py) |
| Terminal context exhaustion | Keep the common finalizer's history/checkpoint behavior and return a local notice. Do not call another model just to describe failure or claim every entry point resets its session. | [Terminal and checkpoint](../../tests/core/hooks/test_extract_learning_models_adapter.py), [zero auxiliary usage](../../tests/core/llm/test_auxiliary_usage.py) |

`PostCompact.persisted` reports summary-artifact persistence. It does **not**
assert that a full replacement-history checkpoint committed. `/compact` supplies
a strict checkpoint callback when its loop owns a checkpoint. The
`manage_context` tool and model-switch path do not supply that callback; their
surrounding turn owns subsequent checkpointing. These stores are not one atomic
transaction. `PostCompact` failure cannot undo a completed replacement;
cancellation propagates while preserving whichever state already committed.
Pruning and cheap masking are separate operations, not hidden `PreCompact` /
`PostCompact` pairs. Public payload schemas remain v1/v2 compatible; resolved
route budgets are internal request state, not authority granted to observers.

Fresh `use_skill` output and its causal tool batch remain protected. A protected
tail can still exceed the budget and end as `context_exhausted`; protection does
not expand model capacity. System instructions continue to come from
`core/agent/system_prompt.py`. Tool-pair repair does not reconstruct missing
results, and a text summary cannot establish semantic fidelity on its own.

## Native and client compaction

Supported Anthropic models retain automatic threshold compaction. For the
selected Anthropic PAYG route, a successful native compaction block defines the
active suffix used for estimation without changing stored replay bytes. Empty
or failed blocks are not successful resets. Native tool-result clearing has a
separate capability list from threshold compaction.

Known Claude models without threshold compaction, including Haiku 4.5,
Sonnet 4.5 and Opus 4.5, can use client text compaction. Manual or confirmed-overflow recovery
on native-capable models can also use it **before a native compaction block is
present**. Unknown Anthropic models or histories containing native compaction
blocks are guarded against text replacement and pruning. A generic text prefix
could be ignored before a threshold block or violate an on-demand block's
position; silently deleting the block would lose continuity. Signed thinking
and causal tool pairs remain intact, with existing model-specific binding
controls retained.

OpenAI Platform, Codex, GLM and OpenRouter continue to use GEODE's client text
path. Public native endpoints or upstream harness implementations do not mean
those endpoints are connected in GEODE. This change adds no OpenAI native or
Anthropic on-demand backend and does not admit unavailable subscription routes.

## Model changes and resume

A model switch resolves the target route's budget before publishing the new
route. Required summarization still uses the previous model/provider/source.
Failed or deferred adaptation retains the previous route; a native-history
guard does not authorize dropping signed state to fit another model.
Resume restores authoritative checkpoint history without re-summarizing it;
the next actual request is checked against its current selected route.

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

This September 17 comparison remains a historical source snapshot, not a
claim about current upstream code. The September 25 research record pins the
newer source and preserves provider/account and test/live-evidence boundaries.
