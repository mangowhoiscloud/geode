# `--dangerously-skip-permissions` + plan auto-proceed

> **작성**: 2026-06-14
> **운영자 지시**: "geode에도 dangerously-skip-permissions 옵션을 추가해. HITL 제약을 두지 않고 움직이는 에이전트 경험을 위해서야. 추가로 plan을 생성한다음 유저의 승인을 받도록 의도적으로 멈추는데 일반 HITL과 동일하게 동작하도록 해. plan 작성한다음 바로 행동으로 이어지게."
> **요지**: Claude Code의 `--dangerously-skip-permissions` 패리티. 켜면 모든 HITL 게이트(write/expensive/bash/MCP 승인) **및** plan-승인 중단을 바이패스 → plan 작성 후 곧장 실행.

---

## 0. GAP 감사 (검증됨)

| 요소 | 현황 | 근거 |
|---|---|---|
| HITL 승인 게이트 | **있음** — `ApprovalWorkflow`가 write/expensive/bash/MCP를 `hitl_level`로 게이트. `hitl_level==0`이 write/expensive 바이패스, `≤1`이 bash/MCP 바이패스 | `core/agent/approval.py:216,249,916,935` |
| 모드별 hitl 기본값 | **있음** — REPL=2, **IPC=2**(thin client로 approval relay), DAEMON/SCHEDULER=0 | `core/server/supervised/services.py:_MODE_DEFAULTS` |
| 대화형 경험의 실제 게이트 | thin CLI → **IPC 세션(hitl=2)** → write/bash 승인 프롬프트가 thin client로 relay됨 | poller `request_approval` |
| plan 중단 | **있음** — `create_plan`이 `settings.plan_auto_execute` False면 `approve_plan` 대기(중단), True면 즉시 실행 | `core/cli/tool_handlers/plan.py:107`, `core/orchestration/plan_mode.py` (`PlanExecutionMode.AUTO`) |
| `--dangerously-skip-permissions` 플래그 | **없음** | — |
| client_capability 글로벌 adopt 패턴 | **있음** — thin client가 model/cwd를 capability로 보내면 daemon이 `settings`에 adopt | poller `client_capability` 핸들러(line ~604 model adopt) |

**핵심**: 인프라(hitl_level, plan_auto_execute, capability-adopt)는 전부 존재. 보강 = 단일 플래그가 이 둘(hitl=0 + plan auto)을 묶고, running daemon에도 capability 핸드셰이크로 전파.

## 1. 설계

`--dangerously-skip-permissions` = `settings.dangerously_skip_permissions: bool`를 켜고, 그 값이:
1. **모든 HITL 게이트 바이패스** — `create_session`에서 `hitl=0` + `auto_approve=True` 강제(모드 기본값 override, REPL/IPC의 2도 0으로).
2. **plan 중단 바이패스** — plan 핸들러가 `plan_auto_execute or dangerously_skip_permissions` → 즉시 auto-execute("일반 HITL과 동일하게" = HITL 게이트의 일종으로 취급).

**전파(running daemon 포함)**: 세션은 daemon 프로세스에서 돌고 thin client는 별도 프로세스. 기존 `client_capability` 핸드셰이크가 model을 글로벌 `settings`에 adopt하는 패턴을 그대로 차용 — thin client가 `dangerously_skip_permissions`를 capability에 실으면 daemon이 매 연결마다 `settings.dangerously_skip_permissions`로 adopt(미전송=False로 명시 set → sticky-on 방지). 단일 사용자 데몬 전제라 글로벌 settings mutation이 적합(model adopt와 동일 전제).

## 2. 변경

| 파일 | 변경 |
|---|---|
| `core/config/_settings.py` | `dangerously_skip_permissions: bool = False` (env `GEODE_DANGEROUSLY_SKIP_PERMISSIONS`) |
| `core/cli/__init__.py` `main` | `--dangerously-skip-permissions` typer 옵션 → 모듈 플래그 set + 경고 배너 + serve auto-start 전에 `os.environ` set(fresh daemon용) |
| `core/cli/ipc_client.py` `_send_client_capability` | capability에 `dangerously_skip_permissions` 필드 추가(모듈 플래그에서 읽음) |
| `core/server/ipc_server/poller.py` | `client_capability` 핸들러(2곳)에서 `settings.dangerously_skip_permissions = bool(msg.get(...))` adopt (model adopt 옆) |
| `core/server/supervised/services.py` `create_session` | `settings.dangerously_skip_permissions` fresh read → True면 `hitl=0`, `auto_approve=True` (모드 기본 override) |
| `core/cli/tool_handlers/plan.py` | `settings.plan_auto_execute or settings.dangerously_skip_permissions` → auto-execute |

## 3. 안전/범위
- DANGEROUS 도구(run_bash/computer)는 `hitl=0`이면 이미 자동 승인(`is_bash_auto_approved` `≤1`). 별도 처리 불필요.
- `_HEADLESS_DENIED_TOOLS`(DAEMON/SCHEDULER에서 run_bash/delegate_task 차단)는 **유지** — 무인 채널(Slack/cron) 안전이라 별개 관심사. skip 플래그는 대화형 경험 대상. (운영자가 헤드리스까지 풀길 원하면 후속.)
- **경고 배너 필수** — 켜질 때 명시적으로 표시(Claude Code 패리티, fail-loud).
- 이름은 Claude Code 패리티 `--dangerously-skip-permissions` 그대로(별칭 없음).

## 4. 검증
- 단위: `create_session`이 skip 시 hitl=0+auto_approve / 미설정 시 모드 기본 유지; plan 핸들러가 skip 시 auto-execute; capability adopt(전송/미전송 모두); 미전송 시 False reset(sticky-on 방지).
- 게이트: ruff/format/mypy(457)/lint-imports/pytest + Codex(gpt-5.5).
- 라이브 E2E(실제 데몬 핸드셰이크)는 운영자 환경.

## 5. Status — ✅ DONE (v0.99.209)
| 항목 | 상태 |
|---|---|
| settings 플래그 (`dangerously_skip_permissions`, env-backed) | ✅ |
| CLI 옵션 `--dangerously-skip-permissions` + env set + 경고 배너 | ✅ |
| capability 전파(client advertise + poller `_adopt_skip_permissions`, no-sticky) | ✅ |
| create_session hitl=0 + auto_approve override (모든 모드) | ✅ |
| plan auto-proceed (`plan_auto_execute or dangerously_skip_permissions`) | ✅ |
| 테스트 (server + plan handler) | ✅ |
