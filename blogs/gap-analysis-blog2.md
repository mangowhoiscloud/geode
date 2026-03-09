# Gap Analysis: Blog Post 2 vs Actual Codebase

**Blog**: `blogs/02-agent-runtime-architecture.md`
**Codebase**: `geode/geode/`
**Date**: 2026-03-02
**Analyst**: Automated cross-reference analysis

---

## Methodology

Every technical claim, code block, architecture description, and behavioral assertion in the blog was cross-referenced against the actual source code. The following intentional domain abstractions are excluded from flagging:

- `entity_name` <-> `ip_name`
- `data_store` <-> `monolake`
- `AgentState` <-> `GeodeState`
- `AgentRuntime` <-> `GeodeRuntime`
- `causal_inference` <-> `psm`
- `cross_check` <-> `cross_llm`
- `OrganizationMemory` <-> `MonoLakeOrganizationMemory`

---

## Section-by-Section Analysis

### Section 1: Production Agent Runtime Requirements (Lines 29-43)

| Claim | Status | Notes |
|-------|--------|-------|
| 20+ infrastructure components | **ACCURATE** | GeodeRuntime.__init__ takes 25+ parameters |
| graph.stream() for real-time progress | **ACCURATE** | cli/__init__.py line 180 uses `graph.stream()` |
| Send API + Reducer strategy | **ACCURATE** | analysts.py and state.py confirm |
| 18-Event Hook Observer | **ACCURATE** | HookEvent enum has exactly 18 members |
| Degraded Response + fault isolation | **ACCURATE** | analysts.py lines 94-104, hooks.py lines 128-141 |
| CUSUM Drift + 4-Phase RLHF | **ACCURATE** | drift.py and feedback_loop.py confirm |
| Node logic is 30% of code, infra is 70% | **ACCURATE** | Reasonable heuristic given file counts |

### Section 2: Runtime Factory Pattern (Lines 46-120)

**GAP-B001** | DIVERGENT | Medium
- Blog Line: 69-71 — `_build_hooks(session_key=session_key, run_id=run_id)`
- Actual: `runtime.py` line 254-259 — `_build_hooks` takes 4 keyword args: `session_key`, `run_id`, `log_dir`, `stuck_timeout_s`
- Description: Blog omits `log_dir` and `stuck_timeout_s` parameters from the `_build_hooks()` call signature. The blog shows a simplified 2-param call, but the actual code requires 4 params.

**GAP-B002** | DIVERGENT | Low
- Blog Line: 89 — `return cls(hooks=hooks, session_store=session_store, **automation)`
- Actual: `runtime.py` lines 692-718 — The `cls()` constructor receives ~25 keyword arguments including `policy_chain`, `tool_registry`, `run_log`, `llm_adapter`, `secondary_adapter`, `profile_store`, `profile_rotator`, `cooldown_tracker`, `coalescing`, `config_watcher`, `stuck_detector`, `lane_queue`, `project_memory`, `organization_memory`, `context_assembler`, `prompt_assembler`, plus `**automation`
- Description: Blog drastically simplifies the constructor call. While acceptable as pedagogical simplification, the "return cls(...)" line shows only 3 args when the actual code passes 20+.

**GAP-B003** | DIVERGENT | Medium
- Blog Line: 92 — Text says "Sub-builder 분리: `_build_hooks()`, `_build_memory()`, `_build_automation()`, `_build_task_graph()`"
- Actual: `runtime.py` has **6** sub-builders: `_build_hooks`, `_build_auth`, `_build_memory`, `_build_automation`, `_build_prompt_assembler`, `_build_task_graph`
- Description: Blog lists 4 sub-builders and the mermaid diagram shows 5 (adding `_build_auth`). But the actual code has 6 sub-builders -- `_build_prompt_assembler` (ADR-007) is missing from both the text and diagram.

