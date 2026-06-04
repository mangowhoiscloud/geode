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
| Fixed 5-min wall-clock budget per run | "Training runs for a fixed 5-minute time budget … regardless of the details of your compute." | `BUDGET_MINUTES = 5` in `core/self_improving/train.py` |
| Git-as-optimiser idiom | branch tip = best run; `git reset` = discard | identical — see `program.md` "The experiment loop" |
| One-shot per invocation | `uv run python train.py` runs one experiment | identical entry point |
| Read-only harness | `prepare.py` immutable | `prepare.py` immutable, only verifies harness (no fineweb / BPE) |
| Loop-from-agent | "Point your agent here and let it go" | identical pattern; `program.md` boots a self-improving loop agent (Claude Code / Codex CLI) |
| Self-contained / minimal deps | "Self-contained with minimal external dependencies" | only the existing GEODE `[audit]` extra |

## 2. Domain swap — what changed

| Layer | Karpathy original | GEODE adaptation | Why |
|---|---|---|---|
| **Domain** | GPT pre-training | LLM alignment auditing | GEODE's stated research goal is improving its own agent harness, not training a GPT |
| **Mutation target** | model architecture / hyperparams / optimizer (Muon + AdamW) inside `train.py` | 7 behaviour scaffold kinds (`TARGET_KINDS`): prompt / tool_policy / decomposition / reflection / skill_catalog / agent_contract / tool_descriptions | the scaffold surfaces are the only thing that can change agent behaviour without re-training the LLM |
| **Workload** | one full GPT training run on a single GPU | one `geode audit` subprocess invocation (~5 min wall-clock) consuming ChatGPT subscription / Anthropic quota | matches GEODE's deployment reality |
| **Metric** | `val_bpb` (validation bits-per-byte, lower better, vocab-size-independent) | AlphaEval fitness scalar — 18-dim taxonomy (5 critical / 10 auxiliary / 3 info), 15 weighted + stability axis, higher better | val_bpb is irrelevant for an agent harness; AlphaEval rubric is the agent-safety SoT |
| **Optimiser** | Muon + AdamW gradient descent | none — it's a discrete prompt-mutation loop, not differentiable | the scaffold surfaces are text, not weights |
| **Promote signal** | val_bpb decreased | `_should_promote` rule: `fitness_gain > max(_MARGIN_GAIN_SIGMA·√(σp² + σc²), 0.005)` (targeted-σ for targeted runs) + every critical dim within `baseline_stderr + critical_margin` | statistical significance threshold under judge-LLM noise |
| **Data prep** | fineweb download + BPE tokenizer training | sanity check on Petri seed pool + AlphaEval rubric + audit CLI reachability (no downloads) | the seed pool is shipped in the repo, not generated |

## 3. Additions — what GEODE added on top

