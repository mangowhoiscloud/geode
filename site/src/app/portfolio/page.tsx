"use client";

import "@astryxdesign/theme-neutral/theme.css";
import "@astryxdesign/core/astryx.css";
import "./astryx-geode.css";

import { Token } from "@astryxdesign/core/Token";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import Image from "next/image";
import Link from "next/link";
import { useRef, useState } from "react";

import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { LocaleProvider, t, useLocale } from "@/components/geode/locale-context";
import { GeodeNav } from "@/components/geode/sections/nav";
import { BENCHMARK_GROUPS } from "@/data/geode/benchmark-measurements";
import { GEODE_SOT } from "@/data/geode/sot";
import { galmuri } from "@/fonts/galmuri";
import { serifDisplay } from "@/fonts/serif";

/**
 * GEODE portfolio v26 — The Fixed Point, in rose and white.
 *
 * Palette (operator-directed 2026-07-10): the whole page is one rose field
 * (`--acc-artifact`) written in warm white `#FFF0F8` — two colors only. The
 * terminal mock keeps its dark product-screenshot colors by standing
 * exception. White appears as ink, as paper plates carrying rose line-art
 * schematics, and as the stage of the final specimen reveal. Scroll is
 * choreography: distillation rain converges through named thresholds, fills
 * the full-bleed wordmark, and further scroll reveals the laboratory.
 */

const PAPER = "#FFF0F8";
const PAPER_75 = "color-mix(in srgb, #FFF0F8 90%, transparent)";
const PAPER_55 = "color-mix(in srgb, #FFF0F8 55%, transparent)";
// Deep-rose ink: same hue as the signature, darkened for legibility on the
// white plates (~4.5:1 vs #FFF0F8; the signature itself is ~1.8:1 as ink).
const ROSE_INK = "#C2447F";
const ROSE_INK_70 = "color-mix(in srgb, #C2447F 72%, transparent)";

const navItems = [
  { id: "hero", label: "Intro" },
  { id: "run", label: "Run" },
  { id: "features", label: "Features" },
  { id: "distill", label: "Distill" },
  { id: "lab", label: "Specimen" },
];

const surfaceChips = ["CLI", "MCP server", "Slack", "cron", "Gateway daemon"];

/** Sprite with a discoverable click reaction: three quick pixel hops. */
function PlayfulSprite({ scale, blink, className }: { scale?: number; blink?: boolean; className?: string }) {
  const [hopping, setHopping] = useState(false);
  return (
    <button
      type="button"
      aria-label="Geodi"
      title="Geodi"
      className={`cursor-pointer touch-manipulation ${className ?? ""}`}
      onClick={() => {
        setHopping(true);
        window.setTimeout(() => setHopping(false), 750);
      }}
    >
      <GeodiSprite scale={scale} blink={blink} className={hopping ? "geodi-hop" : undefined} />
    </button>
  );
}

/* ---------------- terminal: the product moment --------------------------- */

function TerminalMock() {
  const locale = useLocale();
  return (
    <figure className="mx-auto w-full max-w-2xl">
      <div className="overflow-hidden rounded-lg border border-[color-mix(in_srgb,#FFF0F8_35%,transparent)] bg-[var(--paper-deep)] text-left">
        <div className="flex items-center gap-2 border-b border-[var(--rule-soft)] px-4 py-2.5">
          <span className="flex gap-1.5">
            {["#FF5F57", "#FEBC2E", "#28C840"].map((light) => (
              <span key={light} className="h-[9px] w-[9px] rounded-full" style={{ background: light }} />
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
                <span className="font-semibold text-[var(--acc-artifact)]">GEODE</span>{" "}
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
      <figcaption className="mx-auto mt-3 w-fit rounded bg-[#FFF0F8] px-3 py-1 text-center font-mono text-[10.5px] text-[#C2447F]">
        core/ui/mascot.py · geodi_art.py · {t(locale, "CLI 웰컴 스크린을 그대로 옮긴 화면", "the CLI welcome screen, transcribed")}
      </figcaption>
    </figure>
  );
}

/* ---------------- hero: rose field, white statement ----------------------- */

function HeroField() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const heroItem = {
    hidden: { opacity: 0, y: reduceMotion ? 0 : 22 },
    show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] as const } },
  };
  return (
    <section id="hero" className="relative overflow-hidden">
      <Image
        src="/geode/images/geode-sky.png"
        alt=""
        aria-hidden
        fill
        priority
        sizes="100vw"
        className="pointer-events-none select-none object-cover opacity-90"
        style={{ imageRendering: "pixelated" }}
      />
      <motion.div
        className="relative z-10 mx-auto max-w-7xl px-5 pb-16 pt-14 sm:px-8 lg:pt-20"
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.1, delayChildren: 0.05 } } }}
      >
        <motion.p
          variants={heroItem}
          className="font-mono text-[10.5px] uppercase tracking-[0.3em]"
          style={{ color: PAPER_75 }}
        >
          open source · apache-2.0 · {t(locale, "고정점", "the fixed point")}
        </motion.p>
        <motion.h1
          variants={heroItem}
          className="font-serif-display mt-7 max-w-4xl text-balance text-[clamp(2.5rem,5.6vw,4.3rem)] font-black leading-[1.12] text-[#FFF0F8]"
        >
          {t(locale, "일을 맡기면", "The agent that")}
          <br />
          {t(locale, "끝까지 실행하고,", "executes to the end,")}
          <br />
          {t(locale, "스스로를 고쳐 씁니다.", "and rewrites itself.")}
        </motion.h1>
        <motion.div variants={heroItem} className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-3">
          <Link
            href="/docs"
            className="inline-flex touch-manipulation items-center rounded bg-[#FFF0F8] px-5 py-2.5 text-[14px] font-medium text-[#C2447F] transition-opacity hover:opacity-85"
          >
            {t(locale, "문서 읽기", "Read the docs")}
          </Link>
          <Link
            href="https://github.com/mangowhoiscloud/geode"
            target="_blank"
            className="font-mono text-[13px] text-[#FFF0F8] underline decoration-[color-mix(in_srgb,#FFF0F8_45%,transparent)] underline-offset-4 transition-opacity hover:opacity-75"
          >
            GitHub
          </Link>
        </motion.div>
        <motion.div variants={heroItem} className="mt-14 w-full">
          <TerminalMock />
        </motion.div>
      </motion.div>
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] sm:px-8"
        style={{ color: PAPER_55 }}
      >
        <span>geode v{GEODE_SOT.version}</span>
        <span>apache-2.0 · 2026</span>
      </div>
    </section>
  );
}

