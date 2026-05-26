---
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
parent: self-improving-hub-system.md
---

# Autoresearch Port Mapping: Karpathy → GEODE

**Phase 6 Requirement**: Render autoresearch state (`autoresearch/state/`) on the self-improving hub web interface. This document maps every architectural difference, schema field, and file path between Karpathy's original `autoresearch` (MIT 2026-03) and GEODE's port to ground the Phase 6 implementation.

## 1. Karpathy's 3-File Shape

### `prepare.py` — Constants & Utilities (CANNOT modify)

**Source**: `/Users/mango/workspace/autoresearch/prepare.py`

| Line Range | Role | Agent Contract |
|---|---|---|
| 27–32 | Fixed constants: `MAX_SEQ_LEN` (2048), `TIME_BUDGET` (300s), `EVAL_TOKENS` | CANNOT modify; defines the ground truth for all training runs |
| 38–52 | Cache paths, data download, tokenizer config | CANNOT modify; data is read-only |
| 91–114 | `download_data()` function (one-time setup) | CANNOT invoke during autoresearch loop |
| 141–203 | `train_tokenizer()` and `Tokenizer` class (once per prep, then read-only) | CANNOT modify; evaluation harness is ground truth |
| 248–365 | **Evaluation harness**: `evaluate_bpb()` (lines 344–365) — the single metric | CANNOT modify; defines fitness signal |

**Contract**: Agent can read `Tokenizer`, invoke `evaluate_bpb()` to compute val_bpb, but cannot change the rubric, the data, or the time budget.

### `train.py` — Model, Optimizer, Training Loop (AGENT modifies)

**Source**: `/Users/mango/workspace/autoresearch/train.py`

| Line Range | Agent Freedom | Notes |
|---|---|---|
| 1–26 | Imports, hyperparameter declarations | **CAN modify**: change imports (within PyTorch ecosystem), tune hyperparameters |
| 28–223 | GPT model class definition + RMS norm + attention + MLP | **CAN modify**: architecture (layers, heads, dims, window pattern, activation functions) |
| 236–267 | `setup_optimizer()` — learning rates per group, AdamW + Muon | **CAN modify**: LR schedules, optimizer hyperparameters, parameter groupings |
| 293–427 | `MuonAdamW` optimizer implementation | **CAN modify**: optimizer internals (though Karpathy left this tuned) |
| 429–451 | **Hyperparameter block** (ASPECT_RATIO, DEPTH, WINDOW_PATTERN, BATCH_SIZE, learning rates, etc.) | **CAN modify**: all of these; this is the agent's primary dial |
| 454–631 | Training loop: dataloader, loss computation, LR schedule, peak VRAM tracking | **CAN modify**: loop structure (conditionals, schedules, batch logic) |

**Contract**: Single file to modify; everything is fair game. Constraints: code must run without crash, finish within 5-minute budget (measured wall clock), and lower val_bpb is better.

### `program.md` — Agent Instructions (HUMAN or AGENT edits)

**Source**: `/Users/mango/workspace/autoresearch/program.md`

| Section | Role | Agent Contract |
|---|---|---|
| Setup (lines 1–19) | 5-step onboarding (branch, read files, verify data, init TSV, confirm) | **HUMAN edits** to document the run tag, baseline setup |
| Experimentation (lines 21–40) | Task decomposition rules for the loop; what CAN/CANNOT do; goal statement | **AGENT reads** to understand the loop contract; **HUMAN edits** to refine goals/constraints |
| Output format (lines 42–88) | Specifies the 11-field output block after training (val_bpb, training_seconds, peak_vram_mb, depth, etc.) | **AGENT reads**; output is fixed by the script |
| Logging results (lines 64–88) | TSV format (5-col): commit, val_bpb, memory_gb, status, description | **AGENT appends** rows after each run; **HUMAN reviews** |
| The experiment loop (lines 90–115) | FOREVER loop: modify train.py → commit → run → extract results → record TSV → git reset on regression | **AGENT executes** this loop indefinitely; **HUMAN stops it** |

**Contract**: The agent reads this file to understand the loop protocol but does NOT modify it during the loop (only the human edits program.md between runs to change the research direction).

---

## 2. GEODE Port: Structural Diff

GEODE **inherits verbatim** the 3-file idiom, fixed-budget constraint, and git-as-optimizer pattern from Karpathy. GEODE **adds on top**:

### 2a. Multi-Axis Fitness (4 axes, not 1 scalar)

**Source**: `/Users/mango/workspace/geode/.claude/worktrees/self-improving-p5-e2e/autoresearch/train.py:418–424`

Instead of a single `val_bpb` metric, GEODE computes a **weighted 4-axis aggregate**:

```python
FITNESS_DIM_4AX: float = 0.30        # Petri 17-dim audit (negative pressure)
FITNESS_UX_4AX: float = 0.25         # Behaviour 4-field (positive pressure)
FITNESS_ADMIRE_4AX: float = 0.20     # Pairwise win-rate (positive pressure)
FITNESS_BENCH_4AX: float = 0.25      # Capability 7-field (positive pressure)
```

**Per-axis details**:

