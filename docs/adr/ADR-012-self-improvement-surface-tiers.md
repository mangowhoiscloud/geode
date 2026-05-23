# ADR-012: Self-Improvement Surface Tiers

## Status

Proposed (2026-05-21)

## Context

GEODE 는 weight-invariant evolutionary agent 군 (AlphaEvolve / Voyager / Reflexion / Promptbreeder 와 동위) 에 위치한다. 모델 가중치를 수정하는 대신, 모델 외부의 **에이전트 wrapper 정책** 5축을 mutator LLM 으로 진화시키고, autoresearch 의 fitness gate 가 Petri 17-dim 평가로 monotonic ratchet 을 제공한다 (`autoresearch/train.py`).

이 ADR 은 두 가지 직교 발견을 함께 다룬다.

### 발견 1 — 진화 압력의 면적 누수 (1/17)

Petri 17-dim 중 **양의 압력 (성능 향상) 으로 작동하는 dim 은 사실상 `broken_tool_use` 1개** 뿐이고 나머지는 alignment / safety evaluation 축으로 음의 압력 ("안 망가지기") 이다. 17-dim 의 가중치가 동일 차원에 압축돼 fitness 의 정의역이 "에이전트가 망가지지 않는지" 에 쏠려 있다. seed pool 의 정교화 + skill 진화의 노력 대부분이 alignment dim 의 마이크로-튜닝으로 흡수되는 구조적 누수.

### 발견 2 — Mutation 표면의 wiring 누수 (audit 시점 1/5, S0a-d 이후 명시적 4축으로 안정화)

PR-AUDIT-5SLOT (`docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md`) 가 진단한 audit 시점 결과 — mutator 가 mutate 할 수 있다고 명세된 5 slot 중 인퍼런스 reader 가 살아있는 slot 은 `prompt` 하나뿐. 나머지 4 (`tool_policy` / `decomposition` / `retrieval` / `reflection`) 는 SoT 파일 + mutation dispatcher 는 있지만 **인퍼런스 경로에서 정책을 읽어 행동에 반영하는 reader 가 부재** — `core/self_improving_loop/policies.py:29-37` 의 docstring 이 직접 자백한다 (PR-6 의 의도적 follow-up 미완 + 잊혀짐).

**S0a/S0b/S0c/S0d (2026-05-21 머지) 이후 상태**: `tool_policy` + `reflection` + `decomposition` 이 ALIVE 로 전환. `retrieval` 은 **명시적 deprecate** (S0d) — `TARGET_KINDS` 에서 제거되어 5축 → **4축으로 명시 축소** (path constant + dict 매핑은 미래 복원을 위해 보존). reader 위치 — `tool_policy`: `core/agent/tool_policy.py` → `_helpers.py:get_agentic_tools`. `reflection`: `core/agent/reflection_policy.py` → `_reflection.py` LLM 호출 직전. `decomposition`: `core/agent/decomposition_policy.py` → `core/agent/plan.py:decompose_async` 의 `load_prompt("decomposer", "system")` 호출 직후 (PR-CL-A1-followup 2026-05-23 에서 호출 site 가 `core/orchestration/goal_decomposer.py:_llm_decompose` 에서 `decompose_async` 로 이전 — wiring 자체는 동일). 따라서 audit 시점 1/5 → **현재 4/4 ALIVE** (deprecate 한 retrieval 제외).

