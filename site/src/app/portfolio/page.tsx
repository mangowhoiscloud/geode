"use client";

import "@astryxdesign/theme-neutral/theme.css";
import "@astryxdesign/core/astryx.css";
import "./astryx-geode.css";

import {
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
} from "framer-motion";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { GeodiSprite } from "@/components/geode/geodi-sprite";
import {
  LocaleProvider,
  t,
  useLocale,
} from "@/components/geode/locale-context";
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
 * terminal mock uses one brand-derived plum inset by standing exception.
 * White appears as ink, as paper plates carrying rose line-art
 * schematics, and as the stage of the final specimen reveal. Scroll is
 * choreography: distillation rain converges through named thresholds, fills
 * the full-bleed wordmark, and further scroll reveals the laboratory.
 */

const PAPER = "#FFF0F8";
// Deep-rose ink: same hue as the signature, darkened for legibility on the
// white plates (~4.5:1 vs #FFF0F8; the signature itself is ~1.8:1 as ink).
const ROSE_INK = "#C2447F";
const ROSE_INK_70 = "color-mix(in srgb, #C2447F 72%, transparent)";
const FIELD_META_STYLE = {
  color: PAPER,
  textShadow:
    "0 1px 0 rgba(127, 23, 71, 0.72), 0 3px 10px rgba(127, 23, 71, 0.2)",
} as const;

const navItems = [
  { id: "hero", label: "Intro" },
  { id: "install", label: "Install" },
  { id: "run", label: "Run" },
  { id: "features", label: "Features" },
  { id: "distill", label: "Distill" },
  { id: "lab", label: "Specimen" },
];

/* ---------------- install: every channel, typed live ---------------------- */

/**
 * Every distribution channel as a replayed terminal: the command types in
 * character by character (operator direction 2026-07-13), then output
 * reveals line by line exactly like the hero terminal. Transcripts are
 * abridged from the real 2026-07-13 publication runs (PyPI uv tool install,
 * uvx ephemeral env); reduced motion renders the finished
 * transcript statically.
 */
type InstallLine = {
  kind: "cmd" | "out" | "ok" | "welcome" | "prompt";
  text: string;
};

const FIRST_PROMPT_LINES: InstallLine[] = [
  { kind: "welcome", text: "" },
  { kind: "prompt", text: "Hello World" },
];

const supportedProviders = [
  "Anthropic",
  "OpenAI / Codex",
  "ZhipuAI GLM",
] as const;

const installChannels: {
  id: string;
  labelKo: string;
  labelEn: string;
  noteKo: string;
  noteEn: string;
  copy: string;
  lines: InstallLine[];
}[] = [
  {
    id: "uv-tool",
    labelKo: "uv tool",
    labelEn: "uv tool",
    noteKo:
      "파이썬 툴체인 사용자용. 최신 안정 버전을 격리된 도구 환경에 설치합니다.",
    noteEn: "Latest stable release in an isolated tool environment.",
    copy: "uv tool install geode-agent",
    lines: [
      { kind: "cmd", text: "uv tool install geode-agent" },
      { kind: "out", text: "Installed 2 executables: geode, geode-mcp" },
      { kind: "cmd", text: "geode" },
      ...FIRST_PROMPT_LINES,
    ],
  },
  {
    id: "uvx",
    labelKo: "uvx · 설치 없이",
    labelEn: "uvx · no install",
    noteKo: "설치 없이 1회 실행. PATH에 명령을 남기지 않습니다.",
    noteEn: "One-shot run with no install and no PATH changes.",
    copy: "uvx --from geode-agent geode",
    lines: [
      { kind: "cmd", text: "uvx --from geode-agent geode" },
      { kind: "out", text: "Installed 64 packages in 434ms" },
      ...FIRST_PROMPT_LINES,
    ],
  },
  {
    id: "source",
    labelKo: "소스",
    labelEn: "Source",
    noteKo: "개발·기여용. uv run이 프로젝트 환경을 맞춘 뒤 바로 실행합니다.",
    noteEn: "Development checkout with its environment managed by uv.",
    copy: "git clone https://github.com/mangowhoiscloud/geode.git && cd geode && uv run geode",
    lines: [
      {
        kind: "cmd",
        text: "git clone https://github.com/mangowhoiscloud/geode.git && cd geode",
      },
      { kind: "out", text: "Cloning into 'geode'..." },
      { kind: "cmd", text: "uv run geode" },
      { kind: "out", text: "Installed 120 packages in 256ms" },
      ...FIRST_PROMPT_LINES,
    ],
  },
];

