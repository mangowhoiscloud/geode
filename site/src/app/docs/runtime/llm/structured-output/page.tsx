import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Structured output — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/structured-output"
      title="Structured output"
      titleKo="구조화 출력"
      summary="GEODE's JSON Schema contract, adapter wiring, strictness rules, and worker-side validation and retry boundary."
      summaryKo="GEODE의 JSON Schema 계약, adapter별 배선, strictness 규칙, worker 검증과 재시도 경계입니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 구조화 출력 표면은 <code>response_schema</code> 하나입니다.
              caller가 JSON Schema를 loop 또는 특정 LLM call에 붙이면 선택된
              adapter가 자신이 지원하는 wire 형식으로 전달합니다. 다만 필드가
              존재한다는 사실만으로 강제력이 생기지는 않습니다. 실제 보장은
              adapter 배선, schema strictness, worker-side 검증을 나눠 읽어야 합니다.
            </p>

            <h2>계약 범위</h2>
            <table>
              <thead>
                <tr><th>항목</th><th>현재 GEODE 계약</th></tr>
              </thead>
              <tbody>
                <tr><td>입력</td><td><code>dict[str, Any]</code> 형태의 JSON Schema 하나</td></tr>
                <tr><td>기본값</td><td><code>None</code>. 구조화 출력 필드를 wire에 싣지 않음</td></tr>
                <tr><td>적용 범위</td><td>loop 전체 schema 또는 한 번의 <code>_call_llm</code> override</td></tr>
                <tr><td>문서화된 worker 결과</td><td>top-level JSON object. worker validator가 object와 <code>required</code> key를 검사</td></tr>
                <tr><td>별도 constraint 종류</td><td>choice, regex, grammar를 위한 first-class GEODE 필드는 없음</td></tr>
              </tbody>
            </table>
            <p>
              도구의 <code>input_schema</code>는 tool call 인자를 정의하고,{" "}
              <code>response_schema</code>는 모델의 최종 응답을 정의합니다. 둘은
              독립적인 계약이며 하나가 다른 하나를 대신하지 않습니다.
            </p>

            <h2>전달 경로</h2>
            <pre>{`SubTask.response_schema
  → WorkerRequest.response_schema
  → AgenticLoop(response_schema=...)
  → AdapterCallRequest.response_schema
  → adapter-specific output constraint`}</pre>
            <p>
              일반 sub-agent 작업은 위 경로로 schema를 전달합니다. planner나
              judge 같은 보조 호출은 <code>_call_llm(response_schema=...)</code>으로
              loop-level schema를 한 번만 덮어쓸 수 있습니다. override가 없으면
              loop에 설정된 schema를 모든 LLM call에 사용합니다.
            </p>

            <h2>Schema 작성 기준</h2>
            <pre>{`DECISION_SCHEMA = {
    "title": "Decision",
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["accept", "reject"]},
        "reason": {"type": "string"},
    },
    "required": ["decision", "reason"],
    "additionalProperties": False,
}

task = SubTask(..., response_schema=DECISION_SCHEMA)`}</pre>
            <ul>
              <li><code>title</code>은 OpenAI Responses 경로의 schema name이 됩니다. 없으면 <code>response</code>를 사용합니다.</li>
              <li>worker validation을 쓰는 작업은 top-level <code>object</code>와 명시적인 <code>required</code>를 둡니다.</li>
              <li>OpenAI strict enforcement가 필요하면 모든 object에서 <code>additionalProperties: false</code>를 설정하고 모든 property를 <code>required</code>에 넣습니다.</li>
              <li>타입, enum, nested constraint까지 최종적으로 믿어야 하는 caller는 반환 뒤 full schema validation을 수행합니다.</li>
            </ul>

            <h2>내장 adapter 배선</h2>
            <table>
              <thead>
                <tr><th>경로</th><th><code>response_schema</code> wire</th><th>보장 경계</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>openai-payg</code><br /><code>codex-oauth</code></td>
                  <td>Responses API <code>text.format</code>의 <code>json_schema</code></td>
                  <td>strict-compatible schema면 <code>strict=true</code>, 아니면 <code>strict=false</code> hint</td>
                </tr>
                <tr>
                  <td><code>claude-cli</code></td>
                  <td><code>--json-schema &lt;inline JSON&gt;</code></td>
                  <td>CLI subprocess 경계에서 schema flag를 전달</td>
                </tr>
                <tr>
                  <td><code>codex-cli</code></td>
                  <td>임시 JSON 파일을 만든 뒤 <code>--output-schema &lt;FILE&gt;</code></td>
                  <td>subprocess 종료 뒤 임시 파일 삭제</td>
                </tr>
                <tr>
                  <td><code>anthropic-payg</code><br /><code>anthropic-oauth</code></td>
                  <td>현재 공통 Messages request builder가 읽지 않음</td>
                  <td>schema field는 무시됨. JSON discipline이 필요하면 caller prompt와 downstream validation이 별도로 필요</td>
                </tr>
                <tr>
                  <td><code>glm-payg</code><br /><code>glm-coding-plan</code></td>
                  <td>현재 Chat Completions request builder가 읽지 않음</td>
                  <td>이 경로에서는 provider-side schema enforcement 없음</td>
                </tr>
              </tbody>
            </table>
            <p>
              따라서 <code>response_schema</code>가 설정되어도 adapter 선택에 따라
              wire에서 무시될 수 있습니다. GEODE에는 아직 structured-output
              capability를 기준으로 adapter를 선제 차단하는 registry field가
              없습니다. schema 강제가 필요한 작업은 위에서 배선된 경로를
              명시적으로 선택해야 합니다.
            </p>
            <p>
              OpenAI Responses request builder는 tools가 있으면 tool payload와{" "}
              <code>text.format</code>을 같은 요청에 함께 실을 수 있습니다. 반대로
              두 CLI adapter는 structured-output flag는 전달하지만 GEODE tool
              calling은 지원하지 않습니다. 두 capability는 독립적이며, 이 배선
              사실을 모든 모델의 조합 수용 보장으로 확대하지 않습니다.
            </p>

            <h2>OpenAI strict 판정</h2>
            <p>
              OpenAI Responses 경로는 schema를 무조건 <code>strict=true</code>로
              보내지 않습니다. <code>_is_openai_strict_compatible</code>이 다음
              조건을 재귀적으로 검사합니다.
            </p>
            <ul>
              <li>모든 <code>type: object</code>가 <code>additionalProperties: false</code>인가.</li>
              <li>각 object의 property key 전체가 정확히 <code>required</code>에 들어 있는가.</li>
              <li>array의 <code>items</code> schema도 같은 조건을 만족하는가.</li>
              <li><code>oneOf</code>, <code>anyOf</code>, <code>allOf</code>의 모든 branch가 같은 조건을 만족하는가.</li>
            </ul>
            <p>
              모두 만족하면 <code>strict=true</code>, 하나라도 어기면{" "}
              <code>strict=false</code>로 보냅니다. 후자는 schema shape를 전달하는
              hint이지 hard guarantee가 아닙니다. 이 판정 함수를 다른 provider의
              schema subset에 재사용하지 않습니다.
            </p>

            <h2>Worker 검증과 한 번의 retry</h2>
            <p>
              <code>WorkerRequest</code>에 schema가 있는 sub-agent 작업은 첫 실행
              뒤 별도 안전망을 거칩니다. 다음 중 하나면 validator feedback을
              user turn으로 넣고 loop를 정확히 한 번 다시 실행합니다.
            </p>
            <ul>
              <li>결과가 없거나 명시적인 failure termination을 반환함.</li>
              <li>텍스트가 비어 있음.</li>
              <li>본문에서 balanced JSON object를 찾거나 parse할 수 없음.</li>
              <li>parse한 object에 schema의 <code>required</code> key가 빠짐.</li>
            </ul>
            <p>
              retry는 첫 실행 시간이 task timeout의 50% 미만일 때만 허용합니다.{" "}
              <code>input_blocked</code>, <code>user_cancelled</code>,{" "}
              <code>user_clarification_needed</code>는 의도된 non-JSON 종료라서
              retry하지 않습니다. 이 worker validator는 property type, enum,
              nested constraint를 검사하지 않습니다. 그런 full validation은
              downstream parser의 책임입니다.
            </p>

            <h2>보장 수준을 읽는 법</h2>
            <table>
              <thead>
                <tr><th>층</th><th>하는 일</th><th>하지 않는 일</th></tr>
              </thead>
              <tbody>
                <tr><td>Provider/CLI constraint</td><td>선택된 backend에 schema를 전달하거나 강제</td><td>미지원 adapter를 자동으로 다른 경로로 교체하지 않음</td></tr>
                <tr><td>Worker retry</td><td>빈 출력, parse 실패, required key 누락을 한 번 복구</td><td>JSON Schema 전체 검증은 하지 않음</td></tr>
                <tr><td>Downstream parser</td><td>도메인별 type, enum, semantic constraint를 최종 판정</td><td>adapter의 wire 지원을 대신 만들지 않음</td></tr>
              </tbody>
            </table>

            <h2>구현 기준점</h2>
            <ul>
              <li><code>core/llm/adapters/base.py</code>: <code>AdapterCallRequest.response_schema</code>.</li>
              <li><code>core/agent/loop/agent_loop.py</code>: loop-level schema와 per-call override.</li>
              <li><code>core/llm/adapters/_openai_common.py</code>: Responses wire와 strict compatibility.</li>
              <li><code>core/llm/adapters/claude_cli.py</code>, <code>codex_cli.py</code>: CLI flags.</li>
              <li><code>core/agent/worker.py</code>: JSON object 검사와 one-retry gate.</li>
            </ul>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/tool-calling">도구 호출</a>. Tool input schema와 실행/replay 계약.</li>
              <li><a href="/geode/docs/guides/llm-adapter">LLM adapter 추가</a>. 새 경로에 이 schema 표면을 배선하는 절차.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM 라우팅</a>. 어떤 adapter가 선택되는지 결정하는 순서.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE exposes one structured-output surface:{" "}
              <code>response_schema</code>. A caller attaches a JSON Schema to
              a loop or one LLM call, and the selected adapter forwards it in
              the wire format it supports. The field alone does not create a
              guarantee: adapter wiring, schema strictness, and worker-side
              validation are separate layers.
            </p>

            <h2>Contract scope</h2>
            <table>
              <thead><tr><th>Item</th><th>Current GEODE contract</th></tr></thead>
              <tbody>
                <tr><td>Input</td><td>One JSON Schema as <code>dict[str, Any]</code></td></tr>
                <tr><td>Default</td><td><code>None</code>; no structured-output field is put on the wire</td></tr>
                <tr><td>Application scope</td><td>A loop-wide schema or one <code>_call_llm</code> override</td></tr>
                <tr><td>Documented worker result</td><td>A top-level JSON object; the worker validator checks the object and <code>required</code> keys</td></tr>
                <tr><td>Other constraint kinds</td><td>No first-class GEODE fields for choice, regex, or grammar</td></tr>
              </tbody>
            </table>
            <p>
              A tool&apos;s <code>input_schema</code> defines tool-call arguments;
              <code>response_schema</code> defines the model&apos;s final response.
              They are independent contracts.
            </p>

            <h2>Propagation path</h2>
            <pre>{`SubTask.response_schema
  → WorkerRequest.response_schema
  → AgenticLoop(response_schema=...)
  → AdapterCallRequest.response_schema
  → adapter-specific output constraint`}</pre>
            <p>
              Ordinary sub-agent tasks use that path. Auxiliary planner or judge
              calls can override the loop schema once through{" "}
              <code>_call_llm(response_schema=...)</code>. Without an override,
              every LLM call uses the loop-level schema.
            </p>

            <h2>Writing a schema</h2>
            <pre>{`DECISION_SCHEMA = {
    "title": "Decision",
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["accept", "reject"]},
        "reason": {"type": "string"},
    },
    "required": ["decision", "reason"],
    "additionalProperties": False,
}

task = SubTask(..., response_schema=DECISION_SCHEMA)`}</pre>
            <ul>
              <li><code>title</code> becomes the schema name on OpenAI Responses; the fallback is <code>response</code>.</li>
              <li>Worker-validated tasks should use a top-level <code>object</code> and an explicit <code>required</code> list.</li>
              <li>For OpenAI strict enforcement, every object needs <code>additionalProperties: false</code> and every property in <code>required</code>.</li>
              <li>Callers that rely on types, enums, or nested constraints must run full schema validation after the response.</li>
            </ul>

            <h2>Built-in adapter wiring</h2>
            <table>
              <thead><tr><th>Path</th><th><code>response_schema</code> wire</th><th>Guarantee boundary</th></tr></thead>
              <tbody>
                <tr><td><code>openai-payg</code><br /><code>codex-oauth</code></td><td>Responses API <code>json_schema</code> under <code>text.format</code></td><td><code>strict=true</code> when compatible; otherwise a <code>strict=false</code> hint</td></tr>
                <tr><td><code>claude-cli</code></td><td><code>--json-schema &lt;inline JSON&gt;</code></td><td>Passes the schema flag at the CLI subprocess boundary</td></tr>
                <tr><td><code>codex-cli</code></td><td>Writes a temporary JSON file, then <code>--output-schema &lt;FILE&gt;</code></td><td>Deletes the temporary file after the subprocess exits</td></tr>
                <tr><td><code>anthropic-payg</code><br /><code>anthropic-oauth</code></td><td>The shared Messages request builder does not currently read it</td><td>The schema field is ignored; JSON discipline requires a caller prompt and downstream validation</td></tr>
                <tr><td><code>glm-payg</code><br /><code>glm-coding-plan</code></td><td>The Chat Completions request builders do not currently read it</td><td>No provider-side schema enforcement on these paths</td></tr>
              </tbody>
            </table>
            <p>
              An adapter can therefore ignore <code>response_schema</code> even
              when it is set. GEODE does not yet have a registry capability field
              that rejects such a selection up front. Tasks that require schema
              enforcement must explicitly select a wired path from the table.
            </p>
            <p>
              The OpenAI Responses request builder can place tools and{" "}
              <code>text.format</code> on the same request. Conversely, both CLI
              adapters forward structured-output flags while GEODE tool calling
              remains unsupported on those paths. The capabilities are independent;
              this wiring is not a model-wide guarantee for every combination.
            </p>

            <h2>OpenAI strict detection</h2>
            <p>
              The OpenAI Responses path does not send every schema with{" "}
              <code>strict=true</code>. <code>_is_openai_strict_compatible</code>{" "}
              recursively checks that:
            </p>
            <ul>
              <li>every <code>type: object</code> sets <code>additionalProperties: false</code>;</li>
              <li>every property key appears exactly in that object&apos;s <code>required</code> list;</li>
              <li>array <code>items</code> schemas satisfy the same rules; and</li>
              <li>every <code>oneOf</code>, <code>anyOf</code>, and <code>allOf</code> branch is compatible.</li>
            </ul>
            <p>
              A fully compatible schema uses <code>strict=true</code>; any failure
              falls back to <code>strict=false</code>. The latter forwards the
              shape as a hint, not a hard guarantee. The helper is provider-specific
              and must not be reused for another schema subset without verification.
            </p>

            <h2>Worker validation and one retry</h2>
            <p>
              A sub-agent task with <code>WorkerRequest.response_schema</code>{" "}
              runs a separate safety net after its first attempt. Validator
              feedback is added as a user turn and the loop runs exactly once
              more when any of these are true:
            </p>
            <ul>
              <li>the result is missing or carries an explicit failure termination;</li>
              <li>the text is empty;</li>
              <li>no balanced JSON object can be found and parsed; or</li>
              <li>the parsed object is missing a schema <code>required</code> key.</li>
            </ul>
            <p>
              The retry is allowed only when the first attempt consumed less
              than 50% of the task timeout. <code>input_blocked</code>,{" "}
              <code>user_cancelled</code>, and{" "}
              <code>user_clarification_needed</code> are intentional non-JSON
              exits and are not retried. This worker validator does not check
              property types, enums, or nested constraints; the downstream
              parser owns full validation.
            </p>

            <h2>Reading the guarantee levels</h2>
            <table>
              <thead><tr><th>Layer</th><th>What it does</th><th>What it does not do</th></tr></thead>
              <tbody>
                <tr><td>Provider/CLI constraint</td><td>Forwards or enforces the schema on the selected backend</td><td>Does not reroute an unsupported adapter automatically</td></tr>
                <tr><td>Worker retry</td><td>Recovers once from empty output, parse failure, or missing required keys</td><td>Does not perform full JSON Schema validation</td></tr>
                <tr><td>Downstream parser</td><td>Makes the final domain decision on types, enums, and semantic constraints</td><td>Cannot create missing adapter wire support</td></tr>
              </tbody>
            </table>

            <h2>Implementation anchors</h2>
            <ul>
              <li><code>core/llm/adapters/base.py</code>: <code>AdapterCallRequest.response_schema</code>.</li>
              <li><code>core/agent/loop/agent_loop.py</code>: loop-level schema and per-call override.</li>
              <li><code>core/llm/adapters/_openai_common.py</code>: Responses wire and strict compatibility.</li>
              <li><code>core/llm/adapters/claude_cli.py</code> and <code>codex_cli.py</code>: CLI flags.</li>
              <li><code>core/agent/worker.py</code>: JSON object checks and the one-retry gate.</li>
            </ul>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/tool-calling">Tool calling</a>. Tool input schemas and execution/replay.</li>
              <li><a href="/geode/docs/guides/llm-adapter">Add an LLM adapter</a>. Wire this schema surface into a new path.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM routing</a>. How the adapter path is selected.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
