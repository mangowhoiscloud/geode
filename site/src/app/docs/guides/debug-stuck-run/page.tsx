import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Debug a stuck run — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="guides/debug-stuck-run"
      title="Debug a stuck run"
      titleKo="멈춘 실행 디버깅"
      summary="Read the transcript and runlog, find where a run stalled, and recover."
      summaryKo="트랜스크립트와 runlog를 읽어 실행이 멈춘 지점을 찾고 복구하는 방법입니다."
    >
      <Bi
        ko={
          <>
            <p>
              실행이 멈추는 양상은 두 가지입니다. 진전 없이 도는 경우와, 이벤트
              발화가 끊긴 채 매달려 있는 경우입니다. 증거는 디스크의 append-only
              JSONL 두 개에 남습니다. 턴 단위 대화는 transcript, 훅
              이벤트는 runlog입니다. 멈춘 실행
              디버깅은 이 둘을 찾아 마지막 이벤트를 읽고, 원인을 분류해 복구하는
              순서로 진행합니다.
            </p>

            <h2>1. transcript와 runlog를 찾습니다</h2>
            <p>
              세션 transcript는 <code>SessionTranscript</code>(
              <code>core/observability/transcript.py</code>)가{" "}
              <code>~/.geode/transcripts/&lt;project-slug&gt;/&lt;session_id&gt;.jsonl</code>{" "}
              또는 run_dir에 묶인 경우 <code>dialogue.jsonl</code>에 기록합니다.
              user/assistant 메시지, 도구 호출과 결과, 비용, 오류, 라이프사이클
              이벤트가 한 줄씩 들어갑니다. runlog는 <code>RunLog</code>(
              <code>core/observability/run_log.py</code>)가{" "}
              <code>~/.geode/runs/&lt;session_key&gt;.jsonl</code>에 기록하며, 각
              줄은 <code>event</code>, <code>node</code>, <code>status</code>,{" "}
              <code>duration_ms</code>를 가진 <code>RunLogEntry</code>입니다.
              이벤트 이름은 훅 이벤트 값과 같습니다.
            </p>
            <pre>{`ls -t ~/.geode/transcripts/*/            # most recent session jsonl
ls -t ~/.geode/runs/                     # most recent run_key jsonl`}</pre>

            <h2>2. 마지막 이벤트를 읽습니다</h2>
            <p>
              어디서 멈췄는지는 마지막 줄들이 알려줍니다. transcript는{" "}
              <code>read_events(limit=N)</code>로 최근 이벤트를 읽고, runlog는{" "}
              <code>read(limit=N, ...)</code>로 newest-first로 읽으며{" "}
              <code>event_filter</code> / <code>node_filter</code> /{" "}
              <code>status_filter</code>로 좁힐 수 있습니다.
            </p>
            <pre>{`uv run python -c "
from core.observability.transcript import SessionTranscript
tx = SessionTranscript('<session_id>')
for e in tx.read_events(limit=10):
    print(e.get('event'), e.get('tool', ''), e.get('status', ''))
"`}</pre>
            <p>
              마지막이 <code>tool_call</code>인데 짝이 되는{" "}
              <code>tool_result</code>가 없으면 도구 실행에서 매달린 것이고,{" "}
              같은 <code>tool_call</code>이 같은 인자로 반복되면 진전 없는
              루프입니다.
            </p>

            <h2>3. 원인을 분류합니다</h2>
            <p>
              먼저 실행이 끝났는지부터 봅니다. 정상이든 비정상이든 끝난 실행은{" "}
              <code>AgenticResult.termination_reason</code>에 이유를 남깁니다
              (<code>core/agent/loop/models.py</code>). <code>llm_error</code>,{" "}
              <code>context_exhausted</code>, <code>time_budget_expired</code>,{" "}
              <code>cost_budget_exceeded</code>, <code>model_refusal</code>,{" "}
              <code>convergence_detected</code> 같은 값이 보이면 멈춘 것이 아니라
              가드가 끊은 것이고, 해당 가드의 문서(
              <a href="/geode/docs/ops/long-running">장기 실행 안전</a>)를
              따라갑니다. 이유 없이 이벤트만 끊겼다면 매달림입니다.
            </p>
            <ul>
              <li>
                <strong>매달림(이벤트 끊김).</strong>{" "}
                <code>SessionTranscript.is_stale(threshold_s)</code>는 파일
                mtime으로 일정 시간 이벤트가 안 붙었는지 알려줍니다. 이때는
                데몬 쪽 로그 <code>~/.geode/logs/serve.log</code>에서 같은
                시각의 traceback이나 외부 호출 대기를 찾습니다.
              </li>
              <li>
                <strong>진전 없는 루프.</strong> 루프 자체 방어가 먼저
                작동합니다. <code>ConvergenceDetector</code>
                (<code>core/agent/convergence.py</code>)가 도구 오류만 반복되는
                라운드를 추적해 <code>convergence_detected</code>로 끊고,
                도구 호출 없는 고출력 라운드 연속은{" "}
                <code>user_clarification_needed</code>로 멈춰 사용자에게
                묻습니다.
              </li>
            </ul>

            <h2>4. 복구합니다</h2>
            <p>
              transcript와 runlog가 가리키는 마지막 도구를 보고 근본 원인(외부
              호출 타임아웃, 자격증명 오류, 입력 오류)을 고친 뒤 다시
              실행합니다. 데몬 자체가 응답하지 않으면{" "}
              <code>pkill -f &quot;geode serve&quot;</code>로 내리고 재진입합니다.
              세션은 <code>geode --continue</code> 또는 <code>/resume</code>으로
              이어집니다. run log는 크기 게이트로 prune되므로 진단 근거가
              사라지기 전에 보존하세요.
            </p>

            <h2>확인</h2>
            <p>
              복구 후 새 실행의 runlog 마지막 줄들이 <code>status: ok</code>로
              이어지고 <code>session_ended</code>까지 도달하는지 확인합니다.
            </p>
            <pre>{`tail -n 3 ~/.geode/runs/<session_key>.jsonl   # 마지막 이벤트, status ok 기대`}</pre>

            <p className="text-[var(--ink-3)] text-sm">
              <em>참조:</em>{" "}
              <a href="/geode/docs/ops/long-running">Long-running runs</a>,{" "}
              <a href="/geode/docs/verification/observability">Observability</a>.
            </p>
          </>
        }
        en={
          <>
            <p>
              A run stalls in two ways: it spins without progress, or it hangs
              with no further events firing. Both leave evidence in two
              append-only JSONL files on disk: the per-turn dialogue in the
              transcript, and the hook events in the runlog. Debugging a stuck
              run is locating those two, reading the last events, classifying
              the cause, and recovering.
            </p>

            <h2>1. Locate the transcript and runlog</h2>
            <p>
              The session transcript is written by <code>SessionTranscript</code>{" "}
              in <code>core/observability/transcript.py</code> to{" "}
              <code>~/.geode/transcripts/&lt;project-slug&gt;/&lt;session_id&gt;.jsonl</code>,
              or to <code>dialogue.jsonl</code> when bound to a run_dir. It holds
              one line per user and assistant message, tool call and result, cost,
              error, and lifecycle event. The runlog is written by{" "}
              <code>RunLog</code> in <code>core/observability/run_log.py</code> to{" "}
              <code>~/.geode/runs/&lt;session_key&gt;.jsonl</code>, where each line
              is a <code>RunLogEntry</code> with <code>event</code>,{" "}
              <code>node</code>, <code>status</code>, and{" "}
              <code>duration_ms</code>. Event names match the hook event values.
            </p>
            <pre>{`ls -t ~/.geode/transcripts/*/            # most recent session jsonl
ls -t ~/.geode/runs/                     # most recent run_key jsonl`}</pre>

            <h2>2. Read the last events</h2>
            <p>
              The last lines tell you where it stalled. Read the transcript&apos;s
              recent events with <code>read_events(limit=N)</code>, and the runlog
              newest-first with <code>read(limit=N, ...)</code>, which you can
              narrow with <code>event_filter</code> / <code>node_filter</code> /{" "}
              <code>status_filter</code>.
            </p>
            <pre>{`uv run python -c "
from core.observability.transcript import SessionTranscript
tx = SessionTranscript('<session_id>')
for e in tx.read_events(limit=10):
    print(e.get('event'), e.get('tool', ''), e.get('status', ''))
"`}</pre>
            <p>
              If the last event is a <code>tool_call</code> with no matching{" "}
              <code>tool_result</code>, it hung inside tool execution. If the same{" "}
              <code>tool_call</code> repeats with the same args, it is a loop making
              no progress.
            </p>

            <h2>3. Classify the cause</h2>
            <p>
              First check whether the run actually ended. A finished run, clean
              or not, names its reason in{" "}
              <code>AgenticResult.termination_reason</code>
              (<code>core/agent/loop/models.py</code>). Values like{" "}
              <code>llm_error</code>, <code>context_exhausted</code>,{" "}
              <code>time_budget_expired</code>,{" "}
              <code>cost_budget_exceeded</code>, <code>model_refusal</code>, and{" "}
              <code>convergence_detected</code> mean a guard ended it, not a
              stall; follow the guard&apos;s page
              (<a href="/geode/docs/ops/long-running">Long-running safety</a>).
              Events stopping with no reason recorded means a hang.
            </p>
            <ul>
              <li>
                <strong>Hang (events stopped).</strong>{" "}
                <code>SessionTranscript.is_stale(threshold_s)</code> reads the
                file mtime to report that nothing has been appended for a
                while. Then look in the daemon log,{" "}
                <code>~/.geode/logs/serve.log</code>, for a traceback or a
                blocked external call around the same time.
              </li>
              <li>
                <strong>Loop with no progress.</strong> The loop&apos;s own
                defenses fire first. <code>ConvergenceDetector</code>
                (<code>core/agent/convergence.py</code>) tracks rounds where
                every tool call errors and ends the run as{" "}
                <code>convergence_detected</code>; consecutive high-output
                rounds with no tool calls stop as{" "}
                <code>user_clarification_needed</code> and ask the user.
              </li>
            </ul>

            <h2>4. Recover</h2>
            <p>
              Look at the last tool the transcript and runlog point to, fix the
              root cause (external-call timeout, credential error, bad input),
              and re-run. If the daemon itself is unresponsive, take it down
              with <code>pkill -f &quot;geode serve&quot;</code> and re-enter;
              resume the session with <code>geode --continue</code> or{" "}
              <code>/resume</code>. Run logs prune on a size gate, so preserve
              the evidence before it disappears.
            </p>

            <h2>Verify</h2>
            <p>
              After recovery, confirm the new run&apos;s last runlog lines carry{" "}
              <code>status: ok</code> and reach <code>session_ended</code>.
            </p>
            <pre>{`tail -n 3 ~/.geode/runs/<session_key>.jsonl   # last events, expect status ok`}</pre>

            <p className="text-[var(--ink-3)] text-sm">
              <em>See:</em>{" "}
              <a href="/geode/docs/ops/long-running">Long-running runs</a>,{" "}
              <a href="/geode/docs/verification/observability">Observability</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
