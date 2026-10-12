"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Download } from "lucide-react";
import { t, useLocale, type Locale } from "@/components/geode/locale-context";

const jevEvidence = "https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/3bcf4044eb5c2411dd48122d672aef72a83fb30e/reports/e2e-validation/jev-v3-20260927";
const ids = ["research-geode", "research-jev", "jevdb-paper-review"];

/** One copy source for the landing entries and the /research/ collection. */
function publications(locale: Locale) {
  return [
    {
      name: t(locale, "GEODE 리포트", "GEODE report"), title: "GEODE", kind: t(locale, "기술 리포트", "Technical report"),
      image: `/geode/research/geode-report/${locale}/01.webp`, width: 1600, height: 900,
      reader: `/geode/research/geode/?lang=${locale}#page-01`,
      caption: t(locale, "공개 92쪽 판본 · 한국어 원본 1쪽", "Published 92-page edition · English original, page 1"),
      summary: t(locale, "실행, 상태, 권한의 경계에서 평가와 실험까지. 공개 리포트의 도표와 관측을 한 페이지씩 따라갑니다.", "From execution, state, and authority to evaluation and experiments. Read the published figures and observations page by page."),
      scope: t(locale, "각 페이지의 기록 시점과 비교 조건을 보존한 판본입니다.", "This edition preserves the dates and comparison conditions recorded on each page."),
      links: [{ label: t(locale, "PDF 다운로드", "Download PDF"), href: `/geode/report${locale === "en" ? "-en" : ""}.pdf`, download: true }, { label: t(locale, "원본과 출처", "Originals and sources"), href: `/geode/research/geode/?lang=${locale}#readerSources` }],
    },
    {
      name: "Jev Decision Offloading", title: "Jev Decision Offloading", kind: t(locale, "GEODE 실험 연구", "GEODE experimental study"),
      image: `/geode/research/previews/jev-${locale}.webp`, width: 1600, height: 900,
      reader: `/geode/research/jev-system1-offloading/?lang=${locale}#cover`,
      caption: t(locale, "2026.09.28 공개판 · 한국어 표지 · 57장면", "Published 2026.09.28 · English cover · 57 scenes"),
      summary: t(locale, "작은 판정기에 완료 여부를 맡기면 무엇이 달라질까. 판정 정확도, 호출 지연, 과제 완료를 따로 측정한 실험입니다.", "What changes when a small judge decides whether work is complete? Judgment accuracy, call latency, and task completion are measured separately."),
      scope: t(locale, "올바른 수리 후보를 보류한 실패와 실험 조건도 함께 읽습니다.", "The report retains failed decisions, including correct repairs held back, alongside the conditions."),
      links: [{ label: t(locale, "PDF 다운로드", "Download PDF"), href: `/geode/resaerch/jev-system1-offloading/report-${locale}.pdf`, download: true }, { label: t(locale, "평가 기록", "Evaluation records"), href: jevEvidence }, { label: t(locale, "설계와 해석", "Design and interpretation"), href: `/geode/docs/research/overview/?lang=${locale}#jev` }],
    },
    {
      name: t(locale, "JEVDB 리뷰", "JEVDB review"), title: "Prune First, Decide Fast", kind: t(locale, "외부 논문 리뷰", "External paper review"),
      image: "/geode/research/jevdb-slides-v25/01.png", width: 1585, height: 891,
      reader: `/geode/research/jevdb/?lang=${locale}#slide-01`,
      caption: t(locale, "v25 · 영문 원본 1장 · 전체 19장", "v25 · Original English slide 1 · 19 slides"),
      summary: t(locale, "후보 축소, typed decision, 재사용과 LLM escalation. Wang et al.의 JEVDB 논문을 도표와 비교 조건으로 읽습니다.", "Candidate pruning, typed decisions, reuse, and LLM escalation. Read Wang et al.'s JEVDB paper through its figures and comparison conditions."),
      scope: t(locale, "논문의 성능 보고와 별도 GEODE 실험을 구분한 리뷰입니다.", "The review separates paper-reported performance from the independent GEODE study."),
      links: [{ label: t(locale, "발표 영상", "Watch the talk"), href: "https://youtu.be/KKiEyGjGUIo" }, { label: t(locale, "PPT 다운로드", "Download PPT"), href: "/geode/research/jevdb-seminar-v25.pptx", download: true }, { label: t(locale, "원 논문", "Original paper"), href: "https://arxiv.org/abs/2610.02046v1" }],
    },
  ];
}

