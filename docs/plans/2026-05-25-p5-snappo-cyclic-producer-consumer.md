# 2026-05-25 — P5: SnapPO cyclic producer-consumer (sprint plan)

> Status: **Draft (BLOCKED on Solar Open 100B technical report)** — Upstage paper 의 SnapPO detail 출판 후 진행
> Framing: cached intermediate + producer-consumer 분리 (GEODE 의 mutations.jsonl audit infra 와 가장 정합)
> 관련: [[reference-rl-baseline-design-frontier-2026]] (SnapPO Upstage 2026-03-24)

## 1. Background

Upstage Solar Pro 3 (2026-03-24, arXiv 2601.07022) 의 **SnapPO** 는 cyclic off-policy + producer-consumer 분리 + cached intermediate + multi-stage compose. 한국 frontier 의 sovereign-AI 검증.

GEODE 의 mutations.jsonl audit infra (PR-3 #1637 + PR-5 #1641) 가 SnapPO 의 producer-consumer 패턴과 **정합** — runner.py (producer: mutation 생성) + train.py (consumer: audit + attribution). cached intermediate 가 mutations.jsonl 자체.

**BLOCKED**: SnapPO 의 정확한 식 (snapshot policy / cyclic update / importance sampling decoupling) 이 Upstage paper 의 implementation detail level 에서 미공개. Solar Open 100B technical report 출판 후 진행.

## 2. Frame — cyclic off-policy mutation + cached rollout

| 항목 | PR-5 P1-revised | P5 SnapPO |
|---|---|---|
| Mutator call timing | per-cycle live | snapshot policy (period N) + cached rollout |
| Audit subprocess | per-cycle real | cached batch + selective re-audit |
| Producer-consumer | runner→train (1:1) | decoupled queue (M producer, N consumer) |
| Multi-stage compose | single linear cycle | math / code / agentic 각 stage 독립 + compose |

## 3. 채택할 frontier 패턴 (paper detail 후 확정)

| 패턴 | 출처 | GEODE 적용 (추정) |
|---|---|---|
| **Snapshot policy** | SnapPO (Upstage 2026-03) | mutator policy state 의 N-cycle snapshot → snapshot 으로부터 cached mutation rollout |
| **Cyclic off-policy importance sampling** | SnapPO + CISPO (MiniMax-M1) | snapshot policy 와 current policy 의 ratio clipping → 단 mutator frozen 에서는 trivial |
| **Producer-consumer decoupling** | SnapPO + IMPALA / R2D2 (distributed RL infra) | mutator (runner.py) 와 audit (train.py) 의 async queue |
| **Multi-stage compose** | SnapPO | stage 별 mutation kind 분리 (e.g., prompt mutation stage / tool_policy stage / reflection stage) |

## 4. Wiring (추정 LOC, paper 후 확정)

| # | Wiring | 위치 | LOC |
|---|---|---|---|
| **E1** | `SnapshotPolicy` — mutator state 의 N-cycle snapshot | `core/self_improving_loop/snapshot.py` 신규 | ~80 |
| **E2** | Cyclic mutation cache — snapshot 으로부터 cached rollout (queue) | 신규 | ~120 |
| **E3** | Async producer (mutator) + consumer (audit) | `runner.py` modify + asyncio queue | ~150 |
| **E4** | Multi-stage compose — stage 별 mutation kind queue | 신규 | ~100 |
| **E5** | Importance sampling clipping (mutator frozen 이면 trivial = 1, 단 prompt mutation 에 의한 *implicit* policy shift 측정) | 신규 | ~60 |
| **E6** | 12 invariant tests | `tests/.../test_snappo_cyclic.py` 신규 | ~250 |

총 **~760 LOC** + 12 tests. 약 **~5h sprint** (가장 큰 sprint). **BLOCKED on paper detail**.

## 5. Acceptance criteria (가설, paper 후 정정)

- [ ] SnapshotPolicy 의 N-cycle snapshot + restore
- [ ] Cyclic mutation cache 의 producer / consumer 분리
- [ ] Async queue 의 graceful shutdown + drain
- [ ] Multi-stage compose — math / code / agentic 분리 (또는 GEODE 의 5 kind 매핑)
- [ ] Importance sampling clipping 의 implicit policy shift 측정 (prompt mutation 의 policy 효과)
- [ ] backward compat — snappo_mode=False (default) → legacy P1-revised
- [ ] 한국 frontier (Upstage Solar Pro 3) 의 production 검증 정합 명시
- [ ] Codex MCP verification 통과

## 6. Out of Scope

- Training-time weight update — mutator frozen 와 충돌 (Upstage 의 SnapPO 는 training-time)
- 4-stage 의 모든 mutation kind 활성화 — MVP 는 prompt + tool_policy 만
- AsyncIO 의 multi-host scale — single-host MVP

## 7. Risk + Block

| Risk / Block | Mitigation |
|---|---|
| **BLOCKED**: SnapPO paper detail 미공개 | Upstage technical report 출판 후 진행. Solar Open 100B 가 정식 paper. polling: weekly arXiv search |
| Async queue 의 race | asyncio.Queue + graceful shutdown 패턴 |
| GEODE mutator frozen 와 SnapPO 의 training-time 충돌 | inference-time 변형 (snapshot 은 state, weight 아님) |
| Audit cost 의 cached rollout 효과 | cache hit rate 측정 invariant test |

## 8. Action 전 사전 단계

1. **Polling**: Upstage Solar Open 100B technical report arXiv 출판 모니터 (weekly)
2. **Paper 분석**: 출판 시 SnapPO 의 정확한 식 + clipping + queue 패턴 추출
3. **Plan 정정**: 본 plan 의 §3/§4/§5 를 paper detail 반영 정정
4. **Sprint 시작**: 정정된 plan 으로 worktree 할당

## 9. Reference

- [Solar Pro 3 — Upstage Blog](https://www.upstage.ai/blog/en/solar-pro-3-0323)
- [Solar Open Technical Report arXiv 2601.07022](https://arxiv.org/pdf/2601.07022)
- [CISPO MiniMax-M1 arXiv 2506.13585](https://arxiv.org/abs/2506.13585)
- [DAPO arXiv 2503.14476](https://arxiv.org/html/2503.14476v1) (cyclic off-policy 변형 참고)
- [IMPALA arXiv 1802.01561](https://arxiv.org/abs/1802.01561) (distributed RL infra reference)
