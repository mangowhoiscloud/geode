"use client";

import { useEffect, useRef, useState } from "react";
import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { useLocale, t } from "../locale-context";

/* ── PSM 6-Weight Components ── */
const weights = [
  { name: "Exposure Lift", w: 0.25, color: "#F5C542" },
  { name: "Quality", w: 0.20, color: "#818CF8" },
  { name: "Recovery", w: 0.18, color: "#4ECDC4" },
  { name: "Growth", w: 0.12, color: "#34D399" },
  { name: "Momentum", w: 0.20, color: "#C084FC" },
  { name: "Developer", w: 0.05, color: "#60A5FA" },
];

/* ── Tiers ── */
const tiers = [
  { tier: "S", threshold: "≥ 80", color: "#F5C542" },
  { tier: "A", threshold: "≥ 60", color: "#818CF8" },
  { tier: "B", threshold: "≥ 40", color: "#4ECDC4" },
  { tier: "C", threshold: "< 40", color: "#5A6A8A" },
];

/* ── 14-axis evaluators ── */
const evaluators = [
  { name: "Quality Judge", axes: 8, labels: "A–C, B1, C1–C2, M, N", color: "#818CF8" },
  { name: "Hidden Value", axes: 3, labels: "D, E, F", color: "#4ECDC4" },
  { name: "Community Momentum", axes: 3, labels: "J, K, L", color: "#C084FC" },
];

/* ── Radar Chart: each axis individually shoots out from center ── */
const CX = 150, CY = 150, R = 110;
const ANIM_DURATION = 500; // ms — fast snap
const STAGGER = 60; // ms between each axis

function easeOutCubic(t: number) { return 1 - Math.pow(1 - t, 3); }

// Target positions for each weight
const targets = weights.map((w, i) => {
  const a = (Math.PI * 2 * i) / 6 - Math.PI / 2;
  const r = R * (w.w / 0.25);
  return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) };
});

function RadarChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [progress, setProgress] = useState<number[]>(weights.map(() => 0)); // 0→1 per axis
  const startedRef = useRef(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !startedRef.current) {
          startedRef.current = true;
          const t0 = performance.now();
          function tick(now: number) {
            const elapsed = now - t0;
            const next = weights.map((_, i) => {
              const axisElapsed = Math.max(0, elapsed - i * STAGGER);
              const raw = Math.min(1, axisElapsed / ANIM_DURATION);
              return easeOutCubic(raw);
            });
            setProgress(next);
            if (elapsed < ANIM_DURATION + STAGGER * (weights.length - 1) + 100) {
              requestAnimationFrame(tick);
            }
          }
          requestAnimationFrame(tick);
        }
      },
      { threshold: 0.3 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Interpolated positions
  const current = progress.map((p, i) => ({
    x: CX + (targets[i].x - CX) * p,
    y: CY + (targets[i].y - CY) * p,
  }));

  const polyPoints = current.map((c) => `${c.x},${c.y}`).join(" ");
  const allDone = progress.every((p) => p >= 1);

  return (
    <div ref={containerRef} className="flex justify-center">
      <svg viewBox="0 0 300 300" className="w-full max-w-[280px]">
        {/* Static hex grid */}
        {[0.33, 0.66, 1.0].map((scale) => (
          <polygon
            key={scale}
            points={weights.map((_, i) => {
              const a = (Math.PI * 2 * i) / 6 - Math.PI / 2;
              const r = R * scale;
              return `${CX + r * Math.cos(a)},${CY + r * Math.sin(a)}`;
            }).join(" ")}
            fill="none" stroke="white" strokeOpacity={0.06} strokeWidth={1}
          />
        ))}
        {/* Static axis lines */}
        {weights.map((_, i) => {
          const a = (Math.PI * 2 * i) / 6 - Math.PI / 2;
          return <line key={i} x1={CX} y1={CY} x2={CX + R * Math.cos(a)} y2={CY + R * Math.sin(a)} stroke="white" strokeOpacity={0.06} strokeWidth={1} />;
        })}

        {/* Animated data polygon */}
        <polygon
          points={polyPoints}
          fill="#818CF8" fillOpacity={allDone ? 0.12 : 0.08}
          stroke="#818CF8" strokeOpacity={allDone ? 0.4 : 0.2}
          strokeWidth={1.5}
          style={{ transition: allDone ? "fill-opacity 0.5s, stroke-opacity 0.5s" : undefined }}
        />

        {/* Animated axis lines from center → current position */}
        {current.map((c, i) => (
          <line key={`al-${i}`} x1={CX} y1={CY} x2={c.x} y2={c.y} stroke={weights[i].color} strokeOpacity={progress[i] * 0.2} strokeWidth={1} />
        ))}

        {/* Animated vertex dots */}
        {current.map((c, i) => (
          <circle
            key={`ad-${i}`}
            cx={c.x} cy={c.y}
            r={progress[i] > 0.1 ? 4 : 0}
            fill={weights[i].color}
            fillOpacity={progress[i] * 0.8}
          />
        ))}

        {/* Glow pulse after complete */}
        {allDone && (
          <polygon
            points={targets.map((t) => `${t.x},${t.y}`).join(" ")}
            fill="none" stroke="#818CF8" strokeWidth={2} strokeOpacity={0}
          >
            <animate attributeName="stroke-opacity" values="0.3;0" dur="1.5s" begin="0s" repeatCount="1" fill="freeze" />
            <animate attributeName="stroke-width" values="2;8" dur="1.5s" begin="0s" repeatCount="1" fill="freeze" />
          </polygon>
        )}

        {/* Labels (always visible) */}
        {weights.map((w, i) => {
          const a = (Math.PI * 2 * i) / 6 - Math.PI / 2;
          const lx = CX + 130 * Math.cos(a);
          const ly = CY + 130 * Math.sin(a);
          return (
            <g key={w.name}>
              <text x={lx} y={ly - 5} textAnchor="middle" fill={w.color} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{w.name}</text>
              <text x={lx} y={ly + 8} textAnchor="middle" fill={w.color} fillOpacity={0.5} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>{(w.w * 100).toFixed(0)}%</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function ScoringSection() {
  const locale = useLocale();
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(245,197,66,0.015)_0%,transparent_60%)] pointer-events-none" />
      <div className="relative z-10 max-w-5xl mx-auto">
        <SectionHeader
          variant="side"
          label="Scoring"
          labelColor="#F5C542"
          title="PSM 6-Weight Composite"
          description={t(locale,
            "4명 Analyst(Clean Context) × 14축 독립 평가, 3명 Evaluator 교차 집계. 6-Weight 합산 + Confidence Multiplier. confidence < 0.7이면 최대 5회 loopback.",
            "4 Analysts (Clean Context) x 14-axis independent evaluation, 3 Evaluators cross-aggregated. 6-Weight sum + Confidence Multiplier. Loopback up to 5 times if confidence < 0.7."
          )}
        />

        {/* ── Radar: expands from center to weight positions ── */}
        <ScrollReveal delay={0.1}>
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr] gap-8 mb-8">
            <RadarChart />

            {/* Formula + Tiers */}
            <div className="space-y-5">
              <div className="rounded-xl border border-white/[0.04] px-5 py-4">
                <div className="text-xs font-mono text-[#9BB0CC] mb-2">Composite Formula</div>
                <code className="text-sm text-white/70 leading-relaxed block">
                  Base = Σ(weight<sub>i</sub> × score<sub>i</sub>)<br />
                  Final = Base × (0.7 + 0.3 × confidence/100)
                </code>
              </div>
              <div className="flex gap-2">
                {tiers.map((t) => (
                  <div key={t.tier} className="flex-1 text-center px-3 py-2.5 rounded-lg border border-white/[0.04]">
                    <div className="text-xl font-bold" style={{ color: t.color }}>{t.tier}</div>
                    <div className="text-[11px] font-mono text-[#9BB0CC]">{t.threshold}</div>
                  </div>
                ))}
              </div>
              <div className="space-y-2">
                {evaluators.map((e) => (
                  <div key={e.name} className="flex items-center gap-3 px-4 py-2 rounded-lg border border-white/[0.04]" style={{ background: `${e.color}03` }}>
                    <span className="text-sm font-semibold" style={{ color: e.color }}>{e.name}</span>
                    <span className="text-xs text-[#9BB0CC]">{e.axes}축 ({e.labels})</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* Fixture results */}
        <ScrollReveal delay={0.2}>
          <div className="mt-8 rounded-xl border border-white/[0.04] px-5 py-4">
            <div className="text-sm font-semibold text-white/70 mb-3">{locale === "en" ? "Fixture Analysis Results" : "Fixture 분석 결과"}</div>
            <div className="space-y-2 font-mono text-sm">
              {[
                { name: "Berserk", score: "81.2", tier: "S", color: "#F5C542" },
                { name: "Cowboy Bebop", score: "68.4", tier: "A", color: "#818CF8" },
                { name: "Ghost in the Shell", score: "51.7", tier: "B", color: "#4ECDC4" },
              ].map((f) => (
                <div key={f.name} className="flex items-center justify-between px-3 py-2 rounded-lg border border-white/[0.03]">
                  <span className="text-white/60">{f.name}</span>
                  <div className="flex items-center gap-3">
                    <span style={{ color: f.color }} className="font-bold">{f.score}</span>
                    <span className="text-xs px-1.5 py-0.5 rounded" style={{ color: f.color, background: `${f.color}12` }}>{f.tier}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