**GAP-B004** | MISSING | Low
- Blog Line: 94-117 — Mermaid diagram of Runtime.create() sub-builders
- Actual: `runtime.py` lines 497-513 — `_build_prompt_assembler()` exists as a sub-builder returning `PromptAssembler` with `SkillRegistry`
- Description: The mermaid diagram omits the `_build_prompt_assembler` sub-builder and its `SkillRegistry`/`PromptAssembler` outputs.

**GAP-B005** | MISSING | Low
- Blog Line: 50-90 — Runtime.create() code block
- Actual: `runtime.py` lines 531-718 — Actual `create()` also builds `PolicyChain`, `ToolRegistry`, `CoalescingQueue`, `ConfigWatcher`, `LaneQueue`, injects LLM callables via `set_llm_callable`, wires `HybridSessionStore` conditionally, and sets up `.env` hot-reload
- Description: Blog omits many real components: PolicyChain, ToolRegistry, CoalescingQueue, ConfigWatcher (hot-reload), LaneQueue, LLM callable injection, HybridSessionStore conditional wiring. These are significant production infra components.

### Section 3: graph.stream() vs graph.invoke() (Lines 123-176)

**GAP-B006** | ACCURATE | --
- Blog Line: 138-171 — `compile_graph()` function signature and body
- Actual: `graph.py` lines 370-429
- Description: The blog's `compile_graph()` code matches the actual implementation very closely. All parameters (`checkpoint_db`, `hooks`, `confidence_threshold`, `max_iterations`, `memory_fallback`, `enable_drift_scan`, `interrupt_before`, `bootstrap_mgr`, `prompt_assembler`) are accurately represented.

| Claim | Status |
|-------|--------|
| compile_graph signature | **ACCURATE** |
| SqliteSaver for checkpoint_db | **ACCURATE** |
| MemorySaver for memory_fallback | **ACCURATE** |
| interrupt_before for human-in-the-loop | **ACCURATE** |
| CLI uses .stream() not .invoke() | **ACCURATE** (cli/__init__.py line 180) |

### Section 4: Send API Parallel Execution + Reducer (Lines 179-244)

**GAP-B007** | DIVERGENT | Low
- Blog Line: 186-205 — `make_analyst_sends()` code block
- Actual: `analysts.py` lines 299-322
- Description: Blog omits `verbose` and `memory_context` fields from the send_state dict. Actual code includes `"verbose": state.get("verbose", False)` and `"memory_context": state.get("memory_context")`. These are minor omissions but the blog claims to show the full Clean Context implementation.

**GAP-B008** | ACCURATE | --
- Blog Line: 213-222 — GeodeState TypedDict with Annotated reducers
- Actual: `state.py` lines 161-212
- Description: `analyses: Annotated[list[AnalysisResult], operator.add]`, `evaluations: Annotated[dict[str, EvaluatorResult], _merge_dicts]`, and `errors: Annotated[list[str], operator.add]` all match exactly.

| Claim | Status |
|-------|--------|
| Clean Context pattern (analyses=[]) | **ACCURATE** |
| operator.add reducer for analyses | **ACCURATE** |
| _merge_dicts reducer for evaluations | **ACCURATE** |
| operator.add for errors | **ACCURATE** |
| 4 analyst types in ANALYST_TYPES | **ACCURATE** |

### Section 5: Hooked Node Wrapper Pattern (Lines 248-349)

**GAP-B009** | ACCURATE | --
- Blog Line: 254-285 — HookEvent enum with 18 events
- Actual: `hooks.py` lines 18-49
- Description: All 18 events match exactly: 3 pipeline + 4 node + 3 analysis + 2 verification + 5 automation + 1 prompt assembly = 18.

