# Crucible 핸드오프 — 세션 간 진척·상태 문서

> 갱신: 2026-07-06 02:00 KST. 설계 SOT = `docs/architecture/crucible.md` (원칙·게이트·판정 기록 전부 거기).
> 이 문서는 **실행 상태**의 핸드오프: 무엇이 돌고 있고, 어디에 뭐가 있고, 다음이 뭔지.
> 컨텍스트 배경: FuriosaAI 지원 서사와 연동된 작업이나, 공개 저장소이므로 이 문서엔 엔지니어링 내용만.

## 0. Crucible이 무엇인가 (한 문단)

**capability 축 self-evolving 루프.** v1(seedgen+Petri, safety 축)의 후속이 아니라 **형제** —
promotion protocol(champion chain, paired 판정, frozen ruler, "이진 신호는 평균에 안 섞음")은
공유하되 verifier만 교체: Petri 적대 감사 대신 **τ²-bench 결정론 task-success**로 에이전트
하네스/정책을 진화시킨다. 개선 후보를 게이트 사다리 v2(G0 static → G1 trace-replay → G2
micro-sim → G3a targeted → G3b sequential futility → G3c full → G4 held-out → G5 safety →
G6 cost → G7 판정)에 통과시켜 살아남는 승격만 남긴다. 분류: constrained, verifier-guarded
stochastic hill climbing.

## 1. 현재 상태 (2026-07-06 — 실측/판정 일시정지, 코드 반영 완료)

**API 경로 3종이 전부 막혀 새 τ² 실측은 불가. 코드·문서는 정리·반영 완료. 다음은 결정 대기.**

- **clop48 트랙(Claude 구독 opus-4-8): 무효 확정.** 4런 완주했으나 옛 계정(Max 20x)의 7d 창
  소진 후 태스크가 rate-limit 주입으로 오염 → max_steps 지배. **user-sim은 무결**(초기 진단
  오진, 철회). 클린(user_stop) 데이터에 `sequential_gate.py` 적용: **retail CONTINUE(P=0.87,
  flip 3 reg 0), telecom PROMOTE_CAND(P=0.96, flip 4 reg 0)** — 오염 제거하니 S5 유망.
- **API 창 현황**: payg(gpt-5.2)=billing 차단 / Codex 구독=07-07 16:53 리셋 / 옛 Claude 20x=
  07-11 리셋 / **새 계정 Claude Max 5x = 여유(5h 6%·7d 1%)**. 단 5x는 opus 대량엔 빠듯.
- **오늘 코드 반영**: 브랜치 `feature/crucible-tau2-harness` (main 미머지, push 안 함) —
  인프라 버그 5종 수정 2커밋 + Crucible 문서·sequential_gate 1커밋 + CHANGELOG 0.99.275.
  §4 참조.

**S5 판정을 진전시키려면 새 τ² 실측이 필요하나, 지금은 불가.** 유효 경로 후보:
① payg billing 상향(~$65, native user 검증됨) → payg 71건 완결, ② 새 5x로 clop48 오염분
재측정(sonnet 스펙이면 감당, opus면 빠듯). §7 참조.

## 2. 트랙 현황

| 트랙 | 스펙 | 상태 |
|---|---|---|
| **payg (gpt-5.2)** | agent gpt-5.2 high payg + native user_sim gpt-4.1 | M1(S1 프롬프트) **기각 확정**. S5 측정 71건 미완(retail 18·telecom 53) — **OpenAI billing 한도 차단**, 상향 시 ~$65로 완결 가능. 미측정 ID = `tmp/s5_infra_{retail,telecom}.txt` |
| sub55 (gpt-5.5 구독) | 폐기 | Codex 플랜(prolite) 주간 창 소진, 리셋 07-07 16:53 KST. r1/r2 데이터 전량 오염 폐기 |
| **clop48 (opus-4-8 구독)** | 위 §1 | **진행 중**. 창 여유 실측: 5h 7% / 7d 12% (01시 기준) |

병합 금지: 트랙 간 수치 병합·평균 절대 금지 (스펙 상이). 오염 필터 규칙 = termination_reason
infrastructure_error 제외 ∧ 메시지 error ≥3 제외.

## 3. 판정 기록 (상세는 crucible.md §5)

