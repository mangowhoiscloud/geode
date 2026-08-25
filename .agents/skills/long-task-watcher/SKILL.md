---
name: long-task-watcher
description: Monitor long-running GEODE work, CI, audits, and training without losing output to buffering or confusing a watcher with the underlying state authority.
---

# Long-Task Watcher Scaffold

1. Read `.geode/skills/long-task-watcher/SKILL.md` for the runtime monitoring
   contract and pattern selection.
2. Treat the task, CI service, queue, or artifact store as authority. A watcher
   reports state; it does not manufacture progress or completion.
3. Prefer the product's bounded wait/status mechanism. If a local command owns
   a log, preserve it from process start and perform a final whole-file read
   after completion.
4. Use a hard deadline and surface task death, timeout, and unchanged state as
   distinct outcomes. Do not call unchanged state a blocker or green result.
5. Report the authoritative completion state, elapsed time, failed attempts,
   and the exact evidence locator. Archive durable evidence before cleanup.

Do not duplicate polling frameworks, add a monitor-specific state store, or run
live/paid work merely to test the watcher.
