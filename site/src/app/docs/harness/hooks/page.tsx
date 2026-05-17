import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Hook System — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/hooks"
      title="Hook System"
      titleKo="훅 시스템"
      summary="58 lifecycle events grouped into 14 categories. Listeners can observe, intercept, or modify."
      summaryKo="58개 라이프사이클 이벤트, 14개 카테고리로 분류. 리스너가 관찰, 가로채기, 수정 가능."
    >
      <Bi
        ko={
          <>
            <h2>세 가지 트리거 모드</h2>
            <ul>
              <li><strong><code>trigger(event, payload)</code></strong>. fire-and-forget. 리스너 오류는 로깅되며 격리됩니다.</li>
              <li><strong><code>trigger_with_result(event, payload)</code></strong>. 각 핸들러의 반환값을 캡처합니다.</li>
              <li><strong><code>trigger_interceptor(event, payload)</code></strong>. 핸들러가 이벤트를 차단하거나 수정할 수 있습니다.</li>
            </ul>
            <p>
              구현은 <code>core/hooks/system.py:200 class HookSystem</code>에 있습니다.
              동시 실행은 <code>concurrent.futures</code>를 통해 이루어지며,
              핸들러 등록 시 재진입 가능한 락으로 보호됩니다.
            </p>

            <h2>이벤트 그룹</h2>
            <table>
              <thead><tr><th>그룹</th><th>개수</th><th>이벤트</th></tr></thead>
              <tbody>
                <tr><td>pipeline</td><td>3</td><td>PIPELINE_START, PIPELINE_END, PIPELINE_ERROR</td></tr>
                <tr><td>node</td><td>4</td><td>NODE_ENTER, NODE_EXIT, NODE_ERROR, NODE_RETRY</td></tr>
                <tr><td>analysis</td><td>3</td><td>ANALYST_START, ANALYST_COMPLETE, ANALYST_FAILED</td></tr>
                <tr><td>verification</td><td>2</td><td>VERIFICATION_PASS, VERIFICATION_FAIL</td></tr>
                <tr><td>automation</td><td>5</td><td>DRIFT_DETECTED, MODEL_PROMOTED, OUTCOME_COLLECTED, EXPERT_VOTE_CAST, FEEDBACK_PHASE_CHANGED</td></tr>
                <tr><td>memory</td><td>4</td><td>MEMORY_SAVED, RULE_CREATED, RULE_UPDATED, RULE_DELETED</td></tr>
                <tr><td>tool</td><td>8</td><td>TOOL_EXEC_START/END/FAILED, TOOL_RECOVERY_START/END, TOOL_APPROVAL_REQUEST/GRANTED/DENIED</td></tr>
                <tr><td>session</td><td>2</td><td>SESSION_START, SESSION_END</td></tr>
                <tr><td>model</td><td>1</td><td>MODEL_SWITCHED</td></tr>
                <tr><td>llm</td><td>4</td><td>LLM_CALL_START, LLM_CALL_END, LLM_CALL_FAILED, LLM_CALL_RETRY</td></tr>
                <tr><td>approval</td><td>2</td><td>APPROVAL_REQUEST, APPROVAL_GRANTED</td></tr>
                <tr><td>context</td><td>2</td><td>CONTEXT_OVERFLOW, CONTEXT_RESET</td></tr>
                <tr><td>prompt</td><td>1</td><td>PROMPT_ASSEMBLED</td></tr>
                <tr><td>turn</td><td>1</td><td>TURN_COMPLETE</td></tr>
              </tbody>
            </table>
            <p>
              총 14개 그룹, 58개 이벤트 (표에는 주요 항목만 요약). <code>core/hooks/system.py</code>
              소스 주석은 이벤트를 더 세분화하여 (subagent 라이프사이클, agentic turn, 세션,
              LLM 호출, 도구 승인, serve 라이프사이클, MCP 서버) 분류하며, 표에서는 관련 하위
              섹션을 묶어서 표시했습니다.
            </p>

            <h2>등록</h2>
            <pre>{`from core.hooks.system import HookSystem, HookEvent

hooks = HookSystem()
hooks.register(
    HookEvent.PROMPT_ASSEMBLED,
    lambda event, data: print(f"assembled hash={data['assembled_hash']}"),
)`}</pre>

            <h2>매처</h2>
            <p>
              핸들러는 dispatch 전에 이벤트를 필터링하는 매처 predicate를 부착할 수 있습니다.
              예를 들어 <code>node=&quot;analyst&quot;</code>일 때만 발화시키는 방식입니다.
              <code>core/hooks/system.py:_filter_by_matcher</code>를 참고하세요.
            </p>

            <h2>PROMPT_ASSEMBLED payload</h2>
            <p>유일한 prompt 관련 이벤트. payload 구성:</p>
            <ul>
              <li><code>node</code>: &ldquo;analyst&rdquo;, &ldquo;evaluator&rdquo;, &ldquo;synthesizer&rdquo;, &ldquo;router&rdquo;</li>
              <li><code>role_type</code>: 예) &ldquo;game_mechanics&rdquo;, &ldquo;quality_judge&rdquo;</li>
              <li><code>base_template_hash</code>, <code>assembled_hash</code> (SHA-256[:12])</li>
              <li><code>fragment_count</code>, <code>total_chars</code>, <code>fragments_used</code></li>
              <li><em>조건부</em> <code>skill_hashes</code> (스킬별 본문 해시)</li>
              <li><em>조건부</em> <code>truncation_events</code></li>
            </ul>
            <p>
              payload에는 해시와 카운터만 담깁니다. 프롬프트 텍스트 자체는 포함되지 않습니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Three trigger modes</h2>
            <ul>
              <li><strong><code>trigger(event, payload)</code></strong> — fire-and-forget. Listener errors are logged and isolated.</li>
              <li><strong><code>trigger_with_result(event, payload)</code></strong> — capture each handler&apos;s return value.</li>
              <li><strong><code>trigger_interceptor(event, payload)</code></strong> — handlers can block or modify the event.</li>
            </ul>
            <p>
              Implementation lives at <code>core/hooks/system.py:200 class HookSystem</code>.
              Concurrent execution is via <code>concurrent.futures</code> with a
              re-entrant lock around handler registration.
            </p>

            <h2>Event groups</h2>
            <table>
              <thead><tr><th>Group</th><th>Count</th><th>Events</th></tr></thead>
              <tbody>
                <tr><td>pipeline</td><td>3</td><td>PIPELINE_START, PIPELINE_END, PIPELINE_ERROR</td></tr>
                <tr><td>node</td><td>4</td><td>NODE_ENTER, NODE_EXIT, NODE_ERROR, NODE_RETRY</td></tr>
                <tr><td>analysis</td><td>3</td><td>ANALYST_START, ANALYST_COMPLETE, ANALYST_FAILED</td></tr>
                <tr><td>verification</td><td>2</td><td>VERIFICATION_PASS, VERIFICATION_FAIL</td></tr>
                <tr><td>automation</td><td>5</td><td>DRIFT_DETECTED, MODEL_PROMOTED, OUTCOME_COLLECTED, EXPERT_VOTE_CAST, FEEDBACK_PHASE_CHANGED</td></tr>
                <tr><td>memory</td><td>4</td><td>MEMORY_SAVED, RULE_CREATED, RULE_UPDATED, RULE_DELETED</td></tr>
                <tr><td>tool</td><td>8</td><td>TOOL_EXEC_START/END/FAILED, TOOL_RECOVERY_START/END, TOOL_APPROVAL_REQUEST/GRANTED/DENIED</td></tr>
                <tr><td>session</td><td>2</td><td>SESSION_START, SESSION_END</td></tr>
                <tr><td>model</td><td>1</td><td>MODEL_SWITCHED</td></tr>
                <tr><td>llm</td><td>4</td><td>LLM_CALL_START, LLM_CALL_END, LLM_CALL_FAILED, LLM_CALL_RETRY</td></tr>
                <tr><td>approval</td><td>2</td><td>APPROVAL_REQUEST, APPROVAL_GRANTED</td></tr>
                <tr><td>context</td><td>2</td><td>CONTEXT_OVERFLOW, CONTEXT_RESET</td></tr>
                <tr><td>prompt</td><td>1</td><td>PROMPT_ASSEMBLED</td></tr>
                <tr><td>turn</td><td>1</td><td>TURN_COMPLETE</td></tr>
              </tbody>
            </table>
            <p>
              Total: 14 groups, 58 events (table summarises the major ones). The
              <code>core/hooks/system.py</code> source comments group events into
              finer sub-sections (subagent lifecycle, agentic turn, session,
              LLM call, tool approval, serve lifecycle, MCP server) — the table
              rolls related sub-sections together.
            </p>

            <h2>Registration</h2>
            <pre>{`from core.hooks.system import HookSystem, HookEvent

hooks = HookSystem()
hooks.register(
    HookEvent.PROMPT_ASSEMBLED,
    lambda event, data: print(f"assembled hash={data['assembled_hash']}"),
)`}</pre>

            <h2>Matchers</h2>
            <p>
              Handlers can attach a matcher predicate to filter events before
              dispatch — e.g. only fire on <code>node=&quot;analyst&quot;</code>.
              See <code>core/hooks/system.py:_filter_by_matcher</code>.
            </p>

            <h2>PROMPT_ASSEMBLED payload</h2>
            <p>The single prompt-related event. Payload contains:</p>
            <ul>
              <li><code>node</code>: &ldquo;analyst&rdquo;, &ldquo;evaluator&rdquo;, &ldquo;synthesizer&rdquo;, &ldquo;router&rdquo;</li>
              <li><code>role_type</code>: e.g. &ldquo;game_mechanics&rdquo;, &ldquo;quality_judge&rdquo;</li>
              <li><code>base_template_hash</code>, <code>assembled_hash</code> (SHA-256[:12])</li>
              <li><code>fragment_count</code>, <code>total_chars</code>, <code>fragments_used</code></li>
              <li><em>conditional</em> <code>skill_hashes</code> (per-skill body hash)</li>
              <li><em>conditional</em> <code>truncation_events</code></li>
            </ul>
            <p>
              The payload contains hashes and counters only — never the prompt
              text itself.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
