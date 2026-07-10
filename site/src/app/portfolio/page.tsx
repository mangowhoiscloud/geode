"use client";

import "@astryxdesign/theme-neutral/theme.css";
import "@astryxdesign/core/astryx.css";
import "./astryx-geode.css";

import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
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
import { serifDisplay } from "@/fonts/serif";

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
  { id: "why", label: "Why" },
  { id: "sheet", label: "Sheet" },
  { id: "loop", label: "Loop" },
  { id: "growth", label: "Growth" },
  { id: "evolve", label: "Self-evolving" },
];

const surfaceChips = ["CLI", "MCP server", "Slack", "cron", "Gateway daemon"];


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

/** How the loop actually perceives and acts — each row grounded in a module. */
const perceptionActs: { label: string; ko: string; en: string; evidence: string }[] = [
  {
    label: "context",
    ko: "시스템 프롬프트는 캐시되는 <static_context>와 턴마다 새로 조립되는 <dynamic_context> 2층입니다. 현재 시각(프로바이더 게이트), 프로젝트 메모리, 런타임 규칙이 매 턴 주입되고, 프롬프트 캐시 경계가 그 사이에 고정됩니다.",
    en: "The system prompt is two layers: a cached <static_context> and a per-turn <dynamic_context>. Current time (provider-gated), project memory, and runtime rules are injected every turn, with the prompt-cache boundary pinned between the layers.",
    evidence: "core/agent/system_prompt.py",
  },
  {
    label: "documents",
    ko: "로컬 PDF는 임베디드 텍스트 레이어를 먼저 로컬 추출하고, 없으면 프로바이더 PDF API 하나로 파싱해 재사용 가능한 번들로 만듭니다.",
    en: "Local PDFs are ingested by extracting the embedded text layer locally first, falling back to a single provider PDF API, producing a reusable bundle.",
    evidence: "core/tools/document_ingest.py",
  },
  {
    label: "browser",
    ko: "헤드리스가 아니라 운영자의 진짜 Chrome에 CDP로 붙습니다. 실제 프로필과 로그인, 지문이 그대로라 로그인 월과 SPA가 사람에게처럼 동작합니다.",
    en: "Not headless: it attaches to the operator's real Chrome over CDP. The real profile, logins, and fingerprint stay intact, so login walls and SPAs behave as they do for a human.",
    evidence: "core/tools/browser_tools.py",
  },
  {
    label: "desktop",
    ko: "Anthropic과 OpenAI의 computer-use가 같은 로컬 하네스(스크린샷, 클릭, 타이핑)에 위임됩니다. 스크린샷 전에 접근성(AX) 트리로 구조를 읽는 더 싼 1단이 먼저 옵니다.",
    en: "Anthropic's and OpenAI's computer-use both delegate to the same local harness (screenshot, click, type). A cheaper first rung reads the accessibility (AX) tree before any screenshot.",
    evidence: "core/tools/computer_use.py · ui_probe.py",
  },
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
      <h2 className="font-serif-display max-w-3xl text-[27px] font-black leading-[1.35] text-[var(--ink-1)] sm:text-[32px]">{title}</h2>
    </>
  );
}

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

