"use client";

import Link from "next/link";
import { useRef } from "react";
import { ArrowRight, Menu, Repeat2 } from "lucide-react";
import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { LocaleProvider, t, useLocale, useSetLocale } from "@/components/geode/locale-context";
import { LoopMap } from "@/components/geode/loop-map";
import { RecordedRun } from "@/components/geode/landing-run";
import { BenchmarkComparison } from "@/components/geode/landing-benchmark";
import { InstallCommands } from "@/components/geode/landing-install";
import { galmuri } from "@/fonts/galmuri";
import "./landing.css";

const repository = "https://github.com/mangowhoiscloud/geode";

function LandingContent() {
  const locale = useLocale();
  const setLocale = useSetLocale();
  const menuRef = useRef<HTMLDialogElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const navigation = [
    { id: "run", label: t(locale, "실행", "Run") },
    { id: "evidence", label: t(locale, "측정", "Evidence") },
    { id: "research", label: t(locale, "연구", "Research") },
    { id: "roadmap", label: t(locale, "로드맵", "Roadmap") },
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
          <div className="landing-locale" role="group" aria-label={t(locale, "언어", "Language")}>
            <button type="button" aria-pressed={locale === "ko"} onClick={() => setLocale("ko")}>KO</button>
            <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
          </div>
          <button ref={menuButtonRef} className="landing-mobile-menu" type="button" aria-haspopup="dialog" aria-controls="landing-menu"
            onClick={() => menuRef.current?.showModal()}>
            <Menu size={18} strokeWidth={1.5} aria-hidden="true" />
            <span>{t(locale, "메뉴", "Menu")}</span>
          </button>
          <dialog ref={menuRef} id="landing-menu" className="landing-menu-dialog" aria-labelledby="landing-menu-title"
            onClose={() => menuButtonRef.current?.focus()}
            onClick={event => { if (event.target === event.currentTarget) menuRef.current?.close(); }}>
            <div className="landing-menu-body">
              <div className="landing-menu-heading"><h2 id="landing-menu-title">{t(locale, "메뉴", "Menu")}</h2>
                <button type="button" onClick={() => menuRef.current?.close()}>{t(locale, "닫기", "Close")}</button></div>
            <nav
              aria-label={t(locale, "모바일 메뉴", "Mobile navigation")}
              onClick={(event) => {
                if (event.target instanceof Element && event.target.closest("a")) {
                  menuRef.current?.close();
                }
              }}
            >{navigationLinks}</nav>
            </div>
          </dialog>
        </div>
      </header>

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
              <a className="landing-button" href="#research">{t(locale, "연구와 근거 보기", "Explore the research")}</a>
            </div>
          </div>
          <LoopMap locale={locale} />
        </section>

        <section className="landing-container landing-run-section" aria-label={t(locale, "실제 작업의 실행 기록", "A recorded task execution")}>
          <div className="landing-section-heading">
            <p className="landing-kicker">Autonomous Agent Harness</p>
            <h2>{t(locale, "말한 결과에서, 확인할 수 있는 결과로.", "From a claimed result to an inspectable one.")}</h2>
            <p>{t(locale, "TLS 인증서를 만드는 실제 기록으로 작업 요청, 도구 호출, verifier 결과를 따라갑니다. 실행 기록과 과제 성공의 판정을 구분합니다.", "Follow a recorded TLS certificate task from request to tool calls and verifier result. Execution records and the task's success verdict remain distinct.")}</p>
            <Link className="landing-text-link" href={`/docs/architecture/agentic-loop?lang=${locale}`}>{t(locale, "자율 수행의 구조", "How autonomous execution works")}</Link>
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

        <section id="research" className="landing-container landing-section" aria-labelledby="research-title">
          <div className="landing-section-heading">
            <p className="landing-kicker">Experimental Loop</p>
            <h2 id="research-title">{t(locale, "실행 밖에서, 다음 질문을 검증합니다.", "Beyond execution, test the next question.")}</h2>
            <p>{t(locale, "Scaffold Search와 Seed Scenario Generation, SIL, Jev 연구는 서로 다른 질문을 다룹니다. 구현과 관측을 연결하되, 지속적 개선을 입증했다는 주장으로 묶지 않습니다.", "Scaffold Search, Seed Scenario Generation, SIL, and the Jev study address different questions. Connect their designs to observations without assuming sustained improvement.")}</p>
          </div>
          <div className="landing-research-list">
            {[
              ["Scaffold Search", t(locale, "모델을 고정하고 실행 방식을 바꿀 수 있을까?", "Can the scaffold change while model weights stay fixed?"), t(locale, "후보를 변형하고 평가한 뒤 채택하거나 복원합니다. 탐색 중 채택과 독립 검증의 판정은 별도로 남깁니다.", "Mutate, evaluate, then keep or revert. Search acceptance and independent validation retain separate verdicts."), "scaffold"],
              ["Seed Scenario Generation", t(locale, "기존 평가가 놓친 행동을 어떻게 찾을까?", "What behavior do existing evaluations miss?"), t(locale, "시나리오를 생성·비평·pilot·선별합니다. 생성된 seed가 유효한 평가인지, 다음 세대로 이어졌는지 확인합니다.", "Generate, critique, pilot, and select scenarios. Inspect both their validity and what reaches the next generation."), "seeds"],
              ["SIL", t(locale, "실행의 실패를 다음 실험에 연결할 수 있을까?", "Can a failed run inform the next experiment?"), t(locale, "Self-Improving Loop의 연결 경로와 저장된 기록을 살펴봅니다. 세션 기록만으로 변이나 승격을 입증하지 않습니다.", "Trace the Self-Improving Loop and its stored records. A session record alone does not establish a mutation or promotion."), "sil"],
              ["Jev · System 1 offloading", t(locale, "작은 판정기로 완료 여부를 맡겨도 될까?", "Can a small judge decide when the work is done?"), t(locale, "판정 정확도, 호출 지연, 실제 과제 완료를 분리해 실험했습니다. 올바른 수리 후보를 보류한 실패도 공개합니다.", "Measure judgment accuracy, latency, and task completion separately—including correct repairs the judge refused to deliver."), "jev"],
            ].map(([name, question, detail, anchor]) => <article key={anchor}>
              <p className="landing-research-name">{name}</p>
              <div><h3>{question}</h3><p>{detail}</p>
                <Link className="landing-text-link" href={`/docs/research/overview?lang=${locale}#${anchor}`}>{t(locale, "설계·관측·한계 읽기", "Read the design, evidence, and limits")}</Link>
              </div>
            </article>)}
          </div>
          <div className="landing-research-context">
            <p>{t(locale, "연구의 좌표: 평가 피드백을 쓰는 GEODE의 탐색을 DGM, 검색 중 downstream reward를 쓰지 않는 SelfSearch와 구분해 읽습니다.", "Research context: compare GEODE's evaluation-guided search with DGM. SelfSearch differs by excluding downstream rewards during search.")}</p>
            <Link className="landing-text-link" href={`/docs/research/overview?lang=${locale}#related-work`}>{t(locale, "SelfSearch·DGM과의 관계", "Relation to SelfSearch and DGM")}</Link>
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

        <section id="roadmap" className="landing-container landing-section" aria-labelledby="roadmap-title">
          <div className="landing-section-heading">
            <p className="landing-kicker">Research direction · RSI</p>
            <h2 id="roadmap-title">{t(locale, "다음 실행에 남는 개선을 검증합니다.", "Test what the next run inherits.")}</h2>
            <p>{t(locale,
              "개선 실행(L1)의 검증 경계와 제한형 후보 탐색(L2)을 구현했습니다. 다음 과제는 채택된 변경을 이어받은 실행이 고정 전략보다 더 나은 결과를 만드는지 입증하는 것입니다.",
              "Improvement-execution controls (L1) and bounded candidate search (L2) are implemented. Next: establish whether runs inheriting accepted changes outperform a fixed-strategy control.",
            )}</p>
            <p>{t(locale,
              "현재 표시는 코드 범위이며 자율성 등급 인증이 아닙니다. 경험 선택(L3), 배포 적응(L4), 개선 메커니즘의 계승(L5)은 각각 별도 증거가 필요합니다.",
              "These labels describe code scope, not certified autonomy levels. Experience acquisition (L3), deployment adaptation (L4), and recursive inheritance (L5) each need separate evidence.",
            )}</p>
          </div>
          <div className="landing-inline-links">
            <Link href={`/docs/explanation/rsi-roadmap?lang=${locale}`}>{t(locale, "현재 위치·용어·다음 검증", "Current scope, terms, and next tests")}</Link>
            <a href="https://arxiv.org/abs/2609.11873v2">{t(locale, "설계 가이드: RSI 백서 v2", "Design guide: RSI whitepaper v2")}</a>
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
          <a href={`/geode/resaerch/jev-system1-offloading/?lang=${locale}`}>{t(locale, "Jev 연구 보고서", "Jev research report")}</a>
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
