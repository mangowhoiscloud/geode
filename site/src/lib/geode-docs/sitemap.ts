/**
 * GEODE Docs sitemap. Single source of truth for navigation and route
 * generation.
 *
 * Each leaf entry maps to a static page at /docs/<slug> (basePath = /geode,
 * so the final URL is `mangowhoiscloud.github.io/geode/docs/<slug>`).
 *
 * Sections are rendered in the sidebar in the order declared.
 *
 * Quadrant follows Diátaxis (https://diataxis.fr). Every page must declare
 * one of `tutorial`, `how-to`, `reference`, `explanation`. The sidebar
 * shows a small color chip per page.
 *
 * Bilingual: every entry carries an English and Korean title + summary.
 *
 * PR-DOCS-REDESIGN (2026-05-29) — restructured from ten layer-named sections
 * into nine reader-facing sections, concepts-first with a task router on top.
 * The self-improving loop is its own top-level section (GEODE's signature,
 * carries the petri-blue accent). Vanity counts (tool / hook / module / seed
 * numbers) are removed from every title and summary; the system is described
 * by what it does, not by how much of it there is.
 *
 * PR-DOCS-REFERENCE-LINEAGE (2026-05-30) — the Reference section used to open
 * with the verification/* cluster (guardrails, biasbuster, cross-llm, cause
 * tree, observability), which read as an awkward "reference" entry point. The
 * section now leads with GEODE's positioning references — frontier comparison
 * (what GEODE borrows vs. how it differs) and external references — so the
 * reference entry point foregrounds the self-improving-loop lineage rather than
 * validation. The verification/* cluster moved into its own section,
 * "Verification and Guardrails" (id 08b), so it is no longer the face of
 * Reference. Lineage and Co-scientist stay in The Self-Improving Loop section
 * (their home); the docs landing reference grouping cross-links to them.
 */

export type DocQuadrant = "tutorial" | "how-to" | "reference" | "explanation";

export type DocPage = {
  slug: string;
  title: string;
  titleKo: string;
  summary?: string;
  summaryKo?: string;
  quadrant: DocQuadrant;
  /** Optional outbound link. If set, sidebar shows it and the page may simply redirect. */
  externalUrl?: string;
};

export type DocSection = {
  id: string;
  title: string;
  titleKo: string;
  pages: DocPage[];
};

