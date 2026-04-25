# v0.52 Refactor — CLI/Server Split + Bug Class Eradication

> **이 리팩토링의 1차 목적은 "OAuth UI 안 보임" 같은 CLI/IPC 혼동 버그를 *재발 불가능하게* 만드는 것**.
> 디렉토리 구조 정리는 그 invariant를 강제하는 수단일 뿐, 목적이 아니다.

## 1. 재발 방지 대상 버그 클래스

| 코드 | 버그 클래스 | 과거 사례 | 재발 방지 메커니즘 |
|------|-----------|---------|-----------------|
| **B1** | Daemon 안에서 `print()` / `input()` / 직접 `Console()` 사용해서 thin client에 도달 못 함 | v0.51.0 OAuth device-code (`oauth_login.py:9 prints`), `agentic_loop.py` BillingError, `commands.py:cmd_clear` input | (a) `daemon-side print 금지` lint, (b) Daemon-side handler는 IPC writer 의존성 주입 강제, (c) 모든 사용자 가시 출력은 `ui/` 의 emit_* 거침 |
| **B2** | 같은 함수가 thin/daemon 양쪽에서 호출되어 location-dependent behavior | `cmd_login` 이 thin slash command + daemon manage_login tool 양쪽에서 호출되어 IPC writer 가용성 다름 | (a) 명령 함수에 `@cli_only` 또는 `@server_only` 데코레이터, (b) `COMMAND_REGISTRY` 가 location 명시, (c) import-linter로 `cli` ↛ `server` 양방향 차단 |
| **B3** | Daemon RPC 가 `capture_output()` 으로 stdout 삼킴 → 긴 작업 도중 thin client 무응답 | v0.51.0 `/login oauth` (15분 polling 동안 thin client 무한 대기) | (a) Daemon RPC는 ≤2초 보장 명령만 (`DAEMON_SHORT`), (b) 긴 작업은 streaming event channel (`DAEMON_STREAM`), (c) interactive 인 작업은 thin client 직접 실행 (`THIN`) |
| **B4** | 이중 SOT (예: `auth.json` + `auth.toml`) 가 다른 코드 경로에서 동시 사용 | v0.50.0 직후 OAuth 토큰이 두 파일에 분산 | (a) Plan/Profile 같은 데이터 모델은 `auth/` top-level 단일 모듈, (b) 둘 이상 SOT 발견 시 마이그레이션 + 한쪽 deprecation 의무화 |
| **B5** | Provider/Profile/Plan 라벨이 모듈마다 다르게 표기 (`zhipuai` vs `glm`, `openai` vs `openai-codex`) | v0.49 Codex OAuth 가 `openai` 라벨로 등록되어 일반 GPT 호출 오염 | (a) `auth/plans.py` 의 `PROVIDER_VARIANTS` 가 라벨 SOT, (b) `tests/test_provider_label_consistency.py` 가 4-way 일치 검증 — 이미 존재, (c) 새 provider 추가 시 invariant 테스트 자동 갱신 |
| **B6** | 새 IPC event 추가 시 `ipc_client.py` allowlist 갱신 누락 → daemon 이벤트가 thin 에 도달 못 함 | v0.51.1 OAuth events 처음 추가 시 allowlist 빠뜨림 (test 가 잡아냄) | (a) `tests/test_ipc_event_parity.py` 가 emit_* 함수와 allowlist 매칭 자동 검증 — 이미 존재, (b) emit/handler/allowlist 셋을 한 PR 안에서 변경하는 컨벤션 |
| **B7** | Thin client 가 daemon 상태 변경 후 daemon 캐시 invalidate 신호 안 보냄 → daemon 이 stale 데이터 사용 | (잠재) Thin 이 `auth.toml` 갱신 후 daemon 의 ProfileStore 캐시 무효 | (a) `signal_reload(scope)` IPC RPC 추가, (b) Thin 이 `auth/`, `config/` 쓰기 후 자동 호출, (c) Daemon 핸들러가 `lifecycle/container.load_*` 재실행 |
| **B8** | Process binding 이 묵시적 — 함수가 어디서 도는지 코드만 봐서 불명확 | `cmd_login` 이 thin? daemon? — registration site 봐야만 답 | (a) Top-level dir 이 process binding 명시 (`cli/`, `server/`, `agent/`), (b) import-linter 로 cross-process import 금지, (c) 모든 명령은 `COMMAND_REGISTRY` 에 `RunLocation` 명시 |

