import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "tau2: domain matrix — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/tau2/domain-smoke"
      title="tau2: domain matrix"
      titleKo="tau2: domain matrix"
      summary="GEODE tau2 smoke and native user-simulator full-domain measurements across mock, airline, retail, telecom, and banking_knowledge."
      summaryKo="GEODE tau2 smoke와 native user-simulator full-domain 실측을 mock, airline, retail, telecom, banking_knowledge별로 기록합니다."
    >
      <Bi
        ko={
          <>
            <h2>결과 요약</h2>
            <p>
              이 페이지는 두 track을 분리합니다. 첫째는 adapter 회귀 확인용
              smoke matrix이고, 둘째는 native tau2 <code>user_simulator</code>를
              사용한 full-domain comparator입니다. Agent-World식 비교에는
              둘째 track만 사용합니다.
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
                <tr><td>Run date</td><td>2026-07-03 / 2026-07-04 KST</td></tr>
                <tr><td>Harness revision</td><td><code>sierra-research/tau2-bench@1901a30</code>, <code>tau2==1.0.0</code></td></tr>
                <tr><td>GEODE version</td><td><code>v0.99.269</code></td></tr>
                <tr><td>Smoke route</td><td><code>geode_agent</code> + <code>geode_user</code>, <code>gpt-5.5</code> subscription</td></tr>
                <tr><td>Comparator route</td><td><code>geode_agent</code>, <code>gpt-5.2</code>, OpenAI PAYG, effort <code>high</code>; native tau2 <code>user_simulator</code>, <code>gpt-4.1-2025-04-14</code></td></tr>
                <tr><td>Trials</td><td>1 per row</td></tr>
                <tr><td>Purpose</td><td>adapter calibration plus Agent-World-style comparator evidence</td></tr>
              </tbody>
            </table>

            <h2>Native user_simulator full-domain 결과</h2>
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Tasks</th>
                  <th>Reward / pass^1</th>
                  <th>Action checks</th>
                  <th>Duration</th>
                  <th>판독</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>airline</code></td><td>50</td><td><strong>0.820</strong> (41 / 50)</td><td>read 81/91, write 33/49</td><td>avg 284.10s / max 979.65s</td><td>GEODE 내부 비교용으로 유지. OpenAI 공식 GPT-5.2 Tau2 headline은 Airline을 제외합니다.</td></tr>
                <tr><td><code>retail</code></td><td>114</td><td><strong>0.763</strong> (87 / 114)</td><td>read 320/354, write 140/174</td><td>avg 206.52s / max 873.92s</td><td>자연어 응답은 그럴듯하지만 필수 DB/write side effect 누락이 많았습니다.</td></tr>
                <tr><td><code>telecom</code></td><td>114</td><td><strong>0.877</strong> (100 / 114)</td><td>write 471/496, generic 20/20</td><td>avg 252.87s / max 818.58s</td><td>MMS/APN/permission/roaming 조합에서 필수 action 하나를 놓치는 실패가 집중됐습니다.</td></tr>
                <tr><td><strong>weighted avg</strong></td><td>278</td><td><strong>0.820</strong> (228 / 278)</td><td>domain별 action type 상이</td><td>-</td><td>mock smoke 제외. Agent-World식 비교용 내부 aggregate입니다.</td></tr>
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

            <h2>Comparator 실행 명령 패턴</h2>
            <pre><code>{`uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain <domain> \\
  --task-split-name base \\
  --num-tasks <50|114> \\
  --num-trials 1 \\
  --max-concurrency <2|4> \\
  --max-steps 200 \\
  --timeout 3600 \\
  --model gpt-5.2 \\
  --provider openai \\
  --source payg \\
  --effort high \\
  --time-budget-s 600 \\
  --user user_simulator \\
  --user-llm gpt-4.1-2025-04-14 \\
  --user-provider openai \\
  --user-source payg \\
  --user-effort medium \\
  --user-time-budget-s 120 \\
  --save-to <stable-run-id> \\
  --log-level INFO \\
  --auto-resume`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Raw results:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-2-high-native-user-*-base-20260703/results.json</code>
              <br />
              Smoke results:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-*/results.json</code>
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
                <tr><td>tau2 leaderboard</td><td>조건 차이를 명시한 정성 비교만 가능. OpenAI 공식 headline은 별도 research setup입니다.</td></tr>
                <tr><td>native tau2 <code>user_simulator</code> + <code>gpt-5.2</code></td><td>이 페이지의 full-domain comparator track</td></tr>
                <tr><td>MCPMark / BFCL / Terminal-Bench</td><td>다른 benchmark. 평균내지 않음</td></tr>
              </tbody>
            </table>

            <h2>판독</h2>
            <ul>
              <li>mock, airline, retail은 adapter와 verifier path가 정상 동작합니다.</li>
              <li>full-domain comparator는 <code>gpt-5.2</code> PAYG agent와 native <code>user_simulator</code>로 측정했습니다.</li>
              <li><code>gpt-5.2</code>는 현재 Codex subscription backend에서 지원되지 않아 PAYG user route로만 기록했습니다. 중단된 subscription 시도는 결과에 포함하지 않았습니다.</li>
              <li>banking_knowledge는 <code>--retrieval-config bm25</code> 옵션으로 sandbox 의존성을 피했지만, user-side tool policy 보강이 필요합니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Result Summary</h2>
            <p>
              This page separates two tracks: adapter regression smoke rows and
              full-domain comparator rows using tau2&apos;s native{" "}
              <code>user_simulator</code>. Use only the second track for
              Agent-World-style comparisons.
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
                <tr><td>Run date</td><td>2026-07-03 / 2026-07-04 KST</td></tr>
                <tr><td>Harness revision</td><td><code>sierra-research/tau2-bench@1901a30</code>, <code>tau2==1.0.0</code></td></tr>
                <tr><td>GEODE version</td><td><code>v0.99.269</code></td></tr>
                <tr><td>Smoke route</td><td><code>geode_agent</code> + <code>geode_user</code>, <code>gpt-5.5</code> subscription</td></tr>
                <tr><td>Comparator route</td><td><code>geode_agent</code>, <code>gpt-5.2</code>, OpenAI PAYG, effort <code>high</code>; native tau2 <code>user_simulator</code>, <code>gpt-4.1-2025-04-14</code></td></tr>
                <tr><td>Trials</td><td>1 per row</td></tr>
                <tr><td>Purpose</td><td>adapter calibration plus Agent-World-style comparator evidence</td></tr>
              </tbody>
            </table>

            <h2>Native User-Simulator Full-Domain Results</h2>
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Tasks</th>
                  <th>Reward / pass^1</th>
                  <th>Action checks</th>
                  <th>Duration</th>
                  <th>Reading</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>airline</code></td><td>50</td><td><strong>0.820</strong> (41 / 50)</td><td>read 81/91, write 33/49</td><td>avg 284.10s / max 979.65s</td><td>Kept for internal comparison. OpenAI excludes Airline from its GPT-5.2 Tau2 headline.</td></tr>
                <tr><td><code>retail</code></td><td>114</td><td><strong>0.763</strong> (87 / 114)</td><td>read 320/354, write 140/174</td><td>avg 206.52s / max 873.92s</td><td>Many failures were missing required DB/write side effects despite plausible natural-language replies.</td></tr>
                <tr><td><code>telecom</code></td><td>114</td><td><strong>0.877</strong> (100 / 114)</td><td>write 471/496, generic 20/20</td><td>avg 252.87s / max 818.58s</td><td>Failures cluster around MMS/APN/permission/roaming combinations with one omitted required action.</td></tr>
                <tr><td><strong>weighted avg</strong></td><td>278</td><td><strong>0.820</strong> (228 / 278)</td><td>varies by domain</td><td>-</td><td>Excludes mock smoke. Internal Agent-World-style aggregate.</td></tr>
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

            <h2>Comparator Command Pattern</h2>
            <pre><code>{`uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain <domain> \\
  --task-split-name base \\
  --num-tasks <50|114> \\
  --num-trials 1 \\
  --max-concurrency <2|4> \\
  --max-steps 200 \\
  --timeout 3600 \\
  --model gpt-5.2 \\
  --provider openai \\
  --source payg \\
  --effort high \\
  --time-budget-s 600 \\
  --user user_simulator \\
  --user-llm gpt-4.1-2025-04-14 \\
  --user-provider openai \\
  --user-source payg \\
  --user-effort medium \\
  --user-time-budget-s 120 \\
  --save-to <stable-run-id> \\
  --log-level INFO \\
  --auto-resume`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Raw results:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-2-high-native-user-*-base-20260703/results.json</code>
              <br />
              Smoke results:
              <br />
              <code>artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-*/results.json</code>
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
                <tr><td>tau2 leaderboard</td><td>Qualitative comparison only unless the run specs are aligned. OpenAI&apos;s headline uses a separate research setup.</td></tr>
                <tr><td>Native tau2 <code>user_simulator</code> + <code>gpt-5.2</code></td><td>The full-domain comparator track on this page</td></tr>
                <tr><td>MCPMark / BFCL / Terminal-Bench</td><td>Different benchmarks. Do not average</td></tr>
              </tbody>
            </table>

            <h2>Reading</h2>
            <ul>
              <li>mock, airline, and retail validate the adapter and verifier path.</li>
              <li>The full-domain comparator uses a <code>gpt-5.2</code> PAYG agent and native <code>user_simulator</code>.</li>
              <li><code>gpt-5.2</code> is not currently supported by the Codex subscription backend, so only the PAYG user route is counted. The interrupted subscription attempt is excluded.</li>
              <li>banking_knowledge avoids the sandbox dependency with <code>--retrieval-config bm25</code>, but needs stronger user-side tool policy.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
