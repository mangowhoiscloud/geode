---
name: smoke-green-loop
description: Repeat diagnose, fix, verify, merge, rebuild, and smoke for a GEODE workflow until its declared end-to-end acceptance is green. Use when a smoke run fails, produces empty artifacts, or needs CI-gated iterative repair.
---

# Smoke-Green Loop

Use `.agents/skills/geode-workflow/SKILL.md` and the repository GitFlow. For
each iteration:

1. Preserve the failed run and read its structured state, transcript,
   per-agent results, and diagnostics. Never delete evidence to make a rerun
   green.
2. Identify one root cause and the smallest reproduction. Distinguish runtime
   failure from quota, credentials, remote service, or harness contamination.
3. Fix the shared root, add one regression check, and run targeted static and
   test gates. Update `CHANGELOG.md` for functional changes.
4. Merge through a feature PR to `develop` only after required CI is green.
   Rebuild from the merged revision before rerunning the smoke.
5. Archive the prior run, obtain explicit approval for any live or paid call,
   and rerun with the same frozen inputs unless the hypothesis explicitly
   changes them.

Stop only when the declared completion event exists, every required subtask is
successful, requested artifacts are non-empty, and no failure event remains.
Report every iteration, including invalid attempts and costs; do not select
only the first green run.
