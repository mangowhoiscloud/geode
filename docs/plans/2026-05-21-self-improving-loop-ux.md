# Plan: Self-improving loop — operator UX foundation

> **Status**: PR-OPS-1 in progress (2026-05-21). PR-OPS-2/3 deferred.
>
> Goal: surface the GEODE self-improving loop as a first-class
> operator-facing feature. Today the closed loop is fully wired
> (co-scientist → Petri → autoresearch → mutator LLM → SoT write)
> but has **no CLI entry, no REPL slash, no progress feedback, no
> scheduler binding** — running it requires knowing internal module
> paths. This plan lays out the multi-PR UX foundation.

## Problem

The closed loop currently has **zero user-facing surface**:

- No `geode self-improving …` CLI subcommand.
- No `/self-improving` REPL slash. No `/sil` alias.
- No `/schedule` binding for set-and-forget background runs.
- No progress/completion feedback during `SelfImprovingLoopRunner.run_once()`.
- No multi-iteration campaign mode with convergence detection.
- Petri / autoresearch / co-scientist are conceptually peer
  components but operator can't see how they compose at run time
  (no pre-flight dashboard, no quota visibility, no profile
  presets).

Sources of truth for the closed loop (all wired):

- `core/self_improving_loop/runner.py:757` — `SelfImprovingLoopRunner.run_once`.
- `autoresearch/train.py:1101` — `main()` orchestrating Petri call +
  `compute_fitness` + `_should_promote` + `baseline.json` write.
- `plugins/seed_generation/orchestrator.py:345` —
  `_persist_survivors()` writing the cross-loop seed handoff.
- `plugins/petri_audit/runner.py:run_audit` — direct Petri runner
  (currently only invoked via `geode audit` subprocess from
  autoresearch, not from self-improving loop directly).
- `core/paths.py:57` — `~/.geode/self-improving-loop/` SoT root.

## Socratic Gate

| # | Question | Answer |
|---|----------|--------|
| Q1 | Does it already exist in code? | **Partially.** Closed loop logic exists; UX surface (slash / tool / progress / dashboard) does not. PR-OPS-1 adds the smallest surface (slash `status` + design-doc anchor + frontmatter schema fix). |
| Q2 | What breaks if we don't do this? | The loop is unusable as a product — operators must `python -c "from core.self_improving_loop import SelfImprovingLoopRunner; SelfImprovingLoopRunner().run_once()"`. The CHANGELOG/PR-body parity rule fails ("self-improving loop available" is fiction without a CLI). |
| Q3 | How do we measure the effect? | Invariant tests pinning the slash registration, the `cmd_self_improving_status` output format, the seed_generator frontmatter `tags` emission. End-to-end: a user types `/self-improving status` in REPL and sees current baseline + recent mutations. |
| Q4 | What is the simplest implementation? | PR-OPS-1: slash `status` only (read-only — list recent mutations + baseline fitness). No interactive picker. No dashboard. No tool. Frontmatter adapter is one-line schema bump in the seed_generator agent contract. |
| Q5 | Is this pattern in 3+ frontier systems? | Yes — Claude Code's `/cost`, Codex CLI's `codex status`, OpenClaw's read-only status slashes. All three expose runtime state via a status surface before adding interactive controls. |

## System inventory (code-grounded)

### Loops & runners

| Component | Entry | Role |
|-----------|-------|------|
| `SelfImprovingLoopRunner` | `core/self_improving_loop/runner.py:731` | Mutator LLM dispatcher. One iteration per `run_once()`. |
| `autoresearch/train.py` | `:1101 main()` | Petri-call + fitness aggregation + baseline promote. |
| `plugins/seed_generation/orchestrator.Pipeline` | `:Pipeline.run` | 7-phase co-scientist (generator → proximity → critic → pilot → ranker → evolver → meta_reviewer). |
| `plugins/petri_audit/runner.run_audit` | `runner.py` | Raw Petri audit (called via subprocess from autoresearch). |
| `AgenticLoop` | `core/agent/loop/agent_loop.py:60` | Inner agent loop, shared by all of the above. |

### Mutation pathway — corrected mental model

```
[ Petri 호출 + 집계 ──── dim 전달 ────► autoresearch의 LLM ──► GEODE 시스템 자동 수정 ]
       (raw 측정)        (fitness)        (mutator)            (SoT 파일 write)
```