/* ---------------- diagrams: rose line-art on white plates ----------------- */

/**
 * The while(tool_use) cycle as a portrait circuit rail: seven stations on a
 * rectangular track, clockwise arrows, the no-tool_use exit dropping through
 * the bottom rail gap to finalize. Drawn for the postcard plate (portrait).
 */
function LoopDiagram() {
  const locale = useLocale();
  const railL = 52;
  const railR = 308;
  const railT = 64;
  const railB = 372;
  const midX = (railL + railR) / 2;
  const nodeW = 100;
  const nodeH = 30;
  const nodes: { label: string; x: number; y: number }[] = [
    { label: "Perceive", x: midX, y: railT },
    { label: "Plan", x: railR, y: 168 },
    { label: "Act", x: railR, y: 272 },
    { label: "Observe", x: 246, y: railB },
    { label: "Reflect", x: 114, y: railB },
    { label: "Verify", x: railL, y: 272 },
    { label: "Replan", x: railL, y: 168 },
  ];
  // clockwise arrowheads on the rail between stations
  const arrows: { x: number; y: number; deg: number }[] = [
    { x: (midX + railR) / 2 + 24, y: railT, deg: 0 },
    { x: railR, y: 220, deg: 90 },
    { x: railR, y: 330, deg: 90 },
    { x: midX, y: railB, deg: 180 },
    { x: railL, y: 330, deg: 270 },
    { x: railL, y: 220, deg: 270 },
    { x: (railL + midX) / 2 - 24, y: railT, deg: 0 },
  ];
  return (
    <svg viewBox="0 0 360 470" className="h-full w-auto max-w-full" role="img"
      aria-label={t(locale, "while tool_use 루프 다이어그램", "while tool_use loop diagram")}>
      {/* depth: dotted echoes of the rail */}
      {[22, 44].map((inset) => (
        <rect key={inset} x={railL - inset} y={railT - inset} width={railR - railL + inset * 2}
          height={railB - railT + inset * 2} fill="none" stroke={ROSE_INK} strokeWidth="1"
          strokeDasharray="1.5 5" opacity="0.45" shapeRendering="crispEdges" />
      ))}
      {/* the rail */}
      <rect x={railL} y={railT} width={railR - railL} height={railB - railT} fill="none"
        stroke={ROSE_INK} strokeWidth="1.2" shapeRendering="crispEdges" />
      {arrows.map((a, i) => (
        <polygon key={i} points="-3.5,-4 4.5,0 -3.5,4" fill={ROSE_INK}
          transform={`translate(${a.x} ${a.y}) rotate(${a.deg})`} />
      ))}
      {/* center clause */}
      <text x={midX} y={206} textAnchor="middle" fontSize="20" className="font-pixel" fill={ROSE_INK}>while</text>
      <text x={midX} y={230} textAnchor="middle" fontSize="20" className="font-pixel" fill={ROSE_INK}>(tool_use)</text>
      {/* exit through the bottom rail gap */}
      <line x1={midX} y1={252} x2={midX} y2={424} stroke={ROSE_INK} strokeWidth="1.2" strokeDasharray="3 4" />
      <polygon points="-4,-3.5 0,4.5 4,-3.5" fill={ROSE_INK} transform={`translate(${midX} ${424})`} />
      <text x={midX + 10} y={404} textAnchor="start" fontSize="9.5"
        fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK_70}>no tool_use</text>
      <rect x={midX - 48} y={428} width={96} height={28} fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
      <text x={midX} y={446} textAnchor="middle" fontSize="12" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>finalize</text>
      {/* stations */}
      {nodes.map((node) => (
        <g key={node.label}>
          <rect x={node.x - nodeW / 2} y={node.y - nodeH / 2} width={nodeW} height={nodeH}
            fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
          <text x={node.x} y={node.y + 4} textAnchor="middle" fontSize="12"
            fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>{node.label}</text>
        </g>
      ))}
    </svg>
  );
}

