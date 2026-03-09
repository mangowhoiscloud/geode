# GAP Analysis: Blog Post 1 vs Codebase

## Summary
- Total claims analyzed: 42
- Accurate: 25
- Gaps found: 17 (Broken: 2, Missing: 1, Divergent: 12, Fabricated: 2)

---

## Critical Gaps (BROKEN / MISSING)

### GAP-001: session_id not in GeodeState — memory assembly never triggers in pipeline
- **Type**: BROKEN
- **Blog claim**: Section 9 shows `cortex_node` reading `state.get("session_id", "")` and using it to trigger `assembler.assemble(session_id, ip_name)`. The blog implies this is wired end-to-end.
- **Actual code**: `GeodeState` (in `geode/state.py`) does **not** define a `session_id` field. The `cli/__init__.py` constructs `initial_state` without setting `session_id`. Therefore, `cortex_node` always gets `""` from `state.get("session_id", "")`, the `if session_id:` guard fails, and **memory context is never assembled during actual pipeline execution**.
- **File**: `geode/state.py` (no `session_id` field), `geode/cli/__init__.py:345-355` (no `session_id` in initial_state), `geode/nodes/cortex.py:60-64` (guard fails)
- **Impact**: **Critical**. The entire 3-tier memory assembly (the blog's main topic) is dead code in the pipeline. ContextAssembler is constructed and wired but never invoked.
- **Fix**: Add `session_id: str` to `GeodeState`. Set `session_id` in `initial_state` construction in `cli/__init__.py`, using `runtime.session_key` or similar.

### GAP-002: memory_write_back hook gets incomplete data — no ip_name/tier/score in PIPELINE_END event
- **Type**: BROKEN
- **Blog claim**: Section 10 shows `_on_pipeline_end_memory` reading `data.get("ip_name")`, `data.get("tier")`, `data.get("final_score")` from the hook event data to construct an insight string.
- **Actual code**: The `memory_write_back` handler in `runtime.py:434-455` reads these same keys from `data`, but **the caller that triggers PIPELINE_END does not necessarily pass the full pipeline state**. The hook system only receives whatever `data` dict is passed to `hooks.trigger()`. There is no evidence in `graph.py` or the CLI that `PIPELINE_END` is triggered with the full pipeline result state (containing `ip_name`, `tier`, `final_score`, `synthesis_cause`). The hook would receive an empty or partial dict, causing the insight to be `[unknown] tier=?, score=0.00`.
- **File**: `geode/runtime.py:434-455` (handler), no corresponding `hooks.trigger(HookEvent.PIPELINE_END, full_state)` call found in pipeline execution path
- **Impact**: **High**. The auto-learning loop (writing insights to MEMORY.md) produces garbage data even if it were to fire.
- **Fix**: Ensure `PIPELINE_END` is triggered with the full pipeline result state after `graph.stream()` completes in the CLI execution path.

### GAP-003: PromptAssembler has 6 phases, blog shows 5
- **Type**: MISSING
- **Blog claim**: Section 7 describes PromptAssembler as a "5-Phase 프롬프트 조립기" with phases 1-5 (Override, Skill, Memory, Bootstrap, Hash+Event).
- **Actual code**: `geode/llm/prompt_assembler.py` has **6 phases**: Phase 1 (Prompt Override), Phase 2 (Skill Fragment), Phase 3 (Memory Context), Phase 4 (Extra Instructions/Bootstrap), **Phase 5 (Token Budget Enforcement)**, Phase 6 (Hash + Observability). The blog omits Phase 5 entirely.
- **File**: `geode/llm/prompt_assembler.py:159-173` (Phase 5: Token Budget Enforcement with hard limit)
- **Impact**: Medium. The blog omits the token budget enforcement phase, which is an important safety mechanism (hard limit at 6000 chars, warning at 4000 chars).
- **Fix**: Update blog to describe 6 phases and include Phase 5 (Token Budget Enforcement).

---

## Divergent

### GAP-004: Blog uses `entity_name` terminology; code uses `ip_name`
- **Type**: DIVERGENT
- **Blog claim**: Throughout the blog, field names use `entity_name` (e.g., `state["entity_name"]`, `entity:{name}:{phase}`, `get_entity_context`, `get_context_for_entity`, `_entity_name`). The blog's code blocks consistently use "entity" as the domain concept.
- **Actual code**: The codebase consistently uses `ip_name` (e.g., `state["ip_name"]`, `ip:{name}:{phase}`, `get_ip_context`, `get_context_for_ip`, `context["_ip_name"]`).
- **Files**: `geode/state.py:163` (`ip_name`), `geode/memory/context.py:59,112` (`ip_name`, `_ip_name`), `geode/memory/session_key.py:40,52` (`ip:` prefix), `geode/memory/organization.py:55` (`get_ip_context`), `geode/memory/project.py:236` (`get_context_for_ip`), `geode/infrastructure/ports/memory_port.py:47` (`get_ip_context`)
- **Impact**: Medium. A reader trying to find code matching the blog would search for `entity_name` and find nothing. Every code block in the blog that references `entity_name` is wrong.
- **Fix**: Replace all `entity_name` references in the blog with `ip_name`, `entity:` prefix with `ip:`, `get_entity_context` with `get_ip_context`, `get_context_for_entity` with `get_context_for_ip`, `_entity_name` with `_ip_name`.

### GAP-005: Blog uses `data_store` field; code uses `monolake`
- **Type**: DIVERGENT
- **Blog claim**: Section 8 shows `make_analyst_sends` passing `"data_store": state["data_store"]` in the clean context.
- **Actual code**: The actual field name is `"monolake": state["monolake"]`. There is no `data_store` field anywhere in the codebase.
- **File**: `geode/nodes/analysts.py:309` (`"monolake": state["monolake"]`)
- **Impact**: Medium. Code block in blog would not work if copy-pasted.
- **Fix**: Replace `data_store` with `monolake` in the blog's clean context code.

### GAP-006: Blog's `cortex_node` returns `entity_info` + `data_store`; actual returns `ip_info` + `monolake`
- **Type**: DIVERGENT
- **Blog claim**: Section 9 shows `cortex_node` returning `{"entity_info": fixture["entity_info"], "data_store": fixture["data_store"]}`.
- **Actual code**: Returns `{"ip_info": fixture["ip_info"], "monolake": fixture["monolake"]}`.
- **File**: `geode/nodes/cortex.py:42-45`
- **Impact**: Medium. Code block is completely wrong for both key names.
- **Fix**: Update blog code to match actual key names.

### GAP-007: Organization Memory class name differs
- **Type**: DIVERGENT
- **Blog claim**: Section 3 shows the adapter class as `OrganizationMemory`.
- **Actual code**: The class is named `MonoLakeOrganizationMemory`.
- **File**: `geode/memory/organization.py:22`
- **Impact**: Low. Cosmetic but would confuse someone searching the codebase.
- **Fix**: Use `MonoLakeOrganizationMemory` in the blog or note the rename.

### GAP-008: Organization Memory tier mapping differs
- **Type**: DIVERGENT
- **Blog claim**: Section 3 shows `tier_mapping` with 4 tiers: `{"S": {"min_score": 80}, "A": {"min_score": 65}, "B": {"min_score": 50}, "C": {"min_score": 35}}`.
- **Actual code**: Has 5 tiers: `{"S": {"min_score": 80}, "A": {"min_score": 65}, "B": {"min_score": 50}, "C": {"min_score": 35}, "D": {"min_score": 0}}`. The `"D"` tier is present in the actual code but missing from the blog.
- **File**: `geode/memory/organization.py:69-75`
- **Impact**: Low. Minor omission, but the blog is inaccurate about the rubric configuration.
- **Fix**: Add `"D"` tier to the blog's tier_mapping.

### GAP-009: OrganizationMemoryPort uses `get_ip_context` not `get_entity_context`
- **Type**: DIVERGENT
- **Blog claim**: Section 3 defines `OrganizationMemoryPort` with method `get_entity_context(self, entity_name: str)`.
- **Actual code**: The method is `get_ip_context(self, ip_name: str)`.
- **File**: `geode/infrastructure/ports/memory_port.py:47`
- **Impact**: Medium. Interface contract shown in blog does not match actual Protocol definition. (Related to GAP-004 but specific to Port signature.)
- **Fix**: Update blog to show `get_ip_context`.

### GAP-010: PromptAssembler.assemble() signature differs significantly
- **Type**: DIVERGENT
- **Blog claim**: Section 7 shows `assemble(self, *, base_system: str, state: dict[str, Any]) -> AssembleResult` with only 2 keyword args.
- **Actual code**: `assemble(self, *, base_system: str, base_user: str, state: dict[str, Any], node: str, role_type: str) -> AssembledPrompt` with 5 keyword args. Also, the return type is `AssembledPrompt`, not `AssembleResult`.
- **File**: `geode/llm/prompt_assembler.py:89-97`
- **Impact**: High. The signature shown in the blog is completely wrong. The actual method requires `base_user`, `node`, and `role_type` parameters, and the return type name differs.
- **Fix**: Update blog to show actual 5-param signature and `AssembledPrompt` return type.

### GAP-011: `_build_memory` returns `MonoLakeOrganizationMemory` not `OrganizationMemory`
- **Type**: DIVERGENT
- **Blog claim**: Section 9 shows `_build_memory` returning `tuple[ProjectMemory, OrganizationMemory, ContextAssembler]`.
- **Actual code**: Returns `tuple[ProjectMemory, MonoLakeOrganizationMemory, ContextAssembler]`.
- **File**: `geode/runtime.py:282`
- **Impact**: Low. Type annotation mismatch.
- **Fix**: Update return type in blog.

### GAP-012: Blog's `call_llm` comment shows wrong fallback chain
- **Type**: DIVERGENT
- **Blog claim**: Section on multi-model shows `# Failover: primary -> opus-4.6 -> sonnet-4.5`.
- **Actual code**: The `FALLBACK_MODELS` list is `["claude-opus-4-6", "claude-sonnet-4-5-20250929"]`. The model ID format uses dashes (`claude-opus-4-6`) not dots (`opus-4.6`). More importantly, `call_llm` itself has no inline comment about the fallback chain; the failover is handled by `_retry_with_backoff`.
- **File**: `geode/llm/client.py:123-126`
- **Impact**: Low. Blog simplifies the model IDs.
- **Fix**: Update model IDs to match actual `claude-opus-4-6` / `claude-sonnet-4-5-20250929` format.

### GAP-013: Session key prefix is `ip:` not `entity:`
- **Type**: DIVERGENT
- **Blog claim**: Section 6 shows session key format as `entity:{name}:{phase}[:{sub_context}]` with examples like `entity:entity_a:cortex`.
- **Actual code**: Format is `ip:{name}:{phase}[:{sub_context}]` with examples like `ip:berserk:cortex`.
- **File**: `geode/memory/session_key.py:6-13,52`
- **Impact**: Medium. Related to GAP-004, but specific to the session key format documentation.
- **Fix**: Update all session key examples to use `ip:` prefix.

### GAP-014: Blog shows `AgentState`; actual type is `GeodeState`
- **Type**: DIVERGENT
- **Blog claim**: Section 8 uses `def make_analyst_sends(state: AgentState)` and Section 9 uses `def cortex_node(state: AgentState)`.
- **Actual code**: Both functions use `GeodeState` as the state type.
- **File**: `geode/nodes/analysts.py:299`, `geode/nodes/cortex.py:32`
- **Impact**: Low. Type name mismatch.
- **Fix**: Replace `AgentState` with `GeodeState` in blog.

### GAP-015: Clean Context propagation keys differ — blog has `_prompt_overrides`/`_extra_instructions`, omits them from table
- **Type**: DIVERGENT
- **Blog claim**: Section 8 shows `make_analyst_sends` passing these keys: `entity_name`, `entity_info`, `data_store`, `signals`, `dry_run`, `verbose`, `_analyst_type`, `analyses`, `errors`, `memory_context`. The table lists "propagated" vs "blocked" data.
- **Actual code**: Additionally propagates `_prompt_overrides` and `_extra_instructions` (ADR-007 bootstrap keys). Uses `ip_name`, `ip_info`, `monolake` instead of `entity_name`, `entity_info`, `data_store`.
- **File**: `geode/nodes/analysts.py:306-322`
- **Impact**: Medium. Blog omits two important propagated keys that enable prompt assembly customization in analysts.
- **Fix**: Add `_prompt_overrides` and `_extra_instructions` to the blog's propagation table and update field names.

---

## Fabricated

### GAP-016: Blog's PromptAssembler code block is a simplified fabrication
- **Type**: FABRICATED
- **Blog claim**: Section 7 shows a simplified `PromptAssembler` class with `__init__(self, *, max_memory_chars: int = 300)` and a simple `assemble()` that returns `AssembleResult(system=system, user=user)`.
- **Actual code**: The real `PromptAssembler.__init__` takes 9 parameters (`skill_registry`, `hooks`, `allow_full_override`, `max_skill_chars`, `max_skills_per_node`, `max_memory_chars`, `max_extra_instructions`, `max_extra_instruction_chars`, `prompt_warning_chars`, `prompt_hard_limit_chars`). The real `assemble()` method is 90+ lines with 6 phases and returns `AssembledPrompt` with 7 fields (not just `system` + `user`).
- **File**: `geode/llm/prompt_assembler.py:61-204`
- **Impact**: Medium. The blog presents a severely simplified version as if it were the actual code. A reader would not understand the real complexity.
- **Fix**: Either show the actual code or explicitly note that the example is a simplified illustration.

### GAP-017: Blog's `_RedisEntry` dataclass field name differs
- **Type**: FABRICATED (minor)
- **Blog claim**: Section 5 shows `_RedisEntry` using `data: dict[str, Any]`, `created_at: float`, `ttl_seconds: float = DEFAULT_TTL_SECONDS` with a `RedisSessionStore` class.
- **Actual code**: The code matches closely, but the blog shows `RedisSessionStore.get()` checking `time.time() - entry.created_at > entry.ttl_seconds` and doing `del self._store[session_id]`, while the actual code in `geode/memory/session.py` (the `InMemorySessionStore`) uses a different class name `SessionEntry` (not `_RedisEntry`) with `self._ttl` instead of per-entry TTL. The `_RedisEntry` class exists in `hybrid_session.py` and does match the blog description.
- **File**: `geode/memory/session.py:15-19` (`SessionEntry`), `geode/memory/hybrid_session.py:33-38` (`_RedisEntry` matches)
- **Impact**: Low. The blog conflates the simpler `InMemorySessionStore`/`SessionEntry` with `RedisSessionStore`/`_RedisEntry`. The `_RedisEntry` code does match, but the blog presents it as the primary session store when `InMemorySessionStore` (from `session.py`) is what gets used by default.
- **Fix**: Clarify that `_RedisEntry`/`RedisSessionStore` is the hybrid-mode component, not the default.

---

## Accurate Claims

1. **3-Tier architecture concept** (Org -> Project -> Session with lower tiers overriding higher) - accurately described
2. **ContextAssembler class signature** - `__init__` parameters match code (`organization_memory`, `project_memory`, `session_store`, `freshness_threshold_s`)
3. **ContextAssembler.assemble() merge logic** - dict.update() order (Org -> Project -> Session) is correct
4. **ContextAssembler._build_llm_summary()** - logic matches code exactly (checks `_org_loaded`, `_project_loaded`, `_session_loaded`)
5. **ContextAssembler.is_data_fresh()** - logic matches code exactly
6. **ContextAssembler.mark_assembled()** - exists and works as described
7. **Freshness threshold default 3600s** - matches `DEFAULT_FRESHNESS_THRESHOLD_S`
8. **Context metadata keys** - `_assembled_at`, `_session_id`, `_llm_summary`, `_org_loaded`, `_project_loaded`, `_session_loaded` all present in code
9. **ProjectMemory.load_memory()** - MAX_MEMORY_LINES=200, line slicing logic matches
10. **ProjectMemory.load_rules()** - YAML frontmatter parsing, glob pattern matching logic matches
11. **ProjectMemory.add_insight()** - dedup logic, newest-first, MAX_INSIGHTS=50 rotation all match
12. **HybridSessionStore write-through pattern** - L1+L2 simultaneous write, L1-first read with backfill all match
13. **HybridSessionStore class signature** - `__init__(self, l1: SessionStorePort, l2: SessionStorePort)` matches
14. **ALL_PHASES frozenset** - 7 phases match exactly
15. **build_session_key() function** - logic matches (normalize + join with colon)
16. **build_thread_config() function** - returns `{"configurable": {"thread_id": thread_id}}`, matches
17. **Port/Adapter pattern with `runtime_checkable`** - all 3 ports use `@runtime_checkable` Protocol
18. **3 Ports defined** - `OrganizationMemoryPort`, `ProjectMemoryPort`, `SessionStorePort` all exist
19. **Clean Context pattern** - `analyses: []` in Send state, blocking other analysts' results - accurately described
20. **ContextVar injection pattern** - `_context_assembler_ctx` ContextVar in cortex.py matches
21. **set_context_assembler()** - function exists and is called from `_build_memory()` in runtime
22. **_build_memory() wiring** - creates ProjectMemory, OrganizationMemory, ContextAssembler and calls `set_context_assembler` - matches
23. **memory_write_back hook registration** - priority=85, name="memory_write_back", registered on PIPELINE_END - matches
24. **dry_run guard in write-back** - `if data.get("dry_run", False): return` - matches
25. **PromptAssembler Phase 3 memory injection concept** - reads `memory_context` from state, formats with `_format_memory_block`, truncates to `max_memory_chars=300` - concept matches (though details differ per GAP-010/016)

---

## Summary Table

| GAP ID | Type | Severity | Topic |
|--------|------|----------|-------|
| GAP-001 | BROKEN | **Critical** | session_id missing from GeodeState - memory never fires |
| GAP-002 | BROKEN | High | PIPELINE_END hook receives incomplete data |
| GAP-003 | MISSING | Medium | Blog omits Phase 5 (Token Budget Enforcement) |
| GAP-004 | DIVERGENT | Medium | `entity_name` vs `ip_name` throughout |
| GAP-005 | DIVERGENT | Medium | `data_store` vs `monolake` field |
| GAP-006 | DIVERGENT | Medium | cortex_node return keys wrong |
| GAP-007 | DIVERGENT | Low | `OrganizationMemory` vs `MonoLakeOrganizationMemory` |
| GAP-008 | DIVERGENT | Low | tier_mapping missing D tier |
| GAP-009 | DIVERGENT | Medium | Port method name mismatch |
| GAP-010 | DIVERGENT | High | PromptAssembler.assemble() signature completely wrong |
| GAP-011 | DIVERGENT | Low | _build_memory return type annotation |
| GAP-012 | DIVERGENT | Low | Fallback model ID format |
| GAP-013 | DIVERGENT | Medium | Session key prefix `entity:` vs `ip:` |
| GAP-014 | DIVERGENT | Low | `AgentState` vs `GeodeState` type name |
| GAP-015 | DIVERGENT | Medium | Missing propagated keys in clean context |
| GAP-016 | FABRICATED | Medium | PromptAssembler code block is heavily simplified |
| GAP-017 | FABRICATED | Low | SessionEntry vs _RedisEntry conflation |

---

## Priority Fix Order

1. **GAP-001** (Critical): Add `session_id` to `GeodeState` and wire it in CLI initial_state. Without this fix, the blog's entire premise (3-tier memory assembly) is non-functional.
2. **GAP-002** (High): Wire PIPELINE_END hook trigger with full pipeline state data so memory write-back produces meaningful insights.
3. **GAP-004/005/006/009/013/014** (Medium, batch): Rename all `entity_name`/`data_store`/`entity:`/`AgentState` references in the blog to match actual codebase naming (`ip_name`/`monolake`/`ip:`/`GeodeState`).
4. **GAP-010/016** (High/Medium): Fix PromptAssembler code blocks to show actual signature and note simplifications.
5. **GAP-003/015** (Medium): Add Phase 5 description and missing propagated keys.
6. **GAP-007/008/011/012/017** (Low): Fix class names, tier mappings, model IDs.