const TYPE_MS = 26;
const LINE_MS = 520;
const CMD_SETTLE_MS = 380;
const REPLAY_MS = 4800;
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeToReducedMotion(onChange: () => void) {
  const media = window.matchMedia(REDUCED_MOTION_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function getReducedMotionSnapshot() {
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

function useHydrationSafeReducedMotion() {
  // Hydration must begin from the same snapshot the server rendered. React
  // checks the real media query immediately after hydration without an effect.
  return useSyncExternalStore(
    subscribeToReducedMotion,
    getReducedMotionSnapshot,
    () => false,
  );
}

function InstallTerminal({ lines }: { lines: InstallLine[] }) {
  const reduceMotion = useHydrationSafeReducedMotion();
  const [lineIndex, setLineIndex] = useState(0);
  const [charCount, setCharCount] = useState(0);
  const progressRef = useRef({ line: 0, chars: 0 });
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (reduceMotion) return;
    // Resume from the exact visible frame after a live reduced-motion toggle.
    // Resetting local counters to zero while React retained the old frame made
    // the terminal briefly mismatch and then jump backwards.
    let { line, chars } = progressRef.current;
    let timer: number;
    const step = () => {
      if (line >= lines.length) {
        timer = window.setTimeout(() => {
          line = 0;
          chars = 0;
          progressRef.current = { line, chars };
          setLineIndex(0);
          setCharCount(0);
          timer = window.setTimeout(step, 600);
        }, REPLAY_MS);
        return;
      }
      const current = lines[line];
      if (
        (current.kind === "cmd" || current.kind === "prompt") &&
        chars < current.text.length
      ) {
        // The prompt line sits as a bare "> " beat first, then types in
        // (operator direction 2026-07-13: end on the arrow; if the viewer
        // is still watching, type a Hello World).
        const delay = current.kind === "prompt" && chars === 0 ? 1600 : TYPE_MS;
        chars += 1;
        progressRef.current = { line, chars };
        setCharCount(chars);
        timer = window.setTimeout(step, delay);
        return;
      }
      line += 1;
      chars = 0;
      progressRef.current = { line, chars };
      setLineIndex(line);
      setCharCount(0);
      // The welcome banner gets a longer beat, matching the former hero
      // terminal's pacing before the first prompt appears.
      timer = window.setTimeout(
        step,
        current.kind === "cmd"
          ? CMD_SETTLE_MS
          : current.kind === "welcome"
            ? 900
            : LINE_MS,
      );
    };
    timer = window.setTimeout(step, 500);
    return () => window.clearTimeout(timer);
  }, [lines, reduceMotion]);

  useEffect(() => {
    const body = bodyRef.current;
    if (body) body.scrollTop = body.scrollHeight;
  }, [lineIndex, charCount, reduceMotion]);

  const visibleLineIndex = reduceMotion ? lines.length : lineIndex;

  const renderLine = (line: InstallLine, i: number, partial: boolean) => {
    if (line.kind === "cmd") {
      const shown = partial ? line.text.slice(0, charCount) : line.text;
      return (
        <p key={i} className="py-[3px] font-mono text-[12px] sm:text-[13px]">
          <span className="text-[var(--acc-artifact)]">$</span>{" "}
          <span className="text-[var(--ink-1)]">{shown}</span>
          {partial ? (
            <span className="geodi-caret ml-[2px] inline-block h-[13px] w-[7px] translate-y-[2px] bg-[var(--acc-artifact)]" />
          ) : null}
        </p>
      );
    }
    if (line.kind === "ok") {
      return (
        <p key={i} className="py-[3px] font-mono text-[12px] sm:text-[13px]">
          <span className="text-[var(--acc-artifact)]">◆</span>{" "}
          <span className="font-semibold text-[var(--acc-artifact)]">
            GEODE
          </span>{" "}
          <span className="text-[var(--ink-2)]">v{GEODE_SOT.version}</span>
        </p>
      );
    }
    if (line.kind === "welcome") {
      return (
        <div key={i} className="flex items-center gap-6 py-3">
          <PlayfulSprite scale={5} blink className="geodi-bob shrink-0" />
          <div className="min-w-0 font-mono text-[12px] leading-[1.9] sm:text-[13px]">
            <p>
              <span className="text-[var(--acc-artifact)]">◆</span>{" "}
              <span className="font-semibold text-[var(--acc-artifact)]">
                GEODE
              </span>{" "}
              <span className="text-[var(--ink-2)]">v{GEODE_SOT.version}</span>
            </p>
            <p className="text-[var(--ink-3)]">
              anthropic / claude-fable-5 · ~/workspace
            </p>
            <p className="text-[var(--ink-3)]">
              /help for commands · type naturally
            </p>
          </div>
        </div>
      );
    }
    if (line.kind === "prompt") {
      const shown = partial ? line.text.slice(0, charCount) : line.text;
      return (
        <p
          key={i}
          className="border-t border-[var(--rule-soft)] pt-3 font-mono text-[12px] sm:text-[13px]"
        >
          <span className="text-[var(--acc-artifact)]">&gt;</span>{" "}
          <span className="text-[var(--ink-2)]">{shown}</span>
          <span className="geodi-caret ml-1 inline-block h-[13px] w-[7px] translate-y-[2px] bg-[var(--acc-artifact)]" />
        </p>
      );
    }
    return (
      <p
        key={i}
        className="py-[3px] font-mono text-[12px] text-[var(--ink-3)] sm:text-[13px]"
      >
        {line.text}
      </p>
    );
  };

  return (
    <div className="install-terminal overflow-hidden rounded-lg border border-[color-mix(in_srgb,#FFF0F8_35%,transparent)] bg-[var(--paper-deep)] text-left">
      <div className="flex items-center gap-2 border-b border-[var(--rule-soft)] px-4 py-2.5">
        <span className="flex gap-1.5">
          {["#FF5F57", "#FEBC2E", "#28C840"].map((light) => (
            <span
              key={light}
              className="h-[9px] w-[9px] rounded-full"
              style={{ background: light }}
            />
          ))}
        </span>
        <span className="ml-2 font-mono text-[11px] text-[var(--ink-3)]">
          install
        </span>
      </div>
      <div
        ref={bodyRef}
        className="h-[248px] overflow-hidden px-5 py-4 sm:px-7"
      >
        {lines
          .slice(0, visibleLineIndex)
          .map((line, i) => renderLine(line, i, false))}
        {!reduceMotion &&
        lineIndex < lines.length &&
        ((lines[lineIndex].kind === "cmd" && charCount > 0) ||
          lines[lineIndex].kind === "prompt")
          ? renderLine(lines[lineIndex], lineIndex, true)
          : null}
      </div>
    </div>
  );
}

function InstallChannels() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const [activeChannel, setActiveChannel] = useState("uv-tool");
  const [copied, setCopied] = useState(false);
  const channel =
    installChannels.find((c) => c.id === activeChannel) ?? installChannels[0];

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(channel.copy);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable: the command stays selectable below */
    }
  };

  return (
    <section id="install" className="bg-[var(--acc-artifact)]">
      <div className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-24">
        <motion.p
          initial={{ opacity: 0, y: reduceMotion ? 0 : 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="text-center font-mono text-[10.5px] uppercase tracking-[0.3em]"
          style={FIELD_META_STYLE}
        >
          {t(locale, "네 갈래 설치", "every way to install")}
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: reduceMotion ? 0 : 22 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.65, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
          className="mt-8"
        >
          <div className="flex flex-wrap justify-center gap-x-1 gap-y-2 border-b border-[color-mix(in_srgb,#FFF0F8_30%,transparent)]">
            {installChannels.map((entry) => (
              <button
                key={entry.id}
                onClick={() => {
                  setActiveChannel(entry.id);
                  setCopied(false);
                }}
                className="touch-manipulation px-4 py-2 font-mono text-[12.5px] transition-colors"
                style={{
                  color:
                    activeChannel === entry.id
                      ? PAPER
                      : "color-mix(in srgb, #FFF0F8 86%, transparent)",
                  borderBottom: `2px solid ${activeChannel === entry.id ? PAPER : "transparent"}`,
                  marginBottom: "-1px",
                }}
              >
                {locale === "en" ? entry.labelEn : entry.labelKo}
              </button>
            ))}
          </div>
          <div className="mt-6">
            <InstallTerminal key={channel.id} lines={channel.lines} />
          </div>
          <div className="mt-4 flex flex-nowrap items-center justify-between gap-x-4">
            <p
              className="min-w-0 flex-1 font-mono text-[12px]"
              style={{ color: PAPER }}
            >
              {t(locale, channel.noteKo, channel.noteEn)}
            </p>
            <button
              onClick={handleCopy}
              className="shrink-0 touch-manipulation rounded border border-[color-mix(in_srgb,#FFF0F8_55%,transparent)] px-3 py-1 font-mono text-[11px] text-[#FFF0F8] transition-colors hover:bg-[color-mix(in_srgb,#FFF0F8_12%,transparent)]"
            >
              {copied
                ? t(locale, "복사됨", "copied")
                : t(locale, "명령 복사", "copy command")}
            </button>
          </div>
          <p
            className="mt-2 select-all break-all font-mono text-[11.5px]"
            style={{ color: PAPER }}
          >
            {channel.copy}
          </p>
          <div className="mt-5 flex flex-col gap-2 border-t border-[color-mix(in_srgb,#FFF0F8_25%,transparent)] pt-3.5 sm:flex-row sm:items-center sm:justify-between">
            <p
              className="shrink-0 font-mono text-[9px] uppercase tracking-[0.22em]"
              style={{ color: PAPER }}
            >
              supported providers
            </p>
            <ul
              className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5"
              aria-label="Supported providers"
            >
              {supportedProviders.map((provider) => (
                <li key={provider} className="inline-flex items-center gap-1.5">
                  <span
                    aria-hidden="true"
                    className="h-[3px] w-[3px] rotate-45 bg-[#FFF0F8]"
                  />
                  <span
                    className="font-mono text-[10.5px]"
                    style={{ color: PAPER }}
                  >
                    {provider}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

/** Sprite with a discoverable click reaction: three quick pixel hops. */
function PlayfulSprite({
  scale,
  blink,
  className,
}: {
  scale?: number;
  blink?: boolean;
  className?: string;
}) {
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
      <GeodiSprite
        scale={scale}
        blink={blink}
        className={hopping ? "geodi-hop" : undefined}
      />
    </button>
  );
}

/* ---------------- hero: rose field, white statement ----------------------- */

function HeroField() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const heroItem = {
    hidden: { opacity: 0, y: reduceMotion ? 0 : 22 },
    show: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] as const },
    },
  };
  return (
    <section id="hero" className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-[44%] overflow-hidden lg:block">
        <Image
          src="/geode/images/geode-sky.png"
          alt=""
          aria-hidden
          fill
          priority
          sizes="44vw"
          className="select-none object-cover object-center opacity-90"
          style={{ imageRendering: "pixelated" }}
        />
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 z-[1] hidden bg-[#F49BC4] lg:block lg:w-[74%] xl:w-[62%]"
      />
      <motion.div
        className="relative z-10 mx-auto max-w-7xl px-5 pb-16 pt-14 sm:px-8 lg:pt-20"
        initial="hidden"
        animate="show"
        variants={{
          hidden: {},
          show: { transition: { staggerChildren: 0.1, delayChildren: 0.05 } },
        }}
      >
        <motion.p
          variants={heroItem}
          className="font-mono text-[10.5px] uppercase tracking-[0.3em]"
          style={FIELD_META_STYLE}
        >
          open source · apache-2.0 · {t(locale, "고정점", "the fixed point")}
        </motion.p>
        <motion.h1
          variants={heroItem}
          className="font-serif-display mt-7 max-w-[700px] text-balance text-[clamp(2.5rem,5.2vw,4.2rem)] font-black leading-[1.12] text-[#FFF0F8]"
          style={{
            textShadow:
              "0 3px 0 rgba(127, 23, 71, 0.32), 0 14px 32px rgba(127, 23, 71, 0.2)",
          }}
        >
          {t(locale, "일을 맡기면", "The agent that")}
          <br />
          {t(locale, "끝까지 실행하고,", "executes to the end,")}
          <br />
          {t(locale, "스스로를 고쳐 씁니다.", "and rewrites itself.")}
        </motion.h1>
        <motion.div
          variants={heroItem}
          className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-3"
        >
          <Link
            href="/docs"
            className="inline-flex touch-manipulation items-center rounded bg-[#FFF0F8] px-5 py-2.5 text-[14px] font-medium text-[#C2447F] transition-opacity hover:opacity-85"
          >
            {t(locale, "문서 읽기", "Read the docs")}
          </Link>
          <a
            href={locale === "en" ? "/geode/report-en.pdf" : "/geode/report.pdf"}
            aria-label={t(
              locale,
              "GEODE 90쪽 포트폴리오 PDF 열기",
              "Open the 90-page GEODE portfolio PDF",
            )}
            className="group inline-flex touch-manipulation items-center gap-2 rounded border border-[color-mix(in_srgb,#7F1747_42%,transparent)] px-3 py-2 font-mono text-[13px] text-[#7F1747] transition-colors hover:border-[#7F1747] hover:bg-[color-mix(in_srgb,#FFF0F8_18%,transparent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7F1747]"
          >
            <span
              aria-hidden="true"
              className="grid h-7 min-w-7 place-items-center border border-current px-1 text-[8px] font-bold leading-none tracking-[0.08em]"
            >
              PDF
            </span>
            <span>{t(locale, "90쪽 보고서", "90P report")}</span>
          </a>
          <Link
            href="https://github.com/mangowhoiscloud/geode"
            target="_blank"
            className="font-mono text-[13px] text-[#7F1747] underline decoration-[color-mix(in_srgb,#7F1747_45%,transparent)] underline-offset-4 transition-colors hover:text-[#5F1034]"
          >
            GitHub
          </Link>
          <Link
            href="https://github.com/mangowhoiscloud/geode/releases/latest"
            target="_blank"
            className="font-mono text-[13px] text-[#7F1747] underline decoration-[color-mix(in_srgb,#7F1747_45%,transparent)] underline-offset-4 transition-colors hover:text-[#5F1034]"
          >
            {t(
              locale,
              "v" + GEODE_SOT.version + " 릴리스",
              "v" + GEODE_SOT.version + " release",
            )}
          </Link>
        </motion.div>
      </motion.div>
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-10"
        style={FIELD_META_STYLE}
      >
        <div className="mx-auto flex max-w-7xl px-5 pb-4 sm:px-8">
          <div className="flex max-w-[700px] flex-wrap items-center gap-x-6 gap-y-1 font-mono text-[10px] font-semibold uppercase tracking-[0.18em] sm:text-[11px]">
            <span>geode v{GEODE_SOT.version}</span>
            <span>apache-2.0 · 2026</span>
          </div>
        </div>
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
    <svg
      viewBox="0 0 360 470"
      className="h-full w-auto max-w-full"
      role="img"
      aria-label={t(
        locale,
        "while tool_use 루프 다이어그램",
        "while tool_use loop diagram",
      )}
    >
      {/* depth: dotted echoes of the rail */}
      {[22, 44].map((inset) => (
        <rect
          key={inset}
          x={railL - inset}
          y={railT - inset}
          width={railR - railL + inset * 2}
          height={railB - railT + inset * 2}
          fill="none"
          stroke={ROSE_INK}
          strokeWidth="1"
          strokeDasharray="1.5 5"
          opacity="0.45"
          shapeRendering="crispEdges"
        />
      ))}
      {/* the rail */}
      <rect
        x={railL}
        y={railT}
        width={railR - railL}
        height={railB - railT}
        fill="none"
        stroke={ROSE_INK}
        strokeWidth="1.2"
        shapeRendering="crispEdges"
      />
      {arrows.map((a, i) => (
        <polygon
          key={i}
          points="-3.5,-4 4.5,0 -3.5,4"
          fill={ROSE_INK}
          transform={`translate(${a.x} ${a.y}) rotate(${a.deg})`}
        />
      ))}
      {/* center clause */}
      <text
        x={midX}
        y={206}
        textAnchor="middle"
        fontSize="20"
        className="font-pixel"
        fill={ROSE_INK}
      >
        while
      </text>
      <text
        x={midX}
        y={230}
        textAnchor="middle"
        fontSize="20"
        className="font-pixel"
        fill={ROSE_INK}
      >
        (tool_use)
      </text>
      {/* exit through the bottom rail gap */}
      <line
        x1={midX}
        y1={252}
        x2={midX}
        y2={424}
        stroke={ROSE_INK}
        strokeWidth="1.2"
        strokeDasharray="3 4"
      />
      <polygon
        points="-4,-3.5 0,4.5 4,-3.5"
        fill={ROSE_INK}
        transform={`translate(${midX} ${424})`}
      />
      <text
        x={midX + 10}
        y={404}
        textAnchor="start"
        fontSize="9.5"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK_70}
      >
        no tool_use
      </text>
      <rect
        x={midX - 48}
        y={428}
        width={96}
        height={28}
        fill={PAPER}
        stroke={ROSE_INK}
        shapeRendering="crispEdges"
      />
      <text
        x={midX}
        y={446}
        textAnchor="middle"
        fontSize="12"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK}
      >
        finalize
      </text>
      {/* stations */}
      {nodes.map((node) => (
        <g key={node.label}>
          <rect
            x={node.x - nodeW / 2}
            y={node.y - nodeH / 2}
            width={nodeW}
            height={nodeH}
            fill={PAPER}
            stroke={ROSE_INK}
            shapeRendering="crispEdges"
          />
          <text
            x={node.x}
            y={node.y + 4}
            textAnchor="middle"
            fontSize="12"
            fontFamily="var(--font-fira-code), monospace"
            fill={ROSE_INK}
          >
            {node.label}
          </text>
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
    <svg
      viewBox="0 0 520 170"
      className="w-full"
      role="img"
      aria-label={t(locale, "감사 게이트 도식", "audit gate schematic")}
    >
      <rect
        x="8"
        y="72"
        width="92"
        height="26"
        fill={PAPER}
        stroke={ROSE_INK}
        shapeRendering="crispEdges"
      />
      <text
        x="54"
        y="88"
        textAnchor="middle"
        fontSize="9.5"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK}
      >
        {t(locale, "scaffold 변이", "mutation")}
      </text>
      <polygon
        points="-3,-3.5 4,0 -3,3.5"
        fill={ROSE_INK}
        transform="translate(116 85)"
      />
      <line
        x1="100"
        y1="85"
        x2="128"
        y2="85"
        stroke={ROSE_INK}
        strokeWidth="1"
      />
      <rect
        x="132"
        y="28"
        width="150"
        height="116"
        fill="none"
        stroke={ROSE_INK}
        strokeDasharray="3 3"
        shapeRendering="crispEdges"
      />
      <text
        x="207"
        y="20"
        textAnchor="middle"
        fontSize="9"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK_70}
      >
        adversarial audit
      </text>
      <rect
        x="147"
        y="40"
        width="120"
        height="22"
        fill={PAPER}
        stroke={ROSE_INK}
        shapeRendering="crispEdges"
      />
      <text
        x="207"
        y="54"
        textAnchor="middle"
        fontSize="10"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK}
      >
        Petri auditor
      </text>
      <rect
        x="147"
        y="108"
        width="120"
        height="22"
        fill={PAPER}
        stroke={ROSE_INK}
        shapeRendering="crispEdges"
      />
      <text
        x="207"
        y="122"
        textAnchor="middle"
        fontSize="10"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK}
      >
        GEODE
      </text>
      {[171, 207, 243].map((x) => (
        <line
          key={x}
          x1={x}
          y1="64"
          x2={x}
          y2="106"
          stroke={ROSE_INK}
          strokeWidth="1"
          strokeDasharray="2 2"
        />
      ))}
      <polygon
        points="-3,-3.5 4,0 -3,3.5"
        fill={ROSE_INK}
        transform="translate(302 85)"
      />
      <line
        x1="282"
        y1="85"
        x2="314"
        y2="85"
        stroke={ROSE_INK}
        strokeWidth="1"
      />
      {dims.map((h, i) => (
        <rect
          key={i}
          x={320 + i * 13}
          y={104 - h}
          width={9}
          height={h}
          fill={ROSE_INK}
          opacity={i === 3 ? 1 : 0.55}
          shapeRendering="crispEdges"
        />
      ))}
      <line
        x1="316"
        y1="76"
        x2="402"
        y2="76"
        stroke={ROSE_INK}
        strokeWidth="1"
        strokeDasharray="4 2"
      />
      <text
        x="359"
        y="120"
        textAnchor="middle"
        fontSize="8.5"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK_70}
      >
        critical floor
      </text>
      <line
        x1="406"
        y1="85"
        x2="430"
        y2="85"
        stroke={ROSE_INK}
        strokeWidth="1"
      />
      <line
        x1="430"
        y1="85"
        x2="446"
        y2="52"
        stroke={ROSE_INK}
        strokeWidth="1"
      />
      <polygon
        points="-3,-3.5 4,0 -3,3.5"
        fill={ROSE_INK}
        transform="translate(448 49) rotate(-64)"
      />
      <rect
        x="446"
        y="30"
        width="66"
        height="20"
        fill={PAPER}
        stroke={ROSE_INK}
        shapeRendering="crispEdges"
      />
      <text
        x="479"
        y="43"
        textAnchor="middle"
        fontSize="9.5"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK}
      >
        promote
      </text>
      <line
        x1="430"
        y1="85"
        x2="446"
        y2="118"
        stroke={ROSE_INK}
        strokeWidth="1"
      />
      <polygon
        points="-3,-3.5 4,0 -3,3.5"
        fill={ROSE_INK}
        transform="translate(448 121) rotate(64)"
      />
      <rect
        x="446"
        y="120"
        width="66"
        height="20"
        fill={PAPER}
        stroke={ROSE_INK}
        shapeRendering="crispEdges"
      />
      <text
        x="479"
        y="133"
        textAnchor="middle"
        fontSize="9.5"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK}
      >
        reject
      </text>
      <text
        x="470"
        y="90"
        textAnchor="middle"
        fontSize="8"
        fontFamily="var(--font-fira-code), monospace"
        fill={ROSE_INK_70}
      >
        gate·random·never
      </text>
    </svg>
  );
}

