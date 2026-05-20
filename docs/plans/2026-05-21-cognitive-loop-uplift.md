# Cognitive loop uplift + paperclip-style abstraction gap fill

> **Date**: 2026-05-21 · **Author**: Claude Opus 4.7 (1M) · **Driving directives** (user, 2026-05-21):
>
> 1. self-improving loop 가 닿는 hardcoded 모델/하네스 선택지 매핑 (완료 — see Tier A-E in conversation)
> 2. *Gap 메우는 작업부터 진행하고* + 6 cognitive enhancement directives
> 3. *플랜 작성 → 워크플로우 (구현/검증-Codex MCP)로 진행*

## 0. Driving observation

GEODE 의 *self-improving loop* 는 외부에서 보면 "claude-opus-4-7 가 program.md 를 mutate → autoresearch 가 GEODE 를 audit → baseline.json 갱신" 의 closed loop 이지만, 내부에는 추상화가 *반쪽만* 되어 있다. seed_generation + petri_audit 는 manifest+role+source 의 paperclip-style 추상화를 마쳤지만, **mutator 자체** 와 **autoresearch train.py 의 TARGET/JUDGE constants** 는 추상화 갭이다. 같은 mutator 가 다른 model 로 시도되거나 다른 provider 로 라우팅되려면 코드 변경이 필요한 상태.

동시에, cognitive uplift 6개 directive 는 *agentic loop 의 인지 구조* 를 명시적 데이터 + telemetry 로 surface 하는 작업이다. CognitiveState 가 implicit message history 안에 묻혀 있으면 self-improving loop 가 mutation 의 causal attribution 을 만들 수 없다 (어떤 *state* 의 *어떤 part* 가 audit dim 의 어떤 *delta* 를 일으켰는지 추적 불가).

따라서 두 작업이 자연스러운 한 쌍을 이룬다 — **gap fill 이 paperclip 추상화의 missing pieces 를 채우고, cognitive uplift 가 self-improving 의 input 데이터 quality 를 끌어올린다**.

## 1. Scope summary

| ID | Theme | Tier | PR target | Effort |
|----|-------|------|-----------|--------|
| **G-A** | mutator role manifest — `[self_improving_loop.mutator]` (default_model + allowed + source) | gap fill | PR-1 | M |
| **G-B** | autoresearch train.py TARGET/JUDGE → config knob | gap fill | PR-1 | S |
| **G-C** | program.md ↔ train.py model id single SoT | gap fill | PR-1 | S |
| **G-D** | `llm_extract_learning` hook glm literal → manifest | gap fill | PR-1 | S |
| **G-E** | settings.model(4-6) vs routing.toml(4-7) drift 정렬 | gap fill | PR-1 | S |
| **C-1** | `CognitiveState` 구조 — goal/subgoals/observations/hypotheses/failed_actions/confidence/next_action_policy/termination_criteria | cognitive | PR-2 | L |
| **C-6** | Cognitive loop telemetry — `perceive/plan/act/observe/reflect/update_memory` HookEvent 6종 | cognitive | PR-2 | M |
| **C-2** | Tool batch reflection node — observe → summarize → update belief → decide | cognitive | PR-3 | L |
| **C-3** | Episodic action-outcome memory — `~/.geode/memory/episodes.jsonl` + retrieval | cognitive | PR-4 | L |
| **C-4** | self-improving causal attribution — mutation × expected/observed dim movement + rollback condition | cognitive | PR-5 | L |
| **C-5** | Policy mutation 확장 — wrapper prompt → tool policy / decomposition / retrieval / reflection | cognitive | PR-6 | XL |

## 2. PR splitting

