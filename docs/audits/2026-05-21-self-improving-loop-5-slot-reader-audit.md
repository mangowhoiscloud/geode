# Self-Improving Loop — 5 Slot Reader-Wiring Audit

> **Phase**: Pre-ADR-012 진단 (2026-05-21)
> **저자**: GEODE Scaffold (claude code)
> **트리거**: ADR-012 (Self-Improvement Surface Tiers) 작성 도중, 5축 중 `retrieval` slot 의 인퍼런스 reader 가 부재함을 발견. 다른 4 slot 도 같은 상태일 가능성을 진단하기 위함.
> **결과**: **5축 중 4축이 dead policy**. self-improving loop 가 사실상 1축 진화로 운영 중.

---

## 1. 배경

GEODE 의 self-improving loop 는 5개 mutation target (`prompt` / `tool_policy` / `decomposition` / `retrieval` / `reflection`) 을 SoT 파일 5종으로 명세하고 (`core/self_improving_loop/policies.py:67-71`), mutator LLM 이 그 파일들을 mutate → autoresearch 의 fitness gate 통과 시 promote 하는 구조다 (Karpathy autoresearch + AlphaEvolve fork).

이 audit 의 질문 한 줄:

> **5 SoT 파일 각각이 인퍼런스 경로 (에이전트가 응답을 생성하는 시점) 에서 누군가에 의해 읽혀 행동에 반영되는가?**

reader 가 없으면 — mutator 가 그 slot 을 mutate 해도 행동 변화가 0 → `dim_means` 도 0 → fitness 도 0 → 진화 압력이 그 slot 에 도달하지 못한다. 즉 **mutation target 으로 명세돼 있지만 진화 압력은 닿지 않는 dead policy**.

## 2. 발견 — `policies.py` 의 docstring 이 자백한다

`core/self_improving_loop/policies.py:29-37` 의 docstring 본문:

```
PR-6 stops at the *file format + dispatcher*. The Voyager-style
learning loops that actually exercise the new SoTs (curriculum +
skill library + critic) land as follow-ups; PR-6 just makes sure
the four files exist with stable read/write paths so the
infrastructure is committed before the policies that consume them.
```

즉 PR-6 시점부터 **5축 중 4축의 reader 는 "follow-up" 으로 명시적으로 미뤄진 상태**였고, 이 follow-up 이 잊혀져 현재까지 dead 상태. 이건 hidden bug 가 아니라 **미완성된 wiring 의 망각**.

## 3. 5 slot 상태표

| Slot | SoT 파일 | Mutation target? | **인퍼런스 reader 위치** | 상태 |
|---|---|---|---|---|
| `prompt` | `wrapper-sections.json` | ✓ | `core/agent/system_prompt.py:57` (`_load_wrapper_override`) → `:79-80` (SoT fallback read) → `:194` (`build_system_prompt` 호출) → `:198/:210` (audit/normal mode inject) → `core/agent/loop/_context.py:103` → `core/agent/loop/agent_loop.py` (LLM 호출 경로) | **ALIVE** |
| `tool_policy` | `tool-policy.json` | ✓ | **audit 시점 없음** — `paths.py:92`, `policies.py:130` 정의만. **S0a 이후** `core/agent/tool_policy.py` (`_load_tool_policy_override` + `apply_tool_policy`) → `core/agent/loop/_helpers.py:get_agentic_tools` | **DEAD → ALIVE (S0a, 2026-05-21 머지)** |
| `decomposition` | `decomposition.json` | ✓ | **없음** — `_decomposition.py:31` 의 `GoalDecomposer` 는 prompt 를 `core.llm.prompts.load_prompt("decomposer", "system")` 로 별도 SoT 에서 로드. 즉 hardcoded 가 아니지만 어느 경로도 `decomposition.json` 을 읽지 않음 — 그게 dead 사유 | **DEAD** |
| `retrieval` | `retrieval.json` | ✓ | **없음** — `paths.py:94`, `policies.py:132` 정의만 | **DEAD** |
| `reflection` | `reflection.json` | ✓ | **audit 시점 없음** — `_REFLECTION_TOOL` + `_SYSTEM_PROMPT` 가 module-level constant. **S0b 이후** `core/agent/reflection_policy.py` (`_load_reflection_policy_override` + `apply_reflection_policy`) → `core/agent/loop/_reflection.py` 의 reflection LLM 호출 직전 적용 | **DEAD → ALIVE (S0b, 2026-05-21 머지)** |

**총평** (audit 시점, 2026-05-21 오전): 1/5 ALIVE, 4/5 DEAD.

### Post-S0a (2026-05-21 오후) update

ADR-012 S0a (`tool_policy` reader 신설) 머지 후 상태:

| Slot | 변동 | 새 reader 위치 |
|---|---|---|
| `tool_policy` | **DEAD → ALIVE** | `core/agent/tool_policy.py` 의 `_load_tool_policy_override` + `apply_tool_policy` → `core/agent/loop/_helpers.py:get_agentic_tools` (도구 후보 단일 진입점) |