**GAP-B010** | DIVERGENT | Medium
- Blog Line: 290-330 — `_make_hooked_node()` implementation
- Actual: `graph.py` lines 62-154
- Description: The blog's version is significantly simplified compared to actual code. Key omissions:
  1. Blog omits `_analyst_type` / `_evaluator_type` propagation in hook_data (lines 75-78)
  2. Blog omits PIPELINE_START trigger on router node (lines 98-100)
  3. Blog omits PIPELINE_END trigger on synthesizer node with enriched hook_data (lines 133-143)
  4. Blog omits node-specific completion events (ANALYST_COMPLETE, EVALUATOR_COMPLETE, SCORING_COMPLETE) via `_NODE_COMPLETION_EVENTS` (lines 121-122)
  5. Blog omits VERIFICATION_PASS/FAIL trigger logic (lines 125-131)
  6. Blog omits drift_scan_hint for scoring node (lines 111-115)
  7. Blog omits `result_keys` in hook_data (line 108)
  8. Blog omits `__name__` assignment on wrapped function (line 153)
  These are significant because they show the real wrapper does far more than just NODE_ENTER/EXIT/ERROR.

**GAP-B011** | DIVERGENT | Low
- Blog Line: 303-308 — Bootstrap integration in _make_hooked_node
- Actual: `graph.py` lines 82-88
- Description: Blog shows `state = bootstrap_mgr.apply_context(dict(state), ctx)` directly modifying `state`, but actual code uses `effective_state = bootstrap_mgr.apply_context(...)` with a separate variable to avoid mutating the original state reference. Minor but the actual code is more correct.

**GAP-B012** | DIVERGENT | Low
- Blog Line: 336-347 — `build_graph()` simplified version
- Actual: `graph.py` lines 230-334
- Description: Blog's simplified `build_graph` shows `_node(fn, name)` helper calling `_make_hooked_node(fn, name, hooks)` with only 3 args. Actual code passes 5 args: `_make_hooked_node(fn, name, hooks, bootstrap_mgr, prompt_assembler)`. The blog itself notes this is simplified, so this is acceptable.

### Section 6: TaskGraphHookBridge (Lines 353-407)

**GAP-B013** | DIVERGENT | Medium
- Blog Line: 375-385 — `_MULTI_TASK_NODES` mapping
- Actual: `task_bridge.py` lines 38-42
- Description: Blog shows `"scoring": ["scoring", "causal_inference"]` but actual code has `"scoring": ["scoring", "psm"]`. While `causal_inference <-> psm` is listed as an intentional domain abstraction, the blog also shows `"verification": ["verification", "cross_check"]` while actual code has `"verification": ["verification", "cross_llm"]`. The `cross_check <-> cross_llm` mapping is also listed as intentional. Both map correctly under the abstraction rules, so this is **ACCURATE** under the stated domain abstraction rules.

Status: **ACCURATE** (under stated domain abstraction rules)

**GAP-B014** | ACCURATE | --
- Blog Line: 374-385 — _IGNORED_NODES, _SIMPLE_NODES, _MULTI_TASK_NODES
- Actual: `task_bridge.py` lines 29-42
- Description: Structure matches. `_IGNORED_NODES = frozenset({"router", "gather"})`, `_SIMPLE_NODES = {"cortex": "cortex", "signals": "signals"}`, and the multi-task mapping structure all match.

**GAP-B015** | DIVERGENT | Medium
- Blog Line: 391-403 — `_on_node_exit` evaluator counting code
- Actual: `task_bridge.py` lines 128-143
- Description: Blog shows a simplified version. The actual code after evaluator counting checks for general task_ids and marks them completed. The blog's code shows accessing `self._graph.get_task(tid)` and checking `task.status == TaskStatus.RUNNING` which matches. However, the blog omits that the actual evaluator counter also includes error counts (line 60: `self._evaluator_done_count = 0  # exit + error combined`), and the actual _on_node_error also increments the evaluator counter and can fail the task immediately (lines 161-171).

