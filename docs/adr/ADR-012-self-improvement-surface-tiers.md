# ADR-012: Self-Improvement Surface Tiers

## Status

Proposed (2026-05-21)

## Context

GEODE 는 weight-invariant evolutionary agent 군 (AlphaEvolve / Voyager / Reflexion / Promptbreeder 와 동위) 에 위치한다. 모델 가중치를 수정하는 대신, 모델 외부의 **에이전트 wrapper 정책** 5축을 mutator LLM 으로 진화시키고, autoresearch 의 fitness gate 가 Petri 17-dim 평가로 monotonic ratchet 을 제공한다 (`autoresearch/train.py`).

이 ADR 은 두 가지 직교 발견을 함께 다룬다.

### 발견 1 — 진화 압력의 면적 누수 (1/17)

Petri 17-dim 중 **양의 압력 (성능 향상) 으로 작동하는 dim 은 사실상 `broken_tool_use` 1개** 뿐이고 나머지는 alignment / safety evaluation 축으로 음의 압력 ("안 망가지기") 이다. 17-dim 의 가중치가 동일 차원에 압축돼 fitness 의 정의역이 "에이전트가 망가지지 않는지" 에 쏠려 있다. seed pool 의 정교화 + skill 진화의 노력 대부분이 alignment dim 의 마이크로-튜닝으로 흡수되는 구조적 누수.

### 발견 2 — Mutation 표면의 wiring 누수 (1/5)

PR-AUDIT-5SLOT (`docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md`) 가 진단한 결과 — mutator 가 mutate 할 수 있다고 명세된 5 slot 중 인퍼런스 reader 가 살아있는 slot 은 `prompt` 하나뿐. 나머지 4 (`tool_policy` / `decomposition` / `retrieval` / `reflection`) 는 SoT 파일 + mutation dispatcher 는 있지만 **인퍼런스 경로에서 정책을 읽어 행동에 반영하는 reader 가 부재** — `core/self_improving_loop/policies.py:29-37` 의 docstring 이 직접 자백한다 (PR-6 의 의도적 follow-up 미완 + 잊혀짐).

→ 두 누수가 곱해지면 GEODE 의 self-improving loop 는 **명세상 5축 × 17-dim = 85 면적이지만 실제 진화 압력은 1축 × 1-2dim = 1-2 면적**으로 운영 중이다. 누수 대비 1/40 ~ 1/85 의 진화 효율.

### 발견 3 — Fine-tune 표면의 채널 제약

현 운영 채널 (Anthropic API / Claude Code 구독 / OpenAI Codex CLI 구독) 에서 weight fine-tune 표면은 사실상 0 ~ 매우 좁음. Bedrock Haiku 의 SFT 만 부분 가능, Opus/Sonnet/GPT-5 의 direct fine-tune 은 미공개. 즉 진화의 본체는 inference-only 채널에서의 **surrogate fine-tune** 으로 가야 한다.

## Decision

이 ADR 은 GEODE 의 self-improvement 표면을 다음 4가지 축으로 재정렬한다.

1. **Tier 1 / Tier 2** 분리 — mutation 허용/금지 영역의 명시적 정의
2. **Fitness 다축화** — `dim_means` (현재) + `ux_means` + `admire_means` 의 multi-axis strict-reject ratchet
3. **Surrogate fine-tune 5 경로** — weight 권한 없이 inference-only 채널에서 dataset 이 5축 진화를 증폭하는 메커니즘
4. **단기 → 중기 → 장기 성장 곡선** + **의사결정 게이트 G1-G6**

---

### 1. Tier 1 (mutation 허용) / Tier 2 (mutation 금지)

#### Tier 1 — 진화 표면

| 표면 | 위치 | 현재 상태 | reader 상태 |
|---|---|---|---|
| 5축 SoT `prompt` | `wrapper-sections.json` | **가동 중** | **ALIVE** — `system_prompt.py:57` chain |
| 5축 SoT `tool_policy` | `tool-policy.json` | mutation target 정의만 | **DEAD** — S0a reader 신설 필요 |
| 5축 SoT `decomposition` | `decomposition.json` | mutation target 정의만 | **DEAD** — `core/orchestration/goal_decomposer.py` 가 `load_prompt("decomposer", "system")` 로 별도 SoT 사용 중. `decomposition.json` 미연결. S0c reader 신설 필요 |
| 5축 SoT `retrieval` | `retrieval.json` | mutation target 정의만 | **DEAD** — RAG 인프라 부재. S0d 에서 deprecate 또는 보류 |
| 5축 SoT `reflection` | `reflection.json` | mutation target 정의만 | **DEAD** — `core/agent/loop/_reflection.py:65-160` 의 `_REFLECTION_TOOL` 이 module-level constant. S0b reader 신설 필요 |
| Skill 정의 | `.claude/skills/<name>/` (20+개) | 수동 (mutation 채널 밖) | n/a (M1 에서 6번째 target_kind 로 개통) |
| Agent contract | `.claude/agents/seed_*.md` (7-role) | 수동 (mutation 채널 밖) | n/a (M2 에서 7번째 target_kind, 좁게 — mutator 자신 제외) |
| Plugin 분석 코드 | `plugins/petri_audit/`, `plugins/seed_generation/` | 수동 | n/a (M5 에서 격리된 진입 슬롯) |
| Seed pool | `plugins/seed_generation/` co-scientist 7-role | **가동 중 (별도 채널)** | S3 에서 공동 ratchet 으로 묶임 |

