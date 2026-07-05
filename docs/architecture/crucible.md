# Crucible — 개선을 불로 시험하는 게이트 루프

> 상태: 설계 확정(2026-07-04), M1 실험 진행 중. 선행: `docs/architecture/autoresearch.md`(v1 SOT),
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

## 3. 약점 구간 — 실패 41건 전수 진단

results.json 전수 분석(2026-07-04). 실패가 사실상 한 패턴으로 수렴한다:

- **retail 27건**: 최종 해결 write(`exchange_delivered_order_items` ·
  `return_delivered_order_items` · `modify_pending_order_items`)를 실행하지 않은 채
  user_stop 종료. db_mismatch 25, action_miss 22.
- **telecom 14건**: 복합 장애에서 첫 수리 후 잔여 원인(`toggle_roaming` ·
  `reset_apn_settings` · `grant_app_permission` · `enable_roaming` · `refuel_data`)을 남기고
  종료. 14/14 전건 db_mismatch + action_miss.

공통 패턴 = **행동 완결 규율 부재**: 처리를 설명하고는 write 를 실행하지 않거나, 진단
체크리스트를 끝까지 돌지 않는다. write action 성공률(airline 33/49)이 read(81/91) 대비
낮은 것이 부가 신호. 실패 태스크 ID 는 `tmp/tau2_failed_{retail,telecom}.txt` 에 고정.

## 4. 접근 — 시금 체계

### 4.1 원칙과 신호 3축

**판정이 자율보다 먼저 선다.** 루프의 수렴 속도·정확도는 verifier 의 강도와 처리량이
상한을 정한다. 신호는 세 축으로 분리하고 섞지 않는다:

| 축 | 소스 | 역할 |
|---|---|---|
| capability (주 신호) | τ² train 서브셋 결정론 task-success | 최적화 대상 |
| safety (floor) | Petri critical 축 + 도구 계약 PASS/FAIL | 집계 밖 거부권, 교환 불가 |
| cost (예산) | E1 mutation cost ledger | 상한 제약 |

### 4.2 게이트 사다리 v2 (cost ladder — reject accelerator 중심)

v1 설계는 사다리를 문서상 갖췄으나 첫 S5 사이클에서 **비싼 τ² full-ish paired run까지 너무
빨리 갔다**. clop48 한 구간이 ~175M 토큰·~$837 로 승격 0 — verifier 가 optimizer 를 굶긴
상태. 병목은 mutation 품질이 아니라 **verification throughput(the limiting reagent)** 이었다.
v2 는 값싼 기각을 앞단으로 몰아 가망 없는 변이가 full benchmark 에 닿기 전에 죽게 한다.

```
G0 static reject   표면 밖·중복·evidence_refs 부재·과광역 가드·step-budget 위험·        비용 0
                   도구 계약 불일치·기대 실패모드 미명시 → 즉시 기각
G1 trace replay    기존 실패 trajectory 를 replay 해 "이 변이가 개입할 지점이            비용 0 (LLM 無)
                   실제로 있는가"만 확인 — 개입점 0 이면 기각
G2 micro-sim       실패 cluster 대표 5~10 task, max_step 낮게. reject 전용(승격 금지)     분 단위
G3a targeted mini  실패 cluster 12~20 + matched clean control 8~12. reject 전용         소 비용
G3b sequential     full 후보만 진입. 매 ~10 discordant 마다 flip/reg 갱신,               중 비용
                   SPRT/Bayesian futility 로 회귀 위험 높으면 조기 중단
G3c full paired    promotion 직전 최종심만. 공개 수치용 (K=3 replicate)                  주 비용
G4 held-out        telecom 서브셋 + MCPMark File 무회귀                                 중간
G5 safety          Petri critical 후퇴 strict reject ∧ 계약 veto                        중간
G6 cost            $/task·지연 예산 내                                                  기록 재사용
G7 판정            전부 통과 → promote(git chain) / 아니면 revert 또는 archive
```

