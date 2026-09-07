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

## Date-Aware Research

Apply when the requested answer depends on freshness, including scheduled news,
job, price, or trend research. Scheduling alone does not require a date lookup.

- Prefer the authoritative current date, run timestamp, and timezone supplied
  by the runtime. If missing or inconsistent and material to the answer, use an
  available, permitted clock source; do not require a shell or web call merely
  to start a task.
- Add a year/month or freshness filter only when it matches the requested
  period. Preserve older primary evidence when it remains relevant.
- Check publication dates and event dates separately before calling a result
  current. Do not present remembered information as a verified current fact.
- State the as-of date and any material freshness limitation in the result.
