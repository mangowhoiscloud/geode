import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { BENCHMARK_GROUPS } from "@/data/geode/benchmark-measurements";
import {
  BenchmarkMatrix,
  BenchmarkRunList,
  EvalArtifactsRepoLink,
  RunLogLink,
} from "@/components/geode-docs/benchmark-run-ledger";

export const metadata = { title: "MCPMark — GEODE Docs" };

const group = BENCHMARK_GROUPS.find((g) => g.id === "mcpmark")!;

function ServiceCoverageKo() {
  return (
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
        <tr><td><code>filesystem</code></td><td>10</td><td>30</td><td>standard run 완료</td><td>25 / 30 게시</td></tr>
        <tr><td><code>postgres</code></td><td>10</td><td>21</td><td>standard run 완료</td><td>20 / 21, <code>postgres-mcp==0.3.0</code></td></tr>
        <tr><td><code>github</code></td><td>10</td><td>23</td><td>standard run 완료</td><td>19 / 23, Docker GitHub MCP server. State Duplication Error 6건의 원인(<code>GITHUB_EVAL_ORG</code> 미영속)은 2026-07-10 제거</td></tr>
        <tr><td><code>notion</code></td><td>10</td><td>28</td><td>실측 가능 (easy smoke 1/1, 2026-07-10)</td><td>07-04 스톨 원인은 브라우저 세션 만료로 확정, 재발급 절차 확립. standard 28건 미측정</td></tr>
        <tr><td><code>playwright</code></td><td>0</td><td>4</td><td>실행 준비 완료 (2026-07-10)</td><td><code>@playwright/mcp@0.0.68</code> 기동 확인. 4건 미측정</td></tr>
        <tr><td><code>playwright_webarena</code></td><td>10</td><td>21</td><td>stdio adapter 준비</td><td>WebArena Docker 이미지 실측 119GiB vs 로컬 여유 13GiB. 외장 볼륨 또는 VM 필요</td></tr>
        <tr><td><code>insforge</code></td><td colSpan={2}>확인 필요</td><td>조사 중</td><td><code>INSFORGE_API_KEY</code>, task manager 인자 호환성 확인 필요</td></tr>
        <tr><td><code>supabase</code></td><td colSpan={2}>확인 필요</td><td>미지원</td><td>HTTP MCP transport. GEODE <code>MCPServerManager</code>는 현재 stdio 중심</td></tr>
      </tbody>
    </table>
  );
}

