import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Debug a stuck run — GEODE Docs" };

const eventQuery = `uv run python - <<'PY'
from core.observability.event_store import HookEventStore

store = HookEventStore()
try:
    rows = store.read(limit=20, session_key="<session_key>")
    for row in reversed(rows):
        print(row.occurred_at, row.event, row.status, row.action)
finally:
    store.close()
PY`;

export default function Page() {
  return (
    <DocsShell
      slug="guides/debug-stuck-run"
      title="Debug a stuck run"
      titleKo="멈춘 실행 디버깅"
      summary="Correlate SQLite session history, runtime events, a run projection, and daemon logs."
      summaryKo="SQLite session history, runtime event, run projection, 데몬 로그를 맞춰 멈춘 지점을 찾습니다."
    >
      <Bi
        ko={
          <>
            <p>
              실행 순서는 project-local <code>sessions.db:session_events</code>,
              조회 가능한 lifecycle은 <code>hook_events</code>, portable view는
              run-bound <code>events.jsonl</code>에 남습니다. 같은 시각의
              <code>serve.log</code>까지 맞추면 “가드가 정상 종료했는지”와 “외부
              호출에서 실제로 매달렸는지”를 구분할 수 있습니다.
            </p>

            <h2>1. 최근 이벤트를 조회합니다</h2>
            <p>
              <code>HookEventStore()</code>는 현재 workspace의 database를 해석합니다.
              session key를 알고 있으면 아래처럼 최근 이벤트를 시간순으로 봅니다.
              저장 payload는 raw prompt, user input, tool input/result를 포함하지 않습니다.
            </p>
            <pre>{eventQuery}</pre>

            <h2>2. lifecycle pair를 확인합니다</h2>
            <ul>
              <li><code>llm_call_start</code> 뒤 <code>llm_call_end</code>가 없으면 model adapter 대기를 확인합니다.</li>
              <li><code>tool_exec_start</code> 뒤 <code>tool_exec_end</code>가 없으면 tool 실행 또는 process 종료 경계를 확인합니다.</li>
              <li><code>status=blocked</code>는 공개 훅 또는 정책이 의도적으로 막은 실행입니다.</li>
              <li><code>status=failed</code>는 canonical terminal row에 실패가 반영된 경우입니다.</li>
            </ul>

            <h2>3. session record와 daemon log를 맞춥니다</h2>
            <p>
              정본 실행 순서는 <code>sessions.db:session_events</code>, run_dir가 있는
              실행의 portable view는 <code>events.jsonl</code>에서 확인합니다. 마지막
              <code>tool.called</code>에 대응하는 <code>tool.completed</code>가 없거나
              동일 호출이 반복되면
              <code>~/.geode/logs/serve.log</code>에서 같은 timestamp의 traceback,
              timeout, credential 오류를 찾습니다.
            </p>

            <h2>4. 복구 후 확인합니다</h2>
            <p>
              원인을 고치고 재실행한 뒤 새 timeline이 canonical
              <code>session.ended</code>까지 이어지는지 확인합니다. 이벤트 table은
              보존 등급과 전체 행수 상한으로 자동 prune되므로 장기 보존이 필요한
              증거는 별도 run artifact로 내보냅니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              Canonical behavior lives in project-local <code>sessions.db</code>{" "}
              <code>session_events</code>; queryable runtime telemetry lives in
              <code>hook_events</code>. A run-bound <code>events.jsonl</code> is a
              portable projection. Correlate these with
              <code>serve.log</code> to distinguish a guarded termination from a
              genuinely blocked external call.
            </p>

            <h2>1. Query recent events</h2>
            <p>
              <code>HookEventStore()</code> resolves the current workspace database.
              Filter by session key and print the newest timeline in chronological
              order. Persisted payloads exclude raw prompts, user input, and tool
              inputs/results.
            </p>
            <pre>{eventQuery}</pre>

            <h2>2. Check lifecycle pairs</h2>
            <ul>
              <li>A missing <code>llm_call_end</code> after <code>llm_call_start</code> points at the model adapter boundary.</li>
              <li>A missing <code>tool_exec_end</code> after <code>tool_exec_start</code> points at tool execution or process termination.</li>
              <li><code>status=blocked</code> means a public hook or policy intentionally denied the operation.</li>
              <li><code>status=failed</code> records failure on the canonical terminal row.</li>
            </ul>

            <h2>3. Correlate session history and daemon log</h2>
            <p>
              Inspect canonical <code>sessions.db:session_events</code> and, for
              run-bound work, its portable <code>events.jsonl</code> projection. A
              final <code>tool.called</code> without <code>tool.completed</code>, or
              a repeated identical call, should be matched by timestamp against
              <code>~/.geode/logs/serve.log</code> for tracebacks, timeouts, or
              credential failures.
            </p>

            <h2>4. Verify recovery</h2>
            <p>
              After fixing the cause, confirm the new timeline reaches the canonical
              <code>session.ended</code> event. Event rows are automatically
              pruned by retention class and a global cap; export evidence that needs
              longer artifact retention.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
