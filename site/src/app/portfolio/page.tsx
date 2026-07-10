"use client";

import "@astryxdesign/theme-neutral/theme.css";
import "@astryxdesign/core/astryx.css";
import "./astryx-geode.css";

import { Token } from "@astryxdesign/core/Token";
import { motion, useReducedMotion } from "framer-motion";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";

import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { LocaleProvider, t, useLocale } from "@/components/geode/locale-context";
import { GeodeFooter } from "@/components/geode/sections/footer";
import { GeodeNav } from "@/components/geode/sections/nav";
import { BENCHMARK_GROUPS } from "@/data/geode/benchmark-measurements";
import { GEODE_SOT } from "@/data/geode/sot";
import { galmuri } from "@/fonts/galmuri";
import { serifDisplay } from "@/fonts/serif";

import { firstRelease, latestRelease, peakWeek, releaseCount, weeklyCadence } from "./growth";

/**
 * GEODE portfolio v11 — growth log, landing-grade pass.
 *
 * v10 introduced the character-sheet + growth-log concept; v11 raises it to
 * landing-page level (reference: claude.com/product/claude-code): a centered
 * hero whose product moment is a terminal mock of the REAL CLI welcome screen
 * (core/ui/mascot.py layout, core/ui/geodi_art.py sprite), a bento band
 * (character sheet aside + tau2/MCPMark bench matrix + tech stack), and the
 * measured growth log. Display font is Galmuri11 (pixel, matches the dot
 * mascot); no decorative arrows; Astryx components themed via astryx-geode.css.
 */

const navItems = [
  { id: "hero", label: "Intro" },
  { id: "run", label: "Run" },
  { id: "features", label: "Features" },
  { id: "lab", label: "Specimen" },
];

const surfaceChips = ["CLI", "MCP server", "Slack", "cron", "Gateway daemon"];


const MONTH_LABELS: Record<string, string> = {
  "03": "Mar",
  "04": "Apr",
  "05": "May",
  "06": "Jun",
  "07": "Jul",
  "08": "Aug",
};

/** Sprite with a discoverable click reaction: three quick pixel hops. */
function PlayfulSprite({ scale, blink, className }: { scale?: number; blink?: boolean; className?: string }) {
  const [hopping, setHopping] = useState(false);
  return (
    <button
      type="button"
      aria-label="Geodi"
      title="Geodi"
      className={`cursor-pointer ${className ?? ""}`}
      onClick={() => {
        setHopping(true);
        window.setTimeout(() => setHopping(false), 750);
      }}
    >
      <GeodiSprite scale={scale} blink={blink} className={hopping ? "geodi-hop" : undefined} />
    </button>
  );
}

/* ---------------- hero: terminal product moment -------------------------- */

function TerminalMock() {
  const locale = useLocale();
  return (
    <figure className="mx-auto w-full max-w-2xl">
      <div className="overflow-hidden rounded-lg border border-[var(--rule)] bg-[var(--paper-deep)] text-left">
        <div className="flex items-center gap-2 border-b border-[var(--rule-soft)] px-4 py-2.5">
          <span className="flex gap-1.5">
            {[0, 1, 2].map((dot) => (
              <span
                key={dot}
                className="h-[9px] w-[9px] rounded-full border border-[var(--rule)] bg-[var(--paper-2)]"
              />
            ))}
          </span>
          <span className="ml-2 font-mono text-[11px] text-[var(--ink-3)]">geode</span>
        </div>
        <div className="px-5 py-5 sm:px-7">
          <div className="flex items-center gap-6">
            <PlayfulSprite scale={5} blink className="geodi-bob shrink-0" />
            <div className="min-w-0 font-mono text-[12px] leading-[1.9] sm:text-[13px]">
              <p>
                <span className="text-[var(--acc-artifact)]">◆</span>{" "}
                <span className="font-semibold text-[var(--ink)]">GEODE</span>{" "}
                <span className="text-[var(--ink-2)]">v{GEODE_SOT.version}</span>
              </p>
              <p className="text-[var(--ink-3)]">claude-opus-4-8 · ~/workspace/geode</p>
              <p className="text-[var(--ink-3)]">/help for commands · type naturally</p>
            </div>
          </div>
          <div className="mt-4 border-t border-[var(--rule-soft)] pt-4 font-mono text-[12px] sm:text-[13px]">
            <p className="break-words">
              <span className="text-[var(--acc-artifact)]">&gt;</span>{" "}
              <span className="text-[var(--ink-2)]">
                {t(
                  locale,
                  "이 레포 점검하고 릴리스 블로커 요약해줘",
                  "inspect this repo and summarize release blockers"
                )}
              </span>
              <span className="geodi-caret ml-1 inline-block h-[13px] w-[7px] translate-y-[2px] bg-[var(--acc-artifact)]" />
            </p>
          </div>
        </div>
      </div>
      <figcaption className="mx-auto mt-3 w-fit rounded bg-[color-mix(in_srgb,var(--paper)_78%,transparent)] px-3 py-1 text-center font-mono text-[10.5px] text-[var(--acc-aqua)]">
        core/ui/mascot.py · geodi_art.py{" "}
        <span className="text-[var(--ink-2)]">
          {t(locale, "CLI 웰컴 스크린을 그대로 옮긴 화면", "the CLI welcome screen, transcribed")}
        </span>
      </figcaption>
    </figure>
  );
}

