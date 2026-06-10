import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Write a tool — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="guides/custom-tool"
      title="Write a tool"
      titleKo="도구 작성"
      summary="Define a tool, register it, and gate it with a permission policy."
      summaryKo="도구를 정의하고 등록한 뒤 권한 정책으로 게이트를 거는 방법입니다."
    >
      <Bi
        ko={
          <>
            <p>
              도구는 LLM이 부를 수 있는 함수입니다. 새 능력을 루프 안에 직접
              넣지 말고 도구로 추가하면, 루프는 얇게 유지되고 권한 게이트와 훅이
              그 도구에도 그대로 적용됩니다. 도구 하나를 추가하는 작업은 네 단계로
              나뉩니다. 정의, 구현, 등록, 권한 분류입니다.
            </p>

            <h2>1. 정의를 등록합니다</h2>
            <p>
              LLM이 보는 스키마는 <code>core/tools/definitions.json</code>에
              모읍니다. 항목은 리스트의 한 객체이고, <code>name</code>(snake_case),{" "}
              <code>description</code>, <code>input_schema</code>(JSON Schema),
              그리고 분류 메타데이터인 <code>category</code>와{" "}
              <code>cost_tier</code>를 가집니다.
            </p>
            <pre>{`{
  "name": "weather_lookup",
  "description": "Look up the current weather for a city.",
  "category": "external",
  "cost_tier": "free",
  "input_schema": {
    "type": "object",
    "properties": {
      "city": { "type": "string", "description": "City name" }
    },
    "required": ["city"]
  }
}`}</pre>
            <p>
              <code>category</code>와 <code>cost_tier</code>의 허용 값은{" "}
              <code>core/tools/base.py</code>의 <code>VALID_CATEGORIES</code>와{" "}
              <code>VALID_COST_TIERS</code>(<code>free</code> /{" "}
              <code>cheap</code> / <code>expensive</code>)에 정의되어 있습니다.
            </p>

            <h2>2. 핸들러를 구현합니다</h2>
            <p>
              도구는 <code>core/tools/base.py</code>의 <code>Tool</code> 프로토콜을
              따릅니다. <code>name</code>, <code>description</code>,{" "}
              <code>parameters</code> 프로퍼티와 <code>aexecute()</code> 코루틴
              네 가지면 유효한 도구입니다. 상속이 아니라 덕 타이핑이므로 클래스를
              상속할 필요가 없습니다. 실패는 raise 대신{" "}
              <code>tool_error()</code>로 구조화된 dict을 돌려줘서 LLM이 분류하고
              복구할 수 있게 합니다. 기존 구현은{" "}
              <code>core/tools/web_tools.py</code>의 <code>WebFetchTool</code>을
              참고하세요.
            </p>
            <pre>{`# core/tools/weather_tools.py
from typing import Any

class WeatherLookupTool:
    @property
    def name(self) -> str:
        return "weather_lookup"

    @property
    def description(self) -> str:
        return "Look up the current weather for a city."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        city = kwargs["city"]
        if not city:
            from core.tools.base import tool_error
            return tool_error("city is required", error_type="validation")
        # ... fetch and shape ...
        return {"result": {"city": city, "summary": "..."}}`}</pre>

            <h2>3. 핸들러 맵에 등록합니다</h2>
            <p>
              핸들러가 존재한다고 자동으로 호출 대상이 되지는 않습니다.
              실행은 <code>ToolExecutor</code>가 이름과 핸들러 함수의 dict에서
              찾아 일어나고, 그 dict은{" "}
              <code>core/cli/tool_handlers/</code>의{" "}
              <code>_build_tool_handlers()</code>가 그룹별 빌더를 합쳐
              만듭니다. 기존 단일 도구들과 같은 모양으로, 클래스를 인스턴스화해{" "}
              <code>aexecute</code>를 감싼 클로저를 돌려주는 빌더를 추가하고
              병합 목록에 넣습니다
              (<code>core/cli/tool_handlers/single_tool.py</code>의 패턴).
            </p>
            <pre>{`# core/cli/tool_handlers/single_tool.py 패턴
def _build_weather_handlers() -> dict[str, Any]:
    from core.tools.weather_tools import WeatherLookupTool
    tool = WeatherLookupTool()

    async def handle_weather_lookup(**kwargs: Any) -> dict[str, Any]:
        return await tool.aexecute(**kwargs)

    return {"weather_lookup": handle_weather_lookup}

# core/cli/tool_handlers/__init__.py — _build_tool_handlers()
handlers.update(_build_weather_handlers())`}</pre>
            <p>
              definitions.json의 <code>name</code>과 dict 키가 정확히 같아야
              합니다. 스키마만 있고 핸들러가 없으면 LLM이 도구를 부를 때
              &quot;No handler for tool&quot; 경고와 함께 실패합니다.
            </p>

            <h2>4. 권한 등급을 정합니다</h2>
            <p>
              권한 분류는 <code>core/agent/safety.py</code>의 frozenset에서
              결정됩니다. 읽기 전용 도구는 <code>SAFE_TOOLS</code>에 둡니다.
              승인 없이 실행됩니다. 영속 상태(메모리, 파일, 자격증명)를
              바꾸면 <code>WRITE_TOOLS</code>에 넣어 사용자 확인을 받게 하고,
              시스템 접근이면 <code>DANGEROUS_TOOLS</code>에 넣습니다. 비용이 큰
              호출이면 <code>EXPENSIVE_TOOLS</code> dict에 예상 비용을 적어
              비용 확인 게이트를 켭니다. 이 set들을{" "}
              <code>ApprovalWorkflow</code>(<code>core/agent/approval.py</code>)가
              읽어서 실행 직전에 HITL 프롬프트를 띄웁니다.
            </p>
            <pre>{`# core/agent/safety.py
SAFE_TOOLS = frozenset({
    ...,
    "weather_lookup",  # read-only — no approval prompt
})`}</pre>
            <p>
              모드별·노드별 추가 차단이 필요하면{" "}
              <code>core/tools/policy.py</code>의 <code>PolicyChain</code>으로
              <code>denied_tools</code> / <code>allowed_tools</code>를 거는
              6-layer 정책 체인을 사용합니다.
            </p>

            <h2>확인</h2>
            <p>
              스키마와 핸들러 양쪽이 실제로 연결됐는지 확인합니다.
            </p>
            <pre>{`uv run python -c "
from core.tools.base import load_tool_definition
from core.cli.tool_handlers import _build_tool_handlers
print(load_tool_definition('weather_lookup')['name'])
print('weather_lookup' in _build_tool_handlers())
"`}</pre>
            <p>
              둘 다 통과하면 LLM에 스키마가 노출되고 호출이 실행됩니다. 마지막으로
              대화형 세션에서 한 번 불러봅니다. 셸 원샷은 지원하지 않습니다.
            </p>
            <pre>{`geode

> 서울 날씨 알려줘`}</pre>

            <p className="text-[var(--ink-3)] text-sm">
              <em>참조:</em>{" "}
              <a href="/geode/docs/runtime/tools/protocol">Tool protocol</a>,{" "}
              <a href="/geode/docs/runtime/tools/mcp">MCP tools</a>.
            </p>
          </>
        }
        en={
          <>
            <p>
              A tool is a function the LLM can call. Adding a capability as a tool
              instead of inlining it in the loop keeps the loop thin and lets the
              permission gates and hooks apply to your tool too. Adding one tool is
              four steps: define, implement, register, classify.
            </p>

            <h2>1. Register the definition</h2>
            <p>
              The schema the LLM sees lives in{" "}
              <code>core/tools/definitions.json</code>. An entry is one object in
              the list with <code>name</code> (snake_case),{" "}
              <code>description</code>, <code>input_schema</code> (JSON Schema), and
              the classification metadata <code>category</code> and{" "}
              <code>cost_tier</code>.
            </p>
            <pre>{`{
  "name": "weather_lookup",
  "description": "Look up the current weather for a city.",
  "category": "external",
  "cost_tier": "free",
  "input_schema": {
    "type": "object",
    "properties": {
      "city": { "type": "string", "description": "City name" }
    },
    "required": ["city"]
  }
}`}</pre>
            <p>
              The allowed values for <code>category</code> and{" "}
              <code>cost_tier</code> (<code>free</code> / <code>cheap</code> /{" "}
              <code>expensive</code>) are defined in{" "}
              <code>core/tools/base.py</code> as <code>VALID_CATEGORIES</code> and{" "}
              <code>VALID_COST_TIERS</code>.
            </p>

            <h2>2. Implement the handler</h2>
            <p>
              A tool satisfies the <code>Tool</code> protocol in{" "}
              <code>core/tools/base.py</code>. Four members make it valid: the{" "}
              <code>name</code>, <code>description</code>, and{" "}
              <code>parameters</code> properties plus the <code>aexecute()</code>{" "}
              coroutine. The protocol is duck-typed, so you do not subclass
              anything. Return a structured dict via <code>tool_error()</code>{" "}
              instead of raising, so the LLM can classify and recover. Model it on{" "}
              <code>WebFetchTool</code> in <code>core/tools/web_tools.py</code>.
            </p>
            <pre>{`# core/tools/weather_tools.py
from typing import Any

class WeatherLookupTool:
    @property
    def name(self) -> str:
        return "weather_lookup"

    @property
    def description(self) -> str:
        return "Look up the current weather for a city."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        city = kwargs["city"]
        if not city:
            from core.tools.base import tool_error
            return tool_error("city is required", error_type="validation")
        # ... fetch and shape ...
        return {"result": {"city": city, "summary": "..."}}`}</pre>

            <h2>3. Register it in the handler map</h2>
            <p>
              A handler that exists is not yet callable. Execution happens when{" "}
              <code>ToolExecutor</code> looks the name up in a dict of handler
              functions, and that dict is assembled by{" "}
              <code>_build_tool_handlers()</code> in{" "}
              <code>core/cli/tool_handlers/</code> from per-group builders. Add
              a builder in the same shape as the existing single-tool wrappers
              (instantiate the class, wrap <code>aexecute</code> in a closure)
              and merge it in
              (the pattern in <code>core/cli/tool_handlers/single_tool.py</code>).
            </p>
            <pre>{`# the core/cli/tool_handlers/single_tool.py pattern
def _build_weather_handlers() -> dict[str, Any]:
    from core.tools.weather_tools import WeatherLookupTool
    tool = WeatherLookupTool()

    async def handle_weather_lookup(**kwargs: Any) -> dict[str, Any]:
        return await tool.aexecute(**kwargs)

    return {"weather_lookup": handle_weather_lookup}

# core/cli/tool_handlers/__init__.py — _build_tool_handlers()
handlers.update(_build_weather_handlers())`}</pre>
            <p>
              The dict key must match the <code>name</code> in definitions.json
              exactly. A schema without a handler fails at call time with a
              &quot;No handler for tool&quot; warning.
            </p>

            <h2>4. Set the permission tier</h2>
            <p>
              The tier is decided by the frozensets in{" "}
              <code>core/agent/safety.py</code>. If the tool is read-only, add it
              to <code>SAFE_TOOLS</code> and it runs without an approval prompt. If
              it mutates persistent state (memory, files, credentials), add it to{" "}
              <code>WRITE_TOOLS</code> so it requires user confirmation; for system
              access, use <code>DANGEROUS_TOOLS</code>. For costly calls, add an
              estimate to the <code>EXPENSIVE_TOOLS</code> dict to flip the cost
              gate on. <code>ApprovalWorkflow</code> in{" "}
              <code>core/agent/approval.py</code> reads these sets and raises the
              HITL prompt just before execution.
            </p>
            <pre>{`# core/agent/safety.py
SAFE_TOOLS = frozenset({
    ...,
    "weather_lookup",  # read-only — no approval prompt
})`}</pre>
            <p>
              For per-mode or per-node filtering on top of the tier, use the{" "}
              <code>PolicyChain</code> in <code>core/tools/policy.py</code> to set{" "}
              <code>denied_tools</code> / <code>allowed_tools</code> across the
              6-layer policy chain.
            </p>

            <h2>Verify</h2>
            <p>Confirm both ends, the schema and the handler, are wired.</p>
            <pre>{`uv run python -c "
from core.tools.base import load_tool_definition
from core.cli.tool_handlers import _build_tool_handlers
print(load_tool_definition('weather_lookup')['name'])
print('weather_lookup' in _build_tool_handlers())
"`}</pre>
            <p>
              When both pass, the LLM sees the schema and calls execute. Finally
              smoke it inside an interactive session; a shell one-shot is not
              supported.
            </p>
            <pre>{`geode

> what's the weather in Seoul`}</pre>

            <p className="text-[var(--ink-3)] text-sm">
              <em>See:</em>{" "}
              <a href="/geode/docs/runtime/tools/protocol">Tool protocol</a>,{" "}
              <a href="/geode/docs/runtime/tools/mcp">MCP tools</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