/** Seed hypothesis factory — rose blueprint pipeline. */
function SeedgenDiagram() {
  const locale = useLocale();
  return (
    <svg
      viewBox="0 0 520 388"
      className="block h-auto w-full min-w-0 max-w-full"
      role="img"
      aria-label={t(
        locale,
        "시드 생성과 Crucible 제한형 탐색 루프 도식",
        "seed-generation and Crucible bounded-search schematic",
      )}
    >
      <g fontFamily="var(--font-fira-code), monospace">
        <text x="8" y="16" fill={ROSE_INK} fontSize="12" fontWeight="700">
          SEED SEARCH
        </text>
        <text x="512" y="16" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          generate · test · retain
        </text>
        <line x1="8" y1="28" x2="512" y2="28" stroke={ROSE_INK_70} />

        <path
          d="M476 100 V136 H208 V100"
          fill="none"
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />
        <polygon
          points="-4,3 0,-4 4,3"
          fill={ROSE_INK_70}
          transform="translate(208 100)"
        />
        <line x1="88" y1="80" x2="104" y2="80" stroke={ROSE_INK} />
        <polygon
          points="-3,-3.5 4,0 -3,3.5"
          fill={ROSE_INK}
          transform="translate(104 80)"
        />
        <line x1="152" y1="80" x2="168" y2="80" stroke={ROSE_INK} />
        <polygon
          points="-3,-3.5 4,0 -3,3.5"
          fill={ROSE_INK}
          transform="translate(168 80)"
        />
        <line x1="248" y1="80" x2="272" y2="80" stroke={ROSE_INK} />
        <polygon
          points="-3,-3.5 4,0 -3,3.5"
          fill={ROSE_INK}
          transform="translate(272 80)"
        />
        <line x1="320" y1="80" x2="336" y2="80" stroke={ROSE_INK} />
        <polygon
          points="-3,-3.5 4,0 -3,3.5"
          fill={ROSE_INK}
          transform="translate(336 80)"
        />
        <line x1="408" y1="80" x2="440" y2="80" stroke={ROSE_INK} />
        <polygon
          points="-3,-3.5 4,0 -3,3.5"
          fill={ROSE_INK}
          transform="translate(440 80)"
        />

        <rect
          x="8"
          y="60"
          width="80"
          height="40"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <text
          x="48"
          y="84"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="10"
          fontWeight="700"
        >
          generate
        </text>
        <polygon
          points="128,56 152,80 128,104 104,80"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <text x="128" y="84" textAnchor="middle" fill={ROSE_INK} fontSize="9">
          critic
        </text>
        <rect
          x="168"
          y="60"
          width="80"
          height="40"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <text
          x="208"
          y="84"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="10"
          fontWeight="700"
        >
          pilot
        </text>
        <polygon
          points="296,56 320,80 296,104 272,80"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <text x="296" y="84" textAnchor="middle" fill={ROSE_INK} fontSize="9">
          rank
        </text>
        <rect
          x="336"
          y="60"
          width="72"
          height="40"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <text
          x="372"
          y="76"
          textAnchor="middle"
          fill={PAPER}
          fontSize="10"
          fontWeight="700"
        >
          top-5
        </text>
        <text x="372" y="92" textAnchor="middle" fill={PAPER} fontSize="8">
          retain
        </text>
        <rect
          x="440"
          y="60"
          width="72"
          height="40"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <text
          x="476"
          y="84"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="10"
          fontWeight="700"
        >
          evolve
        </text>

        <rect x="272" y="124" width="120" height="20" fill={PAPER} />
        <text
          x="332"
          y="138"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          rewrite → re-pilot
        </text>
        <line
          x1="8"
          y1="156"
          x2="512"
          y2="156"
          stroke={ROSE_INK_70}
          strokeDasharray="2 4"
        />
        <text
          x="260"
          y="172"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          {t(
            locale,
            "human gate가 승인한 top-N만 동결된 다음 세대로 들어갑니다",
            "Only human-approved top-N enters the next frozen generation",
          )}
        </text>

        <text x="8" y="204" fill={ROSE_INK} fontSize="12" fontWeight="700">
          CRUCIBLE
        </text>
        <text x="512" y="204" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          frozen contract · bounded search
        </text>
        <line x1="8" y1="216" x2="512" y2="216" stroke={ROSE_INK_70} />

        <line x1="80" y1="244" x2="96" y2="244" stroke={ROSE_INK} />
        <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(96 244)" />
        <line x1="176" y1="244" x2="192" y2="244" stroke={ROSE_INK} />
        <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(192 244)" />
        <line x1="288" y1="244" x2="292" y2="244" stroke={ROSE_INK} />
        <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(292 244)" />
        <line x1="340" y1="244" x2="352" y2="244" stroke={ROSE_INK} />
        <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(352 244)" />
        <line x1="408" y1="244" x2="440" y2="244" stroke={ROSE_INK} />
        <polygon points="-3,-3.5 4,0 -3,3.5" fill={ROSE_INK} transform="translate(440 244)" />
        <path d="M316 268 V280" fill="none" stroke={ROSE_INK} />
        <polygon
          points="-3,-3.5 4,0 -3,3.5"
          fill={ROSE_INK}
          transform="translate(316 280) rotate(90)"
        />
        <path d="M388 296 H424 V244" fill="none" stroke={ROSE_INK_70} />
        <circle cx="424" cy="244" r="3" fill={ROSE_INK} />
        <path d="M464 268 V296" fill="none" stroke={ROSE_INK} />
        <polygon
          points="-3,-3.5 4,0 -3,3.5"
          fill={ROSE_INK}
          transform="translate(464 296) rotate(90)"
        />
        <text x="476" y="284" fill={ROSE_INK} fontSize="7" fontWeight="700">
          YES
        </text>
        <path
          d="M488 244 H508 V344 H136 V264"
          fill="none"
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />
        <polygon
          points="-3,4 0,-4 3,4"
          fill={ROSE_INK_70}
          transform="translate(136 264)"
        />
        <rect x="232" y="332" width="136" height="16" fill={PAPER} />
        <text x="300" y="343" textAnchor="middle" fill={ROSE_INK_70} fontSize="7">
          NO · NEXT CANDIDATE
        </text>

        <rect x="8" y="224" width="72" height="40" fill={PAPER} stroke={ROSE_INK} />
        <text x="44" y="240" textAnchor="middle" fill={ROSE_INK} fontSize="9" fontWeight="700">
          prepare
        </text>
        <text x="44" y="254" textAnchor="middle" fill={ROSE_INK_70} fontSize="7">
          frozen config
        </text>
        <rect x="96" y="224" width="80" height="40" fill={PAPER} stroke={ROSE_INK} />
        <text x="136" y="240" textAnchor="middle" fill={ROSE_INK} fontSize="9" fontWeight="700">
          candidate
        </text>
        <text x="136" y="254" textAnchor="middle" fill={ROSE_INK_70} fontSize="7">
          private head
        </text>
        <rect x="192" y="224" width="96" height="40" fill={PAPER} stroke={ROSE_INK} />
        <text x="240" y="240" textAnchor="middle" fill={ROSE_INK} fontSize="9" fontWeight="700">
          paired assay
        </text>
        <text x="240" y="254" textAnchor="middle" fill={ROSE_INK_70} fontSize="7">
          base + candidate
        </text>
        <polygon points="316,220 340,244 316,268 292,244" fill={PAPER} stroke={ROSE_INK} />
        <text x="316" y="247" textAnchor="middle" fill={ROSE_INK} fontSize="8">
          decide
        </text>
        <rect x="352" y="224" width="56" height="40" fill={ROSE_INK} stroke={ROSE_INK} />
        <text x="380" y="240" textAnchor="middle" fill={PAPER} fontSize="9" fontWeight="700">
          KEEP
        </text>
        <text x="380" y="254" textAnchor="middle" fill={PAPER} fontSize="7">
          CAS +1
        </text>
        <rect x="276" y="280" width="112" height="32" fill={PAPER} stroke={ROSE_INK} />
        <text x="332" y="294" textAnchor="middle" fill={ROSE_INK} fontSize="8" fontWeight="700">
          REJECT / INVALID
        </text>
        <text x="332" y="306" textAnchor="middle" fill={ROSE_INK_70} fontSize="7">
          head unchanged
        </text>
        <polygon points="464,220 488,244 464,268 440,244" fill={PAPER} stroke={ROSE_INK} />
        <text x="464" y="240" textAnchor="middle" fill={ROSE_INK} fontSize="7">
          limits
        </text>
        <text x="464" y="250" textAnchor="middle" fill={ROSE_INK} fontSize="7">
          reached?
        </text>
        <rect x="412" y="296" width="104" height="32" fill={PAPER} stroke={ROSE_INK} />
        <text x="464" y="310" textAnchor="middle" fill={ROSE_INK} fontSize="8" fontWeight="700">
          summary.json
        </text>
        <text x="464" y="322" textAnchor="middle" fill={ROSE_INK_70} fontSize="7">
          run closed
        </text>

        <line x1="8" y1="360" x2="512" y2="360" stroke={ROSE_INK_70} strokeDasharray="2 4" />
        <text x="8" y="376" fill={ROSE_INK} fontSize="8" fontWeight="700">
          ELIGIBLE KEEP → SEALED TEST
        </text>
        <text x="512" y="376" textAnchor="end" fill={ROSE_INK_70} fontSize="7">
          release stays separate
        </text>
      </g>
    </svg>
  );
}

/* ---------------- runtime entry paths ------------------------------------ */

