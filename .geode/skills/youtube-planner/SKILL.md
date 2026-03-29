---
name: youtube-planner
description: YouTube video planning — idea to structure to script draft. Triggers: 'youtube', '유튜브', '영상', '콘텐츠', '스크립트', '썸네일', '기획'.
tools: web_search, web_fetch, memory_save
risk: safe
---

# YouTube Planner

Supports video planning for the @mango_fr channel. From idea discovery to script drafts.

## Channel Profile

- **Channel**: @mango_fr
- **Topics**: Agentic engineering, autonomous execution harnesses, hands-on LLM operation
- **Tone**: Deep technical + real-world experience sharing, Korean
- **Target Audience**: AI/ML engineers, developers interested in agent systems

## Workflow

### 1. Idea Discovery
- Lessons learned from recent GEODE development
- Connect with trending AI papers/news
- Frequently asked questions from the community

### 2. Structure Design
```
Hook (15s): Present viewer's problem
Problem Definition (1min): Why this matters
Solution Process (5-8min): Code + architecture + failure stories
Result (1min): Before/after
Wrap-up (30s): Key takeaway + next video preview
```

### 3. Script Draft
- Conversational Korean (polite form)
- Code blocks limited to key parts shown on screen
- Include timestamps

## Output Format

```markdown
## Video Plan — [Title]

### Meta
- Estimated length: N min
- Category: [Agent/LLM/Architecture/Troubleshooting]
- Keywords: tag1, tag2, tag3

### Structure
1. Hook: ...
2. Problem: ...
3. Solution: ...
4. Result: ...

### Script Draft
[Script by timestamp]

### Thumbnail Ideas
- Text: ...
- Visual: ...
```

## Guidelines

- Prioritize actual GEODE development experience as material
- Prefer concrete code/architecture over abstract concepts
- Target videos under 10 minutes
- After completion, record the plan via memory_save