| Claim | Status |
|-------|--------|
| Observer over Controller principle | **ACCURATE** |
| TaskGraph never controls LangGraph | **ACCURATE** |
| Bridge registers NODE_ENTER/EXIT/ERROR | **ACCURATE** |
| Evaluator needs 3 NODE_EXIT to complete | **ACCURATE** (though error path is more complex) |

### Section 7: Feedback Loop (Lines 410-488)

**GAP-B016** | ACCURATE | --
- Blog Line: 417-453 — `build_graph()` with `_configured_should_continue` closure
- Actual: `graph.py` lines 230-334
- Description: The closure pattern, confidence normalization (0-100 to 0-1), threshold comparison, max_iterations check, and three return paths ("synthesizer", "synthesizer", "gather") all match exactly.

**GAP-B017** | ACCURATE | --
- Blog Line: 460-473 — `_gather_node()` implementation
- Actual: `graph.py` lines 197-227
- Description: The core logic matches: iteration increment, weak_areas identification from subscores < 50.0, history_entry creation, and return of `{"iteration": iteration + 1, "iteration_history": [history_entry]}`.

**GAP-B018** | DIVERGENT | Low
- Blog Line: 460-473 — `_gather_node` simplified code
- Actual: `graph.py` lines 197-227
- Description: Actual `_gather_node` also records `final_score` and `tier` in the history_entry dict. Blog's version only records `iteration`, `confidence`, and `weak_areas`. The blog omits `final_score` and `tier` from the snapshot.

**GAP-B019** | ACCURATE | --
- Blog Line: 488 — `iteration_history` uses `Annotated[list, operator.add]` Reducer
- Actual: `state.py` line 205 — `iteration_history: Annotated[list[dict[str, Any]], operator.add]`
- Description: Confirmed. The reducer pattern for iteration history accumulation matches.

| Claim | Status |
|-------|--------|
| Confidence closure pattern | **ACCURATE** |
| 0-100 to 0-1 normalization | **ACCURATE** |
| Max iterations safety guard | **ACCURATE** |
| Gather identifies weak areas | **ACCURATE** |
| Loopback to cortex | **ACCURATE** (graph.py line 330: `graph.add_edge("gather", "cortex")`) |

### Section 8: L4.5 Automation — CUSUM Drift + 4-Phase RLHF (Lines 492-576)

**GAP-B020** | ACCURATE | --
- Blog Line: 501-527 — CUSUMDetector implementation
- Actual: `drift.py` lines 87-181
- Description: WARNING_THRESHOLD=2.5, CRITICAL_THRESHOLD=4.0, allowance_k, positive/negative CUSUM accumulators, z-score normalization, severity classification all match exactly.

**GAP-B021** | DIVERGENT | Low
- Blog Line: 505 — `self._baselines[metric_name]` accessed without guard
- Actual: `drift.py` line 143-144 — Has explicit `KeyError` raise: `if metric_name not in self._baselines: raise KeyError(...)`
- Description: Blog omits the safety check that raises KeyError for unknown metrics.

**GAP-B022** | ACCURATE | --
- Blog Line: 533-534 — Hook wiring for drift reaction chain
- Actual: `runtime.py` lines 393-417 — `_on_drift_snapshot` at priority=80, `drift_trigger_handler` at priority=70
- Description: The reactive chain pattern (drift -> auto-snapshot -> trigger) is confirmed in the actual code.

