import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "MCPMark service matrix — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/mcpmark/service-matrix"
      title="MCPMark: service matrix"
      titleKo="MCPMark: service matrix"
      summary="MCPMark service coverage, task counts, credential requirements, and GEODE adapter support status."
      summaryKo="MCPMark 서비스별 task 수, credential 요구사항, GEODE adapter 지원 상태입니다."
    >
      <Bi
        ko={
          <>
            <h2>결과 요약</h2>
            <p>
              이 페이지는 MCPMark 전체를 한 번에 실행한 점수가 아니라, GEODE가
              어떤 MCPMark service를 지금 바로 실행할 수 있고 어떤 service가
              credential 또는 transport 보강을 요구하는지 보여주는 coverage
              ledger입니다. 상세 실측 점수는 service별 run record 페이지로
              분리합니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Benchmark</td><td>MCPMark</td></tr>
                <tr><td>Harness revision</td><td><code>eval-sys/mcpmark@cd45b7f</code></td></tr>
                <tr><td>GEODE adapter</td><td>local <code>BaseMCPAgent</code> adapter wrapping <code>AgenticLoop</code></td></tr>
                <tr><td>Model route</td><td><code>gpt-5.5</code>, provider <code>openai-codex</code>, source <code>subscription</code>, effort <code>xhigh</code></td></tr>
                <tr><td>Verified run</td><td><code>filesystem/easy</code> 10 / 10 published separately</td></tr>
                <tr><td>Single-task rerun</td><td><code>file_context/uppercase</code> 1 / 1, 165.7s, 8 tools / 4 rounds</td></tr>
                <tr><td>Notion unblock smoke</td><td><code>toronto_guide/simple__change_color</code> 1 / 1, duplication 58.9s, agent 216.8s / 8 rounds (2026-07-10)</td></tr>
              </tbody>
            </table>

            <h2>Service coverage</h2>
            <table>
              <thead>
                <tr>
                  <th>Service</th>
                  <th>Easy</th>
                  <th>Standard</th>
                  <th>Adapter 상태</th>
                  <th>Blocker</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>filesystem</code></td><td>10</td><td>30</td><td>실측 가능</td><td>없음. easy 10/10 게시</td></tr>
                <tr><td><code>notion</code></td><td>10</td><td>28</td><td>실측 가능 (easy smoke 1/1, 2026-07-10)</td><td>없음. 07-04 스톨 원인은 브라우저 세션 만료로 확정, 재발급 절차 확립. standard 28건 미측정</td></tr>
                <tr><td><code>github</code></td><td>10</td><td>23</td><td>standard run 완료</td><td>19 / 23, Docker GitHub MCP server. State Duplication Error 6건의 원인(<code>GITHUB_EVAL_ORG</code> 미영속)은 2026-07-10 제거, 재실행 가능</td></tr>
                <tr><td><code>postgres</code></td><td>10</td><td>21</td><td>standard run 완료</td><td>20 / 21, <code>postgres-mcp==0.3.0</code></td></tr>
                <tr><td><code>playwright</code></td><td>0</td><td>4</td><td>실행 준비 완료 (2026-07-10)</td><td>없음. live-web 태스크, <code>@playwright/mcp@0.0.68</code> 기동 확인. 4건 미측정</td></tr>
                <tr><td><code>playwright_webarena</code></td><td>10</td><td>21</td><td>stdio adapter 준비</td><td>WebArena Docker 이미지 tar 실측 119GiB(shopping 62 + admin 8 + reddit 49) vs 로컬 여유 13GiB. 외장 볼륨 또는 VM 필요 (2026-07-10 실측)</td></tr>
                <tr><td><code>insforge</code></td><td>확인 필요</td><td>확인 필요</td><td>조사 중</td><td><code>INSFORGE_API_KEY</code>, <code>INSFORGE_BACKEND_URL</code>, task manager 인자 호환성 확인 필요</td></tr>
                <tr><td><code>supabase</code></td><td>확인 필요</td><td>확인 필요</td><td>미지원</td><td>MCPMark HTTP MCP transport. GEODE <code>MCPServerManager</code>는 현재 stdio 중심</td></tr>
              </tbody>
            </table>

            <h2>실행 명령</h2>
            <p>
              에이전트 등록은 커밋된 런처 <code>plugins/benchmark_harness/run_mcpmark.py</code>가
              담당합니다. upstream <code>pipeline.py</code>는 패치하지 않습니다.
            </p>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
set -a; source .mcp_env; set +a
OPENAI_API_KEY=dummy \\
.venv/bin/python -m plugins.benchmark_harness.run_mcpmark \\
  --mcp <service> \\
  --task-suite <easy|standard> \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 1200 \\
  --exp-name <stable-run-id> \\
  --output-dir ./results-geode-agentworld`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Published filesystem run:
              <br />
              <code>artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-filesystem-easy/geode-gpt-5-5-xhigh__filesystem-easy/run-1</code>
            </p>
            <p>
              Single-task rerun:
              <br />
              <code>artifacts/eval/harnesses/mcpmark/results-geode-live-rerun/geode-gpt55-xhigh-filesystem-uppercase-rerun-20260703/geode-gpt-5-5-xhigh__filesystem-easy/run-1</code>
            </p>

            <h2>판독</h2>
            <ul>
              <li>2026-07-10 기준 5개 service(filesystem, notion, github, postgres, playwright)가 실행 가능 상태입니다. Notion은 세션 만료가 07-04 스톨의 원인이었고, 재로그인 후 easy smoke 1/1로 duplication→실행→검증 전 구간을 확인했습니다.</li>
              <li><code>playwright_webarena</code>만 남은 blocked로, WebArena 이미지 용량(실측 119GiB)이 로컬 디스크를 초과합니다.</li>
              <li>subscription 쿼터(429 usage_limit_reached)가 full-suite 연속 실행을 리셋 창 단위로 분할시킵니다. 429 실패는 점수에 포함하지 않고 해당 태스크를 재실행합니다.</li>
              <li>Supabase는 HTTP MCP transport 대응 없이는 GEODE adapter에서 바로 실행하지 않습니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Result Summary</h2>
            <p>
              This is not a full MCPMark score. It is a coverage ledger showing
              which MCPMark services GEODE can run now and which services need
              credentials, fixtures, or transport support. Detailed scores stay
              on separate service run-record pages.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Benchmark</td><td>MCPMark</td></tr>
                <tr><td>Harness revision</td><td><code>eval-sys/mcpmark@cd45b7f</code></td></tr>
                <tr><td>GEODE adapter</td><td>local <code>BaseMCPAgent</code> adapter wrapping <code>AgenticLoop</code></td></tr>
                <tr><td>Model route</td><td><code>gpt-5.5</code>, provider <code>openai-codex</code>, source <code>subscription</code>, effort <code>xhigh</code></td></tr>
                <tr><td>Verified run</td><td><code>filesystem/easy</code> 10 / 10 published separately</td></tr>
                <tr><td>Single-task rerun</td><td><code>file_context/uppercase</code> 1 / 1, 165.7s, 8 tools / 4 rounds</td></tr>
                <tr><td>Notion unblock smoke</td><td><code>toronto_guide/simple__change_color</code> 1 / 1, duplication 58.9s, agent 216.8s / 8 rounds (2026-07-10)</td></tr>
              </tbody>
            </table>

            <h2>Service Coverage</h2>
            <table>
              <thead>
                <tr>
                  <th>Service</th>
                  <th>Easy</th>
                  <th>Standard</th>
                  <th>Adapter status</th>
                  <th>Blocker</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>filesystem</code></td><td>10</td><td>30</td><td>Measured</td><td>None. easy 10/10 published</td></tr>
                <tr><td><code>notion</code></td><td>10</td><td>28</td><td>Runnable (easy smoke 1/1, 2026-07-10)</td><td>None. The 07-04 stall traced to an expired browser session; re-login procedure established. Standard 28 tasks not yet measured</td></tr>
                <tr><td><code>github</code></td><td>10</td><td>23</td><td>standard run complete</td><td>19 / 23, Docker GitHub MCP server. Root cause of 6 State Duplication Errors (unset <code>GITHUB_EVAL_ORG</code>) removed on 2026-07-10; rerun possible</td></tr>
                <tr><td><code>postgres</code></td><td>10</td><td>21</td><td>standard run complete</td><td>20 / 21, <code>postgres-mcp==0.3.0</code></td></tr>
                <tr><td><code>playwright</code></td><td>0</td><td>4</td><td>Ready to run (2026-07-10)</td><td>None. Live-web tasks; <code>@playwright/mcp@0.0.68</code> launch verified. 4 tasks not yet measured</td></tr>
                <tr><td><code>playwright_webarena</code></td><td>10</td><td>21</td><td>stdio adapter ready</td><td>WebArena Docker image tars measure 119GiB (shopping 62 + admin 8 + reddit 49) vs 13GiB free local disk. Needs an external volume or a VM (measured 2026-07-10)</td></tr>
                <tr><td><code>insforge</code></td><td>Needs check</td><td>Needs check</td><td>Under investigation</td><td><code>INSFORGE_API_KEY</code>, <code>INSFORGE_BACKEND_URL</code>, and task-manager argument compatibility need verification</td></tr>
                <tr><td><code>supabase</code></td><td>Needs check</td><td>Needs check</td><td>Unsupported</td><td>MCPMark HTTP MCP transport. GEODE <code>MCPServerManager</code> is currently stdio-centered</td></tr>
              </tbody>
            </table>

            <h2>Run Command</h2>
            <p>
              Agent registration is handled by the committed launcher
              <code>plugins/benchmark_harness/run_mcpmark.py</code>; the upstream
              <code>pipeline.py</code> is not patched.
            </p>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
set -a; source .mcp_env; set +a
OPENAI_API_KEY=dummy \\
.venv/bin/python -m plugins.benchmark_harness.run_mcpmark \\
  --mcp <service> \\
  --task-suite <easy|standard> \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 1200 \\
  --exp-name <stable-run-id> \\
  --output-dir ./results-geode-agentworld`}</code></pre>

            <h2>Artifact</h2>
            <p>
              Published filesystem run:
              <br />
              <code>artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-filesystem-easy/geode-gpt-5-5-xhigh__filesystem-easy/run-1</code>
            </p>
            <p>
              Single-task rerun:
              <br />
              <code>artifacts/eval/harnesses/mcpmark/results-geode-live-rerun/geode-gpt55-xhigh-filesystem-uppercase-rerun-20260703/geode-gpt-5-5-xhigh__filesystem-easy/run-1</code>
            </p>

            <h2>Reading</h2>
            <ul>
              <li>As of 2026-07-10, five services (filesystem, notion, github, postgres, playwright) are runnable. The Notion 07-04 stall traced to an expired browser session; after re-login an easy smoke passed 1/1 through duplication, execution, and verification.</li>
              <li><code>playwright_webarena</code> is the only remaining blocked service: the WebArena images (measured 119GiB) exceed local disk.</li>
              <li>The subscription quota (429 usage_limit_reached) splits full-suite execution into reset windows. 429 failures are excluded from scores and those tasks are rerun.</li>
              <li>Supabase is not run through the GEODE adapter until HTTP MCP transport support exists.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
