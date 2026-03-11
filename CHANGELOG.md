# Changelog

All notable changes to the GEODE project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Scope Rules

**What to record**:
- New features (Added) — user-facing capabilities, new modules, new tools
- Breaking changes (Changed) — API changes, renamed modules, behavior shifts
- Bug fixes (Fixed) — corrected behavior, edge case handling
- Removals (Removed) — deleted modules, deprecated features
- Infrastructure (Infrastructure) — CI, build, dependency changes
- Architecture (Architecture) — structural decisions that affect future development

**What NOT to record**:
- Internal refactors that don't change behavior (unless architecturally significant)
- Code quality passes (R1→R8 rounds) — summarize as one entry
- Merge commits, branch operations
- Documentation-only changes (blogs, README updates)
- Commit-level granularity — aggregate by feature area

**Granularity**: Feature-level, not commit-level. One entry per logical change.

---

## [0.9.0] — 2026-03-11

General Assistant Transformation, Skills 시스템, MCP 자동설치, Clarification 파이프라인, 마스코트 브랜딩.

### Added

#### General Assistant Transformation (PR #32)
- Offline mode 제거 — AgenticLoop always-online (API 키 없으면 자동 dry-run)
- `key_registration_gate()` — Claude Code 스타일 API 키 등록 게이트
- 9개 신규 도구: `web_fetch`, `general_web_search`, `read_document`, `note_save`, `note_read`, `youtube_search`, `reddit_sentiment`, `steam_info`, `google_trends`
- `StdioMCPClient` — JSON-RPC stdio 기반 MCP 서버 클라이언트
- `MCPServerManager` — MCP 서버 설정 로딩 + 연결 관리 + 도구 디스커버리
- `/mcp` CLI 커맨드 — MCP 서버 상태/도구/재로딩
- `ToolExecutor` MCP fallback — 미등록 도구를 MCP 서버로 자동 라우팅

#### NL Router 개선 (PR #32)
- Scored matching — `_OfflinePattern` dataclass + priority-based 5-phase matching
- Fuzzy IP matching — `difflib.get_close_matches` ("Bersek" → "Berserk")
- Multi-intent — compound splitting ("하고", "and", 쉼표) → 복수 NLIntent 반환
- Disambiguation — `NLIntent.ambiguous` + `alternatives` 필드
- Context injection — 대화 히스토리 (최근 3턴) → LLM 라우터에 전달

#### Skills 시스템 (PR #33)
- `core/extensibility/skills.py` — SkillDefinition + SkillLoader + SkillRegistry
- `core/extensibility/_frontmatter.py` — 공유 YAML frontmatter 파서 (agents.py에서 추출)
- `.claude/skills/*/SKILL.md` 자동 발견 + 시스템 프롬프트 `{skill_context}` 주입
- `/skills` CLI 커맨드 — 목록/상세/reload/add 서브커맨드
- `/skills add <path>` — 외부 스킬 동적 등록 + .claude/skills/ 복사

#### MCP 강화 (PR #33)
- `MCPServerManager.add_server()` — 런타임 서버 등록 + JSON 영속화
- `MCPServerManager.check_health()` / `reload_config()` — 헬스체크 + 설정 재로딩
- `/mcp status|tools|reload|add` 서브커맨드 확장
- `/mcp add <name> <cmd> [args]` — 동적 MCP 서버 추가

#### MCP 자동설치 파이프라인 (PR #33)
- `core/infrastructure/adapters/mcp/catalog.py` — 31개 빌트인 MCP 서버 카탈로그
- `install_mcp_server` 도구 — NL로 MCP 서버 검색/설치 ("LinkedIn MCP 달아줘")
- `search_catalog()` — 키워드 기반 가중 매칭 (name > tags > description > package)
- `AgenticLoop.refresh_tools()` — MCP 도구 핫 리로드 (세션 재시작 불필요)
- `_build_tool_handlers()` 시그니처 확장 — `mcp_manager`, `agentic_ref` 클로저 패턴

