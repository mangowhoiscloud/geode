# 2026-05-25 — P4: PARL swarm-level baseline scaffolding (sprint plan)

> Status: **Draft** (P3 merge 후 후속, 또는 P3 와 병렬)
> Framing: Kimi K2.6 영감의 inference-time swarm-level baseline
> 관련: [[reference-rl-baseline-design-frontier-2026]] (PARL 사례)

## 1. Background

PR-5 #1641 의 N=2 group sampling 은 *single-cycle* group baseline. Kimi K2.6 (Moonshot 2026-04-20) 의 **PARL (Parallel-Agent RL)** 는 300 sub-agent + 4000 coordinated step 의 *swarm-level* baseline — credit assignment 가 sub-agent 별 coordination 식.

GEODE 의 sub-agent 인프라 (이미 6849 test + agent_contracts policy) 가 있어 inference-time PARL 패턴 차용 가능. 단 Kimi 의 *training-time* policy update 는 GEODE 의 mutator frozen 와 충돌 → **inference-time only** 변형.

## 2. Frame — sub-agent 별 mutation rollout coordination

| 항목 | PR-5 N=2 group | P4 swarm |
|---|---|---|
| Unit | single-cycle, 1 mutator | multi-cycle, N sub-agent 가 각자 mutation |
| Coordination | 같은 baseline → N rollout | sub-agent 별 baseline 분리 + 종합 후 fitness aggregation |
| Credit assignment | group mean + advantage | swarm-mean + sub-agent contribution |
| 적용 | single mutation per cycle | sub-agent 별 mutation chain |

## 3. 채택할 frontier 패턴

| 패턴 | 출처 | GEODE 적용 |
|---|---|---|
| **PARL swarm-mean baseline** | Kimi K2.6 (Moonshot 2026-04) | N sub-agent (예: 3) 가 각자 mutation chain → swarm-level fitness mean 을 baseline 으로 |
| **Sub-agent contribution decomposition** | PARL (paper 미공개) | sub-agent 별 attribution row 의 group_id 위에 swarm_id 추가 (multi-level grouping) |
| **Coordinated step (4000) credit assignment** | Kimi K2.6 | inference-time 에서는 ~10 step (cycle) 로 simplified |
| **Sub-agent diversity** | PARL (post-trained decomposition policy) | inference-time 에서는 prompt-time pattern (각 sub-agent 에 다른 system prompt slice) |

## 4. Wiring

| # | Wiring | 위치 | LOC |
|---|---|---|---|
| **D1** | `SwarmConfig` 신규 — sub_agent_count (default 1=disabled, MVP 3) + swarm_aggregation (mean/max) | `core/config/self_improving_loop.py` | ~20 |
| **D2** | `propose_swarm(M sub-agents)` 신규 — M independent mutation chains | `runner.py` 신규 method | ~80 |
| **D3** | `apply_swarm_proposals(swarm_proposals)` — swarm-level audit + mean baseline + sub-agent contribution | 신규 method | ~120 |
| **D4** | mutations.jsonl `kind` 확장: `applied_swarm` (다른 차원 의 mutation 묶음) | runner.py Mutation row | ~20 |
| **D5** | `swarm_id` field (group_id 위의 level 2) — apply row + attribution row | ApplyRecord + AttributionRecord | ~20 |
| **D6** | sub-agent 별 system prompt slice — agent_contracts policy 활용 | `apply_agent_contracts_policy` 의 swarm 분기 | ~50 |
| **D7** | 10 invariant tests | `tests/core/self_improving_loop/test_swarm_scaffolding.py` 신규 | ~200 |

총 **~510 LOC** + 10 tests. 약 ~3h sprint.

## 5. Acceptance criteria

- [ ] SwarmConfig 의 sub_agent_count = 1 (disabled, legacy) / 3 (MVP) / 5 (full)
- [ ] propose_swarm(M) 가 M independent mutation chains 생성 (각자 다른 agent_contract)
- [ ] apply_swarm_proposals 의 swarm-level fitness aggregation (mean / max config)
- [ ] mutations.jsonl 의 applied_swarm row + swarm_id propagation
- [ ] sub-agent contribution decomposition (각 sub-agent 의 fitness Δ)
- [ ] backward compat — sub_agent_count=1 → legacy group sampling (PR-5)
- [ ] agent_contracts policy 의 sub-agent 별 system prompt 가 정확히 reach
- [ ] swarm_id 와 group_id 의 multi-level grouping invariant test
- [ ] Codex MCP verification 통과

## 6. Out of Scope

- PARL 의 training-time policy update (Kimi K2.6 의 핵심) — mutator frozen 와 충돌
- Sub-agent 간 communication / message passing — inference-time 단순 parallel
- 4000-step long-horizon coordination — GEODE 는 ~10 cycle MVP

## 7. Risk

| Risk | Mitigation |
|---|---|
| Audit cost M×N×current cost (P1-revised 의 N 위에 swarm M) | sub_agent_count cap = 5 (config Field(le=5)) |
| swarm aggregation 의 outlier dominance | swarm_aggregation knob (mean → median fallback) |
| sub-agent diversity 부재 시 swarm 무의미 | agent_contracts policy 의 sub-agent 별 contract 명시 |
| group_id + swarm_id 의 join 복잡도 | mutations.jsonl reader API 의 multi-level filter 명시 |

## 8. Reference

- [Kimi K2.6 — MarkTechPost](https://www.marktechpost.com/2026/04/20/moonshot-ai-releases-kimi-k2-6-with-long-horizon-coding-agent-swarm-scaling-to-300-sub-agents-and-4000-coordinated-steps/)
- [Kimi K2.6 Agent Swarm Explained — Verdent](https://www.verdent.ai/guides/kimi-k2-6-agent-swarm)
- [Credit Assignment for Long-Horizon LLM Agents arXiv 2603.08754](https://arxiv.org/html/2603.08754v1)
- [PARL Survey arXiv 2604.09459](https://arxiv.org/html/2604.09459v1)
