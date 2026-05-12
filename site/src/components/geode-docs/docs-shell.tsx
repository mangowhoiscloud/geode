"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode } from "react";
import { useLocale, useSetLocale, t } from "@/components/geode/locale-context";
import { DOCS_SITEMAP, adjacentPages } from "@/lib/geode-docs/sitemap";

const DOCS_BASE = "/docs";

function pageHref(slug: string): string {
  return slug ? `${DOCS_BASE}/${slug}` : DOCS_BASE;
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
      <div className="mt-2 space-y-6">
        {DOCS_SITEMAP.map((section) => (
          <div key={section.id}>
            <div className="px-3 text-[10px] uppercase tracking-[0.18em] text-white/40 font-semibold mb-2">
              {t(locale, section.titleKo, section.title)}
            </div>
            <ul className="space-y-0.5">
              {section.pages.map((page) => {
                const href = pageHref(page.slug);
                const active = pathname === href || pathname === `${href}/`;
                return (
                  <li key={page.slug || "_index"}>
                    <Link
                      href={href}
                      className={
                        "block px-3 py-1.5 rounded text-[13px] transition-colors " +
                        (active
                          ? "bg-white/[0.06] text-[#F0F0FF]"
                          : "text-white/60 hover:text-[#F0F0FF] hover:bg-white/[0.03]")
                      }
                    >
                      {t(locale, page.titleKo, page.title)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
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
            className="block group rounded-lg border border-white/[0.06] p-4 hover:border-white/[0.12] transition-colors"
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
            className="block group rounded-lg border border-white/[0.06] p-4 hover:border-white/[0.12] transition-colors"
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
  return (
    <div className="min-h-screen bg-[#0B1628] text-[#F0F0FF]">
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[#0B1628]/85 backdrop-blur">
        <div className="max-w-7xl mx-auto flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-6">
            <Link href="/portfolio" className="text-sm text-white/60 hover:text-white">
              ← /geode
            </Link>
            <span className="text-sm font-display font-bold tracking-wide">
              {t(locale, "GEODE · 문서", "GEODE · Docs")}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <LocaleToggle />
            <a
              href="https://github.com/mangowhoiscloud/portfolio"
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
        <div className="max-w-7xl mx-auto px-6 py-6 text-xs text-white/40 flex justify-between">
          <span>
            {t(locale, "GEODE v0.64.0 · 문서 생성 2026-05-01", "GEODE v0.64.0 · Docs generated 2026-05-01")}
          </span>
          <span>{t(locale, "출처: github.com/mangowhoiscloud/portfolio", "Source: github.com/mangowhoiscloud/portfolio")}</span>
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
