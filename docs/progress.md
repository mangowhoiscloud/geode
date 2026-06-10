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
- [ ] Docs sprint — 전 페이지 재생성/재설계 진행 중: Phase 0 캐논(v0.99.168)·Phase 1 팩트시트 4종(~/.geode/diagnostics/docs-sprint/)·Phase 2 Axolotl Rose 재스킨(v0.99.173)·**3a(PR #2130→#2131) + 3b Concepts+Self-Improving 21페이지+문체 검수(PR #2135→#2134) 완료**. 잔여: 3c Operate/Guides/Reference/Develop+08b 삭제(워크트리 docs-3c, 에이전트 진행 중), 3d Config, Phase 4 최종 검증(Codex MCP). 브리프=memory project_docs_sprint_brief_2026_06_11 + project_docs_redesign_decisions_2026_06_11
- [ ] H11-tail — routing 상수 모듈레벨 by-value 별칭 해동(core/llm/providers/{anthropic,openai,codex,glm}.py DEFAULT_*/FALLBACK_MODELS + core/skills/agents.py dataclass 기본값) — reload 후에도 boot-frozen, 호출자 스윕 필요. + H1(데몬 client-cwd 세션 해석)은 별도 결정

## In Review

<!-- PRs submitted, awaiting CI + review. -->

## Done

<!-- Completed items. Keep recent 10, archive older ones. -->
<!-- - [x] #issue-number — Short description (PR #N) -->
- [x] Docs 디자인 재설정(Axolotl Rose, docs-sprint Phase 2) — 캐릭터 추출 팔레트(로즈 시그니처+골드+아쿠아), Hermes 틴트 규율, petri-blue 04 스코프 강등, docs 표면 하드코딩 hex/white-유틸 전수 토큰화(잔존 0), 랜딩 캐릭터 배치, DESIGN.md §1-2 재작성, 헤드리스 크롬 3면 시각 검수 (PR #2120 → #2126, v0.99.173)
- [x] Docs content canon + banned-term CI gate — site/CONTENT-CANON.md(정체성: 자기개선 루프=선택, ML 아님 + 5-layer + 시각화 스펙) + scripts/check_docs_canon.py pages.yml blocking 배선, ML 오기술 4페이지 정정(autoresearch 제목 "자가 ML 실험 루프" 등) (PR #2107 → #2110, v0.99.168)
- [x] geode-mcp 원격 접근 — `--http` streamable-HTTP 전송 + GEODE_MCP_TOKEN bearer 인증(SDK auth=AuthSettings 동반 필수 함정 핀), 무토큰 비-루프백 바인드 거부, 라이브 왕복 가드 9종 + 프로덕션 스모크 (PR #2118 → #2119, v0.99.171)
- [x] geode-mcp 노출 점검 — Claude Code 등록(.mcp.json repo-ship)+stdio 라이브 검증, 핸드셰이크 버전 오보고(1.26.0→GEODE 버전)·get_health OAuth 오보고(credential_source 병기) 수정, README/README.ko 검증표 기록 (PR #2113, v0.99.169)
- [x] C-4 config tail — H9 GEODE_CONFIG_TOML 메인로더 통일 + H11 reload시 routing 재바인드(모듈레벨 별칭 잔존=H11-tail) + H13 reload 필드별 경고 + 공유 env loader(train/campaign 순서 정렬)+keep-flag .env 인식 (PR #2114 → #2115, v0.99.170)
- [x] C-3 config loading 통일 — dotenv 단일 순서(project .env 승, H5) + serve 데몬 BEHAVIOR_ENV_KEYS 드롭(세션 reload 항상 승, H2, 탈출구 GEODE_SERVE_KEEP_MODEL_ENV=1) (PR #2105 → #2106, v0.99.167)
- [x] C-1 geode config explain + about mask warning (PR #2094 → #2095, v0.99.164)
- [x] C-2 .env=secrets-only — /model·effort·login-source toml-only + stale-mask auto-cleanup, credential_source cascade read-back (PR #2097 → #2098, v0.99.165)
- [x] Fable 5 support — /model 픽커+capability 앵커+refusal stop_reason(termination model_refusal), 공식문서 3종 검증·인용, 전환 E2E PASS (PR #2100 → #2102, v0.99.166)
- [x] Struct S-5: autoresearch-원형 restore (option b) — train.py 5,542→1,656L, gear → measure/fitness/gate/ledger (dry-run equivalence pinned, regression-vs-main 0), loop/ → mutate/observe/inject domains, program.md single-file contract restored + GEODE.md 5-layer formalised (PR #2090 → #2091, v0.99.163) — STRUCTURE SPRINT S-1..S-5 COMPLETE
- [x] Struct S-3: CLI single home (cmd_*.py ×5 → commands/) + geode seeds assemble / geode hub build promotion (repo-only fail-loud wrappers) (PR #2083 → #2084, v0.99.161)
- [x] Struct S-4: core/utils dissolved (atomic_write→memory, env_io+project_detect→config, redaction→observability, similarity→seedgen; census corrected 2 blueprint guesses) + seed tools → plugins/seed_generation/tools/ + integrations→messaging flatten (PR #2086 → #2087, v0.99.162)
- [x] Struct S-2: test tree → source-mirror convention — 350 git mv (flat 323 + self_improving/audit/observability root folds), 55 repo-root anchors bumped, 26 literal-path sweeps (release.yml mypy targets incl.), ruff src 'tests' root removed (mirror dirs were a second core.* package, isort flip) (PR #2079 → #2080, v0.99.160)
- [x] Struct S-1: misplaced-module moves (bash_tool/audit_lane/config.self_improving/fts_query, 32-importer rename) + hardcoding anchors (CONTEXT_BLOCK_MAX_CHARS ×4, DEFAULT_AGENT_MODEL ×10, pages/repo URLs, registry pagination) (PR #2072 → #2073, v0.99.158)
- [x] S-6 observability: sessions.jsonl now carries run metrics (to_session_row had 0 callers — HIGH), run_log ×2 fold → observability JsonlAppendLog, LatencyMetrics rename, configure_logging(mode) switchboard (mcp/worker/campaign file logs), dead langgraph-checkpoint pins dropped; state/checkpoints verified healthy (PR #2075 → #2076, v0.99.159)
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
