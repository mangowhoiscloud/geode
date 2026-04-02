# Plan: Model Switch Context Guard

## Problem Statement

Haiku 4.5 (`claude-haiku-4-5-20251001`) fails with 400 error classified as `context_overflow`
when selected via `/model`. Root cause is multi-layered:

1. **B3 (Root Cause)**: Anthropic adapter sends `compact-2026-01-12` beta header to ALL models.
   Haiku 4.5 (released 2025-10-01) likely does not support this. API returns 400 with "context"
   in error message -> misclassified as `context_overflow`.

2. **B1 (Dead Code)**: `/model` Context Window Guard in `commands.py:309-328` never executes.
   `set_conversation_context()` has 0 callers -> ContextVar always None -> guard skipped.

3. **B2 (Underestimation)**: `check_context()` uses `response_overhead=500` for system prompt +
   tool definitions. Actual overhead is ~10K tokens. While not the immediate cause (5% of 200K),
   this miscalculation causes `_adapt_context_for_model()` to misjudge compaction need.

## Scope

| Item | File | Change |
|------|------|--------|
| B3 | `core/llm/providers/anthropic.py` | Model-aware beta header injection; skip compact beta for non-supporting models |
| B1 | `core/agent/agentic_loop.py` | Call `set_conversation_context(self.context)` to wire the guard |
| B2 | `core/orchestration/context_monitor.py` | Accept `tools_tokens` parameter; default to measured 10K |
| B2 | `core/agent/agentic_loop.py` | Pass actual tool token count to `check_context()` |
| Tests | `tests/` | Regression tests for all 3 fixes |
| Docs | `CHANGELOG.md` | Record fix |

## Research Grounding

### Claude Code Pattern
- `getContextWindowForModel(model)` — model-specific context windows
- `getAutoCompactThreshold(model)` — dynamic, model-aware thresholds
- Tool definitions sized via `roughTokenCountEstimation()` and included in context budget
- Model switching strips unsupported features dynamically

### OpenClaw Pattern
- Provider-aware strategy selection for context pressure
- Anthropic: server-side compact handles 80-95%; client-side only for emergency (>=95%)
- Non-Anthropic (GLM/OpenAI): client-side compact at 80%+

### Grounding Truth (Measured)
- System prompt: ~2,688 tokens
- 56 base tools: ~7,274 tokens
- Total overhead: ~10K tokens (5% of 200K)
- `response_overhead=500` underestimates by 20x

## Implementation

### B3: Model-Aware Beta Headers

```python
# Models known to support compact beta (1M context models)
_COMPACT_SUPPORTED_MODELS = frozenset({
    "claude-opus-4-6", "claude-opus-4-5",
    "claude-sonnet-4-6", "claude-sonnet-4-5",
})

async def _do_call(m: str) -> Any:
    headers = {}
    body = {}
    if m in _COMPACT_SUPPORTED_MODELS:
        headers["anthropic-beta"] = "context-management-2025-06-27,compact-2026-01-12"
        body["context_management"] = {...}
    return await self._client.messages.create(
        ..., extra_headers=headers, extra_body=body,
    )
```

### B1: Wire Context Guard

In `agentic_loop.py`, after context is initialized:
```python
from core.cli.commands import set_conversation_context
set_conversation_context(self.context)
```

### B2: Fix Overhead Estimation

In `context_monitor.py`:
```python
def check_context(messages, model, *, system_prompt="", tools_tokens: int = 0):
    system_tokens = len(system_prompt) // CHARS_PER_TOKEN if system_prompt else 0
    message_tokens = estimate_message_tokens(messages)
    tools_overhead = tools_tokens if tools_tokens > 0 else _DEFAULT_TOOLS_OVERHEAD
    estimated = system_tokens + message_tokens + tools_overhead
```

## Verification

- Haiku `/model` switch -> "안녕" -> normal response (B3 fix)
- Opus session (large context) -> `/model Haiku` -> guard blocks with warning (B1 fix)
- `check_context()` returns ~10K overhead for standard tool set (B2 fix)
- Full test suite: 3590+ pass
- Lint + Type: 0 errors