export const DOCS_SITEMAP: DocSection[] = [
  {
    id: "01-overview",
    title: "Overview",
    titleKo: "개요",
    pages: [
      { slug: "", title: "What GEODE is", titleKo: "GEODE 소개", summary: "An autonomous execution agent that runs an inner agentic loop and improves itself through an outer loop. What it does, who it is for, where to go next.", summaryKo: "안쪽의 agentic 루프로 일을 처리하고, 바깥쪽 루프로 스스로를 개선하는 자율 실행 에이전트입니다. 무엇을 하는지, 누구를 위한 것인지, 다음에 어디로 갈지 안내합니다.", quadrant: "explanation" },
      { slug: "overview/how-it-runs", title: "How GEODE runs a task", titleKo: "GEODE가 작업을 처리하는 흐름", summary: "One request, traced end to end. The same core serves a CLI task, a gateway message, and a scheduled self-improving run.", summaryKo: "요청 하나가 처음부터 끝까지 어떻게 흐르는지 따라갑니다. CLI 작업, 게이트웨이 메시지, 예약된 자기개선 실행이 모두 같은 코어를 지납니다.", quadrant: "explanation" },
      { slug: "architecture/overview", title: "The 5-layer stack", titleKo: "5-계층 스택", summary: "Model, Runtime, Harness, Agent, Self-Improving. What each layer owns, and where its responsibility ends.", summaryKo: "Model, Runtime, Harness, Agent, Self-Improving. 각 계층이 무엇을 맡고, 책임이 어디서 끝나는지 설명합니다.", quadrant: "reference" },
    ],
  },
  {
    id: "02-start",
    title: "Getting Started",
    titleKo: "시작하기",
    pages: [
      { slug: "quick-start", title: "Quick Start", titleKo: "빠른 시작", summary: "Install GEODE and run your first task in a few minutes.", summaryKo: "GEODE를 설치하고 몇 분 안에 첫 작업을 실행합니다.", quadrant: "tutorial" },
      { slug: "run/pick-path", title: "Pick a path", titleKo: "경로 선택", summary: "Subscription, API key, or free path. How to choose for your situation.", summaryKo: "구독, API 키, 무료 경로 중에서 상황에 맞는 것을 고르는 방법입니다.", quadrant: "how-to" },
      { slug: "run/providers", title: "Configure providers", titleKo: "프로바이더 설정", summary: "Anthropic, OpenAI, Codex, GLM. Where keys go, and what fallback chain you get.", summaryKo: "Anthropic, OpenAI, Codex, GLM. 키를 어디에 두는지, 어떤 폴백 체인이 동작하는지 다룹니다.", quadrant: "how-to" },
      { slug: "run/serve", title: "Run as a daemon", titleKo: "데몬으로 실행", summary: "Start, restart, and stop serve. A thin CLI talks to an IPC-served runtime.", summaryKo: "serve를 시작하고 재시작하고 종료합니다. thin CLI가 IPC로 동작하는 런타임과 통신합니다.", quadrant: "how-to" },
    ],
  },
  {
    id: "03-concepts",
    title: "Core Concepts",
    titleKo: "핵심 개념",
    pages: [
      { slug: "concepts/two-loops", title: "The two loops", titleKo: "두 개의 루프", summary: "The mental model the rest of the docs build on. An inner agentic loop runs a task; an outer loop tunes the system that runs tasks.", summaryKo: "나머지 문서가 기대는 멘탈 모델입니다. 안쪽 agentic 루프가 작업을 처리하고, 바깥쪽 루프가 작업을 처리하는 시스템 자체를 다듬습니다.", quadrant: "explanation" },
      { slug: "architecture/agentic-loop", title: "The inner agentic loop", titleKo: "안쪽 agentic 루프", summary: "The while(tool_use) primitive. How a turn runs, and the paths that end it.", summaryKo: "while(tool_use) 기본 단위입니다. 한 턴이 어떻게 돌고, 어떤 경로로 끝나는지 설명합니다.", quadrant: "reference" },
      { slug: "runtime/context", title: "Context assembly", titleKo: "컨텍스트 조립", summary: "Every LLM call's context is built here. Memory tiers plus prompt layers, under a token budget.", summaryKo: "모든 LLM 호출의 컨텍스트가 여기서 만들어집니다. 메모리 계층과 프롬프트 레이어를 토큰 예산 안에서 합칩니다.", quadrant: "reference" },
      { slug: "runtime/memory/5-tier", title: "Memory tiers", titleKo: "메모리 계층", summary: "From a raw session log to a single LLM-ready summary. Hierarchical override, budget-aware compression.", summaryKo: "raw 세션 로그에서 LLM에 바로 넣을 수 있는 요약까지. 계층 override와 예산 인식 압축을 다룹니다.", quadrant: "reference" },
      { slug: "runtime/llm/prompt-system", title: "Prompt assembly", titleKo: "프롬프트 조립", summary: "How the system prompt is layered and assembled before each call.", summaryKo: "매 호출 전에 시스템 프롬프트가 어떻게 층층이 조립되는지 설명합니다.", quadrant: "reference" },
      { slug: "runtime/tools/protocol", title: "Tools and toolsets", titleKo: "도구와 툴셋", summary: "The tool registry and deferred loading. A few tools load up front, the rest are fetched on demand.", summaryKo: "도구 레지스트리와 지연 로딩입니다. 일부 도구는 미리 로드하고, 나머지는 필요할 때 가져옵니다.", quadrant: "reference" },
      { slug: "harness/hooks", title: "Hooks and observability", titleKo: "훅과 관측성", summary: "Lifecycle events that handlers subscribe to. How observe, react, decide, and act stack on one event.", summaryKo: "핸들러가 구독하는 라이프사이클 이벤트입니다. 하나의 이벤트 위에 observe, react, decide, act가 어떻게 쌓이는지 설명합니다.", quadrant: "reference" },
      { slug: "runtime/llm/providers", title: "LLM routing", titleKo: "LLM 라우팅", summary: "Provider selection and model resolution. Fallback chains ship empty by default; fatal errors fast-fail instead of retrying.", summaryKo: "프로바이더 선택과 모델 해석입니다. 폴백 체인은 기본 비활성으로 출하되고, 치명 오류는 재시도 없이 빠르게 실패합니다.", quadrant: "reference" },
      { slug: "runtime/orchestration", title: "Sub-agent orchestration", titleKo: "서브에이전트 오케스트레이션", summary: "Spawning isolated sub-agents in parallel lanes, with snapshotted memory and merge on completion.", summaryKo: "격리된 서브에이전트를 병렬 레인에서 띄웁니다. 메모리를 스냅샷으로 넘기고 완료 시 병합합니다.", quadrant: "reference" },
      { slug: "runtime/skills", title: "Skills", titleKo: "스킬", summary: "User-invocable skills, distinct from tools. Discovery, lifecycle, override.", summaryKo: "도구와 구분되는, 사용자가 호출하는 스킬입니다. 발견, 라이프사이클, override를 다룹니다.", quadrant: "reference" },
    ],
  },
  {
    id: "04-self-improving",
    title: "The Self-Improving Loop",
    titleKo: "자기개선 루프",
    pages: [
      { slug: "capabilities/autoresearch", title: "The closed loop", titleKo: "폐루프", summary: "The outer loop end to end. Mutate the scaffold, audit with Petri, gate the fitness gain on a margin, then promote or revert. No model weight or parameter ever changes.", summaryKo: "바깥쪽 루프의 전체 흐름입니다. 스캐폴드를 변이하고, Petri로 감사하고, fitness 이득을 margin 게이트로 검증해 승격하거나 되돌립니다. 모델 가중치와 파라미터는 일절 바꾸지 않습니다.", quadrant: "explanation" },
      { slug: "capabilities/co-scientist", title: "Co-scientist seed generation", titleKo: "Co-scientist seed 생성", summary: "A nine-role agent loop that grows the evaluation seed corpus. Supervisor, literature review, generator, proximity, critic, pilot, ranker, evolver, meta-reviewer.", summaryKo: "평가용 seed 코퍼스를 키우는 9-역할 에이전트 루프입니다. supervisor, literature review, generator, proximity, critic, pilot, ranker, evolver, meta-reviewer로 이어집니다.", quadrant: "explanation" },
      { slug: "capabilities/seed-pipeline", title: "Seed pipeline", titleKo: "Seed 파이프라인", summary: "The plugin that regenerates the seed corpus each generation. Picker, orchestrator, manifest, cost preview, and the blend survivor selection.", summaryKo: "세대마다 seed 코퍼스를 다시 만드는 플러그인입니다. picker, orchestrator, manifest, cost preview와 blend 생존자 선택을 다룹니다.", quadrant: "reference" },
      { slug: "capabilities/outer-loop", title: "Outer-loop configuration", titleKo: "아우터 루프 설정", summary: "The shared schema and loader for autoresearch, seed generation, Petri roles, and the auto-trigger scheduler. Strict by default.", summaryKo: "autoresearch, seed 생성, Petri 역할, auto-trigger 스케줄러가 공유하는 스키마와 로더입니다. 기본은 strict 검증입니다.", quadrant: "reference" },
      { slug: "petri/overview", title: "Petri × GEODE", titleKo: "Petri × GEODE", summary: "Anthropic Alignment Science's evaluation framework, wrapped over the GEODE agent as the loop's measurement layer.", summaryKo: "Anthropic Alignment Science의 평가 프레임워크를 GEODE 에이전트 위에 얹어 루프의 측정 계층으로 씁니다.", quadrant: "explanation" },
      { slug: "petri/scenarios", title: "Scenarios", titleKo: "시나리오", summary: "The Petri seed corpus plus GEODE-specific seeds, grouped into critical, auxiliary, and info dimension buckets.", summaryKo: "Petri seed 코퍼스에 GEODE 전용 seed를 더해 critical, auxiliary, info 차원 버킷으로 묶습니다.", quadrant: "reference" },
      { slug: "petri/run", title: "Run an audit", titleKo: "감사 실행", summary: "geode audit, or inspect eval for the raw path. Choose model roles, dimension set, seeds, and turn budget. Dry-run by default.", summaryKo: "geode audit, 또는 raw 경로인 inspect eval을 씁니다. 모델 역할, 차원 세트, seeds, 턴 예산을 고릅니다. 기본은 dry-run입니다.", quadrant: "how-to" },
      { slug: "petri/judge-dimensions", title: "Judge dimensions", titleKo: "Judge 차원", summary: "The 22-dim rubric and the 18-dim fitness universe. Critical floors versus auxiliary drift, on a 1-10 lower-is-better scale.", summaryKo: "22-dim 루브릭과 18-dim fitness universe를 설명합니다. critical 바닥값과 auxiliary drift를 1-10 lower-is-better 스케일에서 구분합니다.", quadrant: "reference" },
      { slug: "petri/seeds", title: "Seed-generation runs", titleKo: "Seed 생성 런", summary: "The per-generation dashboard. Survivors, tokens, meta-review, and next-generation priors per run.", summaryKo: "세대별 대시보드입니다. 런마다 생존 후보, 토큰, 메타리뷰, 다음 세대 prior를 보여줍니다.", quadrant: "reference" },
      { slug: "capabilities/lineage", title: "Lineage and positioning", titleKo: "계보와 좌표", summary: "Where this loop sits in the self-evolving agents literature. An honest recombination of known parts, not a new primitive.", summaryKo: "이 루프가 self-evolving agents 문헌에서 어디에 위치하는지 짚습니다. 새로운 primitive가 아니라, 알려진 조각들을 정직하게 재조합한 결과입니다.", quadrant: "explanation" },
      { slug: "petri/bundle", title: "Bundle viewer", titleKo: "번들 뷰어", summary: "The live inspect_ai transcript viewer for the latest audit run.", summaryKo: "가장 최근 감사 런의 라이브 inspect_ai 트랜스크립트 뷰어입니다.", quadrant: "reference", externalUrl: "/self-improving/petri-bundle/" },
    ],
  },
  {
    id: "05-operate",
    title: "Operating GEODE",
    titleKo: "GEODE 운영",
    pages: [
      { slug: "harness/serve-gateway", title: "Serve and gateway", titleKo: "Serve와 게이트웨이", summary: "Operating the serve daemon's messaging gateway. Pollers, binding routing, lane queue.", summaryKo: "serve 데몬의 메신저 게이트웨이를 운영합니다. poller, binding 라우팅, lane queue를 다룹니다.", quadrant: "how-to" },
      { slug: "run/messaging", title: "Messaging integrations", titleKo: "메신저 연동", summary: "Connect GEODE to Slack, Discord, or Telegram through gateway adapters.", summaryKo: "게이트웨이 어댑터로 GEODE를 Slack, Discord, Telegram에 연결합니다.", quadrant: "how-to" },
      { slug: "run/schedule", title: "Schedule tasks", titleKo: "작업 예약", summary: "Natural language and cron, with jitter. A daily report as a single command.", summaryKo: "자연어와 cron을 jitter와 함께 씁니다. 일일 리포트를 명령 한 줄로 예약합니다.", quadrant: "how-to" },
      { slug: "runtime/scheduler", title: "Scheduler internals", titleKo: "스케줄러 내부", summary: "How scheduled jobs are parsed, persisted, and fired.", summaryKo: "예약된 작업이 어떻게 파싱되고 저장되고 실행되는지 설명합니다.", quadrant: "reference" },
      { slug: "harness/lifecycle", title: "Lifecycle", titleKo: "라이프사이클", summary: "Bootstrap, serve, shutdown. The injection order, and the cold-start lazy arc.", summaryKo: "Bootstrap, serve, shutdown. 주입 순서와 cold-start lazy arc를 다룹니다.", quadrant: "reference" },
      { slug: "ops/long-running", title: "Long-running safety", titleKo: "장기 실행 안전", summary: "Token guards, context overflow, and a sliding window. How a long run drains gracefully.", summaryKo: "토큰 가드, 컨텍스트 오버플로, 슬라이딩 윈도입니다. 긴 실행이 어떻게 안전하게 마무리되는지 다룹니다.", quadrant: "how-to" },
      { slug: "ops/cost", title: "Cost monitoring", titleKo: "비용 모니터링", summary: "Per-session and per-day budgets. The usage ledger, and when to switch models.", summaryKo: "세션별, 일별 예산입니다. 사용량 ledger와 모델을 바꿀 시점을 다룹니다.", quadrant: "how-to" },
      { slug: "run/troubleshooting", title: "Troubleshooting", titleKo: "문제 해결", summary: "Common failure modes and where to look. Logs, hooks, runlog.", summaryKo: "흔한 실패 모드와 살펴볼 곳입니다. 로그, 훅, runlog를 봅니다.", quadrant: "how-to" },
    ],
  },
  {
    id: "06-guides",
    title: "Guides and How-to",
    titleKo: "가이드",
    pages: [
      { slug: "guides/custom-tool", title: "Write a tool", titleKo: "도구 작성", summary: "Define a tool, register it, and gate it with a permission policy.", summaryKo: "도구를 정의하고 등록한 뒤 권한 정책으로 게이트를 거는 방법입니다.", quadrant: "how-to" },
      { slug: "guides/register-hook", title: "Register a hook", titleKo: "훅 등록", summary: "Subscribe a handler to a lifecycle event and wire it in bootstrap.", summaryKo: "라이프사이클 이벤트에 핸들러를 구독하고 bootstrap에 연결하는 방법입니다.", quadrant: "how-to" },
      { slug: "guides/llm-adapter", title: "Add an LLM adapter", titleKo: "LLM 어댑터 추가", summary: "Add a provider to the router and adapter layer, with a fallback entry.", summaryKo: "라우터와 어댑터 레이어에 프로바이더를 추가하고 폴백 항목을 거는 방법입니다.", quadrant: "how-to" },
      { slug: "guides/binding", title: "Configure a binding", titleKo: "바인딩 설정", summary: "Route a messaging channel to a session lane with its own model and policy.", summaryKo: "메신저 채널을 자체 모델과 정책을 가진 세션 레인으로 라우팅하는 방법입니다.", quadrant: "how-to" },
      { slug: "guides/debug-stuck-run", title: "Debug a stuck run", titleKo: "멈춘 실행 디버깅", summary: "Read the transcript and runlog, find where a run stalled, and recover.", summaryKo: "트랜스크립트와 runlog를 읽어 실행이 멈춘 지점을 찾고 복구하는 방법입니다.", quadrant: "how-to" },
    ],
  },
  {
    id: "07-config",
    title: "Configuration",
    titleKo: "설정",
    pages: [
      { slug: "config/basics", title: "Configuration basics", titleKo: "설정 기초", summary: "Where configuration lives, how it loads, and how overrides resolve.", summaryKo: "설정이 어디에 있고, 어떻게 로드되고, override가 어떻게 결정되는지 설명합니다.", quadrant: "how-to" },
      { slug: "config/reference", title: "config.toml reference", titleKo: "config.toml 레퍼런스", summary: "Every configuration key, grouped by area, marked stable or experimental.", summaryKo: "영역별로 묶은 모든 설정 키입니다. stable과 experimental을 표시합니다.", quadrant: "reference" },
      { slug: "runtime/auth", title: "Auth and OAuth", titleKo: "인증과 OAuth", summary: "Profile rotation, the Anthropic ToS path, and the Codex flow.", summaryKo: "프로파일 로테이션, Anthropic ToS 경로, Codex 플로우를 다룹니다.", quadrant: "reference" },
      { slug: "ops/oauth", title: "OAuth token rotation", titleKo: "OAuth 토큰 회전", summary: "Refresh policy and cooldown across providers.", summaryKo: "프로바이더 전반의 갱신 정책과 쿨다운을 다룹니다.", quadrant: "how-to" },
      { slug: "runtime/llm/system-prompt-modes", title: "System prompt modes", titleKo: "시스템 프롬프트 모드", summary: "The persona opt-in and the audit-mode strip. The two ways the system prompt is reshaped.", summaryKo: "persona opt-in과 audit-mode strip입니다. 시스템 프롬프트가 변형되는 두 가지 방식입니다.", quadrant: "reference" },
      { slug: "runtime/llm/prompt-caching", title: "Prompt caching", titleKo: "프롬프트 캐싱", summary: "The static and dynamic boundary, and ephemeral cache control.", summaryKo: "static과 dynamic 경계, ephemeral 캐시 제어를 다룹니다.", quadrant: "reference" },
      { slug: "runtime/llm/prompt-hashing", title: "Prompt hashing", titleKo: "프롬프트 해싱", summary: "Pinned prompt hashes that break the build on unintended drift.", summaryKo: "의도하지 않은 drift가 생기면 빌드를 깨뜨리는 프롬프트 해시 핀입니다.", quadrant: "reference" },
      { slug: "runtime/tools/mcp", title: "MCP servers", titleKo: "MCP 서버", summary: "Connecting MCP servers, the result-size guard, and the HTML to Markdown fallback.", summaryKo: "MCP 서버 연결, 결과 크기 가드, HTML to Markdown 폴백을 다룹니다.", quadrant: "reference" },
    ],
  },
  {
    id: "08-reference",
    title: "Reference",
    titleKo: "레퍼런스",
    pages: [
      { slug: "reference/frontier-comparison", title: "Frontier comparison", titleKo: "프론티어 비교", summary: "What GEODE borrows from Claude Code, Codex CLI, OpenClaw, and Hermes, and where it differs. The reference entry point for GEODE's position in the lineage.", summaryKo: "GEODE가 Claude Code, Codex CLI, OpenClaw, Hermes에서 무엇을 빌려오고, 어디서 갈라지는지 정리합니다. 계보 속 GEODE의 좌표를 짚는 레퍼런스 진입점입니다.", quadrant: "reference" },
      { slug: "reference/external-references", title: "External references", titleKo: "외부 참고", summary: "Frontier agent systems, design standards, and prior work GEODE cites — the self-evolving-agents lineage behind the loop.", summaryKo: "GEODE가 인용하는 frontier 에이전트 시스템, 디자인 표준, 선행 작업입니다. 루프 뒤에 있는 self-evolving agents 계보입니다.", quadrant: "reference" },
      { slug: "harness/cli", title: "CLI and slash commands", titleKo: "CLI와 슬래시 명령", summary: "The thin gateway and IPC, and the slash commands it accepts.", summaryKo: "thin 게이트웨이와 IPC, 그리고 받는 슬래시 명령들입니다.", quadrant: "reference" },
      { slug: "runtime/research", title: "Research, search, and llms.txt", titleKo: "리서치·탐색과 llms.txt", summary: "How GEODE explores: llms.txt-first documentation research, web search delegation, local FTS search, and the llms.txt this site publishes.", summaryKo: "GEODE의 탐색 방법입니다. llms.txt 우선 문서 리서치, 웹 검색 위임, 로컬 FTS 검색, 그리고 이 사이트가 발행하는 llms.txt를 다룹니다.", quadrant: "reference" },
      { slug: "runtime/automation", title: "Automation sidecar", titleKo: "자동화 사이드카", summary: "The feedback loop and model promotion, with drift detection between agent and runtime.", summaryKo: "피드백 루프와 모델 프로모션입니다. 에이전트와 런타임 사이에서 drift를 감지합니다.", quadrant: "reference" },
      { slug: "runtime/computer-use", title: "Computer use", titleKo: "컴퓨터 사용", summary: "Provider-agnostic desktop automation, Anthropic and OpenAI unified.", summaryKo: "프로바이더 독립 데스크탑 자동화입니다. Anthropic과 OpenAI를 통합합니다.", quadrant: "reference" },
      { slug: "runtime/ui/cli-latex", title: "CLI LaTeX rendering", titleKo: "CLI LaTeX 렌더링", summary: "Rendering math in the terminal. Detection, Unicode flatten, pretty print, image fallback.", summaryKo: "터미널에서 수식을 렌더링합니다. 감지, Unicode flatten, pretty print, 이미지 폴백을 거칩니다.", quadrant: "reference" },
      { slug: "reference/changelog", title: "CHANGELOG", titleKo: "CHANGELOG", summary: "Full version history, synced from CHANGELOG.md on every main push.", summaryKo: "main push마다 CHANGELOG.md에서 동기화되는 전체 버전 이력입니다.", quadrant: "reference" },
      { slug: "reference/petri-bundle-isolation", title: "Petri bundle isolation", titleKo: "Petri 번들 격리", summary: "Operator reference for the publish workflow, validator, and hygiene ratchet.", summaryKo: "publish 워크플로우, validator, hygiene ratchet의 운영자 레퍼런스입니다.", quadrant: "reference" },
    ],
  },
  {
    id: "08b-verification",
    title: "Verification and Guardrails",
    titleKo: "검증과 가드레일",
    pages: [
      { slug: "verification/guardrails", title: "Guardrails G1-G4", titleKo: "가드레일 G1-G4", summary: "Schema, range, grounding, consistency. A fail-fast ladder over LLM output.", summaryKo: "Schema, range, grounding, consistency입니다. LLM 출력 위의 fail-fast 사다리입니다.", quadrant: "reference" },
      { slug: "verification/biasbuster", title: "BiasBuster", titleKo: "BiasBuster", summary: "Confirmation, recency, and anchoring detection on top of the guardrails.", summaryKo: "가드레일 위에 얹는 confirmation, recency, anchoring 편향 탐지입니다.", quadrant: "reference" },
      { slug: "verification/cross-llm", title: "Cross-LLM verification", titleKo: "Cross-LLM 검증", summary: "An independent second opinion. A different provider re-scores the verdict.", summaryKo: "독립적인 second opinion입니다. 다른 프로바이더가 판정을 다시 채점합니다.", quadrant: "reference" },
      { slug: "verification/cause-decision-tree", title: "Cause decision tree", titleKo: "원인 분류 트리", summary: "Map a failure cause to a recovery action, instead of blindly retrying.", summaryKo: "무작정 재시도하는 대신, 실패 원인을 복구 행동에 매핑합니다.", quadrant: "reference" },
      { slug: "verification/observability", title: "Observability", titleKo: "관측성", summary: "The lenses on a run. Hooks, runlog, audit diagnostics, Petri.", summaryKo: "실행을 들여다보는 렌즈들입니다. 훅, runlog, audit diagnostics, Petri입니다.", quadrant: "reference" },
    ],
  },
  {
    id: "09-develop",
    title: "Developer and Architecture",
    titleKo: "개발과 아키텍처",
    pages: [
      { slug: "develop/architecture", title: "Architecture deep-dive", titleKo: "아키텍처 심화", summary: "The subsystem map and a recommended reading order, retold as data-flow traces.", summaryKo: "서브시스템 지도와 추천 읽기 순서를 데이터 흐름 추적으로 풀어냅니다.", quadrant: "reference" },
      { slug: "architecture/system-index", title: "System index", titleKo: "시스템 색인", summary: "Every subsystem with its file path. The flat catalog.", summaryKo: "모든 서브시스템과 파일 경로입니다. 평면 카탈로그입니다.", quadrant: "reference" },
      { slug: "explanation/4-layer", title: "Why four layers", titleKo: "왜 4-계층인가", summary: "Model, Runtime, Harness, Agent. Why the boundaries fall where they do.", summaryKo: "Model, Runtime, Harness, Agent. 경계가 왜 그 자리에 있는지 설명합니다.", quadrant: "explanation" },
      { slug: "explanation/self-hosting", title: "Why a self-hosting harness", titleKo: "왜 self-hosting 하네스인가", summary: "The runtime and the build line share primitives. Why that mattered.", summaryKo: "런타임과 빌드 라인이 같은 기본 단위를 공유합니다. 그게 왜 중요했는지 설명합니다.", quadrant: "explanation" },
      { slug: "explanation/ratchet", title: "Why ratchet discipline", titleKo: "왜 ratchet 규율인가", summary: "Pinned prompt hashes and a staged CI. The shape that prevents drift.", summaryKo: "프롬프트 해시 핀과 단계별 CI입니다. drift를 막는 형태를 설명합니다.", quadrant: "explanation" },
      { slug: "ops/release-pypi-lifecycle", title: "Release and PyPI lifecycle", titleKo: "릴리스와 PyPI 라이프사이클", summary: "The version-bump locations, the release workflow, and the rebuild cadence.", summaryKo: "버전 bump 위치, 릴리스 워크플로우, rebuild 주기를 다룹니다.", quadrant: "how-to" },
      { slug: "ops/backlog-dispose", title: "Backlog disposal", titleKo: "백로그 처분", summary: "Retire an idea with a paper trail instead of a silent delete.", summaryKo: "조용히 삭제하는 대신 흔적을 남기며 아이디어를 정리합니다.", quadrant: "how-to" },
    ],
  },
];