/** Three request paths, two hosts, and the AgenticLoop primitive they share. */
function RunRow() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  return (
    <section id="run" className="bg-[var(--acc-artifact)]">
      <div className="mx-auto w-full max-w-7xl px-6 py-20 sm:py-28">
        <motion.div
          initial={{ opacity: 0, y: reduceMotion ? 0 : 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="mx-auto max-w-3xl text-center"
        >
          <p
            className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.3em]"
            style={FIELD_META_STYLE}
          >
            {t(locale, "런타임 진입면", "runtime entry paths")}
          </p>
          <h2
            className="font-serif-display mt-4 text-balance text-[clamp(1.9rem,3.4vw,2.7rem)] font-black leading-[1.08]"
            style={{
              color: PAPER,
              textShadow: "0 2px 8px rgba(127, 23, 71, 0.28)",
            }}
          >
            {t(
              locale,
              "하나의 루프, 세 진입 경로",
              "One loop, three entry paths.",
            )}
          </h2>
          <p
            className="mx-auto mt-4 max-w-lg text-pretty text-[14px] leading-[1.7]"
            style={{
              color: PAPER,
              textShadow: "0 2px 8px rgba(127, 23, 71, 0.22)",
            }}
          >
            {t(
              locale,
              "세션 지속성과 승인 경계는 요청 경로에 남습니다. 각 경로의 차이는 실행이 공통 AgenticLoop에 합류할 때까지 유지됩니다.",
              "Continuity and approval stay attached to each request path. The distinction holds until execution converges on the shared AgenticLoop.",
            )}
          </p>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: reduceMotion ? 0 : 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.65, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
          className="mt-10 overflow-x-auto bg-[#FFF0F8] px-4 py-6 sm:px-8 sm:py-8"
        >
          <svg
            viewBox="0 0 960 352"
            className="h-auto min-w-[840px] w-full"
            role="img"
            aria-label={t(
              locale,
              "세 요청 경로가 두 호스트를 거쳐 하나의 AgenticLoop로 수렴",
              "Three request paths converge through two hosts into one AgenticLoop",
            )}
          >
            <defs>
              <marker
                id="run-arrow"
                markerWidth="8"
                markerHeight="8"
                refX="8"
                refY="4"
                orient="auto"
              >
                <path d="M0 0 L8 4 L0 8 Z" fill={ROSE_INK} />
              </marker>
            </defs>
            <g fontFamily="var(--font-fira-code), monospace">
              <text
                x="20"
                y="20"
                fill={ROSE_INK_70}
                fontSize="9"
                fontWeight="700"
              >
                REQUEST
              </text>
              <text
                x="284"
                y="20"
                fill={ROSE_INK_70}
                fontSize="9"
                fontWeight="700"
              >
                HOST
              </text>
              <text
                x="532"
                y="20"
                fill={ROSE_INK_70}
                fontSize="9"
                fontWeight="700"
              >
                SESSION CONSTRUCTION
              </text>
              <text
                x="788"
                y="20"
                fill={ROSE_INK_70}
                fontSize="9"
                fontWeight="700"
              >
                COMMON CORE
              </text>

              <path
                d="M204 80 H276"
                fill="none"
                stroke={ROSE_INK}
                markerEnd="url(#run-arrow)"
              />
              <path
                d="M204 168 H248 V140 H276"
                fill="none"
                stroke={ROSE_INK}
                markerEnd="url(#run-arrow)"
              />
              <path
                d="M204 272 H276"
                fill="none"
                stroke={ROSE_INK}
                markerEnd="url(#run-arrow)"
              />
              <path
                d="M464 112 H524"
                fill="none"
                stroke={ROSE_INK}
                markerEnd="url(#run-arrow)"
              />
              <path
                d="M464 272 H524"
                fill="none"
                stroke={ROSE_INK}
                markerEnd="url(#run-arrow)"
              />
              <path
                d="M720 112 H752 V160 H776"
                fill="none"
                stroke={ROSE_INK}
                markerEnd="url(#run-arrow)"
              />
              <path
                d="M720 272 H752 V208 H776"
                fill="none"
                stroke={ROSE_INK}
                markerEnd="url(#run-arrow)"
              />

              <rect x="224" y="64" width="68" height="16" fill={PAPER} />
              <text
                x="258"
                y="76"
                textAnchor="middle"
                fill={ROSE_INK_70}
                fontSize="8"
              >
                IPC
              </text>
              <rect x="224" y="144" width="52" height="16" fill={PAPER} />
              <text
                x="250"
                y="156"
                textAnchor="middle"
                fill={ROSE_INK_70}
                fontSize="8"
              >
                JOB
              </text>
              <rect x="208" y="256" width="64" height="16" fill={PAPER} />
              <text
                x="240"
                y="268"
                textAnchor="middle"
                fill={ROSE_INK_70}
                fontSize="7.5"
              >
                STDIO / HTTP
              </text>
              <rect x="732" y="132" width="64" height="16" fill={PAPER} />
              <text
                x="764"
                y="144"
                textAnchor="middle"
                fill={ROSE_INK_70}
                fontSize="8"
              >
                SESSION
              </text>
              <rect x="724" y="244" width="80" height="16" fill={PAPER} />
              <text
                x="764"
                y="256"
                textAnchor="middle"
                fill={ROSE_INK_70}
                fontSize="8"
              >
                ONE-SHOT
              </text>

              <rect
                x="20"
                y="52"
                width="184"
                height="56"
                fill={PAPER}
                stroke={ROSE_INK}
              />
              <text x="32" y="72" fill={ROSE_INK_70} fontSize="8">
                TERMINAL
              </text>
              <text
                x="32"
                y="92"
                fill={ROSE_INK}
                fontSize="13"
                fontWeight="700"
              >
                $ geode
              </text>
              <text x="32" y="104" fill={ROSE_INK_70} fontSize="8">
                session + operator approval relay
              </text>

              <rect
                x="20"
                y="140"
                width="184"
                height="56"
                fill={PAPER}
                stroke={ROSE_INK}
              />
              <text x="32" y="160" fill={ROSE_INK_70} fontSize="8">
                CHANNEL / SCHEDULE
              </text>
              <text
                x="32"
                y="180"
                fill={ROSE_INK}
                fontSize="12"
                fontWeight="700"
              >
                message or due job
              </text>
              <text x="32" y="192" fill={ROSE_INK_70} fontSize="8">
                thread-keyed or scheduled · headless
              </text>

              <rect
                x="20"
                y="244"
                width="184"
                height="56"
                fill={PAPER}
                stroke={ROSE_INK}
              />
              <text x="32" y="264" fill={ROSE_INK_70} fontSize="8">
                MCP CLIENT
              </text>
              <text
                x="32"
                y="284"
                fill={ROSE_INK}
                fontSize="12"
                fontWeight="700"
              >
                run_agent
              </text>
              <text x="32" y="296" fill={ROSE_INK_70} fontSize="8">
                only this MCP tool enters the loop
              </text>

              <rect
                x="280"
                y="52"
                width="184"
                height="160"
                fill={ROSE_INK}
                stroke={ROSE_INK}
              />
              <text x="296" y="76" fill={PAPER} fontSize="8">
                LONG-LIVED HOST
              </text>
              <text x="296" y="104" fill={PAPER} fontSize="16" fontWeight="700">
                geode serve
              </text>
              <line
                x1="296"
                y1="120"
                x2="448"
                y2="120"
                stroke={PAPER}
                opacity="0.55"
              />
              <text x="296" y="144" fill={PAPER} fontSize="9">
                CLI IPC
              </text>
              <text x="296" y="164" fill={PAPER} fontSize="9">
                gateway adapters
              </text>
              <text x="296" y="184" fill={PAPER} fontSize="9">
                scheduler queue
              </text>

              <rect
                x="280"
                y="244"
                width="184"
                height="56"
                fill={PAPER}
                stroke={ROSE_INK}
              />
              <text x="296" y="260" fill={ROSE_INK_70} fontSize="8">
                TOOL HOST
              </text>
              <text
                x="296"
                y="280"
                fill={ROSE_INK}
                fontSize="13"
                fontWeight="700"
              >
                geode-mcp
              </text>
              <text x="296" y="294" fill={ROSE_INK_70} fontSize="7">
                _run_agent bridge
              </text>

              <rect
                x="528"
                y="68"
                width="192"
                height="88"
                fill={PAPER}
                stroke={ROSE_INK}
              />
              <text x="544" y="92" fill={ROSE_INK_70} fontSize="8">
                SHARED SERVICES
              </text>
              <text
                x="544"
                y="116"
                fill={ROSE_INK}
                fontSize="12"
                fontWeight="700"
              >
                create_session(mode)
              </text>
              <text x="544" y="136" fill={ROSE_INK_70} fontSize="8">
                IPC or DAEMON continuity
              </text>

              <rect
                x="528"
                y="236"
                width="192"
                height="72"
                fill={PAPER}
                stroke={ROSE_INK}
                strokeDasharray="4 4"
              />
              <text x="544" y="260" fill={ROSE_INK_70} fontSize="8">
                ISOLATED CONSTRUCTION
              </text>
              <text
                x="544"
                y="284"
                fill={ROSE_INK}
                fontSize="11"
                fontWeight="700"
              >
                arun_agentic_oneshot
              </text>

              <rect
                x="780"
                y="116"
                width="160"
                height="112"
                fill={ROSE_INK}
                stroke={ROSE_INK}
              />
              <text
                x="860"
                y="144"
                textAnchor="middle"
                fill={PAPER}
                fontSize="8"
              >
                SAME PRIMITIVE
              </text>
              <text
                x="860"
                y="172"
                textAnchor="middle"
                fill={PAPER}
                fontSize="16"
                fontWeight="700"
              >
                AgenticLoop
              </text>
              <text
                x="860"
                y="194"
                textAnchor="middle"
                fill={PAPER}
                fontSize="10"
              >
                while(tool_use)
              </text>
              <text
                x="860"
                y="214"
                textAnchor="middle"
                fill={PAPER}
                fontSize="8"
              >
                mode-filtered tools
              </text>

              <line
                x1="20"
                y1="328"
                x2="940"
                y2="328"
                stroke={ROSE_INK_70}
                strokeDasharray="4 4"
              />
              <text x="20" y="346" fill={ROSE_INK_70} fontSize="8">
                serve preserves session continuity
              </text>
              <text
                x="940"
                y="346"
                textAnchor="end"
                fill={ROSE_INK_70}
                fontSize="8"
              >
                MCP run_agent closes an isolated headless session
              </text>
            </g>
          </svg>
        </motion.div>
      </div>
    </section>
  );
}

/* ---------------- features: numbered plates ------------------------------- */

/** GEO's phase, evidence, and authority boundaries. */
function GeoEvidenceBanner() {
  const locale = useLocale();
  const gates = [
    { x: 8, code: "F", name: "fetch" },
    { x: 80, code: "R", name: "retrieve" },
    { x: 152, code: "C", name: "cite" },
    { x: 224, code: "P", name: "place" },
    { x: 296, code: "A", name: "absorb" },
    { x: 368, code: "Q", name: "quality" },
    { x: 440, code: "O", name: "outcome" },
  ];
  return (
    <svg
      viewBox="0 0 520 260"
      role="img"
      aria-label={t(
        locale,
        "GEO의 사전 점검, 승인된 관측, 독립 증거 벡터와 승격 권한 경계",
        "GEO preflight, approved observation, independent evidence vector, and promotion boundary",
      )}
      className="h-full w-full"
    >
      <g fontFamily="var(--font-fira-code), monospace">
        <text x="8" y="16" fill={ROSE_INK} fontSize="12" fontWeight="700">
          /geo
        </text>
        <text x="512" y="16" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          typed evidence state
        </text>
        <line x1="8" y1="28" x2="512" y2="28" stroke={ROSE_INK_70} />

        <text x="8" y="48" fill={ROSE_INK_70} fontSize="8" fontWeight="700">
          PREFLIGHT
        </text>
        <line x1="96" y1="76" x2="116" y2="76" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(116 76)"
        />
        <rect
          x="8"
          y="56"
          width="88"
          height="40"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <text
          x="52"
          y="76"
          textAnchor="middle"
          fill={PAPER}
          fontSize="12"
          fontWeight="700"
        >
          F
        </text>
        <text x="52" y="88" textAnchor="middle" fill={PAPER} fontSize="8">
          fetch
        </text>
        <rect
          x="120"
          y="56"
          width="392"
          height="40"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <text
          x="316"
          y="72"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          LIVE GATE / operator approval
        </text>
        <text
          x="316"
          y="88"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          frozen workload · engine · model · locale · K
        </text>

        <text x="8" y="112" fill={ROSE_INK_70} fontSize="8" fontWeight="700">
          LIVE EVIDENCE
        </text>
        {gates.map((gate) => (
          <g key={gate.code}>
            <rect
              x={gate.x}
              y="120"
              width="64"
              height="44"
              fill={PAPER}
              stroke={ROSE_INK}
            />
            <text
              x={gate.x + 32}
              y="140"
              textAnchor="middle"
              fill={ROSE_INK}
              fontSize="12"
              fontWeight="700"
            >
              {gate.code}
            </text>
            <text
              x={gate.x + 32}
              y="156"
              textAnchor="middle"
              fill={ROSE_INK_70}
              fontSize="8"
            >
              {gate.name}
            </text>
          </g>
        ))}

        <text x="8" y="184" fill={ROSE_INK_70} fontSize="8" fontWeight="700">
          VERDICT
        </text>
        <rect
          x="8"
          y="192"
          width="244"
          height="36"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <text
          x="128"
          y="208"
          textAnchor="middle"
          fill={PAPER}
          fontSize="8"
          fontWeight="700"
        >
          diagnostic
        </text>
        <text x="128" y="220" textAnchor="middle" fill={PAPER} fontSize="8">
          promotion = none
        </text>
        <rect
          x="268"
          y="192"
          width="244"
          height="36"
          fill={PAPER}
          stroke={ROSE_INK}
          strokeDasharray="4 4"
        />
        <text
          x="388"
          y="208"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          experiment
        </text>
        <text
          x="388"
          y="220"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          preregistration required
        </text>

        <line
          x1="8"
          y1="240"
          x2="512"
          y2="240"
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />
        <text
          x="260"
          y="256"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          {t(
            locale,
            "각 축의 분모와 locator가 없으면 not_measured",
            "No denominator and locator means not_measured",
          )}
        </text>
      </g>
    </svg>
  );
}