#### Tier 2 — 자기 보호 영역 (mutation 절대 금지)

| 영역 | 위치 | 금지 이유 |
|---|---|---|
| Bootstrap | `core/runtime.py`, `core/agent/loop/` | 자기 호출 경로 → 무한루프/자기파괴 |
| Self-improving runner | `core/self_improving_loop/runner.py` | mutator 자기 수정 → ratchet 우회 |
| Fitness gate | `autoresearch/train.py`, `compute_fitness`, `baseline.json` 평가 코드 | 평가 기준 mutate → monotonic 보장 무력화 |
| CI ratchet | `tests/test_ratchet_policies_in_repo.py` | guard 자체 mutate → CANNOT 우회 |
| HookSystem | `core/hooks/system.py` | policy chain 우회 |
| Mutator agent contract | mutator 자신의 system prompt | 재귀 자기수정 |
| 4-layer 의존성 룰 | `pyproject.toml [tool.importlinter]` (line 173-233 — 3 contracts) | 아키텍처 contract 우회 |
| Version stamp | `CLAUDE.md` / `README.md` / `pyproject.toml` / `CHANGELOG.md` 의 version 동기화 | mutation 으로 version drift → release discipline 우회 |

`tests/test_adr_012_tier_2_deny_list.py` (이 PR 에서 신설) 가 Tier 2 deny-list 를 강제한다 — Tier 2 파일이 `TARGET_KIND_TO_SOT_FILE` 또는 mutation dispatcher 의 target 목록에 등장하면 즉시 test 실패. PR-AUDIT-5SLOT 의 ratchet 패턴 (`test_ratchet_policies_in_repo.py`) 은 policy SoT 의 gitignore/migration 만 pin 하므로 별개의 deny-list 가 필요했고, 이 ADR PR 이 그 deny-list 의 첫 invariant 를 함께 도입한다.

### 2. Fitness 다축화 — 3축 multi-axis strict-reject ratchet

현재 `baseline.json` 의 fitness 는 `dim_means` 1축. 이 ADR 은 두 축을 추가한다.

```
baseline.json {
  "dim_means":     {...17 dim...},                                     # Petri alignment (음의 압력)
  "ux_means":      {success_rate, token_cost, revert_ratio, latency},  # 행동 (양의 압력)
  "admire_means":  {pairwise_win_rate, human_calibration_corr},        # 체감 (양의 압력)
  "seed_pool_diversity": {...}                                         # cohort 균형
}
```

**Promote 규칙**: 4 묶음 모두 baseline 대비 monotonic 또는 within-stderr 일 때만. 한 축이라도 regress 면 strict reject — AlphaEvolve 식 다축 정책 그대로.

축별 권장 가중치 (초기): `dim_means` 0.4, `ux_means` 0.3, `admire_means` 0.3. 운영하면서 `[self_improving_loop.fitness] axis_weights = {...}` TOML 으로 조정.

#### `ux_means` 구성 (S1 신설)

| 필드 | 출처 | 측정 단위 |
|---|---|---|
| `success_rate` | `RunLog.success` (boolean) 누적 | 0.0 - 1.0 |
| `token_cost` | `LLMUsageAccumulator` 합산 | USD or token 수 |
| `revert_ratio` | git history — merged 후 revert 비율 | 0.0 - 1.0 |
| `latency` | OTel trace 의 task completion time | seconds |

#### `admire_means` 구성 (S2 신설)

`plugins/seed_generation/agents/ranker.py` 의 ELO tournament + 3-voter cross-provider panel 인프라를 그대로 재사용해서 정책 mutation 의 평가 채널로 확장.

