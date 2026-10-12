"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { LocaleProvider, t, useLocale, useSetLocale } from "@/components/geode/locale-context";
import scenes from "@/data/geode/jevdb-slides.json";
import "./jevdb-review.css";

const paper = "https://arxiv.org/abs/2610.02046v1";
const slides = "/geode/research/jevdb-seminar-v25.pptx";
const assets = "/geode/research/jevdb-slides-v25/";
const evidence = "https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/3bcf4044eb5c2411dd48122d672aef72a83fb30e/reports/e2e-validation/jev-v3-20260927";
const sceneId = (index: number) => `slide-${String(index + 1).padStart(2, "0")}`;

function ReviewContent() {
  const locale = useLocale();
  const setLocale = useSetLocale();
  const [index, setIndex] = useState(0);
  const [overview, setOverview] = useState(false);
  const [contents, setContents] = useState(true);
  const [tocOpen, setTocOpen] = useState(false);
  const [transcript, setTranscript] = useState(false);
  const toc = useRef<HTMLDialogElement>(null);
  const sources = useRef<HTMLDialogElement>(null);
  const sourceButton = useRef<HTMLButtonElement>(null);
  const scene = scenes[index];
  const title = locale === "ko" ? scene.titleKo : scene.title;

  const selectScene = useCallback((next: number) => {
    if (next < 0 || next >= scenes.length) return;
    setIndex(next);
    setOverview(false);
    setTranscript(false);
    window.history.pushState(window.history.state, "", `#${sceneId(next)}`);
    toc.current?.close();
    window.scrollTo({ top: 0, behavior: "instant" });
  }, []);

  useEffect(() => {
    const readHash = () => {
      if (window.location.hash === "#readerSources") {
        toc.current?.close();
        if (!sources.current?.open) sources.current?.showModal();
        return;
      }
      if (sources.current?.open) sources.current.close();
      const match = /^#slide-(\d{2})$/.exec(window.location.hash);
      if (!match && window.location.hash) return;
      const next = match ? Number(match[1]) - 1 : 0;
      if (next >= 0 && next < scenes.length) {
        setIndex(next);
        setOverview(false);
        setTranscript(false);
      }
    };
    const timer = window.setTimeout(readHash, 0);
    window.addEventListener("hashchange", readHash);
    window.addEventListener("popstate", readHash);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("hashchange", readHash);
      window.removeEventListener("popstate", readHash);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (overview || toc.current?.open || sources.current?.open || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof Element && event.target.closest("a, button, input, textarea, select, [contenteditable]")) return;
      const target = { ArrowLeft: index - 1, ArrowRight: index + 1, PageUp: index - 1, PageDown: index + 1, Home: 0, End: scenes.length - 1 }[event.key];
      if (target !== undefined) {
        event.preventDefault();
        selectScene(target);
      }
    };
    const onResize = () => {
      if (window.matchMedia("(min-width: 1024px)").matches) toc.current?.close();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [index, overview, selectScene]);

  const sceneList = () => (
    <nav className="jevdb-scene-list" aria-label={t(locale, "장면", "Scenes")}>
      {scenes.map((item, i) => <a key={item.number} href={`#${sceneId(i)}`} aria-current={i === index ? "page" : undefined} onClick={event => { event.preventDefault(); selectScene(i); }}>
        <span>{String(item.number).padStart(2, "0")}</span>{" "}<span>{locale === "ko" ? item.titleKo : item.title}</span>
      </a>)}
    </nav>
  );

  return (
    <div className="jevdb-reader" lang={locale}>
      <a className="jevdb-skip" href="#review-content">{t(locale, "본문으로 이동", "Skip to content")}</a>
      <header className="jevdb-header">
        <div className="jevdb-identity">
          <Link className="jevdb-home" href={`/research/?lang=${locale}`}>GEODE / Research</Link>
          <div><h1>JEVDB: Prune First, Decide Fast</h1><p>{t(locale, "논문 리뷰 · 류지환 · v25", "Paper review · Jihwan Ryu · v25")}</p></div>
        </div>
        <div className="jevdb-actions">
          <div className="jevdb-languages" role="group" aria-label={t(locale, "언어", "Language")}>
            <button type="button" aria-pressed={locale === "ko"} onClick={() => setLocale("ko")}>한국어</button>
            <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>English</button>
          </div>
          <a className="jevdb-video" href="https://youtu.be/KKiEyGjGUIo">{t(locale, "발표 영상 ↗", "Watch the talk ↗")}</a>
          <a className="jevdb-download" href={slides} download>{t(locale, "PPT 다운로드", "Download PPT")}</a>
        </div>
      </header>

      <div className={`jevdb-workspace${contents ? "" : " jevdb-contents-hidden"}`}>
        <aside id="reader-scene-list" className="jevdb-toc" aria-label={t(locale, "장면 목록", "Scene list")}>
          <h2>{t(locale, "장면 목록", "Scenes")} <small>{scenes.length}</small></h2>
          {sceneList()}
        </aside>
        <main id="review-content" className="jevdb-content" tabIndex={-1}>
          <nav className="jevdb-toolbar" aria-label={t(locale, "발표 탐색", "Presentation navigation")}>
            <div className="jevdb-tools">
              <button type="button" className="jevdb-contents-desktop" aria-expanded={contents} aria-controls="reader-scene-list" onClick={() => setContents(!contents)}>{t(locale, "장면 목록", "Contents")}</button>
              <button type="button" className="jevdb-contents-mobile" aria-haspopup="dialog" aria-expanded={tocOpen} aria-controls="reader-contents" onClick={() => { toc.current?.showModal(); setTocOpen(true); }}>{t(locale, "장면 목록", "Contents")}</button>
              <button type="button" aria-pressed={overview} onClick={() => setOverview(!overview)}>{t(locale, "전체 장면", "All scenes")}</button>
              <span className="jevdb-static-label">{t(locale, "영문 원본 슬라이드", "Original English slides")}</span>
            </div>
            <div className="jevdb-pager">
              <button type="button" disabled={index === 0} onClick={() => selectScene(index - 1)}>{t(locale, "이전", "Previous")}</button>
              <span className="jevdb-counter" aria-live="polite">{t(locale, "장면", "Scene")} {index + 1} / {scenes.length} · {t(locale, "단계", "Build")} 1 / 1</span>
              <button type="button" disabled={index === scenes.length - 1} onClick={() => selectScene(index + 1)}>{t(locale, "다음", "Next")}</button>
            </div>
          </nav>

          {overview ? <div className="jevdb-overview" aria-label={t(locale, "전체 장면", "All scenes")}>
            {scenes.map((item, i) => <button key={item.number} type="button" onClick={() => selectScene(i)} aria-label={`${item.number}. ${locale === "ko" ? item.titleKo : item.title}`}>
              <Image src={`${assets}${item.image}`} alt="" width={1585} height={891} />
              <span>{String(item.number).padStart(2, "0")} · {locale === "ko" ? item.titleKo : item.title}</span>
            </button>)}
          </div> : <article className="jevdb-scene" aria-label={title} data-scene={index + 1}>
            <a className="jevdb-canvas" href={`${assets}${scene.image}`} target="_blank" rel="noopener noreferrer" aria-label={t(locale, `${title}: 원본 이미지 크게 보기`, `${title}: open full-size slide`)}>
              <Image src={`${assets}${scene.image}`} alt={scene.title} width={1585} height={891} priority={index === 0} />
            </a>
            <div className="jevdb-caption-row"><span>{t(locale, "v25 · 원본 슬라이드의 도표·출처·조건을 보존합니다.", "v25 · Original figures, sources, and conditions are preserved.")}</span><a href={`${assets}${scene.image}`} target="_blank" rel="noopener noreferrer">{t(locale, "크게 보기 ↗", "Full size ↗")}</a></div>
            <section className="jevdb-reading-note" aria-labelledby="scene-title">
              <div className="jevdb-note-heading"><h2 id="scene-title">{title}</h2><span>{String(scene.number).padStart(2, "0")} / 19</span></div>
              <p>{locale === "ko" ? scene.noteKo : scene.noteEn}</p>
              <p className="jevdb-scope">{locale === "ko" ? scene.scopeKo : scene.scopeEn}</p>
              <p className="jevdb-citation" lang="en">{scene.source}</p>
              {index === 17 && <a className="jevdb-related" href={`/geode/research/jev-system1-offloading/?lang=${locale}#v3-e2e-injected`}>{t(locale, "별도 Decision Offloading 연구 보고서 ↗", "Separate Decision Offloading study ↗")}</a>}
              <button className="jevdb-transcript-button" type="button" aria-expanded={transcript} aria-controls="slide-transcript" onClick={() => setTranscript(!transcript)}>{t(locale, "슬라이드 텍스트", "Slide text")} {transcript ? "−" : "+"}</button>
              <div id="slide-transcript" className="jevdb-transcript" lang="en" hidden={!transcript}>{scene.transcript.map((line, i) => <p key={i}>{line}</p>)}</div>
            </section>
          </article>}

          <footer className="jevdb-footer">
            <p>{t(locale, "원 논문 주장, 발표자 예시, 별도 GEODE 실험을 구분합니다. 언어 선택은 목차와 해설에 적용되며, 슬라이드와 PPT는 영문 v25 원본입니다.", "Paper claims, presenter examples, and the separate GEODE experiment remain distinct. Language selection changes navigation and notes; the slides and PPT preserve the original English v25 edition.")}</p>
            <button ref={sourceButton} type="button" aria-haspopup="dialog" aria-controls="reader-sources" onClick={() => {
              window.history.pushState(window.history.state, "", "#readerSources");
              sources.current?.showModal();
            }}>{t(locale, "자료와 출처", "Materials and sources")}</button>
          </footer>
        </main>
      </div>

      <dialog id="reader-contents" ref={toc} className="jevdb-dialog jevdb-toc-dialog" aria-labelledby="toc-heading" onClose={() => setTocOpen(false)} onClick={event => { if (event.target === event.currentTarget) event.currentTarget.close(); }}>
        <div className="jevdb-dialog-heading"><h2 id="toc-heading">{t(locale, "장면 목록", "Scenes")} <small>19</small></h2><button type="button" onClick={() => toc.current?.close()}>{t(locale, "닫기", "Close")}</button></div>
        {sceneList()}
      </dialog>
      <dialog id="reader-sources" ref={sources} className="jevdb-dialog jevdb-sources" aria-labelledby="sources-heading" onClick={event => { if (event.target === event.currentTarget) event.currentTarget.close(); }} onClose={() => {
        if (window.location.hash === "#readerSources") window.history.replaceState(window.history.state, "", `#${sceneId(index)}`);
        sourceButton.current?.focus();
      }}>
        <div className="jevdb-dialog-heading"><h2 id="sources-heading">{t(locale, "자료와 출처", "Materials and sources")}</h2><button type="button" onClick={() => sources.current?.close()}>{t(locale, "닫기", "Close")}</button></div>
        <div className="jevdb-sources-body">
          <p>{t(locale, "리뷰·발표: 류지환. 원 논문: Zhengle Wang, Hanxu Yan, Fuheng Zhao, Chunwei Liu. 원 논문 그림의 CC BY 4.0 표시는 슬라이드에 남아 있습니다.", "Reviewed and presented by Jihwan Ryu. Original paper by Zhengle Wang, Hanxu Yan, Fuheng Zhao, and Chunwei Liu. Original figure attribution and CC BY 4.0 notices remain in the slides.")}</p>
          <section><h3>{t(locale, "원 논문과 발표 자료", "Paper and presentation")}</h3><ul>
            <li><a href={paper}><span>PAPER</span> <span>Prune First, Decide Fast · arXiv:2610.02046v1</span></a></li>
            <li><a href="https://youtu.be/KKiEyGjGUIo"><span>VIDEO</span> <span>{t(locale, "논문 리뷰 발표 영상", "Paper review recording")}</span></a></li>
            <li><a href={slides} download><span>PPT</span> <span>{t(locale, "v25 · 영문 19장 · 한국어 발표자 메모", "v25 · 19 English slides · Korean speaker notes")}</span></a></li>
            <li><a href={`${assets}manifest.json`}><span>HASH</span> <span>{t(locale, "슬라이드 이미지·원본 PPT SHA-256", "Slide image and original PPT SHA-256")}</span></a></li>
          </ul></section>
          <section><h3>{t(locale, "별도 GEODE 연구 · 장면 18", "Separate GEODE study · scene 18")}</h3><ul>
            <li><a href={`/geode/research/jev-system1-offloading/?lang=${locale}#v3-e2e-injected`}><span>STUDY</span> <span>Jev Decision Offloading · U8c</span></a></li>
            <li><a href={evidence}><span>DATA</span> <span>{t(locale, "고정된 연구 기록 · 3bcf4044", "Pinned study records · 3bcf4044")}</span></a></li>
          </ul><p>{t(locale, "U8c는 18 matched cases의 agent-loop 비교입니다. U3의 frozen-state 단일 판정이나 U8n의 사후 분석과 합치지 않습니다. 이 리뷰에서 새 실험을 실행하지 않았으며 JEVDB 재현 결과를 주장하지 않습니다.", "U8c compares agent loops across 18 matched cases. It is separate from U3 frozen-state single judgments and the U8n post-hoc analysis. This review runs no new experiment and claims no JEVDB reproduction.")}</p></section>
          <section><h3>{t(locale, "원본 보존", "Preserved originals")}</h3><p>{t(locale, "2026년 10월 11일 완성한 v25 PPT는 변경하지 않았습니다. 웹은 기존 v25 PDF 검수 이미지를 재사용하며 원본의 영문 텍스트도 제공합니다. 단계는 슬라이드당 1개이며, 별도의 모션이나 중간 build를 만들지 않았습니다.", "The v25 PPT completed on October 11, 2026 is unchanged. The reader reuses existing v25 PDF review images and provides the original English slide text. Each slide has one settled build; no motion or intermediate builds were added.")}</p></section>
        </div>
      </dialog>
    </div>
  );
}

export function JevdbReview() {
  return <LocaleProvider><ReviewContent /></LocaleProvider>;
}
