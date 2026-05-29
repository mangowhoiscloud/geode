"use client";

import { LocaleProvider } from "@/components/geode/locale-context";
import { GeodeNav } from "@/components/geode/sections/nav";
import { HeroSection } from "@/components/geode/sections/hero";
import { ActHeader } from "@/components/geode/sections/act-header";
import { SelfHostingDefinitionSection } from "@/components/geode/sections/self-hosting-definition";
import { OsThesisSection } from "@/components/geode/sections/os-thesis";
import { OsPrimitivesMapSection } from "@/components/geode/sections/os-primitives-map";
import { RecursionSection } from "@/components/geode/sections/recursion";
import { ComputeAbiSection } from "@/components/geode/sections/compute-abi";
import { RoutingIqSection } from "@/components/geode/sections/routing-iq";
import { KanbanSection } from "@/components/geode/sections/kanban";
import { ScaffoldSection } from "@/components/geode/sections/scaffold";
import { LoopSection } from "@/components/geode/sections/loop";
import { ReasoningSection } from "@/components/geode/sections/reasoning";
import { ArchitectureSection } from "@/components/geode/sections/architecture";
import { GatewaySection } from "@/components/geode/sections/gateway";
import { ConcurrencySection } from "@/components/geode/sections/concurrency";
import { HeadlessSection } from "@/components/geode/sections/headless";
import { SchedulerSection } from "@/components/geode/sections/scheduler";
import { HooksSection } from "@/components/geode/sections/hooks";
import { AgentsTasksSection } from "@/components/geode/sections/agents-tasks";
import { ToolUseSection } from "@/components/geode/sections/tool-use";
import { ContextTiersSection } from "@/components/geode/sections/context-tiers";
import { MultiLlmSection } from "@/components/geode/sections/multi-llm";
import { FeedbackSection } from "@/components/geode/sections/feedback";
import { VerificationSection } from "@/components/geode/sections/verification";
import { OrchestrationSection } from "@/components/geode/sections/orchestration";
import { AutomationSection } from "@/components/geode/sections/automation";
import { BootstrapSection } from "@/components/geode/sections/bootstrap";
import { TimelineSection } from "@/components/geode/sections/timeline";
import { GeodeFooter } from "@/components/geode/sections/footer";

const actLink =
  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors";

