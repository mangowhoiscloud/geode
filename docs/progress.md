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

- [ ] llms_txt_index 전용 도구 — llms.txt 인덱스를 구조화 JSON으로 파싱하는 도구 신설(mcpdoc 2-도구 패턴 수렴, fetch는 기존 web_fetch 재사용). web_fetch 10k truncation으로 큰 인덱스 뒷섹션 소실 문제 해소. router.md 휴리스틱 도구-first 개정 + AGENTIC_SUFFIX re-pin + 가드 갱신
- [ ] H11-tail — routing 상수 모듈레벨 by-value 별칭 해동(core/llm/providers/{anthropic,openai,codex,glm}.py DEFAULT_*/FALLBACK_MODELS + core/skills/agents.py dataclass 기본값) — reload 후에도 boot-frozen, 호출자 스윕 필요. + H1(데몬 client-cwd 세션 해석)은 별도 결정

## In Review

<!-- PRs submitted, awaiting CI + review. -->

## Done

<!-- Completed items. Keep recent 10, archive older ones. -->
<!-- - [x] #issue-number — Short description (PR #N) -->
- [x] Game-IP 시대 검증 잔재 퍼지 — 벤치마크 리포트 사전 정직성 패스(운영자 지시). zero-caller 코드 2건 삭제(Settings.temperature_verification, get_common_rubric) + 운영 문서의 죽은 주장 교정: GEODE.md(SOUL) Expert Panel/G3/confidence-0.7 루프백, README×2 "G1-G4+Cross-LLM α≥0.67" → 실측 turn-verify 계층, AGENTS.md 유령 섹션 2개(core/verification, core/automation), setup×2 Cross-LLM 라벨. 후속 후보: ensemble_mode 노브(display-only), AGENTS.md core/gateway stale (PR #2210, v0.99.187)
- [x] /model source 재추론 + 픽커 UX 묶음 — (1) provider 전환 시 source 재추론(login codex 직후 401 = anthropic 시절 payg가 openai로 따라오던 건, 명시 핀 보존), (2) Space 스테이징(역할 3개 한 세션), (3) 폭 클램프 리페인트(화살표 위로 쏠림 = 래핑 vs _clear_lines 불일치), (4) 비-primary 픽 global 스코프(write-read parity — project에 쓰고 global만 읽던 누수), (5) harness/cli 키 계약 문서화. 가드 11종 (PR #2206 → #2207, v0.99.186)
- [x] web_search 타이밍 정합 + 프론티어 브리지 수렴 — fable-5 검색 58~60s가 60s 클라이언트 타임아웃·120s deadline과 경계 충돌(건강한 재시도 119.9s 사살). 타임아웃 100s/deadline 240s + 부등식 가드. 웹훅 일회용 루프→메인 루프 run_coroutine_threadsafe(hermes/openclaw 수렴), verify ThreadPool 브리지 제거. 가드레일 25테스트 (PR #2201 → #2202, v0.99.185)
- [x] 이벤트 루프 오염 수정 — sync 델리게이트 잔재(도구 호출마다 asyncio.Runner 루프) × 전역 SDK 클라이언트 공유 = web_search 즉사/행(sample로 좀비 루프 2개 물증). async-native 핸들러 21개 + LoopAffineClientCache(adapter 6+provider 3) + 도구/MCP wall-clock deadline + web_search 모델 capability 선택 + 가드레일 21테스트 + run_process_coroutine 카나리아. Codex 4건 반영 (PR #2192 → #2194, v0.99.183)
- [x] stale-dim 할루시네이션 가드 — 시드/풀이 live taxonomy(AXIS_TIERS) 밖 dim 참조 시 assemble 시점 fail-closed(런타임 HALT보다 앞). 운영자 지시(캠페인 HALT 후). 인시던트=held-out redundant_tool_invocation stale. 가드 4종+CLAUDE.md CANNOT (PR #2185 → #2186, v0.99.181)
- [x] dispatch transient-retry + 가드레일 — 장수 데몬의 오염된 pooled connection이 web_search/complete_text를 2-4ms 즉사시키던 건. 같은 adapter 1회 재시도(연결류 한정, PR-NO-FALLBACK 보존, billing 재시도 금지) + cause-chain 로깅 + 15-테스트 가드레일(병렬배치 회복·registry parity ratchet). Codex 3건 반영 (PR #2181 → #2182, v0.99.180)
- [x] 시나리오 품질 P0 — frontier survivor selection(~50% R-Zero band) + saturation 신호 generator wire. self-improving 포화(critical 전부 1.0) 탈출 1차. Codex 검증(orphan 1건 수정). 효과측정=캠페인 variant 분산 (PR #2177 → #2178, v0.99.179)
- [x] /model picker Cancelled — thin CLI가 profile 미하이드레이션→model_available 전부 False→blocked-Enter. ensure_profile_store로 hydrate (PR #2145, v0.99.176)
- [x] tool-call 줄 들여쓰기 들쭉날쭉 — _redraw가 cursor-up 후 column 미복귀. 각 줄 \\r prefix (PR #2155, v0.99.177)
- [x] Docs sprint — 전 페이지 재생성/재설계 COMPLETE: Phase 0 캐논+금지어 CI 게이트(v0.99.168) → Phase 1 팩트시트 4종 → Phase 2 Axolotl Rose 재스킨(v0.99.173) → 3a~3d 콘텐츠 4배치(랜딩+66페이지 재생성, 08b 4p 삭제, runtime/research 신규, README Site 링크 제거, 배치별 문체 검수) → Phase 4 Codex 적대 감사(26주장: 24 OK, REFUTED 2건 p4 정정 #2151→#2152). 잔존 후속은 memory project_docs_sprint_complete_2026_06_11 (GEODE.md 격리 과장=운영자 결정, Mermaid/시그니처 SVG 미구현)
- [x] geode-mcp HTTP 원격 접근 — `--http` streamable-HTTP + GEODE_MCP_TOKEN bearer (PR #2118, v0.99.171)
- [x] geode-mcp run_agent 라이브 핫픽스 — adapter bootstrap(.172) + event-loop async(.174) (PR #2123/#2127)
- [x] /model 라이브 세션 미반영 버그 — thin-CLI↔daemon gap, cmd_model이 settings만 갱신·live loop 미반영(drift-sync는 PR-DRIFT-CUT no-op). CLIPoller가 /model 후 live loop 동기화(primary-axis delta gate, role-switch clobber 방지). Codex 검증 1건 반영 (PR #2139 → #2140, v0.99.175)
- [x] Docs 디자인 재설정(Axolotl Rose, docs-sprint Phase 2) — 캐릭터 추출 팔레트(로즈 시그니처+골드+아쿠아), Hermes 틴트 규율, petri-blue 04 스코프 강등, docs 표면 하드코딩 hex/white-유틸 전수 토큰화(잔존 0), 랜딩 캐릭터 배치, DESIGN.md §1-2 재작성, 헤드리스 크롬 3면 시각 검수 (PR #2120 → #2126, v0.99.173)
- [x] Docs content canon + banned-term CI gate — site/CONTENT-CANON.md(정체성: 자기개선 루프=선택, ML 아님 + 5-layer + 시각화 스펙) + scripts/check_docs_canon.py pages.yml blocking 배선, ML 오기술 4페이지 정정(autoresearch 제목 "자가 ML 실험 루프" 등) (PR #2107 → #2110, v0.99.168)
- [x] geode-mcp run_agent 라이브 핫픽스 — 원격 테스트가 노출한 잠복 결함 2건: adapter registry 미부트스트랩(.172) + 이벤트루프 충돌(async 코어 분리, .174, 동시 docs 세션이 .173 선점해 리넘버). HTTP run_agent E2E PASS('REMOTE-AGENT-OK', rounds=1, natural) (PR #2123/#2127, v0.99.172/174)
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
