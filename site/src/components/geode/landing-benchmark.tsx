"use client";

import evidence from "@/data/geode/landing-evidence.json";
import { t, useLocale } from "./locale-context";

export function BenchmarkComparison() {
  const locale = useLocale();
  const paired = evidence.paired;
  const rows = [
    { name: "GEODE", passes: paired.geodePasses },
    { name: "native Codex", passes: paired.nativePasses },
  ];
  const signed = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
  const sourceLinks = [
    [t(locale, "분석", "Analysis"), paired.sources.analysis.url],
    [t(locale, "사전 등록 조건", "Preregistered protocol"), paired.sources.spec.url],
    [t(locale, "결과 데이터", "Result data"), paired.sources.data.url],
    [t(locale, "통계 근거", "Statistical provenance"), paired.sources.statistics.url],
    [t(locale, "증거 영상 (한국어/영어)", "Evidence film (KO/EN)"), paired.sources.video.url],
  ];

  return (
    <div className="text-[var(--ink)]">
      <p className="max-w-3xl text-base leading-relaxed text-[var(--ink-2)]">
        {t(
          locale,
          `Terminal-Bench 2.1에서 ${paired.model}, ${paired.reasoning} 추론, OpenAI 구독 경로를 사용했습니다. ${paired.harness}가 같은 작업과 canonical verifier를 실행했습니다. 비교 대상은 ${paired.comparator}입니다.`,
          `Both runtimes used ${paired.model}, ${paired.reasoning} reasoning, and the OpenAI subscription route on Terminal-Bench 2.1. ${paired.harness} supplied the same tasks and canonical verifiers. The comparator was ${paired.comparator}.`,
        )}
      </p>

      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-[var(--ink-2)]">
        {t(locale,
          "GEODE 측정군은 b549f3e의 thin AgenticLoop adapter로, custom system_prompt_override와 terminal_exec-only 도구 표면을 사용했습니다. 현재 native/full-runtime 구성의 성능으로 일반화하지 않습니다.",
          "The GEODE arm used b549f3e's thin AgenticLoop adapter with a custom system_prompt_override and terminal_exec-only tools. This does not measure today's native/full-runtime configuration.",
        )}
      </p>

      <table className="mt-8 w-full border-collapse text-left">
        <caption className="caption-top pb-4 text-left text-sm leading-relaxed text-[var(--ink-2)]">
          <span className="block text-base tabular-nums text-[var(--ink)]">
            {t(
              locale,
              `${paired.frozenTrialsPerArm}회 계획 − 환경 미지원 ${paired.excludedTasks.length * paired.repetitions}회 − 짝 비교 불가 ${paired.unresolvedNativeTrials}회 = 공통 유효 ${paired.commonTrials}회`,
              `${paired.frozenTrialsPerArm} planned − ${paired.excludedTasks.length * paired.repetitions} environment-unavailable − ${paired.unresolvedNativeTrials} unmatched = ${paired.commonTrials} common valid trials`,
            )}
          </span>
          <span className="mt-2 block">
            {t(
              locale,
              `native Codex의 인프라 무효 ${paired.unresolvedNativeTrials}회와 대응하는 GEODE 결과도 함께 제외했습니다. 정상 실행 후 실패한 결과는 분모에 남깁니다. 막대 범위는 0~100%입니다.`,
              `The ${paired.unresolvedNativeTrials} infrastructure-invalid native Codex trials and their GEODE counterparts are excluded. Valid task failures remain in the denominator. Bar scale: 0-100%.`,
            )}
          </span>
        </caption>
        <thead className="border-b border-[var(--rule)] text-sm text-[var(--ink-2)]">
          <tr>
            <th scope="col" className="pb-3 pr-3 font-medium">{t(locale, "런타임", "Runtime")}</th>
            <th scope="col" className="pb-3 pr-3 font-medium">{t(locale, "성공 / 유효", "Passed / valid")}</th>
            <th scope="col" className="w-[40%] pb-3 font-medium">{t(locale, "성공률", "Pass rate")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const rate = (row.passes / paired.commonTrials) * 100;
            return (
              <tr key={row.name} className="border-b border-[var(--rule)]">
                <th scope="row" className="py-6 pr-3 text-base font-medium">{row.name}</th>
                <td className="py-6 pr-3 text-base tabular-nums">{row.passes}/{paired.commonTrials}</td>
                <td className="py-6 text-lg tabular-nums">
                  {rate.toFixed(2)}%
                  <div
                    aria-hidden="true"
                    className={`mt-2 h-0.5 ${row.name === "GEODE" ? "bg-[var(--acc-artifact)]" : "bg-[var(--ink-2)]"}`}
                    style={{ width: `${rate}%` }}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="mt-6 max-w-3xl text-base leading-relaxed tabular-nums">
        {t(
          locale,
          `작업별 동일 가중치 차이는 ${signed(paired.taskBalancedDeltaPp)}%p이며, 작업 단위 bootstrap 95% 구간은 ${signed(paired.taskBootstrap95Pp[0])}~${signed(paired.taskBootstrap95Pp[1])}%p입니다.`,
          `The task-balanced difference was ${signed(paired.taskBalancedDeltaPp)} percentage points; the 95% task-bootstrap interval was ${signed(paired.taskBootstrap95Pp[0])} to ${signed(paired.taskBootstrap95Pp[1])} percentage points.`,
        )}
      </p>
      <p className="mt-3 max-w-3xl text-base leading-relaxed text-[var(--ink-2)]">
        {t(
          locale,
          "사전 등록한 전체 지표는 측정 불가이며 결론은 미확정입니다. 구간이 0을 포함하므로 성능 우위를 입증하지 않습니다. 이 결과는 로컬 짝 비교 진단이며 공식 리더보드 점수가 아닙니다.",
          "The preregistered full-suite primary is not measurable; the decision is inconclusive. The interval includes zero and does not establish superiority. This is a local paired-runtime diagnostic, not an official leaderboard score.",
        )}
      </p>

      <details className="mt-6 max-w-3xl text-sm leading-relaxed text-[var(--ink-2)]">
        <summary className="min-h-11 cursor-pointer py-3 text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--acc-artifact)]">
          {t(locale, "제외된 작업과 비교 한계", "Exclusions and comparison limits")}
        </summary>
        <p className="mt-3">
          {t(
            locale,
            `${paired.frozenTasks}개 작업을 ${paired.repetitions}회씩, 런타임당 ${paired.frozenTrialsPerArm}회 실행하도록 등록했습니다. ${paired.excludedTasks.join(", ")}의 amd64 verifier를 arm64 호스트에서 실행할 수 없어 양쪽에서 대칭 제외했습니다. native Codex의 ${paired.unresolvedNativeTrials}회는 보충 한도 이후에도 인프라 무효로 남았습니다.`,
            `The protocol registered ${paired.frozenTasks} tasks with ${paired.repetitions} repetitions, or ${paired.frozenTrialsPerArm} trials per runtime. ${paired.excludedTasks.join(" and ")} were excluded symmetrically because their amd64 verifiers could not run on the arm64 host. ${paired.unresolvedNativeTrials} native Codex trials remained infrastructure-invalid after their supplement caps.`,
          )}
        </p>
        <p className="mt-3">
          {t(
            locale,
            "인프라 무효를 모델의 0점 실패로 바꾸지 않았습니다. Harbor는 공유 seed 제어를 제공하지 않았고, 여러 날에 걸친 실행에서 시점·공급자 용량·인증 계정의 영향은 하네스 효과와 분리되지 않습니다.",
            "Infrastructure-invalid trials were not converted into semantic zeroes. Harbor exposed no shared seed control. The run spanned several days; timing, provider capacity, and credential-principal effects cannot be separated from harness effects.",
          )}
        </p>
      </details>

      <ul className="mt-5 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        {sourceLinks.map(([label, url]) => (
          <li key={url}>
            <a
              href={url}
              className="inline-flex min-h-11 items-center text-[var(--acc-artifact)] underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--acc-artifact)]"
            >
              {label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
