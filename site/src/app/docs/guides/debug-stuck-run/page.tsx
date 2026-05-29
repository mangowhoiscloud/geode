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
              실행이 멈추는 양상은 두 가지입니다. 같은 도구를 같은 인자로 무한히
              도는 경우와, 이벤트 발화가 끊긴 채 매달려 있는 경우입니다. 둘 다
              디스크에 남는 두 개의 append-only JSONL이 증거를 줍니다. 턴 단위
              대화는 transcript, 파이프라인 이벤트는 runlog입니다. 멈춘 실행
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
              <code>core/orchestration/run_log.py</code>)가{" "}
              <code>~/.geode/runs/&lt;session_key&gt;.jsonl</code>에 기록하며, 각
              줄은 <code>event</code>, <code>node</code>, <code>status</code>,{" "}
              <code>duration_ms</code>를 가진 <code>RunLogEntry</code>입니다.
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
              두 가지 정지 양상을 구분합니다.
            </p>
            <ul>
              <li>
                <strong>매달림(이벤트 끊김).</strong>{" "}
                <code>SessionTranscript.is_stale(threshold_s)</code>는 파일
                mtime을 보고 일정 시간 이벤트가 안 붙었는지 알려줍니다.{" "}
                <code>last_touched_at()</code>가 한참 전이면{" "}
                <code>PIPELINE_TIMEOUT</code> / <code>PIPELINE_ERROR</code>를
                발화하지 못한 채 멈춘 것입니다.
              </li>
              <li>
                <strong>노드 stuck.</strong>{" "}
                <code>StuckDetector</code>(
                <code>core/orchestration/stuck_detection.py</code>)가{" "}
                <code>NODE_ENTERED</code> / <code>NODE_EXITED</code> /{" "}
                <code>NODE_ERROR</code> 훅으로 실행 중인 노드를 추적합니다.{" "}
                <code>get_running()</code>은 현재 실행 중인 세션 키와 경과
                시간을 돌려주고, 타임아웃(<code>timeout_s</code>, 기본 2시간)을
                넘으면 <code>check_stuck()</code>이 그 작업을 자동 release하고{" "}
                <code>PIPELINE_ERROR</code>를 발화합니다.
              </li>
            </ul>
            <pre>{`uv run python -c "
from core.orchestration.stuck_detection import StuckDetector
d = StuckDetector()
print(d.get_running())   # {session_key: elapsed_seconds}
print(d.check_stuck())   # released keys past timeout
"`}</pre>

            <h2>4. 복구합니다</h2>
            <p>
              루프가 진전 없이 도는 경우는 <code>ConvergenceDetector</code>가
              동일 도구·동일 인자 반복을 감지해 끊습니다. 매달림이 확인되면{" "}
              <code>StuckDetector.check_stuck()</code>이 작업을 release하고{" "}
              <code>PIPELINE_ERROR</code>를 발화해 세션을 정리합니다. transcript와
              runlog가 가리키는 마지막 도구·노드를 보고 근본 원인(외부 호출
              타임아웃, 자격증명 오류, 입력 오류)을 고친 뒤 다시 실행합니다.
              transcript와 runlog는 30일 자동 정리되므로 진단 근거가 사라지기
              전에 보존하세요.
            </p>

            <h2>확인</h2>
            <p>
              복구 후 새 실행의 transcript가 <code>session_end</code>까지
              도달하는지, runlog의 마지막 이벤트가{" "}
              <code>pipeline_end</code>(<code>status: ok</code>)인지 확인합니다.
            </p>
            <pre>{`tail -n 3 ~/.geode/runs/<session_key>.jsonl   # last events, expect pipeline_end ok`}</pre>

            <p className="text-white/40 text-sm">
              <em>참조:</em>{" "}
              <a href="/geode/docs/ops/long-running">Long-running runs</a>,{" "}
              <a href="/geode/docs/verification/observability">Observability</a>.
            </p>
          </>
        }
        en={
          <>
            <p>
              A run stalls in two ways: it spins on the same tool with the same
              args, or it hangs with no further events firing. Both leave evidence
              in two append-only JSONL files on disk. the per-turn dialogue in the
              transcript, the pipeline events in the runlog. Debugging a stuck run
              is locating those two, reading the last events, classifying the cause,
              and recovering.
            </p>

            <h2>1. Locate the transcript and runlog</h2>
            <p>
              The session transcript is written by <code>SessionTranscript</code>{" "}
              in <code>core/observability/transcript.py</code> to{" "}
              <code>~/.geode/transcripts/&lt;project-slug&gt;/&lt;session_id&gt;.jsonl</code>,
              or to <code>dialogue.jsonl</code> when bound to a run_dir. It holds
              one line per user and assistant message, tool call and result, cost,
              error, and lifecycle event. The runlog is written by{" "}
              <code>RunLog</code> in <code>core/orchestration/run_log.py</code> to{" "}
              <code>~/.geode/runs/&lt;session_key&gt;.jsonl</code>, where each line
              is a <code>RunLogEntry</code> with <code>event</code>,{" "}
              <code>node</code>, <code>status</code>, and{" "}
              <code>duration_ms</code>.
            </p>
            <pre>{`ls -t ~/.geode/transcripts/*/            # most recent session jsonl
ls -t ~/.geode/runs/                     # most recent run_key jsonl`}</pre>

            <h2>2. Read the last events</h2>
            <p>
              The last lines tell you where it stalled. Read the transcript's
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
            <p>Distinguish the two stall shapes.</p>
            <ul>
              <li>
                <strong>Hang (events stopped).</strong>{" "}
                <code>SessionTranscript.is_stale(threshold_s)</code> reads the file
                mtime to report whether no event has been appended for a while. When{" "}
                <code>last_touched_at()</code> is long ago, the run stopped without
                firing <code>PIPELINE_TIMEOUT</code> / <code>PIPELINE_ERROR</code>.
              </li>
              <li>
                <strong>Stuck node.</strong> <code>StuckDetector</code> in{" "}
                <code>core/orchestration/stuck_detection.py</code> tracks running
                nodes via the <code>NODE_ENTERED</code> / <code>NODE_EXITED</code> /{" "}
                <code>NODE_ERROR</code> hooks. <code>get_running()</code> returns the
                running session keys with elapsed time, and once a node passes the
                timeout (<code>timeout_s</code>, default 2 hours),{" "}
                <code>check_stuck()</code> auto-releases the job and fires{" "}
                <code>PIPELINE_ERROR</code>.
              </li>
            </ul>
            <pre>{`uv run python -c "
from core.orchestration.stuck_detection import StuckDetector
d = StuckDetector()
print(d.get_running())   # {session_key: elapsed_seconds}
print(d.check_stuck())   # released keys past timeout
"`}</pre>

            <h2>4. Recover</h2>
            <p>
              For a loop with no progress, the <code>ConvergenceDetector</code>{" "}
              detects same-tool same-args repetition and interrupts it. For a
              confirmed hang, <code>StuckDetector.check_stuck()</code> releases the
              job and fires <code>PIPELINE_ERROR</code> to clear the session. Look
              at the last tool or node the transcript and runlog point to, fix the
              root cause (external-call timeout, credential error, bad input), and
              re-run. The transcript and runlog auto-prune after 30 days, so
              preserve the evidence before it disappears.
            </p>

            <h2>Verify</h2>
            <p>
              After recovery, confirm the new run's transcript reaches{" "}
              <code>session_end</code> and the runlog's last event is{" "}
              <code>pipeline_end</code> with <code>status: ok</code>.
            </p>
            <pre>{`tail -n 3 ~/.geode/runs/<session_key>.jsonl   # last events, expect pipeline_end ok`}</pre>

            <p className="text-white/40 text-sm">
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
