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

- [ ] 시스템 프롬프트 어셈블 + 리팩토링 — fable5 프롬프트(CL4R1T4S 공개 출처)를 1급 예시로 GEODE 프롬프트 표면(router/program/decomposer/commentary/도구 설명) slop·부실 지점 전수 감사 → 일괄 개선 계획부터. P0(dump)·P2-a(구조결함) 완료, 잔여 P2-b(router.md/AGENTIC_SUFFIX 루브릭 산문)·P2-c(60 도구 설명 trigger-pass)·P3(가드 확장+토큰 실측)
- [ ] v1.0.0 스탬프 — 사전 정리(.190)+tool-search(.191) 완료, 위 작업 후 릴리스
- [ ] H11-tail — routing 상수 모듈레벨 by-value 별칭 해동(core/llm/providers/{anthropic,openai,codex,glm}.py DEFAULT_*/FALLBACK_MODELS + core/skills/agents.py dataclass 기본값) — reload 후에도 boot-frozen, 호출자 스윕 필요. + H1(데몬 client-cwd 세션 해석)은 별도 결정

## In Review

<!-- PRs submitted, awaiting CI + review. -->

## Done

<!-- Completed items. Keep recent 10, archive older ones. -->
<!-- - [x] #issue-number — Short description (PR #N) -->
- [x] PR-SUBAGENT-MODEL-ALIGN — 웹서치/툴 모델이 /model과 동일한지 운영자 검증 요청. web_search=동일 확인(라이브: gpt-5.5/codex→codex-oauth+gpt-5.5). 단 delegate_task가 ToolContext를 dispatch에서 떨어뜨려 sub-agent가 전역 settings.model(라이브 스위치 lag) 사용하던 비대칭 발견·수정 — context→default_model threading(precedence: task>agent>live default>settings 보존). stale docstring(codex web_search 미지원 주장) 정정. Codex(gpt-5.5) clean. 가드 4종(precedence+dispatch-wiring) (PR #2255, v0.99.201)
- [x] PR-LOWRISK-SLOP — 코드베이스 전수 slop/frontier-비정렬 스캔 후 저위험 3건 정돈. A: cache_policy·provider_routing(v0.99.196 load_policy_sot 7→1 dedup이 놓친 2개)을 공유 로더로 이행(behavior-preserving, -60줄). C: definitions.json(선언) + Tool 프로토콜(행위) 2-layer 의도 문서화. D: naive 변수명 2건(result_payload/info_fields). **god-module 분할은 frontier 측정으로 기각** — hermes 핵심파일 13k~16k줄·codex 2.2k~3.8k·openclaw 3k~4k인데 GEODE 최대 2.5k줄(at/below norm), 분할 시 over-decompose 아웃라이어. dead 0·dual-registry 0·emoji 0 확인. Codex(gpt-5.5) clean. 자기 hygiene 가드가 칸반 리터럴 경로 누수 적발(머지-게이트 교훈) (PR #2250, v0.99.200)
- [x] PR-PATH-MODERNIZE (Phases 1-4) — path 정책 frontier 수렴 + 부채/slop 전수. GEODE_HOME env override 신설(프론티어 {APP}_HOME parity: CODEX_HOME 등 5/5, 기존 GEODE_STATE_ROOT 패턴) + expanduser, ipc_client GEODE_HOME(serve-cwd 오명명)→GEODE_PROJECT_DIR. GLOBAL_*_POLICY_PATH 16종→AUTORESEARCH_*(in-repo STATE tier 정명명, 227건/34파일). dead PROJECT_SCHEDULER_LOCK 삭제·GLOBAL_SEARCH_DIR 인라인·retrofit dedup. path-literal 가드 plugins/ 확장 + expanduser 패턴 + 3-tier docstring + vendor 카탈로그. 엄밀 누락점검으로 GEODE_AUTH_TOML/PROJECT_DIR expanduser 보너스 수정. ~/.hermes 할루시네이션(미사용 frontier 레퍼런스) 운영자 지적→제거. XDG 스킵(0/5), Phase 5(god-module 분할) deferred. Codex(gpt-5.5) MAJOR 1(fixture 오염) 수정 후 clean. 라이브 스모크: GEODE_HOME override end-to-end (PR #2246, v0.99.199)
- [x] PR-PATH-SCRUB — 하드코딩 home 경로 PII redaction(916파일/1914건 `/Users/<name>`→`~`) + repo-hygiene ratchet(find_home_path_leaks, ci.yml 배선). 대부분 docs/self-improving published 런 아티팩트(hub sync verbatim). resume 경로도 스크럽. Codex(gpt-5.5) MAJOR(bare/대문자) 수정. 가드 3종 (PR #2243, v0.99.198)
- [x] PR-OBS-CONTRACT — Activity-row 스키마 100% typed 커버리지(62/62, union 19→62) + 중앙화. 43 K-group을 선언적 _TYPED_ROW_SPECS 테이블 + 단일 _build_from_spec 빌더로(빌더 43개 아님), 23 공유 details 모델(패밀리당 1개). mirror parity — 4 trigger 변형 전부 mirror(feedback/interceptor 이벤트 timeline 진입, half-connected 계약 해소). silent fallback 제거 — _fallback_reason로 강제-generic 구분 + mirror/dispatch/학습저장 실패 once-per-event WARNING + schema_version. 프라이버시 — raw user_input/cognitive_state/tool result 미적재(input_len만), Codex BLOCKER 2건(fail-soft 경계 스크럽 + value-free reason) 반영. 공식문서(hook-system.md/.en + site hooks 페이지) 로깅·에러·스키마 정책 기록. Codex(gpt-5.5 high) 최종 clean. 가드 6종 (PR #2238, v0.99.197)
- [x] 루프 prune + 정책 로더 dedup — HookEvent 64→62(HANDOFF_COMPLETED/FAILED reserve-without-emit 쌍 삭제) + handoff watcher API 전체 삭제(zero-caller) + 정책 SoT 로더 7→1(load_policy_sot, net -424). 이벤트 카운트 6표면 동기화 (PR #2237, v0.99.196)
- [x] 프롬프트 P2-a — 어셈블 코드 결함 2건: dynamic_context 미폐합 태그(18/18셀) 폐합(B1), 학습패턴 새니타이저 우회 채널 삭제(B2, Conditional Read Parity). 2-존 표기 규칙(저작=md/주입=XML), AGENTIC_SUFFIX 정적 존 이동(캐시 프리픽스 안정). 실측 −770tok/call(−15.5%) (PR #2236, v0.99.195)
- [x] 프롬프트 P0 — geode prompt dump(모델3×표면6 매트릭스, count_tokens 실측, 중복태그 신호) + 가드 5종 + 4단계 계획 문서. 실측: 18셀 4,942~5,087tok, 중복 0. P1 감사에서 코드버그 2(B1 미폐합 태그·B2 새니타이저 우회)+루브릭 위반 카탈로그 도출 (PR #2234, v0.99.194)
- [x] openai Responses 이행 + OpenAI tool_search defer — payg acomplete/astream을 공유 build_responses_kwargs(backend 델타 1개)로 Responses 합류(.192, Codex 리뷰 2건: usage 캐시 토큰·stop_sequences 관측 드롭). OpenAI 공식 tool_search를 양 백엔드 배선(.193) — 정책 SoT tool_defer.py 단일화, 모델 게이트(5.4+), Codex 백엔드 라이브 게이트 통과(DEFER-OK, gpt-5.5, defer 20) 후 기본 ON, "web" 500 블록리스트. 가드 6+6종 (PR #2229/#2230, v0.99.192/193)
- [x] v1.0 사전 정리 + tool-search defer 실배선 — 3-차원 감사(slop·누수·배선, Explore 3기+오탐 3건 증거 반박) 확정분 정리(.190: Cortex 스텁·dead knob/method·MCP 핸드셰이크 "0.9.0"·emoji·tool_ranking rename) 후, 감사 핵심 결함(docstring만 defer 주장, 매 요청 60 스키마 전송)을 공식 Messages API로 해소(.191: defer_loading 필드+호스티드 tool_search_tool_regex, 코어 11종 즉시·49종 defer, 캐시 프리픽스 보존, kill switch=llm.tool_search_defer). 자작 ToolSearchTool 경로 전체 삭제. Codex 검증 BLOCKER 1건(레거시 경로 배선→라이브 빌더 2종 이행) 포함 7건 반영. 라이브 검증: opus-4-8이 defer 20/21 요청 수락(DEFER-OK·end_turn). 가드 11종 (PR #2223/#2224 → #2225, v0.99.190/191)
- [x] llms.txt 발행 측 완성 — docs 66페이지 .md 트윈 export(post-build extractDocsProse 균형 추출+turndown+GFM+bare-pre 펜스, 렌더 URL+.md=트윈, 트윈-투-트윈 링크), llms.txt 링크 전부 .md 전환, llms-full.txt 진짜 전문 덤프(100KB 초과 본문은 명시적 생략 노트 — changelog 1.2MB, 노트=균형추출 간접 가드), sitemap 파서 단일화(sitemap-pages.mjs), pages.yml export-md 배선. Codex 검증 3건 반영(중첩 article 330개로 1-항목 트윈 출하되던 MAJOR 포함). 라이브 검증: quick-start.md 200 text/markdown, llms-full 66엔트리. 가드 5종 (PR #2218 → #2219, v0.99.189)
- [x] llms_txt_index 전용 도구 — instruction-level llms.txt-first 휴리스틱(v0.99.156)을 mcpdoc 수렴 패턴의 전용 도구로 승격: 경로우선 2-probe + llmstxt.org 파서(구조화 sections/links, same_origin=scheme+host, BOM 허용, 희소 인덱스 정직 처리) + section 필터/max_links 관측가능 truncation + not_found 폴백 힌트. TLS 폴백 http_get_with_tls_fallback 공유화. 배선 definitions+delegated+SAFE_TOOLS+toolkits 2종, router.md 도구-first + AGENTIC_SUFFIX re-pin. Codex 검증 4건 반영·1건 반박. 라이브 스모크: platform.claude.com 1,642링크 구조화 PASS. 가드 21+4종 (PR #2213 → #2214, v0.99.188)
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
