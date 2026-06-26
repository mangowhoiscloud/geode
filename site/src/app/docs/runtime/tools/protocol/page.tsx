import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Tools and toolsets — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/tools/protocol"
      title="Tools and toolsets"
      titleKo="도구와 툴셋"
      summary="The tool registry and deferred loading. A few tools load up front, the rest are fetched on demand."
      summaryKo="도구 레지스트리와 deferred loading입니다. 일부 도구는 미리 로드하고, 나머지는 필요할 때 가져옵니다."
    >
      <Bi
        ko={
          <>
            <p>
              도구 시스템은 세 가지 질문에 답합니다. 도구는 어디 정의되는가
              (레지스트리), 매 호출에 어떤 도구를 싣는가 (deferred loading),
              서브에이전트에게 어떤 도구를 주는가 (툴킷)입니다.
            </p>

            <h2>레지스트리</h2>
            <p>
              <code>core/tools/registry.py</code>의 <code>ToolRegistry</code>가
              네이티브 도구를 관리합니다. 정의의 SoT는{" "}
              <code>core/tools/definitions.json</code> 하나입니다. 이름, 설명,
              입력 스키마가 모두 여기 모이고, 핸들러는 카테고리 모듈에서
              이름으로 연결됩니다. MCP 클라이언트(<code>core/mcp/</code>)가
              발견한 외부 도구는 호출 시점에 네이티브 도구와 병합됩니다.{" "}
              <a href="/geode/docs/runtime/tools/mcp">MCP 서버</a> 참고.
            </p>

            <h2>Deferred loading</h2>
            <p>
              모든 도구 스키마를 모든 호출에 실으면 턴마다 input 토큰을 크게
              태웁니다. 프로바이더 어댑터가 <code>core/llm/tool_defer.py</code>의
              공통 정책을 읽고, 공식 <code>defer_loading</code> 필드와 호스티드
              tool_search 도구로 카탈로그를 나눕니다.
            </p>
            <table>
              <thead>
                <tr><th>조건</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>도구 수가 <code>TOOL_DEFER_THRESHOLD</code>(16) 이하</td>
                  <td>전부 즉시 로드</td>
                </tr>
                <tr>
                  <td>임계값 초과</td>
                  <td>호스티드 <code>tool_search</code>를 추가하고, core set만 즉시 싣고, 나머지는 <code>defer_loading=True</code>로 표시해 검색 후 로드</td>
                </tr>
              </tbody>
            </table>
            <p>
              즉시 로드 core set은 <code>TOOL_SEARCH_ALWAYS_LOADED</code>입니다.
              기억, 노트, 파일 읽기, 웹 탐색, 상태 확인처럼 검색 왕복을 치르면
              손해인 고빈도 도구가 여기에 남고, 나머지는 에이전트가{" "}
              <code>tool_search</code>로 찾아 그때 가져옵니다.
            </p>
            <p>
              따라서 도구가 deferred loading 뒤로 밀렸다는 말은 모든 도구가 보이지
              않는다는 뜻이 아닙니다. <code>read_document</code>,{" "}
              <code>grep_files</code>처럼 핵심 읽기 도구는 항상 적재됩니다.
              이런 도구가 반복 호출된다면 보통 도구 수 제한 때문이 아니라
              모델이 더 많은 근거 파일을 읽겠다고 판단한 결과입니다.
            </p>

            <h2>툴킷: 서브에이전트 도구 번들</h2>
            <p>
              서브에이전트는 도구 전체가 아니라 선언된 번들만 받습니다. 매니페스트는{" "}
              <code>core/tools/toolkits.toml</code>, 해석기는{" "}
              <code>core/tools/toolkit_registry.py</code>입니다.
            </p>
            <ol>
              <li>에이전트 frontmatter의 <code>toolkit:</code> 이름이 있으면 그 툴킷을 사용합니다. <code>includes:</code>는 재귀적으로 펼쳐집니다.</li>
              <li>레거시 <code>tools:</code> 목록이 있으면 그대로 사용합니다.</li>
              <li>둘 다 없거나 이름이 틀리면 읽기 전용 <code>_default</code>(<code>read_document</code>, <code>grep_files</code>)로 폴백합니다.</li>
            </ol>
            <p>
              조합용 leaf는 <code>common_read</code>와 <code>common_write</code>,
              선언용 킷은 <code>web_research</code>, <code>data_analysis</code>,{" "}
              <code>general_purpose</code> 등입니다. 존재하지 않는 도구 이름은
              스폰 시점에 경고를 내고 그 도구 없이 실행됩니다
              (<code>core/agent/worker.py</code>).
            </p>

            <h2>대형 결과: 오프로드와 recall</h2>
            <p>
              도구 결과가 5000 토큰 임계값을 넘으면{" "}
              <code>core/orchestration/tool_offload.py</code>의{" "}
              <code>ToolResultOffloadStore</code>가 본문을 세션별 디렉터리
              (<code>.geode/tool-offload/</code> 아래)에 내려쓰고, 컨텍스트에는
              요약과 <code>ref_id</code>만 남깁니다. 모델이 원본이 필요하면{" "}
              <code>recall_tool_result(ref_id)</code>로 다시 가져옵니다. 오프로드마다{" "}
              <code>TOOL_RESULT_OFFLOADED</code> 훅이 발화합니다.
            </p>

            <h2>접근 제어</h2>
            <p>
              어떤 도구를 누가 쓸 수 있는지는{" "}
              <code>core/tools/policy.py</code>의 <code>PolicyChain</code>이
              6단계로 해석합니다. Profile, Organization, Mode, Agent 레벨,
              Node-scope allowlist, 서브에이전트 자동 승인 위임 순서입니다.
              권한 등급은 STANDARD(서브에이전트 자동 승인 가능),
              WRITE(승인 필요), DANGEROUS(항상 HITL. <code>run_bash</code>,{" "}
              <code>computer</code>)입니다. <code>delegate_task</code>는 별도
              위임 경로로 실행되며, 사람이 없는 headless 세션에서는 denylist가
              먼저 막습니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>모델이 분명히 있는 도구를 못 찾음</td>
                  <td>deferred loading으로 스키마가 아직 적재되지 않음</td>
                  <td>정상 경로입니다. 모델이 <code>tool_search</code>로 찾으면 로드됩니다</td>
                </tr>
                <tr>
                  <td><code>read_document</code>나 <code>grep_files</code>가 반복 호출됨</td>
                  <td>핵심 읽기 도구는 항상 적재됨. tool cap에 숨은 것이 아니라 모델의 탐색 판단일 가능성이 큼</td>
                  <td>run log에서 직전 <code>grep_files</code> 쿼리와 읽은 경로를 보고, 필요한 경우 질문에 파일 범위나 금지 경로를 명시합니다</td>
                </tr>
                <tr>
                  <td>서브에이전트가 도구 없이 동작</td>
                  <td>frontmatter의 toolkit 이름 오타</td>
                  <td>스폰 로그의 경고를 확인하고 <code>toolkits.toml</code>의 이름과 맞춥니다</td>
                </tr>
                <tr>
                  <td>도구 결과가 잘려 보임</td>
                  <td>5000 토큰 초과로 오프로드됨</td>
                  <td><code>recall_tool_result(ref_id)</code>로 원본을 조회합니다</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/mcp">MCP 서버</a>. 외부 도구가 합류하는 클라이언트 측.</li>
              <li><a href="/geode/docs/runtime/orchestration">서브에이전트 오케스트레이션</a>. 툴킷이 적용되는 실행 주체.</li>
              <li><a href="/geode/docs/guides/custom-tool">커스텀 도구 만들기</a>. definitions.json에 도구를 추가하는 절차.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The tool system answers three questions: where tools are defined
              (the registry), which tools ship with each call (deferred loading),
              and which tools a sub-agent receives (toolkits).
            </p>

            <h2>The registry</h2>
            <p>
              <code>ToolRegistry</code> in <code>core/tools/registry.py</code>{" "}
              manages native tools. The single source of truth for definitions is{" "}
              <code>core/tools/definitions.json</code>: name, description, and
              input schema all live there, with handlers wired by name from
              category modules. External tools discovered by the MCP client
              (<code>core/mcp/</code>) are merged with native tools at call time.
              See <a href="/geode/docs/runtime/tools/mcp">MCP servers</a>.
            </p>

            <h2>Deferred loading</h2>
            <p>
              Shipping every tool schema on every call burns a large chunk of
              input tokens per turn. Provider adapters read the shared policy in{" "}
              <code>core/llm/tool_defer.py</code> and split the catalog with the
              official <code>defer_loading</code> field plus the hosted
              tool_search tool.
            </p>
            <table>
              <thead>
                <tr><th>Condition</th><th>Behaviour</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Tool count at or below <code>TOOL_DEFER_THRESHOLD</code> (16)</td>
                  <td>Everything loads eagerly</td>
                </tr>
                <tr>
                  <td>Above the threshold</td>
                  <td>Adds hosted <code>tool_search</code>, keeps the core set eager, and marks the rest <code>defer_loading=True</code> to be loaded after a search</td>
                </tr>
              </tbody>
            </table>
            <p>
              The eager core set is <code>TOOL_SEARCH_ALWAYS_LOADED</code>:
              high-frequency memory, note, file-read, web, and status tools
              where paying a search round-trip would be wasteful. The agent
              discovers everything else through <code>tool_search</code> and
              loads it on demand.
            </p>
            <p>
              Deferred does not mean invisible across the board. Core read tools
              such as <code>read_document</code> and <code>grep_files</code> stay
              eager. Repeated calls to those tools usually mean the model chose
              to gather more evidence, not that the tool cap hid a better tool.
            </p>

            <h2>Toolkits: sub-agent tool bundles</h2>
            <p>
              A sub-agent receives a declared bundle, not the whole catalog. The
              manifest is <code>core/tools/toolkits.toml</code>; the resolver is{" "}
              <code>core/tools/toolkit_registry.py</code>.
            </p>
            <ol>
              <li>If the agent&apos;s frontmatter declares <code>toolkit:</code>, that toolkit is used, with <code>includes:</code> expanded recursively.</li>
              <li>A legacy <code>tools:</code> list is used verbatim.</li>
              <li>With neither (or a missing toolkit name), it falls back to the read-only <code>_default</code> (<code>read_document</code>, <code>grep_files</code>).</li>
            </ol>
            <p>
              Composition leaves are <code>common_read</code> and{" "}
              <code>common_write</code>; declared kits include{" "}
              <code>web_research</code>, <code>data_analysis</code>, and{" "}
              <code>general_purpose</code>. A misspelled tool name warns at spawn
              time and the agent runs without that tool
              (<code>core/agent/worker.py</code>).
            </p>

            <h2>Large results: offload and recall</h2>
            <p>
              When a tool result exceeds the 5000-token threshold,{" "}
              <code>ToolResultOffloadStore</code> in{" "}
              <code>core/orchestration/tool_offload.py</code> persists the body
              to a per-session directory under <code>.geode/tool-offload/</code>{" "}
              and leaves a summary plus a <code>ref_id</code> in context. The
              model re-fetches the original with <code>recall_tool_result(ref_id)</code>.
              Each offload fires the <code>TOOL_RESULT_OFFLOADED</code> hook.
            </p>

            <h2>Access control</h2>
            <p>
              Who may use which tool is resolved by the six-layer{" "}
              <code>PolicyChain</code> in <code>core/tools/policy.py</code>:
              Profile, Organization, Mode, Agent level, Node-scope allowlists,
              then sub-agent auto-approval delegation. Permission levels are
              STANDARD (eligible for sub-agent auto-approval), WRITE (approval
              required), and DANGEROUS (always human-in-the-loop:{" "}
              <code>run_bash</code>, <code>computer</code>).{" "}
              <code>delegate_task</code> runs through the delegation path and is
              denied up front in headless sessions.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>The model cannot find a tool that clearly exists</td>
                  <td>Deferred loading; the schema is not loaded yet</td>
                  <td>The normal path: the model finds it via <code>tool_search</code> and it loads</td>
                </tr>
                <tr>
                  <td><code>read_document</code> or <code>grep_files</code> repeats</td>
                  <td>Core read tools are always loaded; this is usually exploration strategy, not the tool cap hiding alternatives</td>
                  <td>Inspect the run log for the preceding <code>grep_files</code> query and read paths; constrain the file scope in the prompt when needed</td>
                </tr>
                <tr>
                  <td>A sub-agent runs without its tools</td>
                  <td>A typo in the frontmatter toolkit name</td>
                  <td>Check the spawn-time warning and match a name in <code>toolkits.toml</code></td>
                </tr>
                <tr>
                  <td>A tool result looks truncated</td>
                  <td>It crossed 5000 tokens and was offloaded</td>
                  <td>Fetch the original with <code>recall_tool_result(ref_id)</code></td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/mcp">MCP servers</a>. The client side where external tools join.</li>
              <li><a href="/geode/docs/runtime/orchestration">Sub-agent orchestration</a>. The executor toolkits apply to.</li>
              <li><a href="/geode/docs/guides/custom-tool">Build a custom tool</a>. Adding a tool to definitions.json.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
