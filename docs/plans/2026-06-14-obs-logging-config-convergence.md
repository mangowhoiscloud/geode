# Observability / Logging / Config convergence + llms.txt version sync (pre-v1.0)

> **작성**: 2026-06-14
> **목적**: v1.0.0 전, 로깅·설정·llms.txt 동기화를 프론티어 에이전트 CLI에 수렴시킨다. 코드베이스 스캔 결과 GEODE는 **typed ActivityRow·pydantic Settings·OTel 배선은 선도**, **구조화 로깅·자동 redaction·config TOML 매핑·검증은 지연**.
> **검증**: ruff/format/mypy/lint-imports/pytest + Codex MCP(gpt-5.5) review.
> **SoT**: 이 문서. **근거**: 2-차원 frontier 감사(observability/logging · config) + 직접 spot-verify(TOML 미매핑 6/6·validator 2개·openclaw tslog→JSONL+자동 redaction 확인).

---

## 0. 발견 카탈로그 (검증됨)

| ID | 항목 | GEODE 근거 | 프론티어 근거 | 등급 |
|----|------|-----------|--------------|------|
| A1 | 텍스트 로깅(구조화 JSON 미지원) | `core/observability/logging_config.py:33` `_FILE_FORMAT` | openclaw `src/logging/logger.ts`(tslog→`JSON.stringify`), paperclip pino | BEHIND |
| A2 | 시크릿 redaction 수동(소수 sink) — **로그 누수 위험** | `core/observability/redaction.py:27` `redact_secrets`는 호출형 | openclaw/hermes 로거-레벨 자동 | BEHIND(보안) |
| A3 | trace↔log 미결합 | OTel span과 로그 분리 | openclaw 로그 JSON에 traceId/spanId | BEHIND |
| C1 | ~17 Settings 필드 TOML 매핑 누락 | `core/config/__init__.py:52` `_TOML_TO_SETTINGS` (cost_limit_usd/hitl_level/scheduler_*/session_* 6/6 확인) | hermes 전 키 YAML 매핑 | BEHIND |
| D1 | config 검증 미흡(`@field_validator` 2개·`Field(ge/le)` 0개) | `core/config/_settings.py` | — | BEHIND(correctness) |
| L1 | **llms.txt/llms-full.txt stale** — "v0.99.189"인데 현재 v0.99.201 | `site/public/llms.txt` 헤더 | (자체 SoT drift) | 동기화 갭 |

**선도 유지(무변경)**: typed ActivityRow 62/62, pydantic BaseSettings 단일 클래스, `geode config explain`, OTel(traceloop) 배선.

---

## 1. 단계별 실행

### Phase A — 구조화 로깅 + 자동 redaction (A1·A2) — **P0(보안 포함)**

**Socratic**: Q2 안 하면? 시크릿이 로그/회전파일에 평문 적재(누수), 기계 필터 불가. Q4 최소? `configure_logging`에 (1) JSON 포매터 옵트인 + (2) **RedactingFilter**(자동) 추가 — 호출처 240파일 무변경. Q5 3+? openclaw/paperclip/hermes 전부 자동 redaction + 2/3 구조화.

구현:
1. `core/observability/logging_config.py`:
   - `_RedactingFilter(logging.Filter)` — `record.getMessage()`(+`record.args`) 통과분에 `redact_secrets` 적용. **양 핸들러(stream+file)에 부착** → 자동.
   - `_JsonFormatter(logging.Formatter)` — `{ts, level, logger, msg, ...record fields}` JSON 한 줄. 활성: `GEODE_LOG_FORMAT=json` env(또는 Settings `log_format`). 기본 `text`(back-compat). file 핸들러는 json 모드 시 JSON, console은 가독성상 text 유지(openclaw도 console=pretty/file=jsonl).
   - mode-spec에 format 선택 반영.
2. 가드: `tests/core/observability/test_logging_redaction.py` — (a) `sk-ant-...`/`sk-proj-...` 토큰이 emit→handler 출력에서 `[REDACTED]`, (b) JSON 모드 한 줄 valid JSON + 필드 존재, (c) text 모드 기본 유지.

**범위 주의**: A3(trace-context-in-logs)는 OTel span 활성 시에만 의미 + 더 큰 변경 → **Phase A에선 JSON 포매터에 `trace_id`/`span_id` 슬롯만 비워두고**, span 주입 Filter는 후속(OTel 상시화와 함께). 본 PR은 A1·A2.

### Phase C — config TOML 매핑 완성 (C1) — **P1(저위험·고ROI)**

