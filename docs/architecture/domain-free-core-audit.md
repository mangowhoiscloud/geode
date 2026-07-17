---
title: Domain-free core — audit + cut-line design
date: 2026-05-06
status: review
audience: GEODE/REODE multi-fork architecture
related:
  - docs/architecture/hook-system.md
  - docs/architecture/wiring-audit-matrix.md
  - plugins/__init__.py (v0.64.0 plugin namespace)
---

# Domain-free core — audit + cut-line design

> [!NOTE]
> Historical audit: its motivation and cut-line reasoning remain useful, but
> package names, counts, and implementation status describe 2026-05-06.
> Current GAP status and execution order are owned by
> [`extensibility-roadmap.md`](extensibility-roadmap.md), especially BND-001
> through BND-004.

## TL;DR

- **Strategy**: GEODE pivots to a multi-fork model. This repo stays as `geode-with-game_ip`. A future REODE fork reuses `core/` for a migration agent. Both share `core/` infra; sync requires `core/` to be **truly domain-free**.
- **Inventory**: 29 files in `core/` reference game_ip. Of those: **4 PURE-INFRA** (no change), **8 PURE-PLUGIN** (whole-file move), **17 MIXED** (surgical split).
- **LOC to extract**: ~5,550 out of `core/` total. Equivalent to roughly 1 release cycle of focused refactor work, sequenced over 8 PRs.
- **The architectural surprise**: `core/graph.py:build_graph()` topology is **hardcoded to the 7-node game_ip DAG** (router → signals → analyst → evaluator → scoring → verification → synthesizer → gather). `core/state.py` `GeodeState` TypedDict is entirely IP-shaped. "Domain-free core" means cleaving the topology and state schema out, not just relocating files.
- **Closest frontier analogue**: Claude Code (closed kernel + filesystem-discovered, frontmatter-contract extensions). Codex CLI's crate-per-concern discipline is the secondary reference for internal organization.
- **Recommendation**: 8-step sequenced refactor. Lowest-risk first (1-line config indirections) → highest-risk last (state.py + graph.py topology surgery). REODE fork is feasible only after step 7-8 land.

---

## 1. Why we audited

### 1.1 The pivot

The strategy clarified in this session:

| Repo | Vertical | Status |
|------|----------|--------|
| `mangowhoiscloud/geode` (this) | Game IP analysis | Stays. Game-IP plugin lives at `plugins/game_ip/` |
| `mangowhoiscloud/reode` (planned) | Migration agent (ASSESS → PLAN → TRANSFORM) | Forks `core/` from this repo; brings its own `plugins/migration/` |

The two repos must be able to **sync `core/` changes between them via cherry-pick or rebase**. That's only feasible if `core/` has zero `plugins/*` dependencies — bidirectional or otherwise.

### 1.2 What v0.64.0 already did, and why it was insufficient

v0.64.0 (2026-04-29) moved `core/domains/game_ip/` → `plugins/game_ip/`. 220 files relocated, 72 import statements rewritten, quality gates extended to `plugins/`. But a quick `grep -rn 'game_ip\|GameIP' core/` returns hits in **27 files**, plus `core/state.py` (uses IP-vocabulary without the literal string) and `core/ui/panels.py` (lazy plugin import inside a method). 29 files total. The directory moved; the dependency lines didn't. v0.64.0 was a *naming* split, not an *architectural* split.

### 1.3 Audit scope

This audit answers: **"What's the boundary between `core/` (infra) and `plugins/game_ip/` (vertical), file by file, with concrete cut lines?"**

Out of scope:
- Implementing the cut. This is design only.
- `tests/`, `docs/`, `scripts/`, `experimental/` directories. Audit covers `core/` Python source.
- Cross-cutting renames in non-Python assets (`.geode/config.toml`, `core/tools/tool_schemas.json`) — flagged as follow-on work, not scoped here.

---

## 2. Frontier pattern comparison

Four frontier autonomous-agent harnesses were surveyed for "how do they cut domain vertical from infra core?"

| System | Cut style | Plugin loading | Contract location | Extension points |
|--------|-----------|----------------|-------------------|------------------|
| **Claude Code** | Closed kernel + open extensions | Filesystem + frontmatter discovery; precedence chain | `.claude-plugin/plugin.json` + `SKILL.md` YAML frontmatter | `commands/`, `agents/`, `skills/`, `hooks/`, `.mcp.json` |
| **Codex CLI** | Open Rust, crate-per-concern | TOML config + multi-root filesystem traversal | `core-skills/` crate + `[mcp_servers.<id>]`, `[skills]`, `[tools]`, `[permissions]`, `[profiles]` TOML tables | Skills, MCP, AGENTS.md, profiles, permission profiles, sandbox modes |
| **OpenClaw** | Plugin-first; even providers/channels are dynamic npm packages | `package.json:openclaw.extensions` + dynamic `import()`; persisted `plugins/installs.json` registry | `definePluginEntry({ register(api) {…} })` exposing ~10 `registerX` methods | Provider, tool, channel, http-route, command, hook, context-engine, service |
| **autoresearch** | **Anti-plugin / single-file** (3 files total, only `train.py` mutable) | N/A | `program.md` (prose contract: Setup, Experimentation, Output, Logging, Loop) | None — adding files/packages is explicitly forbidden |

