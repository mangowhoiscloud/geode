import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "BiasBuster — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/biasbuster"
      title="BiasBuster"
      titleKo="BiasBuster"
      summary="Six bias detectors run against the analyst panel before the synthesizer. overall_pass=true requires all six false."
      summaryKo="synthesizer 전에 analyst 패널을 대상으로 6종 편향 검사기가 동작. overall_pass=true는 6개 모두 false일 때만 성립."
    >
      <Bi
        ko={
          <>
            <h2>6종 편향</h2>
            <table>
              <thead><tr><th>편향</th><th>트리거</th></tr></thead>
              <tbody>
                <tr><td>Confirmation</td><td>모든 analyst가 충분한 신호 발산 없이 같은 방향으로 추세</td></tr>
                <tr><td>Recency</td><td>최근 신호가 점수의 50% 초과 가중치를 차지</td></tr>
                <tr><td>Anchoring</td><td>4명 이상 analyst에서 CV (변동계수) &lt; 0.05</td></tr>
                <tr><td>Position</td><td>첫째 또는 마지막 evaluator 점수가 나머지로부터 표준편차 1 초과 이탈</td></tr>
                <tr><td>Verbosity</td><td>점수가 evidence 단락 길이와 상관 (임계값은 도메인별 조정 가능)</td></tr>
                <tr><td>Self-enhancement</td><td>evaluator가 자신의 이전 출력을 유리하게 채점</td></tr>
              </tbody>
            </table>

            <h2>결정 규칙</h2>
            <p>
              <code>overall_pass = all(flag is False for flag in [confirmation, recency, anchoring, position, verbosity, self_enhancement])</code>
            </p>
            <p>
              어느 편향이라도 하나 표시되면 패널을 재스코어링 라운드로 되돌리며, 표시된 편향이
              evaluator 프롬프트에 제약 조건으로 노출됩니다.
            </p>

            <h2>프롬프트</h2>
            <p>
              <code>core/llm/prompts/biasbuster.md</code>가 system + user 템플릿을 보관합니다.
              <code>_PINNED_HASHES</code>에 <code>BIASBUSTER_SYSTEM</code>과
              <code>BIASBUSTER_USER</code>로 핀 처리됩니다.
            </p>

            <h2>왜 별도 단계인가</h2>
            <p>
              evaluator는 개별적으로 채점되며, BiasBuster는 <em>패널</em>을 보는 유일한 단계입니다.
              6개 검출기는 analyst 점수에 대한 집단 수준 통계이지 개별 출력 검사가 아닙니다.
              이를 별도 단계에 두면 evaluator는 서로를 모르는 상태 (독립성에 좋음)를 유지하면서도
              cross-evaluator 점검을 받을 수 있습니다.
            </p>

            <h2>조정 가능 임계값</h2>
            <p>
              수치 임계값 (CV &lt; 0.05, r &gt; 0.7)은 Game IP 플러그인의
              <code>plugins/game_ip/config/evaluator_axes.yaml</code>에 있습니다. 다른 도메인은
              자체적으로 정의합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>The six biases</h2>
            <table>
              <thead><tr><th>Bias</th><th>Trigger</th></tr></thead>
              <tbody>
                <tr><td>Confirmation</td><td>All analysts trend in the same direction without sufficient signal divergence</td></tr>
                <tr><td>Recency</td><td>Most recent signal weighted &gt; 50% of the score</td></tr>
                <tr><td>Anchoring</td><td>CV (coefficient of variation) &lt; 0.05 across 4+ analysts</td></tr>
                <tr><td>Position</td><td>First/last evaluator score deviates &gt; 1 std from the rest</td></tr>
                <tr><td>Verbosity</td><td>Score correlates with evidence-paragraph length (threshold tunable per domain)</td></tr>
                <tr><td>Self-enhancement</td><td>Evaluator scores its own previous output favourably</td></tr>
              </tbody>
            </table>

            <h2>The decision rule</h2>
            <p>
              <code>overall_pass = all(flag is False for flag in [confirmation, recency, anchoring, position, verbosity, self_enhancement])</code>
            </p>
            <p>
              Any single bias flagged sends the panel back through a re-scoring
              round with the flagged bias surfaced as a constraint to the
              evaluator prompt.
            </p>

            <h2>The prompt</h2>
            <p>
              <code>core/llm/prompts/biasbuster.md</code> holds the system + user
              templates. They are pinned in <code>_PINNED_HASHES</code> as{" "}
              <code>BIASBUSTER_SYSTEM</code> and <code>BIASBUSTER_USER</code>.
            </p>

            <h2>Why a separate stage</h2>
            <p>
              The evaluators are scored individually and BiasBuster is the only
              step that sees the <em>panel</em>. The 6 detectors are population-
              level statistics on the analyst scores, not individual-output
              checks. Putting them in a separate stage lets the evaluators stay
              oblivious to each other (good for independence) while still getting
              the cross-evaluator sanity check.
            </p>

            <h2>Tunable thresholds</h2>
            <p>
              Numeric thresholds (CV &lt; 0.05, r &gt; 0.7) live in{" "}
              <code>plugins/game_ip/config/evaluator_axes.yaml</code> for the
              Game IP plugin. Other domains define their own.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