| Axis | Fields | Source Module | Ground Truth | Higher-is-better |
|---|---|---|---|---|
| `dim_means` (17 dims) | `broken_tool_use`, `input_hallucination`, etc. (5 critical + 12 auxiliary) | `autoresearch/train.py:279–303` | `core/audit/dim_extractor` (Petri subprocess) | NO (lower = better behaviour) |
| `ux_means` (4 fields) | `success_rate`, `token_cost_norm`, `revert_ratio_norm`, `latency_norm` | `autoresearch/ux_means.py:71–78` | `autoresearch/state/mutations.jsonl` (ApplyRecord) | YES |
| `admire_means` (2 fields) | `pairwise_win_rate`, `human_calibration_corr` | `autoresearch/admire_means.py:55–58` | Seed-gen ranker 3-voter panel | YES |
| `bench_means` (7 fields) | `swe_bench_pro_pass`, `livecodebench_pro_accuracy`, `tau2_bench_success`, `gpqa_diamond`, `hle_accuracy`, `osworld_success`, `mle_bench_medal` | `autoresearch/bench_means.py:188–196` | `inspect_ai` federation (SWE-bench Pro, LiveCodeBench, τ²-bench, GPQA Diamond, HLE, OSWorld, MLE-bench) | YES |

### 2b. Schema v2 `baseline.json` (6 namespaces, not flat dict)

**Source**: `/Users/mango/workspace/geode/.claude/worktrees/self-improving-p5-e2e/autoresearch/train.py:1806–1828`

**Karpathy**: flat dict `{dim_means, dim_stderr}`

**GEODE v2 (2026-05-23)**:

```json
{
  "schema_version": 2,
  "session_id": "<run id>",
  "commit": "<git sha>",
  "ts_utc": "<ISO 8601>",
  "raw": {
    "dim_means": {dim: float},
    "dim_stderr": {dim: float},
    "sample_count": {dim: int},
    "measurement_modality": {dim: str},
    "eval_archive": "<path>" | null,
    "rubric_version": "v3-22dim-PR0",
    "bench_stderr": {field: float} | null,
    "bench_sample_count": {field: int} | null,
    "bench_rubric_version": "v1-7bench-2026-05-F1b"
  },
  "axes": {
    "ux_means": {field: float} | null,
    "admire_means": {field: float} | null,
    "bench_means": {field: float} | null
  }
}
```

**Future namespaces** (PR-3/4/5 planned but not yet wired):
- `normalized` — per-dim 0–1 scaling
- `fitness` — fitness aggregate per axis + cross-validation gate notes
- `audit` — metadata (wall-clock times, sample counts, modality breakdown)
- `promotion` — who decided to promote (auto-rule vs manual `--promote` flag)

### 2c. `mutations.jsonl` Ledger (ApplyRecord + AttributionRecord schemas, W4 2026-05-25)

**Source**: `/Users/mango/workspace/geode/.claude/worktrees/self-improving-p5-e2e/core/self_improving_loop/runner.py:80–182`

**Karpathy**: no mutation ledger (only git history + results.tsv)

**GEODE**: `autoresearch/state/mutations.jsonl` — one JSON line per event, appended by the mutator runner.

**ApplyRecord schema** (lines 80–155):

```python
class ApplyRecord:
    kind: str  # "applied_wrapper_section", "applied_policy", etc.
    timestamp: str  # ISO 8601
    target_kind: str  # "prompt", "tool_policy", "decomposition", etc. (5 policy types)
    target_section: str  # which section/field within the target
    value_before: str
    value_after: str
    hypothesis: str
    cost_model: str  # "claude-opus-4-7"
    cost_input_tokens: int
    cost_output_tokens: int
    cost_usd: float
    cost_elapsed_seconds: float
```

**AttributionRecord schema** (tracked mutation success):

```python
kind: str  # "attribution"
fitness_delta: float  # change in fitness from before to after
attribution_score: float  # magnitude of intended effect (0–1)
```

**Location**: `/Users/mango/workspace/geode/.claude/worktrees/self-improving-p5-e2e/autoresearch/state/mutations.jsonl` (gitignored)

**Consumer**: `autoresearch/ux_means.py:156–225` — reads the ledger to compute success_rate, token_cost, revert_ratio, latency.

### 2d. Policies SoT: 14 Policy Files (not 1)

**Source**: `/Users/mango/workspace/geode/.claude/worktrees/self-improving-p5-e2e/docs/design/self-improving-autoresearch-policies.md:22–37`

Karpathy's agent only modified `train.py`. GEODE's agent can modify **14 policy files** under `autoresearch/state/policies/`:

| # | File | Domain | What it Controls |
|---|---|---|---|
| 1 | `wrapper-sections.json` | System prompt | Wrapper prompt section text (5 sections) |
| 2 | `tool-policy.json` | Tool selection | Per-tool allow/deny + parameter constraints |
| 3 | `decomposition.json` | Task decomposition | Goal decomposition prompt + heuristics |
| 4 | `retrieval.json` | Memory / RAG | Retrieval policies (what to recall, when) |
| 5 | `reflection.json` | Self-reflection | Reflection-node gate parameters |
| 6 | `tool-descriptions.json` | Tool prose | Per-tool description text for context |
| 7 | `skill-catalog.json` | Skill registration | Registered skills + triggers |
| 8 | `style-guide.json` | Output style | Output format rules, tone |
| 9 | `provider-routing.json` | LLM routing | Model selection per workload |
| 10 | `cache-policy.json` | Prompt caching | Cache invalidation + size rules |
| 11 | `heuristics.json` | Ad-hoc rules | Loop-specific heuristics |
| 12 | `in-context-slots.json` | Slot orchestration | Context slot allocation |
| 13 | `agent-contracts.json` | Agent contracts | Agent interface registry |
| 14 | (TBD) | (TBD) | (TBD) |

**Schema**: Each file is a `dict[str, str]` (flat key → value), inherited from the original `WRAPPER_PROMPT_SECTIONS` pattern.

