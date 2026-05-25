# 2026-05-25 — P2-revised: Pareto archive + Dynamic Reward Weighting (sprint plan)

> Status: **Draft** (PR-5 #1641 merge 후 후속, P1-revised 의 다음 단계)
> Framing: linear scalarization MORL → Pareto-archive + adaptive scalarization
> 관련 메모리: [[project-baseline-rl-grounding-decisions]], [[reference-rl-baseline-design-frontier-2026]], [[project-autoresearch-separation-architecture]]
> 선행 sprint: PR-5 #1641 (P1-revised group sampling, merged f993e0bb)

## 1. Background

PR-5 #1641 merge 후 self-improving loop 가 N=2 group sampling + variance filter + GRPO whitening 으로 single-trajectory variance 해소. 단 **multi-dim 신호의 scalarization 손실** 잔존:

- 현재 fitness = weighted sum of 17 dims (`autoresearch/train.py:DIM_WEIGHTS`), 즉 *linear scalarization*
- 알려진 한계: concave Pareto front 의 일부 구간 영원히 도달 불가 (Das & Dennis 1997)
- 다른 한계: 한 dim 의 큰 양수가 다른 dim 의 큰 음수 cancel out (substitution)

frontier 의 진화 (TACL '26 arXiv 2509.11452 Dynamic Reward Weighting): fixed-weight scalarization 의 *증명적* 실패 → **hypervolume-guided adaptive weighting**. AlphaEvolve (DeepMind 2025-05) 의 MAP-Elites + island + Pareto rank 도 같은 사상.

## 2. Frame — multi-dim 신호 보존 + non-linear scalarization

| 항목 | 현재 | P2-revised |
|---|---|---|
| Reward 차원 | scalar (weighted sum) | 17-dim vector r ∈ ℝ¹⁷ |
| Baseline reference | previous gen fitness scalar | Pareto frontier (non-dominated set) |
| Scalarization | linear w·r (fixed weights) | adaptive (hypervolume gradient) |
| Concave Pareto 도달 | ❌ (Das-Dennis 한계) | ✅ (Chebyshev/Tchebycheff norm) |
| Archive | mutations.jsonl single-ledger | mutations.jsonl + Pareto-non-dominated set in baseline_archive.jsonl |

## 3. 채택할 frontier 패턴

| 패턴 | 출처 | GEODE 적용 |
|---|---|---|
| **Pareto-non-dominated filter** | AlphaEvolve MAP-Elites, DGM archive | `baseline_archive.jsonl` 에 promoted mutation 의 17-dim vector 보존, dominate 시 archive 에서 제거 |
| **Dynamic Reward Weighting** | TACL '26 arXiv 2509.11452 | weight `w` 가 hypervolume gradient `∇_w HV(F; r_nadir)` 로 update. fixed `w` 의 fail-mode 해소 |
| **Hypervolume indicator** | NeurIPS / TACL 표준 | `HV(F; r_nadir) = Lebesgue(dominated region)` — diversity + total quality 동시 capture |
| **Tchebycheff scalarization** (선택) | Das-Dennis 1997 | `max_i w_i × |r_i - z*_i|` — 모든 Pareto-optimal 점 도달 가능 |

## 4. Out of Scope

- Linear weighted sum 완전 폐기 — 본 PR 는 **dual mode** (legacy linear + new Pareto archive 병존). config knob `pareto_mode: bool` 로 선택
- Tchebycheff scalarization 전체 구현 — P2 의 first iteration 은 linear weight + hypervolume monitor 만, Tchebycheff 는 후속
- Anchor 3 의 calibration 강화 — P3-revised 의 영역

## 5. Wiring

| # | Wiring | 위치 | LOC |
|---|---|---|---|
| **B1** | `PareteArchive` 신규 클래스 — N-dim non-dominated set 유지 (insert/dominate/sample) | `core/self_improving_loop/pareto_archive.py` 신규 | ~150 |
| **B2** | `_compute_hypervolume(archive, r_nadir)` — Lebesgue dominated region | 동상 | ~80 |
| **B3** | `_dynamic_reward_weight(archive, current_w, lr)` — hypervolume gradient ascent | 동상 | ~60 |
| **B4** | `baseline_archive.jsonl` writer + reader | 동상 + `core/paths.py` const | ~50 |
| **B5** | `apply_group_proposals` 의 top-1 selection 분기 — pareto_mode=True 면 hypervolume 기반 | `runner.py` modify | ~50 |
| **B6** | `compute_fitness` 의 weighted sum 식이 dynamic w 받도록 — `autoresearch/train.py` modify | `train.py` | ~30 |
| **B7** | Config knobs — `pareto_mode: bool` (default False), `hypervolume_reference_point: dict[str,float]` | `core/config/self_improving_loop.py` | ~20 |
| **B8** | 10 invariant tests | `tests/core/self_improving_loop/test_pareto_archive.py` 신규 | ~250 |

총 **~690 LOC** + 10 tests. 약 ~4h sprint.

## 6. Acceptance criteria

- [ ] PareteArchive 의 insert / dominate / non_dominated_set / sample
- [ ] Hypervolume 계산 정확 (2-dim known testcase + N-dim Monte Carlo 근사)
- [ ] Dynamic Reward Weighting 의 gradient ascent step (small lr=0.01, 100 iter convergence)
- [ ] baseline_archive.jsonl writer 가 git-tracked + AppendOnly invariant
- [ ] pareto_mode=True 시 top-1 selection 이 archive sample 기반
- [ ] pareto_mode=False (default) 시 legacy linear scalarization 그대로 (backward compat)
- [ ] 17-dim vector reward 가 attribution row 의 observed_dim 과 1:1 mapping
- [ ] config knob hypervolume_reference_point 의 default = dim 별 0 (worst)
- [ ] linear vs pareto mode 의 invariant cross-check test
- [ ] Codex MCP verification 통과

## 7. Risk

| Risk | Mitigation |
|---|---|
| hypervolume 계산 cost O(N!) for N>3 → Monte Carlo 근사 | dim 17 → MC sample 1000 with reproducible seed |
| baseline_archive.jsonl growth | append-only + 월별 prefix (PR-3 RFC 와 정합) |
| Linear → Pareto mode switch 시 비교 baseline 불일치 | switch 시 archive 초기화 + 다음 audit 부터 |
| Codex review WARN 잔존 | sprint 의 acceptance criteria 에 명시 |

## 8. 후속 (P2 의 P2.1+)

- Tchebycheff scalarization 추가 (concave Pareto 도달)
- MAP-Elites grid (dim 별 niche)
- island model (subpopulation 격리)
- 후속 GEPA 의 Pareto frontier sampler 통합

## 9. Reference

- [Dynamic Reward Weighting TACL '26 arXiv 2509.11452](https://arxiv.org/abs/2509.11452)
- [AlphaEvolve — DeepMind blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)
- [DGM lineage archive arXiv 2505.22954](https://arxiv.org/abs/2505.22954)
- [Traversing Pareto Optimal Policies MORL arXiv 2407.17466](https://arxiv.org/pdf/2407.17466)
- [C-MORL arXiv 2410.02236](https://arxiv.org/abs/2410.02236)
- [Pareto Set Learning arXiv 2501.06773](https://arxiv.org/pdf/2501.06773)