→ 두 누수가 곱해지면 GEODE 의 self-improving loop 는 **명세상 5축 × 17-dim = 85 면적이지만 audit 시점 실제 진화 압력은 1축 × 1-2dim = 1-2 면적**으로 운영 중이었다 (1/40~1/85 누수). S0a-d 후 4축 × 1-2dim = 4-8 면적으로 회복, 5축 → 4축 명시 축소로 정직성 안정화. (`retrieval` 의 deprecate 근거는 §Decision.3a — Boris Cherny / arXiv 2605.15184 / Anthropic 공식 blog 의 3-source 합의 참조.)

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
| 5축 SoT `tool_policy` | `tool-policy.json` | **가동 중** (S0a, 2026-05-21) | **ALIVE** — `core/agent/tool_policy.py` (`_load_tool_policy_override` + `apply_tool_policy`) → `core/agent/loop/_helpers.py:get_agentic_tools` |
| 5축 SoT `decomposition` | `decomposition.json` | **가동 중** (S0c, 2026-05-21) | **ALIVE** — `core/agent/decomposition_policy.py` (`_load_decomposition_policy_override` + `apply_decomposition_policy`) → `core/agent/plan.py:decompose_async` 의 `load_prompt("decomposer", "system")` 호출 직후 적용 (override / prefix / suffix 3-mode). PR-CL-A1-followup (2026-05-23): 호출 site 가 `core/orchestration/goal_decomposer.py:_llm_decompose` → `core/agent/plan.py:decompose_async` 로 이전됨 (모듈 삭제), wiring 자체는 동일. |
| ~~5축 SoT `retrieval`~~ | `retrieval.json` | **Deprecated (S0d, 2026-05-21)** — `TARGET_KINDS` 에서 제거. path constant + dict 매핑은 보존 (미래 복원 가능) | **DEPRECATED** — 근거: §Decision.3a (Boris Cherny + arXiv 2605.15184 + Anthropic blog) |
| 5축 SoT `reflection` | `reflection.json` | **가동 중** (S0b, 2026-05-21) | **ALIVE** — `core/agent/reflection_policy.py` (`_load_reflection_policy_override` + `apply_reflection_policy`) → `core/agent/loop/_reflection.py` 의 reflection LLM 호출 직전 적용 |
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

### 2. Fitness 다축화 — 4축 multi-axis strict-reject ratchet

> **2026-05-23 amendment (PR-SIL-5THEME C1)** — 초안의 3축 (dim + ux + admire) 에서 **bench_means** 가 추가되어 **4축** 으로 확장됐다. 초기 운영의 `seed_pool_diversity` 슬롯은 cohort diversity 신호 readers 의 부재 + ELO tournament 가 panel diversity 를 이미 흡수하는 점이 확인돼 **명시적 deprecate**. 코드 상수 `FITNESS_DIM_4AX / FITNESS_UX_4AX / FITNESS_ADMIRE_4AX / FITNESS_BENCH_4AX` (`autoresearch/train.py:344-350`, sum=1.0 assert) 가 ground-truth.

현재 `baseline.json` 의 fitness 는 `dim_means` 1축. 이 ADR 은 세 축을 추가한다 (S1 `ux_means`, S2 `admire_means`, S6 `bench_means`).

```
baseline.json {
  "schema_version": 2,
  "raw": {
    "dim_means":     {...17-22 dim...},                                # Petri alignment (음의 압력)
    "dim_stderr":    {...},                                            # PR-1 of petri-schema-v2
    "sample_count":  {...},                                            # PR-1
    "measurement_modality": {...},                                     # PR-1 (judge_llm / analytics)
    "rubric_version": "v3-22dim-PR0",
    "eval_archive":  "<path>"
  },
  "axes": {
    "ux_means":      {success_rate, token_cost, revert_ratio, latency},          # S1 (행동, 양의 압력)
    "admire_means":  {pairwise_win_rate, human_calibration_corr},                # S2 (체감, 양의 압력)
    "bench_means":   {swe_bench_pro_pass, livecodebench_pro_accuracy, ...}       # S6 (capability, 양의 압력)
  }
}
```

> **Deprecated slot — `seed_pool_diversity`** (2026-05-23 amendment): 초안에 4번째 묶음으로 명시됐으나 코드 0 grep, ELO tournament 의 cross-provider panel (`required_diversity_providers ≥ 2`) 이 diversity 신호를 admire_means 안에 이미 흡수. 명시적 deprecate — fitness 축 산정 4축 (dim + ux + admire + bench) 에서 제외.

**Promote 규칙**: 4 축 모두 baseline 대비 monotonic 또는 within-stderr 일 때만. 한 축이라도 regress 면 strict reject — AlphaEvolve 식 다축 정책 그대로. **§S6 (bench) 추가 후의 cross-validation 규칙**: dim promote + bench regress = `alignment_only_fooling`, bench promote + dim critical regress = `capability_at_alignment_cost`. 두 conflict 모두 strict-reject (`compute_fitness → 0.0`) — Goodhart 양방향 방어.

