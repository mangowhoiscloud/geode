# ADR-013: Mutation Surface Expansion via JSON Schema Pattern

## Status

Proposed (2026-05-21)

## Context

ADR-012 (Self-Improvement Surface Tiers) 가 정착시킨 패턴 — **JSON SoT 파일 + inference path reader + mutation dispatcher** — 가 S0a-d 의 4축 (`prompt` / `tool_policy` / `decomposition` / `reflection`) 으로 검증되었다. 4축 모두 ALIVE 로 가동되면서 self-improving loop 의 진화 면적이 1축 → 4축 회복, fitness 다축화 (S1 ux + S2 admire + S6 bench, 양의 압력 5.9% → 40.7%) 도 정착.

### 추가 mutation 표면 탐색의 동기

ADR-012 의 단기/중기 (S3-S5, M1-M5) 외에 **JSON 명세로 노출 가능한 mutation 표면이 광범위**하게 존재. AlphaEvolve 식 (코드 자체 mutation) 은 자기수정 재귀 + silent breakage + Goodhart on benchmark 의 3 가지 매우 高 risk 동반 → **명시적 배제** 결정 (2026-05-21 사용자 결정). 대신 **S0a 의 검증된 JSON + 명세 + reader 패턴** 을 6 개 신규 표면에 확장.

### 6 신규 표면의 frontier 근거

| # | 표면 | frontier 사례 |
|---|---|---|
| T1 | Tool descriptions | OpenAI function-calling docs ("clear descriptions matter") + Anthropic tool-use guide |
| T2 | Skill registry catalog | Voyager (Wang et al., 2023) — skill library + dependency graph |
| T3 | Response style guide | Anthropic Claude personality docs, OpenAI brand voice tuning |
| T4 | Provider routing | OpenRouter routing rules, LangChain RouterChain |
| T5 | Cache breakpoint policy | Anthropic prompt caching guide (`cache_control` placement) |
| T6 | Heuristic indicators | Promptbreeder evolved keyword patterns (DeepMind 2023) |

## Decision

### 1. 패턴 — JSON SoT + reader + dispatcher (S0a 검증)

각 mutation 표면은 동일 5-element 구조로 명세:

1. **SoT 파일** — post-RATCHET 패턴 (S0d 이후): 1차 `state/self_improving/policies/<name>.json` (in-repo git-tracked), 2차 `~/.geode/self-improving-loop/<name>.json` (operator-local). 두 위치 모두 reader 가 graceful load.
2. **Path constant** — `core/paths.py` 의 `GLOBAL_<NAME>_PATH` (in-repo) + module-local alias (테스트 monkeypatch 용)
3. **Reader 모듈** — `core/agent/<name>_policy.py` 의 `_load_<name>_override()` + `apply_<name>_policy()` (graceful + strict mode)
4. **Inference 진입점** — reader 가 호출되는 단일 지점
5. **Env var override** — `GEODE_<NAME>_OVERRIDE` (audit subprocess strict mode)

### 2. 6 신규 표면 명세

#### T1 — Tool descriptions

| | |
|---|---|
| SoT | `tool-descriptions.json` |
| Schema | `{tool_name: {description: str, hints: [str]}}` |
| Reader 위치 | `core/tools/base.py:load_all_tool_definitions()` 가 description override |
| Inference 진입 | `core/agent/loop/_helpers.py:get_agentic_tools` (S0a wiring 직후) |
| 영향 | `broken_tool_use` dim 직접 (도구 선택 정확도 ↑) |

#### T2 — Skill registry catalog

| | |
|---|---|
| SoT | `skill-catalog.json` |
| Schema | `{skill_name: {trigger_keywords: [str], model_preference: str, dependencies: [str], priority: int}}` |
| Reader 위치 | `core/skills/skills.py` 의 `SkillRegistry` 가 catalog 로 메타데이터 override |
| Inference 진입 | Skill registry 조회 시점 |
| 영향 | Skill routing 정확도 + skill dependency 관리 (Voyager 식) |

#### T3 — Response style guide

| | |
|---|---|
| SoT | `style-guide.json` |
| Schema | `{tone: str, length_cap: int, format: str, language_preference: str}` |
| Reader 위치 | `core/agent/style_policy.py` (신설) |
| Inference 진입 | `system_prompt.py:build_system_prompt` 에서 style guide 를 system prompt 의 안전한 prefix 로 inject |
| 영향 | 사용자 만족도/스타일 knob. (구 `ux_means` 의 `success_rate` + `revert_ratio` 축은 PR-MARGIN-FITNESS-SCALE 2026-05-30 에 제거 — 이제 dim 경유로만 fitness 영향) |

#### T4 — Provider routing

