# MCPMark × Agent-World Comparison Runbook

Date: 2026-07-10. Scope: GEODE + GPT-5.5 subscription(Codex) route로 MCPMark를 측정해
Agent-World Table 1 (arXiv `2604.18292v1`)의 MCP-Mark subdomain(File / Github / Notion /
Play / Post)과 비교 가능한 상태를 만든다. 2026-07-04 실측에서 blocked였던 사례를
다시 실행 가능하게 만드는 환경 조치를 이 문서에 고정한다.

## Agent-World 측 프로토콜 (논문 명시 사실만)

| 항목 | Agent-World | GEODE 측 대응 |
|---|---|---|
| 서비스 | MCP-Mark 5종: File, Github, Notion, Play, Post | 동일 5종 (upstream `eval-sys/mcpmark@cd45b7f`, Verified/standard 127 tasks) |
| 반복 | 8회 반복 평균 (avg@8) | `--k`로 동일 구성 가능. 1차 unblock 검증은 `k=1`, 헤드라인 비교는 `k` 명시 후 별도 라벨 |
| 디코딩 | temperature=1.0, top_p=1.0 | subscription/Codex 루트는 디코딩 파라미터 노출 없음. **directional 비교**로 라벨 |
| 하네스 | in-house framework, "aligned to official scores" | official `pipeline.py` + GEODE `BaseMCPAgent` adapter |
| 모델 | GPT-5.2 High 등 (GPT-5.5 없음) | `gpt-5.5`, provider `openai-codex`, source `subscription`, effort `xhigh` |

비교 규칙: Agent-World 수치는 논문 시점 MCP-Mark, GEODE 수치는 MCPMark
Verified(standard)이다. 같은 표에 넣을 때 버전 라벨을 반드시 분리한다
(frontier-agentic-tool-use-benchmark-cases.md의 comparison rule 준수).
Play 칼럼이 `playwright`(4)만인지 `playwright_webarena`(21) 포함인지 논문은
명시하지 않는다. GEODE 게시 시 두 그룹을 분리 기록한다.

## 환경 상태 (2026-07-10 preflight)

| 서비스 | Standard | 상태 | 2026-07-10 조치 |
|---|---:|---|---|
| filesystem | 30 | 측정 가능 (07-04 실측 존재) | 없음 |
| postgres | 21 | 측정 가능 (07-04 20/21) | `mcpmark-postgres` 컨테이너 재기동, 5개 샘플 DB 및 기본 크리덴셜 접속 확인 |
| github | 23 | **unblock**: 07-04 1차 run의 State Duplication Error 6건은 `GITHUB_EVAL_ORG` 미설정(기본 `mcpleague-eval`에 권한 없음)이 원인 | `.mcp_env`에 `GITHUB_EVAL_ORG=mangowhoiscloud` 영속화 (07-04 retry가 이 값으로 성공했음을 로그로 확인), 토큰 유효성 재확인 |
| notion | 28 | **unblocked (2026-07-10 실측)**: 07-04 스톨 원인은 세션 만료(`notion_state.json` → app.notion.com goto 120s 타임아웃 반복). 재로그인은 Google OAuth의 자동화 브라우저 차단 때문에 real-Chrome channel + `--disable-blink-features=AutomationControlled` + persistent profile로 수행, 세션은 `.app.notion.com` 도메인(`token_v2`)에 저장됨 | smoke `toronto_guide/simple__change_color` 1/1 PASS (duplication 58.9s, agent 216.8s, 8 rounds, 70.8k tokens). 에이전트가 select color 직접 수정 불가(API validation_error)를 스키마 재정의로 우회함을 verifier로 확인. 한국어 UI 셀렉터 패치(uncommitted)가 checkout에 존재 — 공식 프로토콜은 영어 UI 요구, 완전 정합을 원하면 워크스페이스 언어를 English로 |
| playwright | 4 | 측정 가능 (live-web 태스크, WebArena 불필요) | `npx @playwright/mcp@0.0.68` 기동 확인, chromium/firefox 설치 확인 |
| playwright_webarena | 21 | **디스크 blocked**: WebArena 이미지 tar 실측(CMU 미러 HEAD, 2026-07-10) shopping 62GiB + shopping_admin 8GiB + reddit 49GiB = 119GiB, 로컬 여유 13GiB | 로컬 불가 확정(스트리밍 `curl \| docker load`로 tar 저장을 생략해도 최대 단일 이미지 62GiB가 여유 초과). 외장 볼륨 또는 VM에서 `docs/mcp/playwright.md` 절차 수행 필요 |