/** Adversarial audit as a promotion gate — rose blueprint schematic. */
function AuditGateDiagram() {
  const locale = useLocale();
  const dims = [26, 34, 20, 38, 30, 42];
  return (
    <svg viewBox="0 0 520 170" className="w-full max-w-[520px]" role="img"
      aria-label={t(locale, "감사 게이트 도식", "audit gate schematic")}>
      <rect x="8" y="72" width="92" height="26" fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
      <text x="54" y="88" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>
        {t(locale, "scaffold 변이", "mutation")}
      </text>
      <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(116 85)" />
      <line x1="100" y1="85" x2="128" y2="85" stroke={ROSE_INK} strokeWidth="1" />
      <rect x="132" y="28" width="150" height="116" fill="none" stroke={ROSE_INK} strokeDasharray="3 3" shapeRendering="crispEdges" />
      <text x="207" y="20" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK_70}>adversarial audit</text>
      <rect x="147" y="40" width="120" height="22" fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
      <text x="207" y="54" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>Petri auditor</text>
      <rect x="147" y="108" width="120" height="22" fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
      <text x="207" y="122" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>GEODE</text>
      {[171, 207, 243].map((x) => (
        <line key={x} x1={x} y1="64" x2={x} y2="106" stroke={ROSE_INK} strokeWidth="1" strokeDasharray="2 2" />
      ))}
      <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(302 85)" />
      <line x1="282" y1="85" x2="314" y2="85" stroke={ROSE_INK} strokeWidth="1" />
      {dims.map((h, i) => (
        <rect key={i} x={320 + i * 13} y={104 - h} width={9} height={h}
          fill={ROSE_INK} opacity={i === 3 ? 1 : 0.55} shapeRendering="crispEdges" />
      ))}
      <line x1="316" y1="76" x2="402" y2="76" stroke={ROSE_INK} strokeWidth="1" strokeDasharray="4 2" />
      <text x="359" y="120" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK_70}>critical floor</text>
      <line x1="406" y1="85" x2="430" y2="85" stroke={ROSE_INK} strokeWidth="1" />
      <line x1="430" y1="85" x2="446" y2="52" stroke={ROSE_INK} strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(448 49) rotate(-64)" />
      <rect x="446" y="30" width="66" height="20" fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
      <text x="479" y="43" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>promote</text>
      <line x1="430" y1="85" x2="446" y2="118" stroke={ROSE_INK} strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(448 121) rotate(64)" />
      <rect x="446" y="120" width="66" height="20" fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
      <text x="479" y="133" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>reject</text>
      <text x="470" y="90" textAnchor="middle" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK_70}>gate·random·never</text>
    </svg>
  );
}

/** Seed hypothesis factory — rose blueprint pipeline. */
function SeedgenDiagram() {
  const locale = useLocale();
  const stages = ["generator", "critic", "pilot", "ranker", "evolver"];
  const seedCols = [4, 3, 2, 2, 5];
  return (
    <svg viewBox="0 0 520 150" className="w-full max-w-[520px]" role="img"
      aria-label={t(locale, "시드 생성 파이프라인 도식", "seed-generation pipeline schematic")}>
      {stages.map((stage, i) => (
        <g key={stage}>
          <rect x={8 + i * 88} y="34" width="76" height="24" fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
          <text x={46 + i * 88} y="49" textAnchor="middle" fontSize="10"
            fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>{stage}</text>
          {i < 4 && (
            <g>
              <line x1={84 + i * 88} y1="46" x2={96 + i * 88} y2="46" stroke={ROSE_INK} strokeWidth="1" />
              <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform={`translate(${95 + i * 88} 46)`} />
            </g>
          )}
          {Array.from({ length: seedCols[i] }).map((_, seed) => (
            <rect key={seed} x={30 + i * 88 + seed * 9} y="16" width="5" height="5"
              fill={ROSE_INK} opacity={i === 4 ? 1 : 0.7} shapeRendering="crispEdges" />
          ))}
          {i > 0 && i < 4 && (
            <g opacity="0.35">
              <rect x={36 + i * 88} y="78" width="5" height="5" fill={ROSE_INK} shapeRendering="crispEdges" />
              <rect x={50 + i * 88} y="92" width="5" height="5" fill={ROSE_INK} shapeRendering="crispEdges" />
            </g>
          )}
        </g>
      ))}
      <text x="260" y="116" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK_70}>
        {t(locale, "후보는 단계마다 떨어지고, top-5 생존자만 시드 풀에 남습니다", "candidates drop at every stage; only the top-5 survivors reach the seed pool")}
      </text>
      <text x="260" y="134" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK_70}>
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
    cmd: "$ geode",
    ko: "그대로 치면 대화형 세션. geode \"한 문장\"은 그 일을 끝까지 실행하고, serve 데몬은 알아서 기동합니다.",
    en: "Bare geode opens the session; geode \"a sentence\" runs that one job to the end. The serve daemon auto-starts.",
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