/** Goal lifecycle, observation-conditioned plan loop, and Grill frontier. */
function SearchDirectionBanner() {
  const locale = useLocale();
  return (
    <svg
      viewBox="0 0 520 568"
      role="img"
      aria-label={t(
        locale,
        "goal 상태머신, 관측 기반 plan 루프, grill 의존성 frontier",
        "Goal state machine, observation-conditioned plan loop, and Grill dependency frontier",
      )}
      className="h-full w-full"
    >
      <g fontFamily="var(--font-fira-code), monospace">
        <text x="8" y="16" fill={ROSE_INK} fontSize="12" fontWeight="700">
          SEARCH POLICY AT RUNTIME
        </text>
        <text x="512" y="16" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          prior × goal × observation
        </text>
        <line x1="8" y1="28" x2="512" y2="28" stroke={ROSE_INK_70} />

        {/* Goal is a durable envelope that conditionally admits physical loop turns. */}
        <text x="8" y="48" fill={ROSE_INK} fontSize="12" fontWeight="700">
          /goal
        </text>
        <text x="512" y="48" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          DURABLE EXECUTION ENVELOPE
        </text>
        <rect
          x="8"
          y="56"
          width="504"
          height="144"
          fill={PAPER}
          stroke={ROSE_INK_70}
        />
        <text x="20" y="72" fill={ROSE_INK_70} fontSize="8" fontWeight="700">
          sessions.db · typed projection
        </text>
        <text x="500" y="72" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          goal_id · objective · tokens · time · revision
        </text>

        <line x1="44" y1="112" x2="88" y2="112" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(88 112)"
        />
        <line x1="236" y1="112" x2="280" y2="112" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(280 112)"
        />
        <path d="M304 88 V80 H164 V92" fill="none" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(164 92) rotate(90)"
        />
        <line x1="328" y1="112" x2="452" y2="112" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(452 112)"
        />
        <path d="M304 136 V156 H336" fill="none" stroke={ROSE_INK_70} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK_70}
          transform="translate(340 156)"
        />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK_70}
          transform="translate(304 136) rotate(-90)"
        />

        <circle cx="32" cy="112" r="12" fill={PAPER} stroke={ROSE_INK} />
        <rect
          x="92"
          y="92"
          width="144"
          height="40"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <polygon
          points="304,88 328,112 304,136 280,112"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <circle cx="480" cy="112" r="16" fill={PAPER} stroke={ROSE_INK} />
        <circle cx="480" cy="112" r="12" fill="none" stroke={ROSE_INK} />
        <rect
          x="344"
          y="132"
          width="152"
          height="48"
          fill={PAPER}
          stroke={ROSE_INK}
          strokeDasharray="4 4"
        />
        <line
          x1="356"
          y1="140"
          x2="356"
          y2="156"
          stroke={ROSE_INK}
          strokeWidth="2"
        />
        <line
          x1="364"
          y1="140"
          x2="364"
          y2="156"
          stroke={ROSE_INK}
          strokeWidth="2"
        />
        <rect x="196" y="72" width="80" height="16" fill={PAPER} />
        <rect x="284" y="144" width="48" height="12" fill={PAPER} />

        <text x="32" y="116" textAnchor="middle" fill={ROSE_INK} fontSize="12">
          ∅
        </text>
        <text
          x="64"
          y="104"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          create
        </text>
        <text
          x="164"
          y="108"
          textAnchor="middle"
          fill={PAPER}
          fontSize="8"
          fontWeight="700"
        >
          ONE PHYSICAL TURN
        </text>
        <text x="164" y="124" textAnchor="middle" fill={PAPER} fontSize="8">
          tool_use* → natural finish
        </text>
        <text
          x="258"
          y="104"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          account
        </text>
        <text
          x="304"
          y="116"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          state
        </text>
        <text
          x="236"
          y="84"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          ACTIVE · admit
        </text>
        <text
          x="392"
          y="104"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          complete · blocked · budget
        </text>
        <text x="480" y="116" textAnchor="middle" fill={ROSE_INK} fontSize="8">
          settled
        </text>
        <text x="324" y="148" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          pause
        </text>
        <text x="324" y="176" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          resume
        </text>
        <text
          x="420"
          y="150"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="12"
          fontWeight="700"
        >
          PAUSED
        </text>
        <text
          x="420"
          y="170"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          same goal_id · admission closed
        </text>
        <text x="20" y="192" fill={ROSE_INK_70} fontSize="8">
          operator / CAS: pause · resume · edit · clear
        </text>
        <text x="500" y="192" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          model: complete · block
        </text>

        <line
          x1="8"
          y1="212"
          x2="512"
          y2="212"
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />

        {/* Plan is advisory intent whose state changes only after evidence. */}
        <text x="8" y="232" fill={ROSE_INK} fontSize="12" fontWeight="700">
          /plan
        </text>
        <text x="512" y="232" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          OBSERVATION-CONDITIONED ADVISORY
        </text>
        <text x="8" y="248" fill={ROSE_INK_70} fontSize="8">
          planner compares 2-4 structures with tools disabled
        </text>

        {[280, 296, 312].map((y) => (
          <circle key={y} cx="28" cy={y} r="4" fill={PAPER} stroke={ROSE_INK} />
        ))}
        {[280, 296, 312].map((y) => (
          <line key={y} x1="32" y1={y} x2="76" y2="296" stroke={ROSE_INK_70} />
        ))}
        <line x1="224" y1="296" x2="268" y2="296" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(268 296)"
        />
        <line x1="376" y1="296" x2="420" y2="296" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(420 296)"
        />
        <path d="M452 328 V336 H176 V340" fill="none" stroke={ROSE_INK_70} />
        <path d="M452 328 V336 H392 V340" fill="none" stroke={ROSE_INK_70} />

        <rect
          x="80"
          y="264"
          width="144"
          height="64"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <rect
          x="272"
          y="264"
          width="104"
          height="64"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <polygon
          points="452,264 484,296 452,328 420,296"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <rect
          x="104"
          y="340"
          width="144"
          height="28"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <rect
          x="296"
          y="340"
          width="192"
          height="28"
          fill={PAPER}
          stroke={ROSE_INK}
          strokeDasharray="4 4"
        />

        <text
          x="152"
          y="284"
          textAnchor="middle"
          fill={PAPER}
          fontSize="12"
          fontWeight="700"
        >
          PLAN rev n
        </text>
        <text x="152" y="300" textAnchor="middle" fill={PAPER} fontSize="8">
          ≤8 ordered intents
        </text>
        <text x="152" y="316" textAnchor="middle" fill={PAPER} fontSize="8">
          current k · no dispatch
        </text>
        <text
          x="324"
          y="284"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="11"
          fontWeight="700"
        >
          AgenticLoop
        </text>
        <text
          x="324"
          y="300"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          choose next action
        </text>
        <text
          x="324"
          y="316"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          from latest state
        </text>
        <text
          x="452"
          y="292"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          NEW
        </text>
        <text
          x="452"
          y="304"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          EVIDENCE
        </text>
        <text
          x="176"
          y="352"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          expected met
        </text>
        <text
          x="176"
          y="364"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          update_plan / current + 1
        </text>
        <text
          x="392"
          y="352"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          verify fail or confidence &lt; .4
        </text>
        <text
          x="392"
          y="364"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          replan / revision n + 1
        </text>

        <line
          x1="8"
          y1="380"
          x2="512"
          y2="380"
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />

        {/* Grill moves a computed answerable frontier after an exact typed answer. */}
        <text x="8" y="400" fill={ROSE_INK} fontSize="12" fontWeight="700">
          /grill
        </text>
        <text x="512" y="400" textAnchor="end" fill={ROSE_INK_70} fontSize="8">
          TYPED DAG · 1-24 NODES · ACYCLIC
        </text>
        <text x="24" y="424" fill={ROSE_INK_70} fontSize="8" fontWeight="700">
          BEFORE · frontier = Q1
        </text>
        <text x="344" y="424" fill={ROSE_INK_70} fontSize="8" fontWeight="700">
          AFTER · frontier = Q2, Q3
        </text>

        <line x1="88" y1="468" x2="100" y2="468" stroke={ROSE_INK} />
        <line x1="100" y1="444" x2="100" y2="492" stroke={ROSE_INK_70} />
        <line x1="100" y1="444" x2="108" y2="444" stroke={ROSE_INK_70} />
        <line x1="100" y1="492" x2="108" y2="492" stroke={ROSE_INK_70} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK_70}
          transform="translate(108 444)"
        />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK_70}
          transform="translate(108 492)"
        />
        <line x1="176" y1="444" x2="188" y2="444" stroke={ROSE_INK_70} />
        <line x1="176" y1="492" x2="188" y2="492" stroke={ROSE_INK_70} />
        <line x1="188" y1="444" x2="188" y2="492" stroke={ROSE_INK_70} />
        <line x1="188" y1="468" x2="220" y2="468" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(220 468)"
        />
        <line x1="308" y1="468" x2="340" y2="468" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(340 468)"
        />
        <line x1="408" y1="468" x2="420" y2="468" stroke={ROSE_INK} />
        <line x1="420" y1="444" x2="420" y2="492" stroke={ROSE_INK} />
        <line x1="420" y1="444" x2="428" y2="444" stroke={ROSE_INK} />
        <line x1="420" y1="492" x2="428" y2="492" stroke={ROSE_INK} />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(428 444)"
        />
        <polygon
          points="-4,-4 4,0 -4,4"
          fill={ROSE_INK}
          transform="translate(428 492)"
        />

        <rect
          x="24"
          y="452"
          width="64"
          height="32"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <rect
          x="112"
          y="428"
          width="64"
          height="32"
          fill={PAPER}
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />
        <rect
          x="112"
          y="476"
          width="64"
          height="32"
          fill={PAPER}
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />
        <rect
          x="224"
          y="440"
          width="84"
          height="56"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <rect
          x="344"
          y="452"
          width="64"
          height="32"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <rect
          x="432"
          y="428"
          width="64"
          height="32"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <rect
          x="432"
          y="476"
          width="64"
          height="32"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />

        <text
          x="56"
          y="472"
          textAnchor="middle"
          fill={PAPER}
          fontSize="11"
          fontWeight="700"
        >
          Q1
        </text>
        <text
          x="144"
          y="448"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="10"
        >
          Q2 locked
        </text>
        <text
          x="144"
          y="496"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="10"
        >
          Q3 locked
        </text>
        <text
          x="266"
          y="460"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="8"
          fontWeight="700"
        >
          EXACT LABEL
        </text>
        <text
          x="266"
          y="476"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          update_grill
        </text>
        <text
          x="266"
          y="488"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          CAS rev + 1
        </text>
        <text
          x="376"
          y="472"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="10"
          fontWeight="700"
        >
          Q1 ✓
        </text>
        <text
          x="464"
          y="448"
          textAnchor="middle"
          fill={PAPER}
          fontSize="10"
          fontWeight="700"
        >
          Q2
        </text>
        <text
          x="464"
          y="496"
          textAnchor="middle"
          fill={PAPER}
          fontSize="10"
          fontWeight="700"
        >
          Q3
        </text>

        <line
          x1="8"
          y1="528"
          x2="512"
          y2="528"
          stroke={ROSE_INK_70}
          strokeDasharray="4 4"
        />
        <text
          x="260"
          y="544"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          {t(
            locale,
            "답변은 다음 frontier만 열고, unresolved=0일 때만 완료됩니다",
            "Each answer opens only the next frontier; completion requires unresolved = 0",
          )}
        </text>
        <text
          x="260"
          y="560"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="8"
        >
          {t(
            locale,
            "typed state는 dynamic context에 주입되며 prose로 바뀌지 않습니다",
            "Typed state enters dynamic context; prose cannot mutate it",
          )}
        </text>
      </g>
    </svg>
  );
}

