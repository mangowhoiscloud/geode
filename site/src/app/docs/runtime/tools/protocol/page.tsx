import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Tools and toolsets — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/tools/protocol"
      title="Tools and toolsets"
      titleKo="도구와 툴셋"
      summary="Tool ownership, provider-aware discovery, and execution permissions."
      summaryKo="도구의 소유자, 프로바이더별 검색 지원, 실행 권한을 구분합니다."
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
              도구 검색은 레지스트리를 대체하지 않습니다. 실행 가능한 도구를
              권한 정책으로 걸러 <code>ToolPlan</code>에 고정한 뒤, 어댑터가
              해당 요청의 지연 로딩 대상과 모델·API 지원 조건을 확인합니다.
              지원 경로에서는 전체 정의를 서버에 보내되 모델의 초기 컨텍스트에는
              일부만 싣습니다. 정의를 네트워크 요청에서 생략한다는 뜻은 아닙니다.
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
                  <td>임계값 초과 + 지원 모델·API + 설정 활성화</td>
                  <td>검색 도구를 추가하고 정책상 지연 가능한 도구만 검색 후 로드; core set과 네이티브 도구는 즉시 로드</td>
                </tr>
                <tr>
                  <td>미지원 경로 또는 검색 비활성화</td>
                  <td>동일한 허용 도구 집합을 즉시 로드. 검색 실패를 이유로 권한 범위를 넓히지 않음</td>
                </tr>
              </tbody>
            </table>
            <p>
              즉시 로드 core set은 <code>TOOL_SEARCH_ALWAYS_LOADED</code>입니다.
              기억, 노트, 파일 읽기, 웹 탐색, 상태 확인처럼 검색 왕복을 치르면
              손해인 고빈도 도구가 여기에 남습니다. 이 정책은 도구 계획을
              만들 때 적용하며, 어댑터가 별도 목록으로 다시 선택하지 않습니다.
            </p>
            <p>
              따라서 도구가 deferred loading 뒤로 밀렸다는 말은 모든 도구가 보이지
              않는다는 뜻이 아닙니다. <code>read_document</code>,{" "}
              <code>grep_files</code>처럼 핵심 읽기 도구는 항상 적재됩니다.
              이런 도구가 반복 호출된다면 모델이 더 많은 근거 파일을 읽겠다고
              판단했을 가능성이 큽니다.
            </p>

            <h3>프로바이더별 경계</h3>
            <p>2026-09-20 공식 계약 점검 기준입니다. 아래 Anthropic 경계·이력 보강은 Unreleased 변경이며 실제 계정 호출은 별도 검증입니다.</p>
            <table>
              <thead><tr><th>GEODE 경로</th><th>도구 노출 방식</th></tr></thead>
              <tbody>
                <tr><td>Anthropic Messages</td><td>공식 endpoint와 검증된 모델 집합에서 regex 검색. 구형·미확인 모델과 호환 프록시는 즉시 로드. cache breakpoint가 붙은 도구는 지연하지 않음.</td></tr>
                <tr><td>OpenAI Responses</td><td>모델 capability gate 뒤 호스티드 검색. 검색 호출·결과와 발견된 function call의 순서를 다음 요청에 보존.</td></tr>
                <tr><td>Codex 구독 Responses</td><td>기존 검증된 경로와 별도 <code>tool_search_defer_codex</code> 설정 유지. OpenAI API 문서만으로 계정 접근 가능성을 단정하지 않음.</td></tr>
                <tr><td>OpenRouter Chat Completions</td><td>즉시 로드. OpenRouter 자체의 검색 beta는 Responses·Messages 전용이므로 현재 경로에는 보내지 않음.</td></tr>
                <tr><td>GLM 직접 / Coding Plan</td><td>즉시 로드. 함수 호출·MCP discovery 지원을 native schema 검색 지원으로 간주하지 않음.</td></tr>
              </tbody>
            </table>
            <p>
              Anthropic의 <code>server_tool_use</code>와 검색 결과는 assistant
              이력으로 보존하며 로컬 실행기에 넘기지 않습니다. 실제로 발견된
              <code>tool_use</code>에만 실행 결과를 반환합니다. 스킬은 별도로
              짧은 metadata를 먼저 보여주고 <code>use_skill</code>로 지침 본문을
              읽습니다. <a href="/geode/docs/runtime/skills">스킬 카탈로그</a>는
              함수 스키마 검색과 다른 책임입니다.
            </p>
            <p>
              근거: <a href="https://developers.openai.com/api/docs/guides/tools-tool-search">OpenAI tool search</a>,{" "}
              <a href="https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool">Anthropic tool search</a>,{" "}
              <a href="https://openrouter.ai/docs/guides/features/server-tools/tool-search">OpenRouter tool search</a>,{" "}
              <a href="https://code.claude.com/docs/en/mcp#configure-tool-search">Claude Code endpoint 정책</a>.
            </p>

            <h2>응답과 재전송 계약</h2>
            <p>
              Unreleased: provider의 refusal은 번역 과정에서도 보존하여 도구
              실행 전에 종료합니다. 분류된 거절 사유만 남기며 임의의 provider
              설명을 진단 이벤트로 복사하지 않습니다. 출력 한도·미완료 등의
              종료 사유도 보존하지만, 이는 해당 사유별 새 자동 재개 정책을
              구현했다는 뜻은 아닙니다.
            </p>
            <p>
              GLM과 OpenRouter의 Chat Completions reasoning 필드는 기존
              assistant 이력과 비공개 세션 저장에 보존합니다. 다음 요청은
              provider·어댑터·모델이 모두 일치할 때만 원본 필드를 재전송합니다.
              다른 provider의 입력이나 공개 trajectory로 옮기지 않습니다.
              OpenAI 출력 스키마는 객체 루트와 지원 구문을 확인한 뒤 strict
              여부를 정하며, 잘못된 루트는 네트워크 호출 전에 거절합니다.
              모든 provider가 같은 strict 보장을 제공한다는 뜻은 아닙니다.
            </p>
            <h2>툴킷: 서브에이전트 도구 번들</h2>
            <p>
              서브에이전트는 선언된 도구 번들만 받습니다. 매니페스트는{" "}
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
              모델에 전달할 도구 결과가 기본 15,000 토큰 임계값을 넘으면{" "}
              <code>core/orchestration/tool_offload.py</code>의{" "}
              <code>ToolResultOffloadStore</code>가 본문을 세션별 디렉터리
              (<code>.geode/tool-offload/</code> 아래)에 내려쓰고, 컨텍스트에는
              요약과 <code>ref_id</code>만 남깁니다. 모델이 원본이 필요하면{" "}
              <code>recall_tool_result(ref_id)</code>로 다시 가져옵니다. 오프로드마다{" "}
              <code>TOOL_RESULT_OFFLOADED</code> 훅이 발화합니다.
            </p>
            <p>
              MCP 결과는 evidence용 원본과 model-facing 표현을 분리합니다.
              timeline과 tool log에는 전체 <code>CallToolResult</code>를 남기고,
              모델에는 <code>structuredContent</code>를 우선한 단일 표현만
              보냅니다. 호환성용 <code>content</code> 복제본을 다시 직렬화하지
              않으며, 오프로드 뒤 25,000-token hard guard가 최종 상한을
              보장합니다.
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
            <p>
              <code>switch_model</code> 승인 요청에는 JSON으로 인코딩한{" "}
              <code>role</code>과 <code>model_hint</code>가 표시됩니다. 역할을
              생략하면 실행 핸들러와 같은 <code>primary</code>가 표시되므로,
              root 모델 변경과 <code>judgment</code> 전환을 승인 전에 구분할 수
              있습니다. 이 상세 정보는 기존 승인 정책을 대체하지 않으며,
              기본 HITL 2에서는 최초 <code>judgment</code> 전환도 승인 대상입니다.
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
                  <td>핵심 읽기 도구는 항상 적재됨. 반복은 모델의 탐색 판단일 가능성이 큼</td>
                  <td>dialogue transcript에서 직전 <code>grep_files</code> 호출과 읽은 경로를 보고, 필요한 경우 질문에 파일 범위나 금지 경로를 명시합니다</td>
                </tr>
                <tr>
                  <td>서브에이전트가 도구 없이 동작</td>
                  <td>frontmatter의 toolkit 이름 오타</td>
                  <td>스폰 로그의 경고를 확인하고 <code>toolkits.toml</code>의 이름과 맞춥니다</td>
                </tr>
                <tr>
                  <td>도구 결과가 잘려 보임</td>
                  <td>15,000 토큰 초과로 오프로드됨</td>
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
              Tool search does not replace the registry. Permissions filter the
              executable set before <code>ToolPlan</code> freezes its definitions
              and deferred membership. The adapter then checks model and API
              support. Supported hosted-search paths still send the complete
              definitions to the server; only initial model-context loading is
              deferred, not transmission of the definitions.
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
                  <td>Above threshold + supported model/API + enabled setting</td>
                  <td>Add search and defer only eligible definitions; core and native tools stay eager</td>
                </tr>
                <tr>
                  <td>Unsupported route or disabled search</td>
                  <td>Load the same authorized set eagerly. A search failure never widens permissions</td>
                </tr>
              </tbody>
            </table>
            <p>
              The eager core set is <code>TOOL_SEARCH_ALWAYS_LOADED</code>:
              high-frequency memory, note, file-read, web, and status tools
              where paying a search round-trip would be wasteful. Composition
              applies this policy once; adapters consume the request snapshot
              rather than selecting from a second registry.
            </p>
            <p>
              Deferred does not mean invisible across the board. Core read tools
              such as <code>read_document</code> and <code>grep_files</code> stay
              eager. Repeated calls to those tools usually mean the model chose
              to gather more evidence, not that the tool cap hid a better tool.
            </p>

            <h3>Provider boundaries</h3>
            <p>Official contracts checked 2026-09-20. The Anthropic admission and replay corrections below are Unreleased; account-level acceptance requires a separate live check.</p>
            <table>
              <thead><tr><th>GEODE route</th><th>Discovery behavior</th></tr></thead>
              <tbody>
                <tr><td>Anthropic Messages</td><td>Regex search on the official endpoint and verified model set. Older/unknown models and compatible proxies stay eager, as do tools carrying cache breakpoints.</td></tr>
                <tr><td>OpenAI Responses</td><td>Hosted search behind the model capability gate. Search calls, results, and discovered function calls replay in order.</td></tr>
                <tr><td>Codex subscription Responses</td><td>Retains the previously verified path and separate <code>tool_search_defer_codex</code> switch. Platform documentation alone does not establish account access.</td></tr>
                <tr><td>OpenRouter Chat Completions</td><td>Eager. OpenRouter offers search in beta on Responses and Messages, not on the endpoint GEODE currently uses.</td></tr>
                <tr><td>GLM direct / Coding Plan</td><td>Eager. Function calling and MCP discovery do not establish native deferred-schema search support.</td></tr>
              </tbody>
            </table>
            <p>
              Anthropic <code>server_tool_use</code> and search results remain
              assistant history, not local executor requests. Only discovered
              <code>tool_use</code> calls receive application results. Skills
              separately expose short metadata and load instructions through
              <code>use_skill</code>; the <a href="/geode/docs/runtime/skills">skill catalog</a>{" "}
              is not a function-schema search service.
            </p>
            <p>
              Sources: <a href="https://developers.openai.com/api/docs/guides/tools-tool-search">OpenAI tool search</a>,{" "}
              <a href="https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool">Anthropic tool search</a>,{" "}
              <a href="https://openrouter.ai/docs/guides/features/server-tools/tool-search">OpenRouter tool search</a>,{" "}
              <a href="https://code.claude.com/docs/en/mcp#configure-tool-search">Claude Code endpoint policy</a>.
            </p>

            <h2>Response and replay contracts</h2>
            <p>
              Unreleased: provider refusal survives translation and terminates
              before tool dispatch. Diagnostics retain only bounded refusal
              classification, not arbitrary provider explanation. Other stop
              reasons, including output limits and incomplete responses, also
              survive translation; this does not add an automatic continuation
              policy for each reason.
            </p>
            <p>
              GLM and OpenRouter Chat Completions reasoning fields remain in
              existing assistant history and private session storage. Subsequent
              requests replay them only when provider, adapter, and model match.
              They are not copied to another provider or public trajectories.
              OpenAI output schemas are checked for object-root and supported
              strict syntax; an invalid root fails before a network call. This
              does not imply identical strict guarantees across providers.
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
              When the model-facing tool result exceeds the default
              15,000-token threshold,{" "}
              <code>ToolResultOffloadStore</code> in{" "}
              <code>core/orchestration/tool_offload.py</code> persists the body
              to a per-session directory under <code>.geode/tool-offload/</code>{" "}
              and leaves a summary plus a <code>ref_id</code> in context. The
              model re-fetches the original with <code>recall_tool_result(ref_id)</code>.
              Each offload fires the <code>TOOL_RESULT_OFFLOADED</code> hook.
            </p>
            <p>
              MCP separates the evidence receipt from the model-facing view.
              The full <code>CallToolResult</code> remains in the timeline and
              tool log, while the model receives one representation that
              prefers <code>structuredContent</code>. GEODE does not serialize
              the compatibility <code>content</code> copy again, and a
              25,000-token hard guard bounds the final value after offload.
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
            <p>
              A <code>switch_model</code> approval request displays JSON-encoded{" "}
              <code>role</code> and <code>model_hint</code>. An omitted role is
              shown as <code>primary</code>, matching the handler default, so
              the operator can distinguish a root-model change from a{" "}
              <code>judgment</code> switch before approving. These details do
              not replace the existing permission policy. Under default HITL 2,
              the first judgment switch still requires approval.
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
                  <td>Inspect the dialogue transcript for the preceding <code>grep_files</code> call and read paths; constrain the file scope in the prompt when needed</td>
                </tr>
                <tr>
                  <td>A sub-agent runs without its tools</td>
                  <td>A typo in the frontmatter toolkit name</td>
                  <td>Check the spawn-time warning and match a name in <code>toolkits.toml</code></td>
                </tr>
                <tr>
                  <td>A tool result looks truncated</td>
                  <td>It crossed 15,000 tokens and was offloaded</td>
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
