import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { RunLogLink } from "@/components/geode-docs/benchmark-run-ledger";

export const metadata = { title: "Terminal-Bench 2.1 · GEODE Docs" };

const ARTIFACT_REVISION = "a32abcbf78ab6100ea1e85540a2ace9436dc6f76";
const RUN_PATH =
  "terminalbench/results-smoke/terminalbench21-astra-high-openssl-smoke-20260904t202725z";

function ResultStrip({ ko }: { ko: boolean }) {
  const cells = ko
    ? [
        ["Canonical reward", "1 / 1", "단일 동결 task", "smoke only"],
        ["Verifier", "6 / 6", "task-owned 검사", "all passed"],
        ["Recovery", "0", "retry · fallback", "없음"],
      ]
    : [
        ["Canonical reward", "1 / 1", "One frozen task", "Smoke only"],
        ["Verifier", "6 / 6", "Task-owned checks", "All passed"],
        ["Recovery", "0", "Retry · fallback", "None"],
      ];

  return (
    <section aria-labelledby="terminal-bench-result" className="mb-14">
      <div className="border-b border-[var(--rule)] pb-3">
        <p className="!m-0 font-mono text-[10px] uppercase tracking-[0.2em] text-[var(--ink-3)]">
          {ko ? "계정 범위 E2E 증거" : "Account-scoped E2E evidence"}
        </p>
        <h2 id="terminal-bench-result" className="!mb-0 !mt-1">
          {ko ? "Astra가 실제 container task를 끝냈습니다" : "Astra completed a real container task"}
        </h2>
      </div>
      <div className="grid gap-x-8 gap-y-6 py-6 md:grid-cols-3">
        {cells.map(([label, value, scope, status], index) => (
          <div
            key={label}
            className={"border-t border-[var(--rule-soft)] pt-4 " + (index > 0 ? "md:border-l md:pl-6" : "")}
          >
            <p className="!m-0 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ink-3)]">{label}</p>
            <p className="!my-2 font-serif-docs text-3xl font-black text-[var(--ink)]">{value}</p>
            <p className="!m-0 text-sm text-[var(--ink-2)]">{scope}</p>
            <p className="!mt-2 font-mono text-[10px] uppercase tracking-wider text-[var(--section-accent)]">{status}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/terminal-bench"
      title="Terminal-Bench 2.1"
      titleKo="Terminal-Bench 2.1"
      summary="A canonical container-task smoke for GEODE's current GPT-6 Astra subscription route, with verifier and publication boundaries kept explicit."
      summaryKo="GEODE의 현재 GPT-6 Astra 구독 경로를 canonical container task로 확인한 smoke입니다. verifier와 공개 증거의 권한 경계를 분리해 제시합니다."
    >
      <Bi
        ko={
          <>
            <ResultStrip ko />
            <p>
              <a href="https://www.tbench.ai/news/terminal-bench-2-1">Terminal-Bench 2.1</a>은
              Harbor에서 89개 containerized terminal task를 실행하고 task-owned
              verifier로 채점합니다. 공식 제출은{" "}
              <a href="https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/SUBMIT.md">
                89 tasks × k≥5와 maintainer review
              </a>
              를 요구합니다.
            </p>
            <p>
              2026-09-05에 GEODE 1.0.27은 OpenAI 구독 경로의 <code>gpt-6-astra</code>,
              reasoning <code>high</code>로 Harbor 0.22.0의 canonical{" "}
              <code>openssl-selfsigned-cert</code> 작업을 실행했습니다. 3 rounds와
              정확히 짝지어진 terminal tool call/result 2쌍 뒤 자연 종료했고,
              canonical reward 1을 받았습니다.
            </p>

            <h2>증거 권한</h2>
            <table>
              <thead><tr><th>질문</th><th>정본</th></tr></thead>
              <tbody>
                <tr><td>무엇을 실행하기로 고정했나?</td><td><code>run-spec.json</code></td></tr>
                <tr><td>재시도나 fallback이 있었나?</td><td><code>attempts.jsonl</code></td></tr>
                <tr><td>task가 성공했나?</td><td>Harbor <code>result.json</code>과 verifier CTRF</td></tr>
                <tr><td>어떤 결론까지 가능한가?</td><td><code>analysis.json</code></td></tr>
                <tr><td>공개 파일이 원본과 같은가?</td><td>publication manifest와 merge-SHA read-back</td></tr>
              </tbody>
            </table>
            <p>
              <RunLogLink path={RUN_PATH} revision={ARTIFACT_REVISION} />에 9개 공개
              파일, 30,857바이트를 보존했습니다. 공개 trajectory는 scope-complete지만
              9개 payload body를 digest로 대체해 replay-incomplete입니다. prompt,
              reasoning, OAuth 자료, raw tool payload, ATIF, recording, 로컬 경로는
              비공개로 남겼습니다.
            </p>

            <h2>해석 한계</h2>
            <p>
              이 run은 89개 중 1 task, k=1입니다. 이 계정에서 model route가 열렸고
              GEODE가 실제 container task를 끝냈다는 사실만 입증합니다. suite 정확도,
              leaderboard 순위, 다른 harness 대비 우위, 전체 계정의 Astra 가용성을
              주장하지 않습니다. 공식 제출에는 89 tasks × k≥5와 maintainer의 static
              analysis 및 reward-hacking review가 필요합니다.
            </p>
          </>
        }
        en={
          <>
            <ResultStrip ko={false} />
            <p>
              <a href="https://www.tbench.ai/news/terminal-bench-2-1">Terminal-Bench 2.1</a>{" "}
              runs 89 containerized terminal tasks through Harbor and scores them with
              task-owned verifiers. Its{" "}
              <a href="https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/SUBMIT.md">
                official submission contract
              </a>{" "}
              requires 89 tasks at k≥5 and maintainer review.
            </p>
            <p>
              On 2026-09-05, GEODE 1.0.27 used <code>gpt-6-astra</code> with{" "}
              <code>high</code> reasoning through the OpenAI subscription route to run
              Harbor 0.22.0&apos;s canonical <code>openssl-selfsigned-cert</code> task.
              It terminated naturally after three rounds and two exactly paired terminal
              tool calls, then received canonical reward 1.
            </p>

            <h2>Evidence authority</h2>
            <table>
              <thead><tr><th>Question</th><th>Authority</th></tr></thead>
              <tbody>
                <tr><td>What was frozen before execution?</td><td><code>run-spec.json</code></td></tr>
                <tr><td>Was there a retry or fallback?</td><td><code>attempts.jsonl</code></td></tr>
                <tr><td>Did the task pass?</td><td>Harbor <code>result.json</code> and verifier CTRF</td></tr>
                <tr><td>What conclusion is supported?</td><td><code>analysis.json</code></td></tr>
                <tr><td>Do public bytes match the source?</td><td>Publication manifest and merge-SHA read-back</td></tr>
              </tbody>
            </table>
            <p>
              <RunLogLink path={RUN_PATH} revision={ARTIFACT_REVISION} /> retains nine
              public files totaling 30,857 bytes. The public trajectory is scope-complete
              but replay-incomplete because nine payload bodies are represented by digests.
              Prompts, reasoning, OAuth material, raw tool payloads, ATIF, recordings, and
              local paths remain private.
            </p>

            <h2>Interpretation limit</h2>
            <p>
              This run covers one of 89 tasks at k=1. It establishes that this account had
              route access and that GEODE completed one real container task. It does not
              estimate suite accuracy, claim leaderboard rank, compare harnesses, or prove
              general Astra availability. An official submission requires 89 tasks at k≥5,
              maintainer static analysis, and reward-hacking review.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
