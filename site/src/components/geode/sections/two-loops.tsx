"use client";

import { useLocale, t } from "../locale-context";

/**
 * TwoLoopsSection. The one mental model.
 *
 * GEODE runs two nested loops. The inner agentic loop runs a single task
 * (reason, call a tool, observe, repeat). The outer loop tunes the system
 * that runs tasks (mutate, audit, promote or revert). The inner loop
 * produces transcripts and outcomes; the outer loop reads those and changes
 * how the inner loop behaves next time. The visual nests the inner loop
 * (amethyst, artifact / runtime) inside the outer loop (citrine, scaffold /
 * process) so the containment relationship is legible at a glance.
 */
export function TwoLoopsSection() {
  const locale = useLocale();
  return (
    <section className="px-6 py-20">
      <div className="max-w-3xl mx-auto">
        <div className="font-mono text-[11px] tracking-[0.24em] uppercase text-[var(--acc-artifact)]">
          How it works
        </div>
        <h2 className="mt-3 font-display tracking-tight text-[var(--ink)] text-[clamp(1.7rem,3.6vw,2.4rem)] leading-[1.12] font-semibold">
          {t(locale, "두 개의 루프", "Two loops")}
        </h2>
        <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(
            locale,
            "안쪽의 에이전트 루프는 하나의 작업을 실행합니다. 바깥쪽 루프는 작업을 실행하는 시스템 자체를 튜닝합니다. 안쪽 루프는 트랜스크립트와 결과를 남기고, 바깥쪽 루프는 그 기록을 읽어 다음번 안쪽 루프의 동작 방식을 바꿉니다.",
            "An inner agentic loop runs a single task. An outer loop tunes the system that runs tasks. The inner loop produces transcripts and outcomes, and the outer loop reads those to change how the inner loop behaves next time."
          )}
        </p>

        <div className="mt-8 flex justify-center">
          <svg
            viewBox="0 0 460 280"
            className="w-full max-w-[460px] h-auto"
            role="img"
            aria-label={t(
              locale,
              "바깥쪽 루프 안에 안쪽 루프가 중첩된 구조",
              "An inner loop nested inside an outer loop"
            )}
          >
            <defs>
              <marker
                id="two-loops-head-inner"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--acc-artifact)" />
              </marker>
              <marker
                id="two-loops-head-outer"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--acc-line)" />
              </marker>
            </defs>

            {/* Outer loop (citrine). scaffold / process */}
            <rect
              x="14"
              y="14"
              width="432"
              height="252"
              rx="18"
              fill="none"
              stroke="var(--acc-line)"
              strokeWidth="1.5"
            />
            <text
              x="230"
              y="40"
              textAnchor="middle"
              fill="var(--acc-line)"
              fontSize="12.5"
              fontFamily="var(--font-fira-code), ui-monospace, monospace"
              letterSpacing="0.5"
            >
              mutate {"→"} audit {"→"} promote / revert
            </text>
            {/* Outer loop return arrow along the bottom edge */}
            <path
              d="M 360 252 L 100 252"
              fill="none"
              stroke="var(--acc-line)"
              strokeWidth="1.5"
              markerEnd="url(#two-loops-head-outer)"
            />

            {/* Inner loop (amethyst). artifact / runtime, nested inside */}
            <rect
              x="78"
              y="74"
              width="304"
              height="132"
              rx="14"
              fill="none"
              stroke="var(--acc-artifact)"
              strokeWidth="1.5"
            />
            <text
              x="230"
              y="98"
              textAnchor="middle"
              fill="var(--acc-artifact)"
              fontSize="12.5"
              fontFamily="var(--font-fira-code), ui-monospace, monospace"
              letterSpacing="0.5"
            >
              reason {"→"} call tool {"→"} observe
            </text>
            {/* Inner loop return arrow along the inner bottom edge */}
            <path
              d="M 320 192 L 140 192"
              fill="none"
              stroke="var(--acc-artifact)"
              strokeWidth="1.5"
              markerEnd="url(#two-loops-head-inner)"
            />
          </svg>
        </div>

        <div className="mt-5 flex flex-col gap-2 text-[14px] text-[var(--ink-2)]">
          <div className="flex items-center gap-2.5">
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ background: "var(--acc-artifact)" }}
            />
            <span>{t(locale, "안쪽 루프: 한 작업을 실행합니다.", "Inner loop: runs one task.")}</span>
          </div>
          <div className="flex items-center gap-2.5">
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ background: "var(--acc-line)" }}
            />
            <span>{t(locale, "바깥쪽 루프: 시스템을 튜닝합니다.", "Outer loop: tunes the system.")}</span>
          </div>
        </div>

        <a
          href="/geode/docs/concepts/two-loops"
          className="mt-6 inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors"
        >
          {t(locale, "두 루프 자세히", "The two loops")} {"→"}
        </a>
      </div>
    </section>
  );
}
