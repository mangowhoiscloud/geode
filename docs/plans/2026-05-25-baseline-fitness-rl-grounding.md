# 2026-05-25 — Baseline Fitness RL Grounding (P1-revised sprint plan)

> Status: **Draft** (사용자 결정 사항 확정, 구현 sprint 대기)
> Framing: self-improving loop 의 baseline (B) 생성 식 fix — 2026 frontier RL paradigm 기반
> 관련 메모리: [[reference-rl-baseline-design-frontier-2026]], [[project-baseline-rl-grounding-decisions]], [[project-autoresearch-separation-architecture]], [[reference-mutation-surface-frontier-2026-05-25]]
> 선행 sprint: PR-3 attribution wiring gap fill (#1637 merged)

## 1. Background

PR-3 #1637 merge 후 self-improving loop 의 closed loop (mutation → expected_dim → audit → observed_dim → attribution_score) 가 wiring 완료. 다음 단계는 **B (baseline fitness) 생성 식 자체의 fix** — 사용자 결정으로 RL 패러다임 채택 + frontier 그라운딩.

## 2. Frame — RL paradigm 기반 baseline upgrade

GEODE 의 self-improving loop = RL 의 *policy gradient on non-Markovian environment* 와 동형:

| GEODE | RL 추상화 |
|---|---|
| mutator LLM | policy π(a\|s) |
| mutation | action a |
| audit pipeline | environment step |
| 24-dim measurement | observation + multi-dim reward |
| 현재 fitness = Σ w_i·r_i | scalarized reward (linear scalarization) |
| previous baseline | b(s) baseline |
| anchor 3 (admirable/disappointing/needs_attention) | preference triplet ≈ DPO style |

→ **PSM (관측 데이터 보정) 거부** — 환경이 닫혀있고 mutator 와 무관한 sampling bias 의 도구. GEODE 는 mutator 가 정책 자체 → on-policy RL baseline 적합.

## 3. 사용자 결정 사항 (D1-D5)

| # | 결정 |
|---|---|
| **D1** | 24 dim 측정/기록 유지 (baseline.json + mutations.jsonl 의 observed_dim) + mutator 의 expected_dim 주입 후보만 가지치기 |
| **D2** | scenario_realism → seed-gen feedback channel (mutator 분리). admirable / disappointing / needs_attention → self-improving loop baseline (B) 의 input |
| **D3** | B (fitness) 식 fix 먼저, 가지치기 그 다음 |
| **D4** | PSM (geode-scoring PSM Engine analyst_confidence multiplier) 거부 |
| **D5** | P1-revised (DAPO-inspired variance gate + GRPO-inspired score whitening) 채택 — *selection layer only, no policy gradient*. P2-P5 후속 |

## 4. P1-revised 적용 plan

### 4.1 frontier 의 selection layer 만 채택 (weight 학습 X)

GEODE 의 mutator = Anthropic/OpenAI API endpoint, weight frozen. → frontier RL 의 learning layer (gradient descent, ratio clipping, KL penalty) 적용 X. **selection layer 3개만**:

| 채택 (selection-only) | 출처 (inspired by) | GEODE 적용 |
|---|---|---|
| **Group baseline** | GRPO-inspired (DeepSeekMath arXiv 2402.03300; GRPO uses it as policy-update baseline, we use it as selection baseline) | N mutation → μ = mean(fitness) |
| **Score whitening (z-score)** | GRPO-inspired (same source; formula reused as selection-time ranking, not as policy gradient term) | score_i = (fitness_i - μ) / (σ + ε) |
| **Variance gate** | DAPO-inspired (arXiv 2503.14476 *Dynamic Sampling* — applied at training time there, here at selection time) | σ < ε_var 면 group 폐기 |

### 4.2 DAPO 4 technique 중 본 sprint 채택

| Technique | 채택 | 이유 |
|---|---|---|
| Clip-Higher (asymmetric ε_low/ε_high) | ❌ skip | weight 학습 없음. 사상 (asymmetric fitness Δ threshold) 은 후속 |
| **Dynamic Sampling** | ✅ 핵심 | variance filter 의 정확한 frontier 출처 |
| Token-level Loss | ❌ skip | weight 학습 없음. 사상 (mutation per-section attribution) 은 PRM 후속 |
| Overlong Shaping | ❌ skip (적용 X) | GEODE 는 mutation new_value 600 char hard cap 사용 (`runner.py:720`) |

### 4.3 MVP scope

| 항목 | 결정 | 비고 |
|---|---|---|
| group size N | **2** | config knob `[self_improving_loop.autoresearch] group_size`. 1=disabled, 2=MVP, 4=full |
| variance threshold ε_var | **0.01** | config knob. Placeholder default — no externally-verified production value grounded for this knob. history 누적 (N≥30 cycle) 후 percentile-based 로 adapt (PR-VAR-ADAPTIVE follow-up) |
| sibling SoT 처리 | **in-memory** | disk write 없음. audit subprocess spawn 시 env (W3 인프라) 로 SoT path propagate. 채택된 1개만 disk commit |
| mutations.jsonl `kind` 확장 | `applied` (선택됨) + `applied_sibling` (선택 안 됨) + 기존 `attribution` | group_id field 추가 |
| 폐기 시 동작 | cycle skip + log | 안전 default. 후속에 mutator 재시도 with higher temperature 옵션 |
| mutator parallel | asyncio.gather (N mutator LLM call parallel) | mutator cost 가산은 N 배. audit subprocess 는 sequential (OL-P2 audit_lane=1 정합) |
| **mutator temperature** | **1.0 (fix)** | `Settings.temperature_self_improving_mutation` (`core/config/_settings.py:260`) default 그대로 유지. range [0.0, 2.0]. **0.1 미만 override 금지** — group sampling 의 stochasticity 보장 필수 (temperature=0 시 N rollout 모두 같음 → group std=0 → variance filter 영구 trigger). 2026-05-25 운영자 결정 |

## 5. 코드 변경 위치

| 파일 | 변경 | LOC 추정 |
|---|---|---|
| `core/self_improving_loop/runner.py` | `propose_group(N)` 신규, `apply_group_proposals(group)` 신규, `_compute_group_advantage()` 신규. `Mutation.to_audit_row()` 의 `kind` 가 `Literal["applied", "applied_sibling"]` 확장. `group_id`, `group_advantage` field 추가 | ~140 |
| `core/self_improving_loop/policies.py` | in-memory SoT variant + commit-on-accept split. `apply_sibling_in_memory()` 신규 | ~80 |
| `autoresearch/train.py` | env 받는 부분 그대로 (W3 인프라 활용). N audit sequential lane (`acquire_audit_lane` 안에서) | ~30 |
| `core/self_improving_loop/attribution.py` | `AttributionRecord` 의 `group_id`, `group_advantage` field 추가 | ~20 |
| `core/config/self_improving_loop.py` | `group_size: int = 1` + `group_variance_threshold: float = 0.01` 신규 config knob | ~20 |
| `runner.py:_MUTATION_CONTRACT_SUFFIX` | "this batch will generate N=<config> diverse mutations; ensure each is meaningfully different" | ~10 |
| tests | 10 invariant tests (group sampling / variance filter / advantage normalization / sibling kind / group_id join / etc.) | ~250 |

**총 ~570 LOC** (~320 source + ~250 tests).

## 6. Cost / latency / risk

| 차원 | 영향 |
|---|---|
| Audit cost | N=2 → 2x (~$1.10/cycle), N=4 → 4x. mutator cost 도 N 배 |
| Cycle latency | sequential N audit → N × ~20분 = N=2 시 40분 |
| Disk noise | mutations.jsonl 에 N-1 sibling row 추가 → group_id filter 로 mitigate |
| Race | in-memory SoT variant 의 audit subprocess spawn 간 race | env propagation 으로 격리 (W3 인프라) |
| Variance threshold | ε=0.01 가 너무 작으면 모든 group pass, 너무 크면 모든 group fail | config knob + history 누적 후 tune |
| First cycle | mutations.jsonl 가 비어있어도 group 내 비교만 → prior baseline 불필요 (현재 동작 유지) |
| **Temperature override (deterministic)** | `Settings.temperature_self_improving_mutation` 가 0.1 미만이면 N rollout 모두 같음 → group std=0 → variance filter 영구 trigger → loop 영구 cycle skip | **`_compute_group_advantage` 진입 시 `temperature >= 0.1` assert + RuntimeError raise**. 운영자 결정 fix temperature=1.0 (default) |

## 7. Codex MCP 검증 prompt

[[feedback-codex-mcp-verification]] 따라 PR push 직전:

```
GEODE self-improving-loop 의 baseline RL grounding PR (P1-revised) diff 를 검증해줘.
group baseline + score whitening + variance gate (DAPO-inspired Dynamic Sampling, GRPO-inspired
whitening) 가 frontier 의 selection layer 만 채택했는지 + weight 학습 layer (PPO ratio clip, KL penalty,
gradient descent) 가 포함되지 않았는지 cross-check.

특히 다음 anti-deception 패턴 확인:
- sibling SoT 의 in-memory 격리가 정말 disk write 없는가 (W3 env propagation 정합)
- variance filter trigger 시 audit cost 가 정말 절약되는가 (subprocess spawn 안 되는가)
- group_id 가 mutations.jsonl row 와 attribution row 모두 propagate 되는가
- N mutator parallel call 의 cost 가 N 배인가 (cost ledger 검증)
- frontier 의 Clip-Higher / Token-level / Overlong shaping 같은 isolated 변경이 포함됐는가 (scope leak)
- audit subprocess 의 sequential lane (OL-P2) 가 깨졌는가
```

## 8. Acceptance criteria

### Implementation
- [ ] `propose_group(N)` 가 N Mutations 반환 (asyncio.gather parallel)
- [ ] `apply_group_proposals(group)` 가 N audit sequential 실행 + group_mean/group_std 계산
- [ ] variance filter: `if group_std < threshold: skip cycle + log`
- [ ] advantage normalization: `Â_i = (fitness_i - μ) / (σ + ε)`
- [ ] sibling SoT in-memory only, top-1 만 disk commit
- [ ] mutations.jsonl `kind` 확장 (applied + applied_sibling + attribution)
- [ ] group_id field 가 apply row + attribution row 모두 propagate

### Invariant tests (10)
- [ ] `test_propose_group_returns_n_mutations`
- [ ] `test_propose_group_mutator_parallel_calls`
- [ ] `test_apply_group_proposals_audit_sequential`
- [ ] `test_variance_filter_skips_low_std_group`
- [ ] `test_advantage_normalization_correct`
- [ ] `test_sibling_sot_in_memory_only`
- [ ] `test_top1_disk_commit_on_accept`
- [ ] `test_mutations_jsonl_kind_applied_sibling_row`
- [ ] `test_group_id_propagates_to_attribution`
- [ ] `test_legacy_n1_mode_backward_compat`
- [ ] `test_mutator_temperature_nonzero_guard` — `Settings.temperature_self_improving_mutation >= 0.1` 검증, 0 일 때 RuntimeError raise
- [ ] `test_propose_group_returns_distinct_mutations` — N parallel call 의 response 가 distinct (group std > 0 보장)

### Quality gates
- [ ] ruff + format + mypy + pytest 모두 통과
- [ ] lint-imports 4 contracts kept
- [ ] CLI smoke

### Codex MCP verification
- [ ] §7 prompt cross-LLM 검증 통과

## 9. Sprint 추정

| 단계 | 시간 | LOC |
|---|---|---|
| Plan 검토 + 승인 (현재) | — | — |
| Worktree 할당 | 1 min | — |
| `propose_group` + `apply_group_proposals` 구현 | 40 min | ~140 |
| `policies.py` in-memory variant | 30 min | ~80 |
| `attribution.py` + `train.py` field 추가 | 20 min | ~50 |
| config knob 추가 | 10 min | ~20 |
| mutator prompt 변경 | 5 min | ~10 |
| 10 invariant tests | 60 min | ~250 |
| Local quality gates | 5 min | — |
| Codex MCP 검증 | 15 min | — |
| PR 생성 + CI watch + merge | 15 min | — |
| **Total** | **~3.5h** | **~570** |

## 10. 후속 sprint 후보

본 sprint merge 후 우선순위:
1. **P2-revised** — Pareto archive + Dynamic Reward Weighting (multi-dim 신호 손실 해소, MORL)
2. **P3-revised** — anchor calibration + CRM (process-outcome causal) + SPCT self-principle
3. **P4 신규** — swarm-level baseline scaffolding (Kimi K2.6 영감, inference-time)
4. **P5 신규** — SnapPO cyclic producer-consumer (Upstage 영감, Solar Open 100B technical report 출판 후)

또한 **별 디깅 sprint**: "agent 에서 Mutation 을 노출시켜 현재처럼 RL 을 하는 사례" frontier 조사 — GEODE 처럼 inference-time mutation 을 외부에 노출하는 agent 의 RL 사례 (Voyager skill library, DGM lineage archive, AlphaEvolve evolutionary DB 의 inference-time 변형 등). 본 sprint 의 RL paradigm 정합성 추가 검증 + Mutation-noise 가 P1-revised 의 group sampling 과 어떻게 정합하는지.

## 11. Reference

- 2026-05-21 plan: `docs/plans/2026-05-21-cognitive-loop-uplift.md` (PR-1~PR-6 cognitive uplift)
- 2026-05-25 RFC: `docs/plans/2026-05-25-lineage-attribution-schema.md` (PR #1626 amended, single-ledger 유지)
- 2026-05-25 follow-up plan: `docs/plans/2026-05-25-attribution-wiring-gap-fill.md` (PR #1637 merged)
- Memory:
  - [[reference-rl-baseline-design-frontier-2026]] — 2026 RL frontier catalog
  - [[project-baseline-rl-grounding-decisions]] — 본 sprint 결정 사항 D1-D5
  - [[project-autoresearch-separation-architecture]] — 5 kind mutation surface
  - [[project-autoresearch-state-injection-pipeline]] — W3 env propagation 인프라
  - [[project-autoresearch-fragmentation-audit]] — F1-F5 신호
  - [[reference-mutation-surface-frontier-2026-05-25]] — mutation surface 16 사례
  - [[feedback-post-implementation-verification]] — RFC 작성 전 코드 검증 필수
  - [[feedback-codex-mcp-verification]] — §7 Codex MCP 검증
  - [[feedback-dual-sot-drift-invariant]] — sibling in-memory variant 의 drift 방지
- Frontier inspiration (referenced for ideas, not formula citations
  — verify against PDFs before quoting any specific formula):
  - [DAPO arXiv 2503.14476](https://arxiv.org/html/2503.14476v1) — Dynamic Sampling concept (applied here at *selection* time, not as a training-time gradient filter)
  - [GRPO DeepSeekMath arXiv 2402.03300](https://arxiv.org/abs/2402.03300) — group baseline + advantage whitening (formula reused as *selection* score, not as policy gradient term)
  - [GSPO Qwen3 arXiv 2507.18071](https://arxiv.org/pdf/2507.18071) — sequence-level RL training (referenced for sequence-vs-token granularity discussion only; GEODE is not RL training)
  - [Solar Pro 3 SnapPO arXiv 2601.07022](https://arxiv.org/pdf/2601.07022) — cyclic producer-consumer (P5 후속)
  - [Dynamic Reward Weighting TACL '26 arXiv 2509.11452](https://arxiv.org/abs/2509.11452) — MORL P2-revised
- Removed reference (2026-05-26 Phase A audit): EXAONE 4.5 arXiv
  2604.08644 was previously cited as "zero-variance filter
  production" grounding. WebFetch verification confirmed that paper
  is the EXAONE 4.5 vision-language-model technical report (LG AI
  Research) and contains no variance filter / Dynamic Sampling /
  RL-training content. Citation removed to prevent fake-frontier
  alignment from accumulating.
