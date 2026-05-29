"use client";

import Link from "next/link";
import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { DOCS_SITEMAP } from "@/lib/geode-docs/sitemap";
import { useLocale, t } from "@/components/geode/locale-context";
import { GEODE_SOT } from "@/data/geode/sot";

export default function DocsIndex() {
  const locale = useLocale();
  const summaryEn = `A general-purpose autonomous execution agent built on LangGraph. v${GEODE_SOT.version}, Python 3.12+, ${GEODE_SOT.modules.core} core + ${GEODE_SOT.modules.plugins} plugins = ${GEODE_SOT.modules.total} modules, ${GEODE_SOT.tests.standard.toLocaleString()} tests, 81 hook events, 59 tools.`;
  const summaryKo = `LangGraph 기반 범용 자율 실행 에이전트. v${GEODE_SOT.version}, Python 3.12+, core ${GEODE_SOT.modules.core} + plugins ${GEODE_SOT.modules.plugins} = ${GEODE_SOT.modules.total} 모듈, ${GEODE_SOT.tests.standard.toLocaleString()} 테스트, 81 훅, 59 도구.`;
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
            <h2>GEODE 는 무엇인가</h2>
            <p>
              GEODE 는 LangGraph 위에 올린 <strong>장기 실행 자율 실행
              하네스</strong>입니다. 4 계층 (Model · Runtime · Harness · Agent)
              으로 연구, 분석, 자동화, 스케줄링을 스스로 수행하고,
              <code>geode serve</code> 데몬 + 메신저 게이트웨이로 상주합니다.
            </p>
            <h2>두 개의 루프</h2>
            <p>
              GEODE 를 가르는 핵심은 <strong>두 개의 루프</strong>입니다.
            </p>
            <ul>
              <li>
                <strong>Inner loop (Agentic Loop)</strong> — 한 작업을 푸는{" "}
                <code>while(tool_use)</code> 실행 루프. 50 라운드 상한, 5 종료
                경로, 59 도구 + 지연 로딩 (아키텍처 / 런타임 / 하네스 섹션).
              </li>
              <li>
                <strong>Outer loop (Self-Improving Loop)</strong> — GEODE 가
                자기 자신을 개선하는 폐루프. mutation → Petri audit → attribution
                → promote/revert (autoresearch) 와, Petri seed 를 co-scientist
                토너먼트로 진화시키는 seed-generation 이 맞물립니다 (Self-Improving
                Loop 섹션).
              </li>
            </ul>
            <p className="text-white/40 text-sm">
              코드베이스와 wiki(<code>mango-wiki/projects/geode</code>)에서 추출,
              현재 프로덕션 버전을 반영합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>What GEODE is</h2>
            <p>
              GEODE is a <strong>long-running autonomous execution harness</strong>{" "}
              built on LangGraph. A four-layer stack (Model · Runtime · Harness ·
              Agent) runs research, analysis, automation, and scheduling on its
              own, resident behind a <code>geode serve</code> daemon and messaging
              gateways.
            </p>
            <h2>Two loops</h2>
            <p>The defining idea is <strong>two loops</strong>:</p>
            <ul>
              <li>
                <strong>Inner loop (the Agentic Loop)</strong> — the{" "}
                <code>while(tool_use)</code> primitive that solves one task: a
                50-round cap, five termination paths, 59 tools with deferred
                loading (the Architecture / Runtime / Harness sections).
              </li>
              <li>
                <strong>Outer loop (the Self-Improving Loop)</strong> — the closed
                loop where GEODE improves itself: mutation → Petri audit →
                attribution → promote/revert (autoresearch), meshed with
                seed-generation evolving the Petri seed corpus through a
                co-scientist tournament (the Self-Improving Loop section).
              </li>
            </ul>
            <p className="text-white/40 text-sm">
              Generated from the codebase and the wiki at{" "}
              <code>mango-wiki/projects/geode</code>, reflecting the current
              production version.
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