| 필드 | 출처 | 측정 단위 |
|---|---|---|
| `pairwise_win_rate` | mutation before/after 응답의 LLM-judge pairwise (3-voter Opus/Sonnet/GPT-5 panel) | 0.0 - 1.0 |
| `human_calibration_corr` | 분기 단위 human label 50-100 sample 과 LLM-judge 점수의 상관계수 | -1.0 - 1.0 |

Goodhart 방어: judge model 의 주기적 교체 + 3-voter cross-provider panel (PR-COSCI-1 의 `required_diversity_providers ≥ 2` 규약 재사용) + human L4 batch refresh.

### 3. Surrogate fine-tune — 4 경로 (inference-only)

현 운영 채널에서 weight fine-tune 표면이 닫혀 있으므로, DPO/RLHF dataset 은 weight 권한 미래 대비 + inference-only 경로의 즉시 가동 표면 두 가지 역할을 동시에 한다. dataset → 4 경로:

```
mutations.jsonl  →  dpo_pairs.jsonl  ┐
                                      ├─→  ① few-shot pool (prompt cache)
                                      ├─→  ③ mutator candidate reference
                                      ├─→  ④ judge calibration corpus (admire_means)
                                      └─→  ⑤ reflection bad-pattern anchor
```

**경로 ② RAG vector store 는 drop** — `retrieval` slot 의 reader 부재 + 외부 인프라 (로컬 embedding + sqlite-vec/chromadb) 도입 비용 대비 효과 불명확. retrieval slot 의 reader 가 살아나는 시점 (S0d 또는 후속 ADR) 에 reconsider.

| 경로 | 슬롯 | 효과 | 한계 |
|---|---|---|---|
| ① few-shot pool | 5축 `prompt` (이미 reader 있음) | "이런 입력엔 이렇게" in-context learning. target_kind 별 분리 | context window 한정 (top-N) |
| ③ mutator candidate reference | mutator system prompt | mutation 후보 품질 ↑ → reject 비율 ↓ → 진화 속도 ↑ | self-reinforcing local minimum (mitigation: high-temp + random 교체) |
| ④ judge calibration | ranker / voter prompt | judge Goodhart fooling 방어 + 일관된 기준 | calibration corpus stale (mitigation: 분기 human refresh) |
| ⑤ reflection anchor | 5축 `reflection` (S0b 후) | "이렇게는 안 함" negative few-shot | reflection 토큰 비용 ↑ (mitigation: anchor 압축) |

**weight 권한이 열리는 시점** (Anthropic Opus/Sonnet fine-tune 공개 / Bedrock Haiku 보조 라우팅 도입 / open-weight self-hosted 전환) 에는 DPO dataset 그대로 fine-tune publisher 에 emit — 동일 dataset 의 옵션 가치가 inference-only 채널에서부터 누적된다.

### 4. 단기 → 중기 → 장기 성장 곡선

#### S0 — Audit + Dead Slot 처치 (이미 진행 시작)

PR-AUDIT-5SLOT 으로 진단 완료. dead slot 별 reader 신설:

| Sub-PR | 작업 | ROI |
|---|---|---|
| S0a | `tool_policy` reader 신설 — `core/agent/loop/AgenticLoop._select_tools()` 또는 동등 진입점에서 `tool-policy.json` 의 allowed/forbidden/priority 정책 읽어 도구 후보 필터 (~30 line) | **단기 1순위** — `broken_tool_use` dim 직접 영향 (17-dim 중 유일한 양의 압력 dim) |
| S0b | `reflection` reader 신설 — `_REFLECTION_TOOL` 의 description/instructions/criteria 를 `reflection.json` sections 로 override (`wrapper-sections` 패턴 재사용) | **단기 2순위** — `admire_means` + `ux_means` 동시 영향 |
| S0c | `decomposition` reader 신설 — `load_prompt("decomposer", "system")` 과 `decomposition.json` 의 sections 연결 (또는 `_load_decomposition_policy()` 신설) | 단기 3순위 — `task_success_rate` 영향 |
| S0d | `retrieval` 처치 결정 — RAG 인프라 신설 여부 결정 후 (a) reader 신설 (b) `TARGET_KINDS` 에서 제거 5축 → 4축 축소 (c) 보류 | 단기 4순위 또는 deprecate |

#### S1-S5 — Fitness 다축화 + 공동 ratchet + In-context wiring