/** The three entrances — white plates in the postcard language. */
function RunRow() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  return (
    <section id="run" className="bg-[var(--acc-artifact)]">
      <div className="mx-auto w-full max-w-6xl px-6 py-20 sm:py-28">
        <motion.p
          initial={{ opacity: 0, y: reduceMotion ? 0 : 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="text-center font-mono text-[10.5px] uppercase tracking-[0.3em]"
          style={{ color: PAPER_75 }}
        >
          {t(locale, "세 가지 입구", "three ways in")}
        </motion.p>
        <div className="mt-10 grid gap-8 md:grid-cols-3">
          {runModes.map((mode, i) => (
            <motion.div
              key={mode.cmd}
              initial={{ opacity: 0, y: reduceMotion ? 0 : 26 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.65, delay: i * 0.12, ease: [0.22, 1, 0.36, 1] }}
              className="bg-[#FFF0F8] px-7 py-10 text-center"
            >
              <p className="font-mono text-[10.5px] uppercase tracking-[0.28em]" style={{ color: ROSE_INK_70 }}>
                {mode.eyebrow}
              </p>
              <h2 className="font-serif-display mt-3 text-[28px] font-semibold" style={{ color: ROSE_INK }}>
                {locale === "en" ? mode.titleEn : mode.titleKo}
              </h2>
              <p className="mx-auto mt-4 inline-block rounded bg-[#C2447F] px-4 py-2 font-mono text-[13px] font-medium text-[#FFF0F8]">
                {mode.cmd}
              </p>
              <p className="mx-auto mt-4 max-w-[280px] text-[13px] leading-[1.7]" style={{ color: ROSE_INK_70 }}>
                {t(locale, mode.ko, mode.en)}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------- features: numbered plates ------------------------------- */

function PerceiveBanner() {
  return (
    <div className="flex h-full w-full flex-col justify-center gap-2.5 px-6 font-mono text-[12px] leading-relaxed">
      <p><span style={{ color: ROSE_INK }}>context</span><span style={{ color: ROSE_INK_70 }}> · per-turn time, memory, rules</span></p>
      <p><span style={{ color: ROSE_INK }}>documents</span><span style={{ color: ROSE_INK_70 }}> · local pdf ingest</span></p>
      <p><span style={{ color: ROSE_INK }}>browser</span><span style={{ color: ROSE_INK_70 }}> · your real chrome, over cdp</span></p>
      <p><span style={{ color: ROSE_INK }}>desktop</span><span style={{ color: ROSE_INK_70 }}> · ax tree before pixels</span></p>
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
            <p className="font-serif-display text-[26px] font-black" style={{ color: ROSE_INK }}>{cell.value}</p>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.2em]" style={{ color: ROSE_INK_70 }}>{cell.label}</p>
          </div>
        ))}
      </div>
      <p className="text-center font-mono text-[10px] uppercase tracking-[0.14em]" style={{ color: ROSE_INK_70 }}>
        tau2-bench base · gpt-5.5 · openai-codex subscription
      </p>
    </div>
  );
}


function ConnectBanner() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="font-mono text-[12px] leading-relaxed">
        <p style={{ color: ROSE_INK }}>one agent · one memory · every surface</p>
        <p style={{ color: ROSE_INK_70 }}>openai / codex · glm · oauth you own</p>
      </div>
      <div className="flex flex-wrap justify-center gap-1.5">
        {surfaceChips.map((chip) => (
          <Token key={chip} label={chip} size="sm" color="pink" />
        ))}
      </div>
    </div>
  );
}

/**
 * 5-tier context assembly as a core sample (core/memory/context.py):
 * sediment deepens toward the bottom, and the winning tier (session,
 * lower-overrides-higher) is solid rose.
 */
function MemoryBanner() {
  const tiers: { tier: string; name: string; alpha: number }[] = [
    { tier: "tier 0", name: "identity", alpha: 0.08 },
    { tier: "tier 0.5", name: "user profile", alpha: 0.13 },
    { tier: "tier 1", name: "organization", alpha: 0.19 },
    { tier: "tier 2", name: "project", alpha: 0.27 },
  ];
  return (
    <div className="flex h-full w-full items-center justify-center px-8">
      <div className="w-full max-w-[330px]">
        <div className="overflow-hidden border" style={{ borderColor: ROSE_INK_70 }}>
          {tiers.map(({ tier, name, alpha }, i) => (
            <div
              key={tier}
              className="flex items-baseline justify-between px-4 py-[9px] font-mono text-[11px]"
              style={{
                background: `color-mix(in srgb, var(--acc-artifact) ${alpha * 100}%, transparent)`,
                borderTop: i ? "1px solid color-mix(in srgb, var(--acc-artifact) 30%, transparent)" : undefined,
              }}
            >
              <span style={{ color: ROSE_INK_70 }}>{tier}</span>
              <span style={{ color: ROSE_INK }}>{name}</span>
            </div>
          ))}
          <div className="flex items-baseline justify-between bg-[#C2447F] px-4 py-[9px] font-mono text-[11px] text-[#FFF0F8]">
            <span style={{ opacity: 0.8 }}>tier 3</span>
            <span className="font-semibold">session</span>
          </div>
        </div>
        <p className="mt-3 flex items-center justify-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em]" style={{ color: ROSE_INK_70 }}>
          <span className="inline-block h-[5px] w-[5px] rotate-45 bg-[#C2447F]" />
          lower tiers override higher
          <span className="inline-block h-[5px] w-[5px] rotate-45 bg-[#C2447F]" />
        </p>
      </div>
    </div>
  );
}

function ScheduleBanner() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3.5 px-6 text-center font-mono">
      <p className="rounded bg-[#C2447F] px-4 py-2 text-[12px] text-[#FFF0F8]">
        $ geode &quot;schedule daily standup reminder at 9am&quot;
      </p>
      <p className="text-[11px]" style={{ color: ROSE_INK_70 }}>
        cron · briefings · unattended through the gateway
      </p>
    </div>
  );
}

