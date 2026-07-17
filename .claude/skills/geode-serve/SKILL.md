---
name: geode-serve
description: Slack Gateway operations guide. Socket Mode credentials, config.toml bindings, serve restart, receiver debugging, reaction behavior. Triggers on "serve", "gateway", "slack", "바인딩", "binding", "소켓", "socket", "폴러", "poller", "config.toml".
user-invocable: false
---

# geode serve — Slack Gateway Operations Guide

> **Source**: Distilled from Gateway debugging session (2026-03-26)
> **Primary failure modes**: missing binding, missing `xapp-` token, or bot not invited to a bound channel

## Architecture

```
geode serve
  → core/wiring/adapters.py: Merge ~/.geode/config.toml + project overlay
  → SlackPoller: SLACK_APP_TOKEN present → SlackSocketModeClient.run()
  → bounded-queue admit → ACK Events API envelope → filter exact bound channel → route_message()
  → _send_response(): SlackTransport.post_message (direct Web API, thread reply)

No `SLACK_APP_TOKEN` selects an explicit degraded polling fallback. It is a
migration path, not the operational target.
```

## Prerequisites

| Item | How to verify |
|------|---------------|
| `SLACK_BOT_TOKEN` | `echo $SLACK_BOT_TOKEN` — `xoxb-...` |
| `SLACK_APP_TOKEN` | `echo $SLACK_APP_TOKEN` — `xapp-...`, `connections:write` |
| App settings | Socket Mode on; bot events `app_mention`, `message.channels` |
| `.geode/config.toml` | `cat .geode/config.toml` — bindings.rules exist |
| Slack health | `geode doctor slack` is `OPERATIONAL`; every binding says `bot_member=True` |

## config.toml Setup

```bash
# Copy from template (on clean clone)
cp .geode/config.toml.example .geode/config.toml
```

```toml
[gateway.bindings]

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0XXXXXXXXX"  # Slack channel → Click channel name → Channel ID at bottom
auto_respond = true
require_mention = true       # true: respond only on @mention
max_rounds = 5
```

- `config.toml` is in `.gitignore` — not deleted by git pull
- `config.toml.example` is committed — reference for clean clones
- **Adding channels**: Repeat `[[gateway.bindings.rules]]` blocks

## Start/Restart

```bash
# Kill existing process
kill $(pgrep -f "geode serve")

# Restart (background)
nohup uv run geode serve >/dev/null 2>&1 &

# Or foreground
uv run geode serve
```

## Debugging Checklist

### Symptom: Bot does not respond to messages

```bash
# 1. Check process
ps aux | grep "geode serve"

# 2. Verify binding load
grep "binding" ~/.geode/logs/serve.log
# Expected: "Loaded N gateway bindings from config"
# If 0 → config.toml missing or parse error

# 3. Verify config source and Socket Mode
grep -i "gateway config sources" ~/.geode/logs/serve.log
# Expected: "Gateway config sources: global:... [, project:...]"

grep -E "Slack inbound mode|Slack Socket Mode connected" ~/.geode/logs/serve.log
# Expected: Socket Mode (push), then connected

# 4. Verify credentials, scopes, and channel membership
geode doctor slack

# 5. Verify message reception after an @geode mention
grep "Slack message from" ~/.geode/logs/serve.log
```

### Symptoms and Causes

| Symptom | Cause | Resolution |
|---------|-------|------------|
| "Loaded 0 gateway bindings" | `.geode/config.toml` missing | `cp config.toml.example config.toml` + enter channel ID |
| `polling fallback` | `SLACK_APP_TOKEN` missing | Create an `xapp-` app token with `connections:write`, add it to `~/.geode/.env`, restart |
| `not_in_channel` / `bot_member=False` | Bot was not invited | Run `/invite @geode` in the linked channel |
| Repeated disconnects | App token invalid or Socket Mode disabled | Run `geode doctor slack`, then verify app-level token and Socket Mode settings |
| New top-level/unengaged message receives no response | `require_mention=true` but no @mention | Mention @botname once or set `require_mention=false` |
| Engaged thread stops after daemon restart | No resumable ACTIVE/PAUSED checkpoint, or receiver is still polling | Confirm Socket Mode logs; re-mention once if the prior machine is terminal |
| Bot re-responds to its own messages | bot_message filter bypassed | Check `bot_id` field — if normal, check Slack App settings |

## Reaction Behavior

`require_mention = true` + first `<@BOT_ID>` mention:

1. :eyes: reaction (acknowledge receipt)
2. Normalize the root `ts` as `thread_id` and remember the engaged thread
3. `ChannelManager.aroute_message()` → AgenticLoop execution
4. :white_check_mark: reaction (complete)
5. Send response in thread

Later human reply in that engaged thread (no repeated mention):

1. Match channel-scoped engaged state or the durable ACTIVE/PAUSED gateway checkpoint
2. Reuse the same session/lane/checkpoint key and restore checkpoint messages after restart
3. Run the same :eyes: → AgenticLoop → :white_check_mark: → thread-response lifecycle

Unengaged regular message (no mention, `require_mention = false`):

- Process without reaction + thread response

## Related Files

| File | Role |
|------|------|
| `core/messaging/slack_socket_mode.py` | Socket URL, WebSocket ACK/reconnect loop |
| `core/server/supervised/slack_poller.py` | Socket event normalization + compatibility fallback |
| `core/messaging/binding.py` | Binding management + message routing |
| `core/messaging/slack_transport.py` | Bot-token Web API outbound + channel diagnostics |
| `core/wiring/adapters.py` | Gateway config merge and receiver registration |
| `.geode/config.toml` | Channel bindings (local, untracked) |
| `.geode/config.toml.example` | Binding template (committed) |
