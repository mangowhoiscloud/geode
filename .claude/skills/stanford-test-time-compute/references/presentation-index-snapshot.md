# LG AI Research 1차 기술 면접 PT — 작업 SoT

작성 시작: 2026-07-28. 상위 `../README.md`(공고 SoT)와 함께 읽을 것.

## 면접 스펙 (2026-07-28 면접 안내 메일 요약 기준)

- **전형**: 1차 기술 면접 = 개인 PT 발표 (WEBEX 화상)
- **구성**: PT 20분 + 질의응답 40분 (총 1시간)
- **장수**: 본편 37장. Q&A 부록은 근거가 확정된 뒤 별도 설계
- **면접관**: Data Governance Team 리더 외 1명
- **자료**: 자유 양식, 참여도 높은 핵심 프로젝트 2~3개
- **제출 기한**: 면접 하루 전까지 (일정 확정 메일에서 구체화 예정)
- **직무 맥락**: AI Data Engineer Internship의 **Agent Workflow 공고** — 사내 AI 업무 도우미, workflow 개선·테스트, tool calling·agent skill·prompt 검증, 상태 관리, 격리 실행, 로그·실패·평가 분석 (`../README.md` §1 및 [공식 채용 공고](https://www.lgresearch.ai/careers/view?seq=187))

## 발표 구성 (사용자 확정)

1. **Meta harness** — 제작 조건·검증·revision의 change authority
2. **Application runtime** — prompt-only→fixed DAG→loop runtime,
   prompt·state·hook·context·tool·skill·MCP·subagent
3. **Observe / Evaluation / Verify** — Eco² service observability→GEODE
   session/trajectory→Eco² Swiss Cheese Eval→GEODE Verify/Replan
4. **Simulator / Benchmark** — Petri interaction audit와
   τ²·MCPMark의 environment completion contract
5. **External experiment loop** — SIL의 bounded scaffold search와
   Crucible의 독립 promotion control
6. **Transfer** — REODE migration과 EXAONE application vertical slice

## 디렉토리

```text
presentation/
  README.md      ← 이 파일 (SoT)
  progress-audit.md ← 현재 완성도·누락·내러티브 v2
  talk-script-20min.md ← 11개월 작업법 헤드라인·37장 타임코드·발표 대본
  wiki/          ← 역할 조사 + 프로젝트별 실측 수집 (LLM wiki)
  design.md      ← 디자인 진입점·기존 초안 상태
  design/        ← 공식 자산 실측 기반 시각 시스템
  strategy.md    ← 20분 콘텐츠 풀 + Agent Workflow 예상 질문
  slides/        ← 37장 활성 HTML 슬라이드
  assets/        ← (예정) 로고, 다이어그램
```

## 수집 절차 (wiki 규약)

- 역할 SoT: `wiki/role-agent-workflow.md`
- 연구개발 문제의식: `wiki/exaone-agent-rd.md`
- ChatEXAONE Enterprise Agent 심층:
  `wiki/chatexaone-enterprise-agent.md`
- Frontier Agent 원문 비교: `wiki/frontier-agent-engineering-2026.md`
- K-EXAONE 2.0·Solar Open 2·한중 모델 비교:
  `wiki/k-exaone-2.0-solar-open-2-comparison-2026.md`,
  `wiki/k-exaone-2.0-agent-workflow-opportunity-2026-07-31.md`
  (K‑EXAONE 2.0 이후 application control plane의 기회, GEODE current
  main 교정, 31장 call-up/reduce 결정)
- Kimi K2.5 Agent Swarm·PARL:
  `wiki/kimi-k2.5-agent-swarm.md`
- seq=636 이후 공개 추적: `wiki/lg-research-after-seq636.md`
- 프로젝트당 1파일: `wiki/eco2.md`, `wiki/geode.md`, `wiki/reode.md`, `wiki/kiki.md`, `wiki/assets-pipeline.md`
- 축 보강 (2026-07-29): `wiki/skills-geode.md`(GEODE 자체 skill 시스템),
  `wiki/geode-codebase-atlas.md`(PDF 88쪽→현재 코드·test·artifact→발표의
  G0~G9 추적 지도),
  `wiki/skills-eco2.md`(메타하네스 — 클러스터 배포 조정 skill),
  `wiki/evolution-eco2-agent.md`(블로그 104개 인덱스·코드·Git 대조),
  `wiki/geode-context-engineering.md`(PDF 24~33쪽·실행 wiring·Git 대조),
  `wiki/runtime-context-assembly-terminology.md`(GEODE prompt 분기 순서,
  OpenAI·LangChain·Google ADK·Anthropic의 dynamic instruction/context
  용어 대조, turn-scoped assembly 표현),
  `wiki/geode-trajectory-judgment.md`(Eval·Observe·Diagnose와
  feedback/evolution 폐루프·autoresearch/AlphaEvolve/GRPO 게이트 계보·
  Crucible/SIL 판정),
  `wiki/eval-artifact-lineage.md`(Eco² Chat Agent→GEODE Petri의 인과,
  2026-05-11 내부 archive→2026-07-13 공개 저장소, artifact 기반
  승격 판정 프로토콜),
  `wiki/agent-workflow-codebase-map.md`(Understand-Anything knowledge
  graph로 GEODE·Eco²의 runtime·tool·state·evaluation·infra 구조를
  같은 taxonomy에 연결하고 seq=187 어필 포인트를 우선순위화),
  `wiki/evaluation-guided-scaffold-search.md`(Hold-out·nested CV·
  adaptive holdout의 원전 계보, agent scaffold/workflow 탐색 용어와
  GEODE 평가 권한 정렬),
  `wiki/narrative-evaluation-guided-geode.md`(원전→GEODE→
  ChatEXAONE 기여 방향의 사용자 검토용 6단락·90초 내러티브),
  `wiki/deck-restructure-2026-07-30.md`(Eco² desired state→Agent
  활용면/runtime→GEODE meta/runtime harness→eval-artifact
  promotion→REODE→EXAONE application으로 이어지는 15장 발표 SOT),
  `wiki/bounded-harness-control-2607.25415.md`(frozen LLM 주변의
  6개 bounded harness lever·control/bandit/REINFORCE 이론, 공개 코드의
  nominal 729↔effective surface 감사, GEODE 7개 behavior SoT 및
  SIL→Crucible 시간선 정렬),
  `wiki/hyperagents-2603.19461.md`(HyperAgents 원문·Meta 공식 페이지·
  commit-pinned 코드 검증, editable task+meta program과 fixed outer
  evaluator의 경계, Paul 2607.25415의 비판적 해석 교정, Red Queen
  Gödel Machine 원문의 독립 교차 인용),
  `wiki/creator-persona-narrative-audit-2026-07-30.md`(Eco²·GEODE·SIL·
  Crucible의 evidence-derived 제작자 의도 페르소나, 100점 정합성
  scorecard, 오탐·누락·순서 교정, Petri·τ² 결과 경계),
  `wiki/deck-restructure-2026-07-31.md`(38장 구조의 이전 SOT),
  `wiki/k-exaone-2.0-agent-workflow-opportunity-2026-07-31.md`
  (현재 31장 활성 순서와 claim boundary),
  `wiki/eval-gate-visual-grammar-2026-07-31.md`(외부 Eval·실험 발표에서
  추출한 identity→evidence→validity→decision→authority 시각 문법과
  GEODE 화면별 적용),
  `wiki/project-signal-audit-2026-07-31.md`(Eco²·GEODE·Petri·SIL·
  Crucible·REODE·Kiki·EXAONE 본편 누락 신호와 P0/P1/P2 편집 우선순위),
  `wiki/geode-v1.0.10-motivation-control-boundaries-2026-07-31.md`
  (v1.0.10 runtime·hook·benchmark schema 근거와
  Motivation→계약→구현→검증/backlog 발표 문법),
  `wiki/meta-harness-and-prompt-assembly-2026-07-31.md`
  (Eco² research→CI→image/manifest→ArgoCD reconcile, GEODE
  GAP→preflight/CI→protected release, 실제 system prompt XML 조립 순서와
  local dump·구조 테스트),
  `wiki/geode-v1.0.11-documentation-reinforcement-strategy-2026-08-01.md`
  (v1.0.10 기록 구조 감사→v1.0.11 session record·trajectory release 구현→
  공식 Pages·LLM wiki·13/18/27/29/30장 보강 순서와 acceptance gate),
  `wiki/sil-held-out-and-petri-rubric-2026-08-02.md`
  (2026-06-04 SIL 영상·현재 code·공개 eval-artifact 대조, Petri 22-dim
  rubric 구성, selection 10과 held-out 10의 서로 다른 판정 권한, 24·31장
  call-up/reduce 결정),
  `wiki/deck-role-evaluation-loop-2026-08-03.md`
  (면접 메일·seq=187 직무·최신 공식 자료를 기준으로 37장 활성 덱을
  채점한 100점 루브릭, 전수 판정, P0/P1 수정 queue와 승격 gate),
  `wiki/geode-v1.0.12-full-cycle-deck-callup-2026-08-04.md`
  (v1.0.12 Tau2 278-task full cycle의 score·behavior·trajectory·release
  권한 경계, 12·13·18·21·22·27·28·34–35장 call-up/keep 판단),
  `wiki/geode-runtime-faithful-tau2-handoff-2026-08-04.md`
  (Tau2 adapter의 production wiring·deferred tool result·native verdict·
  retry lineage 결손과 benchmark-safe runtime profile, acceptance gate),
  `wiki/evolution-kiki.md`·`wiki/evolution-reode.md`(발전사 + 피드백→개선 축)
- 채점·루브릭 학술 계보: `wiki/eval-rubric-lineage.md` (BARS/CUSUM/McNemar → HealthBench/RaR/Petri 정합)
- Petri 심층: `wiki/petri-judge-reliability.md` (루브릭 제작·시뮬레이션→평가 연결·judge 신뢰성 — Anthropic/Inspect 1차 자료)
- 면접 메일 원문: `source/2026-07-28-interview-notice-mail.md`
- 발표 호흡 근거: `wiki/reference-talk-rhythm.md`
- Stanford CS329A Course Overview의 Agent Workflow 공개 baseline, 42–52분
  구간의 workflow/agent·generator/verifier 경계, Eco²→GEODE→SIL/Crucible
  투사와 7·8·28·30장 반영 결정:
  `wiki/stanford-cs329a-agent-workflow-baseline-2026-08-05.md`
- Stanford CS329A Test-Time Compute Scaling Part 2의 63분 전문·자동 자막·
  contact sheet 보존, repeated-sampling power law·generation-verification
  gap·compute-optimal allocation·Archon inference-program search의 전체
  전개와 Eco²·GEODE·SIL·Crucible 적용 경계:
  `wiki/stanford-cs329a-test-time-compute-part2-2026-08-05.md`
- Stanford CS329A 공개 플레이리스트 9부작의 전체 자동 자막·60초 contact
  sheet·metadata 보존, verification→feedback→planning→RL→search→long-horizon
  evaluation→open-ended loop의 강의별 상세 해설과 재사용 스킬:
  `wiki/stanford-cs329a-self-improving-agents-course-2026-08-05.md`,
  `.agents/skills/apply-self-improving-agent-systems/SKILL.md`
- Eco²의 graph-owned routing에서 GEODE의 model proposal·runtime admission·
  verify·promotion policy 분리로 이어지는 코드 기반 재프레이밍, 기존
  `session_events`→trajectory projection의 정당성, v1.0.13 worktree 판정과
  policy provenance 최소 보강 순서:
  `wiki/policy-trajectory-reframing-2026-08-05.md`
- Palantir의 2026-08-03 AI sovereignty 스탠스, Q2 주주서한 인용 교정,
  model·Ontology/Action·permission·observability·eval·post-training
  control stack과 GEODE runtime/evidence plane의 정렬·과장 경계:
  `wiki/palantir-ai-sovereignty-runtime-control-2026-08-05.md`
- 한국 기업 AI 발표 문법과 시각화 선택표:
  `wiki/korean-enterprise-ai-presentation-grammar.md`
- 기술 보고서·한국 기업 발표·프런티어 엔지니어링 자료의
  evidence-led 제목 문법과 1·22장 적용:
  `wiki/evidence-led-head-message-grammar-2026-07-31.md`
- 프런티어 시스템 보고서·LG AI Research·EXAONE 표지의 시각 문법 대조와
  v26 표지 결정:
  `wiki/cover-visual-alignment-2026-08-01.md`
- 35장 전수 렌더에서 확인한 제목 낱말 절단·label/connector·label/border·
  image/region 충돌 사례와 이를 차단하는 실행형 시각 회귀 게이트:
  `wiki/deck-visual-slop-regression-2026-08-01.md`
- 두 개발 영상과 2025-12~2026-03 `잡담` intent ledger에서 추출한
  개발 동기·작업 원칙, 35장 head-message 결정표와 편집 규칙:
  `wiki/deck-motivation-philosophy-revision-plan-2026-07-31.md`
- 로컬 제목 교정 스킬:
  `.agents/skills/write-evidence-head-messages/SKILL.md`
- observe→verify→failure contract 작업 규율:
  `.agents/skills/practice-observe-verify-engineering/SKILL.md`
- **모든 수치·주장에 근거 병기**: 파일 경로 / 커밋 / URL. 근거 없으면 싣지 않는다
- **검증 등급 태그**: `[실측]`(직접 확인) / `[문서주장]`(레포 문서상 주장, 미재현) / `[미검증]`
- GEODE 정직성 패스 준수: 죽은 주장(G1-G4, Cross-LLM α≥0.67, Expert Panel 등) 금지. confidence는 관찰용
- 수집 관점: 발표의 주축은 **Agent Workflow 직무 적합성**이다. Data Governance는 면접관 관점의 보조 축으로 quality·audit·lineage·access 근거에만 반영한다

## LLM wiki 검증

새로운 외부 조사를 반영할 때는 다음 순서를 지킨다.

1. 회사 방향은 공식 페이지·공식 저장소·기술 보고서에서 확인한다.
2. 업계 맥락은 논문·공식 기술 문서 등 1차 자료로 교차 검증한다.
3. 문장마다 `[직접근거]`, `[외부연구]`, `[해석]`의 경계를 표시한다.
4. 링크와 로컬 문서 참조를 확인한 뒤 Markdown render lint를 실행한다.

```bash
python3 ~/.codex/skills/lg-agent-workflow-assessment/scripts/audit_research_wiki.py \
  presentation/wiki/exaone-agent-rd.md \
  presentation/wiki/frontier-agent-engineering-2026.md \
  presentation/wiki/lg-research-after-seq636.md \
  presentation/wiki/kimi-k2.5-agent-swarm.md \
  presentation/wiki/evaluation-guided-scaffold-search.md \
  presentation/wiki/bounded-harness-control-2607.25415.md \
  presentation/wiki/hyperagents-2603.19461.md \
  presentation/wiki/narrative-evaluation-guided-geode.md \
  presentation/wiki/agentic-engineering-influences-and-geode-origin-talk.md \
  presentation/wiki/creator-persona-narrative-audit-2026-07-30.md \
  presentation/wiki/deck-visual-narrative-audit-2026-07-30.md \
  presentation/wiki/deck-restructure-2026-07-30.md \
  presentation/wiki/deck-restructure-2026-07-31.md \
  presentation/wiki/k-exaone-2.0-solar-open-2-comparison-2026.md \
  presentation/wiki/k-exaone-2.0-agent-workflow-opportunity-2026-07-31.md \
  presentation/wiki/geode-v1.0.10-motivation-control-boundaries-2026-07-31.md \
  presentation/wiki/geode-v1.0.11-documentation-reinforcement-strategy-2026-08-01.md \
  presentation/wiki/evidence-led-head-message-grammar-2026-07-31.md \
  presentation/wiki/deck-motivation-philosophy-revision-plan-2026-07-31.md \
  presentation/wiki/cover-visual-alignment-2026-08-01.md \
  presentation/wiki/palantir-ai-sovereignty-runtime-control-2026-08-05.md \
  presentation/wiki/stanford-cs329a-self-improving-agents-course-2026-08-05.md

${HOME}/workspace/geode/.venv/bin/pymarkdown \
  -c presentation/.pymarkdown.json scan \
  presentation/*.md presentation/design/*.md presentation/wiki/*.md
```

## 현재 덱 작업 핸드오프

다른 세션은 이 절을 읽고 시작한다. 현재 편집 SoT는
`slides/slides-v3.js`와 `slides/styles.css`다. 화면 번호와 렌더 순서는
`slideData` 전체가 아니라 파일 하단 `presentationOrder`의 37개 ID를
기준으로 확인한다.

### 현재 v34 활성 구조

- 본편: 37장
- 편집 게이트: 문장형 head message + 직접 연결된 근거 도식,
  narrative body 12pt 이상, `ink·gray·LG magenta` 3색 계열
- 서술 게이트: `.agents/skills/writer-flow/SKILL.md`를 진입점으로
  page job→pressure→mechanism→consequence를 정렬하고, title·thesis·figure가
  같은 판단 기준을 공유하는지 검사
- 도식 게이트: label–border·label–connector 8px 안전 간격,
  node 아래에서 사라지는 connector와 text를 관통하는 edge 금지
- 활성 순서: `slides/slides-v3.js::presentationOrder`
- 01: 넓은 action search space를 observation·state transition·trajectory로
  축적하고, evaluator가 keep/revert와 다음 탐색 경계를 판정하는 표지
- 02: 11개월 프로젝트 timeline
- 03: 2025-12~2026-07 intent ledger에서 추출한
  code/action supply와 verification·root-cause capacity의 정성적 격차
- 04: 작은 action→external observation→artifact→replay→verdict와
  failure→contract→Git revision의 observe–verify ratchet
- 05: Eco² research→ADR→CI/image→ArgoCD와
  GEODE GAP→contract→preflight→protected release의 meta-harness 비교
- 06: `UserPromptSubmit`→effective `ToolCallRequest`→`VerifyResult`의
  input·action·output contract와 cross-cutting safety authority
- 07: Eco² `list[Send]` fan-out→typed reducer→required-context join,
  구현 metric·structured log·measurement backlog의 경계
- 08: Eco² graph-owned path에서 GEODE의 model proposal→runtime admission→
  verifier decision→gate promotion으로 확장된 policy ownership
- 09: `ACT→OBSERVE→VERIFY/TERMINATE→REPLAN`의 실행 폐루프. Sequence
  connector는 actor lifeline 또는 activation boundary에 직접 결속
- 09: RUN 섹션 시작. action→observation→bounded replan과 closed terminal
- 10–11: 고정 system prompt prefix와 turn-resolved XML assembly,
  provider·surface·memory·verify·plan 조건부 삽입
- 13–20: context·capability·subagent·observability·finalization에서
  `failure signal→contract→verification/backlog`
- 20–21: Eco² Swiss Cheese Eval에서 GEODE Verify/Replan·finalization
  control로 넓어진 Evaluation / Verify 경계
- 18: v1.0.13의 session·turn·call identity로 canonical behavior와 operational
  telemetry를 분리하고, resolved policy snapshot은 남은 계약으로 표시
- 22: v1.0.12 full-cycle resolved assay config, native `200/278`,
  51,985 `session_events`, 3,964 internal call/ACK pairing을 manifest에
  결속하고 score·behavior·policy·replay claim authority를 분리하는 Evidence Admission
- 23–27: Petri interaction audit와 τ²·MCPMark environment completion을
  분리한 Simulator / Benchmark 경계와 실측
- 27: GPT-5.4 subscription/high의 `geode_agent + geode_user`, base 278개,
  `k=1` diagnostic profile. Airline 42/50, Retail 79/114, Telecom 79/114이며
  official leaderboard로 표현하지 않는다.
- 28: native score는 evaluator, canonical behavior는 runtime, named-state
  변경은 gate가 소유하는 External Loop authority boundary
- 29–35: bounded scaffold surface→계산 연산자와 write authority 분리→
  artifact handoff→수치 gate→SIL/Crucible
- 30: same-task best-of-N과 반복 측정은 결과·ledger에만 쓰고,
  named state는 `(1+1)`·sealed gate만 바꾸는 Goodhart control
- 31: 실패 trajectory를 15개 adversarial draft로 변형해 미탐색 failure
  branch와 audit headroom을 넓히고, Elo·Petri pilot·proximity dedup으로
  Top-5를 선별한 뒤 한 JSON section만 수정 후보로 노출
- 32: 22개 raw 측정값을 보존한 채 full aggregate의 신호 희석을
  targeted ICC sub-fitness로 교정하고 full-surface veto를 유지한 baseline 발전
- 33: mutation LLM에 숨긴 held-out 10개를 ledger-only monitor로 쓰되,
  반복 노출·nonfatal·runtime overlap guard 부재 때문에 일반화 보증이나
  sealed test로 부르지 않는다.
- 35: Crucible r14의 train `0.500→0.833` KEEP이 disjoint one-shot sealed에서
  REJECT된 관측 사례. Crucible은 Goodhart 알고리즘이 아니라
  train proxy와 release authority를 분리한 통제 구조다.
- 37: 특정 모델 연계를 전제하지 않고 model·prompt·visible tools·runtime/verify
  policy identity를 request→isolated run→trajectory→verifier→gate→Human
  release 경로에 결속하는 기여 가설
- 대본: `talk-script-20min.md`
- Claim/편집 SOT:
  `wiki/geode-v1.0.10-motivation-control-boundaries-2026-07-31.md`
- 섹션 반전: 05 BUILD · 09 RUN · 17 OBSERVE · 20 EVALUATE · 23 SIMULATE / BENCHMARK ·
  28 EVOLVE · 36 TRANSFER의 첫 화면에만 dark field를 적용
- 본문 흐름: OPEN 01–04 → BUILD 05–16 → OBSERVE 17–19 →
  EVALUATE / VERIFY 20–21 → EVIDENCE ADMISSION 22 →
  SIMULATE / BENCHMARK 23–27 → EVOLVE 28–35 → TRANSFER 36–37
- 렌더: `slides/.render-check-v34/`
- 최근 검증: 37장, viewport·header/visual/footer·SVG text·label/connector 충돌 0

### 이전 v14 핸드오프 (폐기·근거 추적용)

- 화면 27 제목:
  `ReAct의 실행 환경이 전산 상태였기에 τ²를 택했습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-25"`
- 스타일: `styles.css`의 `.v12-tau2*`
- 근거:
  `source/research/tau2-bench-2506.07982.pdf`,
  `wiki/geode-context-engineering.md` §12.2,
  GEODE `plugins/benchmark_harness/tau2_geode_agent.py`와
  `tau2_turn_supervisor.py`
- 시각 문법: 왼쪽은 single-control→dual-control의 측정 대상 변화,
  오른쪽은 τ² evaluator와 GEODE candidate의 ownership boundary다.
  Telecom만 새 dual-control domain이며 Airline/Retail에 같은 구조를
  소급하지 않는다. K‑EXAONE·EXAONE 4.5 표기는 동일 구현 주장이 아니라
  공개 Agentic Tool Use 평가 방향의 정렬만 뜻한다.
- 화면 30 제목:
  `하네스 전체가 아니라 7개 조정면만 실험 대상으로 열었습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-28"`
- 스타일: `styles.css`의 `.v12-levers*`
- 근거:
  `wiki/bounded-harness-control-2607.25415.md`의
  `GEODE의 일곱 변경 표면과 대응`,
  GEODE `core/self_improving/loop/mutate/policies.py::TARGET_KINDS`
- 시각 문법: 외부 연구 3개는 압축한 experiment grammar에만 연결하고,
  오른쪽은 frozen execution plane 안의 7개 JSON behavior key를
  editable surface로 표시한다. `hyperparam`, `retrieval`, runtime
  source는 닫힌 표면으로 남긴다.
- 화면 08 제목:
  `긴 추론 대신 행동과 관측을 짧게 닫았습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-07"`
- 스타일: `styles.css`의 `.v6-sequence*`, `.v11-sequence*`
- 렌더 확인: `slides/.render-check-v14/slide-08.png`
- 화면 09 제목:
  `한 바이트가 달라지면, 캐시는 그 뒤를 재사용하지 못합니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-08"`
- 스타일: `styles.css`의 `.v16-cache-prefix*`
- 렌더 확인: `slides/.render-check-v14/slide-09.png`
- 화면 10 제목:
  `고정 prefix 뒤에서, 실행 상태가 모델이 볼 문맥을 결정합니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-08-materialized"`
- 스타일: `styles.css`의 `.v15-prompt-instance*`
- 렌더 확인: `slides/.render-check-v14/slide-10.png`
- 근거:
  `wiki/geode-context-engineering.md` §5,
  GEODE `core/agent/system_prompt.py`, `core/agent/loop/_context.py`,
  `core/agent/prompt_dump.py`, `core/llm/adapters/registry.py`
- 실측: local `main@440bd3e7`에서 `gpt-5.5 / cli` dump는 18,588자,
  추정 4,647 token, duplicate tag 0건이다. Registry는 adapter provider
  3개, concrete source 3개와 built-in adapter 8개를 등록한다.
- 시각 문법: 화면 09는 세 요청에서 글자·공백·순서까지 같은 prefix와
  달라지는 tail을 겹쳐 보여준다. Anthropic `cache_control=1h`, OpenAI
  `prompt_cache_key=hash(prefix)`, artifact의 cache read 관측을 함께
  표기하되 이 split 단독의 hit-rate 상승률로 읽히지 않게 한다. 화면
  10은 `MODEL ID/INTERACTION CONTRACT/SURFACE`로 고정한 XML instance와
  provider·verify·plan 분기만 맡는다. 검은 코드 패널 대신 밝은 XML
  syntax rail을 사용하고, 우측 조건은 `SIGNAL/STATE/OUTPUT` 고정 열로
  맞춘다. `current_date`는 OpenAI 계열에서 생략되고 Anthropic·GLM에는
  주입된다.
- 화면 21 제목:
  `실패를 규약으로 내리고 Git revision으로 고정했습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-19"`
- 스타일: `styles.css`의 `.v12-failure-contract*`
- 렌더 확인: `slides/.render-check-v14/slide-21.png`
- 근거: `wiki/geode-codebase-atlas.md`의 G1.1·G1.2
- 시각 문법: deterministic failure는 minimum contract→source+test→
  revision ratchet으로, 의미가 열린 failure는 simulation/Judge lane으로
  분리한다. Test 실패는 baseline·SoT·ref를 전진시키지 않는다.
- 화면 23 제목:
  `행동 차단과 제품 승격을 같은 평가 권한으로 두지 않았습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-21"`
- 스타일: `styles.css`의 `.v12-eval-scope*`
- 렌더 확인: `slides/.render-check-v14/slide-23.png`
- 근거:
  GEODE `ToolExecutor._gate_async`, `VerifyResult`,
  `wiki/geode-trajectory-judgment.md`의 SIL·Crucible·Human 권한 경계
- 시각 문법: tool call→turn→run→revision pair→product로 evidence
  scope를 확대하되, automated authority는 release cut 앞에서 끝낸다.
- 화면 24 제목:
  `Agent 평가도 무엇을 환경으로 삼는지가 다릅니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-22"`
- 스타일: `styles.css`의 `.v13-sim-systems*`
- 렌더 확인: `slides/.render-check-v14/slide-24.png`
- 근거:
  [Petri 공식 리포트](https://alignment.anthropic.com/2025/petri/),
  `source/research/tau2-bench-2506.07982.pdf`,
  [MCPMark arXiv:2509.24002](https://arxiv.org/abs/2509.24002)
- 시각 문법: Petri의 seed→adaptive auditor loop→transcript→Judge,
  τ²의 user·agent→shared world→task verifier, MCPMark의 curated
  initial state→MCP tool loop→final state→programmatic verifier를
  같은 execution→artifact→verdict 좌표에 놓되 점수를 합산하지 않는다.
- 화면 31 제목:
  `판정에는 trajectory 전체가 아니라 검증된 수치 투영만 넣었습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-29"`
- 스타일: `styles.css`의 `.v14-sil-projection*`
- 렌더 확인: `slides/.render-check-v14/slide-31.png`
- 화면 32 제목:
  `같은 실험 문법을 서로 다른 비교군과 쓰기 권한으로 통제했습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-30"`
- 스타일: `styles.css`의 `.v14-experiment-compare*`
- 화면 33 제목:
  `판정은 통과 조건과 바뀔 수 있는 상태를 함께 고정했습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-31"`
- 스타일: `styles.css`의 `.v14-verdict-grid*`
- 렌더 확인: `slides/.render-check-v14/slide-33.png`
- 화면 34 제목:
  `Failure artifact로 한 JSON section 후보만 만들었습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-32"`
- 스타일: `styles.css`의 `.v14-artifact-montage*`
- 렌더 확인: `slides/.render-check-v14/slide-34.png`
- 화면 37 제목:
  `업무 Agent가 결과와 실행 증거를 함께 남기게 하고, 그 trajectory로 다음 workflow와 모델을 더 빨리 검증하겠습니다`
- 소스: `slides/slides-v3.js`의 `id: "slide-36"`
- 스타일: `styles.css`의 `.v11-authority-frontier*`
- 렌더 확인: `slides/.render-check-v14/slide-38.png`
- 근거:
  `wiki/hyperagents-2603.19461.md`의 claim ledger와 수정 표면 비교
- 시각 문법: 31은 artifact boundary, 32는 공통 전이 kernel과 대조
  설계, 33은 함수 순서와 상태 전이, 34는 세 하위 시스템 사이의
  artifact handoff를 맡는다. 37은 K‑EXAONE 2.0의 공개 capability 신호를
  JD의 내부 Agent application vertical과 연결하고, 실행 trajectory를
  regression/eval·후속 학습 후보로 정제하는 확장 경로를 그린다. 직무와
  특정 EXAONE 모델의 직접 연결은 확정하지 않는다.
- 권한 경계: Crucible `KEEP`은 private search ref만 바꾸며 sealed
  `ELIGIBLE`에도 제품 release 권한이 없다. SIL과 Crucible 사이에 자동
  candidate handoff가 있다는 뜻이 아니다.

### 슬라이드 31–33 직접 근거

검증 revision은 GEODE
`cabff1adb7bcae94a3a0cb06fe43aaf618cfff89`, 공개 eval artifact
`e9ce94dd33c5c1a05ac4d9263d74816846fe5851`이다.

| 표시 내용 | 코드·artifact 근거 |
|---|---|
| Petri 22 rubric → 18 fitness taxonomy → 15 weighted + stability | `plugins/petri_audit/judge_dims/geode_judge_subset.yaml`, `core/self_improving/fitness.py` |
| `targeted_dims`는 weighted 15의 부분집합이며 ICC reshape한 sub-fitness | `core/self_improving/ledger.py`, `core/self_improving/fitness.py`, `core/self_improving/gate.py` |
| 17→20→targeted→18 발전사 | GEODE `59feb756`, `17e410a29`, `b22969dcd`, `a0ee62a77`; eval artifact 2026-05-12·15·19 reports |
| SIL `.eval`의 mean·stderr·sample row와 hard veto | `core/audit/dim_extractor.py`, `core/self_improving/fitness.py`, `core/self_improving/gate.py` |
| `RunTranscript`는 lifecycle·재현·진단 원장이고 gate의 수치 입력이 아님 | `core/self_improving/loop/observe/run_transcript.py`, `core/self_improving/measure.py`, `core/self_improving/gate.py` |
| `promote` 뒤 baseline 갱신, `reject` 뒤 `previous_value` 복원 | `core/self_improving/train.py`, `core/self_improving/gate.py` |
| 공통 controlled-transition 표기와 SIL async-first control의 실제 경계 | `core/self_improving/campaign.py`, `core/self_improving/train.py`, `plugins/crucible/evidence.py`, `plugins/crucible/promotion.py` |
| Crucible raw trajectory의 identity·coverage·safety·paired effect | `plugins/crucible/tau2_live.py`, `plugins/crucible/verifiers/tau2.py`, `plugins/crucible/promotion.py` |
| `KEEP`만 private search ref 전진, `REJECT/INVALID`는 유지 | `plugins/crucible/supervisor.py`, `plugins/crucible/ref_journal.py` |
| sealed `ELIGIBLE`에도 release authority 없음 | `plugins/crucible/sealed.py`, `plugins/crucible/program.md` |
| Proximity는 cluster를 만들고 survivor dedup은 Ranker 뒤 Elo·Pilot로 수행 | `plugins/seed_generation/orchestrator.py`, `plugins/seed_generation/dedup.py` |
| Seed pool→Petri→SIL은 단일 함수 체인이 아니라 file pointer와 eval artifact handoff | `plugins/seed_generation/orchestrator.py`, `core/self_improving/train.py`, `core/self_improving/measure.py` |

해설과 claim boundary는
`wiki/geode-trajectory-judgment.md`의 **Baseline은 어떻게 추출되고
gate는 무엇을 비교하는가**와 **판정 뒤에는 무엇이 실제로 바뀌는가**를
우선한다. 현재 코드·테스트·commit-pinned artifact가 이 위키와
포트폴리오 PDF보다 우선한다. 포트폴리오 44쪽의 “18개 dim이 fitness
가중”은 현재 코드 기준 `18개 taxonomy / 15개 weighted / 3개 info`로
교정한다.

### 재검증

```bash
python3 presentation/slides/validate.py

NODE_PATH=${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  ${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  presentation/slides/render-check.cjs

${HOME}/workspace/geode/.venv/bin/pymarkdown \
  -c presentation/.pymarkdown.json scan \
  presentation/*.md presentation/design/*.md presentation/wiki/*.md
```

## 진행 상태

- [x] 스캐폴드 생성
- [x] wiki 수집 완료 (2026-07-29, 역할 조사 + 프로젝트 5종)
- [x] EXAONE 공개 구현·LG 기술 보고서·Agent Workflow 원문 17건 로컬 보존 및 출처 대장 갱신
- [x] strategy.md — 슬라이드 맵 16장 + 수치 발화표 + 지뢰 15종 + Q&A 뱅크 + 면접 전 액션
- [x] `design/lg-ai-research-visual-system.md` — 화이트페이퍼 기반,
      `#513FF3` 기술 강조 + `#EC297B` 제한적 브랜드 큐. `design.md`의
      다크 안은 폐기된 이력 초안으로만 보존
- [x] `design/paper-diagram-visualization-taxonomy.md` — 논문형 구조·과정·
      정량·평가·실험 시각화 분류와 16장 슬라이드별 권장 문법
- [x] progress-audit.md — 자료 보존 상태·누락·HEAD 수치 규약·12장 내러티브 v2
- [x] 축 보강 수집 (2026-07-29): skill 2종 + 발전사 3종 +
      reode.md Q&A 근거 복원 + 메일 원문 보존
- [x] GEODE context engineering: PDF v1.0.0과 현재 v1.0.3의
      prompt·budget·state·resume wiring, trajectory 기반 prompt 조립 대조
- [ ] GEODE 코드베이스 G0~G9 전수 감사:
      `wiki/geode-codebase-atlas.md`에서 PDF 88쪽과 current code·test·
      eval artifact를 교차 추적
- [x] seq=636 이후 공개 연구·제품·채용 신호 추적 및 출처 대장
- [x] 공식 웹·기술 보고서 실측 기반 LG AI Research 시각 시스템
- [x] 본편 23장 연속 내러티브 HTML 구조와 렌더 검사
- [ ] 면접 전 액션 아이템 (strategy.md §6 — Slack 스크린샷, 로고 확보)
- [x] OpenClaw·autoresearch·Anthropic 영향 계보 → 두 하네스 → Eco² →
      GEODE 순의 본편 23장 구조 확정
- [ ] 발표용 핵심 자산 수집 및 출처 고정
- [x] Eco² workflow→GEODE runtime→Petri→eval artifact→승격 권한의
      검증된 콘텐츠·도표 주입
- [ ] PPTX 빌드 → 게이트 4종 검증 → 제출본
- [ ] 20분 리허설 2회 + 40분 Q&A 방어 점검