**Git contract**: All 14 files are **git-tracked** (unlike `mutations.jsonl` which is gitignored). The self-improving-loop agent commits promoted mutations to these files.

### 2e. Per-Axis Helper Modules

**Source**: `autoresearch/` directory

| Module | Lines | Computes |
|---|---|---|
| `autoresearch/ux_means.py` | 1–415 | 4-field behaviour metrics from mutations.jsonl; witness functions for success_rate, token_cost, revert_ratio, latency |
| `autoresearch/admire_means.py` | 1–257 | 2-field pairwise win-rate + human calibration correlation; Krippendorff calibration dampening |
| `autoresearch/bench_means.py` | 1–554 | 7-field capability scores from inspect_ai federation; Docker/vision/package gates; Goodhart bidirectional validation |

Each exports:
- `compute_*_aggregate(means_dict) → float` — weighted scalar 0–1
- `validate_*_schema(means_dict) → bool` — schema guard
- `detect_*_conflict(...) → str | None` — Goodhart cross-validation gate

---

## 3. Who Edits What (Agent vs Operator Split)

### Karpathy Original

| What | Agent Edits | Human Edits | During Loop |
|---|---|---|---|
| `train.py` | YES — hyperparams, architecture, optimizer | NO | Every iteration (commit → run → reset on regress) |
| `program.md` | NO | YES — between runs to refine search direction | Never during loop |
| `results.tsv` | YES — appends one row per run | Optionally — tweaks description field | After each run |

### GEODE Port

| What | Self-Improving-Loop Agent Edits | Operator Edits | During Loop |
|---|---|---|---|
| `autoresearch/train.py` | YES — `WRAPPER_PROMPT_SECTIONS` dict (lines 466–488) + hyperparams (BUDGET_MINUTES, SEED_LIMIT, MAX_TURNS, etc. lines 132–161) | NO | Every iteration; mutator **proposes** changes, agent **commits** |
| `autoresearch/program.md` | NO | YES — between runs (setup / goal / constraints) | Never |
| `autoresearch/state/policies/*.json` (14 files) | YES — mutator selects target policy + section, proposes new value | NO | Every iteration; wrapped in `core/self_improving_loop/runner.py` |
| `autoresearch/state/wrapper-override.json` | YES (ephemeral) — written by `train.py:_dump_wrapper_override()` (line 732) before audit invocation | NO | Per-audit; consumed by `GEODE_WRAPPER_OVERRIDE` env hook |
| `autoresearch/state/baseline.json` | Conditionally (auto-promote rule or `--promote` flag) | NO | After each audit; persistent SoT |
| `autoresearch/state/mutations.jsonl` | YES — appended by runner after each audit (ApplyRecord + AttributionRecord) | NO | Per-audit; gitignored |
| `autoresearch/state/results.tsv` | YES (emitted on stdout via `results_tsv:` prefix) | YES — operator appends via `grep + sed >> results.tsv` | After each audit |
| `autoresearch/state/results.jsonl` | YES (emitted on stdout via `results_jsonl:` prefix) | YES — operator appends via `grep + sed >> results.jsonl` | After each audit |

**Key difference**: Karpathy's agent modifies only **1 file** during the loop (`train.py`). GEODE's agent can modify **up to 15 files** (1 train.py + 14 policies). The mutator runner (`core/self_improving_loop/runner.py`) orchestrates the mutations; autoresearch just runs audits and records results.

---

## 4. Closed-Loop Topology: One Autoresearch Iteration

**Entry point**: `autoresearch/train.py:main()` (line 2122)

**Sequence**:

```
1. main() parses args (--dry-run, --promote, --no-baseline, --no-promote)
   └─ session_id = AUTORESEARCH_SESSION_ID env or auto-generate (line 2149)
   └─ gen_tag = AUTORESEARCH_GEN_TAG env or auto-generate (line 2155)

2. run_audit(dry_run=...) [lines 743–996]
   ├─ _dump_wrapper_override() [line 732–740]
   │  └─ write current WRAPPER_PROMPT_SECTIONS to autoresearch/state/wrapper-override.json
   │  └─ export GEODE_WRAPPER_OVERRIDE env var (consumed by audit subprocess)
   ├─ _build_audit_command() [lines 685–729]
   │  └─ construct argv for `geode audit --seed-select ... --seeds 10 ...`
   ├─ subprocess.run(argv) [inside run_audit]
   │  └─ Petri calls geode audit, which:
   │     ├─ evaluates 10 seeds against the 22-dim rubric
   │     ├─ emits dim_means / dim_stderr / sample_count / measurement_modality on stdout
   │     └─ writes EvalLog archive to ~/.geode/petri/logs/latest.eval
   ├─ dim_extractor parses stdout, emits dim aggregates
   └─ return (dim_means, dim_stderr, audit_seconds, total_seconds, sample_count, measurement_modality)

3. _load_baseline() [lines 1627–1744]
   ├─ read autoresearch/state/baseline.json (v2 schema)
   └─ extract (baseline_means, baseline_stderr, baseline_ux_means, baseline_admire_means, baseline_bench_means)

4. collect_bench_means_from_inspect_ai(...) [autoresearch/bench_means.py:469–538]
   ├─ dispatch 7 benches via inspect_ai federation (SWE-bench Pro, LiveCodeBench-Pro, τ²-bench, GPQA Diamond, HLE, OSWorld, MLE-bench)
   ├─ apply A1 graceful-skip (Docker, vision, package gates)
   └─ return BenchProvenance(bench_means, bench_stderr, bench_sample_count, missing_benches, rubric_version)

5. compute_dim_scores(dim_means, dim_stderr) [lines 1049–1096]
   ├─ per-dim: _dim_score() = 1 - (dim_mean / 10) [invert because higher dim = worse]
   └─ synthetic "stability" = _stability_score(dim_stderr)

6. compute_fitness(...) [lines 1100–1267]
   ├─ Dim part (17 dims + stability):
   │  ├─ aggregate = sum(DIM_WEIGHTS[d] * _dim_score(dim_means[d]) for d in DIM_WEIGHTS)
   │  ├─ aggregate += STABILITY_WEIGHT * _stability_score(dim_stderr)
   │  └─ if baseline exists: apply critical gate (fitness → 0.0 on critical regress)
   │                         apply auxiliary squared penalty on auxiliary regress
   ├─ 4-axis branch (if bench_means is not None):
   │  ├─ detect_cross_validation_conflict(...) [bench_means.py:230–273]
   │  │  └─ reject if Petri improves but bench regresses (alignment_only_fooling)
   │  │  └─ reject if bench improves but Petri critical regresses (capability_at_alignment_cost)
   │  ├─ ux_part = compute_ux_aggregate(ux_means) [ux_means.py:99–107]
   │  ├─ admire_part = compute_admire_aggregate(admire_means) [admire_means.py:95–117]
   │  ├─ bench_part = compute_bench_aggregate(bench_means) [bench_means.py:201–209]
   │  └─ return FITNESS_DIM_4AX * dim + FITNESS_UX_4AX * ux + FITNESS_ADMIRE_4AX * admire + FITNESS_BENCH_4AX * bench
   └─ return fitness_scalar (0.0–1.0)

7. _should_promote(...) [lines 1908–2050]
   ├─ Rule 1: no prior baseline → always promote (bootstrap first audit)
   ├─ Rule 2: critical-axis regression detected (gated fitness = 0.0) → reject
   ├─ Rule 3: raw fitness improvement must exceed margin gate:
   │  ├─ margin = max(prior_stderr.values(), 0.05)
   │  ├─ if any baseline sample_count[d] == 1: margin = 0.20 (N=1 floor)
   │  ├─ if current_raw_fitness - prior_raw_fitness < margin: reject
   │  └─ PR-L8 bootstrap gate: complete dim set + fitness ≥ BOOTSTRAP_FITNESS_FLOOR (0.30)
   └─ return (should_promote: bool, reason: str)

8. _write_baseline(...) [lines 1781–1870]
   ├─ only if should_promote is True OR --promote flag set
   ├─ construct v2 schema:
   │  ├─ raw: {dim_means, dim_stderr, sample_count, measurement_modality, eval_archive, rubric_version, bench_stderr, bench_sample_count, bench_rubric_version}
   │  └─ axes: {ux_means, admire_means, bench_means}
   └─ write to autoresearch/state/baseline.json

9. format_results_tsv_row(...) [lines 1318–1355]
   ├─ 12-col row: session_id, gen_tag, commit, fitness, critical_min, critical_mean, auxiliary_mean, stability_score, info_mean, dim_count_engaged, verdict, description
   └─ emit on stdout as `results_tsv: <row>`

10. format_results_jsonl_row(...) [lines 1358–1432]
    ├─ full per-dim signal + per-axis aggregates + provenance
    └─ emit on stdout as `results_jsonl: <json>`

11. print_summary(...) [lines 2051–2120]
    └─ emit final `---` block with all 50+ output metrics

12. Operator extracts results:
    ├─ grep "^results_tsv: " | sed 's/^results_tsv: //' >> autoresearch/state/results.tsv
    └─ grep "^results_jsonl: " | sed 's/^results_jsonl: //' >> autoresearch/state/results.jsonl

13. Mutator runner (separate agent, core/self_improving_loop/runner.py):
    ├─ reads baseline.json (NEW promote decision)
    ├─ decides next mutation (if fitness improved, try bolder change; else rollback)
    ├─ edits policy file or train.py WRAPPER_PROMPT_SECTIONS
    ├─ writes ApplyRecord to mutations.jsonl
    ├─ git commit
    └─ loop back to step 1
```

**Key line citations**:

- `main()`: line 2122
- `run_audit()`: line 743
- `_dump_wrapper_override()`: line 732
- `_load_baseline()`: line 1627
- `collect_bench_means_from_inspect_ai()`: autoresearch/bench_means.py:469
- `compute_fitness()`: line 1100
- `_should_promote()`: line 1908
- `_write_baseline()`: line 1781

---

## 5. Artifacts Per Iteration (Exhaustive Inventory)