function HeroSection() {
  const locale = useLocale();
  return (
    <section id="hero">
      {/* Rose color field, Hermes split composition: editorial serif statement
          left, white-line engraving of the mascot right, corner stamps. */}
      <div className="relative overflow-hidden bg-[var(--acc-artifact)]">
        <div className="relative z-10 mx-auto max-w-7xl px-5 pt-9 text-center sm:px-8">
          <span className="font-pixel text-[19px] font-bold tracking-[0.06em] text-[var(--paper)]">GEODE</span>
        </div>

        <div className="relative mx-auto grid max-w-7xl items-center gap-6 px-5 pb-24 pt-10 sm:px-8 lg:grid-cols-[1.05fr_0.95fr] lg:pb-28 lg:pt-14">
          <div className="relative z-10">
            <p className="font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,var(--paper)_62%,transparent)]">
              open source · apache-2.0 · {t(locale, "루프 실험실", "the loop laboratory")}
            </p>
            <h1 className="font-serif-display mt-7 text-[clamp(2.5rem,5.8vw,4.4rem)] font-black leading-[1.12] text-[var(--paper)]">
              {t(locale, "일을 맡기면 끝까지.", "Executes to the end.")}
              <br />
              {t(locale, "스스로를 고쳐 쓰는", "The agent that")}
              <br />
              {t(locale, "에이전트.", "rewrites itself.")}
            </h1>

            <p className="mt-10 font-mono text-[10.5px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,var(--paper)_62%,transparent)]">
              run via terminal
            </p>
            <div className="mt-3 inline-block rounded bg-[var(--paper)] px-5 py-3 text-left font-mono text-[12.5px] text-[var(--ink-2)] sm:text-[13.5px]">
              <span className="text-[var(--acc-artifact)]">$</span> uv run geode{" "}
              <span className="text-[var(--code-string)]">
                &quot;{t(locale, "이 레포 점검하고 릴리스 블로커 요약해줘", "inspect this repo and summarize release blockers")}&quot;
              </span>
            </div>

            <div className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-3">
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
            </div>
          </div>

          <div className="relative h-[280px] sm:h-[380px] lg:h-[560px]">
            <Image
              src="/geode/images/geode-etch-line.png"
              alt=""
              aria-hidden
              fill
              priority
              sizes="(min-width: 1024px) 46vw, 100vw"
              className="pointer-events-none select-none object-contain lg:scale-[1.22] lg:object-right"
            />
          </div>
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
        <div className="absolute inset-0 flex items-center justify-center px-4 sm:px-6">
          <TerminalMock />
        </div>
      </div>
    </section>
  );
}

/* ---------------- why: the three selling points -------------------------- */

const whyPoints: {
  id: string;
  titleKo: string;
  titleEn: string;
  bodyKo: string;
  bodyEn: string;
  evidence: string;
}[] = [
  {
    id: "01",
    titleKo: "안전 게이트 뒤의 자기개선",
    titleEn: "Self-improvement behind a safety gate",
    bodyKo:
      "모델 가중치가 아니라 스스로의 스캐폴드(시스템 프롬프트, 도구 정책)를 변이시키고, 적대적 안전 감사(Petri)를 fitness로 잽니다. critical 축이 한 번이라도 후퇴하면 승격 자체가 거부되고, 능력 축은 tau2-bench 위 Crucible이 같은 승격 프로토콜로 검증합니다.",
    bodyEn:
      "It mutates its own scaffold (system prompt, tool policy), never model weights, and measures each mutation with an adversarial safety audit (Petri) as fitness. One critical-axis regression vetoes promotion; on the capability axis, Crucible applies the same promotion protocol on tau2-bench.",
    evidence: "core/self_improving/gate.py",
  },
  {
    id: "02",
    titleKo: "끝까지 실행하는 본체 루프",
    titleEn: "A body loop that executes to the end",
    bodyKo:
      "말로 계획하는 래퍼가 아니라 plan, act, verify, replan을 소유하는 실행 루프입니다. verify 실패는 기계가 읽는 신호로 남아 replan을 트리거하고, round·time·cost 예산이 프롬프트 문구가 아닌 루프의 탈출 조건으로 박혀 있습니다.",
    bodyEn:
      "Not a wrapper that plans in prose: an execution loop that owns plan, act, verify, replan. Verify failures persist as machine-readable signals that trigger replanning, and round, time, and cost budgets are compiled in as the loop's exit conditions, not prompt wording.",
    evidence: "core/agent/loop/",
  },
  {
    id: "03",
    titleKo: "당신의 구독으로 상주",
    titleEn: "Resident, on your subscriptions",
    bodyKo:
      "Anthropic, OpenAI/Codex, GLM 구독을 OAuth로 직접 소유하고 프로바이더 간 격리를 지킵니다. CLI, MCP 서버, Slack, cron으로 상주하고, 데스크톱 computer-use 왕복까지 라이브 E2E로 검증했습니다.",
    bodyEn:
      "It owns Anthropic, OpenAI/Codex, and GLM subscriptions directly over OAuth and keeps providers isolated. It lives in the CLI, as an MCP server, in Slack and cron, with desktop computer-use round-trips verified live end-to-end.",
    evidence: "core/llm/providers/",
  },
];

