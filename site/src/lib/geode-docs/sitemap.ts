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
    id: "00-welcome",
    title: "Welcome",
    titleKo: "시작하기",
    pages: [
      {
        slug: "",
        title: "What GEODE is",
        titleKo: "GEODE 소개",
        summary: "A self-hosting agent harness. What it does, who it is for, where to go next.",
        summaryKo: "스스로를 빌드하는 자율 에이전트 하네스. 무엇을 하고, 누구를 위한 것이고, 어디로 갈지.",
        quadrant: "explanation",
      },
      {
        slug: "quick-start",
        title: "Quick Start",
        titleKo: "빠른 시작",
        summary: "Install GEODE and run your first analysis in five minutes.",
        summaryKo: "5분 안에 GEODE를 설치하고 첫 분석을 실행합니다.",
        quadrant: "tutorial",
      },
      {
        slug: "architecture/overview",
        title: "4-Layer Stack",
        titleKo: "4-계층 스택",
        summary: "Model. Runtime. Harness. Agent. One paragraph each.",
        summaryKo: "Model. Runtime. Harness. Agent. 한 문단씩.",
        quadrant: "reference",
      },
    ],
  },
  {
    id: "01-run",
    title: "Run GEODE",
    titleKo: "GEODE 실행하기",
    pages: [
      { slug: "run/pick-path", title: "Pick a Path", titleKo: "경로 선택", summary: "Subscription, API key, or free path. How to choose for your situation.", summaryKo: "구독, API 키, 무료 경로 중 본인 상황에 맞춰 고르는 법.", quadrant: "how-to" },
      { slug: "run/providers", title: "Configure Providers", titleKo: "프로바이더 설정", summary: "Anthropic, OpenAI, Codex, GLM. Where keys go, what fallback chain you get.", summaryKo: "Anthropic, OpenAI, Codex, GLM. 키를 어디에 두고 어떤 폴백 체인이 동작하는지.", quadrant: "how-to" },
      { slug: "run/analyze", title: "Run an Analysis", titleKo: "분석 실행", summary: "Run the Game IP pipeline end to end, dry-run or live.", summaryKo: "Game IP 파이프라인을 dry-run 또는 라이브로 끝까지 돌리기.", quadrant: "how-to" },
      { slug: "run/schedule", title: "Schedule Tasks", titleKo: "작업 예약", summary: "Natural language plus cron, with jitter. Daily reports as a single command.", summaryKo: "자연어와 cron, jitter 포함. 일일 리포트를 한 줄 명령으로.", quadrant: "how-to" },
      { slug: "run/serve", title: "Run as Daemon", titleKo: "데몬으로 실행", summary: "Start serve, restart, stop. Thin CLI on top of an IPC-served runtime.", summaryKo: "serve 시작·재시작·종료. IPC 데몬 위에 thin CLI.", quadrant: "how-to" },
      { slug: "run/messaging", title: "Messaging Integrations", titleKo: "메신저 연동", summary: "Hook GEODE into Slack, Discord, or Telegram via gateway adapters.", summaryKo: "게이트웨이 어댑터로 Slack, Discord, Telegram에 연결.", quadrant: "how-to" },
      { slug: "run/troubleshooting", title: "Troubleshooting", titleKo: "문제 해결", summary: "Common failure modes and where to look. Logs, hooks, runlog.", summaryKo: "흔한 실패 모드와 살펴볼 곳. 로그, 훅, runlog.", quadrant: "how-to" },
    ],
  },
  {
    id: "02-reference",
    title: "System Reference",
    titleKo: "시스템 레퍼런스",
    pages: [
      { slug: "architecture/agentic-loop", title: "Agentic Loop", titleKo: "Agentic 루프", summary: "while(tool_use) primitive. 50-round limit. 5 termination paths.", summaryKo: "while(tool_use) 기본 단위. 50 라운드 상한. 5종 종료 경로.", quadrant: "reference" },
      { slug: "architecture/system-index", title: "System Index", titleKo: "시스템 색인", summary: "Every subsystem with file paths. The flat catalog.", summaryKo: "모든 서브시스템과 파일 경로. 평면 카탈로그.", quadrant: "reference" },
      { slug: "runtime/llm/providers", title: "Providers", titleKo: "프로바이더", summary: "Anthropic, OpenAI, Codex, GLM. Wire-level differences and fallback chains.", summaryKo: "Anthropic, OpenAI, Codex, GLM. wire-level 차이와 폴백 체인.", quadrant: "reference" },
      { slug: "runtime/llm/prompt-system", title: "Prompt System", titleKo: "프롬프트 시스템", summary: "5-layer prompt architecture. Assembly pipeline.", summaryKo: "프롬프트 5계층 아키텍처. 어셈블리 파이프라인.", quadrant: "reference" },
      { slug: "runtime/llm/prompt-caching", title: "Prompt Caching", titleKo: "프롬프트 캐싱", summary: "STATIC and DYNAMIC boundary. Ephemeral cache control.", summaryKo: "STATIC과 DYNAMIC 경계. ephemeral 캐시 제어.", quadrant: "reference" },
      { slug: "runtime/llm/prompt-hashing", title: "Prompt Hashing", titleKo: "프롬프트 해싱", summary: "Karpathy P4 ratchet. 20 pinned hashes. Build break on drift.", summaryKo: "Karpathy P4 ratchet. 20개 해시 핀. drift 발생 시 빌드 break.", quadrant: "reference" },
      { slug: "runtime/llm/langsmith", title: "LangSmith", titleKo: "LangSmith", summary: "Opt-in tracing. Hook + RunLog replacement path.", summaryKo: "Opt-in 트레이싱. 훅과 RunLog 대체 경로.", quadrant: "reference" },
      { slug: "runtime/tools/protocol", title: "Tool Protocol", titleKo: "도구 프로토콜", summary: "Registry, deferred loading, 61 tools. Six always-loaded, the rest fetched on demand.", summaryKo: "레지스트리, 지연 로딩, 61개 도구. 6개 상시 로드, 나머지는 요청 시 가져옴.", quadrant: "reference" },
      { slug: "runtime/tools/mcp", title: "MCP Servers", titleKo: "MCP 서버", summary: "Servers, 25K result guard, HTML to Markdown fallback.", summaryKo: "서버, 25K 결과 가드, HTML to Markdown 폴백.", quadrant: "reference" },
      { slug: "runtime/memory/5-tier", title: "5-Tier Context", titleKo: "5계층 컨텍스트", summary: "raw → assembled → projected. Where each layer reads and writes.", summaryKo: "raw → assembled → projected. 각 계층의 read·write 경로.", quadrant: "reference" },
      { slug: "runtime/memory/vault", title: "Vault", titleKo: "Vault", summary: "Agent artifact storage. Lifetime and access rules.", summaryKo: "에이전트 산출물 저장소. 수명과 접근 규칙.", quadrant: "reference" },
      { slug: "harness/cli", title: "CLI and Slash", titleKo: "CLI와 슬래시 명령", summary: "Thin gateway plus IPC. /model /stop /clean /uninstall /status.", summaryKo: "Thin 게이트웨이와 IPC. /model /stop /clean /uninstall /status.", quadrant: "reference" },
      { slug: "harness/hooks", title: "Hook System", titleKo: "훅 시스템", summary: "58 lifecycle events grouped into 14 categories. Three trigger modes.", summaryKo: "58개 라이프사이클 이벤트, 14개 카테고리. 세 가지 트리거 모드.", quadrant: "reference" },
      { slug: "harness/lifecycle", title: "Lifecycle", titleKo: "라이프사이클", summary: "Bootstrap, serve, shutdown. ContextVar injection order.", summaryKo: "Bootstrap, serve, shutdown. ContextVar 주입 순서.", quadrant: "reference" },
      { slug: "verification/guardrails", title: "Guardrails G1-G4", titleKo: "가드레일 G1-G4", summary: "Schema, Range, Grounding, Coherence. Fail-fast ladder.", summaryKo: "Schema, Range, Grounding, Coherence. fail-fast 사다리.", quadrant: "reference" },
      { slug: "verification/biasbuster", title: "BiasBuster", titleKo: "BiasBuster", summary: "Six bias detectors. Confirmation, recency, anchoring, and three more.", summaryKo: "6종 편향 검사기. Confirmation, recency, anchoring 외 3종.", quadrant: "reference" },
      { slug: "runtime/computer-use", title: "Computer Use", titleKo: "컴퓨터 사용", summary: "Provider-agnostic desktop automation. Anthropic plus OpenAI unified.", summaryKo: "프로바이더 독립 데스크탑 자동화. Anthropic + OpenAI 통합.", quadrant: "reference" },
      { slug: "runtime/scheduler", title: "Scheduler", titleKo: "스케줄러", summary: "Natural language plus cron plus jitter. Where jobs persist.", summaryKo: "자연어 + cron + jitter. 작업 영속 위치.", quadrant: "reference" },
      { slug: "runtime/automation", title: "Automation (L4.5)", titleKo: "자동화 (L4.5)", summary: "Feedback loop plus model promotion. Drift detection.", summaryKo: "피드백 루프 + 모델 프로모션. drift 감지.", quadrant: "reference" },
      { slug: "runtime/orchestration", title: "Orchestration", titleKo: "오케스트레이션", summary: "LangGraph StateGraph. Node topology. Send API parallelism.", summaryKo: "LangGraph StateGraph. 노드 토폴로지. Send API 병렬화.", quadrant: "reference" },
      { slug: "runtime/auth", title: "Auth and OAuth", titleKo: "인증과 OAuth", summary: "Profile rotator, Anthropic ToS path, Codex flow.", summaryKo: "프로파일 로테이터, Anthropic ToS 경로, Codex 플로우.", quadrant: "reference" },
      { slug: "runtime/domains", title: "Domain Plugins", titleKo: "도메인 플러그인", summary: "DomainPort protocol. plugin loader. Add a domain in 30 lines.", summaryKo: "DomainPort 프로토콜. 플러그인 로더. 30 라인으로 도메인 추가.", quadrant: "reference" },
      { slug: "runtime/skills", title: "Skill Registry", titleKo: "스킬 레지스트리", summary: "Runtime skills. Discovery, lifecycle, override.", summaryKo: "런타임 스킬. 발견, 라이프사이클, 오버라이드.", quadrant: "reference" },
      { slug: "plugins/game-ip", title: "Game IP Plugin", titleKo: "Game IP 플러그인", summary: "4 Analysts plus 3 Evaluators plus Synthesizer. 14-axis PSM scoring.", summaryKo: "Analyst 4 + Evaluator 3 + Synthesizer. 14-axis PSM 점수.", quadrant: "reference" },
    ],
  },
  {
    id: "03-build",
    title: "Build on GEODE",
    titleKo: "GEODE 위에서 만들기",
    pages: [
      { slug: "build/add-tool", title: "Add a Tool", titleKo: "도구 추가하기", summary: "Define, register, expose via definitions.json. Make it deferred-loadable.", summaryKo: "정의하고, 등록하고, definitions.json에 노출. deferred 가능하게 만들기.", quadrant: "how-to" },
      { slug: "build/add-domain", title: "Add a Domain Plugin", titleKo: "도메인 플러그인 추가", summary: "Implement DomainPort. Wire into core/domains/loader.py registry.", summaryKo: "DomainPort 구현. core/domains/loader.py 레지스트리에 연결.", quadrant: "how-to" },
      { slug: "build/add-hook", title: "Add a Hook Handler", titleKo: "훅 핸들러 추가", summary: "Pick an event, register a handler, verify with the test harness.", summaryKo: "이벤트 선택, 핸들러 등록, 테스트 하네스로 검증.", quadrant: "how-to" },
      { slug: "build/testing", title: "Test Your Changes", titleKo: "변경사항 테스트", summary: "ruff. mypy. pytest. E2E dry-run. The four quality gates.", summaryKo: "ruff. mypy. pytest. E2E dry-run. 4개 품질 게이트.", quadrant: "how-to" },
    ],
  },
  {
    id: "04-ops",
    title: "Operations",
    titleKo: "운영",
    pages: [
      { slug: "ops/long-running", title: "Long-running Safety", titleKo: "장기 실행 안전", summary: "Token guards, context overflow, sliding window. Graceful drain.", summaryKo: "토큰 가드, 컨텍스트 오버플로, 슬라이딩 윈도. graceful drain.", quadrant: "how-to" },
      { slug: "ops/cost", title: "Cost Monitoring", titleKo: "비용 모니터링", summary: "Per-session and per-day budgets. When to switch models.", summaryKo: "세션·일별 예산. 모델 전환 시점.", quadrant: "how-to" },
      { slug: "ops/oauth", title: "OAuth Token Rotation", titleKo: "OAuth 토큰 회전", summary: "Anthropic ToS, Codex flow, refresh policy.", summaryKo: "Anthropic ToS, Codex 플로우, 갱신 정책.", quadrant: "how-to" },
      { slug: "ops/observability", title: "Observability", titleKo: "관측성", summary: "Hooks, RunLog, Petri audits. Three lenses, one runtime.", summaryKo: "훅, RunLog, Petri 감사. 세 가지 렌즈, 하나의 런타임.", quadrant: "how-to" },
    ],
  },
  {
    id: "05-petri",
    title: "Petri Audit",
    titleKo: "Petri 감사",
    pages: [
      { slug: "petri/overview", title: "Petri × GEODE Integration", titleKo: "Petri × GEODE 통합", summary: "Anthropic Alignment Science's framework, wrapped over GEODE's agent. 173 seeds, 38 judge dimensions.", summaryKo: "Anthropic Alignment Science의 프레임워크를 GEODE 에이전트 위에 얹음. 173 seeds, 38 judge 차원.", quadrant: "explanation" },
      { slug: "petri/run", title: "Run an Audit", titleKo: "감사 실행", summary: "inspect eval inspect_petri/audit. Choose model roles, seeds, and turn budget.", summaryKo: "inspect eval inspect_petri/audit. 모델 역할, seeds, turn 예산 선택.", quadrant: "how-to" },
      { slug: "petri/judge-dimensions", title: "38 Judge Dimensions", titleKo: "38 Judge 차원", summary: "What each dimension scores. How to read the heatmap.", summaryKo: "각 차원이 무엇을 평가하는지. heatmap 읽는 법.", quadrant: "reference" },
      { slug: "petri/bundle", title: "Audit Bundle Viewer", titleKo: "감사 Bundle 뷰어", summary: "Live inspect_ai transcript viewer for the latest GEODE audit run.", summaryKo: "최신 GEODE 감사 run의 라이브 inspect_ai 트랜스크립트 뷰어.", quadrant: "reference", externalUrl: "/petri-bundle/" },
    ],
  },
  {
    id: "06-why",
    title: "Explanation",
    titleKo: "왜 이렇게",
    pages: [
      { slug: "explanation/self-hosting", title: "Why a Self-Hosting Harness", titleKo: "왜 self-hosting 하네스인가", summary: "The runtime and the build line share primitives. Why that mattered.", summaryKo: "런타임과 빌드 라인이 같은 기본 단위를 공유하는 이유.", quadrant: "explanation" },
      { slug: "explanation/ratchet", title: "Why Ratchet Discipline", titleKo: "왜 ratchet 규율인가", summary: "20 pinned prompt hashes. 5-stage CI. The ratchet shape that prevents drift.", summaryKo: "20개 프롬프트 해시 핀. 5단계 CI. drift를 막는 ratchet 형태.", quadrant: "explanation" },
      { slug: "explanation/4-layer", title: "Why 4 Layers", titleKo: "왜 4-계층인가", summary: "Model, Runtime, Harness, Agent. Where each layer's responsibility ends.", summaryKo: "Model, Runtime, Harness, Agent. 각 계층의 책임이 끝나는 지점.", quadrant: "explanation" },
      { slug: "explanation/solo", title: "Why a Solo Author", titleKo: "왜 단독 저자인가", summary: "What ratchet-driven release lets one person hold together. Trade-offs.", summaryKo: "ratchet-driven release가 한 명이 끌고 갈 수 있게 해주는 것. 트레이드오프.", quadrant: "explanation" },
    ],
  },
  {
    id: "99-reference",
    title: "Reference",
    titleKo: "레퍼런스",
    pages: [
      { slug: "reference/changelog", title: "Changelog", titleKo: "변경 이력", summary: "Version history mirrored from CHANGELOG.md.", summaryKo: "CHANGELOG.md를 미러한 버전 이력.", quadrant: "reference" },
      { slug: "reference/frontier-comparison", title: "Frontier Comparison", titleKo: "프론티어 비교", summary: "GEODE versus Claude Code, Codex CLI, OpenClaw, Hermes, autoresearch.", summaryKo: "GEODE와 Claude Code, Codex CLI, OpenClaw, Hermes, autoresearch 비교.", quadrant: "reference" },
      { slug: "reference/sot-metrics", title: "System Metrics SOT", titleKo: "시스템 메트릭 SOT", summary: "Live values for version, modules, tests, releases, since.", summaryKo: "version, 모듈, 테스트, 릴리스, since 라이브 값.", quadrant: "reference" },
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
  tutorial: { label: "Tutorial", labelKo: "튜토리얼", color: "#E89B57" },
  "how-to": { label: "How-to", labelKo: "How-to", color: "#7BB97B" },
  reference: { label: "Reference", labelKo: "레퍼런스", color: "#7895C2" },
  explanation: { label: "Explanation", labelKo: "Explanation", color: "#A573E8" },
};
