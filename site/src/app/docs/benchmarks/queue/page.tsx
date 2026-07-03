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
              실측 표와 클릭 가능한 run record는{" "}
              <a href="/geode/docs/benchmarks/results">Benchmark measurements</a>에
              MCPMark와 Tau2 그룹으로 모읍니다.
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
                  <td><code>mock</code> smoke with <code>geode_agent</code> + <code>geode_user</code> over subscription, then Telecom small run</td>
                  <td>domain split, user route, trial 수를 result page에 명시</td>
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

            <h2>서빙 페이지 형태</h2>
            <p>
              새 benchmark 결과 페이지는 <code>MCPMark: filesystem/easy</code>의
              레코드형 구성을 표준으로 씁니다. 왼쪽 navigation에는 benchmark와
              suite가 짧게 보이지만, 본문 첫 화면은 숫자만 던지지 않고 route,
              artifact, caveat가 같이 보이는 ledger여야 합니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Section</th>
                  <th>화면에 보여야 하는 정보</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Result summary</td><td>benchmark, suite/domain, run date, harness revision, agent/model route, task 수, score</td></tr>
                <tr><td>Comparability</td><td>직접 비교 가능 / 방향성 참고 / 비교 불가 대상을 분리</td></tr>
                <tr><td>Run command</td><td>재현 명령, auth placeholder, subscription/API route caveat</td></tr>
                <tr><td>Artifacts</td><td>raw result directory, transcript/log, verifier output 위치</td></tr>
                <tr><td>Task or domain rows</td><td>task별 PASS/FAIL, reward, termination, duration, rounds/tokens 가능하면 포함</td></tr>
                <tr><td>Interpretation</td><td>실패 원인, adapter 한계, 다음 측정으로 넘길 항목</td></tr>
              </tbody>
            </table>

            <h2>현재 공개 페이지 계획</h2>
            <table>
              <thead>
                <tr>
                  <th>Route</th>
                  <th>역할</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>/docs/benchmarks/mcpmark/filesystem-easy</code></td><td>MCPMark detailed run record의 기준 페이지</td><td>게시됨</td></tr>
                <tr><td><code>/docs/benchmarks/mcpmark/service-matrix</code></td><td>MCP별 task 수, credential/infra, GEODE adapter 지원 상태</td><td>추가</td></tr>
                <tr><td><code>/docs/benchmarks/tau2/mock-smoke</code></td><td>tau2 단일 mock verifier-backed record</td><td>게시됨</td></tr>
                <tr><td><code>/docs/benchmarks/tau2/domain-smoke</code></td><td>mock/airline/retail/telecom/banking smoke matrix와 실패 caveat</td><td>추가</td></tr>
              </tbody>
            </table>

            <h2>진행 규칙</h2>
            <ul>
              <li>각 benchmark는 <code>Benchmark publishing cycle</code>을 하나씩 통과합니다.</li>
              <li>τ²-bench는 사용자 지시에 따라 BFCL V4보다 먼저 진행합니다.</li>
              <li>Live run은 model route, subscription/API 구분, user simulator를 결과에 남깁니다.</li>
              <li>τ²-bench의 기본 run은 agent와 user 모두 GEODE subscription route로 실행합니다.</li>
              <li>native tau2 <code>gpt-4.1</code>/<code>gpt-5.2</code> user simulator run은 별도 비교군으로 보관합니다.</li>
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
              The measured tables and clickable run records live in{" "}
              <a href="/geode/docs/benchmarks/results">Benchmark measurements</a>,
              grouped under MCPMark and Tau2.
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
                  <td><code>mock</code> smoke with <code>geode_agent</code> + <code>geode_user</code> over subscription, then Telecom small run</td>
                  <td>Domain split, user route, and trial count published</td>
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

            <h2>Serving Page Shape</h2>
            <p>
              New benchmark result pages use the same record-style structure as
              <code>MCPMark: filesystem/easy</code>. The navigation label stays
              short, but the first screen of the body must show the route,
              artifact, and caveat next to the score.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Section</th>
                  <th>What must be visible</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Result summary</td><td>benchmark, suite/domain, run date, harness revision, agent/model route, task count, score</td></tr>
                <tr><td>Comparability</td><td>directly comparable, directional, and not-comparable targets separated</td></tr>
                <tr><td>Run command</td><td>reproduction command, auth placeholder, subscription/API route caveat</td></tr>
                <tr><td>Artifacts</td><td>raw result directory, transcript/log, and verifier output pointers</td></tr>
                <tr><td>Task or domain rows</td><td>per-task PASS/FAIL, reward, termination, duration, and rounds/tokens when available</td></tr>
                <tr><td>Interpretation</td><td>failure cause, adapter limitation, and next measured step</td></tr>
              </tbody>
            </table>

            <h2>Current Public Page Plan</h2>
            <table>
              <thead>
                <tr>
                  <th>Route</th>
                  <th>Purpose</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>/docs/benchmarks/mcpmark/filesystem-easy</code></td><td>Reference page for detailed MCPMark run records</td><td>Published</td></tr>
                <tr><td><code>/docs/benchmarks/mcpmark/service-matrix</code></td><td>MCP task counts, credentials, infra, and GEODE adapter support</td><td>Added</td></tr>
                <tr><td><code>/docs/benchmarks/tau2/mock-smoke</code></td><td>Single tau2 mock verifier-backed run record</td><td>Published</td></tr>
                <tr><td><code>/docs/benchmarks/tau2/domain-smoke</code></td><td>mock/airline/retail/telecom/banking smoke matrix and caveats</td><td>Added</td></tr>
              </tbody>
            </table>

            <h2>Rules</h2>
            <ul>
              <li>Each benchmark passes through one <code>Benchmark publishing cycle</code>.</li>
              <li>τ²-bench runs before BFCL V4 by operator priority.</li>
              <li>Live runs record model route, subscription/API source, and user simulator.</li>
              <li>τ²-bench defaults to GEODE subscription route for both agent and user.</li>
              <li>Native tau2 <code>gpt-4.1</code>/<code>gpt-5.2</code> user simulator runs stay in separate comparator groups.</li>
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
