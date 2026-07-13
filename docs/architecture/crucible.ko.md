# Crucible — 개선을 불로 시험하는 게이트 루프

> [English](crucible.md) | **한국어**

> **2026-07-10 정정:** [`crucible-kernel.md`](crucible-kernel.md)의 frozen 3-class
> evidence contract가 아래의 G0-G7 캠페인 절차를 대체한다. 이 파일의 나머지는 실험·사건
> 기록으로 보존되며, candidate revision 간 row 이어붙이기, 노출된 held-out row에 대한
> 튜닝, diagnostic projector 병합을 허용하는 근거가 아니다. 아래에 언급되는 CLI candidate
> 이름은 과거 기록이며 더 이상 활성이 아니다.

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

## 3. Weakness Band -- 41개 실패 전수 진단

`results.json` 전수 분석, 2026-07-04 1차 판독 후 2026-07-06 재분류. 실패 모드는
"에이전트가 write를 안 했다"보다 좁다. retail은 **최종 mutating-tool 인자 선택 오류**가
지배하고, telecom은 **복합 트러블슈팅 워크플로 종료 전 터미널 상태 검증 누락**이 지배한다.

**retail 27건**: 25건이 DB reward 0이다. 상당수에서 에이전트는 툴을 호출했지만, 제출된
필드 중 하나(`order_id`, `item_ids`, `new_item_ids`, 주소, 결제 수단, 취소 사유)가
evaluator gold state와 어긋났다.

| 실패 군집 | 건수 | 처치 표면 |
|---|---:|---|
| 주소 변경 완결성 | 6 | 주소 소스 선택, `address2` 보존, 주문/프로필 동시 갱신 검증 |
| 배송 완료 반품 아이템 선택/환불 | 5 | 부분 반품 아이템 집합과 환불 수단 검증 |
| 배송 완료 교환 아이템 선택 | 4 | variant 선호/폴백의 교체 아이템 매핑 검증 |
| pending 아이템 수정/variant 선택 | 4 | pending 아이템 부분집합과 결제 수단 검증 |
| action-check 실패 없는 DB 불일치 | 4 | action check 밖의 DB-diff 사후조건 검증 |
| pending 주문 취소/주문 부분집합 | 3 | 취소 가능 주문 부분집합과 사유 정규화 검증 |
| 툴 스키마/런타임 에러 | 1 | `address2` 같은 필수 인자 보존 |

예: retail task 0은 `exchange_delivered_order_items`를 호출했지만, 사용자의 폴백 조건과
evaluator gold state에 맞지 않는 키보드 교체품을 선택해 DB reward 0이 됐다. 따라서 S1/S5의
"write를 하라" 처치는 부분적으로만 옳다. 1차 처치는 **mutating write 전 구조화된
commit-plan 검증**이다.

**telecom 14건**: 14건 전부 ENV_ASSERTION 실패다. 군집은 MMS 11, service 2, mobile_data 1.
누락 액션은 `grant_app_permission` 8, `toggle_roaming` 6, `enable_roaming` 5,
`reset_apn_settings` 2, `refuel_data` 1. 복합 이슈에서 에이전트는 앞선 원인 하나를 고친 뒤
남은 원인을 소진하기 전에 이관하거나 종료한다. MMS는 SMS/storage 권한, APN/MMSC, 데이터
사용량, 로밍이 상호작용할 때 특히 약하고, service 태스크는 APN 리셋, 요금 정지, SIM
재장착이 상호작용할 때 특히 약하다.

공통 패턴은 **액션 완결 규율의 부재**지만 도메인별 처치는 다르다. retail은 오기입 write
방지가, telecom은 워크플로 완결과 터미널 verifier가 필요하다. 실패 태스크 ID는
`tmp/tau2_failed_{retail,telecom}.txt`에 동결돼 있다.

## 4. 접근 -- Assay System

### 4.0 기본 개념 -- Verifier 중심 탐색 프로토콜

후보 생성이 저렴해지면 병목은 생성 능력이 아니라 **evaluator/verifier의 비용·처리량·
신뢰도**로 이동한다. Crucible의 핵심 질문은 "LLM 에이전트가 똑똑한가"가 아니다. 질문은
"이 도메인이 후보를 싸게 생성하고, 싸게 기각하고, 값비싼 검증을 그럴 자격이 있는 후보에만
쓸 수 있는가"다.

| 개념 | 의미 | Crucible 대응 |
|---|---|---|
| 탐색 공간 | prompt, policy, harness, 코드, 스케줄, kernel 튜닝 등 가능한 개선 후보의 전체 공간 | S1/S5/R1/T1 같은 변이 후보 |
| 반복 비용 | 후보 하나를 생성·검증하는 데 드는 시간·토큰·비용·사람 주의 | clop48 세그먼트 1회: ~175M 토큰, ~$837 |
| Verifier/evaluator | 후보가 행동을 개선했는지 판정하는 기계적 심판 | τ²-bench, paired task success |
| Cascade | 저렴한 평가에서 비싼 평가로 상승하는 구조 | G0 → G1 → G2 → G3a → G3b → G3c |
| Noisy verifier | 평가가 통계적으로 요동하거나 오염될 수 있음 | K=1 pass 노이즈, rate-limit 오염 |
| Paired 비교 | 같은 태스크에서 base와 candidate를 직접 비교 | flip/regression 중심 판정 |
| 조기 기각 | 승격은 못 하지만 나쁜 후보를 일찍 죽일 수 있는 장치 | `sequential_gate.py` |
| Champion chain | 검증된 최선 상태만 다음 baseline이 된다 | 게이트 통과 전 core 병합 없음 |
| Archive/memory | 미래 탐색을 위한 과거 후보·실패·성공 트레이스 풀 | 실패 군집, trace replay, handoff |
| Multi-fidelity | 정확하고 비싼 평가와 더 싸고 불완전한 평가를 계층화 | full τ²는 최종 법정, 앞 게이트는 reject 전용 |

### 4.1 원칙과 3개 신호 축

**판정이 자율보다 먼저다.** 루프의 수렴 속도와 정확성의 상한은 verifier의 강도와
처리량이다. 신호는 3개 축으로 분리하며 섞지 않는다:

| 축 | 출처 | 역할 |
|---|---|---|
| capability (1차 신호) | τ² train 서브셋의 결정론적 task-success | 최적화 대상 |
| safety (바닥) | Petri critical 축 + tool-contract PASS/FAIL | 집계 밖 거부권, 교환 불가 |
| cost (예산) | E1 mutation cost ledger | 상한 제약 |

### 4.2 게이트 사다리 v2 (비용 사다리 -- 기각 가속기 중심)

v1 설계에는 서류상 사다리가 있었지만, 첫 S5 사이클은 **값비싼 full급 paired τ² 실행에
너무 빨리 도달**했다. clop48 세그먼트 1회가 승격 0으로 ~175M 토큰과 ~$837를 소모했다.
verifier가 옵티마이저를 굶겼다. 병목은 변이 품질이 아니라 **제한 시약인 검증 처리량**
이었다. v2는 저렴한 기각을 앞에 배치해, 가망 없는 변이가 full 벤치마크에 도달하기 전에
죽게 한다.

```
G0 static reject   표면 밖, 중복, evidence_refs 누락, 과도하게 넓은 guard,
                   step-budget 위험, tool-contract 불일치, 기대 실패 모드 누락
                   -> 즉시 기각. 비용 0.
G1 trace replay    기존 실패 trajectory를 replay해 이 변이에 실제 개입 지점이
                   있는지만 묻는다. 개입 지점 = 0이면 기각. 비용 0, LLM 없음.
G2 micro-sim       실패 군집 대표 5-10 태스크, 낮은 max_step.
                   reject 전용, 승격 권한 없음. 분 단위.
G3a targeted mini  실패 군집 12-20 + 매칭된 클린 대조 8-12.
                   reject 전용. 저비용.
G3b sequential     full 후보 전용. discordant pair ~10개마다 flip/regression 갱신.
                   회귀 위험이 높으면 SPRT/Bayesian futility로 조기 중단. 중간 비용.
G3c full paired    승격 직전의 최종 법정. 공개 수치 경로, K=3 replicate. 고비용.
G4 held-out        telecom 서브셋 + MCPMark File 무회귀. 중간 비용.
G5 safety          Petri critical 회귀 엄격 기각 AND contract 거부권. 중간 비용.
G6 cost            $/task·레이턴시 예산 내. 기록 재사용.
G7 verdict         전부 통과 시 git chain에서 승격, 아니면 revert 또는 archive.
```

