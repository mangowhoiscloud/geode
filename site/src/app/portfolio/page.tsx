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

import { firstRelease, latestRelease, releaseCount } from "./growth";

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

/* ---------------- hero: terminal product moment -------------------------- */

function TerminalMock() {
  const locale = useLocale();
  return (
    <figure className="mx-auto w-full max-w-2xl">
      <div className="overflow-hidden rounded-lg border border-[color-mix(in_srgb,#FFF0F8_35%,transparent)] bg-[var(--paper-deep)] text-left">
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
      <figcaption className="mx-auto mt-3 w-fit rounded bg-[#FFF0F8] px-3 py-1 text-center font-mono text-[10.5px] text-[var(--acc-artifact)]">
        core/ui/mascot.py · geodi_art.py{" "}
        <span className="text-[var(--acc-artifact)]">
          {t(locale, "CLI 웰컴 스크린을 그대로 옮긴 화면", "the CLI welcome screen, transcribed")}
        </span>
      </figcaption>
    </figure>
  );
}

function HeroField() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const { scrollY } = useScroll();
  const fieldOpacity = useTransform(scrollY, [0, 700], [1, 0.25]);
  const fieldScale = useTransform(scrollY, [0, 700], [1, 0.965]);
  // Reduced motion keeps the fades but drops movement/scale.
  const heroItem = {
    hidden: { opacity: 0, y: reduceMotion ? 0 : 24 },
    show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] as const } },
  };
  return (
    <section id="hero">
      {/* Rose color field, Hermes split composition: editorial serif statement
          left, white-line engraving of the mascot right, corner stamps. */}
      <div className="relative overflow-hidden bg-[var(--acc-artifact)]">
        <motion.div style={{ opacity: fieldOpacity, scale: reduceMotion ? 1 : fieldScale }}>
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
          <span className="font-pixel text-[19px] font-bold tracking-[0.06em] text-[#FFF0F8]">GEODE</span>
        </div>

        <div className="relative z-10 mx-auto max-w-7xl px-5 pb-14 pt-10 sm:px-8 lg:pb-16 lg:pt-14">
          <motion.div
            className="relative z-10"
            initial="hidden"
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.1, delayChildren: 0.05 } } }}
          >
            <motion.p variants={heroItem} className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_70%,transparent)]">
              open source · apache-2.0 · {t(locale, "루프 실험실", "the loop laboratory")}
            </motion.p>
            <motion.h1 variants={heroItem} className="font-serif-display mt-7 text-balance text-[clamp(2.5rem,5.8vw,4.4rem)] font-black leading-[1.12] text-[#FFF0F8]">
              {t(locale, "일을 맡기면", "The agent that")}
              <br />
              {t(locale, "끝까지 실행하고,", "executes to the end,")}
              <br />
              {t(locale, "스스로를 고쳐 씁니다.", "and rewrites itself.")}
            </motion.h1>

            <motion.p variants={heroItem} className="mt-10 font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_70%,transparent)]">
              run via terminal
            </motion.p>
            <motion.div variants={heroItem} className="mt-3 inline-block rounded bg-[#FFF0F8] px-5 py-3 text-left font-mono text-[12.5px] text-[var(--acc-artifact)] sm:text-[13.5px]">
              <span className="text-[var(--acc-artifact)]">$</span> uv run geode{" "}
              <span className="text-[var(--acc-artifact)]">
                &quot;{t(locale, "이 레포 점검하고 릴리스 블로커 요약해줘", "inspect this repo and summarize release blockers")}&quot;
              </span>
            </motion.div>

            <motion.div variants={heroItem} className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-3">
              <Link
                href="/docs"
                className="inline-flex touch-manipulation items-center rounded bg-[#FFF0F8] px-5 py-2.5 text-[14px] font-medium text-[var(--acc-artifact)] transition-opacity hover:opacity-85"
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
          </motion.div>

        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-[color-mix(in_srgb,#FFF0F8_60%,transparent)] sm:px-8">
          <span>geode v{GEODE_SOT.version}</span>
          <span>apache-2.0 · 2026</span>
        </div>
        </motion.div>
      </div>
    </section>
  );
}

