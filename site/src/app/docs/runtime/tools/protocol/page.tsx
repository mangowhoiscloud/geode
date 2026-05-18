import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Tool Protocol — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/tools/protocol"
      title="Tool Protocol"
      titleKo="도구 프로토콜"
      summary="Tool protocol, registry, deferred loading. 53 tools (6 always-loaded + 47 deferred), single JSON SOT at core/tools/definitions.json."
      summaryKo="도구 프로토콜, 레지스트리, 지연 로딩. 53개 도구 (상시 로드 6개 + 지연 로드 47개), 단일 JSON SOT가 core/tools/definitions.json에 있습니다."
    >
      <Bi
        ko={
          <>
            <h2>프로토콜</h2>
            <p>
              <code>core/tools/base.py:35</code>가 <code>Tool</code>을 Protocol
              클래스로 정의합니다. 네이티브, MCP, 플러그인을 막론하고 모든 도구가
              아래를 구현합니다.
            </p>
            <pre>{`class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    async def execute(self, **kwargs) -> Any: ...`}</pre>

            <h2>단일 진실의 출처</h2>
            <p>
              <code>core/tools/definitions.json</code>이 도구 메타데이터 (이름,
              설명, 스키마, 상시 로드 플래그) 를 중앙 집중화합니다. 핸들러는 카테고리
              모듈 (<code>core/tools/file_tools.py</code>,{" "}
              <code>core/tools/memory_tools.py</code> 등) 에 있고, 이름으로 레지스트리에
              연결됩니다.
            </p>

            <h2>지연 로딩</h2>
            <p>
              도구가 56개일 때 모든 LLM 호출마다 정의 전체를 보내면 턴당 약 10K
              토큰의 input을 태우게 됩니다. GEODE는 카탈로그를 분할합니다.
            </p>
            <table>
              <thead><tr><th>티어</th><th>개수</th><th>동작</th></tr></thead>
              <tbody>
                <tr><td>상시 로드</td><td>6</td><td>모든 LLM 호출에서 전송. <code>memory_search</code>, <code>show_help</code>, <code>general_web_search</code> 등 코어 도구만 포함합니다.</td></tr>
                <tr><td>지연 로드</td><td>55</td><td><code>tool_search</code>로 발견 가능, 요청 시 로드. 전체 도구 수가 <code>defer_threshold</code> (기본 10) 를 넘으면 활성화됩니다.</td></tr>
              </tbody>
            </table>
            <p>
              총 도구 수. <strong>61</strong> (<code>core/tools/definitions.json</code>로
              실측 확인). 상시 로드 도구의 frozenset은{" "}
              <code>core/tools/registry.py:209-218</code>에{" "}
              <code>ALWAYS_LOADED_TOOLS</code>로 정의됩니다.
            </p>
            <p>
              이 패턴은 Claude Code의 도구 지연 로딩 설계에서 빌려온 것입니다.
            </p>

            <h2>도구 실행 라이프사이클 (Hook 이벤트)</h2>
            <ul>
              <li><code>TOOL_EXEC_START</code>. <code>execute()</code> 이전</li>
              <li><code>TOOL_EXEC_END</code>. 성공 이후</li>
              <li><code>TOOL_EXEC_FAILED</code>. 예외 경로</li>
              <li><code>TOOL_RECOVERY_START</code> / <code>TOOL_RECOVERY_END</code>. 재시도 경로</li>
              <li><code>TOOL_APPROVAL_REQUEST</code> / <code>GRANTED</code> / <code>DENIED</code>. HITL 게이트</li>
            </ul>

            <h2>4-티어 안전성</h2>
            <p>
              도구는 <code>definitions.json</code>에서 안전 티어로 태깅됩니다.
            </p>
            <ol>
              <li><strong>읽기 전용</strong>. Read, Grep, Glob, Search → 승인 없음</li>
              <li><strong>로컬 변경</strong>. Edit, Write → CWD 내 allow-list</li>
              <li><strong>부수 효과</strong>. Bash, 메시지 전송 → HITL 승인</li>
              <li><strong>파괴적</strong>. rm -rf, force push → 확인 필요</li>
            </ol>

            <h2>카테고리</h2>
            <ul>
              <li><strong>FileTools</strong>. Read, Write, Edit, Glob, Grep</li>
              <li><strong>MemoryTools</strong>. memory_search, memory_get, memory_save</li>
              <li><strong>DataTools</strong>. Cortex Analyst/Search 기반 데이터 조회</li>
              <li><strong>ComputerUse</strong>. 프로바이더 독립 데스크탑 자동화 (PyAutoGUI)</li>
              <li><strong>MCP</strong>. <code>core/mcp/</code> 서비스를 통해 노출 (서버 16개, 25K 가드)</li>
            </ul>
          </>
        }
        en={
          <>
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
              With 53 tools, sending all definitions on every LLM call would burn
              ~10K tokens of input per turn. GEODE splits the catalog:
            </p>
            <table>
              <thead><tr><th>Tier</th><th>Count</th><th>Behaviour</th></tr></thead>
              <tbody>
                <tr><td>Always-loaded</td><td>6</td><td>Sent on every LLM call: core tools such as <code>memory_search</code>, <code>show_help</code>, and <code>general_web_search</code>.</td></tr>
                <tr><td>Deferred</td><td>55</td><td>Discoverable via <code>tool_search</code>, loaded on demand. Activates when total tools exceed <code>defer_threshold</code> (default 10).</td></tr>
              </tbody>
            </table>
            <p>
              Total tool count: <strong>61</strong> (verified via{" "}
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
              <li><strong>DataTools</strong> — Cortex Analyst/Search data retrieval</li>
              <li><strong>ComputerUse</strong> — provider-agnostic desktop automation (PyAutoGUI)</li>
              <li><strong>MCP</strong> — exposed via <code>core/mcp/</code> service (16 servers, 25K guard)</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
