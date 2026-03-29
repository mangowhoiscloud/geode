# Plan: SharedServices Gateway

> Single factory for REPL/DAEMON/SCHEDULER/FORK sessions.
> All entry points share the same resources, differ only in mode-specific behavior.

## Phases

- Phase 1: Gateway Foundation — SharedServices + SessionMode + create_session()
- Phase 2: Time-Based Constraints — max_rounds=0, time_budget_s per mode
- Phase 3: ContextVar + Thread Safety — globals→ContextVar, _readiness Lock

## Frontier Evidence

Codex ThreadManagerState + SessionServices, OpenClaw Gateway, Claude Code f8 + AppState.

## Validation: 5-persona (Beck/Karpathy/Steinberger/Cherny/GAP Detective)