핵심 원칙: **cheap reject 가 대부분을 걸러야 하고, expensive benchmark 는 소수 후보만,
full paired 는 promotion 직전 최종심.** 조기 중단은 **기각 방향으로만** — full benchmark 는
공개·승격 근거라 중간 결과로 core 에 넣는 건 위험하지만(조기 승격 금지), 중간 결과로 버리는
건 안전하다(조기 기각 허용).

**G3b sequential 판정 (early-stop = reject accelerator).** 114×2 를 처음부터 다 돌리지
않는다. discordant pair 만 순차 관측하며(flip=개선 증거, regression=회귀 증거) 매 갱신마다
Beta-Binomial posterior 로 판정:
- **Hard reject**: ≥12 discordant 후 regression ≥ flip + 4, 또는 held-out 에서
  P(delta < -3pp) > 0.90, 또는 safety floor 위반.
- **Futility stop**: 현재까지로 최종 +3pp 달성 posterior < 5%.
- **Continue**: flip/reg 차 작고 표본 부족.
S5 telecom 은 최종 flip 4 vs reg 12 였으니, 이 규칙이 있었다면 full run 전에 죽었다.
`scripts/eval/sequential_gate.py` 가 구현(Beta(1,1) prior, delta = s5_pass − base_pass).

G3c 는 집계 점수가 아니라 동일 태스크 짝의 뒤집힘만 검정한다(discordant pair 정확
이항검정). G5 는 v1 의 "이진 신호는 평균에 섞지 않는다"를 사다리 구조로 확장한 것이다.

### 4.3 채택 기법과 계보

| 기법 | 출처 | 구현 |
|---|---|---|
| trace-grounded 변이 제안 | GEPA | 실패 트레이스 분류 → 제안에 `evidence_refs` 의무화 |
| 평가 캐스케이드 | AlphaEvolve | 비용 0 게이트부터, 비싼 측정은 생존 후보만 |
| 외부 동결 held-out + 도메인 분할 | Agent-World (arXiv 2604.18292) | train=retail 서브셋 / held-out=telecom / airline=추세 전용 |
| (1+1)-ES trunk + 유계 아카이브 | karpathy/autoresearch + DGM | 사이클당 1변이, 탈락-부분개선 N≤5 보존 |
| slot-disjoint merge | GEPA crossover | 서로소 정책 파일 결합, 동일 게이트 통과 |

**채택하지 않은 것과 부활 조건**: 다목적 Pareto 선택(v0.99 (1+λ)+Tchebycheff 층,
PR-DROP-GROUP-SAMPLING 2026-05-29 제거 — 노이즈 단일 judge 축 위에선 성립 불가. 부활 조건:
clean 축 2개 이상), (1+λ) 병렬 배치(부활 조건: 세대 단위 평가 병렬화), 도메인 특화+라우터
(retail/telecom 규율이 실측으로 갈릴 때만), MAP-Elites/QD(평가가 싸고 결정론인 도메인용).

**선택 구조**: karpathy/autoresearch 원본에는 branching·population 이 의도적으로 없다 —
3-파일 규율, 고정 5분 예산, 단일 지표, git 이 옵티마이저의 전부. 이식하는 철학:
*통제된 비교가 성립하는 한도 안에서 가장 멍청한 옵티마이저를 쓴다. 영리함은 변이 제안에,
단순함은 판정 구조에.* 선택 구조의 복잡도는 실험 경제학의 종속 변수다. trunk 는 선형
champion chain 유지, 확장은 git-native 아카이브/merge 까지.

분류를 정직하게: 이 시스템은 constrained, verifier-guarded **stochastic hill climbing**
이다. naive hill climber 와의 차이는 언덕이 진짜인지 먼저 검증하는 장치 — 노이즈 밴드
선확정(가짜 언덕), 동결 held-out(Goodhart 언덕), floor veto(안전 절벽), 아카이브(고원 탈출).

### 4.4 변이 표면