| Stage | Code path | Output |
|-------|-----------|--------|
| ① Petri 호출 (raw) | `geode audit` subprocess via `autoresearch/train.py:_build_audit_command` | `dim_means`, `dim_stderr` (20-dim) |
| ② autoresearch 집계 | `compute_fitness` (`train.py:672`) + `_should_promote` (`:1047`) | `fitness scalar` + `baseline.json` |
| ③ autoresearch의 LLM (mutator) | `SelfImprovingLoopRunner.run_once` → `[self_improving_loop.mutator]` model | `Mutation` JSON |
| ④ GEODE 자동 수정 | `apply_mutation` (`runner.py:585`) | SoT JSON write + `mutations.jsonl` audit |

**Mutator LLM 의 2가지 운용 모드** (둘 다 코드 존재):

| Mode | 소스 | Trigger |
|------|------|---------|
| **A. Karpathy idiom** (manual agent) | External Claude/Codex session reads `autoresearch/program.md` | Human-bootstrapped long-horizon session |
| **B. Programmatic** | `SelfImprovingLoopRunner.run_once()` → `MutatorConfig.default_model` LLM single call → JSON → auto-apply | `geode self-improving run` (this plan adds this) |

UX 가 가리키는 것은 **Mode B** — 운영자가 한 명령으로 한 반복을 자동 실행.

### Selectable LLM models (allow-list)

`core/config/self_improving_loop.py:146-154`:
- `claude-opus-4-7` (default)
- `claude-sonnet-4-6`
- `claude-haiku-4-5-20251001`
- `gpt-5.5`
- `gpt-5.4`

### Credential sources (`Source` Literal)

`core/config/self_improving_loop.py:62`:
- `auto` (default)
- `api_key` (PAYG)
- `claude-cli` (Claude Code subscription OAuth)
- `openai-codex` (Codex CLI subscription OAuth)

`fallback_to_payg` flag — global + per-component (default `False`).

### Harness selection (mutation 후 fitness 측정)

| Harness | Code path | Active stages |
|---------|-----------|---------------|
| `autoresearch` | `autoresearch/train.py` main | 1+2+3+4 (full pipeline) |
| `petri_raw` | `plugins/petri_audit/runner.py:run_audit` direct | 1+2+3 (no fitness gate) |
| `seed tournament` | `plugins/seed_generation/tournament.py` Elo | 1+2+4 (no Petri) |
| `no-op` | mutation 적용만 | 1+2 (no measurement) |

`petri_raw` 는 현재 **코드에 직접 entry 없음** — PR-OPS-2 의 wiring 작업 대상.

### Mutation target kinds (5 SoT files)

`core/paths.py:57-74`:
- `prompt` → `~/.geode/self-improving-loop/wrapper-sections.json`
- `tool_policy` → `tool-policy.json`
- `decomposition` → `decomposition.json`
- `retrieval` → `retrieval.json`
- `reflection` → `reflection.json`

### Petri role bindings

`core/config/self_improving_loop.py:77-92` `PetriRoleConfig` —
3 roles: `auditor` / `target` / `judge`. Each: `model` (optional,
manifest default) + `source` (Literal, default `"auto"`) +
`fallback_to_payg` (optional).

### Quota knobs

- `warn_threshold` = 0.5 — yellow FE banner
- `abort_threshold` = 0.9 — red banner + abort
- `Settings.cost_limit_usd` = 0.0 (no limit)
- `Settings.agentic_loop_time_budget` = 0.0 (no limit)
- `MutatorConfig.max_tokens` = 1024 (range 128–200K)

## Seed pool 정합성 (co-scientist ↔ Petri)

### File format alignment

```
co-scientist (writer)                       Petri (reader)
─────────────────────                       ──────────────
<run_dir>/candidates/<uuid>.md     ───┐
<run_dir>/survivors/<uuid>.md      ───┼──► flatten_for_inspect_petri
~/.geode/self-improving-loop/         │     (plugins/petri_audit/seed_tree.py:127)
  latest_seed_pool symlink         ───┘     ├── flat dir (passthrough)
                                            └── hierarchical → symlink stage
                                                  ↓
                                            inspect_petri _load_markdown_seeds
                                            (flat glob "*.md")
```

- **File format**: both `*.md`. ✓
- **Directory layout**: bridge via `flatten_for_inspect_petri`. ✓
- **Handoff symlink**: `~/.geode/self-improving-loop/latest_seed_pool`
  updated by `_update_latest_seed_pool_symlink` (`orchestrator.py:436`),
  read by `_resolve_seed_select` priority 2 (`train.py:165-180`). ✓

