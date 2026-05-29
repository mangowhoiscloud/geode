"use client";

import { useLocale, t } from "../locale-context";

const values = [
  {
    id: "V0",
    title: "Agentic OS",
    titleKo: "에이전틱 OS",
    body: "LLM = compute. Agent = its OS. GEODE implements that diagram.",
    bodyKo: "LLM은 compute. 에이전트는 그것의 OS. GEODE는 그 도식의 구현.",
  },
  {
    id: "V1",
    title: "Domain Portability",
    titleKo: "도메인 이식성",
    body: "Two apps. One harness. Zero rewrite.",
    bodyKo: "두 앱. 한 하네스. 재작성 없음.",
  },
  {
    id: "V2",
    title: "Verification Layer",
    titleKo: "검증 계층",
    body: "G1-G4 + panel guard + Cross-LLM + Karpathy P4 hash ratchet.",
    bodyKo: "G1-G4 + panel guard + Cross-LLM + Karpathy P4 해시 래칫.",
  },
  {
    id: "V3",
    title: "Compute ABI",
    titleKo: "Compute ABI",
    body: "One ABI across providers. R1-R9 reasoning wire audit. GLM thinking is GEODE-only.",
    bodyKo: "프로바이더를 단일 ABI로. R1-R9 리즈닝 와이어 감사. GLM thinking 활성화는 GEODE 단독.",
  },
  {
    id: "V4",
    title: "Routing IQ",
    titleKo: "라우팅 IQ",
    body: "Plan-aware quota panel. Equivalence-class routing. Credential breadcrumb.",
    bodyKo: "플랜 인식 쿼터 패널. 동등성 클래스 라우팅. 자격증명 breadcrumb.",
  },
  {
    id: "V5",
    title: "Operator Discipline",
    titleKo: "운영 규율",
    body: "Solo. Ratchet discipline, zero regression. Built by its own scaffold.",
    bodyKo: "단독 개발. ratchet 규율로 회귀 없이. 자기 스캐폴드로 구축.",
  },
];

export function OsThesisSection() {
  const locale = useLocale();
  return (
    <section className="relative py-24 px-6">
      <div className="max-w-5xl mx-auto">
        <div className="mb-12">
          <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--ink-3)] mb-3">
            {t(locale, "§ 1. 출발점", "§ 1. THESIS")}
          </div>
          <h2 className="font-display font-bold tracking-tight text-3xl md:text-4xl text-[var(--ink-1)] leading-tight">
            {t(locale, "에이전트를 운영체제로 본다는 것.", "Treating the agent as an operating system.")}
          </h2>
          <p className="mt-4 text-[var(--ink-2)] max-w-2xl leading-relaxed text-[15px]">
            {t(
              locale,
              "2023년 11월 안드레이 카르파시는 ‘Intro to Large Language Models’ 강연에서 LLM-OS 다이어그램을 제시했습니다. 가운데에 LLM이 위치하고, 주위에 도구·파일시스템·다른 LLM·임베딩 공간이 배치된 구조였습니다. GEODE는 그 다이어그램을 실제 코드로 구현한 사례입니다. LLM은 커널을, 런타임은 시스템콜과 드라이버를, 하네스는 셸과 init을, 에이전트는 항상 동작하는 실행 루프를 담당합니다.",
              "In November 2023, Andrej Karpathy presented an LLM-OS diagram in his talk “Intro to Large Language Models.” The model sits at the center, with tools, a filesystem, other LLMs, and embedding spaces arranged around it. GEODE implements that diagram in production code. The LLM takes the kernel role, the runtime handles syscalls and drivers, the harness handles the shell and init, and the agent runs the always-on execution loop."
            )}
          </p>
          <p className="mt-3 text-[var(--ink-2)] max-w-2xl leading-relaxed text-[15px]">
            {t(
              locale,
              "이 운영체제를 빌드하는 파이프라인도 동일한 패턴을 씁니다. 출시되는 시스템 측에서는 프롬프트 해시 20개가 잠금장치(ratchet)로 고정되고, 빌드 측에서는 CI 5단계가 잠금장치로 고정됩니다. 출력 안정성을 보장하는 규율과 빌드 안정성을 보장하는 규율이 같은 형태로 동작합니다.",
              "The pipeline that builds the system follows the same pattern. On the shipping side, 20 prompt hashes are pinned as a ratchet; on the build side, five CI stages are pinned the same way. The rule that keeps output stable and the rule that keeps the build stable have the same shape."
            )}
          </p>
          {/* Cumulative stats line removed. Lead with character, not counts. */}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {values.map((v) => (
            <div
              key={v.id}
              className="rounded-lg border border-[var(--rule)] hover:border-[var(--ink-3)] p-4 transition-colors"
            >
              <div className="flex items-baseline gap-3 mb-2">
                <span className="text-[10px] font-mono uppercase tracking-widest text-[var(--acc-artifact)]">
                  {v.id}
                </span>
                <span className="font-display font-semibold text-[var(--ink-1)] text-base">
                  {locale === "ko" ? v.titleKo : v.title}
                </span>
              </div>
              <p className="text-[13px] text-[var(--ink-2)] leading-relaxed">
                {locale === "ko" ? v.bodyKo : v.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