입장 기준 4: ① 인과 근접성(실측 실패 모드가 슬롯에 지도) ② 검출 가능성(기대 효과 ≥ paired
검출 한계) ③ 자와의 분리 ④ 평가 비용. §3 진단이 지도하는 표면:

| | 슬롯 | 근거 실패 모드 |
|---|---|---|
| S1 | 에이전트 시스템 프롬프트 행동 규율 섹션 | write 미실행 종료 |
| S2 | tool_policy JSON | 종료 전 pending-write 미확인 |
| S3 | tool_descriptions | write 인자 오류 |
| S4 | decomposition 정책 | 복합 장애 checklist sweep 부재 |
| S5 | evolve-block 코드: 결정론 종료 가드 (Tier 1b, 2차) | 위 전부의 구조적 처방 |

제외: user simulator 프롬프트(비교 가능성 오염), 벤치마크 domain policy(변이=치팅),
태스크 선택·채점 일체(자). 입도: 섹션/키 단위만. 크기: 표면 확장은 게이트 처리량이
감당하는 속도로.

## 5. 현재 실험 — M1 (게이트 시운전, 진행 중)

목적 둘: 실측 개선 후보의 검증 + 게이트 사다리 자체의 시운전. **사람 손 수정도 루프
변이와 같은 사다리를 통과해야 게이트의 공정성이 성립한다.**

- 변이: S1 행동 완결 규율. `plugins/benchmark_harness/tau2_geode_agent.py::_agent_system_prompt`
  의 인자 규율 문단 뒤·`<policy>` 앞. 도메인 무관, 답 유출 없음(OpenAI 가 telecom 에
  "brief, generally helpful instruction" 을 공개적으로 쓴 것과 같은 범주).
- G1 통과(2026-07-04): 프롬프트 단언 테스트 7건, branch `feature/sev2-m1-action-discipline`.
- G2 통과: mock 도메인, G3 동일 배선(gpt-5.2 payg + native user_simulator), DB match 1/1.
- G3 진행 중: 실패 서브셋 표적 재실행(retail 27 + telecom 14, 동시성 8 병렬).
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

### 5.1 첫 사이클 결론 — the limiting reagent (2026-07-06)

첫 Crucible 사이클은 self-improvement 를 증명하지 못했다. **promotion protocol 을 증명했고,
verification throughput 을 the limiting reagent 로 드러냈다.** 다음 엔지니어링 타깃은 더 똑똑한
mutator 가 아니라 더 싼 evaluator cascade 다.

- 좋았던 것: frozen ruler, paired comparison, held-out regression, "그럴듯한 변경을 core 에
  넣기 전에 막음", reject 를 기록 가능한 evidence 로 남김.
- 나빴던 것: 한 iteration 비용 과함(clop48 ~175M tok·~$837), K=1 pass^1 noise 로 검출력 낮음
  (~8pt 한계), quota 가 실험 설계를 지배, cheap gate 가 충분히 discriminative 하지 않음,
  변이 하나 검증에 full simulation 을 과소모.
- 처방: §4.2 게이트 사다리 v2 — G0 static reject 강화 + G1 trace replay(LLM 無) +
  G2 micro-sim(reject 전용) + G3a targeted mini + G3b sequential(SPRT/Bayesian futility) +
  G3c full(promotion 직전만). full τ² 비용을 아끼는 reject accelerator 가 핵심.

## 6. 이후 전개

| 마일스톤 | 내용 |
|---|---|
| M2 | `plugins/benchmark_harness/records.py`(정규화 기록) + `bench_means.py` native provenance 로더 + `gate.py` G3/G4/G6 배선 |
| M3 | 캠페인 1: 잔여 실패 진단 → trace-grounded 변이 5~10 사이클 |
| M4 | 아카이브+merge 가동, S5 evolve-block 1곳 |
| M5 | 공개: ledger 에 pass^k·리비전 명시, hub·docs 게시 |

공개 규율: 모든 run 은 `site/src/data/geode/benchmark-measurements.ts` 에 조건·리비전과
함께 기록. 방향 신호와 확정 수치를 구분해 표기한다.
