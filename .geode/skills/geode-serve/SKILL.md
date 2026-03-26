---
name: geode-serve
description: Slack Gateway 운영 가이드. config.toml 바인딩 설정, serve 시작/재시작, 폴러 디버깅, 리액션 동작. "serve", "gateway", "slack", "바인딩", "binding", "폴러", "poller", "config.toml" 키워드로 트리거.
user-invocable: false
---

# geode serve — Slack Gateway 운영 가이드

> **출처**: Gateway 디버깅 세션에서 증류 (2026-03-26)
> **핵심 원인**: `.geode/config.toml` 부재 → 바인딩 0개 → 폴러가 채널을 모니터링하지 않음

## 아키텍처

```
geode serve
  → runtime.py: .geode/config.toml 로드 → ChannelManager.load_bindings_from_config()
  → SlackPoller._poll_once(): bindings에서 slack 채널 필터 → _poll_channel() 반복
  → _poll_channel(): MCP slack_get_channel_history → 신규 메시지 감지 → route_message()
  → _send_response(): MCP slack_post_message (스레드 응답)
```

## 필수 조건

| 항목 | 확인 방법 |
|------|----------|
| `SLACK_BOT_TOKEN` | `echo $SLACK_BOT_TOKEN` — `xoxb-...` |
| `SLACK_TEAM_ID` | `echo $SLACK_TEAM_ID` — `T...` |
| `.geode/config.toml` | `cat .geode/config.toml` — bindings.rules 존재 |
| MCP slack 서버 | 로그에 `MCP connected: npx ... slack` |

## config.toml 설정

```bash
# 템플릿에서 복사 (클린 클론 시)
cp .geode/config.toml.example .geode/config.toml
```

```toml
[gateway.bindings]

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0XXXXXXXXX"  # Slack 채널 → 채널명 클릭 → 맨 아래 Channel ID
auto_respond = true
require_mention = true       # true: @멘션 시에만 응답
max_rounds = 5
```

- `config.toml`은 `.gitignore` 대상 — git pull로 삭제되지 않음
- `config.toml.example`은 커밋됨 — 클린 클론 시 참조용
- **채널 추가**: `[[gateway.bindings.rules]]` 블록을 반복

## 시작/재시작

```bash
# 기존 프로세스 종료
kill $(pgrep -f "geode serve")

# 재시작 (백그라운드)
nohup uv run geode serve > /tmp/geode-gateway.log 2>&1 &

# 또는 포그라운드
uv run geode serve
```

## 디버깅 체크리스트

### 증상: 봇이 메시지에 응답하지 않음

```bash
# 1. 프로세스 확인
ps aux | grep "geode serve"

# 2. 바인딩 로드 확인
grep "binding" /tmp/geode-gateway.log
# 기대: "Loaded N gateway bindings from config"
# 0이면 → config.toml 부재 또는 파싱 에러

# 3. Slack MCP 연결 확인
grep "slack" /tmp/geode-gateway.log | grep -i "connect"
# 기대: "MCP connected: npx ... slack"

# 4. 폴링 시드 확인
grep "seeded" /tmp/geode-gateway.log
# 기대: "Slack poller seeded ts=... for C0XXX (N skipped)"
# 없으면 → health check 실패 또는 채널 ID 오류

# 5. 메시지 수신 확인
grep "Slack message from" /tmp/geode-gateway.log
```

### 증상별 원인

| 증상 | 원인 | 해결 |
|------|------|------|
| "Loaded 0 gateway bindings" | `.geode/config.toml` 없음 | `cp config.toml.example config.toml` + 채널 ID 입력 |
| seeded 로그 없음 | Slack MCP 미연결 또는 SLACK_BOT_TOKEN 미설정 | 환경변수 확인 + MCP 로그 확인 |
| 메시지 수신되나 응답 없음 | `require_mention=true`인데 @멘션 안 함 | @봇이름으로 멘션하거나 `require_mention=false` |
| 봇 자신의 메시지에 재응답 | bot_message 필터 우회 | `bot_id` 필드 확인 — 정상이면 Slack App 설정 점검 |

## 리액션 동작

`require_mention = true` + `<@BOT_ID>` 멘션 메시지:

1. :eyes: 리액션 (수신 확인)
2. `ChannelManager.route_message()` → AgenticLoop 실행
3. :white_check_mark: 리액션 (완료)
4. 스레드에 응답 전송

일반 메시지 (멘션 없음, `require_mention = false`):
- 리액션 없이 바로 처리 + 스레드 응답

## 관련 파일

| 파일 | 역할 |
|------|------|
| `core/gateway/pollers/slack_poller.py` | Slack 폴링 + 응답 |
| `core/gateway/channel_manager.py` | 바인딩 관리 + 메시지 라우팅 |
| `core/gateway/slack_formatter.py` | Markdown → Slack mrkdwn 변환 |
| `core/runtime.py:1024-1036` | config.toml 로드 로직 |
| `.geode/config.toml` | 채널 바인딩 (로컬, 비추적) |
| `.geode/config.toml.example` | 바인딩 템플릿 (커밋됨) |
