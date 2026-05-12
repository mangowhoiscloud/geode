"use client";

import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { MarkdownLite } from "@/components/geode-docs/markdown-lite";
import { CHANGELOG, CHANGELOG_SYNCED_AT } from "@/data/geode/changelog";

function versionAnchor(version: string): string {
  return "v-" + version.toLowerCase().replace(/[^a-z0-9.]/g, "-");
}

export default function Page() {
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
          <>
            <p>
              전체 <strong>{CHANGELOG.length}</strong>개 버전 entry를 CHANGELOG.md에서 자동 추출했습니다. 정본은 repo의 <code>CHANGELOG.md</code>.
              <code> npm run sync-stats</code> 실행 시 자동 갱신됩니다 (마지막 sync: {CHANGELOG_SYNCED_AT}).
            </p>
            <h2>버전 목록</h2>
            <ol className="not-prose grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 text-[12.5px] font-mono mb-10">
              {CHANGELOG.map((e) => (
                <li key={e.version}>
                  <a href={`#${versionAnchor(e.version)}`} className="text-white/60 hover:text-white">
                    {e.version}
                    {e.date ? <span className="text-white/30"> . {e.date}</span> : null}
                  </a>
                </li>
              ))}
            </ol>
            {CHANGELOG.map((e) => (
              <section key={e.version} id={versionAnchor(e.version)} className="mt-12 scroll-mt-24">
                <h2 className="!mt-0">
                  v{e.version === "Unreleased" ? "Unreleased" : e.version}
                  {e.date ? <span className="text-white/40 text-base font-normal"> . {e.date}</span> : null}
                </h2>
                <MarkdownLite text={e.body} />
              </section>
            ))}
            <hr />
            <h2>정본 출처</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code>가 진리원입니다.
              이 페이지는 그 파일을 <code>site/scripts/sync-stats.mjs</code>가 자동 파싱하여 렌더한 결과입니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              The full <strong>{CHANGELOG.length}</strong>-entry history, auto-extracted from CHANGELOG.md.
              The authoritative source is the repository's <code>CHANGELOG.md</code>. The data refreshes
              when <code>npm run sync-stats</code> runs (last sync: {CHANGELOG_SYNCED_AT}).
            </p>
            <h2>Version index</h2>
            <ol className="not-prose grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 text-[12.5px] font-mono mb-10">
              {CHANGELOG.map((e) => (
                <li key={e.version}>
                  <a href={`#${versionAnchor(e.version)}`} className="text-white/60 hover:text-white">
                    {e.version}
                    {e.date ? <span className="text-white/30"> . {e.date}</span> : null}
                  </a>
                </li>
              ))}
            </ol>
            {CHANGELOG.map((e) => (
              <section key={e.version} id={versionAnchor(e.version)} className="mt-12 scroll-mt-24">
                <h2 className="!mt-0">
                  v{e.version === "Unreleased" ? "Unreleased" : e.version}
                  {e.date ? <span className="text-white/40 text-base font-normal"> . {e.date}</span> : null}
                </h2>
                <MarkdownLite text={e.body} />
              </section>
            ))}
            <hr />
            <h2>Authoritative source</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code> is the source of truth.
              This page is the result of <code>site/scripts/sync-stats.mjs</code> parsing that file and
              rendering it here.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