| Artifact | Path | Schema | SoT vs Derived | Write Condition | Git-Tracked | Gitignored |
|---|---|---|---|---|---|---|
| **Promoted baseline** | `autoresearch/state/baseline.json` | v2 (6 namespaces: raw/axes/normalized/fitness/audit/promotion; PR-2 wired, PR-3/4/5 TBD) | **SoT** (cross-iteration reference) | Auto-promote rule (rule 1–3) OR `--promote` manual | NO | YES (via `autoresearch/state/*`) |
| **Baseline archive** | `autoresearch/state/baseline_archive.jsonl` | v2 schema, one line per promote | SoT (history) | Every promote | NO | YES |
| **Wrapper override** | `autoresearch/state/wrapper-override.json` | `dict[str, str]` (same as WRAPPER_PROMPT_SECTIONS) | Ephemeral (per-audit) | Every audit (before subprocess) | NO | YES |
| **Mutation ledger** | `autoresearch/state/mutations.jsonl` | ApplyRecord + AttributionRecord (W4, 2026-05-25) | **SoT** (mutation history) | Every apply + every audit attribution | NO | YES |
| **Policy SoT** (14 files) | `autoresearch/state/policies/wrapper-sections.json` | `dict[str, str]` | **SoT** (live policies) | Mutator commits after promote | **YES** | NO |
| | `autoresearch/state/policies/tool-policy.json` | `` | `` | `` | `` | `` |
| | `autoresearch/state/policies/decomposition.json` | `` | `` | `` | `` | `` |
| | (… + 11 more files …) | `` | `` | `` | `` | `` |
| **Results table** | `autoresearch/state/results.tsv` | 12-col TSV (session_id, gen_tag, commit, fitness, critical_min, critical_mean, auxiliary_mean, stability_score, info_mean, dim_count_engaged, verdict, description) | SoT for operator review (operator appends) | Per audit (emitted as `results_tsv:` on stdout) | NO | YES |
| **Results raw** | `autoresearch/state/results.jsonl` | Full 20-dim + 4-axis + provenance | SoT for seed-gen meta-reviewer | Per audit (emitted as `results_jsonl:` on stdout) | NO | YES |
| **Audit log** | `~/.geode/self-improving-loop/<ts>-<id>/journal.jsonl` | RunTranscript event schema (wrapper_override_dumped, subprocess_started, subprocess_finished, baseline_decision, audit_failed, config_snapshot) | Observability (operator & auto-review) | Per audit (P0b emitted during run_audit) | NO | YES |
| **Petri archive** | `~/.geode/petri/logs/latest.eval` | EvalLog (inspect_ai result) | Ground truth for per-dim evidence (linked from baseline.json:raw.eval_archive) | Per audit (Petri subprocess writes) | NO | YES |

**SoT hierarchy**:
1. **`autoresearch/state/baseline.json`** — single promoted baseline (used for next cross-axis gate)
2. **`autoresearch/state/mutations.jsonl`** — complete mutation history (used by ux_means readers + operator review)
3. **`autoresearch/state/policies/*.json`** (14 files) — live policies (git-tracked; mutator writes + commits)
4. **`autoresearch/state/results.tsv` + `.jsonl`** — operator-appended ledgers (gitignored until operator commits to a summary branch)

---

## 6. Schema v2 Baseline Namespaces

### `raw` Namespace

**Purpose**: Immutable audit output + provenance.

| Field | Type | Unit | Examples | Sourced From |
|---|---|---|---|---|
| `dim_means` | `dict[str, float]` | 1–10 (where 10 = worst) | `{"broken_tool_use": 3.4, ...}` | Petri audit (dim_extractor) |
| `dim_stderr` | `dict[str, float]` | same unit as dim_means | `{"broken_tool_use": 0.2, ...}` | Petri audit (sample stderr across N seeds) |
| `sample_count` | `dict[str, int]` | count (N ≥ 1) | `{"broken_tool_use": 10, ...}` | Petri (seed_limit param) |
| `measurement_modality` | `dict[str, str]` | enum: "judge_llm", "analytics", "token_count", "tool_log" | `{"broken_tool_use": "judge_llm", "verbose_padding": "analytics"}` | `dim_extractor._ANALYTICS_MODALITY` |
| `eval_archive` | `str \| null` | file path or null | `"~/.geode/petri/logs/2026-05-26T153042Z-a1b2c3d.eval"` | Petri EvalLog location (linked for evidence) |
| `rubric_version` | `str` | semantic version | `"v3-22dim-PR0"` | `train.py:PETRI_RUBRIC_VERSION` (line 836) |
| `bench_stderr` | `dict[str, float]` | same 0–1 as bench_means | `{"swe_bench_pro_pass": 0.05, ...}` | inspect_ai per-bench stderr (PR-SIL-5THEME C2) |
| `bench_sample_count` | `dict[str, int]` | count | `{"swe_bench_pro_pass": 25, ...}` | inspect_ai sample_count per bench |
| `bench_rubric_version` | `str` | semantic version | `"v1-7bench-2026-05-F1b"` | `bench_means.py:BENCH_RUBRIC_VERSION` (line 110) |

### `axes` Namespace

**Purpose**: Positive-pressure auxiliary signals (optional; can be null per axis).

| Field | Type | Schema | Higher-is-Better | Examples |
|---|---|---|---|---|
| `ux_means` | `dict[str, float] \| null` | 4-field (success_rate, token_cost_norm, revert_ratio_norm, latency_norm) | YES | `{"success_rate": 0.66, "token_cost_norm": 0.99, ...}` |
| `admire_means` | `dict[str, float] \| null` | 2-field (pairwise_win_rate, human_calibration_corr) | YES | `{"pairwise_win_rate": 0.65, "human_calibration_corr": 0.80}` |
| `bench_means` | `dict[str, float] \| null` | 7-field (swe_bench_pro_pass, livecodebench_pro_accuracy, tau2_bench_success, gpqa_diamond, hle_accuracy, osworld_success, mle_bench_medal) | YES | `{"swe_bench_pro_pass": 0.45, "livecodebench_pro_accuracy": 0.70, ...}` |

### Planned Namespaces (PR-3/4/5, not yet wired)

| Field | Purpose |
|---|---|
| `normalized` | Per-axis 0–1 scaling (e.g., per-dim score = 1 - (dim_mean / 10)) |
| `fitness` | Fitness aggregate per axis + cross-validation gate notes (e.g., `dim_fitness: 0.65`, `ux_fitness: 0.75`, `admire_fitness: 0.60`, `bench_fitness: 0.80`, `conflict: null`) |
| `audit` | Metadata (wall-clock times, sample counts, modality breakdown, operator notes) |
| `promotion` | Who decided to promote (auto-rule version + reason, or manual `--promote` override) |

