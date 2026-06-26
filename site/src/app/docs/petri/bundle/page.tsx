import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Bundle viewer — GEODE Docs" };

const BUNDLE_URL = "/geode/self-improving/petri-bundle/";
const SEEDS_URL = "/geode/self-improving/petri-bundle/seeds/";

export default function Page() {
  return (
    <DocsShell
      slug="petri/bundle"
      title="Bundle viewer"
      titleKo="번들 뷰어"
      summary="The live inspect_ai transcript viewer for the latest audit run."
      summaryKo="가장 최근 감사 런의 라이브 inspect_ai 트랜스크립트 뷰어입니다."
    >
      <Bi
        ko={
          <>
            <p>
              가장 최근 공개된 Petri × GEODE 감사의 transcript를 함께 제공되는
              Inspect View로 직접 볼 수 있습니다. 같은 GitHub Pages 도메인의
              별도 경로에 배포됩니다.
            </p>

            <table>
              <thead>
                <tr><th>표면</th><th>경로</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><a href={BUNDLE_URL} target="_blank" rel="noreferrer">Eval 로그 뷰어</a></td>
                  <td><code>/geode/self-improving/petri-bundle/</code></td>
                  <td>inspect_ai transcript 뷰어. 런 목록은 <code>logs/listing.json</code>이 SoT.</td>
                </tr>
                <tr>
                  <td><a href={SEEDS_URL} target="_blank" rel="noreferrer">Seed 번들</a></td>
                  <td><code>.../petri-bundle/seeds/</code></td>
                  <td>seed-generation 런 번들. <code>listing.json</code> + 런별 JSON.</td>
                </tr>
                <tr>
                  <td><a href="/geode/docs/petri/seeds">Seed 생성 런 (docs)</a></td>
                  <td><code>/geode/docs/petri/seeds</code></td>
                  <td>같은 데이터를 docs 대시보드로 렌더. 후보 클릭 시 상세.</td>
                </tr>
              </tbody>
            </table>

            <h2>딥링크 규약</h2>
            <p>
              뷰어의 유효한 딥링크는{" "}
              <code>#/logs/&lt;encodeURIComponent(eval_filename)&gt;</code>{" "}
              형식 하나뿐입니다. <code>#/tasks/&lt;id&gt;</code> 라우트는
              존재하지 않으며, 그 형식의 링크는 조용히 런 목록으로
              떨어집니다. 링크 키는 <code>logs/listing.json</code>의 파일명을
              씁니다.
            </p>

            <h2>공개 경로</h2>
            <p>
              번들의 SoT는 리포지토리의{" "}
              <code>docs/self-improving/petri-bundle/</code>이고,{" "}
              <code>geode hub build</code>가 허브 정적 페이지를 갱신합니다.
              Pages 워크플로우가 빌드 시 이 트리를 사이트로 복사합니다. 새
              감사를 공개하려면 <a href="/geode/docs/petri/run">감사
              실행</a> 후 <code>geode petri-archive</code>로 아카이브와 요약을
              남기고 번들을 동기화합니다.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              점수 스케일(1~10, lower-is-better)과 차원 의미는{" "}
              <a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>을
              보세요.
            </p>
          </>
        }
        en={
          <>
            <p>
              The most recently published Petri × GEODE audit transcripts are
              browsable in a vendored Inspect View, deployed on the same
              GitHub Pages domain at a separate path.
            </p>

            <table>
              <thead>
                <tr><th>Surface</th><th>Path</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><a href={BUNDLE_URL} target="_blank" rel="noreferrer">Eval log viewer</a></td>
                  <td><code>/geode/self-improving/petri-bundle/</code></td>
                  <td>inspect_ai transcript viewer. The run list&apos;s SoT is <code>logs/listing.json</code>.</td>
                </tr>
                <tr>
                  <td><a href={SEEDS_URL} target="_blank" rel="noreferrer">Seed bundle</a></td>
                  <td><code>.../petri-bundle/seeds/</code></td>
                  <td>Seed-generation run bundle: <code>listing.json</code> plus per-run JSON.</td>
                </tr>
                <tr>
                  <td><a href="/geode/docs/petri/seeds">Seed-generation runs (docs)</a></td>
                  <td><code>/geode/docs/petri/seeds</code></td>
                  <td>The same data rendered as a docs dashboard, with per-candidate detail.</td>
                </tr>
              </tbody>
            </table>

            <h2>Deep-link convention</h2>
            <p>
              The viewer&apos;s only valid deep-link form is{" "}
              <code>#/logs/&lt;encodeURIComponent(eval_filename)&gt;</code>.
              There is no <code>#/tasks/&lt;id&gt;</code> route; links of that
              shape fall back silently to the run list. Key deep links on the
              filenames in <code>logs/listing.json</code>.
            </p>

            <h2>Publish path</h2>
            <p>
              The bundle&apos;s SoT is{" "}
              <code>docs/self-improving/petri-bundle/</code> in the repository,
              and <code>geode hub build</code> regenerates the hub&apos;s
              static pages. The Pages workflow copies that tree into the
              deployed site at build time. To publish a new audit, follow{" "}
              <a href="/geode/docs/petri/run">Run an audit</a>, then{" "}
              <code>geode petri-archive</code> to preserve the archive and
              summary before syncing the bundle.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              For the score scale (1-10, lower-is-better) and dimension
              meanings, see{" "}
              <a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