## 2. Invariant 테스트 (Phase 0 우선 작성)

이 6개 테스트가 GREEN인 상태로 모든 phase 진행한다. 한 phase에서 RED → 즉시 pause + fix.

| 테스트 파일 | 검증 내용 | 보호하는 버그 클래스 |
|-----------|----------|------------------|
| `tests/test_command_registry.py` (신설) | 모든 슬래시 명령이 `COMMAND_REGISTRY` 에 정확히 1개 `RunLocation` 으로 등록됨. THIN 명령은 IPC writer 의존 안 함 | B2, B3, B8 |
| `tests/test_no_daemon_print.py` (신설) | `core/server/`, `core/agent/`, `core/lifecycle/`, `core/<capability>/` 안의 .py 파일이 native `print(`, `input(`, `rich.console.Console(` 사용 안 함. 사용해야 한다면 `# allow-direct-io: <reason>` annotation 필수 | B1 |
| `tests/test_ipc_event_parity.py` (기존) | 모든 emit_* 함수가 `ipc_client.py` allowlist 에 등록됨 | B6 |
| `tests/test_provider_label_consistency.py` (기존) | provider 문자열이 4 곳 (config, adapters, profiles, registry) 일관 | B5 |
| `tests/test_auth_singleton.py` (기존, 강화) | ProfileStore/PlanRegistry singleton — 두 개 인스턴스 생기지 않음 | B4 |
| `tests/test_signal_reload.py` (신설, Phase 4) | Thin 이 auth.toml 변경 시 `signal_reload` RPC 가 호출되고 daemon 이 reload 함 | B7 |
| `tests/test_import_linter.py` (신설, Phase 6) | `cli ↛ server`, `agent ↛ {cli, server}`, `channels ↛ {cli, server, agent}` 등 import 방향 검증 | B2, B8 |

## 3. 디렉토리 매핑 매트릭스 (228 파일 전수)

### 3.1 Process-bound 신설/이동

| Source (현) | Target (v0.52) | Phase | 버그 보호 |
|-----------|--------------|-------|---------|
| `core/cli/__init__.py:_thin_interactive_loop` | `core/cli/repl.py` | 3 | B2 |
| `core/cli/__init__.py:_handle_command` (thin path) | `core/cli/routing.py` (COMMAND_REGISTRY 기반) | 3 | B2, B8 |
| `core/cli/ipc_client.py` | `core/cli/ipc_client/{client.py, streaming.py, events.py}` | 3 | B6 |
| `core/cli/ui/` | `core/ui/` (top-level 승격, cli + server 공유) | 2 | (재배치) |
| `core/cli/commands.py:cmd_login` (slash path) | `core/cli/commands/auth/login.py` (CLI 직접 실행) | 3 | **B1, B3** (OAuth 결함 해소) |
| `core/cli/commands.py:cmd_login` (manage_login tool path) | `core/server/ipc_server/handlers/manage_login.py` | 4 | B2 |
| `core/cli/commands.py:cmd_key` | `core/cli/commands/auth/key.py` | 3 | (재배치) |
| `core/cli/commands.py:cmd_auth` | `core/cli/commands/auth/legacy_auth.py` (alias 유지) | 3 | (호환) |
| `core/cli/commands.py:_login_*` 헬퍼 | `core/cli/commands/auth/login.py` (helpers) | 3 | (재배치) |
| `core/cli/commands.py:cmd_model` (picker 부분) | `core/cli/commands/model.py` | 3 | (재배치) |
| `core/cli/commands.py:cmd_help`, `cmd_list`, `cmd_verbose` | `core/cli/commands/help.py` | 3 | (재배치) |
| `core/cli/commands.py:cmd_cost` | `core/server/ipc_server/handlers/cost.py` | 4 | B2 |
| `core/cli/commands.py:cmd_status` | `core/server/ipc_server/handlers/status.py` | 4 | B2 |
| `core/cli/commands.py:cmd_clear`, `cmd_compact`, `cmd_context` | `core/server/ipc_server/handlers/context.py` | 4 | **B3** (input() 제거, IPC confirm event) |
| `core/cli/tool_handlers.py` | `core/server/ipc_server/tool_handlers.py` | 4 | B2 |
| `core/cli/cmd_schedule.py` | `core/server/ipc_server/handlers/scheduler.py` | 4 | B2 |
| `core/cli/cmd_skill.py` | `core/server/ipc_server/handlers/skill.py` | 4 | B2 |
| `core/cli/cmd_lifecycle.py` | `core/server/ipc_server/handlers/lifecycle.py` | 4 | B2 |
| `core/cli/agentic_loop.py` (re-export) | `core/agent/loop.py` (이미 별칭) | 7 | (정리) |
| `core/cli/bootstrap.py` | `core/lifecycle/cli_bootstrap.py` (CLI startup 분리) | 1 | (재배치) |
| `core/cli/startup.py` | `core/cli/startup.py` (그대로 — CLI 진입점) | — | — |
| `core/cli/session_state.py`, `session_checkpoint.py` | `core/server/runtime_state/` (daemon-only) | 4 | B2 |
| `core/cli/transcript.py` | `core/server/runtime_state/transcript.py` | 4 | B2 |
| `core/cli/scheduler_drain.py` | `core/server/supervised/scheduler_drain.py` | 4 | B2 |
| `core/cli/result_cache.py` | `core/server/runtime_state/result_cache.py` | 4 | B2 |
| `core/cli/redaction.py` | `core/utils/redaction.py` | 5 | (재배치) |
| `core/cli/terminal.py` | `core/cli/terminal.py` (CLI-only, 그대로) | — | — |
| `core/cli/bash_tool.py` | `core/server/runtime_tools/bash.py` | 4 | B2 |
| `core/cli/batch.py` | `core/server/ipc_server/handlers/batch.py` | 4 | B2 |
| `core/cli/pipeline_executor.py` | `core/server/runtime/pipeline_executor.py` | 4 | B2 |
| `core/cli/report_renderer.py` | `core/ui/report_renderer.py` | 2 | (재배치) |
| `core/cli/memory_handler.py` | `core/server/ipc_server/handlers/memory.py` | 4 | B2 |
| `core/cli/search.py` | `core/server/ipc_server/handlers/search.py` | 4 | B2 |
| `core/cli/ip_names.py` | `core/domains/game_ip/cli_helpers.py` | 5 | (도메인 격리) |
| `core/cli/project_detect.py` | `core/cli/project_detect.py` (CLI-only) | — | — |
| `core/cli/doctor.py` | `core/cli/commands/doctor.py` | 3 | (재배치) |
| `core/cli/_helpers.py` | `core/cli/_helpers.py` (그대로 — CLI-only) | — | — |
| `core/cli/agentic_response.py` | `core/server/runtime/agentic_response.py` | 4 | B2 |