#### Report Generation 강화 (PR #33)
- `_build_skill_narrative()` — geode-scoring/analysis/verification 스킬 주입 → LLM 전문 분석 내러티브 생성
- 리포트 자동 저장 — `.geode/reports/{ip}-{template}.{ext}` 경로로 파일 생성
- `generate_report` → `read_document` 체이닝 — 리포트 생성 후 즉시 열기 가능

#### Clarification 파이프라인 (PR #33)
- Tool parameter validation — `handle_compare_ips`, `handle_analyze_ip`, `handle_generate_report`에 필수 파라미터 검증
- `clarification_needed` 응답 프로토콜 — `missing`, `hint` 필드 포함
- AGENTIC_SUFFIX clarification rules — slot filling, disambiguation, missing parameter 처리 지침
- "Berserk 분석하고 비교하고 리포트" → max_rounds 미도달, 되묻기 정상 동작

#### 마스코트 브랜딩 (PR #33)
- `assets/geode-mascot.png` — GEODE 마스코트 (파란 구체 두구 우파루파)
- `assets/geode-avatar-{128,256,512}.png` — 원형 얼굴 아바타 (RGBA 투명)
- `assets/geode-social-preview.png` — GitHub Social Preview (1280×640)
- `_render_mascot()` — Harness GEODE ASCII art CLI splash (6-color Rich 마크업)

### Changed
- Tool count: 21 → 31 (definitions.json)
- Handler count: 17 → 30
- System prompt: IP 분석 전문 → General AI Assistant + IP 전문성
- `_build_tool_handlers()`: `verbose` only → `verbose`, `mcp_manager`, `agentic_ref`
- `AgenticLoop.__init__()`: `skill_registry`, `mcp_manager` 파라미터 추가
- `agents.py`: inline frontmatter parser → `_frontmatter.py` 공유 모듈 위임
- CLI 브랜딩: "Undervalued IP Discovery Agent" → "게임화 IP 도메인 자율 실행 하네스"
- 7개 Response dataclass에 `to_dict()` 추가 — None 필드 직렬화 시 자동 제외
  (AgenticResult, SubResult, IsolationResult, HookResult, TriggerResponse, ParseResult)
- `ReportGenerator.generate()`: `enhanced_narrative` 파라미터 추가 (스킬 기반 전문 분석 주입)
- `generate_report` 핸들러: `file_path` + `content_preview` 반환, `.geode/reports/` 자동 저장
- `definitions.json` `generate_report`: `format`/`template` enum 파라미터 추가, `read_document` 체이닝 안내
- `cmd_schedule()`: `scheduler_service` 파라미터 추가

### Fixed
- "Berserk 분석하고 비교하고 리포트" max_rounds 도달 → clarification 되묻기로 해결
- `{skill_context}` KeyError — `router.md`에서 `{{skill_context}}` 이스케이프
- `_render_mascot()` E501 — Rich 마크업 변수 리팩토링
- `report.html` 버전 0.7.0 → 0.9.0 정합성 수정
- mypy strict: `call_llm()` Any 반환 → `str()` 래핑, 3개 함수 시그니처 정합성 수정

### Infrastructure
- Test count: 2000+ → 2033+
- Module count: 118 → 121
- `docs/plans/clarification-pipeline.md` — Clarification 설계 문서
- `docs/plans/tool-mcp-catalog.md` — MCP 카탈로그 리서치
- pre-commit: mypy cache → `/tmp` 이동 (hook conflict 방지)

---

## [0.8.0] — 2026-03-11

Plan/Sub-agent NL integration, Claude Code-style UI, response quality hardening.

### Added

#### Plan & Sub-agent NL Integration
- `create_plan` tool — NL로 분석 계획 생성 ("Berserk 분석 계획 세워줘")
- `approve_plan` tool — 계획 승인 및 실행 ("계획 승인해")
- `delegate_task` tool — 서브에이전트 병렬 위임 ("병렬로 처리해")
- NL Router tool count: 17 → 20 (plan/delegate 3개 추가)
- Offline fallback: plan/delegate regex 패턴 추가 (LLM 없이 동작)

