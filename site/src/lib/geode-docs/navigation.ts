import type { DocPage, DocSection } from "./sitemap";

/** Reader tasks group existing topics; sitemap.ts still owns every page and URL. */
export const DOCS_NAV_GROUPS = [
  {
    id: "start",
    title: "Get started",
    titleKo: "시작하기",
    summary: "Install GEODE, choose a provider, and run your first task.",
    summaryKo: "GEODE를 설치하고 프로바이더를 선택해 첫 작업을 실행합니다.",
    sectionIds: ["01-overview", "02-start"],
    entrySlugs: ["quick-start", "run/pick-path", "overview/how-it-runs"],
  },
  {
    id: "use",
    title: "Use and extend",
    titleKo: "사용과 확장",
    summary: "Find commands, schedule work, or connect your own tools.",
    summaryKo: "명령을 찾고 작업을 예약하거나 도구를 추가합니다.",
    sectionIds: ["07-guides"],
    entrySlugs: ["harness/cli", "run/schedule", "guides/custom-tool"],
  },
  {
    id: "operate",
    title: "Configure and operate",
    titleKo: "설정과 운영",
    summary: "Configure credentials and services, track costs, and resolve failures.",
    summaryKo: "자격 증명과 서비스를 설정하고 비용과 실행 오류를 확인합니다.",
    sectionIds: ["08-config", "05-operate"],
    entrySlugs: ["config/basics", "run/providers", "run/troubleshooting"],
  },
  {
    id: "reference",
    title: "Internals and evidence",
    titleKo: "내부 구조와 평가 근거",
    summary: "Trace runtime contracts, inspect evaluations, and explore the codebase.",
    summaryKo: "런타임 계약과 평가 근거를 읽고 코드베이스를 탐색합니다.",
    sectionIds: ["03-concepts", "04-self-improving", "06-benchmarks", "09-reference", "10-develop", "10-codebase-map"],
    entrySlugs: ["architecture/agentic-loop", "benchmarks/terminal-bench", "develop/architecture"],
  },
] as const;

export function docsPageHref(slug: string, locale: "ko" | "en"): string {
  return `/docs${slug ? `/${slug}` : ""}${locale === "en" ? "?lang=en" : ""}`;
}

/** A local title, summary, and path filter, not full-text document search. */
export function matchesDocQuery(page: DocPage, query: string, section?: DocSection): boolean {
  const chapter = section?.chapters?.find((item) => item.id === page.chapter);
  const text = [page.title, page.titleKo, page.summary, page.summaryKo, page.slug,
    section?.title, section?.titleKo, chapter?.title, chapter?.titleKo]
    .filter(Boolean).join(" ").toLowerCase();
  return query.trim().toLowerCase().split(/\s+/).every((word) => text.includes(word));
}

export function matchesDocPath(pageSlug: string, currentSlug: string): boolean {
  return pageSlug === currentSlug || (pageSlug !== "" && currentSlug.startsWith(`${pageSlug}/`));
}

/** One optional chapter level; publication still reads the flat page list. */
export function docChapters(section: DocSection) {
  return (section.chapters ?? []).map((chapter) => ({
    ...chapter,
    pages: section.pages.filter((page) => page.chapter === chapter.id),
  })).filter((chapter) => chapter.pages.length > 0);
}
