import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Tool Protocol — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/tools/protocol"
      title="Tool Protocol"
      summary="Tool protocol, registry, deferred loading. 57 tools (6 always-loaded + 51 deferred), single JSON SOT at core/tools/definitions.json."
    >
      <h2>The protocol</h2>
      <p>
        <code>core/tools/base.py:35</code> defines <code>Tool</code> as a
        Protocol class. Every tool — native, MCP, plugin — implements:
      </p>
      <pre>{`class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    async def execute(self, **kwargs) -> Any: ...`}</pre>

      <h2>Single source of truth</h2>
      <p>
        <code>core/tools/definitions.json</code> centralizes tool metadata
        (name, description, schema, always-on flag). Handlers live in
        category modules (<code>core/tools/file_tools.py</code>,{" "}
        <code>core/tools/memory_tools.py</code>, etc.) and are wired into
        the registry by name.
      </p>

      <h2>Deferred loading</h2>
      <p>
        With 56 tools, sending all definitions on every LLM call would burn
        ~10K tokens of input per turn. GEODE splits the catalog:
      </p>
      <table>
        <thead><tr><th>Tier</th><th>Count</th><th>Behaviour</th></tr></thead>
        <tbody>
          <tr><td>Always-loaded</td><td>6</td><td>Sent on every LLM call: <code>list_ips</code>, <code>search_ips</code>, <code>analyze_ip</code>, <code>memory_search</code>, <code>show_help</code>, <code>general_web_search</code></td></tr>
          <tr><td>Deferred</td><td>51</td><td>Discoverable via <code>tool_search</code>, loaded on demand. Activates when total tools exceed <code>defer_threshold</code> (default 10).</td></tr>
        </tbody>
      </table>
      <p>
        Total tool count: <strong>57</strong> (verified via{" "}
        <code>core/tools/definitions.json</code>). The frozenset of
        always-loaded tools lives at <code>core/tools/registry.py:209-218</code>{" "}
        as <code>ALWAYS_LOADED_TOOLS</code>.
      </p>
      <p>
        The pattern is borrowed from Claude Code&apos;s tool deferred-loading
        design.
      </p>

      <h2>Tool execution lifecycle (Hook events)</h2>
      <ul>
        <li><code>TOOL_EXEC_START</code> — before <code>execute()</code></li>
        <li><code>TOOL_EXEC_END</code> — after success</li>
        <li><code>TOOL_EXEC_FAILED</code> — exception path</li>
        <li><code>TOOL_RECOVERY_START</code> / <code>TOOL_RECOVERY_END</code> — retry path</li>
        <li><code>TOOL_APPROVAL_REQUEST</code> / <code>GRANTED</code> / <code>DENIED</code> — HITL gate</li>
      </ul>

      <h2>4-tier safety</h2>
      <p>
        Tools are tagged with a safety tier in <code>definitions.json</code>:
      </p>
      <ol>
        <li><strong>Read-only</strong> — Read, Grep, Glob, Search → no approval</li>
        <li><strong>Local mutation</strong> — Edit, Write → in-CWD allow-listed</li>
        <li><strong>Side-effect</strong> — Bash, message-send → HITL approval</li>
        <li><strong>Destructive</strong> — rm -rf, force push → confirmation required</li>
      </ol>

      <h2>Categories</h2>
      <ul>
        <li><strong>FileTools</strong> — Read, Write, Edit, Glob, Grep</li>
        <li><strong>MemoryTools</strong> — memory_search, memory_get, memory_save</li>
        <li><strong>DataTools</strong> — query_monolake, IP profile lookup</li>
        <li><strong>ComputerUse</strong> — provider-agnostic desktop automation (PyAutoGUI)</li>
        <li><strong>MCP</strong> — exposed via <code>core/mcp/</code> service (16 servers, 25K guard)</li>
      </ul>
    </DocsShell>
  );
}
