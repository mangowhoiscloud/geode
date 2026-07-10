"use client";

import "@astryxdesign/theme-neutral/theme.css";
import "@astryxdesign/core/astryx.css";
import "./astryx-geode.css";

import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Token } from "@astryxdesign/core/Token";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";

import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { LocaleProvider, t, useLocale } from "@/components/geode/locale-context";
import { ScrollReveal } from "@/components/geode/scroll-reveal";
import { GeodeFooter } from "@/components/geode/sections/footer";
import { GeodeNav } from "@/components/geode/sections/nav";
import { BENCHMARK_GROUPS } from "@/data/geode/benchmark-measurements";
import { GEODE_SOT } from "@/data/geode/sot";
import { geodeTechCategories } from "@/data/geode/tech-stack";
import { galmuri } from "@/fonts/galmuri";

import { eras, firstRelease, latestRelease, peakWeek, releaseCount, weeklyCadence } from "./growth";

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
  { id: "hero", label: "Character" },
  { id: "sheet", label: "Sheet" },
  { id: "demo", label: "Demo" },
  { id: "loop", label: "Loop" },
  { id: "growth", label: "Growth" },
  { id: "evolve", label: "Self-evolving" },
];

const surfaceChips = ["CLI", "MCP server", "Slack", "cron", "Gateway daemon"];

const videoTabs = [
  {
    id: "demo-run",
    labelKo: "에이전트 데모",
    labelEn: "Agent demo",
    src: "https://www.youtube.com/embed/1IftYShGxak",
    title: "GEODE Agent Demo",
  },
  {
    id: "computer-use",
    labelKo: "Computer-use",
    labelEn: "Computer-use",
    src: "https://www.youtube.com/embed/BKg3D6pXwss",
    title: "GEODE Computer-use Demo",
  },
  {
    id: "intro",
    labelKo: "소개 · 구조 · 발전사",
    labelEn: "Intro · architecture · history",
    src: "https://www.youtube.com/embed/Qt3jsR5zOcQ",
    title: "GEODE Introduction",
  },
];

const loopPhases: [string, string, string][] = [
  [
    "Perceive",
    "사용자 입력, 세션 상태, 모델과 도구 가시성, 메모리 컨텍스트를 조립합니다.",
    "Assembles user input, session state, model and tool visibility, and memory context.",
  ],
  [
    "Plan",
    "복합 요청은 sub-goal로 분해하고, 활성 Plan을 프롬프트 블록으로 주입합니다.",
    "Decomposes compound requests into sub-goals and injects the active Plan as a prompt block.",
  ],
  [
    "Act",
    "모델이 tool_use를 내면 내장 도구와 MCP 도구를 같은 표면에서 실행합니다.",
    "When the model emits tool_use, built-in and MCP tools run on the same surface.",
  ],
  [
    "Observe",
    "도구 결과, transcript, 비용을 세션 상태에 적재합니다.",
    "Loads tool results, the transcript, and cost into session state.",
  ],
  [
    "Verify",
    "턴 경계에서 verifier가 실패 이유와 retry 신호를 기계가 읽을 수 있게 남깁니다.",
    "At turn boundaries a verifier records failure reasons and retry signals machine-readably.",
  ],
  [
    "Replan",
    "verify 실패, cadence, 낮은 confidence가 트리거가 되면 새 plan revision을 설치합니다.",
    "Verify failures, cadence, or low confidence trigger a fresh plan revision.",
  ],
  [
    "Stop",
    "round, time, cost 예산과 convergence, handoff 임계에서 루프를 닫습니다.",
    "Closes on round, time, and cost budgets, convergence, or the handoff threshold.",
  ],
];

const MONTH_LABELS: Record<string, string> = {
  "03": "Mar",
  "04": "Apr",
  "05": "May",
  "06": "Jun",
  "07": "Jul",
  "08": "Aug",
};