#### Claude Code-style UI
- `core/ui/agentic_ui.py` — tool call/result/error/token/plan 렌더러
- `core/ui/console.py` — Rich Console 싱글톤 (width=120, GEODE 테마)
- Marker system: `▸` tool call, `✓` success, `✗` error, `✢` tokens, `●` plan

#### LangSmith Trace Coverage
- `@_maybe_traceable` added to verification layer: `run_guardrails`, `run_biasbuster`, `run_cross_llm_check`, `check_rights_risk`
- Full pipeline tracing coverage: router → signals → analysts → evaluators → scoring → verification → synthesizer

### Changed
- `AgenticLoop._process_tool_calls()`: `str(result)` → `json.dumps(result, ensure_ascii=False, default=str)` — LLM이 파싱 가능한 JSON 형식으로 tool 결과 전달
- `snapshot._persist_snapshot()`: `json.dumps(..., default=str)` — non-serializable 필드 안전 처리
- `snapshot.capture()`: `_sanitize_state()` 추가 — `_`-prefixed 내부 필드 필터링
- NL Router offline fallback 순서: plan/delegate 패턴을 known IP 매칭보다 먼저 검사

### Fixed
- Offline mode `_run_offline()`: action name("list") → tool name("list_ips") 매핑 누락 수정 (`_ACTION_TO_TOOL` dict 추가)
- `_TOOL_ACTION_MAP` 누락: `create_plan`, `approve_plan`, `delegate_task` 미등록 → 추가

### Infrastructure
- Test count: 1909+ → 2000+
- Module count: 116 → 118
- `tests/test_agentic_ui.py` (20 tests), plan/delegate NL tests (20 tests)

---

## [0.7.0] — 2026-03-11

Pipeline flexibility improvements (C2-C5), LangSmith observability, orchestration integration.

### Added

#### Pipeline Flexibility (C2-C5)
- **C2**: Analyst types dynamically loaded from YAML (`ANALYST_SPECIFIC.keys()`) — add analyst = add YAML key
- **C3**: `interrupt_before` support via `GEODE_INTERRUPT_NODES` env — pipeline pauses at specified nodes for user review
- **C4**: Dynamic tool addition via `ToolRegistry` in `AgenticLoop` — plugins register tools at runtime
- **C5**: `offline_mode` for `AgenticLoop` — regex-based tool routing without LLM (1 deterministic round)

#### LangSmith Observability
- Token tracking: `track_token_usage()` records input/output tokens + cost per LLM call
- `_maybe_traceable` decorator on `AgenticLoop.run()` and `_call_llm()` for RunTree tracing
- Cost calculation with per-model pricing (Opus, Sonnet, Haiku, GPT)
- `UsageAccumulator` for session-level cost aggregation

#### Orchestration Integration
- `SubAgentManager` integration with `TaskGraph`, `HookSystem`, `CoalescingQueue`
- `AgenticLoop` rate limit retry with exponential backoff (3× at 10s/20s/40s)
- Tool handler enrichment: 17 handlers with structured return data

#### Testing & Verification
- `tests/test_e2e_live_llm.py` — 13 live E2E scenarios (AgenticLoop, LangSmith, Pipeline, Offline)
- `tests/_live_audit_runner.py` — 17-tool parallel audit framework
- 17/17 tool handlers verified via AgenticLoop + Opus 4.6 (live audit PASS)
- `docs/e2e-orchestration-scenarios.md` — E2E scenario documentation

#### Documentation
- `docs/as-is-to-be-flexibility.md` — C1-C5 AS-IS → TO-BE analysis
- `docs/plans/observability-langsmith-plan.md` — LangSmith integration plan
- `.claude/skills/geode-e2e/SKILL.md` — E2E testing skill guide

### Changed
- `ANALYST_TYPES`: hardcoded list → `list(ANALYST_SPECIFIC.keys())` (1-line change)
- `AGENTIC_TOOLS`: module-level constant → `get_agentic_tools(registry)` function
- `AgenticLoop.__init__()`: added `tool_registry`, `offline_mode` parameters
- `AgenticLoop._call_llm()`: added retry logic + token tracking
- `compile_graph()`: `interrupt_before` parameter wired from settings
- `ProfileStore` access: `.profiles` → `.list_all()` (mypy fix)

