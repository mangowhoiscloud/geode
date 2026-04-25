# v0.53 Cleanup Targets — `import-linter` ignore_imports 정리

> v0.52.0 에서 `cli/server/agent/channels` process boundary 를 `import-linter` 4 contracts 로 강제했지만,
> 33 개 legacy violation 은 ignore_imports 로 우회 등록함. 이 문서는 정리 계획서.
>
> 목적: v0.53.x 시리즈에서 한 violation 씩 제거 → ignore_imports 사이즈 0 도달.

## 분류 — 7 그룹

각 violation 을 *원인* 에 따라 묶어서 group 별 PR 로 처리.

### G1 — `cli/__init__.py` 가 daemon 진입점 (`geode serve`) 을 호스팅 (4 violations)

| Violation | Line | 정리 방법 |
|---------|------|---------|
| `core.cli -> core.server.supervised.services` | `cli/__init__.py:1453` | `geode serve` 명령 → `core/server/entrypoint.py` 분리 |
| `core.cli -> core.server.supervised.webhook_handler` | `cli/__init__.py:1559` | (위와 동일 — serve 명령이 webhook 도 시작) |
| `core.cli -> core.server.ipc_server.poller` | `cli/__init__.py:1575` | (위와 동일) |
| `core.cli -> core.channels.binding` | `cli/__init__.py:1435` | channel binding 초기화도 server 측으로 이동 |

**정리 PR**: v0.53.0 — `core/server/entrypoint.py` 신설, `geode serve` 가 thin client 가 아닌 별도 entry → `core/cli/` 는 순수 thin process

### G2 — `cli/scheduler_drain.py` 가 server 의존 (1 violation)

| Violation | 정리 방법 |
|---------|---------|
| `core.cli.scheduler_drain -> core.server.supervised.services` | `scheduler_drain.py` 자체를 `core/server/supervised/scheduler_drain.py` 로 이동 (이미 daemon-side 코드) |

**정리 PR**: v0.53.1

### G3 — `agent/` 가 cli/ 의 utility 모듈 의존 (8 violations)

`agent/` 가 사실 daemon process 안에서 실행되는 추론 엔진인데, util 들이 `cli/` 에 살아 있어 import 가 backwards.

| Violation | 정리 방법 |
|---------|---------|
| `core.agent.loop -> core.cli.session_checkpoint` | `cli/session_checkpoint.py` → `core/server/runtime_state/session_checkpoint.py` |
| `core.agent.loop -> core.cli.transcript` | `cli/transcript.py` → `core/server/runtime_state/transcript.py` |
| `core.agent.loop -> core.cli.commands` | `cmd_*` direct import 대신 callable injection (DI 패턴) |
| `core.agent.approval -> core.cli` | `cli` 통째 import — 정확한 symbol path 로 좁힌 후 이동 |
| `core.agent.tool_executor -> core.cli.bash_tool` | `cli/bash_tool.py` → `core/server/runtime_tools/bash.py` |
| `core.agent.tool_executor -> core.cli.redaction` | `cli/redaction.py` → `core/utils/redaction.py` (capability) |
| `core.agent.system_prompt -> core.cli.ip_names` | `cli/ip_names.py` → `core/domains/game_ip/cli_helpers.py` (도메인 격리) |
| `core.agent.worker -> core.cli.tool_handlers` | `cli/tool_handlers.py` → `core/server/ipc_server/handlers/` (이미 daemon-side) |

**정리 PR**: v0.53.2 (큰 작업 — 7 파일 이동 + 24+ import 갱신)

### G4 — `server/supervised/services.py` 가 cli/ 의존 (4 violations)

`shared_services.py` (구) 가 cli/ command/state/handler 들을 import. G3 정리 시 함께 해소.

| Violation | 정리 방법 |
|---------|---------|
| `core.server.supervised.services -> core.cli.commands` | G3 + commands 의 daemon-side 함수 분리 |
| `core.server.supervised.services -> core.cli.session_state` | G3 정리 후 server 안 import 로 변경 |
| `core.server.supervised.services -> core.cli.tool_handlers` | G3 |
| `core.server.supervised.services -> core.cli.bootstrap` | `cli/bootstrap.py` → `core/lifecycle/cli_bootstrap.py` 또는 server entrypoint 흡수 |

