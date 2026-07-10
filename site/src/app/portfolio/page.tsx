"use client";

import "@astryxdesign/theme-neutral/theme.css";
import "@astryxdesign/core/astryx.css";
import "./astryx-geode.css";

import { Token } from "@astryxdesign/core/Token";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
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
 * GEODE portfolio v20 — the loop laboratory, monochrome-plus-one.
 *
 * Formula (operator-directed, LazyWeb x Hermes synthesis): near-monochrome
 * substrate (warm white paper, near-black record ink), one accent (signature
 * rose), sharp-cornered technical line-art plates, a real terminal hero, and
 * two color acts — the full-rose distillation and the black-stage laboratory
 * finale (operator-approved mock). Exactly three colors: #FFF0F8, #141016,
 * #F49BC4; the terminal mock keeps its dark product colors by exception.
 */

const PAPER = "#FFF0F8";
const INK = "#141016";
const INK_60 = "color-mix(in srgb, #141016 60%, transparent)";
const INK_45 = "color-mix(in srgb, #141016 45%, transparent)";

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
      <div className="overflow-hidden rounded-lg border border-[color-mix(in_srgb,#141016_25%,transparent)] bg-[var(--paper-deep)] text-left shadow-[0_18px_50px_-18px_rgba(20,16,22,0.35)]">
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
      <figcaption className="mt-3 text-center font-mono text-[10.5px]" style={{ color: INK_45 }}>
        core/ui/mascot.py · geodi_art.py · {t(locale, "CLI 웰컴 스크린을 그대로 옮긴 화면", "the CLI welcome screen, transcribed")}
      </figcaption>
    </figure>
  );
}

/* ---------------- hero: statement + terminal ------------------------------ */

function HeroField() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const heroItem = {
    hidden: { opacity: 0, y: reduceMotion ? 0 : 22 },
    show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] as const } },
  };
  return (
    <section id="hero" className="rose-grid relative">
      <motion.div
        className="mx-auto flex max-w-5xl flex-col items-center px-5 pb-16 pt-16 text-center sm:px-8 sm:pt-20"
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.1, delayChildren: 0.05 } } }}
      >
        <motion.div variants={heroItem}>
          <PlayfulSprite scale={4} blink />
        </motion.div>
        <motion.p
          variants={heroItem}
          className="mt-6 font-mono text-[10.5px] uppercase tracking-[0.3em]"
          style={{ color: INK_60 }}
        >
          open source · apache-2.0 · {t(locale, "루프 실험실", "the loop laboratory")}
        </motion.p>
        <motion.h1
          variants={heroItem}
          className="font-serif-display mt-6 text-balance text-[clamp(2.4rem,5.4vw,4.1rem)] font-black leading-[1.14]"
          style={{ color: INK }}
        >
          {t(locale, "일을 맡기면 끝까지 실행하고,", "The agent that executes to the end,")}
          <br />
          {t(locale, "스스로를 고쳐 씁니다.", "and rewrites itself.")}
        </motion.h1>
        <motion.div variants={heroItem} className="mt-8 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <Link
            href="/docs"
            className="inline-flex touch-manipulation items-center rounded bg-[#141016] px-5 py-2.5 text-[14px] font-medium text-[#FFF0F8] transition-opacity hover:opacity-85"
          >
            {t(locale, "문서 읽기", "Read the docs")}
          </Link>
          <Link
            href="https://github.com/mangowhoiscloud/geode"
            target="_blank"
            className="font-mono text-[13px] underline underline-offset-4 transition-opacity hover:opacity-70"
            style={{ color: INK, textDecorationColor: "var(--acc-artifact)" }}
          >
            GitHub
          </Link>
        </motion.div>
        <motion.div variants={heroItem} className="mt-14 w-full">
          <TerminalMock />
        </motion.div>
      </motion.div>
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between px-5 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] sm:px-8"
        style={{ color: INK_45 }}
      >
        <span>geode v{GEODE_SOT.version}</span>
        <span>apache-2.0 · 2026</span>
      </div>
    </section>
  );
}

/* ---------------- diagrams: rose line-art on paper ------------------------ */

const LOOP_NODES = [
  { label: "Perceive" },
  { label: "Plan" },
  { label: "Act" },
  { label: "Observe" },
  { label: "Verify" },
  { label: "Replan" },
];