### 2.1 Closest analogue for GEODE: **Claude Code**

GEODE is already a multi-component Python package with a closed-style core (LangGraph runtime, scoring, verification, hooks) and an emerging extension surface (`.claude/skills/`, ToolRegistry, HookSystem 82 events). Claude Code's "stable closed kernel + filesystem-discovered domain extensions with frontmatter contracts" maps almost 1:1 to where GEODE wants to land.

Codex CLI's crate-per-concern decomposition is the right reference for cleaning up `core/` internally, but GEODE is one Python package, not a Cargo workspace, so the Codex pattern translates to module/subpackage boundaries rather than literal crates.

OpenClaw's full hot-reload-everything model is overkill for GEODE's pipeline-oriented domain — adopting it now would collide with the in-flight refactor. autoresearch is a cautionary tale, not a template; GEODE's typed Pydantic schemas + multi-stage verification pipeline cannot collapse into a single mutable file.

### 2.2 Patterns to adopt

1. **Domain-as-skill, kernel-as-frozen** (Claude Code). `core/` becomes the closed kernel. Every domain-shaped artifact (rubric axes, analyst prompts, evaluator definitions, signal scrapers, scoring weights, IP fixtures, synthesis vocabulary) lives in `plugins/<vertical>/`.
2. **Frontmatter-driven progressive disclosure** (Claude Code, Codex). Each Analyst/Evaluator becomes a directory with `prompt.md`, `schema.json`, and a `META.yaml` frontmatter declaring `triggers`, `output_schema`, `confidence_floor`. Graph builder reads frontmatter at startup.
3. **Crate-style internal cut** (Codex). Even within one Python package, enforce subpackage separation: `core/runtime/`, `core/scoring/` (math only, no domain weights), `core/verification/` (G1-G4 framework, no IP rubric weights), `core/skills/` (registry only, no `reports.py`-style domain code). Strict dependency direction: `plugins/* → core/*`, never reverse.
4. **Two-axis extension** (Claude Code + OpenClaw). Distinguish *behavioral* extensions (skills, prompts, rubrics — text artifacts loaded by the LLM) from *capability* extensions (tools, channels, providers — code artifacts loaded by the runtime). GEODE has hints of both already.
5. **Most-Specific-Wins precedence chain** (Claude Code skills, OpenClaw). Bundled defaults < installed domain plugin < project override < session override.

### 2.3 Anti-patterns to avoid

1. **OpenClaw-style total runtime plugin pluralism** while `core/` is still being de-coupled. Two large refactors collide. Adopt Claude Code posture first; loosen later only if a real second non-vertical plugin (e.g. third-party LLM provider) demands it.
2. **autoresearch single-file purity**. Borrow program.md's *discipline* (constraints documented in prose, simplicity bias) without the file-count constraint.
3. **Plugin-shaped wrappers over still-coupled code**. The Codex test is the right gate: `core/` must compile and pass its own tests **with no `plugins/` directory present**. If it can't, the cut is fake.

### 2.4 Open question for the team

Where does `HookSystem` (82 events) live? Claude Code hooks live inside a plugin (`hooks/` dir alongside `skills/`); OpenClaw hooks register through `register(api).on(...)` and can be cross-plugin; autoresearch has no hooks. If `plugins/migration/` wants to fire `on_analyst_complete` to inject migration-specific verification, does that handler live in `core/hooks/` or `plugins/migration/hooks/`? **The answer determines whether HookSystem is closed-kernel event bus (Claude Code style) or open extension surface (OpenClaw style).** Decide before the second non-game-IP vertical lands; retrofitting hook ownership is one of the harder cuts to reverse.

---

## 3. Inventory — 28 files classified

### 3.1 Summary stats

| Bucket | Count | Files | LOC moved |
|--------|-------|-------|-----------|
| **PURE-PLUGIN** | 8 | `cli/batch`, `cli/ip_names`, `cli/search`, `tools/analysis`, `mcp/signal_adapter`, `state`, `skills/reports`, `ui/panels` | ~2,490 |
| **PURE-INFRA** | 4 | `lifecycle/automation`, `agent/worker`, `domains/port`, `domains/loader` | 0 |
| **MIXED** | 17 | (see §3.2) | ~3,060 |
| **Total** | 29 | — | **~5,550** |

Notes:
- "PURE-PLUGIN" = whole-file move; small remnant (≤50 LOC of generic reducers/enums) may optionally stay as a thin shell, but the bulk goes to the plugin.
- LOC moved is the line count departing `core/`. New abstractions added to `core/` (DomainPort v2 methods, registries, descriptors) add roughly +300 LOC, not counted here.

