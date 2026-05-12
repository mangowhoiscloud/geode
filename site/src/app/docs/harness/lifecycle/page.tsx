import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Lifecycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/lifecycle"
      title="Lifecycle"
      summary="Bootstrap, serve, shutdown. core/lifecycle/ + core/runtime.py drive the daemon's life cycle, handle signal-based termination, and emit lifecycle hook events."
    >
      <h2>Five phases</h2>
      <pre>{`1. Bootstrap     — read config, init paths, register hooks, set ContextVars
2. Wire          — start MCP servers, load tools, discover skills, mount domain plugins
3. Serve         — listen on IPC, accept commands, drive AgenticLoop
4. Drain         — finish pending tool calls, flush queues, close LLM clients
5. Shutdown      — close IPC socket, write session log, exit`}</pre>

      <h2>Entry points</h2>
      <table>
        <thead><tr><th>File</th><th>Role</th></tr></thead>
        <tbody>
          <tr><td><code>core/runtime.py</code></td><td>top-level <code>bootstrap()</code></td></tr>
          <tr><td><code>core/lifecycle/</code> (5 modules)</td><td>phase implementations + signal handlers</td></tr>
          <tr><td><code>core/server/</code> (10 modules)</td><td>IPC listener, request dispatch, daemon main loop</td></tr>
        </tbody>
      </table>

      <h2>Signals</h2>
      <ul>
        <li><strong>SIGTERM</strong> — graceful drain, then shutdown</li>
        <li><strong>SIGINT</strong> — interrupt current LLM call (<code>UserCancelledError</code> propagates), keep daemon alive</li>
        <li><strong>SIGHUP</strong> — reload config (env vars, model registry)</li>
      </ul>

      <h2>ContextVar wiring</h2>
      <p>
        Bootstrap sets <code>ContextVar</code> instances for current session,
        current model, current user profile, and current hook system. The
        agentic loop and tool handlers read these via <code>get_*()</code>{" "}
        accessors instead of receiving them as arguments.
      </p>
      <p>
        CLAUDE.md anti-pattern: a <code>get_*()</code> accessor without a
        corresponding <code>set_*()</code> in bootstrap silently returns{" "}
        <code>None</code> and the dependent feature degrades silently. The
        Wiring Verification table in CLAUDE.md is the gate against this.
      </p>

      <h2>Hook events fired</h2>
      <ul>
        <li><code>SESSION_START</code> — at the end of bootstrap</li>
        <li><code>SESSION_END</code> — at the start of drain</li>
        <li><code>MODEL_SWITCHED</code> — when <code>/model</code> rotates</li>
        <li><code>CONTEXT_RESET</code> — on <code>/clear</code></li>
      </ul>

      <h2>Crash recovery</h2>
      <p>
        Unhandled exceptions in the daemon are caught at the top of the
        request dispatcher, logged with full traceback, and a structured
        error frame is returned to the CLI. The daemon stays alive — only
        the failing call dies. <code>geode serve</code> with{" "}
        <code>--auto-restart</code> respawns on hard crash.
      </p>
    </DocsShell>
  );
}
