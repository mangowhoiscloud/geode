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

            <h2>3. 레지스트리에 등록합니다</h2>
            <p>
              핸들러가 존재한다고 자동으로 호출 대상이 되지는 않습니다.{" "}
              <code>core/wiring/container.py</code>의{" "}
              <code>build_default_registry()</code>에서{" "}
              <code>registry.register(WeatherLookupTool())</code>를 추가해야
              합니다. 같은 이름이 이미 있으면 <code>ToolRegistry.register</code>가{" "}
              <code>ValueError</code>를 던지므로 이름 충돌이 즉시 드러납니다.
            </p>
            <pre>{`# core/wiring/container.py — build_default_registry()
from core.tools.weather_tools import WeatherLookupTool

registry.register(WeatherLookupTool())`}</pre>

            <h2>4. 권한 등급을 정합니다</h2>
            <p>
              권한 분류는 <code>core/agent/safety.py</code>의 frozenset에서
              결정됩니다. 도구가 읽기 전용이면 <code>SAFE_TOOLS</code>에 두면
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
              레지스트리에 실제로 들어갔는지 확인합니다.
            </p>
            <pre>{`uv run python -c "from core.wiring.container import build_default_registry; \\
r = build_default_registry(); print('weather_lookup' in r)"`}</pre>
            <p>
              <code>True</code>가 출력되면 도구가 레지스트리에 등록되어{" "}
              <code>to_anthropic_tools()</code>를 통해 LLM에 노출됩니다. 그 다음
              CLI 스모크로 한 번 불러봅니다.
            </p>
            <pre>{`uv run geode "what's the weather in Seoul"`}</pre>

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

            <h2>3. Register it in the registry</h2>
            <p>
              A handler that exists is not yet callable. Add{" "}
              <code>registry.register(WeatherLookupTool())</code> in{" "}
              <code>build_default_registry()</code> in{" "}
              <code>core/wiring/container.py</code>.{" "}
              <code>ToolRegistry.register</code> raises <code>ValueError</code> if
              the name is already taken, so name collisions surface immediately.
            </p>
            <pre>{`# core/wiring/container.py — build_default_registry()
from core.tools.weather_tools import WeatherLookupTool

registry.register(WeatherLookupTool())`}</pre>

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
            <p>Confirm the tool actually landed in the registry.</p>
            <pre>{`uv run python -c "from core.wiring.container import build_default_registry; \\
r = build_default_registry(); print('weather_lookup' in r)"`}</pre>
            <p>
              When it prints <code>True</code>, the tool is registered and exposed
              to the LLM through <code>to_anthropic_tools()</code>. Then smoke it
              once from the CLI.
            </p>
            <pre>{`uv run geode "what's the weather in Seoul"`}</pre>

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
