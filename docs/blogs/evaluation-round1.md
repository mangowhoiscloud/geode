# Blog Evaluation — Round 1

**Evaluator**: Claude Opus 4.6 (strict 6-dimension rubric)
**Date**: 2026-03-02
**Threshold**: 96.0 weighted average

---

## Blog Post 1: "에이전트 시스템의 계층적 메모리 아키텍처"

### Dimension Scores

| Dimension | Weight | Score (0-100) | Issues |
|-----------|--------|---------------|--------|
| Technical Accuracy | 25% | 92 | [1] Blog `OrganizationMemory.get_common_rubric()` tier_mapping shows S:80, A:65, B:50, C:35 — actual code also has D:0 (minor omission). [2] Blog `ContextAssembler.__init__` omits `self._last_assembly_time: float = 0.0` initialization shown in actual code (line 54). [3] Blog `_build_memory` returns `OrganizationMemory` type — actual code returns `MonoLakeOrganizationMemory` (but blog correctly renames for security). [4] Blog `assemble()` method lacks try/except around each tier — actual code has error handling per tier. |
| Security Compliance | 20% | 100 | Zero forbidden domain terms found. All domain-specific names consistently replaced: `ip_name` → `entity_name`, `ip_info` → `entity_info`, `monolake` → `data_store`, `GeodeState` → `AgentState`, `get_ip_context` → `get_entity_context`, `get_context_for_ip` → `get_context_for_entity`. Session key prefix `ip:` → `entity:`. Pure "agent system" framing throughout. No leakage in code blocks, Mermaid diagrams, or prose. |
| Structural Completeness | 15% | 78 | [1] **NO table of contents** — missing entirely. [2] Mermaid diagrams: 5 found (requirement: 4+) — PASS. [3] Python code blocks: 15 found (requirement: 6+) — PASS. [4] Comparison tables: 4 found (requirement: 2+) — PASS. [5] Insight boxes ("> **인사이트**"): 5 found — PASS. [6] Checklist at end: present — PASS. [7] Metadata header: has title, date, tags, series, part — PASS. |
| Code Quality | 15% | 94 | [1] All code uses Python 3.12+ syntax: `dict[str, Any]`, `list[str]`, `str | None` union types — PASS. [2] Type hints present in all function signatures — PASS. [3] Code blocks are self-contained and understandable. [4] Minor: `add_insight` code block (lines 628-650) uses `...` ellipsis for trimming logic rather than showing actual code — acceptable for blog format but slightly imprecise. [5] `frozenset` usage and `dataclass` patterns are correct. |
| Readability | 15% | 95 | Natural Korean prose, not machine-translated. Smooth transitions between sections ("핵심 원칙은...", "병합 순서가 중요하다"). Technical terms explained on first use (e.g., "lazy eviction 전략은 별도 GC 스레드 없이도 만료 데이터를 정리한다"). Heading hierarchy clean (## sections with ### subsections). Section numbering 1-11. Good balance of prose and code. |
| Insight Depth | 10% | 93 | [1] Good tradeoff analysis: why 200-line limit for MEMORY.md (LLM context efficiency). [2] Clean Context pattern well-motivated with anchoring bias explanation. [3] ContextVar choice justified (asyncio+threading safety, function signature preservation). [4] Port/Adapter pattern benefits clearly articulated (test isolation, adapter swapping). [5] Write-through vs write-back tradeoff could be deeper — does not discuss consistency guarantees. |

**Weighted Average**: 0.25(92) + 0.20(100) + 0.15(78) + 0.15(94) + 0.15(95) + 0.10(93) = 23.0 + 20.0 + 11.7 + 14.1 + 14.25 + 9.3 = **92.35**

### Critical Issues (must fix)

1. **Missing Table of Contents** (Structural Completeness): Both blog posts lack a ToC. This is required by the rubric.

### Revision Instructions (targeted)

1. **Add Table of Contents** after the intro paragraph (before Section 1). Format:
   ```
   ## 목차
   1. [왜 에이전트에게 계층적 메모리가 필요한가](#1-왜-에이전트에게-계층적-메모리가-필요한가)
   2. [3-Tier 아키텍처 개관](#2-3-tier-아키텍처-개관)
   ...
   ```
2. **Add error handling to `assemble()`**: The blog version omits try/except blocks present in the actual code. Add at least a comment noting "production implementation wraps each tier in try/except for resilience."
3. **Add `_session_id` and `_ip_name` to assembled context**: The actual `assemble()` method also sets `context["_session_id"]` and `context["_ip_name"]`. Blog should mention this or add to code.

---

## Blog Post 2: "프로덕션 에이전트 런타임 아키텍처"

### Dimension Scores

| Dimension | Weight | Score (0-100) | Issues |
|-----------|--------|---------------|--------|
| Technical Accuracy | 25% | 89 | [1] Blog `Runtime.create()` signature shows `enable_checkpoint` param — actual `GeodeRuntime.create()` has this but blog omits `log_dir`, `stuck_timeout_s` params. [2] Blog `_build_hooks` returns `(HookSystemPort, RunLog, StuckDetector)` which matches actual. [3] Blog `_MULTI_TASK_NODES` uses `"causal_inference"` and `"cross_check"` — actual uses `"psm"` and `"cross_llm"`. This is intentional security renaming, acceptable. [4] Blog `_should_continue` is a standalone function — actual code is a nested closure `_configured_should_continue` with injected thresholds. Blog misses the closure/configurability aspect. [5] Blog `_gather_node` closely matches actual. [6] Blog `FeedbackLoop.run_cycle()` shows simplified version — actual version is more complex with model promotion logic. [7] Blog `compile_graph` is accurate but omits `interrupt_before`, `enable_drift_scan`, and `bootstrap_mgr` params. [8] Blog `_make_hooked_node` omits `bootstrap_mgr` and `prompt_assembler` params present in actual. [9] Blog `make_analyst_sends` omits `_prompt_overrides`, `_extra_instructions` keys present in actual. |
| Security Compliance | 20% | 100 | Zero forbidden domain terms found. Consistent renaming: `GeodeState` → `AgentState`, `GeodeRuntime` → `AgentRuntime`, `ip_name` → `entity_name`, `ip_info` → `entity_info`. `psm` → `causal_inference`, `cross_llm` → `cross_check`. All code blocks, Mermaid diagrams, and prose are clean. No leakage of domain-specific identifiers. |
| Structural Completeness | 15% | 78 | [1] **NO table of contents** — missing entirely. [2] Mermaid diagrams: 6 found (requirement: 4+) — PASS. [3] Python code blocks: 16 found (requirement: 6+) — PASS. [4] Comparison tables: 5 found (requirement: 2+) — PASS. [5] Insight boxes ("> **인사이트**"): 4 found — PASS. [6] Checklist at end: present — PASS. [7] Metadata header: has title, date, tags, series, part — PASS. |
| Code Quality | 15% | 92 | [1] Python 3.12+ syntax throughout: union types with `|`, `dict[str, Any]` — PASS. [2] Type hints present — PASS. [3] `_MULTI_TASK_NODES` code is syntactically correct. [4] `HookEvent` enum definition is accurate and complete (18 events). [5] Minor: `HookEvent` shows `PROMPT_ASSEMBLED` comment as "(1)" but there are 18 total events grouped as (3+4+3+2+5+1) — this is correct. [6] `FeedbackLoop` code simplification loses `apply_improvement` detail. [7] Degraded Response code block accurately mirrors actual `_run_analyst`. |
| Readability | 15% | 94 | Natural Korean prose. Good opening hook ("LangGraph 에이전트를 프로토타입에서 프로덕션으로 올리는 순간"). Technical terms well-introduced (CUSUM explained as "순차 데이터에서 평균 변화를 감지하는 통계적 방법"). Cohen(1988) citation adds rigor. Smooth section flow from initialization → execution → automation. Heading hierarchy clear. |
| Insight Depth | 10% | 95 | [1] Excellent "프로토타입 vs 프로덕션" comparison table sets context. [2] "Observer over Controller" principle well-articulated for TaskGraph design. [3] Statistical power gate in RLHF feedback loop (Cohen 1988 citation, n>=29 justification) is genuinely insightful. [4] Degraded Response three principles (is_degraded flag, lowest score injection, error accumulation) show deep understanding. [5] `graph.stream()` vs `graph.invoke()` tradeoff analysis is practical and useful. |

**Weighted Average**: 0.25(89) + 0.20(100) + 0.15(78) + 0.15(92) + 0.15(94) + 0.10(95) = 22.25 + 20.0 + 11.7 + 13.8 + 14.1 + 9.5 = **91.35**

### Critical Issues (must fix)

1. **Missing Table of Contents** (Structural Completeness): Same as Blog 1.
2. **`_should_continue` lacks closure/configurability context** (Technical Accuracy): The blog shows a standalone function with hardcoded `0.7` threshold. The actual implementation uses a closure with injected `confidence_threshold` and `max_iterations` parameters. This is an important architectural detail for production configurability.

### Revision Instructions (targeted)

1. **Add Table of Contents** after the intro paragraph, same format as Blog 1.
2. **Update `_should_continue` to show closure pattern**: Replace the standalone function with the closure-based `_configured_should_continue` that demonstrates injected thresholds. This is a key production pattern — configurability without global state.
3. **Add `bootstrap_mgr` parameter to `_make_hooked_node`**: The actual code has a `bootstrap_mgr` parameter for NODE_BOOTSTRAP pre-execution configuration. At minimum, add a comment noting this extension point.
4. **`compile_graph` should mention `interrupt_before` param**: This enables human-in-the-loop support, which is a significant production feature.

---

## Overall Assessment

| Metric | Blog 1 | Blog 2 |
|--------|--------|--------|
| Technical Accuracy (25%) | 92 | 89 |
| Security Compliance (20%) | 100 | 100 |
| Structural Completeness (15%) | 78 | 78 |
| Code Quality (15%) | 94 | 92 |
| Readability (15%) | 95 | 94 |
| Insight Depth (10%) | 93 | 95 |
| **Weighted Average** | **92.35** | **91.35** |

### Verdict: **FAIL**

- Blog 1: 92.35 (threshold: 96.0) — **-3.65 gap**
- Blog 2: 91.35 (threshold: 96.0) — **-4.65 gap**

### Root Cause Analysis

The primary score drag is **Structural Completeness at 78** (both posts), which costs **~2.7 points** each from the weighted average. Adding a Table of Contents would bring this to 90+, recovering most of the gap.

Secondary drags:
- **Technical Accuracy**: Blog 1 at 92, Blog 2 at 89. Blog 2's simplified `_should_continue` and omitted `bootstrap_mgr`/`interrupt_before` params hurt precision.

### Specific Revision Instructions (priority order)

#### Must Fix (both posts)

1. **Add Table of Contents (ToC)** to both posts immediately after the introductory paragraph. Use markdown anchor links. This alone should recover +2.5-3.0 weighted points per post.

#### Must Fix (Blog 1 only)

2. **ContextAssembler.assemble() error handling**: Add try/except or at minimum a comment noting production-grade error handling. This aligns code with actual implementation and improves Technical Accuracy.
3. **Add `_session_id`/`_ip_name` to assembled context output**: Small code addition to match actual behavior.

#### Must Fix (Blog 2 only)

4. **Replace `_should_continue` with closure-based `_configured_should_continue`**: Show the injected `confidence_threshold` parameter. This demonstrates an important production pattern (configurability without global state) and fixes the accuracy issue.
5. **Add `interrupt_before` mention to `compile_graph`**: At minimum, add a comment: "프로덕션에서는 `interrupt_before=["verification"]`으로 human-in-the-loop 지원도 가능하다."
6. **Mention `bootstrap_mgr` in `_make_hooked_node`**: Add a parameter or comment showing the NODE_BOOTSTRAP extension point.

### Expected Post-Revision Scores

| Metric | Blog 1 (est.) | Blog 2 (est.) |
|--------|---------------|---------------|
| Technical Accuracy | 95 (+3) | 94 (+5) |
| Security Compliance | 100 (no change) | 100 (no change) |
| Structural Completeness | 92 (+14) | 92 (+14) |
| Code Quality | 94 (no change) | 93 (+1) |
| Readability | 95 (no change) | 94 (no change) |
| Insight Depth | 93 (no change) | 95 (no change) |
| **Weighted Average** | **96.0** | **95.6** |

Blog 2 may need one additional insight or code refinement to cross the 96.0 threshold. Consider adding a brief subsection on `BootstrapManager` integration or expanding the `compile_graph` section with `interrupt_before` human-in-the-loop discussion.