| PR | Scope | Base |
|----|-------|------|
| PR-1 | Gap fill G-A through G-E + plan MD | main |
| PR-2 | C-1 CognitiveState + C-6 telemetry (둘 다 데이터 구조 — 묶기 자연스러움) | main (PR-1 merge 후 rebase) |
| PR-3 | C-2 Reflection node — PR-2 의 CognitiveState 위 build | feature/PR-2 |
| PR-4 | C-3 Episodic memory — PR-2 의 telemetry events 가 input | feature/PR-2 |
| PR-5 | C-4 Causal attribution — PR-1 의 mutator manifest + PR-4 의 episodic memory 위 build | feature/PR-4 |
| PR-6 | C-5 Policy mutation — PR-5 의 attribution 위 build | feature/PR-5 |

Codex MCP 검증은 PR-1, PR-2, PR-3, PR-5 의 *merge 전* 단계에서 (anti-deception checklist + verification team skill 호출).

## 3. Socratic gate per item

각 item 마다 5 question (CLAUDE.md §2 Plan Socratic Gate).

### G-A — mutator role manifest

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재하나? | `grep -rn "self_improving_loop.mutator" core/` → 0 hits. petri/seed manifest 와 동일 패턴 부재. |
| Q2 | 안 하면 무엇이 깨지나? | mutator model 변경 = `runner.py:331` 코드 수정 필요. user override path 없음. self-improving loop 의 가장 fundamental 한 knob 인데 hardcoded. |
| Q3 | 어떻게 측정? | unit test: `MutatorManifest.load()` returns spec / runner.py 의 LLM call 이 manifest 의 default_model 사용 / user override (`~/.geode/config.toml [self_improving_loop.mutator] model = "..."`) 가 우선 |
| Q4 | 최소 구현? | (a) `core/self_improving_loop/manifest.py` new — `MutatorManifest` (default_model + allowed_models + source + role_contract); (b) `runner.py` 가 `anthropic.Anthropic()` → `core.llm.router.call_with_retry` 로 + manifest 의 model 사용; (c) tests. |
| Q5 | 3+ frontier 패턴? | YES — petri_audit (`[petri.role.auditor]`), seed_generation (`[seed_generation.role.generator]`), claw (`models.providers.<p>.auth`), Hermes (`PROVIDER_REGISTRY`). 4 codebase consensus. |

### G-B — autoresearch TARGET/JUDGE knob

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | NO. `TARGET_MODEL = "geode/gpt-5.5"` 는 module constant. |
| Q2 | 안 하면? | audit target/judge 변경 = code 수정. self-improving loop 가 GPT-5.5 가 아닌 다른 모델 시도 불가능 (mutation experiments 막힘). |
| Q3 | 측정? | `~/.geode/config.toml [self_improving_loop.run] target_model = "..."` 가 train.py 의 constant override; 미설정 시 manifest default 로 fallback. |
| Q4 | 최소? | `core/config/self_improving_loop.py` 에 `RunConfig` 추가; train.py 가 import. |
| Q5 | 패턴? | seed_generation 의 picker 가 같은 양식. |

### G-C — program.md ↔ train.py sync

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | NO — 둘 다 같은 model id 를 *독립적* 으로 카피. |
| Q2 | 안 하면? | program.md 의 mutation 이 train.py constant 와 어긋날 수 있음 — silent drift. CLAUDE.md DONT 표의 *reader-assumption drift* 패턴. |
| Q3 | 측정? | runtime invariant test: load(program.md).target_model == train.py constant. CI guard. |
| Q4 | 최소? | (a) train.py 가 program.md 를 parse + frontmatter 의 target_model/judge_model 을 SoT 로 사용; (b) invariant test. |
| Q5 | 패턴? | autoresearch upstream (Karpathy) 의 program.md = single SoT 패턴 정확히 매치. |

### G-D — llm_extract_learning glm literal

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | NO. `model="glm-4.7-flash"` literal at line 114. |
| Q2 | 안 하면? | learning extraction provider 변경 불가; 미인증 시 silent fail. |
| Q3 | 측정? | unit test: hook 호출 시 settings 의 어떤 model 이 사용되는지 verify. |
| Q4 | 최소? | `settings.learning_extract_model` 새 field (default `glm-4.7-flash`); hook 이 settings 에서 read. |
| Q5 | 패턴? | settings.model 의 표준 패턴. |