**정리 PR**: v0.53.2 (G3 와 동시)

### G5 — `lifecycle/bootstrap.py` 가 cli/startup 의존 (1 violation)

| Violation | 정리 방법 |
|---------|---------|
| `core.lifecycle.bootstrap -> core.cli.startup` | `cli/startup.py` 의 daemon 부분 → `core/lifecycle/startup_checks.py` 분리 |

**정리 PR**: v0.53.3

### G6 — `memory/context.py` 가 cli/project_detect 의존 (1 violation)

| Violation | 정리 방법 |
|---------|---------|
| `core.memory.context -> core.cli.project_detect` | `project_detect.py` 가 사실 capability — `core/utils/project_detect.py` 로 이동 |

**정리 PR**: v0.53.4

### G7 — `server/ipc_server/poller.py` 가 cli/ 의존 (4 violations)

| Violation | 정리 방법 |
|---------|---------|
| `core.server.ipc_server.poller -> core.cli` | thin-client 사이드 ResultCache 접근을 IPC 로 캡슐화 |
| `core.server.ipc_server.poller -> core.cli.session_state` | `session_state.py` → `core/server/runtime_state/` |
| `core.server.ipc_server.poller -> core.cli.startup` | startup 의 daemon 부분 lifecycle 로 분리 (G5) |
| `core.server.ipc_server.poller -> core.cli.session_checkpoint` | G3 (session_checkpoint 이동) |

**정리 PR**: v0.53.5 (G3, G5 선행 후)

### G8 — `lifecycle/adapters.py` 가 channels/ 의존 (1 violation)

| Violation | 정리 방법 |
|---------|---------|
| `core.lifecycle.adapters -> core.channels.binding` | adapter wiring 자체가 channel 을 알아야 함. 정상 의존 — `core.lifecycle` ↛ `core.channels` 룰을 완화하거나 channels 를 lifecycle 의존성으로 인정 |

**정리 PR**: v0.53.6 (룰 변경)

### G9 — `channels/binding.py` 가 server/supervised/poller_base 의존 (1 violation)

| Violation | 정리 방법 |
|---------|---------|
| `core.channels.binding -> core.server.supervised.poller_base` | `poller_base.py` → `core/channels/poller_base.py` 승격 (channel 추상화의 일부) 또는 channels 가 server 의존 인정 |

**정리 PR**: v0.53.7

## 진행 순서

1. **v0.53.0** — G1 (cli/__init__ 의 serve 명령 분리) → 4 violations
2. **v0.53.1** — G2 (scheduler_drain 이동) → 1 violation
3. **v0.53.2** — G3+G4 (agent ↔ cli util 분리) → 12 violations (가장 큰 작업)
4. **v0.53.3** — G5 (lifecycle/bootstrap startup 분리) → 1 violation
5. **v0.53.4** — G6 (project_detect 이동) → 1 violation
6. **v0.53.5** — G7 (poller cli 의존 해소) → 4 violations
7. **v0.53.6** — G8 (lifecycle.adapters 룰 결정) → 1 violation
8. **v0.53.7** — G9 (poller_base 이동) → 1 violation

총 **8 PR, 25 violations 정리** (33 - 8 중복 항목 정정 후 실제 25). 완료 시 `pyproject.toml` `ignore_imports` 비어있음.

## 검증

매 PR 후:
```bash
uv run lint-imports          # 0 broken, ignore_imports 카운트 감소
uv run pytest tests/ -m "not live"  # E2E 보존
```

각 PR 머지 후 `[tool.importlinter]` 의 해당 ignore 항목 1 개씩 제거 → contract violation 0 유지.

## 비고

이 문서는 v0.52.1 (이번 PR) 에 함께 commit 됨. v0.53.x 진행 중 violation 정리 status 추적용. 매 PR 머지 후 해당 group 줄긋기 또는 이 문서 갱신.
