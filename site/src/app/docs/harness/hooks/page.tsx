import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Hook System — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/hooks"
      title="Hook System"
      summary="58 lifecycle events grouped into 12 categories. Listeners can observe, intercept, or modify."
    >
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
        <li><code>node</code>: &ldquo;analyst&rdquo;, &ldquo;evaluator&rdquo;, &ldquo;synthesizer&rdquo;, &ldquo;biasbuster&rdquo;, &ldquo;router&rdquo;</li>
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
    </DocsShell>
  );
}
