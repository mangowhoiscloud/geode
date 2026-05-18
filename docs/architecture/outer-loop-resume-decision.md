# ADR — Outer-Loop Checkpoint + Resume on Credential Rollout

> **Status**: Accepted (2026-05-19)
> **Scope**: GEODE outer-loop (autoresearch + seed-pipeline). When a subscription credential (Claude Code OAuth, ChatGPT Plus OAuth) hits its quota mid-run, the operator must be able to swap accounts and **resume from the last completed unit of work** without re-spending budget on already-finished generations / candidates / matches.

## Context

The 2026-05-19 outer-loop config consolidation plan introduced strict subscription mode (`fallback_to_payg=false` default) so subscription exhaustion aborts with an actionable banner instead of silently rolling over to PAYG. The strict-abort is correct, but creates a new failure mode: a long outer-loop run (multi-generation seed evolution or overnight autoresearch ratchet) loses everything in flight at the moment of abort. The user explicitly asked (2026-05-19): "outer-loop 가 subscription 초과로 끊겨도, 계정 롤아웃해서 이어갈 수 있게 체크포인트와 같은 replay-resume 조치가 되어있는지 점검."

The user also specified the research-before-decision order: "ADR 들어가기 전에 관련 레퍼런스 디깅 + 원본인 co-scientist 의 패키지 구현본을 살펴서 이에 대한 고려가 되어있는지도 확인."

### Reference findings (2026-05-19 agent research, summarised)

