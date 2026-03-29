---
name: slack-digest
description: Slack channel conversation summary — catch up on missed messages. Triggers: 'slack', '슬랙', 'digest', '놓친 메시지', '채널 요약'.
tools: web_search, memory_save
risk: safe
---

# Slack Digest

Summarizes Slack channel conversations received via the geode serve Gateway.

## Summary Scope

- Last 24 hours (or user-specified period)
- Targets binding channels registered in config.toml

## Summary Format

```markdown
## Slack Digest — YYYY-MM-DD

### #channel-name
- **Key Discussion**: Core topic in 1-2 sentences
- **Decisions**: Agreed-upon items (if any)
- **Action Items**: Follow-up tasks (if any)
- **Mentions**: Messages related to @mango (if any)

### #other-channel
...
```

## Guidelines

- Exclude small talk/greetings, include only substantive content
- Highlight mentions (@mango) separately
- Prioritize extracting decisions and action items
- Summarize in English