/** Sub-agents are instances of the same loop (core/agent/sub_agent.py). */
function DelegateDiagram() {
  return (
    <svg viewBox="0 0 340 200" className="w-full max-w-[340px]" role="img" aria-label="sub-agent fan-out">
      <rect x="120" y="16" width="100" height="26" fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
      <text x="170" y="33" textAnchor="middle" fontSize="10.5" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>while(tool_use)</text>
      {[46, 170, 294].map((x) => (
        <g key={x}>
          <line x1="170" y1="42" x2={x} y2="118" stroke={ROSE_INK} strokeWidth="1" />
          <polygon points="-3.5,-3 0,4.5 3.5,-3" fill={ROSE_INK} transform={`translate(${x} ${120})`} />
          <rect x={x - 50} y={124} width={100} height={26} fill={PAPER} stroke={ROSE_INK} shapeRendering="crispEdges" />
          <text x={x} y={141} textAnchor="middle" fontSize="10.5" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK}>while(tool_use)</text>
        </g>
      ))}
      <text x="170" y="184" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill={ROSE_INK_70}>sub-agents are the same loop, isolated per task</text>
    </svg>
  );
}

const features: {
  id: string;
  plate: number;
  index: string;
  headKo: string;
  headEn: string;
  ko: string;
  en: string;
  banner: React.ReactNode;
}[] = [
  {
    id: "execute",
    plate: 1,
    index: "#1 execute",
    headKo: "루프를 돌립니다",
    headEn: "RUNS THE LOOP",
    ko: "계획, 실행, 관찰, 성찰, 검증, 재계획. 도구 호출이 멈출 때까지. 매 라운드 reflection이 가설과 확신도를 갱신합니다.",
    en: "Plan, act, observe, reflect, verify, replan, until tool calls stop. Each round a reflection call updates hypotheses and confidence.",
    banner: <LoopDiagram />,
  },
  {
    id: "perceive",
    plate: 2,
    index: "#2 perceive",
    headKo: "세계를 읽습니다",
    headEn: "SEES YOUR WORLD",
    ko: "턴마다 현재 시각과 메모리를 조립하고, PDF를 읽고, 당신의 진짜 Chrome에 CDP로 붙고, 데스크톱은 AX 트리부터 읽습니다.",
    en: "Per-turn context with the current time, PDF ingest, your real Chrome over CDP, and the desktop read AX-first.",
    banner: <PerceiveBanner />,
  },
  {
    id: "connect",
    plate: 6,
    index: "#3 connect",
    headKo: "하나의 에이전트, 모든 표면",
    headEn: "ONE AGENT, EVERY SURFACE",
    ko: "CLI, MCP 서버, Slack, cron 게이트웨이. 하나의 에이전트가 하나의 메모리로 모든 표면에, 직접 소유한 OAuth로 상주합니다.",
    en: "CLI, MCP server, Slack, and the cron gateway. One agent with one memory on every surface, over OAuth you own.",
    banner: <ConnectBanner />,
  },
  {
    id: "remember",
    plate: 7,
    index: "#4 remember",
    headKo: "쌓이는 기억",
    headEn: "MEMORY THAT COMPOUNDS",
    ko: "조직과 개인으로 층을 나눈 메모리를 SQL에 축적합니다. 세션을 넘어 당신과 프로젝트를 배우고, 턴마다 컨텍스트로 조립됩니다.",
    en: "Organization- and person-scoped memory tiers, accumulated in SQLite. It learns you and your projects across sessions, assembled into every turn.",
    banner: <MemoryBanner />,
  },
  {
    id: "schedule",
    plate: 8,
    index: "#5 schedule",
    headKo: "자리 비운 사이에도",
    headEn: "WORKS WHILE YOU'RE AWAY",
    ko: "보고서와 브리핑을 자연어로 예약합니다. 상주 게이트웨이가 무인으로 수행합니다.",
    en: "Natural-language scheduling for reports and briefings, running unattended through the resident gateway.",
    banner: <ScheduleBanner />,
  },
  {
    id: "delegate",
    plate: 9,
    index: "#6 delegate",
    headKo: "손은 여럿, 루프는 하나",
    headEn: "MANY HANDS, ONE LOOP",
    ko: "서브 에이전트, 플랜, 배치는 모두 같은 루프의 인스턴스입니다. 격리된 컨텍스트, 하나의 규율.",
    en: "Sub-agents, plans, and batches are all instances of the same loop. Isolated contexts, one discipline.",
    banner: <DelegateDiagram />,
  },
  {
    id: "audit",
    plate: 3,
    index: "#7 audit",
    headKo: "모든 변이는 심판대에",
    headEn: "EVERY MUTATION ON TRIAL",
    ko: "자기 손을 믿지 않습니다. 모든 스캐폴드 변이는 적대적 Petri 감사를 통과해야 하고, critical 축이 한 번이라도 후퇴하면 승격은 거부됩니다.",
    en: "It does not grade its own hand. Every scaffold mutation faces an adversarial Petri audit, and one critical regression vetoes promotion.",
    banner: <AuditGateDiagram />,
  },
  {
    id: "breed",
    plate: 4,
    index: "#8 breed",
    headKo: "시험은 점점 어려워집니다",
    headEn: "THE EXAM EVOLVES TOO",
    ko: "generator, critic, pilot, ranker, evolver. 시나리오를 대량으로 초안하고 양질만 선정해, 개선이 보일 측정 headroom을 계속 높입니다. 채점은 변이되지 않는 held-out 벤치의 몫입니다.",
    en: "Generator, critic, pilot, ranker, evolver. It drafts scenarios in bulk and keeps only the sharpest, raising the headroom that keeps improvement measurable; scoring belongs to a held-out bench that never mutates.",
    banner: <SeedgenDiagram />,
  },
  {
    id: "measure",
    plate: 5,
    index: "#9 measure",
    headKo: "정직하게 잽니다",
    headEn: "KEEPS HONEST SCORE",
    ko: "개선에 실패한 캠페인도 기록에 남습니다. 0 승격의 원인 규명까지가 실측 자산입니다.",
    en: "The campaigns that failed to improve it stay on the record, including why zero got promoted.",
    banner: <MeasureBanner />,
  },
];