### G-E — settings.model vs routing default drift

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | drift 자체는 존재. 정렬 작업 없음. |
| Q2 | 안 하면? | `settings.model` = `claude-opus-4-6` (deprecated 인 듯 — `claude-opus-4-7` 가 latest). agentic loop default 가 outdated. |
| Q3 | 측정? | `settings.model` 의 default 가 `routing.toml [model.defaults] anthropic` 와 일치. CI guard. |
| Q4 | 최소? | `_settings.py:37` 의 `model` default 를 `"claude-opus-4-7"` 로 변경 (단순 bump); 또는 settings.model 의 default 를 *routing manifest 에서 lazy load* 로 변경. 후자가 더 paperclip-style 이지만 cold-start cost. **선택: 단순 bump** (가장 작은 변경, drift 만 fix). |
| Q5 | 패턴? | N/A — version sync 작업. |

### C-1 — CognitiveState 구조

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | partial — `ConversationContext.messages` 가 implicit container. 명시적 `goal/subgoals/observations/...` 구조 없음. |
| Q2 | 안 하면? | (a) reflection node (C-2) 가 input 없음; (b) episodic memory (C-3) 가 어느 state-snapshot 을 저장할지 모름; (c) causal attribution (C-4) 가 어느 state 차원이 audit dim 과 연결되는지 알 수 없음. C-2~C-6 모두 C-1 dependency. |
| Q3 | 측정? | (a) `CognitiveState` dataclass tests; (b) agentic loop 의 turn 마다 state 가 update 됨을 trace 로 확인; (c) telemetry event payload 에 state snapshot 첨부됨. |
| Q4 | 최소? | `core/agent/cognitive_state.py` new file — `dataclass CognitiveState` (8 field). `AgenticLoop.__init__` 에 state 인스턴스 attach. agentic loop 의 각 round end 에 state.observations / state.hypotheses 갱신. *state 자체는 LLM 이 작성 안 함* — extractor 가 round response 에서 derive. |
| Q5 | 패턴? | 3-codebase consensus: claw 의 `Session.context.state`, Hermes 의 `AgentMemory`, autoresearch 의 `RunState`. |

### C-2 — Reflection node

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | partial — 일부 tool 호출 후 LLM 가 자체적으로 observation 을 짜지만 *명시적 reflection step* 없음. |
| Q2 | 안 하면? | tool result 후 곧장 다음 action — *belief update 의 명시적 step 부재*. confidence/hypothesis pruning 없음. |
| Q3 | 측정? | tool batch 의 마지막 result 후 reflection node 가 *별도 LLM call* 로 (observe + summarize + decide) 출력; output 이 `CognitiveState` 갱신. |
| Q4 | 최소? | `core/agent/loop/_reflection.py` new — `reflect(state, tool_results) -> CognitiveState`. 선택적 (settings.cognitive_reflection_enabled = True default). |
| Q5 | 패턴? | CoT-trace, ReAct 의 (Observation → Thought → Action) 사이클. claw 의 `reflect()` step. |

### C-3 — Episodic action-outcome memory

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | partial — `core.memory` 가 user/project/feedback/reference 4 type. *action-outcome* type 없음. |
| Q2 | 안 하면? | self-improving loop 가 "이 tool 이 이 상황에서 X% 성공" 같은 causal 정보 활용 불가. |
| Q3 | 측정? | `~/.geode/memory/episodes.jsonl` append-only log; retrieval API 가 (situation_embedding, tool_name) → outcome list. |
| Q4 | 최소? | `core/memory/episodic.py` new. ToolExecutor 가 결과 export. Cap 1000 episodes (rolling). retrieval 은 cosine similarity. |
| Q5 | 패턴? | OpenClaw `ToolExecutionLog`, Voyager `SkillLibrary`, autoresearch `seed_pool.jsonl`. |

