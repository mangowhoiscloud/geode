import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "MCPMark Verified available services — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/mcpmark/verified-available"
      title="MCPMark Verified: available services"
      titleKo="MCPMark Verified: available services"
      summary="Verifier-backed GEODE run record for the MCPMark standard services that were runnable locally: filesystem, postgres, and github."
      summaryKo="로컬에서 실행 가능한 MCPMark standard service인 filesystem, postgres, github에 대한 verifier-backed GEODE 실측 기록입니다."
    >
      <Bi
        ko={
          <>
            <h2>결과 요약</h2>
            <p>
              이 run은 MCPMark 전체 leaderboard 점수가 아닙니다. GEODE가 로컬에서
              준비할 수 있었던 standard service slice만 측정했습니다:
              <code>filesystem</code>, <code>postgres</code>, <code>github</code>.
              모델 route는 GEODE의 Codex subscription route인
              <code>gpt-5.5</code> / <code>xhigh</code>입니다.
            </p>
            <table>
              <thead>
                <tr><th>Service</th><th>Tasks</th><th>Passed</th><th>Accuracy</th><th>Recorded time</th></tr>
              </thead>
              <tbody>
                <tr><td><code>filesystem/standard</code></td><td>30</td><td>25</td><td><strong>83.3%</strong></td><td>13580.6s over 29 recorded tasks</td></tr>
                <tr><td><code>postgres/standard</code></td><td>21</td><td>20</td><td><strong>95.2%</strong></td><td>8765.7s</td></tr>
                <tr><td><code>github/standard</code></td><td>23</td><td>19</td><td><strong>82.6%</strong></td><td>16476.3s</td></tr>
                <tr><td><strong>Measured total</strong></td><td><strong>74</strong></td><td><strong>64</strong></td><td><strong>86.5%</strong></td><td>38822.6s recorded</td></tr>
              </tbody>
            </table>

            <h2>비교 가능성</h2>
            <table>
              <thead>
                <tr><th>비교 대상</th><th>판정</th></tr>
              </thead>
              <tbody>
                <tr><td>동일 MCPMark commit의 filesystem/postgres/github standard slice</td><td>직접 비교 가능</td></tr>
                <tr><td>MCPMark Verified full leaderboard</td><td>직접 비교 불가. Notion/Playwright/WebArena가 제외됨</td></tr>
                <tr><td>Agent-World식 MCP 평균</td><td>방향성 참고 가능. 단, 서비스 구성이 다르면 평균내지 않음</td></tr>
                <tr><td>MCPMark <code>filesystem/easy</code></td><td>별도 smoke subset. 이 페이지의 standard 결과와 분리</td></tr>
              </tbody>
            </table>

            <h2>제외된 service</h2>
            <table>
              <thead>
                <tr><th>Service</th><th>상태</th><th>이유</th></tr>
              </thead>
              <tbody>
                <tr><td><code>notion</code></td><td>blocked</td><td><code>notion_state.json</code>이 없는 환경이라 verifier-backed run을 만들 수 없었습니다.</td></tr>
                <tr><td><code>playwright</code> / WebArena</td><td>blocked</td><td>필수 Docker image와 browser service stack이 준비되지 않았습니다.</td></tr>
              </tbody>
            </table>

            <h2>실행 조건</h2>
            <table>
              <tbody>
                <tr><td>Run date</td><td>2026-07-04 KST</td></tr>
                <tr><td>Agent</td><td>GEODE local MCPMark adapter</td></tr>
                <tr><td>Model route</td><td>GEODE <code>gpt-5.5</code>, provider <code>openai-codex</code>, source <code>subscription</code></td></tr>
                <tr><td>Reasoning effort</td><td><code>xhigh</code></td></tr>
                <tr><td>Harness</td><td><code>eval-sys/mcpmark@cd45b7f</code></td></tr>
                <tr><td>GitHub MCP server</td><td><code>ghcr.io/github/github-mcp-server:v0.15.0</code></td></tr>
                <tr><td>Postgres MCP server</td><td><code>postgres-mcp==0.3.0</code></td></tr>
              </tbody>
            </table>

            <h2>실행 명령</h2>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \\
PYTHONPATH=<geode-worktree>:<geode-site-packages> \\
GITHUB_EVAL_ORG=mangowhoiscloud \\
GEODE_MCPMARK_GITHUB_REPO_VISIBILITY=public \\
.venv/bin/python pipeline.py \\
  --mcp <filesystem|postgres|github> \\
  --task-suite standard \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 1500 \\
  --exp-name geode-gpt55-xhigh-20260704-mcpmark-verified-<service> \\
  --output-dir ./results-geode-agentworld`}</code></pre>
            <p>
              GitHub task는 transient fixture repository를 public으로 전환해
              Docker GitHub MCP server가 일반 public-repo 흐름으로 접근하도록
              했습니다. MCPMark cleanup 이후 잔여 repo는 없었습니다.
            </p>

            <h2>실패 항목</h2>
            <table>
              <thead>
                <tr><th>Service</th><th>Task</th><th>Failure</th></tr>
              </thead>
              <tbody>
                <tr><td><code>filesystem</code></td><td><code>desktop_template/budget_computation</code></td><td>Verifier failed</td></tr>
                <tr><td><code>filesystem</code></td><td><code>papers/author_folders</code></td><td>Two attempts ended without meta output; counted as failed no-result transport run</td></tr>
                <tr><td><code>filesystem</code></td><td><code>papers/find_math_paper</code></td><td>Verifier failed</td></tr>
                <tr><td><code>filesystem</code></td><td><code>student_database/english_talent</code></td><td>Verifier failed</td></tr>
                <tr><td><code>filesystem</code></td><td><code>threestudio/output_analysis</code></td><td>Verifier failed</td></tr>
                <tr><td><code>postgres</code></td><td><code>employees/employee_performance_analysis</code></td><td>Verifier failed</td></tr>
                <tr><td><code>github</code></td><td><code>claude-code/label_color_standardization</code></td><td>Fixture duplication first, then agent-level verification failure on retry</td></tr>
                <tr><td><code>github</code></td><td><code>mcpmark-cicd/deployment_status_workflow</code></td><td>Verifier failed</td></tr>
                <tr><td><code>github</code></td><td><code>missing-semester/assign_contributor_labels</code></td><td>Used suffixed transient usernames instead of canonical contributor labels</td></tr>
                <tr><td><code>github</code></td><td><code>missing-semester/find_salient_file</code></td><td><code>ANSWER.md</code> was not created on the required master branch</td></tr>
              </tbody>
            </table>
          </>
        }
        en={
          <>
            <h2>Result Summary</h2>
            <p>
              This is not a full MCPMark leaderboard score. It measures only the
              standard service slices that were runnable in the local GEODE
              environment: <code>filesystem</code>, <code>postgres</code>, and
              <code>github</code>. The model route is GEODE&apos;s Codex
              subscription route with <code>gpt-5.5</code> and <code>xhigh</code>.
            </p>
            <table>
              <thead>
                <tr><th>Service</th><th>Tasks</th><th>Passed</th><th>Accuracy</th><th>Recorded time</th></tr>
              </thead>
              <tbody>
                <tr><td><code>filesystem/standard</code></td><td>30</td><td>25</td><td><strong>83.3%</strong></td><td>13580.6s over 29 recorded tasks</td></tr>
                <tr><td><code>postgres/standard</code></td><td>21</td><td>20</td><td><strong>95.2%</strong></td><td>8765.7s</td></tr>
                <tr><td><code>github/standard</code></td><td>23</td><td>19</td><td><strong>82.6%</strong></td><td>16476.3s</td></tr>
                <tr><td><strong>Measured total</strong></td><td><strong>74</strong></td><td><strong>64</strong></td><td><strong>86.5%</strong></td><td>38822.6s recorded</td></tr>
              </tbody>
            </table>

            <h2>Comparability</h2>
            <table>
              <thead>
                <tr><th>Comparator</th><th>Status</th></tr>
              </thead>
              <tbody>
                <tr><td>Same MCPMark commit and filesystem/postgres/github standard slices</td><td>Directly comparable</td></tr>
                <tr><td>Full MCPMark Verified leaderboard</td><td>Not directly comparable. Notion and Playwright/WebArena were excluded</td></tr>
                <tr><td>Agent-World style MCP average</td><td>Directional only. Do not average across different service sets</td></tr>
                <tr><td>MCPMark <code>filesystem/easy</code></td><td>Separate smoke subset. Keep it separate from this standard result</td></tr>
              </tbody>
            </table>

            <h2>Excluded Services</h2>
            <table>
              <thead>
                <tr><th>Service</th><th>Status</th><th>Reason</th></tr>
              </thead>
              <tbody>
                <tr><td><code>notion</code></td><td>blocked</td><td>No <code>notion_state.json</code> was available, so a verifier-backed run could not be produced.</td></tr>
                <tr><td><code>playwright</code> / WebArena</td><td>blocked</td><td>Required Docker images and browser service stack were absent.</td></tr>
              </tbody>
            </table>

            <h2>Run Spec</h2>
            <table>
              <tbody>
                <tr><td>Run date</td><td>2026-07-04 KST</td></tr>
                <tr><td>Agent</td><td>GEODE local MCPMark adapter</td></tr>
                <tr><td>Model route</td><td>GEODE <code>gpt-5.5</code>, provider <code>openai-codex</code>, source <code>subscription</code></td></tr>
                <tr><td>Reasoning effort</td><td><code>xhigh</code></td></tr>
                <tr><td>Harness</td><td><code>eval-sys/mcpmark@cd45b7f</code></td></tr>
                <tr><td>GitHub MCP server</td><td><code>ghcr.io/github/github-mcp-server:v0.15.0</code></td></tr>
                <tr><td>Postgres MCP server</td><td><code>postgres-mcp==0.3.0</code></td></tr>
              </tbody>
            </table>

            <h2>Run Command</h2>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \\
PYTHONPATH=<geode-worktree>:<geode-site-packages> \\
GITHUB_EVAL_ORG=mangowhoiscloud \\
GEODE_MCPMARK_GITHUB_REPO_VISIBILITY=public \\
.venv/bin/python pipeline.py \\
  --mcp <filesystem|postgres|github> \\
  --task-suite standard \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 1500 \\
  --exp-name geode-gpt55-xhigh-20260704-mcpmark-verified-<service> \\
  --output-dir ./results-geode-agentworld`}</code></pre>
            <p>
              GitHub tasks converted transient fixture repositories to public
              while running so the Docker GitHub MCP server could use normal
              public-repo semantics. MCPMark cleanup removed all transient repos.
            </p>

            <h2>Failures</h2>
            <table>
              <thead>
                <tr><th>Service</th><th>Task</th><th>Failure</th></tr>
              </thead>
              <tbody>
                <tr><td><code>filesystem</code></td><td><code>desktop_template/budget_computation</code></td><td>Verifier failed</td></tr>
                <tr><td><code>filesystem</code></td><td><code>papers/author_folders</code></td><td>Two attempts ended without meta output; counted as failed no-result transport run</td></tr>
                <tr><td><code>filesystem</code></td><td><code>papers/find_math_paper</code></td><td>Verifier failed</td></tr>
                <tr><td><code>filesystem</code></td><td><code>student_database/english_talent</code></td><td>Verifier failed</td></tr>
                <tr><td><code>filesystem</code></td><td><code>threestudio/output_analysis</code></td><td>Verifier failed</td></tr>
                <tr><td><code>postgres</code></td><td><code>employees/employee_performance_analysis</code></td><td>Verifier failed</td></tr>
                <tr><td><code>github</code></td><td><code>claude-code/label_color_standardization</code></td><td>Fixture duplication first, then agent-level verification failure on retry</td></tr>
                <tr><td><code>github</code></td><td><code>mcpmark-cicd/deployment_status_workflow</code></td><td>Verifier failed</td></tr>
                <tr><td><code>github</code></td><td><code>missing-semester/assign_contributor_labels</code></td><td>Used suffixed transient usernames instead of canonical contributor labels</td></tr>
                <tr><td><code>github</code></td><td><code>missing-semester/find_salient_file</code></td><td><code>ANSWER.md</code> was not created on the required master branch</td></tr>
              </tbody>
            </table>
          </>
        }
      />
    </DocsShell>
  );
}