function ServiceCoverageEn() {
  return (
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
        <tr><td><code>filesystem</code></td><td>10</td><td>30</td><td>standard run complete</td><td>25 / 30 published</td></tr>
        <tr><td><code>postgres</code></td><td>10</td><td>21</td><td>standard run complete</td><td>20 / 21, <code>postgres-mcp==0.3.0</code></td></tr>
        <tr><td><code>github</code></td><td>10</td><td>23</td><td>standard run complete</td><td>19 / 23, Docker GitHub MCP server. Root cause of 6 State Duplication Errors (unset <code>GITHUB_EVAL_ORG</code>) removed on 2026-07-10</td></tr>
        <tr><td><code>notion</code></td><td>10</td><td>28</td><td>Runnable (easy smoke 1/1, 2026-07-10)</td><td>The 07-04 stall traced to an expired browser session; re-login procedure established. Standard 28 tasks not yet measured</td></tr>
        <tr><td><code>playwright</code></td><td>0</td><td>4</td><td>Ready to run (2026-07-10)</td><td><code>@playwright/mcp@0.0.68</code> launch verified. 4 tasks not yet measured</td></tr>
        <tr><td><code>playwright_webarena</code></td><td>10</td><td>21</td><td>stdio adapter ready</td><td>WebArena Docker images measure 119GiB vs 13GiB free local disk. Needs an external volume or a VM</td></tr>
        <tr><td><code>insforge</code></td><td colSpan={2}>Needs check</td><td>Under investigation</td><td><code>INSFORGE_API_KEY</code> and task-manager argument compatibility need verification</td></tr>
        <tr><td><code>supabase</code></td><td colSpan={2}>Needs check</td><td>Unsupported</td><td>HTTP MCP transport. GEODE <code>MCPServerManager</code> is currently stdio-centered</td></tr>
      </tbody>
    </table>
  );
}

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/mcpmark"
      title="MCPMark"
      titleKo="MCPMark"
      summary="GEODE's MCPMark measurements: the Verified available-services headline, service coverage and blockers, every run record, and links to the raw run logs."
      summaryKo="GEODE의 MCPMark 실측입니다. Verified available-services headline, 서비스 coverage와 blocker, run 기록 전체, 원본 run 로그 링크를 담습니다."
    >
      <Bi
        ko={
          <>
            <p>
              MCPMark는 실제 MCP 서버(filesystem, Postgres, GitHub, Notion,
              Playwright 등)를 대상으로 한 tool-use 벤치마크입니다. 태스크마다
              독립 검증 스크립트가 결과 상태를 확인합니다. GEODE는{" "}
              <code>plugins/benchmark_harness</code>의 <code>BaseMCPAgent</code>{" "}
              어댑터로 참가하고 upstream <code>pipeline.py</code>는 패치하지
              않습니다. 점수는 harness commit, 서비스 집합, model route, timeout에
              고정해서만 게시합니다.
            </p>

            <h2>Headline: Verified available-services 트랙</h2>
            <p>
              2026-07-04 run, GEODE v0.99.269 계열, <code>eval-sys/mcpmark@cd45b7f</code>,{" "}
              <code>gpt-5.5</code> Codex 구독 route, effort <code>xhigh</code>. 전체
              leaderboard 점수가 아니라 로컬 환경에서 실행 가능했던 standard
              슬라이스(filesystem, postgres, github)의 측정입니다.
            </p>
            <BenchmarkMatrix group={group} />

            <h2>Service coverage</h2>
            <ServiceCoverageKo />
            <p>
              구독 쿼터(429 usage_limit_reached)는 full-suite 연속 실행을 리셋 창
              단위로 분할시킵니다. 429 실패는 점수에 포함하지 않고 해당 태스크를
              재실행합니다.
            </p>

            <h2>Run 기록</h2>
            <BenchmarkRunList group={group} />

            <h2>Run 로그</h2>
            <p>
              태스크별 <code>meta.json</code>(route, 소요시간, 토큰, verifier 결과)과{" "}
              <code>messages.json</code>(최종 답변 문자열 또는 빈 목록 placeholder),
              생성된 경우 <code>execution.log</code>(순서가 보존된 MCP
              action/result)는 민감한 로컬 경로를 마스킹한 공개용 copy로{" "}
              <EvalArtifactsRepoLink /> 레포에 보존됩니다.
              이 공개 snapshot에는 전체 model dialogue와 hidden turn이 없으므로{" "}
              <code>messages.json</code>만으로 대화를 복원할 수 없습니다.
            </p>
            <ul>
              <li>
                <RunLogLink path="mcpmark/results-geode-agentworld" />: Verified
                트랙 run 디렉터리(<code>geode-gpt55-xhigh-20260704-mcpmark-verified-*</code>).
              </li>
              <li>
                <RunLogLink path="mcpmark/logs" />, <RunLogLink path="mcpmark/logs-cycle" />:
                파이프라인 stdout 로그(state duplication, verification, cleanup 단계).
              </li>
            </ul>
            <p>
              run 기록의 artifact 경로는 측정 당시 로컬 harness 경로입니다. 게시된
              사본은 위 레포 경로에서 run 이름으로 찾습니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              MCPMark is a tool-use benchmark against real MCP servers
              (filesystem, Postgres, GitHub, Notion, Playwright, and more), with
              an independent verifier script checking the resulting state per
              task. GEODE participates through the <code>BaseMCPAgent</code>{" "}
              adapter in <code>plugins/benchmark_harness</code> without patching
              the upstream <code>pipeline.py</code>, and every published number is
              pinned to the harness commit, service set, model route, and timeout
              settings.
            </p>

            <h2>Headline: Verified Available-Services Track</h2>
            <p>
              2026-07-04 run, GEODE v0.99.269-era code,{" "}
              <code>eval-sys/mcpmark@cd45b7f</code>, <code>gpt-5.5</code> through
              the Codex subscription route at effort <code>xhigh</code>. This is
              not a full leaderboard score: it covers the standard service slices
              runnable in the local environment (filesystem, postgres, github).
            </p>
            <BenchmarkMatrix group={group} />

            <h2>Service Coverage</h2>
            <ServiceCoverageEn />
            <p>
              The subscription quota (429 usage_limit_reached) splits full-suite
              execution into reset windows; 429 failures are excluded from scores
              and those tasks are rerun.
            </p>

            <h2>Run Records</h2>
            <BenchmarkRunList group={group} />

            <h2>Run Logs</h2>
            <p>
              Per-task <code>meta.json</code> (route, timing, tokens, verifier
              result), <code>messages.json</code> (a final-answer string or empty-list
              placeholder), and, when produced, <code>execution.log</code> (ordered
              MCP action/result records) are preserved as public copies with
              sensitive local paths redacted in the <EvalArtifactsRepoLink />{" "}
              repository. The public snapshot omits full
              model dialogue and hidden turns, so <code>messages.json</code> cannot
              reconstruct the conversation.
            </p>
            <ul>
              <li>
                <RunLogLink path="mcpmark/results-geode-agentworld" />: Verified
                track run directories
                (<code>geode-gpt55-xhigh-20260704-mcpmark-verified-*</code>).
              </li>
              <li>
                <RunLogLink path="mcpmark/logs" />, <RunLogLink path="mcpmark/logs-cycle" />:
                pipeline stdout logs (state duplication, verification, cleanup stages).
              </li>
            </ul>
            <p>
              Artifact paths inside the run records are the local harness paths at
              measurement time; the published copies live under the repository
              paths above, addressed by run name.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
