# portfolio-usecase-carousel

## 목적
GEODE 포트폴리오에 REPL 유즈케이스 캐러셀(좌우 클릭 네비게이션) 추가. 실제 GEODE GLM-5 응답을 기반으로 제작.

## 파일
- **작업 대상**: `/Users/mango/workspace/portfolio/public/geode.html` (13,000줄+)
- **삽입 위치**: Development Harness 섹션(`id="harness"`, line ~3593) 또는 별도 섹션
- **참고**: 세션 24에서 칸반+worktree 시각화 블록을 이미 추가함 (Block 4, line ~4271 부근)

## 요구사항

### 1. 캐러셀 UI
- 좌우 화살표 클릭으로 유즈케이스 전환
- 기존 포트폴리오 디자인 톤 유지 (Deep Sea Discovery Theme, `--bg-card`, `--border-subtle` 등)
- 한/영 토글 지원 (`lang-ko`, `lang-en` 클래스)
- 모바일 반응형 (768px, 480px breakpoint)

### 2. 유즈케이스 (최소 3건, 확장 가능)
실제 GEODE GLM-5 호출로 응답 확인 후 제작. 현재 GLM-5만 활성화 상태.

| # | 유저 입력 | GEODE 응답 요약 | 특징 |
|---|----------|----------------|------|
| 1 | "나와 어울리는 채용 공고 찾아줄래?" | ML Engineer, Agent Platform Lead, AI Infra 3건 매칭 | 프로필 기반, 3 rounds, 2 tools, ~4s |
| 2 | "이 분석 결과 기억해둬" | `.geode/memory/PROJECT.md`에 저장 | 1 round, 1 tool, ~2s, 메모리 시스템 |
| 3 | "공각기동대 분석해줘" | Tier A · 72.1 · undermarketed | 14축 루브릭, 4 analyst, 3 evaluator, ~12s |

### 3. 각 카드 디자인 요소
```
┌─────────────────────────────────────────┐
│  ❯ 사용자 입력 (터미널 스타일)            │
│                                          │
│  ● AgenticLoop                           │
│    ✢ glm-5 · ↓14.7k ↑892 · $0.0124     │
│                                          │
│  [응답 내용 — 요약 형태]                   │
│                                          │
│  ───────────────────────                 │
│  6 layers · 7 nodes · 5 rounds · ~12s   │
│  ↻ replay                               │
└─────────────────────────────────────────┘
```
- Fira Code 모노스페이스 폰트
- 토큰 사용량/비용 표시
- rounds/tools/시간 메트릭
- 실제 터미널 느낌 (dark background, 프롬프트 `❯`)

### 4. GEODE 실행 방법 (GLM-5)
```bash
# REPL 진입
uv run geode

# 또는 단일 명령
uv run geode "공각기동대 분석해줘"

# dry-run (LLM 없이 fixture)
uv run geode analyze "Ghost in the Shell" --dry-run
```
- `.env`에 `ZAI_API_KEY` 설정 필요
- GLM-5 모델만 현재 활성화
- 채용 공고 검색은 web_search MCP 도구 사용

### 5. 추가 유즈케이스 후보 (GEODE 실행하며 확인)
- "오늘 일정 알려줘" — 캘린더 MCP
- "최근 AI 트렌드 요약해줘" — web_search + web_fetch
- "Berserk vs Cowboy Bebop 비교해줘" — compare_ips 도구
- "/model glm-5" → "/model claude-opus-4-6" — 모델 전환
- "이 코드 리뷰해줘" — 범용 에이전트 활용

## 기존 포트폴리오 디자인 참고

### CSS 변수 (보존 필수)
```css
--bg-card: rgba(15, 23, 42, 0.6)
--border-subtle: rgba(129, 140, 248, 0.08)
--text-primary: rgba(255, 255, 255, 0.92)
--text-secondary: rgba(255, 255, 255, 0.6)
--text-muted: rgba(255, 255, 255, 0.35)
```

### 색상 체계
- Purple `#C084FC` — 하네스/메타
- Blue `#60A5FA` — 인프라
- Green `#34D399` — 성공/검증
- Amber `#F5C542` — 실행/진행
- Red `#EF4444` — 제약/에러
- Pink `#F4B8C8` — 분석

### 폰트
- Inter (본문), Fira Code (코드/모노), Noto Sans KR (한글)

## 세션 24 완료 사항 (컨텍스트)

### 코드 품질 전면 개선 (PR #436)
- S1: Thread Safety 4건 (HookSystem Lock 등)
- S2: Error Handling 4건 (synthesizer KeyError 등)
- S3: DRY + Resource 4건 (retry 통합 등)
- S4: AgenticLoop → ToolCallProcessor 추출 (-477줄)
- S6: Flaky test 격리
- REPL 가로채기 제거 (detect_api_key + dry-run regex)

### 포트폴리오 추가 (세션 24)
- Development Harness 섹션에 **Block 4: Kanban State Machine + Worktree Memory Model** 추가
- 칸반 상태 머신 SVG + 3-Checkpoint Protocol
- Worktree alloc/own/execute/free 라이프사이클 SVG
- GitFlow 시각화 (feature → develop → main)

### 버전
- GEODE v0.26.0 (221 modules, 3080 tests)

## 작업 순서
1. GEODE REPL 실행 (GLM-5)하여 3+건 유즈케이스 실제 응답 수집
2. 응답 데이터 기반 캐러셀 HTML 작성
3. 기존 포트폴리오 디자인 톤에 맞춰 스타일링
4. 한/영 토글 + 모바일 반응형 적용
5. 브라우저에서 레이아웃 확인
6. portfolio 레포 커밋 + 푸시 → GitHub Pages 배포
