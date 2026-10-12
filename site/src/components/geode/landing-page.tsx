"use client";

import Link from "next/link";
import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { LocaleProvider, t, useLocale } from "@/components/geode/locale-context";
import { LoopMap } from "@/components/geode/loop-map";
import { RecordedRun } from "@/components/geode/landing-run";
import { BenchmarkComparison } from "@/components/geode/landing-benchmark";
import { InstallCommands } from "@/components/geode/landing-install";
import { LandingHeader } from "./landing-header";
import { LegacyResearchRedirect } from "./legacy-research-redirect";
import { ResearchEntries } from "@/components/geode/landing-research";
import { galmuri } from "@/fonts/galmuri";
import "./landing.css";

const repository = "https://github.com/mangowhoiscloud/geode";

function LandingContent() {
  const locale = useLocale();

  return (
    <div className={`geode-landing ${galmuri.variable}`} lang={locale}>
      <a className="landing-skip" href="#main-content">{t(locale, "본문으로 이동", "Skip to content")}</a>
      <LandingHeader home />
      <LegacyResearchRedirect />

      <main id="main-content" tabIndex={-1}>
        <section id="hero" className="landing-container landing-hero">
          <div className="landing-hero-copy">
            <p className="landing-product-label">{t(locale, "자율 수행 에이전트 하네스", "Autonomous Agent Harness")}</p>
            <h1>{t(locale, "작업을 수행하고,\n더 나은 실행을\n탐구합니다.", "Execute the task.\nExplore a better\nway to run it.")}</h1>
            <p className="landing-hero-description">
              {t(locale,
                "GEODE는 도구의 관측을 바탕으로 다음 행동을 선택합니다. 바깥의 Experimental Loop는 scaffold와 평가 시나리오를 탐색하고, 후보의 채택과 복원을 관리합니다.",
                "GEODE chooses its next action from tool observations. An outer Experimental Loop searches scaffolds and evaluation scenarios, then manages candidate acceptance and reversion.",
              )}
            </p>
            <div className="landing-actions">
              <a className="landing-button landing-button-primary" href="#install">{t(locale, "GEODE 설치", "Install GEODE")}</a>
              <a className="landing-button" href={`/geode/research/?lang=${locale}`}>{t(locale, "연구 살펴보기", "Explore the research")}</a>
            </div>
          </div>
          <LoopMap locale={locale} />
        </section>

        <section className="landing-container landing-run-section" aria-label={t(locale, "실제 작업의 실행 기록", "A recorded task execution")}>
          <div className="landing-section-heading">
            <h2>{t(locale, "말한 결과에서, 확인할 수 있는 결과로.", "From a claimed result to an inspectable one.")}</h2>
            <p>{t(locale, "TLS 인증서를 만드는 실제 기록으로 작업 요청, 도구 호출, verifier 결과를 따라갑니다. 실행 기록과 과제 성공의 판정을 구분합니다.", "Follow a recorded TLS certificate task from request to tool calls and verifier result. Execution records and the task's success verdict remain distinct.")}</p>
            <div className="landing-inline-links">
              <Link href={`/docs/architecture/agentic-loop?lang=${locale}`}>{t(locale, "자율 수행의 구조", "How autonomous execution works")}</Link>
              <Link href={`/docs/architecture/overview?lang=${locale}`}>{t(locale, "구조", "Architecture")}</Link>
            </div>
          </div>
          <RecordedRun />
        </section>

        <section id="evidence" className="landing-container landing-section" aria-labelledby="evidence-title">
          <div className="landing-section-heading">
            <p className="landing-kicker">Harbor × Terminal-Bench 2.1</p>
            <h2 id="evidence-title">{t(locale, "같은 모델. 다른 하네스.", "Same model. Different harness.")}</h2>
            <p>{t(locale,
              "GEODE와 native Codex를 같은 작업과 verifier로 비교했습니다. 결과와 한계를 함께 공개합니다.",
              "GEODE and native Codex, measured on the same tasks and verifiers. Read the results with their limits.",
            )}</p>
            <Link className="landing-text-link" href={`/docs/benchmarks/terminal-bench?lang=${locale}`}>{t(locale, "측정 방법 보기", "Read the evaluation method")}</Link>
          </div>
          <BenchmarkComparison />
        </section>

        <ResearchEntries />

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
          <a href={`/geode/research/jev-system1-offloading/?lang=${locale}`}>{t(locale, "Jev 연구 보고서", "Jev research report")}</a>
          <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts">{t(locale, "평가 데이터", "Evaluation data")}</a>
          <a href={`${repository}/releases`}>{t(locale, "릴리즈 노트", "Release notes")}</a>
          <Link href="/about">{t(locale, "만든 사람", "About the author")}</Link>
        </div>
      </footer>
    </div>
  );
}

export function GeodeLanding() {
  return <LocaleProvider defaultLocale="en"><LandingContent /></LocaleProvider>;
}