**S0a 직후 상태**: 2/5 ALIVE, 3/5 DEAD.

### Post-S0b (2026-05-21 오후 2차) update

ADR-012 S0b (`reflection` reader 신설) 머지 후 상태:

| Slot | 변동 | 새 reader 위치 |
|---|---|---|
| `reflection` | **DEAD → ALIVE** | `core/agent/reflection_policy.py` 의 `_load_reflection_policy_override` + `apply_reflection_policy` → `core/agent/loop/_reflection.py` 의 reflection LLM 호출 직전 적용 |

**현재 상태**: 3/5 ALIVE, 2/5 DEAD. 남은 dead slot: `decomposition` (S0c 예정) / `retrieval` (S0d 처치 결정 예정).

## 4. 인과 체인의 끊김

```
mutator LLM
  ↓ apply_mutation()
  ↓ load_policy(<sot_file>)
  ↓ write_policy(<sot_file>)
  ↓ [4 slot 의 경우 인퍼런스 reader 부재 — 정책 변경이 행동에 반영되지 않음]
  ↓
에이전트 응답 (정책 변경 무관)
  ↓ Petri eval
  ↓ dim_means (변동 없음)
  ↓ fitness (변동 없음)
  ↓ baseline.json (promote 불가)
```

→ 4 slot 의 mutation 은 fitness gate 에서 항상 "no signal" 로 처리된다. mutator 는 이걸 "이 slot 은 fitness 개선이 어려운 영역" 으로 잘못 학습할 수 있다.

## 5. ALIVE slot 의 상세 — `prompt`

`prompt` 만이 진화 압력에 닿는 유일한 slot. 인퍼런스 경로:

| 단계 | 코드 위치 | 동작 |
|---|---|---|
| 1 | `core/agent/system_prompt.py:57` | `_load_wrapper_override()` 가 `wrapper-sections.json` 의 sections 를 읽음 |
| 2 | `system_prompt.py:79-80` | SoT fallback 검사 (override 가 없으면 default sections) |
| 3 | `system_prompt.py:194` | `build_system_prompt()` 가 호출되어 override sections 를 prompt 본문에 inject (`:198` audit / `:210` normal mode) |
| 4 | `core/agent/loop/_context.py:103` | `build_system_prompt` 호출자 — loop context 구성 진입점 |
| 5 | `core/agent/loop/agent_loop.py` | 구성된 system prompt 가 LLM 호출 경로로 흘러들어감 |
| 6 | Petri eval | 변경된 system prompt 로 응답 → dim_means 변동 → fitness gate 작동 |

이게 5축 중 유일하게 닫힌 루프. 나머지 4축은 (1)→(2) 사이에서 끊김.

## 6. DEAD slot 별 권고

### 6a. `tool_policy` (S0a 머지 완료, 2026-05-21)

| 항목 | 내용 |
|---|---|
| 의도 | 도구 선택/허용/우선순위 정책의 진화 (Voyager 의 tool selection 학습) |
| audit 시점 | `tool-policy.json` 파일은 mutate 가능하지만 어떤 도구 호출 경로도 이걸 읽지 않음 |
| S0a 머지 후 | `core/agent/tool_policy.py` 신설 (`_load_tool_policy_override` + `apply_tool_policy`), `core/agent/loop/_helpers.py:get_agentic_tools` 의 단일 적용 지점에서 호출. schema: `allowed_tools` / `forbidden_tools` / `priority_order` (list[str] 또는 mutation 의 string payload 정규화) |
| 권고 B (deprecate) | `TARGET_KINDS` 에서 제거. 5축 → 4축으로 축소 명시 |
| ROI 추정 | **권고 A** — `broken_tool_use` dim 직접 영향. 5축 중 가장 양의 압력 우호적인 dim 이라 ROI 높음 |

### 6b. `decomposition`

| 항목 | 내용 |
|---|---|
| 의도 | 작업 분해 (multi-step plan) 의 진화 |
| 현재 | `GoalDecomposer` (`core/orchestration/goal_decomposer.py`) 의 분해 prompt 가 hardcoded — `decomposition.json` 무관 |
| 권고 A (살리기) | `GoalDecomposer` 의 prompt 가 현재 `core.llm.prompts.load_prompt("decomposer", "system")` 로 별도 SoT 에서 로드되므로, `decomposition.json` 과 그 SoT 의 연결 (load_prompt 가 `decomposition.json` 의 sections override 를 우선 적용) 또는 `_load_decomposition_policy()` 신설로 `wrapper-sections` 패턴 재사용 |
| 권고 B (deprecate) | 같음 |
| ROI 추정 | **권고 A** — 작업 분해 품질이 `task_success_rate` (단기 S1 의 `ux_means` 의 한 축) 직접 영향 |

### 6c. `retrieval`