type Publication = ReturnType<typeof publications>[number];

function PublicationLinks({ item, locale }: { item: Publication; locale: Locale }) {
  return <nav className="research-links" aria-label={t(locale, `${item.name} 자료`, `${item.name} materials`)}>
    <a className="research-open" href={item.reader}>{t(locale, "장면으로 읽기", "Read scene by scene")}<ArrowUpRight size={18} aria-hidden="true" /></a>
    {item.links.map(link => <a key={link.href} href={link.href} download={link.download || undefined}>{link.label}{link.download ? <Download size={15} aria-hidden="true" /> : <ArrowUpRight size={15} aria-hidden="true" />}</a>)}
  </nav>;
}

/** Landing entry list: each reader is one link away; the collection holds the full selector. */
export function ResearchEntries() {
  const locale = useLocale();
  return (
    <section id="publications" className="landing-container landing-section" aria-labelledby="publications-title">
      <div className="landing-section-heading"><h2 id="publications-title" lang="en">Research</h2><p>{t(locale, "실행을 들여다보고, 판단을 실험합니다.", "Inside the execution. Into the decisions.")}</p></div>
      <ol className="research-entries">
        {publications(locale).map(item => <li key={item.reader}>
          <figure>
            <a href={item.reader} tabIndex={-1}><Image src={item.image} alt={t(locale, `${item.name} 원본 표지`, `Original cover of ${item.name}`)} width={item.width} height={item.height} sizes="(max-width: 767px) 100vw, (max-width: 1023px) 45vw, 380px" /></a>
            <figcaption className="research-preview-caption">{item.caption}</figcaption>
          </figure>
          <div>
            <p className="research-kind">{item.kind}</p>
            <h3><a href={item.reader}>{item.title}</a></h3>
            <p className="research-summary">{item.summary}</p>
            <p className="research-scope">{item.scope}</p>
            <PublicationLinks item={item} locale={locale} />
          </div>
        </li>)}
      </ol>
      <div className="landing-inline-links">
        <a href={`/geode/research/?lang=${locale}`}>{t(locale, "연구 살펴보기", "Explore the research")}</a>
        <Link href={`/docs/research/overview?lang=${locale}`}>{t(locale, "연구와 근거", "Research and evidence")}</Link>
        <Link href={`/docs/capabilities/outer-loop?lang=${locale}`}>{t(locale, "외부 루프 살펴보기", "Explore the outer loop")}</Link>
        <Link href={`/docs/explanation/rsi-roadmap?lang=${locale}`}>{t(locale, "현재 위치·용어·다음 검증", "Current scope, terms, and next tests")}</Link>
      </div>
    </section>
  );
}

