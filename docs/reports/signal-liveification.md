# Signal Liveification — Implementation Report

**Date**: 2026-03-16
**Branch**: `feature/signal-liveification`
**Status**: Complete

## Summary

MCP 기반 라이브 시그널 수집 시스템을 구현하여, fixture-only였던 signals 노드를
MCP 어댑터 우선 호출 → fixture fallback 구조로 전환했다. `signal_source` 상태 필드로
데이터 출처(live/mixed/fixture)를 추적한다.

## Architecture

```
signals_node(state)
    │
    ▼
Injected adapter? ──No──→ Load fixture → signal_source="fixture"
    │
   Yes
    │
    ▼
CompositeSignalAdapter.fetch_signals(ip_name)
    │
    ├─ SteamMCPSignalAdapter  → Steam MCP server (player_count, review_score, review_count)
    │
    ├─ BraveSignalAdapter     → Brave Search MCP (snippets, urls, result_count)
    │
    └─ _enrichment_sources    → provenance list
    │
    ▼
data keys >= 3? ──Yes──→ signal_source="live"
    │
   No (1-2 keys)
    │
    ▼
Known fixture IP? ──Yes──→ Merge live + fixture → signal_source="mixed"
    │
   No
    │
    ▼
signal_source="fixture" (fallback)
```

## Files Changed

| File | Change |
|------|--------|
| `core/nodes/signals.py` | Modified — MCP adapter 우선 호출 로직, `signal_source` 반환, `set_signal_adapter()` DI |
| `core/runtime.py` | Modified — `_build_signal_adapter()` 메서드 추가 (CompositeSignalAdapter 조립 + 주입) |
| `core/state.py` | Modified — `signal_source` 필드 추가 (`Literal["live", "mixed", "fixture", "web_search"]`) |
| `core/infrastructure/adapters/mcp/steam_adapter.py` | Modified — `SteamMCPSignalAdapter` MCP manager 모드 추가 |
| `core/infrastructure/adapters/mcp/brave_adapter.py` | Modified — `BraveSignalAdapter` Brave Search 기반 시그널 추출 |
| `core/infrastructure/adapters/mcp/composite_signal.py` | **NEW** — `CompositeSignalAdapter` 다중 어댑터 체이닝 |
| `tests/test_signal_liveification.py` | **NEW** — 20 tests |
| `CHANGELOG.md` | Updated |
| `README.md` | Updated |

## Signal Source Determination

| Condition | signal_source | Description |
|-----------|--------------|-------------|
| MCP adapter returns >= 3 data keys | `live` | 충분한 라이브 데이터 |
| MCP adapter returns 1-2 data keys + fixture 존재 | `mixed` | 라이브 + fixture 병합 (live overrides) |
| MCP adapter 미설정 / unavailable / 에러 | `fixture` | fixture 자동 fallback |
| Web search enrichment 경로 | `web_search` | (향후 확장) |

## Design Decisions

1. **DI via `set_signal_adapter()`**: `contextvars` 기반 주입으로 테스트에서 어댑터를 자유롭게 교체 가능. 프로덕션에서는 `GeodeRuntime._build_signal_adapter()`가 조립.

2. **CompositeSignalAdapter 체이닝**: 개별 어댑터(Steam, Brave)를 합성하여 단일 인터페이스로 제공. `_enrichment_sources` 리스트로 어느 소스에서 데이터가 왔는지 추적.

3. **Graceful degradation**: MCP 서버 미연결, 에러, 빈 결과 모두 fixture로 자동 fallback. 파이프라인은 항상 정상 완료.

4. **Live override in mixed mode**: 동일 키가 live와 fixture 양쪽에 존재하면 live 값이 우선. fixture는 live에 없는 키만 보충.

5. **Threshold 3 keys**: 데이터 키 3개 이상이면 "충분한 라이브 데이터"로 판정하여 fixture 병합 없이 진행.

## Test Coverage

20 tests across 7 test classes:

| Test Class | Count | Coverage |
|------------|-------|----------|
| `TestLiveSignals` | 2 | CompositeSignalAdapter 라이브 시그널 수집 |
| `TestFixtureFallback` | 3 | 어댑터 없음/unavailable/에러 시 fixture fallback |
| `TestMixedSignals` | 2 | 부분 라이브 + fixture 병합, live override |
| `TestSignalSourceTracking` | 4 | signal_source 필드 값 검증 (live/fixture/mixed) |
| `TestCompositeSignalAdapter` | 4 | 다중 소스 병합, unavailable 건너뛰기, is_available |
| `TestSteamMCPSignalAdapterManager` | 3 | MCP manager 모드 (healthy/unhealthy/error) |
| `TestBraveSignalAdapter` | 3 | Brave Search 성공/unavailable/빈 결과 |

## Quality Gates

| Gate | Result |
|------|--------|
| `ruff check core/ tests/` | All checks passed |
| `mypy core/` | Success: 132 source files |
| `pytest tests/ -q` | 2226 passed, 19 deselected |
