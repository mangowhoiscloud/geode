# Crucible 핸드오프 — 세션 간 진척·상태 문서

> 갱신: 2026-07-05 02:00 KST. 설계 SOT = `docs/architecture/crucible.md` (원칙·게이트·판정 기록 전부 거기).
> 이 문서는 **실행 상태**의 핸드오프: 무엇이 돌고 있고, 어디에 뭐가 있고, 다음이 뭔지.
> 컨텍스트 배경: FuriosaAI 지원 서사와 연동된 작업이나, 공개 저장소이므로 이 문서엔 엔지니어링 내용만.

## 0. Crucible이 무엇인가 (한 문단)

self-evolving v2. 자기 생성 시뮬레이션(v1: seedgen+Petri)의 3중 분산·폐쇄성·판정 비용 한계를
외부 동결 벤치마크(τ²-bench)로 교체하고, 개선 후보를 게이트 사다리(G0 제안가드 → G1 legality
→ G2 smoke → G3 paired capability → G4 held-out → G5 safety floor → G6 cost → G7 판정)에
통과시켜 살아남는 승격만 남긴다. 수동 수정도 같은 사다리를 탄다(M1). 분류: constrained,
verifier-guarded stochastic hill climbing.

## 1. 지금 돌고 있는 것 (2026-07-05 01:20 기준)

**clop48 트랙 야간 배치** — Claude 구독 경로 S5 재판정.
- 스펙(동결): agent claude-opus-4-8 sub high / user geode_user claude-sonnet-4-6 sub medium / c3 / 직렬 4런 (retail base→s5 → telecom base→s5)
- 실행체: `nohup zsh .claude/worktrees/sev2-s5/tmp/run_clop48_overnight.zsh` (disown, 세션 독립)
- 보호: 런 전 5h 창 가드(사용률>0.85 대기), 30분 주기 OAuth 토큰 리프레셔 내장
- 진척 확인: `tmp/clop48_orchestrator.log` + `data/simulations/geode-clop48-*-20260705/results.json`
- 완료 신호: `tmp/clop48.done` 마커 + `tmp/clop48_verdict.txt` (오염 필터 내장 paired 자동 판독)
- 01:06 시작 → 01:57 토큰 만료 사고(버그④)로 중지·수정 → 01:55(r2) 재발사, auto-resume 승계
- Opus 연소율 주의: 첫 50분에 5h 창 7%→47% — 창 가드(>85% 대기)가 페이스를 조절하므로 판정은 **~08~09시로 연장 가능**
- 루프 실사용 검증됨: 평균 1.4라운드/턴(최대 4), 수렴 감지 실전 발동 확인

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

## 4. 이번 사이클에서 발굴·수정한 GEODE 버그 3종 (main 반입 PR 필요)

| 커밋(양팔 동일) | 내용 |
|---|---|
| sev2-s5 브랜치 내 | ① `_codex_sdk_workaround.py` install() 무락 레이스 → 동시성에서 RecursionError (락+클로저 캡처+멱등 마커) |
| 〃 | ② `anthropic-oauth`가 OAuth 토큰을 x-api-key로 전송 → 401 (auth_token= Bearer + oauth-2025-04-20 베타 헤더) |
| 〃 | ③ OAuth 추론 게이트: sonnet/opus는 Claude Code 신원이 **정확 일치하는 독립 첫 system 블록**이어야 함, 연결형은 bare 429 (kwargs 레벨 2-블록 재작성). haiku는 면제. 창 상태는 응답의 `anthropic-ratelimit-unified-*` 헤더로 실측 가능 — `get_quota_windows` 배선 개선감 |
| 〃 | ④ `anthropic-oauth` 토큰 회전 미반영: loop-affine 캐시가 첫 빌드 클라이언트를 유지해, CLI가 OAuth 토큰을 갱신하면 모든 캐시 클라이언트가 프로세스 사망까지 401 (01:57 만료 사고). codex 패턴의 sha256 fingerprint 무효화 이식 |