축별 권장 가중치 (2026-05-23 amendment 후): `dim_means` 0.30, `ux_means` 0.25, `admire_means` 0.20, `bench_means` 0.25 (sum=1.0). 운영하면서 `[self_improving_loop.fitness] axis_weights = {...}` TOML 으로 조정.

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

### 3a. Retrieval slot deprecate 결정 (S0d, 2026-05-21)

5축 mutation 중 마지막 dead slot `retrieval` 의 처치 — 3가지 옵션을 frontier evidence 로 평가했다.

| 옵션 | 의미 | 비용 | 채택? |
|---|---|---|---|
| A. **Deprecate** | `TARGET_KINDS` 에서 제거 + path constant 보존 (미래 복원 가능) | 매우 낮음 | **채택** |
| B. RAG 인프라 신설 | sqlite-vec/chromadb + 로컬 embedding (BGE/e5) + reader 신설 | 중-高 | 보류 |
| C. 보류 | 결정 미루기 | 0 | 거부 |

#### 옵션 A 의 frontier 3-source 합의

**1. Boris Cherny (Claude Code architect at Anthropic)** — *Latent Space podcast, 2025-05*:

> "Originally, we tried very, very early versions of Claude actually used RAG. So we, like, indexed the code base... **It outperformed everything. By a lot. By a lot.** And this was surprising."
>
> "There's this whole indexing step that you have to do for RAG. And there's a lot of complexity that comes with that because **the code drifts out of sync**."
>
> "There's **security issues** because this index has to live somewhere. And then, what if that provider gets hacked? And so it's just a lot of liability."
>
> "Agentic search just sidesteps all of that. So essentially, **at the cost of latency and tokens, you now have really awesome search without security downsides**."
>
> — https://www.latent.space/p/claude-code

**2. arXiv 2605.15184 ("Is Grep All You Need? How Agent Harnesses Reshape Agentic Search", PwC US, 2026-05-14)**:

- 116-Q LongMemEval × Claude Code / Codex / Gemini CLI / Chronos 4-harness 교차 평가
- 결론: **"grep generally yields higher accuracy than vector retrieval"** + "agents fail or win through their harness"
- 학술 peer-style empirical study 로서 단일-시스템 bias 없음
- https://arxiv.org/abs/2605.15184

**3. Anthropic 공식 blog** — *"How Claude Code Works in Large Codebases"*:

> "navigates a codebase the way a software engineer would: **it traverses the file system, reads files, uses grep to find exactly what it needs**"

Staleness 의 구체적 예시: "RAG returns a function the team renamed two weeks ago". Claude Code FAQ 도 "no RAG, no embeddings, no vector DB" 공식 확인.
- https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start

#### Frontier embedding 사용 히트맵 (S0d 결정의 codebase-level 근거)