### 3.2 Classification table

| # | File | Bucket | LOC moved | Risk | Note |
|---|------|--------|-----------|------|------|
| 1 | `core/cli/__init__.py` | MIXED | ~250 / 1888 | medium | `_handle_command` slash dispatcher generic; bodies hardcoded to game_ip. `_build_runtime_for_serve` line 1880 hardcodes `domain_name="game_ip"` |
| 2 | `core/cli/bootstrap.py` | MIXED | ~6 / 238 | low | Two `load_domain_adapter("game_ip")` calls; replace with `settings.default_domain` |
| 3 | `core/cli/tool_handlers.py` | MIXED | ~250 / 1628 | medium | `_build_analysis_handlers` (180 LOC) + 4 signal entries in `_DELEGATED_TOOLS` + `handle_rerun_node` allowlist |
| 4 | `core/cli/batch.py` | PURE-PLUGIN | 246 (whole) | low | Imports `plugins.game_ip.fixtures.FIXTURE_MAP` at top-level; entire file is IP-batch UX |
| 5 | `core/cli/pipeline_executor.py` | MIXED-leans-PLUGIN | ~600 / 691 | **HIGH** | **87% game_ip.** `_STEP_LABELS` hardcodes 7-node game_ip topology; analyst/evaluator counts hardcoded 4/3; 6 panel renderers; `_resolve_ip_name`, `_run_analysis`, `_build_initial_state` all IP. Generic remnants: `_progress_line`, `_handle_interrupt`, `_merge_event_output` (~125 LOC) |
| 6 | `core/cli/ip_names.py` | PURE-PLUGIN | 44 (whole) | low | Filename honest; entire file is IP fixture name resolution |
| 7 | `core/cli/commands.py` | MIXED | ~120 / 2544 | medium | Mostly generic auth/model/login/cost/skills (~95%); `cmd_list`, `cmd_generate`, `cmd_batch` and game_ip slash entries in `COMMAND_MAP`/`show_help` are vertical |
| 8 | `core/cli/search.py` | PURE-PLUGIN | 198 (whole) | low | `_SYNONYMS` (Korean→English game-genre dict), `_IPIndex` shape, `IPSearchEngine` — all fixture-coupled |
| 9 | `core/tools/analysis.py` | PURE-PLUGIN | 285 (whole) | medium | `RunAnalystTool`, `RunEvaluatorTool`, `PSMCalculateTool`, `ExplainScoreTool`. Tool schemas in `tool_schemas.json` need parallel relocation |
| 10 | `core/tools/signal_tools.py` | MIXED | ~410 / ~640 | medium | 5 IP signal tools (YouTube/Reddit/Twitch/Steam/GoogleTrends) coupled with reusable MCP helpers (`_parse_mcp_content`, `_try_mcp_signal`) and `WebSearchTool`. Best split candidate in cluster |
| 11 | `core/tools/data_tools.py` | MIXED | ~80 / ~185 | low | `QueryMonoLakeTool` IP; `CortexAnalystTool`, `CortexSearchTool` are domain-agnostic Snowflake stubs (keep) |
| 12 | `core/mcp_server.py` | MIXED | ~110 / ~190 | high | 4 IP-specific MCP tools + `geode://fixtures` resource. Server framework + `query_memory` + `get_health` + `geode://soul` stay |
| 13 | `core/mcp/signal_adapter.py` | PURE-PLUGIN | 75 (whole) | low | Misnamed (not an MCP framework adapter). `FixtureSignalAdapter`, `LiveSignalAdapter`, `create_signal_adapter` |
| 14 | `core/graph.py` | MIXED-leans-PLUGIN | ~550 / ~790 | **HIGH** | **`build_graph()` topology hardcoded.** Imports 9 game_ip nodes; `_NODE_COMPLETION_EVENTS` enumerates ANALYST/EVALUATOR/SCORING; `_make_degraded_result` knows 14-axis schema; `_verification_node` hardcodes rights_risk. Generic `_make_hooked_node`, `compile_graph`, `invoke_with_timeout`, `PipelineTimeoutError` (~240 LOC) stay |
| 15 | `core/runtime.py` | MIXED | ~30-50 (renames) | medium | `ip_name` first-class field; `domain_name="game_ip"` default; `phase="analysis"` hardcoded. Wiring is generic; vocabulary is IP. Mostly semantic renaming |
| 16 | `core/state.py` | PURE-PLUGIN | ~280 / ~330 | **HIGH** | Docstring claims "domain layer" but the file IS the domain. `RightsStatus`, `LicenseInfo`, `RightsRiskResult`, `CauseLiteral` (undermarketed/conversion_failure/...), `ActionLiteral`, `AnalysisResult`, `EvaluatorResult`, `PSMResult`, `SynthesisResult`, `AxisCalibration`, `EvaluatorCalibration`, `CalibrationResult`, `GeodeState` TypedDict — all IP. Generic: `_add_and_trim_history`, `_merge_dicts` reducers (~50 LOC) |
| 17 | `core/lifecycle/bootstrap.py` | MIXED | ~5 / 730 | low | 95% generic infra (build_hooks 25 handlers, build_memory, build_session_store, build_config_watcher). 1 plugin reach: `from plugins.game_ip.nodes.router import set_context_assembler` (L528-530) + `create_geode_task_graph` call (L640) |
| 18 | `core/lifecycle/automation.py` | PURE-INFRA | 0 | low | **Already cleaned.** Comment at L91-96 acknowledges domain extraction done. L4.5 monitoring (drift detector, snapshots, triggers, feedback) all generic. Optional: rename `ip_name` → `subject_id` |
| 19 | `core/lifecycle/adapters.py` | MIXED | ~40 / ~315 | low | `build_signal_adapter()` (L16-54) imports `from plugins.game_ip.nodes.signals` and wires Steam. Notification/Calendar/Gateway adapter halves are clean infra |
| 20 | `core/agent/worker.py` | PURE-INFRA | 0 | low | **Gold standard for domain-free infra.** Claude-Code-style isolated subprocess worker. `domain` field is opaque string; `_run_agentic` runs whatever prompt. Reference for the rest of `core/` |
| 21 | `core/agent/system_prompt.py` | MIXED | ~50 / ~460 | medium | `_NOTABLE_IPS` set (16 IP names) + `build_system_prompt` body that imports `plugins.game_ip.fixtures` are IP. G1-G4 memory hierarchy + model-card + identity-context (~410 LOC) is generic Claude Code prompt-cache infrastructure |
| 22 | `core/domains/port.py` | PURE-INFRA | 0 | low | Generic `DomainPort` Protocol (17 methods). v2 caveat: methods like `get_cause_values`, `get_tier_thresholds`, `get_cause_to_action` assume an evaluation/scoring domain shape. Research/automation verticals may need optional fields |
| 23 | `core/domains/loader.py` | PURE-INFRA | 1 (seed) | low | `_BUILTIN_DOMAINS = {"game_ip": "..."}` is string-only seed (not import). Move seed to plugin's `__init__.py` registration hook or config-driven |
| 24 | `core/verification/calibration.py` | MIXED | ~250 / ~378 | medium | `_EVALUATOR_AXIS_COUNTS` enumerates 14-axis evaluator weights; `_GOLDEN_SET_PATH` hardcodes `plugins/game_ip/fixtures/_golden_set.json`. Generic skeleton: `_calibrate_axes`, `load_golden_set(path)`, `AxisCalibration`, the three thresholds. Depends on `state.py` cluster decision |
| 25 | `core/skills/reports.py` | PURE-PLUGIN | ~1,100 + templates | medium | **Misfiled** — not a "skill", it's the IP report generator. `ReportFormat`/`ReportTemplate` enums (~30 LOC) optionally stay as `core/skills/report_format.py` |
| 26 | `core/llm/prompts/axes.py` | MIXED | ~50 / ~64 | medium-high | **Worst latent coupling.** Module-level eager YAML load (L19) — any `import core.llm.prompts.axes` without `plugins/game_ip` present **fails at import**. `_YAML_PATH`, `ANALYST_SPECIFIC`, `EVALUATOR_AXES`, `PROSPECT_EVALUATOR_AXES`, `AXES_VERSIONS` move to plugin. `core/llm/prompts/axes.py` keeps `get_valid_axes_map()` (already delegates to DomainPort) + `_hash_axes` |
| 27 | `core/memory/organization.py` | MIXED | ~80 / ~127 | medium | `MonoLakeOrganizationMemory` (despite generic-sounding name, fixture-shape-coupled), `DEFAULT_FIXTURE_DIR`, `get_common_rubric` move. `DEFAULT_SOUL_PATH` + `get_soul()` (Karpathy P7) stay as generic agent identity infra |
| 28 | `core/ui/event_renderer.py` | MIXED | ~160 / ~770 | medium | **Hidden runtime plugin import** at L567: `from plugins.game_ip.scoring_constants import score_ansi_color` inside `_handle_pipeline_evaluation`. Pipeline-specific handlers (`_handle_pipeline_*`, `_handle_feedback_loop`) move; generic event lifecycle stays |
| 29 | `core/ui/panels.py` | PURE-PLUGIN | ~265 (whole) | medium | All panels (gather/analyst/evaluator/score/verify/result) are IP-shaped. Imports `AnalysisResult/EvaluatorResult/PSMResult/SynthesisResult` from `core.state`. `core/ui/agentic_ui.py emit_pipeline_*` helpers likely also relocate |

