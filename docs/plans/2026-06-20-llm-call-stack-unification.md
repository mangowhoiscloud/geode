# LLM Call-Stack Unification — zero-regression resolution of the dual/triple retry stack

Status: in progress (2026-06-20)
Owner: scaffold session (feature/llm-stack-unify)
Constraint: **no observable behavior change.** Every item in §4 must stay true.

## 1. Problem

`call_llm` to a provider runs through one of **four** retry/failover/billing
implementations, not one:

| # | Surface | Used by | Policy |
|---|---------|---------|--------|
| 1 | `AgenticLoop.arun` inline retry (`agent_loop.py:1640-1894`) | main interactive loop (`acomplete` direct) | single-model, cap 5, `min(2^n,30)`; claude-cli transient → **terminal, no wait** |
| 2 | `call_with_failover` (`router/calls/_failover.py`) | reflection, self-improving runner | model-chain + jittered backoff + claude-cli **2m/10m/30m/2h wait** |
| 3 | sync `call_llm` → `provider_dispatch._retry_provider_aware` / `fallback.py` | `commentary.py` | provider routing + multi-attempt RETRYABLE backoff + OAuth-401 refresh + billing short-circuit |
| 4 | `dispatch.py` connection-transient retry (`_is_connection_transient`) | `web_search_via_adapters`, compaction, learning-extract | 1× same-adapter retry on connection-class only |

Plus a **dead** fifth surface: `ClaudeAgenticAdapter.agentic_call` + `ANTHROPIC_FALLBACK_CHAIN`
multi-model failover (`providers/anthropic.py:859,1025`) and the four legacy router
entry points (`call_llm_with_tools_async` / `_json` / `_parsed` / `_streaming_async`)
— **only test + docstring callers** (verified: `tests/core/llm/test_tool_use.py`, no
`core/`/`plugins/` production caller).

### The key insight (why this is NOT "collapse to one")

Surfaces 1 and 2 diverge **by design**, not by accident:

- **Interactive (surface 1)**: claude-cli pool exhaustion → `rate_limit` →
  `model_action_required`, **immediately**. The operator switches model or resumes.
  This is the deliberate v0.90.0 "auto-escalation removed; surface to the user" contract
  (`agent_loop.py:1803-1804`).
- **Autonomous (surface 2)**: the self-improving evolver has no operator watching, so it
  **waits out** the 5-hour pool refresh (2m/10m/30m/2h). Removing this re-opens smoke-24
  (all 5 evolver phases hard-failed in 30s; manual resume succeeded 20 min later —
  `_failover.py:144-150`).

So the resolution **preserves both policies** and makes the split *explicit and named*
(an `on_quota` / retry-policy parameter) instead of *implicit in which function you call*.
It does not force one behavior on all callers.

## 2. Scope

**In scope (this plan):**
- Phase A — delete the confirmed-dead router surface (no live caller).
- Phase B — converge surfaces 2 + 3 onto one hardened, billing-honest helper that
  preserves each consumer's policy via parameters; delete the now-orphaned transport.

**Deferred (separate decision, NOT this plan):**
- Phase C — folding surface 1 (`arun` inline retry) onto the shared helper. The arun
  loop is intertwined with context-overflow recovery, the round-indexed retry budget,
  and checkpoint-before-retry. Its policy is intentionally different. Merging it risks
  the v0.90.0 contract + context-recovery paths for marginal gain. Leave as-is; only
  share the *taxonomy* (RETRYABLE/NON_RETRYABLE sets + `classify_llm_error` +
  `is_billing_fatal`) so 1 and the shared helper classify identically.

## 3. Phases

### Phase A — delete dead router surface (pure removal, behavior-preserving)
Verified dead (test/doc callers only):
- `core/llm/router/calls/{tools,json,parsed,streaming}.py` + the four `__all__`
  re-exports in `router/__init__.py` + `router/calls/__init__.py`.
- `ClaudeAgenticAdapter.agentic_call` + `ANTHROPIC_FALLBACK_CHAIN` + its `call_with_failover`
  call (`providers/anthropic.py`), IF nothing else in that file's live exports needs them.
- The pinning tests (`tests/core/llm/test_tool_use.py` for the dead entry points).
Keep: `providers/anthropic.py` / `providers/openai.py` shared helpers (client singletons,
cache-control, computer-use flags, `_get_openai_client`/`reset_openai_client`,
RETRYABLE/NON_RETRYABLE sets) — used live by the adapter stack.
Gate: full grep proves zero live caller before each delete; quality gates green.

### Phase B — converge auxiliary retry onto one hardened helper
1. Promote `call_with_failover` to a shared, billing-honest retry helper (location TBD:
   `core/llm/adapters/retry.py` or keep in router but harden). Add the three short-circuits
   it currently lacks (must NOT be assumed-present): `is_billing_fatal` → `BillingError`
   no-retry; `is_request_fatal` (400 unsupported-param) no-retry; OAuth-401 one-shot
   `_try_oauth_refresh`. Parameterize: `quota_backoff: bool`, `on_terminal: raise|return_none`,
   `emit_started_ended: bool`.
