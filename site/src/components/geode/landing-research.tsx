"use client";

import Link from "next/link";
import { Download, ExternalLink } from "lucide-react";
import { t, useLocale } from "@/components/geode/locale-context";

const jevEvidence = "https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/3bcf4044eb5c2411dd48122d672aef72a83fb30e/reports/e2e-validation/jev-v3-20260927";

export function ResearchSection() {
  const locale = useLocale();
  const jevReader = `/geode/resaerch/jev-system1-offloading/?lang=${locale}`;
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
      <div className="landing-section-heading">
        <h2 id="research-title" lang="en">Research</h2>
        <p>{t(locale,
          "GEODE의 실험 연구와 외부 논문 리뷰를 읽습니다. 질문과 관측, 해석의 한계에서 출발해 보고서·발표자료·공개 근거로 이어집니다.",
          "Explore GEODE experiments and reviews of outside research. Follow each question through its observations and limits to reports, presentations, and public evidence.",
        )}</p>
      </div>

      <div className="landing-research-tier" aria-labelledby="research-materials-title">
        <h3 id="research-materials-title">{t(locale, "공개 연구자료", "Research materials")}</h3>

        <article id="research-jev" className="landing-research-resource" data-provenance="geode" aria-labelledby="research-jev-title">
          <p className="landing-research-provenance">{t(locale, "GEODE 실험 연구", "GEODE experimental study")}</p>
          <h4 id="research-jev-title" lang="en"><a href={jevReader}>Jev: System 1 Decision Offloading</a></h4>
          <dl className="landing-research-facts">
            <div>
              <dt>{t(locale, "질문", "Question")}</dt>
              <dd>{t(locale, "작은 판정기에 작업 완료 여부를 맡겨도 될까?", "Can a small judge decide when the work is done?")}</dd>
            </div>
            <div>
              <dt>{t(locale, "관측과 한계", "Observations and limits")}</dt>
              <dd>{t(locale,
                "판정 정확도, 호출 지연, 실제 과제 완료를 분리해 실험했습니다. 올바른 수리 후보를 보류한 실패도 공개합니다.",
                "The study measures judgment accuracy, call latency, and task completion separately. It also reports failures where correct repairs were held back.",
              )}</dd>
            </div>
            <div>
              <dt>{t(locale, "자료", "Materials")}</dt>
              <dd>
                <nav className="landing-research-formats" aria-label={t(locale, "Jev 연구자료", "Jev research materials")}>
                  <a className="landing-button" href={jevReader}>{t(locale, "보고서 읽기", "Read the report")}</a>
                  <a href={`/geode/resaerch/jev-system1-offloading/report-${locale}.pdf`} download>{t(locale, "PDF 보고서", "PDF report")}<Download size={16} aria-hidden="true" /></a>
                  <a href={jevEvidence}>{t(locale, "평가 기록", "Evaluation records")}<ExternalLink size={16} aria-hidden="true" /></a>
                  <span className="landing-research-format-note">{t(locale, "고정 커밋", "Pinned commit")} <code>3bcf404</code></span>
                  <Link href={`/docs/research/overview?lang=${locale}#jev`}>{t(locale, "설계와 해석", "Design and interpretation")}</Link>
                </nav>
              </dd>
            </div>
          </dl>
        </article>

        <article id="jevdb-paper-review" className="landing-research-resource" data-provenance="external" aria-labelledby="research-jevdb-title">
          <p className="landing-research-provenance">{t(locale, "외부 논문 리뷰", "External paper review")}</p>
          <h4 id="research-jevdb-title" lang="en"><Link href={`/research/jevdb?lang=${locale}`}>JEVDB: Prune First, Decide Fast</Link></h4>
          <p className="landing-research-attribution">{t(locale, "원 논문: Wang et al., arXiv:2610.02046v1", "Original paper: Wang et al., arXiv:2610.02046v1")}</p>
          <dl className="landing-research-facts">
            <div>
              <dt>{t(locale, "질문", "Question")}</dt>
              <dd>{t(locale, "후보 축소와 typed decision은 어떻게 작동하고, 보고된 성능은 어떤 조건에서 나왔을까?", "How do candidate pruning and typed decisions work, and under what conditions were the results reported?")}</dd>
            </div>
            <div>
              <dt>{t(locale, "검토 내용과 한계", "Review scope and limits")}</dt>
              <dd>{t(locale,
                "Semantic query의 후보 축소, 재사용, LLM escalation과 비교 실험의 조건을 검토합니다. 논문의 성능 보고와 별도 GEODE 실험을 구분하며, JEVDB 재현 결과를 주장하지 않습니다.",
                "Reviews pruning, reuse, LLM escalation, and benchmark conditions in semantic queries. The paper's reported results remain distinct from the separate GEODE study; this is not a JEVDB replication.",
              )}</dd>
            </div>
            <div>
              <dt>{t(locale, "자료", "Materials")}</dt>
              <dd>
                <nav className="landing-research-formats" aria-label={t(locale, "JEVDB 리뷰 자료", "JEVDB review materials")}>
                  <Link className="landing-button" href={`/research/jevdb?lang=${locale}`}>{t(locale, "리뷰 읽기", "Read the review")}</Link>
                  <a href="https://youtu.be/KKiEyGjGUIo">{t(locale, "발표 영상", "Review video")}<ExternalLink size={16} aria-hidden="true" /></a>
                  <a href="/geode/research/jevdb-seminar-v25.pptx" download>{t(locale, "슬라이드 PPTX", "Slides (PPTX)")}<Download size={16} aria-hidden="true" /></a>
                  <span className="landing-research-format-note">{t(locale, "v25 영문 19장, 한국어 발표자 메모", "v25: 19 English slides, Korean speaker notes")}</span>
                  <a href="https://arxiv.org/abs/2610.02046v1">{t(locale, "원 논문", "Original paper")}<ExternalLink size={16} aria-hidden="true" /></a>
                </nav>
              </dd>
            </div>
          </dl>
        </article>
      </div>

      <div className="landing-research-tier landing-research-directions" aria-labelledby="research-directions-title">
        <h3 id="research-directions-title">{t(locale, "구현과 탐색 방향", "Implementation and search directions")}</h3>
        <p>{t(locale, "설계와 저장된 관측을 함께 읽습니다. 구현 여부와 지속적인 개선을 입증하는 결과는 구분합니다.", "Read the designs alongside stored observations. An implemented mechanism is distinct from evidence of sustained improvement.")}</p>
        <div className="landing-research-topics">
          {topics.map(topic => (
            <article key={topic.anchor}>
              <Link href={`/docs/research/overview?lang=${locale}#${topic.anchor}`}>{topic.name}</Link>
              <div><h4>{topic.question}</h4><p>{topic.detail}</p></div>
            </article>
          ))}
          <article>
            <Link href={`/docs/research/overview?lang=${locale}#related-work`}>{t(locale, "연구의 좌표", "Research context")}</Link>
            <div>
              <h4>{t(locale, "SelfSearch·DGM과의 관계", "Relation to SelfSearch and DGM")}</h4>
              <p>{t(locale, "평가 피드백을 쓰는 GEODE의 탐색을 DGM, 검색 중 downstream reward를 쓰지 않는 SelfSearch와 구분해 읽습니다.", "Compare GEODE's evaluation-guided search with DGM. SelfSearch differs by excluding downstream rewards during search.")}</p>
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}