| Sub-PR | 작업 |
|---|---|
| S1 | `ux_means` fitness 축 신설 — `RunLog`/`LLMUsageAccumulator`/git history/OTel trace 수집 + `compute_fitness` 다축화 |
| S2 | `admire_means` LLM-as-judge 채널 — ranker.py 의 ELO + 3-voter panel 인프라 재사용 |
| S3 | 공동 ratchet — `baseline.json` 의 4-묶음 schema + monotonic AND/OR rule |
| S4 | task-completion seed cohort — RunLog 에서 실제 사용자 task 추출 + `task_success_rate` 측정 |
| S5 | 4종 in-context slot 의 명시적 schema — `few_shot_examples` / `recent_promoted_examples` / `historical_judge_examples` / `bad_pattern_anchors` |

#### M1-M5 — Tier 1 확장 + DPO pipeline

| Sub-PR | 작업 |
|---|---|
| M1 | Skill mutation 슬롯 개통 — `.claude/skills/<name>/` 를 6번째 `target_kind` |
| M2 | Agent contract mutation 슬롯 — `.claude/agents/seed_*.md` 를 7번째 `target_kind` (mutator 자신 제외) |
| M3 | Prompt cache few-shot 자동 적재 |
| M4.0 | DPO 수집 인프라 — `eval_response_recorded` SessionJournal event + mutation row hydrate 필드 |
| M4.1 | DPO canonical pack — `policies/dpo_pairs.jsonl` git-tracked |
| M4.2 | Publisher adapter — OpenAI Preference / Bedrock SFT / HF TRL DPO |
| M4.3 | Redaction + stats + CI ratchet 화이트리스트 |
| M4.4 | In-context wiring — ①③④⑤ 4 경로의 실제 wiring (5축 retrieval slot reader 가 살아 있으면 ② 도) |
| M5 | Plugin 코드 mutation 진입 — `plugins/*/` 격리 |

#### 장기 — Weight 표면 시나리오 대비

| 시나리오 | 트리거 (외부) | 준비 |
|---|---|---|
| (a) Anthropic Opus/Sonnet fine-tune 공개 | Anthropic 발표 | M4.2 의 DPO dataset 으로 즉시 학습 시작 |
| (b) Bedrock Haiku 보조 라우팅 도입 | 내부 결정 | 라우터에 Haiku-tier 추가 + Haiku fine-tune cycle |
| (c) Open-weight (Llama/Mistral) self-hosted 전환 | 비용/통제 필요성 | 인퍼런스 인프라 (vLLM/SGLang) + LoRA pipeline |

### 5. 의사결정 게이트 G1-G6

| Gate | 트리거 | 결정 | 단계 |
|---|---|---|---|
| G1 | 5축 reader audit 완료 (PR-AUDIT-5SLOT) | dead slot 별 처치 시퀀스 (S0a-d) 진입 | **완료** |
| G2 | S0a-c 머지 후 5축 mutation 의 fitness delta 가 음의 압력 dim 에 90%+ 편향 (4 주 측정 window) | `ux_means` + `admire_means` 두 양의 축 신설 (S1+S2) | 단기 |
| G3 | seed 진화 promote 율과 정책 fitness promote 율의 시간 상관계수 < 0.1 (4 주 측정) | 공동 ratchet (S3) — baseline.json 4-묶음 monotonic | 단기 |
| G4 | S0+S1-S5 후에도 `broken_tool_use` dim 의 baseline 개선폭 < stderr (8 주 측정) | Skill mutation 슬롯 (M1) | 중기 |
| G5 | Tier 1 의 G1-G4 안정화 + 4 주 연속 monotonic promote | Plugin mutation 진입 (M5) | 중기 |
| G6 | (a)/(b)/(c) 중 하나 충족 (외부 트리거) | 해당 시나리오 pipeline 활성 | 장기 |

각 게이트의 측정 임계값은 S1 의 `ux_means` metric 정착 후 한 번 더 재평가한다 — S1 가 cost/latency/success-rate 의 baseline 분포를 확립하면 G2-G5 의 stderr / 상관계수 임계값을 데이터-기반으로 정밀화 가능.

## Consequences

### 긍정적 결과

1. **진화 면적 1/85 → ~17/85 (Tier 1 확장 완료 후)** — 5 slot 모두 reader 가 살아나면 5축 진화가 실현된다. + Skill / Agent contract / Plugin 까지 가면 추가 표면.
2. **fitness 동력의 정직성** — `ux_means` + `admire_means` 의 양의 압력 두 축이 alignment dim 의 음의 압력 16개를 균형 잡는다. mutation 의 진화 동력이 alignment 마이크로-튜닝에서 벗어남.
3. **weight 권한 외부 변수에 대한 옵션 가치** — DPO dataset curation 이 inference-only 채널에서 즉시 가동되면서 (a)/(b)/(c) 어느 weight 시나리오가 먼저 와도 즉시 진입 가능.
4. **자기수정 안전성** — Tier 2 명시 + CI ratchet 화이트리스트로 mutator 의 재귀 자기수정 회피.

