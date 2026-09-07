"use client";

import Link from "next/link";
import { ArrowRight, Repeat2 } from "lucide-react";
import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { LocaleProvider, t, useLocale } from "@/components/geode/locale-context";
import { RecordedRun } from "@/components/geode/landing-run";
import { BenchmarkComparison } from "@/components/geode/landing-benchmark";
import { InstallCommands } from "@/components/geode/landing-install";
import { GEODE_SOT } from "@/data/geode/sot";
import { galmuri } from "@/fonts/galmuri";
import "./landing.css";

const repository = "https://github.com/mangowhoiscloud/geode";

function LandingContent() {
  const locale = useLocale();
  const navigation = [
    { id: "run", label: t(locale, "실행", "Run") },
    { id: "evidence", label: t(locale, "측정", "Evidence") },
    { id: "features", label: t(locale, "기능", "Features") },
    { id: "install", label: t(locale, "설치", "Install") },
  ];
  const navigationLinks = (
    <>
      {navigation.map((item) => <a key={item.id} href={`#${item.id}`}>{item.label}</a>)}
      <Link href={`/docs?lang=${locale}`}>{t(locale, "문서", "Docs")}</Link>
      <a href={repository}>GitHub</a>
    </>
  );

  return (
    <div className={`geode-landing ${galmuri.variable}`} lang={locale}>
      <a className="landing-skip" href="#main-content">{t(locale, "본문으로 이동", "Skip to content")}</a>
      <header className="landing-header">
        <div className="landing-container landing-nav-row">
          <a href="#hero" className="landing-brand" aria-label={t(locale, "GEODE 처음으로", "GEODE home")}>
            <GeodiSprite scale={2} />
            <span>GEODE</span>
          </a>
          <nav className="landing-desktop-nav" aria-label={t(locale, "주 메뉴", "Main navigation")}>
            {navigationLinks}
          </nav>
          <details className="landing-mobile-menu">
            <summary>{t(locale, "메뉴", "Menu")}</summary>
            <nav
              aria-label={t(locale, "모바일 메뉴", "Mobile navigation")}
              onClick={(event) => {
                if (event.target instanceof Element && event.target.closest("a")) {
                  event.currentTarget.closest("details")?.removeAttribute("open");
                }
              }}
            >{navigationLinks}</nav>
          </details>
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        <section id="hero" className="landing-container landing-hero">
          <div className="landing-hero-copy">
            <p className="landing-product-label">{t(locale, "스스로 호스팅하는 에이전트 런타임", "A self-hosting agent runtime")}</p>
            <h1>{t(locale, "작업을 맡기고,\n결과를 확인하세요.", "Run the task.\nInspect the result.")}</h1>
            <p className="landing-hero-description">
              {t(locale,
                "GEODE는 모델과 도구를 연결해 작업을 실행하고, 확인할 수 있는 실행 기록을 남깁니다.",
                "GEODE connects models to your tools, runs the task, and keeps execution records you can inspect.",
              )}
            </p>
            <div className="landing-actions">
              <a className="landing-button landing-button-primary" href="#install">{t(locale, "GEODE 설치", "Install GEODE")}</a>
              <a className="landing-button" href="#run">{t(locale, "실행 기록 보기", "Inspect a run")}</a>
            </div>
          </div>
          <RecordedRun />
        </section>

        <section className="landing-container landing-loop-section" aria-labelledby="loop-title">
          <div className="landing-section-heading">
            <h2 id="loop-title">{t(locale, "도구의 결과가 다음 판단으로.", "The result becomes the next step.")}</h2>
            <p>{t(locale,
              "한 번 답하고 끝나지 않습니다. 도구를 실행하고 결과를 읽은 뒤, 다음 동작이나 최종 응답을 선택합니다.",
              "The loop runs a tool, reads its result, then chooses another action or a final response.",
            )}</p>
          </div>
          <div className="landing-loop" role="group" aria-label={t(locale, "에이전트 루프 개념도", "Conceptual agentic loop")}>
            <ol className="landing-loop-stages">
              {[
                [t(locale, "작업 요청", "Your task"), t(locale, "목표와 환경", "Goal and environment")],
                [t(locale, "다음 동작 선택", "Choose an action"), t(locale, "모델의 판단", "Model decision")],
                [t(locale, "도구 실행", "Run a tool"), t(locale, "허용된 작업", "Permitted action")],
                [t(locale, "결과 관찰", "Read the result"), t(locale, "다음 판단의 근거", "Context for the next decision")],
              ].map(([title, detail], index) => (
                <li key={title}>
                  <span className="landing-loop-step">{index + 1}</span>
                  <strong>{title}</strong><span>{detail}</span>
                  {index < 3 ? <ArrowRight className="landing-loop-next" size={20} aria-hidden="true" /> : null}
                </li>
              ))}
            </ol>
            <div className="landing-loop-return">
              <Repeat2 size={20} aria-hidden="true" />
              <p>{t(locale, "필요하면 반복합니다. 최종 응답은 성공의 외부 검증과 다릅니다.", "Repeat when needed. A final response is not an external proof of success.")}</p>
            </div>
          </div>
          <div className="landing-loop-notes">
            <p>{t(locale, "승인 정책, 실행 예산, 취소 신호가 실행을 제어합니다.", "Approval policies, execution budgets, and cancellation govern the run.")}</p>
            <Link className="landing-text-link" href={`/docs/architecture/agentic-loop?lang=${locale}`}>{t(locale, "런타임 살펴보기", "Explore the runtime")}</Link>
          </div>
        </section>

        <section id="evidence" className="landing-container landing-section" aria-labelledby="evidence-title">
          <div className="landing-section-heading">
            <p className="landing-kicker">Harbor × Terminal-Bench 2.1</p>
            <h2 id="evidence-title">{t(locale, "같은 모델. 다른 하네스.", "Same model. Different harness.")}</h2>
            <p>{t(locale,
              "GEODE와 native Codex를 같은 작업과 verifier로 비교했습니다. 결과와 한계를 함께 공개합니다.",
              "GEODE and native Codex, measured on the same tasks and verifiers. Read the results with their limits.",
            )}</p>
          </div>
          <BenchmarkComparison />
        </section>

        <section id="features" className="landing-container landing-section" aria-labelledby="features-title">
          <div className="landing-section-heading">
            <h2 id="features-title">{t(locale, "실행하고, 측정하고, 개선합니다.", "Run it. Measure it. Improve it.")}</h2>
            <p>{t(locale,
              "실행과 평가, scaffold 탐색은 서로 다른 책임입니다. 현재 작업의 성공과 개선 후보의 판정을 섞지 않습니다.",
              "Execution, evaluation, and scaffold search have separate responsibilities. A completed turn is not a promoted improvement.",
            )}</p>
          </div>
          <div className="landing-responsibilities">
            <article className="landing-runtime-role">
              <span className="landing-package">core</span>
              <h3>{t(locale, "작업이 실행되는 곳", "Where the work happens")}</h3>
              <p>{t(locale, "터미널, 채널, MCP 진입점에서 같은 AgenticLoop를 사용합니다. 도구, 세션, 실행 제어를 런타임이 담당합니다.", "Terminal, channel, and MCP entry points use the same AgenticLoop. The runtime owns tools, sessions, and execution controls.")}</p>
              <div className="landing-inline-links">
                <Link href={`/docs/architecture/overview?lang=${locale}`}>{t(locale, "구조", "Architecture")}</Link>
                <Link href={`/docs/runtime/context?lang=${locale}`}>{t(locale, "컨텍스트", "Context")}</Link>
                <Link href={`/docs/runtime/skills?lang=${locale}`}>{t(locale, "스킬", "Skills")}</Link>
              </div>
            </article>
            <div className="landing-consumer-roles">
              <article>
                <span className="landing-package">evals</span>
                <h3>{t(locale, "측정과 판정의 근거", "Evidence for a judgement")}</h3>
                <p>{t(locale, "작업 결과, trajectory, verifier를 구분해 비교와 감사를 지원합니다.", "Task results, trajectories, and verifier receipts support comparison and audit without becoming the same record.")}</p>
                <Link className="landing-text-link" href={`/docs/benchmarks/terminal-bench?lang=${locale}`}>{t(locale, "측정 방법 보기", "Read the evaluation method")}</Link>
              </article>
              <article id="distill">
                <span className="landing-package">evolve</span>
                <h3>{t(locale, "별도로 검증하는 개선 후보", "Improvement, tested separately")}</h3>
                <p>{t(locale, "Scaffold 후보를 탐색하고 평가합니다. 실험에서 선택된 후보가 곧 프로덕션 릴리즈는 아닙니다.", "Scaffold candidates are searched and evaluated. An experiment's selected candidate is not a production release.")}</p>
                <Link className="landing-text-link" href={`/docs/capabilities/outer-loop?lang=${locale}`}>{t(locale, "외부 루프 살펴보기", "Explore the outer loop")}</Link>
              </article>
            </div>
          </div>
        </section>

        <section id="install" className="landing-container landing-section landing-install-section" aria-labelledby="install-title">
          <div className="landing-section-heading">
            <h2 id="install-title">{t(locale, "내 환경에서 시작하세요.", "Start in your environment.")}</h2>
            <p>{t(locale, "최신 안정 버전을 설치하고, 모델 인증 후 첫 작업을 맡겨보세요.", "Install the stable release, connect a model, and give GEODE its first task.")}</p>
          </div>
          <InstallCommands />
          <div className="landing-provider-row" aria-label="Supported providers">
            <span>{t(locale, "모델 연결", "Model connections")}</span>
            <span>Anthropic</span><span>OpenAI / Codex</span><span>OpenRouter</span><span>ZhipuAI GLM</span>
            <Link className="landing-text-link" href={`/docs/run/pick-path?lang=${locale}`}>{t(locale, "인증 경로 선택", "Choose an auth path")}</Link>
          </div>
          <p className="landing-install-caution">{t(locale, "구독 인증과 API 종량제는 별도 경로입니다. 사용 가능한 모델과 비용은 계정과 제공자에 따라 다릅니다.", "Subscription authentication and metered APIs are separate routes. Model access and billing depend on your account and provider.")}</p>
        </section>
      </main>

      <footer id="lab" className="landing-container landing-footer">
        <div className="landing-footer-brand"><GeodiSprite scale={3} /><span>GEODE</span></div>
        <div className="landing-footer-links">
          <a href={locale === "en" ? "/geode/report-en.pdf" : "/geode/report.pdf"}>{t(locale, "기술 보고서 PDF", "Technical report PDF")}</a>
          <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts">{t(locale, "평가 데이터", "Evaluation data")}</a>
          <a href={`${repository}/releases/tag/v${GEODE_SOT.version}`}>{t(locale, "릴리즈 노트", "Release notes")}</a>
          <Link href="/about">{t(locale, "만든 사람", "About the author")}</Link>
        </div>
      </footer>
    </div>
  );
}

export function GeodeLanding() {
  return <LocaleProvider defaultLocale="en"><LandingContent /></LocaleProvider>;
}
