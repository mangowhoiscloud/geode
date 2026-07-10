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
          <span className="ml-2 font-mono text-[11px] text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]">geode</span>
        </div>
        <div className="px-5 py-5 sm:px-7">
          <div className="flex items-center gap-6">
            <PlayfulSprite scale={5} blink className="geodi-bob shrink-0" />
            <div className="min-w-0 font-mono text-[12px] leading-[1.9] sm:text-[13px]">
              <p>
                <span className="text-[var(--acc-artifact)]">◆</span>{" "}
                <span className="font-semibold text-[var(--acc-artifact)]">GEODE</span>{" "}
                <span className="text-[var(--acc-artifact)]">v{GEODE_SOT.version}</span>
              </p>
              <p className="text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]">claude-opus-4-8 · ~/workspace/geode</p>
              <p className="text-[color-mix(in_srgb,var(--acc-artifact)_75%,transparent)]">/help for commands · type naturally</p>
            </div>
          </div>
          <div className="mt-4 border-t border-[var(--rule-soft)] pt-4 font-mono text-[12px] sm:text-[13px]">
            <p className="break-words">
              <span className="text-[var(--acc-artifact)]">&gt;</span>{" "}
              <span className="text-[var(--acc-artifact)]">
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

/** Crisp pixel cloud that drifts across (and past) frames. */
function PixelCloud({ className, flip = false }: { className?: string; flip?: boolean }) {
  return (
    <div
      aria-hidden
      className={`geodi-drift pointer-events-none absolute z-20 flex flex-col ${flip ? "items-start" : "items-center"} ${className ?? ""}`}
    >
      <div className="h-[8px] w-[30px] bg-[var(--acc-artifact)]" />
      <div className="h-[8px] w-[54px] bg-[var(--acc-artifact)]" />
    </div>
  );
}

