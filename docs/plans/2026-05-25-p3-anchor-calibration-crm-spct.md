# 2026-05-25 — P3-revised: anchor calibration + CRM + SPCT self-principle (sprint plan)

> Status: **Draft** (P2-revised merge 후 후속)
> Framing: judge anchor 의 active feedback loop + process-outcome causal + self-principle
> 관련: [[project-baseline-rl-grounding-decisions]] D2 (anchor 3 routing)

## 1. Background

PR-5 #1641 후 anchor 3 (admirable / disappointing / needs_attention) 가 fitness 계산에서 자동 제외됨 (DIM_WEIGHTS dict 미포함, weight=0). 단 **anchor 의 자체 signal 은 mutator 의 self-improvement 에 unused**:

- anchor 가 judge 의 calibration 신호인데 baseline 식에 들어가지 않음
- 사용자 결정 D2: anchor 3 → "self-improving loop baseline 의 input" (P3 routing)

frontier 의 진화 (2026-Q1 SPCT DeepSeek-GRM): self-generated judging principle → critique → reward chain. Meta-Rewarding (Meta 2024-07 arXiv 2407.19594) 의 meta-judge 패턴으로 judge saturation 회피.

CRM (Conditional Reward Modeling arXiv 2509.26578): process step reward 와 outcome reward 의 causal 연결.

## 2. Frame — anchor 의 active feedback + judge calibration

| 항목 | 현재 | P3-revised |
|---|---|---|
| anchor 3 의 fitness 영향 | weight=0 (제외) | confidence multiplier (PSM 거부 후) → SPCT principle-based |
| judge calibration | Petri judge LLM 의 inherent rubric | self-generated principle (SPCT) + meta-judge (Meta-Rewarding) |
| process-outcome 연결 | fitness scalar 만 | per-dim causal trace (CRM) |
| judge drift 방지 | (없음) | meta-judge 가 judge 평가 |

## 3. 채택할 frontier 패턴

| 패턴 | 출처 | GEODE 적용 |
|---|---|---|
| **Self-Principled Critique Tuning** | DeepSeek-GRM 2026-Q1 (Medium analysis) | mutator 가 mutation 직전 *명시 principle* 생성 → 그 principle 로 critique → critique 가 next-cycle context |
| **Meta-Rewarding** | Meta 2024-07 arXiv 2407.19594 | mutation_id 의 attribution 결과를 meta-judge LLM 이 retrospective evaluate → judge drift detect |
| **Conditional Reward Modeling** | arXiv 2509.26578 | per-dim observed_dim 과 mutation 의 target_section 의 causal hypothesis 명시 + attribution row 에 기록 |
| **anchor 의 confidence band** | AutoGLM ORM 의 outcome confidence | anchor 3 score → fitness 의 confidence range [0.7, 1.0] (PSM 거부 후 RL-derived) |

## 4. Wiring

| # | Wiring | 위치 | LOC |
|---|---|---|---|
| **C1** | mutator system prompt 에 "first generate principle" 단계 추가 | `runner.py:_MUTATION_CONTRACT_SUFFIX` | ~20 |
| **C2** | Mutation.principle field 추가 (frozen dataclass, default "") | `runner.py:Mutation` | ~10 |
| **C3** | parse_mutation 의 principle 추출 + LLM 응답 schema 의 `principle` key | `runner.py:parse_mutation` | ~20 |
| **C4** | apply row 의 ApplyRecord 에 principle field | `runner.py:ApplyRecord` | ~10 |
| **C5** | meta-judge invocation (cron job 또는 manual) — mutations.jsonl 의 최근 N 의 attribution 결과를 meta-judge LLM 에 보내 retrospective evaluate | `core/self_improving_loop/meta_judge.py` 신규 | ~150 |
| **C6** | CRM causal hypothesis — Mutation.causal_hypothesis field (mutation 직전 mutator 가 명시 "이 mutation 이 dim X 의 Y 효과 → fitness Z 변화 인과사슬") | `runner.py:Mutation` + parse_mutation | ~30 |
| **C7** | anchor confidence multiplier — fitness_final = base_fitness × (0.7 + 0.3 × anchor_score) | `autoresearch/train.py:compute_fitness` | ~30 |
| **C8** | 12 invariant tests | `tests/core/self_improving_loop/test_anchor_crm_spct.py` 신규 | ~250 |

총 **~520 LOC** + 12 tests. 약 ~4h sprint.

## 5. Acceptance criteria

- [ ] mutator prompt 가 principle 단계 명시 + parse_mutation 이 principle 추출
- [ ] ApplyRecord 의 principle field schema (Pydantic, optional, max_length=500)
- [ ] meta-judge LLM 호출 (recent N=10 mutations 의 attribution 비교) 의 driftScore 출력
- [ ] CRM causal_hypothesis 의 schema + post-audit observed_dim 과 cross-check
- [ ] anchor confidence multiplier 의 fitness 식 변경 (legacy mode + new mode dual)
- [ ] backward compat — Mutation.principle="" 일 때 legacy 동작 그대로
- [ ] anchor 3 (admirable / disappointing / needs_attention) 의 dim_means 값이 multiplier 에 정확히 들어감
- [ ] meta-judge cron job 의 schedule + idempotent re-run
- [ ] Codex MCP verification 통과

## 6. Out of Scope

- anchor 3 의 자체 mutation target 화 (사용자 결정 D1 — 측정만 유지)
- SPCT 의 RFT/RL training 단계 (mutator weight frozen, training-time 적용 X)
- Self-Rewarding LLM 의 DPO iteration (training-time)

## 7. Risk

| Risk | Mitigation |
|---|---|
| principle 의 LLM 생성이 over-verbose | max_length=500 + parse_mutation strict |
| meta-judge cost — N=10 LLM call/cron | weekly cron + cost ledger |
| anchor multiplier 의 mutation gaming | multiplier range [0.7, 1.0] 으로 cap |
| causal_hypothesis 의 hallucination | post-audit cross-check + CRM consistency test |

## 8. Reference

- [SPCT DeepSeek-GRM analysis](https://medium.com/@noailabs/self-principled-critique-tuning-spct-deepseek-grm-0669f822d0cb)
- [Meta-Rewarding LM arXiv 2407.19594](https://arxiv.org/abs/2407.19594)
- [Self-Rewarding LM arXiv 2401.10020](https://arxiv.org/abs/2401.10020)
- [CRM arXiv 2509.26578](https://arxiv.org/abs/2509.26578)
- [Constitutional AI arXiv 2212.08073](https://arxiv.org/abs/2212.08073)
