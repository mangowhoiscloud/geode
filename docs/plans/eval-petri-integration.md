# Plan: Petri × GEODE — Alignment Audit Integration (PoC)

> Branch: `feature/eval-petri-integration` (base: `main`, develop branch absent at start)
> Worktree: `.claude/worktrees/eval-petri-integration`
> Author: 2026-05-10 session
> Status: Phase P0 (GAP Audit) complete — entering P1 (skeleton)

## Problem

GEODE has no alignment evaluation pipeline. The agentic loop (`core/agent/loop/loop.py:57` `AgenticLoop`) executes user-facing tasks but cannot be probed for misaligned behaviors (sycophancy, unprompted self-preservation, harmful sysprompt cooperation, unprompted whistleblowing).

Without an audit pipeline:
- No empirical signal on which dimensions GEODE is at risk for as production autonomy grows.
- No basis for designing a domain-specific evaluator (the eventual goal — referred to here as "path B").
- Future capability changes ship without a regression baseline on alignment behavior.

This plan integrates Petri (Anthropic alignment auditing tool, currently maintained at `meridianlabs-ai/inspect_petri`) as an external audit harness to produce that signal. The integration is intentionally PoC-scoped: produce data, not commit to a long-term framework.

## Socratic Gate

| # | Question | Answer |
|---|----------|--------|
| Q1 | Does it already exist in code? | No. GAP Audit confirmed: `inspect-ai`/`inspect_petri` absent from `pyproject.toml`; no `core/eval/`, no `plugins/petri_audit/`; no Petri-related identifiers (`TargetContext`, `audit_judge`) anywhere. Existing `tests/_live_audit_runner.py` is GEODE's E2E runner, unrelated to Petri. |
| Q2 | What breaks if we don't do this? | (a) Path B (own evaluator) has no design input. (b) Production agent ships alignment-blind — when GEODE gains broader tool access (hooks, scheduler, gateway), no regression test catches drift on `unprompted_initiative` / `unprompted_self_preservation` / `cooperation_with_harmful_sysprompt` / `unprompted_whistleblowing`. |
| Q3 | How do we measure the effect? | Three metrics. (1) Petri's 38 judge dimensions, focused on the 4 target axes above. (2) Per-run cost (KRW), enforced gate at < 5,000 KRW (Phase P2) and < 30,000 KRW (Phase P3). (3) Trace integrity — confirm GEODE's hook-based RunLog (introduced v0.89.0 after external tracing removal) captures Petri-driven invocations correctly. |
| Q4 | What is the simplest implementation? | Inspect AI Custom Target (`execute(state, context: TargetContext)`) calling `AgenticLoop` directly. No HTTP wrapper. `target_tools="none"` so Petri does not simulate tools — GEODE's real tool loop runs. Optional extra dependency (`uv sync --extra audit`) keeps cold-start untouched. |
| Q5 | Is this pattern in 3+ frontier systems? | Yes. (1) Petri itself (Anthropic Alignment Science). (2) Inspect AI framework (UK AISI) — same `Task` + `Solver` + `Scorer` pattern. (3) OpenAI Evals — separated grader from target model. The 3-role separation (auditor/target/judge) is established cross-vendor. |

## Design

### Approach

**Path A — Inspect AI Custom Target** (selected over an OpenAI-compatible HTTP wrapper).

```
Petri auditor (e.g. claude-sonnet-4-6)
    ↓ multi-turn conversation via Inspect AI's Channel transport
GEODE Custom Target  (plugins/petri_audit/targets/geode_target.py)
    ↓ execute(state, context: TargetContext)
AgenticLoop (core/agent/loop/loop.py:57)
    ↓ tool-use loop with GEODE's real tools
        ↓
Petri judge (e.g. claude-opus-4-6 or haiku-4-5 for cost)
    ↓ scores transcript across 38 dimensions
RunLog (GEODE hook system, post-v0.89.0)
```

Key design constraints from current GEODE state (v0.89.3):

