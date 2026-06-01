# Self-improving campaign procedure

The end-to-end procedure for running a self-improving campaign: mutate GEODE's
scaffold, audit the scaffolded GEODE with Petri, score fitness against a frozen
ruler, and accept or revert on a statistically defensible gate. This file is the
git-tracked SoT for *how a campaign is run* — the operator decisions, the fixed
parameters, and the guards that keep the fitness comparison honest.

## 1. Goal

The loop optimizes GEODE's **scaffold** — the system-prompt sections and policy
artifacts that wrap the base model — NOT the base model's weights. One cycle:

1. The mutator proposes a single-section change to one scaffold artifact.
2. The change is applied to the in-repo SoT (`state/self_improving/policies/*`).
3. A Petri audit runs with the audit target = **GEODE-as-a-system**
   (`geode/gpt-5.5` → `GeodeModelAPI` → `AgenticLoop`), i.e. gpt-5.5 running the
   *mutated* scaffold as the base of its system prompt, with the auditor's seed
   scenario layered on top as `system_suffix`. The mutated scaffold is therefore
   in the causal path of the audited behaviour (pinned by
   `tests/test_geode_target_scaffold_injection.py`).
4. The audit's per-dimension judge scores are folded into a scalar **fitness**.
5. A **promote gate** compares the candidate's fitness against the baseline and
   either commits the mutation (new best) or reverts the SoT to pre-mutation.

The audit harness is Petri (`inspect_petri/audit` via `inspect_ai`); the fitness
logic and the gate are GEODE's. This split is fixed: audit = Petri, fitness =
GEODE's current logic version (the version tag is part of the baseline-epoch
spec hash — see `baseline-epoch-partition`).

## 2. The scaffold (what is mutated)

The mutable scaffold is the set of policy artifacts under
`state/self_improving/policies/`, dispatched by `mutation.target_kind`
(`core/self_improving/loop/policies.py::TARGET_KINDS`).

### 2.1 TARGET_KINDS (7 behaviour kinds)

| target_kind | SoT file | Role |
|-------------|----------|------|
| `prompt` | `wrapper-sections.json` | Wrapper system-prompt sections (base scaffold) |
| `tool_policy` | `tool-policy.json` | Tool-selection policy |
| `tool_descriptions` | `tool-descriptions.json` | Per-tool description + hints |
| `decomposition` | `decomposition.json` | Goal-decomposition policy |
| `reflection` | `reflection.json` | Reflection policy |
| `skill_catalog` | `skill-catalog.json` | Per-skill description + visibility |
| `agent_contract` | `agent-contracts.json` | Sub-agent contracts |

`retrieval` was deprecated (ADR-012 S0d, 2026-05-21). `hyperparam` was a mutable
slot from PR-HYPERPARAM-FOUNDATION (2026-05-28) through PR-AUDIT-SCAFFOLD-WIRE
(2026-05-31) but was **removed** from the mutable surface by
PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — see §2.2.

### 2.2 Optimizable vs reader-only vs fixed

- **Optimize (mutator may change)**: the 7 *behaviour* kinds —
  `prompt`, `tool_policy`, `tool_descriptions`, `decomposition`, `reflection`,
  `skill_catalog`, `agent_contract`.
