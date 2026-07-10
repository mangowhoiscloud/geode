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
import { GeodeFooter } from "@/components/geode/sections/footer";
import { GeodeNav } from "@/components/geode/sections/nav";
import { GEODE_SOT } from "@/data/geode/sot";

import { eras, firstRelease, latestRelease, peakWeek, releaseCount, weeklyCadence } from "./growth";

/**
 * GEODE portfolio v10 — growth log.
 *
 * The page reads like the agent's character sheet: the pixel mascot the CLI
 * actually draws (core/ui/geodi_art.py::GEODI_PIXELS), the concept in one
 * loop, and the growth measured from the synced CHANGELOG (426+ releases).
 * Component foundation: Astryx (@astryxdesign/core) themed onto the GEODE
 * Axolotl Rose tokens via ./astryx-geode.css. Prior version archived at
 * versions/v9.
 */

const navItems = [
  { id: "hero", label: "Character" },
  { id: "demo", label: "Demo" },
  { id: "loop", label: "Loop" },
  { id: "growth", label: "Growth" },
  { id: "evolve", label: "Self-evolving" },
];

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
      <h2 className="max-w-3xl text-3xl font-semibold text-[var(--ink-1)] sm:text-4xl">{title}</h2>
    </>
  );
}

/* ---------------- hero: character card --------------------------------- */

