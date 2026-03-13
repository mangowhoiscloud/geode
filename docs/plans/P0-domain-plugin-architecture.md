# P0: Domain Plugin Architecture — 범용 에이전트 프레임워크 전환

> **Priority**: P0 (Architecture)
> **Status**: Draft
> **Date**: 2026-03-13
> **Scope**: GEODE를 범용 자율 에이전트 프레임워크로 전환, 게임 IP 분석은 하나의 도메인 플러그인으로 분리

## 1. 현황 진단

### 1.1 도메인 결합도 측정

| 분류 | 모듈 수 | LOC | 비율 |
|------|---------|-----|------|
| INFRA (재사용 가능) | ~97 | ~21,000 | 81% |
| DOMAIN (게임 IP 전용) | ~23 | ~5,000 | 19% |
| **합계** | ~120 | ~26,000 | 100% |

### 1.2 도메인 결합 핫스팟 8곳

| # | 위치 | 결합 유형 | LOC |
|---|------|----------|-----|
| H1 | `core/nodes/analysts.py:29` | ANALYST_TYPES 하드코딩 | 446 |
| H2 | `core/nodes/evaluators.py` | EVALUATOR_AXES + 축 검증 | 579 |
| H3 | `core/nodes/scoring.py` | 가중치, 공식, Tier 임계값 | 495 |
| H4 | `core/nodes/synthesizer.py:52-94` | Decision Tree (D-E-F 축) | 377 |
| H5 | `core/state.py:19-34` | CauseLiteral, ActionLiteral | 278 |
| H6 | `core/config/evaluator_axes.yaml` | 14축 루브릭 (11/14 게임 전용) | 244 |
| H7 | `core/config/cause_actions.yaml` | 6 원인 → 5 행동 매핑 | 40 |
| H8 | `core/llm/prompts/*.md` (9 files) | 도메인 전용 프롬프트 | ~2,500 |

### 1.3 이미 재사용 가능한 인프라 (변경 불요)

```
core/cli/              — AgenticLoop, NLRouter, commands, search
core/llm/              — client, token_tracker, prompt_assembler
core/memory/           — 3-tier (org/project/session), hybrid
core/orchestration/    — hooks, planner, task_system, coalescing
core/automation/       — triggers, drift, feedback_loop, scheduler
core/verification/     — guardrails, biasbuster, cross_llm (일부 파라미터화 필요)
core/infrastructure/   — ports, adapters (LLM, auth)
core/extensibility/    — plugins, skills, agents, reports
core/tools/            — registry, policy, generic tools
core/ui/               — console, agentic_ui, panels
```

## 2. 목표 아키텍처

### 2.1 핵심 원칙

```
P1 (제약 기반): 도메인 플러그인이 수정할 수 있는 표면적을 DomainPort 인터페이스로 제한
P8 (Dumb Platform): 프레임워크는 라우팅 + 실행만, 도메인 로직은 플러그인에
P10 (Simplicity): 기존 Plugin/Skill/Port 패턴 재사용, 새 추상화 최소화
```

### 2.2 레이어 분리

```
┌─────────────────────────────────────────────────┐
│  L7: DOMAIN PLUGINS                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ game_ip  │ │ book_ip  │ │ custom_research  │ │
│  │ (built-in)│ │ (future) │ │ (user-defined)   │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│  L6: EXTENSIBILITY  — Plugins, Skills, Agents   │
│  L5: AUTOMATION     — Triggers, Drift, Feedback  │
│  L4: ORCHESTRATION  — Hooks, Planner, Tasks      │
│  L3: AGENTIC CORE   — AgenticLoop, Tools         │
│  L2: MEMORY         — 3-Tier + Hybrid             │
│  L1: FOUNDATION     — LLM, APIs, Ports, DI        │
├─────────────────────────────────────────────────┤
│  L0: PIPELINE ENGINE (domain-agnostic)           │
│  ┌──────────────────────────────────────────┐    │
│  │ StateGraph + GenericNodes + DomainPort DI │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### 2.3 DomainPort Protocol

```python
# core/infrastructure/ports/domain_port.py

