import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "tau2 mock smoke — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/tau2/mock-smoke"
      title="tau2: mock smoke"
      titleKo="tau2: mock smoke"
      summary="Verifier-backed tau2 mock smoke run with GEODE as both agent and simulated user through the subscription route."
      summaryKo="GEODE가 agent와 simulated user 양쪽을 subscription route로 실행한 tau2 mock smoke verifier-backed 기록입니다."
    >
      <Bi
        ko={
          <>
            <h2>결과 요약</h2>
            <p>
              이 페이지는 tau2-bench의 <code>mock</code> domain 1-task smoke를
              GEODE subscription-only 경로로 실행한 첫 공식 run record입니다.
              측정 대상은 <code>geode_agent</code>와 <code>geode_user</code>가
              모두 <code>gpt-5.5</code> subscription route를 사용하는 구성입니다.
            </p>
            <table>
              <tbody>
                <tr><td>Benchmark</td><td>tau2-bench</td></tr>
                <tr><td>Domain / task</td><td><code>mock</code> / <code>create_task_1</code></td></tr>
                <tr><td>Run date</td><td>2026-07-03</td></tr>
                <tr><td>Harness revision</td><td><code>sierra-research/tau2-bench@1901a30</code>, <code>tau2==1.0.0</code></td></tr>
                <tr><td>Agent route</td><td><code>geode_agent</code>, <code>gpt-5.5</code>, source <code>subscription</code>, effort <code>xhigh</code></td></tr>
                <tr><td>User route</td><td><code>geode_user</code>, <code>gpt-5.5</code>, source <code>subscription</code>, effort <code>high</code></td></tr>
                <tr><td>Trials / tasks</td><td>1 / 1</td></tr>
                <tr><td>Reward</td><td><strong>1.0000</strong></td></tr>
                <tr><td>Pass^1</td><td><strong>1.000</strong></td></tr>
                <tr><td>DB check</td><td>1.0</td></tr>
                <tr><td>Action check</td><td><code>create_task</code> write action 1.0</td></tr>
                <tr><td>Termination</td><td><code>user_stop</code></td></tr>
                <tr><td>Duration</td><td>54.90s</td></tr>
              </tbody>
            </table>

            <h2>실행 명령</h2>
            <pre><code>{`uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain mock \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 8 \\
  --timeout 900 \\
  --model gpt-5.5 \\
  --provider openai \\
  --source subscription \\
  --effort xhigh \\
  --time-budget-s 180 \\
  --user geode_user \\
  --user-llm gpt-5.5 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt-5-5-xhigh-geode-user-mock-smoke-20260703-r5 \\
  --log-level INFO \\
  --verbose-logs`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Raw result:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-mock-smoke-20260703-r5/results.json</code>
            </p>

            <h2>비교 가능성</h2>
            <p>
              이 수치는 tau2 leaderboard 점수가 아닙니다. <code>mock</code> 1-task
              smoke는 GEODE와 tau2 harness의 연결, subscription-backed user,
              tool projection, DB diff verifier가 동작하는지 보는 regression
              baseline입니다.
            </p>
            <ul>
              <li>native tau2 <code>user_simulator</code> + <code>gpt-4.1</code> run과 평균내지 않습니다.</li>
              <li>native tau2 <code>user_simulator</code> + <code>gpt-5.2</code> leaderboard-compatible run과 평균내지 않습니다.</li>
              <li>다음 실측은 같은 adapter로 Telecom small run을 별도 페이지에 기록합니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Result Summary</h2>
            <p>
              This is GEODE&apos;s first official run record for a tau2-bench
              <code>mock</code> domain smoke using a subscription-only route.
              Both <code>geode_agent</code> and <code>geode_user</code> run
              through GEODE&apos;s <code>gpt-5.5</code> subscription path.
            </p>
            <table>
              <tbody>
                <tr><td>Benchmark</td><td>tau2-bench</td></tr>
                <tr><td>Domain / task</td><td><code>mock</code> / <code>create_task_1</code></td></tr>
                <tr><td>Run date</td><td>2026-07-03</td></tr>
                <tr><td>Harness revision</td><td><code>sierra-research/tau2-bench@1901a30</code>, <code>tau2==1.0.0</code></td></tr>
                <tr><td>Agent route</td><td><code>geode_agent</code>, <code>gpt-5.5</code>, source <code>subscription</code>, effort <code>xhigh</code></td></tr>
                <tr><td>User route</td><td><code>geode_user</code>, <code>gpt-5.5</code>, source <code>subscription</code>, effort <code>high</code></td></tr>
                <tr><td>Trials / tasks</td><td>1 / 1</td></tr>
                <tr><td>Reward</td><td><strong>1.0000</strong></td></tr>
                <tr><td>Pass^1</td><td><strong>1.000</strong></td></tr>
                <tr><td>DB check</td><td>1.0</td></tr>
                <tr><td>Action check</td><td><code>create_task</code> write action 1.0</td></tr>
                <tr><td>Termination</td><td><code>user_stop</code></td></tr>
                <tr><td>Duration</td><td>54.90s</td></tr>
              </tbody>
            </table>

            <h2>Command</h2>
            <pre><code>{`uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain mock \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 8 \\
  --timeout 900 \\
  --model gpt-5.5 \\
  --provider openai \\
  --source subscription \\
  --effort xhigh \\
  --time-budget-s 180 \\
  --user geode_user \\
  --user-llm gpt-5.5 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt-5-5-xhigh-geode-user-mock-smoke-20260703-r5 \\
  --log-level INFO \\
  --verbose-logs`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Raw result:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-mock-smoke-20260703-r5/results.json</code>
            </p>

            <h2>Comparability</h2>
            <p>
              This is not a tau2 leaderboard score. The <code>mock</code>
              one-task smoke is a regression baseline for GEODE/tau2 harness
              wiring, subscription-backed user simulation, tool projection, and
              the DB diff verifier.
            </p>
            <ul>
              <li>Do not average it with native tau2 <code>user_simulator</code> + <code>gpt-4.1</code> runs.</li>
              <li>Do not average it with native tau2 <code>user_simulator</code> + <code>gpt-5.2</code> leaderboard-compatible runs.</li>
              <li>The next measured step is a Telecom small run through the same adapter, recorded on a separate page.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
