"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, type CSSProperties } from "react";
import { useLocale, useSetLocale, t } from "@/components/geode/locale-context";
import { DOCS_SITEMAP, adjacentPages, findPage, QUADRANT_META, type DocQuadrant } from "@/lib/geode-docs/sitemap";
import { GEODE_SOT } from "@/data/geode/sot";

const DOCS_BASE = "/docs";

function pageHref(slug: string): string {
  return slug ? `${DOCS_BASE}/${slug}` : DOCS_BASE;
}

function QuadrantChip({ quadrant, size = "sm" }: { quadrant: DocQuadrant; size?: "sm" | "xs" }) {
  const locale = useLocale();
  const meta = QUADRANT_META[quadrant];
  const classes =
    size === "xs"
      ? "inline-flex items-center px-1.5 py-0 rounded text-[9px] font-mono uppercase tracking-wider"
      : "inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider";
  return (
    <span
      className={classes}
      style={{ color: meta.color, border: `1px solid ${meta.color}40`, backgroundColor: `${meta.color}10` }}
    >
      {t(locale, meta.labelKo, meta.label)}
    </span>
  );
}

function Sidebar() {
  const pathname = usePathname() ?? "";
  const locale = useLocale();
  return (
    <nav className="text-sm">
      <Link
        href={DOCS_BASE}
        className="block px-3 py-2 text-[#F0F0FF] font-display font-bold tracking-wide"
      >
        {t(locale, "GEODE Docs", "GEODE Docs")}
      </Link>
      <div className="mt-2 space-y-5">
        {DOCS_SITEMAP.map((section) => {
          // The Self-Improving Loop section carries the petri-blue signature
          // accent (see DESIGN.md §11.1); every other section stays muted.
          const sectionAccent =
            section.id === "04-self-improving" ? "var(--acc-si)" : undefined;
          return (
          <div key={section.id}>
            <div
              className="px-3 text-[10px] uppercase tracking-[0.18em] text-white/40 font-semibold mb-2"
              style={sectionAccent ? { color: sectionAccent } : undefined}
            >
              {t(locale, section.titleKo, section.title)}
            </div>
            <ul className="space-y-0.5">
              {section.pages.map((page) => {
                const href = pageHref(page.slug);
                const active = pathname === href || pathname === `${href}/`;
                const meta = QUADRANT_META[page.quadrant];
                return (
                  <li key={page.slug || "_index"}>
                    <Link
                      href={href}
                      className={
                        "flex items-center gap-2 px-3 py-1.5 rounded text-[13px] transition-colors " +
                        (active
                          ? "bg-white/[0.06] text-[#F0F0FF]"
                          : "text-white/60 hover:text-[#F0F0FF] hover:bg-white/[0.03]")
                      }
                      style={active && sectionAccent ? { color: sectionAccent } : undefined}
                    >
                      <span
                        className="shrink-0 inline-block w-1 h-1 rounded-full"
                        style={{ backgroundColor: meta.color }}
                        aria-label={meta.label}
                      />
                      <span className="flex-1 truncate">{t(locale, page.titleKo, page.title)}</span>
                      {page.externalUrl && (
                        <span className="text-[9px] text-white/30">↗</span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
          );
        })}
      </div>
    </nav>
  );
}

function PrevNext({ slug }: { slug: string }) {
  const { prev, next } = adjacentPages(slug);
  const locale = useLocale();
  if (!prev && !next) return null;
  return (
    <div className="mt-16 grid grid-cols-2 gap-4 border-t border-white/[0.06] pt-8">
      <div>
        {prev && (
          <Link
            href={pageHref(prev.slug)}
            className="docs-card block group rounded-lg border border-white/[0.06] p-4 hover:border-white/[0.12] transition-colors"
          >
            <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">
              {t(locale, "이전", "Previous")}
            </div>
            <div className="text-[#F0F0FF] font-medium group-hover:text-white">
              ← {t(locale, prev.titleKo, prev.title)}
            </div>
          </Link>
        )}
      </div>
      <div className="text-right">
        {next && (
          <Link
            href={pageHref(next.slug)}
            className="docs-card block group rounded-lg border border-white/[0.06] p-4 hover:border-white/[0.12] transition-colors"
          >
            <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">
              {t(locale, "다음", "Next")}
            </div>
            <div className="text-[#F0F0FF] font-medium group-hover:text-white">
              {t(locale, next.titleKo, next.title)} →
            </div>
          </Link>
        )}
      </div>
    </div>
  );
}

function LocaleToggle() {
  const locale = useLocale();
  const setLocale = useSetLocale();
  return (
    <div className="flex items-center gap-1 rounded-md border border-white/[0.08] p-0.5 text-[11px]">
      <button
        type="button"
        onClick={() => setLocale("ko")}
        className={
          "px-2 py-1 rounded transition-colors " +
          (locale === "ko"
            ? "bg-white/[0.10] text-[#F0F0FF]"
            : "text-white/50 hover:text-white")
        }
      >
        KO
      </button>
      <button
        type="button"
        onClick={() => setLocale("en")}
        className={
          "px-2 py-1 rounded transition-colors " +
          (locale === "en"
            ? "bg-white/[0.10] text-[#F0F0FF]"
            : "text-white/50 hover:text-white")
        }
      >
        EN
      </button>
    </div>
  );
}

export function DocsShell({
  slug,
  title,
  titleKo,
  summary,
  summaryKo,
  children,
}: {
  slug: string;
  title: string;
  titleKo?: string;
  summary?: string;
  summaryKo?: string;
  children: ReactNode;
}) {
  const locale = useLocale();
  const displayTitle = titleKo ? t(locale, titleKo, title) : title;
  const displaySummary =
    summary && summaryKo ? t(locale, summaryKo, summary) : summary;
  const found = findPage(slug);
  const quadrant = found?.page.quadrant;
  const currentSection = DOCS_SITEMAP.find((s) =>
    s.pages.some((p) => p.slug === slug)
  );
  // Self-Improving Loop section carries the petri-blue signature; every other
  // section inherits the default amethyst artifact accent. --section-accent is
  // consumed by the eyebrow here and by the [data-doc-section] rules in docs.css.
  const sectionAccent =
    currentSection?.id === "04-self-improving"
      ? "var(--acc-si)"
      : "var(--acc-artifact)";
  return (
    <div
      className="min-h-screen bg-[#0B1628] text-[#F0F0FF]"
      data-doc-section={currentSection?.id}
      style={{ ["--section-accent"]: sectionAccent } as CSSProperties}
    >
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[#0B1628]/85 backdrop-blur">
        <div className="max-w-7xl mx-auto flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-6">
            <Link href="/portfolio" className="text-sm text-white/60 hover:text-white">
              ← /geode/portfolio
            </Link>
            <span className="text-sm font-display font-bold tracking-wide">
              {t(locale, "GEODE . 문서", "GEODE . Docs")}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <LocaleToggle />
            <a
              href="https://github.com/mangowhoiscloud/geode"
              className="text-xs text-white/50 hover:text-white"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto flex gap-8 px-6 py-10">
        <aside className="w-64 shrink-0 hidden md:block sticky top-20 self-start max-h-[calc(100vh-6rem)] overflow-y-auto pr-3">
          <Sidebar />
        </aside>

        <main className="flex-1 min-w-0 max-w-3xl">
          <div className="mb-10">
            {currentSection && (
              <div
                className="mb-2 text-[11px] font-mono uppercase tracking-[0.2em]"
                style={{ color: "var(--section-accent)" }}
              >
                {t(locale, currentSection.titleKo, currentSection.title)}
              </div>
            )}
            {quadrant && (
              <div className="mb-3">
                <QuadrantChip quadrant={quadrant} />
              </div>
            )}
            <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tight">
              {displayTitle}
            </h1>
            {displaySummary && (
              <p className="mt-2 text-white/60 text-base leading-relaxed">{displaySummary}</p>
            )}
          </div>
          <article className="docs-prose">{children}</article>
          <PrevNext slug={slug} />
        </main>
      </div>

      <footer className="border-t border-white/[0.06] mt-20">
        <div className="max-w-7xl mx-auto px-6 py-6 text-xs text-white/40 flex justify-between flex-wrap gap-2">
          <span>
            {t(
              locale,
              `GEODE v${GEODE_SOT.version} . 문서 동기화 ${GEODE_SOT.syncedAt}`,
              `GEODE v${GEODE_SOT.version} . Docs synced ${GEODE_SOT.syncedAt}`
            )}
          </span>
          <span>
            {t(
              locale,
              "출처: github.com/mangowhoiscloud/geode",
              "Source: github.com/mangowhoiscloud/geode"
            )}
          </span>
        </div>
      </footer>
    </div>
  );
}

/**
 * Helper for pages with bilingual content.
 *
 * Usage:
 *   <Bi ko={<>... 한국어 ...</>} en={<>... english ...</>} />
 */
export function Bi({ ko, en }: { ko: ReactNode; en: ReactNode }) {
  const locale = useLocale();
  return <>{locale === "ko" ? ko : en}</>;
}