/** One plate as a postcard: index, perforated Geodi stamp, art, caption. */
function PlateCard({ feature }: { feature: (typeof features)[number] }) {
  const locale = useLocale();
  return (
    <div className="flex flex-col bg-[#FFF0F8] p-4 pb-6" style={{ aspectRatio: "100/148" }}>
      <div className="flex items-start justify-between gap-3">
        <p className="pt-1 font-mono text-[10.5px] uppercase tracking-[0.22em]" style={{ color: ROSE_INK_70 }}>
          {feature.index}
        </p>
        <div
          className="flex h-12 w-11 shrink-0 items-center justify-center border border-dashed"
          style={{ borderColor: ROSE_INK_70 }}
        >
          <GeodiSprite scale={1.6} silhouette={ROSE_INK} />
        </div>
      </div>
      <div
        className="mt-3 min-h-0 flex-1 overflow-hidden bg-cover bg-center"
        style={{
          backgroundImage: `linear-gradient(rgba(255,240,248,0.8), rgba(255,240,248,0.8)), url(/geode/images/plate-bg-${feature.plate}.png)`,
          imageRendering: "pixelated",
        }}
      >
        <div className="flex h-full w-full items-center justify-center px-2 py-3">{feature.banner}</div>
      </div>
      <h2
        className="font-serif-display mt-4 text-balance text-[24px] font-black uppercase leading-[1.12] sm:text-[26px]"
        style={{ color: ROSE_INK }}
      >
        {locale === "en" ? feature.headEn : feature.headKo}
      </h2>
      <p className="mt-2 text-[12.5px] leading-[1.65]" style={{ color: ROSE_INK_70 }}>
        {t(locale, feature.ko, feature.en)}
      </p>
    </div>
  );
}

function FeaturesGrid() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const rows = [features.slice(0, 3), features.slice(3, 6), features.slice(6, 9)];
  return (
    <section id="features" className="bg-[var(--acc-artifact)]">
      <div className="mx-auto max-w-7xl px-6 py-16 sm:py-24">
        <p className="text-center font-mono text-[10.5px] uppercase tracking-[0.3em]" style={{ color: PAPER_75 }}>
          {t(locale, "도판 i-ix", "plates i-ix")}
        </p>
        {/* one postcard row per scroll step: the row rises as a unit */}
        <div className="mt-12 space-y-10">
          {rows.map((row, rowIndex) => (
            <div key={rowIndex} className="grid gap-8 md:grid-cols-2 xl:grid-cols-3">
              {row.map((feature, i) => (
                <motion.div
                  key={feature.id}
                  initial={{ opacity: 0, y: reduceMotion ? 0 : 46 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: "-140px" }}
                  transition={{ duration: 0.7, delay: i * 0.1, ease: [0.22, 1, 0.36, 1] }}
                >
                  <PlateCard feature={feature} />
                </motion.div>
              ))}
            </div>
          ))}
        </div>
        <div
          className="mt-16 flex items-end justify-between font-mono text-[10px] uppercase tracking-[0.18em]"
          style={{ color: PAPER_55 }}
        >
          <span>the fixed point · plates i-ix</span>
          <span>evidence: core/ · plugins/</span>
        </div>
      </div>
    </section>
  );
}

/* ---------------- the distillation, ending in the laboratory -------------- */

/**
 * Token snowfall: every flake gets its own deterministic fall speed, phase,
 * size, opacity, and lateral sway — organic drift instead of marching
 * columns. `converge` pulls spawn points toward the center (the funnel).
 */
