"use client";

import { useState } from "react";
import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { MarkdownLite } from "@/components/geode-docs/markdown-lite";
import { useLocale, useSetLocale, t } from "@/components/geode/locale-context";
import {
  CHANGELOG,
  CHANGELOG_SYNCED_AT,
  type ChangelogEntry,
} from "@/data/geode/changelog";

// === Helpers =================================================================

function versionAnchor(version: string): string {
  return "v-" + version.toLowerCase().replace(/[^a-z0-9.]/g, "-");
}

function decileOf(version: string): string {
  if (version === "Unreleased") return "Unreleased";
  const m = version.match(/^0\.(\d+)\./);
  if (!m) return "Other";
  return `0.${Math.floor(parseInt(m[1], 10) / 10)}x`;
}

type Scope = "minor" | "patch" | "unreleased";

function scopeOf(version: string): Scope {
  if (version === "Unreleased") return "unreleased";
  const m = version.match(/^\d+\.\d+\.(\d+)/);
  if (!m) return "patch";
  return m[1] === "0" ? "minor" : "patch";
}

type Lang = "ko" | "en";

/**
 * Classify a markdown block as KO / EN / both / neutral.
 * - ko: predominantly Hangul.
 * - en: predominantly Latin alphabet.
 * - both: visible mix; routed to both halves.
 * - neutral: too short or code-only.
 */
function classifyBlock(text: string): "ko" | "en" | "both" | "neutral" {
  const ko = (text.match(/[ㄱ-힝가-힣]/g) || []).length;
  const en = (text.match(/[a-zA-Z]/g) || []).length;
  const tot = ko + en;
  if (tot < 15) return "neutral";
  const ratio = ko / tot;
  if (ratio > 0.35) return "ko";
  if (ratio < 0.04) return "en";
  return "both";
}

/**
 * Split an entry body into KO + EN halves at block level.
 * Code fences and short / symbol-only blocks are duplicated into both halves
 * because they are language-neutral context.
 */
function splitBodyByLanguage(body: string): {
  ko: string;
  en: string;
  hasKo: boolean;
  hasEn: boolean;
} {
  const lines = body.split("\n");
  const blocks: string[] = [];
  let cur: string[] = [];
  let inFence = false;
  for (const line of lines) {
    if (line.startsWith("```")) {
      cur.push(line);
      inFence = !inFence;
      if (!inFence) {
        blocks.push(cur.join("\n"));
        cur = [];
      }
      continue;
    }
    if (inFence) {
      cur.push(line);
      continue;
    }
    if (line.trim() === "") {
      if (cur.length) blocks.push(cur.join("\n"));
      cur = [];
    } else {
      cur.push(line);
    }
  }
  if (cur.length) blocks.push(cur.join("\n"));

  const koBlocks: string[] = [];
  const enBlocks: string[] = [];
  let hasKo = false;
  let hasEn = false;
  for (const b of blocks) {
    const isFence = b.startsWith("```");
    const lang = isFence ? "neutral" : classifyBlock(b);
    if (lang === "ko") {
      koBlocks.push(b);
      hasKo = true;
    } else if (lang === "en") {
      enBlocks.push(b);
      hasEn = true;
    } else if (lang === "both") {
      koBlocks.push(b);
      enBlocks.push(b);
      hasKo = true;
      hasEn = true;
    } else {
      // neutral: live in both halves
      koBlocks.push(b);
      enBlocks.push(b);
    }
  }
  return {
    ko: koBlocks.join("\n\n"),
    en: enBlocks.join("\n\n"),
    hasKo,
    hasEn,
  };
}

function groupByDecile(entries: ChangelogEntry[]) {
  const seenDeciles: string[] = [];
  const byDecile: Record<string, ChangelogEntry[]> = {};
  for (const e of entries) {
    const d = decileOf(e.version);
    if (!byDecile[d]) {
      byDecile[d] = [];
      seenDeciles.push(d);
    }
    byDecile[d].push(e);
  }
  return seenDeciles.map((d) => ({ decile: d, entries: byDecile[d] }));
}

// === UI atoms ================================================================

function ScopeChip({ scope }: { scope: Scope }) {
  const meta = {
    minor: { label: "MINOR", color: "#7BB97B" },
    patch: { label: "PATCH", color: "#7895C2" },
    unreleased: { label: "PENDING", color: "#E89B57" },
  }[scope];
  return (
    <span
      className="inline-flex items-center px-1.5 py-0 rounded text-[9px] font-mono uppercase tracking-wider"
      style={{
        color: meta.color,
        border: `1px solid ${meta.color}40`,
        backgroundColor: `${meta.color}10`,
      }}
    >
      {meta.label}
    </span>
  );
}