### 3.3 Cluster aggregates

| Cluster | Files | LOC moved |
|---------|-------|-----------|
| A — CLI (`core/cli/*`) | 8 | ~1,710 |
| B — Tools + MCP (`core/tools/*`, `core/mcp_server.py`, `core/mcp/signal_adapter.py`) | 5 | ~960 |
| C — Runtime/Lifecycle/Agent/State (`core/{graph,runtime,state}.py`, `core/lifecycle/*`, `core/agent/*`) | 8 | ~975 |
| D — Domain/Verify/Skills/Memory/UI/Prompts (`core/domains/*`, `core/verification/calibration.py`, `core/skills/reports.py`, `core/llm/prompts/axes.py`, `core/memory/organization.py`, `core/ui/*`) | 8 | ~1,905 |
| **Total** | **29** | **~5,550** |

---

## 4. The architectural surprises (worth flagging individually)

1. **`core/graph.py:build_graph()` topology is hardcoded to game_ip.** This is the central finding. The function names every node (`router`, `signals`, `analyst`, `evaluator`, `scoring`, `skip_check`, `verification`, `synthesizer`, `gather`), wires the Send-API fanout based on `_analyst_type`/`_evaluator_type`, hardcodes the rights_risk verification step, and embeds 14-axis schema knowledge in `_make_degraded_result`. Generic LangGraph wiring exists (compile, hooks, timeout) but the *topology* is game_ip-shaped. A REODE fork reuses ~30% of `core/graph.py` and rebuilds `build_graph` from scratch.

