"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { LocaleProvider, t, useLocale, useSetLocale } from "@/components/geode/locale-context";
import { attachReaderSwipe } from "@/lib/reader-swipe.mjs";
import editions from "@/data/geode/report-pages.json";
// The existing JEVDB presentation owns this shared reading workspace.
import "./jevdb-review.css";
import "./report-reader.css";

const assets = "/geode/research/geode-report/";
const pageId = (index: number) => `page-${String(index + 1).padStart(2, "0")}`;
const chapters = [
  [1, "리포트 안내", "Introduction"],
  [5, "문제와 좌표", "Problem and coordinates"],
  [11, "실행 코어", "Execution core"],
  [27, "상태와 메모리", "State and memory"],
  [36, "권한과 경계", "Authority and boundaries"],
  [44, "평가와 관측", "Evaluation and observation"],
  [57, "Crucible", "Crucible"],
  [78, "Self-Improving Loop", "Self-Improving Loop"],
] as const;

function ReportContent() {
  const locale = useLocale();
  const setLocale = useSetLocale();
  const edition = editions[locale];
  const [index, setIndex] = useState(0);
  const [overview, setOverview] = useState(false);
  const [focused, setFocused] = useState(false);
  const [text, setText] = useState(false);
  const [tocOpen, setTocOpen] = useState(false);
  const [query, setQuery] = useState("");
  const toc = useRef<HTMLDialogElement>(null);
  const sources = useRef<HTMLDialogElement>(null);
  const tocButton = useRef<HTMLButtonElement>(null);
  const sourceButton = useRef<HTMLButtonElement>(null);
  const canvas = useRef<HTMLAnchorElement>(null);
  const page = edition.pages[index];
  const image = `${assets}${locale}/${page.image}`;

  const select = useCallback((next: number) => {
    if (!Number.isInteger(next) || next < 0 || next >= 92) return;
    setIndex(next);
    setOverview(false);
    setText(false);
    window.history.pushState(window.history.state, "", `#${pageId(next)}`);
    toc.current?.close();
    window.scrollTo({ top: 0, behavior: "instant" });
  }, []);

  useEffect(() => {
    if (!overview && canvas.current) return attachReaderSwipe(canvas.current, direction => select(index + direction));
  }, [index, locale, overview, select]);

  useEffect(() => {
    const readHash = () => {
      if (window.location.hash === "#readerSources") {
        toc.current?.close();
        if (!sources.current?.open) sources.current?.showModal();
        return;
      }
      if (sources.current?.open) sources.current.close();
      const match = /^#page-(\d{2})$/.exec(window.location.hash);
      if (!match && window.location.hash) return;
      const next = match ? Number(match[1]) - 1 : 0;
      if (next >= 0 && next < 92) { setIndex(next); setOverview(false); setText(false); }
    };
    const timer = window.setTimeout(readHash, 0);
    window.addEventListener("hashchange", readHash);
    window.addEventListener("popstate", readHash);
    return () => { window.clearTimeout(timer); window.removeEventListener("hashchange", readHash); window.removeEventListener("popstate", readHash); };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (overview || sources.current?.open || toc.current?.open || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof Element && event.target.closest("a,button,input,textarea,select,[contenteditable]")) return;
      const next = { ArrowLeft: index - 1, ArrowRight: index + 1, PageUp: index - 1, PageDown: index + 1, Home: 0, End: 91 }[event.key];
      if (next !== undefined) { event.preventDefault(); select(next); }
    };
    const onResize = () => { if (window.matchMedia("(min-width: 1024px)").matches) toc.current?.close(); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("resize", onResize); };
  }, [index, overview, select]);

  const contents = () => <>
    <nav className="report-chapters" aria-label={t(locale, "리포트 구성", "Report chapters")}>
      {chapters.map(([number, ko, en], i) => <a key={number} href={`#${pageId(number - 1)}`} aria-current={index + 1 >= number && index + 1 < (chapters[i + 1]?.[0] ?? 93) ? "location" : undefined} onClick={event => { event.preventDefault(); select(number - 1); }}><span>{String(number).padStart(2, "0")}</span>{t(locale, ko, en)}</a>)}
    </nav>
    <label className="report-search">{t(locale, "페이지 찾기", "Find a page")}<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={t(locale, "제목 또는 본문", "Title or text")} /></label>
    <nav className="jevdb-scene-list report-page-list" aria-label={t(locale, "전체 페이지", "All pages")}>
      {edition.pages.filter(item => !query.trim() || item.text.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(item => <a key={item.number} href={`#${pageId(item.number - 1)}`} aria-current={item.number === index + 1 ? "page" : undefined} onClick={event => { event.preventDefault(); select(item.number - 1); }}><span>{String(item.number).padStart(2, "0")}</span><span>{item.title}</span></a>)}
      {query.trim() && !edition.pages.some(item => item.text.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && <p className="report-no-results">{t(locale, "일치하는 페이지가 없습니다.", "No matching pages.")}</p>}
    </nav>
  </>;

  return <div className={`jevdb-reader geode-report-reader${focused ? " report-focused" : ""}`} lang={locale}>
    <a className="jevdb-skip" href="#report-content">{t(locale, "본문으로 이동", "Skip to content")}</a>
    <header className="jevdb-header">
      <div className="jevdb-identity"><Link className="jevdb-home" href={`/research/${locale === "en" ? "?lang=en" : ""}`}>GEODE / Research</Link><div><h1>{t(locale, "GEODE 기술 리포트", "GEODE technical report")}</h1><p>{t(locale, "공개 기술 리포트 · 92쪽", "Published technical report · 92 pages")}</p></div></div>
      <div className="jevdb-actions"><div className="jevdb-languages" role="group" aria-label={t(locale, "언어", "Language")}><button type="button" aria-pressed={locale === "ko"} onClick={() => setLocale("ko")}>한국어</button><button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>English</button></div><a className="jevdb-download" href={edition.pdf} download>{t(locale, "PDF 다운로드", "Download PDF")}</a></div>
    </header>
    <div className={`jevdb-workspace${focused ? " jevdb-contents-hidden" : ""}`}>
      <aside className="jevdb-toc report-toc" aria-label={t(locale, "목차", "Contents")}><h2>{t(locale, "목차", "Contents")}</h2>{contents()}</aside>
      <main id="report-content" className="jevdb-content" tabIndex={-1}>
        <nav className="jevdb-toolbar" aria-label={t(locale, "페이지 탐색", "Page navigation")}>
          <div className="jevdb-tools"><button ref={tocButton} type="button" className="jevdb-contents-mobile" aria-haspopup="dialog" aria-expanded={tocOpen} aria-controls="report-contents" onClick={() => { toc.current?.showModal(); setTocOpen(true); }}>{t(locale, "목차", "Contents")}</button><button className="report-focus-button" type="button" aria-pressed={focused} onClick={() => setFocused(!focused)}>{t(locale, focused ? "목차와 함께" : "집중 보기", focused ? "Show contents" : "Focus view")}</button><button type="button" aria-pressed={overview} onClick={() => setOverview(!overview)}>{t(locale, "전체 페이지", "All pages")}</button></div>
          <div className="jevdb-pager"><button type="button" disabled={index === 0} onClick={() => select(index - 1)}>{t(locale, "이전", "Previous")}</button><span className="jevdb-counter" aria-live="polite">{index + 1} / 92</span><button type="button" disabled={index === 91} onClick={() => select(index + 1)}>{t(locale, "다음", "Next")}</button></div>
        </nav>
        {overview ? <div className="jevdb-overview" aria-label={t(locale, "전체 페이지", "All pages")}>{edition.pages.map(item => <button key={item.number} type="button" onClick={() => select(item.number - 1)} aria-label={`${item.number}. ${item.title}`}><Image src={`${assets}${locale}/${item.image}`} alt="" width={1600} height={900} /><span>{String(item.number).padStart(2, "0")} · {item.title}</span></button>)}</div> : <article className="report-page" data-page={index + 1}>
          <a ref={canvas} className="jevdb-canvas" href={image} target="_blank" rel="noopener noreferrer" aria-label={t(locale, `${index + 1}쪽 원본 크게 보기`, `Open page ${index + 1} at full size`)}><Image key={image} src={image} alt={page.title} width={1600} height={900} priority={index === 0} /></a>
          <div className="jevdb-caption-row"><span>{t(locale, "페이지별 도표·출처·측정 조건", "Page figures, sources, and measurement conditions")}</span><a href={image} target="_blank" rel="noopener noreferrer">{t(locale, "크게 보기 ↗", "Full size ↗")}</a></div>
          <section className="report-text"><button type="button" className="jevdb-transcript-button" aria-expanded={text} aria-controls="report-page-text" onClick={() => setText(!text)}>{t(locale, "본문 읽기", "Read page text")} {text ? "−" : "+"}</button><div id="report-page-text" hidden={!text}><p>{t(locale, "PDF에서 자동 추출한 텍스트입니다. 배치와 도표의 정본은 위 페이지와 PDF입니다.", "Text extracted automatically from the PDF. The page image and PDF are authoritative for layout and figures.")}</p><pre>{page.text}</pre></div></section>
        </article>}
        <footer className="jevdb-footer"><p>{t(locale, "공개 92쪽 판본입니다. 각 페이지의 버전·측정 시점·비교 조건을 기준으로 읽습니다.", "Published 92-page edition. Read each page against its recorded version, measurement date, and comparison conditions.")}</p><button ref={sourceButton} type="button" aria-haspopup="dialog" aria-controls="report-sources" onClick={() => { window.history.pushState(window.history.state, "", "#readerSources"); sources.current?.showModal(); }}>{t(locale, "원본과 출처", "Originals and sources")}</button></footer>
      </main>
    </div>
    <dialog ref={toc} id="report-contents" className="jevdb-dialog jevdb-toc-dialog" aria-labelledby="report-contents-title" onClose={() => { setTocOpen(false); tocButton.current?.focus(); }} onClick={event => { const r = event.currentTarget.getBoundingClientRect(); if (event.target === event.currentTarget && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) toc.current?.close(); }}><div className="jevdb-dialog-heading"><h2 id="report-contents-title">{t(locale, "목차", "Contents")}</h2><button type="button" onClick={() => toc.current?.close()}>{t(locale, "닫기", "Close")}</button></div>{contents()}</dialog>
    <dialog ref={sources} id="report-sources" className="jevdb-dialog jevdb-sources" aria-labelledby="report-sources-title" onClose={() => { if (window.location.hash === "#readerSources") window.history.replaceState(window.history.state, "", `#${pageId(index)}`); sourceButton.current?.focus(); }} onClick={event => { const r = event.currentTarget.getBoundingClientRect(); if (event.target === event.currentTarget && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) sources.current?.close(); }}>
      <div className="jevdb-dialog-heading"><h2 id="report-sources-title">{t(locale, "원본과 출처", "Originals and sources")}</h2><button type="button" onClick={() => sources.current?.close()}>{t(locale, "닫기", "Close")}</button></div>
      <div className="jevdb-sources-body"><p>{t(locale, "공개 PDF의 페이지 이미지와 추출 텍스트를 제공합니다. 한·영 PDF와 이미지의 SHA-256은 아래 manifest에서 확인할 수 있습니다.", "Read page images and extracted text from the published PDFs. The manifest below records SHA-256 hashes for both PDF editions and their page images.")}</p><section><h3>{t(locale, "다운로드와 원본 식별", "Downloads and identity")}</h3><ul><li><a href="/geode/report.pdf" download><span>KO</span><span>{t(locale, "한국어 PDF", "Korean PDF")}</span></a></li><li><a href="/geode/report-en.pdf" download><span>EN</span><span>{t(locale, "영어 PDF", "English PDF")}</span></a></li><li><a href={`${assets}manifest.json`}><span>HASH</span><span>{t(locale, "PDF와 페이지 이미지 SHA-256", "PDF and page image SHA-256")}</span></a></li></ul><p>{t(locale, "현재 언어의 PDF", "Current-language PDF")} SHA-256</p><code className="report-hash">{edition.sha256}</code></section><section><h3>{t(locale, "읽는 범위", "Reading scope")}</h3><p>{t(locale, "목차는 원본 3쪽의 구성을 따릅니다. 상세 측정 조건과 인용은 해당 페이지를 확인하세요. Jev Decision Offloading과 JEVDB 논문 리뷰는 별도 자료입니다.", "Chapters follow the contents on page 3. Measurement conditions and citations remain on their original pages. Jev Decision Offloading and the JEVDB paper review are separate publications.")}</p><ul><li><a href={`/geode/research/jev-system1-offloading/?lang=${locale}`}><span>JEV</span><span>Jev Decision Offloading</span></a></li><li><Link href={`/research/jevdb/?lang=${locale}`}><span>JEVDB</span><span>{t(locale, "외부 논문 리뷰", "External paper review")}</span></Link></li><li><Link href={`/docs?lang=${locale}`}><span>DOCS</span><span>{t(locale, "현재 구현 문서", "Current implementation docs")}</span></Link></li></ul></section></div>
    </dialog>
  </div>;
}

export function ReportReader() {
  return <LocaleProvider><ReportContent /></LocaleProvider>;
}
