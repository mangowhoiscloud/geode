# Karpathy autoresearch vs GEODE autoresearch — mapping & rationale

> Companion to the hero visualization. The GEODE `autoresearch/` directory
> ports the **3-file scaffold + fixed-budget loop + git-as-optimiser**
> idiom from
> [karpathy/autoresearch](https://github.com/karpathy/autoresearch)
> (MIT, 2026-03) verbatim, then swaps the domain from GPT pre-training
> to GEODE's alignment audit. This doc lists every borrowed, changed,
> and added element so the visualization (and any future agent prompt)
> can ground its narrative against the actual divergence.

## 1. Direct copies — borrowed verbatim

| Element | Karpathy original | GEODE adaptation |
|---|---|---|
| Three-file shape | `prepare.py` / `train.py` / `program.md` | identical names + roles |
| Single-file mutation scope | agent edits `train.py` only | agent edits `train.py` only |
| Fixed 5-min wall-clock budget per run | "Training runs for a fixed 5-minute time budget … regardless of the details of your compute." | `BUDGET_MINUTES = 5` in `autoresearch/train.py` |
| Git-as-optimiser idiom | branch tip = best run; `git reset` = discard | identical — see `program.md` "The experiment loop" |
| One-shot per invocation | `uv run python train.py` runs one experiment | identical entry point |
| Read-only harness | `prepare.py` immutable | `prepare.py` immutable, only verifies harness (no fineweb / BPE) |
| Loop-from-agent | "Point your agent here and let it go" | identical pattern; `program.md` boots a self-improving loop agent (Claude Code / Codex CLI) |
| Self-contained / minimal deps | "Self-contained with minimal external dependencies" | only the existing GEODE `[audit]` extra |

## 2. Domain swap — what changed

| Layer | Karpathy original | GEODE adaptation | Why |
|---|---|---|---|
| **Domain** | GPT pre-training | LLM alignment auditing | GEODE's stated research goal is improving its own agent harness, not training a GPT |
| **Mutation target** | model architecture / hyperparams / optimizer (Muon + AdamW) inside `train.py` | `WRAPPER_PROMPT_SECTIONS` dict + audit-runner hyperparameters (`BUDGET_MINUTES`, `TARGET_MODEL`, `JUDGE_MODEL`, `USE_OAUTH`, `SEED_LIMIT`, …) | wrapper-prompt sections are the only thing that can change agent behaviour without re-training the LLM |
| **Workload** | one full GPT training run on a single GPU | one `geode audit` subprocess invocation (~5 min wall-clock) consuming ChatGPT Plus / Anthropic quota | matches GEODE's deployment reality |
| **Metric** | `val_bpb` (validation bits-per-byte, lower better, vocab-size-independent) | AlphaEval fitness scalar — 17-dim weighted aggregate + stability axis, higher better | val_bpb is irrelevant for an agent harness; AlphaEval rubric is the agent-safety SoT |
| **Optimiser** | Muon + AdamW gradient descent | none — it's a discrete prompt-mutation loop, not differentiable | wrapper-prompt sections are text, not weights |
| **Promote signal** | val_bpb decreased | `decide_promote` rule: `raw_fitness_gain > max(prior_stderr, 0.05)` + every critical dim within `baseline_stderr + critical_margin` | statistical significance threshold under judge-LLM noise |
| **Data prep** | fineweb download + BPE tokenizer training | sanity check on Petri seed pool + AlphaEval rubric + audit CLI reachability (no downloads) | the seed pool is shipped in the repo, not generated |

## 3. Additions — what GEODE added on top

| Addition | Where | Why it's new (no Karpathy original counterpart) |
|---|---|---|
| **Multi-objective tiered scoring** | `AXIS_TIERS` (5 critical / 12 auxiliary / 3 info) in `autoresearch/train.py` | val_bpb is scalar; alignment audit needs differentiated risk policy across dims |
| **Critical floor (hard reject)** | `compute_fitness` — `if new_mean > baseline + stderr + margin: return 0.0` | safety dims must not be traded for efficiency gains |
| **Auxiliary squared penalty** | `compute_fitness` — `λ × (Δ / 10)²` summed across 12 aux dims | soft regularization on non-safety axes |
| **Stability axis** | `_stability_score = 1 / (1 + mean(dim_stderr))` | judge-LLM noise floor needs to enter fitness; rewards confident measurements |
| **`baseline.json` snapshot** | `autoresearch/state/baseline.json` written on every promote | enables cross-run baseline regression detection |
| **Cross-run priors** | `meta_review.json` + `latest_meta_review.json` symlink (PR-G4) | "what did the last meta-reviewer flag" feedback that Karpathy original doesn't model |
| **seed-generation pipeline** | `plugins/seed_generation/` (S0-S11; 7 specialist agents — generator / proximity / critic / pilot / ranker / evolver / meta_reviewer) | Karpathy original treats seeds as fixed; GEODE evolves them via a Co-Scientist-style sub-loop |
| **Petri-side measurement layer** | `plugins/petri_audit/` + `core/audit/dim_extractor` | Karpathy original folds measurement into `train.py`; GEODE separates measurement (Petri) from selection (autoresearch) for SoT clarity |
| **SessionJournal observability** | `~/.geode/self-improving-loop/<session>/journal.jsonl` | Karpathy original logs only via stdout + `results.tsv`; GEODE adds structured events (config_snapshot, audit_started, baseline_decision, cost_divergence …) |
| **Cost / quota tracking** | `usd_spent` rollup + cost-divergence journal events (PR-P2) | irrelevant for local-GPU training; mandatory for LLM-API budgets |
| **Cross-loop handoff** | `latest_seed_pool` symlink (PR-G1) | seed-generation → autoresearch evolved-pool ingestion; Karpathy original has no equivalent |

## 4. Visualization mapping — for the hero video

| Hero video Bit | Karpathy element | GEODE element shown |
|---|---|---|
| 1-4 Stage 1 (Co-Scientist pattern) | N/A — Karpathy seeds are fixed | seed-generation 7-agent grid |
| 5-8 Stage 2 (Petri audit) | training step + val_bpb evaluation | Petri audit subprocess + 20-dim rubric grid + dim_extractor → dim_means / dim_stderr |
| 9 compute_fitness | `val_bpb = ...` | `fitness = Σ wᵢ · score(dim_meansᵢ) + w_stab · stability` |
| 10 critical floor | **none — Karpathy has no equivalent** | regression of any critical dim past `baseline + stderr + margin` → fitness 0.0 |
| 11 auto-promote | "keep or discard the run" | `gain > max(stderr, 0.05)` rule; baseline.json updated on promote |
| 12 next generation | `git commit` + agent loop continues | wrapper-prompt mutation; gen N → gen N+1; cycle closure |
| Outro ratchet chart | `results.tsv` series | fitness over generations + commit chain |
| Rubric Detail page | none (val_bpb is scalar) | 20-dim tiered rubric + Petri audit emits + autoresearch aggregates |
| Glossary | terse README | 19-term EN/KO term/definition table |

## 5. Acknowledgement

The 3-file pattern, fixed-budget single-script idiom, and "git as
optimiser" framing are direct quotes (in design intent) from
[karpathy/autoresearch](https://github.com/karpathy/autoresearch).
GEODE's contribution is the *domain swap + multi-objective tiered
scoring + cross-loop measurement separation* layered on top. The
visualization is faithful to both: the agent grid (Bits 1-4) is the
Karpathy idiom + Co-Scientist agent menu; everything from Bit 5
onward (Petri audit, fitness composition, critical floor, promote
rule, ratchet chart) is GEODE-specific.

## 6. Files & line references

* GEODE autoresearch: `autoresearch/train.py`
  - `_dim_score` (line 627)
  - `_stability_score` (line 635)
  - `compute_fitness` (line 672)
  - critical-floor branch (line 692)
  - `DIM_WEIGHTS` / `STABILITY_WEIGHT` (lines 224 / 246)
  - `AXIS_TIERS` 5+12+3 listing (line 196)
* Karpathy autoresearch: https://github.com/karpathy/autoresearch
  (228791f) — local reference clone `~/workspace/autoresearch/`
* GEODE README on this split: `autoresearch/README.md`
  "Role split — petri vs autoresearch" table.