### 3.2 Gateway 폐기 → 재분배

| Source (현) | Target (v0.52) | Phase | 버그 보호 |
|-----------|--------------|-------|---------|
| `core/gateway/auth/*` | `core/auth/*` (top-level 승격) | 1 | **B4** (단일 SOT 강화) |
| `core/gateway/pollers/cli_poller.py` | `core/server/ipc_server/poller.py` | 4 | (재배치) |
| `core/gateway/pollers/base.py` | `core/server/supervised/poller_base.py` | 4 | (재배치) |
| `core/gateway/pollers/slack_poller.py` | `core/server/supervised/slack_poller.py` + `core/channels/slack/` | 4 | **B5** (channel abstraction) |
| `core/gateway/pollers/discord_poller.py` | `core/server/supervised/discord_poller.py` + `core/channels/discord/` | 4 | B5 |
| `core/gateway/pollers/telegram_poller.py` | `core/server/supervised/telegram_poller.py` + `core/channels/telegram/` | 4 | B5 |
| `core/gateway/channel_manager.py` | `core/channels/binding.py` | 4 | (재배치) |
| `core/gateway/models.py` | `core/channels/models.py` | 4 | (재배치) |
| `core/gateway/shared_services.py` | `core/server/supervised/services.py` | 4 | (재배치) |
| `core/gateway/slack_formatter.py` | `core/channels/slack/formatter.py` | 4 | (재배치) |
| `core/gateway/webhook_handler.py` | `core/server/supervised/webhook_handler.py` | 4 | (재배치) |

### 3.3 Runtime wiring → lifecycle

| Source (현) | Target (v0.52) | Phase | 버그 보호 |
|-----------|--------------|-------|---------|
| `core/runtime_wiring/__init__.py` | `core/lifecycle/__init__.py` | 1 | (rename) |
| `core/runtime_wiring/bootstrap.py` | `core/lifecycle/bootstrap.py` | 1 | (rename) |
| `core/runtime_wiring/infra.py` | `core/lifecycle/container.py` | 1 | (rename + DI 의도 명시) |
| `core/runtime_wiring/adapters.py` | `core/lifecycle/adapters.py` | 1 | (rename) |
| `core/runtime_wiring/automation.py` | `core/lifecycle/wiring/automation.py` | 1 | (rename) |