| | |
|---|---|
| SoT | `provider-routing.json` |
| Schema | `{task_type: {primary: str, fallback: [str], cost_cap_per_call: float}}` |
| Reader 위치 | `core/agent/routing_policy.py` (신설) |
| Inference 진입 | `core/llm/router/calls/_route.py` (routing) + `core/llm/provider_dispatch.py` (provider dispatch) 의 model selection 직전. (`core/llm/router/` 는 package — 단일 module 이 아님.) |
| 영향 | cost/quality trade-off knob. (구 `ux_means` 의 `token_cost_norm` 축은 PR-MARGIN-FITNESS-SCALE 2026-05-30 에 제거) |

#### T5 — Cache breakpoint policy

| | |
|---|---|
| SoT | `cache-policy.json` |
| Schema | `{breakpoints: [{location: str, ttl: int}], strategy: str}` |
| Reader 위치 | `core/agent/cache_policy.py` (신설) |
| Inference 진입 | `core/llm/providers/anthropic.py:apply_messages_cache_control` 호출 직전 |
| 영향 | M3 (Prompt cache few-shot 자동 적재) 와 결합 — token cost ↓ + latency ↓ |

#### T6 — Heuristic indicators

| | |
|---|---|
| SoT | `heuristics.json` |
| Schema | `{simple_patterns: [str], compound_indicators: [str]}` |
| Reader 위치 | `core/agent/heuristics_policy.py` (신설) |
| Inference 진입 | `core/agent/plan.py:_is_clearly_simple` + `_has_compound_indicators` 의 hardcoded list override (PR-CL-A1-followup 2026-05-23 — `goal_decomposer.py` 삭제 후 host 이전) |
| 영향 | decomposer 의 simple/compound 판별 정확도 → `gaia_accuracy` (S6) 영향 |

### 3. AlphaEvolve 명시적 배제

코드 자체의 mutation (AlphaEvolve / FunSearch / DeepMind 2025) 은 다음 risk 로 인해 **GEODE 에서 채택하지 않음**:

| Risk | 시나리오 |
|---|---|
| 자기수정 재귀 | mutator 가 자기 자신 또는 fitness gate 코드를 evolve → ratchet 우회 |
| Silent breakage | unit test 미커버 edge case 에서 break, production 에서 발견 (늦음) |
| Goodhart on benchmark | mutator 가 visible test 만 통과 (실제 의미 X) |
| Dependency chain 파괴 | 함수 시그니처 변경 시 caller 깨짐 |
| 진입 비용 | EVOLVE marker + AST validator + hidden test + property test + sandbox pool 의 5 가지 harness 필요 |

→ ADR-013 의 모든 6 표면은 **JSON mutation only** — 코드 변경 0. AlphaEvolve risk 모두 회피.

### 4. 동작 원리 — 4-step lifecycle

```
1. operator 또는 mutator LLM 이 SoT JSON 파일 작성
   (~/.geode/self-improving-loop/<name>.json)
   ↓
2. 다음 에이전트 호출 시 reader 가 SoT 를 graceful load
   (graceful: schema 위반 시 WARNING + 기본값 fallback)
   ↓
3. apply_<name>_policy() 가 default + override 를 결합
   (deep-copy 로 default 오염 방지, S0a-c 패턴)
   ↓
4. 에이전트 응답 생성 시 override 정책 반영
   ↓ (Petri / bench / ux / admire evaluation)
   ↓
   compute_fitness 가 4축 평가 → promote/reject
```

### 5. 선택 이유 — 6 표면 우선순위

| 우선 | 표면 | 선택 이유 |
|---|---|---|
| 1 | T1 Tool descriptions | OpenAI/Anthropic 검증된 기법 + 비용 0 + `broken_tool_use` dim 직접 |
| 2 | T2 Skill registry catalog | M1 (Skill markdown mutation) 의 자연스러운 확장 — 메타데이터 mutate 만으로 routing 진화 |
| 3 | T3 Response style guide | 사용자 만족도/스타일 knob (구 `ux_means` 축 제거 2026-05-30 — dim 경유) |
| 4 | T4 Provider routing | 비용/품질 trade-off knob (구 `ux_means.token_cost_norm` 축 제거 2026-05-30) |
| 5 | T5 Cache breakpoint policy | M3 와 결합, prompt caching ROI 정량적 |
| 6 | T6 Heuristic indicators | decomposer 의 simple/compound 판별 정확도 ↑ → `gaia_accuracy` 영향 |

배제된 24 표면 (Lane config / Token budget / Agent topology / Custom dims / Voter panel / Pilot dim / Calibration corpus / Goodhart rules 등) 은 다음 중 하나 사유:
- Tier 2 보호 영역과 충돌 (fitness gate / eval 정확성 / Goodhart defense)
- 우선순위 낮음 (run-time tuning 보다 정책 진화가 ROI 高)
- 의존 기능 미정착 (Custom dims 은 Petri schema 확장 필요)

## Consequences

### 긍정적 결과