### Frontmatter schema gap (PR-OPS-1 scope)

| Source | Frontmatter fields | Dim attribution |
|--------|-------------------|-----------------|
| Petri static (`01_base.md`) | `tags: [...]` | dir path (`<tier>/<dim>/`) |
| co-scientist (`seed_generator.md:23`) | `name`, `category`, `target_dims`, `paraphrase_seed` | `target_dims` list |

**Mismatch impact**: `inspect_petri._load_markdown_seeds` reads
body only — execution doesn't fail. BUT downstream tools that
read frontmatter (analysis scripts, dim-stderr breakdown) lose
attribution when consuming a mixed pool.

**PR-OPS-1 fix**: amend `seed_generator.md` contract to emit BOTH
`target_dims` (preserved for co-scientist internal tooling) AND
`tags: [<dim>, "geode_specific"]` (Petri-compatible). Generator
emits both at write time.

**Deferred**: dim-encoded directory layout for co-scientist
survivors (`<tier>/<dim>/` re-organization) — PR-OPS-3.

## Full system flow (closed loop, code-grounded)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                  [GEODE self-improving loop closed cycle]               │
└─────────────────────────────────────────────────────────────────────────┘

  ┌─① co-scientist (seed_generation) ──────────────────────────────────┐
  │  Pipeline: generator → proximity → critic → pilot → ranker →       │
  │             evolver → meta_reviewer (7 sub-agents 병렬)            │
  │  Output: <run_dir>/survivors/ + survivors.json                     │
  │  Side: ~/.geode/self-improving-loop/latest_seed_pool symlink update│
  └────────────────────────────────────────────┬───────────────────────┘
                                               │ seed pool handoff
                                               ▼
  ┌─② Petri 호출 (geode audit subprocess) ─────────────────────────────┐
  │  Caller: autoresearch/train.py:_build_audit_command                │
  │  Inside subprocess: inspect_petri runs audit transcripts           │
  │  Bias: same-provider judge auto -10~22% (petri_audit/bias.py)      │
  │  Output: dim_means + dim_stderr (20-dim)                           │
  └────────────────────────────────────────────┬───────────────────────┘
                                               │ dim 전달
                                               ▼
  ┌─③ autoresearch 집계 ───────────────────────────────────────────────┐
  │  compute_fitness(current, baseline)                                │
  │    - critical 5 dim 회귀시 fitness=0.0 (strict reject)             │
  │    - 정상이면 weighted sum (1.0 total)                             │
  │  _should_promote(current, baseline, margin=stderr_floor)           │
  │    - baseline 없으면 bootstrap promote                              │
  │    - gated_fitness=0 → reject                                      │
  │    - margin 초과 개선이면 baseline.json overwrite                  │
  └────────────────────────────────────────────┬───────────────────────┘
                                               │ fitness + baseline
                                               ▼
  ┌─④ autoresearch의 LLM (mutator) ────────────────────────────────────┐
  │  Source: SelfImprovingLoopRunner.run_once()                        │
  │  Reads: baseline.json + latest_meta_review.json + program.md       │
  │         + WRAPPER_PROMPT_SECTIONS 현재값                            │
  │  Calls: [self_improving_loop.mutator] 모델 (default claude-opus-4-7)│
  │  Output: Mutation { target_kind, target_section, prev, new, ... }  │
  └────────────────────────────────────────────┬───────────────────────┘
                                               │ Mutation JSON
                                               ▼
  ┌─⑤ GEODE 자동 수정 (apply_mutation) ────────────────────────────────┐
  │  Writes: ~/.geode/self-improving-loop/{wrapper-sections |          │
  │          tool-policy | decomposition | retrieval | reflection}.json│
  │  Appends: autoresearch/state/mutations.jsonl (git-tracked audit)   │
  │  Side: GEODE runtime의 PromptAssembler / ToolPolicy / ... 가         │
  │         다음 호출부터 새 SoT 읽음                                  │
  └────────────────────────────────────────────┬───────────────────────┘
                                               │ next iteration
                                               ▼
                                       (cycle back to ②)