### 3.4 Automation → scheduler 분리

| Source (현) | Target (v0.52) | Phase | 버그 보호 |
|-----------|--------------|-------|---------|
| `core/automation/scheduler.py` | `core/scheduler/scheduler.py` | 5 | (분리) |
| `core/automation/cron*.py` (있다면) | `core/scheduler/cron.py` | 5 | (분리) |
| `core/automation/triggers.py` | `core/scheduler/triggers.py` | 5 | (분리) |
| `core/automation/calendar_bridge.py` | `core/scheduler/calendar_bridge.py` | 5 | (분리) |
| `core/automation/correlation.py`, `drift.py`, `feedback_loop.py`, `outcome_tracking.py`, `snapshot.py` | `core/automation/` 그대로 (자율 학습 부분만 남김) | — | (분리 후 잔여) |
| `core/automation/expert_panel.py`, `predefined.py`, `model_registry.py`, `nl_scheduler.py` | `core/scheduler/<적절>.py` 또는 `core/automation/` 잔류 | 5 | (case-by-case) |

### 3.5 Config 디렉토리화

| Source (현) | Target (v0.52) | Phase | 버그 보호 |
|-----------|--------------|-------|---------|
| `core/config.py` (Settings 클래스 부분) | `core/config/settings.py` | 5 | (분리) |
| `core/config.py` (모델 상수 ANTHROPIC_PRIMARY 등) | `core/config/models.py` | 5 | (분리) |
| `core/config.py` (`ModelPolicy` 부분) | `core/config/policy.py` | 5 | (분리) |
| `core/config.py` (`_resolve_provider`) | `core/config/provider_routing.py` | 5 | (분리) |
| `core/paths.py` | `core/config/paths.py` | 5 | (이동) |

### 3.6 Agent 내부 정리

| Source (현) | Target (v0.52) | Phase | 버그 보호 |
|-----------|--------------|-------|---------|
| `core/agent/agentic_loop.py` | `core/agent/loop.py` | 7 | (rename) |
| `core/agent/safety_constants.py` | `core/agent/safety.py` | 7 | (rename) |
| `core/agent/approval.py` | `core/agent/approval.py` (그대로) | — | — |
| `core/agent/sub_agent.py` | `core/agent/sub_agent.py` (그대로) | — | — |
| `core/agent/error_recovery.py` | `core/agent/error_recovery.py` (그대로) | — | — |

### 3.7 변경 없음 (capability — 이미 잘 정돈됨)

| 디렉토리 | 변경 |
|---------|------|
| `core/llm/` | 없음 (registry, providers, adapters 모두 그대로) |
| `core/memory/` | 없음 |
| `core/orchestration/` | 없음 |
| `core/tools/` | 없음 |
| `core/skills/` | 없음 |
| `core/mcp/` | 없음 |
| `core/hooks/` | 없음 |
| `core/verification/` | 없음 |
| `core/domains/` | 없음 (game_ip 도메인 플러그인) |
| `core/utils/` | 없음 (`redaction.py` 추가만) |

## 4. Phase 별 PR 계획

각 phase 완료 시 invariant 테스트 7개 모두 GREEN, ruff/mypy/pytest 통과, E2E `geode analyze "Cowboy Bebop" --dry-run` → A (68.4) 유지.