/**
 * Tau2 numbers over a measurement slip that separates what is being
 * measured (the agentic harness: GEODE's loop wrapped around a model) from
 * the ruler (the tau2-bench eval harness), closing on the external paper
 * reference and comparability verdict. Values from benchmark-measurements.ts
 * and the externally preserved tau2 run artifacts.
 */
function MeasureBanner() {
  const tau2 = BENCHMARK_GROUPS.find((group) => group.id === "tau2");
  const cells = (tau2?.matrix ?? []).filter((cell) =>
    ["Retail", "Telecom", "Airline"].includes(cell.label),
  );
  const slip: {
    key: string;
    value: string;
    section?: string;
    verdict?: boolean;
  }[] = [
    {
      key: "loop",
      value: "geode v0.99.269",
      section: "agentic harness · measured",
    },
    { key: "model", value: "gpt-5.2 high · payg" },
    {
      key: "bench",
      value: "tau2 @ 1901a30 · 2026-07-03",
      section: "eval harness · the ruler",
    },
    { key: "user-sim", value: "gpt-4.1 · pass^1 k=1" },
    { key: "airline", value: "trend-reference" },
    {
      key: "reference",
      value: "gpt-5.2 · wrapper undisclosed · 0.802",
      section: "agent-world paper",
    },
    {
      key: "verdict",
      value: "directional · causal effect unmeasured",
      verdict: true,
    },
  ];
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-[clamp(0.875rem,1.2vw,1.125rem)] px-4">
      <div className="flex items-baseline justify-center gap-[clamp(1.5rem,2vw,2rem)]">
        {cells.map((cell) => (
          <div key={cell.label} className="text-center">
            <p
              className="font-serif-display text-[clamp(24px,2.3vw,30px)] font-black"
              style={{ color: ROSE_INK }}
            >
              {cell.value}
            </p>
            <p
              className="mt-1 font-mono text-[clamp(9.5px,0.85vw,11px)] uppercase tracking-[0.2em]"
              style={{ color: ROSE_INK_70 }}
            >
              {cell.label}
            </p>
          </div>
        ))}
      </div>
      <div
        className="w-[82%] max-w-none overflow-hidden border"
        style={{ borderColor: ROSE_INK_70 }}
      >
        {slip.map(({ key, value, section, verdict }, i) => (
          <div key={key}>
            {section && (
              <p
                className="px-3 pb-[clamp(2px,0.25vw,4px)] pt-[clamp(6px,0.55vw,8px)] text-left font-mono text-[clamp(8px,0.7vw,9.5px)] uppercase tracking-[0.22em]"
                style={{
                  color: ROSE_INK_70,
                  background: "color-mix(in srgb, #C2447F 8%, transparent)",
                  borderTop: i
                    ? "1px solid color-mix(in srgb, #C2447F 25%, transparent)"
                    : undefined,
                }}
              >
                {section}
              </p>
            )}
            <div
              className={`flex items-baseline justify-between gap-3 px-3 py-[clamp(4px,0.45vw,6px)] font-mono text-[clamp(9.5px,0.82vw,11px)] ${verdict ? "bg-[#C2447F] text-[#FFF0F8]" : ""}`}
              style={
                verdict || section
                  ? section && !verdict
                    ? {
                        background:
                          "color-mix(in srgb, #C2447F 8%, transparent)",
                      }
                    : undefined
                  : {
                      borderTop: i
                        ? "1px solid color-mix(in srgb, #C2447F 18%, transparent)"
                        : undefined,
                    }
              }
            >
              <span
                className="uppercase tracking-[0.14em]"
                style={verdict ? { opacity: 0.85 } : { color: ROSE_INK_70 }}
              >
                {key}
              </span>
              <span
                className={verdict ? "font-semibold" : ""}
                style={verdict ? undefined : { color: ROSE_INK }}
              >
                {value}
              </span>
            </div>
          </div>
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
    <div className="flex h-full w-full items-center justify-center px-4">
      <div className="w-[82%] max-w-none">
        <div
          className="overflow-hidden border"
          style={{ borderColor: ROSE_INK_70 }}
        >
          {tiers.map(({ tier, name, alpha }, i) => (
            <div
              key={tier}
              className="flex items-baseline justify-between px-4 py-[clamp(9px,0.85vw,12px)] font-mono text-[clamp(11px,1vw,13px)]"
              style={{
                background: `color-mix(in srgb, var(--acc-artifact) ${alpha * 100}%, transparent)`,
                borderTop: i
                  ? "1px solid color-mix(in srgb, var(--acc-artifact) 30%, transparent)"
                  : undefined,
              }}
            >
              <span style={{ color: ROSE_INK_70 }}>{tier}</span>
              <span style={{ color: ROSE_INK }}>{name}</span>
            </div>
          ))}
          <div className="flex items-baseline justify-between bg-[#C2447F] px-4 py-[clamp(9px,0.85vw,12px)] font-mono text-[clamp(11px,1vw,13px)] text-[#FFF0F8]">
            <span style={{ opacity: 0.8 }}>tier 3</span>
            <span className="font-semibold">session</span>
          </div>
        </div>
        <p
          className="mt-3 flex items-center justify-center gap-2 font-mono text-[clamp(10px,0.85vw,11.5px)] uppercase tracking-[0.2em]"
          style={{ color: ROSE_INK_70 }}
        >
          <span className="inline-block h-[5px] w-[5px] rotate-45 bg-[#C2447F]" />
          lower tiers override higher
          <span className="inline-block h-[5px] w-[5px] rotate-45 bg-[#C2447F]" />
        </p>
      </div>
    </div>
  );
}

/** Three generations of eval-data contracts, from legacy input to PRE lineage. */
function DataLineageBanner() {
  const locale = useLocale();
  const rows: {
    label: string;
    y: number;
    nodes: {
      x: number;
      width: number;
      title: string;
      sub: string;
      focal?: boolean;
      proposed?: boolean;
    }[];
  }[] = [
    {
      label: "LEGACY",
      y: 48,
      nodes: [
        { x: 88, width: 104, title: "transcript JSONL", sub: "read adapter" },
        { x: 208, width: 144, title: "trajectory@2026", sub: "07-29 · 07-31" },
        { x: 368, width: 144, title: "public bytes", sub: "immutable" },
      ],
    },
    {
      label: "CURRENT",
      y: 112,
      nodes: [
        {
          x: 88,
          width: 104,
          title: "session-event@1",
          sub: "canonical events",
        },
        {
          x: 208,
          width: 144,
          title: "trajectory@1",
          sub: "stable projection",
          focal: true,
        },
        { x: 368, width: 144, title: "release@1", sub: "scope + privacy" },
      ],
    },
    {
      label: "PRE",
      y: 176,
      nodes: [
        { x: 88, width: 96, title: "example@1", sub: "input", proposed: true },
        {
          x: 200,
          width: 96,
          title: "rollout@1",
          sub: "attempt",
          proposed: true,
        },
        { x: 312, width: 96, title: "trajectory@1", sub: "behavior" },
        { x: 424, width: 88, title: "reward@1", sub: "score", proposed: true },
      ],
    },
  ];
  return (
    <svg
      viewBox="0 0 520 252"
      role="img"
      aria-label={t(
        locale,
        "legacy부터 현재와 PRE까지 세 단계로 이어지는 평가 데이터 계약 발전사",
        "Three generations of eval-data contracts from legacy through current and PRE",
      )}
      className="h-full w-full"
    >
      <g fontFamily="var(--font-fira-code), monospace">
        <text x="8" y="16" fill={ROSE_INK} fontSize="14" fontWeight="700">
          EVAL DATA EVOLUTION
        </text>
        <text x="512" y="16" textAnchor="end" fill={ROSE_INK_70} fontSize="10">
          schema_id = geode.*
        </text>
        <line x1="8" y1="28" x2="512" y2="28" stroke={ROSE_INK_70} />

        <line
          x1="72"
          y1="68"
          x2="72"
          y2="224"
          stroke={ROSE_INK_70}
          strokeDasharray="2 4"
        />
        <polygon
          points="-4,-3 0,4 4,-3"
          fill={ROSE_INK_70}
          transform="translate(72 224)"
        />
        {rows.map((row) => (
          <g key={`${row.label}-arrows`}>
            {row.nodes.slice(0, -1).map((node, index) => {
              const next = row.nodes[index + 1];
              return (
                <g key={node.title}>
                  <line
                    x1={node.x + node.width}
                    y1={row.y + 20}
                    x2={next.x}
                    y2={row.y + 20}
                    stroke={ROSE_INK}
                  />
                  <polygon
                    points="-3,-3.5 4,0 -3,3.5"
                    fill={ROSE_INK}
                    transform={`translate(${next.x} ${row.y + 20})`}
                  />
                </g>
              );
            })}
          </g>
        ))}

        {rows.map((row) => (
          <g key={row.label}>
            <circle
              cx="72"
              cy={row.y + 20}
              r={row.label === "CURRENT" ? 6 : 4}
              fill={row.label === "CURRENT" ? ROSE_INK : PAPER}
              stroke={ROSE_INK}
            />
            <text
              x="8"
              y={row.y + 16}
              fill={row.label === "CURRENT" ? ROSE_INK : ROSE_INK_70}
              fontSize="9"
              fontWeight="700"
            >
              {row.label}
            </text>
            {row.nodes.map((node) => (
              <g key={node.title}>
                <rect
                  x={node.x}
                  y={row.y}
                  width={node.width}
                  height="40"
                  fill={node.focal ? ROSE_INK : PAPER}
                  stroke={ROSE_INK}
                  strokeDasharray={node.proposed ? "4 4" : undefined}
                />
                <text
                  x={node.x + node.width / 2}
                  y={row.y + 16}
                  textAnchor="middle"
                  fill={node.focal ? PAPER : ROSE_INK}
                  fontSize="9.5"
                  fontWeight="700"
                >
                  {node.title}
                </text>
                <text
                  x={node.x + node.width / 2}
                  y={row.y + 32}
                  textAnchor="middle"
                  fill={node.focal ? PAPER : ROSE_INK_70}
                  fontSize="9"
                >
                  {node.sub}
                </text>
              </g>
            ))}
          </g>
        ))}

        <line
          x1="8"
          y1="232"
          x2="512"
          y2="232"
          stroke={ROSE_INK_70}
          strokeDasharray="2 4"
        />
        <text
          x="260"
          y="248"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="9.5"
        >
          {t(
            locale,
            ".eval은 native evidence · reward는 release 권한이 아닙니다",
            ".eval stays native evidence · reward never grants release",
          )}
        </text>
      </g>
    </svg>
  );
}

/** Delegation contract: frozen authority, isolated execution, correlated return. */
function DelegateDiagram() {
  const locale = useLocale();
  const children = [112, 246, 380];
  return (
    <svg
      viewBox="0 0 520 200"
      className="h-full w-full"
      role="img"
      aria-label={t(
        locale,
        "부모가 작업 계약을 동결하고 권한을 필터링한 뒤 격리된 자식 세션의 결과를 task_id로 회수하는 구조",
        "A parent freezes the task contract, filters authority, and rejoins isolated child results by task ID",
      )}
    >
      <g fontFamily="var(--font-fira-code), monospace">
        <text x="8" y="16" fill={ROSE_INK} fontSize="14" fontWeight="700">
          DELEGATE
        </text>
        <text x="512" y="16" textAnchor="end" fill={ROSE_INK_70} fontSize="10">
          depth 1 / session cap 15
        </text>
        <line x1="8" y1="28" x2="512" y2="28" stroke={ROSE_INK_70} />

        <text x="8" y="50" fill={ROSE_INK_70} fontSize="10" fontWeight="700">
          CONTRACT
        </text>
        <rect
          x="112"
          y="34"
          width="388"
          height="28"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <text
          x="306"
          y="52"
          textAnchor="middle"
          fill={PAPER}
          fontSize="10"
          fontWeight="700"
        >
          task / model / tool policy
        </text>

        <text x="8" y="84" fill={ROSE_INK_70} fontSize="10" fontWeight="700">
          GATE
        </text>
        <line
          x1="112"
          y1="76"
          x2="500"
          y2="76"
          stroke={ROSE_INK}
          strokeDasharray="4 4"
        />
        <rect
          x="218"
          y="67"
          width="176"
          height="18"
          fill={PAPER}
          stroke={ROSE_INK}
        />
        <text
          x="306"
          y="79"
          textAnchor="middle"
          fill={ROSE_INK}
          fontSize="9"
          fontWeight="700"
        >
          deny auth / personal / delegate
        </text>

        <text x="8" y="119" fill={ROSE_INK_70} fontSize="10" fontWeight="700">
          RUN
        </text>
        <line x1="306" y1="85" x2="306" y2="96" stroke={ROSE_INK} />
        <line x1="172" y1="96" x2="440" y2="96" stroke={ROSE_INK} />
        {children.map((x, index) => (
          <g key={x}>
            <line x1={x + 60} y1="96" x2={x + 60} y2="104" stroke={ROSE_INK} />
            <polygon
              points="-3,-3.5 4,0 -3,3.5"
              fill={ROSE_INK}
              transform={`translate(${x + 60} 104) rotate(90)`}
            />
            <rect
              x={x}
              y="104"
              width="120"
              height="34"
              fill={PAPER}
              stroke={ROSE_INK}
            />
            <text
              x={x + 60}
              y="119"
              textAnchor="middle"
              fill={ROSE_INK}
              fontSize="10"
              fontWeight="700"
            >
              child session {String.fromCharCode(65 + index)}
            </text>
            <text
              x={x + 60}
              y="131"
              textAnchor="middle"
              fill={ROSE_INK_70}
              fontSize="8.5"
            >
              isolated context
            </text>
          </g>
        ))}

        <text x="8" y="166" fill={ROSE_INK_70} fontSize="10" fontWeight="700">
          JOIN
        </text>
        {children.map((x) => (
          <line
            key={x}
            x1={x + 60}
            y1="138"
            x2={x + 60}
            y2="150"
            stroke={ROSE_INK}
          />
        ))}
        <rect
          x="112"
          y="150"
          width="388"
          height="28"
          fill={ROSE_INK}
          stroke={ROSE_INK}
        />
        <text
          x="306"
          y="168"
          textAnchor="middle"
          fill={PAPER}
          fontSize="10"
          fontWeight="700"
        >
          SubResult &#123; task_id / status / output &#125;
        </text>
        <text
          x="306"
          y="193"
          textAnchor="middle"
          fill={ROSE_INK_70}
          fontSize="9.5"
        >
          {t(
            locale,
            "성공 / 실패 / 중단을 부모 실행 기록에 합류",
            "Success / failure / interruption rejoin the parent record",
          )}
        </text>
      </g>
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
  status?: "pre" | "pre-release";
}[] = [
  {
    id: "execute",
    plate: 1,
    index: "#1 execute",
    headKo: "루프를 돌립니다",
    headEn: "RUNS THE LOOP",
    ko: "GEODE는 Plan, Act, Observe, Reflect, Verify 순환으로 추론을 관측에 묶습니다. 각 결과는 다음 도구 호출 전에 제안과 확신도를 다시 조정합니다. 자연스러운 완료가 turn을 닫습니다.",
    en: "GEODE keeps reasoning coupled to evidence through a Plan, Act, Observe, Reflect, Verify cycle. Each result can revise the next proposal before tool use continues. Natural completion closes the turn.",
    banner: <LoopDiagram />,
  },
  {
    id: "geo",
    plate: 2,
    index: "#2 explore",
    headKo: "증거가 있는 단계만 측정합니다",
    headEn: "MEASURES ONLY RECEIPTED STAGES",
    ko: "GEO는 가시성을 영수증이 남는 관측 사슬로 봅니다. fetch에서 시작해 동결되고 승인된 실행만 다음 단계를 엽니다. 측정은 끊긴 지점을 찾고 승격은 별도로 판단합니다.",
    en: "GEO models visibility as receipted observations. Fetch opens the chain; frozen, approved runs admit later stages. Diagnosis finds the break, while promotion stays a separate decision.",
    banner: <GeoEvidenceBanner />,
    status: "pre-release",
  },
  {
    id: "direct",
    plate: 6,
    index: "#3 direct",
    headKo: "관측할 때마다 다음 탐색 범위를 줄입니다",
    headEn: "NARROWS THE SEARCH AFTER EACH OBSERVATION",
    ko: "GEODE는 관측할 때마다 긴 작업의 다음 탐색 범위를 줄입니다. /goal은 목표를 보존하고, /plan과 /grill은 typed state 안에서 경로와 결정을 갱신합니다.",
    en: "GEODE narrows long tasks after each observation. /goal preserves the objective while /plan and /grill update the route and its blocking decisions under typed state.",
    banner: <SearchDirectionBanner />,
  },
  {
    id: "remember",
    plate: 7,
    index: "#4 remember",
    headKo: "쌓이는 기억",
    headEn: "MEMORY THAT COMPOUNDS",
    ko: "기억은 하나의 transcript가 아니라 범위별 상태로 축적됩니다. 개인, 조직, 프로젝트, 세션 정보는 SQLite에 남습니다. 다음 turn에는 필요한 층만 다시 컨텍스트로 조립됩니다.",
    en: "Memory accumulates as scoped state rather than one transcript. Personal, organizational, project, and session knowledge persists in SQLite. Each turn assembles only the tiers it needs.",
    banner: <MemoryBanner />,
  },
  {
    id: "eval-lineage",
    plate: 8,
    index: "#5 eval data",
    headKo: "평가 데이터도 진화합니다",
    headEn: "TRACKS HOW EVAL DATA EVOLVED",
    ko: "평가 데이터는 하나의 점수가 아니라 버전 계보입니다. transcript는 stable trajectory를 거쳐 example, rollout, reward로 분화합니다. native .eval은 실행을 보존하고 release는 별도로 판정합니다.",
    en: "Evaluation data forms a versioned lineage. Transcripts become stable trajectories, then proposed example, rollout, and reward records. Native .eval records execution; release remains separate.",
    banner: <DataLineageBanner />,
    status: "pre",
  },
  {
    id: "delegate",
    plate: 9,
    index: "#6 delegate",
    headKo: "위임마다 권한 경계를 고정합니다",
    headEn: "DELEGATES WITH BOUNDED AUTHORITY",
    ko: "위임은 작업, 모델, 허용 도구를 먼저 고정합니다. 격리된 depth-one child는 originating task_id로 돌아옵니다. 지속과 release 권한은 부모에게 남습니다.",
    en: "Delegation freezes the task, model, and allowed tools first. Each isolated, depth-one child returns under its originating task_id. The parent retains continuation and release authority.",
    banner: <DelegateDiagram />,
  },
  {
    id: "audit",
    plate: 3,
    index: "#7 audit",
    headKo: "모든 변이는 심판대에",
    headEn: "EVERY MUTATION ON TRIAL",
    ko: "변이와 판정은 서로 다른 권한으로 남습니다. 스캐폴드 변경은 적대적 Petri 감사를 받고 critical 회귀 하나가 승격을 막습니다. 채택 후보는 선호가 아니라 증거를 견딘 결과입니다.",
    en: "Mutation and judgment stay separate. Scaffold changes face an adversarial Petri audit, and any critical regression blocks promotion. Kept candidates have survived evidence, not preference.",
    banner: <AuditGateDiagram />,
  },
  {
    id: "breed",
    plate: 4,
    index: "#8 breed",
    headKo: "시험을 키우고 탐색에 경계를 둡니다",
    headEn: "GROWS THE EXAM, BOUNDS THE SEARCH",
    ko: "Seed generation은 시험의 범위를 넓히고 Crucible은 후보를 동결된 계약 아래 반복 비교합니다. KEEP은 private search head를 전진시킵니다. 한계에 닿은 실행은 별도의 sealed test와 release 경계로 넘어갑니다.",
    en: "Seed generation expands the exam while Crucible compares candidates under a frozen contract. KEEP advances the private search head. A bounded run hands off to separate sealed-test and release authorities.",
    banner: <SeedgenDiagram />,
  },
  {
    id: "measure",
    plate: 5,
    index: "#9 measure",
    headKo: "정직하게 잽니다",
    headEn: "KEEPS HONEST SCORE",
    ko: "GEODE와 비교 행은 명시된 측정 계약 아래에서만 읽습니다. tau2는 wrapped system을 기록하고 Agent-World는 방향성 맥락을 제공합니다. 인과 주장은 조건을 맞춘 대조군을 기다립니다.",
    en: "GEODE and its reference row follow explicit measurement contracts. Tau2 records the wrapped system; Agent-World offers directional context. Causal claims wait for a matched control.",
    banner: <MeasureBanner />,
  },
];

/** One plate as a postcard: index, perforated Geodi stamp, art, caption. */
function PlateCard({
  feature,
  onOpen,
}: {
  feature: (typeof features)[number];
  onOpen?: () => void;
}) {
  const locale = useLocale();
  const needsDiagramRoom = ["direct", "eval-lineage", "delegate"].includes(
    feature.id,
  );
  return (
    <div
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      aria-haspopup={onOpen ? "dialog" : undefined}
      aria-label={
        onOpen
          ? t(locale, `${feature.headKo} 크게 보기`, `Open ${feature.headEn}`)
          : undefined
      }
      onClick={onOpen}
      onKeyDown={
        onOpen
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onOpen();
              }
            }
          : undefined
      }
      className={`flex h-full min-w-0 flex-col bg-[#FFF0F8] p-4 pb-6 ${onOpen ? "cursor-zoom-in focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#FFF0F8]" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div
          className="flex items-center gap-2 pt-1 font-mono text-[10.5px] uppercase tracking-[0.22em]"
          style={{ color: ROSE_INK_70 }}
        >
          <span>{feature.index}</span>
          {feature.status ? (
            <span
              className="border px-1.5 py-0.5 text-[8px] font-semibold tracking-[0.18em]"
              style={{ borderColor: ROSE_INK, color: ROSE_INK }}
            >
              {feature.status === "pre-release" ? "PRE-RELEASE" : "PRE"}
            </span>
          ) : null}
        </div>
        <div
          className="flex h-12 w-11 shrink-0 items-center justify-center border border-dashed"
          style={{ borderColor: ROSE_INK_70 }}
        >
          <GeodiSprite scale={1.6} silhouette={ROSE_INK} />
        </div>
      </div>
      <div
        className="mt-3 min-h-0 min-w-0 flex-1 overflow-hidden bg-cover bg-center"
        style={{
          backgroundImage: `linear-gradient(rgba(255,240,248,0.8), rgba(255,240,248,0.8)), url(/geode/images/plate-bg-${feature.plate}.png)`,
          imageRendering: "pixelated",
        }}
      >
        <div
          className={`flex h-full w-full min-w-0 items-center justify-center py-3 ${needsDiagramRoom ? "px-0" : "px-2"}`}
        >
          {feature.banner}
        </div>
      </div>
      <h2
        className="font-serif-display mt-4 text-balance text-[24px] font-black uppercase leading-[1.12] sm:text-[26px]"
        style={{ color: ROSE_INK }}
      >
        {locale === "en" ? feature.headEn : feature.headKo}
      </h2>
      <p
        className="mt-2 max-w-[494px] text-[12.5px] leading-[1.65]"
        style={{ color: ROSE_INK_70 }}
      >
        {t(locale, feature.ko, feature.en)}
      </p>
    </div>
  );
}

function FeaturesGrid() {
  const locale = useLocale();
  const reduceMotion = useReducedMotion();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [selectedFeature, setSelectedFeature] = useState<
    (typeof features)[number] | null
  >(null);
  const [isDialogClosing, setIsDialogClosing] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (selectedFeature && dialog && !dialog.open) dialog.showModal();
  }, [selectedFeature]);

  const closeDialog = () => {
    const dialog = dialogRef.current;
    if (!dialog?.open) return;
    if (reduceMotion) dialog.close();
    else setIsDialogClosing(true);
  };

  return (
    <section id="features" className="bg-[var(--acc-artifact)]">
      <div className="mx-auto max-w-7xl px-6 py-16 sm:py-24">
        <div className="grid gap-10 md:grid-cols-2 xl:grid-cols-3">
          {features.map((feature, i) => (
            <motion.div
              key={feature.id}
              className="aspect-[100/148] min-w-0"
              initial={{ opacity: 0, y: reduceMotion ? 0 : 46 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-140px" }}
              transition={{
                duration: 0.7,
                delay: (i % 2) * 0.1,
                ease: [0.22, 1, 0.36, 1],
              }}
            >
              <PlateCard
                feature={feature}
                onOpen={() => {
                  setIsDialogClosing(false);
                  setSelectedFeature(feature);
                }}
              />
            </motion.div>
          ))}
        </div>
        <dialog
          ref={dialogRef}
          aria-label={
            selectedFeature
              ? t(
                  locale,
                  `${selectedFeature.headKo} 상세 엽서`,
                  `${selectedFeature.headEn} postcard detail`,
                )
              : undefined
          }
          data-closing={isDialogClosing ? "true" : undefined}
          onCancel={(event) => {
            event.preventDefault();
            closeDialog();
          }}
          onClose={() => {
            setIsDialogClosing(false);
            setSelectedFeature(null);
          }}
          onClick={(event) => {
            if (event.target === event.currentTarget) closeDialog();
          }}
          className="postcard-dialog m-auto max-h-[94dvh] max-w-none overflow-visible bg-transparent p-0"
        >
          {selectedFeature ? (
            <motion.div
              initial={reduceMotion ? false : { opacity: 0 }}
              animate={{ opacity: isDialogClosing ? 0 : 1 }}
              transition={{
                duration: isDialogClosing ? 0.18 : 0.32,
                ease: isDialogClosing
                  ? [0.22, 1, 0.36, 1]
                  : [0.25, 0.1, 0.25, 1],
              }}
              onAnimationComplete={() => {
                if (isDialogClosing) dialogRef.current?.close();
              }}
              className="relative flex min-h-[90dvh] min-w-[92vw] items-center justify-center overflow-hidden p-5 sm:p-8"
              style={{
                backgroundColor: "#8D4C67",
                backgroundImage:
                  "linear-gradient(110deg, rgba(255,240,248,0.09), transparent 38%), repeating-linear-gradient(2deg, rgba(78,20,45,0.16) 0 1px, transparent 1px 18px)",
                boxShadow: "0 32px 90px rgba(74, 25, 49, 0.48)",
              }}
            >
              <button
                type="button"
                aria-label={t(locale, "상세 엽서 닫기", "Close postcard detail")}
                onClick={closeDialog}
                className="absolute right-3 top-3 z-[1] flex h-9 w-9 items-center justify-center rounded-md text-[#FFF0F8]/70 transition-[background-color,color,transform] hover:bg-[#FFF0F8]/10 hover:text-[#FFF0F8] focus-visible:bg-[#FFF0F8]/10 focus-visible:text-[#FFF0F8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#FFF0F8] active:scale-95 active:bg-[#FFF0F8]/15 sm:right-5 sm:top-5"
              >
                <svg aria-hidden="true" viewBox="0 0 20 20" className="h-5 w-5" fill="none">
                  <path
                    d="M5 5L15 15M15 5L5 15"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
              <motion.div
                initial={
                  reduceMotion ? false : { opacity: 0, scale: 0.9, y: 30 }
                }
                animate={
                  isDialogClosing
                    ? { opacity: 0, scale: 0.97, y: 10 }
                    : { opacity: 1, scale: 1, y: 0 }
                }
                transition={
                  isDialogClosing
                    ? { duration: 0.18, ease: [0.22, 1, 0.36, 1] }
                    : { type: "spring", stiffness: 170, damping: 22, mass: 0.8 }
                }
                className="aspect-[100/148] shadow-[0_28px_72px_rgba(72,18,43,0.42)]"
                style={{ width: "min(86vw, 56dvh, 720px)" }}
              >
                <PlateCard feature={selectedFeature} />
              </motion.div>
            </motion.div>
          ) : null}
        </dialog>
        <div
          className="mt-16 flex items-end justify-end font-mono text-[10px] uppercase tracking-[0.18em]"
          style={FIELD_META_STYLE}
        >
          <span>evidence: core/ · evals/ · evolve/</span>
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
    <div
      aria-hidden
      className="relative w-full overflow-hidden"
      style={{ height }}
    >
      {items.map((f, i) => (
        <div
          key={i}
          className="absolute inset-y-0"
          style={{ left: `${f.left + (50 - f.left) * converge}%` }}
        >
          <div
            className="geodi-snow h-full"
            style={{
              animationDuration: `${f.dur}s`,
              animationDelay: `${f.delay}s`,
            }}
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
    <div
      aria-hidden
      className="relative mx-auto flex w-full max-w-5xl items-center gap-4 px-8"
    >
      <div className="h-px flex-1 bg-gradient-to-r from-transparent to-[rgba(127,23,71,0.55)]" />
      <span className="h-[5px] w-[5px] rotate-45 bg-[#7F1747] opacity-80" />
      <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.34em] text-[#7F1747]">
        {label}
      </span>
      <span className="h-[5px] w-[5px] rotate-45 bg-[#7F1747] opacity-80" />
      <div className="h-px flex-1 bg-gradient-to-l from-transparent to-[rgba(127,23,71,0.55)]" />
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
  const { scrollYProgress } = useScroll({
    target: wrapRef,
    offset: ["start start", "end end"],
  });
  // Clip extends 15% past the line box: leading-[0.82] lets the pixel glyphs
  // overflow it, and a box-bounded clip would leave the letter caps unfilled.
  const fill = useTransform(
    scrollYProgress,
    [0.18, 0.55],
    ["inset(-15% 0 115% 0)", "inset(-15% 0 -15% 0)"],
  );
  const ledgerOp = useTransform(scrollYProgress, [0.48, 0.64], [0, 1]);
  const labOp = useTransform(scrollYProgress, [0.74, 0.9], [0, 1]);
  const labPointer = useTransform(
    labOp,
    (v) => (v > 0.55 ? "auto" : "none") as "auto" | "none",
  );
  // The pinned headline recedes as the laboratory rises — same scroll window
  // as labOp so the two pinned layers never compete for the corner.
  const headOp = useTransform(scrollYProgress, [0.74, 0.9], [1, 0.12]);
  const headBlur = useTransform(
    scrollYProgress,
    [0.74, 0.9],
    ["blur(0px)", "blur(6px)"],
  );
  const ledger: { id: string; verdict: string; keep?: boolean }[] = [
    { id: "gen-2606-i1-004", verdict: "REJECT" },
    { id: "gen-2606-i2-001", verdict: "REJECT" },
    { id: "crucible-S1", verdict: "REJECT" },
    { id: "crucible-S5", verdict: "PENDING", keep: true },
  ];
  return (
    <section
      id="distill"
      ref={wrapRef}
      className="relative h-[340vh] bg-[var(--acc-artifact)]"
    >
      {/* nav anchor: jumping to #lab lands where the laboratory has revealed */}
      <div
        id="lab"
        aria-hidden
        className="absolute left-0 top-[76%] h-px w-px"
      />
      <div className="sticky top-0 flex h-screen flex-col overflow-hidden">
        <motion.div
          style={{
            opacity: headOp,
            filter: reduceMotion ? undefined : headBlur,
          }}
          className="pointer-events-none absolute left-5 top-8 z-20 max-w-[360px] text-left sm:left-10 sm:top-12"
        >
          <p
            className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.3em]"
            style={FIELD_META_STYLE}
          >
            {t(locale, "증류", "the distillation")}
          </p>
          <h2 className="font-serif-display mt-3 text-balance text-[clamp(1.6rem,3.1vw,2.3rem)] font-black leading-[1.22] text-[#FFF0F8]">
            {t(
              locale,
              "천 번의 토큰을 걸러, 한 방울로.",
              "A thousand tokens, filtered to a single drop.",
            )}
          </h2>
        </motion.div>

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
              <span
                className="font-semibold uppercase tracking-[0.24em]"
                style={FIELD_META_STYLE}
              >
                baseline ledger
              </span>
              {ledger.map((row) => (
                <span
                  key={row.id}
                  className={`text-[#7F1747] ${row.keep ? "font-semibold" : ""}`}
                >
                  {row.id} · {row.verdict}
                </span>
              ))}
            </div>
            <p className="mt-4 text-center font-serif-display text-[15px] font-semibold leading-[1.6] text-[#FFF0F8]">
              {t(
                locale,
                "첫 방울은 아직 매달려 있습니다. 기록은 그 무게까지 답니다.",
                "The first drop is still forming. The ledger weighs even that.",
              )}
            </p>
          </motion.div>
        </div>

        {/* final act: white enters — the rose field becomes a specimen slide on a paper stage */}
        <motion.div
          style={{ opacity: labOp, pointerEvents: labPointer }}
          className="absolute inset-0 bg-[#FFF0F8]"
        >
          <div className="absolute inset-x-2 bottom-12 top-2 bg-[var(--acc-artifact)] sm:inset-x-3 sm:top-3" />
          {/* ghost distillate: replicates the visible act's column layout so the
              crossfade keeps the word at identical coordinates — keep the
              invisible spacers in sync with the markup above */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 flex flex-col overflow-hidden"
          >
            <div className="min-h-0 flex-1" />
            <div className="flex flex-col items-center pb-8">
              <p className="font-pixel w-full whitespace-nowrap text-center text-[24vw] font-bold leading-[0.82] text-[#FFF0F8] opacity-[0.16]">
                GEODE
              </p>
              <div className="invisible mt-6 w-full max-w-3xl border-t px-6 pt-4">
                <div className="flex flex-wrap items-baseline justify-center gap-x-7 gap-y-2 font-mono text-[11.5px]">
                  <span className="uppercase tracking-[0.24em]">
                    baseline ledger
                  </span>
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
                    "The first drop is still forming. The ledger weighs even that.",
                  )}
                </p>
              </div>
            </div>
          </div>
          <div className="absolute inset-x-2 bottom-12 top-2 sm:inset-x-3 sm:top-3">
            <div className="relative z-10 mx-auto flex h-full max-w-5xl flex-col items-center justify-center gap-7 px-6 text-center">
              <div>
                <p
                  className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.42em]"
                  style={FIELD_META_STYLE}
                >
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
                {t(
                  locale,
                  "실패를 기록하고, 스스로를 고쳐 씁니다.",
                  "It records its failures, and rewrites itself.",
                )}
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
                  className="font-mono text-[13px] text-[#7F1747] underline decoration-[color-mix(in_srgb,#7F1747_45%,transparent)] underline-offset-4 transition-colors hover:text-[#5F1034]"
                >
                  {t(locale, "전체 기록 보기", "View the full record")}
                </a>
              </div>
              <div className="mt-6 flex flex-col items-center gap-2.5">
                <p
                  className="font-mono text-[10px] font-semibold uppercase tracking-[0.3em]"
                  style={FIELD_META_STYLE}
                >
                  {t(
                    locale,
                    "실험 기록 · 승격 0회까지 그대로",
                    "experiment records · zero promotions included",
                  )}
                </p>
                <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 font-mono text-[12px]">
                  <a
                    href="/geode/self-improving/"
                    className="text-[#7F1747] underline decoration-[color-mix(in_srgb,#7F1747_45%,transparent)] underline-offset-4 transition-colors hover:text-[#5F1034]"
                  >
                    {t(locale, "self-improving 허브", "self-improving hub")}
                  </a>
                  <a
                    href="/geode/self-improving/petri-bundle/"
                    className="text-[#7F1747] underline decoration-[color-mix(in_srgb,#7F1747_45%,transparent)] underline-offset-4 transition-colors hover:text-[#5F1034]"
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
        <GeodeNav items={navItems} light showLocaleToggle={false} />
        <HeroField />
        <InstallChannels />
        <RunRow />
        <FeaturesGrid />
        <DistillationAct />
      </main>
    </LocaleProvider>
  );
}
