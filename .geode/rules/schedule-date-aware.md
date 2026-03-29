---
name: schedule-date-aware
paths:
  - "*schedule*"
  - "*batch*"
  - "*cron*"
  - "*job*"
  - "*search*"
  - "*채용*"
  - "*뉴스*"
  - "*trend*"
---

## Date-Aware Schedule Execution Rules

### Principle
Since the LLM's training data cutoff may have passed, all schedule/batch job executions must perform the following:

### Execution Protocol
1. **Date Verification (Mandatory Step 1)**: Before starting any task, always verify the current date using `general_web_search("today's date")` or `run_bash("date")`
2. **Date Tagging**: Include the verified year/month in all search queries (e.g., "LLM developer jobs March 2026")
3. **Freshness Filter**: When performing web searches, apply freshness='pw' (past 7 days) or 'pm' (past 31 days) when possible
4. **Result Verification**: Cross-check that the dates in search results match the current time
5. **Cutoff Warning**: When providing time-sensitive information using only LLM knowledge without web search, always display a ⚠️ cutoff warning

### Scope
- Job posting searches
- News/trend collection
- Price/market data lookups
- IP latest trend analysis
- All time-sensitive scheduled tasks

### Prohibited Actions
- ❌ Claiming information is "latest" without date verification
- ❌ Presenting pre-cutoff training data as current facts
- ❌ Delivering search results without verifying their dates