- **M1 (S1 행동 완결 프롬프트): 기각.** retail 76.3→78.1 (flip 12 vs 회귀 10, p=0.416),
  telecom 87.7→83.3 (p=0.885, 점추정 음). 방향 신호(실패 서브셋 flip 39%)가 전체 paired에서
  재추첨 노이즈로 판명 — 실패분만 재실행하면 회귀가 안 보인다는 설계 경고의 실증.
- **S5 (결정론 종료 가드) payg 트랙: 미완.** 클린 병합 retail +3.1pt(p=0.332)·telecom -3.3pt.
  71건 미측정 상태로 보류. clop48이 cross-family 재판정 중.
- **노이즈 바닥 실측**: pass^1 K=1 태스크당 flip ~20% → 검출 한계 ~8pt. 하네스 개입 효과(~3pt급)는
  K=3 replicate 없이 검출 불가. 사전 등록(K=3, discordant 정확 이항 단측 p<0.05, 승격 상한 2)이
  선택이 아니라 필수임의 데이터 확증.

## 4. 코드 반영 상태 (2026-07-06)

**브랜치 `feature/crucible-tau2-harness` (main 미머지, push 안 함) — 4커밋:**
| 커밋 | 내용 |
|---|---|
| `ee8c5ffde` fix(codex-oauth) | ① `_codex_sdk_workaround.py` install() 무락 레이스 → 동시성 RecursionError (락+클로저 캡처+멱등 마커) |
| `c9b9566e0` fix(anthropic-oauth) | ②③④ 구독 경로 3결함: x-api-key→Bearer(oauth-2025-04-20 베타) / 신원 독립 첫 system 블록(연결형 429) / 토큰 회전 sha256 무효화 |
| `e63f21676` docs(crucible) | crucible.md·crucible-handoff.md·`scripts/eval/sequential_gate.py` |
| `0b6faef08` docs(changelog) | 0.99.275 — Architecture/Added/Fixed/Known Issues |

- 실험 코드(S5 종료 가드·S1 프롬프트)는 main에 **미반입** — 판정 미완/기각이라 champion chain
  규율상 코어 진입 불가. 브랜치 아카이브로만 보존(§5).
- **미수정 버그(⑥, CHANGELOG Known Issues)**: rate-limit 에러가 대화 메시지로 주입돼
  `infrastructure_error` 격리를 우회 → max_steps 오완료. 어댑터 레벨 격리가 정식 수정(pending).
- 교훈: 외부 벤치마크를 고동시성으로 돌리는 것 자체가 런타임 결함 발굴기(버그 6종 전부 이렇게 나옴).

## 4.5 업계 지형 조사 결과 (2026-07-06 — cascade 스코프 재조정)

cascade/parallel-eval을 자체 구현하려다, 기존 프레임워크가 대부분 이미 함을 확인:
- **ShinkaEvolve**(Sakana, ICLR 2026): pluggable evaluator + prompt/scaffolding 진화 + island/archive.
  단 "sequential hypothesis testing·paired comparison 없음, noise를 aggregation으로 흡수".
- **FlashEvolve**: non-parametric artifact(system prompt·harness) 진화 + async parallel orchestration
  (**3.5× throughput** 실증) + speculative early rejection.
- **OpenEvolve**: AlphaEvolve 오픈소스, (initial code + evaluator + metrics) 인터페이스.
- **AutoPass/KernelAgent**: verifier-rich 도메인의 cheap-to-expensive cascade(syntax→schema→runtime).
→ **결론: cascade 러너·evaluator 포트·parallel eval = 재발명(자체 구현 철회). 고유 기여 = 단 하나,
   noisy verifier에서 통계적으로 엄밀한 조기 기각(paired Bayesian futility) = `sequential_gate.py`.**
   이걸 자체 유지할지 vs ShinkaEvolve evaluator 슬롯에 얹을지가 §7 결정 사항.

## 5. 워크트리·브랜치 지도

| 워크트리/브랜치 | 역할 |
|---|---|
| `feature/crucible-tau2-harness` (main 워킹트리) | **오늘 반영분** — 인프라 수정 + 문서 + sequential_gate. 리뷰 후 머지 결정 |
| `.claude/worktrees/sev2-m1` / `feature/sev2-m1-action-discipline` | S1 변이(기각) — 아카이브 |
| `.claude/worktrees/sev2-s5` / `feature/sev2-s5-termination-guard` | S5 변이 팔 + 오케스트레이터/판독 스크립트 + 인프라 수정(base와 동일) |
| `.claude/worktrees/sev2-s5-base` / `exp/sub55-base` | baseline 팔 (S5 없음, 인프라 수정만) — 오늘 인프라 커밋의 소스 |

