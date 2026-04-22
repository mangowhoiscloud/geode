---
name: deep-researcher
visibility: public
description: Systematic web search, collection, analysis, and report generation on a topic. Triggers: 'research', '리서치', '조사해', '알아봐', '찾아봐', '트렌드', '동향'.
tools: web_search, web_fetch, memory_save
risk: safe
---

# Deep Researcher

Systematically investigates a given topic and generates a structured report.

## Workflow

1. **Topic decomposition**: Break the user request into 3-5 search queries
2. **Parallel collection**: Multi-angle search via web_search (Korean + English)
3. **Deep collection**: Fetch body text from top 3-5 URLs via web_fetch
4. **Cross-validation**: Only adopt information confirmed by 2+ sources
5. **Report generation**: Write a structured markdown report
6. **Save**: Record insights to project memory via memory_save

## Report Format

```markdown
## [Topic] Research Report
> Date: YYYY-MM-DD | Sources: N

### Key Findings
- Finding 1 (source: ...)
- Finding 2 (source: ...)

### Detailed Analysis
[Organized by section]

### Sources
- [Title](URL) — Summary
```

## Guidelines

- Perform at least 3 searches with different keywords
- No single-source dependency — cross-validation required
- Prioritize recent sources for time-sensitive information
- Clearly distinguish speculation from facts
- Write report in English (keep original-language citations as-is)
