import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Benchmark publishing cycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/publishing-cycle"
      title="Benchmark publishing cycle"
      titleKo="Benchmark publishing cycle"
      summary="A repeatable cycle for running a GEODE benchmark, recording the evidence ledger, publishing the official docs page, and verifying GitHub Pages."
      summaryKo="GEODE benchmark 실측, evidence ledger 기록, 공식문서 반영, GitHub Pages 검증을 하나로 묶은 반복 사이클입니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 benchmark 결과는 단순히 숫자 하나를 적는 일이 아닙니다.
              하나의 publish cycle은 harness를 고정하고, live run을 보존하고,
              비교 가능성을 분리하고, 공식문서에 올린 뒤, main 배포와 Pages
              응답까지 확인해야 끝납니다.
            </p>

            <h2>Cycle 정의</h2>
            <table>
              <thead>
                <tr>
                  <th>Gate</th>
                  <th>완료 증거</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Scope</td><td>Benchmark, suite, model route, reasoning setting, live-test 승인, 예산을 기록</td></tr>
                <tr><td>Harness</td><td>Upstream source, version, local path, install command, smoke 결과를 기록</td></tr>
                <tr><td>Run</td><td>Raw result, verifier output, transcript, token/time total을 보존</td></tr>
                <tr><td>Interpret</td><td>직접 비교 가능 score와 방향성 baseline을 분리</td></tr>
                <tr><td>Publish</td><td><code>docs/eval</code> ledger와 <code>site/src/app/docs/benchmarks</code> 페이지를 갱신</td></tr>
                <tr><td>Deploy</td><td><code>develop</code>과 <code>main</code> merge 후 Pages workflow와 live URL을 확인</td></tr>
              </tbody>
            </table>

            <h2>Run record 필드</h2>
            <p>
              모든 benchmark run은 공개 전에 같은 필드를 채워야 합니다. 특히
              subscription route와 API-key route를 섞어 쓰면 안 됩니다. 예를 들어
              <code>OPENAI_API_KEY=dummy</code>가 harness placeholder였고 실제
              호출이 <code>openai-codex</code>의 <code>source=subscription</code>로
              나갔다면, 그 auth note를 결과 페이지에 그대로 남깁니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>내용</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Run ID</td><td><code>{"<benchmark>-<suite>-<model>-<reasoning>-<yyyymmdd>"}</code></td></tr>
                <tr><td>GEODE revision</td><td>commit SHA, branch, local change 여부</td></tr>
                <tr><td>Harness revision</td><td>repo URL, commit/package version, server versions, task-set label</td></tr>
                <tr><td>Model route</td><td>provider, model label, subscription/API route, auth caveat</td></tr>
                <tr><td>Task scope</td><td>domain, suite, task count, <code>k</code>, pass@k 또는 accuracy 정의</td></tr>
                <tr><td>Artifacts</td><td>raw result directory, transcripts, verifier reports, logs, generated summaries</td></tr>
                <tr><td>Comparability</td><td>직접 비교, 방향성 참고, 비교 불가 대상을 분리</td></tr>
              </tbody>
            </table>

            <h2>디렉터리 규칙</h2>
            <pre>{`artifacts/eval/harnesses/<benchmark>/        # ignored third-party checkout
artifacts/eval/runs/<run-id>/                # ignored raw run collection
docs/eval/<benchmark-or-cluster>.md          # internal evidence ledger
site/src/app/docs/benchmarks/<...>/page.tsx  # public page`}</pre>
            <p>
              로컬 사용자명, 홈 디렉터리 절대경로, API key, OAuth token, 계정 식별자는
              공식문서에 싣지 않습니다. 공개 명령에는 <code>{"<geode-worktree>"}</code>
              같은 placeholder를 씁니다.
            </p>

            <h2>운영 루프</h2>
            <ol>
              <li>Feature worktree를 <code>develop</code>에서 만들고 목적과 non-goal을 기록합니다.</li>
              <li>Upstream benchmark 문서와 현재 leaderboard/source를 확인합니다.</li>
              <li>Harness를 <code>artifacts/eval/harnesses</code>에 설치하고 no-LLM 또는 단일 task smoke를 통과시킵니다.</li>
              <li>Stable run ID로 live benchmark를 실행하고 raw artifacts를 보존합니다.</li>
              <li>Per-task, category/domain, token, time, round, failure row를 추출합니다.</li>
              <li>내부 ledger와 public docs page를 같은 run record에서 갱신합니다.</li>
              <li>PR을 <code>develop</code>으로 squash merge하고, 필요하면 <code>main -&gt; develop</code> sync 후 <code>develop -&gt; main</code> merge를 진행합니다.</li>
              <li>Pages workflow를 watch하고 live URL에서 새 score와 caveat가 보이는지 확인합니다.</li>
            </ol>

            <h2>검증</h2>
            <pre>{`git diff --check
npx eslint site/src/app/docs/benchmarks/<path>/page.tsx
cd site && npm run build

gh run list --workflow "Deploy site to GitHub Pages" --branch main --limit 5
gh run watch <run-id> --exit-status
curl -L https://mangowhoiscloud.github.io/geode/docs/benchmarks/<path> | rg "<score|run-id|model>"`}</pre>
            <p>
              Benchmark를 위해 GEODE core를 수정했다면 targeted pytest, ruff, format
              check, mypy도 같은 cycle의 verification에 포함합니다.
            </p>

            <h2>완료 기준</h2>
            <ul>
              <li>Raw artifacts가 ignored artifact 경로에 보존되어 있습니다.</li>
              <li>Internal ledger가 setup, result, comparability를 설명합니다.</li>
              <li>Public docs page가 score, command, artifact pointer, caveat를 노출합니다.</li>
              <li>Feature PR CI가 통과했고 <code>develop</code>에 merge됐습니다.</li>
              <li><code>develop</code>이 <code>main</code>에 merge됐습니다.</li>
              <li>GitHub Pages deploy가 성공했고 live URL에서 새 결과를 확인했습니다.</li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm">
              내부 runbook과 템플릿은 <code>docs/eval/benchmark-publishing-cycle.md</code>와{" "}
              <code>docs/eval/benchmark-run-record.template.md</code>에 있습니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              Publishing a GEODE benchmark is not just writing down a number. A
              complete cycle pins the harness, preserves the live run, separates
              comparability, updates the official docs, merges through the normal
              branch flow, and verifies the deployed GitHub Pages URL.
            </p>

            <h2>Cycle definition</h2>
            <table>
              <thead>
                <tr>
                  <th>Gate</th>
                  <th>Exit evidence</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Scope</td><td>Benchmark, suite, model route, reasoning setting, live-test approval, and budget recorded</td></tr>
                <tr><td>Harness</td><td>Upstream source, version, local path, install command, and smoke result recorded</td></tr>
                <tr><td>Run</td><td>Raw result, verifier output, transcript, token totals, and time totals preserved</td></tr>
                <tr><td>Interpret</td><td>Directly comparable scores separated from directional baselines</td></tr>
                <tr><td>Publish</td><td><code>docs/eval</code> ledger and <code>site/src/app/docs/benchmarks</code> page updated</td></tr>
                <tr><td>Deploy</td><td><code>develop</code> and <code>main</code> merges done; Pages workflow and live URL checked</td></tr>
              </tbody>
            </table>

            <h2>Run record fields</h2>
            <p>
              Every benchmark run uses the same publication fields. In
              particular, do not blur subscription routes and API-key routes. If
              <code>OPENAI_API_KEY=dummy</code> was only a harness placeholder and
              the actual calls went through <code>openai-codex</code> with{" "}
              <code>source=subscription</code>, keep that auth note on the result
              page.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Content</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Run ID</td><td><code>{"<benchmark>-<suite>-<model>-<reasoning>-<yyyymmdd>"}</code></td></tr>
                <tr><td>GEODE revision</td><td>commit SHA, branch, and local-change state</td></tr>
                <tr><td>Harness revision</td><td>repo URL, commit/package version, server versions, and task-set label</td></tr>
                <tr><td>Model route</td><td>provider, model label, subscription/API route, and auth caveat</td></tr>
                <tr><td>Task scope</td><td>domain, suite, task count, <code>k</code>, and pass@k or accuracy definition</td></tr>
                <tr><td>Artifacts</td><td>raw result directory, transcripts, verifier reports, logs, and generated summaries</td></tr>
                <tr><td>Comparability</td><td>direct, directional, and not-comparable targets separated</td></tr>
              </tbody>
            </table>

            <h2>Directory convention</h2>
            <pre>{`artifacts/eval/harnesses/<benchmark>/        # ignored third-party checkout
artifacts/eval/runs/<run-id>/                # ignored raw run collection
docs/eval/<benchmark-or-cluster>.md          # internal evidence ledger
site/src/app/docs/benchmarks/<...>/page.tsx  # public page`}</pre>
            <p>
              Do not publish local usernames, home-directory absolute paths, API
              keys, OAuth tokens, or account identifiers. Public commands use
              placeholders such as <code>{"<geode-worktree>"}</code>.
            </p>

            <h2>Operator loop</h2>
            <ol>
              <li>Create a feature worktree from <code>develop</code> and record the objective plus non-goals.</li>
              <li>Check the upstream benchmark docs and current leaderboard/source.</li>
              <li>Install the harness under <code>artifacts/eval/harnesses</code> and pass a no-LLM or single-task smoke.</li>
              <li>Run the live benchmark with a stable run ID and preserve raw artifacts.</li>
              <li>Extract per-task, category/domain, token, time, round, and failure rows.</li>
              <li>Update the internal ledger and public docs page from the same run record.</li>
              <li>Squash the feature PR into <code>develop</code>, sync <code>main -&gt; develop</code> if needed, then merge <code>develop -&gt; main</code>.</li>
              <li>Watch the Pages workflow and verify that the live URL contains the new score and caveat.</li>
            </ol>

            <h2>Verification</h2>
            <pre>{`git diff --check
npx eslint site/src/app/docs/benchmarks/<path>/page.tsx
cd site && npm run build

gh run list --workflow "Deploy site to GitHub Pages" --branch main --limit 5
gh run watch <run-id> --exit-status
curl -L https://mangowhoiscloud.github.io/geode/docs/benchmarks/<path> | rg "<score|run-id|model>"`}</pre>
            <p>
              If the benchmark required a GEODE core change, include targeted
              pytest, ruff, format check, and mypy in the same cycle&apos;s
              verification.
            </p>

            <h2>Done definition</h2>
            <ul>
              <li>Raw artifacts are preserved under an ignored artifact path.</li>
              <li>The internal ledger explains setup, result, and comparability.</li>
              <li>The public docs page exposes score, command, artifact pointer, and caveat.</li>
              <li>The feature PR CI passed and merged into <code>develop</code>.</li>
              <li><code>develop</code> merged into <code>main</code>.</li>
              <li>GitHub Pages deployed successfully and the live URL contains the new result.</li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm">
              The internal runbook and template live at{" "}
              <code>docs/eval/benchmark-publishing-cycle.md</code> and{" "}
              <code>docs/eval/benchmark-run-record.template.md</code>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
