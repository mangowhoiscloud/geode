# Adaptive Error Recovery System

**Date**: 2026-03-16
**Branch**: `feature/error-recovery`
**Status**: Complete

## Summary

Replaced the 2-consecutive-failure auto-skip mechanism in AgenticLoop with an
adaptive error recovery system that progressively tries alternative strategies
before giving up.

## Architecture

```
Tool fails 2+ times consecutively
    │
    ▼
ErrorRecoveryStrategy.recover()
    │
    ├─ RetryStrategy: re-execute with 1s backoff delay
    │   └─ Success? → done
    │
    ├─ AlternativeToolStrategy: same category, different tool
    │   └─ definitions.json category field → find registered alternative
    │   └─ Success? → done
    │
    ├─ FallbackStrategy: cheaper cost_tier tool
    │   └─ definitions.json cost_tier field → find cheaper registered tool
    │   └─ Success? → done
    │
    └─ EscalateStrategy: signal HITL needed
        └─ Always returns failure (user must intervene)
```

## Files Changed

| File | Change |
|------|--------|
| `core/cli/error_recovery.py` | **NEW** — ErrorRecoveryStrategy, RecoveryResult, RecoveryAttempt |
| `core/cli/agentic_loop.py` | Modified — _process_tool_calls uses recovery chain; _attempt_recovery + _emit_hook |
| `core/orchestration/hooks.py` | Added 3 HookEvents: TOOL_RECOVERY_ATTEMPTED/SUCCEEDED/FAILED |
| `tests/test_error_recovery.py` | **NEW** — 32 tests covering all strategies and edge cases |
| `tests/test_hooks.py` | Updated event count 27 → 30 |
| `tests/test_bootstrap.py` | Updated event count 27 → 30 |
| `tests/test_karpathy_prompt_hardening.py` | Updated event count 27 → 30 |
| `CHANGELOG.md` | Added entries |
| `CLAUDE.md` | Updated HookSystem count, module count, project structure |
| `README.md` | Updated HookSystem count |

## Safety Invariants Preserved

- **DANGEROUS tools** (`run_bash`): excluded from recovery — always require HITL approval
- **WRITE tools** (`memory_save`, `note_save`, `set_api_key`, `manage_auth`): excluded from recovery
- **max_recovery_attempts=3**: prevents infinite recovery loops
- **Escalate is terminal**: always returns failure, signaling user intervention needed

## Strategy Selection Logic

| Failure Count | Strategies Tried |
|---------------|-----------------|
| 1 | retry only |
| 2+ | retry → alternative → fallback → escalate |

## Category/Cost-Tier Usage

- **Alternative**: same `category` field from `definitions.json` (e.g., `discovery` → `list_ips` ↔ `search_ips`)
- **Fallback**: lower `cost_tier` (expensive → cheap → free)

## Hook Events

| Event | When | Data |
|-------|------|------|
| `TOOL_RECOVERY_ATTEMPTED` | Recovery chain starts | tool_name, fail_count |
| `TOOL_RECOVERY_SUCCEEDED` | A strategy succeeds | tool_name, strategy, attempts |
| `TOOL_RECOVERY_FAILED` | All strategies exhausted | tool_name, strategies_tried |

## Test Coverage

32 tests across 5 test classes:
- `TestErrorRecoveryStrategy` (16): unit tests for all strategies
- `TestAgenticLoopRecovery` (6): integration with AgenticLoop
- `TestRecoveryHookEvents` (4): hook event definitions
- `TestRecoveryEdgeCases` (6): boundary conditions

## Quality Gates

| Gate | Result |
|------|--------|
| `ruff check core/ tests/` | All checks passed |
| `mypy core/` | Success: 133 source files |
| `pytest tests/ -q` | 2260 passed, 19 deselected |