1. **Mutation 표면 4 → 10 으로 2.5배 확장**, 모두 JSON SoT 기반 (코드 변경 0).
2. **frontier-aligned 패턴 일관성** — S0a 의 검증된 5-element 구조 그대로 재사용.
3. **AlphaEvolve risk 회피** — 자기수정 재귀 / silent breakage / Goodhart on benchmark 모두 회피.
4. **각 표면의 ROI 명확** — fitness 축 (dim/admire/bench; ux 축은 2026-05-30 제거) 중 어디에 영향 미치는지 명세.

### Risks + Mitigations

| Risk | Mitigation |
|---|---|
| 6 표면 동시 진입 시 schema 충돌 | 각 표면이 별도 PR (T1-T6) + 독립 SoT 파일 + 독립 reader. 의존성 없음 |
| reader 신설 후 wiring 누락 (PR-AUDIT-5SLOT 의 1/5 누수 재발) | 각 PR 의 invariant test 가 reader call chain 검증 (S0a-c 패턴) |
| SoT 파일 손상 시 silent fallback (graceful) 로 정책 무효화 | WARNING 로그 + `validate_<name>_schema` invariant + audit subprocess strict mode 로 catch |
| Tier 2 deny-list 와 충돌 | 각 표면이 ADR-012 §Decision.1 의 Tier 2 영역 (bootstrap / runner / fitness gate) 와 무관 — invariant test 로 확인 |

### Operational dial

각 표면이 `TARGET_KINDS` 에 추가되면 `policies.py:TARGET_KINDS` 크기 4 → 10. mutator 의 mutation candidate 풀이 2.5배. 단계별 진입 (T1 → T2 → ... → T6) 로 fitness gate 가 새 표면의 효과를 격리 측정 가능.

## Reference — 6 표면별 frontier 사례 정밀 인용

### T1 — Tool descriptions
- **OpenAI function calling guide**: "The way you describe functions has a big impact on what the model does. Clearer descriptions yield more accurate selection."
- **Anthropic tool use docs**: "tool description must clearly explain purpose, when to use, parameter semantics"
- **DSPy** (Stanford): bootstrap demos 가 tool description 의 fewshot 역할

### T2 — Skill registry catalog
- **Voyager** (Wang et al., NeurIPS 2023): skill library + automatic curriculum + skill 호출 그래프 (자동 dependency 학습은 부분 — Voyager 의 핵심은 reusable code skill library, 본 ADR 의 catalog 는 메타데이터 routing 으로 더 좁게 매핑)
- **ToolLLM** (THU, 2023): skill catalog 의 trigger keyword embedding routing

### T3 — Response style guide
- **Anthropic Claude personality docs**: tone calibration 의 system prompt anchor
- **OpenAI brand voice tuning**: GPT-5 의 voice/style 정책 분리

### T4 — Provider routing
- **OpenRouter routing rules**: model 선택의 정책 분리 (cost vs quality)
- **LangChain RouterChain**: task type 별 LLM 분기
- **GEODE 의 PR-G2** (mutator role-tab): 이미 model 선택의 부분 분리

### T5 — Cache breakpoint policy
- **Anthropic prompt caching guide**: `cache_control={"type":"ephemeral"}` placement
- **OpenAI prompt caching**: 1024-token 단위 자동 cache
- **GEODE 의 PROMPT_CACHE_BOUNDARY** (`system_prompt.py`): 이미 가동, 정책화 가능

### T6 — Heuristic indicators
- **Promptbreeder** (DeepMind, 2023): task prompts + mutation prompts evolve — 본 ADR 의 keyword list mutation 은 그 *축소판* (단순 string list 의 evolve, 전체 prompt 의 evolve 가 아님)
- **DSPy bootstrap**: heuristic 의 LLM-as-judge 적응
- **GEODE 의 `core/agent/plan.py`** (현재 hardcoded list — PR-CL-A1-followup 2026-05-23 에 `goal_decomposer.py` 에서 이전): JSON 으로 추출 가능

### 배제 — AlphaEvolve / FunSearch
- **AlphaEvolve** (DeepMind, 2025-05): algorithm function mutation — risk 너무 高, 명시적 배제
- **FunSearch** (DeepMind, 2023): AlphaEvolve 의 전신
- **AI Scientist** (Sakana, 2024): research code mutation — 같은 위험 카테고리

## 후속 PR 시퀀스

| Sub-PR | task | 우선순위 |
|---|---|---|
| T1 — Tool descriptions reader | #78 | 1 |
| T2 — Skill registry catalog reader | #79 | 2 |
| T3 — Response style guide reader | #80 | 3 |
| T4 — Provider routing reader | #81 | 4 |
| T5 — Cache breakpoint policy reader | #82 | 5 |
| T6 — Heuristic indicators reader | #83 | 6 |

각 PR 은 S0a 패턴 그대로 — reader 모듈 신설 + `apply_*_policy` + invariant test (graceful/strict load + apply 의 효과 + ALIVE marker) + audit subprocess env wiring + ADR-012 Tier 1 표 갱신 + TARGET_KINDS 확장 (각 1 entry).

ADR-013 머지 후 T1 부터 단계별 진입.