/**
 * Per-entry KO / EN toggle. Defaults to the page locale, and only renders
 * when both languages are detected. Buttons disabled when the corresponding
 * language is unavailable.
 */
function LangToggle({
  value,
  onChange,
  hasKo,
  hasEn,
}: {
  value: Lang;
  onChange: (lang: Lang) => void;
  hasKo: boolean;
  hasEn: boolean;
}) {
  const both = hasKo && hasEn;
  if (!both) return null;
  return (
    <div className="inline-flex items-center rounded-md border border-white/[0.10] overflow-hidden text-[10px] font-mono">
      <button
        type="button"
        onClick={() => onChange("ko")}
        className={
          "px-2 py-0.5 transition-colors " +
          (value === "ko"
            ? "bg-[#A573E8]/20 text-[#A573E8]"
            : "text-white/50 hover:text-white")
        }
      >
        KO
      </button>
      <span className="w-px h-3 bg-white/[0.10]" />
      <button
        type="button"
        onClick={() => onChange("en")}
        className={
          "px-2 py-0.5 transition-colors " +
          (value === "en"
            ? "bg-white/[0.15] text-[#F0F0FF]"
            : "text-white/50 hover:text-white")
        }
      >
        EN
      </button>
    </div>
  );
}

/**
 * Stripe-style fallback banner. Surfaces "this entry is only available in
 * <other language>" when the requested language is missing for this entry.
 */
function FallbackBanner({
  desired,
  available,
}: {
  desired: Lang;
  available: Lang;
}) {
  const messages = {
    ko: {
      missingKo: "이 entry는 영어 원문만 작성됐습니다. 한국어 번역 기여 환영.",
      missingEn: "This entry exists only in Korean. EN translation welcome.",
    },
    en: {
      missingKo: "이 entry는 영어 원문만 작성됐습니다. 한국어 번역 기여 환영.",
      missingEn: "This entry exists only in Korean. EN translation welcome.",
    },
  };
  const text =
    desired === "ko" && available === "en"
      ? messages.ko.missingKo
      : messages.en.missingEn;
  return (
    <div className="mb-3 rounded-md border border-[#E89B57]/30 bg-[#E89B57]/[0.06] px-3 py-2 text-[12px] text-[#E89B57]">
      {text}
    </div>
  );
}

// === Entry card ==============================================================

function EntryCard({ entry, initial }: { entry: ChangelogEntry; initial: Lang }) {
  const split = splitBodyByLanguage(entry.body);
  const both = split.hasKo && split.hasEn;
  // Resolve initial lang to a value the entry actually has.
  const effectiveInitial: Lang = both
    ? initial
    : split.hasKo
      ? "ko"
      : "en";
  const [lang, setLang] = useState<Lang>(effectiveInitial);

  const scope = scopeOf(entry.version);
  const showFallback = (lang === "ko" && !split.hasKo) || (lang === "en" && !split.hasEn);
  const renderText = lang === "ko" ? split.ko : split.en;

  return (
    <article
      id={versionAnchor(entry.version)}
      className="rounded-lg border border-white/[0.06] hover:border-white/[0.10] p-5 scroll-mt-32 transition-colors"
    >
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-4 pb-3 border-b border-white/[0.04]">
        <span className="font-display font-bold text-lg text-[#F0F0FF]">
          v{entry.version}
        </span>
        {entry.date && (
          <span className="text-white/40 text-xs font-mono">{entry.date}</span>
        )}
        <span className="flex items-center gap-2 ml-auto">
          <ScopeChip scope={scope} />
          <LangToggle
            value={lang}
            onChange={setLang}
            hasKo={split.hasKo}
            hasEn={split.hasEn}
          />
        </span>
      </header>
      <div className="docs-prose">
        {showFallback && (
          <FallbackBanner
            desired={lang}
            available={split.hasKo ? "ko" : "en"}
          />
        )}
        <MarkdownLite text={renderText || entry.body} />
      </div>
    </article>
  );
}

// === Page ====================================================================

