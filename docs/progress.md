# GEODE Progress Board

> Multi-agent shared kanban. Updated from `main` only.
> Each item maps 1:1 to a GitHub Issue or TaskCreate ID.

## Backlog

<!-- Add items here when identified. Format: -->
<!-- - [ ] #issue-number — Short description (@assignee) -->
- [ ] CLI white-line — operator TTY visual confirm at idle prompt (post-rebuild v0.99.147)
- [ ] 10-cycle self-improving campaign — runtime resync (A+B merged) + operator launch
- [ ] viz-sync — geode_hero / critical_floor / autoresearch_compare → 18-dim
- [ ] Target re-selection — broken/input floor on opus-4-8 (operator decision)

## In Progress

<!-- Move items here when work begins. -->
<!-- 3-Checkpoint: (1) alloc → (2) merge (CI 5/5) → (3) verify -->
- [ ] Folder-structure audit follow-ups — report delivered (F1/F2 stale, already shipped in D-1); standing: loop/ 32-module split + train.py 5,510L, tests/ triple convention (330 flat vs 190 nested + dup self_improving roots), cli cmd_*/commands/ dual home, misplaced modules (bash_tool/run_log ×2/audit_lane/seed tools), scripts→CLI promotion, integrations→messaging flatten, husk sweep, layer map 11/21

## In Review

<!-- PRs submitted, awaiting CI + review. -->

## Done

<!-- Completed items. Keep recent 10, archive older ones. -->
<!-- - [x] #issue-number — Short description (PR #N) -->
- [x] Slop cleanup sprint: 5 Game-IP-era skills + 4 orphan prompt templates + axes.py husk deleted (hash pins 15→4), router.md dedupe + (CRITICAL) 4→2, program.md verdict-label fix, CLAUDE.md skills-table/entry-point sync; LinkedIn/playwriter audit claims rejected as MCP false positives (PR #2068 → #2069, v0.99.157)
- [x] llms.txt sprint: router.md llms.txt-first research heuristic + web_fetch description (instruction-level per frontier convergence) + site llms.txt llmstxt.org spec shape + sitemap section-parser regression fix (lost groupings since docs redesign) (PR #2063 → #2064, v0.99.156)
- [x] Audit bundle D-3a: G1-G4 guardrail subgraph + M4.x DPO chain deleted (operator decisions ①②), AUTORESEARCH_VERDICT derived from gate outcome (⑥), CYCLE_INPUT_POOL repo-pinned semantics recorded (⑤) (PR #2056 → #2057, v0.99.154)
- [x] Audit bundle D-3b: /recall slash surface (save/list/show, reader-parser parity) + geode-mcp first-class entry point (run_agent / self_improving_status / propose+apply two-step gate), run_agentic_oneshot shared stack (PR #2059 → #2060, v0.99.155)
- [x] Audit bundle D-1: safe-delete batch — 10 zombie modules + 9 dedicated tests, 16 dead Settings fields, v0.88 router compat surface, orphaned instructor/textgrad deps (PR #2047 → #2048, v0.99.152)
- [x] Audit bundle D-2: path/config anchors — petri logs ×6, seed-pool ×3, CLI bootstrap paths, config template fork, campaign defaults, shared CLI serializer + Quality Gates table now mirrors CI incl. scripts/ (PR #2050 → #2051, v0.99.153)
- [x] Audit bundle E: drift anchors — PROVIDER_REGISTRY_NORMALIZATION (4 copies unified) + core/llm/model_capabilities.py (5 mirror sets), identity-pinned by test_drift_anchors.py (PR #2042 → #2043, v0.99.151)
- [x] Dup/dead-code follow-up audit — report delivered: 10 literal mirrors (petri logs ×6, config template fork w/ stale model, seed-pool ×3) + 15+ test-only zombie modules, D bundle expanded
- [x] Audit bundles A+B: session-store fake-success wired + _load_baseline graceful guard + TLS/cost fallback visibility + MUTATION_REJECTED emits (5 sites) + VERIFICATION_*/FALLBACK_CROSS_PROVIDER deleted (HookEvent 64) (PR #2037 → #2038, v0.99.150)
- [x] Audit bundle C: dead pipeline family deleted — 15 HookEvents (82→67), core/automation/ + StuckDetector + TaskGraphHookBridge + NodeBootstrapper removed, live scheduler → wiring/scheduling.py, -6,654 LoC (PR #2032 → #2033, v0.99.149)
- [x] Prompt-cache: system reminder append-only — messages[0] per-round rewrite was invalidating the whole history prefix cache every agentic round; reminder now appended last on a per-request copy, pinned by TestCacheContract (PR #2026 → #2028, v0.99.148)
- [x] Ops: auto-backmerge unblocked — repo Actions workflow permissions `read`→`write` + allow PR create/approve; rerun of failed run 27224199909 green (no PR/version)
- [x] Ops: stale worktree prune — baseline-registry (superseded by #1913 v2) / release-v0.99.72 / release-v0.99.83 / runtime-main + local branches deleted (no PR/version)
- [x] CLI: program.md fallback hook-controlled — drop `_FALLBACK_SYSTEM_PROMPT` literal, `HookEvent.PROGRAM_MD_UNREADABLE` + fail-loud, hook 81→82 (PR #2022, v0.99.147)
- [x] Scaffold §7: serve-kill `pkill -f` — fix `ps aux | grep` truncation footgun that left stale daemons fighting over the socket (PR #2020)
- [x] CLI: remove cold-start "white line" — hide empty quota bar per prompt (PR #2018, v0.99.146)
- [x] Session model resolution: daemon adopts each session's project model + `.env` outranks `config.toml` (PR #2014 / #2016, v0.99.145)
- [x] System-prompt quality pass — hook count 69→81, SOUL over-promise scope, wrapper persona (PR #2012)
- [x] Runtime Anthropic primary opus-4-7 → opus-4-8 + GEODE.md Models sync (PR #2010)
