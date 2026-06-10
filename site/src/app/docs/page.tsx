"use client";

import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { DOCS_SITEMAP } from "@/lib/geode-docs/sitemap";
import { useLocale, t } from "@/components/geode/locale-context";

export default function DocsIndex() {
  const locale = useLocale();
  const summaryEn =
    "A general-purpose autonomous execution agent for research, analysis, automation, and scheduling. Its signature: an outer loop that improves the system itself, kept honest by an adversarial safety audit.";
  const summaryKo =
    "리서치, 분석, 자동화, 스케줄 작업을 수행하는 범용 자율 실행 에이전트. 시그니처는 시스템 자체를 개선하는 바깥쪽 루프이고, 그 과정을 적대적 안전 감사가 검증합니다.";
  return (
    <DocsShell
      slug=""
      title="GEODE Documentation"
      titleKo="GEODE 문서"
      summary={summaryEn}
      summaryKo={summaryKo}
    >
      <Bi
        ko={
          <>
            <h2>GEODE는 무엇인가</h2>
            <p>
              GEODE는 <strong>범용 자율 실행 에이전트</strong>입니다. 리서치,
              분석, 자동화, 스케줄 작업을 CLI와 메신저(Slack, Discord,
              Telegram)에서 수행하고, <code>geode-mcp</code> 서버로 다른
              에이전트에 도구로 붙습니다. 진입점은 <code>geode</code>와{" "}
              <code>geode-mcp</code> 둘이며, 어느 쪽으로 들어와도 같은{" "}
              <a href="/geode/docs/architecture/overview">5-계층 스택</a>
              (Model, Runtime, Harness, Agent, Self-Improving)을 지납니다.
            </p>
            <p>
              그 본체 위의 시그니처가 <strong>자기개선 루프</strong>입니다. 모델
              가중치와 파라미터는 절대 건드리지 않습니다. 갱신 대상은 모델을
              감싼 스캐폴드, 곧 시스템 프롬프트 섹션과 behaviour kinds이고,
              메커니즘은 변이와 선택입니다. 변화의 적합도는 능력 벤치마크가
              아니라 <strong>적대적 안전 감사</strong>(Petri 급의 다차원
              감사)로 측정하며, 핵심 안전 차원에는 하한선이 있어 그 선을 넘어
              후퇴하는 변화는 거부합니다. 평가에 쓰는 seed도 고정돼 있지
              않습니다. co-scientist 파이프라인이 에이전트와 나란히 적대적 seed
              분포를 키웁니다.
            </p>
            <h2>두 개의 루프</h2>
            <p>
              GEODE 를 가르는 핵심은 <strong>두 개의 루프</strong>입니다.
            </p>
            <ul>
              <li>
                <strong>Inner loop (Agentic Loop)</strong>. 한 작업을 푸는{" "}
                <code>while(tool_use)</code> 실행 루프입니다. 라운드 상한과 종료
                경로 안에서 도구를 지연 로딩하며 일을 끝까지 처리합니다.
              </li>
              <li>
                <strong>Outer loop (Self-Improving Loop)</strong>. 작업을 처리하는
                시스템 자체를 다듬는 폐루프입니다. 스캐폴드를 변형하고, 감사하고,
                결과를 귀속한 뒤, 실제 이득이 있을 때만 승격하고 아니면 되돌립니다.
                정직한 (1+1) 챔피언 체인입니다.
              </li>
            </ul>
            <p>
              루프의 계보(Promptbreeder, STOP, ADAS, DGM, GEPA)는 이미 잘 닦여
              있습니다. GEODE 는 그 루프를 능력에서 안전으로, 가중치에서
              스캐폴드로, 그리고 함께 진화하는 적대적 seed 위로 다시 겨냥합니다.
              새로운 primitive 가 아니라, 비어 있던 칸을 채우는 재조합입니다.
            </p>
          </>
        }
        en={
          <>
            <h2>What GEODE is</h2>
            <p>
              GEODE is a <strong>general-purpose autonomous execution
              agent</strong>. It runs research, analysis, automation, and
              scheduled work from the CLI and from messengers (Slack, Discord,
              Telegram), and it attaches to other agents as a tool through the{" "}
              <code>geode-mcp</code> server. There are two entry points,{" "}
              <code>geode</code> and <code>geode-mcp</code>, and both pass
              through the same{" "}
              <a href="/geode/docs/architecture/overview">5-layer stack</a>{" "}
              (Model, Runtime, Harness, Agent, Self-Improving).
            </p>
            <p>
              On top of that body sits its signature: the{" "}
              <strong>self-improving loop</strong>. It never updates model
              weights or parameters. What changes is the scaffold around the
              model, the system-prompt sections and behaviour kinds, and the
              mechanism is mutation and selection. Its fitness signal is an{" "}
              <strong>adversarial safety audit</strong> (Petri-grade,
              multi-dimensional), not a capability benchmark, and critical
              safety dimensions sit behind a hard floor: a change that
              regresses them is rejected. The evaluation seeds are not fixed
              either. A co-scientist pipeline grows an adversarial seed
              distribution alongside the agent.
            </p>
            <h2>Two loops</h2>
            <p>The defining idea is <strong>two loops</strong>:</p>
            <ul>
              <li>
                <strong>Inner loop (the Agentic Loop)</strong>. The{" "}
                <code>while(tool_use)</code> primitive that solves one task. It
                works through a task within a round cap and a set of termination
                paths, loading tools on demand.
              </li>
              <li>
                <strong>Outer loop (the Self-Improving Loop)</strong>. A closed
                loop that tunes the system that runs tasks. It mutates the
                scaffolding, audits the result, attributes it, then promotes on a
                real gain and otherwise reverts. An honest (1+1) champion chain.
              </li>
            </ul>
            <p>
              The loop lineage (Promptbreeder, STOP, ADAS, DGM, GEPA) is
              well-established. GEODE re-aims it from capability to safety, from
              weights to scaffolding, on co-evolved adversarial seeds. A
              recombination occupying an empty cell, not a new primitive.
            </p>
          </>
        }
      />

      <Bi
        ko={
          <>
            <h2>레퍼런스: GEODE의 좌표부터</h2>
            <p>
              레퍼런스의 진입점은 검증 절차가 아니라{" "}
              <strong>자기개선 폐루프의 계보와 좌표</strong>입니다. GEODE가 어떤
              프론티어 시스템에서 무엇을 빌려오고, 어디서 갈라지는지부터 짚습니다.
            </p>
            <ul>
              <li>
                <a href="/geode/docs/reference/frontier-comparison">프론티어 비교</a>.
                Claude Code, Codex CLI, OpenClaw, Hermes에서 빌려온 것과 갈라지는 지점.
              </li>
              <li>
                <a href="/geode/docs/capabilities/lineage">계보와 좌표</a>. 이 루프가
                self-evolving agents 문헌에서 어디에 위치하는지.
              </li>
              <li>
                <a href="/geode/docs/capabilities/co-scientist">Co-scientist 루프</a>.
                적대적 seed 분포를 함께 진화시키는 다중 역할 루프.
              </li>
              <li>
                <a href="/geode/docs/reference/external-references">외부 참고</a>. GEODE가
                인용하는 frontier 시스템과 선행 작업.
              </li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Reference: GEODE&apos;s position first</h2>
            <p>
              The reference entry point leads with the{" "}
              <strong>self-improving loop&apos;s lineage and position</strong>, not the
              validation machinery. Start with what GEODE borrows from frontier
              systems and where it differs.
            </p>
            <ul>
              <li>
                <a href="/geode/docs/reference/frontier-comparison">Frontier comparison</a>.
                What GEODE borrows from Claude Code, Codex CLI, OpenClaw, Hermes, and where it differs.
              </li>
              <li>
                <a href="/geode/docs/capabilities/lineage">Lineage and positioning</a>.
                Where this loop sits in the self-evolving agents literature.
              </li>
              <li>
                <a href="/geode/docs/capabilities/co-scientist">Co-scientist loop</a>.
                The multi-role loop that co-evolves the adversarial seed distribution.
              </li>
              <li>
                <a href="/geode/docs/reference/external-references">External references</a>.
                The frontier systems and prior work GEODE cites.
              </li>
            </ul>
          </>
        }
      />

      <h2>{t(locale, "섹션", "Sections")}</h2>
      <div className="not-prose mt-3 border-t border-[var(--rule)]">
        {DOCS_SITEMAP.map((section) => (
          <a
            key={section.id}
            href={`/geode/docs/${section.pages[0]?.slug ?? ""}`}
            className="flex flex-col gap-0.5 border-b border-[var(--rule)] py-3 group"
          >
            <span className="font-display font-semibold text-[var(--ink)] group-hover:text-[var(--acc-soft)]">
              <span className="mr-2 text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
                {section.id}
              </span>
              {t(locale, section.titleKo, section.title)}
            </span>
            <span className="text-sm text-[var(--ink-2)]">
              {section.pages.slice(0, 4).map((p, i) => (
                <span key={p.slug}>
                  {i > 0 && ", "}
                  {t(locale, p.titleKo, p.title)}
                </span>
              ))}
              {section.pages.length > 4 && ", …"}
            </span>
          </a>
        ))}
      </div>

      <Bi
        ko={
          <>
            <h2>다음에 어디로</h2>
            <ul>
              <li>
                <a href="/geode/docs/overview/how-it-runs">GEODE가 작업을 처리하는 흐름</a>.
                요청 하나가 처음부터 끝까지 어떻게 흐르는지 따라갑니다.
              </li>
              <li>
                <a href="/geode/docs/concepts/two-loops">두 개의 루프</a>. 나머지
                문서가 기대는 멘탈 모델입니다.
              </li>
              <li>
                <a href="/geode/docs/capabilities/autoresearch">자기개선 루프(폐루프)</a>.
                스캐폴드를 변형하고, 감사하고, 승격하거나 되돌리는 바깥쪽 루프입니다.
              </li>
              <li>
                <a href="/geode/docs/capabilities/lineage">계보와 좌표</a>. 이
                루프가 self-evolving agents 문헌에서 어디에 위치하는지 짚습니다.
              </li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Where to go next</h2>
            <ul>
              <li>
                <a href="/geode/docs/overview/how-it-runs">How GEODE runs a task</a>.
                One request, traced end to end.
              </li>
              <li>
                <a href="/geode/docs/concepts/two-loops">The two loops</a>. The
                mental model the rest of the docs build on.
              </li>
              <li>
                <a href="/geode/docs/capabilities/autoresearch">The self-improving loop</a>.
                The outer loop that mutates the scaffolding, audits, and promotes
                or reverts.
              </li>
              <li>
                <a href="/geode/docs/capabilities/lineage">Lineage and positioning</a>.
                Where this loop sits in the self-evolving agents literature.
              </li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