class DomainPort(Protocol):
    """도메인 플러그인이 구현해야 하는 계약."""

    # --- Identity ---
    @property
    def name(self) -> str: ...           # "game_ip", "book_ip"
    @property
    def version(self) -> str: ...        # "1.0.0"

    # --- Analyst Configuration ---
    def get_analyst_types(self) -> list[str]: ...
    def get_analyst_prompt(self, analyst_type: str) -> tuple[str, str]: ...
        # Returns (system_prompt, user_template)

    # --- Evaluator Configuration ---
    def get_evaluator_types(self) -> list[str]: ...
    def get_evaluator_axes(self, evaluator_type: str) -> set[str]: ...
    def get_evaluator_prompt(self, evaluator_type: str) -> tuple[str, str]: ...

    # --- Scoring ---
    def get_scoring_weights(self) -> dict[str, float]: ...
    def get_tier_thresholds(self) -> dict[str, float]: ...
    def calculate_subscores(self, axes: dict[str, float]) -> dict[str, float]: ...

    # --- Classification ---
    def classify_cause(self, axes: dict[str, float]) -> str: ...
    def get_cause_actions(self) -> dict[str, dict]: ...

    # --- State Types ---
    def get_cause_values(self) -> list[str]: ...
    def get_action_values(self) -> list[str]: ...

    # --- Prompts ---
    def get_synthesizer_prompt(self) -> tuple[str, str]: ...
    def get_biasbuster_prompt(self) -> tuple[str, str]: ...
    def get_commentary_prompt(self) -> tuple[str, str]: ...

    # --- Fixtures (optional) ---
    def get_fixture_data(self, name: str) -> dict | None: ...
    def list_fixtures(self) -> list[str]: ...
```

### 2.4 DI 주입 메커니즘

```python
# core/infrastructure/ports/domain_port.py (하단)

from contextvars import ContextVar

_domain_ctx: ContextVar[DomainPort] = ContextVar("domain_port")

def set_domain(domain: DomainPort) -> None:
    _domain_ctx.set(domain)

def get_domain() -> DomainPort:
    return _domain_ctx.get()  # 미설정 시 LookupError
```

### 2.5 사용 흐름

```python
# core/runtime.py — 수정

class GeodeRuntime:
    @classmethod
    def create(cls, *, domain: str = "game_ip", **kwargs) -> GeodeRuntime:
        # 1) 도메인 어댑터 로드
        adapter = load_domain_adapter(domain)
        set_domain(adapter)

        # 2) 기존 인프라 초기화 (변경 없음)
        ...
```

```python
# core/nodes/analysts.py — 수정 예시

from core.infrastructure.ports.domain_port import get_domain

def _run_single_analyst(analyst_type: str, state: dict) -> dict:
    domain = get_domain()
    system, user_template = domain.get_analyst_prompt(analyst_type)
    # ... LLM 호출
```

## 3. 디렉토리 구조 (목표)

```
core/
├── domains/                          # NEW: 도메인 플러그인 디렉토리
│   ├── __init__.py
│   ├── loader.py                     # load_domain_adapter(name) → DomainPort
│   ├── game_ip/                      # 게임 IP 도메인 (기존 코드 이동)
│   │   ├── __init__.py
│   │   ├── adapter.py                # GameIPDomain(DomainPort) 구현체
│   │   ├── config/
│   │   │   ├── evaluator_axes.yaml   # ← core/config/evaluator_axes.yaml
│   │   │   └── cause_actions.yaml    # ← core/config/cause_actions.yaml
│   │   ├── prompts/
│   │   │   ├── analyst.md            # ← core/llm/prompts/analyst.md
│   │   │   ├── evaluator.md          # ← core/llm/prompts/evaluator.md
│   │   │   ├── synthesizer.md        # ← core/llm/prompts/synthesizer.md
│   │   │   ├── biasbuster.md         # ← core/llm/prompts/biasbuster.md
│   │   │   ├── commentary.md         # ← core/llm/prompts/commentary.md
│   │   │   └── cross_llm.md          # ← core/llm/prompts/cross_llm.md
│   │   ├── fixtures/                 # ← core/fixtures/*.json
│   │   ├── scoring.py                # 게임 IP 전용 scoring 로직
│   │   └── classification.py         # Decision Tree 로직
│   └── research/                     # 미래: 범용 리서치 도메인 예시
│       ├── __init__.py
│       ├── adapter.py
│       └── prompts/
│
├── infrastructure/ports/
│   ├── domain_port.py                # NEW: DomainPort Protocol + contextvars
│   └── ... (기존 포트 유지)
│
├── nodes/                            # 수정: 하드코딩 → get_domain() 호출
│   ├── analysts.py                   # ANALYST_TYPES → get_domain().get_analyst_types()
│   ├── evaluators.py                 # VALID_AXES → get_domain().get_evaluator_axes()
│   ├── scoring.py                    # WEIGHTS → get_domain().get_scoring_weights()
│   └── synthesizer.py               # Decision Tree → get_domain().classify_cause()
│
├── state.py                          # 수정: Literal → str (도메인별 값은 DomainPort에서)
│
├── llm/prompts/                      # 유지: 도메인 무관 프롬프트만 잔류
│   ├── router.md                     # 범용 (AgenticLoop용)
│   ├── tool_augmented.md             # 범용
│   └── axes.py                       # 수정: VALID_AXES_MAP → get_domain() 위임
│
└── ... (나머지 인프라 동일)
```

## 4. 구현 단계

### Phase 1: DomainPort 인터페이스 정의 (1일)

```
1. core/infrastructure/ports/domain_port.py 생성
   - DomainPort Protocol 정의
   - contextvars 기반 DI (set_domain / get_domain)