export default function Page() {
  const locale = useLocale();
  const setLocale = useSetLocale();
  const groups = groupByDecile(CHANGELOG);
  const initial: Lang = locale === "en" ? "en" : "ko";

  return (
    <DocsShell
      slug="reference/changelog"
      title="Changelog"
      titleKo="변경 이력"
      summary={`Full version history auto-synced from CHANGELOG.md (${CHANGELOG.length} entries, last synced ${CHANGELOG_SYNCED_AT}).`}
      summaryKo={`CHANGELOG.md에서 자동 sync된 전체 버전 이력 (${CHANGELOG.length} entries, ${CHANGELOG_SYNCED_AT} 최신).`}
    >
      <Bi
        ko={
          <p>
            전체 <strong>{CHANGELOG.length}</strong>개 버전 entry를 CHANGELOG.md에서 자동 추출.
            각 entry는 한국어와 영어가 모두 작성됐으면 우상단 <code>KO</code> / <code>EN</code> 토글로 전환합니다.
            한쪽 언어만 있으면 토글이 안 뜨고, 페이지 locale과 다르면 안내 배지가 떠요.
          </p>
        }
        en={
          <p>
            All <strong>{CHANGELOG.length}</strong> version entries auto-extracted from CHANGELOG.md.
            When an entry exists in both Korean and English, switch via the per-entry <code>KO</code> / <code>EN</code> pill.
            Mono-lingual entries skip the toggle and show a small fallback notice when the requested language is missing.
          </p>
        }
      />

      {/* Sticky decile pill bar. Jump nav + global locale shortcut */}
      <nav
        aria-label={t(locale, "버전 decile 점프", "Decile jump nav")}
        className="not-prose sticky top-16 z-20 -mx-6 px-6 py-3 backdrop-blur bg-[#0B1628]/90 border-y border-white/[0.06] mb-10 flex flex-wrap items-center gap-2"
      >
        {groups.map((g) => (
          <a
            key={g.decile}
            href={`#decile-${g.decile.replace(/[^a-zA-Z0-9]/g, "-")}`}
            className="text-[11px] font-mono px-2.5 py-1 rounded-full border border-white/[0.10] hover:border-[#A573E8] text-white/70 hover:text-[#F0F0FF] transition-colors"
          >
            {g.decile}
            <span className="ml-1 opacity-50">{g.entries.length}</span>
          </a>
        ))}
        <span className="ml-auto inline-flex items-center rounded-md border border-white/[0.10] overflow-hidden text-[10px] font-mono">
          <button
            type="button"
            onClick={() => setLocale("ko")}
            className={
              "px-2.5 py-1 transition-colors " +
              (locale === "ko"
                ? "bg-[#A573E8]/20 text-[#A573E8]"
                : "text-white/50 hover:text-white")
            }
          >
            한국어
          </button>
          <span className="w-px h-3 bg-white/[0.10]" />
          <button
            type="button"
            onClick={() => setLocale("en")}
            className={
              "px-2.5 py-1 transition-colors " +
              (locale === "en"
                ? "bg-white/[0.15] text-[#F0F0FF]"
                : "text-white/50 hover:text-white")
            }
          >
            English
          </button>
        </span>
      </nav>

      {groups.map((g) => (
        <section
          key={g.decile}
          id={`decile-${g.decile.replace(/[^a-zA-Z0-9]/g, "-")}`}
          className="not-prose scroll-mt-32 mb-16"
        >
          <h2 className="font-display text-2xl md:text-3xl font-bold tracking-tight mb-6 flex items-baseline gap-3">
            <span>{g.decile}</span>
            <span className="text-white/40 text-sm font-normal font-mono">
              {g.entries.length}{" "}
              {t(locale, "릴리스", g.entries.length === 1 ? "release" : "releases")}
            </span>
          </h2>
          <div className="space-y-6">
            {g.entries.map((e) => (
              <EntryCard key={e.version} entry={e} initial={initial} />
            ))}
          </div>
        </section>
      ))}

      <hr />
      <Bi
        ko={
          <>
            <h2>정본 출처</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code>가 진리원입니다.
              이 페이지는 <code>site/scripts/sync-stats.mjs</code>가 그 파일을 자동 파싱한 결과.
            </p>
            <h2>토글 동작</h2>
            <ul>
              <li>각 entry는 본문에서 한국어 / 영어 비율을 자동 감지합니다.</li>
              <li>두 언어가 모두 있는 entry: 우상단 <strong>KO / EN</strong> pill. 클릭으로 본문 swap.</li>
              <li>한 언어만 있는 entry: 토글 없음. 페이지 locale과 다르면 amber banner로 안내.</li>
              <li>코드 블록과 신호어(파일 경로, 식별자)는 양쪽에 모두 노출됩니다.</li>
              <li>상단 nav 우측의 <strong>한국어 / English</strong> 토글은 페이지 전역 locale을 바꿉니다 (모든 entry 기본값 동시 전환).</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Source of truth</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code> is the authoritative file.
              This page is the result of <code>site/scripts/sync-stats.mjs</code> parsing it.
            </p>
            <h2>Toggle behavior</h2>
            <ul>
              <li>Each entry's body is scanned for Hangul / Latin ratios.</li>
              <li>Entries with both languages: <strong>KO / EN</strong> pill at top right; click to swap.</li>
              <li>Mono-lingual entries: no toggle. If the active locale differs, an amber banner notes the absence.</li>
              <li>Code blocks and identifier-heavy strings (file paths, names) live in both sides.</li>
              <li>The <strong>한국어 / English</strong> control on the top nav switches the page-wide default for all entries at once.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
