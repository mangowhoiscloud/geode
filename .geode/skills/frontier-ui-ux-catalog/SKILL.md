---
name: frontier-ui-ux-catalog
visibility: public
triggers: terminal ui, spinner, status line, CLI UX, animation, shimmer, 터미널 UI, 스피너
description: Source-grounded catalog of dynamic terminal UI/UX patterns in Claude Code 2.1.170 and Codex CLI 0.142.4 — live status lines, spinner verb sets, streaming and progress affordances. Reference for GEODE CLI/REPL UX work.
---

# Frontier Terminal UI/UX Catalog

Survey of the live, animated terminal UI in the latest installed frontier CLIs
(captured 2026-06-30): Claude Code 2.1.170 (strings extracted directly from
the binary) and Codex CLI 0.142.4 (official docs + GitHub issues).

Use when designing or reviewing GEODE CLI/REPL surfaces — spinners, live
status lines, token/elapsed readouts, streaming updates, progress affordances.
The motivating example is the composite live status line that updates several
times a second:

```
✢ Hyperspacing… (7m 29s · ↓ 27.7k tokens · thought for 7s)
```

## Reference (load on demand)

- `reference.md` — the full catalog: status-line composition, spinner verb
  sets and cadences, streaming/interrupt affordances, and per-surface
  behaviour notes for both CLIs.