2. 테스트:
   - tests/test_domain_port.py — Protocol 준수 검증
```

**변경 파일**: 1 new
**위험도**: 낮음 (추가만, 기존 코드 미변경)

### Phase 2: GameIPDomain 어댑터 구현 (2일)

```
1. core/domains/__init__.py, loader.py 생성
2. core/domains/game_ip/adapter.py — DomainPort 구현
   - 기존 하드코딩된 값들을 메서드로 래핑
   - evaluator_axes.yaml, cause_actions.yaml 로딩
   - 프롬프트 파일 로딩 (core/llm/prompts/*.md에서)

3. 테스트:
   - tests/test_game_ip_domain.py — 전체 DomainPort 계약 검증
   - 기존 fixture 결과 (Berserk S/81.3, Cowboy Bebop A/68.4, GitS B/51.6) 동일 확인
```

**변경 파일**: 3 new
**위험도**: 낮음 (새 파일만, 기존 코드에서 값 복사)

### Phase 3: 노드 파라미터화 (2일)

```
1. core/nodes/analysts.py
   - ANALYST_TYPES 상수 → get_domain().get_analyst_types()
   - 프롬프트 로딩 → get_domain().get_analyst_prompt(type)

2. core/nodes/evaluators.py
   - VALID_AXES_MAP → get_domain().get_evaluator_axes(type)
   - 프롬프트 → get_domain().get_evaluator_prompt(type)

3. core/nodes/scoring.py
   - WEIGHTS → get_domain().get_scoring_weights()
   - TIER_THRESHOLDS → get_domain().get_tier_thresholds()
   - subscore 공식 → get_domain().calculate_subscores()

4. core/nodes/synthesizer.py
   - Decision Tree → get_domain().classify_cause(axes)
   - cause_actions → get_domain().get_cause_actions()

5. core/state.py
   - CauseLiteral/ActionLiteral → str (동적 검증은 DomainPort에서)
   - EvaluatorResult.validate_axes() → get_domain().get_evaluator_axes() 위임

6. core/llm/prompts/axes.py
   - VALID_AXES_MAP → get_domain() 위임 wrapper

7. 테스트:
   - 기존 2125+ 테스트 전부 통과 확인 (래칫 P4)
```

**변경 파일**: 7 modified
**위험도**: 중간 (핵심 노드 수정, 래칫으로 안전 보장)

### Phase 4: 도메인 리소스 이동 (1일)

```
1. 파일 이동:
   core/config/evaluator_axes.yaml    → core/domains/game_ip/config/
   core/config/cause_actions.yaml     → core/domains/game_ip/config/
   core/llm/prompts/analyst.md        → core/domains/game_ip/prompts/
   core/llm/prompts/evaluator.md      → core/domains/game_ip/prompts/
   core/llm/prompts/synthesizer.md    → core/domains/game_ip/prompts/
   core/llm/prompts/biasbuster.md     → core/domains/game_ip/prompts/
   core/llm/prompts/commentary.md     → core/domains/game_ip/prompts/
   core/llm/prompts/cross_llm.md      → core/domains/game_ip/prompts/
   core/fixtures/                     → core/domains/game_ip/fixtures/

2. 기존 위치에 backward-compat symlink 또는 re-export (1 릴리스 유지 후 삭제)

3. GameIPDomain.adapter가 새 위치에서 로딩하도록 경로 업데이트

4. 테스트: 전체 regression
```

**변경 파일**: 9 moved, 1 modified
**위험도**: 낮음 (경로 변경만, 로직 동일)

### Phase 5: Runtime 통합 + CLI (1일)

```
1. core/runtime.py
   - GeodeRuntime.create(domain="game_ip") 파라미터 추가
   - load_domain_adapter() 호출 → set_domain()
   - 기본값: "game_ip" (하위호환)

2. core/cli/__init__.py
   - --domain CLI 옵션 추가 (optional, default="game_ip")

3. core/cli/commands.py
   - /domain 명령어 추가: list, activate, info

4. 테스트:
   - tests/test_runtime_domain.py — 도메인 전환 E2E
   - CLI dry-run: uv run geode analyze "Berserk" --domain game_ip --dry-run
```

**변경 파일**: 3 modified, 1 new test
**위험도**: 낮음 (기본값으로 하위호환)

### Phase 6: 범용 리서치 도메인 스캐폴딩 (선택, 1일)

```
1. core/domains/research/adapter.py — 최소 DomainPort 구현
   - analyst_types: ["literature_review", "methodology", "findings", "limitations"]
   - evaluator_axes: 논문 품질 축 (novelty, rigor, impact, reproducibility)
   - scoring: 논문 평가 가중치

2. 검증: uv run geode analyze "Attention Is All You Need" --domain research --dry-run
```

**변경 파일**: 3 new
**위험도**: 낮음 (독립 도메인, 기존 코드 미영향)

## 5. 리스크 & 완화

| 리스크 | 확률 | 영향 | 완화 |
|--------|------|------|------|
| Phase 3에서 테스트 깨짐 | 중 | 중 | 래칫 P4: 각 노드 수정 후 즉시 전체 테스트 |
| DomainPort 인터페이스 과다 설계 | 중 | 중 | P10: 최소 메서드만. 필요 시 확장 |
| 프롬프트 이동 시 경로 누락 | 저 | 중 | grep으로 모든 참조 확인 후 이동 |
| 성능 저하 (contextvars 호출 오버헤드) | 저 | 저 | contextvars는 ns 단위, LLM 호출 대비 무시 |

## 6. 성공 기준

```
□ DomainPort Protocol 정의 완료
□ GameIPDomain 어댑터가 기존 동작 100% 재현
□ 기존 2125+ 테스트 전부 통과 (래칫)
□ fixture 결과 동일: Berserk S/81.3, Cowboy Bebop A/68.4, GitS B/51.6
□ CLI dry-run 정상: uv run geode analyze "Berserk" --dry-run
□ /domain list 명령어 동작
□ 제2 도메인(research) 스캐폴딩 가능 확인
```

## 7. 의사결정 기록

| # | 결정 | 근거 | 대안 |
|---|------|------|------|
| D1 | contextvars DI (기존 패턴 유지) | 이미 LLMClientPort 등에서 사용 중. 일관성. | Registry lookup, Module-level singleton |
| D2 | Protocol (duck typing) vs ABC | 기존 ports/가 모두 Protocol. 타입 안전 + 느슨 결합. | ABC 강제 상속 → 불필요한 결합 |
| D3 | 도메인 리소스를 core/domains/에 배치 | 자기 완결적 패키지. Plugin.install()에서 경로 자동 해결. | 별도 top-level domains/ → import 경로 복잡 |
| D4 | state.py Literal → str | 도메인별 원인/행동 값이 다름. 런타임 검증으로 전환. | Union[GameCause, ResearchCause] → 타입 폭발 |
| D5 | backward-compat symlink (1 릴리스) | 외부 참조 깨짐 방지. 다음 MINOR에서 삭제. | 즉시 삭제 → breaking change |
| D6 | Phase 1-5 순서 (인터페이스 → 구현 → 파라미터화 → 이동 → 통합) | 각 단계에서 테스트 가능. 롤백 용이. | 빅뱅 리팩터 → 래칫 불가 |

## 8. 변경량 추정

| Phase | 신규 LOC | 수정 LOC | 삭제 LOC | 일수 |
|-------|---------|---------|---------|------|
| 1. DomainPort | ~100 | 0 | 0 | 1 |
| 2. GameIPDomain | ~400 | 0 | 0 | 2 |
| 3. 노드 파라미터화 | ~50 | ~300 | ~200 | 2 |
| 4. 리소스 이동 | 0 | ~30 | 0 | 1 |
| 5. Runtime + CLI | ~80 | ~50 | 0 | 1 |
| 6. Research 스캐폴딩 | ~200 | 0 | 0 | 1 |
| **합계** | **~830** | **~380** | **~200** | **~8** |

> 순 증가: ~1,010 LOC. 기존 26,000 LOC 대비 3.9% 증가로 범용 프레임워크 전환 달성.
