"use client";

import { DocsShell } from "@/components/geode-docs/docs-shell";
import Link from "next/link";
import { DocsNavigation } from "@/components/geode-docs/docs-navigation";
import { findPage } from "@/lib/geode-docs/sitemap";
import { DOCS_NAV_GROUPS, docsPageHref } from "@/lib/geode-docs/navigation";
import { useLocale, t } from "@/components/geode/locale-context";

export default function DocsIndex() {
  const locale = useLocale();
  const summaryEn =
    "An Autonomous Agent Harness for tasks, with a separate Experimental Loop for scaffold search and evaluation.";
  const summaryKo =
    "작업을 수행하는 자율 에이전트 하네스와 scaffold 탐색·평가를 위한 별도의 Experimental Loop를 살펴봅니다.";
  return (
    <DocsShell
      slug=""
      title="GEODE Documentation"
      titleKo="GEODE 문서"
      summary={summaryEn}
      summaryKo={summaryKo}
    >
      <section className="docs-two-layers" aria-label={t(locale, "GEODE의 두 층", "GEODE's two layers")}>
        <h2>{t(locale, "작업을 수행하는 하네스. 실행을 연구하는 루프.", "A harness for work. A loop for experiments.")}</h2>
        <p>{t(locale, "Autonomous Agent Harness에서는 모델이 도구 관측을 읽고 다음 행동을 선택합니다. Experimental Loop에서는 scaffold 후보와 평가 시나리오를 생성·측정하고, 채택과 복원을 관리합니다.", "In the Autonomous Agent Harness, the model chooses its next action from tool observations. The Experimental Loop generates and evaluates scaffolds and scenarios, managing candidate acceptance and reversion.")}</p>
        <p><Link href={docsPageHref("architecture/agentic-loop", locale)}>{t(locale, "자율 수행의 구조", "Understand the harness")}</Link>{" / "}<Link href={docsPageHref("research/overview", locale)}>{t(locale, "Experimental Loop의 연구와 근거", "Explore Experimental Loop research and evidence")}</Link></p>
      </section>

      <section className="docs-task-routes" aria-label={t(locale, "목적별 시작점", "Start with your task")}>
        {DOCS_NAV_GROUPS.map((group) => (
          <div key={group.id} className="docs-task-route">
            <div>
              <h2>{t(locale, group.titleKo, group.title)}</h2>
              <p>{t(locale, group.summaryKo, group.summary)}</p>
            </div>
            <ul>{group.entrySlugs.map((slug) => {
              const page = findPage(slug)!.page;
              return <li key={slug}><Link href={docsPageHref(slug, locale)}>
                <span className="docs-task-title">{t(locale, page.titleKo, page.title)}</span>{" "}
                <span className="docs-task-description">{t(locale, page.summaryKo ?? "", page.summary ?? "")}</span>
              </Link></li>;
            })}</ul>
          </div>
        ))}
      </section>

      <section className="docs-index-directory">
        <h2>{t(locale, "전체 문서", "All documentation")}</h2>
        <p>{t(locale, "분야를 선택하거나 제목·요약·경로로 문서를 찾으세요.", "Choose an area or find documents by title, summary, or path.")}</p>
        <DocsNavigation slug="" directory />
      </section>

      <section className="docs-index-background" aria-label={t(locale, "설계 배경", "Design background")}>
        <h2>{t(locale, "서로 다른 책임, 연결된 근거", "Separate responsibilities, connected evidence")}</h2>
        <p>{t(locale, "런타임은 모델이 관측에서 다음 행동을 선택하도록 도구, 컨텍스트, 실행 제어를 제공합니다. 평가 계층은 실행 기록과 과제 verifier를 읽고, 실험 계층은 제한된 후보의 채택·복원을 관리합니다. 일반 작업이 끝났다는 사실과 개선 후보가 검증됐다는 사실은 다릅니다.", "The runtime supplies tools, context, and execution controls while the model chooses actions from observations. Evaluation reads records and task verifiers; experiments manage acceptance and reversion of bounded candidates. Completing a task and validating an improvement candidate are different outcomes.")}</p>
        <p>{t(locale, "가중치 고정 scaffold 탐색과 시나리오 생성, 판정 모델 연구를 실제 산출물로 확인하세요. SelfSearch와 DGM은 탐색 대상과 피드백 경계를 비교할 연구이며, 동일 방법이나 재현 성과로 묶지 않습니다.", "Inspect fixed-weight scaffold search, scenario generation, and judgment research through their artifacts. SelfSearch and DGM help compare search targets and feedback boundaries; they are not equivalent methods or reproduced results.")}</p>
        <ul>
          <li><Link href={docsPageHref("research/overview", locale)}>{t(locale, "연구 질문·설계·관측·한계", "Research questions, designs, observations, and limits")}</Link></li>
          <li><Link href={docsPageHref("concepts/two-loops", locale)}>{t(locale, "두 루프의 구조", "The two-loop structure")}</Link></li>
          <li><Link href={docsPageHref("reference/external-references", locale)}>{t(locale, "외부 참고 자료", "External references")}</Link></li>
        </ul>
      </section>
    </DocsShell>
  );
}
