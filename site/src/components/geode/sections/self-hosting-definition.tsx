"use client";

import { useLocale, t } from "../locale-context";

/**
 * Single shared definition of the master neologism.
 * Sits between hero and Ch01 (os-thesis), so every chapter below
 * can reference the term without redefining it.
 */
export function SelfHostingDefinitionSection() {
  const locale = useLocale();
  return (
    <section className="relative py-16 px-6">
      <div className="max-w-3xl mx-auto">
        <div className="rounded-lg border border-[var(--rule)] bg-[var(--paper-2)] px-6 py-6">
          <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--acc-line)] mb-3">
            {t(locale, "용어 정의", "Term")}
          </div>
          <h3 className="font-display font-semibold text-[var(--ink-1)] text-xl md:text-2xl leading-snug mb-3">
            {t(
              locale,
              "Self-hosting agent harness.",
              "Self-hosting agent harness."
            )}
          </h3>
          <p className="text-[var(--ink-2)] leading-[1.7] text-[14.5px]">
            {t(
              locale,
              "컴파일러 분야에서 self-hosting은 자기 자신을 컴파일하는 컴파일러를 가리킵니다. GEODE는 그 의미를 에이전트로 옮긴 결과입니다. 출시되는 자율 에이전트의 출력 안정성을 보장하는 규율과, 그 에이전트를 빌드하는 라인의 안정성을 보장하는 규율이 동일한 패턴을 사용합니다. 두 규율이 같은 형태라는 사실이 Ch 04의 9행 표 한 장으로 노출됩니다.",
              "In compilers, self-hosting names a compiler that compiles itself. GEODE applies the same idea to agents. The discipline that keeps the shipped agent's output stable and the discipline that keeps the build line stable share the same pattern. Chapter 04 puts that self-consistency into a single 9-row table."
            )}
          </p>
        </div>
      </div>
    </section>
  );
}
