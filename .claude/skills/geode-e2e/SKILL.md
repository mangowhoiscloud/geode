---
name: geode-e2e
description: Live E2E verification + LangSmith Observability + quality inspection patterns. Mock/Live test tiers, scenario mapping, _make_loop() pattern, ReadinessReport control, trace verification. Triggers on "e2e", "live test", "검증", "langsmith", "tracing", "observability", "품질 점검".
---

## Test Tiers

| Tier | File | LLM Calls | Execution Time | Purpose |
|------|------|-----------|----------------|---------|
| **Mock** | `test_agentic_loop.py`, `test_e2e.py`, `test_e2e_orchestration_live.py` | No | ~3s | CI/CD, regression |
| **Live** | `test_e2e_live_llm.py` | Yes (Anthropic API) | ~5min | Real behavior verification |

## Live Test Execution

```bash
# Load .env + run live-marked tests only
set -a && source .env && set +a && uv run pytest tests/test_e2e_live_llm.py -v -m live

# Specific scenario only
uv run pytest tests/test_e2e_live_llm.py::TestAgenticLoopLive::test_1_2_single_tool -v

# Offline mode only (no API cost)
uv run pytest tests/test_e2e_live_llm.py::TestOfflineModeLive -v
```

## Scenario Mapping (docs/e2e/e2e-orchestration-scenarios.md)

### §1 AgenticLoop (Real Anthropic API)

| ID | Scenario | Verification Points |
|----|----------|---------------------|
| 1-1 | Text response ("Hello") | tool_calls=[], rounds=1, text not empty |
| 1-2 | Single tool ("Show IP list") | list_ips tool called, no error in result |
| 1-3 | Sequential tools ("Analyze then compare") | analyze_ip → compare_ips order, rounds >= 2 |
| 1-4 | Parallel tools ("Search both") | tool_calls >= 2 |
| 1-5 | Max rounds guardrail | rounds <= max_rounds, error="max_rounds" |
| 1-7 | Multi-turn context | turn_count increases, references previous analysis |

### §4 LangSmith Tracing

| ID | Verification Points |
|----|---------------------|
| 4-2 | AgenticLoop trace exists in LangSmith 'geode' project |

### §5 Full Pipeline (Real LLM)

| ID | Scenario | Verification Points |
|----|----------|---------------------|
| 5-1 | Single IP (Berserk) | tier in S/A/B/C, score > 0, analyses = 4, synthesis exists |
| 5-2 | 3 IP smoke test | All 3 have valid tier + score |
| 5-3 | Feedback loop | synthesizer visited, high confidence → gather not visited |

### §6 Plan/Sub-agent NL Integration

| ID | Scenario | Verification Points |
|----|----------|---------------------|
| 6-1 | Plan NL ("Make a plan") | create_plan tool called, plan_id returned |
| 6-2 | Plan Approve NL ("Approve it") | approve_plan tool called |
| 6-3 | Delegate NL ("Process in parallel") | delegate_task tool called |
| 6-4 | Plan Offline | regex → plan action |
| 6-5 | Delegate Offline | regex → delegate action |

### §C5 Offline Mode

| ID | Verification Points |
|----|---------------------|
| offline-list | regex → list action, rounds=1 |
| offline-analyze | regex → analyze action |
| offline-help | unrecognized → help fallback |
| offline-plan | regex → plan action ("계획", "plan") |
| offline-delegate | regex → delegate action ("병렬", "parallel") |

## Key Patterns

### 1. _make_loop() — Complete test environment setup

```python
def _make_loop(*, force_dry_run=False):
    # 1. ReadinessReport setup (force_dry_run control)
    # 2. _build_tool_handlers() → Register 20 handlers (including plan/delegate)
    # 3. ToolExecutor(action_handlers=handlers)
    # 4. AgenticLoop(context, executor)
```

**Note**: Creating `ToolExecutor()` without handlers causes all tool calls to return `Unknown tool` errors. Always register handlers via `_build_tool_handlers()`.

### 2. ReadinessReport — dry-run control

```python
readiness = check_readiness()
readiness.force_dry_run = False  # Allow real LLM calls
readiness.has_api_key = True
_set_readiness(readiness)
```

Inside `_build_tool_handlers()`, `_get_readiness().force_dry_run` is read to determine the dry_run default for analyze_ip, etc.

### 3. LangSmith Trace Verification

```python
import time
from langsmith import Client

time.sleep(3)  # Wait for async flush
client = Client()
runs = list(client.list_runs(project_name="geode", limit=5))
assert any("AgenticLoop" in (r.name or "") for r in runs)
```

### 4. Quality Inspection Checklist

Mandatory checks after running live tests:

- [ ] **Tool execution success**: No `error` key in tool_calls results
- [ ] **Handler registration**: Using `_build_tool_handlers()`, no empty ToolExecutor
- [ ] **ReadinessReport**: Confirmed `force_dry_run=False` (for live tests)
- [ ] **Token cost**: Check cost_usd in LangSmith metrics
- [ ] **Pipeline mode**: Confirm `dry-run (no LLM)` vs actual model name
- [ ] **LangSmith traces**: Verify no pending-state runs
- [ ] **Claude Code UI**: Confirm `▸`/`✓`/`✗` markers output on tool calls
- [ ] **Plan/Delegate NL**: Confirm "계획 세워줘"→plan, "병렬로"→delegate mapping

## Environment Variables

```bash
# .env (required)
ANTHROPIC_API_KEY=sk-ant-...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=geode
```

## Update Rules

When features change, update E2E tests in this order:

1. **Scenario document**: `docs/e2e/e2e-orchestration-scenarios.md`
2. **Mock tests**: `test_agentic_loop.py`, `test_e2e.py`, `test_e2e_orchestration_live.py`
3. **Live tests**: `test_e2e_live_llm.py`
4. **This skill**: Scenario mapping tables + verification points

### Per-Change Type Guide

| Change | Mock Tests | Live Tests | Scenario Doc |
|--------|-----------|-----------|--------------|
| New tool added | Add ToolExecutor mock | Add 1-2 type scenario | Add to §1 |
| Pipeline node added | Update 5-1 type visited_nodes | Update 5-1 type asserts | Add to §5 |
| LLM adapter changed | Update 4-* tracing mock | Verify 4-2 LangSmith | Update §4 |
| Offline pattern added | Test nl_router regex | Add offline-* scenario | Update §C5 |