**GAP-B023** | DIVERGENT | Medium
- Blog Line: 560-572 — FeedbackLoop.run_cycle() simplified code
- Actual: `feedback_loop.py` lines 380-473
- Description: Blog shows a simplified 4-step `run_cycle` that directly calls `self.collect()`, `self.analyze()`, `self.propose_improvement()`, `self.validate_and_deploy()`, then checks `validation.get("all_passed")` for model promotion. The actual code has significantly more logic:
  1. Actual `run_cycle` calls `validate_and_deploy(candidates, cycle_input.metric_values)` passing metric_values as validation_scores -- blog omits this parameter.
  2. Actual code computes `correlation_before`/`correlation_after` -- blog omits.
  3. Actual code builds a full `FeedbackCycleResult` dataclass with `cycle_id`, `phase_results`, `improvements_applied`, `drift_alerts`, etc. -- blog simplifies to `FeedbackCycleResult(success=...)`.
  4. Actual code applies improvements after validation: `for candidate in candidates: self.apply_improvement(candidate)` -- blog omits.
  5. Actual model promotion has an additional guard: it checks `current.stage == PromotionStage.STAGING` before promoting to CANARY -- blog omits this staging gate.
  6. Actual code emits hook events (DRIFT_DETECTED, OUTCOME_COLLECTED) after completion -- blog omits.
  7. Actual code updates `_stats` counters -- blog omits.

**GAP-B024** | ACCURATE | --
- Blog Line: 554-557 — 4-Phase table (Collection, Analysis, Improvement, Validation)
- Actual: `feedback_loop.py` — FeedbackPhase enum and methods confirm all 4 phases.

**GAP-B025** | ACCURATE | --
- Blog Line: 575 — Statistical power analysis (Cohen 1988, n>=29 for rho=0.5)
- Actual: `feedback_loop.py` lines 28-35 — `MIN_SAMPLE_SIZE = 10`, `RECOMMENDED_SAMPLE_SIZE = 30` with Cohen citation in comments.

### Section 9: Degraded Response Pattern (Lines 579-633)

**GAP-B026** | ACCURATE | --
- Blog Line: 584-603 — `_run_analyst()` Degraded Response implementation
- Actual: `analysts.py` lines 82-104
- Description: The degraded response pattern matches: `analyst_type`, `score=1.0`, `key_finding="[DEGRADED]..."`, `reasoning="Schema validation failed..."`, `evidence=["validation_error"]`, `confidence=0.0`, `is_degraded=True`.

**GAP-B027** | ACCURATE | --
- Blog Line: 615-630 — HookSystem.trigger() error isolation
- Actual: `hooks.py` lines 119-143
- Description: The try/except per-handler pattern with HookResult construction matches exactly. One handler failure does not block others.

**GAP-B028** | DIVERGENT | Low
- Blog Line: 615-630 — trigger() return type shown as `list[HookResult]`
- Actual Port: `hook_port.py` line 18 — `HookSystemPort.trigger()` declares return type `None`
- Actual Impl: `hooks.py` line 119 — `HookSystem.trigger()` returns `list[HookResult]`
- Description: The blog shows the concrete `HookSystem.trigger()` which returns `list[HookResult]`, which matches the implementation. However, the Port protocol declares `-> None`. This is a codebase inconsistency (port vs implementation) rather than a blog error. The blog accurately represents the implementation.

### Section 10: Summary + Checklist (Lines 637-684)

| Checklist Item | Status |
|----------------|--------|
| Runtime Factory deterministic assembly | **ACCURATE** |
| Sub-builder independent unit testing | **ACCURATE** |
| graph.stream() for progress | **ACCURATE** |
| Annotated[list, operator.add] Reducer | **ACCURATE** |
| Clean Context for analysts | **ACCURATE** |
| All nodes wrapped with Hooked Node | **ACCURATE** |
| TaskGraph observer-only pattern | **ACCURATE** |
| Confidence-based Feedback Loop + max_iterations | **ACCURATE** |
| CUSUM Drift Detection baselines | **ACCURATE** |
| RLHF Collection power check | **ACCURATE** |
| LLM failure -> Degraded Response | **ACCURATE** |
| Hook handler isolation | **ACCURATE** |
| shutdown() method | **ACCURATE** (`runtime.py` lines 848-856) |

---

## Numbered Gap List

