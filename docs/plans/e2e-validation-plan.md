# GEODE E2E 실사용 검증 계획

> 작성일: 2026-03-25
> 목적: 폴더 구조 리팩토링 + 코드 품질 개선 후 전 기능 정상 동작 확인
> 방법: 자연어 쿼리 입력 → 도구 선택/실행 관찰 → 기대 결과 대조

---

## Phase 1: 기본 동작 (CLI 진입점 + 부트스트랩)

| # | 자연어 쿼리 / 동작 | 검증 대상 | 기대 결과 |
|---|-------------------|----------|----------|
| 1.1 | `geode --help` | Typer CLI 진입점 | 명령어 목록 출력 |
| 1.2 | `geode` (REPL 진입) | Bootstrap, ContextVar 초기화 | 프롬프트 표시, MCP/Skills 로드 |
| 1.3 | `안녕` | AgenticLoop 텍스트 응답 | 도구 미호출, 자연어 응답 |
| 1.4 | `너 누구야?` | 시스템 프롬프트 확인 | GEODE 자기소개 |
| 1.5 | `/help` | 슬래시 커맨드 디스패치 | 명령어 목록 |
| 1.6 | `/context` | ContextAssembler 7-Tier | T0 SOUL ~ V0 Vault 표시 |
| 1.7 | `/context career` | Career identity | career.toml 내용 |
| 1.8 | `/context profile` | User profile | 프로필 데이터 |
| 1.9 | `/model` | 모델 상태 | 현재 모델 + 프로바이더 |
| 1.10 | `/verbose` | Verbose 토글 | on/off 전환 |
| 1.11 | `/cost` | 토큰 비용 추적 | 세션 비용 (0 or 누적) |
| 1.12 | `/skills` | 스킬 목록 | 로드된 스킬 수 |
| 1.13 | `/mcp` | MCP 서버 상태 | 서버 목록 + 도구 수 |
| 1.14 | `/quit` | 종료 | 세션 정리 + 종료 |
| 1.15 | `geode "hello"` (단발 모드) | 비대화형 실행 | 응답 후 종료 |
| 1.16 | `geode analyze "Cowboy Bebop" --dry-run` | CLI 단발 분석 | A (68.4) |
| 1.17 | `geode analyze "Berserk" --dry-run` | CLI 단발 분석 | S (81.2) |
| 1.18 | `geode analyze "Ghost in the Shell" --dry-run` | CLI 단발 분석 | B (51.7) |
| 1.19 | 잘못된 IP: `geode analyze "없는IP" --dry-run` | 에러 핸들링 | 에러 메시지 |
| 1.20 | `geode --version` | 버전 확인 | 0.24.0 |

## Phase 2: 도구 호출 (Tool Use — 분석/검색/메모리)

| # | 자연어 쿼리 | 검증 도구 | 기대 결과 |
|---|-----------|----------|----------|
| 2.1 | `IP 목록 보여줘` | `list_ips` | fixture 목록 (150+) |
| 2.2 | `다크 판타지 게임 찾아줘` | `search_ips` | 검색 결과 |
| 2.3 | `소울라이크 장르 검색` | `search_ips` | Hollow Knight 등 |
| 2.4 | `Berserk 분석해 dry-run으로` | `analyze_ip(dry_run=True)` | S (81.2) |
| 2.5 | `Cowboy Bebop 분석해줘 LLM 없이` | `analyze_ip(dry_run=True)` | A (68.4) |
| 2.6 | `Berserk랑 Cowboy Bebop 비교해 dry-run` | `compare_ips` | 비교 표 |
| 2.7 | `Berserk 리포트 만들어줘 dry-run` | `generate_report` | 리포트 출력 |
| 2.8 | `이 결과 기억해줘` | `memory_save` (WRITE) | HITL 승인 → 저장 |
| 2.9 | `아까 저장한 거 뭐였지?` | `memory_search` | 저장된 내용 조회 |
| 2.10 | `내 프로필 보여줘` | `profile_show` | 프로필 데이터 |
| 2.11 | `상태 확인` | `check_status` | readiness report |
| 2.12 | `도움말` | `show_help` | 도구 목록 |
| 2.13 | `Steam 게임 중 로그라이크 찾아줘` | `search_ips(query="roguelike")` | Steam fixture 검색 |
| 2.14 | `Hades 분석해 dry-run` | `analyze_ip` | 결과 표시 |
| 2.15 | `분석 계획 보여줘` | `list_plans` | 계획 목록 |
| 2.16 | `현재 세션 비용 얼마야?` | `check_status` 내 cost | 비용 표시 |
| 2.17 | `메모 저장: 오늘 Berserk S등급 확인` | `note_save` | 메모 저장 |
| 2.18 | `저장된 메모 읽어줘` | `note_read` | 메모 내용 |
| 2.19 | `배치로 Berserk, Cowboy Bebop, Ghost 분석 dry-run` | `batch_analyze` | 3건 결과 |
| 2.20 | `결과 요약해줘` | 텍스트 응답 | LLM 요약 |