function HeroField() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const { scrollY } = useScroll();
  const fieldOpacity = useTransform(scrollY, [0, 700], [1, 0.25]);
  const fieldScale = useTransform(scrollY, [0, 700], [1, 0.965]);
  // The Lanthimos zoom: scroll pushes the camera into the theatre.
  const sceneZoom = useTransform(scrollY, [0, 900], [1, 1.22]);
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

        <div className="relative z-10 mx-auto grid max-w-7xl items-center gap-6 px-5 pb-24 pt-10 sm:px-8 lg:grid-cols-[1.05fr_0.95fr] lg:pb-28 lg:pt-14">
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
              {t(locale, "컴퓨터의 모든 일을", "The agentic OS")}
              <br />
              {t(locale, "모델로 실행하고,", "that runs everything,")}
              <br />
              {t(locale, "스스로를 고쳐 쓰는 OS.", "and rewrites itself.")}
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

          <motion.div
            className="relative mx-auto w-full max-w-[440px]"
            initial={{ opacity: 0, y: reduceMotion ? 0 : 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
          >
            <PixelCloud className="-left-7 top-14" />
            <PixelCloud className="-right-6 bottom-24" flip />
            <motion.div
              animate={reduceMotion ? undefined : { y: [0, -7, 0] }}
              transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
              className="overflow-hidden"
            >
              <motion.div className="bg-[var(--acc-artifact)]" style={{ scale: reduceMotion ? 1 : sceneZoom, transformOrigin: "50% 78%" }}>
              <Image
                src="/geode/images/geode-etch-line.png"
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

/** Full-bleed gallery band: the theatre hall with the CLI terminal on stage. */
function GalleryBand() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const bandRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: bandRef, offset: ["start end", "end start"] });
  // Camera pulls back as the act arrives, then keeps drifting.
  const hallScale = useTransform(scrollYProgress, [0, 0.5, 1], [1.28, 1.06, 1]);
  return (
      <div ref={bandRef} className="relative w-full overflow-hidden">
        <motion.div style={{ scale: reduceMotion ? 1 : hallScale, transformOrigin: "50% 42%" }}>
          <Image
            src="/geode/images/geode-ripples-wide.png"
            alt=""
            aria-hidden
            width={2400}
            height={750}
            className="h-[480px] w-full select-none object-cover sm:h-[560px]"
            style={{ imageRendering: "pixelated" }}
          />
        </motion.div>
        <motion.div
          className="absolute inset-0 flex items-center justify-center px-4 sm:px-6"
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

const LOOP_NODES = [
  { label: "Perceive", color: "var(--acc-artifact)" },
  { label: "Plan", color: "var(--acc-artifact)" },
  { label: "Act", color: "var(--acc-artifact)" },
  { label: "Observe", color: "var(--acc-artifact)" },
  { label: "Verify", color: "var(--acc-artifact)" },
  { label: "Replan", color: "var(--acc-artifact)" },
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
            <line x1={node.x} y1={node.y} x2={next.x} y2={next.y} stroke="var(--acc-artifact)" strokeWidth="1" />
            <polygon
              points="-3,-3.5 4,0 -3,3.5"
              fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)"
              transform={`translate(${mx} ${my}) rotate(${angleDeg})`}
            />
          </g>
        );
      })}
      {/* exit: model answers without tool_use */}
      <line x1={cx} y1={cy + 30} x2={cx} y2={262} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="2 3" />
      <polygon points="-3.5,-3 0,4 3.5,-3" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)" transform={`translate(${cx} ${262})`} />
      <rect
        x={cx - 38}
        y={264}
        width={76}
        height={22}
        fill="#FFF0F8"
        stroke="var(--acc-artifact)"
        shapeRendering="crispEdges"
      />
      <text x={cx} y={279} textAnchor="middle" fontSize="10.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        finalize
      </text>
      <text x={cx + 8} y={cy + 66} textAnchor="start" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)">
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
            fill="#FFF0F8"
            stroke="var(--acc-artifact)"
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
      <rect x="8" y="72" width="92" height="26" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="54" y="88" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        scaffold 변이
      </text>
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)" transform="translate(116 85)" />
      <line x1="100" y1="85" x2="128" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />

      {/* adversarial arena */}
      <rect x="132" y="28" width="150" height="116" fill="none" stroke="var(--acc-artifact)" strokeDasharray="3 3" shapeRendering="crispEdges" />
      <text x="207" y="20" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)">
        adversarial audit
      </text>
      <rect x="147" y="40" width="120" height="22" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="207" y="54" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        Petri auditor
      </text>
      <rect x="147" y="108" width="120" height="22" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="207" y="122" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        GEODE
      </text>
      {[171, 207, 243].map((x) => (
        <line key={x} x1={x} y1="64" x2={x} y2="106" stroke="var(--acc-artifact)" strokeWidth="1" strokeDasharray="2 2" />
      ))}

      <polygon points="-3,-3.5 4,0 -3,3.5" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)" transform="translate(302 85)" />
      <line x1="282" y1="85" x2="314" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />

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
      <line x1="316" y1="76" x2="402" y2="76" stroke="var(--acc-artifact)" strokeWidth="1" strokeDasharray="4 2" />
      <text x="359" y="120" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)">
        critical floor
      </text>

      {/* gate branches */}
      <line x1="406" y1="85" x2="430" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />
      <line x1="430" y1="85" x2="446" y2="52" stroke="var(--acc-artifact)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(448 49) rotate(-64)" />
      <rect x="446" y="30" width="66" height="20" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="479" y="43" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        promote
      </text>
      <line x1="430" y1="85" x2="446" y2="118" stroke="var(--ink-3)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)" transform="translate(448 121) rotate(64)" />
      <rect x="446" y="120" width="66" height="20" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
      <text x="479" y="133" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)">
        reject
      </text>
      <text x="470" y="90" textAnchor="middle" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)">
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
          <rect x={8 + i * 88} y="34" width="76" height="24" fill="#FFF0F8" stroke="var(--acc-artifact)" shapeRendering="crispEdges" />
          <text
            x={46 + i * 88}
            y="49"
            textAnchor="middle"
            fontSize="10"
            fontFamily="var(--font-fira-code), monospace"
            fill="var(--acc-artifact)"
          >
            {stage}
          </text>
          {i < 4 && (
            <g>
              <line x1={84 + i * 88} y1="46" x2={96 + i * 88} y2="46" stroke="var(--acc-artifact)" strokeWidth="1" />
              <polygon points="-3,-3.5 4,0 -3,3.5" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)" transform={`translate(${95 + i * 88} 46)`} />
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
              fill={i === 4 ? "var(--acc-artifact)" : "var(--acc-artifact)"}
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
      <text x="260" y="116" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill="color-mix(in_srgb,var(--acc-artifact)_75%,transparent)">
        {t(locale, "후보는 단계마다 떨어지고, top-5 생존자만 시드 풀에 남습니다", "candidates drop at every stage; only the top-5 survivors reach the seed pool")}
      </text>
      <text x="260" y="134" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill="var(--acc-artifact)">
        Elo + difficulty blend · co-evolving pool
      </text>
    </svg>
  );
}