```

### Wiring 상태 + GAP

| 연결 | 상태 | Ground |
|------|-----|--------|
| ① → ② seed pool handoff | ✓ wired | `latest_seed_pool` symlink + env override + toml fallback |
| ② → ③ dims → fitness | ✓ wired | subprocess stdout 파싱 |
| ③ → ④ baseline → mutator | ✓ wired | `baseline_reader.load_baseline` |
| ④ → ⑤ Mutation → SoT | ✓ wired | `apply_mutation` 5-kind dispatcher |
| ⑤ → ② new SoT → next audit | ✓ wired | `GEODE_WRAPPER_OVERRIDE` env |
| **⚠ Frontmatter schema** | partial | PR-OPS-1 fix — add `tags` to seed_generator |
| **⚠ Dim dir encoding loss** | partial | PR-OPS-3 deferred |
| **❌ UI 노출** | none | PR-OPS-1/2/3 adds slash + tool + dashboard |
| **❌ petri_raw harness entry** | none | PR-OPS-2 wires direct `run_audit` call |

## UX Design — 3-tier hierarchy

35+ knobs across 5 components. Pre-flight prompt for every knob
is unfeasible → 3-tier hierarchy:

### Tier 1 — pre-flight dashboard (매번 노출)

`/self-improving run` 진입 시 Rich Panel 1개. 4-stage pipeline
diagram + per-stage role 매트릭스 + harness radio + scope/quota.

```
┌─ Self-improving loop — pre-flight ─────────────────────────────────────────┐
│                                                                             │
│  Profile  [● balanced]  cheap  max-quality  subs-only  petri-alignment      │
│                                                                             │
│  Pipeline (harness=autoresearch)                                            │
│  ┌─ ① Seed gen ──┐  ┌─ ② Mutate ────┐  ┌─ ③ Measure ──┐  ┌─ ④ Orchestrate┐  │
│  │ co-scientist  │→ │ Mode B runner │→ │ Petri        │→ │ autoresearch  │  │
│  │ 7 roles · gen1│  │ mutator LLM   │  │ 17-dim audit │  │ subprocess    │  │
│  │ 15 cand       │  │ → SoT write   │  │ bias auto ⓘ  │  │ conductor (×5)│  │
│  └───────────────┘  └───────────────┘  └──────────────┘  └───────────────┘  │
│                                                                             │
│  Harness mode                                                               │
│   [●] autoresearch     (stages 1+2+3+4 · 5min · dry-run)                    │
│   [ ] petri_raw        (stages 1+2+3 · raw 17-dim · no gate)  ❌ not wired │
│   [ ] seed tournament  (stages 1+2+4 · Elo · no Petri)                      │
│   [ ] no-op            (stages 1+2 · apply only)                            │
│                                                                             │
│  Active roles                                                               │
│  ┌─ Stage ┬ Role                ┬ Model              ┬ Source ┬ Cost ─┐    │
│  │  ①     │ co-scientist (×7)   │ mixed (opus/snt/h) │ auto   │ ●●○   │    │
│  │  ②     │ mutator LLM         │ claude-opus-4-7    │ auto   │ ●●○   │    │
│  │  ③     │ Petri auditor       │ claude-opus-4-7    │ oauth  │ ●●●   │    │
│  │  ③     │ Petri target        │ geode/gpt-5.5      │ oauth  │ ●○○   │    │
│  │  ③     │ Petri judge         │ claude-code/opus   │ oauth  │ ●●●   │    │
│  │  ④     │ (autoresearch orchestrator — no LLM; conducts ③ subprocess)│  │
│  └────────┴─────────────────────┴────────────────────┴────────┴───────┘    │
│                                                                             │
│  Petri-only                                                                 │
│   bias correction   ✓ auto (same-provider judge → -10~22%)                  │
│   dim_set           5axes  (geode_5axes available)                          │
│   audit_mode        dry_run · auto_approve · denied=[edit_file]             │
│                                                                             │
│  Scope                                                                      │
│   target_kind       any  (prompt|tool_policy|decomp|retr|reflect)           │
│   iterations        1                                                       │
│                                                                             │
│  Quota & budget                                                             │
│   Anthropic         ▓▓▓▓▓░░░ 52%  ⚠ warn                                    │
│   OpenAI codex      ▓░░░░░░░  8%  ✓ ok                                      │
│   PAYG fallback     [disabled]    ⓘ                                         │
│   Session cost      USD  unlimited                                          │
│                                                                             │
│  Cognitive reflection   [enabled]  haiku · every 1 round  ⓘ                 │
│                                                                             │
│  [Enter]=run  [p]=profile  [h]=harness  [m]=model  [s]=source              │
│  [t]=target_kind  [n]=iterations  [a]=audit_mode  [d]=drill-down  [q]=cancel│
└─────────────────────────────────────────────────────────────────────────────┘
```

**Active roles 표 — harness 선택에 따라 동적**:

| Harness | Active role rows |
|---------|-----|
| `autoresearch` | co-scientist + mutator + Petri auditor/target/judge + (gate compute-only) |
| `petri_raw` | co-scientist + mutator + Petri auditor/target/judge |
| `seed tournament` | co-scientist + mutator |
| `no-op` | mutator only |

### Stage ④ autoresearch orchestrator — sub-panel

autoresearch 는 LLM 호출 주체가 아니지만 **5개 책임을 가진 subprocess
conductor** (코드 ground: 2026-05-21 verification):

| # | Responsibility | Code anchor |
|---|---------------|-------------|
| ① | Seed pool cross-loop receiver | `autoresearch/train.py:161-180` `_resolve_seed_select` (env > symlink > toml > module) |
| ② | Mutation in-flight delivery | `autoresearch/train.py:484-492` `_dump_wrapper_override` + `env["GEODE_WRAPPER_OVERRIDE"]` (line 555) |
| ③ | Measurement subprocess lifecycle | `autoresearch/train.py:495-614` `run_audit` (spawn + timeout + capture) |
| ④ | Fitness / promote decider | `autoresearch/train.py:672-728 compute_fitness`, `:1047-1099 _should_promote` |
| ⑤ | Telemetry emitter | `autoresearch/train.py:421-449 _emit_journal` (9 events) |

`results.tsv` / `results.jsonl` rendering is **stdout only** — caller (operator
script or `SelfImprovingLoopRunner._run_autoresearch_subprocess`) appends to
disk. Git commit is NOT autoresearch's responsibility — post-audit agent owns.

Operator-visible sub-panel (Tier 1 dashboard 의 stage ④ 카드 클릭 시):

```
┌─ Stage ④ autoresearch orchestrator ────────────────────────────────────────┐
│                                                                              │
│   subprocess control                                                         │
│     budget_minutes      5     (1 ~ 60)         ⓘ subprocess timeout         │
│     max_turns           10    (1 ~ 200)        ⓘ audit transcript depth     │
│     use_oauth           [✓]                    ⓘ subscription vs PAYG       │
│                                                                              │
│   measurement scope                                                          │
│     seed_limit          10    (1 ~ 1000)       ⓘ Petri audit 시나리오 수    │
│     dim_set             5axes (5axes | geode_5axes)                          │
│     seed_select         auto  (env > symlink > toml > module)                │
│       └─ resolved      ~/.geode/.../latest_seed_pool → <co-scientist run>   │
│                                                                              │
│   mutation delivery (G7)                                                     │
│     wrapper-override   state/wrapper-override.json   [last dumped 12:34:56]  │
│     env injection      GEODE_WRAPPER_OVERRIDE → audit subprocess             │
│                                                                              │
│   subprocess lifecycle (G10)                                                 │
│     last run           02:34 elapsed · ok  /  timeout · failed               │
│     forwards to ③      --target=gpt-5.5  --judge=opus  (edit stage ③ →)    │
│                                                                              │
│   fitness aggregation                                                        │
│     critical floor     strict reject on regression of 5 critical dims        │
│     fitness margin     0.05  (raw_fitness gain > max(prior_stderr, .05))    │
│     stability weight   0.10                                                  │
│                                                                              │
│   promote decision (G8)                                                      │
│     last promoted      2026-05-21T10:00  baseline.json fitness=0.7345       │
│     last decision      promote · reject (margin 0.012 ≤ 0.05)                │
│                                                                              │
│   telemetry (G9 — last 9 journal events)                                     │
│     12:34:00 audit_started   12:34:01 config_snapshot                        │
│     12:34:01 wrapper_override_dumped  12:34:02 subprocess_started            │
│     12:36:30 subprocess_finished  12:36:31 baseline_decision (promote)       │
│     12:36:32 per_dim_scores  12:36:33 audit_finished                         │
│                                                                              │
│   model column: (none — autoresearch 자체는 LLM 호출 주체 아님)              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Stage ④ owner re-attribution