재실행 대상 blocked 사례 목록 (07-04 결과 기준):

- github State Duplication Error 6건: `easyr1__advanced_branch_strategy`,
  `easyr1__qwen3_issue_management`, `easyr1__config_parameter_audit`,
  `easyr1__performance_regression_investigation`,
  `claude-code__label_color_standardization`, `harmony__fix_conflict`
- notion standard 28건 전체 (실측 0)
- playwright standard 4건 + playwright_webarena standard 21건 (실측 0)

## 실행 방법

에이전트 등록은 커밋된 런처가 담당한다 (`--agent geode`가 upstream 무패치로 동작):

```bash
cd artifacts/eval/harnesses/mcpmark
set -a; source .mcp_env; set +a
OPENAI_API_KEY=dummy .venv/bin/python -m plugins.benchmark_harness.run_mcpmark \
  --mcp <filesystem|notion|github|postgres|playwright|playwright_webarena> \
  --task-suite standard \
  --tasks <category/task | all> \
  --models geode-gpt-5.5 \
  --agent geode \
  --reasoning-effort xhigh \
  --k 1 \
  --timeout 1200 \
  --exp-name geode-gpt55-xhigh-<date>-<slug> \
  --output-dir ./results-geode-agentworld
```

`OPENAI_API_KEY=dummy`는 pipeline의 env 검사용이다. 실제 모델 호출은 GEODE
`openai-codex` provider, `source=subscription`으로 나간다.

실행 전 점검:

```bash
.venv/bin/python -m plugins.benchmark_harness.cli preflight mcpmark --env-file .mcp_env
docker ps --format '{{.Names}} {{.Status}}' | grep mcpmark-postgres   # postgres
docker images -q ghcr.io/github/github-mcp-server:v0.15.0             # github MCP
npx -y @playwright/mcp@0.0.68 --version                               # playwright MCP
```

## 사이클 상태 (2026-07-10)

첫 full cycle(notion→playwright→github→postgres→filesystem, standard, k=1,
exp-name `geode-gpt55-xhigh-20260710-agentworld-cycle`)은 시작 직후 구독 쿼터
`429 usage_limit_reached`(plan `prolite`)를 만나 즉시 중단했다. 오염된 태스크
결과 1건(`notion/company_in_a_box__employee_onboarding`)은 삭제했다. resume
로직은 non-retryable error message가 남은 실패를 최종 결과로 취급해 영구
스킵하므로, 429로 실패한 태스크 디렉토리는 반드시 지우고 재개해야 한다.

재개 절차: 쿼터 리셋 후 동일 exp-name으로 driver 재실행(auto-resume이 완료
태스크를 스킵). 429 실패는 점수에 포함하지 않는다. full-suite 106태스크는
xhigh 기준 리셋 창 여러 개에 걸친다.

## 기록 계약

각 run은 frontier-agentic-tool-use-benchmark-cases.md의 GEODE Reporting Contract
schema를 따른다. Agent-World 비교 표에 넣을 때 최소 라벨: harness commit,
suite(Verified/standard), k, route(`openai-subscription/codex`), effort(xhigh),
그리고 "decoding params not controllable" 주석.

원시 실로그는 공개 저장소에 스냅샷으로 게시한다:
<https://github.com/mangowhoiscloud/geode-eval-artifacts> (MCPMark run
디렉토리 전체 + 파이프라인 로그 + tau2 simulations). 로컬
`artifacts/eval/harnesses/**` 경로를 인용하는 run record는 이 저장소의 동일
상대 경로에서 원본을 볼 수 있다. 게시 전 시크릿 스캔이 게이트이며, 스냅샷은
append-only로 유지한다.