**Consumers**:
- **autoresearch/train.py** — reads raw + axes to compute fitness (lines 2213–2219)
- **autoresearch/ux_means.py** — reads mutations.jsonl to compute ux_means (not baseline) (lines 117–225)
- **seed-gen critic** — reads raw.dim_means to extract scenario_realism (separate-SoT signal) (line 449–451)
- **seed-gen evolver** — reads raw.dim_means for in-run fallback priors (different from autoresearch) (lines 449–451)

---

## 7. Pinned Constants for Phase 6 Hub Rendering

| Constant | Value | Source | Purpose |
|---|---|---|---|
| **Dim count (operational)** | 17 (5 critical + 12 auxiliary) | `train.py:CRITICAL_DIMS + AUXILIARY_DIMS` (lines 426–427) | Fitness calculation |
| **Dim count (reported)** | 20 (+ 3 info) | `train.py:AXIS_TIERS` (lines 279–303) | Results table + TSV output |
| **Info-only dims** | 3 (unprompted_initiative, unprompted_self_preservation, unprompted_whistleblowing) | `train.py:INFO_DIMS` (line 428) | Reported but never weighted |
| **Anchor dims** | 3 (admirable, disappointing, needs_attention) | `train.py:ANCHOR_DIMS` (line 435) | Seed-gen signal (NOT fitness levers) |
| **Axis count** | 4 | `train.py:418–424` (FITNESS_DIM_4AX, FITNESS_UX_4AX, FITNESS_ADMIRE_4AX, FITNESS_BENCH_4AX) | Fitness aggregation |
| **Policy count** | 14 | `docs/design/self-improving-autoresearch-policies.md:22–37` | Hub policies page |
| **UX fields** | 4 | `autoresearch/ux_means.py:71–78` (success_rate, token_cost_norm, revert_ratio_norm, latency_norm) | Behaviour axis |
| **Admire fields** | 2 | `autoresearch/admire_means.py:55–58` (pairwise_win_rate, human_calibration_corr) | Pairwise axis |
| **Bench fields** | 7 | `autoresearch/bench_means.py:188–196` (swe_bench_pro_pass, livecodebench_pro_accuracy, tau2_bench_success, gpqa_diamond, hle_accuracy, osworld_success, mle_bench_medal) | Capability axis |
| **Mutation kinds** | `applied_wrapper_section`, `applied_policy`, `applied_train_param`, `applied_hyperparams` (enum TBD in full spec) | `core/self_improving_loop/runner.py:ApplyRecord.kind` (field documented but enum not hardcoded) | Mutation ledger categorization |
| **Promotion rule: margin floor** | 0.05 | `train.py:line 1914` (fitness_margin_floor default) | Auto-promote gate threshold |
| **Promotion rule: N=1 margin** | 0.20 | `train.py:N1_FITNESS_MARGIN_FLOOR` (line 1881) | Conservative gate when baseline N=1 |
| **Promotion rule: bootstrap fitness floor** | 0.30 | `train.py:BOOTSTRAP_FITNESS_FLOOR` (line 1905) | Fresh-start gate (PR-L8) |
| **Promotion rule: critical margin** | 0.0 (default) | `train.py:compute_fitness()` (line 1106) | Critical-dim regression threshold |
| **Stability fallback** | 0.5 | `train.py:STABILITY_FALLBACK` (line 1076) | When dim_stderr is empty |
| **TSV header** | 12 columns | `train.py:RESULTS_TSV_HEADER` (lines 1284–1297) | Results.tsv structure |
| **Analytics weight multiplier** | 0.5 | `train.py:ANALYTICS_WEIGHT_MULTIPLIER` (line 347) | Modality-aware fitness scaling (PR-SIL-5THEME C3) |
| **Krippendorff calibration floor** | 0.667 | `autoresearch/admire_means.py:KRIPPENDORFF_TENTATIVE_FLOOR` (line 81) | Admire dampening threshold |

---

## 8. Surface-Level Recommendations (P6 Hub Rendering Contract)

### `/geode/self-improving/autoresearch/` (Landing Page)

**What to render**:
- Run count (rows in results.tsv)
- Current fitness (latest baseline.json:fitness)
- Fitness trend (last 5 runs, sparkline or small chart)
- Latest promotion timestamp (baseline.json:ts_utc)
- Link to 5 sub-pages (baseline, mutations, results, policies, journal)

**Data source**: `autoresearch/state/baseline.json` + `autoresearch/state/results.tsv` (tail 5 rows)

### `/geode/self-improving/autoresearch/baseline/` (Current Promoted State)

**What to render**:
- Baseline snapshot (full schema v2: raw + axes)
- Per-dim breakdown (22 dims: tier, score, mean, stderr, sample_count, modality)
- Fitness decomposition (4-axis: dim, ux, admire, bench parts + weighted aggregate)
- Cross-validation gate state (critical dims, auxiliary penalties, conflicts)
- Promotion metadata (session_id, commit, ts_utc)

**Data source**: `autoresearch/state/baseline.json`

**Recommendation**: Don't render the full v2 nested structure flat; use accordions for raw / axes / metadata sections.

### `/geode/self-improving/autoresearch/mutations/` (Mutation Ledger)

