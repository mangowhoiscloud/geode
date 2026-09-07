---
name: smoke-green-loop
description: Diagnose and repair a failed GEODE smoke workflow within the requested acceptance criteria. Preserve failed evidence, verify the shared root cause, and apply merge, rebuild, or live rerun stages only when authorized.
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
4. If integration is authorized, follow the repository GitFlow and required
   CI. Rebuild or restart only when in scope; a local fix can be verified in
   its owned worktree without first merging or changing a global installation.
5. Archive the prior run, obtain explicit approval for any live or paid call,
   and rerun with the same frozen inputs unless the hypothesis explicitly
   changes them.

Declare success only when the specified acceptance checks pass and requested
artifacts contain the expected evidence. Preserve historical failure events;
they do not need to disappear for a later attempt to succeed. Stop and report
when remaining work needs new authority, user input, or an external-state
change. Report attempted iterations, invalid attempts, costs, and unresolved
limits; do not select only the first green run.