/** Flat list of all leaf pages. Used by [...slug]/generateStaticParams. */
export function flattenSitemap(): DocPage[] {
  const out: DocPage[] = [];
  for (const section of DOCS_SITEMAP) {
    for (const page of section.pages) {
      out.push(page);
    }
  }
  return out;
}

/** Look up a page by slug (no leading slash, may be empty for index). */
export function findPage(slug: string): { page: DocPage; section: DocSection } | undefined {
  for (const section of DOCS_SITEMAP) {
    for (const page of section.pages) {
      if (page.slug === slug) return { page, section };
    }
  }
  return undefined;
}

/** Compute prev/next navigation for a given slug. */
export function adjacentPages(slug: string): { prev?: DocPage; next?: DocPage } {
  const all = flattenSitemap();
  const idx = all.findIndex((p) => p.slug === slug);
  if (idx < 0) return {};
  return {
    prev: idx > 0 ? all[idx - 1] : undefined,
    next: idx < all.length - 1 ? all[idx + 1] : undefined,
  };
}

/** Quadrant display metadata. */
export const QUADRANT_META: Record<DocQuadrant, { label: string; labelKo: string; color: string }> = {
  // Axolotl Rose mapping: gold = act (tutorial), aqua = inform (how-to),
  // rose = look up (reference), muted ink = understand (explanation).
  tutorial: { label: "Tutorial", labelKo: "튜토리얼", color: "#FFD66B" },
  "how-to": { label: "How-to", labelKo: "How-to", color: "#7FD8E8" },
  reference: { label: "Reference", labelKo: "레퍼런스", color: "#F49BC4" },
  explanation: { label: "Explanation", labelKo: "Explanation", color: "#9A93AC" },
};
