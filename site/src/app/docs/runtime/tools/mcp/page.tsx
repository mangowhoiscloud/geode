import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "MCP Servers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/tools/mcp"
      title="MCP Servers"
      titleKo="MCP 서버"
      summary="MCP servers managed by core/mcp. Token guards, lifecycle, and adapters for Apple Calendar, Discord, Slack, Signal."
      summaryKo="core/mcp가 관리하는 MCP 서버. 토큰 가드, 라이프사이클, Apple Calendar, Discord, Slack, Signal 어댑터."
    >
      <Bi
        ko={
          <>
            <h2>MCP란 무엇인가</h2>
            <p>
              Model Context Protocol. 외부 프로세스 서비스로서 LLM에 도구를
              노출하는 표준입니다. GEODE는 MCP 서버를 <strong>소비</strong>하기도
              하고, 자기 자신을 MCP 서버로 <strong>노출</strong>하기도
              합니다 (<code>core/mcp_server.py</code>).
            </p>

            <h2>매니저</h2>
            <p>
              <code>core/mcp/manager.py</code>가 <code>MCPManager</code>를 보유합니다.
              서버 프로세스를 소유하고 도구 호출을 라우팅하며 가드를 강제합니다.
              공개 API.
            </p>
            <pre>{`class MCPManager:
    async def start_server(self, name: str) -> None: ...
    async def stop_server(self, name: str) -> None: ...
    async def call_tool(self, server: str, tool: str, args: dict) -> Any: ...
    async def list_tools(self, server: str) -> list[ToolSpec]: ...`}</pre>

            <h2>25K 토큰 가드</h2>
            <p>
              MCP 도구는 임의로 큰 페이로드를 반환할 수 있습니다 (웹 fetch,
              디렉토리 트리, DB 쿼리). 상한이 없으면 도구 호출 한 번이 컨텍스트
              윈도를 날려버릴 수 있습니다. GEODE는 모든 MCP 도구 결과에 대해{" "}
              <strong>25,000 토큰</strong>의 하드 상한을 강제합니다. 상한 초과 →
              서버 측 절단 + 절단 지점을 알려주는 sentinel 마커. 모델이 무엇을
              잃었는지 알 수 있도록 합니다.
            </p>
            <p>
              구현. <code>core/mcp/</code>의 결과 경로 위에 있는 가드 미들웨어.
              해당하는 경우 HTML→Markdown 변환이 상한 적용보다 먼저 일어나
              절단이 콘텐츠가 아니라 포매팅 노이즈를 제거하게 합니다.
            </p>

            <h2>관리되는 서버</h2>
            <p>대표 목록 (환경별 가용성에 따라 달라질 수 있음).</p>
            <ul>
              <li>filesystem, git, github</li>
              <li>web (fetch + search)</li>
              <li>apple_calendar, composite_calendar (멀티 계정 병합)</li>
              <li>signal (composite messaging)</li>
              <li>slack, discord</li>
              <li>linkedin-reader (브라우저 제어)</li>
              <li>claude-in-chrome (브라우저 브릿지)</li>
              <li>playwright</li>
              <li>context7 (라이브러리 문서)</li>
              <li>google-drive</li>
              <li>+ 몇 개의 특화 어댑터</li>
            </ul>

            <h2>예외 계층</h2>
            <p>
              <code>core/mcp/base.py:12</code>에 agentic 루프까지 전파되는 실패
              타입이 정의되어 있습니다.
            </p>
            <ul>
              <li><code>MCPTimeoutError</code>. 서버가 시간 안에 응답하지 않음</li>
              <li><code>MCPConnectionError</code>. 서버가 크래시했거나 시작되지 않음</li>
              <li><code>MCPProtocolError</code>. 응답이 잘못된 형식</li>
              <li><code>MCPGuardError</code>. 가드가 호출을 거부함 (크기 상한, 인증 등)</li>
            </ul>

            <h2>GEODE-as-MCP</h2>
            <p>
              <code>core/mcp_server.py</code>는 GEODE 자체 도구 (그리고 제한된
              형태로 agentic 루프 자체) 를 MCP 서버로 노출합니다. Claude Code,
              Codex CLI 같은 다른 에이전트가 GEODE를 자신이 호출하는 다른
              에이전트와 같은 방식으로 호출할 수 있게 해줍니다.
            </p>
          </>
        }
        en={
          <>
            <h2>What MCP is</h2>
            <p>
              Model Context Protocol — a standard for exposing tools to LLMs as
              out-of-process services. GEODE both <strong>consumes</strong> MCP
              servers and <strong>exposes itself</strong> as one (
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

            <h2>Managed servers</h2>
            <p>A representative list (subject to environment-specific availability):</p>
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
          </>
        }
      />
    </DocsShell>
  );
}