이전 Petri-only 블록에 잘못 들어있던 knob 들 → Stage ④ sub-panel 로 이동:

| Knob | 이전 위치 | 정정 위치 | Owner (코드) |
|------|---------|---------|------------|
| `budget_minutes` | Petri-only | Stage ④ subprocess control | autoresearch (subprocess timeout 산정) |
| `max_turns` | Petri-only | Stage ④ subprocess control | autoresearch (argv 전달) |
| `seed_limit` | (불명) | Stage ④ measurement scope | autoresearch (argv 전달) |
| `dim_set` | Petri-only | Stage ④ measurement scope | autoresearch (argv 전달) |
| `use_oauth` | (없음) | Stage ④ subprocess control | autoresearch (argv conditional flag) |
| `_resolve_seed_select` 4-tier | (없음) | Stage ④ measurement scope | autoresearch (precedence resolver) |
| `_dump_wrapper_override` env conveyor | (없음) | Stage ④ mutation delivery | autoresearch (mutation in-flight delivery) |
| `_should_promote` 3-rule | "pure compute" 단순화 | Stage ④ promote decision | autoresearch (3-rule gate) |
| 9개 SessionJournal event | (없음) | Stage ④ telemetry timeline | autoresearch (observability) |
| Subprocess timeout/failed branch | (없음) | Stage ④ subprocess lifecycle | autoresearch (lifecycle manager) |

