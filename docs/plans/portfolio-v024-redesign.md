# portfolio-v024-redesign

## 목적
배포된 GEODE 포트폴리오(v0.8.0 디자인)의 CSS/레이아웃/애니메이션을 보존하면서, 콘텐츠를 v0.24.0 기준으로 전면 교체.

## 파일
- **원본(디자인 기준)**: `resume/portfolio/public/geode.html` (9,421줄, v0.8.0)
- **현행 5-Slide 버전(보존)**: `resume/portfolio/geode.html` (resume 스타일, 배포하지 않음)
- **작업 결과물**: `resume/portfolio/public/geode.html` 덮어쓰기 → GitHub Pages 자동 배포

## 배포된 v0.8.0 구조 (8 섹션)

| # | 섹션 | 현재 콘텐츠 (v0.8.0) | 교체 콘텐츠 (v0.24.0) |
|---|------|---------------------|---------------------|
| 00 | Agentic Engineering | 6 원칙 카드 (21 tools, 5 LLM, 10 rounds) | 5축 하네스 엔지니어링 (46 tools, 42 MCP, 36 hooks) + Karpathy/Beck 프레이밍 |
| 00 | Agent Reasoning Flow | while(tool_use) 루프 + Cowboy Bebop 예시 | AgenticLoop + Sub-Agent 병렬 위임 + 3사 LLM Failover |
| 01 | Agent Architecture | 6-Layer (L1-L5, 11 Hook) | 6-Layer 갱신 (L0-L5, 36 Hook) + geode serve Gateway + 5-Layer Context Hub |
| 02 | Causal Scoring (Game Domain) | 14-Axis PSM + 3 Fixture (Berserk 82.2, CB 69.4, GitS 54.0) | Game IP 도메인 플러그인으로 프레이밍 — DomainPort Protocol 교체 가능한 DAG, 수치 갱신 (81.2/68.4/51.7). portfolio/geode PPTX+HTML 참고 |
| 03 | Self-Correction | G1-G4 + BiasBuster + Cross-LLM (Claude/GPT-4/Gemini) | 5-Layer Verification + Cross-LLM (Claude×GPT, Krippendorff α ≥ 0.67) |
| 04 | Multi-Agent Coordination | Sub-Agent + 3-Tier Memory + Plan Mode + 11 Hook | Sub-Agent (CoalescingQueue+TaskGraph+IsolatedRunner) + 5-Layer Context Hub + 36 Hook |
| 05 | Self-Improvement | CUSUM + RLAIF + Feedback Loop 5-Phase | 유지 (대부분 동일) |
| 06 | Multi-LLM Ensemble | 5 LLM (Opus 4.5, GPT-5.2, Gemini 3.0) + 21 tools | 3사 Failover (Opus 4.6/Sonnet 4.6, GPT-5.4, GLM-5) + 46 tools + 42 MCP + Security Envelope |
| 07 | Timeline | v0.6.0 ~ v0.9.0 | v0.6.0 ~ v0.24.0 핵심 마일스톤 |

## Hero 섹션 변경
- 제목: "Autonomous IP Discovery Agent" → "범용 자율 실행 에이전트 하네스"
- 부제: "모델 능력이 상수일 때, 변수는 오케스트레이션의 구조입니다"
- 수치 배지: 21 tools → 46 tools, 5 LLMs → 3 Providers, 10 rounds → 50 rounds, 14 PSM → 182 modules

## 프레이밍 (PPTX 검증 완료)
- "모델 능력이 상수일 때, 변수는 오케스트레이션의 구조입니다"
- "제어 없는 확률적 시스템은 발산한다"
- "입력의 정밀도가 출력의 상한을 결정한다"
- "v1이 정상 경로를 구현, v2는 장애 경로까지 설계"
- Karpathy: 확률적 시스템의 제어 평면 필요성
- Beck: "테스트 없는 코드는 레거시 코드다", "모든 설계는 트레이드오프다"

## 신규 추가 콘텐츠

### 핵심 서사 (v0.8.0에 없던 것)
- **DomainPort → REODE 피봇**: 게임 IP → 범용 하네스 → 코드 마이그레이션 도메인 이식, 실제 산업 현장 레거시 Java 마이그레이션에 도입 운영 중
- **REODE 재설계 상세**: DomainPort 삭제 → PipelineTemplate(L1) + LanguageAdapter(L2) 2-Protocol 직교 분리, DI 3점, 그래프 정의 L0→L1 이동
- **Cross-Project Loop**: Eco²→GEODE→REODE 패턴 전이 테이블 (메모리, 평가, 컨텍스트, Resilience, 루프 제어)