핵심 원칙: **저렴한 기각이 후보 대부분을 제거해야 하고, 비싼 벤치마크는 소수 생존자를
위한 것이며, full paired 평가는 승격 직전의 최종 법정이다.** 조기 중단은 **reject 전용**
이다. full 벤치마크 결과는 공개/승격 증거이므로, 중간 결과가 조기 승격으로 core에
들어가면 안 된다. 다만 중간 증거로 후보를 죽이는 것은 안전하다.

**G3b sequential 판정 (조기 중단 = 기각 가속기).** 처음부터 114×2를 돌리지 않는다.
discordant pair만 순차 관찰한다: flip = 개선 증거, regression = 회귀 증거. 갱신마다
Beta-Binomial posterior로 판정한다:
- **Hard reject**: discordant pair 12개 이상에서 regression >= flip + 4, 또는 held-out에서
  P(delta < -3pp) > 0.90, 또는 safety-floor 위반.
- **Futility stop**: 최종 +3pp 개선의 posterior 확률이 5% 미만.
- **Continue**: flip/regression 격차가 작고 표본이 부족.
S5 telecom은 flip 4 vs regression 12로 끝났으므로, 이 규칙이었다면 full 실행 전에 죽였을
것이다. `scripts/eval/sequential_gate.py`가 Beta(1,1) prior와 delta = s5_pass − base_pass로
이를 구현한다.

G3c는 집계 점수가 아니라 paired task flip을 검정하며, discordant pair에 대한 정확 단측
이항검정을 쓴다. G5는 v1의 "이진 신호는 평균에 섞지 않는다" 규칙을 게이트 사다리로 확장한
것이다.

### 4.3 외부 사례와 계보 -- 같은 경제학, 다른 verifier

시스템마다 네트워크와 도메인은 다르지만 구조는 같다: **후보 생성기는 저렴해지고,
verifier 처리량이 실험의 경제학을 지배한다.**

| 계열 | 사례 | 핵심 구조 | Crucible 해석 |
|---|---|---|---|
| LLM+evaluator 발견 | AlphaEvolve, FunSearch | LLM이 실행 가능한 코드/함수 후보를 생성하고, 자동 evaluator가 검증하며, 강한 후보만 archive/prompt 재료로 들어간다 | 핵심 자산은 mutator가 아니라 archive + evaluator + selection 루프다. full τ²를 기본 inner-loop evaluator로 쓰면 안 된다 |
| 컴파일러/커널 오토튜닝 | AutoTVM, Ansor, TVM MetaSchedule, Triton | 거대한 schedule/탐색 공간을 cost model, 진화 탐색, 단계적 측정으로 줄인다 | 반복 비용에 대한 반도체 쪽 표준 처방은 surrogate/cost-model/단계적 측정이다. τ²에는 full 실행 전에 trace replay, micro-sim, targeted 서브셋이 필요하다 |
| 칩 설계 자동화 | Google RL floorplanning/AlphaChip, NVIDIA ChipNeMo | PPA/EDA verifier를 갖춘 주변 루프(placement, EDA 스크립트, 버그 요약/분석)를 자동화한다 | core 행동을 먼저 변이시키는 것보다 harness/triage/스크립트 루프 자동화의 ROI가 높다. 프로덕션 가속기 플랫폼 에이전트 시스템에도 부합한다. |
| 소프트웨어 엔지니어링 에이전트 평가 | SWE-bench, SWE-agent, OpenHands, Agentless | 실제 이슈를 유닛 테스트나 패치 검증으로 확인한다. agent-computer interface와 localization이 성능을 지배한다 | 더 agentic하다고 항상 낫지 않다. 정확한 실패 위치 특정과 저렴한 패치 검증이 먼저다 |
| 반복 비용 이론 | Hyperband, multi-fidelity BO, sequential testing | 많은 후보에 작은 예산을 주고, 유망하거나 불확실한 후보에 더 큰 예산을 준다. 증거가 충분하면 고정 표본 크기 전에 중단한다 | `sequential_gate.py`는 옳은 방향이지만, 다음 빠진 조각은 후보 단위 value-of-information 예산 스케줄링이다 |
| Physical AI 불확실성 | Conformal prediction + SIL/HIL/실세계 cascade | 물리 평가는 비싸고 위험하므로, 불확실성이 높을 때만 사람/실세계 verifier를 부른다 | τ²도 비싼 세계다. 불확실한 후보만 full verifier에 도달해야 한다 |

출처(공개 1차 또는 준1차): AlphaEvolve DeepMind blog
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

요약: **Crucible은 "LLM 에이전트 자기개선"보다 좁고 실용적이다. noisy verifier 아래에서
엔지니어링 후보의 반복 비용을 줄이는 verifier 중심 탐색 프로토콜이다.**

| 기법 | 출처 계보 | 구현 |
|---|---|---|
| Trace 기반 변이 제안 | GEPA + SWE-bench/Agentless 교훈 | 실패 트레이스 분류 → 제안에 `evidence_refs` 필수 |
| 평가 cascade | AlphaEvolve/FunSearch + 컴파일러 오토튜닝 + Hyperband | 비용 0 게이트에서 시작, 생존 후보만 비싼 측정 |
| 동결 외부 held-out + 도메인 분할 | Agent-World (arXiv 2604.18292) | train=retail 서브셋 / held-out=telecom / airline=추세 전용 |
| (1+1)-ES trunk + 유한 archive | karpathy/autoresearch + DGM | 사이클당 변이 1개, 기각/부분 개선 후보 최대 N<=5 보존 |
| Slot-disjoint 병합 | GEPA crossover | 동일 게이트 통과 후에만 disjoint policy slot 병합 |
| Multi-fidelity 예산 | Hyperband + multi-fidelity BO | posterior value of information으로 G3a/G3b/G3c 예산 배분(미구현) |

**기각된 기법과 부활 조건**: multi-objective Pareto selection(v0.99 (1+lambda)+Tchebycheff
층, noisy judge 단일 축에서는 무효라 2026-05-29 PR-DROP-GROUP-SAMPLING으로 제거. 부활
조건: 클린 축 2개 이상), (1+lambda) 병렬 배치(부활 조건: 세대 단위 평가 병렬성), 도메인
특화 + router(부활 조건: retail/telecom 규칙의 실측 분화), MAP-Elites/QD(저렴한 결정론적
평가 도메인 전용).

**선택 구조**: 원본 karpathy/autoresearch 루프는 의도적으로 분기도 population도 없다:
3-파일 규율, 고정 5분 예산, 단일 metric, 그리고 git이 옵티마이저다. 가져온 철학: *통제
비교가 성립하는 한도 안에서 가장 단순한 옵티마이저를 쓴다. 영리함은 변이 제안에,
단순함은 판정 구조에 속한다.* 선택 복잡도는 실험 경제학의 종속 변수다. trunk는 선형
champion chain을 유지하고, 확장은 git-native archive/merge로 한정한다.

정직한 분류: 이 시스템은 제약되고 verifier로 보호되는 **stochastic hill climbing**이다.
순진한 hill climber와의 차이는 언덕이 진짜인지 먼저 검증하는 장치들이다: 가짜 언덕에는
노이즈 밴드 사전 측정, Goodhart 언덕에는 동결 held-out, 안전 절벽에는 floor 거부권, 정체
탈출에는 archive.

### 4.4 변이 표면

진입 기준: (1) 인과 근접성(실측 실패 모드가 슬롯에 대응), (2) 검출 가능성(기대 효과가
paired 검출 바닥 이상), (3) 자(ruler)와의 분리, (4) 평가 비용. §3 진단은 다음 표면에
대응한다:

| | 슬롯 | 증거 실패 모드 |
|---|---|---|
| S1 | Agent system-prompt 행동 완결 규칙 | 필수 write 액션 전 종료 |
| S2 | `tool_policy` JSON | 종료 전 pending-write 확인 누락 |
| S3 | Tool descriptions | mutating-tool 인자 오기입 |
| S4 | Decomposition policy | 복합 트러블슈팅의 체크리스트 소진 누락 |
| S5 | Evolve-block 코드: 결정론 종료 가드(Tier 1b, 2차) | 위 실패들에 대한 구조적 처치 |
| R1 | Retail commit-plan guard | 주문/아이템/주소/결제 write 오기입 |
| T1 | Telecom workflow-completion guard | 종료/이관 전 터미널 verifier 누락 |

제외: user simulator 프롬프트(비교 오염), 벤치마크 도메인 policy(변이 = 부정행위), 모든
태스크 선택/채점 표면(자 그 자체). 입도: 섹션/키 수준만. 크기: 게이트 처리량이 흡수할 수
있는 속도로만 변이 표면을 확장한다.

**프롬프트 언어 규칙.** 설계 근거는 한국어로 써도 되지만, system prompt·guard 텍스트·
policy 문구 등 모델 컨텍스트에 들어갈 수 있는 scaffold 텍스트는 영문 원문으로 기록해야
한다. 측정 대상 agent와 user simulator는 영어 벤치마크 환경에서 실행되므로, 한국어
프롬프트 텍스트를 중간 프롬프트 산출물로 남기지 않는다.

R1/T1 초안 scaffold 텍스트는 영문으로만 기록한다:

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
  (태스크당 flip 확률 ~20%, 준무효과 변이 기준 추정). 단일 pass^1 비교로는
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

### 5.1 첫 사이클 결론 -- 제한 시약 (2026-07-06)

첫 Crucible 사이클은 자기개선을 증명하지 못했다. 당시에는 승격 프로토콜을 검증하고
verifier 처리량이 제한 시약임을 드러낸 것으로 해석했다. 2026-07-10 contract 감사가 그
해석을 대체한다: candidate revision, evaluator 상태, held-out row가 함께 동결되지
않았으므로, 이 사이클은 단조성도 승격 프로토콜도 검증하지 못했다.

- 남은 유용한 것: 실행 가능한 실패, paired-run 진단, 차단된 병합, 그리고 이제
  train/incident 증거로 분류된 기각 트레이스.
- 실패한 것: 반복 비용이 너무 높았고(clop48 ~175M 토큰, ~$837), K=1 pass^1 노이즈로
  검출력이 낮았으며(~8pt 바닥), quota가 실험을 좌우했고, 저렴한 게이트의 변별력이
  부족했고, 변이 하나가 full 시뮬레이션을 과도하게 소모했다.
- 역사적 처방: §4.2 게이트 사다리 v2. 아래에는 활성 절차가 아니라 사건 기록으로
  보존한다. `crucible-kernel.md`가 frozen contract, 정규화된 증거, 단일 paired 판정으로
  이를 대체한다.

### 5.2 현 설계 평가 -- Keep, Revise, Hold

**회고적 정정.** S1/S5는 core에 들어가지 않았지만, 그 역사적 결과가 프로토콜이 옳았음을
증명하지 않는다. row 이어붙이기, evaluator 결합, 노출 태스크 재사용으로 false-promotion
위험이 측정되지 않은 채 남았다. 교환 불가 거부권 원칙은 살아남고, 옛 증거 주장은
살아남지 못한다.

**Revise.** 재분류된 실패는 S5의 "종료 전 write nudge"가 너무 넓음을 보여준다. retail의
지배 실패는 wrong-write이므로 R1 commit-plan guard가 필요하다. telecom은 T1
workflow-completion guard가 필요하다. 도메인 무관 행동 문장 하나로 두 실패 계열을 함께
줄이려는 시도의 한계는 M1/S5가 이미 보여줬다.

**Hold.** S5는 clop48 클린 서브셋에서 유망한 신호가 있지만(retail CONTINUE, telecom
PROMOTE_CAND), rate-limit 오염과 작은 표본 때문에 승격 자격이 없다. payg/native-user
재측정 또는 오염 태스크 재측정이 끝나기 전에는 최종 판정을 내리지 않는다.

**현 자원으로의 다음 루프.** full τ² 실행을 한 번 더 쓰기 전에, 기존 클린 실패 41건과
매칭된 pass 대조군으로 G1/G2를 강화한다.

1. **실패 manifest**: 각 실패에 `cluster`, `expected_write`, `actual_write`,
   `intervention_turn`, `candidate_guard`, `false_positive_risk`를 붙인다. 비용: 0.
2. **G1 trace replay**: R1/T1이 기존 transcript에 개입 지점이 있는지, 통과 트레이스에
   불필요하게 개입하는지 판정한다. LLM 호출 없음.
3. **G2 micro-sim**: 대표 태스크 5-10개만 낮은 max-step 예산으로 실행한다. reject 전용.
4. **G3a targeted mini**: 실패 군집 태스크 12-20개와 매칭된 클린 대조군 8-12개를
   실행한다. 여전히 승격 권한 없음.
5. **G3b/G3c**: full 후보만 sequential futility를 거쳐 full paired 평가에 도달한다. 공개
   수치는 여기서 시작한다.

평가: 설계 방향은 옳지만 **예산 스케줄러**와 **실패 manifest 스키마**가 아직 없다.
`sequential_gate.py`는 G3b 구성요소 하나일 뿐이다. 다음 병목은 G0부터 G3a까지 자동
운영하는 multi-fidelity scaffold다.

### 5.3 루프 실행 스펙과 예산

Crucible은 full tau2 스윕 반복이 아니라 단계적 평가 루프로 돌아야 한다. 루프는:

1. **Observe**: 실패/통과 트레이스를 수집하고, 실패 군집을 분류하고, 좁은 변이 표면
   하나를 고른다.
2. **Propose**: 도메인 특화 candidate guard 또는 harness 변경 하나를 생성한다. R1과 T1은
   분리 유지.
3. **Replay**: 기존 transcript와 매칭된 pass 대조군으로 후보를 검사한다. reject 전용.
4. **Micro-sim**: 낮은 step 예산으로 작은 live 슬라이스를 돌린다. reject 전용.
5. **Targeted mini**: 실패 군집과 클린 대조군에만 live 호출을 쓴다. 신호가 압도적이고
   사전 등록된 경우가 아니면 reject 전용.
6. **Sequential gate**: futility나 오염 시 조기 중단. 이 게이트 단독으로 승격하지 않는다.
7. **Full tau2**: 승격 권한. paired base-vs-candidate 비교, 동결 태스크 ID, ledger 규칙을
   쓴다.

| 단계 | 범위 | 승격 권한 | 예상 예산 |
|---|---|---:|---:|
| 실패 manifest | 클린 실패 41 + 매칭 pass 대조군 | 없음 | $0, 엔지니어 1-2시간 |
| G1 trace replay | 기존 transcript만 | 없음 | $0, 엔지니어 2-4시간 |
| G2 micro-sim | 태스크 5-10, 낮은 max-step, 단일 도메인 | 없음 | 구독 quota 소량 |
| G3a targeted mini | 군집 태스크 12-20 + 대조군 8-12 | 없음 | 구독 quota 중간 |
| G3b sequential | futility/continue까지 paired 태스크 증분 | 없음 | posterior value-of-information으로 상한 |
| G3c full | 사전 등록된 paired 도메인 슬라이스 | 있음 | 구독 quota 최대. G3b 생존 후에만 실행 |
| G4 held-out | G3c 후 미노출 태스크 슬라이스 | 있음(확증) | 도메인 의존. 승격 후보에만 실행 |

모델/경로 호환성은 측정 계약의 일부다:

| Lane | 현재 모델 지원 | Crucible에서의 용도 |
|---|---|---|
| OpenAI PAYG/API | `gpt-5.2`가 로컬 등록돼 있고 native-user 비교 lane이다 | billing이 가능할 때 동일 조건 tau2/native-user 확증에 사용 |
| Codex / ChatGPT 구독 | `gpt-5.5`가 로컬 라우팅의 지원/기본 Codex lane이다. OpenAI Codex 문서는 ChatGPT sign-in에서 `gpt-5.2`를 deprecated로 표기. 2026-07-06 live probe에서 `gpt-5.2`는 400, `gpt-5.5`는 OK | 현금 절약형 product-route 탐색 lane으로 사용. PAYG `gpt-5.2`와 평균 금지 |
| Anthropic 구독 | Claude 구독 모델은 별도 계열(`claude-sonnet-*`, `claude-opus-*`) | Claude 특화 후보 증거에만 사용. 동일 모델 증거로 비교 금지 |

함의: 구독은 현금 소모를 줄일 수 있지만 `gpt-5.2` PAYG tau2 트랙의 동일 모델 대체물이
아니다. 구독 run은 reject 전용 스크리닝과 정성 디버깅에 유용하다. 최종 승격은 baseline과
같은 model/user 경로를 쓰거나, 별도의 product-route 결과로 공표해야 한다.

**PAYG 없는 운영 모드(현재 루프).** PAYG를 제외하면 Crucible은 측정 계약을 약화하는
대신 재설정한다:

- baseline = `gpt-5.5` Codex/ChatGPT 구독 위의 현재 GEODE
- user 경로 = `gpt-5.5` Codex/ChatGPT 구독 위의 `geode_user`
- 판정 범위 = product-route 개선만. PAYG `gpt-5.2` 대비 주장 없음
- full tau2 = 여전히 승격 권한이나, 같은 구독 model/user 경로 안에서만
- 공표 문구 = "subscription product-route result". "tau2 leaderboard comparator" 아님

이 모드의 비용 0 입력은 `scripts/eval/build_failure_manifest.py`가 생성한다:
`tmp/crucible_failure_manifest.json`은 현재 실패 41건과 pass 대조군 187건을 R1/T1
candidate guard, expected write, 실제 write성 호출, 인자 diff, 미충족 environment
assertion, 개입 turn, false-positive 위험 메모와 함께 기록한다. 관측된 실패 군집: 주소
변경 완결성 10, 배송 완료 반품 선택/환불 6, 배송 완료 교환 선택 5, pending 주문 취소
부분집합 3, pending 아이템 수정 2, 툴 스키마/런타임 1, MMS 워크플로 완결 11, service
터미널 verifier 2, mobile-data 터미널 verifier 1.

G1 trace replay는 `scripts/eval/trace_replay_gate.py`가 생성한다:
`tmp/crucible_g1_trace_replay.json`의 현재 결과:

| Guard | G1 판정 | 실패 지지 | Pass 대조 차단율 | G2 조건 |
|---|---|---:|---:|---|
| R1 | `PASS_TO_G2_WITH_CONTROLS` | 24/27 = 0.889 | 4/87 = 0.046 | targeted mini 전에 대조 태스크 ID 2, 46, 64, 73을 G2에 포함 |
| T1 | `PASS_TO_G2` | 14/14 = 1.000 | 0/100 = 0.000 | G2 micro-sim으로 진행 |

따라서 당장의 구독 전용 live 지출은 full S5 재실행이 아니다. G2 micro-sim이다: T1 먼저,
그다음 차단된 대조군 4개를 canary로 포함한 R1.

G2가 구독 quota를 쓰기 전에 runner는 **route readiness hard gate**를 강제한다. 2026-07-06
의 T1 baseline micro-sim 시도
(`crucible-tau2-g2-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n2k1-20260706-a`)
는 Codex 구독 `empty output_text` completion 반복으로 중단됐다. 원시 tau2 `results.json`에
simulation이 0건이므로 이것은 성능 증거가 **아니다**. 인프라 증거다: product-route
evaluator/런타임이 G2에 준비되지 않았다. 진단 덤프:
`~/.geode/diagnostics/codex-oauth-empty-text/1783286103-gpt-5.5.json`부터
`1783286160-gpt-5.5.json`까지.

`plugins/benchmark_harness/tau2_geode_agent.py`는 이제 projected tau2 tool call이 없는 빈
visible GEODE turn을 기본적으로 인프라 실패로 취급한다. harness가 그 조건을 합성
user/assistant 메시지로 바꾸기 전에 raise한다. `--allow-empty-geode-turn`은 디버깅
전용이며, 채점되는 G2/G3 run에 쓰면 안 된다.

더 좁은 2026-07-06 readiness probe
(`crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-a`)
는 첫 hard gate가 불충분함을 보여줬다: Codex `empty output_text`가 내부
reflection/recovery 경로에서 발생했지만, 최종 turn은 visible 텍스트를 냈고 tau2는
`max_steps`로 완료됐다. 이것 역시 오염 증거이지 성능 증거가 아니다. runner는 이제
`GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT=1`을 기본 활성화해, codex-oauth adapter가 모든 빈 구독
응답에서 raise하게 한다. 또한 tau2 run 동안 AgenticLoop cognitive reflection을 기본
비활성화하고, `GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR=1`을 설정해 AgenticLoop이 같은 오염
프롬프트를 재시도하는 대신 adapter 실패를 전파하게 한다. OpenAI의 Responses 가이드는 수동
관리 multi-turn 상태에서 이전 `response.output` item을 다음 요청에 되돌려 넣으라고 하며,
특히 `store=false`의 reasoning/tool-use 흐름에서 그렇다. Codex adapter는 이제 그 공식
output item을 보존·replay한 뒤에야 구식 reasoning-item 재구성 경로로 폴백한다. 백스톱으로
runner는 run 후 `~/.geode/diagnostics/codex-oauth-empty-text/`를 스캔한다. 새 덤프가
있으면 trajectory snapshot 후 abort해 infra-failure 증거를 보존한다. runner는
`--max-retries`도 노출하고 기본값 0으로 둬, tau2가 같은 인프라 실패를 세 번 더 재시도하지
않게 한다. `--allow-empty-geode-turn`은 adapter 수준 fail-fast와 최종 turn 폴백 가드를
디버깅 전용으로 끈다. `--enable-cognitive-reflection`과 `--disable-codex-output-replay`는
이 벤치마크 경로에서 디버그 전용이다.

2026-07-06 readiness 상태: 구독 경로가 실제 telecom 태스크를 실행하기 전에
adapter-surface 수정 2건이 더 필요했다:

- replay되는 `response.output` item은 Codex 구독 input validator에 맞게 정리해야 한다:
  의미 payload와 id는 유지하되, 최상위 `status` 같은 반환 lifecycle 필드와
  `tool_search_call.content` 같은 `None` 필드는 제거한다.
- 빈 `output_text`는 응답에 tool call이 없을 때만 인프라 실패다. 정상적인 Responses
  tool-use turn은 `output_text=""`에 유효한 `function_call` item을 가질 수 있다.

이 수정들 후 strict readiness run이 인프라 오염 없이 완료됐다:
`crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-e`.
결과: simulation 1건 평가, reward 0.0, termination `max_steps`, trajectory snapshot 기록.
이것은 승격급 신호가 **아니지만**, 구독 경로가 이제 multi-turn tau2 tool call을 실행할 수
있음을 증명한다. 다음 병목은 Codex OAuth 전송이 아니라 telecom 워크플로 완결/종료다.

이전 probe들은 인프라 증거로만 남는다:

| Probe run | 경로 | 결과 | 해석 |
|---|---|---|---|
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-output-replay-a` | agent xhigh / user high | 400 `input[1].status` | 반환 output-item lifecycle 필드용 replay sanitizer 부재 |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-output-replay-b` | agent xhigh / user high | infra error, reasoning 전용 빈 텍스트 | strict gate 작동. tool/액션 미방출 |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-c` | agent high / user high | 유효한 `function_call`에 거짓 infra error | function-call 전용 turn 허용으로 수정 |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-d` | agent high / user high | 400 `tool_search_call.content` | 최상위 `None` replay 필드 제거로 수정 |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-e` | agent high / user high | 평가됨. `max_steps`, reward 0.0 | 경로 준비 완료. 워크플로 완결은 여전히 부족 |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-f` | agent xhigh / user high | infra error, 평가 0, exit 1 | strict gate 작동. 경로 미준비 |
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-none-openai-sub-gpt55-none-n1k1-20260706-a` | agent none / user none | infra error, 평가 0, exit 1 | effort를 낮춰도 backend 빈 출력 실패는 해소되지 않음 |

저렴한 종료 중심 telecom 루프 결과(같은 태스크, 같은 `gpt-5.5/high` 구독 경로):

| Probe run | Variant | 결과 | 해석 |
|---|---|---|---|
| `crucible-tau2-cheaploop-telecom-candidate-t1-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | T1 terminal-verifier 프롬프트 | 평가됨. `max_steps`, reward 0.0, 메시지 24 | trajectory 형상 악화: 조기 `can_send_mms`, 사용자 액션 번들 없음 |
| `crucible-tau2-cheaploop-telecom-candidate-t2-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-b` | agent step-economy 프롬프트 | 긴 히스토리 후 infra error | 성능 증거로 무효. 후반 Codex 빈 최종 답변 |
| `crucible-tau2-cheaploop-telecom-candidate-t3-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-c` | agent + user step-economy 프롬프트 | 평가됨. `max_steps`, reward 0.0, 메시지 36 | user 측 번들링은 나타났으나, 추가 트러블슈팅 분기를 열었다 |
| `crucible-tau2-cheaploop-telecom-candidate-planner-capped-nodefer-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | 결정론 planner 프롬프트 + `--agent-max-rounds 2 --user-max-rounds 2 --disable-tool-search-defer` | 평가됨. `max_steps`, reward 0.0, 메시지 15, projected tau2 tool call 0 | 비용은 제한됐지만 행동 품질이 붕괴: 루프가 벤치마크 툴로 행동하는 대신 수동 점검을 말로 진행 |

판정: 프롬프트 전용 telecom guard는 불충분하다. 다음 유효한 단계는 채점 G2도, 또 다른
프롬프트 전용 variant도 **아니다**. 루프에는 저렴한 결정론적 G2 surrogate가 필요하다:
trajectory를 읽고 blocker 순서나 step 예산을 위반하는 후보를 live τ² 지출 전에 기각하는
telecom workflow state machine이다. MMS/no-service 태스크에서 state machine은
airplane mode off -> SIM active -> mobile data on -> non-2G network -> APN/MMS 설정 유효 ->
`can_send_mms == true` 순서와, 각 체크포인트 도달의 max-turn 예산을 추적해야 한다.

`scripts/eval/telecom_workflow_gate.py`가 이제 그 reject 전용 surrogate를 구현한다. 하나
이상의 tau2 `results.json` 파일을 소비해 `tmp/crucible_telecom_workflow_gate.json`을 쓰고
다음을 방출한다:

| 입력 run | Surrogate 판정 | 사유 |
|---|---|---|
| baseline `...output-replay-e` | `REJECT_SURROGATE` | `max_steps`, 터미널 `can_send_mms == true` 부재 |
| T1 `...cheaploop...t1...20260706-a` | `REJECT_SURROGATE` | 조기 `can_send_mms`, `max_steps`, 터미널 성공 부재 |
| T2 `...cheaploop...t2...20260706-b` | `INVALID_INFRA` | Codex 빈 출력 인프라 실패 |
| T3 `...cheaploop...t3...20260706-c` | `REJECT_SURROGATE` | 조기 `can_send_mms`, `max_steps`, 메시지/tool-call 예산 초과, 터미널 성공 부재 |
| planner capped/no-defer `...planner-capped-nodefer...20260706-a` | `REJECT_SURROGATE` | `max_steps`, 수동 체크리스트 전 액션 부재, 터미널 성공 부재 |

이것이 다음 pre-live 게이트가 된다: telecom 후보는 paired G2 지출 전에 replay 또는 소형
probe trajectory에서 이 surrogate를 통과해야 한다.

Planner 후보 scaffold (zero-live):

- `scripts/eval/telecom_action_planner.py`는 결정론적 MMS blocker planner를 정의한다.
  `airplane_mode_on=True`, `sim_active=False`, `mobile_data_on=False`, `network_type=2G`,
  APN/MMSC 누락이 주어지면 하나의 유한 안전 번들을 방출한다:
  `toggle_airplane_mode`, `reseat_sim_card`, `toggle_data`, `set_network_mode_preference`,
  `reset_apn_settings`, `reboot_device`, `check_apn_settings`.
- `can_send_mms`는 blocker 해소가 확인된 후에만 방출한다.
- 데모 출력: `tmp/crucible_telecom_action_plan.json`.
- 합성 trajectory: `tmp/crucible_telecom_action_plan.synthetic_results.json`.
- Surrogate 결과: `PASS_SURROGATE [mms_issue]synthetic_planner_success messages=14 calls=8`.

이것은 live 개선을 증명하지 **않는다**. 다음 후보 형상이 runner나 프롬프트 표면에 배선된
뒤 소형 live probe를 시도할 만큼 정합적임을 증명할 뿐이다.

Live planner 배선 결과 (2026-07-06): `--agent-planner telecom-mms-v1`이 이제 같은 결정론적
액션 시퀀스를 tau2 agent 프롬프트에 주입한다. runner는 벤치마크 전용 비용 제어 2종도
노출한다: 참가자별 GEODE loop round 상한(`--agent-max-rounds`, `--user-max-rounds`)과
`--disable-tool-search-defer`. capped/no-defer probe는 대화를 메시지 15개로 줄이고 hosted
`tool_search_call` 오버헤드를 제거했지만, **projected tau2 tool call 0건**도 함께 만들었다.
유용한 음성 결과다: 단순한 "짧은 turn" 압박은 그 자체로 유효한 최적화 대상이 아니다. 다음
후보는 비용 제어를 액션 품질 전제조건과 결합해야 한다: 사용자 신원 확보 후 에이전트는
수동 폰 점검을 요청하기 전에 tau2 툴로 backend 상태를 조회해야 하고, 모든 cheaploop
probe는 행동 증거로 인정받으려면 projected environment action을 최소 1건 요구해야 한다.

Action-before-talk 게이트가 이제 `telecom_workflow_gate.py`에 구현됐다: projected tau2
environment tool call이 먼저 나타나지 않으면 assistant의 수동 폰 체크리스트 루프를
기각한다. capped/no-defer probe를 replay하면 이제 `missing_action_before_manual_checklist`
가 나오며, 메시지 15/액션 0 trajectory를 효율적 후보가 아니라 저액션 기각으로 올바르게
분류한다.

Main-loop 정렬 (2026-07-06): action-before-talk 요구가 이제 오프라인 trajectory surrogate
만이 아니라 GEODE 런타임 verifier에도 존재한다. `core.agent.verify`는 opt-in
`GEODE_VERIFY_ACTION_BEFORE_TALK=1` knob을 받아, tau2식 폰/네트워크 체크리스트가 해당
turn에 tool call 없이 나타나면 재시도 가능한 `manual_checklist_without_action` miss를
방출한다. `plugins/benchmark_harness/tau2_geode_agent.py`는 벤치마크 run에서 이를 기본
활성화하고 snapshot metadata에 기록한다. 결정론적 `telecom_action_planner.py`는 후보
형상의 scaffold/fixture 생성기로 남으며, 행동 권위가 아니다. 실제 후보는 GEODE loop의
prompt, policy, verify, tool-execution 표면으로 표현해야 한다.

Live main-loop-alignment probes (2026-07-06):

| Run | 표면 | 판정 | 핵심 신호 |
|---|---|---|---|
| `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-mainverify-a` | baseline + main-loop action-before-talk verifier | `REJECT_SURROGATE` | 경로 준비 완료: tool call 7, 인프라 오염 없음, snapshot 기록. 여전히 `max_steps`, 조기 `can_send_mms`, 터미널 성공 없음 |
| `crucible-tau2-cheaploop-telecom-candidate-t1-mainverify-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | T1 guard + main-loop action-before-talk verifier | `REJECT_SURROGATE` | baseline과 같은 호출 순서: 계정 read → 조기 `can_send_mms` → `check_network_status` → `toggle_airplane_mode`. T1 프롬프트 guard는 워크플로 순서를 고치지 못했다 |
| `crucible-tau2-cheaploop-telecom-candidate-workfloworder-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | workflow-order 동적 scaffold | `REJECT_SURROGATE` | 순서 개선: `premature_can_send_mms` 없음. 호출은 계정 read → `check_network_status` → `toggle_airplane_mode` → `check_network_status` → `reseat_sim_card`. 여전히 `max_steps`, 터미널 성공 없음 |
| `crucible-tau2-cheaploop-telecom-candidate-stepeconomy-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | workflow-order + step-economy scaffold | `REJECT_SURROGATE` | infra/usage 소진 증거 없음. 소폭의 경제성 개선(메시지 24→23, 호출 7→6)이나 user simulator는 여전히 한 번에 한 액션을 고집. 여전히 `max_steps`, 터미널 성공 없음 |
| `crucible-tau2-cheaploop-telecom-diagnostic-stepeconomy-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | step-economy scaffold + user 측 번들링 guard | `REJECT_SURROGATE` | 진단 전용: user 측 결합으로 큰 번들 액션이 가능해졌으나, 메시지 36 / 호출 21로 과교정되고 조기 `can_send_mms`, 메시지/tool 예산 초과 |
| `crucible-tau2-cheaploop-telecom-candidate-boundedbundle-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | bounded-bundle workflow scaffold | `REJECT_SURROGATE` | usage 소진 증거 없음. 조기 터미널 verifier 없음, 메시지 24 / 호출 7, multi-tool user turn 2회. user는 여전히 초기 번들을 거부했고, run은 network/APN 수리와 터미널 `can_send_mms` 전에 종료 |
| `crucible-tau2-cheaploop-telecom-diagnostic-boundedbundle-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | bounded-bundle scaffold + bounded user guard | `REJECT_SURROGATE` | 진단 전용: user 측 번들링이 기본 전제조건과 터미널 `can_send_mms`에 도달했으나, roaming이 여전히 비활성이라 MMS는 false 유지. 메시지 32 / 호출 15, usage 소진 증거 없음 |
| `crucible-tau2-cheaploop-telecom-candidate-roamingrecovery-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | 조건부 roaming-recovery scaffold | `REJECT_SURROGATE` | agent-route 전용 후보는 roaming recovery에 도달하지 못했다. user simulator가 또 초기 번들을 거부했고, run은 터미널 MMS 전 `toggle_data`에서 멈췄다. 메시지 24 / 호출 7, usage 소진 증거 없음 |
| `crucible-tau2-cheaploop-telecom-candidate-phasedrecovery-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | native-user phased recovery scaffold | `REJECT_SURROGATE` | agent-route 전용 후보가 지출을 줄였으나(메시지 21 / 호출 4) 여전히 한 번에 한 액션. `toggle_data`에서 멈춤, 터미널 MMS 없음. usage 소진 증거 없음 |
| `crucible-tau2-cheaploop-telecom-diagnostic-roamingrecovery-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a` | roaming recovery + bounded user guard | `REJECT_SURROGATE` | 진단 전용: 터미널 `can_send_mms=false`에 도달한 뒤 line 상세와 data usage를 조회했으나, `roaming_enabled=false` 수리 대신 여전히 Wi-Fi calling으로 분기. 메시지 31 / 호출 15, usage 소진 증거 없음 |

결론: action projection은 더 이상 당면 blocker가 아니다. T1 프롬프트 전용은 여전히
blocker 해소 전에 터미널 verifier를 소모하고, workflow-order scaffold는 그 실패 클래스를
제거하지만 여전히 `max_steps`에 걸린다. 이 상태에서 채점 G2를 돌리지 **말 것**. MMS에서
`can_send_mms`는 network status, airplane mode, SIM, mobile data/network mode, APN/MMSC
blocker가 해소되거나 명시적으로 배제될 때까지 미뤄지는 터미널 verifier로 남아야 하며,
다음 후보는 step 수도 줄여야 한다.

Workflow-order scaffold (zero-live 구현, 다음 저렴한 probe 준비 완료):

- `plugins/benchmark_harness/tau2_workflow_order.py`는 `TelecomMmsWorkflowOrder`를 정의한다.
  tau2 telecom tool 출력을 소비해, GEODE assistant turn마다 간결한 영문
  `<crucible_workflow_order>` dynamic context 블록을 렌더링하는 상태 기반 blocker
  추적기다.
- `plugins/benchmark_harness/tau2_geode_agent.py`는
  `--agent-workflow-order telecom-mms-v1`,
  `--agent-workflow-order telecom-mms-step-economy-v1`,
  `--agent-workflow-order telecom-mms-bounded-bundle-v1`을 노출한다. 이들은 후보 표면이지,
  별도의 planner도 승격 권한도 아니다. 행동을 GEODE main loop 안(prompt/context →
  tool-use → trajectory 증거)에 유지한다.
- Snapshot metadata는 `agent_workflow_order`를 기록하고, raw assistant metadata는
  `geode_workflow_order`와 `geode_premature_terminal_tools`를 기록해, 조기 터미널
  verifier 호출을 오프라인 surrogate 실행 전에도 감사할 수 있게 한다.
- 다음 live 명령 형상:
  `--agent-workflow-order telecom-mms-v1 --trajectory-stage cheaploop --trajectory-arm candidate`.
  통과 조건은 여전히 `telecom_workflow_gate.py == PASS_SURROGATE`이며, 아니면 채점 G2
  없이 기각한다.

첫 live 결과: workflow-order scaffold는 조기 터미널 verifier 실패 클래스를 고쳤지만,
루프가 blocker를 한 번에 하나씩 해소해 trajectory는 여전히 `max_steps`로 기각됐다. 다음
저렴한 후보는 워크플로 순서를 유지하면서 **동시에** step 경제성을 개선해야 한다:
`check_network_status`가 복수 blocker를 보여주면, tau2 policy/user simulator가 허용하는
범위에서 안전한 폰 액션을 번들로 묶고(`toggle_airplane_mode`, 이어서
SIM/data/network/APN 교정), 그 후에야 터미널 verifier 호출을 다시 소모한다.

Step-economy scaffold (zero-live 구현): `telecom-mms-step-economy-v1`은 같은 상태 추적기에
명시적 번들 권고를 더한다. blocker가 해소될 때까지 `can_send_mms`를 번들 밖에 두되, 진단
결과 하나가 이미 복수 blocker를 드러냈다면 user simulator에게 안전한 전제조건 액션을 순서
있는 한 응답으로 수행하도록 요청한다. 다음 live 명령 형상:
`--agent-workflow-order telecom-mms-step-economy-v1 --trajectory-stage cheaploop --trajectory-arm candidate`.

첫 live 결과: `telecom-mms-step-economy-v1`은 surrogate를 통과하지 못했다. 터미널 verifier
규율을 유지했고 구독 소진도 보이지 않았지만, user simulator가 "one step at a time"으로
응답하며 폰 액션을 쪼갰다. agent 측 dynamic context만으로는 `max_steps` 병목을 제거하기에
부족하다는 뜻이다. 다음 진단은 **user 측 결합 probe**
(`--user-prompt-append-file scripts/eval/telecom_user_step_economy_guard.md`)로, agent
policy 실패와 시뮬레이션 user의 step-economy 마찰을 구분한다. user simulator를 바꾸면
evaluator 경로가 바뀌므로, 이것은 승격 증거가 아니라 측정 진단으로 취급한다.

User 측 결합 진단 결과: guard는 시뮬레이션 user가 폰 액션을 번들로 수행할 수 있음을
확인했지만, 자유 형식 번들링은 너무 느슨하다. tool call 21회를 실행해 메시지/tool 예산을
초과했고, surrogate가 blocker 해소로 판단하기 전에 `can_send_mms`가 나타났다. 다음 유효한
scaffold는 또 다른 자유 형식 프롬프트가 아니다. **bounded bundle protocol**이어야 한다:
명시적 allowlist를 갖고 `can_send_mms`를 제외한 전제조건 번들 1회, 그다음 통합 상태 보고
1회, 그리고 추적된 blocker가 해소된 경우에만 별도의 터미널 verifier.

Bounded-bundle scaffold (zero-live 구현): `telecom-mms-bounded-bundle-v1`은 workflow-order
와 step-economy 상태 추적기를 유지하되, 번들 언어를 allowlist된 전제조건 번들 하나로
좁힌다. 이전 tool 증거가 해당 분기를 도입하지 않는 한 `can_send_mms`, roaming, Wi-Fi
calling, 앱 권한, 에스컬레이션, 반복 광역 진단을 명시적으로 제외한다. 다음 저렴한 명령
형상:
`--agent-workflow-order telecom-mms-bounded-bundle-v1 --trajectory-stage cheaploop --trajectory-arm candidate`.
이것은 reject 전용으로 남는다. 결정론적 telecom workflow gate가 `PASS_SURROGATE`를
반환할 때까지 채점 G2는 차단 유지.

첫 live 결과: `telecom-mms-bounded-bundle-v1`은 `REJECT_SURROGATE`로 남았다. 경로에 usage
소진 징후는 없었다: 기존 07:54:57 KST 파일 이후 새 `codex-oauth-empty-text` 덤프 없음,
adapter 예외 전파 없음, transcript에 실제 quota/rate-limit 텍스트 없음. 행동 신호는 더
깨끗하다: 터미널 verifier 규율은 유지됐지만, 시뮬레이션 user가 첫 multi-action 번들을
거부한 뒤 작은 번들만 수행했고(`check_network_status` + `toggle_airplane_mode` +
`check_network_status`, 이어 `reseat_sim_card` + `check_sim_status`), run은 `max_steps`에
걸렸다. 게이트 출력:
`tmp/crucible_telecom_workflow_gate_boundedbundle_a.json` → 메시지 24, 호출 7,
`multi_tool_user_turns=2`, `non_2g_network=false`, `apn_valid=false`, `mms_verified=false`.

다음 유효한 진단:
`--user-prompt-append-file scripts/eval/telecom_user_bounded_bundle_guard.md`로 하는
bounded user 측 결합. user 경로를 바꾸므로 승격 증거가 아니라 측정 진단으로 남는다.
목적은 "agent가 올바른 번들을 구성하지 못한다"와 "tau2 시뮬레이션 user가 user 측
evaluator를 명시적으로 스코프하지 않으면 번들된 폰 액션을 거부한다"를 분리하는 것이다.
agent-route 전용 후보가 surrogate를 통과할 때까지 채점 G2를 돌리지 않는다.

Bounded user 측 진단 결과: `telecom_user_bounded_bundle_guard.md`는 evaluator가 bounded
전제조건 번들을 실행할 수 있음을 확인했다. `can_send_mms`에 도달했지만, 기본 blocker
해소 후에도 터미널 verifier가 false를 반환했다. task id에
`user_abroad_roaming_disabled_off`가 포함되며, tau2 소스는 이것이 계정 측
`enable_roaming`과 폰 측 `turn_roaming_on`/`toggle_roaming`을 모두 요구함을 확인해준다.
따라서 올바른 다음 agent 전용 후보는 Wi-Fi calling이나 앱 권한 분기가 아니라, 터미널 MMS
체크 실패 후의 조건부 roaming recovery다.

조건부 roaming-recovery scaffold: `telecom-mms-roaming-recovery-v1`은 기본 MMS blocker가
해소된 상태에서 `can_send_mms`가 실패한 후에만 roaming phase를 연다. line 상세가
`roaming_enabled=false`를 보이면 계정 측 roaming을 수리하고, Data Roaming이 꺼져 있으면
폰 측 roaming 액션 1회를 사용자에게 요청한 뒤, 터미널 `can_send_mms` verifier를 1회
재실행하도록 assistant에 요청한다. 게이트도 조정해, 기본 blocker 해소 후의 이른
`can_send_mms=false`는 이후 `can_send_mms=true`가 나타나면 회복 가능하게 했다.

첫 live 결과: `telecom-mms-roaming-recovery-v1`은 `REJECT_SURROGATE`로 남았다. 이것이
roaming recovery phase를 반증한 것은 아니다. run이 거기 도달하지 못했다. user 측 guard
없이 시뮬레이션 user가 또 초기 번들을 거부하고 one-step 교정을 강제했다. run은 network
mode/APN/터미널 MMS 전 `toggle_data`에서 멈췄다. 이것으로 현재 blocker가 확정된다:
**native tau2 user-sim 마찰이 이 태스크에서 agent 전용 번들 policy의 루프 압축을
막는다.** 다음 설계는 (a) user simulator가 번들을 거부하지 않고 받아들이는 더 작은
native-user phase protocol을 겨냥하거나, (b) step-economy 측정을 bounded 번들을 명시
지원하는 evaluator 경로로 옮기고 route-diagnostic 증거로 명확히 라벨링해야 한다.

Native-user phased recovery 결과: `telecom-mms-phased-recovery-v1`은 큰 번들 하나 대신 더
작은 phase들을 요청했다. tool 지출(호출 4)과 실행 시간을 줄였지만, 대화를 충분히
압축하지는 **못했다**: native user는 여전히 개별 step을 강제했고(`check_network_status` →
`toggle_airplane_mode` → `reseat_sim_card` → pending `toggle_data`), 터미널 MMS 전에
max out됐다. "더 작은 phase"만으로는 부족함이 확인된다.

Bounded user 경로의 roaming-recovery 진단 결과: user 경로는 터미널 `can_send_mms=false`에
도달했고, agent는 두 line의 `get_details_by_id`와 `get_data_usage`를 조회했다. 활성 line
상세가 `roaming_enabled=false`를 보였는데도 assistant는 `enable_roaming` 호출과 폰 측
roaming 요청 대신 Wi-Fi calling 점검으로 분기했다. 따라서 다음 유용한 변경은 **또 다른
프롬프트 전용 scaffold가 아니다**. GEODE main loop 또는 tau2 runner의 hard ordering
gate다: `mms_failed_after_prereqs=true`이고 활성 line `roaming_enabled=false`일 때,
`enable_roaming` 시도와 폰 측 Data Roaming 활성화(또는 명시적 배제)가 이뤄지기 전까지
Wi-Fi/앱 권한/에스컬레이션 분기를 차단한다.

구독 usage 소진 판별기:

- OpenAI 구독 경로는 현재 신뢰할 만한 로컬 잔여 usage 미터를 노출하지 않는다. 로컬 토큰
  카운터만으로 quota 상태를 추정하지 말고, 텍스트를 냈다는 이유만으로 run에 quota 여유가
  있었다고 주장하지 말 것.
- 다음 hard evidence 채널 중 하나 이상이 발화할 때만 run을 구독/경로 소진 가능성으로
  취급한다: 새 `codex-oauth-empty-text/*.json` 진단, adapter 예외 전파,
  `infrastructure_error` 종료, tau2 transcript에 주입된 rate-limit/quota/빈 출력 텍스트.
- 2026-07-06의 mainverify/workfloworder/step-economy/userguard/bounded-bundle/
  roaming-recovery/phased-recovery 저렴 probe들은 그 소진 서명을 보이지 **않는다**: 종료는
  `max_steps`, GEODE raw turn 종료는 `natural`, 07:54:57 KST 이후 새 빈 출력 덤프 없음,
  transcript의 `billing`·`usage`·`429` 문자열 히트는 telecom policy 텍스트나 타임스탬프의
  거짓 양성이었다. 새 증거 채널이 나타나지 않는 한 행동적 `max_steps` 실패로 해석한다.

| Readiness 항목 | 통과 조건 | 실패 시 |
|---|---|---|
| Codex 구독 응답 | agent/user/reflection 어느 호출에도 `codex-oauth: empty output_text` 이벤트 없음 | runner env에서 adapter hard-fail. 후보 품질 측정 전에 codex-oauth 빈 출력 복구를 수정 |
| Adapter 예외 전파 | adapter 실패가 재시도 대신 AgenticLoop 밖으로 전파 | runner가 벤치마크 run에 `GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR=1` 설정 |
| Codex state replay | 손실 있는 assistant-message 재구성 전에 이전 `response.output` item을 replay | adapter가 `codex_output_items`를 캡처. runner는 output replay를 기본 유지 |
| tau2 태스크 재시도 | 인프라 실패를 확률적 태스크 실패처럼 재시도하지 않음 | runner 기본 `--max-retries 0` |
| GEODE visible 텍스트 / tool 액션 | 모든 최종 GEODE turn에 visible 텍스트 또는 projected tau2 tool call 존재 | runner hard-fail. 폴백 벤치마크 메시지 합성 금지 |
| Action-before-talk 품질 | 액션 요구 tau2 태스크에서, 대화가 수동 체크리스트 루프에 도달하기 전에 projected environment tool call 최소 1건 | 런타임 verifier가 tau2 env에서 재시도. 오프라인 surrogate는 메시지 수가 적어도 저액션 행동으로 기각 |
| 숨은 reflection 호출 | 명시적 디버깅이 아니면 cognitive reflection 비활성 | 숨은 quota 지출이나 삼켜진 reflection 예외가 벤치마크 run에 영향을 주지 않게 한다 |
| 진단 백스톱 | run 중 새 `codex-oauth-empty-text/*.json` 덤프 없음 | runner는 snapshot 먼저, 그다음 인프라 증거로 abort |
| Checkpoint 무결성 | `results.json`에 완료된 simulation 최소 1건 | snapshot·채점 금지 |
| 오염 필터 | 대화 메시지에 rate-limit 텍스트 주입 없음 | 중단. 인프라로 분류 |
| Guard provenance | candidate run의 raw message metadata에 `geode_agent_guard` 존재 | 중단. 후보가 인과 경로에 없었음 |

Trajectory snapshot 명명은 live G2 전에 고정된다:

```text
run_id:
  crucible-tau2-<stage>-<domain>-<arm>-<guard>-<agent_route>-<user_route>-n<tasks>k<trials>-<yyyymmdd>-<seq>

files:
  artifacts/eval/runs/crucible/trajectory-snapshots/<run-id>.trajectory.json
  artifacts/eval/runs/crucible/trajectory-snapshots/<run-id>.snapshot.json
```

여기서 `stage`는 `g2`, `g3a`, `g3b`, `g3c`, `arm`은 `baseline` 또는 `candidate`,
`guard`는 `none`, `r1`, `t1`이며, route 필드는 provider·source·model·reasoning effort를
인코딩해야 한다. 원시 tau2 결과 디렉토리는
`artifacts/eval/harnesses/tau2-bench/data/simulations/<run-id>/results.json`으로 유지된다.
snapshot 파일은 그 raw trajectory의 사본이고, metadata 파일은 guard, route, 태스크 ID,
max steps, concurrency, argv를 기록한다. runner는 `--trajectory-snapshot-dir`로 이를
구현하고, `--save-to`가 주어지면 자동으로 snapshot을 쓴다.

GEODE loop 비용 자세:

- 일반 GEODE에는 단순 요청용 비용 제어가 이미 있다: decomposition은 명백히 단순하거나
  비복합인 입력을 건너뛰고, 큰 tool set에서는 tool definition을 hosted tool search 뒤로
  미루며, cognitive reflection은 끌 수 있고, convergence/no-progress guard가 반복 실패를
  끊는다.
- tau2 runner는 다른 표면이다. GEODE의 full `AgenticLoop`을 assistant와 시뮬레이션 user
  참가자 양쪽으로 내장한다. 즉 runner가 벤치마크 전용 예산을 설정하지 않으면 모든 tau2
  turn이 내부 agentic loop이 될 수 있다. 새 `--agent-max-rounds`와 `--user-max-rounds`
  플래그가 그 예산을 명시화한다.
- capped/no-defer probe가 트레이드오프를 보여준다: turn 비용을 낮추기는 쉽고, 벤치마크급
  액션 품질을 보존하기가 어렵다. retail의 지배 실패는 많은 올바른 read 후의 잘못된 최종
  write payload다. telecom의 지배 실패는 대화 부족이 아니라 워크플로 완결과 터미널 검증의
  부재다. 따라서 Crucible은 raw 메시지 수가 아니라 **올바른 environment 액션당 비용**을
  최적화해야 한다.

### 5.4 외부 사례 정렬 -- 피드백 신호와 반복 형상

현재 Crucible 루프가 참조 시스템들과 정렬되려면, 각 피드백 신호에 고정된 소유자가 있고
각 반복 단계에 유한 예산이 있어야 한다:

| 참조 패턴 | 최적화 대상 | Crucible 대응물 | 현 상태 |
|---|---|---|---|
| AlphaEvolve / FunSearch | 자동 evaluator에 대한 후보 생성. archive/selection이 유용한 후보를 보존 | R1/T1 guard 후보, tau2 task-success evaluator, 실패 manifest/archive | 후보/archive/evaluator 분리는 존재. live evaluator 지출 전 route-readiness 게이트가 이제 필수 |
| AutoTVM / Ansor / MetaSchedule | cost model과 단계적 하드웨어 측정으로 큰 탐색 공간을 좁힘 | full tau2 전의 G1 trace replay와 G2 micro-sim | G1이 존재하고 실행 가능한 판정을 냈다: T1 통과, R1 조건부 통과 |
| Hyperband / multi-fidelity BO | 저렴한 low-fidelity 시도가 high-fidelity 시도 전에 후보를 기각 | 실패 manifest → G1 trace replay → G2 micro-sim → G3a targeted mini → G3b sequential → G3c full | 사다리는 존재. 예산 스케줄러/value-of-information은 아직 없음 |
| SWE-agent / Agentless | interface/localization/패치 검증이 agentic 복잡도를 지배하는 경우가 많음 | guard 주입 표면, raw trajectory snapshot, 태스크 단위 paired 검증 | guard 주입과 snapshot 명명은 구현됨. live G2는 product-route 빈 출력으로 차단 |
| Physical AI / conformal 불확실성 | 비싼 실세계 시험은 불확실성·안전 게이트 후에만 | 구독 tau2를 비싼 live 세계로 취급. 인프라 오염은 거부권 | readiness 실패는 낮은 점수가 아니라 거부권 |

신호 계약:

| 신호 | 출처 | 용도 | 금지 용도 |
|---|---|---|---|
| 실패 군집 | `tmp/crucible_failure_manifest.json` | 후보 설계와 G1 지지 | 승격 증거 |
| G1 replay 판정 | `tmp/crucible_g1_trace_replay.json` | G2 quota 지출 여부 결정 | live 성능 점수 |
| 빈 출력 / rate-limit 진단 | Codex 진단과 transcript 스캔 | route readiness / 인프라 거부권 | 후보 회귀 |
| Paired flip/regression | 클린 base-vs-candidate live trajectory | G3b/G3c 후보 판정 | 경로 간 평균 |
| Full tau2 pass rate | 같은 model/user 경로, 클린 full 슬라이스 | product-route 승격/공개 결과 | PAYG `gpt-5.2` comparator |

## 6. 다음 개발

| Milestone | 내용 |
|---|---|
| M2 | rate-limit 대화 주입 격리 + `plugins/benchmark_harness/records.py` 정규화 레코드 + G3/G4/G6용 `gate.py` 배선 |
| M2.5 | 실패 manifest 스키마 + G1 trace replay runner + R1/T1 guard 제안 scaffold (영문 프롬프트 원문) |
| M3 | 캠페인 1: retail R1과 telecom T1을 별도 변이로 G0-G3a 저렴 게이트에 통과 |
| M4 | 예산 스케줄러(value of information) + archive/merge 운영 |
| M5 | full τ² G3c/G4/G5 통과 후보만 pass^k·revision과 함께 ledger·hub·docs에 공표 |

공표 규칙: 모든 run은 조건·revision과 함께 `site/src/data/geode/benchmark-measurements.ts`
에 기록한다. 방향 신호와 확정 승격 수치는 별도로 라벨링해야 한다.
