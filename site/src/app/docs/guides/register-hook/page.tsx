import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Register hooks and middleware — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="guides/register-hook"
      title="Register hooks and middleware"
      titleKo="훅과 미들웨어 등록"
      summary="Choose the narrowest extension surface, register it once, and verify the real production boundary."
      summaryKo="가장 좁은 확장 표면을 골라 한 번만 등록하고 실제 프로덕션 경계를 검증합니다."
    >
      <Bi
        ko={
          <>
            <p>
              먼저 필요한 권한을 고릅니다. 외부 통합의 안정된 경계라면 공개 훅,
              요청 변경이나 실제 실행 래핑이라면 신뢰 미들웨어, 관측만 한다면
              런타임 이벤트를 사용합니다. 내부 이벤트를 실행 제어에 사용하는 것은
              지원 계약이 아닙니다.
            </p>

            <h2>1. 공개 훅 등록</h2>
            <p>
              <code>HookRegistry</code>는 13개의 <code>HookName</code>만
              받습니다. 같은 훅 안에서 이름은 고유해야 하고 낮은 priority가 먼저
              실행됩니다. handler는 <code>HookDecision</code> 또는{" "}
              <code>None</code>을 반환합니다.
            </p>
            <pre>{`from core.hooks import HookAction, HookDecision, HookName

def require_ticket(invocation):
    args = invocation.payload["arguments"]
    if invocation.payload["tool_name"] == "run_bash" and "ticket" not in args:
        return HookDecision(
            action=HookAction.REQUEST_PERMISSION,
            reason="run_bash requires an operator decision",
        )
    return HookDecision(action=HookAction.CONTINUE)

hook_registry.register(
    HookName.PRE_TOOL_USE,
    require_ticket,
    name="require_ticket",
    priority=50,
)`}</pre>
            <p>
              rewrite는 payload의 실제 필드명을 사용합니다. 도구 인자를 바꾸려면{" "}
              <code>{`updates={"arguments": {...}}`}</code>를 반환하며, GEODE가
              변경된 요청을 다시 스키마 검증한 뒤 정책과 승인을 수행합니다.
            </p>

            <h2>2. 신뢰 미들웨어 등록</h2>
            <p>
              요청 변환과 실행 래핑을 섞지 않습니다. 아래 예시는 실제 provider
              호출의 지연만 측정하고 요청은 그대로 전달합니다.
            </p>
            <pre>{`class LlmLatency:
    async def llm_execution(self, request, next_call):
        started = time.monotonic()
        try:
            return await next_call(request)
        finally:
            metrics.observe("llm", time.monotonic() - started)

middleware_registry.register_llm_execution(
    LlmLatency(),
    name="llm_latency",
    priority=100,
)`}</pre>
            <p>
              <code>tool_request</code>, <code>tool_execution</code>,{" "}
              <code>llm_request</code>, <code>llm_execution</code>마다 별도의 등록
              메서드가 있습니다. execution에서 다른 요청을{" "}
              <code>next_call</code>에 넘기거나 두 번 호출하면 fail-loud합니다.
            </p>
            <table>
              <thead><tr><th>결합점</th><th>기본 timeout</th><th>실패 계약</th></tr></thead>
              <tbody>
                <tr><td><code>tool_request</code></td><td>10초</td><td>변환 실패 시 executor에 진입하지 않음</td></tr>
                <tr><td><code>llm_request</code></td><td>10초</td><td>변환 실패 시 provider에 진입하지 않음</td></tr>
                <tr><td><code>tool_execution</code></td><td>300초</td><td><code>next_call</code> 전 실패는 전파; 실행 완료 뒤 wrapper 실패는 완료 결과 보존</td></tr>
                <tr><td><code>llm_execution</code></td><td>900초</td><td><code>next_call</code> 전 실패는 전파; provider 완료 뒤 wrapper 실패는 결과를 보존해 재과금 방지</td></tr>
              </tbody>
            </table>
            <p>
              실행 미들웨어의 실패를 보고 같은 tool/provider 호출을 임의로 재시도하지
              마세요. downstream 호출이 끝난 뒤 발생한 wrapper 오류는 런타임이 완료
              결과를 보존합니다. <code>llm_request</code>가 cache-sensitive prefix를
              바꾸려면 등록 시 <code>allow_cache_invalidation=True</code>와 요청 metadata의
              <code>cache_invalidation_reason</code>이 둘 다 필요합니다.
            </p>

            <h2>3. 내부 런타임 이벤트 구독</h2>
            <p>
              운영 메트릭이나 저장 sink처럼 제어권이 필요 없는 코드는{" "}
              <code>RuntimeEventBus</code>를 구독합니다. prefix 구독은 내부
              관측자용이며 공개 훅에는 없습니다.
            </p>
            <pre>{`from core.hooks import RuntimeEvent

events.subscribe(
    RuntimeEvent.TOOL_EXEC_FAILED,
    record_tool_failure,
    name="tool_failure_metrics",
    priority=60,
)`}</pre>

            <h2>4. 한 번만 소유하고 실제 경계를 검증</h2>
            <p>
              프로덕션에서는 <code>SharedServices</code>가{" "}
              <code>HookRegistry</code>와 <code>MiddlewareRegistry</code>를 각각
              한 번 만들고 <code>ToolExecutor</code>에 주입합니다.{" "}
              <code>AgenticLoop</code>는 executor의 같은 인스턴스를 공유합니다.
              요청마다 새 registry를 만들면 등록이 보이지 않으므로 금지합니다.
            </p>
            <ul>
              <li>public hook은 해당 경계의 payload schema와 action 제한을 테스트합니다.</li>
              <li>tool middleware는 승인 전 변환과 승인 후 실행 순서를 함께 테스트합니다.</li>
              <li>LLM middleware는 모든 adapter call 경로와 retry마다 실행되는지 확인합니다.</li>
              <li>관측 행은 run projection이 없어도 SQLite에 남고, <code>RunTimeline</code> 활성 시에만 <code>events.jsonl</code>에도 남는지 확인합니다.</li>
            </ul>

            <h2>PostVerify 등록 시 주의</h2>
            <p>
              revise와 Stop continue는 빈 지시를 반환할 수 없습니다. 실패한 내장
              검증에 accept를 반환하면 escalation으로 처리됩니다. 연속 시도는
              기본 2회로 제한되며 이전 도구 부수 효과는 재생하지 않습니다.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>참조:</em>{" "}
              <a href="/geode/docs/harness/hooks">훅과 미들웨어 계약</a>,{" "}
              <a href="/geode/docs/architecture/agentic-loop">Agentic loop</a>.
            </p>
          </>
        }
        en={
          <>
            <p>
              Start by choosing the authority you need. Use a public hook for a
              stable external boundary, trusted middleware for request changes
              or real execution wrapping, and a runtime event for observation
              only. Using an internal event as an execution-control API is not a
              supported contract.
            </p>

            <h2>1. Register a public hook</h2>
            <p>
              <code>HookRegistry</code> accepts only the thirteen{" "}
              <code>HookName</code> values. Names are unique within one hook,
              lower priority runs first, and handlers return{" "}
              <code>HookDecision</code> or <code>None</code>.
            </p>
            <pre>{`from core.hooks import HookAction, HookDecision, HookName

def require_ticket(invocation):
    args = invocation.payload["arguments"]
    if invocation.payload["tool_name"] == "run_bash" and "ticket" not in args:
        return HookDecision(
            action=HookAction.REQUEST_PERMISSION,
            reason="run_bash requires an operator decision",
        )
    return HookDecision(action=HookAction.CONTINUE)

hook_registry.register(
    HookName.PRE_TOOL_USE,
    require_ticket,
    name="require_ticket",
    priority=50,
)`}</pre>
            <p>
              A rewrite uses actual payload field names. To replace tool
              arguments, return <code>{`updates={"arguments": {...}}`}</code>.
              GEODE revalidates the effective request before policy and approval.
            </p>

            <h2>2. Register trusted middleware</h2>
            <p>
              Keep request transforms separate from execution wrapping. This
              example measures the real provider call and forwards the unchanged
              request.
            </p>
            <pre>{`class LlmLatency:
    async def llm_execution(self, request, next_call):
        started = time.monotonic()
        try:
            return await next_call(request)
        finally:
            metrics.observe("llm", time.monotonic() - started)

middleware_registry.register_llm_execution(
    LlmLatency(),
    name="llm_latency",
    priority=100,
)`}</pre>
            <p>
              Separate registration methods exist for <code>tool_request</code>,{" "}
              <code>tool_execution</code>, <code>llm_request</code>, and{" "}
              <code>llm_execution</code>. Passing a changed request at execution
              time or calling <code>next_call</code> twice fails loudly.
            </p>
            <table>
              <thead><tr><th>Join point</th><th>Default timeout</th><th>Failure contract</th></tr></thead>
              <tbody>
                <tr><td><code>tool_request</code></td><td>10 seconds</td><td>A transform failure prevents executor entry</td></tr>
                <tr><td><code>llm_request</code></td><td>10 seconds</td><td>A transform failure prevents provider entry</td></tr>
                <tr><td><code>tool_execution</code></td><td>300 seconds</td><td>Failures before <code>next_call</code> propagate; wrapper failures after execution preserve the completed result</td></tr>
                <tr><td><code>llm_execution</code></td><td>900 seconds</td><td>Failures before <code>next_call</code> propagate; wrapper failures after provider completion preserve the result to prevent rebilling</td></tr>
              </tbody>
            </table>
            <p>
              Do not blindly retry a tool or provider call after an execution
              middleware error. The runtime preserves a completed downstream result
              when the wrapper fails afterward. Changing a cache-sensitive prefix in
              <code>llm_request</code> requires both
              <code>allow_cache_invalidation=True</code> at registration and a
              <code>cache_invalidation_reason</code> in request metadata.
            </p>

            <h2>3. Subscribe to an internal runtime event</h2>
            <p>
              Operational metrics and persistence sinks that need no control
              authority subscribe to <code>RuntimeEventBus</code>. Prefix
              subscriptions are internal-observer functionality and do not exist
              on the public hook surface.
            </p>
            <pre>{`from core.hooks import RuntimeEvent

events.subscribe(
    RuntimeEvent.TOOL_EXEC_FAILED,
    record_tool_failure,
    name="tool_failure_metrics",
    priority=60,
)`}</pre>

            <h2>4. Own each registry once and test the real boundary</h2>
            <p>
              In production, <code>SharedServices</code> creates one{" "}
              <code>HookRegistry</code> and one <code>MiddlewareRegistry</code>,
              injects them into <code>ToolExecutor</code>, and{" "}
              <code>AgenticLoop</code> shares those exact instances from the
              executor. Per-request registries hide registrations and are not
              supported.
            </p>
            <ul>
              <li>Test the hook-specific payload schema and action allowlist.</li>
              <li>Test tool transforms before approval and execution wrappers after it.</li>
              <li>Verify LLM middleware covers every adapter path and each retry attempt.</li>
              <li>Verify SQLite persistence without a run projection and conditional <code>events.jsonl</code> mirroring with <code>RunTimeline</code>.</li>
            </ul>

            <h2>PostVerify cautions</h2>
            <p>
              Revision and Stop continuation decisions require a non-empty
              instruction. Accepting a failed built-in verification is treated
              as escalation. Continuations are bounded to two attempts and do
              not replay prior tool side effects.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>See:</em>{" "}
              <a href="/geode/docs/harness/hooks">Hook and middleware contracts</a>,{" "}
              <a href="/geode/docs/architecture/agentic-loop">Agentic loop</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