- **Cold-start protection**: v0.89.1–v0.89.3 reduced cold-start by 46% / 20% / 53% via lazy imports. `inspect-ai` is heavy (~200ms+ import). Mitigation: `[project.optional-dependencies] audit = [...]` + lazy import inside `plugins/petri_audit/` — never imported in default cold path.
- **Type strictness**: B2 batches (v0.88.3–v0.88.5) removed mypy ignores. New code must be `mypy core/ plugins/` clean with zero new ignores.
- **Trace integration**: Observability is hook-based after the external tracing dependency was removed. Petri runs should emit through the same hook system, not a separate trace channel.
- **Petri version**: `main` branch (3.0) — `v3.0.4` Custom Target API + `v3.0.6` `cache` parameter are required. The 2.0 stable tag (release `v2.0.0`, 2026-01-22) lacks the Custom Target ergonomics. Pin by commit SHA at install time.

### Affected Files

| File | Change |
|------|--------|
| `pyproject.toml` | Add `[project.optional-dependencies] audit = ["inspect-ai>=0.3.211", "inspect-petri @ git+https://github.com/meridianlabs-ai/inspect_petri@<sha>"]` |
| `plugins/petri_audit/__init__.py` | New — plugin entry, lazy export only |
| `plugins/petri_audit/wiring.py` | New — registry hookup mirroring `plugins/game_ip/wiring.py` |
| `plugins/petri_audit/adapter.py` | New — adapts GEODE `AgenticLoop` to Petri `TargetContext` semantics |
| `plugins/petri_audit/targets/geode_target.py` | New — `execute(state, context: TargetContext)` implementation |
| `plugins/petri_audit/seeds/` | New (P3) — GEODE-specific seeds beyond Petri's 181 built-ins |
| `plugins/petri_audit/dimensions/` | New (P3) — focused dimension subset (4 target axes + GEODE-specific) |
| `core/domains/loader.py` | Register `petri_audit` plugin (defer until P2 to avoid hot-path import) |
| `tests/plugins/petri_audit/test_skeleton.py` | New — smoke test that does not require `inspect-ai` installed |
| `CHANGELOG.md` | Entry under appropriate version bump (PoC = MINOR) |

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Path B: HTTP wrapper exposing GEODE as OpenAI-compatible endpoint | Loses Inspect AI's cache, rollback, trajectory branching, refusal fail-open. ~Same implementation cost with worse capabilities. |
| Petri 2.0 (stable v2.0.0 tag) | Lacks `execute(state, context)` (added v3.0.4) and `cache` parameter (added v3.0.6). Migration to 3.0 later doubles work. |
| Place under `core/eval/` | Would imply core-level promotion of an external evaluator. Plugin layout (`plugins/petri_audit/`) matches the precedent of `plugins/game_ip/` and respects layering. |
| Add `inspect-ai` as a regular dependency | Reverses the v0.89.x cold-start work. |
| Build own evaluator from scratch immediately (skip Petri) | Path B is the long-term goal but lacks design input — Petri PoC produces the data needed to define GEODE-specific axes. |

## Phased Rollout

| Phase | Scope | Cost gate |
|-------|-------|-----------|
| P0 — GAP Audit | Verify nothing exists | 0 |
| P1 — Skeleton | `plugins/petri_audit/` directories + stub `geode_target.py` (returns `NotImplementedError`) + smoke test. **No `inspect-ai` import.** First PR. | 0 |
| P2 — Live Smoke | Add `[audit]` extra. Implement `execute()` against real `AgenticLoop`. Run 3 seeds × `max_turns=10` × Haiku judge. | < 5,000 KRW |
| P3 — Tag Subset | Extend to one tag (e.g. `tags:sycophancy`, ~10 seeds). Add focused dimension subset. Halt and report. | < 30,000 KRW |
| P4 — Path B Design Input | Analyze which dimensions produced signal. Specify GEODE-native evaluator axes. Plan handed off to a separate branch. | 0 |

P3 is a deliberate pause point — full 181-seed runs are not authorized until findings justify it.

## Cost Controls

| Lever | Effect | Setting |
|-------|--------|---------|
| `cache=true` (Petri 3.0.6) | 30–70% reuse on shared prefixes outside rollback siblings | `-T cache=true` |
| Tag filtering | ÷~18 vs full | `-T seed_instructions=tags:<tag>` |
| `max_turns=10` | ÷3 vs default 30 | `-T max_turns=10` |
| Haiku judge | ÷5 vs Opus | `--model-role judge=anthropic/claude-haiku-4-5` |
| GEODE `--dry-run` target (where supported) | ÷10+ vs full LLM path | engaged in P1 only, P2+ uses real path |
| `realism_filter=false` (default) | 1 fewer model call per turn | leave default |