2. **`core/state.py` is a contract violation.** Docstring claims "Domain layer: pure data models with no infrastructure dependencies" but the data models *are* the domain. `GeodeState` TypedDict has no generic counterpart. The `EvaluatorResult.validate_axes` validator hard-imports `core.llm.prompts.axes` to enforce 14-axis names — runtime invariant a non-IP domain cannot satisfy.

3. **`core/llm/prompts/axes.py` does eager IP-YAML loading at import time** (L19). Any `import core.llm.prompts.axes` in a non-game-IP context fails immediately. The file pretends to be infra but is a side-effecting IP loader. Worst latent coupling; **highest priority to fix** because it gates "can REODE even import core/?".

4. **`core/cli/pipeline_executor.py` is 87% game_ip.** Filename suggests a generic LangGraph executor; on inspection it hardcodes 4 analysts, 3 evaluators, 7 named nodes, 6 specialized panel renderers, and `AnalysisResult`/`EvaluatorResult` payload shapes. Only `_progress_line`, `_handle_interrupt`, `_merge_event_output` (~125 LOC) are generic.

5. **`core/mcp/signal_adapter.py` is misnamed and misplaced.** Reads as MCP framework infra; is in fact a thin fixture-to-game_ip wrapper for Steam/YouTube/Reddit signals. Wrong directory.

6. **`core/skills/reports.py` is misfiled.** It's not a "skill" — it's the IP report generator. ~1,100 LOC. The `core/skills/` namespace presumably should host generic CLI skill primitives (`SkillRegistry`, `SkillLoader`); putting `ReportGenerator` there is a taxonomy bug.

7. **`core/ui/event_renderer.py` has a hidden lazy plugin import** inside `_handle_pipeline_evaluation` (L567): `from plugins.game_ip.scoring_constants import score_ansi_color`. Easy to miss with a top-of-file grep.

8. **`core/agent/worker.py` is the gold standard for domain-free infra.** Claude-Code-style isolated subprocess worker. The `domain` field is opaque, `_run_agentic` runs whatever prompt it receives through a generic AgenticLoop. No game_ip vocabulary anywhere. Use as the reference shape for the rest of `core/`.

9. **`core/lifecycle/automation.py` is already cleaned.** Comment at L91-96 acknowledges "Predefined automations are domain-specific templates (game_ip). Registration is skipped — users can enable predefined templates via /schedule enable when a domain plugin provides the callback wiring." Someone has done the domain extraction here. Model for the rest of the cluster.

10. **`MonoLake*` is a naming false-positive.** `MonoLakeOrganizationMemory` reads as a game_ip leak by name (MonoLake is the IP-vertical data layer). It is in fact the only OrgMemory implementation and is consumed by generic `cmd_context` / `propagate_to_thread`. Rename in a separate cleanup PR — don't bundle with this audit's actions. Similarly: `tier` in `cmd_login` (commands.py L2097, L2240-2256) refers to GLM Coding Plan **subscription tiers**, not game_ip's S/A/B tiers. Easy to false-positive on if grepping `tier` blindly.

---

## 5. DomainPort v2 — the contract this audit implies

To make MIXED files cleanly splittable, `core/domains/port.py` needs to expose more than the current 17 evaluation-shaped methods. The audit findings imply the following additions:

| New method / accessor | Why |
|------------------------|-----|
| `get_state_class() -> type[TypedDict]` | So `core/graph.py` can compile a StateGraph parametrized over the domain's state shape (replaces hardcoded `GeodeState`) |
| `build_graph(state_class, hooks, ...) -> StateGraph` | So topology is plugin-supplied (replaces hardcoded `core/graph.py:build_graph`) |
| `get_pipeline_descriptor() -> PipelineDescriptor` | `step_labels`, `expected_step_counts`, `panel_set`, `state_key_lists` (drives `pipeline_executor.py` UI state machine) |
| `register_event_handlers(renderer)` | Plugin-side handlers register into `core/ui/event_renderer.py` (replaces lazy plugin import in `_handle_pipeline_evaluation`) |
| `register_tool_handlers(registry)` | Plugin contributes its tool handler bundle (replaces hardcoded `_build_analysis_handlers`) |
| `register_slash_commands(map)` | Plugin contributes `/analyze`/`/run`/`/list`/`/search` etc. (replaces hardcoded `COMMAND_MAP`) |
| `register_typer_commands(app)` | Plugin contributes Typer CLI subcommands (replaces hardcoded `analyze`/`report`/`search`/`list`/`batch` Typer commands) |
| `register_mcp_tools(server)` | Plugin contributes MCP tools to `core/mcp_server.py` |
| `wire_context_assembler(assembler)` | Plugin-side hook for `core/lifecycle/bootstrap.py` (replaces hardcoded `from plugins.game_ip.nodes.router import set_context_assembler`) |
| `build_task_graph(memory, subject_id) -> TaskGraph` | Replaces `create_geode_task_graph(ip_name)` in `core/lifecycle/bootstrap.py:build_task_graph` |
| `build_signal_adapter(...) -> SignalAdapter` | Replaces hardcoded `core/lifecycle/adapters.py:build_signal_adapter` |
| `compose_system_prompt_static(model) -> str` | Plugin supplies the IP-router-flavored prefix; core composes G1-G4 + dynamic suffix |
| `get_evaluator_axes() / get_valid_axes_map() / get_analyst_specific()` | Already half-wired in `core/llm/prompts/axes.py:get_valid_axes_map()` — make it the SOLE path |

### 5.1 Pipeline descriptor shape (concrete)

```python
@dataclass
class PipelineDescriptor:
    step_labels: dict[str, str]                      # "analyst" → "분석가"
    expected_step_counts: dict[str, int]             # {"analyst": 4, "evaluator": 3}
    panel_set: PanelSet                              # bundle of analyst/evaluator/score/verify/result render fns
    state_list_keys: set[str]                        # which state keys are merge-list (analyses, evaluations)
    rerunnable_nodes: frozenset[str]                 # which nodes /rerun_node will accept
    completion_event_set: frozenset[HookEvent]       # ANALYST_COMPLETE, EVALUATOR_COMPLETE, SCORING_COMPLETE
```

### 5.2 v1 → v2 migration shape

The current `DomainPort` Protocol stays valid for evaluation-shaped domains (game_ip). v2 additions are mostly **structural extensions** rather than method renames. Backward compatibility: keep v1 methods; v2 plugins implement the new ones. `core/` consumers prefer v2 methods if available, fall back to v1 when not. Migration of `plugins/game_ip/adapter.py` to fully implement v2 happens in step 7-8 (state + graph extraction) since those are the methods that need plugin-side counterparts.

---

## 6. Sequenced refactor plan (8 steps, 8 PRs)

Lowest-risk first → highest-risk last. Each step is sized to fit one PR.

