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
    <section className="px-6 py-24">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-2">
          <span className="h-px w-6 bg-[var(--acc-artifact)]" />
          <span className="text-[12px] tracking-[0.22em] uppercase text-[var(--acc-artifact)] font-medium">
            How it works
          </span>
        </div>
        <h2 className="mt-4 font-display tracking-tight text-[var(--ink)] text-[clamp(1.85rem,3.8vw,2.6rem)] leading-[1.12] font-semibold">
          {t(locale, "두 개의 루프", "Two loops")}
        </h2>
        <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(
            locale,
            "안쪽의 에이전트 루프는 하나의 작업을 실행합니다. 바깥쪽 루프는 작업을 실행하는 시스템 자체를 튜닝합니다. 안쪽 루프는 트랜스크립트와 결과를 남기고, 바깥쪽 루프는 그 기록을 읽어 다음번 안쪽 루프의 동작 방식을 바꿉니다.",
            "An inner agentic loop runs a single task. An outer loop tunes the system that runs tasks. The inner loop produces transcripts and outcomes, and the outer loop reads those to change how the inner loop behaves next time."
          )}
        </p>

        <div className="mt-10 flex justify-center">
          <svg
            viewBox="0 0 560 320"
            className="w-full max-w-xl h-auto"
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
                markerWidth="8"
                markerHeight="8"
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
              x="16"
              y="16"
              width="528"
              height="288"
              rx="20"
              fill="none"
              stroke="var(--acc-line)"
              strokeWidth="1.75"
            />
            <text
              x="280"
              y="46"
              textAnchor="middle"
              fill="var(--acc-line)"
              fontSize="14"
              fontFamily="var(--font-fira-code), ui-monospace, monospace"
              letterSpacing="0.5"
            >
              mutate {"→"} audit {"→"} promote / revert
            </text>
            {/* Outer loop return arrow along the bottom edge */}
            <path
              d="M 440 288 L 120 288"
              fill="none"
              stroke="var(--acc-line)"
              strokeWidth="1.75"
              markerEnd="url(#two-loops-head-outer)"
            />

            {/* Inner loop (petri-blue, dominant). artifact / runtime, nested inside */}
            <rect
              x="92"
              y="84"
              width="376"
              height="152"
              rx="16"
              fill="none"
              stroke="var(--acc-artifact)"
              strokeWidth="3"
            />
            <text
              x="280"
              y="116"
              textAnchor="middle"
              fill="var(--acc-artifact)"
              fontSize="15"
              fontWeight="500"
              fontFamily="var(--font-fira-code), ui-monospace, monospace"
              letterSpacing="0.5"
            >
              reason {"→"} call tool {"→"} observe
            </text>
            {/* Inner loop return arrow along the inner bottom edge */}
            <path
              d="M 392 216 L 168 216"
              fill="none"
              stroke="var(--acc-artifact)"
              strokeWidth="3"
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
