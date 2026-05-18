# Self-Improving Loop — Observability Gap Audit (2026-05-19)

> Source: 2026-05-19 Phase α–δ config consolidation (PR-δ1 #1325 + PR-δ2 #1323)
> 직후 dry-run 스모크 + 관측성 sink/event 전수 스캔의 결과.
> 본 문서는 **(1) 명명 결정**, **(2) 현재 활성 sink 인벤토리**,
> **(3) 누락 매트릭스**, **(4) 에러 swallow 매트릭스**,
> **(5) 중복(dedup) 매트릭스**, **(6) 우선순위 + 작업 계획** 을
> 단일 SoT 로 정착시킵니다. 후속 구현 PR 들은 이 문서를 참조합니다.

## 1. 한 줄 요약

`autoresearch + seed_generation + petri` 3-축이 합세해서 **세대 간 자기 개선 (self-improving)** 을 수행하는 루프이지만, 관측성 인프라(`SessionJournal` + `sessions.jsonl` + `diag()` + `quota_banner`)가 **부분적으로만 wiring 되어** 운영자가 재현/디버그/예산 추적을 하기 어려운 상태. 본 audit 은 모든 누락 지점을 매트릭스로 정착시키고 P0/P1/P2 로 우선순위화한다.

## 2. 명명 결정 — `outer_loop` → `self_improving_loop`

### 2.1 문제

기존 식별자 `outer_loop` 가 **무엇을 하는 루프인지** 폴더패스/파일명/식별자만으로 식별 불가. "outer" 는 위치 관계 표현일 뿐, 의도(intent) 가 드러나지 않음. 사용자/LLM 이 작성·참조 시 혼선.

본 시스템의 실제 동작:
- `autoresearch/train.py` — gen N → gen N+1 fitness 측정 → ratchet
- `plugins/seed_pipeline/` (rename 예정 → `seed_generation/`) — gen N+1 후보 생성 → debate → evolve → survivors
- `plugins/petri_audit/` — gen N 의 18-dim 평가
- 세대 간 fitness ratchet 으로 **agent 가 자신을 개선** — 이것이 본질

### 2.2 결정

| Aspect | Before | After |
|---|---|---|
| Python module | `core/config/outer_loop.py` | `core/config/self_improving_loop.py` |
| Class | `OuterLoopConfig` / `OuterLoopBindings` | `SelfImprovingLoopConfig` / `SelfImprovingLoopBindings` |
| Loader fn | `load_outer_loop_config()` | `load_self_improving_loop_config()` |
| TOML section | `[outer_loop.*]` | `[self_improving_loop.*]` |
| Runtime dir | `~/.geode/outer-loop/` | `~/.geode/self-improving-loop/` |
| Env var | `OUTER_LOOP_HOME` | `SELF_IMPROVING_LOOP_HOME` |
| Docs | "outer loop" prose | "self-improving loop" prose |

### 2.3 영향 범위

| Identifier | 등장 파일 수 |
|---|---:|
| `outer_loop` (snake) | 26 |
| `outer-loop` (kebab) | 34 |
| `OuterLoop` (PascalCase) | 3 |
| **총** | **~63** (중복 제거 후) |

### 2.4 마이그레이션 정책

- TOML 키는 **breaking** — 사용자가 `~/.geode/config.toml` 에 `[outer_loop.*]` 를 적었다면 ValueError. 현재 사용자는 빈 섹션이므로 영향 0.
- Runtime dir 은 **자동 마이그레이션 가능** — 시작 시 구 경로 발견하면 새 경로로 rename + 1회성 WARNING.
- Class/모듈 경로는 **외부 export 없음** (plugins/autoresearch 내부 호출만) — 일괄 변경 OK.

## 3. 활성 sink 인벤토리

현재 데이터가 실제로 기록되고 있는 채널 (드라이런 검증 완료, smoke log: `~/.geode/diagnostics/smoke/2026-05-19T0729-autoresearch-dry-run.log`):

| Sink | 경로 | Writer | 검증 상태 |
|---|---|---|---|
| diagnostics ledger | `~/.geode/diagnostics/<YYYY-MM>.log` | `core.audit.diagnostics.diag()` × 6 사이트 | ✅ |
| serve daemon log | `~/.geode/logs/serve.log` | Python logging root handler | ✅ (docs cleanup 2026-05-19 후) |
| self-improving-loop run index | `~/.geode/self-improving-loop/sessions.jsonl` (rename 예정) | `autoresearch._append_sessions_index` + `seed_generation.Pipeline._append_session_index` | ✅ 직전 dry-run entry 1건 |
| self-improving-loop event journal | `~/.geode/self-improving-loop/<session_id>/journal.jsonl` (rename 예정) | `SessionJournal.append` | ⚠️ event 종류 빈약 |
| token usage ledger | `~/.geode/usage/<YYYY-MM>.jsonl` | token tracker | ✅ |
| RunLog | `~/.geode/runs/{key}.jsonl` | `AgenticLoop` | ✅ |
| SessionTranscript | `~/.geode/journal/transcripts/<project>/<session>.jsonl` | `core.runtime_state.transcript` | ✅ |
| petri raw eval | `~/.geode/petri/logs/*.eval` | inspect_ai subprocess | ✅ |
| autoresearch stdout summary | console 45-line block | `print` in `train.py` | ✅ |
| autoresearch RUN_LOG | `~/.geode/self-improving-loop/<session>/audit.log` (rename 예정) | subprocess stdout+stderr | ✅ |

## 4. 누락 매트릭스 — Pipeline 이벤트 × 관측성 채널

표기 약속: ✅ 기록됨 / ⚠️ 일부 / ❌ 무관측 / 🚨 wiring 결손

| Pipeline Event | stdout | diag() | SessionJournal | sessions.jsonl | Gap |
|---|---|---|---|---|---|
| **Config loader** (`core/config/outer_loop.py`) | | | | | |
| `[self_improving_loop]` 부재 → default 사용 | ❌ | ❌ | ❌ | ❌ | 운영자는 어떤 값으로 돌았는지 알 수 없음 |
| Pydantic ValueError (typo 키) | ✅ trace | ❌ | ❌ | ❌ | log 만, journal 무 |
| OSError 읽기 실패 | ❌ | ❌ | ❌ | ❌ | `log.warning` 뿐 |
| **Subscription guard** (`plugins/petri_audit/credential_source.py`) | | | | | |
| `outer_loop_fallback_policy` ImportError | ❌ | ❌ | ❌ | ❌ | 조용히 `True` 반환 — 잘못된 fallback 정책으로 진행 가능 |
| `CredentialResolutionError(subscription_only=True)` | ✅ | ❌ | ❌ | ❌ | 사용자 본 메시지만, journal 무 |
| OAuth account swap (user_id 변화) | ❌ | ❌ | ❌ | ❌ | 어떤 계정으로 돌았는지 추적 불가 |
| **Quota banner** (`core/cli/quota_banner.py`) | | | | | |
| `set_state` writer | — | — | — | — | 🚨 **production code 0 호출** — 설치만 되고 데이터 미공급 |
| `trip_abort` writer | — | — | — | — | 🚨 **production code 0 호출** — abort 가 UI 에 반영 안 됨 |
| Tier 전이 (green→yellow→red) | ❌ | ❌ | ❌ | ❌ | 임계 통과 시점 무관측 |
| **autoresearch run** (`autoresearch/train.py`) | | | | | |
| `audit_started` | ⚠️ implicit | ❌ | ❌ | ❌ | journal 에 시작 이벤트 없음 — finished 만 |
| 어떤 config 값으로 돌았는가 | ⚠️ 일부 필드만 console | ❌ | ❌ | ❌ | 재현 불가능 |
| Subprocess timeout 발생 | ⚠️ RuntimeError raise | ❌ | ❌ | ❌ | journal 무 — 다음 run 에서 직전 timeout 이유 모름 |
| Per-dim score 분포 | ✅ console | ❌ | ❌ | ⚠️ aggregate fitness 만 | dim_scores 가 journal payload 에 없음 |
| Wrapper override active | ✅ console | ❌ | ❌ | ❌ | journal 무 |
| Baseline gate (gen-0) | ✅ console | ❌ | ❌ | ❌ | journal 무 |
| Run duration breakdown | ✅ console | ❌ | ❌ | ❌ | audit_seconds/total_seconds journal 무 |
| `audit_finished` | ✅ | ❌ | ✅ | ✅ | OK (3중 기록 → §6 dedup 항목) |
| **seed_generation orchestrator** (`plugins/seed_pipeline/orchestrator.py`, rename 예정) | | | | | |
| `pipeline_started` | ✅ | ❌ | ✅ (minimal) | ❌ | OK |
| Per-stage (S0..S11) 전이 | ⚠️ log.info | ❌ | ❌ | ❌ | 단계별 진행률 무관측 |
| Agent registration 충돌/재등록 | ⚠️ log.warning | ❌ | ❌ | ❌ | journal 무 |
| Cost preview vs 실제 비용 | ⚠️ console preview | ❌ | ❌ | ⚠️ usd_spent 만 | 예측-실측 divergence 추적 불가 |
| Pre-flight 게이트 실패 | ✅ console + report | ❌ | ❌ | ❌ | journal 무 |
| `pipeline_finished` | ✅ | ❌ | ✅ | ✅ | OK (3중 기록 → §6 dedup) |
| **LLM provider** (`core/llm/providers/anthropic.py`) | | | | | |
| BadRequest | ❌ | ✅ | ❌ | ❌ | OK (diag) |
| call_failed (catch-all) | ❌ | ✅ | ❌ | ❌ | OK |
| **529 Overloaded** | ⚠️ | ⚠️ | ❌ | ❌ | 🚨 `RETRYABLE_ERRORS` 에 명시 X — `InternalServerError` 로 분류되는지 SDK 매핑 미확정 |
| Retry 성공 (after fail) | ❌ | ❌ | ❌ | ❌ | "결국 됐는지" 신호 무 |
| **petri runner/target** (`plugins/petri_audit/targets/geode_target.py`) | | | | | |
| Run entry | ❌ | ✅ | ❌ | ❌ | OK |
| audit_mode apply 성공/실패 | ❌ | ✅ | ❌ | ❌ | OK |
| Per-rollout 결과 | ❌ | ❌ | ❌ | ❌ | 샘플별 관측 무 |

## 5. 에러 swallow 매트릭스

silent failure 가 가능한 지점 — 사용자가 잘못된 fallback 으로 진행되는데 알지 못함.

| 위치 | 조건 | swallow 결과 | 영향 | 권장 조치 |
|---|---|---|---|---|
| `autoresearch/train.py:124` | `_get_self_improving_loop_config()` `except Exception` (rename 후) | SimpleNamespace fallback | config 가 망가졌는데 default 로 조용히 진행 | `diag()` + journal event 추가 |
| `autoresearch/train.py:1010` | `except ImportError` (SessionJournal) | journal append skip | observability silent off | 무거운 변경 없이 `diag()` fallback |
| `plugins/seed_pipeline/cli.py:80` | `_get_seed_generation_config()` `except Exception` (rename 후) | SimpleNamespace fallback | 동일 위험 | 동일 |
| `plugins/petri_audit/credential_source.py:183` | `self_improving_loop_fallback_policy()` ImportError (rename 후) | return True | fallback 정책이 사용자 의도와 무관하게 True | `diag()` 추가 |
| `plugins/petri_audit/credential_source.py:187` | 동 함수 일반 Exception | `log.warning` + True | OK (log 있음) | — |
| `plugins/petri_audit/user_overrides.py:142` | `_read_role_from_self_improving_loop` ImportError (rename 후) | empty dict | legacy petri.toml 로 silent fallback | `diag()` 추가 |
| `core/cli/prompt_session.py:144` | banner 초기화 `except Exception` | `warn=0.5, abort=0.9` default | log.warning 있음 — OK | — |

## 6. 중복(dedup) 매트릭스

같은 데이터가 여러 sink 에 기록되어 drift risk 가 있는 항목.

| 데이터 | Sink 1 | Sink 2 | Sink 3 | Drift Risk | 권장 SoT |
|---|---|---|---|---|---|
| `audit_finished` fitness | console (`print`) | `sessions.jsonl` (run-level index) | `journal.jsonl` (event stream) | 한 곳만 업데이트되면 inconsistent | **`sessions.jsonl` 을 SoT**, journal/console 은 reference |
| `pipeline_started/finished` | console | `journal.jsonl` | `sessions.jsonl` | 동일 | 동일 |
| Subprocess output | RUN_LOG (file) | console echo | — | 둘 다 같은 stream → 낮음 | — |
| Pre-flight findings | console (rendered) | `PreFlightReport` object | (journal 누락) | divergence 가능 | console 은 rendered, report 는 raw — 역할 명확 |

## 7. 우선순위 + 작업 계획

영향 × 노력 × 검증 가능성 기준.

| # | 항목 | 영향 | 노력 | 우선순위 | 비고 |
|---|---|---|---|---|---|
| 1 | **명명 rename** `outer_loop` → `self_improving_loop` (63 파일) | 中 (intent clarity) | 중 | **PR-η1a** | grep+Edit. CI 가 보호. |
| 2 | **명명 rename** `seed_pipeline` → `seed_generation` (71 파일) | 中 | 중 | **PR-η1b** | η1a 직후. |
| 3 | **Quota banner write-path 결손** | 🚨 사용자 UX 신호 부재 | 중 | **P0** | anthropic provider hook + token tracker tap |
| 4 | **autoresearch journal 이벤트 빈약** | 高 (재현/디버그 불가) | 소 | **P0** | 5-7 줄 추가 |
| 5 | **audit_finished 3중 기록 SoT 통일** | 中 | 소 | **P0** | sessions.jsonl 을 SoT, journal/console reference |
| 6 | **529 Overloaded retry 정책 미정** | 中 | 중 | **P1** | RETRYABLE_ERRORS 확장 + 분류 테스트 |
| 7 | **subscription guard journal emit 없음** | 中 | 소 | **P1** | 3 사이트 SessionJournal.append |
| 8 | **seed_generation per-stage journal emit 없음** | 中 | 중 | **P1** | orchestrator 7 stage hook |
| 9 | **config loader default 사용 통보 없음** | 低 | 소 | **P2** | 1 줄 print + 1 journal event |
| 10 | **cost preview vs 실측 divergence 추적 없음** | 低 | 중 | **P2** | — |
| 11 | **Pre-flight 실패 journal emit 없음** | 低 | 소 | **P2** | — |

### 작업 순서 (PR 분할)

```
PR-η1a:  outer_loop → self_improving_loop rename (63 파일)
         + docs/setup.* + README.md /tmp → ~/.geode/logs/serve.log cleanup (3 파일)
         + 본 audit MD 정착 (1 파일)
              ↓ merge to develop, smoke pass

PR-η1b:  seed_pipeline → seed_generation rename (71 파일)
              ↓ merge to develop, smoke pass

PR-P0a:  audit_finished dedup (sessions.jsonl SoT 통일)
              ↓

PR-P0b:  autoresearch journal events 확장 (audit_started/config_snapshot/
         subprocess_started/timeout/baseline_decision/per_dim_scores)
              ↓

PR-P0c:  quota banner writer wiring (token tracker tap + trip_abort hook)
              ↓ smoke verify banner tier transitions

PR-P1a:  529 Overloaded retry policy
PR-P1b:  subscription guard journal emit
PR-P1c:  seed_generation per-stage journal emit
              ↓

PR-P2:   config-default notice + cost divergence + pre-flight journal
```

## 8. 부록 — Smoke 자료

- **2026-05-19 dry-run smoke log**: `~/.geode/diagnostics/smoke/2026-05-19T0729-autoresearch-dry-run.log`
- **세션 인덱스 entry**: `~/.geode/outer-loop/sessions.jsonl` (마지막 줄, session_id=`2026-05-18T2230Z-6b156b`)
- **세션 journal**: `~/.geode/outer-loop/2026-05-18T2230Z-6b156b/journal.jsonl` — 1 event 만 (`audit_finished`) — §4 의 누락 가설 dry-run 으로 검증됨

(rename 후 sessions.jsonl + journal.jsonl 의 디스크 경로는 `~/.geode/self-improving-loop/` 로 이전. 본 부록의 참조는 rename 이전 시점 기록.)
