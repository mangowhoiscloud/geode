# ADR-011: .geode 시스템 고도화

## Status

Proposed (2026-03-17)

## Context

GEODE의 `.geode/` 디렉토리 시스템은 v0.14.0까지 점진적으로 성장했다. 현재 `~/.geode/`(글로벌), `.geode/`(프로젝트 로컬), `.claude/`(Claude Code 호환) 3곳에 설정과 상태가 분산되어 있다.

프론티어 에이전트 시스템(Claude Code, Karpathy autoresearch, OpenClaw)과 비교하면 다음 Gap이 존재한다:

1. **설정 캐스케이드 부재**: `Settings`가 env와 `.env` 파일만 처리. 프로젝트별/글로벌 `config.toml` 없음.
2. **실행 이력 단절**: `RunLog`에 기록하지만 다음 실행 컨텍스트에 자동 주입하지 않음.
3. **비용 추적 단절**: `LLMUsageAccumulator`가 세션 내에서만 유지. 세션 간 누적 비용 추적 없음.
4. **Agent Reflection 부재**: 에이전트가 자신의 실행 결과로부터 학습하는 폐쇄 루프 없음.
5. **초기화 UX 부재**: 신규 프로젝트에서 `.geode/` 구조를 자동 생성하는 `geode init` 없음.

상세 리서치: `docs/plans/research-geode-enhancement.md`

## Decision

3단계(Phase)로 `.geode/` 시스템을 고도화한다.

### Phase 1: Config Cascade + Run History Injection + `geode init` (1-2일)

**Config Cascade** -- TOML 기반 설정 파일 도입.

```
우선순위 (높음 → 낮음):
  CLI 인자 > 환경변수 > .geode/config.toml > ~/.geode/config.toml > 기본값
```

`config.toml` 스키마:

```toml
[llm]
primary_model = "claude-opus-4-6"
secondary_model = "gpt-5.4"
temperature = 0.7

[output]
language = "ko"
format = "concise"     # concise | detailed | json
verbose = false

[pipeline]
confidence_threshold = 0.7
max_iterations = 5

[cost]
monthly_budget_usd = 50.0
warning_threshold_pct = 80
```

`Settings` 클래스를 확장하여 TOML 파일을 `model_config`의 `toml_file` 소스로 추가한다. Pydantic Settings v2의 `toml_file` 지원을 활용.

**Run History Context Injection** -- `ContextAssembler.assemble()`에서 최근 `RunLog` 3건을 P6 Context Budget 패턴으로 1줄 요약 주입.

```python
# 주입 형식 (P6 L2 추출):
# "Recent: Berserk S/81.3 (2h ago) | Cowboy Bebop A/68.4 (1d ago)"
```

**`geode init`** -- Typer 서브커맨드로 `.geode/` + `.claude/` 구조 자동 생성.

### Phase 2: Cost Tracker + Agent Reflection + Cache Expiry (3-5일)

**Cost Tracker 영속화** -- `~/.geode/usage/YYYY-MM.jsonl` 월별 JSONL.

```jsonl
{"ts":1710000000,"model":"claude-opus-4-6","in":1200,"out":350,"cost":0.0148,"session":"abc123"}
```

`TokenTracker.record()`에서 JSONL append. `geode usage` 명령으로 월별/모델별 비용 조회.

**Agent Reflection** -- `PIPELINE_COMPLETE` Hook에서 실행 결과를 `learned.md`에 자동 기록.

```
반영 대상:
- 분석 IP별 Tier 변동 (이전 S → 현재 A → 경고)
- 자주 사용되는 규칙 (규칙 적중 횟수 추적)
- 실패 패턴 (timeout, API error 등 → 자동 회피 학습)
```

**Result Cache Expiry** -- 24시간 + prompt hash 기반 무효화.

### Phase 3: Workflow Persistence + Usage Dashboard (1-2주)

**Workflow Persistence** -- Plan Mode/Agentic Loop 진행 상태를 `.geode/workflows/`에 저장. 프로세스 재시작 후 `geode resume` 명령으로 재개.

**Usage Dashboard** -- `geode usage` 명령을 Rich 테이블/차트로 확장. 일별/모델별/IP별 비용 시각화.

## Alternatives Considered

### A. 단일 디렉토리 통합 (.geode/ only)

`.claude/`를 `.geode/`에 흡수하는 방안. Claude Code 호환성을 포기하게 되므로 기각. `.claude/`는 Claude Code의 CLAUDE.md/rules/skills 자동 로딩에 필수.

### B. SQLite 기반 상태 관리

JSONL/JSON 파일 대신 SQLite 단일 DB를 사용하는 방안. 장점: 쿼리/집계 용이, 트랜잭션 보장. 단점: 파일 기반 대비 디버깅 어려움, 텍스트 에디터로 직접 편집 불가, 추가 의존성. GEODE의 "설정은 텍스트 파일, 사람이 읽을 수 있어야 한다" 원칙에 위배되므로 기각.

### C. Redis/PostgreSQL 먼저 도입

`HybridSessionStore`가 이미 Redis/PostgreSQL URL 설정을 지원하지만, 현재 시뮬레이션 수준. 로컬 개발에서는 파일 기반이 더 적합. 프로덕션 배포 시 고려할 사항이므로 이번 스코프에서 제외.

### D. 전면 TOML 전환 (env 폐기)

`.env` + `GEODE_*` 환경변수를 완전히 폐기하고 TOML만 사용하는 방안. CI/CD 파이프라인과 Docker 환경에서 환경변수가 표준이므로 기각. 환경변수와 TOML의 공존이 최선.

## Consequences

### 긍정적

- **설정 투명성**: `config.toml`은 사람이 읽고 편집할 수 있는 프로젝트 설정 SOT
- **실행 연속성**: 이전 분석 결과가 다음 분석에 자동 반영 (P4 Ratchet 효과)
- **비용 가시성**: 월별 비용 추적으로 예산 초과 방지
- **학습 루프**: Agent Reflection으로 반복 실패 방지 (P5 실패 기록 보존)

### 부정적

- **복잡성 증가**: 설정 소스가 4개(CLI > env > project TOML > global TOML)로 증가. 디버깅 시 "어떤 설정이 어디서 왔는지" 추적 필요
- **마이그레이션**: 기존 env 기반 설정을 TOML로 이전하는 안내 필요 (강제 아님, 공존)

### 리스크

- TOML 파일 파싱 의존성 추가 (Python 3.11+ `tomllib` 내장이므로 무시 가능)
- RunLog 자동 주입 시 컨텍스트 윈도우 증가 (P6 Context Budget 1줄 요약으로 최소화)

## Implementation Plan

아래 `docs/plans/geode-enhancement-plan.md`에 상세 구현 계획 기술.

## References

- `docs/plans/research-geode-enhancement.md` -- 프론티어 리서치 결과
- `.claude/skills/karpathy-patterns/SKILL.md` -- P4 Ratchet, P6 Context Budget, P7 program.md
- `.claude/skills/openclaw-patterns/SKILL.md` -- Config Cascade, Atomic Store, Run Log JSONL
- `core/config.py` -- 현재 Pydantic Settings 구현
- `core/memory/context.py` -- ContextAssembler (주입 대상)
- `core/llm/token_tracker.py` -- TokenTracker (비용 추적 대상)
