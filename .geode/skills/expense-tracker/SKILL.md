---
name: expense-tracker
description: Track agentic engineering investment/expenses. Triggers: 'expense', '지출', '비용', 'cost', '투자', '얼마 썼'.
tools: memory_save
risk: safe
---

# Expense Tracker

Tracks and analyzes investment costs for agentic engineering projects.

## Tracking Categories

| Category | Example Items |
|----------|---------------|
| **API Costs** | Anthropic, OpenAI, ZhipuAI monthly usage |
| **Infrastructure** | Servers, domains, CI/CD, GitHub |
| **Tools/Services** | MCP server API keys, SaaS subscriptions |
| **Learning** | Courses, books, conferences |
| **Hardware** | GPU, MacBook, monitors |

## Report Format

```markdown
## Investment Status — as of YYYY-MM-DD

### Cumulative Investment (25.10 ~ present)
- **Total**: ₩XX,XXX,XXX
- **API Costs**: ₩...
- **Infrastructure**: ₩...
- **Tools**: ₩...

### Monthly Trends
| Month | API | Infrastructure | Other | Total |
|-------|-----|----------------|-------|-------|

### Insights
- Largest cost item: ...
- Month-over-month change: ...
- Potential savings: ...
```

## Guidelines

- When the user provides amounts, record them via memory_save
- Query past expense data from existing memory
- Use KRW (₩) as the base, with USD equivalent noted alongside
- Classify API costs by provider
