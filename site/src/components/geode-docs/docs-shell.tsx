"use client";

import Link from "next/link";
import { useLayoutEffect, useRef, type ReactNode, type CSSProperties } from "react";
import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { useLocale, useSetLocale, t } from "@/components/geode/locale-context";
import { DocsNavigation } from "@/components/geode-docs/docs-navigation";
import { DOCS_SITEMAP, adjacentPages, findPage, QUADRANT_META } from "@/lib/geode-docs/sitemap";
import { docsPageHref, matchesDocPath } from "@/lib/geode-docs/navigation";
import { GEODE_SOT } from "@/data/geode/sot";
import { galmuri } from "@/fonts/galmuri";

const SIDEBAR_SCROLL_STORAGE_KEY = "geode:docs-sidebar-scroll-top";
const DESKTOP_SIDEBAR_QUERY = "(min-width: 768px)";

let lastSidebarScrollTop = 0;

function useRememberedSidebarScroll(slug: string) {
  const sidebarRef = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const sidebar = sidebarRef.current;
    if (!sidebar) return;

    const desktop = window.matchMedia(DESKTOP_SIDEBAR_QUERY);
    const remember = () => {
      if (!desktop.matches) return;

      lastSidebarScrollTop = sidebar.scrollTop;
      try {
        window.sessionStorage.setItem(
          SIDEBAR_SCROLL_STORAGE_KEY,
          String(lastSidebarScrollTop)
        );
      } catch {
        // Route-to-route restoration still works through the module fallback.
      }
    };
    const restore = () => {
      if (!desktop.matches) return;

      let scrollTop = lastSidebarScrollTop;
      try {
        const stored = window.sessionStorage.getItem(SIDEBAR_SCROLL_STORAGE_KEY);
        if (stored !== null) {
          const parsed = Number(stored);
          if (Number.isFinite(parsed) && parsed >= 0) scrollTop = parsed;
        }
      } catch {
        // Keep the in-memory fallback when storage is unavailable.
      }
      sidebar.scrollTop = scrollTop;
      const current = sidebar.querySelector<HTMLElement>("[aria-current]");
      if (current) {
        const bounds = sidebar.getBoundingClientRect();
        const link = current.getBoundingClientRect();
        const visibleTop = bounds.top + (sidebar.querySelector(".docs-find")?.getBoundingClientRect().height ?? 0) + 12;
        if (link.top < visibleTop || link.bottom > bounds.bottom) {
          sidebar.scrollTop += link.top - visibleTop;
        }
      }
    };

    restore();
    sidebar.addEventListener("scroll", remember, { passive: true });
    desktop.addEventListener("change", restore);

    return () => {
      sidebar.removeEventListener("scroll", remember);
      desktop.removeEventListener("change", restore);
      // A display:none aside reports scrollTop=0. Do not erase the last
      // desktop position when navigating through docs on a mobile viewport.
      remember();
    };
  }, [slug]);

  return sidebarRef;
}

function PrevNext({ slug }: { slug: string }) {
  const { prev, next } = adjacentPages(slug);
  const locale = useLocale();
  if (!prev && !next) return null;
  return (
    <nav className="docs-pagination" aria-label={t(locale, "이전과 다음 문서", "Previous and next documents")}>
      <div>
        {prev && (
          <Link
            href={docsPageHref(prev.slug, locale)}
            className="docs-page-link"
          >
            <span>
              {t(locale, "이전", "Previous")}
            </span>
            <strong>
              {t(locale, prev.titleKo, prev.title)}
            </strong>
          </Link>
        )}
      </div>
      <div className="text-right">
        {next && (
          <Link
            href={docsPageHref(next.slug, locale)}
            className="docs-page-link"
          >
            <span>
              {t(locale, "다음", "Next")}
            </span>
            <strong>
              {t(locale, next.titleKo, next.title)}
            </strong>
          </Link>
        )}
      </div>
    </nav>
  );
}