### Risks + Mitigations

| Risk | Mitigation |
|---|---|
| **Petri 17-dim 마이크로-튜닝 빨림** | G2 의 `ux_means` + `admire_means` 두 양의 축 단기 신설 |
| **LLM-as-judge Goodhart fooling** | judge 주기 교체 + 분기 human L4 batch + 3-voter cross-provider panel |
| **자기수정 재귀** | Tier 2 의 mutator contract 절대 보호 + `test_ratchet_policies_in_repo.py` 의 화이트리스트 |
| **Mutation surface 폭발 → 풀-pytest 비용** | Tier 1 확장 단계마다 worktree 격리 + per-mutation diff bisect |
| **CANNOT 가드 우회** | `tests/test_ratchet_policies_in_repo.py` 의 Tier 2 경로 화이트리스트 검증 |
| **dead slot 의 reader 신설 후 mutation 폭발** | S0a-c 가 각각 별도 PR — 한 번에 한 reader 만 활성, 영향 측정 후 다음 단계 |
| **Surrogate ↔ weight 표면 갭** | M4.2 의 DPO publisher adapter 가 권한 열릴 시점 즉시 진입 가능 상태 유지 |
| **자기참조 local minimum** (③ mutator reference) | high-temperature sampling + 풀 일부 random 교체 + 주기적 cold-start (dataset 안 본 mutator 호출) |
| **Context window 폭발** (5 경로 모두 prompt 에 inject) | 경로별 토큰 budget 분배 (few-shot 1k / mutator-ref 1k / judge-calib 0.5k / reflection-anchor 0.5k) + LLM 으로 anchor 압축 |

### 운영 dial 3층

| 층 | 노브 | 위치 |
|---|---|---|
| 가용 (즉시 조정) | `critical_margin` / dim 가중치 / λ / mutator model / target model / source channel / `fallback_to_payg` / `required_diversity_providers` | `train.py`, TOML, `/model` UI |
| 노출만 (mutation 채널 추가 필요) | Skill 본문 / Agent contract / Plugin 코드 | M1/M2/M5 |
| 미명세 (단기 신설) | `ux_means` 가중치 / `admire_means` 가중치 / 공동 ratchet rule / fitness axis weights TOML | S1/S2/S3 |

## Reference

- AlphaEvolve (Google DeepMind) — 알고리즘 함수의 evolutionary loop. 좁은 mutation surface + 강한 fitness gate
- Voyager (Wang et al.) — skill library 만 mutate, core agent loop 불변. Tier 분리의 frontier 사례
- Reflexion (Shinn et al.) — self-critique → reflection memory. 5축 `reflection` slot 의 영감
- Promptbreeder (Fernando et al.) — evolved prompt pool 이 다음 mutation 의 종자. 4 경로 ③ 의 frontier 사례
- AI Scientist (Sakana) — 연구 코드 자체 진화. M5 plugin mutation 의 frontier 사례
- STaR (Zelikman et al.) — reasoning chain dataset 으로 weight fine-tune. G6 (a)/(b) 의 frontier 사례
- Karpathy autoresearch — 본 ADR 의 fitness gate 본체. baseline.json + dim_means 17개 + compute_fitness
- `docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md` — S0 진단의 근거 문서
- `core/self_improving_loop/policies.py:29-37` — PR-6 의 의도적 follow-up 미완 자백 (1/5 누수의 출처)
- `autoresearch/train.py:220-250` — 17-dim 가중치 + `compute_fitness` 의 음의 압력 편향 (1/17 누수의 출처)
- `plugins/seed_generation/agents/ranker.py` — `admire_means` 의 ELO + 3-voter panel 인프라 재사용 출발점

## 후속 PR 시퀀스 (이 ADR 머지 후 즉시)

1. **S0a** — `tool_policy` reader 신설 (`broken_tool_use` dim 직접)
2. **S0b** — `reflection` reader 신설
3. **S0c** — `decomposition` reader 신설
4. **S0d** — `retrieval` 처치 결정 PR
5. **S1** — `ux_means` fitness 축 신설
6. **S2** — `admire_means` LLM-judge 채널
7. (이후) S3-S5 / M1-M5 / 장기 시나리오

각 PR 은 단일 fitness 축 추가 / 단일 target_kind 추가 / 단일 surrogate 채널 가동을 원자 단위로 보장. 단계 사이마다 baseline.json 이 다축 monotonic 유지 검증.