function RainBand({
  phase,
  height,
  converge = 0,
  flakes = 24,
}: {
  phase: number;
  height: string;
  converge?: number;
  flakes?: number;
}) {
  const items = Array.from({ length: flakes }, (_, i) => {
    const a = ((i * 73 + phase * 131) % 97) / 97;
    const b = ((i * 149 + phase * 61) % 89) / 89;
    const c = ((i * 31 + phase * 17) % 83) / 83;
    return {
      left: a * 100,
      dur: 5 + b * 5,
      delay: -(c * 10),
      size: 4 + Math.round(b * 2),
      sway: 5 + c * 11,
      swayDur: 2.4 + a * 2.6,
      op: 0.45 + c * 0.55,
    };
  });
  return (
    <div aria-hidden className="relative w-full overflow-hidden" style={{ height }}>
      {items.map((f, i) => (
        <div key={i} className="absolute inset-y-0" style={{ left: `${f.left + (50 - f.left) * converge}%` }}>
          <div
            className="geodi-snow h-full"
            style={{ animationDuration: `${f.dur}s`, animationDelay: `${f.delay}s` }}
          >
            <span
              className="geodi-snow-sway block bg-[#FFF0F8]"
              style={{
                width: f.size,
                height: f.size,
                opacity: f.op,
                animationDuration: `${f.swayDur}s`,
                animationDelay: `${f.delay / 2}s`,
                ["--sway" as string]: `${f.sway}px`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * A filter is not drawn; it is only named. Hairlines dissolve toward the
 * edges, a pixel diamond flanks each side of the whispered label — the rule
 * reads as a threshold of light, not a drawn sieve.
 */
function FilterLine({ label }: { label: string }) {
  return (
    <div aria-hidden className="relative mx-auto flex w-full max-w-5xl items-center gap-4 px-8">
      <div className="h-px flex-1 bg-gradient-to-r from-transparent to-[rgba(255,240,248,0.55)]" />
      <span className="h-[5px] w-[5px] rotate-45 bg-[#FFF0F8] opacity-80" />
      <span className="font-mono text-[10.5px] uppercase tracking-[0.34em] text-[color-mix(in_srgb,#FFF0F8_88%,transparent)]">
        {label}
      </span>
      <span className="h-[5px] w-[5px] rotate-45 bg-[#FFF0F8] opacity-80" />
      <div className="h-px flex-1 bg-gradient-to-l from-transparent to-[rgba(255,240,248,0.55)]" />
    </div>
  );
}

/**
 * One continuous act: rain converges through named thresholds and fills the
 * full-bleed wordmark; keep scrolling past the finished distillate and the
 * laboratory reveals itself — a white stage enters, the rose field becomes a
 * specimen slide. Scroll drives only opacity/clip (RM keeps the fades).
 */
function DistillationAct() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: wrapRef, offset: ["start start", "end end"] });
  // Clip extends 15% past the line box: leading-[0.82] lets the pixel glyphs
  // overflow it, and a box-bounded clip would leave the letter caps unfilled.
  const fill = useTransform(scrollYProgress, [0.18, 0.55], ["inset(-15% 0 115% 0)", "inset(-15% 0 -15% 0)"]);
  const ledgerOp = useTransform(scrollYProgress, [0.48, 0.64], [0, 1]);
  const labOp = useTransform(scrollYProgress, [0.74, 0.9], [0, 1]);
  const labPointer = useTransform(labOp, (v) => (v > 0.55 ? "auto" : "none") as "auto" | "none");
  const ledger: { id: string; verdict: string; keep?: boolean }[] = [
    { id: "gen-2606-i1-004", verdict: "REJECT" },
    { id: "gen-2606-i2-001", verdict: "REJECT" },
    { id: "crucible-S1", verdict: "REJECT" },
    { id: "crucible-S5", verdict: "PENDING", keep: true },
  ];
  return (
    <section id="distill" ref={wrapRef} className="relative h-[340vh] bg-[var(--acc-artifact)]">
      {/* nav anchor: jumping to #lab lands where the laboratory has revealed */}
      <div id="lab" aria-hidden className="absolute left-0 top-[76%] h-px w-px" />
      <div className="sticky top-0 flex h-screen flex-col overflow-hidden">
        <div className="pointer-events-none absolute left-5 top-8 z-20 max-w-[360px] text-left sm:left-10 sm:top-12">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.3em]" style={{ color: PAPER_75 }}>
            {t(locale, "증류", "the distillation")}
          </p>
          <h2 className="font-serif-display mt-3 text-balance text-[clamp(1.6rem,3.1vw,2.3rem)] font-black leading-[1.22] text-[#FFF0F8]">
            {t(locale, "천 번의 토큰을 걸러, 한 방울로.", "A thousand tokens, filtered to a single drop.")}
          </h2>
        </div>

        <div className="flex min-h-0 flex-1 flex-col justify-center">
          <RainBand phase={0} height="12vh" flakes={96} />
          <FilterLine label="critic" />
          <RainBand phase={1} height="9vh" converge={0.42} flakes={56} />
          <FilterLine label="petri gate" />
          <RainBand phase={2} height="7vh" converge={0.78} flakes={30} />
          <FilterLine label="held-out" />
          <RainBand phase={1} height="5vh" converge={0.92} flakes={16} />
        </div>

        <div className="flex flex-col items-center pb-8">
          {/* the word takes the whole width — the distillate is the wordmark */}
          <div className="relative w-full text-center">
            <p className="font-pixel whitespace-nowrap text-[24vw] font-bold leading-[0.82] text-[#FFF0F8] opacity-25">
              GEODE
            </p>
            <motion.p
              aria-hidden
              style={{ clipPath: reduceMotion ? "inset(-15% 0 -15% 0)" : fill }}
              className="font-pixel absolute inset-0 whitespace-nowrap text-[24vw] font-bold leading-[0.82] text-[#FFF0F8]"
            >
              GEODE
            </motion.p>
          </div>
          <motion.div
            style={{ opacity: reduceMotion ? 1 : ledgerOp }}
            className="mt-6 w-full max-w-3xl border-t border-[color-mix(in_srgb,#FFF0F8_50%,transparent)] px-6 pt-4"
          >
            <div className="flex flex-wrap items-baseline justify-center gap-x-7 gap-y-2 font-mono text-[11.5px]">
              <span className="uppercase tracking-[0.24em]" style={{ color: PAPER_75 }}>
                baseline ledger
              </span>
              {ledger.map((row) => (
                <span key={row.id} className={row.keep ? "text-[#FFF0F8]" : "text-[color-mix(in_srgb,#FFF0F8_60%,transparent)]"}>
                  {row.id} · {row.verdict}
                </span>
              ))}
            </div>
            <p className="mt-4 text-center font-serif-display text-[15px] font-semibold leading-[1.6] text-[#FFF0F8]">
              {t(
                locale,
                "첫 방울은 아직 매달려 있습니다. 기록은 그 무게까지 답니다.",
                "The first drop is still forming. The ledger weighs even that."
              )}
            </p>
          </motion.div>
        </div>

        {/* final act: white enters — the rose field becomes a specimen slide on a paper stage */}
        <motion.div style={{ opacity: labOp, pointerEvents: labPointer }} className="absolute inset-0 bg-[#FFF0F8]">
          <div className="absolute inset-x-2 bottom-12 top-2 bg-[var(--acc-artifact)] sm:inset-x-3 sm:top-3" />
          {/* ghost distillate: replicates the visible act's column layout so the
              crossfade keeps the word at identical coordinates — keep the
              invisible spacers in sync with the markup above */}
          <div aria-hidden className="pointer-events-none absolute inset-0 flex flex-col overflow-hidden">
            <div className="min-h-0 flex-1" />
            <div className="flex flex-col items-center pb-8">
              <p className="font-pixel w-full whitespace-nowrap text-center text-[24vw] font-bold leading-[0.82] text-[#FFF0F8] opacity-[0.16]">
                GEODE
              </p>
              <div className="invisible mt-6 w-full max-w-3xl border-t px-6 pt-4">
                <div className="flex flex-wrap items-baseline justify-center gap-x-7 gap-y-2 font-mono text-[11.5px]">
                  <span className="uppercase tracking-[0.24em]">baseline ledger</span>
                  {ledger.map((row) => (
                    <span key={`ghost-${row.id}`}>
                      {row.id} · {row.verdict}
                    </span>
                  ))}
                </div>
                <p className="font-serif-display mt-4 text-center text-[15px] font-semibold leading-[1.6]">
                  {t(
                    locale,
                    "첫 방울은 아직 매달려 있습니다. 기록은 그 무게까지 답니다.",
                    "The first drop is still forming. The ledger weighs even that."
                  )}
                </p>
              </div>
            </div>
          </div>
          <div className="absolute inset-x-2 bottom-12 top-2 sm:inset-x-3 sm:top-3">
            <div className="relative z-10 mx-auto flex h-full max-w-5xl flex-col items-center justify-center gap-7 px-6 text-center">
              <div>
                <p className="font-mono text-[10.5px] uppercase tracking-[0.42em]" style={{ color: PAPER_75 }}>
                  edited by
                </p>
                <h2 className="font-serif-display mt-2 text-balance text-[clamp(2.6rem,6.4vw,4.5rem)] font-black leading-[1.05] tracking-[0.04em] text-[#FFF0F8]">
                  MANGO
                </h2>
              </div>
              <div className="flex h-48 w-48 items-center justify-center rounded-full border border-[#FFF0F8] sm:h-56 sm:w-56">
                <GeodiSprite scale={4} silhouette="#FFF0F8" />
              </div>
              <p className="font-serif-display max-w-xl text-[clamp(1.05rem,2.4vw,1.4rem)] font-semibold leading-[1.6] text-[#FFF0F8]">
                {t(locale, "실패를 기록하고, 스스로를 고쳐 씁니다.", "It records its failures, and rewrites itself.")}
              </p>
              <div className="mt-2 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
                <Link
                  href="/docs"
                  className="inline-flex touch-manipulation items-center rounded bg-[#FFF0F8] px-5 py-2.5 text-[14px] font-medium text-[#C2447F] transition-opacity hover:opacity-85"
                >
                  {t(locale, "문서 읽기", "Read the docs")}
                </Link>
                <a
                  href="https://github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md"
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-[13px] text-[#FFF0F8] underline decoration-[color-mix(in_srgb,#FFF0F8_45%,transparent)] underline-offset-4 transition-opacity hover:opacity-75"
                >
                  {t(locale, "전체 기록 보기", "View the full record")}
                </a>
              </div>
              <div className="mt-6 flex flex-col items-center gap-2.5">
                <p className="font-mono text-[10px] uppercase tracking-[0.3em]" style={{ color: PAPER_75 }}>
                  {t(locale, "실험 기록 · 승격 0회까지 그대로", "experiment records · zero promotions included")}
                </p>
                <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 font-mono text-[12px]">
                  <a
                    href="/geode/self-improving/"
                    className="text-[#FFF0F8] underline decoration-[color-mix(in_srgb,#FFF0F8_45%,transparent)] underline-offset-4 transition-opacity hover:opacity-75"
                  >
                    {t(locale, "self-improving 허브", "self-improving hub")}
                  </a>
                  <a
                    href="/geode/self-improving/petri-bundle/"
                    className="text-[#FFF0F8] underline decoration-[color-mix(in_srgb,#FFF0F8_45%,transparent)] underline-offset-4 transition-opacity hover:opacity-75"
                  >
                    {t(locale, "petri 감사 아카이브", "petri audit archive")}
                  </a>
                </div>
              </div>
            </div>
          </div>
          <div
            className="absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-3.5 font-mono text-[10px] uppercase tracking-[0.18em]"
            style={{ color: ROSE_INK }}
          >
            <span className="pointer-events-none">specimen · geodi</span>
            <a
              href="/geode/self-improving/petri-bundle/"
              className="underline decoration-[color-mix(in_srgb,#C2447F_45%,transparent)] underline-offset-4 transition-opacity hover:opacity-75"
              style={{ color: ROSE_INK }}
            >
              petri audit attached
            </a>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

/* ---------------- page ----------------------------------------------------- */

export default function GeodePortfolioPage() {
  return (
    <LocaleProvider defaultLocale="en">
      <main
        data-astryx-theme="neutral"
        className={`${galmuri.variable} ${serifDisplay.variable} min-h-screen overflow-x-clip bg-[var(--acc-artifact)] text-[#FFF0F8]`}
      >
        <GeodeNav items={navItems} light />
        <HeroField />
        <RunRow />
        <FeaturesGrid />
        <DistillationAct />
      </main>
    </LocaleProvider>
  );
}
