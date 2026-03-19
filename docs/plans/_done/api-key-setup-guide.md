# GEODE API 키 발급 가이드

> 우선순위별 정리. 각 단계는 클릭 + 로그인만으로 완료 가능.
> 발급 후 `.env`에 추가하면 즉시 동작.
> 키 불필요한 MCP (wikidata, playwright, steam-reviews)는 설정만으로 즉시 사용 가능.

## .env 추가 형식

```env
# === Priority 1: Gaming + Search + Social ===
TWITCH_CLIENT_ID=...
TWITCH_CLIENT_SECRET=...
BRAVE_API_KEY=BSA...
YOUTUBE_API_KEY=AIza...
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
TAVILY_API_KEY=tvly-...
EXA_API_KEY=...
DISCORD_BOT_TOKEN=...

# === Priority 2: Agent Infra ===
E2B_API_KEY=e2b_...

# === Priority 3: 개발/모니터링 ===
SENTRY_AUTH_TOKEN=sntrys_...
NOTION_API_KEY=secret_...
FIRECRAWL_API_KEY=fc-...
```

---

## 키 불필요 — 설정만으로 즉시 사용 (3개)

다음 MCP는 API 키 없이 `mcp_servers.json`에 이미 등록되어 있어 바로 동작합니다.

| MCP | 용도 | GEODE 연결 |
|---|---|---|
| **wikidata** | IP 프랜차이즈/스튜디오/크리에이터 구조화 메타데이터 | router — IP 기본 정보 보강 |
| **playwright** | 브라우저 자동화 (SteamDB, VGInsights 크롤링) | signals — 동적 웹 데이터 수집 |
| **steam-reviews** | Steam 리뷰 감성 분석 | signals — community sentiment |

---

## Priority 1 — 게임 IP 파이프라인 직결 (8개)

### 1. IGDB (Twitch Dev 계정)

> **게임 메타데이터의 SSOT.** 장르, 플랫폼, 평점, 프랜차이즈 관계 조회.
> fixture 데이터를 실제 IGDB 데이터로 대체 가능.

| 항목 | 내용 |
|---|---|
| 무료 | 무제한 (Twitch dev 계정 무료) |
| URL | https://dev.twitch.tv/console |

**단계:**
1. Twitch 로그인 → https://dev.twitch.tv/console
2. **애플리케이션 등록** 클릭
3. 이름: `GEODE`, OAuth 리디렉트: `http://localhost`, 카테고리: **Application Integration**
4. **만들기** → Client ID 복사 → `.env`에 `TWITCH_CLIENT_ID=` 뒤에 붙여넣기
5. **새 시크릿** 클릭 → Client Secret 복사 → `.env`에 `TWITCH_CLIENT_SECRET=` 뒤에 붙여넣기

---

### 2. Discord Bot Token

> **팬 커뮤니티 활성도 측정.** 디스코드 서버 멤버 수, 메시지 빈도 = growth_potential 핵심 신호.

| 항목 | 내용 |
|---|---|
| 무료 | 무제한 |
| URL | https://discord.com/developers/applications |

**단계:**
1. Discord 로그인 → 위 URL
2. **New Application** → 이름: `GEODE` → **Create**
3. 좌측 **Bot** → **Reset Token** → 토큰 복사
4. **Privileged Gateway Intents** 아래 **Message Content Intent** ON
5. `.env`에 `DISCORD_BOT_TOKEN=` 뒤에 붙여넣기

---

### 3. Brave Search API

> 웹 검색. 현재 `mcp_servers.json`에 등록돼 있어 시작 시 에러 발생 중.

| 항목 | 내용 |
|---|---|
| 무료 | $5 크레딧/월 (~1,000 쿼리) |
| URL | https://brave.com/search/api/ |

**단계:**
1. 위 URL → **Get Started** 클릭
2. GitHub 또는 이메일로 가입
3. Dashboard → **API Keys** → **Create API Key**
4. `BSA...` 키 복사 → `.env`에 `BRAVE_API_KEY=` 뒤에 붙여넣기

---

### 4. YouTube Data API v3

> 유튜브 조회수/트렌드 수집. IP 성장 잠재력 분석에 사용.

| 항목 | 내용 |
|---|---|
| 무료 | 10,000 units/일 (검색 ~100회/일) |
| URL | https://console.cloud.google.com/ |

