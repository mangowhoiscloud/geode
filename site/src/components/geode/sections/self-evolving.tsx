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
 * what mutates, what never mutates, and how the change is measured.
 */
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