/** Product band: the CLI welcome terminal floating on the field. */
function GalleryBand() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  return (
      <div className="relative flex h-[480px] w-full items-center justify-center bg-[var(--acc-artifact)] px-4 sm:h-[560px] sm:px-6">
        <motion.div
          initial={{ opacity: 0, y: reduceMotion ? 0 : 46 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.85, ease: [0.22, 1, 0.36, 1] }}
        >
          <TerminalMock />
        </motion.div>
      </div>
  );
}

/** Scroll-driven stage lighting (opacity-only, RM-safe). */
function StageLight({ children, className }: { children: React.ReactNode; className?: string }) {
  const lightRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: lightRef, offset: ["start end", "end start"] });
  const shade = useTransform(scrollYProgress, [0, 0.22, 0.78, 1], [0.5, 0, 0, 0.5]);
  return (
    <div ref={lightRef} className={`relative ${className ?? ""}`}>
      {children}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-30 bg-[var(--acc-artifact)]"
        style={{ opacity: shade }}
      />
    </div>
  );
}

const LOOP_NODES = [
  { label: "Perceive" },
  { label: "Plan" },
  { label: "Act" },
  { label: "Observe" },
  { label: "Verify" },
  { label: "Replan" },
];

/** The while(tool_use) cycle as a rose-ink ring on the white plate. */
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
    <svg viewBox="0 0 340 300" className="w-full max-w-[380px]" role="img"
      aria-label={t(locale, "while tool_use 루프 다이어그램", "while tool_use loop diagram")}>
      {points.map((node, i) => {
        const next = points[(i + 1) % points.length];
        const mx = (node.x + next.x) / 2;
        const my = (node.y + next.y) / 2;
        const angleDeg = (Math.atan2(next.y - node.y, next.x - node.x) * 180) / Math.PI;
        return (
          <g key={`edge-${node.label}`}>
            <line x1={node.x} y1={node.y} x2={next.x} y2={next.y} stroke="var(--acc-artifact)" strokeWidth="1" />
            <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform={`translate(${mx} ${my}) rotate(${angleDeg})`} />
          </g>
        );
      })}
      <line x1={cx} y1={cy + 30} x2={cx} y2={262} stroke="var(--acc-artifact)" strokeWidth="1" strokeDasharray="2 3" />
      <polygon points="-3.5,-3 0,4 3.5,-3" fill="var(--acc-artifact)" transform={`translate(${cx} ${262})`} />
      <rect x={cx - 38} y={264} width={76} height={22} fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x={cx} y={279} textAnchor="middle" fontSize="10.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">finalize</text>
      <text x={cx + 8} y={cy + 66} textAnchor="start" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">no tool_use</text>
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize="15" className="font-pixel" fill="var(--acc-artifact)">while</text>
      <text x={cx} y={cy + 14} textAnchor="middle" fontSize="15" className="font-pixel" fill="var(--acc-artifact)">(tool_use)</text>
      {points.map((node) => (
        <g key={node.label}>
          <rect x={node.x - nodeW / 2} y={node.y - nodeH / 2} width={nodeW} height={nodeH}
            fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
          <text x={node.x} y={node.y + 3.5} textAnchor="middle" fontSize="10.5"
            fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">{node.label}</text>
        </g>
      ))}
    </svg>
  );
}

