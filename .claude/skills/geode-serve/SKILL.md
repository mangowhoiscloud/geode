---
name: geode-serve
description: Slack Gateway operations guide. config.toml binding settings, serve start/restart, poller debugging, reaction behavior. Triggers on "serve", "gateway", "slack", "바인딩", "binding", "폴러", "poller", "config.toml".
user-invocable: false
---

# geode serve — Slack Gateway Operations Guide

> **Source**: Distilled from Gateway debugging session (2026-03-26)
> **Root cause**: Missing `.geode/config.toml` → 0 bindings → poller not monitoring any channel

## Architecture

```
geode serve
  → runtime.py: Load .geode/config.toml → ChannelManager.load_bindings_from_config()
  → SlackPoller._poll_once(): Filter slack channels from bindings → _poll_channel() loop
  → _poll_channel(): MCP slack_get_channel_history → Detect new messages → route_message()
  → _send_response(): MCP slack_post_message (thread reply)
```

## Prerequisites

| Item | How to verify |
|------|---------------|
| `SLACK_BOT_TOKEN` | `echo $SLACK_BOT_TOKEN` — `xoxb-...` |
| `SLACK_TEAM_ID` | `echo $SLACK_TEAM_ID` — `T...` |
| `.geode/config.toml` | `cat .geode/config.toml` — bindings.rules exist |
| MCP slack server | Log shows `MCP connected: npx ... slack` |

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
nohup uv run geode serve > /tmp/geode-gateway.log 2>&1 &

# Or foreground
uv run geode serve
```

## Debugging Checklist

### Symptom: Bot does not respond to messages

```bash
# 1. Check process
ps aux | grep "geode serve"

# 2. Verify binding load
grep "binding" /tmp/geode-gateway.log
# Expected: "Loaded N gateway bindings from config"
# If 0 → config.toml missing or parse error

# 3. Verify Slack MCP connection
grep "slack" /tmp/geode-gateway.log | grep -i "connect"
# Expected: "MCP connected: npx ... slack"

# 4. Verify polling seed
grep "seeded" /tmp/geode-gateway.log
# Expected: "Slack poller seeded ts=... for C0XXX (N skipped)"
# If missing → health check failed or channel ID error

# 5. Verify message reception
grep "Slack message from" /tmp/geode-gateway.log
```

### Symptoms and Causes

| Symptom | Cause | Resolution |
|---------|-------|------------|
| "Loaded 0 gateway bindings" | `.geode/config.toml` missing | `cp config.toml.example config.toml` + enter channel ID |
| No seeded log | Slack MCP not connected or SLACK_BOT_TOKEN not set | Check env vars + MCP logs |
| Messages received but no response | `require_mention=true` but no @mention | Use @botname or set `require_mention=false` |
| Bot re-responds to its own messages | bot_message filter bypassed | Check `bot_id` field — if normal, check Slack App settings |

## Reaction Behavior

`require_mention = true` + `<@BOT_ID>` mention message:

1. :eyes: reaction (acknowledge receipt)
2. `ChannelManager.route_message()` → AgenticLoop execution
3. :white_check_mark: reaction (complete)
4. Send response in thread

Regular message (no mention, `require_mention = false`):
- Process without reaction + thread response

## Related Files

| File | Role |
|------|------|
| `core/gateway/pollers/slack_poller.py` | Slack polling + response |
| `core/gateway/channel_manager.py` | Binding management + message routing |
| `core/gateway/slack_formatter.py` | Markdown → Slack mrkdwn conversion |
| `core/runtime.py:1024-1036` | config.toml load logic |
| `.geode/config.toml` | Channel bindings (local, untracked) |
| `.geode/config.toml.example` | Binding template (committed) |