function WhySection() {
  const locale = useLocale();
  return (
    <section id="why" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <SectionHeader
          eyebrow={t(locale, "01 / 왜 GEODE인가", "01 / why geode")}
          title={t(locale, "성장보다 먼저, 무엇이 다른가", "Before the growth, what is different")}
        />
        <div className="mt-8 grid gap-x-8 gap-y-8 border-t border-[var(--rule)] pt-8 md:grid-cols-3">
          {whyPoints.map((point) => (
            <div key={point.id}>
              <p className="font-mono text-[11px] text-[var(--ink-3)]">{point.id}</p>
              <h3 className="font-serif-display mt-2 text-[19px] font-semibold leading-snug text-[var(--ink-1)]">
                {locale === "en" ? point.titleEn : point.titleKo}
              </h3>
              <p className="mt-3 text-[13.5px] leading-[1.75] text-[var(--ink-2)]">
                {locale === "en" ? point.bodyEn : point.bodyKo}
              </p>
              <code className="mt-3 inline-block rounded bg-[var(--paper-deep)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--acc-aqua)]">
                {point.evidence}
              </code>
            </div>
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
        <PlayfulSprite scale={8} blink />
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
          <MetadataListItem label={"Birth"}>
            {firstRelease.date} (v{firstRelease.version})
          </MetadataListItem>
          <MetadataListItem label={t(locale, "레벨", "Level")}>
            v{latestRelease.version} · {t(locale, `${releaseCount}번째 릴리스`, `release #${releaseCount}`)}
          </MetadataListItem>
          <MetadataListItem label={t(locale, "본체", "Body")}>while(tool_use) AgenticLoop</MetadataListItem>
          <MetadataListItem label={t(locale, "서식지", "Habitat")}>CLI · MCP · Slack · cron</MetadataListItem>
          <MetadataListItem label={t(locale, "프로바이더", "Providers")}>
            Anthropic · OpenAI / Codex · GLM
          </MetadataListItem>
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

/** "0.763" -> 0.763, "100.0% (10/10)" -> 1.0, "blocked" -> null. */
function benchRatio(value: string): number | null {
  const numeric = parseFloat(value);
  if (Number.isNaN(numeric)) return null;
  const ratio = value.includes("%") ? numeric / 100 : numeric;
  return ratio >= 0 && ratio <= 1 ? ratio : null;
}

/** Distinct model · provider · source routes behind a bench group's numbers. */
function groupRoutes(group: (typeof BENCHMARK_GROUPS)[number]): string {
  const routes = new Set(group.measurements.map((m) => `${m.model} · ${m.provider} · ${m.source}`));
  return [...routes].join("  /  ");
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
            <p className="mt-0.5 font-mono text-[10px] text-[var(--ink-3)]">{groupRoutes(group)}</p>
            <div className="mt-2 space-y-1.5">
              {group.matrix.map((cell) => {
                const ratio = benchRatio(cell.value);
                return (
                  <div key={cell.label} className="grid grid-cols-[88px_56px_56px_1fr] items-center gap-2">
                    <span className="font-mono text-[12px] text-[var(--ink-2)]">{cell.label}</span>
                    <span className="font-mono text-[12.5px] text-[var(--acc-line)]">{cell.value.split(" ")[0]}</span>
                    {ratio === null ? (
                      <span />
                    ) : (
                      <span className="h-[7px] w-full bg-[var(--rule-soft)]">
                        <span
                          className="block h-full bg-[var(--acc-artifact)] opacity-80"
                          style={{ width: `${Math.round(ratio * 100)}%` }}
                        />
                      </span>
                    )}
                    <span className="truncate font-mono text-[10.5px] text-[var(--ink-3)]" title={cell.note}>
                      {cell.note ?? ""}
                    </span>
                  </div>
                );
              })}
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
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <SectionHeader
          eyebrow={t(locale, "02 / 시트", "02 / the sheet")}
          title={t(locale, "캐릭터, 지표, 도구", "Character, measurements, tools")}
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

/* ---------------- loop --------------------------------------------------- */

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

function LoopSection() {
  const locale = useLocale();
  return (
    <section id="loop" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <SectionHeader
          eyebrow={t(locale, "03 / 본체", "03 / the body")}
          title={t(
            locale,
            "본체는 도구 호출이 멈출 때까지 도는 루프 하나입니다",
            "The body is one loop that runs until tool calls stop"
          )}
        />
        <div className="mt-8 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="flex items-center justify-center rounded-lg border border-[var(--rule)] bg-[var(--paper-deep)] p-5">
            <LoopDiagram />
          </div>
          <div className="border-t border-[var(--rule)]">
            {loopPhases.map(([phase, ko, en]) => (
              <div
                key={phase}
                className="grid gap-1 border-b border-[var(--rule-soft)] py-3.5 sm:grid-cols-[110px_1fr]"
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
            "서브에이전트, 플랜, 배치는 별도 시스템이 아니라 모두 이 루프의 인스턴스입니다. 가드레일은 프롬프트 문구가 아니라 루프의 탈출 조건으로 존재하고, 종료는 명시된 사유 카탈로그의 값으로만 끝납니다.",
            "Sub-agents, plans, and batches are not separate systems, each is an instance of this loop. Guardrails exist as the loop's exit conditions, not as prompt wording, and every termination ends with a value from an explicit reason catalog."
          )}
        </p>

        <div className="mt-10">
          <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
            {t(locale, "지각과 행동, 실제 구현", "perception and action, as implemented")}
          </p>
          <div className="border-t border-[var(--rule)]">
            {perceptionActs.map((row) => (
              <div
                key={row.label}
                className="grid gap-2 border-b border-[var(--rule-soft)] py-4 lg:grid-cols-[110px_1fr_auto]"
              >
                <p className="font-mono text-[12.5px] text-[var(--acc-aqua)]">{row.label}</p>
                <p className="text-[13.5px] leading-[1.7] text-[var(--ink-2)]">{t(locale, row.ko, row.en)}</p>
                <code className="self-start rounded bg-[var(--paper-deep)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--ink-3)]">
                  {row.evidence}
                </code>
              </div>
            ))}
          </div>
        </div>
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

/** Portal-style chapter break: ghost type, the specimen dish, corner stamps. */
function ChapterBand() {
  const locale = useLocale();
  return (
    <div className="relative overflow-hidden bg-[var(--acc-artifact)]">
      <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <span className="font-pixel select-none text-[26vw] font-bold leading-none text-[var(--paper)] opacity-[0.06]">
          GEODE
        </span>
      </div>
      <div className="relative z-10 mx-auto flex max-w-6xl flex-col items-center gap-8 px-6 py-24 text-center sm:py-28">
        <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-[color-mix(in_srgb,var(--paper)_65%,transparent)]">
          plan · act · observe · verify · replan
        </p>
        <h2 className="font-serif-display text-[clamp(2.2rem,5.5vw,3.8rem)] font-black leading-[1.15] text-[var(--paper)]">
          {t(locale, "루프 실험실", "The Loop Laboratory")}
        </h2>
        {/* the specimen dish — Petri, literally */}
        <div className="flex h-44 w-44 items-center justify-center rounded-full border-2 border-[var(--paper)] sm:h-52 sm:w-52">
          <GeodiSprite scale={5} silhouette="var(--paper)" />
        </div>
        <p className="font-serif-display max-w-xl text-[clamp(1.05rem,2.4vw,1.4rem)] font-semibold leading-[1.6] text-[var(--paper)]">
          {t(
            locale,
            "실패를 기록하고, 스스로를 고쳐 씁니다.",
            "It records its failures, and rewrites itself."
          )}
        </p>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between px-5 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-[color-mix(in_srgb,var(--paper)_55%,transparent)] sm:px-8">
        <span>specimen · geodi</span>
        <span>petri audit attached</span>
      </div>
    </div>
  );
}

function GrowthSection() {
  const locale = useLocale();
  const weeks = weeklyCadence.length;
  return (
    <section id="growth" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-4xl px-4 py-20 sm:px-6 sm:py-28">
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
              [firstRelease.date, "Birth"],
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
              <article
                className={`grid gap-4 border-t border-[var(--rule-soft)] py-8 first:border-t-[var(--rule)] sm:grid-cols-[72px_1fr] ${era.open ? "opacity-60" : ""}`}
              >
                <div className="flex flex-row items-center gap-3 sm:flex-col sm:items-start sm:gap-2">
                  <Image
                    src={`/geode/images/geode-${era.pose}.png`}
                    alt={`Geodi ${era.pose} pose`}
                    width={44}
                    height={44}
                    style={{ imageRendering: "pixelated", opacity: era.open ? 0.5 : 1 }}
                  />
                  <span className="font-mono text-[11px] text-[var(--ink-3)]">{era.id}</span>
                </div>
                <div>
                  <p className="font-mono text-[11px] tracking-[0.14em] text-[var(--acc-aqua)]">
                    {era.range} <span className="ml-2 text-[var(--ink-3)]">{era.period}</span>
                  </p>
                  <h3 className="font-serif-display mt-2 text-[18px] font-semibold leading-snug text-[var(--ink-1)]">
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

/** Honest attempt history — anchored to CHANGELOG / campaign records. */
const evolveLog: { date: string; ko: string; en: string }[] = [
  {
    date: "2026-05-11",
    ko: "Petri 감사 배선 완료 (v0.90-93). 자기 자신을 실험 대상으로 올렸습니다.",
    en: "Petri audit wired in (v0.90-93). GEODE became its own test subject.",
  },
  {
    date: "2026-06-03",
    ko: "seed generation 생존자 선택이 Elo + 난이도 블렌드로 (v0.99.127).",
    en: "Seed-generation survivor selection moved to an Elo + difficulty blend (v0.99.127).",
  },
  {
    date: "2026-06",
    ko: "안전 축 캠페인 결과: 인프라는 검증됐지만 robust한 자기개선은 없었습니다. 0 승격의 원인은 지표 포화(margin floor가 noise의 19배)로 규명됐습니다.",
    en: "Safety-axis campaign result: the infrastructure held, but no robust self-improvement. The zero-promotion outcome was traced to metric saturation (margin floor at 19x noise).",
  },
  {
    date: "2026-07-06",
    ko: "Crucible 1차 사이클 (v0.99.279): 자기개선 입증 실패, 대신 승격 프로토콜을 입증. 변이 S1은 풀 페어드 런에서 기각, S5는 보류. 병목은 검증 처리량으로 판명됐습니다.",
    en: "Crucible first cycle (v0.99.279): it did not prove self-improvement; it proved the promotion protocol. Mutation S1 was rejected on a full paired run, S5 is pending. The limiting reagent is verification throughput.",
  },
];

function EvolveSection() {
  const locale = useLocale();
  return (
    <section id="evolve" className="border-b border-[var(--rule)]">
      <div className="mx-auto max-w-4xl px-4 py-20 sm:px-6 sm:py-28">
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
        <div className="mt-10 space-y-14">
          <div className="grid items-center gap-8 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="flex justify-center rounded-lg border border-[var(--rule)] bg-[var(--paper-deep)] p-6">
              <AuditGateDiagram />
            </div>
            <div>
              <h3 className="font-serif-display text-[19px] font-semibold leading-snug text-[var(--ink-1)]">
                {t(locale, "감사가 곧 게이트입니다", "The audit is the gate")}
              </h3>
              <p className="mt-3 text-[13.5px] leading-[1.75] text-[var(--ink-2)]">
                {t(
                  locale,
                  "scaffold 변이는 부착된 적대적 감사(Petri)를 통과해야 합니다. 감사자가 GEODE를 다차원 rubric으로 몰아붙이고, critical 축이 하한선을 한 번이라도 넘으면 그 변이는 기각됩니다. gate, random, never 세 promote arm이 선택 효과와 드리프트를 분리하고, 모든 감사 로그는 inspect 뷰어로 공개됩니다.",
                  "A scaffold mutation must survive the attached adversarial audit (Petri). The auditor presses GEODE across a multi-dimension rubric; a single critical-floor breach rejects the mutation. Three promote arms (gate, random, never) separate selection effect from drift, and every audit log is published through the inspect viewer."
                )}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {["core/self_improving/gate.py", "core/audit/"].map((path) => (
                  <code key={path} className="rounded bg-[var(--paper-deep)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--acc-aqua)]">
                    {path}
                  </code>
                ))}
              </div>
            </div>
          </div>

          <div className="grid items-center gap-8 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="order-2 lg:order-1">
              <h3 className="font-serif-display text-[19px] font-semibold leading-snug text-[var(--ink-1)]">
                {t(locale, "가설은 공장에서 옵니다", "Hypotheses come from a factory")}
              </h3>
              <p className="mt-3 text-[13.5px] leading-[1.75] text-[var(--ink-2)]">
                {t(
                  locale,
                  "무엇을 시험할지도 스스로 만듭니다. generator가 적대적 시드 시나리오를 뿌리면 critic, pilot, ranker가 단계마다 후보를 걸러내고, evolver가 생존자를 변주합니다. 생존자 선택은 Elo와 난이도의 블렌드이고, 평가 시드 풀은 고정되어 있지 않고 에이전트와 나란히 자랍니다.",
                  "It also manufactures what to test. The generator seeds adversarial scenarios; critic, pilot, and ranker cull candidates at every stage; the evolver mutates the survivors. Selection blends Elo with difficulty, and the evaluation pool is not frozen; it grows alongside the agent."
                )}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <code className="rounded bg-[var(--paper-deep)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--acc-aqua)]">
                  plugins/seed_generation/
                </code>
              </div>
            </div>
            <div className="order-1 flex justify-center rounded-lg border border-[var(--rule)] bg-[var(--paper-deep)] p-6 lg:order-2">
              <SeedgenDiagram />
            </div>
          </div>
        </div>

        <div className="mt-10">
          <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
            {t(locale, "시도 이력, 결과 그대로", "attempt history, results as-is")}
          </p>
          <div className="border-t border-[var(--rule)]">
            {evolveLog.map((entry) => (
              <div
                key={entry.date}
                className="grid gap-2 border-b border-[var(--rule-soft)] py-3.5 sm:grid-cols-[110px_1fr]"
              >
                <p className="font-mono text-[12px] text-[var(--ink-3)]">{entry.date}</p>
                <p className="text-[13.5px] leading-[1.7] text-[var(--ink-2)]">{t(locale, entry.ko, entry.en)}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 max-w-3xl text-[13px] leading-[1.7] text-[var(--ink-3)]">
            {t(
              locale,
              "실패한 시도를 지우지 않습니다. 무엇이 안 됐고 왜 안 됐는지가 이 루프의 실측 자산입니다.",
              "Failed attempts are not erased. What did not work, and why, is this loop's measured asset."
            )}
          </p>
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
        className={`${galmuri.variable} ${serifDisplay.variable} min-h-screen overflow-x-hidden bg-[var(--paper)] text-[var(--ink)]`}
      >
        <GeodeNav items={navItems} />
        <HeroSection />
        <WhySection />
        <SheetSection />
        <LoopSection />
        <ChapterBand />
        <GrowthSection />
        <EvolveSection />
        <GeodeFooter />
      </main>
    </LocaleProvider>
  );
}