교훈: 외부 벤치마크를 고동시성으로 돌리는 것 자체가 런타임 결함 발굴기다. 셋 다
`feature/sev2-s5-termination-guard` 와 `exp/sub55-base` 에 동일 커밋으로 존재.

## 5. 워크트리·브랜치 지도

| 워크트리 | 브랜치 | 역할 |
|---|---|---|
| `.claude/worktrees/sev2-m1` | feature/sev2-m1-action-discipline | M1 변이(기각) — 아카이브 보존 |
| `.claude/worktrees/sev2-s5` | feature/sev2-s5-termination-guard | S5 변이 팔 + 인프라 수정 3종 + 오케스트레이터/판독 스크립트 |
| `.claude/worktrees/sev2-s5-base` | exp/sub55-base | baseline 팔 (1c3ecd64c + 인프라 수정 3종만; S5 없음) |

## 6. 파일 지도

- 설계·판정 SOT: `docs/architecture/crucible.md`
- 실행 스크립트: `sev2-s5/tmp/run_clop48_overnight.zsh` (창 가드·리프레셔 포함), `analyze_g3_flips.py`
- 미측정 ID: `geode/tmp/s5_infra_{retail,telecom}.txt`, `tau2_failed_{retail,telecom}.txt`(M0 진단)
- 공개 ledger: `site/src/data/geode/benchmark-measurements.ts` (리비전 명시·평균 금지 규율)
- OAuth 물질화: `~/.claude/oauth-token.json` (0600, keychain 'Claude Code-credentials'에서 덤프,
  ~1h 만료 — 리프레셔가 갱신. 재물질화 스니펫은 오케스트레이터 `refresh_token()` 참조)
- 포트폴리오 측(비공개 워크스페이스): `~/Downloads/GEODE-포트폴리오/Crucible-덱-설계.md`,
  resume 저장소 `furiosa/.../interview-prep.md` 자산 8

## 7. 다음 액션 큐 (순서 고정)

1. **clop48 판정** (~06시): `tmp/clop48_verdict.txt` → crucible.md §5 기입. 승격/기각/보류 판정.
2. 승격 시: S5 코어 이식 설계 (`core/agent/verify.py` rule-based check + 정책 SoT 임계) + 어댑터 가드 제거 + `system_prompt_override`→wrapper 섹션 합성 재배선(M2). 참고: 현 override는 v1 변이 표면(WRAPPER_PROMPT_SECTIONS)을 우회 — 벤치가 코어 변이를 측정 못 하는 구조적 갭.
3. payg 한도 상향 시: S5 payg 71건 완결(~$65) → 양 트랙 판정 비교.
4. airline 50건 trend(집계 형식 완결용, 게이트 제외) → comparator run(tau2 내장 `llm_agent`, 동일 조건 head-to-head — "GEODE vs 바닐라" 정당 근거).
5. 인프라 수정 3종 main 반입 PR + M2(records.py·bench_means 재활성·gate.py 배선).
6. 수치 확정 후: ledger 행 추가 → Crucible 덱 빌드(KO/EN PPTX+PDF+영상) + 이력서 GEODE Self-improving 섹션 불릿 1개 교체.

## 8. 함정 목록 (재발 방지)

- tau2 `--task-ids`는 `--num-tasks`(기본 1!)로 뒤에서 슬라이스 — 항상 ID 수와 같게 명시.
- 실패 서브셋만 재실행한 flip rate는 방향 신호일 뿐(회귀 안 보임) — 전체 paired 전 공개 금지.
- quota 사망 중 완료된 run을 무필터로 읽으면 변이 효과로 오독(§2 오염 필터 필수).
- 세션 소유 백그라운드는 세션 종료와 함께 죽음 — 장기 런은 nohup+disown.
- native tau2 user_simulator는 GEODE 어댑터 우회(litellm→payg 직행) — 구독 트랙은 geode_user 라우트.
- Codex/Claude 구독 창은 조회 표면 없음(Claude는 응답 헤더로 가능) — 런 전 창 가드 필수.
