/**
 * GEODE Docs sitemap — single source of truth for navigation and route generation.
 *
 * Each leaf entry maps to a static page at /geode/docs/<slug>.
 * Sections are rendered in the sidebar in the order declared.
 *
 * Bilingual: every entry carries an English and Korean title + summary.
 */

export type DocPage = {
  slug: string;
  title: string;
  titleKo: string;
  summary?: string;
  summaryKo?: string;
};

export type DocSection = {
  id: string;
  title: string;
  titleKo: string;
  pages: DocPage[];
};

export const DOCS_SITEMAP: DocSection[] = [
  {
    id: "intro",
    title: "Introduction",
    titleKo: "시작하기",
    pages: [
      { slug: "", title: "Overview", titleKo: "개요", summary: "What GEODE is and how the docs are organized", summaryKo: "GEODE의 정체성과 docs 구성" },
      { slug: "quick-start", title: "Quick Start", titleKo: "빠른 시작", summary: "Install and run", summaryKo: "설치와 실행" },
    ],
  },
  {
    id: "architecture",
    title: "Architecture",
    titleKo: "아키텍처",
    pages: [
      { slug: "architecture/overview", title: "4-Layer Stack", titleKo: "4-계층 스택", summary: "Model → Runtime → Harness → Agent", summaryKo: "Model → Runtime → Harness → Agent" },
      { slug: "architecture/agentic-loop", title: "Agentic Loop", titleKo: "Agentic 루프", summary: "while(tool_use) primitive", summaryKo: "while(tool_use) 기본 단위" },
      { slug: "architecture/system-index", title: "System Index", titleKo: "시스템 색인", summary: "All subsystems catalog", summaryKo: "전체 서브시스템 카탈로그" },
    ],
  },
  {
    id: "runtime-llm",
    title: "Runtime · LLM",
    titleKo: "런타임 · LLM",
    pages: [
      { slug: "runtime/llm/prompt-system", title: "Prompt System", titleKo: "프롬프트 시스템", summary: "5-layer prompt architecture", summaryKo: "프롬프트 5계층 아키텍처" },
      { slug: "runtime/llm/prompt-caching", title: "Prompt Caching", titleKo: "프롬프트 캐싱", summary: "STATIC/DYNAMIC boundary + ephemeral", summaryKo: "STATIC/DYNAMIC 경계 + ephemeral 캐시" },
      { slug: "runtime/llm/prompt-hashing", title: "Prompt Hashing", titleKo: "프롬프트 해싱", summary: "Karpathy P4 ratchet, 20 pinned hashes", summaryKo: "Karpathy P4 ratchet, 20 핀" },
      { slug: "runtime/llm/providers", title: "Providers", titleKo: "프로바이더", summary: "Anthropic / OpenAI / Codex / GLM", summaryKo: "Anthropic / OpenAI / Codex / GLM" },
      { slug: "runtime/llm/langsmith", title: "LangSmith", titleKo: "LangSmith", summary: "Opt-in tracing", summaryKo: "Opt-in 트레이싱" },
    ],
  },
  {
    id: "runtime-tools",
    title: "Runtime · Tools",
    titleKo: "런타임 · 도구",
    pages: [
      { slug: "runtime/tools/protocol", title: "Tool Protocol", titleKo: "도구 프로토콜", summary: "Tool registry, deferred loading", summaryKo: "도구 레지스트리, 지연 로딩" },
      { slug: "runtime/tools/mcp", title: "MCP Servers", titleKo: "MCP 서버", summary: "16 servers, 25K guard", summaryKo: "16개 서버, 25K 토큰 가드" },
    ],
  },
  {
    id: "runtime-memory",
    title: "Runtime · Memory",
    titleKo: "런타임 · 메모리",
    pages: [
      { slug: "runtime/memory/5-tier", title: "5-Tier Context", titleKo: "5계층 컨텍스트", summary: "raw → assembled → projected", summaryKo: "raw → assembled → projected" },
      { slug: "runtime/memory/vault", title: "Vault", titleKo: "Vault", summary: "Agent artifact storage", summaryKo: "에이전트 산출물 저장소" },
    ],
  },
  {
    id: "runtime-other",
    title: "Runtime · Other",
    titleKo: "런타임 · 기타",
    pages: [
      { slug: "runtime/scheduler", title: "Scheduler", titleKo: "스케줄러", summary: "NL + cron + jitter", summaryKo: "자연어 + cron + jitter" },
      { slug: "runtime/automation", title: "Automation (L4.5)", titleKo: "자동화 (L4.5)", summary: "Feedback loop + model promotion", summaryKo: "피드백 루프 + 모델 프로모션" },
      { slug: "runtime/orchestration", title: "Orchestration", titleKo: "오케스트레이션", summary: "LangGraph StateGraph", summaryKo: "LangGraph StateGraph" },
      { slug: "runtime/auth", title: "Auth & OAuth", titleKo: "인증 & OAuth", summary: "Profile rotator, Anthropic ToS, Codex", summaryKo: "프로파일 로테이터, Anthropic ToS, Codex" },
      { slug: "runtime/computer-use", title: "Computer Use", titleKo: "컴퓨터 사용", summary: "Provider-agnostic desktop automation", summaryKo: "프로바이더 독립 데스크탑 자동화" },
      { slug: "runtime/domains", title: "Domain Plugins", titleKo: "도메인 플러그인", summary: "DomainPort protocol, plugin loader", summaryKo: "DomainPort 프로토콜, 플러그인 로더" },
    ],
  },
  {
    id: "harness",
    title: "Harness",
    titleKo: "하네스",
    pages: [
      { slug: "harness/cli", title: "CLI & Slash Commands", titleKo: "CLI & 슬래시 명령", summary: "Thin gateway + IPC", summaryKo: "Thin 게이트웨이 + IPC" },
      { slug: "harness/hooks", title: "Hook System", titleKo: "훅 시스템", summary: "58 events lifecycle", summaryKo: "58개 라이프사이클 이벤트" },
      { slug: "harness/lifecycle", title: "Lifecycle", titleKo: "라이프사이클", summary: "Bootstrap / serve / shutdown", summaryKo: "부트스트랩 / 서브 / 종료" },
    ],
  },
  {
    id: "verification",
    title: "Verification",
    titleKo: "검증",
    pages: [
      { slug: "verification/guardrails", title: "Guardrails G1-G4", titleKo: "가드레일 G1-G4", summary: "Schema/Range/Grounding/Coherence", summaryKo: "Schema/Range/Grounding/Coherence" },
      { slug: "verification/biasbuster", title: "BiasBuster", titleKo: "BiasBuster", summary: "6 bias detection", summaryKo: "6가지 편향 검사" },
    ],
  },
  {
    id: "plugins",
    title: "Plugins",
    titleKo: "플러그인",
    pages: [
      { slug: "plugins/game-ip", title: "Game IP Plugin", titleKo: "Game IP 플러그인", summary: "4 Analysts + 3 Evaluators + Synthesizer", summaryKo: "4 Analyst + 3 Evaluator + Synthesizer" },
    ],
  },
  {
    id: "reference",
    title: "Reference",
    titleKo: "레퍼런스",
    pages: [
      { slug: "reference/changelog", title: "Changelog", titleKo: "변경 이력", summary: "Version history", summaryKo: "버전 이력" },
      { slug: "reference/frontier-comparison", title: "Frontier Comparison", titleKo: "프론티어 비교", summary: "GEODE vs Hermes/OpenClaw/Claude Code", summaryKo: "GEODE vs Hermes/OpenClaw/Claude Code" },
    ],
  },
];

/** Flat list of all leaf pages — used by [...slug]/generateStaticParams. */
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