Petri-only 블록에 남는 것 (정합 유지):
- bias correction (-10~22%) — `plugins/petri_audit/bias.py` owner
- audit_mode (allow_dangerous / allow_write / force_dry_run / auto_approve)
- per-transcript judge rubric application

### GAP list — UI 비주얼화 누락

| # | Knob/동작 | Owner | Pre-PR-OPS-2 dashboard | 정정 위치 |
|---|---------|------|----------|-----------|
| G1 | `budget_minutes` | autoresearch | Petri-only block | Stage ④ subprocess control |
| G2 | `max_turns` | autoresearch | Petri-only block | Stage ④ subprocess control |
| G3 | `seed_limit` | autoresearch | (없음) | Stage ④ measurement scope |
| G4 | `dim_set` | autoresearch | Petri-only block | Stage ④ measurement scope |
| G5 | `use_oauth` | autoresearch | (없음) | Stage ④ subprocess control |
| G6 | `seed_select` 4-tier resolution | autoresearch | (없음) | Stage ④ measurement scope (resolved path) |
| G7 | `GEODE_WRAPPER_OVERRIDE` env conveyor | autoresearch | (없음) | Stage ④ mutation delivery |
| G8 | `_should_promote` 3-rule | autoresearch | "pure compute" | Stage ④ promote decision (rule view) |
| G9 | 9 SessionJournal event timeline | autoresearch | (없음) | Stage ④ telemetry |
| G10 | subprocess timeout/failed status | autoresearch | (없음) | Stage ④ subprocess lifecycle |
| G11 | `results.tsv` / `.jsonl` viewer | autoresearch (stdout) | (없음) | PR-OPS-3 results viewer |
| G12 | Git commit owner clarification | NOT autoresearch (post-audit agent) | 사용자 혼동 위험 | "외부 agent 책임" 라벨 |

### Tier 2 — drill-down sub-pickers

- `m` → component → model picker (existing `effort_picker` 재사용)
- `s` → component → source picker
- `h` → harness modifier (dry-run / live / budget / dim_set / audit_mode)
- `a` → audit_mode toggles (allow_dangerous / allow_write / force_dry_run / auto_approve / denied_tools list)
- `d` → drill-down: co-scientist 7 roles | autoresearch tgt/judge | Petri roles | cognitive reflection

### Tier 3 — config-only (`~/.geode/config.toml` 편집)

`/self-improving config` 슬래시 또는 외부 편집:
- Bias correction band (`DISADVANTAGE_BAND` = (0.10, 0.22))
- Token cost model parameters (per-role in/out tokens, cache_read_ratio)
- AuditMode default policies
- Quota thresholds (warn/abort)
- PAYG fallback policy
- Learning extract model

## Profile bundles

`~/.geode/config.toml [self_improving_loop.profile.<name>]`:

| Profile | Mutator | Harness | co-scientist | Source | Petri | Use case |
|---------|---------|---------|--------------|--------|-------|----------|
| `cheap` | haiku | no-op | all-haiku | api_key | — | 빠른 dry-run 실험 |
| `balanced` (default) | sonnet | autoresearch dry-run | mixed | auto | — | 일반 운용 |
| `max-quality` | opus | autoresearch live | all-opus | oauth | — | 최고 품질 |
| `subs-only` | sonnet | no-op | sonnet | claude-cli | — | 구독 quota만 |
| `petri-alignment` | opus | petri_raw dry-run | mixed | oauth | auditor=opus, target=gpt-5.5, judge=sonnet | alignment 검증 (judge≠mutator 로 bias 회피) |
| `tournament` | opus | seed tournament | mixed | auto | — | 후보 순위만, Petri 비용 절약 |
| `custom` | — | — | — | — | — | 사용자 정의 |

## Slash command surface

`COMMAND_REGISTRY` (`core/cli/routing.py`) + `COMMAND_MAP` (`core/cli/commands/_state.py`):

| Command | Action | PR |
|---------|--------|----|
| `/self-improving` (no action) | = `status` (default) | OPS-1 |
| `/self-improving status` | recent baseline + last N mutations | OPS-1 |
| `/self-improving run [--n N] [--profile=…]` | N iterations with per-iteration confirmation prompt | OPS-2 |
| `/self-improving history [--n N]` | last N audit rows tabular | OPS-3 |
| `/self-improving rollback <mutation_id>` | restore previous_value to SoT + audit row | OPS-3 |
| `/self-improving config` | show/edit `[self_improving_loop.*]` toml | OPS-3 |
| `/sil <action>` | alias | OPS-1 (registered for forward compat) |

## Natural language surface (Tool registry)

`core/tools/self_improving_tool.py` (PR-OPS-2):

```python
run_self_improving_loop(
    iterations: int = 1,
    auto_apply: bool = False,
    profile: str | None = None,
    target_kind: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict
```

자연어 예:
- "self-improving loop 한 번 돌려" → `iterations=1, profile=None`
- "petri-alignment 프로필로 1회" → `profile="petri-alignment"`
- "judge 만 sonnet 으로 바꿔 진행" → `overrides={"autoresearch.judge_model": "claude-sonnet-4-6"}`

## Confirmation prompt UX

`/self-improving run` 의 매 iteration confirmation (사용자 결정):

```
[Self-improving loop — proposal 1/1]
  target_kind:    tool_policy
  target_section: delegate_task.priority
  previous_value: 5
  new_value:      8
  rationale:      delegation success rate 0.62 → 0.78
                  in last 10 episodes
  baseline:       0.72 (SoT)
  expected_dim:   throughput +0.08
  rollback_cond:  fitness < 0.70 over 3 generations

Apply? [y/N/d=show-diff/s=show-rationale]:
```

응답:
- `y` → apply (SoT write + audit `kind: applied`)
- `N` (default) → skip (audit `kind: rejected`, optional reason)
- `d` / `s` → 보조 출력 후 재-prompt

## Implementation Checklist

### PR-OPS-1 (this PR)

- [ ] `docs/plans/2026-05-21-self-improving-loop-ux.md` (this file)
- [ ] `core/cli/commands/cmd_self_improving.py` — new slash handler with `status` action
- [ ] `core/cli/routing.py` — register `/self-improving` + `/sil` (THIN location)
- [ ] `core/cli/commands/_state.py` — add to `COMMAND_MAP`
- [ ] `core/cli/dispatcher.py` — wire `_handle_command` route
- [ ] `.claude/agents/seed_generator.md` — amend contract: emit BOTH `target_dims` and `tags` fields in frontmatter
- [ ] `plugins/seed_generation/agents/generator.py` — instruct sub-agent prompt to include `tags`
- [ ] Tests: `tests/test_self_improving_status_slash.py` — slash registration + output format invariants
- [ ] CHANGELOG `[Unreleased]` entry
- [ ] PR feature → develop, CI 8/8 + Codex MCP

### PR-OPS-2

- [ ] Tier 1 dashboard (Rich Panel + prompt_toolkit hot-key)
- [ ] Tier 2 drill-down sub-pickers (m / s / h / a / d)
- [ ] Tool `run_self_improving_loop` in tool registry
- [ ] `/self-improving run [--n N] [--profile=…]` with confirmation prompt
- [ ] 3 profile presets (balanced/cheap/max-quality)
- [ ] `petri_raw` harness wiring — direct `plugins/petri_audit/runner.py:run_audit` entry

### PR-OPS-3