**단계:**
1. Google 로그인 → https://console.cloud.google.com/
2. 상단 프로젝트 선택 → **새 프로젝트** → 이름: `geode` → 만들기
3. 좌측 메뉴 **API 및 서비스** → **라이브러리**
4. `YouTube Data API v3` 검색 → **사용 설정**
5. 좌측 **사용자 인증 정보** → **사용자 인증 정보 만들기** → **API 키**
6. `AIza...` 키 복사 → `.env`에 `YOUTUBE_API_KEY=` 뒤에 붙여넣기

---

### 5. GitHub Personal Access Token

> GitHub 리포 조회, 이슈 관리, PR 자동화에 사용.

| 항목 | 내용 |
|---|---|
| 무료 | 무제한 |
| URL | https://github.com/settings/tokens?type=beta |

**단계:**
1. GitHub 로그인 → 위 URL
2. **Generate new token** 클릭
3. Token name: `geode-mcp`
4. Expiration: 90 days (또는 원하는 기간)
5. Repository access: **All repositories** (또는 특정 리포만)
6. Permissions: `Contents: Read`, `Issues: Read/Write`, `Pull requests: Read/Write`
7. **Generate token** → `github_pat_...` 복사 → `.env`에 붙여넣기

---

### 6. Tavily Search API

> AI 특화 웹 검색. Brave 대비 구조화된 결과 반환. Grounding 검증(G3)에 적합.

| 항목 | 내용 |
|---|---|
| 무료 | 1,000 크레딧/월 |
| URL | https://app.tavily.com/sign-in |

**단계:**
1. 위 URL → GitHub 또는 Google로 가입
2. Dashboard → API Key 자동 표시
3. `tvly-...` 키 복사 → `.env`에 `TAVILY_API_KEY=` 뒤에 붙여넣기

---

### 7. Exa AI Search

> AI 시맨틱 검색. "Berserk와 유사한 IP" 같은 개념 검색 가능.

| 항목 | 내용 |
|---|---|
| 무료 | 1,000 req/월 |
| URL | https://dashboard.exa.ai/signup |

**단계:**
1. 위 URL → Google 또는 이메일로 가입
2. Dashboard → **API Keys** → 키 복사
3. `.env`에 `EXA_API_KEY=` 뒤에 붙여넣기

---

### 8. E2B Sandbox

> 격리된 코드 실행. 통계 계산/데이터 분석을 안전한 샌드박스에서 실행.
> OpenClaw Sub-agent Spawn 패턴 + Claude Code 코드 실행 패턴 참조.

| 항목 | 내용 |
|---|---|
| 무료 | 100시간/월 |
| URL | https://e2b.dev/dashboard |

**단계:**
1. 위 URL → GitHub로 가입
2. Dashboard → **API Keys** → 키 복사
3. `e2b_...` 키 복사 → `.env`에 `E2B_API_KEY=` 뒤에 붙여넣기

---

## Priority 2 — 개발/모니터링 (3개)

### 9. Sentry

> 에러 모니터링. 프로덕션 배포 시 필요.

| 항목 | 내용 |
|---|---|
| 무료 | 5,000 errors/월 |
| URL | https://sentry.io/signup/ |

**단계:**
1. 위 URL → GitHub로 가입
2. 프로젝트 생성 → Platform: **Python**
3. Settings → **Auth Tokens** → **Create New Token**
4. `sntrys_...` 복사 → `.env`에 `SENTRY_AUTH_TOKEN=` 뒤에 붙여넣기

---

### 10. Notion API

> 문서 연동. 분석 결과를 Notion에 자동 저장할 때 사용.

| 항목 | 내용 |
|---|---|
| 무료 | 무제한 API, 3 req/초 |
| URL | https://www.notion.so/my-integrations |

**단계:**
1. Notion 로그인 → 위 URL
2. **새 통합** → 이름: `GEODE` → 워크스페이스 선택
3. **제출** → Internal Integration Secret 표시
4. `secret_...` 복사 → `.env`에 `NOTION_API_KEY=` 뒤에 붙여넣기

---

### 11. Firecrawl

> 웹 스크레이핑. IP 관련 웹페이지 구조화 추출.

| 항목 | 내용 |
|---|---|
| 무료 | 500 크레딧 (일회성) |
| URL | https://www.firecrawl.dev/app/sign-up |

**단계:**
1. 위 URL → Google 또는 GitHub으로 가입
2. Dashboard → API Key 표시
3. `fc-...` 복사 → `.env`에 `FIRECRAWL_API_KEY=` 뒤에 붙여넣기