export default function GeodePage() {
  return (
    <LocaleProvider>
      <main className="min-h-screen bg-[var(--paper)] text-[var(--ink)] overflow-x-hidden">
        <GeodeNav />

        {/* Opening: what GEODE is */}
        <div id="hero"><HeroSection /></div>
        <div id="definition"><SelfHostingDefinitionSection /></div>
        <div id="thesis"><OsThesisSection /></div>
        <div id="primitives"><OsPrimitivesMapSection /></div>
        <div id="recursion"><RecursionSection /></div>

        {/* Act I: the inner loop */}
        <ActHeader
          id="act-inner"
          eyebrow="Act I . The inner loop"
          title="How GEODE runs one task"
          titleKo="한 작업을 처리하는 법"
          body="The inner loop is a while(tool_use) agent. Within a round cap and a set of termination paths, it reasons, calls a tool, reads the result, and decides the next step. Everything below feeds that loop: how it reasons, which tools it reaches for, the context it assembles, and how it routes across models."
          bodyKo="안쪽 루프는 while(tool_use) 에이전트입니다. 라운드 상한과 종료 경로 안에서 추론하고, 도구를 호출하고, 결과를 읽어 다음 단계를 정합니다. 아래의 모든 조각이 이 루프를 떠받칩니다. 어떻게 추론하고, 어떤 도구를 집어 들고, 어떤 컨텍스트를 조립하며, 모델 사이를 어떻게 라우팅하는지입니다."
        />
        <div id="loop"><LoopSection /></div>
        <div id="reasoning"><ReasoningSection /></div>
        <div id="tools"><ToolUseSection /></div>
        <div id="context"><ContextTiersSection /></div>
        <div id="llm"><MultiLlmSection /></div>
        <div id="compute-abi"><ComputeAbiSection /></div>
        <div id="routing-iq"><RoutingIqSection /></div>

        {/* Act II: the harness */}
        <ActHeader
          id="act-harness"
          eyebrow="Act II . The harness"
          title="How a task gets served"
          titleKo="그 루프가 서빙되는 법"
          body="One daemon runs the loop for every entry point: a CLI call, a messaging gateway, a scheduled job. The harness is what turns a single loop into a running system. Process layout and boot order, concurrency lanes, the scheduler, the hook bus every subsystem listens on, and the sub-agents a task can spawn."
          bodyKo="하나의 데몬이 모든 진입점에서 이 루프를 돌립니다. CLI 호출이든, 메신저 게이트웨이든, 예약된 작업이든 같습니다. 하네스는 단일 루프를 살아 있는 시스템으로 만드는 층입니다. 프로세스 구성과 부팅 순서, 동시성 레인, 스케줄러, 모든 서브시스템이 듣는 훅 버스, 그리고 한 작업이 띄우는 서브에이전트입니다."
        />
        <div id="architecture"><ArchitectureSection /></div>
        <div id="gateway"><GatewaySection /></div>
        <div id="concurrency"><ConcurrencySection /></div>
        <div id="headless"><HeadlessSection /></div>
        <div id="scheduler"><SchedulerSection /></div>
        <div id="hooks"><HooksSection /></div>
        <div id="agents"><AgentsTasksSection /></div>
        <div id="orchestration"><OrchestrationSection /></div>
        <div id="bootstrap"><BootstrapSection /></div>

        {/* Act III: the outer loop (the signature) */}
        <ActHeader
          id="act-outer"
          eyebrow="Act III . The outer loop"
          title="How GEODE improves itself"
          titleKo="GEODE가 스스로를 개선하는 법"
          body="This is what makes GEODE more than a harness. An outer loop mutates the scaffolding the inner loop runs on, audits the result against an adversarial safety rubric, and promotes the change only when it clears a hard floor on the critical dimensions. No weights are touched, and the test set itself is co-evolved alongside the agent."
          bodyKo="GEODE를 단순한 하네스 이상으로 만드는 부분입니다. 바깥쪽 루프는 안쪽 루프가 올라타는 스캐폴드를 변형하고, 그 결과를 적대적 안전 루브릭으로 감사한 뒤, 핵심 차원의 하한선을 넘겼을 때만 변경을 승격합니다. 가중치는 건드리지 않으며, 평가용 테스트 세트 자체가 에이전트와 함께 진화합니다."
        >
          <div className="flex flex-wrap items-center gap-3">
            <a href="/geode/docs/capabilities/autoresearch" className={actLink}>The closed loop →</a>
            <a href="/geode/self-improving/" className={actLink}>Live hub →</a>
            <a href="/geode/self-improving/petri-bundle/" className={actLink}>Audit transcripts →</a>
          </div>
        </ActHeader>
        <div id="feedback"><FeedbackSection /></div>
        <div id="automation"><AutomationSection /></div>
        <div id="verify"><VerificationSection /></div>

        {/* Act IV: positioning (framing only) */}
        <ActHeader
          id="act-positioning"
          eyebrow="Act IV . Where it sits"
          title="An honest place in the lineage"
          titleKo="계보 위의 정직한 자리"
          body="The self-improvement loop is not new. Promptbreeder, STOP, ADAS, DGM, and GEPA built the lineage. GEODE's contribution is a recombination. It re-aims that loop from capability to safety, from weights to scaffolding, and runs it on co-evolved adversarial seeds. That is an empty cell in the design space, not a new primitive."
          bodyKo="자기개선 루프는 새로운 것이 아닙니다. Promptbreeder, STOP, ADAS, DGM, GEPA가 그 계보를 닦았습니다. GEODE의 기여는 재조합입니다. 그 루프를 능력에서 안전으로, 가중치에서 스캐폴드로 다시 겨냥하고, 함께 진화하는 적대적 seed 위에서 돌립니다. 새로운 primitive가 아니라, 설계 공간의 비어 있던 칸입니다."
        >
          <a href="/geode/docs/capabilities/lineage" className={actLink}>Lineage and positioning →</a>
        </ActHeader>

        {/* Act V: how it was built */}
        <ActHeader
          id="act-build"
          eyebrow="Act V . The build"
          title="Built by its own scaffold"
          titleKo="자기 자신의 스캐폴드로 빌드한"
          body="GEODE is built with the same primitives it runs. The development scaffold, the board, and the release line apply the agent's own patterns to itself. The timeline below is how that compounded, chapter by chapter."
          bodyKo="GEODE는 자신이 실행하는 것과 같은 기본 단위로 빌드됩니다. 개발 스캐폴드와 보드, 릴리스 라인은 에이전트의 패턴을 자기 자신에게 적용한 결과입니다. 아래 타임라인은 그것이 어떻게 챕터를 거듭하며 쌓였는지입니다."
        />
        <div id="scaffold"><ScaffoldSection /></div>
        <div id="kanban"><KanbanSection /></div>
        <div id="timeline"><TimelineSection /></div>

        <GeodeFooter />
      </main>
    </LocaleProvider>
  );
}
