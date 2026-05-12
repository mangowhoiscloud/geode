import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Audit Bundle Viewer — GEODE Docs" };

const BUNDLE_URL = "/petri-bundle/";

export default function Page() {
  return (
    <DocsShell
      slug="petri/bundle"
      title="Audit Bundle Viewer"
      titleKo="감사 Bundle 뷰어"
      summary="Live inspect_ai transcript viewer for the latest GEODE audit run."
      summaryKo="최신 GEODE 감사 run의 라이브 inspect_ai 트랜스크립트 뷰어."
    >
      <Bi
        ko={
          <>
            <p>
              <strong>Reference:</strong> 가장 최근 published Petri × GEODE audit의 라이브 transcript 뷰어 링크입니다.
              GitHub Pages의 같은 도메인 다른 path에 publish됩니다.
            </p>

            <p>
              <a
                href={BUNDLE_URL}
                className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-4 py-2 mt-2 text-base font-medium hover:border-[#A573E8] hover:text-[#A573E8] transition-colors"
                target="_blank"
                rel="noreferrer"
              >
                /geode/petri-bundle/ 뷰어 열기 ↗
              </a>
            </p>

            <h2>Bundle에 들어 있는 것</h2>
            <ul>
              <li>전체 transcript JSONL (auditor·target·judge 발화 + tool call 트레이스)</li>
              <li>Judge 점수표 (N seeds × 38 dims)</li>
              <li>실행 메타: 사용 모델, seed list, max-turns, 총 비용</li>
              <li>matplotlib heatmap + summary stats</li>
            </ul>

            <h2>Bundle을 새로 만들려면</h2>
            <p>
              <a href="/docs/petri/run">감사 실행</a> 가이드에 따라 audit를 돌린 뒤 결과 디렉토리를
              <code>site/public/petri-bundle/</code>에 publish 합니다. Pages workflow가 path-filter <code>site/**</code>를
              잡고 자동 deploy합니다.
            </p>

            <h2>점수 해석</h2>
            <p>
              차원별 의미와 0-3 점수 스케일은 <a href="/docs/petri/judge-dimensions">38 Judge 차원</a> 페이지를 참조하세요.
            </p>

            <p className="text-white/40 text-sm">
              <em>참고:</em> 뷰어가 404로 나오면 아직 publish되지 않았다는 뜻입니다. CHANGELOG에서 가장 최근
              Petri 항목 (PR #1024+, v0.92.0 이후)을 확인하세요.
            </p>
          </>
        }
        en={
          <>
            <p>
              <strong>Reference:</strong> live transcript viewer link for the most recently published Petri × GEODE
              audit. Hosted on the same GitHub Pages domain, different path.
            </p>

            <p>
              <a
                href={BUNDLE_URL}
                className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-4 py-2 mt-2 text-base font-medium hover:border-[#A573E8] hover:text-[#A573E8] transition-colors"
                target="_blank"
                rel="noreferrer"
              >
                Open /geode/petri-bundle/ viewer ↗
              </a>
            </p>

            <h2>What the bundle contains</h2>
            <ul>
              <li>Full transcript JSONL (auditor, target, judge utterances plus tool-call traces)</li>
              <li>Judge score grid (N seeds by 38 dims)</li>
              <li>Run metadata: models used, seed list, max-turns, total cost</li>
              <li>matplotlib heatmap and summary statistics</li>
            </ul>

            <h2>Publishing a new bundle</h2>
            <p>
              Follow the <a href="/docs/petri/run">Run an Audit</a> guide, then drop the result directory at
              <code>site/public/petri-bundle/</code>. The Pages workflow path-filter <code>site/**</code>
              will deploy automatically.
            </p>

            <h2>Score interpretation</h2>
            <p>
              For dimension meanings and the 0-3 score scale, see <a href="/docs/petri/judge-dimensions">38 Judge Dimensions</a>.
            </p>

            <p className="text-white/40 text-sm">
              <em>Note:</em> if the viewer 404s, the bundle has not been published yet. Check CHANGELOG for the most
              recent Petri entry (PR #1024+, v0.92.0 onward).
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
