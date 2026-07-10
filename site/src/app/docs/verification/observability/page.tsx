import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Observability — GEODE Docs" };

const queryExample = `from core.observability.event_store import HookEventStore

store = HookEventStore()
try:
    for row in store.read(limit=50, event_filter="tool_exec_end"):
        print(row.session_key, row.status, row.action, row.occurred_at)
finally:
    store.close()`;

export default function Page() {
  return (
    <DocsShell
      slug="verification/observability"
      title="Observability"
      titleKo="관측성"
      summary="Queryable SQLite lifecycle events, portable transcripts, bounded metrics, and process logs."
      summaryKo="조회 가능한 SQLite lifecycle 이벤트, portable transcript, bounded metrics, process log를 설명합니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 관측성은 목적별 저장소를 사용합니다. query/filter/aggregate가
              필요한 훅 이벤트는 SQLite, 순서대로 읽고 내보내는 실행 artifact는
              JSONL, 프로세스 진단은 rotating log입니다. raw prompt와 tool 결과를
              운영 event table에 복제하지 않습니다.
            </p>

            <h2>저장소 지도</h2>
            <table>
              <thead><tr><th>렌즈</th><th>저장소</th><th>용도</th></tr></thead>
              <tbody>
                <tr><td>Hook events</td><td><code>sessions.db:hook_events</code></td><td>세션/이벤트/status/action 조회와 보존 정책</td></tr>
                <tr><td>Run transcript</td><td><code>transcript.jsonl</code></td><td>활성 autoresearch timeline과 tail</td></tr>
                <tr><td>Dialogue</td><td><code>dialogue.jsonl</code> / session transcript</td><td>사용자·assistant·tool 대화 artifact</td></tr>
                <tr><td>Session metrics</td><td>메모리 + run summary</td><td>토큰, 비용, latency percentile</td></tr>
                <tr><td>Usage ledger</td><td><code>~/.geode/usage/YYYY-MM.jsonl</code></td><td>LLM 호출별 비용 time series</td></tr>
                <tr><td>Scheduler job tail</td><td><code>.geode/scheduler_logs/*.jsonl</code></td><td>job별 portable bounded history</td></tr>
                <tr><td>Process logs</td><td><code>~/.geode/logs/</code></td><td>traceback과 외부 시스템 진단</td></tr>
              </tbody>
            </table>

            <h2>한 trigger, 한 durable row</h2>
            <p>
              <code>HookSystem</code>은 handler chain이 끝난 뒤
              <code>HookDispatch</code>를 sink에 한 번 보냅니다. 그래서 sync/async,
              feedback/interceptor 경로마다 writer를 반복하지 않습니다. legacy 실패나
              승인 이벤트처럼 canonical 이벤트와 의미가 겹치는 신호는 외부 handler에는
              전달하지만 SQL과 transcript에는 중복 기록하지 않습니다.
            </p>

            <h2>이벤트 조회</h2>
            <pre>{queryExample}</pre>
            <p>
              row는 event, dispatch mode, status, handler error count, actor/action/entity,
              bounded payload hash를 가집니다. payload의 문자열·collection·깊이·전체 bytes에
              상한이 있고 secret pattern을 redaction합니다.
            </p>

            <h2>보존과 수명주기</h2>
            <ul>
              <li>high-volume 7일, standard 30일, audit 180일</li>
              <li>project database 전체 100,000행 상한</li>
              <li>append 중 incremental prune + 명시적 <code>prune_events()</code></li>
              <li>runtime shutdown이 producer를 멈춘 뒤 hook sink와 SQLite connection을 닫음</li>
              <li>latency percentile sample과 model cardinality도 bounded</li>
            </ul>

            <h2>실패 가시성</h2>
            <p>
              handler 실패는 다른 handler를 막지 않으며 row의
              <code>handler_error_count</code>에 반영됩니다. sink 실패는 event 종류별로
              한 번 WARNING하고 agentic loop는 계속합니다. 멈춘 실행의 조사 순서는
              <a href="/geode/docs/guides/debug-stuck-run"> 멈춘 실행 디버깅</a>을 따릅니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              GEODE uses a store for each observability job. Hook events that need
              query, filtering, and aggregation go to SQLite; ordered run artifacts
              remain JSONL; process diagnostics use rotating logs. Raw prompts and
              tool results are not copied into the operational event table.
            </p>

            <h2>Storage map</h2>
            <table>
              <thead><tr><th>Lens</th><th>Store</th><th>Purpose</th></tr></thead>
              <tbody>
                <tr><td>Hook events</td><td><code>sessions.db:hook_events</code></td><td>session/event/status/action queries and retention</td></tr>
                <tr><td>Run transcript</td><td><code>transcript.jsonl</code></td><td>active autoresearch timeline and tailing</td></tr>
                <tr><td>Dialogue</td><td><code>dialogue.jsonl</code> / session transcript</td><td>user, assistant, and tool conversation artifact</td></tr>
                <tr><td>Session metrics</td><td>memory + run summary</td><td>tokens, cost, and latency percentiles</td></tr>
                <tr><td>Usage ledger</td><td><code>~/.geode/usage/YYYY-MM.jsonl</code></td><td>per-call LLM cost series</td></tr>
                <tr><td>Scheduler job tail</td><td><code>.geode/scheduler_logs/*.jsonl</code></td><td>portable bounded per-job history</td></tr>
                <tr><td>Process logs</td><td><code>~/.geode/logs/</code></td><td>tracebacks and external-system diagnostics</td></tr>
              </tbody>
            </table>

            <h2>One trigger, one durable row</h2>
            <p>
              After the handler chain completes, <code>HookSystem</code> sends one
              <code>HookDispatch</code> to the sink. Writer logic is therefore not
              repeated across sync, async, feedback, and interceptor paths.
              Compatibility signals that duplicate a canonical failure or approval
              transition still reach handlers but do not create another SQL or
              transcript row.
            </p>

            <h2>Query events</h2>
            <pre>{queryExample}</pre>
            <p>
              Rows carry event, dispatch mode, status, handler error count,
              actor/action/entity classification, and a bounded payload hash.
              Strings, collections, nesting depth, and total payload bytes are capped,
              and secret patterns are redacted.
            </p>

            <h2>Retention and lifecycle</h2>
            <ul>
              <li>High-volume 7 days, standard 30 days, audit 180 days</li>
              <li>Global project-database cap of 100,000 rows</li>
              <li>Incremental append-time pruning plus explicit <code>prune_events()</code></li>
              <li>Runtime shutdown stops producers before closing sinks and SQLite connections</li>
              <li>Latency percentile samples and model cardinality are bounded too</li>
            </ul>

            <h2>Failure visibility</h2>
            <p>
              A handler failure does not stop later handlers and is reflected in
              <code>handler_error_count</code>. A sink failure warns once per event
              type while the agentic loop continues. Follow
              <a href="/geode/docs/guides/debug-stuck-run"> Debug a stuck run</a> to
              investigate a stalled timeline.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