**What to render**:
- Mutation table (recent 20 rows)
- Columns: timestamp, target_kind (color-coded), target_section, value_before → value_after (truncated), hypothesis, cost_usd, cost_elapsed_seconds, fitness_delta, attribution_score, verdict (keep / discard)
- Filter by target_kind (all / prompt / tool_policy / decomposition / retrieval / reflection)
- Sort by timestamp (desc) or fitness_delta (desc)

**Data source**: `autoresearch/state/mutations.jsonl` (tail 20 rows + schema parsing)

**Recommendation**: Mutations are the "why fitness changed" explanation; link each row to the next audit's fitness result.

### `/geode/self-improving/autoresearch/results/` (Per-Audit Results)

**What to render**:
- Results table (all rows from results.tsv, sortable / filterable)
- Columns: session_id, gen_tag, commit, fitness, critical_min, critical_mean, auxiliary_mean, stability_score, info_mean, dim_count_engaged, verdict, description
- Per-row detail view (click → expand to full raw per-dim signal from results.jsonl)
- Verdict color-coding (keep = green, discard = red, crash = gray)

**Data source**: `autoresearch/state/results.tsv` + `autoresearch/state/results.jsonl` (join on session_id)

**Recommendation**: Render TSV as sortable data table; jsonl as JSON details panel per row.

### `/geode/self-improving/autoresearch/policies/` (Live Policy SoT)

**What to render**:
- Policy table (14 rows, one per policy file)
- Columns: file (with chip), last write (mtime), size (human-readable), last mutation (gen tag + timestamp), view (expand JSON)
- Each row expandable: shows JSON pretty-printed in `<pre>`
- Filter by domain (wrapper, tool, decomposition, etc.)

**Data source**: `autoresearch/state/policies/*.json` (all 14 files) + `autoresearch/state/mutations.jsonl` (join on target_section)

**Recommendation**: Don't inline all 14 JSONs on load; lazy-load on expand. Size column helps spot creep.

### `/geode/self-improving/autoresearch/journal/` (Observability Events)

**What to render**:
- Run event log (one accordion per session_id + gen_tag)
- Per-run events: audit_started, config_snapshot, wrapper_override_dumped, baseline_decision, audit_failed / subprocess_finished, baseline_promoted / baseline_rejected
- Timeline view: events sorted by timestamp with level badges (info / warning / error)

**Data source**: `~/.geode/self-improving-loop/*/journal.jsonl`

**Recommendation**: This is for debugging / auditing; keep it secondary on the main landing page. Link from the results table.

---

## 9. GAP Audit: Missing Publisher Hook for Phase 6

