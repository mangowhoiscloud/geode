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
- [ ] Audit bundle D (expanded by dup/dead-code audit) — D-1 safe-delete batch (Settings 17 fields, 9 zombie modules + their tests, paths orphan constants) / D-2 path anchors (petri logs ×6, seed-pool ×3, paths.py bypasses, config template fork, CLI defaults) / D-3 operator decisions (G1-G4 guardrails, M4.x DPO chain, recall_writer, mcp_server) — awaiting pick

## In Review

<!-- PRs submitted, awaiting CI + review. -->

## Done

<!-- Completed items. Keep recent 10, archive older ones. -->
<!-- - [x] #issue-number — Short description (PR #N) -->
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