---

## Priority 3 — 선택 사항 (4개)

### 12. Slack Bot Token

> 슬랙 알림. 분석 완료 시 채널에 알림 전송.

| 항목 | 내용 |
|---|---|
| 무료 | 무료 (워크스페이스 필요) |
| URL | https://api.slack.com/apps |

**단계:**
1. 위 URL → **Create New App** → **From scratch**
2. App Name: `GEODE`, Workspace 선택
3. 좌측 **OAuth & Permissions** → Scopes에 `chat:write` 추가
4. **Install to Workspace** → **허용**
5. **Bot User OAuth Token** (`xoxb-...`) 복사 → `.env`에 붙여넣기

---

### 13. Pinecone

> 벡터 DB. IP 임베딩 저장/검색. 대규모 IP 비교 시 사용.

| 항목 | 내용 |
|---|---|
| 무료 | 2GB, 2M writes/월 |
| URL | https://app.pinecone.io/signup |

**단계:**
1. 위 URL → Google 또는 이메일로 가입
2. Dashboard → **API Keys** → 키 복사
3. `.env`에 `PINECONE_API_KEY=` 뒤에 붙여넣기

---

### 14. Qdrant

> 벡터 DB (Pinecone 대안). 오픈소스 기반.

| 항목 | 내용 |
|---|---|
| 무료 | 1GB RAM, 4GB disk (영구) |
| URL | https://cloud.qdrant.io/ |

**단계:**
1. 위 URL → GitHub 또는 Google로 가입
2. **Create Cluster** → Free tier 선택
3. Cluster URL 복사 (예: `https://xxx.us-east4-0.gcp.cloud.qdrant.io:6333`)
4. API Key 생성 → `.env`에 `QDRANT_URL=` 뒤에 붙여넣기

---

### 15. Zep

> 대화 메모리 서버. 멀티턴 세션 기록 저장.

| 항목 | 내용 |
|---|---|
| 무료 | 1,000 에피소드/월 |
| URL | https://app.getzep.com/signup |

**단계:**
1. 위 URL → Google 또는 이메일로 가입
2. Dashboard → **API Key** 복사
3. `.env`에 `ZEP_API_KEY=` 뒤에 붙여넣기

---

## 비추천 — 비용 발생 (2개)

| 서비스 | 이유 | 대안 |
|---|---|---|
| **Twitter/X API** ($200/월) | 읽기 Basic $200/월. 무료는 write-only | Brave/Tavily로 트위터 검색 대체 |
| **Google Maps** (카드 필수) | 신용카드 등록 필수 | GEODE에 지도 기능 불필요 |

---

## 체크리스트

```
키 불필요 (즉시 사용)
[x] Wikidata — mcp_servers.json에 등록 완료
[x] Playwright — mcp_servers.json에 등록 완료
[x] Steam Reviews — mcp_servers.json에 등록 완료

Priority 1 (게임 IP 파이프라인)
[ ] 1. IGDB (Twitch Dev)
[ ] 2. Discord Bot Token
[ ] 3. Brave Search API
[ ] 4. YouTube Data API v3
[ ] 5. GitHub PAT
[ ] 6. Tavily Search
[ ] 7. Exa AI Search
[ ] 8. E2B Sandbox

Priority 2 (개발/모니터링)
[ ] 9. Sentry
[ ] 10. Notion API
[ ] 11. Firecrawl

Priority 3 (선택)
[ ] 12. Slack Bot Token
[ ] 13. Pinecone
[ ] 14. Qdrant
[ ] 15. Zep

비추천
[x] Twitter/X — $200/월, skip
[x] Google Maps — 카드 필수, skip
```

---

## 참조: 패턴별 MCP 매핑

| 참조 시스템 | 패턴 | GEODE MCP |
|---|---|---|
| **OpenClaw** | Sub-agent Spawn (격리 실행) | E2B Sandbox |
| **OpenClaw** | Plugin Architecture | catalog.py 동적 등록 |
| **Karpathy** | P8 Dumb Platform (외부 지식) | IGDB + Wikidata |
| **Karpathy** | P4 Ratchet (자기 모니터링) | LangSmith MCP |
| **Claude Code** | 브라우저 자동화 | Playwright |
| **Claude Code** | 코드 샌드박스 | E2B Sandbox |

> 발급 완료 후 `geode`로 MCP 에러 없이 시작되는지 확인.