- [ ] `/self-improving config` slash
- [ ] Quota bar real-time wiring (FE banner)
- [ ] co-scientist survivors hierarchical `<tier>/<dim>/` dir layout

> **PR-MINIMAL-1 (2026-05-21) drops**:
> - `/self-improving history` — wired to print `git log -p autoresearch/state/mutations.jsonl` recipe. PR-RATCHET-1 made both mutations.jsonl + policies/ git-tracked, so `git log` IS the canonical history; no need to re-implement a JSONL tail walker in the slash.
> - `/self-improving rollback <id>` — wired to print `git revert <sha>` recipe (with `git log --grep=<id>` to find the SHA). Re-implementing rollback would duplicate git semantics.
> - 7-profile preset bundle (cheap/balanced/max-quality/subs-only/petri-alignment/tournament/custom) — deferred indefinitely; upstream Karpathy autoresearch has no profile concept. `~/.geode/config.toml` toml overrides cover the same need with one less concept. PR-OPS-2b's dashboard will surface `Settings.model` + `[self_improving_loop.*]` toml values directly.
> - Tier 2 drill-down sub-pickers (m / s / h / a / d) — strongly de-prioritised. Tier 1 dashboard renders the current state; operators edit `config.toml` for changes. Re-introduce only when concrete operator demand surfaces.
> - 4-harness picker (autoresearch / petri_raw / seed tournament / no-op) → single default `autoresearch`. `--harness=<name>` flag stays as power-user opt-in but isn't surfaced in the default UI.

## Mode A vs Mode B (post-MINIMAL-1)

| Mode | Trigger | LLM | Audit channel |
|------|---------|-----|--------------|
| **A. Karpathy idiom** | External Claude/Codex session boots with `autoresearch/program.md` as system prompt; operator reads + edits `autoresearch/train.py` manually | Whatever runs the external session (typically Claude Code) | `git diff` + `git log`; same `autoresearch/state/policies/*.json` SoT |
| **B. Programmatic** (canonical) | `geode /self-improving run` slash OR scheduled job calling `SelfImprovingLoopRunner.run_once()` | `[self_improving_loop.mutator] default_model` (default `claude-opus-4-7`) | `git log autoresearch/state/mutations.jsonl` + `git diff autoresearch/state/policies/` |

**Mode A 의 운영자 매뉴얼**: `autoresearch/README.md` 의 "Running the agent" 섹션 참조 — boot prompt `Read program.md and start a new experiment` 로 외부 long-horizon Claude 세션 띄우면 됨. Mode A 는 *manual long-horizon agent* path. GEODE CLI 의 슬래시/툴 표면은 Mode B 만 trigger 함 — 두 path 가 동일 `autoresearch/state/policies/` SoT 를 공유하므로 결과는 호환됨.

**PR-MINIMAL-1 (2026-05-21) — Mode A 는 docs-only**. CLI/REPL 표면은 Mode B 에 집중. Mode A 에 별도 UI 슬래시 추가 안 함 (외부 agent session 컨트롤은 GEODE 책임 밖).

## DONT lessons applied (CLAUDE.md table)

- **"Programmatic mutator LLM = autoresearch's LLM"** — Mode A
  (Karpathy external agent) and Mode B (`SelfImprovingLoopRunner`)
  are both valid mutator pathways; UI surface only triggers Mode
  B. Doc this explicitly in `cmd_self_improving.py` docstring.
- **Frontmatter schema mismatch** — Petri uses `tags`, co-scientist
  uses `target_dims`. Emit BOTH at write time to avoid downstream
  attribution loss.
- **Wiring claim verification** — PR body claims "self-improving
  loop available" → grep for new slash registration in
  `COMMAND_REGISTRY` + `COMMAND_MAP` before push.
- **CHANGELOG/PR-body parity** — every verb in CHANGELOG ("operator-
  facing surface", "status visible", "Petri-compatible") must have
  a grep-provable code anchor.

## Reference

- Karpathy autoresearch (3-file pattern source): https://github.com/karpathy/autoresearch (228791f, MIT 2026-03)
- Previous wiring sprint: `docs/plans/2026-05-19-self-improving-loop-wiring-sprint.md`
- Config consolidation: `docs/plans/2026-05-19-self-improving-loop-config-consolidation.md`
- Cognitive uplift Phase 2: `docs/plans/2026-05-21-cognitive-loop-uplift.md`
- Petri × GEODE alignment audit: `docs/audits/2026-05-15-petri-insights.md`