function SectionHeader({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <>
      <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--acc-aqua)]">{eyebrow}</p>
      <h2 className="font-pixel max-w-3xl text-[26px] leading-[1.35] text-[var(--ink-1)] sm:text-[30px]">{title}</h2>
    </>
  );
}

/* ---------------- hero: terminal product moment -------------------------- */

function TerminalMock() {
  const locale = useLocale();
  return (
    <figure className="mx-auto mt-14 w-full max-w-2xl">
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
            <GeodiSprite scale={5} blink className="geodi-bob shrink-0" />
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
      <figcaption className="mt-3 text-center font-mono text-[10.5px] text-[var(--acc-aqua)]">
        core/ui/mascot.py · geodi_art.py{" "}
        <span className="text-[var(--ink-3)]">
          {t(locale, "CLI 웰컴 스크린을 그대로 옮긴 화면", "the CLI welcome screen, transcribed")}
        </span>
      </figcaption>
    </figure>
  );
}

function HeroSection() {
  const locale = useLocale();
  return (
    <section id="hero" className="border-b border-[var(--rule)]">
      <div className="rose-grid mx-auto max-w-6xl px-4 pb-20 pt-20 text-center sm:px-6 lg:pt-28">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          GEODE / {t(locale, "성장 로그", "growth log")}
        </p>
        <h1 className="font-pixel mt-8 text-[clamp(3rem,9vw,5.5rem)] font-bold leading-none text-[var(--acc-artifact)]">
          GEODE
        </h1>
        <p className="font-pixel mx-auto mt-6 max-w-2xl text-[clamp(1.05rem,2.4vw,1.45rem)] leading-[1.6] text-[var(--ink-1)]">
          {t(
            locale,
            "일을 맡기면 끝까지 실행하고, 스스로를 고쳐 쓰는 자율 에이전트.",
            "An autonomous agent that executes to completion and rewrites itself."
          )}
        </p>
        <p className="mx-auto mt-6 max-w-xl text-[15px] leading-[1.75] text-[var(--ink-2)]">
          {t(
            locale,
            `${firstRelease.date} v${firstRelease.version}에서 부화해 ${releaseCount}번의 릴리스를 지나 v${latestRelease.version}까지 왔습니다. 이 페이지는 그 성장 기록이고, 아래 터미널의 도트 캐릭터는 실제 CLI가 그리는 스프라이트입니다.`,
            `Hatched at v${firstRelease.version} on ${firstRelease.date}, grown through ${releaseCount} releases to v${latestRelease.version}. This page is that growth record, and the pixel character in the terminal below is the sprite the real CLI draws.`
          )}
        </p>

        <div className="mt-9 flex flex-wrap items-center justify-center gap-x-6 gap-y-3">
          <Link
            href="/docs"
            className="inline-flex items-center rounded bg-[var(--acc-artifact)] px-5 py-2.5 text-[14px] font-medium text-[var(--paper)] transition-colors hover:bg-[var(--acc-soft)]"
          >
            {t(locale, "문서 읽기", "Read the docs")}
          </Link>
          <Link
            href="https://github.com/mangowhoiscloud/geode"
            target="_blank"
            className="font-mono text-[13px] text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]"
          >
            GitHub
          </Link>
        </div>

        <TerminalMock />

        <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
          {surfaceChips.map((chip) => (
            <span
              key={chip}
              className="rounded border border-[var(--rule)] px-2.5 py-1 font-mono text-[11.5px] text-[var(--ink-2)]"
            >
              {chip}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------- bento: character sheet + bench + stack ----------------- */

function CharacterCard() {
  const locale = useLocale();
  return (
    <aside className="flex h-full flex-col rounded-lg border border-[var(--rule)] bg-[var(--paper-2)]">
      <div className="flex items-center justify-between border-b border-[var(--rule-soft)] px-5 py-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          {t(locale, "캐릭터 시트", "character sheet")}
        </span>
        <Token label={`v${GEODE_SOT.version}`} size="sm" />
      </div>

      <div className="rose-grid flex flex-col items-center px-5 pb-4 pt-8">
        <GeodiSprite scale={8} blink />
        <p className="mt-4 font-mono text-[10.5px] text-[var(--acc-aqua)]">
          core/ui/geodi_art.py · GEODI_PIXELS 22x12
        </p>
      </div>

      <div className="flex grow flex-col px-5 pb-5">
        <MetadataList columns="single">
          <MetadataListItem label={t(locale, "이름", "Name")}>Geodi</MetadataListItem>
          <MetadataListItem label={t(locale, "클래스", "Class")}>
            {t(locale, "자율 실행 하네스", "autonomous execution harness")}
          </MetadataListItem>
          <MetadataListItem label={t(locale, "부화", "Hatched")}>
            {firstRelease.date} (v{firstRelease.version})
          </MetadataListItem>
          <MetadataListItem label={t(locale, "레벨", "Level")}>
            v{latestRelease.version} · {t(locale, `${releaseCount}번째 릴리스`, `release #${releaseCount}`)}
          </MetadataListItem>
          <MetadataListItem label={t(locale, "본체", "Body")}>while(tool_use) AgenticLoop</MetadataListItem>
          <MetadataListItem label={t(locale, "서식지", "Habitat")}>CLI · MCP · Slack · cron</MetadataListItem>
          <MetadataListItem label={t(locale, "기록", "Record")}>
            {/* measured 2026-07-10: find core|plugins -name '*.py' / pytest --co */}
            {t(locale, "492 모듈 · 9,479 테스트", "492 modules · 9,479 tests")}
          </MetadataListItem>
        </MetadataList>

        <div className="mt-auto border-t border-[var(--rule-soft)] pt-4">
          <ProgressBar
            label={t(locale, "EXP · v1.0.0까지", "EXP · toward v1.0.0")}
            value={99}
            max={100}
            hasValueLabel
          />
          <p className="mt-2 font-mono text-[10.5px] text-[var(--ink-3)]">
            {t(
              locale,
              "v1.0 기능 게이트 정리 완료, 릴리스 컷 대기",
              "v1.0 feature gates cleared, release cut pending"
            )}
          </p>
        </div>
      </div>
    </aside>
  );
}

function BenchCard() {
  const locale = useLocale();
  return (
    <div className="rounded-lg border border-[var(--rule)] bg-[var(--paper-2)]">
      <div className="border-b border-[var(--rule-soft)] px-5 py-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          {t(locale, "벤치 실측", "bench measurements")}
        </span>
      </div>
      <div className="px-5 py-4">
        {BENCHMARK_GROUPS.map((group) => (
          <div key={group.id} className="border-b border-[var(--rule-soft)] py-3 first:pt-0 last:border-b-0 last:pb-0">
            <h3 className="font-pixel text-[15px] text-[var(--ink-1)]">{group.title}</h3>
            <div className="mt-2 space-y-1.5">
              {group.matrix.map((cell) => (
                <div key={cell.label} className="grid grid-cols-[96px_72px_1fr] items-baseline gap-2">
                  <span className="font-mono text-[12px] text-[var(--ink-2)]">{cell.label}</span>
                  <span className="font-mono text-[13px] text-[var(--acc-line)]">{cell.value}</span>
                  <span className="truncate font-mono text-[10.5px] text-[var(--ink-3)]" title={cell.note}>
                    {cell.note ?? ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
        <p className="mt-3 font-mono text-[10.5px] leading-relaxed text-[var(--ink-3)]">
          {t(
            locale,
            "tau2 base run은 native user_simulator 기준이고 Mock은 배선 스모크입니다. 리더보드 수치와 평균 내지 않습니다.",
            "tau2 base runs use the native user_simulator; Mock is a wiring smoke. Never averaged with leaderboard numbers."
          )}
        </p>
      </div>
    </div>
  );
}

function StackCard() {
  const locale = useLocale();
  return (
    <div className="rounded-lg border border-[var(--rule)] bg-[var(--paper-2)]">
      <div className="border-b border-[var(--rule-soft)] px-5 py-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          {t(locale, "기술 스택", "tech stack")}
        </span>
      </div>
      <div className="px-5 py-4">
        {geodeTechCategories.map((category) => (
          <div
            key={category.title}
            className="grid grid-cols-[96px_1fr] gap-2 border-b border-[var(--rule-soft)] py-2.5 first:pt-0 last:border-b-0 last:pb-0"
          >
            <span className="pt-1 font-mono text-[11px] uppercase tracking-[0.1em] text-[var(--ink-3)]">
              {category.title}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {category.items.map((item) => (
                <Token key={item} label={item} size="sm" />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SheetSection() {
  const locale = useLocale();
  return (
    <section id="sheet" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
        <SectionHeader
          eyebrow={t(locale, "01 / 시트", "01 / the sheet")}
          title={t(locale, "캐릭터, 지표, 장비", "Character, measurements, equipment")}
        />
        <div className="mt-8 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <ScrollReveal y={24}>
            <CharacterCard />
          </ScrollReveal>
          <div className="flex flex-col gap-4">
            <ScrollReveal y={24} delay={0.08}>
              <BenchCard />
            </ScrollReveal>
            <ScrollReveal y={24} delay={0.16}>
              <StackCard />
            </ScrollReveal>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------------- demo -------------------------------------------------- */

function DemoSection() {
  const locale = useLocale();
  const [activeVideo, setActiveVideo] = useState(videoTabs[0].id);
  const activeTab = videoTabs.find((tab) => tab.id === activeVideo) ?? videoTabs[0];
  return (
    <section id="demo" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6 sm:py-20">
        <SectionHeader
          eyebrow={t(locale, "02 / 실행 화면", "02 / see it run")}
          title={t(locale, "말보다 실행 화면이 빠릅니다", "The run is faster than the pitch")}
        />
        <div className="mt-8">
          <SegmentedControl
            value={activeVideo}
            onChange={setActiveVideo}
            label={t(locale, "데모 영상 선택", "Select demo video")}
            size="sm"
          >
            {videoTabs.map((tab) => (
              <SegmentedControlItem
                key={tab.id}
                value={tab.id}
                label={locale === "en" ? tab.labelEn : tab.labelKo}
              />
            ))}
          </SegmentedControl>
          <div
            className="relative mt-4 overflow-hidden rounded-lg border border-[var(--rule)]"
            style={{ paddingBottom: "56.25%" }}
          >
            <iframe
              className="absolute inset-0 h-full w-full"
              src={activeTab.src}
              title={activeTab.title}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            />
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------------- loop --------------------------------------------------- */

function LoopSection() {
  const locale = useLocale();
  return (
    <section id="loop" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
        <SectionHeader
          eyebrow={t(locale, "03 / 본체", "03 / the body")}
          title={t(
            locale,
            "본체는 도구 호출이 멈출 때까지 도는 루프 하나입니다",
            "The body is one loop that runs until tool calls stop"
          )}
        />
        <div className="mt-8 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <pre className="overflow-x-auto rounded-lg border border-[var(--rule)] bg-[var(--paper-deep)] p-5 font-mono text-[12.5px] leading-[1.8] text-[var(--ink-2)]">
            {`while true:
  check round/time/cost guards
  maybe_replan(verify_fail | cadence)
  assemble_prompt(memory + plan)
  response = call_model(tools)
  if not tool_use: finalize
  observe(execute_tools(response))`}
          </pre>
          <div className="rounded-lg border border-[var(--rule)] bg-[var(--paper-2)]">
            {loopPhases.map(([phase, ko, en]) => (
              <div
                key={phase}
                className="grid gap-1 border-b border-[var(--rule-soft)] px-5 py-3.5 last:border-b-0 sm:grid-cols-[110px_1fr]"
              >
                <p className="font-mono text-[13px] text-[var(--acc-line)]">{phase}</p>
                <p className="text-[13.5px] leading-6 text-[var(--ink-2)]">{t(locale, ko, en)}</p>
              </div>
            ))}
          </div>
        </div>
        <p className="mt-6 max-w-3xl text-[14px] leading-[1.75] text-[var(--ink-2)]">
          {t(
            locale,
            "서브에이전트, 플랜, 배치는 별도 시스템이 아니라 모두 이 루프의 인스턴스입니다. 가드레일은 프롬프트 문구가 아니라 루프의 탈출 조건으로 존재합니다.",
            "Sub-agents, plans, and batches are not separate systems, each is an instance of this loop. Guardrails exist as the loop's exit conditions, not as prompt wording."
          )}
        </p>
      </div>
    </section>
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
            <rect
              key={bin.start}
              className="cadence-bar"
              x={i * barSlot + 1}
              y={chartHeight - h}
              width={barSlot - 2}
              height={h}
              shapeRendering="crispEdges"
            >
              <title>{`${bin.start} · ${bin.count} releases`}</title>
            </rect>
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

function GrowthSection() {
  const locale = useLocale();
  const weeks = weeklyCadence.length;
  return (
    <section id="growth" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6 sm:py-20">
        <div className="mb-10 flex justify-center">
          <Image
            src="/geode/images/geode-discover.png"
            alt=""
            aria-hidden
            width={52}
            height={52}
            style={{ imageRendering: "pixelated" }}
            className="opacity-80"
          />
        </div>
        <SectionHeader
          eyebrow={t(locale, "04 / 성장 로그", "04 / growth log")}
          title={t(
            locale,
            `${weeks}주, ${releaseCount}번의 릴리스로 자랐습니다`,
            `Grown through ${releaseCount} releases in ${weeks} weeks`
          )}
        />
        <p className="mt-4 max-w-3xl text-[14px] leading-[1.75] text-[var(--ink-2)]">
          {t(
            locale,
            "아래 숫자와 막대는 산문이 아니라 CHANGELOG 실측입니다. 페이지 빌드 시점에 릴리스 기록을 그대로 집계합니다.",
            "The numbers and bars below are not prose, they are measured from the CHANGELOG, aggregated at build time from the release records."
          )}
        </p>

        <ScrollReveal y={24}>
          <div className="mt-8 grid gap-3 border-t border-[var(--rule)] pt-6 sm:grid-cols-3">
            {[
              [String(releaseCount), t(locale, "릴리스", "releases")],
              [firstRelease.date, t(locale, "부화일", "hatch date")],
              [
                String(peakWeek.count),
                t(locale, `최다 주간 릴리스 (${peakWeek.start} 주)`, `peak week (${peakWeek.start})`),
              ],
            ].map(([value, label]) => (
              <div key={label}>
                <p className="font-pixel text-[24px] text-[var(--acc-artifact)]">{value}</p>
                <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--ink-3)]">{label}</p>
              </div>
            ))}
          </div>

          <CadenceChart />
        </ScrollReveal>

        <div className="mt-14">
          {eras.map((era, index) => (
            <ScrollReveal key={era.id} y={28} delay={index * 0.04}>
              <article className="grid gap-4 border-t border-[var(--rule-soft)] py-8 first:border-t-[var(--rule)] sm:grid-cols-[72px_1fr]">
                <div className="flex flex-row items-center gap-3 sm:flex-col sm:items-start sm:gap-2">
                  <Image
                    src={`/geode/images/geode-${era.pose}.png`}
                    alt={`Geodi ${era.pose} pose`}
                    width={44}
                    height={44}
                    style={{ imageRendering: "pixelated" }}
                  />
                  <span className="font-mono text-[11px] text-[var(--ink-3)]">{era.id}</span>
                </div>
                <div>
                  <p className="font-mono text-[11px] tracking-[0.14em] text-[var(--acc-aqua)]">
                    {era.range} <span className="ml-2 text-[var(--ink-3)]">{era.period}</span>
                  </p>
                  <h3 className="font-pixel mt-2 text-[17px] leading-snug text-[var(--ink-1)]">
                    {locale === "en" ? era.titleEn : era.titleKo}
                  </h3>
                  <p className="mt-2 max-w-2xl text-[14px] leading-[1.75] text-[var(--ink-2)]">
                    {locale === "en" ? era.bodyEn : era.bodyKo}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {era.chips.map((chip) => (
                      <Token key={chip.v} size="sm" label={`${chip.v} · ${locale === "en" ? chip.en : chip.ko}`} />
                    ))}
                  </div>
                </div>
              </article>
            </ScrollReveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------- self-evolving ------------------------------------------ */

function EvolveSection() {
  const locale = useLocale();
  return (
    <section id="evolve" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6 sm:py-20">
        <SectionHeader
          eyebrow={t(locale, "05 / 자기개선", "05 / self-evolving")}
          title={t(locale, "다음 레벨은 스스로 오릅니다", "It levels itself up")}
        />
        <div className="mt-6 max-w-3xl space-y-3 text-[15px] leading-[1.75] text-[var(--ink-2)]">
          <p>
            {t(
              locale,
              "GEODE는 모델 가중치를 학습시키지 않습니다. 대신 자신을 둘러싼 스캐폴드, 곧 시스템 프롬프트와 도구 정책을 변이시키고, 적대적 안전 감사(Petri)를 fitness로 삼아 측정합니다. critical 안전 축이 한 번이라도 후퇴하면 그 변이는 승격되지 않습니다.",
              "GEODE never trains model weights. It mutates the scaffold around itself, the system prompt and tool policy, and measures each mutation with an adversarial safety audit (Petri) as the fitness signal. A mutation that regresses any critical safety axis is never promoted."
            )}
          </p>
          <p>
            {t(
              locale,
              "시트의 Tau2 실측이 그 다음 단계입니다. 안전 축에서 검증한 promotion protocol을 능력 축으로 복제하는 Crucible 루프가 tau2-bench 위에서 돌고 있습니다.",
              "The tau2 measurements in the sheet are the next step. Crucible, the loop that clones the safety-proven promotion protocol onto the capability axis, runs on tau2-bench."
            )}
          </p>
        </div>
        <div className="mt-6 flex flex-wrap gap-2">
          {["core/self_improving/train.py", "core/self_improving/measure.py", "core/self_improving/gate.py"].map(
            (path) => (
              <code
                key={path}
                className="rounded bg-[var(--paper-deep)] px-1.5 py-0.5 font-mono text-[12px] text-[var(--acc-aqua)]"
              >
                {path}
              </code>
            )
          )}
        </div>
        <div className="mt-10 flex flex-wrap gap-x-6 gap-y-2 border-t border-[var(--rule)] pt-6 font-mono text-[13px]">
          <Link href="/docs" className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]">
            {t(locale, "문서 전체", "full docs")}
          </Link>
          <a
            href="/geode/petri-bundle/landing.html"
            className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]"
          >
            {t(locale, "감사 로그 허브", "audit log hub")}
          </a>
          <a
            href="https://github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md"
            target="_blank"
            rel="noreferrer"
            className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]"
          >
            {t(locale, "전체 성장 기록", "full growth record")}
          </a>
        </div>
      </div>
    </section>
  );
}

/* ---------------- page ---------------------------------------------------- */

export default function GeodePortfolioPage() {
  return (
    <LocaleProvider>
      <main
        data-astryx-theme="neutral"
        className={`${galmuri.variable} min-h-screen overflow-x-hidden bg-[var(--paper)] text-[var(--ink)]`}
      >
        <GeodeNav items={navItems} />
        <HeroSection />
        <SheetSection />
        <DemoSection />
        <LoopSection />
        <GrowthSection />
        <EvolveSection />
        <GeodeFooter />
      </main>
    </LocaleProvider>
  );
}
