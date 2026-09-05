import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { RunLogLink } from "@/components/geode-docs/benchmark-run-ledger";

export const metadata = { title: "Terminal-Bench 2.1 · GEODE Docs" };

const ARTIFACT_REVISION = "a32abcbf78ab6100ea1e85540a2ace9436dc6f76";
const RUN_PATH =
  "terminalbench/results-smoke/terminalbench21-astra-high-openssl-smoke-20260904t202725z";
const REPLAY_REVISION = "52b7d0eab37ec9122492ec51d77e1502d5b9e085";
const OBSERVABILITY_REVISION = "d277607f3a179f191ad24b1497c0934beb9d2470";
const PAIRED_RUN = "terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z";

function PairedReplay({ ko }: { ko: boolean }) {
  return (
    <section aria-labelledby="paired-execution-replay">
      <h2 id="paired-execution-replay">{ko ? "Sol 비교 실행을 다시 읽는 Replay" : "Replay the Sol paired execution"}</h2>
      <p>{ko
        ? "아래 기록은 Astra smoke와 별개인 2026-08-27~09-02 UTC의 Sol/max 비교 실행입니다. GEODE revision b549f3e의 OpenAI subscription 경로와 native Codex를 Harbor 0.22.0에서 실행했습니다. 동결 full-suite primary는 측정 불가이며, 공식 leaderboard 결과가 아닙니다."
        : "This is the separate August 27–September 2 UTC Sol/max comparison, not the Astra smoke above. Harbor 0.22.0 ran GEODE revision b549f3e and native Codex through the OpenAI subscription route. The frozen full-suite primary is not measurable; this is not an official leaderboard result."}</p>
      <p>{ko
        ? "Pair 001~445는 89 tasks × 5 repetitions입니다. 각 쌍의 왼쪽은 GEODE, 오른쪽은 Codex이며, task·반복·arm 하나가 cell입니다. 재생하면 새 tool event가 아래에 나타나고 이전 기록은 위로 올라갑니다. 상단의 arm 정보는 고정됩니다."
        : "Pairs 001–445 represent 89 tasks × 5 repetitions. GEODE is on the left, Codex on the right; one task, repetition and arm form a cell. New tool events appear at the bottom and older lines move upward while arm metadata stays fixed."}</p>
      <p><a href="/geode/benchmarks/terminal-bench/replay/" target="_blank" rel="noopener noreferrer">
        {ko ? "445쌍 Replay 열기" : "Open the 445-pair replay"}
      </a></p>
      <table>
        <thead><tr><th>{ko ? "관찰 범위" : "Evidence coverage"}</th><th>GEODE</th><th>Codex</th><th>{ko ? "합계" : "Total"}</th></tr></thead>
        <tbody>
          <tr><td>ATIF-derived tool events</td><td>407</td><td>428</td><td>835</td></tr>
          <tr><td>Receipt only</td><td>28</td><td>7</td><td>35</td></tr>
          <tr><td>{ko ? "실행 전 제외" : "Not executed"}</td><td>10</td><td>10</td><td>20</td></tr>
          <tr><td>{ko ? "계획된 cells" : "Intended cells"}</td><td>445</td><td>445</td><td>890</td></tr>
        </tbody>
      </table>
      <p>{ko
        ? "16,244개 tool 호출의 순서를 재구성했습니다. 공개판은 tool·프로그램 종류, payload 크기, 해시와 시각만 표시합니다. command/output 본문, 모델 메시지와 provider reasoning은 공개하지 않습니다. 원본 UTC를 보존하고 KST로 표시하며, 5 events/s는 편집 속도입니다. 좌우는 tool-event 순서로 정렬했으며 실제 동시 실행이나 wall-time 정렬이 아닙니다."
        : "The view reconstructs 16,244 tool calls. It exposes tool/program labels, payload sizes, hashes and timestamps, not command/output bodies, model messages or provider reasoning. UTC sources are displayed in KST. Five events per second is editorial pacing; event-index alignment does not imply concurrent execution or wall-time synchronization."}</p>
      <p>{ko
        ? "35개 receipt-only cell에는 terminal 내용을 만들어 넣지 않았습니다. bn-fit-modify와 tune-mjcf의 20개 cell은 arm64 호스트에서 amd64 oracle/verifier가 정상 완료되지 않아 모델 호출 전에 대칭 제외했습니다. 별도로 미해소 native 인프라 무효가 6개 남았습니다. 공통 유효 429쌍의 secondary 결과는 GEODE 339/429, Codex 331/429이며, 이를 전체 suite 우위로 일반화하지 않습니다."
        : "No terminal content is invented for 35 receipt-only cells. Twenty cells from bn-fit-modify and tune-mjcf were symmetrically excluded before model calls because their amd64 oracle/verifier did not complete normally on the arm64 host. Six native infrastructure-invalid cells remain unresolved. The 429 common valid pairs give secondary results of 339/429 for GEODE and 331/429 for Codex, not a general full-suite superiority claim."}</p>
      <p>{ko
        ? "화면의 raw verifier와 selected reward는 구분해서 읽어야 합니다. 동결 규칙상 canonical timeout과 safety refusal은 selected zero이며, raw verifier가 1인 18개 cell도 여기에 포함됩니다. 점수의 근거는 Harbor result/verifier와 frozen attempt ledger·analysis입니다. 이 화면은 원본 PTY나 새로운 점수 판정기가 아닙니다."
        : "Read raw verifier and selected reward separately. Frozen rules assign selected zero to canonical timeouts and safety refusals, including 18 cells with raw verifier reward one. Harbor result/verifier, the frozen attempt ledger and analysis own scoring. This view is neither raw PTY footage nor a new scorer."}</p>
      <p><RunLogLink path={`${PAIRED_RUN}/recording/replay-v19-20260905`} revision={REPLAY_REVISION} label="Replay source · coverage · SHA-256 receipts" />{" · "}
        <RunLogLink path={PAIRED_RUN} revision={ARTIFACT_REVISION} label="Frozen run · attempts · analysis" />
      </p>
      <h3>{ko ? "보존된 원본에서 복구한 실행 지표" : "Execution metrics recovered from preserved evidence"}</h3>
      <p>{ko
        ? "호출별 usage를 GEODE 401셀·4,709건, Codex 418셀·12,214건에서 복구하고 Harbor trial 합계와 대조했습니다. GEODE cache 필드 648건은 미기록 상태인 null로 보존합니다. Cached input은 input에 포함되며, 확인된 부분합을 전체 cache 값으로 표시하지 않습니다. Usage event는 ATIF tool step과 다른 단위이므로 재생 위치와 연동하지 않습니다."
        : "Call-level usage was recovered and reconciled with Harbor trial totals for 401 GEODE cells / 4,709 events and 418 Codex cells / 12,214 events. The 648 missing GEODE cache fields remain null. Cached input is part of input; an observed subtotal is not presented as a complete total. Usage events are distinct from ATIF tool steps and are not synchronized to playback."}</p>
      <p>{ko
        ? "Replay의 지표 항목을 펼치면 호출별 input·output·cache, environment setup·agent setup·execution·verifier 경과 시간, 완료된 shell command의 exit code 집계를 볼 수 있습니다. Nonzero exit는 tool 오류율이 아닙니다. 실제 CPU 사용률·peak RAM·subscription 청구액은 미계측이며, producer 비용 추정치는 청구액과 구분합니다. 원본 점수와 제외 규칙은 바뀌지 않았습니다."
        : "Expand the replay metrics to inspect per-call input, output and cache, phase elapsed times, and completed shell-command exit summaries. Nonzero exit is not a tool error rate. Actual CPU utilization, peak RAM and subscription billing are unmeasured; producer cost estimates are labeled separately. Original scores and exclusions remain unchanged."}</p>
      <p><RunLogLink path={`${PAIRED_RUN}/recording/research-v20`} revision={OBSERVABILITY_REVISION} label="Recovered observability · method · source hashes" /></p>
      <p className="text-sm text-[var(--ink-3)]">{ko
        ? "Next.js·React·TypeScript 페이지에서 재생합니다. Pinned commit의 metadata JSON을 SHA-256으로 검증한 뒤 표시하며, 검증 실패 시 재생을 차단합니다. 외부 HTML이나 스크립트를 실행하지 않습니다. 기존 .html 주소는 새 경로로 연결됩니다. Private viewer는 공개하지 않습니다."
        : "Playback runs in a native Next.js, React and TypeScript page. Metadata JSON from a pinned commit is SHA-256 verified before rendering; failure blocks playback. No external HTML or script is executed. The legacy .html URL redirects to the new route. The private viewer remains unpublished."}</p>
    </section>
  );
}

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
      summary="Astra container-task smoke and the historical Sol paired replay, with scoring authority, coverage and publication limits kept separate."
      summaryKo="Astra container-task smoke와 이전 Sol 비교 실행의 Replay를 소개합니다. 각 실행의 점수 근거, 관찰 범위와 공개 한계를 구분합니다."
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
            <PairedReplay ko />
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
            <PairedReplay ko={false} />
          </>
        }
      />
    </DocsShell>
  );
}