| 시스템 | 도메인 | 임베딩 | 추세 |
|---|---|---|---|
| Hermes-Agent | Long-term memory | ✅ YES (적극, Hindsight Cloud/Local + Holographic HRR + 자체 SQLite native + opt. Chroma — sqlite-vec 는 미사용) | 활발 |
| OpenClaw | Agent memory + retrieval | ✅ YES (sqlite-vec + FTS5 + MMR + temporal decay) | 활발 |
| Claude Code | Code/agent | ❌ NO (의도적 회피, Glob+Grep+Read+Agent) | LLM-native zero-index |
| Cursor (2023) | IDE | ✅ YES (indexing-first) | 1세대 |
| Cursor (2026) | IDE | ⚪ Hybrid (자체 학습 embedding + Turbopuffer, agent-first 재설계 — embedding 은 background) | agentic-first 로 이동 |
| OpenAI Codex CLI | Code/agent | ❌ NO | LLM-native (사용자 요구로 검토 중 #609/#5181) |
| Devin | Code/agent | ❌ NO | agentic-only |

→ Code/agent 도메인 frontier 3/3 (Claude Code / Codex CLI / Devin) 이 embedding 회피. memory 도메인 (Hermes / OpenClaw) 은 적극 사용 — 두 도메인이 정반대 결정. **GEODE 의 self-improving loop 정책 진화는 code/agent 도메인** — Claude Code 라인.

#### Cursor 의 embedding 약화 4-축 원인 (왜 frontier 합의가 옅어지는가)

1. **Long context 확장** (Claude 200K→1M) — 중소 repo 통째 주입 가능
2. **Prompt caching 경제성** — Claude Code 의 92% prefix reuse + 81% 비용 절감으로 agentic 반복 호출이 cache 로 거의 무료화
3. **Agentic search 의 경험적 우세** (Boris 의 가장 강한 근거) — precision / freshness / cite-ability / AST 보존
4. **Tool use 성숙도** — Bitter Lesson 패턴 (model 이 retrieval scaffold 흡수)

#### GEODE-specific 적용 검증 (5축 wiring 분석)

Boris 의 6 근거 중 4개 (1/2/5/6) 가 GEODE 의 `retrieval` slot 에 직접 적용:

| Boris 근거 | GEODE 의 retrieval slot 에서 |
|---|---|
| Performance ("outperformed by a lot") | Petri 17-dim 이 fitness 평가 — vector lookup 불필요 |
| Index staleness | 5축 정책 SoT 가 mutation 마다 변함 — stale 위험 동일 |
| Precision (exact match) | 다른 4 slot (`tool_policy` / `reflection` / `decomposition` / `prompt`) 이 in-context 정책 진화로 fuzzy match 회피 |
| Bitter Lesson | M4 surrogate ① few-shot pool + ③ mutator reference 가 in-context 자료 흐름을 이미 처리 |

→ **결론: 옵션 A 채택**. `TARGET_KINDS` 에서 `retrieval` 제거, 5축 → 4축 명시 축소. path constant + dict 매핑 보존 (별도 ADR 로 복원 가능). 정직성 회복 — "되는 것만 명세" 가 self-improving loop 의 ratchet 정신과 일치.

### S6. Bench fitness axis — 7-bench frontier federation (2026-05-23 신설)

> **신설 근거**: 코드 (`autoresearch/bench_means.py` + `autoresearch/train.py` 의 `FITNESS_BENCH_4AX=0.25`) 가 4번째 fitness 축 `bench_means` 를 이미 정의했고 §Decision.2 가 그 사실을 명세화 했지만 (이 amendment), bench 축의 *구성* — 어느 7 benchmark, 가중치, frontier 갱신 근거 — 가 ADR 측에 누락돼 있었다. 본 §S6 가 그 빈자리를 채운다.

#### S6.1 — Bench 의 역할

`dim_means` (Petri alignment, 음의 압력) + `ux_means` / `admire_means` (양의 압력) 옆에 추가되는 **capability** 양의 압력 축. Petri 가 alignment evaluation (안 망가지기), bench 는 real task completion (제대로 함) 의 ground-truth 평가.

#### S6.2 — 7-bench schema (2026-05 frontier 갱신, F1.b LCB substitution 후 확정)

| Field | weight | metric | inspect_ai port (2026-05-23) |
|-------|--------|--------|-----------------------------|
| `swe_bench_pro_pass` | 0.25 | resolve rate | `inspect-harbor==0.4.5` (third-party, Docker scaleapi 이미지) |
| `livecodebench_pro_accuracy` | 0.15 | accuracy (LightCPVerifier C++ exec) | `inspect-evals==0.13.0` |
| `tau2_bench_success` | 0.20 | pass^1 rate | `inspect-evals` |
| `gpqa_diamond` | 0.15 | accuracy | `inspect-evals` |
| `hle_accuracy` | 0.10 | accuracy | `inspect-evals` (multi-modal items: vision 모델 필요 가능) |
| `osworld_success` | 0.10 | success rate | `inspect-evals` (VM/Docker sandbox) |
| `mle_bench_medal` | 0.05 | medal rate | `inspect-evals` (Kaggle dataset + Docker exec) |
| **합** | **1.00** | — | — |

#### S6.3 — Frontier 갱신 history (2026-05)

원본 S6 초안의 4 bench 는 모두 saturated / OpenAI retire / contamination 이슈로 outdated 됐다 — 2026 frontier (Claude Opus 4.5 system card + GPT-5 system card 공통 채택) 으로 7-field schema 갱신:

- **SWE-bench (Verified) → SWE-bench Pro** (Scale AI): OpenAI 2026-02-23 공식 retire, saturated + contaminated
- **HumanEval → LiveCodeBench-Pro** (F1.b 의 substitution): Top-4 93-95% saturated. *Vanilla LiveCodeBench* 가 contamination-defense 측면에서 후속이었으나 inspect_ai port 부재 — frontier consensus 는 `livecodebench_pro` (C++ 경쟁 프로그래밍, live-contest scrape, time-cutoff windowing, v2 2026 초에 ICPC WF/IOI/Chinese olympiad 추가) 가 그 niche 를 흡수
- **TAU-bench → τ²-bench** (Sierra 2025): telecom domain 0.993 saturated, dual-control 후속
- **GAIA → HLE + OSWorld 분할**: DeepAgent 91.69% saturated. HLE (Nature 2026-01) + OSWorld (computer-use) 로 도메인 분리
- (신규) **GPQA Diamond**: Anthropic + OpenAI 카드 공통 PhD reasoning
- (신규) **MLE-bench**: self-improving loop 도메인 정합 (ML engineering)

#### S6.4 — Cross-validation gate (Goodhart 양방향 방어)

- **alignment_only_fooling**: dim_means promote (Petri 개선) + bench_means regress (capability 저하) → fooling 의심, strict reject
- **capability_at_alignment_cost**: bench_means promote + dim critical regress → capability gain at alignment cost, strict reject

두 conflict 모두 `compute_fitness → 0.0` 발화 (`autoresearch/bench_means.py:detect_cross_validation_conflict` + `autoresearch/train.py:compute_fitness` 의 4-axis 분기에서 호출).

#### S6.5 — Frontier sources (2026-05)

- OpenAI SWE-bench retire 공지 — `https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/`
- Scale AI SWE-bench Pro — `https://labs.scale.com/leaderboard/swe_bench_pro_public`
- Sierra τ²-bench — `https://sierra.ai/resources/research/tau-squared-bench`
- Humanity's Last Exam (Nature 2026-01) — `https://agi.safe.ai/`
- LiveCodeBench-Pro 논문 — `https://arxiv.org/abs/2506.11928`
- GPQA Diamond (NYU 2024)
- OSWorld (2024 frontier computer-use agent benchmark)
- MLE-bench (OpenAI 2024 ML engineering)
- inspect_evals (UK AISI) — `https://github.com/UKGovernmentBEIS/inspect_evals`
- inspect_harbor (meridianlabs-ai) — `https://github.com/meridianlabs-ai/inspect_harbor`
- Claude Opus 4.5 system card — `https://www.anthropic.com/claude-opus-4-5-system-card`
- GPT-5 system card — `https://cdn.openai.com/gpt-5-system-card.pdf`

### S6b. Bench production wiring (2026-05-23 신설, PR-SIL-5THEME C2 의 명세)

§S6 는 **schema + math + cross-validation gate** + **2026 frontier 갱신** 명세. §S6b 는 그 명세의 **실제 production wiring** — collector / dispatcher / persistence / observability / 누락 보고 — 전부.

#### S6b.1 — `collect_bench_means_from_inspect_ai` 실구현

- 7-bench dispatcher: 각 bench 의 inspect_ai task 호출 (`inspect_evals` 또는 `inspect_harbor`)
- A1 graceful-skip 패턴: Docker / VM 미가용 시 해당 bench 만 skip, `missing_benches` 에 등록, neutral fallback (0.5) 으로 fitness 계산 진행
- per-bench provenance 동시 emit: `bench_stderr` (sample-level pass/fail 에서 자동 산출) / `bench_sample_count` / `bench_rubric_version="v1-7bench-2026-05"`

#### S6b.2 — `main()` 의 4-axis fitness 활성

- `run_audit` 직후 `collect_bench_means_from_inspect_ai` 호출
- `compute_fitness(... bench_means=current_bench, baseline_bench_means=baseline_bench)` 4-axis 분기 활성 (현재 분기는 정의돼 있으나 호출 0회, S6b 가 firing path 활성화)
- `_baseline_provenance` dict 에 `bench_means` + provenance 슬롯 추가 → `_write_baseline` 가 axes.bench_means + raw.bench_provenance 영속화
- `_should_promote` internal compute_fitness 에 bench 전달 → cross-validation gate 가 promote 결정에 영향

#### S6b.3 — Observability 페이로드 확장

- `format_results_jsonl_row`: `bench_means` / `ux_means` / `admire_means` + per-axis aggregate 컬럼 emit
- OL-C1 eval emit (`eval_response_recorded`): `axis_scores["bench_means_aggregate"]` 를 baseline → **current** 로 교체 (M4.1 DPO pile 의 stale signal 해소)
- `_emit_journal("baseline_decision")`: `baseline_axis_coverage` 에 bench count 외 per-bench breakdown 추가
- conflict 발화 시 reason payload (`alignment_only_fooling` / `capability_at_alignment_cost`) journal + results.jsonl 보존 → fitness=0.0 의 원인 구분 가능

#### S6b.4 — `prepare.py` 의 Docker pre-flight (A1 명세)

`autoresearch/prepare.py` 에 신규 헬퍼:
- `_check_docker_available()`: `docker --version` + image pull dry-run
- `_check_inspect_evals_installed()`: `inspect_evals` / `inspect_harbor` import 가용성
- 결과를 `missing_benches` 에 미리 등록 → collector 가 호출 안 함

#### S6b.5 — 의존성 추가

`pyproject.toml [audit]` extra 에:
- `inspect-evals==0.13.0` — 6 bench (LCB-Pro + τ²/GPQA/HLE/OSWorld/MLE)
- `inspect-harbor==0.4.5` — 1 bench (SWE-bench Pro)

### 4. 단기 → 중기 → 장기 성장 곡선

#### S0 — Audit + Dead Slot 처치 (이미 진행 시작)

PR-AUDIT-5SLOT 으로 진단 완료. dead slot 별 reader 신설:

| Sub-PR | 작업 | ROI |
|---|---|---|
| S0a | `tool_policy` reader 신설 — `core/agent/loop/AgenticLoop._select_tools()` 또는 동등 진입점에서 `tool-policy.json` 의 allowed/forbidden/priority 정책 읽어 도구 후보 필터 (~30 line) | **단기 1순위** — `broken_tool_use` dim 직접 영향 (17-dim 중 유일한 양의 압력 dim) |
| S0b | `reflection` reader 신설 (머지 완료, #1408) — `_REFLECTION_TOOL["description"]` + `_SYSTEM_PROMPT` 를 `reflection.json` 의 `description` / `system_prompt` field 로 override. `input_schema` 는 mutate 대상 아님 (typed payload contract 보존). | **단기 2순위** — `admire_means` + `ux_means` 동시 영향 |
| S0c | `decomposition` reader 신설 — `load_prompt("decomposer", "system")` 과 `decomposition.json` 의 sections 연결 (또는 `_load_decomposition_policy()` 신설) | 단기 3순위 — `task_success_rate` 영향 |
| S0d | `retrieval` 처치 — **deprecate 채택** (§Decision.3a). `TARGET_KINDS` 에서 제거, path constant + dict 매핑 보존. 머지 완료 (2026-05-21) | 완료 |

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
7. **S6** — `bench_means` fitness 축 명세 (schema + math + cross-validation gate) — *이 amendment (PR-SIL-5THEME C1) 으로 ADR 측 명세 완료*
8. **S6b** — `bench_means` production wiring (collector / dispatcher / persistence / observability / Docker graceful-skip) — *PR-SIL-5THEME C2*
9. (이후) S3-S5 / M1-M5 / 장기 시나리오

각 PR 은 단일 fitness 축 추가 / 단일 target_kind 추가 / 단일 surrogate 채널 가동을 원자 단위로 보장. 단계 사이마다 baseline.json 이 다축 monotonic 유지 검증.
