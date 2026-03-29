---
name: job-hunter
description: AI/ML Engineer job posting search + match analysis. Triggers: 'job', '채용', '공고', '포지션', '이직', 'recruit', 'hiring', '취업', '구직'.
tools: web_search, web_fetch, memory_save
risk: safe
---

# Job Hunter

Automatically searches for AI/ML Engineer positions and analyzes profile match scores.

## User Profile

- **Role**: AI/ML Engineer (specializing in agentic systems)
- **Core Stack**: Python, LangGraph, MCP, Claude API, OpenAI API, LLM Orchestration
- **Strengths**: Autonomous agent E2E design, harness architecture (GEODE/REODE), frontier model hands-on operation
- **Background**: Former Rakuten Symphony, independent developer, YouTube @mango_fr
- **Preferences**: Remote-first, AI/agent teams, Series B+ startups or Big Tech AI Labs
- **Location**: Korea-based, global remote available

## Search Strategy

### Keyword Combinations (priority order)
1. `"AI Engineer" OR "ML Engineer" + "agentic" OR "LLM" + remote`
2. `"LangGraph" OR "MCP" OR "Claude" + engineer + hiring`
3. `AI engineer hiring agent LLM`
4. `"AI infrastructure" OR "ML platform" + engineer`

### Search Sources
- LinkedIn Jobs (web_search)
- Wanted/RocketPunch (Korea)
- Y Combinator Work at a Startup
- Anthropic/OpenAI/Google DeepMind careers
- RemoteOK, WeWorkRemotely

## Match Analysis

5-axis matching for each posting:

| Axis | Criteria |
|------|----------|
| **Stack Fit** | Match with Python, LLM, agent-related requirements |
| **Role Level** | Senior/Staff level matching |
| **Remote Available** | Fully remote / hybrid / on-site |
| **Growth Potential** | Team size, funding stage, tech vision |
| **Compensation** | Published salary range, stock options |

## Report Format

```markdown
## Job Search Report — YYYY-MM-DD

### Top Matches (80%+ fit)
| Company | Position | Stack | Remote | Compensation | Link |
|---------|----------|-------|--------|--------------|------|

### Candidates of Interest (60-80% fit)
| Company | Position | Notes | Link |

### Market Insights
- AI Engineer demand trends
- Salary band changes
- Notable companies/teams
```

## Schedule Integration

```
/schedule create "every monday at 10:00" action="Search this week's AI/ML Engineer job postings"
```

## Guidelines

- Include only postings published within the last 7 days
- Exclude postings without a clear JD
- Sort by match score in descending order
- Include direct application URL links
- After completion, record insights via memory_save
