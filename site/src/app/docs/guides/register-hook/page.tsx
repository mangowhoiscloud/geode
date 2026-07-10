import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Register a hook — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="guides/register-hook"
      title="Register a hook"
      titleKo="훅 등록"
      summary="Subscribe a handler to a lifecycle event and wire it in bootstrap."
      summaryKo="라이프사이클 이벤트에 핸들러를 구독하고 bootstrap에 연결하는 방법입니다."
    >
      <Bi
        ko={
          <>
            <p>
              훅은 루프가 의미 있는 경계에서 발화하는 이벤트에 핸들러를 붙이는
              방법입니다. 관측, 비용 집계, 감사 로그 같은 횡단 관심사를 루프 코드를
              건드리지 않고 추가할 때 씁니다. 가장 흔한 함정은 핸들러를 작성하고도
              bootstrap에 등록하지 않는 것입니다. 핸들러가 존재한다고 발화하지는
              않습니다.
            </p>

            <h2>1. 이벤트를 고릅니다</h2>
            <p>
              발화 지점은 <code>core/hooks/system.py</code>의{" "}
              <code>HookEvent</code> enum에 모두 정의되어 있습니다. 도구 실행을
              듣고 싶으면 <code>TOOL_EXEC_STARTED</code> /{" "}
              <code>TOOL_EXEC_ENDED</code> / <code>TOOL_EXEC_FAILED</code>,
              세션 경계는 <code>SESSION_STARTED</code> /{" "}
              <code>SESSION_ENDED</code>, LLM 호출은{" "}
              <code>LLM_CALL_STARTED</code> / <code>LLM_CALL_ENDED</code>를
              고릅니다. 없는 이벤트가 필요하면 enum에 멤버를 추가하고 발화 지점도
              같은 PR에 함께 넣습니다. 예약만 하고 emit-site를 미루면 발화하지 않는
              죽은 이벤트가 됩니다.
            </p>

            <h2>2. 핸들러를 작성합니다</h2>
            <p>
              핸들러 시그니처는 <code>(event: HookEvent, data: dict) -&gt; None</code>입니다.
              fire-and-forget 관측자는 <code>None</code>을 돌려주고, 권고 값을
              호출자에게 돌려주는 피드백 훅은 dict을 돌려줍니다. 핸들러 안의
              예외는 <code>HookSystem.trigger</code>가 잡아서 경고 로그로
              남기므로 다른 핸들러를 막지 않습니다. 동기·비동기 둘 다 지원합니다.
            </p>
            <pre>{`from core.hooks import HookEvent

def on_tool_failed(event: HookEvent, data: dict) -> None:
    tool_name = data.get("tool_name", "")
    error = data.get("error", "")
    # observe only — no return value needed
    log.warning("tool %s failed: %s", tool_name, error)`}</pre>

            <h2>3. bootstrap에서 등록합니다</h2>
            <p>
              이 단계가 핵심입니다. <code>core/wiring/bootstrap.py</code>의{" "}
              <code>build_hooks()</code>가 <code>HookSystem</code>을 만들고 모든
              핵심 핸들러를 붙이는 곳입니다. 거기서{" "}
              <code>hooks.register(event, handler, name=..., priority=...)</code>를
              호출합니다. <code>name</code>은 겹치는 exact/prefix 범위에서
              고유해야 합니다. 다른 핸들러를 같은 이름으로 등록하면 fail-loud하며,
              의도적 교체만 <code>replace=True</code>를 사용합니다.
            </p>
            <pre>{`# core/wiring/bootstrap.py — build_hooks()
hooks.register(
    HookEvent.TOOL_EXEC_FAILED,
    on_tool_failed,
    name="tool_failure_observer",
    priority=60,
)`}</pre>
            <p>
              한 핸들러를 이벤트 family에 붙이려면{" "}
              <code>register_prefix(&quot;SUBAGENT&quot;, handler, ...)</code>를 씁니다.
              운영 이벤트 저장은 일반 핸들러가 아니라 post-dispatch sink가 담당합니다.
            </p>

            <h2>4. 우선순위 등급을 정합니다</h2>
            <p>
              <code>priority</code>는 낮을수록 먼저 실행됩니다(기본 100).
              데이터를 보강하는 인터셉터는 낮게, 단순 관측자는 높게 둡니다. 기존
              bootstrap의 등급을 기준으로 삼으면 됩니다. metrics는 45,
              agent_runtime_state 기록은 55, 세션 라이프사이클 로거는 90입니다.
              <code>trigger_interceptor()</code> 경로의 핸들러는{" "}
              <code>{`{"block": True}`}</code> 또는{" "}
              <code>{`{"modify": {...}}`}</code>를 돌려줘 체인을 막거나 데이터를
              수정할 수 있습니다.
            </p>

            <h2>확인</h2>
            <p>
              발화되는지 직접 트리거해서 확인합니다.{" "}
              <code>list_hooks()</code>는 와일드카드 구독자까지 합쳐 어떤 핸들러가
              실제로 발화될지 보여줍니다.
            </p>
            <pre>{`from core.hooks import HookEvent, HookSystem

hooks = HookSystem()
hooks.register(HookEvent.TOOL_EXEC_FAILED, on_tool_failed, name="tool_failure_observer")
print(hooks.list_hooks(HookEvent.TOOL_EXEC_FAILED))
# {'tool_exec_failed': ['tool_failure_observer']}

results = hooks.trigger(HookEvent.TOOL_EXEC_FAILED, {"tool_name": "web_fetch", "error": "timeout"})
print([r.success for r in results])  # [True]`}</pre>

            <p className="text-[var(--ink-3)] text-sm">
              <em>참조:</em>{" "}
              <a href="/geode/docs/harness/hooks">Hook system</a>,{" "}
              <a href="/geode/docs/architecture/agentic-loop">Agentic loop</a>.
            </p>
          </>
        }
        en={
          <>
            <p>
              A hook attaches a handler to an event the loop fires at a meaningful
              boundary. Use it to add cross-cutting concerns such as
              observability, cost accounting, and audit logging without touching
              loop code. The most
              common trap is writing a handler and never registering it in
              bootstrap. A handler that exists does not fire.
            </p>

            <h2>1. Pick an event</h2>
            <p>
              Every fire point is defined in the <code>HookEvent</code> enum in{" "}
              <code>core/hooks/system.py</code>. To watch tool execution, pick{" "}
              <code>TOOL_EXEC_STARTED</code> / <code>TOOL_EXEC_ENDED</code> /{" "}
              <code>TOOL_EXEC_FAILED</code>; for session boundaries,{" "}
              <code>SESSION_STARTED</code> / <code>SESSION_ENDED</code>; for LLM
              calls, <code>LLM_CALL_STARTED</code> / <code>LLM_CALL_ENDED</code>.
              If you need an event that does not exist, add the enum member and its
              fire site in the same change. Reserving the name without the emit
              site leaves a dead event that never fires.
            </p>

            <h2>2. Write the handler</h2>
            <p>
              The handler signature is{" "}
              <code>(event: HookEvent, data: dict) -&gt; None</code>. A
              fire-and-forget observer returns <code>None</code>; a feedback hook
              that hands a recommendation back to the caller returns a dict. An
              exception inside a handler is caught by{" "}
              <code>HookSystem.trigger</code> and logged as a warning, so it never
              blocks other handlers. Both sync and async handlers are supported.
            </p>
            <pre>{`from core.hooks import HookEvent

def on_tool_failed(event: HookEvent, data: dict) -> None:
    tool_name = data.get("tool_name", "")
    error = data.get("error", "")
    # observe only — no return value needed
    log.warning("tool %s failed: %s", tool_name, error)`}</pre>

            <h2>3. Register it in bootstrap</h2>
            <p>
              This is the step that matters. <code>build_hooks()</code> in{" "}
              <code>core/wiring/bootstrap.py</code> is where the{" "}
              <code>HookSystem</code> is created and every core handler is attached.
              Call <code>hooks.register(event, handler, name=..., priority=...)</code>{" "}
              there. The <code>name</code> must be unique in overlapping exact/prefix
              scopes. A different handler with the same name fails loudly; use
              <code>replace=True</code> only for an intentional replacement.
            </p>
            <pre>{`# core/wiring/bootstrap.py — build_hooks()
hooks.register(
    HookEvent.TOOL_EXEC_FAILED,
    on_tool_failed,
    name="tool_failure_observer",
    priority=60,
)`}</pre>
            <p>
              To attach one handler to an event family, use{" "}
              <code>register_prefix(&quot;SUBAGENT&quot;, handler, ...)</code>. Operational
              persistence is a post-dispatch sink rather than a wildcard handler.
            </p>

            <h2>4. Choose a priority tier</h2>
            <p>
              Lower <code>priority</code> runs first (default 100). Put interceptors
              that enrich data low and plain observers high. Anchor to the existing
              bootstrap tiers: metrics are 45, the agent_runtime_state
              recorders are 55, the session lifecycle loggers are 90. Handlers on the{" "}
              <code>trigger_interceptor()</code> path can return{" "}
              <code>{`{"block": True}`}</code> or{" "}
              <code>{`{"modify": {...}}`}</code> to stop the chain or edit the
              event data.
            </p>

            <h2>Verify</h2>
            <p>
              Confirm it fires by triggering it directly.{" "}
              <code>list_hooks()</code> merges in wildcard subscribers, so it shows
              every handler that would actually fire.
            </p>
            <pre>{`from core.hooks import HookEvent, HookSystem

hooks = HookSystem()
hooks.register(HookEvent.TOOL_EXEC_FAILED, on_tool_failed, name="tool_failure_observer")
print(hooks.list_hooks(HookEvent.TOOL_EXEC_FAILED))
# {'tool_exec_failed': ['tool_failure_observer']}

results = hooks.trigger(HookEvent.TOOL_EXEC_FAILED, {"tool_name": "web_fetch", "error": "timeout"})
print([r.success for r in results])  # [True]`}</pre>

            <p className="text-[var(--ink-3)] text-sm">
              <em>See:</em>{" "}
              <a href="/geode/docs/harness/hooks">Hook system</a>,{" "}
              <a href="/geode/docs/architecture/agentic-loop">Agentic loop</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