/** The while(tool_use) cycle as a rose-ink ring on the paper plate. */
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
      <rect x={cx - 38} y={264} width={76} height={22} fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
      <text x={cx} y={279} textAnchor="middle" fontSize="10.5" fontFamily="var(--font-fira-code), monospace" fill={INK}>finalize</text>
      <text x={cx + 8} y={cy + 66} textAnchor="start" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill={INK_60}>no tool_use</text>
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize="15" className="font-pixel" fill={INK}>while</text>
      <text x={cx} y={cy + 14} textAnchor="middle" fontSize="15" className="font-pixel" fill={INK}>(tool_use)</text>
      {points.map((node) => (
        <g key={node.label}>
          <rect x={node.x - nodeW / 2} y={node.y - nodeH / 2} width={nodeW} height={nodeH}
            fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
          <text x={node.x} y={node.y + 3.5} textAnchor="middle" fontSize="10.5"
            fontFamily="var(--font-fira-code), monospace" fill={INK}>{node.label}</text>
        </g>
      ))}
    </svg>
  );
}

/** Adversarial audit as a promotion gate — blueprint schematic. */
function AuditGateDiagram() {
  const locale = useLocale();
  const dims = [26, 34, 20, 38, 30, 42];
  return (
    <svg viewBox="0 0 520 170" className="w-full max-w-[520px]" role="img"
      aria-label={t(locale, "감사 게이트 도식", "audit gate schematic")}>
      <rect x="8" y="72" width="92" height="26" fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
      <text x="54" y="88" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill={INK}>
        {t(locale, "scaffold 변이", "mutation")}
      </text>
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(116 85)" />
      <line x1="100" y1="85" x2="128" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />
      <rect x="132" y="28" width="150" height="116" fill="none" stroke="var(--acc-artifact)" strokeDasharray="3 3" shapeRendering="crispEdges" />
      <text x="207" y="20" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill={INK_60}>adversarial audit</text>
      <rect x="147" y="40" width="120" height="22" fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
      <text x="207" y="54" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill={INK}>Petri auditor</text>
      <rect x="147" y="108" width="120" height="22" fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
      <text x="207" y="122" textAnchor="middle" fontSize="10" fontFamily="var(--font-fira-code), monospace" fill={INK}>GEODE</text>
      {[171, 207, 243].map((x) => (
        <line key={x} x1={x} y1="64" x2={x} y2="106" stroke="var(--acc-artifact)" strokeWidth="1" strokeDasharray="2 2" />
      ))}
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(302 85)" />
      <line x1="282" y1="85" x2="314" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />
      {dims.map((h, i) => (
        <rect key={i} x={320 + i * 13} y={104 - h} width={9} height={h}
          fill="var(--acc-artifact)" opacity={i === 3 ? 1 : 0.55} shapeRendering="crispEdges" />
      ))}
      <line x1="316" y1="76" x2="402" y2="76" stroke={INK} strokeWidth="1" strokeDasharray="4 2" />
      <text x="359" y="120" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill={INK_60}>critical floor</text>
      <line x1="406" y1="85" x2="430" y2="85" stroke="var(--acc-artifact)" strokeWidth="1" />
      <line x1="430" y1="85" x2="446" y2="52" stroke="var(--acc-artifact)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(448 49) rotate(-64)" />
      <rect x="446" y="30" width="66" height="20" fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
      <text x="479" y="43" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill={INK}>promote</text>
      <line x1="430" y1="85" x2="446" y2="118" stroke="var(--acc-artifact)" strokeWidth="1" />
      <polygon points="-3,-3.5 4,0 -3,3.5" fill="var(--acc-artifact)" transform="translate(448 121) rotate(64)" />
      <rect x="446" y="120" width="66" height="20" fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
      <text x="479" y="133" textAnchor="middle" fontSize="9.5" fontFamily="var(--font-fira-code), monospace" fill={INK}>reject</text>
      <text x="470" y="90" textAnchor="middle" fontSize="8" fontFamily="var(--font-fira-code), monospace" fill={INK_60}>gate·random·never</text>
    </svg>
  );
}