### Fixed
- `ProfileStore.profiles` → `ProfileStore.list_all()` attribute error
- Null-safe `model_dump()` in analyze handler (union-attr mypy error)
- Rate limit exhaustion: 3× retry with exponential backoff prevents transient failures

### Infrastructure
- Test count: 1879 → 1909+ (30 new tests)
- Module count: 115 → 116
- `langsmith` added as optional dependency

---

## [0.6.1] — 2026-03-10

Content/code separation + infrastructure hardening. No new user-facing features.

### Changed
- Package structure: `src/geode/` → `core/` (315 files removed, all imports updated)
- Prompt templates: Python strings → 8 `.md` template files with `load_prompt()` loader
- Tool definitions: inline dicts → `core/tools/definitions.json` (19 tools) + `tool_schemas.json` (11 schemas)
- Domain data: hardcoded axes/actions → `evaluator_axes.yaml`, `cause_actions.yaml`
- Report templates: inline strings → `core/extensibility/templates/` (HTML + 2 Markdown)
- Constants: hardcoded values → `pydantic-settings` (`router_model`, `agreement_threshold`, etc.)
- `VALID_AXES_MAP` / `EVALUATOR_TYPES` derived from canonical YAML (SSOT)

### Fixed
- CI: `--cov=geode` → `--cov=core`, 85 test files import path 수정
- Bandit B404/B602: `# nosec` for intentional subprocess in `bash_tool.py`
- 201 fixture JSON files: missing EOF newline

### Infrastructure
- Pre-commit hooks: ruff lint/format, mypy, bandit, standard hooks (local via `uv run`)
- `pre-commit` added as dev dependency
- Test count: 1823 → 1879

---

## [0.6.0] — 2026-03-10

Initial release of GEODE — Undervalued IP Discovery Agent.
56 commits across 5 development phases.

### Added

#### Core Pipeline (LangGraph StateGraph)
- 7-node pipeline: `router → signals → analyst×4 → evaluator×3 → scoring → verification → synthesizer`
- LangGraph `Send()` API for parallel analyst/evaluator fan-out
- `GeodeState` (TypedDict) with Pydantic validation models
- `GeodeRuntime` — production wiring with dependency injection
- Streaming mode (`_execute_pipeline_streaming`) — progressive panel rendering

#### Analysis Engine
- 4 Analysts: `game_mechanics`, `player_experience`, `growth_potential`, `discovery`
- Clean Context anchoring prevention (no cross-analyst contamination)
- 3 Evaluators: `quality_judge`, `hidden_value`, `community_momentum`
- 14-Axis Rubric Scoring (PSM Engine)
- 6-weighted composite score × confidence multiplier → Tier S/A/B/C classification

#### Verification Layer
- Guardrails G1–G4 (score bounds, consistency, genre-fit, data quality)
- BiasBuster — 6-bias detection (anchoring, genre, recency, popularity, cultural, survivorship)
- Cross-LLM validation (agreement threshold ≥ 0.67)
- Rights Risk assessment (GAP-5)
- Cause Classification Decision Tree

#### CLI (Typer + Rich)
- Interactive REPL with dual routing: `/command` (deterministic) + free-text (NL Router)
- 16+ slash commands: `/analyze`, `/compare`, `/search`, `/batch`, `/report`, `/model`, `/status`, etc.
- NL Router — Claude Opus 4.6 Tool Use (12 tools, autonomous routing)
- 3-stage graceful degradation: LLM Tool Use → offline pattern matching → help fallback
- IP search engine with keyword/genre matching
- Report generation (HTML, JSON, Markdown × Summary/Detailed/Executive templates)
- Batch analysis with parallel execution and ranking table

#### Agentic Loop (v0.6.0-latest)
- `AgenticLoop` — `while(tool_use)` multi-round execution (max 10 rounds)
- `ConversationContext` — sliding-window multi-turn history (max 20 turns)
- `ToolExecutor` — 17 tool handlers with HITL safety gate
- `BashTool` — shell execution with 9 blocked dangerous patterns + user approval
- `SubAgentManager` — parallel task delegation via `IsolatedRunner` (MAX_CONCURRENT=5)
- Multi-intent support: sequential tool chaining by LLM decision
- Multi-turn context: pronoun resolution, follow-up queries