function LocaleToggle() {
  const locale = useLocale();
  const setLocale = useSetLocale();
  return (
    <div className="docs-locale" role="group" aria-label={t(locale, "문서 언어", "Document language")}>
      <button
        type="button"
        onClick={() => setLocale("ko")}
        aria-pressed={locale === "ko"}
        aria-label="한국어"
      >
        KO
      </button>
      <button
        type="button"
        onClick={() => setLocale("en")}
        aria-pressed={locale === "en"}
        aria-label="English"
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
  wide = false,
  children,
}: {
  slug: string;
  title: string;
  titleKo?: string;
  summary?: string;
  summaryKo?: string;
  wide?: boolean;
  children: ReactNode;
}) {
  const locale = useLocale();
  const sidebarRef = useRememberedSidebarScroll(slug);
  const mobileNavRef = useRef<HTMLDetailsElement>(null);
  const closeMobileNav = () => {
    const menu = mobileNavRef.current;
    if (!menu) return;
    menu.open = false;
    menu.querySelector("summary")?.focus();
  };
  const displayTitle = titleKo ? t(locale, titleKo, title) : title;
  const displaySummary =
    summary && summaryKo ? t(locale, summaryKo, summary) : summary;
  const found = findPage(slug);
  const quadrant = found?.page.quadrant;
  const currentSection = DOCS_SITEMAP.find((s) =>
    s.pages.some((p) => matchesDocPath(p.slug, slug))
  );
  const currentPage = currentSection?.pages.find((page) => matchesDocPath(page.slug, slug));
  const currentChapter = currentSection?.chapters?.find((chapter) => chapter.id === currentPage?.chapter);
  // Experimental Loop section carries the petri-blue signature; every other
  // section inherits the rose identity accent. Content retains its topic scope.
  const sectionAccent =
    currentSection?.id === "04-self-improving"
      ? "var(--acc-si)"
      : "var(--acc-artifact)";
  const canonical = `https://mangowhoiscloud.github.io/geode/docs${slug ? `/${slug}` : ""}/`;
  return (
    <>
      <link rel="canonical" href={canonical} />
      <div
        className="geode-docs"
        lang={locale}
        data-doc-section={currentSection?.id}
        style={{ ["--section-accent"]: sectionAccent } as CSSProperties}
      >
      <a href="#docs-main" className="docs-skip">{t(locale, "본문으로 이동", "Skip to content")}</a>
      <header className="docs-header">
        <div className="docs-header-inner">
            <Link href={`/${locale === "ko" ? "?lang=ko" : ""}`} className={`${galmuri.variable} docs-brand`} aria-label={t(locale, "GEODE 홈", "GEODE home")}>
              {/* Docs brand carries the CLI mascot: same GEODI_PIXELS sprite, static (no blink outside the portfolio hero budget). */}
              <GeodiSprite scale={2} />
              <span style={{ fontFamily: "var(--font-pixel), var(--font-display), sans-serif" }}>
                GEODE
              </span>
            </Link>
          <div className="docs-header-actions">
            <Link href={docsPageHref("", locale)} className="docs-home-link">{t(locale, "문서", "Docs")}</Link>
            <LocaleToggle />
            <a
              href="https://github.com/mangowhoiscloud/geode"
              className="docs-github-link"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>
          </div>
        </div>
      </header>

      <details key={slug} ref={mobileNavRef} className="docs-mobile-nav" onKeyDown={(event) => {
        if (event.key === "Escape" && mobileNavRef.current?.open) closeMobileNav();
      }}>
        <summary>{t(locale, "문서 탐색", "Browse docs")}<span>{displayTitle}</span></summary>
        <div className="docs-mobile-nav-content"><DocsNavigation slug={slug} onNavigate={closeMobileNav} /></div>
      </details>

      <div className="docs-layout">
        <aside
          ref={sidebarRef}
          className="docs-sidebar"
        >
          <DocsNavigation slug={slug} />
        </aside>

        <main id="docs-main" tabIndex={-1} className={`docs-main${wide ? " docs-main-wide" : ""}`}>
          <div className="docs-page-header">
            <div className="docs-context">
            {currentSection && (
              <span style={{ color: "var(--section-accent)" }}>
                {t(locale, currentSection.titleKo, currentSection.title)}
              </span>
            )}
            {currentChapter && <span>{t(locale, currentChapter.titleKo, currentChapter.title)}</span>}
            {quadrant && (
              <span>{t(locale, QUADRANT_META[quadrant].labelKo, QUADRANT_META[quadrant].label)}</span>
            )}
            </div>
            <h1>
              {displayTitle}
            </h1>
            {displaySummary && (
              <p>{displaySummary}</p>
            )}
          </div>
          <article className="docs-prose">{children}</article>
          <PrevNext slug={slug} />
        </main>
      </div>

      <footer className="docs-footer">
        <div>
          <span>
            {t(
              locale,
              `GEODE v${GEODE_SOT.version} . 문서 동기화 ${GEODE_SOT.syncedAt}`,
              `GEODE v${GEODE_SOT.version} . Docs synced ${GEODE_SOT.syncedAt}`
            )}
          </span>
          <a href="https://github.com/mangowhoiscloud/geode">
            {t(
              locale,
              "출처: github.com/mangowhoiscloud/geode",
              "Source: github.com/mangowhoiscloud/geode"
            )}
          </a>
        </div>
      </footer>
      </div>
    </>
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