## Phase 3: 범용 에이전트 (웹/파일/bash)

| # | 자연어 쿼리 | 검증 도구 | 기대 결과 |
|---|-----------|----------|----------|
| 3.1 | `최근 AI 트렌드 검색해줘` | `general_web_search` | 검색 결과 |
| 3.2 | `2026년 게임 산업 뉴스 찾아줘` | `general_web_search` | 뉴스 결과 |
| 3.3 | `LangGraph 최신 버전 검색` | `general_web_search` | 버전 정보 |
| 3.4 | `https://news.ycombinator.com 읽어줘` | `web_fetch` | HN 내용 |
| 3.5 | `https://github.com/langchain-ai/langgraph 읽어줘` | `web_fetch` | 리포지토리 정보 |
| 3.6 | `README.md 읽어줘` | `read_document` | README 내용 |
| 3.7 | `CHANGELOG.md 읽어줘` | `read_document` | 변경이력 |
| 3.8 | `pyproject.toml 읽어줘` | `read_document` | 설정 파일 |
| 3.9 | `echo "hello geode"` | `run_bash` (DANGEROUS) | HITL → 실행 |
| 3.10 | `python3 --version` | `run_bash` | Python 버전 |
| 3.11 | `ls core/agent/` | `run_bash` | 파일 목록 |
| 3.12 | `wc -l core/agent/agentic_loop.py` | `run_bash` | 줄 수 |
| 3.13 | `git log --oneline -5` | `run_bash` | 최근 커밋 |
| 3.14 | `오늘 날씨 서울` | `general_web_search` | 날씨 정보 |
| 3.15 | `"autonomous agent" 키워드로 논문 검색` | `general_web_search` | 학술 결과 |
| 3.16 | `docs/plans/ 폴더 내용 보여줘` | `run_bash` | 파일 목록 |
| 3.17 | `core/ 하위 모듈 수 세어줘` | `run_bash` | 숫자 출력 |
| 3.18 | `CLAUDE.md에서 Architecture 섹션 찾아줘` | `read_document` | 아키텍처 섹션 |
| 3.19 | `현재 시간 알려줘` | `run_bash` (date) | 시각 |
| 3.20 | `core/agent/ 폴더 구조 트리로 보여줘` | `run_bash` (tree/find) | 트리 출력 |

## Phase 4: MCP 도구 + 외부 연동

| # | 동작 | 검증 대상 | 기대 결과 |
|---|------|----------|----------|
| 4.1 | `/mcp` 상태 확인 | MCP 서버 목록 | 연결 현황 |
| 4.2 | `/mcp tools` | MCP 도구 목록 | 사용 가능 도구 |
| 4.3 | MCP 서버별 ping | 개별 서버 상태 | alive/dead |
| 4.4 | Brave Search MCP 호출 | `brave_search` | 웹 검색 |
| 4.5 | Steam Signal MCP | `steam_signal` | 게임 시그널 |
| 4.6-4.20 | (연결된 MCP 서버에 따라 동적 결정) | 가용 MCP 도구 | 각 도구 정상 실행 |

