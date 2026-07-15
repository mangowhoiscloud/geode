import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Tool calling — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/tool-calling"
      title="Tool calling"
      titleKo="도구 호출"
      summary="How GEODE advertises tools, translates tool choice, executes calls, and replays results across provider adapters."
      summaryKo="GEODE가 도구를 노출하고, tool choice를 변환하고, 호출을 실행한 뒤 결과를 다음 턴에 되돌리는 계약입니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 도구 호출은 특정 프로바이더 payload가 아니라{" "}
              <code>AgenticLoop</code>의 공통 계약에서 시작합니다. 도구 정의를
              adapter-neutral <code>ToolSpec</code>으로 만들고, 선택한 adapter가
              wire 형식으로 변환합니다. 모델이 반환한 호출은 다시 하나의{" "}
              <code>ToolUseBlock</code>으로 정규화되므로 실행기와 다음 턴은
              프로바이더 문법을 알 필요가 없습니다.
            </p>

            <h2>한 라운드의 계약</h2>
            <pre>{`definitions.json / MCP discovery
  → ToolSpec(name, description, input_schema)
  → AdapterCallRequest(tools, tool_choice)
  → provider tool call
  → ToolUseBlock(id, name, input)
  → ToolCallProcessor → tool_result
  → assistant call + result replay → next model round`}</pre>
            <ol>
              <li><code>core/tools/definitions.json</code>과 MCP discovery 결과가 이번 호출의 도구 목록을 만듭니다.</li>
              <li><code>AgenticLoop</code>가 목록과 <code>tool_choice</code>를 <code>AdapterCallRequest</code>에 싣습니다.</li>
              <li>adapter가 프로바이더별 tool definition과 선택 문법으로 변환합니다.</li>
              <li>응답의 호출 id, 이름, 인자를 <code>ToolUseBlock</code>으로 정규화합니다.</li>
              <li><code>ToolCallProcessor</code>가 도구를 실행하고 id가 연결된 결과를 만듭니다.</li>
              <li>assistant의 호출과 tool result를 함께 history에 넣어 다음 모델 라운드로 보냅니다.</li>
            </ol>

            <h2>도구 정의</h2>
            <table>
              <thead>
                <tr><th><code>ToolSpec</code> 필드</th><th>의미</th><th>출처</th></tr>
              </thead>
              <tbody>
                <tr><td><code>name</code></td><td>모델이 호출하고 registry가 handler를 찾는 안정된 이름</td><td><code>definitions.json</code> 또는 MCP tool name</td></tr>
                <tr><td><code>description</code></td><td>도구 선택에 쓰는 모델 가시 설명</td><td>도구 metadata</td></tr>
                <tr><td><code>input_schema</code></td><td>호출 인자의 JSON Schema</td><td>도구 metadata의 입력 계약</td></tr>
              </tbody>
            </table>
            <p>
              이 스키마는 도구 <em>입력</em> 계약입니다. 모델의 최종 답변 shape를
              고정하는 <code>response_schema</code>와는 별개입니다. 레지스트리,
              deferred loading, toolkit 구성은{" "}
              <a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>에서
              설명합니다.
            </p>

            <h2>도구 선택 모드</h2>
            <table>
              <thead>
                <tr><th>Adapter-neutral 값</th><th>의미</th><th><code>AgenticLoop</code> 기본 경로</th></tr>
              </thead>
              <tbody>
                <tr><td><code>auto</code></td><td>모델이 도구 호출과 텍스트 응답 중 선택</td><td>일반 라운드에서 사용</td></tr>
                <tr><td><code>none</code></td><td>도구 호출 금지</td><td>round 또는 time budget의 wrap-up 구간에서 강제</td></tr>
                <tr><td><code>required</code> / <code>any</code></td><td>하나 이상의 도구 호출 요구</td><td>adapter request 계약은 번역하지만 일반 loop는 현재 생성하지 않음</td></tr>
                <tr><td><code>{'{"type":"tool","name":"…"}'}</code></td><td>이름으로 한 도구 강제</td><td>adapter request 계약은 지원하지만 일반 loop의 사용자 설정 표면은 아님</td></tr>
              </tbody>
            </table>
            <p>
              즉, GEODE CLI에서 평소 도구 호출은 <code>auto</code>이고 종료 여유가
              부족해지면 <code>none</code>으로 전환됩니다. <code>required</code>와
              named forcing은 adapter-neutral 내부 표면이지 현재 일반 실행의
              사용자 옵션이 아닙니다.
            </p>

            <h2>내장 adapter 배선</h2>
            <table>
              <thead>
                <tr><th>경로</th><th>GEODE가 만드는 요청</th><th>선택 변환</th><th>결과 replay</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>anthropic-payg</code><br /><code>anthropic-oauth</code></td>
                  <td>Messages API tool definition</td>
                  <td><code>required</code>→<code>any</code>, named→<code>tool</code></td>
                  <td><code>tool_use_id</code>가 있는 <code>tool_result</code></td>
                </tr>
                <tr>
                  <td><code>openai-payg</code><br /><code>codex-oauth</code></td>
                  <td>Responses API의 flat function tool, <code>parallel_tool_calls=true</code></td>
                  <td><code>any</code>→<code>required</code>, named→flat function</td>
                  <td><code>call_id</code>로 묶인 <code>function_call</code> / <code>function_call_output</code></td>
                </tr>
                <tr>
                  <td><code>glm-payg</code><br /><code>glm-coding-plan</code></td>
                  <td>Chat Completions의 nested function tool</td>
                  <td><code>any</code>→<code>required</code>, named→nested function</td>
                  <td><code>tool_call_id</code>가 있는 <code>role=tool</code> message</td>
                </tr>
                <tr>
                  <td><code>claude-cli</code><br /><code>codex-cli</code></td>
                  <td>GEODE adapter 경계는 text-only이며 <code>supports_tools=False</code></td>
                  <td>전달하지 않음</td>
                  <td>GEODE tool result replay 없음</td>
                </tr>
              </tbody>
            </table>
            <p>
              이 표는 GEODE request builder의 보장입니다. 특정 모델이 모든
              선택 모드나 tool schema를 받아들인다는 모델별 호환성 주장까지
              포함하지 않습니다.
            </p>

            <h2>복수 호출과 실행</h2>
            <p>
              한 응답에 <code>tool_use</code> block이 둘 이상이면{" "}
              <code>ToolCallProcessor</code>가 safety tier별 batch를 만듭니다.
              SAFE, MCP auto-approved, 사용자가 batch 승인한 EXPENSIVE 도구는{" "}
              <code>asyncio.gather</code>로 병렬 실행합니다. WRITE와 DANGEROUS
              도구는 개별 승인 뒤 순차 실행하고, 최종 result 순서는 원래 call
              순서를 유지합니다. 호출이 하나면 곧바로 순차 fast path를 사용합니다.
              OpenAI Responses 경로는 모델 쪽 병렬 호출도 명시적으로 켜지만,
              Anthropic과 GLM 요청에는 GEODE 별도 parallel toggle이 없습니다.
            </p>

            <h2>결과 직렬화와 다음 턴</h2>
            <ul>
              <li>일반 결과는 JSON으로 직렬화하고 원래 call id를 유지합니다.</li>
              <li>computer-use screenshot은 텍스트 base64가 아니라 image content block으로 되돌립니다.</li>
              <li>큰 결과는 token guard를 거친 뒤 필요하면 파일로 offload하고 요약과 <code>ref_id</code>만 context에 남깁니다.</li>
              <li>assistant의 호출 message와 user 쪽 tool result를 연달아 history에 추가해야 다음 턴의 id pairing이 유지됩니다.</li>
            </ul>

            <h2>실패와 종료</h2>
            <table>
              <thead>
                <tr><th>상황</th><th>GEODE 동작</th></tr>
              </thead>
              <tbody>
                <tr><td>모델이 tool call 없이 텍스트로 끝냄</td><td>자연 종료로 처리하고 최종 텍스트를 반환</td></tr>
                <tr><td>같은 도구가 연속 실패</td><td>2회 실패를 기록한 뒤 다음 호출에서 adaptive recovery chain을 시작</td></tr>
                <tr><td>전체 도구 오류가 3회 이상 연속</td><td>다른 접근을 요구하는 backpressure hint를 다음 턴에 삽입</td></tr>
                <tr><td>서로 다른 라운드에서 같은 도구와 같은 인자를 5회 반복</td><td>no-progress loop로 보고 diversity hint를 삽입</td></tr>
                <tr><td>CLI adapter를 선택</td><td>도구 schema를 subprocess에 전달하지 않는 text-only 경로</td></tr>
              </tbody>
            </table>

            <h2>구현 기준점</h2>
            <ul>
              <li><code>core/llm/adapters/base.py</code>: <code>ToolSpec</code>, <code>AdapterCallRequest</code>.</li>
              <li><code>core/llm/tool_choice.py</code>: provider별 선택 모드 정규화.</li>
              <li><code>core/llm/adapters/translation.py</code>: loop와 adapter 사이 공통 shape.</li>
              <li><code>core/agent/tool_executor/processor.py</code>: 실행, 병렬화, 결과 직렬화.</li>
              <li><code>core/agent/loop/agent_loop.py</code>: wrap-up 선택과 다음 라운드 replay.</li>
            </ul>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/structured-output">구조화 출력</a>. 최종 답변의 JSON Schema 계약.</li>
              <li><a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>. registry, deferred loading, 접근 제어.</li>
              <li><a href="/geode/docs/guides/custom-tool">커스텀 도구 만들기</a>. 새 <code>ToolSpec</code>의 원천을 추가하는 절차.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE tool calling starts from the shared{" "}
              <code>AgenticLoop</code> contract, not a provider payload. Tool
              definitions become adapter-neutral <code>ToolSpec</code> objects;
              the selected adapter translates them to the wire. Returned calls
              normalize back to <code>ToolUseBlock</code>, so execution and the
              next round do not depend on provider syntax.
            </p>

            <h2>One-round contract</h2>
            <pre>{`definitions.json / MCP discovery
  → ToolSpec(name, description, input_schema)
  → AdapterCallRequest(tools, tool_choice)
  → provider tool call
  → ToolUseBlock(id, name, input)
  → ToolCallProcessor → tool_result
  → assistant call + result replay → next model round`}</pre>
            <ol>
              <li><code>core/tools/definitions.json</code> and MCP discovery build the tool list for this call.</li>
              <li><code>AgenticLoop</code> puts the list and <code>tool_choice</code> into <code>AdapterCallRequest</code>.</li>
              <li>The adapter translates definitions and selection syntax for its provider.</li>
              <li>Call id, name, and arguments normalize to <code>ToolUseBlock</code>.</li>
              <li><code>ToolCallProcessor</code> executes the tools and creates id-correlated results.</li>
              <li>The assistant call and tool results enter history together for the next model round.</li>
            </ol>

            <h2>Tool definition</h2>
            <table>
              <thead><tr><th><code>ToolSpec</code> field</th><th>Meaning</th><th>Source</th></tr></thead>
              <tbody>
                <tr><td><code>name</code></td><td>Stable name called by the model and resolved by the registry</td><td><code>definitions.json</code> or an MCP tool name</td></tr>
                <tr><td><code>description</code></td><td>Model-visible guidance used to select the tool</td><td>Tool metadata</td></tr>
                <tr><td><code>input_schema</code></td><td>JSON Schema for call arguments</td><td>The tool metadata input contract</td></tr>
              </tbody>
            </table>
            <p>
              This is a tool <em>input</em> schema. It is separate from{" "}
              <code>response_schema</code>, which constrains the model&apos;s final
              answer. See <a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>{" "}
              for the registry, deferred loading, and toolkit composition.
            </p>

            <h2>Tool selection modes</h2>
            <table>
              <thead><tr><th>Adapter-neutral value</th><th>Meaning</th><th>Default <code>AgenticLoop</code> path</th></tr></thead>
              <tbody>
                <tr><td><code>auto</code></td><td>The model chooses between a tool call and text</td><td>Used on normal rounds</td></tr>
                <tr><td><code>none</code></td><td>Forbid tool calls</td><td>Forced during round- or time-budget wrap-up</td></tr>
                <tr><td><code>required</code> / <code>any</code></td><td>Require at least one call</td><td>Translated by the adapter request contract; not emitted by the normal loop</td></tr>
                <tr><td><code>{'{"type":"tool","name":"…"}'}</code></td><td>Force one named tool</td><td>Supported by the adapter request contract; not a normal-loop user setting</td></tr>
              </tbody>
            </table>
            <p>
              Normal GEODE CLI rounds therefore use <code>auto</code> and switch
              to <code>none</code> near the termination budget. Required and
              named forcing are internal adapter-neutral surfaces, not current
              end-user options for a standard run.
            </p>

            <h2>Built-in adapter wiring</h2>
            <table>
              <thead><tr><th>Path</th><th>Request GEODE builds</th><th>Selection translation</th><th>Result replay</th></tr></thead>
              <tbody>
                <tr><td><code>anthropic-payg</code><br /><code>anthropic-oauth</code></td><td>Messages API tool definition</td><td><code>required</code>→<code>any</code>, named→<code>tool</code></td><td><code>tool_result</code> with <code>tool_use_id</code></td></tr>
                <tr><td><code>openai-payg</code><br /><code>codex-oauth</code></td><td>Responses API flat function tool with <code>parallel_tool_calls=true</code></td><td><code>any</code>→<code>required</code>, named→flat function</td><td><code>function_call</code> / <code>function_call_output</code> paired by <code>call_id</code></td></tr>
                <tr><td><code>glm-payg</code><br /><code>glm-coding-plan</code></td><td>Chat Completions nested function tool</td><td><code>any</code>→<code>required</code>, named→nested function</td><td><code>role=tool</code> message with <code>tool_call_id</code></td></tr>
                <tr><td><code>claude-cli</code><br /><code>codex-cli</code></td><td>Text-only GEODE adapter boundary with <code>supports_tools=False</code></td><td>Not forwarded</td><td>No GEODE tool-result replay</td></tr>
              </tbody>
            </table>
            <p>
              This table specifies GEODE request builders. It does not assert
              that every model behind a path accepts every selection mode or
              tool schema.
            </p>

            <h2>Multiple calls and execution</h2>
            <p>
              With two or more <code>tool_use</code> blocks in one response,{" "}
              <code>ToolCallProcessor</code> groups them by safety tier. SAFE,
              MCP auto-approved, and user batch-approved EXPENSIVE tools run in
              parallel through <code>asyncio.gather</code>. WRITE and DANGEROUS
              tools receive individual approval and run sequentially; results
              retain the original call order. A single call uses the sequential
              fast path. OpenAI Responses also enables model-side parallel calls
              explicitly, while Anthropic and GLM requests have no separate
              GEODE parallel toggle.
            </p>

            <h2>Result serialization and the next round</h2>
            <ul>
              <li>Ordinary results serialize as JSON and retain the originating call id.</li>
              <li>Computer-use screenshots return as image content blocks, not base64 text.</li>
              <li>Large results pass through the token guard and may be offloaded, leaving a summary and <code>ref_id</code> in context.</li>
              <li>The assistant call and user-side tool result are appended together so id pairing survives the next turn.</li>
            </ul>

            <h2>Failure and termination</h2>
            <table>
              <thead><tr><th>Situation</th><th>GEODE behavior</th></tr></thead>
              <tbody>
                <tr><td>The model ends with text and no tool call</td><td>Natural termination; return the final text</td></tr>
                <tr><td>The same tool fails repeatedly</td><td>After recording two failures, start adaptive recovery on the next call</td></tr>
                <tr><td>Three or more consecutive tool errors overall</td><td>Inject a backpressure hint asking for another approach</td></tr>
                <tr><td>The same tool and arguments repeat across five rounds</td><td>Treat it as no progress and inject a diversity hint</td></tr>
                <tr><td>A CLI adapter is selected</td><td>Text-only path; tool schemas do not cross the subprocess boundary</td></tr>
              </tbody>
            </table>

            <h2>Implementation anchors</h2>
            <ul>
              <li><code>core/llm/adapters/base.py</code>: <code>ToolSpec</code> and <code>AdapterCallRequest</code>.</li>
              <li><code>core/llm/tool_choice.py</code>: provider-specific selection normalization.</li>
              <li><code>core/llm/adapters/translation.py</code>: shared loop-to-adapter shape.</li>
              <li><code>core/agent/tool_executor/processor.py</code>: execution, concurrency, and result serialization.</li>
              <li><code>core/agent/loop/agent_loop.py</code>: wrap-up selection and next-round replay.</li>
            </ul>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/structured-output">Structured output</a>. JSON Schema for the final answer.</li>
              <li><a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>. Registry, deferred loading, and access control.</li>
              <li><a href="/geode/docs/guides/custom-tool">Build a custom tool</a>. Add a new source of <code>ToolSpec</code>.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