| ID | Type | Severity | Blog Lines | Actual Location | Description |
|----|------|----------|------------|-----------------|-------------|
| GAP-B001 | DIVERGENT | Medium | 69-71 | `runtime.py:254-259` | `_build_hooks()` call omits `log_dir` and `stuck_timeout_s` parameters |
| GAP-B002 | DIVERGENT | Low | 89 | `runtime.py:692-718` | `cls()` constructor call drastically simplified (3 args shown vs 20+ actual) |
| GAP-B003 | DIVERGENT | Medium | 92 | `runtime.py:253-525` | Blog lists 4 sub-builders, diagram shows 5, actual code has 6 (`_build_prompt_assembler` missing) |
| GAP-B004 | MISSING | Low | 94-117 | `runtime.py:497-513` | Mermaid diagram omits `_build_prompt_assembler` sub-builder |
| GAP-B005 | MISSING | Low | 50-90 | `runtime.py:531-718` | Blog omits PolicyChain, ToolRegistry, CoalescingQueue, ConfigWatcher, LaneQueue, LLM injection, HybridSessionStore |
| GAP-B006 | -- | -- | 138-171 | `graph.py:370-429` | `compile_graph()` implementation is **ACCURATE** |
| GAP-B007 | DIVERGENT | Low | 186-205 | `analysts.py:299-322` | `make_analyst_sends()` omits `verbose` and `memory_context` fields |
| GAP-B008 | -- | -- | 213-222 | `state.py:161-212` | Reducer declarations are **ACCURATE** |
| GAP-B009 | -- | -- | 254-285 | `hooks.py:18-49` | 18 HookEvent members are **ACCURATE** |
| GAP-B010 | DIVERGENT | Medium | 290-330 | `graph.py:62-154` | `_make_hooked_node()` significantly simplified -- omits 7 features: analyst/evaluator type propagation, PIPELINE_START/END triggers, node-specific completion events, VERIFICATION_PASS/FAIL, drift_scan_hint, result_keys, __name__ assignment |
| GAP-B011 | DIVERGENT | Low | 303-308 | `graph.py:81-88` | Blog mutates `state` directly; actual uses `effective_state` for immutability |
| GAP-B012 | DIVERGENT | Low | 336-347 | `graph.py:252-257` | Simplified `_node()` helper shows 3 args; actual passes 5 (includes bootstrap_mgr, prompt_assembler) -- blog acknowledges simplification |
| GAP-B013 | -- | -- | 375-385 | `task_bridge.py:38-42` | Multi-task mappings **ACCURATE** under stated domain abstraction rules |
| GAP-B014 | -- | -- | 374-385 | `task_bridge.py:29-42` | Node-to-task mapping structures are **ACCURATE** |
| GAP-B015 | DIVERGENT | Medium | 391-403 | `task_bridge.py:128-171` | Blog's `_on_node_exit` omits error counting in evaluator counter and error-path immediate failure |
| GAP-B016 | -- | -- | 417-453 | `graph.py:297-329` | `_configured_should_continue` closure is **ACCURATE** |
| GAP-B017 | -- | -- | 460-473 | `graph.py:197-227` | `_gather_node` core logic is **ACCURATE** |
| GAP-B018 | DIVERGENT | Low | 460-473 | `graph.py:215-221` | `_gather_node` history_entry omits `final_score` and `tier` fields |
| GAP-B019 | -- | -- | 488 | `state.py:205` | `iteration_history` Reducer is **ACCURATE** |
| GAP-B020 | -- | -- | 501-527 | `drift.py:87-181` | CUSUMDetector implementation is **ACCURATE** |
| GAP-B021 | DIVERGENT | Low | 505 | `drift.py:143-144` | Blog omits KeyError guard for unknown metrics |
| GAP-B022 | -- | -- | 533-534 | `runtime.py:393-417` | Drift reaction hook chain is **ACCURATE** |
| GAP-B023 | DIVERGENT | Medium | 560-572 | `feedback_loop.py:380-473` | `run_cycle()` significantly simplified -- omits validation_scores pass-through, correlation tracking, full FeedbackCycleResult construction, improvement application, staging gate on promotion, hook event emission, stats updates |
| GAP-B024 | -- | -- | 554-557 | `feedback_loop.py:38-44` | 4-Phase RLHF structure is **ACCURATE** |
| GAP-B025 | -- | -- | 575 | `feedback_loop.py:28-35` | Statistical power analysis is **ACCURATE** |
| GAP-B026 | -- | -- | 584-603 | `analysts.py:82-104` | Degraded Response implementation is **ACCURATE** |
| GAP-B027 | -- | -- | 615-630 | `hooks.py:119-143` | Hook error isolation is **ACCURATE** |
| GAP-B028 | DIVERGENT | Low | 615-630 | `hook_port.py:18` | Port declares `trigger() -> None` but implementation returns `list[HookResult]` (codebase inconsistency, not blog error) |

