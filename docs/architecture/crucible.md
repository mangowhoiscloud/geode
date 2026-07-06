# Crucible — 개선을 불로 시험하는 게이트 루프

> 상태: 설계 v2 정렬(2026-07-06), M1 기각·S5 판정 보류·iteration-cost 재설계 중. 선행: `docs/architecture/autoresearch.md`(v1 SOT),
> `docs/adr/ADR-012-self-improvement-surface-tiers.md`(§S6), `core/self_improving/program.md`.
> 명명: crucible(도가니) — 광석을 녹여 불로 시험하는 그릇, 관용적으로 '혹독한 시험'.
> 겉보기(황철석, fool's gold)가 아니라 불이 가치를 정한다. GEODE 에서 캐낸 개선 후보를
> **외부 동결 벤치마크와 게이트 사다리의 불에 통과시켜, 살아남는 승격만 남긴다**는 v2의
> 정체성. 담금질처럼 시험이 강도를 만든다. GEODE 광물 계보(광석 → 도가니) 정합.
> 어휘는 CONTENT-CANON §2: 변이·선택·승격·되돌림. 가중치 갱신 없음.

## 1. self-improving loop v1의 한계 — 왜 새 체계인가

v1은 seed generation + Petri 시뮬레이션 기반이다. 적대 시나리오를 스스로 생성하고
(co-scientist 토폴로지, proximity 중복 제거, Elo 선별), Petri 감사가 행동을 다차원으로
측정하고, fitness 게이트가 승격을 판정했다. 2026-06 캠페인의 결론은 채택 0 — 게이트가
비개선 변이를 정확히 기각한 정직한 기록이지만, 동시에 세 한계의 기록이기도 하다.

1. **신호 분산이 3중이다.** 시드 분포 + auditor 행동 + judge 채점이 전부 확률적이라
   노이즈 밴드가 넓고, 검출 한계 위로 올라오는 개선이 드물다. 병목은 옵티마이저가 아니라
   측정이었다.
2. **폐쇄 회로다.** 시드도 측정도 자기 생성 — 외부 앵커가 없어, 시뮬레이션 위의 개선이
   실태스크 능력과 얼마나 닿는지 검증할 수 없다.
3. **판정이 비싸다.** LLM-judge 집계는 replicate 를 늘릴수록 비용이 정비례라, 노이즈를
   통계로 조일 수단이 사실상 없다.

v1이 확립한 것은 남긴다: 무변이·무작위 대조군, 버전 동결 held-out, K-재측정 반증,
"이진 신호는 평균에 섞지 않는다"(`core/audit/contracts.py`). Crucible 은 이 규율 위에
**신호만 교체**한다.

## 2. τ²-bench 실측 — 외부 자로 먼저 잰 좌표

2026-07-03, sierra-research/tau2-bench@1901a30, GEODE v0.99.269, agent gpt-5.2 (high, payg),
native user_simulator gpt-4.1-2025-04-14, pass^1 (num_trials=1):

| 도메인 | Reward / pass^1 | 세부 |
|---|---|---|
| retail | **0.7632** (87/114) | write actions 140/174, db_match 88/113 |
| telecom | **0.8772** (100/114) | write actions 471/496, 종료 전건 user_stop |
| airline | 0.8200 (41/50) | 채점 ground-truth 품질 이슈로 추세 참고용 |
| 가중 집계 | 0.8201 (228/278) | Agent-World 식 내부 비교 전용 |

좌표: Agent-World 표의 GPT-5.2 High(80.2)와 동급, Claude Sonnet-4.5(84.7)·Gemini-3 Pro(85.4)
아래, OpenAI 공식 GPT-5.2 Thinking(telecom 98.7 / retail 82.0, 자체 리서치 셋업·airline 제외)
대비 **-11.0 / -5.7**. 같은 모델에서 나는 격차이므로 손실은 모델이 아니라 하네스 정책 층이다.

## 3. Weakness Band — Full Diagnosis Of 41 Failures

Full `results.json` analysis, first pass on 2026-07-04 and reclassified on 2026-07-06. The failure
mode is narrower than "the agent did not write." Retail is dominated by **wrong final mutating-tool
argument selection**. Telecom is dominated by **missing terminal state verification before ending a
compound troubleshooting workflow**.

**Retail, 27 failures** — 25 have DB reward 0. In many cases the agent did call a tool, but one of the
submitted fields (`order_id`, `item_ids`, `new_item_ids`, address, payment method, or cancel reason)
diverged from the evaluator gold state.

| Failure cluster | Count | Treatment surface |
|---|---:|---|
| address mutation completeness | 6 | Verify address source selection, `address2` preservation, and order/profile joint update |
| return delivered item selection/refund | 5 | Verify partial-return item set and refund method |
| exchange delivered item selection | 4 | Verify variant preference/fallback mapping to replacement item |
| pending item modification/variant choice | 4 | Verify pending item subset and payment method |
| DB mismatch without action-check failure | 4 | Verify DB-diff postconditions outside action checks |
| cancel pending order/order subset | 3 | Verify cancellable order subset and reason canonicalization |
| tool schema/runtime error | 1 | Preserve required args such as `address2` |

Example: retail task 0 called `exchange_delivered_order_items`, but selected a keyboard replacement
that did not match the user's fallback condition and evaluator gold state, producing DB reward 0.
Therefore the S1/S5 "do the write" treatment is only partially correct. The primary treatment is
**structured commit-plan verification before mutating writes**.

**Telecom, 14 failures** — all 14 fail ENV_ASSERTION. The failures cluster as MMS 11, service 2, and
mobile_data 1. Missing actions are `grant_app_permission` 8, `toggle_roaming` 6, `enable_roaming` 5,
`reset_apn_settings` 2, and `refuel_data` 1. In compound issues, the agent fixes an early cause and
then transfers or ends before exhausting the remaining causes. MMS is especially weak when
SMS/storage permission, APN/MMSC, data usage, and roaming interact. Service tasks are especially weak
when APN reset, bill suspension, and SIM reseat interact.

The shared pattern is **missing action-completion discipline**, but the domain treatments differ.
Retail needs wrong-write prevention. Telecom needs workflow completion and terminal verifiers. Failed
task IDs are frozen in `tmp/tau2_failed_{retail,telecom}.txt`.

## 4. Approach — Assay System

### 4.0 Basic Concepts — Verifier-Centered Search Protocol

Once candidate generation becomes cheap, the bottleneck moves from generation ability to the
**cost, throughput, and reliability of the evaluator/verifier**. Crucible's core question is not
"is the LLM agent smart?" The question is: "Can this domain generate candidates cheaply, reject them
cheaply, and spend expensive verification only on candidates that deserve it?"

| Concept | Meaning | Crucible mapping |
|---|---|---|
| Search space | The full space of possible improvement candidates: prompts, policies, harnesses, code, schedules, kernel tuning, etc. | Mutation candidates such as S1/S5/R1/T1 |
| Iteration cost | Time, tokens, money, and human attention required to generate and verify one candidate | One clop48 segment: ~175M tokens and ~$837 |
| Verifier/evaluator | Mechanical judge that determines whether a candidate improved behavior | τ²-bench, paired task success |
| Cascade | Structure that escalates from cheap evaluation to expensive evaluation | G0 → G1 → G2 → G3a → G3b → G3c |
| Noisy verifier | Evaluation can fluctuate statistically or be contaminated | K=1 pass noise, rate-limit contamination |
| Paired comparison | Direct comparison between base and candidate on the same task | Flip/regression-centered verdicts |
| Early rejection | Device that cannot promote, but can kill bad candidates early | `sequential_gate.py` |
| Champion chain | Only the best verified state becomes the next baseline | No core merge before gates pass |
| Archive/memory | Pool of past candidates, failures, and success traces for future search | Failure clusters, trace replay, handoff |
| Multi-fidelity | Layering accurate/expensive evaluation with cheaper/imperfect evaluation | Full τ² is the final court; earlier gates are reject-only |

### 4.1 Principles And Three Signal Axes

**Verdict comes before autonomy.** The convergence rate and correctness of the loop are upper-bounded
by verifier strength and throughput. Signals are split into three axes and are not mixed:

| Axis | Source | Role |
|---|---|---|
| capability (primary signal) | deterministic task-success on τ² train subsets | Optimization target |
| safety (floor) | Petri critical axis + tool-contract PASS/FAIL | Out-of-aggregate veto, not exchangeable |
| cost (budget) | E1 mutation cost ledger | Upper-bound constraint |

### 4.2 Gate Ladder v2 (Cost Ladder — Reject Accelerator Centered)

The v1 design had a ladder on paper, but the first S5 cycle reached **expensive full-ish paired τ²
runs too quickly**. One clop48 segment consumed ~175M tokens and ~$837 with zero promotions. The
verifier starved the optimizer. The bottleneck was not mutation quality; it was **verification
throughput, the limiting reagent**. v2 pushes cheap rejection to the front so hopeless mutations die
before reaching the full benchmark.

```
G0 static reject   Out-of-surface, duplicate, missing evidence_refs, overbroad guard,
                   step-budget risk, tool-contract mismatch, or missing expected failure mode
                   -> immediate reject. Cost 0.
G1 trace replay    Replay existing failure trajectories and ask only whether this mutation has
                   a real intervention point. If intervention points = 0, reject. Cost 0, no LLM.
G2 micro-sim       Representative 5-10 tasks from the failure cluster, low max_step.
                   Reject-only, no promotion authority. Minute-scale.
G3a targeted mini  Failure cluster 12-20 + matched clean control 8-12.
                   Reject-only. Low cost.
G3b sequential     Full candidates only. Update flip/regression every ~10 discordant pairs.
                   Stop early on SPRT/Bayesian futility when regression risk is high. Medium cost.
G3c full paired    Final court immediately before promotion. Public-number path, K=3 replicate.
                   High cost.
G4 held-out        Telecom subset + MCPMark File no-regression. Medium cost.
G5 safety          Petri critical regression strict reject AND contract veto. Medium cost.
G6 cost            Within $/task and latency budget. Reuse records.
G7 verdict         If all pass, promote in the git chain; otherwise revert or archive.
```

Core principle: **cheap rejection must eliminate most candidates; expensive benchmarks are for the
few survivors; full paired evaluation is the final court immediately before promotion.** Early stop
is **reject-only**. Full benchmark results are public/promotion evidence, so mid-run results must not
enter core as early promotion. But mid-run evidence can safely kill a candidate.

**G3b sequential verdict (early-stop = reject accelerator).** Do not run 114×2 from the start. Observe
only discordant pairs sequentially: flip = improvement evidence, regression = regression evidence.
After each update, render a verdict from a Beta-Binomial posterior:
- **Hard reject**: after at least 12 discordant pairs, regression >= flip + 4; or on held-out,
  P(delta < -3pp) > 0.90; or a safety-floor violation.
- **Futility stop**: posterior probability of final +3pp improvement is below 5%.
- **Continue**: flip/regression gap is small and sample size is insufficient.
S5 telecom ended at flip 4 vs regression 12, so this rule would have killed it before a full run.
`scripts/eval/sequential_gate.py` implements this with a Beta(1,1) prior and delta = s5_pass −
base_pass.

G3c tests paired task flips, not aggregate scores, using exact one-sided binomial tests over
discordant pairs. G5 extends the v1 rule "do not average binary signals" into the gate ladder.

### 4.3 External Cases And Lineage — Same Economics, Different Verifiers

The systems differ by network and domain, but the structure is the same: **candidate generators get
cheap, and verifier throughput governs the economics of experimentation.**

| Family | Cases | Core structure | Crucible interpretation |
|---|---|---|---|
| LLM+evaluator discovery | AlphaEvolve, FunSearch | LLM produces executable code/function candidates; automated evaluators verify them; only strong candidates enter the archive/prompt material | The core asset is not the mutator. It is the archive + evaluator + selection loop. Full τ² must not be the default inner-loop evaluator |
| Compiler/kernel autotuning | AutoTVM, Ansor, TVM MetaSchedule, Triton | Huge schedule/search spaces are reduced with cost models, evolutionary search, and staged measurement | The standard semiconductor treatment for iteration cost is surrogate/cost-model/staged measurement. τ² needs trace replay, micro-sim, and targeted subsets before full runs |
| Chip design automation | Google RL floorplanning/AlphaChip, NVIDIA ChipNeMo | Peripheral loops with PPA/EDA verifiers are automated: placement, EDA scripts, bug summarization/analysis | Automating harness/triage/script loops has higher ROI than mutating core behavior first. This aligns with Furiosa AX-style roles |
| Software engineering agent eval | SWE-bench, SWE-agent, OpenHands, Agentless | Real issues are verified by unit tests or patch validation. Agent-computer interface and localization dominate performance | More agentic is not always better. Accurate failure localization and cheap patch validation come first |
| Iteration-cost theory | Hyperband, multi-fidelity BO, sequential testing | Many candidates get small budgets; promising or uncertain candidates receive larger budgets; runs stop before fixed sample size once evidence is sufficient | `sequential_gate.py` is the right direction, but the next missing piece is candidate-level value-of-information budget scheduling |
| Physical AI uncertainty | Conformal prediction + SIL/HIL/real-world cascade | Physical evaluation is expensive and risky, so humans/real-world verifiers are called only when uncertainty is high | τ² is also an expensive world. Only uncertain candidates should reach the full verifier |

Sources, public primary or near-primary: AlphaEvolve DeepMind blog
`https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/`,
FunSearch Nature `https://www.nature.com/articles/s41586-023-06924-6`, Ansor OSDI
`https://www.usenix.org/conference/osdi20/presentation/zheng`, Hyperband JMLR
`https://jmlr.org/papers/v18/16-558.html`, AutoTVM `https://arxiv.org/abs/1805.08166`,
TVM MetaSchedule `https://tvm.apache.org/docs/deep_dive/tensor_ir/tutorials/meta_schedule.html`,
Triton `https://openai.com/index/triton/`, Google chip placement
`https://www.nature.com/articles/s41586-021-03544-w`, AlphaChip
`https://deepmind.google/blog/how-alphachip-transformed-computer-chip-design/`, ChipNeMo
`https://research.nvidia.com/publication/2023-10_chipnemo-domain-adapted-llms-chip-design`,
SWE-bench `https://www.swebench.com/original.html`, SWE-agent `https://arxiv.org/abs/2405.15793`,
OpenHands `https://arxiv.org/abs/2407.16741`, Agentless `https://arxiv.org/abs/2407.01489`,
multi-fidelity BO survey `https://arxiv.org/html/2311.13050v2`, conformal robotics warning
`https://stanfordasl.github.io/wp-content/papercite-data/pdf/Luo.Zhao.ICRA22.pdf`.

Summary: **Crucible is narrower and more practical than "LLM agent self-improvement." It is a
verifier-centered search protocol for reducing the iteration cost of engineering candidates under a
noisy verifier.**

| Technique | Source lineage | Implementation |
|---|---|---|
| Trace-grounded mutation proposal | GEPA + SWE-bench/Agentless lessons | Classify failure traces → require `evidence_refs` in proposals |
| Evaluation cascade | AlphaEvolve/FunSearch + compiler autotuning + Hyperband | Start with zero-cost gates; expensive measurement only for surviving candidates |
| Frozen external held-out + domain split | Agent-World (arXiv 2604.18292) | train=retail subset / held-out=telecom / airline=trend only |
| (1+1)-ES trunk + bounded archive | karpathy/autoresearch + DGM | One mutation per cycle; retain at most N<=5 rejected/partial-improvement candidates |
| Slot-disjoint merge | GEPA crossover | Merge disjoint policy slots only after the same gates pass |
| Multi-fidelity budget | Hyperband + multi-fidelity BO | Allocate budget between G3a/G3b/G3c using posterior value of information (not implemented) |

**Rejected techniques and revival conditions**: multi-objective Pareto selection (v0.99
(1+lambda)+Tchebycheff layer, removed by PR-DROP-GROUP-SAMPLING on 2026-05-29 because it is invalid
on one noisy judge axis; revival condition: at least two clean axes), (1+lambda) parallel batches
(revival condition: generation-level evaluation parallelism), domain specialization + router
(revival condition: measured retail/telecom rules diverge), and MAP-Elites/QD (for cheap,
deterministic-evaluation domains only).

**Selection structure**: the original karpathy/autoresearch loop intentionally has no branching or
population: three-file discipline, fixed five-minute budget, one metric, and git as the optimizer.
The imported philosophy is: *use the dumbest optimizer that still permits controlled comparison.
Smartness belongs in mutation proposal; simplicity belongs in verdict structure.* Selection
complexity is a dependent variable of experiment economics. The trunk remains a linear champion
chain; expansion is limited to git-native archive/merge.

Honest classification: this system is constrained, verifier-guarded **stochastic hill climbing**.
The difference from a naive hill climber is the machinery that first verifies whether the hill is
real: noise-band premeasurement for fake hills, frozen held-out for Goodhart hills, floor veto for
safety cliffs, and archive for plateau escape.

### 4.4 Mutation Surface

Entry criteria: (1) causal proximity, where measured failure modes map to the slot; (2)
detectability, where expected effect is at least as large as the paired detection floor; (3)
separation from the ruler; and (4) evaluation cost. The §3 diagnosis maps to these surfaces:

| | Slot | Evidence failure mode |
|---|---|---|
| S1 | Agent system-prompt action-completion rule | Ending before required write actions |
| S2 | `tool_policy` JSON | Missing pending-write check before ending |
| S3 | Tool descriptions | Wrong mutating-tool arguments |
| S4 | Decomposition policy | Missing checklist sweep for compound troubleshooting |
| S5 | Evolve-block code: deterministic termination guard (Tier 1b, second pass) | Structural treatment for the above failures |
| R1 | Retail commit-plan guard | Wrong order/item/address/payment write |
| T1 | Telecom workflow-completion guard | Missing terminal verifier before ending or transfer |

Exclusions: user simulator prompts (comparison contamination), benchmark domain policy
(mutation-as-cheating), and all task selection/scoring surfaces (the ruler itself). Granularity:
section/key level only. Size: expand mutation surfaces only as fast as gate throughput can absorb.

**Prompt language rule.** Design rationale may be written in Korean, but any scaffold text that can
enter the model context, including system prompts, guard text, and policy wording, must be recorded
as English source text. The measured agent and user simulator run in an English benchmark
environment, so Korean prompt text must not be kept as an intermediate prompt artifact.

R1/T1 draft scaffold text is recorded only in English:

```text
R1 retail commit-plan guard:
Before any mutating retail tool call, build a concise commit plan that lists
the exact order_id, item_ids, replacement item_ids, address fields, payment
method, and reason that will be sent to the tool. Verify each field against the
latest tool results and the user's stated preferences, including fallback
preferences. If any field is inferred rather than observed, ask or inspect
before calling the mutating tool.

T1 telecom workflow-completion guard:
Before transferring or ending a telecom troubleshooting conversation, verify
the terminal condition for the issue type. For MMS, confirm can_send_mms is
true. For mobile data, confirm mobile data is enabled and the speed test meets
the user's required threshold. For no-service issues, confirm service status is
connected. If the terminal verifier fails, continue the workflow instead of
ending or transferring, unless the policy explicitly requires escalation.
```

## 5. 첫 사이클 기록 — M1/S5 게이트 시운전

목적 둘: 실측 개선 후보의 검증 + 게이트 사다리 자체의 시운전. **사람 손 수정도 루프
변이와 같은 사다리를 통과해야 게이트의 공정성이 성립한다.**

- 변이: S1 행동 완결 규율. `plugins/benchmark_harness/tau2_geode_agent.py::_agent_system_prompt`
  의 인자 규율 문단 뒤·`<policy>` 앞. 도메인 무관, 답 유출 없음(OpenAI 가 telecom 에
  "brief, generally helpful instruction" 을 공개적으로 쓴 것과 같은 범주).
- G1 통과(2026-07-04): 프롬프트 단언 테스트 7건, branch `feature/sev2-m1-action-discipline`.
- G2 통과: mock 도메인, G3 동일 배선(gpt-5.2 payg + native user_simulator), DB match 1/1.
- G3 진행 기록: 실패 서브셋 표적 재실행(retail 27 + telecom 14, 동시성 8 병렬).
  **해석 규율: 실패분만 재실행은 방향 신호(flip rate)일 뿐** — 통과분 회귀가 안 재지므로,
  신호 확인 시 도메인 전체 paired 재실행 후에만 수치를 공개한다. 리비전이 다른 run 은
  평균하지 않는다.
- 사전 등록(초안, 캠페인 전 hash 봉인): train 서브셋 = retail 실패 27 + 통과 층화 23 = 50,
  K=3, discordant 정확 이항검정 단측 p<0.05, 승격 상한 캠페인당 2, 무변이 대조 arm 상시.
- G3 방향 신호 (2026-07-04): 실패 서브셋 표적 재실행 flip-to-pass — retail 10/27 (37%),
  telecom 6/14 (43%), 합계 16/41 (39%).
- **M1 최종 판정 (2026-07-04, 전체 paired, 각 n=114): 기각.**
  retail 0.7632→0.7807 (flip 12 vs 회귀 10, 정확 이항 단측 p=0.416),
  telecom 0.8772→0.8333 (flip 10 vs 회귀 15, p=0.885 — 점추정 음, 비유의).
  방향 신호 39% 는 재추첨 노이즈가 지배한 것으로 판명 — 실패 서브셋만 재실행하면
  회귀가 안 보인다는 설계 경고 그대로다. 회귀 트레이스는 부작용 서명이 아니라
  동일 실패 모드(write 미실행)의 재추첨: 이 모드는 태스크 집합 전체에 확률적으로
  분포하며, 프롬프트 문장 하나로는 발생률이 움직이지 않는다.
  → S1 은 승격하지 않는다. 변이 브랜치(`feature/sev2-m1-action-discipline`)는
  아카이브로 보존. **처방을 코드 층으로 이동: S5 결정론 종료 가드**
  (`feature/sev2-s5-termination-guard`, 첫 EVOLVE-BLOCK).
- **부수 실측 — pass^1 재실행 노이즈 바닥**: 양 도메인 discordance 22/114·25/114
  (태스크당 flip 확률 ~20%, 準무효과 변이 기준 추정). 단일 pass^1 비교로는
  ~8pt 미만 효과가 검출 한계 아래 — K=3 replicate 사전 등록의 데이터 확증.
  (정밀한 노이즈 바닥은 무변이 대조 재실행으로 별도 확정 예정.)

### S5 측정 경과 (2026-07-04, 판정 미완)

S5(결정론 종료 가드, `feature/sev2-s5-termination-guard` @ e1b060474) 전체 paired 측정 중
**OpenAI quota 소진(21:59 KST)으로 retail 43·telecom 58건이 infrastructure_error 로 오염**됐다.
오염분은 판독에서 제외하고 태스크 ID 를 `tmp/s5_infra_{retail,telecom}.txt` 에 고정 —
quota 복구 후 동일 리비전으로 패치 측정해 병합한다(사건·병합 프로토콜 공개 전제).

오염 제거 클린 판독 (중간, 판정 아님):
- retail (train, n=70): 0.771 → 0.871 (+10.0pt), flip 11 vs 회귀 4, p=0.059 —
  사전 등록 임계(0.05) 직상. 방향 양호하나 게이트 통과 선언 불가, 잔여 43건이 판정을 가른다.
- telecom (held-out, n≈51 클린): flip 1 vs 클린 회귀 2 — 쉬운 태스크로 편향된 서브셋에서
  중립 수준. 무회귀 확인은 잔여 58건 측정 후.
- 회귀 트레이스에 nudge 부작용 서명(과잉 write·스텝 고갈) 없음 — 기존 실패 모드의 재추첨 범위.

패치 측정(2026-07-04 22시대)도 quota 재소진으로 부분 완료. 오염 필터(infrastructure_error
∨ 메시지 에러 ≥3) 적용 클린 병합 판독:
- retail (train): 측정 96/114, 0.8021 → 0.8333 (+3.1pt), flip 12 vs 회귀 9, p=0.332 —
  중간 구간의 +10pt(p=0.059)가 표본 확장에서 수축. 현 증거로는 승격 불가.
- telecom (held-out): 측정 61/114, flip 1 vs 회귀 3 (-3.3pt, p=0.94) — 회귀가 service_issue
  (apn/lock_sim) 절차형 태스크에 군집. M1 에서도 telecom 점추정이 음이었다 — retail 의
  write-skip 을 겨냥한 개입이 telecom 의 다단계 절차 흐름을 방해한다는 가설이 두 사이클에서
  일관. trigger B(미검증 write nudge)의 도메인 조건화가 evolve-block 1차 변이 후보.
- 미측정 retail 18 + telecom 53 — quota 복구 후 완결 전까지 최종 판정 보류.

두 사이클(M1·S5)의 공통 관찰: pass^1 K=1 의 검출 한계(~8pt) 아래에 하네스 개입의 실효과
(~3pt급)가 있다. 사전 등록된 K=3 replicate 는 선택이 아니라 이 효과 크기를 재는 유일한
수단이다. 검증 처리량(quota 헤드룸 포함)이 곧 루프의 상한이라는 본 문서 원칙의 실측 사례.

교훈(운영): 외부 API quota 는 측정 인프라의 단일 장애점 — 캠페인 전 quota 헤드룸 확인을
G2(smoke) 체크리스트에 추가한다. quota 사망 중 완료된 run 은 termination_reason 필터 없이
읽으면 변이 효과로 오독된다(본 사건에서 watcher 의 무필터 1차 판독이 실제로 오독을 냈고,
too_many_errors + 메시지 에러 다발도 부분 오염으로 배제해야 한다).

### sub55 트랙 시도와 이중 한도 소진 (2026-07-04 밤 — 기록)

payg quota 차단을 우회하려 subscription 전용 트랙(sub55: agent gpt-5.5 sub high +
geode_user gpt-5.5 sub medium, 양팔 = S5 부모 vs S5)을 설계·발사했다. 결과 두 가지:

1. **실버그 발굴·수정**: tau2 동시성(c3+)에서 codex-oauth 가 RecursionError 로 즉사 —
   `_codex_sdk_workaround.py::install()` 의 무락 check-then-act 레이스로, 늦은 스레드가
   패치된 함수를 원본으로 캡처해 전역을 덮어쓰면 자기 호출 사슬이 형성되는 버그.
   설치 락 + 클로저 캡처 + 멱등 마커로 수정(유닛 5종·8스레드 스트레스·c4 실증 통과,
   양팔 동일 커밋). 외부 벤치마크를 세게 돌리는 일 자체가 런타임 결함을 드러낸 사례.
2. **구독 usage limit 실증 소진**: 수정 후 c6 재발사에서 recursion 0 을 확인했으나,
   plan(prolite)의 사용 창이 소진돼 429 폭풍(rate limit 18k+) 후
   `usage_limit_reached` (reset 07-07 16:53 KST). r2 데이터는 전량 폐기.

측정 경로 현황: payg = billing 한도 차단(상향 시 gpt-5.2 트랙 잔여 71건으로 S5 판정 완결
가능), subscription = 07-07 리셋 대기. **검증 처리량이 루프의 상한이라는 원칙의 세 번째
실측**(judge 노이즈 → API quota → 구독 창). 캠페인 설계에 quota 헤드룸 사전 확인(G2)과
플랜 규모 대비 런 예산 산정이 상수로 들어가야 한다.

### clop48 트랙 usage 오염 (2026-07-05~06 — 재측정 대상, user-sim은 무결)

Claude 구독 경로 S5 재판정(opus-4-8 agent + geode_user sonnet user). 4런 완주했으나
옛 계정(Max 20x)의 **7d 창 소진 이후 태스크가 rate-limit 주입으로 오염**. 태스크 단위 분해:
rate-limit 없는 태스크는 전부 user_stop 정상 종료했고 **순수 미종료(user-sim 결함)는 0건**
(retail/s5만 5건). 즉 **user simulator는 무결**했고 초기 진단(종료 결함)은 오진 — 정정.
오염분은 max_steps로 "완료" 기록돼 auto-resume이 스킵했을 뿐, 재측정 가능.

클린(user_stop) 태스크 수: telecom base 40·s5 19, retail base 31·s5 28. paired 유효는 양팔
공통 클린 교집합만 → 도메인당 최대 ~19·~28이라 재측정 없이는 검정력 부족.

버그 발굴(⑥, main 반입 PR): **rate-limit 에러가 대화 메시지로 주입돼 termination_reason
필터를 우회**(infrastructure_error로 격리 안 됨) → max_steps로 오완료. 격리 배선이 개선점.
(⑤ user-sim 종료 결함은 오진으로 철회.)

재측정 경로: 새 계정(Max 5x, 창 여유) 또는 payg(native user). 오염 task_id는
`tmp/clop48_contaminated_{dom}_{arm}.txt`로 추출.

### 5.1 First-Cycle Conclusion — The Limiting Reagent (2026-07-06)

The first Crucible cycle did not prove self-improvement. It **proved the promotion protocol and
exposed verification throughput as the limiting reagent.** The next engineering target is not a
smarter mutator; it is a cheaper evaluator cascade.

- What worked: frozen ruler, paired comparison, held-out regression, blocking plausible-looking
  changes before core merge, and recording rejection as evidence.
- What failed: iteration cost was too high (clop48 ~175M tokens and ~$837), K=1 pass^1 noise gave low
  detection power (~8pt floor), quota shaped the experiment, cheap gates were not discriminative
  enough, and one mutation consumed too much full simulation.
- Treatment: §4.2 Gate Ladder v2 — stronger G0 static reject, G1 trace replay with no LLM, G2
  reject-only micro-sim, G3a targeted mini, G3b sequential SPRT/Bayesian futility, and G3c full only
  immediately before promotion. The core is a reject accelerator that preserves full τ² budget.

### 5.2 Current Design Assessment — Keep, Revise, Hold

**Keep.** The promotion protocol was correct. The frozen ruler, champion chain, paired comparison,
contamination filter, held-out regression, and "do not average binary veto signals" rule prevented
S1/S5 from entering core prematurely. The first win of the loop is not a self-improvement promotion;
it is **false-promotion prevention**.

**Revise.** The reclassified failures show that S5's "write nudge before ending" is too broad. Retail's
dominant failure is wrong-write, so it needs R1 commit-plan guard. Telecom needs T1
workflow-completion guard. M1/S5 already showed the limit of trying to reduce both failure families
with one domain-agnostic behavioral sentence.

**Hold.** S5 has promising signal in the clop48 clean subset (retail CONTINUE, telecom
PROMOTE_CAND), but rate-limit contamination and small sample size make it ineligible for promotion.
Do not issue a final verdict until payg/native-user remeasurement or contaminated-task remeasurement
is complete.

**Next loop with current resources.** Before spending another full τ² run, strengthen G1/G2 using the
41 existing clean failures plus matched pass controls.

1. **Failure manifest**: attach `cluster`, `expected_write`, `actual_write`, `intervention_turn`,
   `candidate_guard`, and `false_positive_risk` to each failure. Cost: zero.
2. **G1 trace replay**: determine whether R1/T1 has an intervention point in existing transcripts and
   whether it would intervene unnecessarily on passing traces. No LLM calls.
3. **G2 micro-sim**: run only 5-10 representative tasks with a low max-step budget. Reject-only.
4. **G3a targeted mini**: run 12-20 failure-cluster tasks plus 8-12 matched clean controls. Still no
   promotion authority.
5. **G3b/G3c**: only full candidates reach sequential futility and then full paired evaluation. Public
   numbers start here.

Assessment: the design direction is correct, but the **budget scheduler** and **failure manifest
schema** are still missing. `sequential_gate.py` is only one G3b component. The next bottleneck is the
multi-fidelity scaffold that operates G0 through G3a automatically.

### 5.3 Loop Execution Spec And Budget

Crucible should run as a staged evaluation loop, not as repeated full tau2 sweeps. The loop is:

1. **Observe**: ingest failed and passing traces, classify failure clusters, and select one narrow
   mutation surface.
2. **Propose**: generate one domain-specific candidate guard or harness change. Keep R1 and T1 separate.
3. **Replay**: test the candidate against existing transcripts and matched pass controls. Reject only.
4. **Micro-sim**: run a small live slice with low step budgets. Reject only.
5. **Targeted mini**: spend live calls only on failure clusters plus clean controls. Reject only unless
   the signal is overwhelming and pre-registered.
6. **Sequential gate**: stop early for futility or contamination; do not promote from this gate alone.
7. **Full tau2**: promotion authority. Use paired base-vs-candidate comparisons, frozen task IDs, and
   the ledger rules.

| Stage | Scope | Promotion authority | Expected budget |
|---|---|---:|---:|
| Failure manifest | 41 clean failures + matched pass controls | No | $0, 1-2 engineer hours |
| G1 trace replay | Existing transcripts only | No | $0, 2-4 engineer hours |
| G2 micro-sim | 5-10 tasks, low max-step, one domain | No | low subscription quota burn |
| G3a targeted mini | 12-20 cluster tasks + 8-12 controls | No | medium subscription quota burn |
| G3b sequential | Incremental paired tasks until futility/continue | No | capped by posterior value-of-information |
| G3c full | Pre-registered paired domain slice | Yes | highest subscription quota burn; run only after G3b survives |
| G4 held-out | Fresh unseen task slice after G3c | Yes, confirmatory | domain-dependent; run only for promotion candidates |

Model/route compatibility is part of the measurement contract:

| Lane | Current model support | Use in Crucible |
|---|---|---|
| OpenAI PAYG/API | `gpt-5.2` is registered locally and is the native-user comparator lane | Use for apples-to-apples tau2/native-user confirmation when billing is available |
| Codex / ChatGPT subscription | `gpt-5.5` is the supported/default Codex lane in local routing; OpenAI Codex docs list `gpt-5.2` as deprecated for ChatGPT sign-in; live probe on 2026-07-06 returned 400 for `gpt-5.2` and OK for `gpt-5.5` | Use as a lower-cash, product-route exploration lane; do not average with PAYG `gpt-5.2` |
| Anthropic subscription | Claude subscription models are a separate family (`claude-sonnet-*`, `claude-opus-*`) | Use only for Claude-specific candidate evidence; do not compare as same-model evidence |

Implication: subscription can reduce cash burn, but it is not a same-model substitute for the
`gpt-5.2` PAYG tau2 track. Subscription runs are useful for reject-only screening and qualitative
debugging; final promotion should either use the same model/user route as the baseline or be published
as a separate product-route result.

**PAYG-free operating mode (current loop).** If PAYG is excluded, Crucible resets the measurement
contract instead of weakening it:

- baseline = current GEODE over `gpt-5.5` Codex/ChatGPT subscription
- user route = `geode_user` over `gpt-5.5` Codex/ChatGPT subscription
- verdict scope = product-route improvement only; no claim against PAYG `gpt-5.2`
- full tau2 = still promotion authority, but only inside the same subscription model/user route
- published wording = "subscription product-route result", not "tau2 leaderboard comparator"

The zero-cost input for this mode is generated by `scripts/eval/build_failure_manifest.py`:
`tmp/crucible_failure_manifest.json` currently records 41 failures and 187 pass controls with R1/T1
candidate guards, expected writes, actual write-like calls, argument diffs, unmet environment
assertions, intervention turns, and false-positive risk notes. The observed failure clusters are:
address mutation completeness 10, return delivered item selection/refund 6, exchange delivered item
selection 5, cancel pending order subset 3, pending item modification 2, tool schema/runtime 1,
MMS workflow completion 11, service terminal verifier 2, and mobile-data terminal verifier 1.

G1 trace replay is generated by `scripts/eval/trace_replay_gate.py`:
`tmp/crucible_g1_trace_replay.json` currently gives:

| Guard | G1 verdict | Failure support | Pass-control block rate | G2 condition |
|---|---|---:|---:|---|
| R1 | `PASS_TO_G2_WITH_CONTROLS` | 24/27 = 0.889 | 4/87 = 0.046 | Include control task IDs 2, 46, 64, 73 in G2 before any targeted mini |
| T1 | `PASS_TO_G2` | 14/14 = 1.000 | 0/100 = 0.000 | Proceed to G2 micro-sim |

Therefore the immediate subscription-only live spend is not a full S5 rerun. It is a G2 micro-sim:
T1 first, then R1 with the four blocked controls included as canaries.

Before G2 spends subscription quota, the runner enforces a **route readiness hard gate**. A 2026-07-06 attempted T1
baseline micro-sim
(`crucible-tau2-g2-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n2k1-20260706-a`)
was interrupted after repeated Codex subscription `empty output_text` completions. The raw tau2
`results.json` contains 0 simulations, so it is **not** performance evidence. It is infrastructure
evidence: the product-route evaluator/runtime was not ready for G2. Diagnostic dumps:
`~/.geode/diagnostics/codex-oauth-empty-text/1783286103-gpt-5.5.json` through
`1783286160-gpt-5.5.json`.

`plugins/benchmark_harness/tau2_geode_agent.py` now treats an empty visible GEODE turn with no
projected tau2 tool call as an infrastructure failure by default. It raises before the harness can
turn that condition into a synthetic user/assistant message. `--allow-empty-geode-turn` exists only
for debugging and must not be used for scored G2/G3 runs.

A narrower 2026-07-06 readiness probe
(`crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-a`)
showed the first hard gate was insufficient: Codex `empty output_text` occurred in an internal
reflection/recovery path, but the final turn still produced visible text and tau2 completed as
`max_steps`. This is also contamination evidence, not performance evidence. The runner now enables
`GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT=1` by default so the codex-oauth adapter raises on any empty
subscription response. It also disables AgenticLoop cognitive reflection by default during tau2 runs
and sets `GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR=1` so AgenticLoop propagates adapter failures instead
of retrying the same contaminated prompt. OpenAI's Responses guidance says manually managed
multi-turn state should pass prior `response.output` items back into the next request, especially
for reasoning/tool-use flows under `store=false`; the Codex adapter now preserves and replays those
official output items before falling back to the older reasoning-item reconstruction path. As a
backstop, the runner scans
`~/.geode/diagnostics/codex-oauth-empty-text/` after the run; any new dump aborts after trajectory
snapshotting so infra-failure evidence is still preserved. The runner also exposes `--max-retries` and defaults it to 0 so tau2 does not retry
the same infrastructure failure three more times. `--allow-empty-geode-turn` disables the
adapter-level fail-fast and the final-turn fallback guard for debugging only.
`--enable-cognitive-reflection` and `--disable-codex-output-replay` are debug-only for this
benchmark path.

Readiness status on 2026-07-06: the subscription route required two more adapter-surface fixes
before it could run a real telecom task:

- replayed `response.output` items must be sanitized for the Codex subscription input validator:
  keep semantic payloads and ids, but drop returned lifecycle fields such as top-level `status` and
  `None` fields such as `tool_search_call.content`;
- empty `output_text` is an infrastructure failure only when the response has no tool calls. A
  normal Responses tool-use turn can have `output_text=""` and a valid `function_call` item.

After those fixes, the strict readiness run completed without infra contamination:
`crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-e`.
Result: evaluated 1 simulation, reward 0.0, termination `max_steps`, trajectory snapshot written.
This is **not** a promotion-quality signal, but it proves the subscription route can now execute
multi-turn tau2 tool calls. The next bottleneck is telecom workflow completion/termination, not the
Codex OAuth transport.

Earlier probes remain infra evidence only:

| Probe run | Route | Result | Interpretation |
|---|---|---|---|
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-output-replay-a` | agent xhigh / user high | 400 `input[1].status` | replay sanitizer missing for returned output-item lifecycle fields |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-output-replay-b` | agent xhigh / user high | infra error, reasoning-only empty text | strict gate works; no tool/action emitted |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-c` | agent high / user high | false infra error on valid `function_call` | fixed by allowing function-call-only turns |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-d` | agent high / user high | 400 `tool_search_call.content` | fixed by dropping top-level `None` replay fields |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-e` | agent high / user high | evaluated; `max_steps`, reward 0.0 | route ready; workflow completion still poor |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-f` | agent xhigh / user high | infra error, 0 evaluated, exit 1 | strict gate works; route not ready |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-none-openai-sub-gpt55-none-n1k1-20260706-a` | agent none / user none | infra error, 0 evaluated, exit 1 | lowering effort does not clear the backend empty-output failure |

Cheap termination-focused telecom loop results (same task, same `gpt-5.5/high` subscription route):

| Probe run | Variant | Result | Interpretation |
|---|---|---|---|
| `crucible-tau2-cheaploop-telecom-candidate-t1-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | T1 terminal-verifier prompt | evaluated; `max_steps`, reward 0.0, 24 messages | Worse trajectory shape: premature `can_send_mms`, no bundled user actions |
| `crucible-tau2-cheaploop-telecom-candidate-t2-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-b` | agent step-economy prompt | infra error after long history | Invalid as performance evidence; late Codex empty final-answer |
| `crucible-tau2-cheaploop-telecom-candidate-t3-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-c` | agent + user step-economy prompts | evaluated; `max_steps`, reward 0.0, 36 messages | User-side bundling appeared, but opened extra troubleshooting branches |
| `crucible-tau2-cheaploop-telecom-candidate-planner-capped-nodefer-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | deterministic planner prompt + `--agent-max-rounds 2 --user-max-rounds 2 --disable-tool-search-defer` | evaluated; `max_steps`, reward 0.0, 15 messages, 0 projected tau2 tool calls | Cost was bounded, but behavior quality collapsed: the loop talked through manual checks instead of acting through benchmark tools |

Verdict: prompt-only telecom guards are insufficient. The next valid step is **not** scored G2 and
not another prompt-only variant. The loop needs a cheap deterministic G2 surrogate: a telecom
workflow state machine that reads the trajectory and rejects candidates that violate blocker order
or step budget before live τ² spend. For MMS/no-service tasks, the state machine should track:
airplane mode off -> SIM active -> mobile data on -> non-2G network -> APN/MMS settings valid ->
`can_send_mms == true`, plus a max-turn budget for reaching each checkpoint.

`scripts/eval/telecom_workflow_gate.py` now implements that reject-only surrogate. It consumes one
or more tau2 `results.json` files, writes `tmp/crucible_telecom_workflow_gate.json`, and emits:

| Input run | Surrogate verdict | Reasons |
|---|---|---|
| baseline `...output-replay-e` | `REJECT_SURROGATE` | `max_steps`, missing terminal `can_send_mms == true` |
| T1 `...cheaploop...t1...20260706-a` | `REJECT_SURROGATE` | premature `can_send_mms`, `max_steps`, missing terminal success |
| T2 `...cheaploop...t2...20260706-b` | `INVALID_INFRA` | Codex empty-output infrastructure failure |
| T3 `...cheaploop...t3...20260706-c` | `REJECT_SURROGATE` | premature `can_send_mms`, `max_steps`, message/tool-call budget exceeded, missing terminal success |
| planner capped/no-defer `...planner-capped-nodefer...20260706-a` | `REJECT_SURROGATE` | `max_steps`, missing action before manual checklist, missing terminal success |

This becomes the next pre-live gate: a telecom candidate must pass this surrogate on replayed or
small-probe trajectories before any paired G2 spend.

Planner candidate scaffold (zero-live):

- `scripts/eval/telecom_action_planner.py` defines a deterministic MMS blocker planner. Given
  `airplane_mode_on=True`, `sim_active=False`, `mobile_data_on=False`, `network_type=2G`, and missing
  APN/MMSC, it emits one bounded safe bundle:
  `toggle_airplane_mode`, `reseat_sim_card`, `toggle_data`, `set_network_mode_preference`,
  `reset_apn_settings`, `reboot_device`, `check_apn_settings`.
- It only emits `can_send_mms` after blockers are known clear.
- Demo output: `tmp/crucible_telecom_action_plan.json`.
- Synthetic trajectory: `tmp/crucible_telecom_action_plan.synthetic_results.json`.
- Surrogate result: `PASS_SURROGATE [mms_issue]synthetic_planner_success messages=14 calls=8`.

This does **not** prove live improvement. It only proves the next candidate shape is coherent enough
to attempt a tiny live probe once wired into the runner or prompt surface.

Live planner wiring result (2026-07-06): `--agent-planner telecom-mms-v1` now injects the same
deterministic action sequence into the tau2 agent prompt. The runner also exposes two benchmark-only
cost controls: per-participant GEODE loop round caps (`--agent-max-rounds`, `--user-max-rounds`) and
`--disable-tool-search-defer`. A capped/no-defer probe reduced the conversation to 15 messages and
removed hosted `tool_search_call` overhead, but it also produced **zero projected tau2 tool calls**.
That is a useful negative result: simple "short turn" pressure is not a valid optimization target by
itself. The next candidate must pair cost controls with an action-quality precondition: after user
identity is available, the agent must query backend state with tau2 tools before asking for manual
phone checks, and every cheaploop probe must require at least one projected environment action before
it can be considered behavior evidence.

Action-before-talk gate is now implemented in `telecom_workflow_gate.py`: assistant manual phone
checklist loops are rejected unless at least one projected tau2 environment tool call appears first.
Replaying the capped/no-defer probe now produces
`missing_action_before_manual_checklist`, which correctly classifies the 15-message/0-action
trajectory as a low-action reject rather than an efficient candidate.

Main-loop alignment (2026-07-06): the action-before-talk requirement now also exists in GEODE's
runtime verifier, not only in the offline trajectory surrogate. `core.agent.verify` accepts the
opt-in `GEODE_VERIFY_ACTION_BEFORE_TALK=1` knob and emits a retryable
`manual_checklist_without_action` miss when a tau2-style phone/network checklist appears without any
tool call in the turn. `plugins/benchmark_harness/tau2_geode_agent.py` enables this by default for
benchmark runs and records it in snapshot metadata. The deterministic
`telecom_action_planner.py` remains a scaffold/fixture generator for candidate shapes; it is not the
behavior authority. Real candidates should be expressed through the GEODE loop's prompt, policy,
verify, and tool-execution surfaces.

Live main-loop-alignment probes (2026-07-06):

| Run | Surface | Verdict | Key signal |
|---|---|---|---|
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-mainverify-a` | baseline + main-loop action-before-talk verifier | `REJECT_SURROGATE` | route ready: 7 tool calls, no infra contamination, snapshot written; still `max_steps`, premature `can_send_mms`, no terminal success |
| `crucible-tau2-cheaploop-telecom-candidate-t1-mainverify-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | T1 guard + main-loop action-before-talk verifier | `REJECT_SURROGATE` | same call order as baseline: account reads → premature `can_send_mms` → `check_network_status` → `toggle_airplane_mode`; T1 prompt guard did not fix workflow ordering |
| `crucible-tau2-cheaploop-telecom-candidate-workfloworder-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | workflow-order dynamic scaffold | `REJECT_SURROGATE` | ordering improved: no `premature_can_send_mms`; calls became account reads → `check_network_status` → `toggle_airplane_mode` → `check_network_status` → `reseat_sim_card`; still `max_steps`, missing terminal success |
| `crucible-tau2-cheaploop-telecom-candidate-stepeconomy-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | workflow-order + step-economy scaffold | `REJECT_SURROGATE` | no infra/usage-exhaustion evidence; slight economy gain (24→23 messages, 7→6 calls) but user simulator still insisted on one action at a time; still `max_steps`, missing terminal success |
| `crucible-tau2-cheaploop-telecom-diagnostic-stepeconomy-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | step-economy scaffold + user-side bundling guard | `REJECT_SURROGATE` | diagnostic only: user-side coupling enabled large bundled actions, but overcorrected to 36 messages / 21 calls with premature `can_send_mms`, message/tool budget exceeded |
| `crucible-tau2-cheaploop-telecom-candidate-boundedbundle-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | bounded-bundle workflow scaffold | `REJECT_SURROGATE` | no usage-exhaustion evidence; no premature terminal verifier, 24 messages / 7 calls, two multi-tool user turns; user still refused the initial bundle and the run ended before network/APN repair and terminal `can_send_mms` |
| `crucible-tau2-cheaploop-telecom-diagnostic-boundedbundle-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | bounded-bundle scaffold + bounded user guard | `REJECT_SURROGATE` | diagnostic only: user-side bundling reached basic prerequisites and terminal `can_send_mms`, but MMS stayed false because roaming was still disabled; 32 messages / 15 calls, no usage-exhaustion evidence |
| `crucible-tau2-cheaploop-telecom-candidate-roamingrecovery-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | conditional roaming-recovery scaffold | `REJECT_SURROGATE` | agent-route-only candidate did not reach roaming recovery; user simulator again rejected the initial bundle and the run stopped at `toggle_data` before terminal MMS; 24 messages / 7 calls, no usage-exhaustion evidence |
| `crucible-tau2-cheaploop-telecom-candidate-phasedrecovery-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | native-user phased recovery scaffold | `REJECT_SURROGATE` | agent-route-only candidate reduced spend (21 messages / 4 calls) but still followed one-action-at-a-time; stopped at `toggle_data`, no terminal MMS; no usage-exhaustion evidence |
| `crucible-tau2-cheaploop-telecom-diagnostic-roamingrecovery-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | roaming recovery + bounded user guard | `REJECT_SURROGATE` | diagnostic only: reached terminal `can_send_mms=false`, then inspected line details and data usage, but still branched to Wi-Fi calling instead of repairing `roaming_enabled=false`; 31 messages / 15 calls, no usage-exhaustion evidence |

Conclusion: action projection is no longer the immediate blocker. T1 prompt-only still spends the
terminal verifier before clearing blockers, while the workflow-order scaffold removes that failure
class but still hits `max_steps`. Do **not** run scored G2 from this state. For MMS, `can_send_mms`
must remain a terminal verifier delayed until network status, airplane mode, SIM, mobile
data/network mode, and APN/MMSC blockers are cleared or explicitly ruled out; the next candidate
must also reduce step count.

Workflow-order scaffold (zero-live implementation, ready for the next cheap probe):

- `plugins/benchmark_harness/tau2_workflow_order.py` defines `TelecomMmsWorkflowOrder`, a stateful
  blocker tracker that consumes tau2 telecom tool outputs and renders a compact English
  `<crucible_workflow_order>` dynamic context block for each GEODE assistant turn.
- `plugins/benchmark_harness/tau2_geode_agent.py` exposes
  `--agent-workflow-order telecom-mms-v1` and
  `--agent-workflow-order telecom-mms-step-economy-v1`, and
  `--agent-workflow-order telecom-mms-bounded-bundle-v1`. These are candidate surfaces, not separate
  planners and not promotion authority. They keep the behavior inside GEODE's main loop:
  prompt/context → tool-use → trajectory evidence.
- Snapshot metadata records `agent_workflow_order`, and raw assistant metadata records
  `geode_workflow_order` plus `geode_premature_terminal_tools` so premature terminal verifier calls
  are auditable even before the offline surrogate runs.
- Next live command shape:
  `--agent-workflow-order telecom-mms-v1 --trajectory-stage cheaploop --trajectory-arm candidate`.
  Pass condition remains `telecom_workflow_gate.py == PASS_SURROGATE`; otherwise reject without
  scored G2.

First live result: workflow-order scaffold fixed the premature terminal-verifier failure class, but
the trajectory still rejected on `max_steps` because the loop cleared blockers one at a time. The next
cheap candidate must keep workflow order **and** improve step economy: after `check_network_status`
shows multiple blockers, bundle safe phone actions where tau2 policy/user simulator permits it
(`toggle_airplane_mode`, then SIM/data/network/APN remediation) before spending another terminal
verifier call.

Step-economy scaffold (zero-live implementation): `telecom-mms-step-economy-v1` extends the same
state tracker with an explicit bundle recommendation. It keeps `can_send_mms` out of the bundle until
blockers are clear, but asks the user simulator to perform safe prerequisite actions in one ordered
reply when one diagnostic result already exposed multiple blockers. Next live command shape:
`--agent-workflow-order telecom-mms-step-economy-v1 --trajectory-stage cheaploop --trajectory-arm candidate`.

First live result: `telecom-mms-step-economy-v1` did not pass the surrogate. It preserved the
terminal-verifier discipline and did not show subscription exhaustion, but the user simulator replied
"one step at a time" and split the phone actions. That means agent-side dynamic context alone is not
enough to remove the `max_steps` bottleneck. The next diagnostic should be a **user-side coupling
probe** (`--user-prompt-append-file scripts/eval/telecom_user_step_economy_guard.md`) to distinguish
agent policy failure from simulated-user step-economy friction. Treat that as measurement diagnosis,
not promotion evidence, because changing the user simulator changes the evaluator route.

User-side coupling diagnostic result: the guard confirmed that the simulated user can bundle phone
actions, but free-form bundling is too loose. It ran 21 tool calls, exceeded the message/tool budgets,
and let `can_send_mms` appear before the surrogate considered blockers clear. The next valid scaffold
is not another free-form prompt. It should be a **bounded bundle protocol**: one prerequisite bundle
with an explicit allowlist and no `can_send_mms`, then one consolidated status, then a separate
terminal verifier only if the tracked blockers are clear.

Bounded-bundle scaffold (zero-live implementation): `telecom-mms-bounded-bundle-v1` keeps the
workflow-order and step-economy state tracker, but narrows the bundle language to a single allowlisted
prerequisite bundle. It explicitly excludes `can_send_mms`, roaming, Wi-Fi calling, app permissions,
escalation, and repeated broad diagnostics unless prior tool evidence introduces that branch. Next
cheap command shape:
`--agent-workflow-order telecom-mms-bounded-bundle-v1 --trajectory-stage cheaploop --trajectory-arm candidate`.
This remains reject-only; scored G2 stays blocked until the deterministic telecom workflow gate returns
`PASS_SURROGATE`.

First live result: `telecom-mms-bounded-bundle-v1` stayed `REJECT_SURROGATE`. The route did not show
usage exhaustion: no new `codex-oauth-empty-text` dump appeared after the existing 07:54:57 KST file,
no adapter exception propagated, and the transcript contained no real quota/rate-limit text. The
behavioral signal is cleaner: the terminal-verifier discipline held, but the simulated user refused
the first multi-action bundle, then performed only small bundles (`check_network_status` +
`toggle_airplane_mode` + `check_network_status`, then `reseat_sim_card` + `check_sim_status`) before
the run hit `max_steps`. Gate output:
`tmp/crucible_telecom_workflow_gate_boundedbundle_a.json` → 24 messages, 7 calls,
`multi_tool_user_turns=2`, `non_2g_network=false`, `apn_valid=false`, `mms_verified=false`.

Next valid diagnostic: bounded user-side coupling with
`--user-prompt-append-file scripts/eval/telecom_user_bounded_bundle_guard.md`. This remains
measurement diagnosis, not promotion evidence, because it changes the user route. Its purpose is to
separate "agent cannot formulate the right bundle" from "the tau2 simulated user refuses bundled phone
actions unless the user-side evaluator is explicitly scoped." Do not run scored G2 until an
agent-route-only candidate passes the surrogate.

Bounded user-side diagnostic result: `telecom_user_bounded_bundle_guard.md` confirmed the evaluator
can execute a bounded prerequisite bundle. It reached `can_send_mms`, but the terminal verifier
returned false after the basic blockers were clear. The task id includes
`user_abroad_roaming_disabled_off`; tau2 source confirms that this requires both account-side
`enable_roaming` and phone-side `turn_roaming_on`/`toggle_roaming`. Therefore the correct next
agent-only candidate is conditional roaming recovery after a failed terminal MMS check, not Wi-Fi
calling or app-permission branching.

Conditional roaming-recovery scaffold: `telecom-mms-roaming-recovery-v1` opens a roaming phase only
after `can_send_mms` fails with the basic MMS blockers clear. It asks the assistant to repair
account-side roaming if line details show `roaming_enabled=false`, ask the user for one phone-side
roaming action if Data Roaming is off, then rerun one terminal `can_send_mms` verifier. The gate was
also adjusted so an early `can_send_mms=false` after basic blockers is recoverable if a later
`can_send_mms=true` appears.

First live result: `telecom-mms-roaming-recovery-v1` stayed `REJECT_SURROGATE`. This did not falsify
the roaming recovery phase; the run never reached it. Without a user-side guard, the simulated user
again refused the initial bundle and forced one-step remediation. The run stopped at `toggle_data`
before network mode/APN/terminal MMS. This establishes the current blocker: **native tau2 user-sim
friction prevents an agent-only bundle policy from compressing the loop on this task.** The next
design should either (a) target a smaller native-user phase protocol that the user simulator accepts
without refusing bundles, or (b) move step-economy measurement to an evaluator route that explicitly
supports bounded bundles and clearly label it as route-diagnostic evidence.

Native-user phased recovery result: `telecom-mms-phased-recovery-v1` asked for smaller phases rather
than one large bundle. It reduced tool spend (4 calls) and wall time, but it did **not** compress the
conversation enough: the native user still forced individual steps (`check_network_status` →
`toggle_airplane_mode` → `reseat_sim_card` → pending `toggle_data`) and maxed out before terminal MMS.
This confirms that "smaller phase" alone is not enough.

Roaming-recovery diagnostic result with bounded user route: the user route reached terminal
`can_send_mms=false`, then the agent inspected `get_details_by_id` for both lines and `get_data_usage`.
The active line details showed `roaming_enabled=false`, but the assistant still branched to Wi-Fi
calling checks instead of calling `enable_roaming` and asking for phone-side roaming. Therefore the
next useful change is **not another prompt-only scaffold**. It is a hard ordering gate in the GEODE
main loop or tau2 runner: when `mms_failed_after_prereqs=true` and active line
`roaming_enabled=false`, Wi-Fi/app-permission/escalation branches are blocked until `enable_roaming`
has been attempted and phone-side Data Roaming has been turned on or explicitly ruled out.

Subscription-usage exhaustion discriminator:

- OpenAI subscription routes do not currently expose a reliable local remaining-usage meter. Do not
  infer quota health from local token counters alone, and do not claim that a run had available quota
  merely because it produced text.
- Treat a run as likely subscription/route exhaustion only when at least one hard evidence channel
  fires: new `codex-oauth-empty-text/*.json` diagnostics, adapter exception propagation,
  `infrastructure_error` termination, or rate-limit/quota/empty-output text injected into the tau2
  transcript.
- The 2026-07-06 mainverify/workfloworder/step-economy/userguard/bounded-bundle/roaming-recovery/
  phased-recovery cheap probes do **not** show those exhaustion signatures: terminations are
  `max_steps`, GEODE raw turn terminations are `natural`, no new empty-output dumps appeared after
  07:54:57 KST, and transcript string hits for `billing`, `usage`, and `429` were false positives
  from telecom policy text or timestamps. Interpret them as behavioral `max_steps` failures unless a
  new evidence channel appears.

| Readiness item | Pass condition | If it fails |
|---|---|---|
| Codex subscription response | No `codex-oauth: empty output_text` event anywhere in agent, user, or reflection calls | Adapter hard-fails under runner env; fix codex-oauth empty-output recovery before measuring candidate quality |
| Adapter exception propagation | Adapter failures propagate out of AgenticLoop instead of retrying | Runner sets `GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR=1` for benchmark runs |
| Codex state replay | Prior `response.output` items are replayed before lossy assistant-message reconstruction | Adapter captures `codex_output_items`; runner keeps output replay enabled by default |
| tau2 task retries | Infrastructure failure is not retried as if it were stochastic task failure | Runner defaults `--max-retries 0` |
| GEODE visible text / tool action | Every final GEODE turn has visible text or a projected tau2 tool call | Runner hard-fails; do not synthesize fallback benchmark messages |
| Action-before-talk quality | On action-requiring tau2 tasks, at least one projected environment tool call appears before the conversation reaches manual checklist loops | Runtime verifier retries under tau2 env; offline surrogate rejects as low-action behavior even if message count is low |
| Hidden reflection calls | Cognitive reflection disabled unless explicitly debugging | Do not let hidden quota spend or swallowed reflection exceptions affect benchmark runs |
| Diagnostics backstop | No new `codex-oauth-empty-text/*.json` dump appears during a run | Runner snapshots first, then aborts as infrastructure evidence |
| Checkpoint integrity | `results.json` records at least one completed simulation | Do not snapshot or score |
| Contamination filter | No rate-limit text injected into conversation messages | Stop; classify as infrastructure |
| Guard provenance | `geode_agent_guard` appears in raw message metadata for candidate runs | Stop; candidate was not in the causal path |

Trajectory snapshot naming is fixed before live G2:

```text
run_id:
  crucible-tau2-<stage>-<domain>-<arm>-<guard>-<agent_route>-<user_route>-n<tasks>k<trials>-<yyyymmdd>-<seq>

files:
  artifacts/eval/runs/crucible/trajectory-snapshots/<run-id>.trajectory.json
  artifacts/eval/runs/crucible/trajectory-snapshots/<run-id>.snapshot.json
```

Where `stage` is `g2`, `g3a`, `g3b`, or `g3c`; `arm` is `baseline` or
`candidate`; `guard` is `none`, `r1`, or `t1`; and route fields must encode
provider, source, model, and reasoning effort. The raw tau2 result directory remains
`artifacts/eval/harnesses/tau2-bench/data/simulations/<run-id>/results.json`. The snapshot file is a
copy of that raw trajectory; the metadata file records guard, route, task IDs, max steps, concurrency,
and argv. The runner implements this via `--trajectory-snapshot-dir` and writes snapshots automatically
when `--save-to` is provided.

GEODE loop cost posture:

- General GEODE already has cost controls for simple requests: decomposition skips clearly simple or
  non-compound inputs, tool definitions are deferred behind hosted tool search for large tool sets,
  cognitive reflection can be disabled, and convergence/no-progress guards break repeated failures.
- The tau2 runner is a different surface. It embeds GEODE's full `AgenticLoop` as both the assistant
  and simulated user participant. That means every tau2 turn can become an internal agentic loop
  unless the runner sets benchmark-specific budgets. The new `--agent-max-rounds` and
  `--user-max-rounds` flags make that budget explicit.
- The capped/no-defer probe shows the tradeoff: lower turn cost is easy; preserving benchmark-grade
  action quality is the hard part. For retail, the dominant failure is wrong final write payloads
  after many correct reads. For telecom, the dominant failure is not lack of conversation but missing
  workflow completion and terminal verification. Therefore Crucible should optimize **cost per
  correct environment action**, not raw message count.

### 5.4 External-Case Alignment — Feedback Signals And Iteration Shape

The current Crucible loop is aligned to the referenced systems only if each feedback signal has a
fixed owner and each iteration stage has a bounded budget:

| Reference pattern | What it optimizes | Crucible equivalent | Current status |
|---|---|---|---|
| AlphaEvolve / FunSearch | Candidate generation against automated evaluators; archive/selection keeps useful candidates | R1/T1 guard candidates, tau2 task-success evaluator, failure manifest/archive | Candidate/archive/evaluator split exists; route-readiness gate is now required before live evaluator spend |
| AutoTVM / Ansor / MetaSchedule | Large search spaces are narrowed by cost models and staged hardware measurement | G1 trace replay and G2 micro-sim before full tau2 | G1 exists and produced actionable verdicts: T1 pass, R1 conditional pass |
| Hyperband / multi-fidelity BO | Cheap low-fidelity trials reject candidates before high-fidelity trials | Failure manifest → G1 trace replay → G2 micro-sim → G3a targeted mini → G3b sequential → G3c full | Ladder exists; budget scheduler/value-of-information is still missing |
| SWE-agent / Agentless | Interface/localization/patch validation often dominates agentic complexity | Guard injection surface, raw trajectory snapshots, task-level paired validation | Guard injection and snapshot naming are implemented; live G2 blocked by product-route empty output |
| Physical AI / conformal uncertainty | Expensive real-world tests happen only after uncertainty and safety gates | Subscription tau2 is treated as an expensive live world; infra contamination is a veto | Readiness failure is a veto, not a low score |

Signal contract:

| Signal | Source | Use | Must not be used as |
|---|---|---|---|
| Failure cluster | `tmp/crucible_failure_manifest.json` | Candidate design and G1 support | Promotion evidence |
| G1 replay verdict | `tmp/crucible_g1_trace_replay.json` | Decide whether to spend G2 quota | Live performance score |
| Empty-output / rate-limit diagnostics | Codex diagnostics and transcript scan | Route readiness / infrastructure veto | Candidate regression |
| Paired flip/regression | Clean base-vs-candidate live trajectories | G3b/G3c candidate verdict | Cross-route average |
| Full tau2 pass rate | Same model/user route, clean full slice | Product-route promotion/public result | PAYG `gpt-5.2` comparator |

## 6. Next Development

| Milestone | Content |
|---|---|
| M2 | Isolate rate-limit conversation injection + normalized records in `plugins/benchmark_harness/records.py` + `gate.py` wiring for G3/G4/G6 |
| M2.5 | failure manifest schema + G1 trace replay runner + R1/T1 guard proposal scaffold (English prompt source text) |
| M3 | Campaign 1: evaluate retail R1 and telecom T1 as separate mutations through G0-G3a cheap gates |
| M4 | Budget scheduler (value of information) + archive/merge operation |
| M5 | Publish only candidates that pass full τ² G3c/G4/G5, with pass^k and revision in the ledger, hub, and docs |

Publication rule: every run is recorded in `site/src/data/geode/benchmark-measurements.ts` with
conditions and revision. Directional signals and confirmed promotion numbers must be labeled
separately.