/** The /research/ collection: one publication canvas with three document tabs. */
export function ResearchSection() {
  const locale = useLocale();
  const [selected, setSelected] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    const readHash = () => {
      const index = ids.indexOf(window.location.hash.slice(1));
      setSelected(index >= 0 ? index : 0);
    };
    const timer = window.setTimeout(readHash, 0);
    window.addEventListener("hashchange", readHash);
    window.addEventListener("popstate", readHash);
    return () => { window.clearTimeout(timer); window.removeEventListener("hashchange", readHash); window.removeEventListener("popstate", readHash); };
  }, []);
  const materials = publications(locale);
  const topics = [
    {
      name: "Scaffold Search", anchor: "scaffold",
      question: t(locale, "모델을 고정하고 실행 방식을 바꿀 수 있을까?", "Can the scaffold change while model weights stay fixed?"),
      detail: t(locale, "후보를 변형하고 평가한 뒤 채택하거나 복원합니다. 탐색 중 채택과 독립 검증의 판정은 별도로 남깁니다.", "Mutate, evaluate, then keep or revert. Search acceptance and independent validation retain separate verdicts."),
    },
    {
      name: "Seed Scenario Generation", anchor: "seeds",
      question: t(locale, "기존 평가가 놓친 행동을 어떻게 찾을까?", "What behavior do existing evaluations miss?"),
      detail: t(locale, "시나리오를 생성·비평·pilot·선별합니다. 생성된 seed가 유효한 평가인지, 다음 세대로 이어졌는지 확인합니다.", "Generate, critique, pilot, and select scenarios. Inspect both their validity and what reaches the next generation."),
    },
    {
      name: "SIL", anchor: "sil",
      question: t(locale, "실행의 실패를 다음 실험에 연결할 수 있을까?", "Can a failed run inform the next experiment?"),
      detail: t(locale, "Self-Improving Loop의 연결 경로와 저장된 기록을 살펴봅니다. 세션 기록만으로 변이나 승격을 입증하지 않습니다.", "Trace the Self-Improving Loop and its stored records. A session record alone does not establish a mutation or promotion."),
    },
  ];

  return (
    <section id="research" className="landing-container landing-section landing-research" aria-labelledby="research-title">
      <div className="landing-section-heading"><h1 id="research-title" lang="en">Research</h1><p>{t(locale, "실행을 들여다보고, 판단을 실험합니다.", "Inside the execution. Into the decisions.")}</p></div>
      <div className="research-tabs" role="tablist" aria-label={t(locale, "연구자료 선택", "Select a publication")}>
        {materials.map((item, i) => <button key={ids[i]} ref={element => { tabs.current[i] = element; }} id={`${ids[i]}-tab`} type="button" role="tab" aria-selected={selected === i} aria-controls={`${ids[i]}-panel`} tabIndex={selected === i ? 0 : -1} onClick={() => { setSelected(i); window.history.pushState(window.history.state, "", `#${ids[i]}`); }} onKeyDown={event => { const next = { ArrowLeft: (i + 2) % 3, ArrowRight: (i + 1) % 3, Home: 0, End: 2 }[event.key]; if (next !== undefined) { event.preventDefault(); tabs.current[next]?.focus(); } }}><span>{item.name}</span><span className="research-tab-kind">{item.kind}</span></button>)}
      </div>
      {materials.map((item, i) => <article key={ids[i]} id={`${ids[i]}-panel`} role="tabpanel" aria-labelledby={`${ids[i]}-tab`} hidden={selected !== i} tabIndex={0} className="research-publication">
        <a className="research-preview" href={item.reader} aria-label={t(locale, `${item.name} 첫 장면 열기`, `Open the first scene of ${item.name}`)}><Image src={item.image} alt={t(locale, `${item.name} 원본 표지`, `Original cover of ${item.name}`)} width={item.width} height={item.height} /></a>
        <p className="research-preview-caption">{item.caption}</p>
        <div className="research-publication-caption"><div><p className="research-kind">{item.kind}</p><h2><a href={item.reader}>{item.title}<ArrowUpRight size={24} aria-hidden="true" /></a></h2><p className="research-summary">{item.summary}</p><p className="research-scope">{item.scope}</p></div><PublicationLinks item={item} locale={locale} /></div>
      </article>)}
      <div className="landing-research-directions" aria-labelledby="research-directions-title"><h2 id="research-directions-title">{t(locale, "이어지는 연구", "Further research")}</h2><div className="landing-research-topics">{topics.map(topic => <article key={topic.anchor}><Link href={`/docs/research/overview?lang=${locale}#${topic.anchor}`}>{topic.name}<ArrowUpRight size={16} aria-hidden="true" /></Link><h3>{topic.question}</h3><p>{topic.detail}</p></article>)}<article><Link href={`/docs/research/overview?lang=${locale}#related-work`}>{t(locale, "연구의 좌표", "Research context")}<ArrowUpRight size={16} aria-hidden="true" /></Link><h3>SelfSearch · DGM</h3><p>{t(locale, "평가 피드백을 쓰는 GEODE의 탐색과 각 연구의 조건을 구분합니다.", "Compare GEODE's evaluation-guided search with the conditions of each study.")}</p></article></div></div>
    </section>
  );
}