| Source | Has resume? | Mechanism |
|---|---|---|
| co-scientist paper (arXiv:2502.18864) | claimed (1 sentence: *"easy restarts in-case of any failure"*) | "persistent context memory" — mechanism/schema undefined |
| co-scientist reference impl (Swarms `AI-CoScientist`) | partial / **stubbed-broken** (README TODO lists "Fix state saving") | per-agent JSON files; broken in released code |
| Karpathy autoresearch | not designed — `program.md` explicitly forbids pause | de-facto: git commit + `results.tsv` per accepted generation; resume = re-run agent in same worktree |
| **LangGraph** | ✅ first-class | `Checkpointer` interface (SqliteSaver / MemorySaver / PostgresSaver), `(thread_id, checkpoint_id)` key, step-level granularity, `Command(resume=...)` semantics |
| **Inspect_ai** | ✅ first-class | `.eval` log file + stable sample IDs + `inspect eval-retry`; sample ID = idempotency key, up to 10 retries default |
| **Stripe API** | ✅ pattern (`Idempotency-Key` header) | client-generated UUID per logical operation, server caches result ≥24h, `Idempotent-Replayed: true` on replay |
| OpenAI Agents SDK | ❌ explicitly rejected (issue #2172 closed as not planned) | — |
| AutoGen v0.4 | primitives only (`save_state` / `load_state`) | implementer adds policy |
| Hermes credential_pools | auto-rotate on 429/402 | silent rotation; **multiple active bugs** (#11364 / #6907 / #15099) for token overwrite + persistence; does NOT survive process death |
| OpenClaw | broken (#26872 / #50791 / #51917 / #62442) | session JSONL but in-flight sub-agent work dropped on restart |
| AutoGPT | none native | manual log-backup workaround |
| CrewAI Flows | pluggable `FlowPersistence` (LanceDB) | `kickoff(restore_from_state_id=...)` — but silent fallback on miss |

Net: **co-scientist neither in paper nor reference impl provides a usable design**. The real prior art is LangGraph (`thread_id` checkpointer) + Inspect_ai (stable sample IDs + retry-idempotent) + Stripe (idempotency-key replay), with Codex CLI's `forced_login_method` already adopted for the banner side.

### GEODE current state (audit summary)

| Layer | Surface | Persist | Load | Resume-ready |
|---|---|---|---|---|
| C3 | `core/runtime_state/session_checkpoint.py` `SessionCheckpoint` | ✅ atomic_write_json + SQLite | ✅ `load()` / `list_resumable()` | ✅ `/resume <session_id>` CLI |
| C2 | `core/memory/project_journal.py` ProjectJournal | ✅ fsync + append | tail/aggregate only | ❌ audit only |
| Outer | `~/.geode/outer-loop/sessions.jsonl` (P1a) | ✅ append | tail only | ❌ index only |
| Outer | `~/.geode/outer-loop/<session>/journal.jsonl` (P1c) | ✅ append | tail only | ❌ event audit |
| Seed-pipeline | `<run_dir>/state.json` (S8 `_persist_state`) | ✅ write_text (non-atomic) | ❌ **`_load_state()` 미구현** | ❌ |
| Autoresearch | `autoresearch/state/baseline.json` (P0a) | ✅ atomic | ✅ `_load_baseline()` | partial (promote/run only) |
| Primitive | `core/utils/atomic_io.py` | tmp + `os.replace` + `fsync` | — | ✅ |

**Key insight**: GEODE already has `SessionCheckpoint` — a production-ready C3 checkpoint+resume layer with `atomic_write_json` + SQLite + `/resume` CLI. The outer-loop drivers (seed-pipeline + autoresearch) are NOT yet layered on top of it. The S8 `_persist_state` comment says *"S11 CLI `geode audit-seeds resume` will re-hydrate"* but the load path is not implemented.

## Decision

**Layer the outer-loop drivers on top of the existing `SessionCheckpoint`** rather than build a parallel checkpoint system. Borrow three frontier patterns directly:

1. **LangGraph-style** — `SessionCheckpoint` already provides `(session_id, ...)`-keyed SQLite-backed snapshots with atomic writes. Outer-loop just needs to call `SessionCheckpoint.save()` at safe boundaries and `SessionCheckpoint.load()` on resume.
2. **Inspect_ai-style** — Every unit of work (generation, candidate, match, audit) gets a stable ID that acts as the idempotency key on resume. Already-completed units are skipped on re-invocation; partially-complete units retry from the last completed step.
3. **Stripe idempotency-key** — Per-(run_id, unit_id, agent_role) UUID embedded in LLM call metadata. A local response cache keyed by that UUID short-circuits the duplicate spend after credential rollout.

The credential-rollout boundary stays **user-driven** (Codex `forced_login_method` pattern adopted in PR-β1) — no auto-rotation. The new resume mechanism reduces the cost of the manual swap from "lose the entire run" to "lose ≤ one unit of work."

### Coarseness — checkpoint between units, not between LLM calls

Per autoresearch's `git commit per generation` + co-scientist's "Supervisor writes state periodically" + LangGraph's super-step boundary: checkpoint between **units**, not inside them.

| Driver | Unit boundary | Checkpoint write trigger |
|---|---|---|
| autoresearch | generation (= one `train.py` invocation = one audit subprocess) | after `_should_promote()` decision, before `_write_baseline()` |
| seed-pipeline | phase (Generation → Proximity → Critic → Pilot → Ranker → Evolver → MetaReviewer) | after `_run_phase()` returns, before next `_run_phase()` |
| Petri inner-loop | sample (one seed × auditor × judge transcript) | already handled by `inspect_ai` `.eval` log — GEODE outer-loop just records `eval` path |

Inside a unit (e.g., mid-LLM-call), we accept "lose this unit" as the cost ceiling. Checkpointing inside an LLM call is rejected (storage churn vs. UX value).

### Idempotency-key shape

```
<run_id>::<driver>::<unit_kind>::<unit_id>::<agent_role>

Examples:
  2026-05-19T1530Z-a1b2c3 :: seed-pipeline :: phase     :: pilot      :: pilot-llm
  2026-05-19T1530Z-a1b2c3 :: seed-pipeline :: candidate :: c-007      :: critic
  2026-05-19T1530Z-a1b2c3 :: seed-pipeline :: match     :: m042       :: voter-haiku
  2026-05-19T1610Z-b4c5d6 :: autoresearch  :: audit     :: 7f3a9c2    :: judge
```

Logged into `~/.geode/outer-loop/<session>/journal.jsonl` (P1c) per LLM call. On resume, the runtime scans the journal for completed `<...key>` entries and skips them.

### Credential context captured in checkpoint

```json
{
  "session_id": "2026-05-19T1530Z-a1b2c3",
  "gen_tag": "autoresearch-176d8778",
  "active_sources": {
    "anthropic": "claude-cli",
    "openai":    "openai-codex"
  },
  "completed_units": ["...idempotency-keys..."],
  "next_unit": {"driver": "seed-pipeline", "kind": "phase", "id": "ranker"},
  "fallback_to_payg": false
}
```

On resume:
1. Re-resolve sources via `resolve_credential_source(..., fallback_to_payg=cfg.fallback_to_payg)`.
2. If active source changed (e.g., claude-cli → claude-cli on a different account), record it in the checkpoint with a `credential_rolled_over_at` marker so the journal carries the boundary.
3. If the user explicitly requested `fallback_to_payg=true` on the resume invocation that was `false` on the original, the runtime emits a `credential_policy_change` event into the journal before continuing.

### Within-source account rotation (paperclip / crumb pattern)

A separate dimension from the cross-source PAYG ramp blocked by PR-β1: **multiple accounts inside the same `family.source`** (e.g., two Claude Code OAuth accounts the operator has both stored). The 2026-05-19 user directive — "paperclip, crumb 의 사례처럼 로컬에 기록된 계정 기록으로 롤아웃" — refers to this case. paperclip / crumb (cf. `docs/audits/2026-05-18-i2-paperclip-review.md`, external repo `~/workspace/crumb/`) achieve it via `claude -p` subprocess picking up `~/.claude/credentials` automatically + symlink swap or env var for account selection. The pattern is **non-interactive subprocess + locally-recorded credential**.

GEODE already has a richer, in-process equivalent — `core/auth/profiles.py` (AuthProfile / ProfileStore / EligibilityResult), `core/auth/rotation.py` (`ProfileRotator.resolve(provider)` returning best-eligible, `mark_failure` → cooldown, managed-token auto-refresh ≤120 s pre-expiry), `core/auth/credential_breadcrumb.py` (LLM-readable hint per ProfileRejectReason — Claude Code `createModelSwitchBreadcrumbs` parity). Outer-loop currently uses none of it; `plugins/petri_audit/credential_source.py` only does process-local `suppress_credential_source(family, source)` (no profile dimension).

**Decision** (Phase ζ extension):

1. **Wire `ProfileRotator` into the outer-loop credential path.**
   `resolve_credential_source(family, ..., fallback_to_payg)` returns the source key (e.g. `claude-cli`); a new layer `resolve_outer_loop_binding(family) → (source, profile)` adds the second dimension. autoresearch / seed-pipeline pass `profile.name` through every LLM call so failures route into `ProfileRotator.mark_failure(profile)` instead of the in-process suppress set.

2. **Rotation is operator-driven, never automatic.** When strict-mode trips abort (PR-β1's `CredentialResolutionError(subscription_only=True)`), the FE banner (PR-γ1) checks whether ProfileRotator has another eligible profile for the same family. If yes, the abort dialog shows a 2-axis picker (next sub-section). If no, the dialog shows the existing "add a profile / wait for reset / opt-in PAYG" options.

3. **Rollout boundary writes to journal.** The new active `(source, profile)` is captured in the checkpoint and a `credential_rolled_over` event is appended to `~/.geode/outer-loop/<session>/journal.jsonl` (P1c). Idempotency keys per LLM call (PR-ζ4) already include `agent_role`, so a swapped account picks up the same cache entries when applicable.

### Account picker UX (2-axis, GEODE slash-command parity)

Per 2026-05-19 user directive — "자연어 뿐 아니라 UI/UX 로도 선택/입력 가능 (GEODE 슬래시 명령어 구조 참고). provider 변경은 좌우, 계정 선택은 위아래" — the picker is a 2D interactive selector mirroring the existing `pick_model_and_effort` pattern in `core/cli/effort_picker.py` (Claude Code `ModelPicker.tsx` parity):

```
┌─ Subscription quota exhausted — claude-cli (anthropic:work) ─────────┐
│                                                                       │
│  ◀ anthropic    openai     zhipuai ▶          (←/→ change provider)  │
│                                                                       │
│  Profiles for anthropic:                                              │
│    anthropic:work                              [exhausted]            │
│  ▶ anthropic:personal     OAuth · 0% used      [eligible]    ↑↓      │
│    anthropic:org-shared   OAuth · 12% used     [eligible]             │
│    anthropic:api-key      api_key · PAYG       [blocked by strict]    │
│    + Add new profile…                                                 │
│                                                                       │
│  [Enter] swap & resume     [n] add new     [w] wait for reset         │
│  [p] opt-in PAYG fallback (this run only)    [Esc] keep aborted       │
└───────────────────────────────────────────────────────────────────────┘
```

Entry points (both required per directive):

1. **Slash command**: `/login` already exists for account add/remove (`core/cli/commands/login.py`). Extend with `/login picker` or trigger via `/account` alias to open the 2-axis picker directly. Auto-triggered when banner is red (aborted state).
2. **Natural language**: agent loop recognises phrases like "swap account", "use my other Claude account", "rollout to next profile" and invokes the same picker programmatically.

Implementation reuses `pick_model_and_effort`'s raw-tty 2-axis input loop. Per directive: **provider = ←→, account = ↑↓**. The action row (`[Enter] / [n] / [w] / [p] / [Esc]`) makes the policy boundary explicit — there is no automatic rotation; every swap is a user keystroke.

## Non-Decisions (explicitly rejected)

| Alternative | Why rejected |
|---|---|
| Hermes-style auto credential rotation | Silent rotation hides cost (contradicts `feedback_test_cost`) + Hermes's own bug tracker (#11364, #6907, #15099) documents the rotation logic is fragile |
| Build a parallel checkpoint system | `SessionCheckpoint` already exists and is production-ready; layering on top reuses atomic_write + SQLite + `/resume` CLI |
| Per-LLM-call checkpointing | Storage churn / IO cost not worth the marginal UX win; unit boundary is sufficient |
| `CrewAI silent fallback on missing checkpoint ID | violates `anti-deception-checklist` — fail loudly instead |
| autoresearch "never pause" policy | works for a single-user single-credential ML run; breaks for multi-credential outer loop |
| Generic re-run on abort (no checkpoint) | re-spends the entire run's budget; defeats the purpose of strict-mode subscription |

## Consequences

### Positive
- Subscription rollout becomes a routine operational gesture rather than a full restart.
- Idempotency keys also unblock provider-side response caching when the SDK supports it.
- Builds on existing `SessionCheckpoint`, reducing risk and code surface.
- The 3 frontier patterns are battle-tested at scale (LangGraph, Inspect_ai, Stripe).

### Negative
- Adds `~1500 LOC` to the consolidation sprint (1 PR per phase ζ row).
- Idempotency-key bookkeeping makes every LLM call slightly heavier; mitigated by limiting checks to unit-boundary hits, not per-token.
- The unit-level granularity means **a single unit's mid-flight cost is still lost** on credential abort; this is the accepted ceiling.

### Out-of-scope (deferred)
- Multi-process file lock for parallel resume — single-resumer assumption is acceptable for v1.
- Hook replay on resume — emit only `RESUME_STARTED` once, not the full lifecycle re-emit.
- Cross-machine resume — checkpoint files are path-portable but require manual copy.

## Implementation plan

Lives as Phase ζ in `docs/plans/2026-05-19-outer-loop-config-consolidation.md`. **8 PRs** (~2100 LOC + 1 backfill) — expanded from 6 after the 2026-05-19 paperclip/crumb directive:

- **PR-ζ1**: extend `SessionCheckpoint` schema for outer-loop fields (active_sources, completed_units, next_unit, fallback_to_payg, active_profile). Tests round-trip.
- **PR-ζ2**: `_load_state()` companion for `plugins/seed_pipeline/orchestrator.py:PipelineState`. CLI flag `geode audit-seeds resume <run_id>`.
- **PR-ζ3**: autoresearch `_load_pending_audit()` + `--resume <session_id>` flag in `autoresearch/train.py`.
- **PR-ζ4**: idempotency-key embedding in LLM call metadata + local response cache lookup (`~/.geode/outer-loop/<session>/idempotency.db`).
- **PR-ζ5**: credential-rollover detection — at resume, compare active sources to checkpoint; emit `credential_rolled_over_at` event into journal.
- **PR-ζ5.5** (NEW): wire `ProfileRotator` into the outer-loop credential path. `resolve_outer_loop_binding(family) → (source, profile)` adds the profile dimension. `plugins/petri_audit/credential_source.py` routes failures through `ProfileRotator.mark_failure(profile)` instead of the in-process suppress set. autoresearch + seed-pipeline pass `profile.name` through LLM call metadata so cooldowns track per-account.
- **PR-ζ5.6** (NEW): 2-axis account picker (provider ←→ × profile ↑↓), mirroring `core/cli/effort_picker.py`. Two entry points: (a) `/login picker` slash command + auto-trigger from the red banner abort dialog (PR-γ1 trigger condition), (b) agent loop natural-language phrase recogniser invokes the picker programmatically. Action row: Enter (swap+resume) / n (add new profile via `claude /login` subprocess delegate) / w (wait for reset) / p (opt-in PAYG for this run) / Esc (keep aborted).
- **PR-ζ6**: docs + sample resume run-book (`docs/audits/2026-05-19-resume-rollout-runbook.md`) + CHANGELOG.

## Reference

- co-scientist paper (arXiv:2502.18864): https://arxiv.org/abs/2502.18864 (§4.5 "persistent context memory" + §5 "Supervisor agent")
- co-scientist reference impl: https://github.com/The-Swarm-Corporation/AI-CoScientist (README TODO marks save-state as broken)
- Karpathy autoresearch: https://github.com/karpathy/autoresearch (`train.py` + `program.md`)
- LangGraph Checkpoints: https://reference.langchain.com/python/langgraph/checkpoints
- Inspect_ai eval-retry: https://inspect.aisi.org.uk/reference/inspect_eval-retry.html
- Stripe idempotency: https://docs.stripe.com/api/idempotent_requests
- Codex CLI `forced_login_method`: https://developers.openai.com/codex/config-reference
- Hermes credential_pools (negative reference): https://hermes-agent.nousresearch.com/docs/user-guide/features/credential-pools
- OpenAI Agents SDK issue #2172 (closed as not planned): https://github.com/openai/openai-agents-python/issues/2172
- GEODE `SessionCheckpoint`: `core/runtime_state/session_checkpoint.py`
- GEODE `atomic_io`: `core/utils/atomic_io.py`
- Predecessor plan: `docs/plans/2026-05-19-outer-loop-config-consolidation.md`
- Predecessor ADRs: `docs/architecture/seed-pipeline-decision.md`, `docs/architecture/autoresearch-axis-decision.md`