/** Crisp pixel cloud that drifts across (and past) frames. */
function PixelCloud({ className, flip = false }: { className?: string; flip?: boolean }) {
  return (
    <div
      aria-hidden
      className={`geodi-drift pointer-events-none absolute z-20 flex flex-col ${flip ? "items-start" : "items-center"} ${className ?? ""}`}
    >
      <div className="h-[8px] w-[30px] bg-[#FFF0F8]" />
      <div className="h-[8px] w-[54px] bg-[#FFF0F8]" />
    </div>
  );
}

function HeroSection() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  return (
    <section id="hero">
      {/* Rose color field, Hermes split composition: editorial serif statement
          left, white-line engraving of the mascot right, corner stamps. */}
      <div className="relative overflow-hidden bg-[var(--acc-artifact)]">
        <Image
          src="/geode/images/geode-sky.png"
          alt=""
          aria-hidden
          fill
          priority
          sizes="100vw"
          className="pointer-events-none select-none object-cover"
          style={{ imageRendering: "pixelated" }}
        />
        <div className="relative z-10 mx-auto max-w-7xl px-5 pt-9 text-center sm:px-8">
          <span className="font-pixel text-[19px] font-bold tracking-[0.06em] text-[var(--paper)]">GEODE</span>
        </div>

        <div className="relative z-10 mx-auto grid max-w-7xl items-center gap-6 px-5 pb-24 pt-10 sm:px-8 lg:grid-cols-[1.05fr_0.95fr] lg:pb-28 lg:pt-14">
          <motion.div
            className="relative z-10"
            initial={reduceMotion ? false : "hidden"}
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.1, delayChildren: 0.05 } } }}
          >
            <motion.p variants={{ hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] } } }} className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,var(--paper)_62%,transparent)]">
              open source · apache-2.0 · {t(locale, "루프 실험실", "the loop laboratory")}
            </motion.p>
            <motion.h1 variants={{ hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] } } }} className="font-serif-display mt-7 text-[clamp(2.5rem,5.8vw,4.4rem)] font-black leading-[1.12] text-[var(--paper)]">
              {t(locale, "일을 맡기면", "The agent that")}
              <br />
              {t(locale, "끝까지 실행하고,", "executes to the end,")}
              <br />
              {t(locale, "스스로를 고쳐 씁니다.", "and rewrites itself.")}
            </motion.h1>

            <motion.p variants={{ hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] } } }} className="mt-10 font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,var(--paper)_62%,transparent)]">
              run via terminal
            </motion.p>
            <motion.div variants={{ hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] } } }} className="mt-3 inline-block rounded bg-[var(--paper)] px-5 py-3 text-left font-mono text-[12.5px] text-[var(--ink-2)] sm:text-[13.5px]">
              <span className="text-[var(--acc-artifact)]">$</span> uv run geode{" "}
              <span className="text-[var(--code-string)]">
                &quot;{t(locale, "이 레포 점검하고 릴리스 블로커 요약해줘", "inspect this repo and summarize release blockers")}&quot;
              </span>
            </motion.div>

            <motion.div variants={{ hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] } } }} className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-3">
              <Link
                href="/docs"
                className="inline-flex items-center rounded bg-[var(--paper)] px-5 py-2.5 text-[14px] font-medium text-[var(--acc-artifact)] transition-opacity hover:opacity-85"
              >
                {t(locale, "문서 읽기", "Read the docs")}
              </Link>
              <Link
                href="https://github.com/mangowhoiscloud/geode"
                target="_blank"
                className="font-mono text-[13px] text-[var(--paper)] underline decoration-[color-mix(in_srgb,var(--paper)_40%,transparent)] underline-offset-4 transition-opacity hover:opacity-75"
              >
                GitHub
              </Link>
            </motion.div>
          </motion.div>

          <motion.div
            className="relative mx-auto w-full max-w-[440px]"
            initial={reduceMotion ? false : { opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
          >
            <PixelCloud className="-left-7 top-14" />
            <PixelCloud className="-right-6 bottom-24" flip />
            <motion.div
              animate={reduceMotion ? undefined : { y: [0, -7, 0] }}
              transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
            >
              <Image
                src="/geode/images/geode-lab-scene.png"
                alt={t(
                  locale,
                  "체커보드 대리석 실험실 홀 중앙의 Geodi 도트 아트",
                  "Pixel-art of Geodi centered in a checkerboard marble laboratory hall"
                )}
                width={1200}
                height={1500}
                priority
                className="w-full select-none border border-[color-mix(in_srgb,var(--paper)_35%,transparent)]"
                style={{ imageRendering: "pixelated" }}
              />
            </motion.div>
          </motion.div>
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-[color-mix(in_srgb,var(--paper)_55%,transparent)] sm:px-8">
          <span>geode v{GEODE_SOT.version}</span>
          <span>apache-2.0 · 2026</span>
        </div>
      </div>

      {/* Full-bleed gallery band: the illustration blurred edge-to-edge, the
          real CLI welcome screen floating at its center. */}
      <div className="relative w-full">
        <Image
          src="/geode/images/geode-gallery-blur.jpg"
          alt=""
          aria-hidden
          width={1600}
          height={1066}
          className="h-[480px] w-full select-none object-cover sm:h-[560px]"
        />
        <motion.div
          className="absolute inset-0 flex items-center justify-center px-4 sm:px-6"
          initial={reduceMotion ? false : { opacity: 0, y: 46 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.85, ease: [0.22, 1, 0.36, 1] }}
        >
          <TerminalMock />
        </motion.div>
      </div>
    </section>
  );
}