`_TOML_TO_SETTINGS`에 누락 필드 추가 → operator가 `.geode/config.toml`로 설정 가능. **구현 전 각 필드 재검증**(Settings에 실존 + 현재 미매핑 + env-only 의도(api_key 류)는 제외). 후보(검증 후 확정): cost_limit_usd, hitl_level, plan_auto_execute, ensemble_mode, computer_use_enabled, scheduler_*(interval_s/auto_start/jitter), session_*(ttl_hours/storage_dir), notification_*, gateway_*, webhook_*, tool_offload_*, observation_mask_keep_rounds, checkpoint_db, postgres_url, redis_url, organization_fixture_dir, user_profile_dir. **보안 env-only 제외**: *_api_key.
가드: `test_toml_settings_map_coverage` — 모든 비-secret Settings 필드가 `_TOML_TO_SETTINGS`에 존재(미래 드리프트 방지).

### Phase D — config 검증자 (D1) — **P2(저위험 correctness)**

`_settings.py`에 pydantic validator 추가:
- temperature_* → `Field(ge=0.0, le=2.0)` 또는 `@field_validator` range.
- *_timeout / *_interval_s → `Field(gt=0)`.
- agentic_effort → enum validator({low,medium,high,max,xhigh} — 실제 허용셋 확인 후).
- hitl_level → `Field(ge=0, le=N)`.
가드: `test_settings_validation` — 범위 밖 값이 ValidationError.

### Phase L — llms.txt/llms-full.txt 버전 동기화 (L1) — **P1(사용자 지시)**

문제: `site/public/llms.txt`·`llms-full.txt` 헤더가 "Version v0.99.189"로 **12버전 stale**. 체인(pyproject→sync-stats→sot.ts→export-md)이 버전업마다 재생성 안 됨. committed SoT가 deployed와 drift(= CLAUDE.md "dual SoT without drift invariant" 위반).

구현:
1. **헤더 재동기화**: 현재 버전으로 committed 헤더 갱신(가능하면 `npm run sync-stats` 실행; full export-md는 build 필요하니 헤더 라인만이라도 pyproject 버전으로 정정).
2. **드리프트 가드**(핵심): `scripts/check_llms_version.py`(또는 sync-stats 검증 확장) — committed `site/public/llms.txt`+`llms-full.txt`의 `Version vX` 헤더가 pyproject `version`과 일치하지 않으면 fail. CI(ci.yml render-lint 또는 docs-check)에 배선 → 버전업 후 재생성 강제. 가드 테스트 포함.
3. docs-sync 절차에 "llms 헤더 동기화"를 5-location 옆에 명문화(CLAUDE.md docs-sync 표).

---

## 2. 검증
각 Phase: ruff/format/mypy(scripts/ 포함)/lint-imports/pytest + Codex(gpt-5.5). 로깅은 핸들러 출력 캡처 가드, config는 ValidationError 가드, llms는 버전-매칭 가드.

## 3. Out-of-scope (보류)
- A3 trace-context-in-logs 전면 배선 + OTel 상시화 → 별도(span 주입 Filter).
- ActivityRow → OTel GenAI Semantic Conventions 매핑(표준 정렬) → 대형, 별도 sprint.
- config trust-sandbox(Codex `allow_managed_hooks_only` 류) → org-SoC 기능, v1.0 후.
- auxiliary-task별 model config 표면(hermes 20+) → 수요 확인 후.

## 4. Status
| Phase | 상태 |
|---|---|
| A — 구조화 로깅 + 자동 redaction | DONE — `_RedactingTextFormatter`(양 핸들러 자동) + `_JsonFormatter`(`GEODE_LOG_FORMAT=json` 옵트인). 가드 4 테스트. |
| C — TOML 매핑 완성 | DONE — `_TOML_TO_SETTINGS` 48필드 추가(73 매핑 + 3 env-only secret = 76 전체). parity 가드(`test_config_centralization`). |
| D — config 검증자 | DONE — timeout/interval `>0` + agentic_effort enum validator. temperature_*는 이미 native `Field(ge/le)`라 중복 validator 제거(감사 "Field 0개" 정정). |
| L — llms.txt 버전 동기화 + 가드 | DONE — `scripts/check_llms_version.py`(check + `--fix`), ci.yml ratchet 배선, 가드 4 테스트, CLAUDE.md docs-sync 행. docs-sync에서 sync-stats 재생성 + `--fix`. |

**감사 정정**: 발견 D1의 "`Field(ge/le)` 0개"는 부정확 — temperature_* 4필드는 이미 `Field(ge=0.0, le=2.0)`. 실제 미검증 표면은 timeout 4 + interval 3 + agentic_effort. 중복 validator를 만들지 않고 plain 필드만 가드.