/** Seed hypothesis factory — blueprint pipeline. */
function SeedgenDiagram() {
  const locale = useLocale();
  const stages = ["generator", "critic", "pilot", "ranker", "evolver"];
  const seedCols = [4, 3, 2, 2, 5];
  return (
    <svg viewBox="0 0 520 150" className="w-full max-w-[520px]" role="img"
      aria-label={t(locale, "시드 생성 파이프라인 도식", "seed-generation pipeline schematic")}>
      {stages.map((stage, i) => (
        <g key={stage}>
          <rect x={8 + i * 88} y="34" width="76" height="24" fill={PAPER} stroke={INK} shapeRendering="crispEdges" />
          <text x={46 + i * 88} y="49" textAnchor="middle" fontSize="10"
            fontFamily="var(--font-fira-code), monospace" fill={INK}>{stage}</text>
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
      <text x="260" y="116" textAnchor="middle" fontSize="9" fontFamily="var(--font-fira-code), monospace" fill={INK_60}>
        {t(locale, "후보는 단계마다 떨어지고, top-5 생존자만 시드 풀에 남습니다", "candidates drop at every stage; only the top-5 survivors reach the seed pool")}
      </text>
      <text x="260" y="134" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-fira-code), monospace" fill={INK_60}>
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
    <section id="run" className="border-t" style={{ borderColor: "color-mix(in srgb, #141016 12%, transparent)" }}>
      <div className="mx-auto max-w-6xl px-6 py-16 sm:py-20">
        <p className="text-center font-mono text-[10.5px] uppercase tracking-[0.3em]" style={{ color: INK_60 }}>
          {t(locale, "세 가지 입구", "three ways in")}
        </p>
        <div className="mt-10 grid gap-px overflow-hidden border md:grid-cols-3"
          style={{ borderColor: "color-mix(in srgb, #141016 18%, transparent)", background: "color-mix(in srgb, #141016 18%, transparent)" }}>
          {runModes.map((mode) => (
            <div key={mode.cmd} className="bg-[#FFF0F8] px-7 py-9 text-center">
              <p className="font-mono text-[10.5px] uppercase tracking-[0.28em]" style={{ color: INK_45 }}>{mode.eyebrow}</p>
              <h2 className="font-serif-display mt-3 text-[28px] font-semibold" style={{ color: INK }}>
                {locale === "en" ? mode.titleEn : mode.titleKo}
              </h2>
              <p className="mx-auto mt-4 inline-block rounded bg-[#141016] px-4 py-2 font-mono text-[13px] text-[#FFF0F8]">
                {mode.cmd}
              </p>
              <p className="mx-auto mt-4 max-w-[260px] text-[13px] leading-[1.7]" style={{ color: INK_60 }}>
                {t(locale, mode.ko, mode.en)}
              </p>
            </div>
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
      <p><span style={{ color: INK }}>context</span><span style={{ color: INK_60 }}> · per-turn time, memory, rules</span></p>
      <p><span style={{ color: INK }}>documents</span><span style={{ color: INK_60 }}> · local pdf ingest</span></p>
      <p><span style={{ color: INK }}>browser</span><span style={{ color: INK_60 }}> · your real chrome, over cdp</span></p>
      <p><span style={{ color: INK }}>desktop</span><span style={{ color: INK_60 }}> · ax tree before pixels</span></p>
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
            <p className="font-serif-display text-[26px] font-black" style={{ color: INK }}>{cell.value}</p>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.2em]" style={{ color: INK_60 }}>{cell.label}</p>
          </div>
        ))}
      </div>
      <p className="text-center font-mono text-[10px] uppercase tracking-[0.14em]" style={{ color: INK_60 }}>
        tau2-bench base · gpt-5.5 · openai-codex subscription
      </p>
    </div>
  );
}

function ResideBanner() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 px-6">
      <div className="font-mono text-[12px] leading-relaxed">
        <p style={{ color: INK }}>anthropic · openai / codex · glm</p>
        <p className="text-center" style={{ color: INK_60 }}>oauth you own · provider-isolated</p>
      </div>
      <div className="flex flex-wrap justify-center gap-1.5">
        {surfaceChips.map((chip) => (
          <Token key={chip} label={chip} size="sm" color="gray" />
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
    <section id="features" className="rose-grid border-t" style={{ borderColor: "color-mix(in srgb, #141016 12%, transparent)" }}>
      <div className="mx-auto max-w-7xl px-6 py-16 sm:py-24">
        <p className="text-center font-mono text-[10.5px] uppercase tracking-[0.3em]" style={{ color: INK_60 }}>
          {t(locale, "도판 i-vi", "plates i-vi")}
        </p>
        <div className="mt-12 grid gap-x-8 gap-y-14 md:grid-cols-2 xl:grid-cols-3">
          {features.map((feature) => (
            <div key={feature.id}>
              <p className="font-mono text-[11px] uppercase tracking-[0.26em]" style={{ color: INK_45 }}>
                {feature.index}
              </p>
              <h2
                className="font-serif-display mt-3 text-balance text-[28px] font-black uppercase leading-[1.08] sm:text-[32px]"
                style={{ color: INK }}
              >
                {locale === "en" ? feature.headEn : feature.headKo}
              </h2>
              <div
                className="mt-5 flex h-[240px] items-center justify-center overflow-hidden border bg-[#FFF0F8] px-4 py-3"
                style={{ borderColor: "color-mix(in srgb, #141016 18%, transparent)" }}
              >
                {feature.banner}
              </div>
              <p className="mt-4 max-w-[380px] text-[13px] leading-[1.75]" style={{ color: INK_60 }}>
                {t(locale, feature.ko, feature.en)}
              </p>
            </div>
          ))}
        </div>
        <div
          className="mt-16 flex items-end justify-between font-mono text-[10px] uppercase tracking-[0.18em]"
          style={{ color: INK_45 }}
        >
          <span>the loop laboratory · plates i-vi</span>
          <span>evidence: core/ · plugins/</span>
        </div>
      </div>
    </section>
  );
}

/* ---------------- the distillation: one composed rose screen ------------- */

const RAIN_COLS = [7, 16, 24, 33, 41, 52, 60, 69, 77, 86, 93] as const;

function RainBand({
  keep,
  phase,
  height,
  converge = 0,
  dots = 8,
}: {
  keep: number;
  phase: number;
  height: string;
  converge?: number;
  dots?: number;
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
          {Array.from({ length: dots }).map((_, k) => (
            <span key={k} className="h-[6px] w-[6px] bg-[#FFF0F8]" style={{ opacity: k % 3 === phase % 3 ? 1 : 0.55 }} />
          ))}
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
 * The whole funnel lives on one composed screen: headline, three converging
 * rain bands through named filters, the word filling top-down, the ledger.
 * Scroll progress drives only the fill and the ledger reveal — no translate,
 * so no dead frames at any scroll position.
 */
function DistillationAct() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: wrapRef, offset: ["start start", "end end"] });
  const fill = useTransform(scrollYProgress, [0.25, 0.75], ["inset(0 0 100% 0)", "inset(0 0 0% 0)"]);
  const ledgerOp = useTransform(scrollYProgress, [0.6, 0.85], [0, 1]);
  const ledger: { id: string; verdict: string; keep?: boolean }[] = [
    { id: "gen-2606-i1-004", verdict: "REJECT" },
    { id: "gen-2606-i2-001", verdict: "REJECT" },
    { id: "crucible-S1", verdict: "REJECT" },
    { id: "crucible-S5", verdict: "PENDING", keep: true },
  ];
  return (
    <section id="distill" ref={wrapRef} className="relative h-[220vh] bg-[var(--acc-artifact)]">
      <div className="sticky top-0 flex h-screen flex-col overflow-hidden">
        <div className="px-6 pt-10 text-center sm:pt-12">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,#FFF0F8_75%,transparent)]">
            {t(locale, "증류", "the distillation")}
          </p>
          <h2 className="font-serif-display mx-auto mt-3 max-w-2xl text-balance text-[clamp(1.5rem,3vw,2.1rem)] font-black leading-[1.25] text-[#FFF0F8]">
            {t(locale, "천 번의 토큰이 한 단어가 될 때까지.", "A thousand tokens, distilled into one word.")}
          </h2>
        </div>

        <div className="flex min-h-0 flex-1 flex-col justify-center">
          <RainBand keep={1} phase={0} height="12vh" dots={5} />
          <FilterLine label="critic" />
          <RainBand keep={0.55} phase={1} height="9vh" converge={0.42} dots={4} />
          <FilterLine label="petri gate" />
          <RainBand keep={0.25} phase={2} height="7vh" converge={0.78} dots={3} />
          <FilterLine label="held-out" />
          <RainBand keep={0.18} phase={1} height="5vh" converge={0.92} dots={3} />
        </div>

        <div className="flex flex-col items-center pb-8">
          {/* the word takes the whole width — the distillate is the wordmark */}
          <div className="relative w-full text-center">
            <p className="font-pixel whitespace-nowrap text-[24vw] font-bold leading-[0.82] text-[#FFF0F8] opacity-25">
              GEODE
            </p>
            <motion.p
              aria-hidden
              style={{ clipPath: reduceMotion ? "inset(0 0 0 0)" : fill }}
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
              <span className="uppercase tracking-[0.24em] text-[color-mix(in_srgb,#FFF0F8_75%,transparent)]">
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
      </div>
    </section>
  );
}

/* ---------------- wordmark -> laboratory crossfade ------------------------ */

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

/* ---------------- page ----------------------------------------------------- */

export default function GeodePortfolioPage() {
  return (
    <LocaleProvider defaultLocale="en">
      <main
        data-astryx-theme="neutral"
        className={`${galmuri.variable} ${serifDisplay.variable} min-h-screen overflow-x-clip bg-[#FFF0F8] text-[#141016]`}
      >
        <GeodeNav items={navItems} light />
        <HeroField />
        <RunRow />
        <FeaturesGrid />
        <DistillationAct />
        <WordToLab />
      </main>
    </LocaleProvider>
  );
}
