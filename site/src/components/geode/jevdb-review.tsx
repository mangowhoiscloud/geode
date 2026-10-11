"use client";

import Link from "next/link";
import { LocaleProvider, t, useLocale, useSetLocale } from "@/components/geode/locale-context";
import "./jevdb-review.css";

const paper = "https://arxiv.org/abs/2610.02046v1";
const slides = "/geode/research/jevdb-seminar-v25.pptx";

function ReviewContent() {
  const locale = useLocale();
  const setLocale = useSetLocale();

  return (
    <div className="jevdb-review" lang={locale}>
      <a className="jevdb-skip" href="#review-content">{t(locale, "본문으로 이동", "Skip to content")}</a>
      <header className="jevdb-header">
        <Link href={`/?lang=${locale}#research`}>GEODE / Research</Link>
        <div className="jevdb-locale" role="group" aria-label={t(locale, "언어", "Language")}>
          <button type="button" aria-pressed={locale === "ko"} onClick={() => setLocale("ko")}>KO</button>
          <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
        </div>
      </header>
      <main id="review-content" tabIndex={-1}>
        <article>
          <header className="jevdb-intro">
            <p className="jevdb-eyebrow">JEVDB · {t(locale, "논문 리뷰", "Paper review")}</p>
            <h1>Prune First,<br />Decide Fast</h1>
            <p className="jevdb-subtitle">Scalable Semantic Query Processing with JEVDB</p>
            <p className="jevdb-byline">{t(locale, "리뷰·발표 류지환", "Reviewed and presented by Jihwan Ryu")} · <time dateTime="2026-10-11">2026.10.11</time></p>
            <div className="jevdb-actions">
              <a className="jevdb-watch" href="https://youtu.be/KKiEyGjGUIo">{t(locale, "논문 리뷰 영상 보기", "Watch the paper review")}</a>
              <a href={slides} download>{t(locale, "발표 자료 다운로드 · PPTX", "Download the slides · PPTX")}</a>
            </div>
            <p className="jevdb-caption">{t(locale, "v25 · 영문 19장 · 한국어 발표자 메모 포함", "v25 · 19 English slides · Korean speaker notes")}</p>
            <p className="jevdb-lead">{t(locale,
              "Semantic query가 필요한 것은 문장 전체가 아니라 확률, 범주, 점수일 수 있습니다. 이 리뷰는 JEVDB가 판단 하나의 생성 비용과 판단해야 할 후보 수를 함께 줄이는 방법을 설명하고, 보고된 성능을 비교 조건과 함께 읽습니다.",
              "A semantic query may need a probability, category, or score rather than generated prose. This review explains how JEVDB reduces both generation per decision and the number of candidates, then reads the reported performance alongside its comparison conditions.",
            )}</p>
            <p className="jevdb-source">{t(locale, "원 논문", "Original paper")}: Zhengle Wang, Hanxu Yan, Fuheng Zhao, Chunwei Liu.<br /><a href={paper}>arXiv:2610.02046v1</a></p>
          </header>

          <section aria-labelledby="decision-title">
            <p className="jevdb-eyebrow">01 · Slides 3–6</p>
            <h2 id="decision-title">{t(locale, "Query가 요구하는 판단부터 정합니다", "Start with the decision a query needs")}</h2>
            <p>{t(locale,
              "보고서와 공지를 semantic join할 때 모델이 판단할 것은 특정 공지가 보고된 결함을 다루는지입니다. 논문은 입력과 task, output space를 묶어 Noul의 확률, Choice의 범주, Score의 기대 점수를 DB operator에 연결합니다. DB는 반환값으로 filter, classification, ranking, join 결과를 구성합니다.",
              "For a semantic join between reports and bulletins, the model judges whether a bulletin covers the reported defect. The paper binds input, task, and output space to Noul probabilities, Choice categories, and Score expected values. Database operators use those outputs to filter, classify, rank, and join rows.",
            )}</p>
            <p>{t(locale,
              "출력 타입을 제한하면 답변을 생성하고 다시 파싱하는 작업을 줄일 수 있습니다. 다만 typed output은 정답 보장이 아닙니다. 판단당 비용이 작아져도 두 테이블의 전체 조합을 평가하면 후보 수 문제는 남습니다.",
              "A constrained output can reduce answer generation and parsing, but a typed output does not guarantee a correct judgment. Even cheap decisions leave a candidate-count problem if the engine evaluates the full cross product of two tables.",
            )}</p>
          </section>

          <section aria-labelledby="work-title">
            <p className="jevdb-eyebrow">02 · Slides 7–12</p>
            <h2 id="work-title">{t(locale, "판단할 작업을 먼저 줄입니다", "Reduce the work before judging")}</h2>
            <p>{t(locale,
              "JEVDB는 relational key와 등록된 necessary condition으로 후보를 먼저 걸러냅니다. 예를 들어 결함 부품이 일치해야 한다는 조건이 타당하면 battery 보고서와 display 공지의 조합을 제외할 수 있습니다. 알 수 없는 속성은 남겨야 하며, lossless pruning이라는 주장은 조건과 속성 추출이 모두 타당할 때 성립합니다. 발표의 보고서·공지 예시는 이 경계를 설명하기 위한 예시입니다.",
              "JEVDB first screens candidates using relational keys and registered necessary conditions. If a sound condition requires compatible components, a battery report and a display bulletin can be excluded. Unknown attributes must remain eligible. Lossless pruning depends on both a sound condition and sound attribute extraction; the report–bulletin examples in the talk illustrate that boundary.",
            )}</p>
            <p>{t(locale,
              "남은 입력에는 exact-input decision 재사용, batching, 반복 문서 공유를 적용합니다. 문서별 interpretation을 저장해 조합하는 경로도 제시하지만, 이는 모든 query 작업을 선형으로 만든다는 뜻은 아닙니다. Pair 관리와 escalation은 여전히 남습니다. Full JEVDB는 predicate별로 보정한 불확실 구간을 reasoning LLM에 넘기며, 확신을 가진 오판은 이 경로를 통과하지 않을 수 있습니다.",
              "For surviving inputs, the paper uses exact-input decision reuse, batching, and shared repeated text. It also proposes combining stored document interpretations. That does not make all query work linear: pair management and escalation remain. Full JEVDB sends a predicate-calibrated uncertainty band to a reasoning LLM, while confidently wrong decisions can bypass escalation.",
            )}</p>
          </section>

          <section aria-labelledby="results-title">
            <p className="jevdb-eyebrow">03 · Slides 13–16</p>
            <h2 id="results-title">{t(locale, "품질·시간·비용을 같은 조건에서 읽습니다", "Read quality, time, and cost together")}</h2>
            <p>{t(locale,
              "SemBench의 Flash 비교에서는 모델과 실행 전략이 함께 달라집니다. Flash 1회 실행과 baseline 5회 평균을 비교하며, query별 비율과 전체 시간 합계의 비율도 다른 집계입니다. 따라서 보고된 개선을 특정 구성요소 하나의 효과로 분해할 수는 없습니다.",
              "The SemBench Flash comparison changes both the model and execution strategy. Flash is measured once against five-run baseline means, and per-query ratios differ from a ratio of total elapsed times. The reported gain therefore cannot be assigned to a single component.",
            )}</p>
            <p>{t(locale,
              "Shelob에서는 완료한 query의 F1과 timeout 시점의 evaluated-pair progress를 구분해야 합니다. Full JEVDB가 Flash보다 높은 품질을 얻는 데 더 긴 시간이 필요한 경우도 있습니다. 리뷰는 index 구축 비용의 별도 처리, CPU embedding 조건, reference answer 생성·검수 절차의 불명확성을 함께 짚습니다. 수치와 표별 조건은 발표 자료에 원 논문의 절·표와 함께 표시했습니다.",
              "On Shelob, F1 for completed queries must be distinguished from evaluated-pair progress at timeout. Full JEVDB can require more time than Flash to reach higher quality. The review also examines separately accounted index setup, CPU embedding conditions, and an unspecified reference-answer creation and checking procedure. The slides pair numerical results with the relevant paper sections, tables, and conditions.",
            )}</p>
          </section>

          <section aria-labelledby="questions-title">
            <p className="jevdb-eyebrow">04 · Slides 17–19</p>
            <h2 id="questions-title">{t(locale, "계획과 재사용에 남는 질문", "Questions for planning and reuse")}</h2>
            <p>{t(locale,
              "어떤 screening 순서가 제거할 후보 수와 검사 비용을 함께 줄이는지, 문서가 바뀌면 어떤 interpretation과 종속 판단을 갱신해야 하는지가 다음 질문입니다. 논문의 semantic-aware query optimization과 reusable semantic state 방향을 이 두 관점에서 읽었습니다. 발표의 변경 예시는 연구 방향을 설명하며 새 실험 결과를 뜻하지 않습니다.",
              "Which screening order balances the candidates removed against the cost of checking? When a document changes, which interpretations and dependent decisions need refreshing? These questions frame the paper’s directions for semantic-aware query optimization and reusable semantic state. The change examples in the talk illustrate research directions, not new experimental results.",
            )}</p>
            <p>{t(locale,
              "마지막 장면은 별도의 GEODE completion-verifier 실험을 연결합니다. 실행·수리와 완료 판정의 역할을 나눠 verification 비용을 관찰한 사례이며, JEVDB의 벤치마크나 이 논문의 재현 결과가 아닙니다. 실험 단위와 측정 범위는 별도 연구 보고서에서 확인할 수 있습니다.",
              "The closing research perspective connects a separate GEODE completion-verifier experiment. It observes verification cost by separating execution and repair from completion judgment. It is neither a JEVDB benchmark nor a reproduction of this paper. The separate research report records the experimental units and measurement boundaries.",
            )}</p>
            <a href={`/geode/resaerch/jev-system1-offloading/?lang=${locale}`}>{t(locale, "별도 Jev Decision Offloading 연구 보고서", "Separate Jev Decision Offloading research report")}</a>
          </section>

          <footer className="jevdb-footer">
            <h2>{t(locale, "자료와 출처", "Materials and sources")}</h2>
            <p>{t(locale,
              "이 페이지는 류지환의 논문 리뷰입니다. 원 논문의 저자와 리뷰 발표자를 구분하며, 논문 그림의 출처와 CC BY 4.0 표시는 슬라이드에 남아 있습니다. 공개 PPTX는 2026년 10월 11일 완성한 v25 원본입니다.",
              "This page presents Jihwan Ryu’s paper review. The paper authors and review presenter are identified separately; original figure attribution and CC BY 4.0 notices remain in the slides. The public PPTX preserves the v25 file completed on October 11, 2026.",
            )}</p>
            <div className="jevdb-source-links">
              <a href={paper}>{t(locale, "원 논문 v1", "Original paper v1")}</a>
              <a href={slides} download>{t(locale, "v25 PPTX 다운로드", "Download v25 PPTX")}</a>
              <a href="https://github.com/mangowhoiscloud/geode/tree/7e7a74dcef5412c7b9eab3a7c431496b36630614/research">{t(locale, "원본 파일과 SHA-256", "Source file and SHA-256")}</a>
            </div>
          </footer>
        </article>
      </main>
    </div>
  );
}

export function JevdbReview() {
  return <LocaleProvider><ReviewContent /></LocaleProvider>;
}