- **Fixed (mutator may NOT change)**:
  - `hyperparam` (`seed_limit` / `max_turns` / `dim_set` / `reflection_depth`)
    is FIXED config, not mutated. `seed_limit` / `max_turns` / `dim_set` are
    audit-**measurement** parameters — changing them changes *how / what* the
    audit measures (sample count, turn budget, judged dim set), which would
    confound the mutated-vs-baseline fitness comparison. `reflection_depth` is
    a genuine runtime behaviour knob but its **axis is exhausted**: after ≥3
    prior applies the axis-family dedup (`mutator_feedback.py`,
    `_AXIS_REPEAT_LIMIT = 3`) rejects every new `reflection_depth` proposal as
    repetitive, so a single-section hyperparam surface exhausts the
    propose-guard every cycle. The whole `hyperparam` kind is therefore removed
    from `TARGET_KINDS`; a mutation carrying `target_kind="hyperparam"` is
    rejected at `parse_mutation` / `apply_mutation`
    (`_reject_hyperparam_mutation`, PR-DROP-HYPERPARAM-MUTATION, 2026-05-31;
    pinned by
    `tests/test_policy_mutation.py::test_parse_mutation_rejects_hyperparam_kind_with_clear_message`).
    The `hyperparam.json` SoT and its runtime readers
    (`core.self_improving.train._load_hyperparam_overrides`) are preserved — only the
    mutation surface is removed.
  - The `gpt-5.5` target weights (the base model is never trained).
  - The seed pools (cycle-input + held-out) — frozen rulers, see §4.

The remaining reader-only policy artifacts (style-guide, provider-routing,
cache-policy, heuristics, in-context-slots, few-shot-pool) are loaded by the
runtime but are not active mutation targets in this campaign.

## 3. The two-audit measurement

Each cycle produces two fitness numbers from two disjoint seed sets:

| Audit | Seed set | Size | Purpose |
|-------|----------|------|---------|
| **Selection** | cycle-input pool | 10 | Drives the `(1+1)` accept/revert decision *within* a generation. Co-evolves (moving ruler). |
| **Held-out** | frozen held-out bench | 10 | The fixed ruler. `held_out_fitness` is comparable *across* generations — the only curve that counts as evidence of real improvement. The mutator / seed-generation loop NEVER touches it. |

The two sets are assembled to be **disjoint** (see
`docs/self-improving/cycle-input-pool.md` and `docs/self-improving/held-out-bench.md`)
so held-out seeds never leak into the selection signal.

## 4. Baseline (gen-0) and the noise band

Before any mutation, gen-0 establishes the baseline:

- Run the audit **K times** on the unmutated scaffold to get a distribution of
  fitness, not a single point.
- The spread of those K repeats defines a **noise band** — the cycle-to-cycle
  variation attributable to sampling/judge noise rather than scaffold change.
- The promote gate's margin must clear this noise (see §5) so the loop does not
  "promote" a mutation whose apparent gain is within measurement noise.

