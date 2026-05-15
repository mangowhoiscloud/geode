import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Run an Analysis — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/analyze"
      title="Run an Analysis"
      titleKo="분석 실행"
      summary="Run the Game IP pipeline end to end, dry-run or live."
      summaryKo="Game IP 파이프라인을 dry-run 또는 라이브로 끝까지 돌리기."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE의 첫 도메인 플러그인인 Game IP 분석 파이프라인을 한 번 끝까지 실행합니다.</p>

            <h2>Dry-run (API 호출 없음)</h2>
            <pre>{`uv run geode analyze "Cowboy Bebop" --dry-run
# → A (68.4) — undermarketed`}</pre>
            <p>고정된 3 fixture (Berserk·Cowboy Bebop·Ghost in the Shell)로 파이프라인 전체를 통과시킵니다. 비용 0.</p>

            <h2>Live run</h2>
            <pre>{`uv run geode analyze "Berserk" --verbose`}</pre>
            <p>실제 LLM 호출이 발생합니다. 비용 가드는 <a href="/docs/ops/cost">비용 모니터링</a>에서 설정하세요.</p>

            <h2>출력 구조</h2>
            <ul>
              <li>점수: 14축 PSM scoring → 최종 tier (S/A/B/C/D)</li>
              <li>원인: 6 카테고리 중 분류 (예: undermarketed, conversion_failure, discovery_failure)</li>
              <li>전체 reasoning trail: hooks + runlog</li>
            </ul>

            <h2>다음</h2>
            <ul>
              <li>점수 의미: <a href="/docs/plugins/game-ip">Game IP 플러그인</a></li>
              <li>다른 도메인 추가: <a href="/docs/runtime/domains">도메인 플러그인 추가</a></li>
            </ul>
          </>
        }
        en={
          <>
            <p>This guide runs GEODE's first domain plugin, the Game IP valuation pipeline, end to end.</p>

            <h2>Dry-run (no API calls)</h2>
            <pre>{`uv run geode analyze "Cowboy Bebop" --dry-run
# → A (68.4) — undermarketed`}</pre>
            <p>Three fixed fixtures (Berserk, Cowboy Bebop, Ghost in the Shell) exercise the full pipeline at zero cost.</p>

            <h2>Live run</h2>
            <pre>{`uv run geode analyze "Berserk" --verbose`}</pre>
            <p>Real LLM calls. Configure cost guards in <a href="/docs/ops/cost">Cost Monitoring</a>.</p>

            <h2>Output shape</h2>
            <ul>
              <li>Score: 14-axis PSM scoring leading to a tier (S/A/B/C/D).</li>
              <li>Cause: one of six classes (undermarketed, conversion_failure, discovery_failure, …).</li>
              <li>Full reasoning trail via hooks and runlog.</li>
            </ul>

            <h2>Next</h2>
            <ul>
              <li>What the scores mean: <a href="/docs/plugins/game-ip">Game IP Plugin</a>.</li>
              <li>Add another domain: <a href="/docs/runtime/domains">Add a Domain Plugin</a>.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