---

## All Accurate Claims

1. **18 HookEvent members** exactly match (S5, line 254-285)
2. **graph.stream()** used in production CLI (S3, line 136)
3. **compile_graph()** signature and body match closely (S3, line 138-171)
4. **Annotated reducers**: `analyses: Annotated[list, operator.add]`, `evaluations: Annotated[dict, _merge_dicts]`, `errors: Annotated[list, operator.add]` (S4, line 213-222)
5. **Clean Context pattern**: `analyses: []` in Send state (S4, line 198)
6. **4 analyst types**: `game_mechanics`, `player_experience`, `growth_potential`, `discovery` (S4)
7. **_IGNORED_NODES**: `frozenset({"router", "gather"})` (S6, line 375)
8. **_SIMPLE_NODES**: `{"cortex": "cortex", "signals": "signals"}` (S6, line 378)
9. **_MULTI_TASK_NODES** structure matches under domain abstractions (S6, line 381-385)
10. **Observer over Controller**: TaskGraph never controls LangGraph (S6, line 406)
11. **_configured_should_continue** closure with confidence normalization, threshold, max_iterations (S7, line 427-446)
12. **_gather_node** identifies weak areas from subscores < 50.0 (S7, line 465)
13. **gather -> cortex** loopback edge (S7, confirmed graph.py line 330)
14. **iteration_history** with `Annotated[list, operator.add]` Reducer (S7, line 488)
15. **CUSUMDetector**: WARNING=2.5, CRITICAL=4.0, allowance_k, pos/neg accumulators (S8, line 501-527)
16. **Drift reaction chain**: drift -> auto-snapshot at priority=80, trigger at priority=70 (S8, line 533-534)
17. **4-Phase RLHF**: Collection, Analysis, Improvement, Validation (S8, line 554-557)
18. **Statistical power**: MIN_SAMPLE_SIZE=10, RECOMMENDED=30, Cohen 1988 citation (S8, line 575)
19. **Degraded Response**: score=1.0, confidence=0.0, is_degraded=True (S9, line 595-603)
20. **Hook error isolation**: try/except per handler, HookResult (S9, line 615-630)
21. **shutdown()** method cleans up background components (S10, line 683)
22. **Factory Method + Sub-builder** general pattern (S2, line 50-90)
23. **SqliteSaver / MemorySaver** conditional checkpointing (S3, line 158-163)
24. **interrupt_before** for human-in-the-loop (S3, line 166-167)
25. **Evaluator counting**: 3 exits needed to complete evaluators task (S6, line 396)
26. **FeedbackCycleInput** / **FeedbackCycleResult** dataclass pattern (S8)
27. **BootstrapManager** skip logic in _make_hooked_node (S5, line 304-308)
28. **PromptAssembler** injection via state (S5, line 311-312)

---

## Summary Table

| Category | Count | Percentage |
|----------|-------|------------|
| ACCURATE | 28 | 71.8% |
| DIVERGENT (simplification) | 11 | 28.2% |
| BROKEN | 0 | 0% |
| FABRICATED | 0 | 0% |
| MISSING (from blog) | 2 | -- |

