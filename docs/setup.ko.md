# GEODE 설치 가이드

> [README](../README.md) | [Context Lifecycle](architecture/context-lifecycle.md) | [Hook System](architecture/hook-system.md) | [Workflow](workflow.md) | [English](setup.md) | **한국어**

## 설치

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode && uv sync
```

## 빠른 시작

```bash
# Thin CLI (serve daemon이 없으면 자동 시작)
uv run geode

# 원샷 프롬프트
uv run geode "summarize the latest AI research trends"

# Headless daemon (Slack/Discord/Telegram + scheduler)
uv run geode serve
```

API key 없이 시작하면 자동으로 dry-run 모드로 전환됩니다.

---

## 아키텍처: Thin-Only

```
geode (thin CLI) ── Unix socket IPC ──→ geode serve (unified daemon)
                                          │
                                      GeodeRuntime
                                       ├── CLIPoller    → SessionMode.IPC
                                       ├── Gateway      → SessionMode.DAEMON (Slack/Discord)
                                       └── Scheduler    → SessionMode.SCHEDULER (cron)
```

- `geode` = thin client. 모든 실행은 serve daemon으로 IPC relay.
- serve가 미실행이면 자동 시작 (auto-start, 30s timeout).
- 실시간 streaming: tool calls (▸), results (✓/✗), token usage (✢) thin client에 표시.

---

## 환경 설정

### 1. API Keys

```bash
# Global keys (모든 프로젝트에 적용)
mkdir -p ~/.geode
cat > ~/.geode/.env << 'EOF'
# LLM Providers (최소 1개 필수)
ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com/settings/keys
OPENAI_API_KEY=sk-proj-...         # https://platform.openai.com/api-keys
ZAI_API_KEY=...                    # https://open.bigmodel.cn/usercenter/apikeys (선택)

# 메시징 (Slack Gateway)
SLACK_BOT_TOKEN=xoxb-...           # https://api.slack.com/apps → OAuth & Permissions
SLACK_APP_TOKEN=xapp-...           # Basic Information → App-Level Tokens (connections:write)
SLACK_TEAM_ID=T...                 # 선택; doctor의 클릭 가능한 채널 링크에 사용

EOF
chmod 600 ~/.geode/.env
```

**Secret 우선순위**: 수동 env export > 전역 `~/.geode/.env` > 프로젝트 `.env`.
전역 파일이 권위를 갖는 secret store이고, 프로젝트 `.env`는 전역에 없는 키만
채웁니다. Behavior 설정은 반대로 project `./.geode/config.toml` 이 global
`~/.geode/config.toml` 을 덮습니다.

### 2. 프로젝트 설정

```bash
# .geode/ 구조 초기화
uv run geode init

# 또는 수동으로
mkdir -p .geode
touch .geode/config.toml
```

### 3. Global CLI 설치

```bash
uv tool install geode-agent
geode version   # 어디서든 실행 가능
```

`geode-agent` 는 PyPI 배포명이고, 설치되는 실행 명령은 `geode` 입니다.
현재 릴리즈가 아직 PyPI 에 공개되지 않았거나 GEODE 자체를 개발한다면 소스
체크아웃으로 설치합니다.

```bash
uv sync
uv tool install -e . --force
geode version
```

업데이트와 삭제 경로는 설치 방식에 따라 다릅니다.

```bash
geode update                  # uv: 최신 patch; 소스: pull + rebuild
geode update --latest         # uv 전용: minor/major 업데이트 허용
geode update --dry-run        # 설치 경로를 판별하고 변경 없이 미리 보기
geode uninstall               # 런타임 데이터 + 설치된 CLI 제거
uv tool uninstall geode-agent # CLI만 제거
```

`geode update`는 현재 디렉터리를 추측하지 않고 설치 메타데이터를 읽습니다.
표준 registry 기반 uv 도구는 현재 major/minor 계열의 최신 patch로 제한하고,
editable 설치는 실제 GEODE 소스 체크아웃을 갱신합니다. 사용자 정의 uv
receipt는 설치 설정을 버리지 않고 receipt 경로를 알리며 중단합니다.
메타데이터가 없으면 현재 Git checkout으로 추측하지 않습니다. registry 해석은
현재 프로젝트의 uv 설정과 격리됩니다. 실행 중인 daemon은 업데이트 검증 후에만
중지하며, 새 daemon의 준비 상태까지 확인합니다. CLI 시작 시 암묵적인 네트워크
업데이트는 실행하지 않습니다.

---

## `geode serve` — 통합 Daemon

모든 실행 경로의 backbone. thin CLI, Slack, scheduler 모두 serve를 통합니다.

### 명령어

```bash
geode serve                # foreground (Ctrl+C로 종료)
geode serve -p 5.0         # Discord/Telegram + Slack 폴백 poll 간격 (기본값: 3.0)

