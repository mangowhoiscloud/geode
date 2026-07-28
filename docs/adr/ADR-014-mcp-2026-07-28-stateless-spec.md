# ADR-014: MCP 2026-07-28 Stateless 스펙 대응

## Status

Accepted (2026-07-29)

## Context

2026-07-28에 Model Context Protocol 스펙 개정판과 Python SDK v2.0.0 stable이 동시 릴리스됐다.

| 사실 | 근거 |
|------|------|
| 스펙 2026-07-28 최종 릴리스 | MCP 공식 블로그 "The 2026-07-28 Specification" (2026-07-28, Soria Parra·Delimarsky) |
| initialize 핸드셰이크 제거 (SEP-2575), `Mcp-Session-Id`·프로토콜 세션 제거 (SEP-2567) | 스펙 릴리스 후보 공지 + The Register (2026-07-23) |
| 신규 기능: `server/discover`, `subscriptions/listen`, Multi Round-Trip Requests, Extensions, MCP Apps | python-sdk v2.0.0 릴리스 노트 |
| python-sdk v2.0.0: `pip install mcp`가 이제 2.x 설치. `FastMCP` → `MCPServer` 개명, `ClientSession`+`initialize()` 층이 단일 `Client`로 대체 | github.com/modelcontextprotocol/python-sdk releases/v2.0.0 (2026-07-28) |
| v1.x는 maintenance mode (critical bug fix + 보안 패치만, 지원 하한 1.28). 공식 권고: 미마이그레이션 프로젝트는 `mcp>=1.28,<2` | 동일 릴리스 노트 |
| v2 서버는 양쪽 프로토콜 시대를 모두 서빙 — stdio는 opening request로 시대 판별, classic 클라이언트 계속 수용 | 동일 릴리스 노트 + v2.0.0rc1 노트 (#3152) |
| Tier 1 SDK 검증 윈도우 10주 | 릴리스 후보 공지 |

### GEODE 노출 지점 (2026-07-29 감사)

| # | 지점 | 내용 | 심각도 |
|---|------|------|--------|
| 1 | `pyproject.toml` `[mcp]`·`[audit]` extras | `mcp>=1.0.0` 무상한 — fresh resolve가 2.0.0을 끌어오면 `core/mcp_server.py`의 `from mcp.server.fastmcp import FastMCP`가 ImportError로 즉사. lock은 1.26.0이지만 신규 설치 경로(pip/uv tool install)는 무방비 | 높음 (즉시 수정) |
| 2 | `core/mcp/stdio_client.py` | 수제 stdio 클라이언트가 최고령 개정판 `2024-11-05`를 선언하고 서버가 협상해 돌려준 `protocolVersion`을 읽지 않음 — 구개정 지원을 내리는 서버에서 원인 불명의 generic 실패로 표면화 | 중간 (즉시 수정) |
| 3 | `core/mcp_server.py:153-161` | SDK 사설 속성(`mcp._mcp_server.version`) 주입으로 핸드셰이크 버전 보고 — v1 전용 형상, v2에서 무의미(핸드셰이크 자체 제거) | v2 마이그레이션 항목 |
| 4 | `core/mcp_server.py` `_pending_proposals` | propose → apply 2단계 확인 게이트가 프로세스 메모리 dict — 기본 stdio(클라이언트당 1프로세스)에서는 안전, stateless HTTP 다중 워커에서는 "no pending proposal"로 기능 파손(fail-closed라 보안 회귀는 아님) | v2 마이그레이션 항목 |
| 5 | `plugins/petri_audit/mcp_bridge/bridge_server.py` | v1 low-level `Server` + `create_initialization_options()` 사용 — v1 핀 하에서 안전 | v2 마이그레이션 항목 |

## Decision

**지금 (이 ADR과 함께 랜딩):**

1. `mcp>=1.28,<2` — 두 extras 모두, 공식 권고 범위 그대로. v1 라인은 maintenance mode지만 GEODE의 전 MCP 표면(FastMCP 서버, petri bridge, HTTP transport 테스트)이 v1 API에 결합돼 있고, v2 서버·클라이언트 생태계는 classic 개정판을 계속 서빙하므로 즉각적 상호운용 손실이 없다.
2. stdio 클라이언트 선언 개정판을 `2025-06-18`로 상향(모듈 상수 `_PROTOCOL_VERSION`) — 지원 집합 최신은 `2025-11-25`지만 outbound 선언은 배포 폭이 가장 넓은 `2025-06-18`을 유지(서버가 상위를 원하면 협상으로 올라감). initialize 응답의 협상 결과는 지원 집합(`_SUPPORTED_PROTOCOL_VERSIONS` = 4개 classic 개정판) 검증 후 `server_protocol_version`으로 기록 — 집합 밖(미래 개정판·누락 포함)이면 스펙의 SHOULD대로 연결을 끊고 warning 로그, 집합 안 불일치는 info 로그만(기저 연산 wire shape 동일).

**보류 (후속 작업 — SDK v2 마이그레이션):**

| 항목 | 내용 |
|------|------|
| `FastMCP` → `MCPServer` | import·생성자 치환 + 사설 속성 버전 주입(`_mcp_server.version`) 대체 확인. `tests/core/test_mcp_server_tools.py:39-49`의 핸드셰이크 버전 pin은 v2에서 의미가 바뀌므로 재설계 |
| propose/apply 게이트 | stateless HTTP에서 살아남으려면 `_pending_proposals`를 디스크(`~/.geode/state`) 또는 서명 토큰으로 외부화. stdio-only로 남기면 HTTP lane에서 해당 도구 2종을 명시 거부하는 것도 대안 |
| petri bridge | low-level `Server` API의 v2 대응 (`서버는 양시대 서빙`이므로 v1 핀 유지 중엔 무변경) |
| HTTP transport | v2의 stateless 기본값 재검토 — 정적 bearer 토큰 검증(`_StaticTokenVerifier`)은 per-request라 stateless 친화적, 변경 불요 예상 |
| 테스트 격리 | MCP 테스트의 `importorskip("mcp")` — extra 미설치 CI job에서 조용히 skip되므로, v2 마이그레이션 PR은 `[mcp]` extra가 설치된 잡에서 게이트되는지 확인 |
| 주기 헬스 스윕 (R6) | `check_health(auto_restart=True)`의 프로덕션 호출자 부재 — 복구는 호출-시점 반응형(미드콜 1회 재시도)뿐. serve 데몬 주기 스윕은 후속 |

### ReAct 루프 stateless 감사 (2026-07-29, 후속 하드닝)

서버 recycle 관점의 루프↔MCP 배선 감사 결과와 처분. R1~R5는 같은 트레인에서 수정, R6·R7은 위 보류 표.

| # | 결함 | 처분 |
|---|------|------|
| R1 | JSON-RPC 응답 id 미대조 — 서버발 notification 1프레임이 스트림을 영구 오염, health는 계속 정상 보고 | 수정: id 매칭 + 비대상 프레임 skip (`stdio_client._send_request`) |
| R2 | 자식 stderr 미배수 — 64 KB 버퍼에서 웨지, 전 호출 타임아웃 | 수정: 데몬 배수 스레드 (`_drain_stderr`) |
| R3 | 다운/쿨다운 서버의 도구가 모델에 "Unknown tool"로 오보(스키마에는 존재) | 수정: `last_known_server_for_tool` 메모 + executor "currently unavailable" 응답 |
| R4 | 미드콜 사망 시 재시도 부재 — 일시 recycle이 라운드를 소실 | 수정: fresh 클라이언트로 1회 재시도 (`manager.acall_tool`) |
| R5 | 루프 도구 스냅샷이 재연결 후 stale (IPC 세션 수명 동안) | 수정: `connection_epoch` + arun 리프레시 게이트 |
| R6 | 주기 헬스 스윕 부재 | 보류 (위 표) |
| R7 | `_pending_proposals` 프로세스 친화성 | 보류 (기존 체크리스트 항목) |

v2 마이그레이션 시점: 고정 기한 없음 (스펙의 10주 검증 윈도우는 RC→GA 구간으로 2026-07-28에 이미 종료). 외부 압력 신호가 트리거 — (a) 주요 원격 MCP 서버의 classic 개정판 서빙 중단, (b) v1 라인 유지보수(critical bug fix·보안 패치) 종료 공지.

## Consequences

- 신규 설치(`uv sync --extra mcp` / `--extra audit`, `pip install geode-agent[mcp]`)가 v2 SDK를 우발적으로 받는 경로가 차단된다.
- GEODE가 붙는 외부 MCP 서버에 대해 협상된 개정판이 처음으로 관측 가능해지고 (`server_protocol_version`), 미지원 개정판은 generic 실패 대신 명시적 warning으로 표면화된다.
- v2 신기능(`server/discover`, MRTR, Extensions)은 마이그레이션 전까지 사용 불가 — 현재 GEODE 표면은 어느 것도 요구하지 않는다.

## Verification (live E2E, 2026-07-28 UTC)

착지 직후 구독 백엔드(gpt-5.5, codex-oauth)로 라이브 E2E 프로브를 실행해 전 경로를 검증했다: 루프백 `geode-mcp`(python-sdk 1.29.0) 협상 `2025-06-18` 기록·도구 6종, stateless-only 가짜 서버(`2026-07-28` 응답) fail-loud 거부, AgenticLoop의 MCP 디스패치 2회(natural 종료, rounds 3/6). 정규화 궤적과 검증 리포트는 외부 증거 저장소에 발행:

- `mangowhoiscloud/geode-eval-artifacts` @ `647583b3455d16e0769c2b2dc21b380aa24f7bde`
  - `trajectories/geode-agenticloop-mcp-2026-07-28-spec-e2e-20260728T202349Z-7acb62a4184c/` — `trajectory.json` sha256 `8b77e3b05eeba51374cef5b640ddf1109c323f4e3defe869934bbadd43138b42` (9 events, dialogue+tool)
  - `reports/e2e-validation/2026-07-28-mcp-stateless-spec-e2e.md`

## References

- MCP Blog — The 2026-07-28 Specification (2026-07-28)
- MCP Blog — Beta SDKs for the 2026-07-28 MCP Spec Release Candidate (2026-06-29)
- modelcontextprotocol/python-sdk — v2.0.0 release notes (2026-07-28)
- GitHub Changelog — GitHub MCP Server supports the next MCP specification (2026-07-23)
- 트리거: wikidocs.net/blog/@goodhosup/25930 "MCP 2026-07-28 스펙 전환" (2026-07-24)
- 관련 계약: `docs/v1.0.0-stability-contract.md` §C (MCP 도구 표면)
