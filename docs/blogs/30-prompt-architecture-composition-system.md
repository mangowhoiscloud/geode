# GEODE 프롬프트 아키텍처 — 조합, 격리, 캐싱, 그리고 무결성 검증

> Date: 2026-03-16 | Author: geode-team | Tags: [prompt-engineering, prompt-caching, clean-context, skill-injection, karpathy-p4, structured-output, agentic-loop]

## 목차

1. [도입 — 프롬프트가 코드가 될 때](#1-도입--프롬프트가-코드가-될-때)
2. [템플릿 구조 — 마크다운 섹션 기반 로더](#2-템플릿-구조--마크다운-섹션-기반-로더)
3. [6단계 조합 파이프라인 (ADR-007)](#3-6단계-조합-파이프라인-adr-007)
4. [Clean Context — 앵커링 방지 격리](#4-clean-context--앵커링-방지-격리)
5. [동적 축 주입 — YAML에서 루브릭으로](#5-동적-축-주입--yaml에서-루브릭으로)
6. [프롬프트 캐싱 — 반복 호출 비용 절감](#6-프롬프트-캐싱--반복-호출-비용-절감)
7. [무결성 검증 — SHA-256 해시 핀닝](#7-무결성-검증--sha-256-해시-핀닝)
8. [Structured Output — 자유 텍스트의 종말](#8-structured-output--자유-텍스트의-종말)
9. [마무리](#9-마무리)

---

## 1. 도입 — 프롬프트가 코드가 될 때

GEODE의 파이프라인은 8개 노드에서 최소 10회의 LLM 호출을 수행합니다. 4명의 Analyst가 병렬로 호출되고, 3명의 Evaluator가 14개 축을 평가하며, Synthesizer가 최종 내러티브를 생성합니다. 각 호출에는 서로 다른 시스템 프롬프트, 사용자 프롬프트, 루브릭 데이터, 스킬 컨텍스트가 필요합니다.

이 상황에서 프롬프트를 Python 문자열 상수로 관리하면 어떻게 될까요?

```python
# 이렇게 하지 않습니다
ANALYST_SYSTEM = """You are a game mechanics analyst.
Focus on: core gameplay loop quality, combat/interaction system potential,
progression mechanics, skill/ability design space, and replay value.
..."""
```

프롬프트 하나를 수정하면 관련된 10개 호출 지점을 확인해야 하고, 루브릭을 변경하면 3개 Evaluator 프롬프트를 동시에 갱신해야 합니다. 프롬프트가 3000자를 넘어가면 코드 리뷰에서 diff를 읽기 어렵고, 의도하지 않은 변경이 CI를 통과할 수 있습니다.

이 글에서는 GEODE가 프롬프트를 **코드와 동일한 수준으로 관리**하는 방법을 다룹니다.

---

## 2. 템플릿 구조 — 마크다운 섹션 기반 로더

### 파일 포맷

GEODE의 프롬프트 템플릿은 `.md` 파일입니다. `=== SECTION_NAME ===` 구분자로 하나의 파일 안에 여러 프롬프트를 정의합니다.

```markdown
=== SYSTEM ===

You are GEODE, a general-purpose autonomous execution agent.
You help the user with any task — research, analysis, automation.

## Core capabilities
- Answer questions directly using your knowledge
- Process URLs (web_fetch), search the web (general_web_search)
...

=== AGENTIC_SUFFIX ===

## Completion criteria (CRITICAL)
After each tool result, ask yourself:
"Has the user's original request been fully answered?"
...
```

> 하나의 `.md` 파일에 SYSTEM과 AGENTIC_SUFFIX를 함께 두는 이유는 **관련 프롬프트의 공동 변경(co-change)**을 보장하기 위해서입니다. SYSTEM에서 도구 사용 규칙을 변경하면 AGENTIC_SUFFIX의 완료 기준도 함께 검토해야 합니다. 같은 파일에 있으면 PR의 diff에서 자연스럽게 함께 보입니다.

### 로딩 메커니즘

```python
# core/llm/prompts/__init__.py
def _load_template(name: str) -> dict[str, str]:
    """Load a .md template, split by === SECTION === markers."""
    path = _PROMPT_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current_key = ""
    for line in text.splitlines():
        m = re.match(r"^===\s*(\w+)\s*===$", line)
        if m:
            current_key = m.group(1).lower()
            sections[current_key] = ""
        elif current_key:
            sections[current_key] += line + "\n"
    return {k: v.strip() for k, v in sections.items()}
```

> 정규식 `^===\s*(\w+)\s*===$`은 Markdown 렌더링에서도 시각적으로 구분되는 구분자입니다. GitHub에서 `.md` 파일을 열면 `=== SYSTEM ===`이 구분선처럼 보여서 편집 시 섹션 경계가 명확합니다.

### 7개 템플릿 파일

| 파일 | 섹션 | 용도 |
|------|------|------|
| `router.md` | SYSTEM, AGENTIC_SUFFIX | AgenticLoop 자율 실행 |
| `analyst.md` | SYSTEM, USER | 4 Analyst 병렬 분석 |
| `evaluator.md` | SYSTEM, USER | 3 Evaluator 14축 평가 |
| `synthesizer.md` | SYSTEM, USER | 최종 내러티브 + 원인 분류 |
| `biasbuster.md` | SYSTEM, USER | 인지 편향 탐지 |
| `commentary.md` | SYSTEM, USER | 사용자 대면 코멘터리 |
| `cross_llm.md` | SYSTEM, RESCORE, DUAL_VERIFY | Cross-LLM 교차 검증 |

---

## 3. 6단계 조합 파이프라인 (ADR-007)

프롬프트는 로딩 후 바로 LLM에 전달되지 않습니다. `PromptAssembler`가 6단계를 거쳐 최종 프롬프트를 조합합니다.

```
Base Template (.md)
  ↓ Phase 1: Prompt Overrides (append/replace)
  ↓ Phase 2: Skill Fragment Injection (max 3, 500자/skill)
  ↓ Phase 3: Memory Context Injection (max 300자)
  ↓ Phase 4: Extra Instructions — Bootstrap (max 5, 100자/inst)
  ↓ Phase 5: Token Budget Enforcement (hard limit 6000자)
  ↓ Phase 6: Hash + Hook Event
  → AssembledPrompt (system, user, assembled_hash, fragments_used)
```

### 조합 결과 스키마

```python
# core/llm/prompt_assembler.py
class AssembledPrompt(frozen=True):
    system: str              # 최종 조합된 시스템 프롬프트
    user: str                # 사용자 프롬프트 (보통 변경 없음)
    assembled_hash: str      # SHA-256[:12] of (system + user)
    base_template_hash: str  # 원본 템플릿의 해시
    fragment_count: int      # 주입된 프래그먼트 수
    total_chars: int         # 총 문자 수
    fragments_used: list[str]  # 사용된 프래그먼트 목록
```

> 조합 결과를 `frozen=True` 데이터클래스로 만든 이유는 **불변성 보장**입니다. 조합된 프롬프트가 LLM 호출 직전에 변조되면 재현이 불가능합니다. `assembled_hash`로 어떤 프롬프트가 사용되었는지 사후 추적할 수 있습니다.

### Phase 2: 스킬 주입

스킬은 `.claude/skills/` 디렉토리에 YAML frontmatter + Markdown body 형태로 정의됩니다.

```yaml
---
name: "geode-analysis-tuning"
node: "analyst"
type: "game_mechanics"
priority: 10
version: "1.0"
role: "system"
enabled: true
---
## Pattern Recognition
When analyzing combat systems, look for Souls-like mechanics.
```

PromptAssembler는 `(node, role_type)` 매칭으로 해당 스킬을 찾아 시스템 프롬프트에 `## Skill: {name}` 헤더와 함께 추가합니다. `max_skills_per_node=3`으로 제한하여 컨텍스트 폭발을 방지합니다.

### Phase 5: 토큰 예산

```python
# 경고 임계값과 하드 리밋
prompt_warning_chars = 4000   # 초과 시 로그 경고
prompt_hard_limit_chars = 6000  # 초과 시 시스템 프롬프트 절삭
```

> Claude Opus 4.6의 컨텍스트 윈도우는 충분하지만, 프롬프트가 길면 **주의력 분산(attention dilution)**이 발생합니다. 6000자 하드 리밋은 프롬프트의 지시 밀도를 유지하기 위한 설계 제약입니다.

---

## 4. Clean Context — 앵커링 방지 격리

4명의 Analyst가 동일한 IP를 평가할 때, 한 Analyst의 점수가 다른 Analyst의 판단에 영향을 주면 **앵커링 편향(anchoring bias)**이 발생합니다.

### 격리 메커니즘

```python
# core/nodes/analysts.py — Send API 호출 전
base = {k: v for k, v in state.items()
        if k not in ("analyses", "_analyst_type")}
Send("analyst", {**base, "_analyst_type": analyst_type})
```

> `analyses` 키를 제거하여 각 Analyst가 다른 Analyst의 결과를 볼 수 없게 합니다. LangGraph의 `Send()` API가 병렬 실행을 보장하므로, 실행 순서에 의한 정보 누출도 발생하지 않습니다.

### 프롬프트 수준 격리

Analyst 시스템 프롬프트에도 명시적 격리 지시가 포함됩니다.

```
# analyst.md — SYSTEM
Evaluate this IP from the perspective of {analyst_type}.
Do NOT reference other analysts or their scores.
Your evaluation must be independent.
```

### 앵커링 탐지 (BiasBuster)

격리가 실패했는지 사후 검증합니다.

```python
# Coefficient of Variation(변동계수) 기반 앵커링 탐지
CV = std / mean
anchoring_bias = CV < 0.05 and n >= 4
```

> CV가 0.05 미만이면 4명의 Analyst가 거의 같은 점수를 냈다는 의미입니다. 독립 평가인데 점수가 이렇게 밀집되는 것은 통계적으로 의심스럽습니다. 이 경우 `anchoring_bias` 플래그가 활성화되어 전체 LLM BiasBuster 검사를 트리거합니다.

---

## 5. 동적 축 주입 — YAML에서 루브릭으로

Evaluator는 14개 축(axis)에 대해 1-5점 루브릭 평가를 수행합니다. 축 정의와 앵커 기준은 코드가 아닌 **YAML**에서 관리됩니다.

### YAML 구조

```yaml
# core/config/evaluator_axes.yaml
evaluator_axes:
  quality_judge:
    description: "Game Quality Evaluator"
    axes:
      a_score: "Core Mechanics potential"
      b_score: "IP Integration depth"
      c_score: "Gameplay Depth"
      # ... 5 more axes
    rubric:
      a_score:
        "1": "기본 조작 불량"
        "2": "장르 이하"
        "3": "장르 평균"
        "4": "장르 이상"
        "5": "혁신적 메카닉"
```

### 주입 과정

YAML → `_format_axes_schema()` → `{axes_schema}` 플레이스홀더 → Evaluator 시스템 프롬프트:

```
## Required axes (respond with exactly these keys):
"a_score": <float 1-5 — Core Mechanics potential>,
"b_score": <float 1-5 — IP Integration depth>,
...
```

YAML → `_format_rubric_anchors()` → `{rubric_anchors}` 플레이스홀더:

```
## Rubric Anchors
- a_score: 1=기본 조작 불량, 2=장르 이하, 3=장르 평균, 4=장르 이상, 5=혁신적 메카닉
```

> 축 정의를 YAML로 분리한 이유는 **도메인 교체**입니다. `DomainPort` 프로토콜을 통해 게임 IP가 아닌 다른 도메인(예: 연구 논문 평가)으로 전환할 때 YAML 파일만 교체하면 Evaluator 프롬프트가 자동으로 새 축을 사용합니다.

### 축 버전 해싱

```python
AXES_VERSIONS: dict[str, str] = {
    "EVALUATOR_AXES": _hash_axes(EVALUATOR_AXES),
    "PROSPECT_EVALUATOR_AXES": _hash_axes(PROSPECT_EVALUATOR_AXES),
    "ANALYST_SPECIFIC": _hash_axes(ANALYST_SPECIFIC),
}
```

축 데이터도 해싱하여 프롬프트와 동일한 무결성 검증 체계에 포함됩니다.

---

## 6. 프롬프트 캐싱 — 반복 호출 비용 절감

4명의 Analyst가 동일한 시스템 프롬프트를 사용합니다. Anthropic의 프롬프트 캐싱을 활용하면 2번째 호출부터 입력 토큰 비용이 90% 절감됩니다.

### 구현

```python
# core/llm/client.py
def _system_with_cache(system: str) -> list[TextBlockParam]:
    return [
        TextBlockParam(
            type="text",
            text=system,
            cache_control={"type": "ephemeral"},
        )
    ]
```

> `ephemeral` 캐시는 5분간 유지됩니다. 4명의 Analyst는 수 초 간격으로 호출되므로 첫 호출의 캐시가 나머지 3회에 적중합니다.

### 비용 절감 계산

| 호출 | 캐시 | 입력 토큰 비용 | 비고 |
|------|------|----------------|------|
| Analyst 1 | Creation | 1.25x | 캐시 생성 비용 |
| Analyst 2 | Read | 0.10x | 캐시 적중 |
| Analyst 3 | Read | 0.10x | 캐시 적중 |
| Analyst 4 | Read | 0.10x | 캐시 적중 |
| **합계** | | **1.55x** | 캐시 없이 4.0x 대비 **61% 절감** |

3명의 Evaluator도 유사한 시스템 프롬프트 구조를 공유하므로 추가 절감이 발생합니다.

---

## 7. 무결성 검증 — SHA-256 해시 핀닝

프롬프트는 LLM 출력의 품질을 결정하는 핵심 요소입니다. 의도하지 않은 프롬프트 변경은 분석 결과의 일관성을 깨뜨립니다. GEODE는 Karpathy P4(Ratchet Mechanism) 패턴을 적용하여 프롬프트 변경을 CI 게이트에서 감지합니다.

### 해시 계산

```python
# core/llm/prompts/__init__.py
def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]

PROMPT_VERSIONS: dict[str, str] = {
    "ANALYST_SYSTEM": _hash_prompt(ANALYST_SYSTEM),
    "ANALYST_USER": _hash_prompt(ANALYST_USER),
    # ... 20개 프롬프트 × 12자리 해시
}
```

### 핀 등록

```python
_PINNED_HASHES: dict[str, str] = {
    "AGENTIC_SUFFIX": "8ec998fdf916",
    "ANALYST_SYSTEM": "924433f5bf11",
    "EVALUATOR_AXES": "0d82eb1aa5b4",
    # ... 20개 항목
}
```

> 핀 해시는 **하드코딩**입니다. 프롬프트를 의도적으로 변경하면 개발자가 이 값을 함께 갱신해야 합니다. 갱신 없이 프롬프트만 변경하면 CI 테스트가 실패합니다.

### CI 테스트

```python
def verify_prompt_integrity(*, raise_on_drift: bool = False) -> list[str]:
    """런타임 해시를 핀과 비교. 불일치 시 drift 목록 반환."""
    drifted = []
    for name, pinned in _PINNED_HASHES.items():
        computed = PROMPT_VERSIONS.get(name, "")
        if computed != pinned:
            drifted.append(f"{name}: pinned={pinned} computed={computed}")
    if drifted and raise_on_drift:
        raise RuntimeError(f"Prompt drift detected: {drifted}")
    return drifted
```

```python
# tests/test_karpathy_prompt_hardening.py
class TestPromptDriftDetection:
    def test_no_drift_on_clean_state(self):
        drifted = verify_prompt_integrity()
        assert drifted == [], f"Unexpected prompt drift: {drifted}"
```

> 이 테스트는 매 PR의 CI에서 실행됩니다. 프롬프트 `.md` 파일을 수정했는데 핀 해시를 갱신하지 않으면 테스트가 실패하며, 의도치 않은 프롬프트 변경이 main 브랜치에 도달하는 것을 방지합니다.

---

## 8. Structured Output — 자유 텍스트의 종말

프롬프트의 출력을 자유 텍스트로 받으면 JSON 파싱 실패, 키 누락, 타입 불일치 등의 문제가 발생합니다. GEODE는 Anthropic의 `messages.parse()`와 Pydantic 모델을 결합하여 **구조화된 출력**을 강제합니다.

### Pydantic 모델 기반 파싱

```python
# core/llm/client.py
def call_llm_parsed(
    system: str,
    user: str,
    response_model: type[T],
    **kwargs,
) -> T:
    """Anthropic SDK messages.parse() — 타입 안전 응답."""
    return client.messages.parse(
        model=model,
        system=_system_with_cache(system),
        messages=[{"role": "user", "content": user}],
        response_model=response_model,
    )
```

### Evaluator별 타입 모델

```python
# core/state.py
class QualityJudgeAxes(BaseModel):
    a_score: float = Field(ge=1.0, le=5.0)  # Core Mechanics
    b_score: float = Field(ge=1.0, le=5.0)  # IP Integration
    # ... 8축 각각 [1.0, 5.0] 범위 강제

class HiddenValueAxes(BaseModel):
    d_score: float = Field(ge=1.0, le=5.0)  # Discovery Gap
    e_score: float = Field(ge=1.0, le=5.0)  # Exploitation Gap
    f_score: float = Field(ge=1.0, le=5.0)  # Fandom Resilience
```

> Evaluator마다 다른 Pydantic 모델을 사용합니다. `quality_judge`가 8개 축을, `hidden_value`가 3개 축을 반환해야 하는데, 단일 모델로는 이를 표현할 수 없습니다. 모델이 축 이름과 범위를 강제하므로 LLM이 잘못된 키를 반환하거나 범위를 벗어난 점수를 줄 수 없습니다.

### 레거시 JSON 추출 (Fallback)

```python
def call_llm_json(system: str, user: str, **kwargs) -> dict[str, Any]:
    """raw text → JSON 추출 (레거시 호환)."""
    text = call_llm(system, user, **kwargs)
    # 코드블록, JSON 라인, 부분 JSON 등 다양한 포맷에서 추출
```

> Structured Output이 실패하는 경우(API 버전 불일치, 모델 미지원 등)를 위한 fallback입니다. 실제 프로덕션에서는 99% 이상 `call_llm_parsed`를 사용합니다.

---

## 9. 마무리

### 핵심 정리

| 항목 | 값 |
|------|-----|
| 템플릿 파일 | 7개 `.md` + 1개 YAML (축 정의) |
| 프롬프트 상수 | 20개 (PROMPT_VERSIONS에 등록) |
| 변수 플레이스홀더 | 50+ 고유 변수 |
| 조합 단계 | 6 Phase (Override → Skill → Memory → Bootstrap → Budget → Hash) |
| 캐시 전략 | Anthropic ephemeral (5분), 4 Analyst 호출에서 61% 절감 |
| 무결성 검증 | SHA-256[:12] 핀 해싱, CI 테스트 게이트 |
| 앵커링 방지 | Send API Clean Context + BiasBuster CV 탐지 |
| 출력 구조화 | Pydantic 모델 기반 `messages.parse()` + JSON fallback |

### 설계 원칙

1. **프롬프트는 코드다**: 버전 관리, 해시 검증, CI 게이트를 코드와 동일하게 적용합니다.
2. **조합은 결정적이다**: 같은 입력(스킬, 메모리, 부트스트랩)이면 같은 프롬프트가 생성됩니다. `assembled_hash`로 재현 가능합니다.
3. **격리는 구조적이다**: 프롬프트 수준 지시(텍스트)와 데이터 수준 격리(Send API state 필터링)를 이중으로 적용합니다.
4. **확장은 주입으로**: 프롬프트 본문을 수정하지 않고 스킬, 메모리, 부트스트랩을 주입하여 동작을 변경합니다.

### 체크리스트

- [x] `.md` 섹션 기반 템플릿 로더
- [x] 6단계 PromptAssembler (ADR-007)
- [x] Clean Context 앵커링 방지 (Send API + 프롬프트 지시)
- [x] YAML 축 정의 → 동적 루브릭 주입
- [x] Anthropic ephemeral 프롬프트 캐싱
- [x] SHA-256 핀 해싱 + CI drift 테스트
- [x] Pydantic Structured Output + JSON fallback
- [x] Hook 이벤트 관측성 (PROMPT_ASSEMBLED)