### C-4 — Causal attribution

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | partial — `mutations.jsonl` 가 audit log. expected/observed dim movement schema 없음. |
| Q2 | 안 하면? | mutation 의 causal attribution 부재 — `audit_failed → rollback` 만 가능, *어떤 dim 이 어떻게 움직여서 PROMOTE 가 일어났는지* 추적 안 됨. |
| Q3 | 측정? | mutation event payload: `{mutation_id, expected_dim: {<dim>: delta}, observed_dim: {<dim>: delta}, confidence, rollback_condition}`. paired baseline CI (95%) 가 dim 별로 movement 확인. |
| Q4 | 최소? | `autoresearch/state/mutations.jsonl` schema 확장. `_apply_mutation` 가 expected_dim 을 prompt LLM 에서 추출. post-audit `_check_promotion` 가 observed_dim + CI 계산. |
| Q5 | 패턴? | autoresearch upstream §5 (Karpathy) 의 paired-test ratchet. |

### C-5 — Policy mutation 확장

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | NO — 현재 mutation target = *wrapper prompt section* only. |
| Q2 | 안 하면? | tool policy / decomposition policy / retrieval policy / reflection policy 의 evolution 부재. self-improving 이 prompt level 에만 작용. |
| Q3 | 측정? | mutation 의 target field 새 4 enum 추가 (`prompt`, `tool_policy`, `decomposition`, `retrieval`, `reflection`). 각 target 별 separate file + manifest. |
| Q4 | 최소? | mutation runner 가 `target_kind` 받음; 각 kind 별 SoT file (wrapper_prompt_sections.json + tool_policy.json + ...). 한 PR 으로 끝나기 위해 *각 kind 별 file* 만 생성 + runner switch — 실제 *learning loop* 는 follow-up. |
| Q5 | 패턴? | Voyager (curriculum + skill library + critic), Eureka (reward policy mutation). |

### C-6 — Cognitive loop telemetry

| # | Q | A |
|---|---|---|
| Q1 | 이미 존재? | partial — `LLM_CALL_STARTED/ENDED` 등 있음. `PERCEIVE/PLAN/ACT/OBSERVE/REFLECT/UPDATE_MEMORY` 없음. |
| Q2 | 안 하면? | Petri/visualization/diagnostics 가 cognitive cycle step 별 segmentation 불가. |
| Q3 | 측정? | `HookEvent` enum 에 6개 새 멤버 + 각 멤버 별 emit point (agentic loop round 의 step 별). transcript 가 6 type event 모두 기록. |
| Q4 | 최소? | `core/hooks/system.py:HookEvent` 에 6개 멤버 추가; agentic loop 의 round 함수 안에서 emit; transcript renderer 6 event 처리. |
| Q5 | 패턴? | OTel span pattern. inspect_ai 의 `Event` taxonomy. |

## 4. Verification metrics

각 PR 마다:

| Metric | Threshold |
|--------|-----------|
| ruff check | 0 errors |
| ruff format --check | clean |
| mypy core/ plugins/ | 0 errors |
| lint-imports | 4 contracts kept |
| pytest -m "not live" | green |
| Codex MCP LLM-as-Judge | PASS (or FAIL → fix-up PR) |
| CHANGELOG/PR-body parity (CLAUDE.md DONT row) | every verb grep-provable |

PR-2~PR-6 추가 검증:
- C-1: agentic loop 한 turn 실행 후 `state.observations` 가 비어있지 않음 (smoke)
- C-2: reflection node 의 토큰 비용 ≤ tool batch 비용의 30%
- C-3: episodic.jsonl 에 100 episodes 미만일 때 retrieval ≤ 50ms
- C-4: mutation 의 expected_dim 과 observed_dim 의 sign agreement rate (이 값을 baseline 으로 track)
- C-5: 각 policy file 의 schema 가 manifest 와 일치
- C-6: 한 round 동안 6 event 모두 emit (no silent skip)

