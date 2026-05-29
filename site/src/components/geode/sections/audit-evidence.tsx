"use client";

import { useLocale, t } from "../locale-context";

/**
 * AuditEvidenceSection. How it is measured: evidence, not adjectives.
 *
 * Every candidate change is scored against a multi-dimensional safety rubric.
 * Critical safety dimensions sit behind a hard floor, so a change that
 * regresses them is rejected outright (a veto). Auxiliary dimensions only
 * penalize upward drift. A change is promoted only on a real gain past the
 * noise floor, otherwise the baseline is restored. The table states the
 * rubric STRUCTURE only. No score number is cited, because none exist to
 * cite. The rubric is rendered as a mono evidence panel that reads like an
 * audit log readout, not a generic table: a --code-bg panel, mono headers,
 * petri-blue on the critical-floor row label, hairline rows. The live scores
 * and full auditor transcripts are published, linked below.
 */
type RubricRow = {
  axisKo: string;
  axisEn: string;
  ruleKo: string;
  ruleEn: string;
  /** The critical-floor row, highlighted in petri-blue. */
  critical?: boolean;
};

const rubricRows: RubricRow[] = [
  {
    axisKo: "핵심 차원",
    axisEn: "critical dimensions",
    ruleKo: "하드 플로어. 어느 차원이든 후퇴하면 변경을 거부합니다 (veto).",
    ruleEn: "hard floor. any regression rejects the change (veto).",
    critical: true,
  },
  {
    axisKo: "보조 차원",
    axisEn: "auxiliary dimensions",
    ruleKo: "위쪽으로 드리프트하면 패널티를 줍니다.",
    ruleEn: "upward drift is penalized.",
  },
  {
    axisKo: "승격 게이트",
    axisEn: "promote gate",
    ruleKo: "노이즈 수준을 넘는 이득이 있을 때만 승격하고, 아니면 되돌립니다.",
    ruleEn: "promote only on a gain past the noise floor, else revert.",
  },
];

export function AuditEvidenceSection() {
  const locale = useLocale();
  return (
    <section className="px-6 py-20">
      <div className="max-w-3xl mx-auto">
        <div className="font-mono text-[11px] tracking-[0.24em] uppercase text-[var(--acc-artifact)]">
          How it is measured
        </div>
        <h2 className="mt-3 font-display tracking-tight text-[var(--ink)] text-[clamp(1.7rem,3.6vw,2.4rem)] leading-[1.12] font-semibold">
          {t(locale, "적대적 감사로 측정", "Measured by an adversarial audit")}
        </h2>
        <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(
            locale,
            "후보 변경은 모두 다차원 안전 루브릭으로 채점됩니다. 핵심 안전 차원은 하드 플로어 뒤에 있어서, 이 차원을 후퇴시키는 변경은 그 자리에서 거부됩니다. 변경은 노이즈 수준을 넘어서는 실제 이득이 있을 때만 승격되고, 그렇지 않으면 기준선으로 되돌립니다.",
            "Every candidate change is scored against a multi-dimensional safety rubric. Critical safety dimensions sit behind a hard floor, so a change that regresses them is rejected outright. A change is promoted only on a real, significant gain past the noise floor, otherwise the baseline is restored."
          )}
        </p>

        <div className="mt-8 rounded border border-[var(--rule)] bg-[var(--code-bg)] overflow-x-auto">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--rule)] font-mono text-[10px] tracking-[0.2em] uppercase text-[var(--ink-3)]">
            <span>{t(locale, "안전 루브릭", "safety rubric")}</span>
            <span>{t(locale, "규칙", "rule")}</span>
          </div>
          <div className="font-mono text-[12.5px] leading-relaxed">
            {rubricRows.map((row, index) => (
              <div
                key={row.axisEn}
                className="flex flex-col sm:flex-row gap-y-1 sm:gap-x-4 px-4 py-3"
                style={{
                  borderTop: index === 0 ? "none" : "1px solid var(--rule)",
                }}
              >
                <div
                  className="sm:w-[34%] shrink-0"
                  style={{ color: row.critical ? "var(--acc-artifact)" : "var(--ink-1)" }}
                >
                  {row.critical && <span className="text-[var(--acc-artifact)]">{"⏺"}</span>}{" "}
                  {t(locale, row.axisKo, row.axisEn)}
                </div>
                <div className="text-[var(--ink-2)]">{t(locale, row.ruleKo, row.ruleEn)}</div>
              </div>
            ))}
          </div>
        </div>

        <p className="mt-5 text-[var(--ink-2)] leading-[1.75] text-[14px]">
          {t(
            locale,
            "라이브 점수와 감사 트랜스크립트 전문은 공개되어 있습니다.",
            "The live scores and full auditor transcripts are published."
          )}
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-2.5">
          <a
            href="/geode/self-improving/"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors"
          >
            {t(locale, "라이브 허브", "Live hub")} {"→"}
          </a>
          <a
            href="/geode/self-improving/petri-bundle/"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors"
          >
            {t(locale, "감사 트랜스크립트", "Audit transcripts")} {"→"}
          </a>
        </div>
      </div>
    </section>
  );
}
