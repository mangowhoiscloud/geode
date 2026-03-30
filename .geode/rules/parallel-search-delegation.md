---
name: parallel-search-delegation
paths:
  - "*search*"
  - "*탐색*"
  - "*조사*"
  - "*리서치*"
  - "*수집*"
  - "*채용*"
  - "*job*"
  - "*compare*"
  - "*batch*"
---

## Parallel Search Delegation Rule (CANNOT)

### Principle
When a task requires 3+ parallel or sequential web searches, the parent agent
MUST NOT execute them directly. Instead, delegate to sub-agents via
`delegate_task` to prevent context explosion in the parent's window.

### Why
Each `general_web_search` result appends 5-20K tokens to the parent's context.
14 sequential searches accumulated 277K input tokens, crossing the 200K
long-context rate limit threshold and exhausting all Anthropic models.
Sub-agents have isolated context windows — only their summary (< 500 tokens)
returns to the parent.

### CANNOT
- Parent agent calling `general_web_search` 3+ times in a single turn
- Parent agent calling `read_web_page` 3+ times in a single turn
- Parent agent accumulating tool results that push context beyond 150K tokens

### MUST
- **3+ searches needed**: Use `delegate_task` with a clear description
  - Each sub-agent handles 2-4 related searches
  - Sub-agent returns a structured summary (key findings, URLs, dates)
- **Result aggregation**: Parent receives summaries from all sub-agents,
  then synthesizes the final answer
- **Task decomposition**: Split by topic, not by search engine
  - Good: "Search for AI agent jobs at NAVER" (topic-scoped)
  - Bad: "Do search query 1, query 2, query 3" (mechanical split)

### Example Decomposition
User request: "한국 AI 에이전트 채용 전방위 탐색"

Instead of 14 sequential `general_web_search` calls:
```
delegate_task([
  {description: "NAVER/카카오 AI agent 채용 공고 탐색", ...},
  {description: "토스/당근 AI engineer 채용 공고 탐색", ...},
  {description: "업스테이지/뤼튼 AI agent 채용 공고 탐색", ...},
  {description: "기타 한국 스타트업 AI 채용 탐색", ...},
])
```

Each sub-agent: 2-4 `general_web_search` calls within its own isolated context.
Parent receives 4 summaries (< 2K tokens total) instead of 277K raw results.

### Scope
- Job/recruitment searches
- Market research and trend collection
- Competitive analysis
- Any exploratory task requiring broad web coverage
