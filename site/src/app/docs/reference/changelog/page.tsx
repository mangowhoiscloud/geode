"use client";

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

type Lang = "ko" | "en";

/**
 * Classify one markdown block.
 *  - ko: predominantly Hangul
 *  - en: predominantly Latin alphabet
 *  - both: visible mix
 *  - neutral: too short or code-only
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
 * Walk the body and split it into KO / EN halves, grouping by `### Section`.
 * A section header is only emitted on a side when at least one block under it
 * lives on that side. Prevents empty "Infrastructure" headers from appearing
 * when one language has no content for that section.
 */
function splitBodyByLanguage(body: string): {
  ko: string;
  en: string;
  hasKo: boolean;
  hasEn: boolean;
} {
  // Step 1. Parse into block strings.
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

  // Step 2. Group into sections delimited by `### ` headings.
  type Section = { header: string | null; blocks: string[] };
  const sections: Section[] = [];
  let curSec: Section = { header: null, blocks: [] };
  for (const b of blocks) {
    if (b.startsWith("### ") && !b.includes("\n")) {
      if (curSec.header || curSec.blocks.length) sections.push(curSec);
      curSec = { header: b, blocks: [] };
    } else {
      curSec.blocks.push(b);
    }
  }
  if (curSec.header || curSec.blocks.length) sections.push(curSec);

  // Step 3. Per side, only include a section's header if at least one of its
  // blocks lives on that side.
  const koOut: string[] = [];
  const enOut: string[] = [];
  let hasKo = false;
  let hasEn = false;

  for (const sec of sections) {
    const koBlocks: string[] = [];
    const enBlocks: string[] = [];
    let secHasMeaningfulKo = false;
    let secHasMeaningfulEn = false;
    for (const b of sec.blocks) {
      const isFence = b.startsWith("```");
      const lang = isFence ? "neutral" : classifyBlock(b);
      if (lang === "ko") {
        koBlocks.push(b);
        secHasMeaningfulKo = true;
        hasKo = true;
      } else if (lang === "en") {
        enBlocks.push(b);
        secHasMeaningfulEn = true;
        hasEn = true;
      } else if (lang === "both") {
        koBlocks.push(b);
        enBlocks.push(b);
        secHasMeaningfulKo = true;
        secHasMeaningfulEn = true;
        hasKo = true;
        hasEn = true;
      } else {
        // neutral: route to both, but does not count as meaningful for header emission
        koBlocks.push(b);
        enBlocks.push(b);
      }
    }
    if (sec.header && secHasMeaningfulKo) {
      koOut.push(sec.header);
    }
    if (secHasMeaningfulKo) {
      koOut.push(...koBlocks);
    }
    if (sec.header && secHasMeaningfulEn) {
      enOut.push(sec.header);
    }
    if (secHasMeaningfulEn) {
      enOut.push(...enBlocks);
    }
  }

  return {
    ko: koOut.join("\n\n"),
    en: enOut.join("\n\n"),
    hasKo,
    hasEn,
  };
}

// === UI atoms ================================================================

function MonolingualChip({ lang }: { lang: "ko" | "en" }) {
  return (
    <span className="text-[9px] font-mono uppercase tracking-wider text-white/30 border border-white/[0.10] rounded px-1.5 py-0">
      {lang === "ko" ? "KR only" : "EN only"}
    </span>
  );
}

// === Entry card ==============================================================