| # | PR scope | LOC change | Risk | Unblocks |
|---|----------|-----------|------|----------|
| **1** | **DomainPort v2 scaffold + axes.py defusing.** Add v2 method stubs to `DomainPort` + `GameIPDomain`. **Move eager YAML load out of `core/llm/prompts/axes.py`** to `plugins/game_ip/axes.py`. Replace hardcoded `load_domain_adapter("game_ip")` in `core/cli/bootstrap.py` and `core/cli/__init__.py:_build_runtime_for_serve` with `settings.default_domain` (None default). Empty `_BUILTIN_DOMAINS` in `core/domains/loader.py`; plugin self-registers via `__init__.py` import-time hook. | ~120 | low | Everything else (eager-import breakage gone; config-driven domain wiring) |
| **2** | **PURE-PLUGIN whole-file moves (low-risk batch).** Move `core/cli/ip_names.py`, `core/cli/search.py`, `core/cli/batch.py`, `core/mcp/signal_adapter.py`, `core/tools/data_tools.py:QueryMonoLakeTool` → `plugins/game_ip/`. Update <10 import sites each. Keep `CortexAnalystTool`, `CortexSearchTool` in `core/tools/data_tools.py` (rename file to `core/tools/cortex.py`). | ~565 | low | step 4 |
| **3** | **Lifecycle & system_prompt seam.** Replace `core/lifecycle/bootstrap.py:528-530` plugin reach with `domain.wire_context_assembler(assembler)`. Replace `create_geode_task_graph` with `domain.build_task_graph()`. Move `build_signal_adapter` from `core/lifecycle/adapters.py` to `plugins/game_ip/wiring.py`; convert `build_plugins()` to iterate over a domain-port list. Move `_NOTABLE_IPS` + IP example fixture loading from `core/agent/system_prompt.py` to `plugins/game_ip/prompt.py`; expose `compose_system_prompt(static_template_resolver, model)` in core. Rename `core/lifecycle/automation.py:wire_automation_hooks` `ip_name` → `subject_id` (cosmetic). | ~140 | low | step 5 |
| **4** | **CLI commands / tool_handlers extraction.** Move `cmd_list`, `cmd_generate`, `cmd_batch` and game_ip slashes from `core/cli/commands.py` to `plugins/game_ip/cli_commands.py`. Move `_build_analysis_handlers` (180 LOC), 4 signal entries from `_DELEGATED_TOOLS`, `handle_generate_data` from `core/cli/tool_handlers.py` to `plugins/game_ip/tool_handlers.py`. Promote `COMMAND_MAP` to a `SlashCommandRegistry` extended by domain. Parameterize `handle_rerun_node` allowlist via `domain.pipeline.rerunnable_nodes`. | ~370 | medium | step 7 |
| **5** | **Tools cluster split.** Move `core/tools/analysis.py` (whole) and `core/tools/signal_tools.py` IP-half (5 signal tools + `_load_signal`) to `plugins/game_ip/tools/`. Extract `_parse_mcp_content`, `_try_mcp_signal` to new `core/mcp/utils.py`. Move `WebSearchTool` to `core/tools/web_search.py`. Update `core/tools/tool_schemas.json` split (core-generic vs plugin-specific). | ~700 | medium | step 6 |
| **6** | **MCP server plugin-registration contract.** Refactor `core/mcp_server.py` to accept plugin-contributed tools/resources. Move `analyze_ip`, `quick_score`, `get_ip_signals`, `list_fixtures`, `geode://fixtures` to `plugins/game_ip/mcp_tools.py`. Split `core/tools/mcp_tools.json`. Define `MCPToolPlugin` protocol or use the `register_mcp_tools(server)` DomainPort method. | ~120 | medium-high | step 8 |
| **7** | **State.py + reports.py + panels.py extraction.** Move IP-shaped Pydantic models from `core/state.py` to `plugins/game_ip/state.py`: `RightsStatus`, `LicenseInfo`, `RightsRiskResult`, `CauseLiteral`, `ActionLiteral`, `AnalysisResult`, `EvaluatorResult`, `PSMResult`, `SynthesisResult`, `AxisCalibration`, `EvaluatorCalibration`, `CalibrationResult`, `GeodeState` TypedDict (rename → `GameIPState`). Define thin `BaseState` TypedDict in `core/state.py` (errors/iteration/run_id/dry_run + reducers only). Move `core/skills/reports.py` (whole) + `core/skills/templates/report*` to `plugins/game_ip/reports/`. Move `core/ui/panels.py` (whole) + dependent `core/ui/agentic_ui.py:emit_pipeline_*` to `plugins/game_ip/ui/`. Subclass `EventRenderer` → `GameIPEventRenderer` in `plugins/game_ip/ui/event_renderer.py` (overrides `_handle_pipeline_*` handlers). Remove lazy plugin import in `core/ui/event_renderer.py:567`. Refactor `core/verification/calibration.py` into generic skeleton + plugin-side weights/golden_set. **Every node type annotation, every test fixture using `GeodeState` updates.** | ~1,800 + tests | **HIGH** | step 8 |
| **8** | **Graph topology extraction (the big one).** Move `core/graph.py:build_graph()` body to `plugins/game_ip/graph.py:build_game_ip_graph()`. Move `_NODE_COMPLETION_EVENTS`, `_make_degraded_result`, `_skip_check_node`, `_route_after_skip_check`, `_verification_node`, `_gather_node`, `_register_drift_scan_hook`, `core.state` model whitelist for serializer. Keep `_make_hooked_node`, `compile_graph` (parameterized over `build_graph` callable injected by domain), `invoke_with_timeout`, `PipelineTimeoutError` in `core/graph.py` (or rename `core/pipeline_runner.py`). Move `core/cli/pipeline_executor.py` body (87% game_ip) to `plugins/game_ip/pipeline_executor.py`; keep `_progress_line`/`_handle_interrupt`/`_merge_event_output` in `core/cli/pipeline_runtime.py`. The `JsonPlusSerializer` `allowed_modules` list becomes domain-supplied. **REODE fork is feasible after this PR merges.** | ~1,300 | **HIGH** | REODE |

### 6.1 Cross-cutting verification gate

Every step verified by:

```bash
uv run ruff check core/ tests/ plugins/    # 0 errors
uv run mypy core/ plugins/                  # 0 errors
uv run pytest tests/ -m "not live"          # 4380+ pass
uv run geode analyze "Cowboy Bebop" --dry-run   # A (68.4) — anchor unchanged
```

### 6.2 The Codex test (truth gate)

After step 8, the truth gate is:

```bash
# Temporarily move plugins/ aside
mv plugins plugins.bak
uv run pytest tests/test_core_only/   # Should pass: zero plugin dependency
mv plugins.bak plugins
```