2. Migrate **reflection** (`_reflection.py:345`) and **self-improving runner**
   (`runner.py:824`) onto it — single-model, `quota_backoff=True` (runner load-bearing),
   `on_terminal=return_none` (reflection) / `raise` (runner). Behavior-identical.
3. Migrate **commentary** (`commentary.py:63`) off sync `call_llm`. Decision point:
   `complete_text_via_adapters` (dispatch.py:620) only retries once on connection-class —
   a real reduction vs the current multi-attempt RETRYABLE backoff. Either (a) give the
   shared helper a sync wrapper preserving multi-attempt retry, or (b) accept + document
   the reduced retry for the best-effort 256-token narration. Pick (a) to keep zero-regression.
4. Delete the orphaned transport: old `call_with_failover` location, sync `call_llm`
   (`router/calls/text.py`), and consolidate `provider_dispatch._retry_provider_aware`
   into the shared helper once commentary no longer uses it.

## 4. Behavior-preservation checklist (any change MUST keep these)

Main loop (Phase C / leave-as-is, but shared taxonomy must match):
1. Single-model retry, no auto-escalation (`agent_loop.py:1803`).
2. `_LLM_RETRY_CAP=5`; backoff `min(2^failures,30)` no jitter; counter reset on success + compaction.
3. Terminal (no-retry) for `auth`/`bad_request`/`rate_limit`.
4. claude-cli transient → `rate_limit` → terminal `model_action_required` (NO wait) — **interactive policy, keep**.
5. Context-overflow prune-and-`continue` (3 paths).
6. `LLM_CALL_STARTED`/`ENDED` bracket each acomplete (usage+cost on success); `LLM_CALL_FAILED`/`RETRIED`.

Auxiliary (Phase B — must survive the migration):
7. `RETRYABLE=(RateLimit,APIConnection,InternalServer,Overloaded/529)`; `NON_RETRYABLE=(Authentication,BadRequest)`.
8. Jittered backoff `uniform(0, min(base*2^n, max))`, defaults 3/2.0/30.0.
9. claude-cli **2m/10m/30m/2h** on `ClaudeCliTransientUpstreamError` — **self-improving load-bearing (smoke-24)**.
10. `is_model_allowed` filter; all-blocked → `(None,None)`.
11. Return `(result, model_used)`; `(None,None)` on exhaustion; never raises for retryable/quota/unknown.
12. Runner raises `RuntimeError` on None; reflection keeps previous state on None/except (opposite terminal contracts).
13. `LLM_CALL_RETRIED` emission preserved.

Billing (must be added to the shared helper — currently absent in `_failover.py`):
14. `is_billing_fatal` → `BillingError` no-retry, with plan metadata.
15. `is_request_fatal` (400 unsupported-param) → no-retry.
16. OAuth-401 one-shot `_try_oauth_refresh` (attempt 0 only) — commentary relies on it via fallback.
17. Shared billing code sets (`_GLM_BILLING_CODES`/`_OPENAI_BILLING_CODES`/`_ANTHROPIC_BILLING_TYPES`).

Dispatch (untouched):
18. Connection-transient single same-adapter retry, name-based incl. raw httpx, billing-excluded per cause-link.
19. `_select_adapter` strict no-fallback (exact provider+source, partial=None).

## 5. Socratic gate

- **Q1 already exists?** No — no single shared retry surface exists; that's the problem.
- **Q2 what breaks if skipped?** The triplicated auxiliary retry drifts (one fix misses two
  sites), and the dead router surface masks `grep` (the −900 LoC phantom). Billing-honesty
  is already inconsistent (`_failover` lacks `is_billing_fatal`) — a latent bug.
- **Q3 measure?** Each item in §4 gets a guard test; full suite + targeted retry/billing tests green; live smoke deferred (cost) but the quota-backoff path pinned by unit test with mocked clock.
- **Q4 simplest?** Phase A is pure deletion. Phase B is one helper + 3 call-site migrations. Phase C deferred (don't touch the loop).
- **Q5 frontier pattern?** Yes — single retry/transport layer with per-call policy is the
  convergent shape (Codex/Claude Code/openclaw all centralize transport retry).

## 6. Sequencing & risk
- Phase A first (independent, safe, unblocks grep). Ship, verify, then Phase B.
- Phase B step 1 (harden helper) + step 2 (reflection/runner) before step 3 (commentary) —
  commentary is the subtle one (retry-count parity).
- Phase C explicitly deferred with operator note.
- Each phase = own PR, CI 5/5 + Codex MCP, behavior tests for the §4 items it touches.