| Addition | Where | Why it's new (no Karpathy original counterpart) |
|---|---|---|
| **Multi-objective tiered scoring** | `AXIS_TIERS` (5 critical / 10 auxiliary / 3 info — 18-dim taxonomy, 15 weighted) in `core/self_improving/train.py` | val_bpb is scalar; alignment audit needs differentiated risk policy across dims |
| **Critical floor (hard reject)** | `compute_fitness` — `if new_mean > baseline + stderr + margin: return 0.0` | safety dims must not be traded for efficiency gains |
| **Auxiliary squared penalty** | `compute_fitness` — `λ × (Δ / 10)²` summed across the 10 aux dims | soft regularization on non-safety axes |
| **Stability axis** | `_stability_score = 1 / (1 + mean(dim_stderr))` | judge-LLM noise floor needs to enter fitness; rewards confident measurements |
| **`baseline.json` snapshot** | `state/self_improving/baseline.json` written on every promote | enables cross-run baseline regression detection |
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
| 5-8 Stage 2 (Petri audit) | training step + val_bpb evaluation | Petri audit subprocess + 18-dim rubric grid; the LLM judge scores each transcript directly into `dim_means` / `dim_stderr` (100% LLM-judge-scored — no script-computed dim since #1964) |
| 9 compute_fitness | `val_bpb = ...` | `fitness = Σ wᵢ · score(dim_meansᵢ) + w_stab · stability` |
| 10 critical floor | **none — Karpathy has no equivalent** | regression of any critical dim past `baseline + stderr + margin` → fitness 0.0 |
| 11 auto-promote | "keep or discard the run" | `gain > max(_MARGIN_GAIN_SIGMA·√(σp² + σc²), 0.005)` rule; baseline.json updated on promote |
| 12 next generation | `git commit` + agent loop continues | scaffold mutation (one of 7 `TARGET_KINDS`); gen N → gen N+1; cycle closure |
| Resolution (honest result) | `results.tsv` series | the measured run — `broken_tool_use` improved by 0, never-arm drift 2.67 → 3.38 (noise > mutation signal), per-arm table + 18-dim headroom-vs-noise ranking (`docs/self-improving/run-2606-broken-tool-use.md`) |
| Rubric Detail page | none (val_bpb is scalar) | 18-dim tiered rubric + Petri audit emits + autoresearch aggregates |
| Glossary | terse README | 19-term EN/KO term/definition table |

## 4b. File-by-file walk — `autoresearch_filewalk.py`

The hero video and the high-level overview scene (`autoresearch_compare.py`)
both stay in the "what is borrowed / swapped / added" register. The
**filewalk** scene zooms in on the three files themselves so the
domain swap is visible as a diagram, not a table.

| Filewalk Bit | What it shows | Source for the data |
|---|---|---|
| 1 — 6-panel grid | Karpathy `{prepare, train, program}` vs GEODE `{prepare, train, program}` side by side, with LoC + top symbols per panel | this doc §3 + LoC counts measured 2026-05-21 (`wc -l` on `autoresearch/` + Karpathy 228791f) |
| 2-4 — per-file detail | Two large panels per file (prepare.py / train.py / program.md) with full outline + LoC delta arrow | this doc §1-§3 + actual `grep -c "^def\|^class"` |
| 5 — LoC bar chart | Karpathy vs GEODE bars for each file; arithmetic Δ in the same row | 3 measurements above; `prepare.py 390→203 (-187)`, `train.py 724→1308 (+584)`, `program.md ~200→360 (+160)` |
| 6 — 3×3 heatmap | rows = file, cols = (verbatim / swapped / added), cells = qualitative intensity in [0, 1] | this doc §1-§3 — counts of items in each section, normalised |
| Outro | one-line takeaway: *"Same scaffold. Different objective. Bigger safety perimeter."* + 3-color dot row | summary of §1-§3 |

Render:

    uv run manim -qh -o AutoresearchFilewalk-EN \
        scripts/visualizations/autoresearch_filewalk.py AutoresearchFilewalk
    GEODE_HERO_LANG=ko uv run manim -qh -o AutoresearchFilewalk-KO \
        scripts/visualizations/autoresearch_filewalk.py AutoresearchFilewalk

Source: `scripts/visualizations/autoresearch_filewalk.py`. Heatmap
intensities are hard-coded in the module-level `HEATMAP` dict and
sourced from §1-§3 of this document — when the comparison evolves,
update both sides together.

## 5. Acknowledgement

The 3-file pattern, fixed-budget single-script idiom, and "git as
optimiser" framing are direct quotes (in design intent) from
[karpathy/autoresearch](https://github.com/karpathy/autoresearch).
GEODE's contribution is the *domain swap + multi-objective tiered
scoring + cross-loop measurement separation* layered on top. The
visualization is faithful to both: the agent grid (Bits 1-4) is the
Karpathy idiom + Co-Scientist agent menu; everything from Bit 5
onward (Petri audit, fitness composition, critical floor, promote
rule, honest Resolution) is GEODE-specific.

## 6. Files & line references

* GEODE autoresearch: `core/self_improving/train.py`
  - `_dim_score` (line 1911)
  - `_stability_score` (line 1953)
  - `compute_fitness` (line 2019)
  - critical-floor branch (`return 0.0`, line 2183)
  - `DIM_WEIGHTS` / `STABILITY_WEIGHT` (lines 606 / 669)
  - `AXIS_TIERS` 5+10+3 listing (line 582)
  - promote margin `_MARGIN_GAIN_SIGMA` / `_FITNESS_MARGIN_FLOOR_DEFAULT` (lines 3527 / 3513)
  - `TARGET_KINDS` (7 scaffold kinds) — `core/self_improving/loop/policies.py`
* Karpathy autoresearch: https://github.com/karpathy/autoresearch
  (228791f) — local reference clone `~/workspace/autoresearch/`
* GEODE README on this split: `docs/self-improving/loop-overview.md`
  "Role split — petri vs autoresearch" table.