/** Scroll-driven stage lighting: an act brightens as it takes center stage
    and falls back into the dark as it leaves (opacity-only, RM-safe). */
function StageLight({ children, className }: { children: React.ReactNode; className?: string }) {
  const lightRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: lightRef, offset: ["start end", "end start"] });
  const shade = useTransform(scrollYProgress, [0, 0.28, 0.72, 1], [0.78, 0, 0, 0.78]);
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
            <p className="mx-auto mt-3 inline-block rounded bg-[var(--acc-artifact)] px-4 py-2 font-mono text-[13px] text-[var(--acc-artifact)]">
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

/* ---------------- the distillation: tokens filtered to one drop ---------- */

const RAIN_COLS = [7, 16, 24, 33, 41, 52, 60, 69, 77, 86, 93] as const;

function RainBand({ keep, phase }: { keep: number; phase: number }) {
  // keep: fraction of columns that survive into this band (deterministic).
  const cols = RAIN_COLS.filter((_, i) => (i * 7 + phase * 3) % 10 < keep * 10);
  return (
    <div aria-hidden className="relative h-[52vh] w-full overflow-hidden">
      {cols.map((left, i) => (
        <div
          key={left}
          className="geodi-rain absolute top-[-8%] flex h-[116%] flex-col justify-between"
          style={{ left: `${left}%`, animationDelay: `${(i * 0.37 + phase * 0.19) % 2.4}s` }}
        >
          {Array.from({ length: 7 }).map((_, k) => (
            <span key={k} className="h-[6px] w-[6px] bg-[#FFF0F8]" style={{ opacity: k % 3 === phase % 3 ? 1 : 0.55 }} />
          ))}
        </div>
      ))}
    </div>
  );
}

function FilterRule({ label }: { label: string }) {
  return (
    <div className="relative flex w-full items-center" aria-hidden>
      <div className="h-[2px] flex-1 bg-[repeating-linear-gradient(90deg,#FFF0F8_0,#FFF0F8_14px,transparent_14px,transparent_26px)]" />
      <span className="ml-4 font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_75%,transparent)]">
        {label}
      </span>
    </div>
  );
}

/** Tokens pour like water over the baseline ledger; three filters thin the
    rain until a single drop of improvement is left — still forming, as the
    record honestly stands. Scroll descends the funnel. */