## 6. 파일 지도

- 설계·판정 SOT: `docs/architecture/crucible.md` (§4.2 게이트 v2·§5.1 limiting reagent 결론)
- sequential gate: `scripts/eval/sequential_gate.py` (인자 없이 실행 → clop48 clean 재현)
- 실행 스크립트(sev2-s5/tmp/): `run_clop48_overnight.zsh`(창 가드·리프레셔), `analyze_g3_flips.py`
- 재측정 ID: `sev2-s5/tmp/clop48_remeasure_{dom}.txt`(오염 union), `clop48_contaminated_{dom}_{arm}.txt`
- M0 진단 ID: `geode/tmp/tau2_failed_{retail,telecom}.txt`, `s5_infra_{retail,telecom}.txt`
- 공개 ledger: `site/src/data/geode/benchmark-measurements.ts` (리비전 명시·평균 금지 규율)
- OAuth 물질화: `~/.claude/oauth-token.json` (0600, keychain 'Claude Code-credentials'에서 덤프,
  ~1h 만료 — `run_clop48_overnight.zsh::refresh_token()` 스니펫 참조). **버그④ 수정 후엔 어댑터가
  회전 자동 반영하므로, 프로덕션 경로는 재덤프 불필요; 스크립트는 창 헤더 조회용으로만 유지**
- 포트폴리오(비공개): `~/Downloads/GEODE-포트폴리오/Crucible-덱-설계.md`,
  resume `furiosa/.../interview-prep.md` 자산 8

## 7. 다음 액션 큐 (결정 대기 포함)

**결정 필요 (사용자):**
- D1. **S5 판정 재측정 경로**: ① payg billing 상향(~$65, native user) / ② 새 5x로 clop48 오염분
  재측정(sonnet 감당·opus 빠듯) / ③ 판정 보류하고 다음 변이(트리거 B 도메인 조건화)로. 목적이
  "iteration 비용 절감"이면 A(full 확증)보다 저비용 경로 우선.
- D2. **sequential_gate 거처**: 자체 유지(경량) vs ShinkaEvolve evaluator 슬롯에 얹기(재발명 없음,
  island/archive/parallel 공짜, 외부 의존). §4.5 참조.

**실행 큐 (D1/D2 정해지면):**
1. (D1 정해지면) S5 재측정 → `sequential_gate.py`로 futility/promote 판정 → crucible.md §5 확정.
2. S5 승격 시: 코어 이식 M2 — `core/agent/verify.py` rule-based check + 정책 SoT 임계, 어댑터
   가드 제거, `system_prompt_override`→wrapper 섹션 합성 재배선(현 override는 v1 변이 표면
   `WRAPPER_PROMPT_SECTIONS`을 우회 — 벤치가 코어 변이를 측정 못 하는 구조적 갭).
3. 버그⑥(rate-limit 대화 주입 격리) 어댑터 수정 → main 반입.
4. `feature/crucible-tau2-harness` 리뷰 → main 머지/push (사용자 승인 시).
5. airline 50건 trend + comparator run(tau2 내장 `llm_agent`, "GEODE vs 바닐라") — payg 여유 시.
6. 수치 확정 후: ledger 행 + Crucible 덱 빌드(KO/EN) + 이력서 GEODE Self-improving 불릿 교체.

## 8. 함정 목록 (재발 방지)

- tau2 `--task-ids`는 `--num-tasks`(기본 1!)로 뒤에서 슬라이스 — 항상 ID 수와 같게 명시.
- 실패 서브셋만 재실행한 flip rate는 방향 신호일 뿐(회귀 안 보임) — 전체 paired 전 공개 금지.
- quota 사망 중 완료된 run을 무필터로 읽으면 변이 효과로 오독(§2 오염 필터 필수).
- 세션 소유 백그라운드는 세션 종료와 함께 죽음 — 장기 런은 nohup+disown.
- native tau2 user_simulator는 GEODE 어댑터 우회(litellm→payg 직행) — 구독 트랙은 geode_user 라우트.
- Codex/Claude 구독 창은 조회 표면 없음(Claude는 응답 헤더로 가능) — 런 전 창 가드 필수.
