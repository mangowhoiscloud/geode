"use client";

import Link from "next/link";
import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { DOCS_SITEMAP } from "@/lib/geode-docs/sitemap";
import { useLocale, t } from "@/components/geode/locale-context";
import { GEODE_SOT } from "@/data/geode/sot";

export default function DocsIndex() {
  const locale = useLocale();
  const summaryEn = `A general-purpose autonomous execution agent built on LangGraph. v${GEODE_SOT.version}, Python 3.12+, ${GEODE_SOT.modules.core} core + ${GEODE_SOT.modules.plugins} plugins = ${GEODE_SOT.modules.total} modules, ${GEODE_SOT.tests.standard.toLocaleString()} tests, 58 hook events, 61 tools.`;
  const summaryKo = `LangGraph 기반 범용 자율 실행 에이전트. v${GEODE_SOT.version}, Python 3.12+, core ${GEODE_SOT.modules.core} + plugins ${GEODE_SOT.modules.plugins} = ${GEODE_SOT.modules.total} 모듈, ${GEODE_SOT.tests.standard.toLocaleString()} 테스트, 58 훅, 61 도구.`;
  return (
    <DocsShell
      slug=""
      title="GEODE Documentation"
      titleKo="GEODE 문서"
      summary={summaryEn}
      summaryKo={summaryKo}
    >
      <Bi
        ko={
          <>
            <h2>이 문서에서 다루는 것</h2>
            <p>
              본 사이트는 GEODE 의 아키텍처, 런타임, 하네스, 플러그인 생태계를
              다룹니다. 코드베이스와 wiki(<code>mango-wiki/projects/geode</code>)
              에서 추출되어 현재 프로덕션 버전을 반영합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>What you&apos;ll find here</h2>
            <p>
              This site documents GEODE&apos;s architecture, runtime, harness,
              and plugin ecosystem. It is generated from the codebase and the
              wiki at <code>mango-wiki/projects/geode</code>, and reflects the
              current production version.
            </p>
          </>
        }
      />

      <h2>{t(locale, "섹션", "Sections")}</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 not-prose">
        {DOCS_SITEMAP.filter((s) => s.id !== "intro").map((section) => (
          <Link
            key={section.id}
            href={`/docs/${section.pages[0]?.slug ?? ""}`}
            className="block rounded-lg border border-white/[0.06] hover:border-white/[0.14] p-4 transition-colors group"
          >
            <div className="text-[10px] uppercase tracking-[0.18em] text-white/40 mb-1.5">
              {section.id}
            </div>
            <div className="text-[#F0F0FF] font-display font-semibold text-lg group-hover:text-white">
              {t(locale, section.titleKo, section.title)}
            </div>
            <div className="mt-1 text-sm text-white/60">
              {section.pages.length}{" "}
              {t(
                locale,
                section.pages.length === 1 ? "페이지" : "페이지",
                section.pages.length === 1 ? "page" : "pages"
              )}
              {" . "}
              {section.pages.slice(0, 3).map((p, i) => (
                <span key={p.slug}>
                  {i > 0 && ", "}
                  {t(locale, p.titleKo, p.title)}
                </span>
              ))}
              {section.pages.length > 3 && ", …"}
            </div>
          </Link>
        ))}
      </div>

      <Bi
        ko={
          <>
            <h2>상태</h2>
            <p>
              모든 섹션은 푸터의 날짜 기준 콘텐츠 완료 상태입니다. 페이지는
              자동 생성된 API 레퍼런스가 아니라 사람이 큐레이팅한 내러티브입니다.
              메트릭은 GEODE_SOT (`site/src/data/geode/sot.ts`)에서 자동 sync됩니다.
            </p>

            <h2>이 문서가 다루지 않는 것</h2>
            <ul>
              <li>API 레퍼런스 자동 생성 (이 사이트는 사람이 작성한 내러티브)</li>
              <li>검색 인덱스 (사이드바가 네비게이션 표면)</li>
              <li>버전별 문서 (현재 main 브랜치만 반영)</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Status</h2>
            <p>
              All sections are content-complete as of the date in the footer.
              Pages are hand-curated narrative, not an auto-generated API
              reference. Metrics are auto-synced from GEODE_SOT
              (<code>site/src/data/geode/sot.ts</code>).
            </p>

            <h2>Out of scope</h2>
            <ul>
              <li>API reference auto-generation (this site is hand-curated narrative).</li>
              <li>Search index (the sidebar is the navigation surface).</li>
              <li>Versioned docs (the site reflects the current main branch).</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