| 항목 | 내용 |
|---|---|
| 의도 | "Retrieval (RAG / memory) policies" (`program.md:75` 의 placeholder 설명) |
| 현재 | 인퍼런스 경로에 retrieval 자체가 없음 (GEODE 는 현재 외부 vector store 없음) |
| 권고 A (살리기) | Retrieval 인프라 자체를 신설 + reader 신설 — **큰 작업**. 외부 인프라 (embedding model + vector store) 도입 필요 |
| 권고 B (deprecate) | 현재 단계에서는 deprecate 가 정직함. RAG 인프라가 신설되는 시점에 다시 도입 |
| ROI 추정 | **권고 B 단기 / 권고 A 중-장기 conditional** |

### 6d. `reflection` (S0b 머지 완료, 2026-05-21)

| 항목 | 내용 |
|---|---|
| 의도 | 응답 생성 후 self-critique 정책 |
| audit 시점 | `_REFLECTION_TOOL` schema + `_SYSTEM_PROMPT` 가 module-level constant 로 hardcoded — `reflection.json` 무관 |
| S0b 머지 후 | `core/agent/reflection_policy.py` 신설 (`_load_reflection_policy_override` + `apply_reflection_policy`), `core/agent/loop/_reflection.py` 의 reflection LLM 호출 직전 적용. schema: `description` / `system_prompt` (둘 다 string). `input_schema` 는 contract 보존 차원에서 mutate 대상 아님 |
| 권고 B (deprecate) | 같음 |
| ROI 추정 | **권고 A** — reflection 품질 ↑ → 응답 품질 ↑ → `admire_means` (단기 S2) 와 `ux_means` 동시 영향 |

## 7. ADR-012 에 대한 함의 (S0 작업 정의)

ADR-012 의 단기 시퀀스는 **5 slot reader 가 모두 살아있다** 는 잘못된 가정 위에 구축되어 있었다. 이 audit 의 결과로 **S0 (audit + dead slot 처치)** 가 ADR-012 의 가장 앞단으로 들어가야 한다.

**S0 sub-PR 권고 시퀀스** (audit 결과 기반):

| Sub-PR | 작업 | 우선순위 |
|---|---|---|
| S0a | `tool_policy` reader 신설 (권고 6a-A) — `broken_tool_use` dim 직접 영향 | 단기 1 |
| S0b | `reflection` reader 신설 (권고 6d-A) — `admire_means` + `ux_means` 동시 영향 | 단기 2 |
| S0c | `decomposition` reader 신설 (권고 6b-A) — `task_success_rate` 영향 | 단기 3 |
| S0d | `retrieval` 명시적 deprecate (권고 6c-B) — `TARGET_KINDS` 에서 제거, 5축 → 4축 축소 (또는 RAG 인프라 신설 결정 시까지 보류) | 단기 4 또는 deprecate |

S0a-c 완료 후에야 ADR-012 의 단기 S1 (`ux_means` 신설) 이 진정한 의미를 가진다. dead slot 의 reader 가 살아나면서 진화 압력이 4축까지 확장되고, 그 위에 fitness 다축화 (`ux_means` + `admire_means`) 가 얹히는 순서.

## 8. CHANGELOG / PR-body parity 보장

이 audit 의 모든 인용은 grep-provable:

```bash
grep -n "_load_wrapper_override" core/agent/system_prompt.py
grep -n "GoalDecomposer" core/agent/loop/_decomposition.py
grep -n 'load_prompt("decomposer"' core/orchestration/goal_decomposer.py
grep -n "_REFLECTION_TOOL" core/agent/loop/_reflection.py
grep -n "PR-6 stops at the" core/self_improving_loop/policies.py
# Reader 부재 — 4 DEAD slot 의 SoT 파일명이 인퍼런스 디렉토리 어디에서도
# 참조되지 않는지 확인 (self_improving_loop 의 mutation 정의/디스패처는 제외):
for slot in tool-policy.json decomposition.json retrieval.json reflection.json; do
  grep -rn "$slot" core/agent core/orchestration core/skills core/llm plugins autoresearch \
    | grep -v "self_improving_loop/policies.py" \
    | grep -v "self_improving_loop/runner.py" \
    | grep -v "test_"
done
```

invariant test (`tests/test_self_improving_5_slot_reader_audit.py`) 가 각 인용 라인의 존재를 pin 한다. dead slot 의 reader 가 미래에 신설되면 (S0a-c PR 들이 머지되면) 해당 test 가 명시적으로 갱신되도록 anchor 가 박혀있다.

## 9. 참고

- `core/self_improving_loop/policies.py:29-37` — PR-6 의 의도적 미완성 자백
- `core/agent/system_prompt.py:57-194` — `prompt` slot 의 살아있는 reader 경로
- `core/agent/loop/_decomposition.py:31` — hardcoded `GoalDecomposer`
- `core/agent/loop/_reflection.py:65-160` — hardcoded reflection tool schema
- `autoresearch/program.md:75` — `retrieval` 의 placeholder 설명
- ADR-012 (작성 예정) — 이 audit 의 함의를 반영한 surface tier 명세