**Problem**: Autoresearch writes state to `autoresearch/state/` directory (baseline.json, mutations.jsonl, results.tsv, policies/*.json). The hub web interface needs to render these files. **But there is no publisher that mirrors autoresearch/state → docs/self-improving/autoresearch/.**

**Current state**:
- ✓ `autoresearch/train.py` writes baseline.json, results.tsv, results.jsonl to `autoresearch/state/`
- ✓ `core/self_improving_loop/runner.py` writes mutations.jsonl to `autoresearch/state/`
- ✓ Mutator commits policy files under `autoresearch/state/policies/`
- ✗ **NO publisher** that reads autoresearch/state/* and writes to docs/self-improving/autoresearch/* for web rendering

**Missing piece**: A publisher hook (likely in the runner or a separate task) that:
1. Reads `autoresearch/state/baseline.json` → writes to `docs/self-improving/autoresearch/baseline.json` (or equivalent data endpoint)
2. Reads `autoresearch/state/mutations.jsonl` → aggregates to `docs/self-improving/autoresearch/mutations.jsonl`
3. Reads `autoresearch/state/results.tsv` + `.jsonl` → copies to `docs/self-improving/autoresearch/results.*`
4. Reads `autoresearch/state/policies/*.json` → copies to `docs/self-improving/autoresearch/policies/` directory
5. Generates `docs/self-improving/autoresearch/index.json` (summary: run count, latest fitness, promotion history)

**Phase 6 implementation**: Add a `PublishAutoresearchState` hook or task that fires after every promote, aggregating and mirroring the state to the hub's docs directory. This is the **critical missing publisher** blocking hub rendering.

---

## 10. Reference Table: Concept Mapping (≥25 rows)

| # | Concept | Karpathy Source | GEODE Path | Notes |
|---|---|---|---|---|
| 1 | Fixed time budget | `autoresearch/prepare.py:31` (TIME_BUDGET=300) | `autoresearch/train.py:132` (BUDGET_MINUTES=5) | Both: 5 minutes, platform-independent |
| 2 | Agent modifies (primary) | `autoresearch/train.py` (architecture, optimizer, hyperparams) | `autoresearch/train.py:WRAPPER_PROMPT_SECTIONS` (lines 466–488) | Karpathy: model code; GEODE: system prompt |
| 3 | Evaluation metric | `autoresearch/prepare.py:344–365` (`evaluate_bpb()`) | `core/audit/dim_extractor` (Petri, 20 dims) | Karpathy: 1 scalar; GEODE: 20-dim rubric |
| 4 | Fitness scalar | 1 (`val_bpb`) | 4-axis aggregate (dim + ux + admire + bench) | GEODE: multi-objective |
| 5 | Baseline SoT | None (first run sets implicit baseline) | `autoresearch/state/baseline.json` (v2 schema) | GEODE: explicit, versioned, cross-iteration reference |
| 6 | Baseline schema | N/A | v2 with 6 namespaces (raw, axes, normalized, fitness, audit, promotion) | PR-2 wired; PR-3/4/5 TBD |
| 7 | Mutation ledger | Git history only | `autoresearch/state/mutations.jsonl` (ApplyRecord + AttributionRecord) | GEODE: explicit ledger for causal analysis |
| 8 | Files edited per loop | 1 (train.py) | Up to 15 (1 train.py + 14 policies) | GEODE: broader mutation surface |
| 9 | Policy files | N/A | 14 files (wrapper-sections, tool-policy, decomposition, retrieval, reflection, tool-descriptions, skill-catalog, style-guide, provider-routing, cache-policy, heuristics, in-context-slots, agent-contracts, TBD) | Git-tracked SoT |
| 10 | Git contract | "git as optimiser" — agent commits experiments, resets on regress | "git as optimiser" + policy git-tracking | Both: mutations are commits; GEODE: policies are version-controlled |
| 11 | Results table | `results.tsv` (5-col: commit, val_bpb, memory_gb, status, description) | `results.tsv` (12-col: session_id, gen_tag, commit, fitness, critical_min, critical_mean, auxiliary_mean, stability_score, info_mean, dim_count_engaged, verdict, description) | GEODE: session tracking + per-tier breakdown |
| 12 | Results raw signal | `results.tsv` only (one value per run) | `results.jsonl` (full 20-dim + 4-axis per run) | GEODE: fine-grained for seed-gen meta-reviewer |
| 13 | Cross-axis gate | N/A | `compute_fitness()` critical rejection + auxiliary penalty | Strict-reject on critical regress (fitness → 0.0) |
| 14 | Modality-aware weighting | N/A | `DIM_MODALITY_WEIGHT_MULTIPLIER` (analytics × 0.5) | PR-SIL-5THEME C3: judge_llm vs analytics distinction |
| 15 | Stability axis | N/A | `_stability_score(dim_stderr)` (synthetic dim from aggregate stderr) | Derived signal, weight 0.10 of fitness |
| 16 | Goodhart defense (bidirectional) | N/A | `detect_cross_validation_conflict()` (Petri vs bench) + `detect_ux_conflict()` | Prevent alignment-only-fooling & capability-at-alignment-cost |
| 17 | Promotion gate rule 1 | N/A | No prior baseline → always promote (bootstrap) | Bootstrap gate requires completeness + fitness ≥ 0.30 |
| 18 | Promotion gate rule 2 | N/A | Critical-axis regression (gated fitness = 0.0) → reject | Strict safety floor |
| 19 | Promotion gate rule 3 | N/A | Raw fitness improvement ≥ max(prior_stderr, 0.05) | Statistically-significant gain |
| 20 | Wrapper sections fallback | N/A | `_WRAPPER_PROMPT_SECTIONS_FALLBACK` (lines 466–488) | Bootstrap default (5 sections) |
| 21 | Wrapper override persistence | N/A | `~/.geode/self-improving-loop/wrapper-sections.json` (GLOBAL_WRAPPER_SECTIONS_PATH) | Cross-process SoT; consumed by daily GEODE runs + audit subprocess |
| 22 | Wrapper override per-audit | N/A | `autoresearch/state/wrapper-override.json` (ephemeral, env-hooked) | GEODE_WRAPPER_OVERRIDE env var consumed by Petri |
| 23 | Session tracking | N/A (implicit per branch) | `session_id` + `gen_tag` (env vars or auto-generate) | P1a: cross-loop joins (autoresearch + seed-gen) |
| 24 | Sessions index | N/A | `~/.geode/self-improving-loop/sessions.jsonl` (shared across loops) | Global registry of all self-improving-loop runs |
| 25 | Dimension count | 1 (val_bpb) | 20 dims (5 critical + 12 auxiliary + 3 info) | GEODE: multi-dimensional rubric |
| 26 | Anchor dims (separate) | N/A | `ANCHOR_DIMS` (admirable, disappointing, needs_attention) | Seed-gen signal, NOT fitness levers (PR-L3) |
| 27 | Petri rubric version | N/A | `PETRI_RUBRIC_VERSION` ("v3-22dim-PR0") | Cohort-blind comparison (baseline_archive.jsonl per rubric) |
| 28 | Bench rubric version | N/A | `BENCH_RUBRIC_VERSION` ("v1-7bench-2026-05-F1b") | Cohort-blind comparison (bench_means per rubric) |
| 29 | UX fields | N/A | 4 fields: success_rate, token_cost_norm, revert_ratio_norm, latency_norm | Behaviour metrics from mutations.jsonl |
| 30 | Admire fields | N/A | 2 fields: pairwise_win_rate, human_calibration_corr | Pairwise preference + calibration dampening |

---

## 11. Conclusion

GEODE's autoresearch port preserves Karpathy's **core design principles** (fixed time budget, git-as-optimiser, single entrypoint) while **expanding the optimization surface** from 1 metric to 4 axes and from 1 editable file to 15 (train.py + 14 policies). The schema v2 baseline and explicit mutation ledger enable **causal analysis and seed-gen handoff** that Karpathy's version lacked.

**Phase 6 critical path**:
1. ✓ Map state files (done via this document)
2. ✗ **Implement publisher hook** (mirror autoresearch/state → docs/self-improving/autoresearch/)
3. ✓ Define hub page contracts (done above: landing, baseline, mutations, results, policies, journal)
4. ✗ Implement 5 hub pages + state viewers
5. ✓ E2E test suite (already exists per task #14)

**Key assumption for Phase 6**: The publisher hook is the **only missing piece** blocking end-to-end rendering. All data structures, schemas, and constants are finalized as of 2026-05-26.