### 시스템 신규
- **geode serve Gateway**: Slack 데몬, ChannelBinding, LaneQueue, Echo Prevention 3중
- **Security Envelope**: Secret Redaction 8패턴, Bash 3-Layer, PolicyChain 6-layer, Tool permission 3단계(STANDARD/WRITE/DANGEROUS)
- **MCP 42 카탈로그**: 병렬 연결 110s→15s, Deferred Loading, Singleton MCPServerManager
- **5-Layer Context Hub (C0-C4)**: System Prompt → Org → Project → Session → User Profile, Context Compaction (80% WARNING → Haiku 압축)
- **Sub-Agent 메모리 격리**: 부모 스냅샷 읽기 전용, task_id 스코프 버퍼, summary만 병합
- **장애 시나리오 7건**: 네트워크 다운, CI 타임아웃, 메모리 부패, Confidence 미달, LLM 전체 장애, MCP 실패, .owner 부재

### REODE 관련 (포트폴리오에 섹션 추가 검토)
- **Migration Scorecard 3-Tier**: 5 Gate(Reward Hacking 방지) + S/A/B/C 4등급 + Insight
- **Fix Node**: Explore→Reason→Act 재귀 수정, 수렴 감지(동일 에러 3회 → 에스컬레이션)
- **AgentRole 4종**: ARCHITECT(Opus)/ENGINEER(Sonnet)/REVIEWER(Haiku)/SCOUT(Haiku) 노드별 비용 라우팅
- **OpenRewrite(결정적 70%) + LLM(확률적 30%)**: 확률적 시스템 개입 범위 최소화

### 외부 하네스 구축 (5축)
- Claude Code(.claude/ Skills·Hooks·CLAUDE.md)로 GEODE를 생산
- harness-for-real: 4-Phase FSM, Backpressure hooks, LEARNINGS.md 축적, Token budget 자동 정지
- GEODE→REODE 2-Protocol 재설계로 클라이언트 납품

## 산출물 구분

| 매체 | 파일 | 용도 | 상태 |
|------|------|------|------|
| **Web (GitHub Pages)** | `resume/portfolio/public/geode.html` | 배포 포트폴리오 — v0.8.0 디자인 보존 + v0.24.0 콘텐츠 | Backlog |
| **PPTX** | `portfolio/geode/GEODE-Portfolio.pptx` | 발표/공유용 — 33 슬라이드 | Backlog (수치 갱신) |
| **5-Slide HTML (보존)** | `resume/portfolio/geode.html` | resume 스타일 — 배포하지 않음 | 보존 |

## PPTX Outdated (12건)

| 파일 | 현재값 | 정확값 |
|------|--------|--------|
| s00-cover.html | 178 modules | **182** |
| s00-cover.html | 2930+ tests | **3,055+** |
| s01-intro.html | 178 모듈, 21 릴리스 | **182 모듈, 25+ 릴리스** |
| s13-results.html | Berserk 81.3 | **81.2** |
| s13-results.html | GitS 51.6 | **51.7** |
| s16-summary.html | 184 modules | **182** |
| s16-summary.html | 3058+ tests | **3,055+** |
| s16-summary.html | 24 releases | **25+** |
| s17-tools.html | 48 tools (2곳) | **46** |
| s19-skills.html | 21+ skills | **25** |
| s20-mcp.html | 42 MCP servers | **43 catalog** |

## CSS/디자인 보존 규칙
- `:root` CSS 변수 전체 유지 (Deep Sea Discovery Theme)
- 섹션 구조 (`section.slide`, `.hero`, `.nav`) 유지
- 애니메이션/트랜지션 유지
- 반응형 breakpoint (768px, 480px) 유지
- 폰트 (Inter, Fira Code, Noto Sans KR) 유지
- 한/영 토글 유지

## 작업 순서
1. `portfolio/public/geode.html` 백업 (`geode-v080.html`)
2. CSS `<style>` 블록 + `<script>` 블록 그대로 보존
3. `<body>` 내 HTML 콘텐츠만 섹션별 교체
4. 브라우저에서 레이아웃 확인
5. resume 레포 커밋 + 푸시 → GitHub Pages 배포