# Background (프로덕션) — stdout/stderr는 내부 로거가
# ~/.geode/logs/serve.log 로 기록합니다. 별도 스트림이 필요할 때만 redirect 하세요.
nohup geode serve >/dev/null 2>&1 &
```

### 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--poll`, `-p` | `3.0` | Discord/Telegram 및 Slack 호환 폴백 poll 간격 (초) |

### 시작 순서

1. ContextVars (domain, memory, profile, env)
2. Readiness check (API keys)
3. GeodeRuntime (MCP 13 servers, 10-30s)
4. SchedulerService (jobs 로드, 60s tick 시작)
5. Gateway receivers (Slack Socket Mode, Discord/Telegram poller)
6. CLIPoller (Unix socket `~/.geode/cli.sock`)

### 자동 시작

thin CLI (`geode`)는 serve 미실행 시 자동 시작합니다:

```
geode → is_serve_running()? → No → start_serve_if_needed(30s) → connect IPC
```

- Pidfile lock (`~/.geode/cli.startup.lock`)로 TOCTOU 방지
- `start_new_session=True` + stdout DEVNULL로 background spawn

---

## Slack Gateway

### 1. Slack Bot 생성

- [api.slack.com/apps](https://api.slack.com/apps) → Create New App
- **OAuth & Permissions** → Bot Token Scopes:
  `app_mentions:read`, `chat:write`, `channels:history`, `channels:read`
  (`reactions:write`는 선택이며 진행 리액션에 사용)
- **Socket Mode** → Enable Socket Mode
- **Basic Information** → App-Level Tokens → `connections:write` 범위의
  `xapp-...` 토큰 생성
- **Event Subscriptions** → bot event `app_mention`, `message.channels` 구독 후
  앱 설치/재설치
- `SLACK_BOT_TOKEN=xoxb-...`와 `SLACK_APP_TOKEN=xapp-...`를 모두
  `~/.geode/.env`에 넣고, 바인딩한 모든 채널에서 `/invite @geode` 실행

### 2. Channel Binding (`.geode/config.toml`)

```bash
cp .geode/config.toml.example .geode/config.toml
```

```toml
[gateway]
enabled = true

[gateway.bindings]

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0XXXXXXXXX"   # Slack channel → 이름 클릭 → 하단 "Channel ID"
auto_respond = true
require_mention = true        # true: @mention만 반응
max_rounds = 5
```

### 3. 확인

```bash
geode serve &
grep -E "Slack inbound mode|Slack Socket Mode connected" ~/.geode/logs/serve.log
# → Slack inbound mode: Socket Mode (push)
# → Slack Socket Mode connected

grep "binding" ~/.geode/logs/serve.log
# → Channel binding added: slack/C0XXXXXXXXX (auto_respond=True)

geode doctor slack
# 모든 binding_access 행이 bot_member=True이고 채널 링크를 포함해야 합니다.
```

`SLACK_APP_TOKEN`이 없으면 GEODE는 `polling fallback`을 로그로 명시하고 이전
history poll 경로를 마이그레이션 호환용으로 유지합니다. `geode doctor slack`은
이 상태를 `DEGRADED`로 보고하며, 운영 목표 상태는 아닙니다.

### 리액션

@mention 메시지 → :eyes: (수신) → AgenticLoop → :white_check_mark: (완료) → thread 응답

`require_mention = true`여도 새 최상위 대화(또는 아직 GEODE가 참여하지 않은
스레드)의 첫 메시지만 멘션하면 됩니다. GEODE가 참여한 스레드의 이후 사람
대댓글은 `@geode`를 반복하지 않아도 같은 세션으로 이어지고, 동일한 리액션
수명주기와 스레드 응답을 받습니다. 첫 턴부터 루트 timestamp를 세션/체크포인트
식별자로 쓰므로 데몬 재시작 뒤에도 ACTIVE 또는 PAUSED 스레드를 재개할 수
있습니다.

---

## Scheduler

### CLI 사용법

```bash
# 생성 (action 필수)
/schedule create "every 5 minutes" "check system drift"
/schedule create "daily at 9:00" "summarize today's news"

# 관리
/schedule list
/schedule delete <job_id>
/schedule enable <job_id>
/schedule disable <job_id>
/schedule run <job_id>
```

### 자연어 입력 (AgenticLoop 경유)

```
> 매일 아침 9시에 뉴스 요약해줘
  ▸ schedule_job(expression="daily at 9:00", action="summarize today's news")
  ✓ schedule_job → Created: nl_abc12345
```

### 영속성

- Jobs: `~/.geode/scheduler/jobs.json` (atomic write, fcntl lock)
- 실행 로그: `~/.geode/scheduler/logs/{job_id}.jsonl` (자동 정리 2MB/2000 lines)
- Guardrail: `action=""` jobs 거부 (zombie no-op 방지)

---

## 인터랙티브 슬래시 명령어

| 명령어 | 별칭 | 설명 |
|--------|------|------|
| `/help` | | 전체 명령어 표시 |
| `/status` | | 시스템 상태 (model, API keys, MCP, mode) |
| `/model [N\|name]` | | LLM 모델 표시 / 전환 |
| `/key [provider] [value]` | | API key 표시 / 설정 |
| `/cost` | | LLM 비용 대시보드 (세션 + 월간) |
| `/verbose` | | 상세 출력 토글 |
| `/mcp` | | MCP 서버 상태 |
| `/skills` | | 런타임 skills 목록 |
| `/context` | `/ctx` | Context 티어 표시 |
| `/schedule` | `/sched` | Scheduler 관리 |
| `/trigger` | | 이벤트 트리거 관리 |
| `/tasks` | `/t` | 작업 목록 |
| `/clear` | | 대화 초기화 |
| `/compact` | | Context 압축 |
| `/quit` | `/q` | 종료 |

---

## CLI 명령어 (Typer)

```bash
geode                                  # 인터랙티브 thin CLI
geode "prompt"                         # IPC 경유 원샷 프롬프트
geode --continue                       # 마지막 세션 이어서
geode --resume <session_id>            # 특정 세션 재개

geode version                          # 버전 정보
geode init                             # .geode/ 구조 초기화
geode history                          # 실행 이력 + 비용
geode serve [-p 3.0]                   # Headless daemon
```

---

## 설정 레퍼런스

Secret 은 user-global `~/.geode/.env` 에 둡니다. Project `./.env` 는
global secret 이 없을 때만 채우는 고급 fallback 입니다. Behavior 는
`config.toml` 에 두며, project `./.geode/config.toml` 이
`~/.geode/config.toml` 보다 우선합니다.

`.env` 변수 (전체 목록: `core/config.py`):

| 변수 | 기본값 | 설명 |
|------|--------|------|
| **LLM** | | |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `OPENAI_API_KEY` | | GPT API key (OpenAI adapter) |
| `ZAI_API_KEY` | | ZhipuAI GLM key |
| `GEODE_MODEL` | `claude-opus-4-6` | 수동 session override 전용; 지속 설정은 `config.toml` 사용 |
| `GEODE_ENSEMBLE_MODE` | `single` | 수동 session override 전용; 지속 설정은 `config.toml` 사용 |
| **Gateway** | | |
| `GEODE_GATEWAY_ENABLED` | `false` | 수동 session override; 지속 설정은 `config.toml` 의 `[gateway] enabled = true` 권장 |
| `SLACK_BOT_TOKEN` | | Slack bot token |
| `SLACK_APP_TOKEN` | | Slack Socket Mode app token (`xapp-`, `connections:write`) |
| `SLACK_TEAM_ID` | | 클릭 가능한 진단 링크용 선택 workspace ID |
| **Pipeline** | | |
| **Observability** | | |
| _(별도 env 없음 — 내장 event sink)_ | | lifecycle 이벤트는 project-local `sessions.db:hook_events`에 기록되고, 활성 autoresearch 실행은 정제된 row를 `transcript.jsonl`에도 mirror |

---

## 테스트

```bash
uv run pytest tests/ -m "not live" -q     # 3,422+ tests
uv run ruff check core/ tests/            # Lint
uv run mypy core/                         # Type check (190 modules)
uv run geode version                      # CLI 스모크
```