#### Memory System (3-Tier)
- Organization Memory (fixtures, immutable)
- Project Memory (`.claude/MEMORY.md`, persistent insights + rules)
- Session Memory (in-memory TTL, conversation context)
- Auto-learning loop: `PIPELINE_END` → insight write-back to `MEMORY.md`
- Rule CRUD: create/update/delete/list analysis rules

#### Infrastructure (Hexagonal Architecture)
- `LLMClientPort` / `ClaudeAdapter` / `OpenAIAdapter` — multi-provider LLM
- `SignalEnrichmentPort` — market signal adapters
- Prompt caching (Anthropic cache_control)
- Ensemble mode: single / cross-LLM
- MCP Server (FastMCP: 6 tools, 2 resources)
- Auth profile management

#### Orchestration
- `HookSystem` — 23 lifecycle events (pipeline, node, analysis, verification, memory, prompt)
- `IsolatedRunner` — concurrent execution with timeout + semaphore (MAX_CONCURRENT=5)
- `TaskGraph` — DAG-based task dependency tracking
- `StuckDetector` — pipeline deadlock detection via hooks
- `LaneQueue` — concurrency control lanes
- `RunLog` — structured execution logging
- `PlanMode` — DRAFT → APPROVED → EXECUTING workflow

#### Tools & Policies
- `ToolRegistry` — 24 registered tools with lazy loading
- `PolicyChain` — composable tool access policies
- `NodeScopePolicy` — per-node tool allowlists
- Tool-augmented analyst paths with node-level retry

#### Automation (L4.5)
- Drift detection and monitoring
- Model registry with promotion lifecycle
- Confidence gating (feedback loop)
- Snapshot capture for reproducibility
- Trigger system (event-driven + cron-based)

### Fixed
- Scoring confidence calculation — empty/single/zero-mean edge cases (`7591445`)
- Evaluator fallback defaults `1.0 → 3.0` neutral + CLI type safety (`76e4e30`)
- Session ID wiring into pipeline initial state — GAP-001 (`e8fbcfe`)
- Billing error detection with user-friendly message (`d878078`)
- Memory 6 issues from 3-agent quality audit (`4430fd4`)
- API key availability → dry-run mode decision logic (`eeec586`, `8ea0555`)
- CI: bandit false positives, ruff format, mypy errors across 3 fix cycles

### Architecture
- Clean Architecture (Hexagonal) — ports/adapters separation
- 6-Layer hierarchy: Foundation → Memory → Agentic Core → Orchestration → Automation → Extensibility
- `src/` layout migration (`bf2bc24`)
- OpenClaw-inspired patterns: Gateway, Session Key, Binding Router, Lane Queue

### Infrastructure
- CI: 5-job pipeline (lint, typecheck, test matrix 3.12/3.13, security, gate)
- Strict `mypy` type checking (zero errors)
- `ruff` linting with S-series security rules
- `bandit` security scanning
- 1,879 tests across 115 modules
- 8 Claude skills + 4 analyst sub-skills
- LangSmith tracing (conditional, via `_maybe_traceable`)

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.9.0 | 2026-03-11 | General Assistant, Skills, MCP 자동설치, Clarification, 마스코트 |
| 0.8.0 | 2026-03-11 | Plan/Sub-agent NL, Claude Code UI, response quality, verification tracing |
| 0.7.0 | 2026-03-11 | C2-C5 flexibility, LangSmith observability, orchestration integration, 17-tool audit |
| 0.6.1 | 2026-03-10 | Content/code separation, package rename, pre-commit hooks |
| 0.6.0 | 2026-03-10 | Initial release — full pipeline, agentic loop, 3-tier memory |

<!-- Links -->
[Unreleased]: https://github.com/mangowhoiscloud/geode/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/mangowhoiscloud/geode/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/mangowhoiscloud/geode/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/mangowhoiscloud/geode/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/mangowhoiscloud/geode/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/mangowhoiscloud/geode/releases/tag/v0.6.0