function CharacterCard() {
  const locale = useLocale();
  return (
    <aside className="rounded-lg border border-[var(--rule)] bg-[var(--paper-2)]">
      <div className="flex items-center justify-between border-b border-[var(--rule-soft)] px-5 py-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          {t(locale, "캐릭터 시트", "character sheet")}
        </span>
        <Token label={`v${GEODE_SOT.version}`} size="sm" />
      </div>

      <div className="rose-grid flex flex-col items-center px-5 pb-4 pt-8">
        <GeodiSprite scale={9} blink />
        <p className="mt-4 font-mono text-[10.5px] text-[var(--acc-aqua)]">
          core/ui/geodi_art.py · GEODI_PIXELS 22x12
        </p>
        <p className="mt-1 font-mono text-[10.5px] text-[var(--ink-3)]">
          {t(
            locale,
            "CLI 웰컴 스크린이 그리는 스프라이트와 같은 픽셀 데이터",
            "the same pixel data the CLI welcome screen draws"
          )}
        </p>
      </div>

      <div className="px-5 pb-5">
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

        <div className="mt-5 border-t border-[var(--rule-soft)] pt-4">
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

function HeroSection() {
  const locale = useLocale();
  return (
    <section id="hero" className="border-b border-[var(--rule)]">
      <div className="mx-auto grid max-w-6xl gap-12 px-4 pb-16 pt-16 sm:px-6 lg:grid-cols-[1.1fr_0.9fr] lg:pb-20 lg:pt-24">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
            GEODE / {t(locale, "성장 로그", "growth log")}
          </p>
          <h1 className="mt-6 font-display text-[clamp(3rem,8vw,5rem)] font-semibold leading-[1.02] tracking-tight text-[var(--ink)]">
            GEODE
          </h1>
          <p className="mt-4 font-display text-[clamp(1.3rem,2.6vw,1.7rem)] leading-snug text-[var(--ink-1)]">
            {t(
              locale,
              "일을 맡기면 끝까지 실행하고, 스스로를 고쳐 쓰는 자율 에이전트.",
              "An autonomous agent that executes to completion and rewrites itself."
            )}
          </p>

          <div className="mt-8 max-w-xl space-y-3 text-[15px] leading-[1.75] text-[var(--ink-2)]">
            <p>
              {t(
                locale,
                `이 페이지는 GEODE의 성장 로그입니다. ${firstRelease.date} v${firstRelease.version}에서 부화해, ${releaseCount}번의 릴리스를 지나 v${latestRelease.version}까지 왔습니다. 무엇을 할 수 있는지는 아래 데모로, 어떻게 자랐는지는 기록으로 보여드립니다.`,
                `This page is GEODE's growth log. It hatched at v${firstRelease.version} on ${firstRelease.date} and has grown through ${releaseCount} releases to v${latestRelease.version}. The demo shows what it does, the log below shows how it grew.`
              )}
            </p>
            <p>
              {t(
                locale,
                "옆의 도트 캐릭터는 장식이 아닙니다. core/ui/geodi_art.py의 픽셀 그리드를 그대로 옮겨 그린, CLI 웰컴 스크린의 그 스프라이트입니다.",
                "The pixel character is not decoration. It is rendered from the same pixel grid in core/ui/geodi_art.py that the CLI welcome screen draws."
              )}
            </p>
          </div>

          <div className="mt-10 rounded-lg border border-[var(--rule)] bg-[var(--code-bg)] px-6 py-5 font-mono text-[14px] leading-loose text-[var(--code-text)]">
            <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
              {t(locale, "한 줄로 실행", "run it")}
            </div>
            <div>
              <span className="font-medium text-[var(--acc-artifact)]">{"▸"}</span>{" "}
              <span className="text-[var(--ink-3)]">uv run geode</span>{" "}
              <span className="text-[var(--code-string)]">
                &quot;inspect this repo and summarize release blockers&quot;
              </span>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
            <Link
              href="/docs"
              className="inline-flex items-center gap-2 rounded bg-[var(--acc-artifact)] px-4 py-2 text-[14px] font-medium text-[var(--paper)] transition-colors hover:bg-[var(--acc-soft)]"
            >
              {t(locale, "문서 읽기", "Read the docs")} {"→"}
            </Link>
            <div className="flex items-center gap-4 font-mono text-[13px]">
              <Link
                href="https://github.com/mangowhoiscloud/geode"
                target="_blank"
                className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]"
              >
                Source
              </Link>
              <Link
                href="https://rooftopsnow.tistory.com/category/Harness"
                target="_blank"
                className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]"
              >
                {t(locale, "개발 블로그", "Dev Blog")}
              </Link>
            </div>
          </div>
        </div>

        <div className="lg:self-center">
          <CharacterCard />
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
          eyebrow={t(locale, "01 / 실행 화면", "01 / see it run")}
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
          eyebrow={t(locale, "02 / 본체", "02 / the body")}
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
        <SectionHeader
          eyebrow={t(locale, "03 / 성장 로그", "03 / growth log")}
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

        <div className="mt-8 grid gap-3 border-t border-[var(--rule)] pt-6 sm:grid-cols-3">
          {[
            [String(releaseCount), t(locale, "릴리스", "releases")],
            [`${firstRelease.date} →`, t(locale, "부화일", "hatch date")],
            [
              String(peakWeek.count),
              t(locale, `최다 주간 릴리스 (${peakWeek.start} 주)`, `peak week (${peakWeek.start})`),
            ],
          ].map(([value, label]) => (
            <div key={label}>
              <p className="font-mono text-2xl text-[var(--acc-artifact)]">{value}</p>
              <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--ink-3)]">{label}</p>
            </div>
          ))}
        </div>

        <CadenceChart />

        <div className="mt-14">
          {eras.map((era) => (
            <article
              key={era.id}
              className="grid gap-4 border-t border-[var(--rule-soft)] py-8 first:border-t-[var(--rule)] sm:grid-cols-[72px_1fr]"
            >
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
                <h3 className="mt-2 text-[17px] font-semibold tracking-tight text-[var(--ink-1)]">
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
          eyebrow={t(locale, "04 / 자기개선", "04 / self-evolving")}
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
              "이 성장 로그의 마지막 막이 진행형인 이유입니다. 사람이 밀어 올린 릴리스 위에, 스스로 검증하고 스스로 승격하는 루프를 얹는 중입니다.",
              "That is why the last era of this growth log is still open. On top of the human-pushed releases, a loop that verifies and promotes itself is being layered in."
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
            {t(locale, "문서 전체", "full docs")} {"→"}
          </Link>
          <a
            href="/geode/petri-bundle/landing.html"
            className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]"
          >
            {t(locale, "감사 로그 허브", "audit log hub")} {"→"}
          </a>
          <a
            href="https://github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md"
            target="_blank"
            rel="noreferrer"
            className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]"
          >
            {t(locale, "전체 성장 기록", "full growth record")} {"→"}
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
        className="min-h-screen overflow-x-hidden bg-[var(--paper)] text-[var(--ink)]"
      >
        <GeodeNav items={navItems} />
        <HeroSection />
        <DemoSection />
        <LoopSection />
        <GrowthSection />
        <EvolveSection />
        <GeodeFooter />
      </main>
    </LocaleProvider>
  );
}
