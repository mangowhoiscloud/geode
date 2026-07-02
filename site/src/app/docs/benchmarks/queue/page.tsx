import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Benchmark queue — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/queue"
      title="Benchmark queue"
      titleKo="Benchmark queue"
      summary="The current GEODE benchmark execution order after the MCPMark filesystem/easy baseline."
      summaryKo="MCPMark filesystem/easy baseline 이후의 현재 GEODE benchmark 실행 순서입니다."
    >
      <Bi
        ko={
          <>
            <p>
              이 큐는 GEODE benchmark를 한 번에 섞어 평균내지 않기 위한 운영
              순서입니다. 각 항목은 별도 harness revision, model route, artifact
              path, 비교 가능성 판정을 가진 독립 run record로 공개합니다.
            </p>

            <h2>현재 순서</h2>
            <table>
              <thead>
                <tr>
                  <th>순위</th>
                  <th>Benchmark</th>
                  <th>첫 목표</th>
                  <th>완료 기준</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>1</td>
                  <td>MCPMark Verified</td>
                  <td><code>easy</code> across available MCPs, then Verified filesystem slice</td>
                  <td>GEODE adapter로 verifier-backed result 생성</td>
                </tr>
                <tr>
                  <td>2</td>
                  <td>τ²-bench</td>
                  <td><code>mock</code> smoke, then Telecom small runs with separate <code>gpt-4.1</code> and <code>gpt-5.2</code> user simulators</td>
                  <td>domain split, user simulator, trial 수를 result page에 명시</td>
                </tr>
                <tr>
                  <td>3</td>
                  <td>BFCL V4</td>
                  <td>Agentic subset first</td>
                  <td>function-calling route와 aggregation을 고정</td>
                </tr>
                <tr>
                  <td>4</td>
                  <td>HAL Reliability</td>
                  <td>tau-bench airline single-rerun smoke</td>
                  <td>rerun consistency schema 확인</td>
                </tr>
                <tr>
                  <td>5</td>
                  <td>Terminal-Bench 2.0</td>
                  <td>1-task Docker/tmux smoke</td>
                  <td>post-run test artifact와 shell transcript 보존</td>
                </tr>
                <tr>
                  <td>6</td>
                  <td>Toolathlon</td>
                  <td>credential-free or lowest-credential smoke</td>
                  <td>MCP app surface, turn cap, credential caveats 기록</td>
                </tr>
              </tbody>
            </table>

            <h2>진행 규칙</h2>
            <ul>
              <li>각 benchmark는 <code>Benchmark publishing cycle</code>을 하나씩 통과합니다.</li>
              <li>τ²-bench는 사용자 지시에 따라 BFCL V4보다 먼저 진행합니다.</li>
              <li>Live run은 model route, subscription/API 구분, user simulator를 결과에 남깁니다.</li>
              <li>τ²-bench의 <code>gpt-4.1</code> user run과 <code>gpt-5.2</code> user run은 별도 비교군으로 보관합니다.</li>
              <li>공개 점수는 verifier-backed artifact가 있는 경우에만 추가합니다.</li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm">
              내부 큐는 <code>docs/eval/README.md</code>와{" "}
              <code>docs/eval/frontier-agentic-tool-use-benchmark-cases.md</code>에
              기록됩니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              This queue keeps GEODE benchmark publication sequential instead of
              mixing unrelated scores into one average. Each item gets its own
              harness revision, model route, artifact path, and comparability
              decision.
            </p>

            <h2>Current order</h2>
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Benchmark</th>
                  <th>First target</th>
                  <th>Exit criterion</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>1</td>
                  <td>MCPMark Verified</td>
                  <td><code>easy</code> across available MCPs, then Verified filesystem slice</td>
                  <td>Verifier-backed result through the GEODE adapter</td>
                </tr>
                <tr>
                  <td>2</td>
                  <td>τ²-bench</td>
                  <td><code>mock</code> smoke, then Telecom small runs with separate <code>gpt-4.1</code> and <code>gpt-5.2</code> user simulators</td>
                  <td>Domain split, user simulator, and trial count published</td>
                </tr>
                <tr>
                  <td>3</td>
                  <td>BFCL V4</td>
                  <td>Agentic subset first</td>
                  <td>Function-calling route and aggregation pinned</td>
                </tr>
                <tr>
                  <td>4</td>
                  <td>HAL Reliability</td>
                  <td>tau-bench airline single-rerun smoke</td>
                  <td>Rerun consistency schema validated</td>
                </tr>
                <tr>
                  <td>5</td>
                  <td>Terminal-Bench 2.0</td>
                  <td>1-task Docker/tmux smoke</td>
                  <td>Post-run test artifact and shell transcript preserved</td>
                </tr>
                <tr>
                  <td>6</td>
                  <td>Toolathlon</td>
                  <td>credential-free or lowest-credential smoke</td>
                  <td>MCP app surface, turn cap, and credential caveats recorded</td>
                </tr>
              </tbody>
            </table>

            <h2>Rules</h2>
            <ul>
              <li>Each benchmark passes through one <code>Benchmark publishing cycle</code>.</li>
              <li>τ²-bench runs before BFCL V4 by operator priority.</li>
              <li>Live runs record model route, subscription/API source, and user simulator.</li>
              <li>τ²-bench <code>gpt-4.1</code> user runs and <code>gpt-5.2</code> user runs stay in separate comparator groups.</li>
              <li>Public scores are added only when backed by verifier artifacts.</li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm">
              The internal queue is tracked in <code>docs/eval/README.md</code>{" "}
              and <code>docs/eval/frontier-agentic-tool-use-benchmark-cases.md</code>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