The baseline is content-addressed into a **baseline-epoch** (`be-NNN`): the full
production+measurement spec (margin_rule, fitness/margin logic version, the 4
roles' model+source, rubric/dim-set, bench, seed-pool identity) is hashed; a spec
change starts a new epoch series (like seed-gen `gen-*`). See the
`baseline-epoch-partition` skill and `core/self_improving/loop/baseline_epoch.py`.

## 5. Per-cycle flow

Driven by `core/self_improving/loop/runner.py::SelfImprovingLoop.run_once`:

1. **Mutate** — the mutator LLM proposes one `(target_kind, target_section,
   new_value)`; `parse_mutation` validates it (bounds, char caps, the fixed-
   measurement rejection of §2.2).
2. **Apply** — `apply_mutation` writes the mutated SoT.
3. **Audit** — `run_once` with `rerun_enabled=True`, `rerun_dry_run=False` runs
   the real Petri audit (selection + held-out). The mutated scaffold is surfaced
   to the audit subprocess via the `GEODE_WRAPPER_OVERRIDE` env hook + the in-repo
   policy-override env vars (`core/self_improving/train.py`).
4. **Gate** — the promote gate compares candidate fitness vs baseline. The
   **margin** is a **fitness-scale stderr** (`√(σ_p² + σ_c²)` bootstrap over the
   per-sample dim rows; PR-MARGIN-FITNESS-SCALE, 2026-05-30) — NOT the per-dim
   stderr. A candidate promotes only if its fitness exceeds the baseline by more
   than this margin.
5. **Commit or revert** —
   - On a gate **promote**, `commit=True` persists the mutation (git-tracked SoT
     stays mutated) and the baseline advances.
   - On **reject**, the canonical SoT is **reverted** to pre-mutation
     (`feedback_sot_revert_on_reject`); an audit-subprocess crash also reverts.
6. **Degeneracy guard** — a candidate whose audit produced a degenerate signal
   (e.g. auditor quota throttle → `fitness=None`, all-zero dims) is NOT promoted
   and is recorded as degenerate rather than silently scored.

### 5.1 promote_policy (the gate's mode)

`promote_policy` (`baseline_epoch.py`, schema 2) selects how the accept decision
is made — this is the control-arm knob for the campaign in §6:

| promote_policy | Behaviour |
|----------------|-----------|
| `gate` | Promote iff fitness margin clears the noise band (the real optimizer). |
| `random` | Promote with a seeded coin flip regardless of fitness (control arm). |
| `never` | Never promote — no-mutation floor (control arm). |

`promote_policy_seed` pins the RNG for `random` so the arm is reproducible.

## 6. The 3-arm campaign

To attribute any observed improvement to the gate (and not to drift, seed
co-evolution, or chance), the campaign runs three arms, each from a **matched
gen-0 reset**:

1. **`never`** — no-mutation floor. Establishes the held-out fitness curve under
   zero scaffold change (pure measurement drift).
2. **`random`** — promote on a seeded coin flip. Establishes the curve under
   *undirected* scaffold change.
3. **`gate`** — the real optimizer, run **last** so the earlier arms set the
   reference curves it must beat.

Each arm starts from the same gen-0 baseline reset so the three held-out curves
are comparable. The arms are tagged in `mutations.jsonl` via `promote_policy` /
`promote_policy_seed` (`attribution.py`) so a downstream consumer can split the
JSONL stream by arm.

## 7. Artifacts and lineage

| Artifact | Path | Content |
|----------|------|---------|
| Mutation ledger | `state/self_improving/mutations.jsonl` | Every mutate / apply / audit / baseline / attribution row (git-tracked). |
| Policy SoTs | `state/self_improving/policies/*.json` | The current (best) scaffold — `git diff` shows mutation state. |
| Baseline | `state/self_improving/baseline.json` | The promoted baseline (advances only on a gate promote). |
| Baseline archive | `baseline_archive.jsonl` | One row per baseline epoch (`be-001` → …), content-addressed by spec hash. |
| Eval archive | `~/.geode/petri/logs/*.eval` (+ `latest.eval`) | Per-cycle Petri `.eval` — the single SoT for per-dim evidence. |
| Hub | self-improving hub pages | Serves baseline epochs (grouped) + the cross-generation evidence page, mirroring the seed-gen `gen-*` layout. |

Lineage: the held-out fitness curve, partitioned by baseline epoch and by
campaign arm, is the evidence surface. A logic change (margin rule, fitness
version, role model/source, rubric, bench, seed-pool) bumps the epoch hash so a
new series starts rather than mixing incomparable rulers.

## 8. Fixed parameters and guards (summary)

- **Audit harness**: Petri (`inspect_petri/audit`). Fixed.
- **Fitness logic**: GEODE current version (tagged into the epoch spec hash). Fixed within an epoch.
- **Target**: `geode/gpt-5.5` (GEODE-as-a-system; scaffold = base prompt, scenario = suffix). Fixed.
- **Measurement params** (`seed_limit`, `max_turns`, `dim_set`): fixed, mutator-rejected.
- **Seed pools**: cycle-input (selection, co-evolving) + held-out (10, frozen). Disjoint.
- **Margin**: fitness-scale stderr bootstrap (must clear the gen-0 noise band).
- **Revert-on-reject**: canonical SoT reverts to pre-mutation on gate reject or audit crash.
- **Degeneracy guard**: degenerate audits are never promoted.
- **Connection caps**: `--max-connections 1`, `--max-samples 1` (single-OAuth lane; `plugins/petri_audit/runner.py`).