function EntryCard({ entry }: { entry: ChangelogEntry }) {
  const locale = useLocale() as Lang;
  const split = splitBodyByLanguage(entry.body);
  const both = split.hasKo && split.hasEn;
  const monoLang: Lang | null = !both ? (split.hasKo ? "ko" : "en") : null;
  const body =
    locale === "ko"
      ? split.ko || split.en || entry.body
      : split.en || split.ko || entry.body;

  return (
    <article
      id={versionAnchor(entry.version)}
      className="rounded-lg border border-white/[0.06] p-5 scroll-mt-24"
    >
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-4 pb-3 border-b border-white/[0.04]">
        <span className="font-display font-bold text-lg text-[#F0F0FF]">
          v{entry.version}
        </span>
        {entry.date && (
          <span className="text-white/40 text-xs font-mono">{entry.date}</span>
        )}
        {monoLang && (
          <span className="ml-auto">
            <MonolingualChip lang={monoLang} />
          </span>
        )}
      </header>
      <div className="docs-prose">
        <MarkdownLite text={body} />
      </div>
    </article>
  );
}

// === Page ====================================================================

export default function Page() {
  const locale = useLocale();
  const setLocale = useSetLocale();

  return (
    <DocsShell
      slug="reference/changelog"
      title="CHANGELOG"
      titleKo="CHANGELOG"
      summary={`Full history auto-synced from CHANGELOG.md. ${CHANGELOG.length} entries, last synced ${CHANGELOG_SYNCED_AT}.`}
      summaryKo={`CHANGELOG.md에서 자동 sync된 전체 이력. ${CHANGELOG.length} entries, ${CHANGELOG_SYNCED_AT} 최신.`}
    >
      <Bi
        ko={
          <p>
            전체 <strong>{CHANGELOG.length}</strong>개 entry를 CHANGELOG.md에서 자동 추출.
            상단 토글로 한국어 / 영어 전환. 한쪽만 작성된 entry는 표시 옆에 작은
            <code className="mx-1">KR only</code>/<code>EN only</code> 라벨이 붙고, 현재 locale에 콘텐츠가
            없는 경우 자동으로 다른 언어 fallback. 정본은 repo의 <code>CHANGELOG.md</code>.
          </p>
        }
        en={
          <p>
            All <strong>{CHANGELOG.length}</strong> entries auto-extracted from CHANGELOG.md.
            Switch language with the toggle above. Entries authored in only one language carry a small
            <code className="mx-1">KR only</code>/<code>EN only</code> chip; missing content falls back
            automatically. The repo&apos;s <code>CHANGELOG.md</code> is the source of truth.
          </p>
        }
      />

      {/* Single prominent top toggle. Replaces the previous sticky bar. */}
      <div className="not-prose flex justify-center my-8">
        <div className="inline-flex items-center rounded-md border border-white/[0.12] overflow-hidden text-sm">
          <button
            type="button"
            onClick={() => setLocale("ko")}
            className={
              "px-4 py-1.5 transition-colors " +
              (locale === "ko"
                ? "bg-[var(--acc-artifact)]/20 text-[var(--acc-artifact)] font-medium"
                : "text-white/55 hover:text-white")
            }
          >
            한국어
          </button>
          <span className="w-px h-5 bg-white/[0.12]" />
          <button
            type="button"
            onClick={() => setLocale("en")}
            className={
              "px-4 py-1.5 transition-colors " +
              (locale === "en"
                ? "bg-white/[0.15] text-[#F0F0FF] font-medium"
                : "text-white/55 hover:text-white")
            }
          >
            English
          </button>
        </div>
      </div>

      <div className="not-prose space-y-4">
        {CHANGELOG.map((e) => (
          <EntryCard key={e.version} entry={e} />
        ))}
      </div>

      <hr />
      <Bi
        ko={
          <>
            <h2>정본 출처</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code>가 진리원입니다.
              이 페이지는 <code>site/scripts/sync-stats.mjs</code>가 그 파일을 자동 파싱한 결과.
            </p>
            <p>
              {t(locale, "마지막 sync: ", "Last sync: ")}
              <code>{CHANGELOG_SYNCED_AT}</code>
            </p>
          </>
        }
        en={
          <>
            <h2>Source of truth</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code> is the authoritative file.
              This page is the result of <code>site/scripts/sync-stats.mjs</code> parsing it.
            </p>
            <p>
              Last sync: <code>{CHANGELOG_SYNCED_AT}</code>
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
