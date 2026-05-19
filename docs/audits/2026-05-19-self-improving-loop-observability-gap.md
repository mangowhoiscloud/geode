# Self-Improving Loop — Observability Gap Audit (2026-05-19)

> Source: 2026-05-19 Phase α–δ config consolidation (PR-δ1 #1325 + PR-δ2 #1323)
> 직후 dry-run 스모크 + 관측성 sink/event 전수 스캔의 결과.
> 본 문서는 **(1) 명명 결정**, **(2) 현재 활성 sink 인벤토리**,
> **(3) 누락 매트릭스**, **(4) 에러 swallow 매트릭스**,
> **(5) 중복(dedup) 매트릭스**, **(6) 우선순위 + 작업 계획** 을
> 단일 SoT 로 정착시킵니다. 후속 구현 PR 들은 이 문서를 참조합니다.

## 1. 한 줄 요약

`autoresearch + seed_generation + petri` 3-축이 합세해서 **세대 간 자기 개선 (self-improving)** 을 수행하는 루프이지만, 관측성 인프라(`SessionJournal` + `sessions.jsonl` + `diag()` + `quota_banner`)가 **부분적으로만 wiring 되어** 운영자가 재현/디버그/예산 추적을 하기 어려운 상태. 본 audit 은 모든 누락 지점을 매트릭스로 정착시키고 P0/P1/P2 로 우선순위화한다.

## 2. 명명 결정 — 두 건의 rename

본 audit 은 두 건의 명명 결정을 묶어서 처리한다. 원칙은 같다 — **폴더패스/파일명/식별자만으로 무엇을 하는 모듈인지 식별 가능해야 한다** ([[feedback_explicit_naming]]).

### 2.1 `outer_loop` → `self_improving_loop`

기존 `outer_loop` 는 위치 관계만 표현 (autoresearch + seed + petri 를 감싸는 "outer" 루프). 실제 본질은 gen N → gen N+1 fitness ratcheting 으로 **agent 가 자신을 개선** 하는 것이므로 의도가 드러나는 `self_improving_loop` 채택.

| Aspect | Before | After |
|---|---|---|
| Python module | `core/config/outer_loop.py` | `core/config/self_improving_loop.py` |
| Class | `OuterLoopConfig` / `OuterLoopBindings` | `SelfImprovingLoopConfig` / `SelfImprovingLoopBindings` |
| Loader fn | `load_outer_loop_config()` | `load_self_improving_loop_config()` |
| TOML section | `[outer_loop.*]` | `[self_improving_loop.*]` |
| Runtime dir | `~/.geode/outer-loop/` | `~/.geode/self-improving-loop/` |
| Env var | `OUTER_LOOP_HOME` | `SELF_IMPROVING_LOOP_HOME` |
| Docs prose | "outer loop" | "self-improving loop" |
| 영향 파일 수 | — | **45** |

### 2.2 `seed_pipeline` → `seed_generation`

기존 `seed_pipeline` 의 "pipeline" 은 일반 추상명사. 실제 동작은 8-stage 후보 생성 (S0 manifest → S1 generator → S2 critic → S3 evolver → S4-S8 ranker/pilot/proximity/meta_reviewer/tournament) 으로 결국 **seed candidate 를 생성** 하는 작업. 따라서 도메인 동사+명사 패턴 `seed_generation` 채택.

| Aspect | Before | After |
|---|---|---|
| Python package | `plugins/seed_pipeline/` | `plugins/seed_generation/` |
| Plugin TOML | `plugins/seed_pipeline/seed_pipeline.plugin.toml` | `plugins/seed_generation/seed_generation.plugin.toml` |
| Class | `SeedPipelineConfig` / `SeedPipelineManifest` | `SeedGenerationConfig` / `SeedGenerationManifest` |
| TOML section | `[self_improving_loop.seed_pipeline]` | `[self_improving_loop.seed_generation]` |
| Skill dir | `.geode/skills/seed-pipeline-cycle/` | `.geode/skills/seed-generation-cycle/` |
| Test dir | `tests/plugins/seed_pipeline/` | `tests/plugins/seed_generation/` |
| CLI command | `audit-seeds` (변경 없음 — 이미 명시적) | `audit-seeds` |
| 영향 파일 수 | — | **72** |

### 2.3 마이그레이션 정책 (양쪽 공통)

- **TOML 키**: breaking — 사용자가 구 키를 적었다면 pydantic ValueError. 현재 사용자 `~/.geode/config.toml` 에는 outer-loop/seed 관련 섹션 없음 → 영향 0.
- **Runtime dir**: 자동 마이그레이션은 별도 PR (P0+ 이후). 신규 run 은 새 경로 사용, 구 경로는 read-only 로 보존.
- **CHANGELOG / 2026-05-15 audits**: historical revisionism 회피 차원에서 verbatim 보존 (rename 적용 X).
- **Class/모듈 경로**: 외부 export 없음 (plugins/autoresearch 내부 호출만) — 일괄 변경 OK.

## 3. 활성 sink 인벤토리

현재 데이터가 실제로 기록되고 있는 채널 (드라이런 검증 완료, smoke log: `~/.geode/diagnostics/smoke/2026-05-19T0729-autoresearch-dry-run.log`):

| Sink | 경로 | Writer | 검증 상태 |
|---|---|---|---|
| diagnostics ledger | `~/.geode/diagnostics/<YYYY-MM>.log` | `core.audit.diagnostics.diag()` × 6 사이트 | ✅ |
| serve daemon log | `~/.geode/logs/serve.log` | Python logging root handler | ✅ (docs cleanup 2026-05-19 후) |
| self-improving-loop run index | `~/.geode/self-improving-loop/sessions.jsonl` | `autoresearch._append_sessions_index` + `seed_generation.Pipeline._append_session_index` | ✅ 직전 dry-run entry 1건 |
| self-improving-loop event journal | `~/.geode/self-improving-loop/<session_id>/journal.jsonl` | `SessionJournal.append` | ⚠️ event 종류 빈약 |
| token usage ledger | `~/.geode/usage/<YYYY-MM>.jsonl` | token tracker | ✅ |
| RunLog | `~/.geode/runs/{key}.jsonl` | `AgenticLoop` | ✅ |
| SessionTranscript | `~/.geode/journal/transcripts/<project>/<session>.jsonl` | `core.runtime_state.transcript` | ✅ |
| petri raw eval | `~/.geode/petri/logs/*.eval` | inspect_ai subprocess | ✅ |
| autoresearch stdout summary | console 45-line block | `print` in `train.py` | ✅ |
| autoresearch RUN_LOG | `~/.geode/self-improving-loop/<session>/audit.log` | subprocess stdout+stderr | ✅ |

## 4. 누락 매트릭스 — Pipeline 이벤트 × 관측성 채널

표기 약속: ✅ 기록됨 / ⚠️ 일부 / ❌ 무관측 / 🚨 wiring 결손

| Pipeline Event | stdout | diag() | SessionJournal | sessions.jsonl | Gap |
|---|---|---|---|---|---|
| **Config loader** (`core/config/self_improving_loop.py`) | | | | | |
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
| **seed_generation orchestrator** (`plugins/seed_generation/orchestrator.py`) | | | | | |
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
| `autoresearch/train.py:124` | `_get_autoresearch_config()` `except Exception` | SimpleNamespace fallback | config 가 망가졌는데 default 로 조용히 진행 | `diag()` + journal event 추가 |
| `autoresearch/train.py:1010` | `except ImportError` (SessionJournal) | journal append skip | observability silent off | 무거운 변경 없이 `diag()` fallback |
| `plugins/seed_generation/cli.py:80` | `_get_seed_generation_config()` `except Exception` | SimpleNamespace fallback | 동일 위험 | 동일 |
| `plugins/petri_audit/credential_source.py:183` | `self_improving_loop_fallback_policy()` ImportError | return True | fallback 정책이 사용자 의도와 무관하게 True | `diag()` 추가 |
| `plugins/petri_audit/credential_source.py:187` | 동 함수 일반 Exception | `log.warning` + True | OK (log 있음) | — |
| `plugins/petri_audit/user_overrides.py:142` | `_read_role_from_self_improving_loop` ImportError | empty dict | legacy petri.toml 로 silent fallback | `diag()` 추가 |
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
| 1 | **명명 rename** `outer_loop` → `self_improving_loop` (45 파일) | 中 (intent clarity) | 중 | **PR-η1a** ✅ | commit `7e6e969e`. |
| 2 | **명명 rename** `seed_pipeline` → `seed_generation` (72 파일) | 中 | 중 | **PR-η1b** ✅ | η1a 후속, 본 PR 에 동봉. |
| 3 | **audit_finished 3중 기록 SoT 통일** | 中 | 소 | **P0a** ✅ | commit `86f3b4db`. |
| 4 | **autoresearch journal 이벤트 빈약** | 高 (재현/디버그 불가) | 소 | **P0b** ✅ | 8 이벤트 추가 (audit_started/config_snapshot/wrapper_override_dumped/subprocess_started/finished/timeout/audit_failed/baseline_decision/per_dim_scores), 6 새 테스트, Codex cross-LLM verify pass. |
| 5 | **Quota banner write-path 결손** | 🚨 사용자 UX 신호 부재 | 중 | **P0c** ✅ | anthropic httpx event_hook + CredentialResolutionError trip_abort + 6 tests, Codex cross-LLM 1-pass clean. |
| 6 | **529 Overloaded retry 정책 미정** | 高 (조사 결과 실제 silent fail 이었음) | 소 | **P1a** ✅ | `OverloadedError` 가 `InternalServerError` 의 sibling 임을 발견 — RETRYABLE_ERRORS 에 추가 + lazy resolver 가 `_exceptions` 까지 fallthrough + `_on_retry_journal_emit` 으로 retry 마다 `llm_retry` event emit + 6 tests. |
| 7 | **subscription guard journal emit 없음** | 中 | 소 | **P1b** ✅ | 3 emit 사이트 (credential_subscription_abort + fallback_policy_resolved + petri_role_legacy_fallback) + 5 새 tests + Codex clean. |
| 8 | **seed_generation per-stage journal emit 없음** | 中 | 중 | **P1c** | orchestrator S0-S11 hook |
| 9 | **config loader default 사용 통보 없음** | 低 | 소 | **P2** | 1 journal event |
| 10 | **cost preview vs 실측 divergence 추적 없음** | 低 | 중 | **P2** | — |
| 11 | **Pre-flight 실패 journal emit 없음** | 低 | 소 | **P2** | — |

### 작업 순서 (PR 분할)

```
PR-η1a:  outer_loop → self_improving_loop rename (45 파일)         ✅ DONE
         + docs/setup.* + README.md /tmp → ~/.geode/logs/serve.log cleanup
         + 본 audit MD 정착
              commit 7e6e969e

PR-η1b:  seed_pipeline → seed_generation rename (72 파일)           ✅ commit d7d89a11
              ↓

PR-P0a:  audit_finished dedup (sessions.jsonl SoT 통일)              ✅ commit 86f3b4db
              ↓

PR-P0b:  autoresearch journal events 확장 (audit_started/config_snapshot/
         subprocess_started/timeout/baseline_decision/per_dim_scores/
         audit_failed + Codex MCP cross-LLM verify)               ◀ next commit
              ↓

PR-P0c:  quota banner writer wiring (httpx event_hook + trip_abort)  ◀ this commit
              ↓ smoke verify banner tier transitions

PR-P1a:  529 Overloaded retry policy
PR-P1b:  subscription guard journal emit
PR-P1c:  seed_generation per-stage journal emit
              ↓

PR-P2:   config-default notice + cost divergence + pre-flight journal
```

## 8. 부록 — Smoke 자료

- **2026-05-19T0729 dry-run smoke (pre-rename)**: `~/.geode/diagnostics/smoke/2026-05-19T0729-autoresearch-dry-run.log`
- **2026-05-19T0800 dry-run smoke (post η1a)**: `~/.geode/diagnostics/smoke/2026-05-19T0800-autoresearch-dry-run-post-rename.log`
- **2026-05-19T0815 dry-run smoke (post η1b)**: `~/.geode/diagnostics/smoke/2026-05-19T0815-autoresearch-dry-run-post-seed-rename.log`
- **legacy 세션 (rename 이전)**: `~/.geode/outer-loop/sessions.jsonl` + `~/.geode/outer-loop/2026-05-18T2230Z-6b156b/journal.jsonl` — 1 event 만 (`audit_finished`)
- **신규 세션 (rename 이후)**: `~/.geode/self-improving-loop/sessions.jsonl` + `~/.geode/self-improving-loop/2026-05-18T2300Z-fe4b1a/journal.jsonl` + `~/.geode/self-improving-loop/2026-05-18T2308Z-e61e35/journal.jsonl`
