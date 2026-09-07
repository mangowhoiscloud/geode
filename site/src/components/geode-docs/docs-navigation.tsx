"use client";

import Link from "next/link";
import { useId, useRef, useState } from "react";
import { useLocale, t } from "@/components/geode/locale-context";
import { DOCS_SITEMAP, type DocPage } from "@/lib/geode-docs/sitemap";
import { DOCS_NAV_GROUPS, docChapters, docsPageHref, matchesDocPath, matchesDocQuery } from "@/lib/geode-docs/navigation";

export function DocsNavigation({
  slug,
  directory = false,
  onNavigate,
}: {
  slug: string;
  directory?: boolean;
  onNavigate?: () => void;
}) {
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const searching = query.trim().length > 0;
  const filteredSections = DOCS_SITEMAP.map((section) => ({
    ...section, pages: section.pages.filter((page) => matchesDocQuery(page, query, section)),
  })).filter((section) => section.pages.length > 0);
  const count = filteredSections.reduce((total, section) => total + section.pages.length, 0);
  const renderPages = (pages: DocPage[]) => (
    <ul>
      {pages.map((page) => (
        <li key={page.slug}>
          <Link
            href={docsPageHref(page.slug, locale)}
            onClick={onNavigate}
            aria-current={slug === page.slug ? "page" : matchesDocPath(page.slug, slug) ? "location" : undefined}
            className="docs-nav-link"
          >
            <span>{t(locale, page.titleKo, page.title)}</span>
            {directory && <span className="docs-nav-description">{t(locale, page.summaryKo ?? "", page.summary ?? "")}</span>}
          </Link>
        </li>
      ))}
    </ul>
  );

  return (
    <nav className={`docs-navigation${directory ? " docs-directory" : ""}`} aria-label={t(locale, directory ? "전체 문서 색인" : "문서 탐색", directory ? "All documentation" : "Documentation navigation")}>
      <div className="docs-find">
        <label htmlFor={inputId}>{t(locale, "문서 찾기", "Find a document")}</label>
        <div className="docs-find-control">
          <input
            id={inputId}
            ref={inputRef}
            type="search"
            name="docs-filter"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t(locale, "예: 인증, 도구, 비용", "e.g. auth, tools, cost")}
            aria-describedby={`${inputId}-hint`}
          />
          {searching && <button type="button" onClick={() => { setQuery(""); inputRef.current?.focus(); }}>{t(locale, "지우기", "Clear")}</button>}
        </div>
        <p id={`${inputId}-hint`}>{t(locale, "분류·제목·요약·경로에서 찾습니다.", "Matches topics, titles, summaries, and paths.")}</p>
        <p role="status" aria-live="polite" className="docs-find-status">
          {searching ? t(locale, `${count}개 문서`, `${count} documents`) : ""}
        </p>
      </div>

      {count === 0 && <p className="docs-find-empty">{t(locale, "일치하는 문서가 없습니다. 다른 단어를 입력하거나 검색어를 지우세요.", "No matching documents. Try another term or clear the filter.")}</p>}
      {DOCS_NAV_GROUPS.map((group) => {
        const sections = group.sectionIds.flatMap((id) => filteredSections.filter((section) => section.id === id));
        if (!sections.length) return null;
        return (
          <section key={group.id} className="docs-nav-group" aria-labelledby={`${inputId}-${group.id}`}>
            <h2 id={`${inputId}-${group.id}`}>{t(locale, group.titleKo, group.title)}</h2>
            {sections.map((section) => {
              const current = section.pages.some((page) => matchesDocPath(page.slug, slug));
              const chapters = docChapters(section);
              return (
                <details key={`${section.id}:${slug}:${query}`} open={searching || current} className="docs-nav-topic" data-topic={section.id} data-current={current || undefined}>
                  <summary>
                    <span className="docs-nav-count" aria-hidden="true">{section.pages.length}</span>
                    <span>{t(locale, section.titleKo, section.title)}</span>
                  </summary>
                  {chapters.length ? chapters.map((chapter) => (
                    <details key={chapter.id} className="docs-nav-chapter" open={searching || chapter.pages.some((page) => matchesDocPath(page.slug, slug))}>
                      <summary>
                        <span className="docs-nav-count" aria-hidden="true">{chapter.pages.length}</span>
                        <span>{t(locale, chapter.titleKo, chapter.title)}</span>
                      </summary>
                      {renderPages(chapter.pages)}
                    </details>
                  )) : renderPages(section.pages)}
                </details>
              );
            })}
          </section>
        );
      })}
    </nav>
  );
}