| Phase | Scope | 파일 변경 | Invariant 추가 | 버그 해소 |
|-------|-------|---------|--------------|---------|
| **0** | 신설: `tests/test_command_registry.py`, `tests/test_no_daemon_print.py` (둘 다 처음엔 skip 또는 expected-fail). 매핑 매트릭스 docs commit | 2 신설 + 1 docs | B1, B2, B3, B8 (감지 인프라) | (감지만) |
| **1** | `runtime_wiring/` → `lifecycle/`. `gateway/auth/` → `auth/` top-level. import 경로 갱신. `auth_singleton` 테스트 강화 | ~20 file | B4 강화 | (구조 정돈) |
| **2** | `cli/ui/` → `ui/` top-level. `cli/report_renderer.py` → `ui/`. `agentic_ui.py` 의 emit_* 명세 정비 | ~10 file | (위치 변경) | (구조 정돈) |
| **3** | `cli/__init__:_thin_interactive_loop` → `cli/repl.py`. `cli/routing.py` 신설 + `COMMAND_REGISTRY` (RunLocation 명시). `cli/commands/auth/{login,key,wizard}.py` 신설. **OAuth flow CLI 직접 실행** (B1, B3 정식 해소). 기존 `cli/commands.py` 의 thin-side 함수만 분리 | ~15 file + 5 신설 | B2, B3, B8 (test_command_registry 본격 enforce) | **B1, B3** 해소 |
| **4** | `core/server/` 신설. `gateway/pollers/cli_poller` → `server/ipc_server/poller.py`. `gateway/pollers/{slack,discord,telegram}` → `server/supervised/` + `channels/{slack,discord,telegram}/`. daemon-side handler 분리 (`server/ipc_server/handlers/`). `signal_reload` RPC 신설. `tests/test_signal_reload.py` 추가 | ~40 file | B7 추가 | B7 해소 |
| **5** | `automation/` cron 부분 → `scheduler/`. `config.py` → `config/{settings,models,policy,provider_routing,paths}.py`. `core/paths.py` → `core/config/paths.py` | ~30 file | (정돈) | (구조 정돈) |
| **6** | `pyproject.toml` 에 import-linter contracts 추가. CI step 추가. `tests/test_import_linter.py` 추가. `gateway/` 빈 dir 제거 | 5 file | **B2, B8 강제** | B2, B8 강제 |
| **7** | `agent/agentic_loop.py` → `agent/loop.py`. `agent/safety_constants.py` → `agent/safety.py`. `agent/context/` 신설 (breadcrumb 등 흡수) | ~10 file | (정돈) | (구조 정돈) |

총 7 phase, 7 PR. 각 PR feature → develop, 모두 통과 후 develop → main 한 번에. v0.52.0~v0.52.6.

## 5. Invariant 작성 우선 (Phase 0)

```python
# tests/test_no_daemon_print.py — 핵심 발췌
def test_daemon_modules_avoid_native_io():
    """server/, agent/, lifecycle/, capability/ 안의 .py 파일이 native print/input/Console 사용 안 함.

    예외: # allow-direct-io: <reason> annotation 라인.
    """
    forbidden_dirs = ["core/server", "core/agent", "core/lifecycle",
                      "core/auth", "core/llm", "core/memory",
                      "core/orchestration", "core/tools", "core/skills",
                      "core/mcp", "core/hooks", "core/scheduler",
                      "core/verification", "core/channels"]
    forbidden_patterns = [
        (r"^\s*print\(", "native print()"),
        (r"^\s*input\(", "native input()"),
        (r"rich\.console\.Console\(\)", "direct Console()"),
    ]
    violations = []
    for d in forbidden_dirs:
        for path in Path(d).rglob("*.py"):
            for ln, line in enumerate(path.read_text().splitlines(), 1):
                if "# allow-direct-io" in line:
                    continue
                for pat, name in forbidden_patterns:
                    if re.match(pat, line):
                        violations.append(f"{path}:{ln} {name}")
    assert not violations, "\n".join(violations)
```

```python
# tests/test_command_registry.py — 핵심 발췌
def test_every_slash_command_has_registered_location():
    from core.cli.routing import COMMAND_REGISTRY, RunLocation
    for cmd_name, spec in COMMAND_REGISTRY.items():
        assert spec.location in RunLocation, f"{cmd_name} has invalid location"

def test_thin_commands_do_not_use_ipc_writer():
    """THIN 위치 명령의 핸들러가 _ipc_writer_local 의존 안 함."""
    from core.cli.routing import COMMAND_REGISTRY, RunLocation
    for cmd_name, spec in COMMAND_REGISTRY.items():
        if spec.location is RunLocation.THIN:
            src = inspect.getsource(spec.handler)
            assert "_ipc_writer_local" not in src, (
                f"{cmd_name} (THIN) must not depend on IPC writer"
            )
```

## 6. Rollback safety

각 phase 의 단일 commit 은:
1. 새 위치에 파일 추가 + 새 import 갱신
2. 기존 위치에 re-export shim 남김 (`from core.new.location import *`)
3. 모든 테스트 통과 확인
4. 다음 phase 에서 shim 제거

이렇게 하면 phase 도중 문제 발생 시 한 phase 이전으로 revert 가능, 다른 PR/사용 코드 영향 0.
