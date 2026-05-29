"use client";

import { useLocale, t } from "../locale-context";

/**
 * SelfEvolvingSection. The differentiator.
 *
 * GEODE improves by mutating the scaffolding around itself (system prompt,
 * tool policy, decomposition, reflection, skills), never the model weights.
 * The change is non-parametric: the weights are frozen and only the harness
 * around them moves. Each candidate change is measured by an adversarial
 * safety audit (Petri-grade). The three-row table states the contract:
 * what mutates, what never mutates, and how the change is measured. Below it,
 * a cycle-flow visual shows the SHAPE of the outer loop, mutate then audit
 * then attribute then promote-or-revert, in petri-blue mono labels over a
 * hairline. No fabricated fitness numbers.
 */
const cycleSteps: { ko: string; en: string }[] = [
  { ko: "정책 변형", en: "mutate a policy" },
  { ko: "감사 (안전 루브릭)", en: "audit (safety rubric)" },
  { ko: "기여도 분석", en: "attribute" },
  { ko: "승격 또는 되돌림", en: "promote or revert" },
];

export function SelfEvolvingSection() {
  const locale = useLocale();
  return (
    <section className="px-6 py-20">
      <div className="max-w-3xl mx-auto">
        <div className="font-mono text-[11px] tracking-[0.24em] uppercase text-[var(--acc-artifact)]">
          The differentiator
        </div>
        <h2 className="mt-3 font-display tracking-tight text-[var(--ink)] text-[clamp(1.7rem,3.6vw,2.4rem)] leading-[1.12] font-semibold">
          {t(locale, "self-evolving, 비-파라메트릭", "Self-evolving, non-parametric")}
        </h2>
        <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(
            locale,
            "GEODE는 자기 자신을 둘러싼 스캐폴딩을 바꾸면서 개선됩니다. 모델 가중치는 절대 건드리지 않습니다.",
            "GEODE improves by mutating the scaffolding around itself, never the model weights."
          )}
        </p>

        <div className="mt-8 rounded-lg border border-[var(--rule)] overflow-x-auto">
          <table className="w-full text-[14px] border-collapse">
            <thead>
              <tr className="bg-[var(--paper-2)]">
                <th className="text-left p-3 border border-[var(--rule)] font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)] w-[26%]">
                  {t(locale, "측면", "Aspect")}
                </th>
                <th className="text-left p-3 border border-[var(--rule)] font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)]">
                  {t(locale, "값", "Value")}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="p-3 border border-[var(--rule)] font-mono text-[12px] text-[var(--acc-artifact)] align-top">
                  {t(locale, "바꾸는 것", "mutates")}
                </td>
                <td className="p-3 border border-[var(--rule)] text-[var(--ink-2)] leading-relaxed align-top">
                  {t(
                    locale,
                    "스캐폴딩: 시스템 프롬프트, 도구 정책, 작업 분해, 리플렉션, 스킬",
                    "scaffolding: system prompt, tool policy, decomposition, reflection, skills"
                  )}
                </td>
              </tr>
              <tr>
                <td className="p-3 border border-[var(--rule)] font-mono text-[12px] text-[var(--acc-artifact)] align-top">
                  {t(locale, "절대 안 바꾸는 것", "never")}
                </td>
                <td className="p-3 border border-[var(--rule)] text-[var(--ink-2)] leading-relaxed align-top">
                  {t(locale, "모델 가중치", "model weights")}
                </td>
              </tr>
              <tr>
                <td className="p-3 border border-[var(--rule)] font-mono text-[12px] text-[var(--acc-artifact)] align-top">
                  {t(locale, "측정 방법", "measured by")}
                </td>
                <td className="p-3 border border-[var(--rule)] text-[var(--ink-2)] leading-relaxed align-top">
                  {t(
                    locale,
                    "적대적 안전 감사 (Petri 등급)",
                    "an adversarial safety audit (Petri-grade)"
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="mt-6 rounded border border-[var(--rule)] bg-[var(--code-bg)] p-4">
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-[var(--ink-3)]">
            {t(locale, "외부 루프", "outer loop")}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-2 font-mono text-[12.5px]">
            {cycleSteps.map((step, index) => (
              <span key={step.en} className="flex items-center gap-x-2">
                <span className="text-[var(--acc-artifact)]">{t(locale, step.ko, step.en)}</span>
                {index < cycleSteps.length - 1 && (
                  <span className="text-[var(--ink-3)]">{"→"}</span>
                )}
              </span>
            ))}
            <span className="text-[var(--ink-3)]">{"↺"}</span>
          </div>
        </div>
        <p className="mt-3 text-[var(--ink-2)] leading-[1.75] text-[14px]">
          {t(
            locale,
            "한 사이클의 모양입니다. 변형이 승격되면 다음 사이클의 기준선이 되고, 되돌려지면 같은 기준선에서 다시 시작합니다.",
            "The shape of one cycle. A promoted mutation becomes the next cycle's baseline; a reverted one restarts from the same baseline."
          )}
        </p>

        <a
          href="/geode/docs/capabilities/autoresearch"
          className="mt-6 inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors"
        >
          {t(locale, "폐루프 보기", "The closed loop")} {"→"}
        </a>
      </div>
    </section>
  );
}
