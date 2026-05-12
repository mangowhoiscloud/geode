"use client";

import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { useLocale, t } from "../locale-context";

const phases = [
  { id: 1, name: "Collection", color: "#60A5FA", desc: "자동 스코어, 휴먼 레이팅, 전문가 피드백 수집. 통계적 파워 분석(최소 n=10, 권장 n=30)으로 충분한 샘플 확보.", descEn: "Collect auto scores, human ratings, and expert feedback. Statistical power analysis (min n=10, recommended n=30) ensures sufficient samples.", detail: "auto scores + human ratings + expert feedback" },
  { id: 2, name: "Analysis", color: "#818CF8", desc: "Spearman 상관계수(파워 게이트: n<10이면 스킵) + CUSUM 드리프트 감지. 4개 메트릭(spearman_rho, human_llm_alpha, precision@10, tier_accuracy) 모니터링.", descEn: "Spearman correlation (power gate: skip if n<10) + CUSUM drift detection. Monitor 4 metrics (spearman_rho, human_llm_alpha, precision@10, tier_accuracy).", detail: "Spearman + CUSUM drift on 4 metrics" },
  { id: 3, name: "Improvement", color: "#F5C542", desc: "rho<0.5이면 가중치 재조정, 드리프트 감지 시 베이스라인 재보정 제안. 선택적 승인 게이트 적용 후 반영.", descEn: "Retune weights if rho < 0.5, suggest baseline recalibration on drift detection. Applied after optional approval gate.", detail: "retune weights, recalibrate baselines" },
  { id: 4, name: "Validation", color: "#34D399", desc: "개선안의 기대 vs 실제 메트릭 향상 검증. 각 후보별 품질 기준 충족 여부 확인.", descEn: "Verify expected vs. actual metric improvement of proposed changes. Confirm quality criteria met for each candidate.", detail: "expected vs actual metric improvement" },
  { id: 5, name: "RLAIF", color: "#C084FC", desc: "AI 피드백이 휴먼 피드백을 보강. 전문가 레이팅으로 합성 선호 쌍 생성, 4개 헌법 원칙(정확성, 보정 일관성, 공정성, 투명성) 체크.", descEn: "AI feedback augments human feedback. Generate synthetic preference pairs from expert ratings, checking 4 constitutional principles (accuracy, calibration consistency, fairness, transparency).", detail: "synthetic pairs + 4 constitutional checks" },
];

