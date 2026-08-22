# Claude CLI retirement scope

작성: 2026-08-22
기준: `origin/develop`
상태: complete

## 삭제 대상

| 영역 | 제거 경로 |
|---|---|
| Core adapter | `core/llm/adapters/{claude_cli.py,_claude_cli_runtime.py,claude_cli_runtime.py,anthropic_oauth.py}`, registry/export/translation 등록 |
| Auth and retry | `core/auth/claude_cli_oauth.py`, `core/llm/{claude_cli_errors.py,oauth_usage.py}`, Anthropic OAuth login·quota·refresh·failover 분기 |
| Concurrency | `core/orchestration/claude_cli_lane.py`, container/startup lane 등록과 Claude CLI 전용 timeout |
| Agent resume | `core/agent/task_isolation.py`, `resume_session_id`, `claude_cli_session_id`, CLI cwd 격리, worker/loop/lifecycle/session DB/관측 projection의 resume read·write·schema·index |
| Petri | `geode_product/petri_audit/{claude_cli_provider.py,adapters/claude_cli_backend.py,mcp_bridge/**}`, `plugins/petri_audit/` 호환 facade, manifest entry point/source, CLI 전용 stream parser·tool translator |
| SIL | `geode_product/self_improving/loop/mutate/cli_subprocess.py`와 Claude subprocess dispatch. Mutation·proposal·apply·verdict·rollback 표면은 유지 |
| Seed generation | Claude CLI probe/override/adapter mapping, preflight, active voter/role source |
| Benchmark | MCPMark Claude model label의 retired subscription source routing |
| UX/config | `/login` Claude CLI 활성화, source picker 노출, welcome/readiness 문구, routing manifest와 package entry point |
| Tests | 위 모듈·resume·MCP bridge·subprocess 계약 전용 테스트. 레거시 차단 및 역사 artifact 판독 테스트는 유지 |
| Docs/generated | README·현재 architecture/public site의 활성 사용 안내, llms-full·changelog projection·architecture baseline은 구현 후 재생성 |

## 유지 대상

- `claude-cli` / `oauth`가 들어간 기존 설정은 파싱 단계에서 거부하지 않는다. 실행 시 퇴역 사실과 `api_key` 전환 방법을 명시하고 호출하지 않는다.
- 과거 CHANGELOG, `.eval`, trajectory, session/event fixture의 source와 receipt는 감사·재현 증거이므로 수정하지 않는다.
- Claude Code에서 참고한 일반 설계 패턴 문서와 주석은 실행 통합이 아니므로 유지한다.
- SIL mutation surface와 Cognitive Loop의 verify/replan은 이번 범위 밖이며 유지한다.
- OpenAI Codex OAuth와 외부 adapter 확장 경계는 유지한다.

## 완료 조건

- production import/manifest/registry에서 Claude CLI subprocess에 도달하는 경로가 0개다.
- legacy source는 네트워크·subprocess 호출 전에 fail loud 한다.
- Anthropic 활성 경로는 API key뿐이며 OpenAI Codex subscription 경로는 회귀하지 않는다.
- dedicated tests, full non-live suite, static gates, package/site 생성 검증이 통과한다.

## 병합 후 독립 감사

빈 컨텍스트의 세 에이전트가 runtime reachability, module dependency,
anti-deception을 각각 검사했다. 실행 adapter·auth·subprocess·resume 경로는
모두 0개였고 SIL mutation 및 cognitive verify/replan은 연결된 상태였다.
감사에서 발견한 활성 문서·주석의 삭제 모듈명과 Petri의 미사용 `binary`
필드는 후속 정돈했다. fresh-build 감사에서 확인한 누락도 함께 닫아
`/grill`·`/geo`의 `.geode/skills`가 wheel/sdist에 포함되도록 했다. 기본
설치의 `geode-mcp`가 MCP 2를 받아 깨지던 의존성도 `mcp>=1.28,<2`로
고정하고 실제 서버 생성 smoke를 추가했다. 현행 design 문서에서는 실행
source를 동적으로 읽고, Claude CLI 표시는 과거 receipt임을 명시한다.
과거 `.eval`·trajectory·fixture의 판독 문자열, legacy fail-loud migration
값, 외부 호스트의 일반 Claude Code 참고는 유지한다.