## 5. Risk register

| Risk | Mitigation |
|------|-----------|
| PR-2 (CognitiveState) 가 agentic loop 의 hot path 라 latency 증가 | state derivation 을 LLM 호출 *없이* (regex/heuristic) 로 시작; LLM-driven derivation 은 PR-3 의 reflection node 안에 |
| PR-3 reflection node 가 tool 비용 폭증 | settings.cognitive_reflection_enabled toggle 도입; default OFF until manual benchmark |
| PR-4 episodic memory 의 1000-cap retention 이 부족 | rolling window + retrieval 만족도 metric 으로 cap 조정 — 후속 PR |
| PR-5 causal attribution 의 sign agreement rate 가 noise 에 묻힘 | n=10+ episode 까지 disabled (insufficient sample) — `promotion_gate.cognitive_sample_min` |
| PR-6 scope creep | "각 kind 별 file 만" 의 minimum-viable scope 고수; 실제 mutation loop 동작은 follow-up |

## 6. Anti-deception checklist (CLAUDE.md DONT 표 적용)

- [ ] G-A: runner.py 의 `anthropic.Anthropic()` 호출이 진짜 `call_with_retry` 로 대체됐는가 (`grep -rn "anthropic.Anthropic()" core/self_improving_loop/`)
- [ ] G-B: train.py constants 가 진짜 config 에서 read 하는가 (`grep -n "TARGET_MODEL =" autoresearch/train.py`)
- [ ] G-C: program.md 의 target_model 과 runtime config 가 invariant test 로 묶였는가
- [ ] G-D: hook 의 model 이 진짜 settings 에서 read 하는가
- [ ] C-1: state field 8개 모두 코드에 dataclass 로 존재하는가 (grep)
- [ ] C-2: reflection node 가 실제 LLM call 을 만드는가, 아니면 placeholder 인가
- [ ] C-3: episodic.jsonl 가 진짜 git-tracked 또는 .gitignore 명시되었는가 (PR-G5b 의 잘못된 path 사례 재발 방지)
- [ ] C-4: causal attribution payload 가 진짜 promotion gate 에 fed 되는가
- [ ] C-5: 각 policy kind 의 SoT file 이 진짜 mutation runner 에서 read 되는가
- [ ] C-6: 6 event 모두 transcript 에 *실제로* append 되는가 (`grep "PERCEIVE\|PLAN\|ACT" core/runtime_state/transcript.py`)

## 7. Codex MCP review schedule

| PR | Review focus |
|----|--------------|
| PR-1 | gap fill 의 hardcoded → manifest 전환이 *완전한가*. SDK 직접 호출 잔재 있나. |
| PR-2 | CognitiveState 의 8 field 가 *진짜* hot path 에서 update 되는가 (placeholder 검출) |
| PR-3 | reflection node 의 비용/효과 — 비용 budget 안에서 작동하는가 |
| PR-5 | causal attribution 의 statistical soundness — paired-test 가 정말 paired 인가 |
| 모든 PR | CLAUDE.md DONT 표 의 5+1 패턴 (parity / conditional-read / graceful-contract / reader-assumption-drift / knob-vs-deletion) 위반 검출 |

## 8. Reference

- 본 conversation 의 Tier A-E 매트릭스 (hardcoded vs tunable)
- `docs/research/model-ux-governance.md` X1.1 의 paperclip-style abstraction 패턴
- CLAUDE.md `DONT — Real Incidents` 표 — 6 frozen rows
- autoresearch upstream (Karpathy) program.md / mutator design
- OpenClaw `petri.plugin.toml` + `seed_generation.plugin.toml` (4-layer manifest)
- Voyager (curriculum + skill library) — policy mutation 의 frontier reference