const LOOP_NODES = [
  { label: "Perceive", color: "var(--ink-2)" },
  { label: "Plan", color: "var(--ink-2)" },
  { label: "Act", color: "var(--acc-line)" },
  { label: "Observe", color: "var(--ink-2)" },
  { label: "Verify", color: "var(--acc-aqua)" },
  { label: "Replan", color: "var(--ink-2)" },
];

/** The while(tool_use) cycle as a pixel-styled hexagon ring (section 03 visual). */
function LoopDiagram() {
  const locale = useLocale();
  const cx = 170;
  const cy = 138;
  const r = 96;
  const nodeW = 76;
  const nodeH = 22;
  const points = LOOP_NODES.map((node, i) => {
    const angle = ((-90 + i * 60) * Math.PI) / 180;
    return { ...node, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });
  return (
    <svg
      viewBox="0 0 340 300"
      className="w-full max-w-[380px]"
      role="img"
      aria-label={t(
        locale,
        "while tool_use 루프 다이어그램. Perceive, Plan, Act, Observe, Verify, Replan이 순환하고, tool_use가 멈추면 finalize로 나갑니다.",
        "while tool_use loop diagram. Perceive, Plan, Act, Observe, Verify, Replan cycle; when tool_use stops it exits to finalize."
      )}
    >
      {points.map((node, i) => {
        const next = points[(i + 1) % points.length];
        const mx = (node.x + next.x) / 2;
        const my = (node.y + next.y) / 2;
        const angleDeg = (Math.atan2(next.y - node.y, next.x - node.x) * 180) / Math.PI;
        return (
          <g key={`edge-${node.label}`}>
            <line x1={node.x} y1={node.y} x2={next.x} y2={next.y} stroke="var(--rule)" strokeWidth="1" />
            <polygon
              points="-3,-3.5 4,0 -3,3.5"
              fill="var(--ink-3)"
              transform={`translate(${mx} ${my}) rotate(${angleDeg})`}
            />
          </g>
        );
      })}
      {/* exit: model answers without tool_use */}
      <line x1={cx} y1={cy + 30} x2={cx} y2={262} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="2 3" />
      <polygon points="-3.5,-3 0,4 3.5,-3" fill="var(--ink-3)" transform={`translate(${cx} ${262})`} />
      <rect
        x={cx - 38}
        y={264}
        width={76}
        height={22}
        fill="var(--paper-2)"
        stroke="var(--rule)"
        shapeRendering="crispEdges"
      />
      <text x={cx} y={279} textAnchor="middle" fontSize="10.5" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-2)">
        finalize
      </text>
      <text x={cx + 8} y={cy + 66} textAnchor="start" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-3)">
        no tool_use
      </text>
      {/* center */}
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize="15" className="font-pixel" fill="var(--acc-artifact)">
        while
      </text>
      <text x={cx} y={cy + 14} textAnchor="middle" fontSize="15" className="font-pixel" fill="var(--acc-artifact)">
        (tool_use)
      </text>
      {points.map((node) => (
        <g key={node.label}>
          <rect
            x={node.x - nodeW / 2}
            y={node.y - nodeH / 2}
            width={nodeW}
            height={nodeH}
            fill="var(--paper-2)"
            stroke="var(--rule)"
            shapeRendering="crispEdges"
          />
          <text
            x={node.x}
            y={node.y + 3.5}
            textAnchor="middle"
            fontSize="10.5"
            fontFamily="var(--font-fira-code), monospace"
            fill={node.color}
          >
            {node.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

/* ---------------- growth ------------------------------------------------- */

function CadenceChart() {
  const locale = useLocale();
  const max = peakWeek.count;
  const barSlot = 10;
  const chartHeight = 100;
  const width = weeklyCadence.length * barSlot;
  let lastMonth = "";
  const monthTicks: { x: number; label: string }[] = [];
  weeklyCadence.forEach((bin, i) => {
    const month = bin.start.slice(5, 7);
    if (month !== lastMonth) {
      monthTicks.push({ x: i * barSlot + 1, label: MONTH_LABELS[month] ?? month });
      lastMonth = month;
    }
  });
  return (
    <figure className="mt-8">
      <div className="flex items-baseline justify-between">
        <figcaption className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          {t(locale, "주간 릴리스 수", "releases per week")}
        </figcaption>
        <span className="font-mono text-[11px] text-[var(--ink-3)]">
          {t(locale, `최대 ${max}`, `peak ${max}`)}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${chartHeight + 14}`}
        className="mt-2 w-full"
        role="img"
        aria-label={t(
          locale,
          `주간 릴리스 수 막대 차트, 최대 주 ${max}건`,
          `Bar chart of releases per week, peaking at ${max}`
        )}
      >
        <line x1="0" y1={chartHeight + 0.5} x2={width} y2={chartHeight + 0.5} stroke="var(--rule)" strokeWidth="1" />
        {weeklyCadence.map((bin, i) => {
          const h = max === 0 ? 0 : (bin.count / max) * (chartHeight - 8);
          return (
            <motion.rect
              key={bin.start}
              className="cadence-bar"
              x={i * barSlot + 1}
              y={chartHeight - h}
              width={barSlot - 2}
              height={h}
              shapeRendering="crispEdges"
              style={{ transformBox: "fill-box", transformOrigin: "bottom" }}
              initial={{ scaleY: 0 }}
              whileInView={{ scaleY: 1 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.5, delay: i * 0.03, ease: [0.22, 1, 0.36, 1] }}
            >
              <title>{`${bin.start} · ${bin.count} releases`}</title>
            </motion.rect>
          );
        })}
        {monthTicks.map((tick) => (
          <text
            key={tick.label}
            x={tick.x}
            y={chartHeight + 11}
            fontSize="5.5"
            fontFamily="var(--font-fira-code), monospace"
            fill="var(--ink-3)"
          >
            {tick.label}
          </text>
        ))}
      </svg>
    </figure>
  );
}

/** Adversarial audit as a promotion gate — pixel schematic. */
function AuditGateDiagram() {
  const locale = useLocale();
  const dims = [26, 34, 20, 38, 30, 42];
  return (
    <svg
      viewBox="0 0 520 170"
      className="w-full max-w-[520px]"
      role="img"
      aria-label={t(
        locale,
        "감사 게이트 도식. scaffold 변이가 적대적 Petri 감사를 거쳐 차원 점수화되고, critical 하한선을 넘으면 기각, 통과하면 champion으로 승격합니다.",
        "Audit gate schematic. A scaffold mutation passes an adversarial Petri audit, gets scored per dimension, is rejected on any critical-floor breach, and promotes to champion otherwise."
      )}
    >
      {/* candidate */}
      <rect x="8" y="72" width="92" height="26" fill="var(--paper-2)" stroke="var(--rule)" shapeRendering="crispEdges" />
      <text x="54" y="88" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-2)">
        scaffold 변이
      </text>
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--ink-3)" transform="translate(116 85)" />
      <line x1="100" y1="85" x2="128" y2="85" stroke="var(--rule)" strokeWidth="1" />

      {/* adversarial arena */}
      <rect x="132" y="28" width="150" height="116" fill="none" stroke="var(--rule)" strokeDasharray="3 3" shapeRendering="crispEdges" />
      <text x="207" y="20" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-3)">
        adversarial audit
      </text>
      <rect x="147" y="40" width="120" height="22" fill="var(--paper-2)" stroke="var(--rule)" shapeRendering="crispEdges" />
      <text x="207" y="54" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-2)">
        Petri auditor
      </text>
      <rect x="147" y="108" width="120" height="22" fill="var(--paper-2)" stroke="var(--rule)" shapeRendering="crispEdges" />
      <text x="207" y="122" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        GEODE
      </text>
      {[171, 207, 243].map((x) => (
        <line key={x} x1={x} y1="64" x2={x} y2="106" stroke="var(--rule)" strokeWidth="1" strokeDasharray="2 2" />
      ))}

      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--ink-3)" transform="translate(302 85)" />
      <line x1="282" y1="85" x2="314" y2="85" stroke="var(--rule)" strokeWidth="1" />

      {/* dimension bars + critical floor */}
      {dims.map((h, i) => (
        <rect
          key={i}
          x={320 + i * 13}
          y={104 - h}
          width={9}
          height={h}
          fill={i === 3 ? "var(--acc-artifact)" : "var(--rule)"}
          shapeRendering="crispEdges"
        />
      ))}
      <line x1="316" y1="76" x2="402" y2="76" stroke="var(--acc-line)" strokeWidth="1" strokeDasharray="4 2" />
      <text x="359" y="120" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-3)">
        critical floor
      </text>

      {/* gate branches */}
      <line x1="406" y1="85" x2="430" y2="85" stroke="var(--rule)" strokeWidth="1" />
      <line x1="430" y1="85" x2="446" y2="52" stroke="var(--acc-line)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-line)" transform="translate(448 49) rotate(-64)" />
      <rect x="446" y="30" width="66" height="20" fill="var(--paper-2)" stroke="var(--acc-line)" shapeRendering="crispEdges" />
      <text x="479" y="43" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-line)">
        promote
      </text>
      <line x1="430" y1="85" x2="446" y2="118" stroke="var(--ink-3)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--ink-3)" transform="translate(448 121) rotate(64)" />
      <rect x="446" y="120" width="66" height="20" fill="var(--paper-2)" stroke="var(--rule)" shapeRendering="crispEdges" />
      <text x="479" y="133" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-3)">
        reject
      </text>
      <text x="470" y="90" textAnchor="middle" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-3)">
        gate·random·never
      </text>
    </svg>
  );
}

/** Seed hypothesis factory — candidates culled stage by stage. */
function SeedgenDiagram() {
  const locale = useLocale();
  const stages = ["generator", "critic", "pilot", "ranker", "evolver"];
  const seedCols = [4, 3, 2, 2, 5];
  return (
    <svg
      viewBox="0 0 520 150"
      className="w-full max-w-[520px]"
      role="img"
      aria-label={t(
        locale,
        "시드 생성 파이프라인 도식. generator, critic, pilot, ranker, evolver를 거치며 후보가 단계마다 걸러지고 생존자만 시드 풀로 들어갑니다.",
        "Seed-generation pipeline schematic. Candidates pass generator, critic, pilot, ranker, evolver, culled at each stage; only survivors enter the seed pool."
      )}
    >
      {stages.map((stage, i) => (
        <g key={stage}>
          <rect x={8 + i * 88} y="34" width="76" height="24" fill="var(--paper-2)" stroke="var(--rule)" shapeRendering="crispEdges" />
          <text
            x={46 + i * 88}
            y="49"
            textAnchor="middle"
            fontSize="10"
            fontFamily="var(--font-fira-code), monospace"
            fill="var(--ink-2)"
          >
            {stage}
          </text>
          {i < 4 && (
            <g>
              <line x1={84 + i * 88} y1="46" x2={96 + i * 88} y2="46" stroke="var(--rule)" strokeWidth="1" />
              <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--ink-3)" transform={`translate(${95 + i * 88} 46)`} />
            </g>
          )}
          {/* seeds in flight above each stage */}
          {Array.from({ length: seedCols[i] }).map((_, seed) => (
            <rect
              key={seed}
              x={30 + i * 88 + seed * 9}
              y="16"
              width="5"
              height="5"
              fill={i === 4 ? "var(--acc-line)" : "var(--acc-artifact)"}
              shapeRendering="crispEdges"
            />
          ))}
          {/* culled seeds falling below critic/pilot/ranker */}
          {i > 0 && i < 4 && (
            <g opacity="0.3">
              <rect x={36 + i * 88} y="78" width="5" height="5" fill="var(--acc-artifact)" shapeRendering="crispEdges" />
              <rect x={50 + i * 88} y="92" width="5" height="5" fill="var(--acc-artifact)" shapeRendering="crispEdges" />
            </g>
          )}
        </g>
      ))}
      <text x="260" y="116" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill="var(--ink-3)">
        {t(locale, "후보는 단계마다 떨어지고, top-5 생존자만 시드 풀에 남습니다", "candidates drop at every stage; only the top-5 survivors reach the seed pool")}
      </text>
      <text x="260" y="134" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-aqua)">
        Elo + difficulty blend · co-evolving pool
      </text>
    </svg>
  );
}


/* ---------------- run row: three ways in --------------------------------- */

const runModes = [
  {
    eyebrow: "any terminal",
    titleKo: "터미널",
    titleEn: "Terminal",
    cmd: "$ uv run geode",
    ko: "자연어로 맡기면 루프가 끝까지 실행합니다.",
    en: "Hand it a sentence; the loop executes to the end.",
  },
  {
    eyebrow: "any mcp client",
    titleKo: "MCP 서버",
    titleEn: "MCP Server",
    cmd: "$ geode-mcp",
    ko: "다른 에이전트의 도구로 붙습니다. run_agent, memory, self-improving까지.",
    en: "Mounts as another agent's tool: run_agent, memory, self-improving.",
  },
  {
    eyebrow: "resident daemon",
    titleKo: "상주 데몬",
    titleEn: "Daemon",
    cmd: "$ geode serve",
    ko: "Slack과 cron을 받는 게이트웨이로 상주합니다.",
    en: "Stays resident as a gateway for Slack and cron.",
  },
];

function RunRow() {
  const locale = useLocale();
  return (
    <section id="run" className="border-b border-[var(--rule)]">
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-20 text-center sm:py-24 md:grid-cols-3">
        {runModes.map((mode) => (
          <div key={mode.cmd}>
            <p className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[var(--ink-3)]">{mode.eyebrow}</p>
            <h2 className="font-serif-display mt-3 text-[30px] font-semibold text-[var(--ink-1)]">
              {locale === "en" ? mode.titleEn : mode.titleKo}
            </h2>
            <p className="mx-auto mt-3 inline-block rounded bg-[var(--paper-deep)] px-4 py-2 font-mono text-[13px] text-[var(--acc-line)]">
              {mode.cmd}
            </p>
            <p className="mx-auto mt-3 max-w-[260px] text-[13px] leading-[1.7] text-[var(--ink-2)]">
              {t(locale, mode.ko, mode.en)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---------------- features: numbered plates on the print slab ------------ */

/** Print-slab (rose-white) surface colors — art-plate scope only. */
const SLAB_INK = "#0B0A10";
const SLAB_ACCENT = "#8E3A66";

function PerceiveBanner() {
  return (
    <div className="flex h-full w-full flex-col justify-center gap-2.5 px-6 font-mono text-[12px] leading-relaxed">
      <p><span className="text-[var(--acc-aqua)]">context</span><span className="text-[var(--ink-3)]"> · per-turn time, memory, rules</span></p>
      <p><span className="text-[var(--acc-aqua)]">documents</span><span className="text-[var(--ink-3)]"> · local pdf ingest</span></p>
      <p><span className="text-[var(--acc-aqua)]">browser</span><span className="text-[var(--ink-3)]"> · your real chrome, over cdp</span></p>
      <p><span className="text-[var(--acc-aqua)]">desktop</span><span className="text-[var(--ink-3)]"> · ax tree before pixels</span></p>
    </div>
  );
}

function MeasureBanner() {
  const tau2 = BENCHMARK_GROUPS.find((group) => group.id === "tau2");
  const cells = (tau2?.matrix ?? []).filter((cell) => ["Retail", "Telecom", "Airline"].includes(cell.label));
  return (
    <div className="flex h-full w-full flex-col justify-center gap-4 px-6">
      <div className="flex items-baseline justify-center gap-6">
        {cells.map((cell) => (
          <div key={cell.label} className="text-center">
            <p className="font-serif-display text-[26px] font-black text-[var(--acc-line)]">{cell.value}</p>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.2em] text-[var(--ink-3)]">{cell.label}</p>
          </div>
        ))}
      </div>
      <p className="text-center font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ink-3)]">
        tau2-bench base · native user_simulator
      </p>
    </div>
  );
}

function ResideBanner() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 px-6">
      <div className="font-mono text-[12px] leading-relaxed text-[var(--ink-2)]">
        <p>anthropic · openai / codex · glm</p>
        <p className="text-center text-[var(--ink-3)]">oauth you own · provider-isolated</p>
      </div>
      <div className="flex flex-wrap justify-center gap-1.5">
        {surfaceChips.map((chip) => (
          <Token key={chip} label={chip} size="sm" />
        ))}
      </div>
    </div>
  );
}

const features: {
  id: string;
  index: string;
  headKo: string;
  headEn: string;
  ko: string;
  en: string;
  banner: React.ReactNode;
}[] = [
  {
    id: "execute",
    index: "#1 execute",
    headKo: "루프를 돌립니다",
    headEn: "RUNS THE LOOP",
    ko: "계획, 실행, 관찰, 검증, 재계획. 도구 호출이 멈출 때까지. 예산은 프롬프트 문구가 아니라 루프의 탈출 조건입니다.",
    en: "Plan, act, observe, verify, replan — until tool calls stop. Budgets are exit conditions, not prompt wording.",
    banner: <LoopDiagram />,
  },
  {
    id: "perceive",
    index: "#2 perceive",
    headKo: "세계를 읽습니다",
    headEn: "SEES YOUR WORLD",
    ko: "턴마다 현재 시각과 메모리를 조립하고, PDF를 읽고, 당신의 진짜 Chrome에 CDP로 붙고, 데스크톱은 AX 트리부터 읽습니다.",
    en: "Per-turn context with the current time, PDF ingest, your real Chrome over CDP, and the desktop read AX-first.",
    banner: <PerceiveBanner />,
  },
  {
    id: "audit",
    index: "#3 audit",
    headKo: "스스로를 감사합니다",
    headEn: "AUDITS ITSELF",
    ko: "모든 스캐폴드 변이는 적대적 Petri 감사를 통과해야 합니다. critical 축이 한 번이라도 후퇴하면 승격은 거부됩니다.",
    en: "Every scaffold mutation faces an adversarial Petri audit. One critical regression vetoes promotion.",
    banner: <AuditGateDiagram />,
  },
  {
    id: "breed",
    index: "#4 breed",
    headKo: "시험도 스스로 만듭니다",
    headEn: "BREEDS ITS OWN TESTS",
    ko: "generator, critic, pilot, ranker, evolver. 평가 시드 풀이 에이전트와 나란히 자랍니다.",
    en: "Generator, critic, pilot, ranker, evolver. The evaluation pool grows alongside the agent.",
    banner: <SeedgenDiagram />,
  },
  {
    id: "measure",
    index: "#5 measure",
    headKo: "정직하게 잽니다",
    headEn: "KEEPS HONEST SCORE",
    ko: "개선에 실패한 캠페인도 기록에 남습니다. 0 승격의 원인 규명까지가 실측 자산입니다.",
    en: "The campaigns that failed to improve it stay on the record — including why zero got promoted.",
    banner: <MeasureBanner />,
  },
  {
    id: "reside",
    index: "#6 reside",
    headKo: "당신의 구독으로 상주합니다",
    headEn: "ON YOUR SUBSCRIPTIONS",
    ko: "Anthropic, OpenAI/Codex, GLM을 직접 소유한 OAuth로. 프로바이더 격리를 지키며 모든 표면에 상주합니다.",
    en: "Anthropic, OpenAI/Codex, and GLM over OAuth you own — provider-isolated, resident on every surface.",
    banner: <ResideBanner />,
  },
];

function FeaturesGrid() {
  const locale = useLocale();
  return (
    <section id="features" style={{ backgroundColor: "#FFF0F8" }}>
      <div className="mx-auto max-w-7xl px-6 py-20 sm:py-28">
        <div className="grid gap-x-8 gap-y-16 md:grid-cols-2 xl:grid-cols-3">
          {features.map((feature) => (
            <div key={feature.id}>
              <p className="font-mono text-[11px] uppercase tracking-[0.26em]" style={{ color: SLAB_ACCENT }}>
                {feature.index}
              </p>
              <h2
                className="font-serif-display mt-3 text-[30px] font-black uppercase leading-[1.08] sm:text-[34px]"
                style={{ color: SLAB_INK }}
              >
                {locale === "en" ? feature.headEn : feature.headKo}
              </h2>
              <div className="mt-5 flex h-[230px] items-center justify-center overflow-hidden rounded-sm bg-[var(--paper)] px-2">
                {feature.banner}
              </div>
              <p className="mt-4 max-w-[380px] text-[13px] leading-[1.75]" style={{ color: SLAB_INK }}>
                {t(locale, feature.ko, feature.en)}
              </p>
            </div>
          ))}
        </div>
        <div
          className="mt-16 flex items-end justify-between font-mono text-[10px] uppercase tracking-[0.18em]"
          style={{ color: SLAB_ACCENT }}
        >
          <span>the loop laboratory · plates i-vi</span>
          <span>evidence: core/ · plugins/</span>
        </div>
      </div>
    </section>
  );
}

/* ---------------- giant wordmark band ------------------------------------ */

function WordmarkBand() {
  return (
    <div aria-hidden className="select-none overflow-hidden border-y border-[var(--rule)] bg-[var(--paper)]">
      <p className="font-pixel -my-[0.06em] whitespace-nowrap text-center text-[23.5vw] font-bold leading-[0.86] text-[var(--acc-artifact)]">
        GEODE
      </p>
    </div>
  );
}

/* ---------------- finale: the specimen ----------------------------------- */

function LabFinale() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  return (
    <section id="lab" className="relative overflow-hidden bg-[var(--acc-artifact)]">
      <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <span className="font-pixel select-none text-[24vw] font-bold leading-none text-[var(--paper)] opacity-[0.06]">
          GEODE
        </span>
      </div>
      <div className="relative z-10 mx-auto flex max-w-5xl flex-col items-center gap-7 px-6 py-24 text-center sm:py-32">
        <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,var(--paper)_65%,transparent)]">
          birth {firstRelease.date} · release #{releaseCount} · v{latestRelease.version}
        </p>
        <h2 className="font-serif-display text-[clamp(2.4rem,6vw,4.2rem)] font-black leading-[1.1] text-[var(--paper)]">
          {t(locale, "루프 실험실", "The Loop Laboratory")}
        </h2>
        <motion.div
          className="flex h-44 w-44 items-center justify-center rounded-full border-2 border-[var(--paper)] sm:h-52 sm:w-52"
          initial={reduceMotion ? false : { scale: 0.82, opacity: 0 }}
          whileInView={{ scale: 1, opacity: 1 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ type: "spring", stiffness: 120, damping: 16 }}
        >
          <GeodiSprite scale={5} silhouette="var(--paper)" />
        </motion.div>
        <p className="font-serif-display max-w-xl text-[clamp(1.05rem,2.4vw,1.4rem)] font-semibold leading-[1.6] text-[var(--paper)]">
          {t(locale, "실패를 기록하고, 스스로를 고쳐 씁니다.", "It records its failures, and rewrites itself.")}
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <Link
            href="/docs"
            className="inline-flex items-center rounded bg-[var(--paper)] px-5 py-2.5 text-[14px] font-medium text-[var(--acc-artifact)] transition-opacity hover:opacity-85"
          >
            {t(locale, "문서 읽기", "Read the docs")}
          </Link>
          <a
            href="https://github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md"
            target="_blank"
            rel="noreferrer"
            className="font-mono text-[13px] text-[var(--paper)] underline decoration-[color-mix(in_srgb,var(--paper)_40%,transparent)] underline-offset-4 transition-opacity hover:opacity-75"
          >
            {t(locale, "전체 기록 보기", "View the full record")}
          </a>
        </div>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-[color-mix(in_srgb,var(--paper)_55%,transparent)] sm:px-8">
        <span>specimen · geodi</span>
        <span>petri audit attached</span>
      </div>
    </section>
  );
}

/* ---------------- page ---------------------------------------------------- */


export default function GeodePortfolioPage() {
  return (
    <LocaleProvider defaultLocale="en">
      <main
        data-astryx-theme="neutral"
        className={`${galmuri.variable} ${serifDisplay.variable} min-h-screen overflow-x-hidden bg-[var(--paper)] text-[var(--ink)]`}
      >
        <GeodeNav items={navItems} />
        <HeroSection />
        <RunRow />
        <FeaturesGrid />
        <WordmarkBand />
        <LabFinale />
        <GeodeFooter />
      </main>
    </LocaleProvider>
  );
}
