import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "tau2: domain smoke matrix — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/tau2/domain-smoke"
      title="tau2: domain smoke matrix"
      titleKo="tau2: domain smoke matrix"
      summary="GEODE subscription-route tau2 smoke matrix across mock, airline, retail, telecom, and banking_knowledge."
      summaryKo="GEODE subscription route로 실행한 tau2 mock, airline, retail, telecom, banking_knowledge smoke matrix입니다."
    >
      <Bi
        ko={
          <>
            <h2>결과 요약</h2>
            <p>
              이 페이지는 tau2-bench 전체 domain을 한 번에 평균내는 leaderboard가
              아니라, GEODE adapter가 각 domain에서 어디까지 통과하는지 보는
              smoke matrix입니다. 기본 row는 agent와 simulated user 모두 GEODE의
              <code>gpt-5.5</code> subscription route를 사용했고, telecom
              게시 row는 <code>gpt-5.2</code> PAYG user route를 별도로 기록했습니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Benchmark</td><td>tau2-bench</td></tr>
                <tr><td>Run date</td><td>2026-07-03</td></tr>
                <tr><td>Harness revision</td><td><code>sierra-research/tau2-bench@1901a30</code>, <code>tau2==1.0.0</code></td></tr>
                <tr><td>Agent route</td><td><code>geode_agent</code>, <code>gpt-5.5</code>, source <code>subscription</code>, effort <code>xhigh</code></td></tr>
                <tr><td>User route</td><td><code>geode_user</code>, default <code>gpt-5.5</code> subscription; telecom retry <code>gpt-5.2</code> PAYG</td></tr>
                <tr><td>Trials</td><td>1 per smoke row</td></tr>
                <tr><td>Purpose</td><td>domain adapter calibration and regression evidence, not public tau2 leaderboard aggregation</td></tr>
              </tbody>
            </table>

            <h2>Domain별 smoke 결과</h2>
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Task ID / case</th>
                  <th>Reward</th>
                  <th>Termination</th>
                  <th>Duration</th>
                  <th>판독</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>mock</code></td><td><code>create_task_1</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>65.69s</td><td>DB diff와 assistant write action 모두 통과</td></tr>
                <tr><td><code>airline</code></td><td><code>task_id=0</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>134.86s</td><td>DB/communicate reward 통과</td></tr>
                <tr><td><code>retail</code></td><td><code>task_id=0</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>283.61s</td><td>5개 expected action check 모두 통과</td></tr>
                <tr><td><code>telecom</code></td><td><code>mobile_data_issue</code>, <code>gpt-5.2/payg user</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>219.12s</td><td><code>max_steps=200</code>에서 <code>toggle_airplane_mode</code>와 <code>toggle_roaming</code> 통과</td></tr>
                <tr><td><code>banking_knowledge</code></td><td><code>task_001</code></td><td>0.0</td><td><code>user_stop</code></td><td>360.77s</td><td><code>bm25</code> retrieval로 하네스는 실행됐지만 user-side write action 미발화</td></tr>
              </tbody>
            </table>

            <h2>실행 명령 패턴</h2>
            <pre><code>{`uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain <domain> \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps <8|14|30|200> \\
  --timeout <900|1200|1800> \\
  --model gpt-5.5 \\
  --provider openai \\
  --source subscription \\
  --effort xhigh \\
  --time-budget-s <180|240|300> \\
  --user geode_user \\
  --user-llm gpt-5.5 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s <120|180|240> \\
  --save-to <stable-run-id> \\
  --log-level INFO`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Raw results:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-*/results.json</code>
              <br />
              GPT-5.2 PAYG telecom retry:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-gpt-5-2-payg-telecom-mobile-data-20260703-max200/results.json</code>
            </p>

            <h2>비교 가능성</h2>
            <table>
              <thead>
                <tr>
                  <th>비교 대상</th>
                  <th>판정</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>같은 GEODE adapter smoke 재실행</td><td>직접 비교 가능</td></tr>
                <tr><td>tau2 leaderboard</td><td>직접 비교 불가. GEODE simulated user와 subscription route를 사용</td></tr>
                <tr><td>native tau2 <code>user_simulator</code> + <code>gpt-5.2</code></td><td>별도 comparator track으로 분리</td></tr>
                <tr><td>MCPMark / BFCL / Terminal-Bench</td><td>다른 benchmark. 평균내지 않음</td></tr>
              </tbody>
            </table>

            <h2>판독</h2>
            <ul>
              <li>mock, airline, retail은 adapter와 verifier path가 정상 동작합니다.</li>
              <li>telecom 게시 row는 <code>gpt-5.2</code> PAYG user route와 <code>max_steps=200</code>에서 통과한 결과만 남겼습니다.</li>
              <li><code>gpt-5.2</code>는 현재 Codex subscription backend에서 지원되지 않아 PAYG user route로만 기록했습니다. 중단된 subscription 시도는 결과에 포함하지 않았습니다.</li>
              <li>banking_knowledge는 <code>--retrieval-config bm25</code> 옵션으로 sandbox 의존성을 피했지만, user-side tool policy 보강이 필요합니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Result Summary</h2>
            <p>
              This is not a tau2 leaderboard aggregate. It is a smoke matrix for
              checking how far the GEODE adapter gets in each tau2 domain. The
              default rows use GEODE&apos;s <code>gpt-5.5</code> subscription route
              for both agent and simulated user; the published telecom row records a
              separate <code>gpt-5.2</code> PAYG user route.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Benchmark</td><td>tau2-bench</td></tr>
                <tr><td>Run date</td><td>2026-07-03</td></tr>
                <tr><td>Harness revision</td><td><code>sierra-research/tau2-bench@1901a30</code>, <code>tau2==1.0.0</code></td></tr>
                <tr><td>Agent route</td><td><code>geode_agent</code>, <code>gpt-5.5</code>, source <code>subscription</code>, effort <code>xhigh</code></td></tr>
                <tr><td>User route</td><td><code>geode_user</code>, default <code>gpt-5.5</code> subscription; telecom retry <code>gpt-5.2</code> PAYG</td></tr>
                <tr><td>Trials</td><td>1 per smoke row</td></tr>
                <tr><td>Purpose</td><td>domain adapter calibration and regression evidence, not public tau2 leaderboard aggregation</td></tr>
              </tbody>
            </table>

            <h2>Smoke Results By Domain</h2>
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Task ID / case</th>
                  <th>Reward</th>
                  <th>Termination</th>
                  <th>Duration</th>
                  <th>Reading</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>mock</code></td><td><code>create_task_1</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>65.69s</td><td>DB diff and assistant write action passed</td></tr>
                <tr><td><code>airline</code></td><td><code>task_id=0</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>134.86s</td><td>DB and communicate reward passed</td></tr>
                <tr><td><code>retail</code></td><td><code>task_id=0</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>283.61s</td><td>All 5 expected action checks passed</td></tr>
                <tr><td><code>telecom</code></td><td><code>mobile_data_issue</code>, <code>gpt-5.2/payg user</code></td><td><strong>1.0</strong></td><td><code>user_stop</code></td><td>219.12s</td><td>Passed <code>toggle_airplane_mode</code> and <code>toggle_roaming</code> with <code>max_steps=200</code></td></tr>
                <tr><td><code>banking_knowledge</code></td><td><code>task_001</code></td><td>0.0</td><td><code>user_stop</code></td><td>360.77s</td><td>Harness ran with <code>bm25</code> retrieval, but the user-side write action did not fire</td></tr>
              </tbody>
            </table>

            <h2>Command Pattern</h2>
            <pre><code>{`uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain <domain> \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps <8|14|30|200> \\
  --timeout <900|1200|1800> \\
  --model gpt-5.5 \\
  --provider openai \\
  --source subscription \\
  --effort xhigh \\
  --time-budget-s <180|240|300> \\
  --user geode_user \\
  --user-llm gpt-5.5 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s <120|180|240> \\
  --save-to <stable-run-id> \\
  --log-level INFO`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Raw results:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-*/results.json</code>
              <br />
              GPT-5.2 PAYG telecom retry:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-gpt-5-2-payg-telecom-mobile-data-20260703-max200/results.json</code>
            </p>

            <h2>Comparability</h2>
            <table>
              <thead>
                <tr>
                  <th>Comparator</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Same GEODE adapter smoke rerun</td><td>Directly comparable</td></tr>
                <tr><td>tau2 leaderboard</td><td>Not directly comparable. This uses GEODE simulated user and subscription route</td></tr>
                <tr><td>Native tau2 <code>user_simulator</code> + <code>gpt-5.2</code></td><td>Separate comparator track</td></tr>
                <tr><td>MCPMark / BFCL / Terminal-Bench</td><td>Different benchmarks. Do not average</td></tr>
              </tbody>
            </table>

            <h2>Reading</h2>
            <ul>
              <li>mock, airline, and retail validate the adapter and verifier path.</li>
              <li>The published telecom row only keeps the passing <code>gpt-5.2</code> PAYG user route result with <code>max_steps=200</code>.</li>
              <li><code>gpt-5.2</code> is not currently supported by the Codex subscription backend, so only the PAYG user route is counted. The interrupted subscription attempt is excluded.</li>
              <li>banking_knowledge avoids the sandbox dependency with <code>--retrieval-config bm25</code>, but needs stronger user-side tool policy.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
