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
        <tr><td><code>filesystem</code></td><td>10</td><td>30</td><td>standard run 완료</td><td>historical 25 / 30; paired GPT-5.4 21 / 30</td></tr>
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
        <tr><td><code>filesystem</code></td><td>10</td><td>30</td><td>standard run complete</td><td>historical 25 / 30; paired GPT-5.4 21 / 30</td></tr>
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
              <code>geode_product/benchmark_harness</code>의 <code>BaseMCPAgent</code>{" "}
              어댑터로 참가하고 upstream <code>pipeline.py</code>는 패치하지
              않습니다. 점수는 harness commit, 서비스 집합, model route, timeout에
              고정해서만 게시합니다.
            </p>

            <h2>2026-08-13 GPT-5.4 filesystem/standard 정정 관측</h2>
            <p>
              고정된 30개 <code>filesystem/standard</code> task를 GPT-5.4
              subscription / effort <code>high</code>로 task별 paired 실행했습니다.
              GEODE는 <strong>21/30 (70.0%)</strong>, Codex CLI는{" "}
              <strong>20/30 (66.7%)</strong>로 GEODE가 1건 앞섰습니다. 60개
              trajectory에 3,381 events가 보존됐고, 1,430 tool call/result가
              정확히 pairing됐으며 orphan은 없습니다.
            </p>
            <p>
              사후 source audit에서 원래 사전등록한 equal-hard-deadline 전제가
              성립하지 않았음이 확인됐습니다. GEODE는 MCP setup 뒤의
              <code>loop.arun</code>만, Codex는 내부 MCP startup을 포함하는 process
              communication을 timed surface로 사용했습니다. 따라서 prospective
              hypothesis는 invalidated이며, 점수는 retrospective description으로만
              남습니다. Native input 총합은 GEODE가 작았지만 cache 제외 입력은
              4.20M 대 1.44M으로 더 컸으므로 token-efficiency도 주장하지 않습니다.
              공개 bundle에는 정확한 runner가 없으므로 독립 실행 가능한 재현
              패키지도 아닙니다.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="mcpmark/results-paired/mcpmark-filesystem-standard-gpt54-high-geode-codex-k1-boundary-aligned-20260813"
                  revision="e5d442f25c9fb4861e28744dbe924a36325c746b"
                />:
                원본 spec·receipt와 이를 supersede하는 정정 analysis·receipt.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt54-high-mcpmark-filesystem-standard-gpt54-high-geode-codex--818b13fe1039-20260812T231820Z-ed26f124b9c7"
                  revision="e5d442f25c9fb4861e28744dbe924a36325c746b"
                />:
                privacy-reviewed GEODE 30-task trajectory release.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-codex-gpt54-high-mcpmark-filesystem-standard-gpt54-high-geode-codex--f749317fe281-20260812T231820Z-828560273a4e"
                  revision="e5d442f25c9fb4861e28744dbe924a36325c746b"
                />:
                privacy-reviewed Codex 30-task trajectory release.
              </li>
            </ul>

            <h2>2026-08-12 matched token-efficiency rerun</h2>
            <p>
              같은 GPT-5.4 subscription / effort <code>high</code>, 같은 pinned{" "}
              <code>filesystem/easy</code> 10건을 수정 전후로 대조했습니다. 점수는{" "}
              <strong>9/10 (90.0%)</strong>로 유지됐고, 입력 토큰은 447,376에서
              314,219로 <strong>29.8%</strong>, 출력 토큰은 25,157에서 20,385로{" "}
              <strong>19.0%</strong> 줄었습니다.
            </p>
            <p>
              10건 중 8건의 입력 토큰이 감소했고 round 수가 같은 4건도 12.5%
              감소했습니다. 188개 canonical event와 54/54 exact tool pair에는
              orphan이 없습니다. 단, 한 번의 matched trial이므로 MCPMark Verified
              점수·신뢰구간·구독 과금 절감으로 일반화하지 않습니다.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt54-high-token-efficiency-rerun-filesystem-easy-20260812T090254Z-35db8b275a36"
                  revision="2c2d1f0621f64ff7ceeff8c05d8ebd3449501aaf"
                />:
                원격 read-back과 privacy 검증을 통과한 10개 stable trajectory.
              </li>
              <li>
                <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/2c2d1f0621f64ff7ceeff8c05d8ebd3449501aaf/reports/e2e-validation/2026-08-12-mcpmark-geode-gpt54-token-efficiency-rerun.md">
                  matched rerun report
                </a>
                : task별 변화와 promotion 경계를 포함한 판정 근거.
              </li>
            </ul>

            <h2>2026-08-03 v1.0.12 post-release regression</h2>
            <p>
              공개 배포된 GEODE <code>v1.0.12</code> (<code>f99cea63</code>)과{" "}
              <code>gpt-5.4</code> subscription / effort <code>high</code>로{" "}
              <code>filesystem/easy</code> 10건을 실행했습니다. 공식 verifier는{" "}
              <strong>9/10 (90.0%)</strong>, 총 802.2초와 53 turns입니다.
              실패한 <code>file_context/uppercase</code>는 다섯 파일을 모두
              만들었지만 <code>file_01.txt</code>를 완전히 대문자로 바꾸지
              못했습니다.
            </p>
            <p>
              인증·quota·provider adapter·MCP transport 오류는 없었습니다. 10개
              trajectory는 182개 canonical event와 56개 exact tool pair를
              보존하며 <code>scope_complete=true</code>,{" "}
              <code>replay_complete=false</code>입니다. v1.0.11의 GPT-5.6 10/10과
              비교할 때 모델까지 바뀌었으므로 release 회귀로 단정하지 않습니다.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="mcpmark/results-geode-agentworld/geode-gpt54-high-v1.0.12-f99cea63-20260803-mcpmark-filesystem-easy"
                  revision="04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd"
                />:
                verifier receipt, redacted execution logs, raw/public digest ledger.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt54-v1.0.12-f99cea63-filesystem-easy-20260803T104819Z-9636b39c16fb"
                  revision="04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd"
                />:
                manifest SHA-256 <code>9636b39c16fb…d267</code>로 원격
                read-back된 stable release.
              </li>
            </ul>

            <h2>2026-07-31 v1.0.11 release regression</h2>
            <p>
              배포된 GEODE <code>v1.0.11</code> (<code>686ff372</code>)과{" "}
              <code>gpt-5.6-sol</code> subscription / effort <code>high</code>로{" "}
              <code>filesystem/easy</code> 10건을 재측정했습니다. 공식 verifier는{" "}
              <strong>10/10 (100.0%)</strong>, 총 596.6초와 56 turns입니다.
              이전 <code>edb74602b</code> run의 유일한 실패였던{" "}
              <code>file_context/uppercase</code>도 통과했습니다.
            </p>
            <p>
              10개 stable trajectory의 226개 이벤트는 canonical SQLite 행과
              ID·session·turn·call·kind까지 일치합니다. 78개 tool call/result가
              모두 정확히 pairing됐고 필수 turn ID 누락은 0건입니다.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="mcpmark/results-geode-agentworld/geode-gpt56-sol-high-v1011-686ff372-20260731-mcpmark-filesystem-easy"
                  revision="16a54f08450db771c02e30c73bdc3867f6282f83"
                />:
                마스킹된 verifier receipt와 ordered MCP execution logs.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt56-v1.0.11-686ff372-filesystem-easy-20260731T105713Z-82fe94b01a25"
                  revision="16a54f08450db771c02e30c73bdc3867f6282f83"
                />:
                privacy review와 source digest 검증을 통과한 10개{" "}
                <code>geode.trajectory@1</code>.
              </li>
            </ul>

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
              adapter in <code>geode_product/benchmark_harness</code> without patching
              the upstream <code>pipeline.py</code>, and every published number is
              pinned to the harness commit, service set, model route, and timeout
              settings.
            </p>

            <h2>2026-08-13 GPT-5.4 Filesystem/Standard Corrected Observation</h2>
            <p>
              We ran the same 30 pinned <code>filesystem/standard</code> tasks
              through GPT-5.4 subscription at effort <code>high</code>, paired by
              task. GEODE scored <strong>21/30 (70.0%)</strong> and Codex CLI{" "}
              <strong>20/30 (66.7%)</strong>. Across 60 trajectories, all 3,381
              events are preserved, and all 1,430 tool calls/results retain exact
              pairing with zero orphans.
            </p>
            <p>
              A post-run source audit found that the preregistered equal-hard-
              deadline premise did not hold. GEODE timed <code>loop.arun</code>
              after MCP setup, while Codex timed process communication including
              its internal MCP startup. The prospective hypothesis is therefore
              invalidated, and the scores remain retrospective descriptions only.
              GEODE reports a lower native-input total, but its cache-excluded
              input is 4.20M versus 1.44M, so the run does not support a token-
              efficiency claim. The exact runner is withheld, so the public
              bundle is not independently executable.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="mcpmark/results-paired/mcpmark-filesystem-standard-gpt54-high-geode-codex-k1-boundary-aligned-20260813"
                  revision="e5d442f25c9fb4861e28744dbe924a36325c746b"
                />:
                original spec and receipts plus the superseding analysis and
                correction receipt.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt54-high-mcpmark-filesystem-standard-gpt54-high-geode-codex--818b13fe1039-20260812T231820Z-ed26f124b9c7"
                  revision="e5d442f25c9fb4861e28744dbe924a36325c746b"
                />:
                privacy-reviewed GEODE 30-task trajectory release.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-codex-gpt54-high-mcpmark-filesystem-standard-gpt54-high-geode-codex--f749317fe281-20260812T231820Z-828560273a4e"
                  revision="e5d442f25c9fb4861e28744dbe924a36325c746b"
                />:
                privacy-reviewed Codex 30-task trajectory release.
              </li>
            </ul>

            <h2>2026-08-12 Matched Token-Efficiency Rerun</h2>
            <p>
              We compared the repaired runtime on the same pinned ten{" "}
              <code>filesystem/easy</code> tasks with GPT-5.4 subscription at{" "}
              effort <code>high</code>. Accuracy held at{" "}
              <strong>9/10 (90.0%)</strong>, while input tokens fell from
              447,376 to 314,219 (<strong>29.8%</strong>) and output tokens from
              25,157 to 20,385 (<strong>19.0%</strong>).
            </p>
            <p>
              Eight of ten tasks used fewer input tokens, including a 12.5%
              reduction across the four tasks with identical round counts. The
              188 canonical events retain 54/54 exact tool pairs with zero
              orphans. This is one matched trial, not MCPMark Verified, a
              confidence interval, or a subscription billing claim.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt54-high-token-efficiency-rerun-filesystem-easy-20260812T090254Z-35db8b275a36"
                  revision="2c2d1f0621f64ff7ceeff8c05d8ebd3449501aaf"
                />:
                ten privacy-reviewed stable trajectories verified by remote
                read-back.
              </li>
              <li>
                <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/2c2d1f0621f64ff7ceeff8c05d8ebd3449501aaf/reports/e2e-validation/2026-08-12-mcpmark-geode-gpt54-token-efficiency-rerun.md">
                  matched rerun report
                </a>
                : task-level deltas and the bounded promotion decision.
              </li>
            </ul>

            <h2>2026-08-03 v1.0.12 Post-Release Regression</h2>
            <p>
              We ran the ten <code>filesystem/easy</code> tasks against the
              public GEODE <code>v1.0.12</code> release (<code>f99cea63</code>)
              with <code>gpt-5.4</code> subscription at effort <code>high</code>.
              The official verifier scored <strong>9/10 (90.0%)</strong> over
              802.2 seconds and 53 turns. The failed{" "}
              <code>file_context/uppercase</code> task created all five files but
              did not fully uppercase <code>file_01.txt</code>.
            </p>
            <p>
              There was no authentication, quota, provider-adapter, or MCP
              transport failure. The ten trajectories retain 182 canonical
              events and 56 exact tool pairs with{" "}
              <code>scope_complete=true</code> and{" "}
              <code>replay_complete=false</code>. The v1.0.11 GPT-5.6 score was
              10/10, but the model changed too, so this is not attributed to the
              release alone.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="mcpmark/results-geode-agentworld/geode-gpt54-high-v1.0.12-f99cea63-20260803-mcpmark-filesystem-easy"
                  revision="04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd"
                />:
                verifier receipts, redacted execution logs, and raw/public
                digest ledger.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt54-v1.0.12-f99cea63-filesystem-easy-20260803T104819Z-9636b39c16fb"
                  revision="04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd"
                />:
                stable release remotely read back at manifest SHA-256{" "}
                <code>9636b39c16fb…d267</code>.
              </li>
            </ul>

            <h2>2026-07-31 v1.0.11 Release Regression</h2>
            <p>
              We reran the ten <code>filesystem/easy</code> tasks with the
              released GEODE <code>v1.0.11</code> (<code>686ff372</code>) and{" "}
              <code>gpt-5.6-sol</code> subscription at effort <code>high</code>.
              The official verifier scored <strong>10/10 (100.0%)</strong> over
              596.6 seconds and 56 turns. The earlier{" "}
              <code>file_context/uppercase</code> failure now passes.
            </p>
            <p>
              All 226 events in the ten stable trajectories join their canonical
              SQLite rows on ID, session, turn, call, and kind. All 78 tool
              calls have exactly one result, with zero missing required turn IDs.
            </p>
            <ul>
              <li>
                <RunLogLink
                  path="mcpmark/results-geode-agentworld/geode-gpt56-sol-high-v1011-686ff372-20260731-mcpmark-filesystem-easy"
                  revision="16a54f08450db771c02e30c73bdc3867f6282f83"
                />:
                redacted verifier receipts and ordered MCP execution logs.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/mcpmark-geode-gpt56-v1.0.11-686ff372-filesystem-easy-20260731T105713Z-82fe94b01a25"
                  revision="16a54f08450db771c02e30c73bdc3867f6282f83"
                />:
                ten privacy-reviewed, source-digest-verified{" "}
                <code>geode.trajectory@1</code> artifacts.
              </li>
            </ul>

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