function DistillationAct() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: wrapRef, offset: ["start start", "end end"] });
  const descend = useTransform(scrollYProgress, [0, 1], ["0vh", "-158vh"]);
  const ledger: { id: string; verdict: string; keep?: boolean }[] = [
    { id: "gen-2606-i1-004", verdict: "REJECT · margin < floor" },
    { id: "gen-2606-i2-001", verdict: "REJECT · critical regress" },
    { id: "crucible-S1", verdict: "REJECT · full paired run" },
    { id: "crucible-S5", verdict: "EVOLVE-BLOCK · pending", keep: true },
  ];
  return (
    <section ref={wrapRef} className="relative h-[280vh] bg-[var(--acc-artifact)]">
      <div className="sticky top-0 h-screen overflow-hidden">
        <div className="pointer-events-none absolute left-5 top-8 z-20 max-w-[320px] text-left sm:left-10 sm:top-12">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_70%,transparent)]">
            {t(locale, "증류", "the distillation")}
          </p>
          <h2 className="font-serif-display mt-3 text-balance text-[clamp(1.5rem,3vw,2.2rem)] font-black leading-[1.25] text-[#FFF0F8]">
            {t(
              locale,
              "천 번의 토큰이 한 방울이 될 때까지.",
              "A thousand tokens, filtered to a single drop."
            )}
          </h2>
        </div>

        <motion.div style={{ y: reduceMotion ? "-158vh" : descend }} className="relative">
          <RainBand keep={1} phase={0} />
          <div className="mx-auto max-w-5xl px-6"><FilterRule label="critic" /></div>
          <RainBand keep={0.55} phase={1} />
          <div className="mx-auto max-w-5xl px-6"><FilterRule label="petri gate" /></div>
          <RainBand keep={0.25} phase={2} />
          <div className="mx-auto max-w-5xl px-6"><FilterRule label="held-out" /></div>

          {/* the last chamber: one drop, still forming, above the ledger */}
          <div className="flex h-[100vh] flex-col items-center justify-center gap-10 px-6">
            <div className="flex flex-col items-center gap-2" aria-hidden>
              <span className="geodi-drop h-[7px] w-[7px] bg-[#FFF0F8]" />
              <span className="h-[10px] w-[2px] bg-[color-mix(in_srgb,#FFF0F8_45%,transparent)]" />
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

/* ---------------- giant wordmark band ------------------------------------ */

function WordmarkBand() {
  return (
    <div aria-hidden className="select-none overflow-hidden bg-[var(--acc-artifact)]">
      <p className="font-pixel -mb-[0.16em] -mt-[0.02em] whitespace-nowrap text-center text-[24.5vw] font-bold leading-[0.9] text-[#FFF0F8]">
        GEODE
      </p>
    </div>
  );
}

/* ---------------- finale: the specimen ----------------------------------- */

function LabFinale() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const finaleRef = useRef<HTMLElement | null>(null);
  const { scrollYProgress } = useScroll({ target: finaleRef, offset: ["start end", "end start"] });
  const ghostScale = useTransform(scrollYProgress, [0, 1], [1.16, 0.94]);
  return (
    <section id="lab" ref={finaleRef} className="relative overflow-hidden bg-[var(--acc-artifact)]">
      <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <motion.span
          style={{ scale: reduceMotion ? 1 : ghostScale }}
          className="font-pixel select-none text-[24vw] font-bold leading-none text-[#FFF0F8] opacity-[0.06]"
        >
          GEODE
        </motion.span>
      </div>
      <div className="relative z-10 mx-auto flex max-w-5xl flex-col items-center gap-7 px-6 py-24 text-center sm:py-32">
        <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_70%,transparent)]">
          cultured since {firstRelease.date} · release #{releaseCount} · v{latestRelease.version}
        </p>
        <h2 className="font-serif-display text-balance text-[clamp(2.4rem,6vw,4.2rem)] font-black leading-[1.1] text-[#FFF0F8]">
          {t(locale, "루프 실험실", "The Loop Laboratory")}
        </h2>
        <motion.div
          className="flex h-44 w-44 items-center justify-center rounded-full border-2 border-[var(--paper)] sm:h-52 sm:w-52"
          initial={{ opacity: 0, scale: reduceMotion ? 1 : 0.82 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ type: "spring", stiffness: 120, damping: 16 }}
        >
          <GeodiSprite scale={5} silhouette="var(--paper)" />
        </motion.div>
        <p className="font-serif-display max-w-xl text-[clamp(1.05rem,2.4vw,1.4rem)] font-semibold leading-[1.6] text-[#FFF0F8]">
          {t(locale, "실패를 기록하고, 스스로를 고쳐 씁니다.", "It records its failures, and rewrites itself.")}
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <Link
            href="/docs"
            className="inline-flex touch-manipulation items-center rounded bg-[#FFF0F8] px-5 py-2.5 text-[14px] font-medium text-[var(--acc-artifact)] transition-opacity hover:opacity-85"
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
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-[color-mix(in_srgb,#FFF0F8_60%,transparent)] sm:px-8">
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
          <WordmarkBand />
          <StageLight>
            <LabFinale />
          </StageLight>
        </div>
      </main>
    </LocaleProvider>
  );
}