/** Adversarial audit as a promotion gate — rose ink schematic. */
function AuditGateDiagram() {
  const locale = useLocale();
  const dims = [26, 34, 20, 38, 30, 42];
  return (
    <svg viewBox="0 0 520 170" className="w-full max-w-[520px]" role="img"
      aria-label={t(locale, "감사 게이트 도식", "audit gate schematic")}>
      <rect x="8" y="72" width="92" height="26" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="54" y="88" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">scaffold 변이</text>
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(116 85)" />
      <line x1="100" y1="85" x2="128" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />
      <rect x="132" y="28" width="150" height="116" fill="none" stroke="var(--acc-artifact)" strokeDasharray="3 3" shapeRendering="crispEdges" />
      <text x="207" y="20" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">adversarial audit</text>
      <rect x="147" y="40" width="120" height="22" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="207" y="54" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">Petri auditor</text>
      <rect x="147" y="108" width="120" height="22" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="207" y="122" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">GEODE</text>
      {[171, 207, 243].map((x) => (
        <line key={x} x1={x} y1="64" x2={x} y2="106" stroke="var(--acc-artifact)" strokeWidth="1" strokeDasharray="2 2" />
      ))}
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(302 85)" />
      <line x1="282" y1="85" x2="314" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />
      {dims.map((h, i) => (
        <rect key={i} x={320 + i * 13} y={104 - h} width={9} height={h}
          fill="var(--acc-artifact)" opacity={i === 3 ? 1 : 0.55} shapeRendering="crispEdges" />
      ))}
      <line x1="316" y1="76" x2="402" y2="76" stroke="var(--acc-artifact)" strokeWidth="1" strokeDasharray="4 2" />
      <text x="359" y="120" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">critical floor</text>
      <line x1="406" y1="85" x2="430" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />
      <line x1="430" y1="85" x2="446" y2="52" stroke="var(--acc-artifact)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(448 49) rotate(-64)" />
      <rect x="446" y="30" width="66" height="20" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="479" y="43" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">promote</text>
      <line x1="430" y1="85" x2="446" y2="118" stroke="var(--acc-artifact)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(448 121) rotate(64)" />
      <rect x="446" y="120" width="66" height="20" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="479" y="133" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">reject</text>
      <text x="470" y="90" textAnchor="middle" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">gate·random·never</text>
    </svg>
  );
}

/** Seed hypothesis factory — rose ink pipeline. */
function SeedgenDiagram() {
  const locale = useLocale();
  const stages = ["generator", "critic", "pilot", "ranker", "evolver"];
  const seedCols = [4, 3, 2, 2, 5];
  return (
    <svg viewBox="0 0 520 150" className="w-full max-w-[520px]" role="img"
      aria-label={t(locale, "시드 생성 파이프라인 도식", "seed-generation pipeline schematic")}>
      {stages.map((stage, i) => (
        <g key={stage}>
          <rect x={8 + i * 88} y="34" width="76" height="24" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
          <text x={46 + i * 88} y="49" textAnchor="middle" fontSize="10"
            fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">{stage}</text>
          {i < 4 && (
            <g>
              <line x1={84 + i * 88} y1="46" x2={96 + i * 88} y2="46" stroke="var(--acc-artifact)" strokeWidth="1" />
              <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform={`translate(${95 + i * 88} 46)`} />
            </g>
          )}
          {Array.from({ length: seedCols[i] }).map((_, seed) => (
            <rect key={seed} x={30 + i * 88 + seed * 9} y="16" width="5" height="5"
              fill="var(--acc-artifact)" opacity={i === 4 ? 1 : 0.7} shapeRendering="crispEdges" />
          ))}
          {i > 0 && i < 4 && (
            <g opacity="0.35">
              <rect x={36 + i * 88} y="78" width="5" height="5" fill="var(--acc-artifact)" shapeRendering="crispEdges" />
              <rect x={50 + i * 88} y="92" width="5" height="5" fill="var(--acc-artifact)" shapeRendering="crispEdges" />
            </g>
          )}
        </g>
      ))}
      <text x="260" y="116" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        {t(locale, "후보는 단계마다 떨어지고, top-5 생존자만 시드 풀에 남습니다", "candidates drop at every stage; only the top-5 survivors reach the seed pool")}
      </text>
      <text x="260" y="134" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
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
    <section id="run" className="bg-[#FFF0F8]">
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-20 text-center sm:py-24 md:grid-cols-3">
        {runModes.map((mode) => (
          <div key={mode.cmd}>
            <p className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]">{mode.eyebrow}</p>
            <h2 className="font-serif-display mt-3 text-[30px] font-semibold text-[var(--acc-artifact)]">
              {locale === "en" ? mode.titleEn : mode.titleKo}
            </h2>
            <p className="mx-auto mt-3 inline-block rounded bg-[var(--acc-artifact)] px-4 py-2 font-mono text-[13px] text-[#FFF0F8]">
              {mode.cmd}
            </p>
            <p className="mx-auto mt-3 max-w-[260px] text-[13px] leading-[1.7] text-[var(--acc-artifact)]">
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
const SLAB_INK = "#FFF0F8";
const SLAB_ACCENT = "color-mix(in srgb, #FFF0F8 72%, transparent)";

function PerceiveBanner() {
  return (
    <div className="flex h-full w-full flex-col justify-center gap-2.5 px-6 font-mono text-[12px] leading-relaxed">
      <p><span className="text-[var(--acc-artifact)]">context</span><span className="text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]"> · per-turn time, memory, rules</span></p>
      <p><span className="text-[var(--acc-artifact)]">documents</span><span className="text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]"> · local pdf ingest</span></p>
      <p><span className="text-[var(--acc-artifact)]">browser</span><span className="text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]"> · your real chrome, over cdp</span></p>
      <p><span className="text-[var(--acc-artifact)]">desktop</span><span className="text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]"> · ax tree before pixels</span></p>
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
            <p className="font-serif-display text-[26px] font-black text-[var(--acc-artifact)]">{cell.value}</p>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.2em] text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]">{cell.label}</p>
          </div>
        ))}
      </div>
      <p className="text-center font-mono text-[10px] uppercase tracking-[0.14em] text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]">
        tau2-bench base · native user_simulator
      </p>
    </div>
  );
}