## Phase 5: 브라우저 조작 (Chrome MCP)

| # | 동작 | 검증 대상 | 기대 결과 |
|---|------|----------|----------|
| 5.1 | 현재 탭 목록 조회 | `tabs_context_mcp` | 열린 탭 정보 |
| 5.2 | 새 탭 열기 (Google) | `tabs_create_mcp` | 탭 생성 |
| 5.3 | 페이지 읽기 | `read_page` | DOM 내용 |
| 5.4 | 페이지 텍스트 추출 | `get_page_text` | 텍스트 |
| 5.5 | Google 검색 폼 입력 | `form_input` | 검색어 입력 |
| 5.6 | 네비게이션 | `navigate` | 페이지 이동 |
| 5.7 | 스크린샷 (GIF 레코딩) | `gif_creator` | GIF 파일 |
| 5.8 | JavaScript 실행 | `javascript_tool` | 스크립트 결과 |
| 5.9 | 콘솔 로그 읽기 | `read_console_messages` | 로그 |
| 5.10 | 네트워크 요청 확인 | `read_network_requests` | 요청 목록 |
| 5.11 | 요소 찾기 | `find` | 요소 위치 |
| 5.12 | 창 크기 조정 | `resize_window` | 리사이즈 |
| 5.13 | GitHub 리포 탐색 | navigate + read_page | 리포 정보 |
| 5.14 | LinkedIn 프로필 조회 | linkedin-reader MCP | 프로필 데이터 |
| 5.15 | HN 최신 글 목록 | navigate + get_page_text | 글 목록 |
| 5.16 | 이미지 업로드 | `upload_image` | 업로드 결과 |
| 5.17 | 키보드 단축키 | `shortcuts_execute` | 동작 |
| 5.18 | 멀티 탭 작업 | 탭 전환 | 탭 간 데이터 |
| 5.19 | 폼 제출 | form_input + click | 제출 결과 |
| 5.20 | 복합 브라우저 작업 | 여러 도구 조합 | E2E 시나리오 |

## Phase 6: 서브에이전트 + 고급 기능

| # | 자연어 쿼리 | 검증 대상 | 기대 결과 |
|---|-----------|----------|----------|
| 6.1 | 복합 요청: `Berserk 분석하면서 동시에 관련 뉴스 검색해줘` | GoalDecomposer | 분해 + 병렬 |
| 6.2 | `이 작업을 서브에이전트한테 시켜줘` | `delegate_task` | 서브에이전트 실행 |
| 6.3 | `/schedule` | 스케줄러 목록 | 예약 작업 |
| 6.4 | `/resume` | 세션 복원 | 이전 세션 |
| 6.5 | `/context career` | Career TOML | 직업 정보 |
| 6.6 | `/context profile` | User profile | 사용자 정보 |
| 6.7 | `/key` 상태 | API 키 현황 | 키 마스킹 표시 |
| 6.8 | `/auth` | 인증 프로필 | 프로필 목록 |
| 6.9 | 에러 복구: 의도적 실패 유발 | ErrorRecoveryStrategy | 모델 에스컬레이션 |
| 6.10 | 컨텍스트 오버플로우 | ContextMonitor | 경고/프루닝 |
| 6.11 | 연속 도구 실패 | backpressure | 수렴 감지 |
| 6.12 | `/apply` | ApplicationTracker | 지원 관리 |
| 6.13 | 멀티턴 대화 | 컨텍스트 유지 | 이전 대화 참조 |
| 6.14 | 한국어 + 영어 혼용 | 다국어 처리 | 자연스러운 응답 |
| 6.15 | 매우 긴 질문 | 토큰 관리 | 정상 처리 |
| 6.16 | 모델 전환: `/model sonnet` | switch_model | 모델 변경 |
| 6.17 | `/generate 3` | 합성 데이터 | 3건 생성 |
| 6.18 | 세션 체크포인트 | checkpoint save/load | 상태 보존 |
| 6.19 | 트랜스크립트 기록 | transcript | 대화 기록 |
| 6.20 | `/cost` 최종 | 전체 비용 | 누적 토큰/비용 |