If `core/` still imports from `plugins/` after step 8, the cut is fake. This is the gate that distinguishes architectural split from cosmetic relocation.

---

## 7. Workload estimate

| Dimension | Estimate |
|-----------|----------|
| LOC moved out of `core/` | ~5,550 |
| LOC retained as generic in `core/` | unchanged + ~300 LOC of new abstractions (DomainPort v2 methods, PipelineDescriptor, registries) |
| PRs | 8 (per the sequenced plan above) |
| Calendar time | 2-4 weeks of focused work, 1-2 PRs/week |
| Test impact | 4380+ tests must continue passing. Step 7 likely touches >100 test files (every test using `GeodeState`). Step 8 touches LangGraph topology tests + the E2E anchor `analyze "Cowboy Bebop"` |
| Risk concentration | Steps 7-8 carry ~70% of total risk. Steps 1-6 are sequencing/hygiene |

---

## 8. Open questions

1. **Hook ownership**: HookSystem (82 events) stays as closed-kernel event bus (Claude Code style), or becomes domain-extensible (OpenClaw style)? Decide before second non-game-IP vertical lands.
2. **DomainPort v2 surface**: Some methods like `get_cause_values`, `get_tier_thresholds`, `get_cause_to_action` assume an evaluation-shaped domain. A REODE migration agent (ASSESS → PLAN → TRANSFORM) doesn't have causes/tiers. Does v2 mark these `Optional[…]`, or does it split into `EvaluationDomainPort(DomainPort)` and `TaskDomainPort(DomainPort)`?
3. **Step ordering**: Steps 1-6 are sequenced low-risk → medium-risk and unblock step 7-8. But step 7 is single-PR-large (~1,800 LOC + tests). Should step 7 split into 7a (state.py + reports.py + panels.py) and 7b (calibration.py + event_renderer.py)? Trade-off: more PRs (more review overhead) vs. one giant PR (atomic but reviewer-fatigue).
4. **Migration discipline**: Do we add the Codex truth gate (`mv plugins plugins.bak && pytest`) to CI as a permanent ratchet? Once `core/` is plugin-free, the cheapest way to keep it that way is automated.

---

## 9. Recommendation

Adopt **Claude Code-style two-layer split**, with Codex CLI's crate-per-concern discipline applied internally to `core/`:

- **Closed-style `core/`**: LangGraph runtime, LLM router, hooks, agent loop, MCP framework, sandbox, lifecycle, generic verification framework (G1-G4 logic, no IP-specific weights), generic skills registry, generic memory framework. No `plugins/*` imports anywhere.
- **Plugin-discovered `plugins/<vertical>/`**: state schema, pipeline graph topology, scoring weights, rubric axes, signal scrapers, fixtures, reports, panels, slash commands, MCP tools, system-prompt static prefix, calibration golden set.

Path forward (next-step decision needed from user):

| Option | Description | Output of this audit cycle |
|--------|-------------|----------------------------|
| **(a) Audit → user reviews → done.** | This PR ships only the design doc. Implementation steps 1-8 land in subsequent cycles. | This file, committed to `develop` via PR. No code change. |
| **(b) Audit → step 1 in same PR.** | Bundle DomainPort v2 stubs + axes.py defusing + bootstrap config indirection (~120 LOC) with the design doc. Highest-leverage low-risk first move. | Doc + step-1 PR. Eager-import breakage gone in one cycle. |
| **(c) Audit → steps 1-3 in same cycle (3 PRs).** | Aggressive cleanup. Doc + 3 small PRs. Leaves cluster A-D MIXED items for step 4-8 PRs to follow. | Doc + ~825 LOC across 3 PRs. |

Recommend **(a)** for this cycle — keep the audit standalone so the architecture decisions get reviewed in isolation, then schedule step 1 as the first implementation PR after sign-off. The audit is the contract; step PRs are the execution.

---

## Appendix A — Per-cluster raw audit reports

The full per-file findings from the 4 cluster audits are preserved in this commit's history. Cluster summaries are inlined in §3.2; for symbol-level line-number citations, see the relevant cluster agent's output (referenced by PR description on the audit branch).

## Appendix B — Frontier source citations

- Anthropic: Claude Code repository — https://github.com/anthropics/claude-code
- Claude Code plugins README — https://github.com/anthropics/claude-code/blob/main/plugins/README.md
- Claude Code skills docs — https://code.claude.com/docs/en/skills
- OpenAI Codex repository — https://github.com/openai/codex
- Codex `core-skills` crate — https://github.com/openai/codex/tree/main/codex-rs/core-skills
- Codex Configuration Reference — https://developers.openai.com/codex/config-reference
- OpenClaw repository — https://github.com/openclaw/openclaw
- OpenClaw Plugins docs — https://docs.openclaw.ai/tools/plugin
- karpathy/autoresearch — https://github.com/karpathy/autoresearch
- autoresearch program.md — https://github.com/karpathy/autoresearch/blob/master/program.md