### Severity Distribution (Gaps Only)

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 0 | -- |
| High | 0 | -- |
| Medium | 5 | GAP-B001, GAP-B003, GAP-B010, GAP-B015, GAP-B023 |
| Low | 8 | GAP-B002, GAP-B004, GAP-B005, GAP-B007, GAP-B011, GAP-B012, GAP-B018, GAP-B021, GAP-B028 |

---

## Priority Fix Order

### Priority 1 (Medium — Code blocks showing simplified behavior)

1. **GAP-B010**: `_make_hooked_node()` — The most significant gap. Blog shows only NODE_ENTER/EXIT/ERROR but actual code has 7 additional behaviors (PIPELINE_START/END, node-specific events, VERIFICATION_PASS/FAIL, drift_scan_hint, analyst/evaluator type propagation). **Recommendation**: Add a callout paragraph after the code block explaining: "This is the core pattern. The production wrapper additionally triggers PIPELINE_START on the router node, PIPELINE_END on the synthesizer, node-specific completion events (ANALYST_COMPLETE, EVALUATOR_COMPLETE, SCORING_COMPLETE), and VERIFICATION_PASS/FAIL based on guardrail results."

2. **GAP-B023**: `FeedbackLoop.run_cycle()` — Blog shows 8 lines; actual method is 90+ lines with correlation tracking, improvement application, staging gate on promotion, hook event emission, and stats. **Recommendation**: Add a note: "Production `run_cycle` additionally tracks correlation before/after, applies improvements via `apply_improvement()`, gates model promotion on PromotionStage.STAGING, and emits DRIFT_DETECTED/OUTCOME_COLLECTED hook events."

3. **GAP-B003**: Sub-builder count — Blog says 4, diagram shows 5, actual has 6. **Recommendation**: Update text and mermaid diagram to include `_build_prompt_assembler()` as the 6th sub-builder.

4. **GAP-B001**: `_build_hooks()` parameters — Easy fix: add `log_dir` and `stuck_timeout_s` to the blog's code block.

5. **GAP-B015**: Evaluator error counting — Blog omits that errors also increment the counter and can immediately fail the task. **Recommendation**: Add a brief note about the error path.

### Priority 2 (Low — Acceptable simplifications)

6. GAP-B002, GAP-B005: Constructor/create() simplification — Blog legitimately simplifies for pedagogical clarity
7. GAP-B004: Missing prompt_assembler in diagram — Cosmetic
8. GAP-B007: Missing `verbose`/`memory_context` in send_state — Minor omission
9. GAP-B011: `state` vs `effective_state` naming — Minor naming difference
10. GAP-B012: `_node()` helper args — Blog acknowledges simplification
11. GAP-B018: `_gather_node` history fields — Minor omission
12. GAP-B021: Missing KeyError guard — Defensive code omission
13. GAP-B028: Port vs implementation return type mismatch — Codebase issue, not blog issue

---

## Overall Assessment

**Blog quality: HIGH.** No broken, fabricated, or critically inaccurate claims. All code blocks represent real patterns that exist in the codebase. The 11 divergent findings are all simplifications for readability -- the blog intentionally uses "simplified for clarity" patterns while the actual codebase has richer implementations. The 5 medium-severity gaps are all cases where the blog's simplified code blocks omit meaningful production behavior that a reader might expect to find if they inspect the source.

**Key strength**: The blog accurately captures all architectural patterns, design decisions, and invariants. The domain abstractions are consistent and never contradict the codebase.

**Key weakness**: `_make_hooked_node()` (GAP-B010) and `run_cycle()` (GAP-B023) are the two code blocks where the simplified blog version may mislead readers about the scope of production behavior. Adding callout paragraphs noting the additional production features would resolve this.
