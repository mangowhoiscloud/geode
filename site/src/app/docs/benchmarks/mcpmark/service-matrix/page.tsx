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
                <tr><td><code>notion</code></td><td>10</td><td>28</td><td>stdio adapter 준비</td><td><code>SOURCE_NOTION_API_KEY</code>, <code>EVAL_NOTION_API_KEY</code>, parent page 설정 필요</td></tr>
                <tr><td><code>github</code></td><td>10</td><td>23</td><td>Docker stdio adapter 준비</td><td><code>GITHUB_TOKENS</code> 필요</td></tr>
                <tr><td><code>postgres</code></td><td>10</td><td>21</td><td>stdio adapter 준비</td><td>DB bootstrap과 <code>DATABASE_URI</code> 필요</td></tr>
                <tr><td><code>playwright</code></td><td>0</td><td>4</td><td>stdio adapter 준비</td><td>브라우저 runtime smoke 필요</td></tr>
                <tr><td><code>playwright_webarena</code></td><td>10</td><td>21</td><td>stdio adapter 준비</td><td>WebArena fixture/server 준비 필요</td></tr>
                <tr><td><code>insforge</code></td><td>확인 필요</td><td>확인 필요</td><td>조사 중</td><td><code>INSFORGE_API_KEY</code>, <code>INSFORGE_BACKEND_URL</code>, task manager 인자 호환성 확인 필요</td></tr>
                <tr><td><code>supabase</code></td><td>확인 필요</td><td>확인 필요</td><td>미지원</td><td>MCPMark HTTP MCP transport. GEODE <code>MCPServerManager</code>는 현재 stdio 중심</td></tr>
              </tbody>
            </table>

            <h2>실행 명령</h2>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp <service> \\
  --task-suite <easy|standard> \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 900 \\
  --exp-name <stable-run-id> \\
  --output-dir ./results-geode-live`}</code></pre>

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
              <li>GEODE가 현재 안정적으로 공개 점수를 낼 수 있는 MCPMark service는 <code>filesystem</code>입니다.</li>
              <li>Notion, GitHub, Postgres, Playwright 계열은 adapter는 준비됐지만 credential/fixture smoke가 먼저 필요합니다.</li>
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
                <tr><td><code>notion</code></td><td>10</td><td>28</td><td>stdio adapter ready</td><td><code>SOURCE_NOTION_API_KEY</code>, <code>EVAL_NOTION_API_KEY</code>, and parent page setup required</td></tr>
                <tr><td><code>github</code></td><td>10</td><td>23</td><td>Docker stdio adapter ready</td><td><code>GITHUB_TOKENS</code> required</td></tr>
                <tr><td><code>postgres</code></td><td>10</td><td>21</td><td>stdio adapter ready</td><td>DB bootstrap and <code>DATABASE_URI</code> required</td></tr>
                <tr><td><code>playwright</code></td><td>0</td><td>4</td><td>stdio adapter ready</td><td>Browser runtime smoke required</td></tr>
                <tr><td><code>playwright_webarena</code></td><td>10</td><td>21</td><td>stdio adapter ready</td><td>WebArena fixture/server setup required</td></tr>
                <tr><td><code>insforge</code></td><td>Needs check</td><td>Needs check</td><td>Under investigation</td><td><code>INSFORGE_API_KEY</code>, <code>INSFORGE_BACKEND_URL</code>, and task-manager argument compatibility need verification</td></tr>
                <tr><td><code>supabase</code></td><td>Needs check</td><td>Needs check</td><td>Unsupported</td><td>MCPMark HTTP MCP transport. GEODE <code>MCPServerManager</code> is currently stdio-centered</td></tr>
              </tbody>
            </table>

            <h2>Run Command</h2>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp <service> \\
  --task-suite <easy|standard> \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 900 \\
  --exp-name <stable-run-id> \\
  --output-dir ./results-geode-live`}</code></pre>

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
              <li>The MCPMark service GEODE can currently publish confidently is <code>filesystem</code>.</li>
              <li>Notion, GitHub, Postgres, and Playwright-family services have adapter coverage but still need credential or fixture smoke runs.</li>
              <li>Supabase is not run through the GEODE adapter until HTTP MCP transport support exists.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
