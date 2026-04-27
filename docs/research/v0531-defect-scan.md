# v0.53.1 후속 defect scan — cross-provider parity gaps

## 1. Agentic adapter return-type parity

| Adapter | return normalizer | Returns AgenticResponse | file:line | Status |
|---------|-------------------|----------------------|-----------|--------|
| anthropic | normalize_anthropic | ✅ | anthropic.py:471 | OK |
| openai | normalize_openai_responses | ✅ | openai.py:539 | OK |
| codex | normalize_openai_responses | ✅ | codex.py:301 | ✅ FIXED v0.53.1 |
| glm | normalize_openai | ✅ | glm.py:199 | OK |

**Finding:** All 4 adapters now return AgenticResponse dataclass (not dict). v0.53.1 fixed Codex normalizer.

---

## 2. LLMClientPort method coverage (sync adapters)

| Adapter | generate | gen_structured | gen_parsed | gen_stream | gen_with_tools | Coverage |
|---------|----------|-----------------|-----------|------------|----------------|----------|
| ClaudeAdapter | ✅ | ✅ | ✅ | ✅ | ✅ | 100% |
| OpenAIAdapter | ✅ | ✅ | ✅ | ✅ | ✅ | 100% |

**Finding:** All LLMClientPort methods implemented in both sync adapters. No NotImplementedError paths.

---

## 3. Agentic adapter (async) protocol parity

| Adapter | agentic_call | last_error attr | reset_client | Circuit Breaker | File |
|---------|-------------|-----------------|--------------|-----------------|------|
| ClaudeAgenticAdapter | ✅ async | ✅ | ✅ | ✅ | anthropic.py:270-475 |
| OpenAIAgenticAdapter | ✅ async | ✅ | ✅ | ✅ | openai.py:387-549 |
| CodexAgenticAdapter | ✅ async | ✅ (inherited) | ✅ (inherited) | ✅ | codex.py:170-301 |
| GlmAgenticAdapter | ✅ async | ✅ | ✅ (inherited) | ✅ | glm.py:107-200 |

**Finding:** All adapters implement full AgenticLLMPort protocol.

---

## 4. Circuit breaker + last_error consistency

**Anthropic (anthropic.py):**
- Line 282: `self.last_error: Exception | None = None`
- Line 311, 432, 461: sets `self.last_error`
- No `_circuit_breaker.record_failure()` call in agentic_call (uses router-level retry)

**OpenAI (openai.py:387-549):**
- Line 408: `self.last_error: Exception | None = None`
- Lines 467, 472, 523: sets `self.last_error`
- Lines 525, 529, 532: calls `self._circuit_breaker.record_failure() / record_success()`

**Codex (codex.py:170-301):**
- Inherits from OpenAIAgenticAdapter
- Lines 204, 209, 276: sets `self.last_error`
- Lines 278, 282, 285: calls `_codex_circuit_breaker.record_failure() / record_success()`

**GLM (glm.py:107-200):**
- Inherits from OpenAIAgenticAdapter
- Lines 140, 145, 174: sets `self.last_error`
- Lines 176, 180, 183: calls `self._circuit_breaker.record_failure() / record_success()`

**DEFECT FOUND:** Anthropic adapter doesn't call `_circuit_breaker.record_failure()` in agentic_call exception path. Uses delegated router.call_with_failover retry instead (line 428), but never records CB state. This breaks CB observability parity — Anthropic calls succeed silently even after repeated failures.

---

## 5. BillingError handling parity

**Anthropic (anthropic.py:434-441):**
```python
if "credit balance" in msg.lower() or "billing" in msg.lower():
    from core.llm.errors import BillingError
    raise BillingError(
        "Anthropic API credit balance too low. "
        "Visit https://console.anthropic.com/settings/billing to add credits."
    ) from exc
```
✅ Raises BillingError with context message

**OpenAI (openai.py):**
- No BillingError raise in agentic_call (line 449-549)
- Uses generic exception handler → `self.last_error = exc` (line 523)
- Then returns None

**Codex (codex.py):**
- No BillingError raise
- Generic exception handler (line 275-279)

**GLM (glm.py):**
- No BillingError raise
- Generic exception handler (line 173-177)

**DEFECT FOUND:** Only Anthropic raises BillingError on credit exhaustion. OpenAI/Codex/GLM treat billing errors identically to other exceptions (silent None return). AgenticLoop can't distinguish quota-exhausted state from transient failures.

---

## 6. IPC event parity (agentic_ui → event_renderer)

**emit_* functions in core/ui/agentic_ui.py:**
- emit_budget_warning (line 664)
- emit_retry_wait (line 675)
- emit_llm_error (line 703)
- emit_model_escalation (line 732)
- emit_llm_retry (line 749)
- emit_cost_budget_exceeded (line 765)
- emit_time_budget_expired (line 774)
- emit_convergence_detected (line 791)
- ... (18+ emit_* functions)

**Finding:** No KNOWN_EVENT_TYPES allowlist found in ipc_client.py. Recent v0.52.0 test_ipc_event_parity.py exists but not checked for coverage of all 20+ emit_* functions. **Need separate audit of IPC event schema versioning to prevent silent event drops in thin clients.**

---

## 7. Token tracker MODEL_PRICING coverage