export function FeedbackSection() {
  const locale = useLocale();
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <SectionHeader
          variant="minimal"
          title="5-Phase Self-Improvement"
          description={t(locale,
            "파이프라인 실행 결과를 수집, 분석, 개선, 검증, RLAIF 5단계로 순환하여 스코어링 정확도를 자율적으로 개선합니다. 성공 시 ModelRegistry에 프로모션합니다.",
            "Pipeline results cycle through 5 phases (Collection, Analysis, Improvement, Validation, RLAIF) to autonomously improve scoring accuracy. Successful improvements are promoted to ModelRegistry."
          )}
        />

        {/* 5-Phase SVG */}
        <ScrollReveal delay={0.1}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 750 170" className="w-full min-w-[560px]" style={{ maxHeight: 200 }}>
              {phases.map((p, i) => {
                const x = 20 + i * 146;
                const w = 130;
                return (
                  <g key={p.id}>
                    <rect x={x} y={25} width={w} height={60} rx={10} fill="#0C1220" stroke={p.color} strokeWidth={0.8} strokeOpacity={0.4} />
                    <text x={x + w / 2} y={50} textAnchor="middle" fill={p.color} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>{p.name}</text>
                    <text x={x + w / 2} y={68} textAnchor="middle" fill={p.color} fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">Phase {p.id}</text>
                    {i < 4 && (
                      <path d={`M${x + w},55 C${x + w + 5},50 ${x + w + 11},50 ${x + w + 16},55`} stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />
                    )}
                  </g>
                );
              })}
              {/* Loopback — smooth U-arc below all boxes */}
              <path d="M730,85 C735,120 680,140 400,145 C120,140 30,120 20,85" fill="none" stroke="#F5C542" strokeOpacity={0.25} strokeWidth={1.2} strokeDasharray="5 4" className="animate-flow" />
              <text x={375} y={155} textAnchor="middle" fill="#F5C542" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">cycle → ModelRegistry promotion</text>
            </svg>
          </div>
        </ScrollReveal>

        {/* Phase details */}
        <ScrollReveal delay={0.15}>
          <div className="space-y-2">
            {phases.map((p) => (
              <div key={p.id} className="flex items-start gap-4 px-4 py-3 rounded-lg border border-white/[0.04]" style={{ background: `${p.color}03` }}>
                <span className="shrink-0 w-7 text-center text-[11px] font-mono font-bold mt-0.5" style={{ color: p.color }}>{p.id}</span>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-semibold text-white/80">{p.name}</span>
                    <span className="text-[10px] font-mono text-[#9BB0CC]">{p.detail}</span>
                  </div>
                  <p className="text-sm text-[#A0B4D4] leading-relaxed">{locale === "en" ? p.descEn : p.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </ScrollReveal>

        {/* Trigger Types (F1-F4) */}
        <ScrollReveal delay={0.2}>
          <div className="mt-8 rounded-xl border border-white/[0.04] px-5 py-4 mb-6">
            <div className="text-sm font-semibold text-white/70 mb-3">Trigger Types (F1-F4)</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              {[
                { id: "F1", name: "MANUAL",    color: "#60A5FA", desc: "사용자 직접 실행", descEn: "User-initiated execution", dispatch: "fire_manual()" },
                { id: "F2", name: "SCHEDULED",  color: "#818CF8", desc: "Cron 시간 기반",   descEn: "Cron-based scheduling", dispatch: "check_scheduled()" },
                { id: "F3", name: "EVENT",      color: "#4ECDC4", desc: "HookEvent 반응",   descEn: "HookEvent reactive", dispatch: "make_event_handler()" },
                { id: "F4", name: "WEBHOOK",    color: "#F5C542", desc: "외부 HTTP POST",   descEn: "External HTTP POST", dispatch: "handle_webhook()" },
              ].map((tr) => (
                <div key={tr.id} className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: `${tr.color}04` }}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-mono font-bold" style={{ color: tr.color }}>{tr.id}</span>
                    <span className="text-xs font-semibold text-white/70">{tr.name}</span>
                  </div>
                  <div className="text-xs text-[#9BB0CC] mb-1.5">{locale === "en" ? tr.descEn : tr.desc}</div>
                  <code className="text-[10px] font-mono text-white/20">{tr.dispatch}</code>
                </div>
              ))}
            </div>
          </div>
        </ScrollReveal>

        {/* CUSUM Drift Detection + Trigger Chain */}
        <ScrollReveal delay={0.25}>
          <div className="rounded-xl border border-white/[0.04] px-5 py-4 mb-6">
            <div className="text-sm font-semibold text-white/70 mb-3">CUSUM Drift Detection</div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              {[
                { zone: "NONE", range: "< 2.5", color: "#34D399", desc: "정상. 드리프트 미감지.", descEn: "Normal. No drift detected." },
                { zone: "WARNING", range: "2.5 ~ 4.0", color: "#F5C542", desc: "모니터링 강화. PSI 0.10~0.25.", descEn: "Enhanced monitoring. PSI 0.10~0.25." },
                { zone: "CRITICAL", range: "≥ 4.0", color: "#E87080", desc: "DRIFT_DETECTED hook 발화. 재분석 트리거.", descEn: "DRIFT_DETECTED hook fires. Triggers reanalysis." },
              ].map((z) => (
                <div key={z.zone} className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: `${z.color}04` }}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full" style={{ background: z.color }} />
                    <span className="text-sm font-mono font-bold" style={{ color: z.color }}>{z.zone}</span>
                    <span className="text-xs font-mono text-[#9BB0CC] ml-auto">{z.range}</span>
                  </div>
                  <div className="text-xs text-[#A0B4D4]">{locale === "en" ? z.descEn : z.desc}</div>
                </div>
              ))}
            </div>
            <div className="text-xs text-[#9BB0CC] font-mono mb-4">
              4 metrics: spearman_rho(0.50) · human_llm_alpha(0.80) · precision@10(0.60) · tier_accuracy(0.70)
            </div>

            {/* Drift → Trigger → Reanalysis chain */}
            <div className="border-t border-white/[0.04] pt-4">
              <div className="text-xs font-semibold text-white/50 mb-3">Drift → Trigger → Reanalysis</div>
              <div className="space-y-1.5">
                {[
                  { step: "CUSUM Detector",  detail: "4 metrics 모니터링. 임계치 초과 감지", detailEn: "Monitor 4 metrics. Detect threshold breach", color: "#E87080" },
                  { step: "DRIFT_DETECTED",  detail: "HookEvent 발화 → TriggerManager 전달", detailEn: "HookEvent fires → forwarded to TriggerManager", color: "#F5C542" },
                  { step: "P70 DriftTrigger", detail: "F3 EVENT trigger → 재분석 파이프라인", detailEn: "F3 EVENT trigger → reanalysis pipeline", color: "#4ECDC4" },
                  { step: "P80 DriftSnapshot", detail: "SnapshotManager → 상태 캡처 보존", detailEn: "SnapshotManager → state capture and retention", color: "#818CF8" },
                  { step: "P90 DriftLogger",  detail: "구조화 로깅 → journal/errors.jsonl", detailEn: "Structured logging → journal/errors.jsonl", color: "#60A5FA" },
                ].map((d, i) => (
                  <div key={d.step} className="flex items-center gap-3">
                    <span className="shrink-0 w-5 h-5 rounded flex items-center justify-center text-[9px] font-mono font-bold"
                      style={{ color: d.color, background: `${d.color}10` }}>{i + 1}</span>
                    <span className="text-xs font-medium text-white/60 w-[130px] shrink-0 font-mono">{d.step}</span>
                    <span className="text-xs text-[#9BB0CC]">{locale === "en" ? d.detailEn : d.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
