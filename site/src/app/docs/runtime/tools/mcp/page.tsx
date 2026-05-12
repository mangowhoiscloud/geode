import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "MCP Servers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/tools/mcp"
      title="MCP Servers"
      summary="16 MCP servers managed by core/mcp. Token guards, lifecycle, and adapters for Apple Calendar, Discord, Slack, Signal."
    >
      <h2>What MCP is</h2>
      <p>
        Model Context Protocol — a standard for exposing tools to LLMs as
        out-of-process services. GEODE both <strong>consumes</strong> MCP
        servers (16 of them) and <strong>exposes itself</strong> as one (
        <code>core/mcp_server.py</code>).
      </p>

      <h2>The manager</h2>
      <p>
        <code>core/mcp/manager.py</code> holds <code>MCPManager</code>, which
        owns server processes, routes tool calls, and enforces guards. The
        public API:
      </p>
      <pre>{`class MCPManager:
    async def start_server(self, name: str) -> None: ...
    async def stop_server(self, name: str) -> None: ...
    async def call_tool(self, server: str, tool: str, args: dict) -> Any: ...
    async def list_tools(self, server: str) -> list[ToolSpec]: ...`}</pre>

      <h2>The 25K token guard</h2>
      <p>
        MCP tools can return arbitrarily large payloads (a web fetch, a
        directory tree, a database query). Without a cap, a single tool
        call can blow the context window. GEODE enforces a hard{" "}
        <strong>25,000 token</strong> cap on every MCP tool result. Over the
        cap → server-side truncation + a sentinel marker indicating where
        the truncation happened, so the model knows what it lost.
      </p>
      <p>
        Implementation: <code>core/mcp/</code> guard middleware on the
        result path. HTML→Markdown conversion (when applicable) happens
        before the cap so the truncation removes formatting noise rather
        than content.
      </p>

      <h2>The 16 servers</h2>
      <p>The list as of v0.64.0 (subject to environment-specific availability):</p>
      <ul>
        <li>filesystem, git, github</li>
        <li>web (fetch + search)</li>
        <li>apple_calendar, composite_calendar (multi-account merge)</li>
        <li>signal (composite messaging)</li>
        <li>slack, discord</li>
        <li>linkedin-reader (browser-controlled)</li>
        <li>claude-in-chrome (browser bridge)</li>
        <li>playwright</li>
        <li>context7 (library docs)</li>
        <li>google-drive</li>
        <li>+ a few specialized adapters</li>
      </ul>

      <h2>Exception hierarchy</h2>
      <p>
        <code>core/mcp/base.py:12</code> defines the failure types that
        propagate up to the agentic loop:
      </p>
      <ul>
        <li><code>MCPTimeoutError</code> — server did not respond in time</li>
        <li><code>MCPConnectionError</code> — server crashed or never started</li>
        <li><code>MCPProtocolError</code> — malformed response</li>
        <li><code>MCPGuardError</code> — guard rejected the call (size cap, auth, etc.)</li>
      </ul>

      <h2>GEODE-as-MCP</h2>
      <p>
        <code>core/mcp_server.py</code> exposes GEODE&apos;s own tools (and
        the agentic loop itself, in restricted form) as an MCP server. This
        lets other agents — Claude Code, Codex CLI, etc. — call GEODE the
        same way GEODE calls them.
      </p>
    </DocsShell>
  );
}
