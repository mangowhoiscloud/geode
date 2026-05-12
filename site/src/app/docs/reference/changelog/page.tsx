"use client";

import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { MarkdownLite } from "@/components/geode-docs/markdown-lite";
import { useLocale, t } from "@/components/geode/locale-context";
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

type Lang = "ko" | "en" | "both" | "neutral";

function classifyLanguage(text: string): Lang {
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
 * Split an entry body into KO and EN halves at block level.
 *
 * A "block" is a paragraph, list, or fenced code block separated from
 * neighbours by a blank line. Code fences are language-neutral and live in
 * both halves.
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
    const lang = isFence ? "neutral" : classifyLanguage(b);
    if (lang === "ko") {
      koBlocks.push(b);
      hasKo = true;
    } else if (lang === "en") {
      enBlocks.push(b);
      hasEn = true;
    } else if (lang === "both") {
      // A block that mixes both languages in the same paragraph. Keep it whole
      // on both sides so neither column loses context.
      koBlocks.push(b);
      enBlocks.push(b);
      hasKo = true;
      hasEn = true;
    } else {
      // neutral (code, symbols, short): show on both sides
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

function entryLanguage(body: string): "ko" | "en" | "both" {
  const split = splitBodyByLanguage(body);
  if (split.hasKo && split.hasEn) return "both";
  return split.hasKo ? "ko" : "en";
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

function LangChip({ lang }: { lang: "ko" | "en" | "both" }) {
  const label = lang === "both" ? "KR · EN" : lang === "ko" ? "KR" : "EN";
  const color = lang === "both" ? "#A573E8" : "#807665";
  return (
    <span
      className="inline-flex items-center px-1.5 py-0 rounded text-[9px] font-mono uppercase tracking-wider"
      style={{
        color,
        border: `1px solid ${color}40`,
        backgroundColor: `${color}10`,
      }}
    >
      {label}
    </span>
  );
}

// === Page ====================================================================

export default function Page() {
  const locale = useLocale();
  const groups = groupByDecile(CHANGELOG);

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
            전체 <strong>{CHANGELOG.length}</strong>개 버전 entry를 CHANGELOG.md에서 자동 추출했습니다.
            <code> npm run sync-stats</code> 실행 시 자동 갱신됩니다 (마지막 sync: {CHANGELOG_SYNCED_AT}).
            정본은 repo의 <code>CHANGELOG.md</code>.
          </p>
        }
        en={
          <p>
            Auto-extracted <strong>{CHANGELOG.length}</strong> version entries from CHANGELOG.md. Refreshes when
            <code> npm run sync-stats </code>runs (last sync: {CHANGELOG_SYNCED_AT}). The repository&apos;s
            <code> CHANGELOG.md </code>is the source of truth.
          </p>
        }
      />

      {/* Sticky decile pill bar. Jump nav. */}
      <nav
        aria-label={t(locale, "버전 decile 점프", "Decile jump nav")}
        className="not-prose sticky top-16 z-20 -mx-6 px-6 py-3 backdrop-blur bg-[#0B1628]/90 border-y border-white/[0.06] mb-10 flex flex-wrap gap-2"
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
            {g.entries.map((e) => {
              const lang = entryLanguage(e.body);
              const scope = scopeOf(e.version);
              const split = lang === "both" ? splitBodyByLanguage(e.body) : null;
              return (
                <article
                  key={e.version}
                  id={versionAnchor(e.version)}
                  className="rounded-lg border border-white/[0.06] hover:border-white/[0.10] p-5 scroll-mt-32 transition-colors"
                >
                  <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-4 pb-3 border-b border-white/[0.04]">
                    <span className="font-display font-bold text-lg text-[#F0F0FF]">
                      v{e.version}
                    </span>
                    {e.date && (
                      <span className="text-white/40 text-xs font-mono">{e.date}</span>
                    )}
                    <span className="flex items-center gap-1.5 ml-auto">
                      <ScopeChip scope={scope} />
                      <LangChip lang={lang} />
                    </span>
                  </header>
                  <div className="docs-prose">
                    {split ? (
                      <div className="grid md:grid-cols-2 gap-x-8">
                        <div className="border-l-2 border-[#A573E8]/30 pl-4">
                          <div className="text-[10px] font-mono uppercase tracking-wider text-[#A573E8] mb-2">
                            한국어
                          </div>
                          <MarkdownLite text={split.ko} />
                        </div>
                        <div className="border-l-2 border-white/[0.10] pl-4 mt-6 md:mt-0">
                          <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
                            English
                          </div>
                          <MarkdownLite text={split.en} />
                        </div>
                      </div>
                    ) : (
                      <MarkdownLite text={e.body} />
                    )}
                  </div>
                </article>
              );
            })}
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
              이 페이지는 그 파일을 <code>site/scripts/sync-stats.mjs</code>가 자동 파싱하여 렌더한 결과입니다.
            </p>
            <h2>한·영 분리 동작</h2>
            <p>
              각 entry는 본문에서 한국어 / 영어 비율을 자동 감지합니다. 두 언어가 모두 있으면
              위쪽처럼 좌·우 컬럼으로 분리해 렌더합니다. 코드 블록은 양쪽 컬럼에 동일하게 들어갑니다.
              한쪽 언어만 있으면 단일 컬럼.
            </p>
            <p>
              앞으로 작성하는 entry는 두 단락을 모두 두면 자동으로 좌·우 split이 적용됩니다.
              형식 예시는 <code>geode-changelog</code> 스킬 참조.
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
            <h2>How the KR / EN split works</h2>
            <p>
              Each entry&apos;s body is scanned for Hangul / Latin character ratios. When both languages are
              present, the body renders as left (한국어) and right (English) columns; code blocks live in
              both. Mono-lingual entries render in a single column.
            </p>
            <p>
              When you write a new entry with both Korean and English paragraphs, the side-by-side split is
              applied automatically. See the <code>geode-changelog</code> skill for the format.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
