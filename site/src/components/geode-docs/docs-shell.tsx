"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, type CSSProperties } from "react";
import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { useLocale, useSetLocale, t } from "@/components/geode/locale-context";
import { DOCS_SITEMAP, adjacentPages, findPage, QUADRANT_META, type DocQuadrant } from "@/lib/geode-docs/sitemap";
import { GEODE_SOT } from "@/data/geode/sot";
import { galmuri } from "@/fonts/galmuri";
import { serifDisplay } from "@/fonts/serif";

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
        className="block px-3 py-2 text-[var(--acc-artifact)] font-display font-bold tracking-wide"
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
              className="px-3 text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)] font-semibold mb-2"
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
                          ? "bg-[var(--paper-2)] text-[var(--ink)]"
                          : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--paper-2)]")
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
                        <span className="text-[9px] text-[var(--ink-3)]">↗</span>
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
    <div className="mt-16 grid grid-cols-2 gap-4 border-t border-[var(--rule-soft)] pt-8">
      <div>
        {prev && (
          <Link
            href={pageHref(prev.slug)}
            className="docs-card block group rounded-lg border border-[var(--rule-soft)] p-4 hover:border-[var(--rule)] transition-colors"
          >
            <div className="text-[10px] uppercase tracking-wider text-[var(--ink-3)] mb-1">
              {t(locale, "이전", "Previous")}
            </div>
            <div className="text-[var(--ink)] font-medium group-hover:text-[var(--acc-soft)]">
              {t(locale, prev.titleKo, prev.title)}
            </div>
          </Link>
        )}
      </div>
      <div className="text-right">
        {next && (
          <Link
            href={pageHref(next.slug)}
            className="docs-card block group rounded-lg border border-[var(--rule-soft)] p-4 hover:border-[var(--rule)] transition-colors"
          >
            <div className="text-[10px] uppercase tracking-wider text-[var(--ink-3)] mb-1">
              {t(locale, "다음", "Next")}
            </div>
            <div className="text-[var(--ink)] font-medium group-hover:text-[var(--acc-soft)]">
              {t(locale, next.titleKo, next.title)}
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
    <div className="flex items-center gap-1 rounded-md border border-[var(--rule)] p-0.5 text-[11px]">
      <button
        type="button"
        onClick={() => setLocale("ko")}
        className={
          "px-2 py-1 rounded transition-colors " +
          (locale === "ko"
            ? "bg-[var(--paper-2)] text-[var(--ink)]"
            : "text-[var(--ink-3)] hover:text-[var(--ink)]")
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
            ? "bg-[var(--paper-2)] text-[var(--ink)]"
            : "text-[var(--ink-3)] hover:text-[var(--ink)]")
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
      className="min-h-screen bg-[var(--paper)] text-[var(--ink)]"
      data-doc-section={currentSection?.id}
      style={{ ["--section-accent"]: sectionAccent } as CSSProperties}
    >
      <header className="sticky top-0 z-30 border-b border-[var(--rule-soft)] bg-[color-mix(in_srgb,var(--paper)_85%,transparent)] backdrop-blur">
        <div className="max-w-7xl mx-auto flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-6">
            <span className={`${galmuri.variable} flex items-center gap-2.5 text-sm font-bold`}>
              {/* Docs brand carries the CLI mascot: same GEODI_PIXELS sprite, static (no blink outside the portfolio hero budget). */}
              <GeodiSprite scale={2} />
              <span style={{ fontFamily: "var(--font-pixel), var(--font-display), sans-serif" }}>
                {t(locale, "GEODE . 문서", "GEODE . Docs")}
              </span>
            </span>
          </div>
          <div className="flex items-center gap-4">
            <LocaleToggle />
            <a
              href="https://github.com/mangowhoiscloud/geode"
              className="text-xs text-[var(--ink-3)] hover:text-[var(--ink)]"
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
            <h1
              className={`${serifDisplay.variable} font-serif-docs text-3xl font-black md:text-4xl`}
            >
              {displayTitle}
            </h1>
            {displaySummary && (
              <p className="mt-2 text-[var(--ink-2)] text-base leading-relaxed">{displaySummary}</p>
            )}
          </div>
          <article className={`${serifDisplay.variable} docs-prose`}>{children}</article>
          <PrevNext slug={slug} />
        </main>
      </div>

      <footer className="border-t border-[var(--rule-soft)] mt-20">
        <div className="max-w-7xl mx-auto px-6 py-6 text-xs text-[var(--ink-3)] flex justify-between flex-wrap gap-2">
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
