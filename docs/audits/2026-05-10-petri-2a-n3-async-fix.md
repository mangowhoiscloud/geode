# Petri × GEODE — N3 결과: target invocation root cause + asyncio fix

> **Phase**: P3-b-2a, N3 (post-mortem of v2 — `docs/audits/2026-05-10-petri-2a-v2.md`)
> **실행**: 2026-05-10 (코드 분석 + 1회 직접 호출 검증, $0.0002)
> **Branch**: `feature/p3-b-2a-n3-cache-debug`
> **Status**: **C4 confirmed (asyncio nested-loop bug). fix 적용 + regression guard test 추가. inspect-petri 통합 환경 라이브 검증은 다음 PR (N3a-followup)**

## TL;DR

v2 의 target metrics 미관측 원인은 **`_default_geode_runner` 의
`loop.run()` 호출이 inspect-petri 의 async event loop 안에서
`asyncio.run() cannot be called from a running event loop`
RuntimeError 를 던지고 있었던 것**. inspect-petri 의 `replayable
(target_model.generate, surface_errors=True)` wrapper 가 이 error 를
받아 auditor 측에 surface → auditor 가 매 send_message 마다
rollback_conversation 으로 응답 → 38 dim 모두 baseline 결과 + GEODE
token tracker 0건.

수정: `loop.run(last_user)` → `await loop.arun(last_user)`. 직접 호출
재현으로 LLM call 정상 발생 + token tracker 1건 기록 ($0.0002,
`claude-opus-4-6`, in=3, out=6) 검증 완료.

## 가설 (v2 보고서) → 결론

| # | 가설 | 결과 | 증거 |
|---|------|------|------|
| **C4** | **`_default_geode_runner` bootstrap fail → empty 응답** | ✅ confirmed (정확한 메커니즘 = asyncio nested-loop) | 직접 호출 시 RuntimeError; v2 transcript 의 rollback_conversation 빈도; auditor_failure dim 비-baseline (#2/#3) |
| C1 | `cache=true` 로 cache hit | ❌ rejected | C4 가 모든 호출을 fail 시키므로 cache 도 만들어진 적 없음 |
| C2 | `geode/*` provider 가 inspect_ai model_usage 누락 | ❌ rejected | provider 자체는 정상 호출되어야 stats 에 기록되는데, 그 단계 도달 못함 |
| C3 | replayable wrapper 가 generate 우회 | ❌ rejected | replayable 은 첫 호출은 record (live), 그 후 cache. 우리 첫 호출이 `surface_errors=True` 로 bubble up |

## 증거

### 1. 직접 호출 RuntimeError (수정 전)

```
calling _default_geode_runner... (t=...)
FAIL (t+0.3s): RuntimeError: asyncio.run() cannot be called from a running event loop
GEODE token_tracker records during call: 0
sys:1: RuntimeWarning: coroutine 'AgenticLoop.arun' was never awaited
```

### 2. fix 후 재현 — 정상 LLM call

```
calling _default_geode_runner... (t=...)
● AgenticLoop  (✢ Thinking...)
✢ claude-opus-4-6 · ↓3 ↑6 · $0.0002
OK (t+2.9s): result snippet = 'pong'
GEODE token_tracker records during call: 1
  ts=... model=claude-opus-4-6 in=3 out=6 cost=$0.0002
```

LLM 호출 + token tracker 갱신 **둘 다** 발생 → C4 의 직접 메커니즘
(asyncio nested-loop) 가 fix 로 해소됨을 확인.

### 3. 코드 위치

| File | Before | After |
|------|--------|-------|
| `plugins/petri_audit/targets/geode_target.py:195` | `result = loop.run(last_user)` | `result = await loop.arun(last_user)` |

`AgenticLoop.run()` (`core/agent/loop/loop.py:298-301`) 가 `asyncio.run
(self.arun(...))` 를 wrap. inspect-petri 가 이미 own event loop 안에서
호출하므로 nested asyncio.run() 이 항상 실패. `await loop.arun(...)`
로 직접 await 가 정답.

## v1 → v2 → 본 PR 의 진화

| 단계 | max_turns | send_message / sample | target metrics | dim 결과 | root cause |
|------|-----------|------------------------|----------------|----------|-------------------|
| v1 (#984/#985) | 5 | **0** | 0 | baseline | H2 (max_turns=5 부족) |
| v2 (#988/#989) | 10 | **3** | 0 | baseline + auditor_failure 일부 | C4 (asyncio nested-loop) |
| **본 PR (N3 fix)** | 10 | (TBD — N3a) | **TBD** (정상 호출 가능) | TBD | ✅ — fix 적용, 다음 라이브 검증 대기 |

## Halt-and-report 결정

본 PR 자체는 **fix + 단위 검증** 만. plan § Halt-and-report 의 모든
조건은 NOT triggered (라이브 호출 0회, $0.0002 만 발생).

## 다음 단계 (별도 PR + 사용자 cost 재승인)

| # | 액션 | 비용 |
|---|------|------|
| **N3a-followup** | fix 후 1 sample (initiative) 라이브 — target metrics nonzero / 4 표적 dim signal 발생 검증 | ~$1.33 / 1,862 KRW |
| **N5** | 4 표적 dim 에서 signal 첫 관측 시 — Phase-2b 진입 가능 (3 seed × 4 dim × 10 turn, ~22K KRW). 사용자 별도 승인 |  ~$15 |
| **N4** | calibration: N3a 정상 호출 데이터로 `DEFAULT_TOKEN_ASSUMPTIONS` 갱신 + `geode_amplifier` 실측 | $0 |

본 PR 머지 후 `geode audit --max-turns 10 --tags initiative --live --yes`
1회로 N3a-followup 자체 진행 가능.

## 본 PR 변경

| File | Change |
|------|--------|
| `plugins/petri_audit/targets/geode_target.py:195` | `loop.run(last_user)` → `await loop.arun(last_user)` + 의도 주석 |
| `tests/plugins/petri_audit/test_skeleton.py` | regression guard `test_default_runner_uses_async_arun_not_sync_run` — source-inspect 로 sync `loop.run(...)` 재도입 차단 |
| `docs/audits/2026-05-10-petri-2a-n3-async-fix.md` | 본 보고서 |
| `CHANGELOG.md` | 항목 |

## 비용 누적

본 세션 누적: v1 391 + v2 1,162 + N3 검증 0.3 = **1,553.3 KRW**.
5K KRW gate 의 30% 수준. N3a-followup 진행 시 ~3,415 KRW 누적 예상.

## 참조

- v2 (#988/#989): `docs/audits/2026-05-10-petri-2a-v2.md` § C4 가설
- N1 (#986/#987): `docs/audits/2026-05-10-petri-2a-target-debug.md` § max_turns root cause
- AgenticLoop sync wrapper: `core/agent/loop/loop.py:298-301`
- inspect-petri target_agent: `.venv/lib/python3.12/site-packages/inspect_petri/target/_agent.py:23-44`
- inspect-petri replayable: `.venv/lib/python3.12/site-packages/inspect_petri/target/_history.py:43-115`