function ResideBanner() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 px-6">
      <div className="font-mono text-[12px] leading-relaxed text-[var(--acc-artifact)]">
        <p>anthropic · openai / codex · glm</p>
        <p className="text-center text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]">oauth you own · provider-isolated</p>
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
    ko: "계획, 실행, 관찰, 검증, 재계획. 도구 호출이 멈출 때까지. 예산은 프롬프트 문구가 아니라 루프의 탈출 조건입니다.",
    en: "Plan, act, observe, verify, replan — until tool calls stop. Budgets are exit conditions, not prompt wording.",
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
    id: "audit",
    plate: 3,
    index: "#3 audit",
    headKo: "스스로를 감사합니다",
    headEn: "AUDITS ITSELF",
    ko: "모든 스캐폴드 변이는 적대적 Petri 감사를 통과해야 합니다. critical 축이 한 번이라도 후퇴하면 승격은 거부됩니다.",
    en: "Every scaffold mutation faces an adversarial Petri audit. One critical regression vetoes promotion.",
    banner: <AuditGateDiagram />,
  },
  {
    id: "breed",
    plate: 4,
    index: "#4 breed",
    headKo: "시험도 스스로 만듭니다",
    headEn: "BREEDS ITS OWN TESTS",
    ko: "generator, critic, pilot, ranker, evolver. 평가 시드 풀이 에이전트와 나란히 자랍니다.",
    en: "Generator, critic, pilot, ranker, evolver. The evaluation pool grows alongside the agent.",
    banner: <SeedgenDiagram />,
  },
  {
    id: "measure",
    plate: 5,
    index: "#5 measure",
    headKo: "정직하게 잽니다",
    headEn: "KEEPS HONEST SCORE",
    ko: "개선에 실패한 캠페인도 기록에 남습니다. 0 승격의 원인 규명까지가 실측 자산입니다.",
    en: "The campaigns that failed to improve it stay on the record — including why zero got promoted.",
    banner: <MeasureBanner />,
  },
  {
    id: "reside",
    plate: 6,
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
  const reduceMotion = useReducedMotion();
  const slabRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: slabRef, offset: ["start end", "end start"] });
  const bannerDrift = useTransform(scrollYProgress, [0, 1], [12, -12]);
  return (
    <section id="features" ref={slabRef} className="bg-[var(--acc-artifact)]">
      <div className="mx-auto max-w-7xl px-6 py-20 sm:py-28">
        <div className="grid gap-x-8 gap-y-16 md:grid-cols-2 xl:grid-cols-3">
          {features.map((feature) => (
            <div key={feature.id}>
              <p className="font-mono text-[11px] uppercase tracking-[0.26em]" style={{ color: SLAB_ACCENT }}>
                {feature.index}
              </p>
              <h2
                className="font-serif-display mt-3 text-balance text-[30px] font-black uppercase leading-[1.08] sm:text-[34px]"
                style={{ color: SLAB_INK }}
              >
                {locale === "en" ? feature.headEn : feature.headKo}
              </h2>
              <div
                className="mt-5 h-[240px] overflow-hidden rounded-sm bg-[#FFF0F8] bg-cover bg-center"
                style={{ backgroundImage: `url(/geode/images/plate-bg-${feature.plate}.png)`, imageRendering: "pixelated" }}
              >
                <motion.div
                  className="flex h-full items-center justify-center px-4 py-3"
                  style={{ y: reduceMotion ? 0 : bannerDrift }}
                >
                  {feature.banner}
                </motion.div>
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

/* ---------------- the distillation: rain, sieves, drainpipe, the word ---- */

const RAIN_COLS = [7, 16, 24, 33, 41, 52, 60, 69, 77, 86, 93] as const;

function RainBand({
  keep,
  phase,
  height = "34vh",
  converge = 0,
}: {
  keep: number;
  phase: number;
  height?: string;
  converge?: number;
}) {
  const cols = RAIN_COLS.filter((_, i) => (i * 7 + phase * 3) % 10 < keep * 10);
  return (
    <div aria-hidden className="relative w-full overflow-hidden" style={{ height }}>
      {cols.map((left, i) => (
        <div
          key={left}
          className="geodi-rain absolute top-[-8%] flex h-[116%] flex-col justify-between"
          style={{ left: `${left + (50 - left) * converge}%`, animationDelay: `${(i * 0.37 + phase * 0.19) % 2.4}s` }}
        >
          {Array.from({ length: 13 }).map((_, k) => (
            <span key={k} className="h-[6px] w-[6px] bg-[#FFF0F8]" style={{ opacity: k % 3 === phase % 3 ? 1 : 0.55 }} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** A filter is not drawn; it is only named. Hairline + a small label chip. */
function FilterLine({ label }: { label: string }) {
  return (
    <div aria-hidden className="relative mx-auto flex w-full max-w-4xl items-center justify-center px-6">
      <div className="absolute inset-x-6 top-1/2 h-px bg-[color-mix(in_srgb,#FFF0F8_45%,transparent)]" />
      <span className="relative z-10 bg-[var(--acc-artifact)] px-3">
        <Token label={label} size="sm" />
      </span>
    </div>
  );
}

/** Rain through sieves, down the drainpipe, filling the word itself. */
function DistillationAct() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: wrapRef, offset: ["start start", "end end"] });
  const descend = useTransform(scrollYProgress, [0.04, 1], ["0vh", "-118vh"]);
  const fill = useTransform(scrollYProgress, [0.55, 0.92], ["inset(0 0 100% 0)", "inset(0 0 0% 0)"]);
  const ledger: { id: string; verdict: string; keep?: boolean }[] = [
    { id: "gen-2606-i1-004", verdict: "REJECT · margin < floor" },
    { id: "gen-2606-i2-001", verdict: "REJECT · critical regress" },
    { id: "crucible-S1", verdict: "REJECT · full paired run" },
    { id: "crucible-S5", verdict: "EVOLVE-BLOCK · pending", keep: true },
  ];
  return (
    <section ref={wrapRef} className="relative h-[260vh] bg-[var(--acc-artifact)]">
      <div className="sticky top-0 h-screen overflow-hidden">
        <div className="pointer-events-none absolute left-5 top-8 z-20 max-w-[320px] text-left sm:left-10 sm:top-12">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_70%,transparent)]">
            {t(locale, "증류", "the distillation")}
          </p>
          <h2 className="font-serif-display mt-3 text-balance text-[clamp(1.5rem,3vw,2.2rem)] font-black leading-[1.25] text-[#FFF0F8]">
            {t(
              locale,
              "천 번의 토큰이 한 단어가 될 때까지.",
              "A thousand tokens, distilled into one word."
            )}
          </h2>
        </div>

        <motion.div style={{ y: reduceMotion ? "-118vh" : descend }} className="relative">
          <RainBand keep={1} phase={0} />
          <FilterLine label="critic" />
          <RainBand keep={0.55} phase={1} converge={0.42} />
          <FilterLine label="petri gate" />
          <RainBand keep={0.25} phase={2} height="30vh" converge={0.78} />
          <FilterLine label="held-out" />
          
          {/* the survivors keep falling onto the word — shaved-ice piling */}
          <div className="flex h-[78vh] flex-col items-center justify-center gap-12 px-6">
            <div className="relative">
              <div aria-hidden className="absolute inset-x-0 -top-[26vh] flex h-[26vh] justify-center gap-14 overflow-hidden">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="geodi-rain flex h-[120%] flex-col justify-between" style={{ animationDelay: `${i * 0.8}s` }}>
                    {Array.from({ length: 5 }).map((_, k) => (
                      <span key={k} className="h-[6px] w-[6px] bg-[#FFF0F8]" style={{ opacity: k % 2 ? 0.6 : 1 }} />
                    ))}
                  </div>
                ))}
              </div>
              <p className="font-pixel whitespace-nowrap text-[13vw] font-bold leading-none text-[#FFF0F8] opacity-25">
                GEODE
              </p>
              <motion.p
                aria-hidden
                style={{ clipPath: reduceMotion ? "inset(0 0 0 0)" : fill }}
                className="font-pixel absolute inset-0 whitespace-nowrap text-[13vw] font-bold leading-none text-[#FFF0F8]"
              >
                GEODE
              </motion.p>
            </div>
            <div className="w-full max-w-xl border-t border-[color-mix(in_srgb,#FFF0F8_50%,transparent)]">
              <p className="mt-3 font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_70%,transparent)]">
                baseline ledger
              </p>
              <div className="mt-4 space-y-2.5 font-mono text-[12.5px]">
                {ledger.map((row) => (
                  <div key={row.id} className="flex items-baseline justify-between gap-4">
                    <span className={row.keep ? "text-[#FFF0F8]" : "text-[color-mix(in_srgb,#FFF0F8_55%,transparent)]"}>
                      {row.id}
                    </span>
                    <span className={row.keep ? "text-[#FFF0F8]" : "text-[color-mix(in_srgb,#FFF0F8_55%,transparent)]"}>
                      {row.verdict}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-6 font-serif-display text-[15.5px] font-semibold leading-[1.6] text-[#FFF0F8]">
                {t(
                  locale,
                  "첫 방울은 아직 매달려 있습니다. 기록은 그 무게까지 답니다.",
                  "The first drop is still forming. The ledger weighs even that."
                )}
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

/* ---------------- wordmark -> laboratory crossfade ----------------------- */

function WordToLab() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const xRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: xRef, offset: ["start start", "end end"] });
  const wordOp = useTransform(scrollYProgress, [0.18, 0.5], [1, 0]);
  const labOp = useTransform(scrollYProgress, [0.42, 0.72], [0, 1]);
  const ghostScale = useTransform(scrollYProgress, [0.4, 1], [1.12, 0.98]);
  return (
    <div id="lab" ref={xRef} className="relative h-[240vh] bg-[var(--acc-artifact)]">
      <div className="sticky top-0 h-screen overflow-hidden">
        {/* act 1: the word, fading as the lab arrives */}
        <motion.div
          aria-hidden
          style={{ opacity: reduceMotion ? 0 : wordOp }}
          className="absolute inset-0 flex select-none items-center justify-center"
        >
          <p className="font-pixel whitespace-nowrap text-[24.5vw] font-bold leading-[0.9] text-[#FFF0F8]">GEODE</p>
        </motion.div>

        {/* act 2: black enters — the pink field becomes a specimen slide on a dark stage */}
        <motion.div style={{ opacity: reduceMotion ? 1 : labOp }} className="absolute inset-0 bg-[#141016]">
          <div className="absolute inset-x-2 bottom-12 top-2 bg-[var(--acc-artifact)] sm:inset-x-3 sm:top-3">
            <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden">
              <motion.span
                style={{ scale: reduceMotion ? 1 : ghostScale }}
                className="font-pixel select-none whitespace-nowrap text-[24vw] font-bold leading-none text-[#141016] opacity-[0.08]"
              >
                GEODE
              </motion.span>
            </div>
            <div className="relative z-10 mx-auto flex h-full max-w-5xl flex-col items-center justify-center gap-7 px-6 text-center">
              <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#141016_72%,transparent)]">
                cultured since {firstRelease.date} · release #{releaseCount} · v{latestRelease.version}
              </p>
              <h2 className="font-serif-display text-balance text-[clamp(2.4rem,6vw,4.2rem)] font-black leading-[1.1] text-[#141016]">
                {t(locale, "루프 실험실", "The Loop Laboratory")}
              </h2>
              <div className="flex h-48 w-48 items-center justify-center rounded-full border border-[#141016] sm:h-56 sm:w-56">
                <GeodiSprite scale={4} silhouette="#141016" />
              </div>
              <p className="font-serif-display max-w-xl text-[clamp(1.05rem,2.4vw,1.4rem)] font-semibold leading-[1.6] text-[#141016]">
                {t(locale, "실패를 기록하고, 스스로를 고쳐 씁니다.", "It records its failures, and rewrites itself.")}
              </p>
              <div className="mt-2 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
                <Link
                  href="/docs"
                  className="inline-flex touch-manipulation items-center rounded bg-[#141016] px-5 py-2.5 text-[14px] font-medium text-[#FFF0F8] transition-opacity hover:opacity-85"
                >
                  {t(locale, "문서 읽기", "Read the docs")}
                </Link>
                <a
                  href="https://github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md"
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-[13px] text-[#141016] underline decoration-[color-mix(in_srgb,#141016_45%,transparent)] underline-offset-4 transition-opacity hover:opacity-70"
                >
                  {t(locale, "전체 기록 보기", "View the full record")}
                </a>
              </div>
            </div>
          </div>
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-3.5 font-mono text-[10px] uppercase tracking-[0.18em] text-[color-mix(in_srgb,#FFF0F8_55%,transparent)] sm:px-8">
            <span>specimen · geodi</span>
            <span>petri audit attached</span>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

/* ---------------- page ---------------------------------------------------- *//* ---------------- page ---------------------------------------------------- */


export default function GeodePortfolioPage() {
  return (
    <LocaleProvider defaultLocale="en">
      <main
        data-astryx-theme="neutral"
        className={`${galmuri.variable} ${serifDisplay.variable} min-h-screen overflow-x-hidden bg-[var(--paper)] text-[var(--acc-artifact)]`}
      >
        <GeodeNav items={navItems} />
        {/* Act curtain stack: the hero field pins beneath the flow; every
            later act carries a solid background and slides over it. */}
        <div className="sticky top-0 z-0">
          <HeroField />
        </div>
        <div className="relative z-10">
          <StageLight>
            <GalleryBand />
          </StageLight>
          <StageLight>
            <RunRow />
          </StageLight>
          <StageLight>
            <FeaturesGrid />
          </StageLight>
          <DistillationAct />
          <WordToLab />
        </div>
      </main>
    </LocaleProvider>
  );
}
