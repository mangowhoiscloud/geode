import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { GEODE_SOT } from "@/data/geode/sot";

export const metadata = { title: "System Metrics SOT — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/sot-metrics"
      title="System Metrics SOT"
      titleKo="시스템 메트릭 SOT"
      summary="Live values for version, modules, tests, releases, since."
      summaryKo="version, 모듈, 테스트, 릴리스, since 라이브 값."
    >
      <Bi
        ko={
          <>
            <p><strong>Reference:</strong> 사이트 전체가 인용하는 단일 진실 원천(SOT) 값입니다. <code>site/scripts/sync-stats.mjs</code>가 GEODE repo의 <code>pyproject.toml</code> + 파일시스템 + <code>CHANGELOG.md</code>를 읽어 자동 갱신합니다.</p>

            <h2>현재 값 (사이트 빌드 시점)</h2>
            <table>
              <thead><tr><th>키</th><th>값</th></tr></thead>
              <tbody>
                <tr><td>version</td><td><code>{GEODE_SOT.version}</code></td></tr>
                <tr><td>modules.core</td><td><code>{GEODE_SOT.modules.core}</code></td></tr>
                <tr><td>modules.plugins</td><td><code>{GEODE_SOT.modules.plugins}</code></td></tr>
                <tr><td>modules.total</td><td><code>{GEODE_SOT.modules.total}</code></td></tr>
                <tr><td>tests.standard</td><td><code>{GEODE_SOT.tests.standard.toLocaleString()}</code></td></tr>
                <tr><td>tests.live</td><td><code>{GEODE_SOT.tests.live}</code></td></tr>
                <tr><td>releases</td><td><code>{GEODE_SOT.releases}</code></td></tr>
                <tr><td>since</td><td><code>{GEODE_SOT.since}</code></td></tr>
                <tr><td>syncedAt</td><td><code>{GEODE_SOT.syncedAt}</code></td></tr>
              </tbody>
            </table>

            <h2>갱신 방법</h2>
            <pre>{`cd site && npm run sync-stats`}</pre>
            <p>출력 파일: <code>site/src/data/geode/sot.ts</code></p>

            <h2>왜 SOT 인가</h2>
            <p>이전 버전 (basePath /portfolio)에서는 페이지마다 메트릭이 하드코딩돼 있었고, 그 결과 사이트가 본 코드베이스보다 24 minor 버전 뒤처져 있었습니다. SOT 자동 sync가 그 갭을 0으로 만듭니다.</p>

            <h2>CI 게이트 (계획)</h2>
            <p>Pages workflow에 <code>npm run sync-stats</code>를 build step에 두어, 매 deploy마다 최신 값을 확보합니다. 추후 PR 시점에 SOT diff 가 발생하면 자동으로 commit하는 path도 검토 중.</p>
          </>
        }
        en={
          <>
            <p><strong>Reference:</strong> the single source of truth values cited site-wide. <code>site/scripts/sync-stats.mjs</code> reads the GEODE repo's <code>pyproject.toml</code>, filesystem, and <code>CHANGELOG.md</code> to refresh them automatically.</p>

            <h2>Current values (at site build time)</h2>
            <table>
              <thead><tr><th>Key</th><th>Value</th></tr></thead>
              <tbody>
                <tr><td>version</td><td><code>{GEODE_SOT.version}</code></td></tr>
                <tr><td>modules.core</td><td><code>{GEODE_SOT.modules.core}</code></td></tr>
                <tr><td>modules.plugins</td><td><code>{GEODE_SOT.modules.plugins}</code></td></tr>
                <tr><td>modules.total</td><td><code>{GEODE_SOT.modules.total}</code></td></tr>
                <tr><td>tests.standard</td><td><code>{GEODE_SOT.tests.standard.toLocaleString()}</code></td></tr>
                <tr><td>tests.live</td><td><code>{GEODE_SOT.tests.live}</code></td></tr>
                <tr><td>releases</td><td><code>{GEODE_SOT.releases}</code></td></tr>
                <tr><td>since</td><td><code>{GEODE_SOT.since}</code></td></tr>
                <tr><td>syncedAt</td><td><code>{GEODE_SOT.syncedAt}</code></td></tr>
              </tbody>
            </table>

            <h2>How to refresh</h2>
            <pre>{`cd site && npm run sync-stats`}</pre>
            <p>Output file: <code>site/src/data/geode/sot.ts</code>.</p>

            <h2>Why an SOT</h2>
            <p>Earlier (basePath /portfolio), each page hardcoded metrics, leaving the site 24 minor versions behind the codebase. Automatic SOT sync brings that drift to zero.</p>

            <h2>CI gate (planned)</h2>
            <p>The Pages workflow runs <code>npm run sync-stats</code> as a build step so every deploy carries fresh values. A PR-time auto-commit on SOT diff is under consideration.</p>
          </>
        }
      />
    </DocsShell>
  );
}