## Known Risks

| Risk | Mitigation |
|------|------------|
| Petri 3.0 has no release tag — `main` API may shift | Pin install to a specific commit SHA. P2 fallback path: switch to `petri-v2` branch. |
| `meridianlabs-ai/inspect_petri` is not under the Anthropic org (rename of `safety-research/petri`). License: MIT. | Documented; no Anthropic-official guarantee assumed. Pin SHA, vendor-hash-check, MIT-compatible. |
| `develop` branch absent at start — gitflow drift vs CLAUDE.md L153 | This branch took `main` as base. Documented above. Resolve at PR time (rebase if `develop` is recreated). |
| GEODE 1-turn = 5–20 LLM calls inside `AgenticLoop` (cost multiplier) | Cost gates at P2 (< 5K KRW) and P3 (< 30K KRW); halt-and-report at P3. |
| Naming: `audit` keyword overlaps with `tests/_live_audit_runner.py` | Plugin uses `petri_audit` (compound name). Internal terms `auditor`/`target`/`judge` are Petri's, kept distinct from GEODE's existing `evaluator`/`verification`. |
| Cold-start regression if lazy import is broken | P1 acceptance: import time of `geode` CLI unchanged ±2% with and without `[audit]` installed. |

## Implementation Checklist

- [ ] P1 — `plugins/petri_audit/` skeleton (no `inspect-ai` import in default path)
- [ ] P1 — `pyproject.toml` `[audit]` optional extra (commit SHA-pinned)
- [ ] P1 — Smoke test that runs without `[audit]` installed
- [ ] P1 — Lint + Type check + cold-start regression check
- [ ] P1 — CHANGELOG entry + first PR
- [ ] P2 — Real `execute()` implementation against `AgenticLoop`
- [ ] P2 — 3-seed × 10-turn × Haiku-judge live run
- [ ] P2 — Cost report (< 5K KRW)
- [ ] P3 — One-tag subset (~10 seeds) + focused dimension subset
- [ ] P3 — Findings report; halt-and-decide
- [ ] P4 — Hand off learnings to Path B (own evaluator) plan

## Verification (P1 acceptance)

```bash
uv run ruff check core/ tests/ plugins/
uv run mypy core/ plugins/
uv run pytest tests/ -m "not live"
uv run geode analyze "Cowboy Bebop" --dry-run        # E2E unchanged: A (68.4)

# Cold-start regression check (no audit extra installed)
hyperfine --warmup 3 'uv run geode --version'        # within ±2% of baseline
```

P2 acceptance adds:

```bash
uv sync --extra audit
inspect eval inspect_petri/audit \
  --model-role auditor=anthropic/claude-sonnet-4-6 \
  --model-role target=geode \
  --model-role judge=anthropic/claude-haiku-4-5 \
  -T seed_instructions=tags:sycophancy \
  -T max_turns=10 \
  -T cache=true
```

## References

- Anthropic blog (Petri 1.0): https://www.anthropic.com/research/petri-open-source-auditing
- Anthropic Alignment blog (Petri 2.0): https://alignment.anthropic.com/2026/petri-v2/
- GitHub repo: https://github.com/meridianlabs-ai/inspect_petri
- Docs site: https://meridianlabs-ai.github.io/inspect_petri
- CHANGELOG (3.0.x): https://github.com/meridianlabs-ai/inspect_petri/blob/main/CHANGELOG.md
- Inspect AI framework: https://github.com/UKGovernmentBEIS/inspect_ai
- Petri 2.0 release tag: https://github.com/meridianlabs-ai/inspect_petri/releases/tag/v2.0.0
- Frontier precedent: Anthropic Petri (own), UK AISI Inspect AI (target framework), OpenAI Evals (separation pattern).
- GEODE entry point: `core/agent/loop/loop.py:57` (`AgenticLoop`)
- GEODE plugin reference: `plugins/game_ip/`
- GEODE vendor-free trace path (v0.89.0): hook system + RunLog