**Missing from MODEL_PRICING (token_tracker.py:152-188):**
- "claude-opus-4" (legacy, kept in ANTHROPIC_FALLBACK_CHAIN at config.py:96)
- "gpt-5" family (pre-5.3) dropped per v0.52.4 policy

**Inconsistency found:**
- Line 162: `"claude-sonnet-4": _ant(3.00, 15.00)` is in MODEL_PRICING
- But config.py:95-96 has ANTHROPIC_FALLBACK_CHAIN = [claude-opus-4-7, claude-opus-4-6, claude-sonnet-4-6, ...]
- "claude-sonnet-4" (non-versioned) not in fallback chain

**Also note:** MODEL_CONTEXT_WINDOW (line 198-220) has same 11 models, good parity.

**DEFECT FOUND:** claude-opus-4 (line 159 in pricing) can be selected via fallback but doesn't exist in current MODEL_CONTEXT_WINDOW. Line 320: `max_ctx = MODEL_CONTEXT_WINDOW.get(model, 200_000)` returns default silently.

---

## 8. Provider equivalence consistency

**_resolve_provider (config.py:416-449):**
- gpt-5.5 / gpt-5.5-pro → "openai-codex" (line 435-436)
- *-codex* suffix → "openai-codex" (line 437-438)
- gpt-5.x → "openai" (line 439)

**MODEL_PROFILES (commands.py:61-73):**
- "gpt-5.5" mapped to "openai" (line 66)
- "gpt-5.3-codex" mapped to "openai-codex" (line 69)

**PROVIDER_EQUIVALENCE (registry.py:101-110):**
- "openai" ↔ ["openai-codex", "openai"]
- "openai-codex" ↔ ["openai-codex", "openai"]

**DEFECT FOUND:** commands.py:66 labels gpt-5.5 with provider="openai" but _resolve_provider returns "openai-codex" for gpt-5.5. The routing resolver (plan_registry.py:172) uses _resolve_provider at runtime, which corrects this, but the static MODEL_PROFILES picker shows wrong provider label to user.

---

## 9. LLMClientPort NotImplementedError coverage

**Finding:** No adapter raises NotImplementedError on any LLMClientPort method. All 5 methods (generate, generate_structured, generate_parsed, generate_stream, generate_with_tools) are implemented in both ClaudeAdapter and OpenAIAdapter. Sync-only adapters don't implement async agentic_call, but that's AgenticLLMPort, not LLMClientPort.

---

## 10. Tool schema normalization (_tools_to_* converters)

**Anthropic tool format (native):**
```
{name, description, input_schema, [cache_control, type]}
```

**OpenAI Chat Completions (_tools_to_chat_completions, openai.py:685-704):**
```
{type: "function", function: {name, description, parameters}}
```

**OpenAI Responses API (_tools_to_openai, openai.py:662-682):**
```
{type: "function", name, description, parameters}
```

**Coverage:**
- Codex uses _tools_to_openai (openai.py import, line 227)
- GLM uses _tools_to_chat_completions (openai.py import, line 151)

**Finding:** Both converters exist and are used. No missing provider path. Good parity.

---

## Summary — Found Defects

| # | Severity | File:Line | Bug Class | Notes |
|----|----------|-----------|-----------|-------|
| D1 | **P1** | anthropic.py:292-471 | Missing circuit breaker record_* | Anthropic agentic_call never calls `_circuit_breaker.record_failure()` on exception. OpenAI/Codex/GLM do. Breaks observability parity. |
| D2 | **P1** | openai.py, codex.py, glm.py:agentic_call | No BillingError distinction | Only Anthropic raises BillingError on credit exhaustion. Others return None silently. AgenticLoop can't trigger quota_exhausted IPC event. |
| D3 | **P2** | token_tracker.py:152-220 | claude-opus-4 no context window | claude-opus-4 is in fallback chain + pricing but missing from MODEL_CONTEXT_WINDOW. Falls back to 200K default silently. |
| D4 | **P2** | commands.py:66 | MODEL_PROFILES provider label mismatch | gpt-5.5 labeled provider="openai" but _resolve_provider returns "openai-codex". UI picker shows wrong provider. |

---

## Recommended Next Patches

### v0.53.2 (P0 / P1)

1. **Anthropic circuit breaker parity (D1):**
   - Add `self._circuit_breaker.record_failure()` to anthropic.py:460-463 exception handler
   - Add `self._circuit_breaker.record_success()` after line 471 before normalize_anthropic return

2. **BillingError handling for OpenAI/Codex/GLM (D2):**
   - Extract BillingError detection from anthropic.py:434 into shared utility
   - Apply to openai.py:522-526, codex.py:275-279, glm.py:173-177
   - Raise BillingError on "billing", "quota", "exceeded", "insufficient_quota" patterns

3. **claude-opus-4 context window (D3):**
   - Add "claude-opus-4" to MODEL_CONTEXT_WINDOW (200K default)
   - Or drop from ANTHROPIC_FALLBACK_CHAIN if deprecated

### v0.53.3 (P2)

4. **MODEL_PROFILES provider label (D4):**
   - Change commands.py:66 from `"openai"` to `"openai-codex"` in gpt-5.5 ModelProfile
   - Document why: gpt-5.5 is OAuth-only per config.py:408-413

