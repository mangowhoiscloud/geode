"use client";

import { useLocale, t } from "../locale-context";

/**
 * LineagePositioningSection. The trust beat.
 *
 * The self-improvement loop is not new, a lineage built it. GEODE's
 * contribution is a recombination: it re-aims that loop from capability to
 * safety, from weights to scaffolding, and runs it on co-evolved adversarial
 * seeds. That is an empty cell in the design space, not a new primitive. The
 * influences render as a definition list (not cards), each term the influence
 * and each definition the one line of what GEODE took from it.
 */
type Influence = {
  nameKo: string;
  nameEn: string;
  tookKo: string;
  tookEn: string;
};

const influences: Influence[] = [
  {
    nameKo: "Karpathy LLM-OS",
    nameEn: "Karpathy LLM-OS",
    tookKo: "에이전트를 운영체제로 보는 틀을 가져왔습니다.",
    tookEn: "The agent-as-OS framing.",
  },
  {
    nameKo: "Darwin Godel Machine / STOP / ADAS",
    nameEn: "Darwin Godel Machine / STOP / ADAS",
    tookKo: "평가 게이트 아래에서 스캐폴드를 스스로 고쳐 쓰는 구조를 가져왔습니다.",
    tookEn: "Self-modifying scaffolding under an evaluation gate.",
  },
  {
    nameKo: "GEPA / TextGrad",
    nameEn: "GEPA / TextGrad",
    tookKo: "가중치를 건드리지 않는 반성 기반 변형을 가져왔습니다.",
    tookEn: "Reflective, weight-free mutation.",
  },
  {
    nameKo: "Rainbow Teaming / Petri",
    nameEn: "Rainbow Teaming / Petri",
    tookKo: "공진화한 적대적 시드와 안전 감사를 가져왔습니다.",
    tookEn: "Co-evolved adversarial seeds and a safety audit.",
  },
];

export function LineagePositioningSection() {
  const locale = useLocale();
  return (
    <section className="px-6 py-20">
      <div className="max-w-3xl mx-auto">
        <div className="font-mono text-[11px] tracking-[0.24em] uppercase text-[var(--acc-artifact)]">
          Where it sits
        </div>
        <h2 className="mt-3 font-display tracking-tight text-[var(--ink)] text-[clamp(1.7rem,3.6vw,2.4rem)] leading-[1.12] font-semibold">
          {t(locale, "계보 위의 정직한 자리", "An honest place in the lineage")}
        </h2>
        <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(
            locale,
            "자기 개선 루프는 새롭지 않습니다. Promptbreeder, STOP, ADAS, DGM, GEPA가 계보를 쌓았습니다. GEODE의 기여는 재조합입니다. 그 루프를 능력에서 안전으로, 가중치에서 스캐폴드로 다시 겨누고, 공진화한 적대적 시드 위에서 돌립니다. 새로운 원형이 아니라 설계 공간의 빈 칸입니다.",
            "The self-improvement loop is not new. Promptbreeder, STOP, ADAS, DGM, and GEPA built the lineage. GEODE's contribution is a recombination. It re-aims that loop from capability to safety, from weights to scaffolding, and runs it on co-evolved adversarial seeds. That is an empty cell in the design space, not a new primitive."
          )}
        </p>

        <dl className="mt-8">
          {influences.map((influence) => (
            <div
              key={influence.nameEn}
              className="border-t border-[var(--rule)] py-3 first:border-t-0"
            >
              <dt className="font-mono text-[13px] text-[var(--ink-1)]">
                {t(locale, influence.nameKo, influence.nameEn)}
              </dt>
              <dd className="mt-1 text-[var(--ink-2)] leading-[1.6] text-[15px]">
                {t(locale, influence.tookKo, influence.tookEn)}
              </dd>
            </div>
          ))}
        </dl>

        <a
          href="/geode/docs/capabilities/lineage"
          className="mt-8 inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors"
        >
          {t(locale, "계보와 좌표", "Lineage and positioning")} {"→"}
        </a>
      </div>
    </section>
  );
}
