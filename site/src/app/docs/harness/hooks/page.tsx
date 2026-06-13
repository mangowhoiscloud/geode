import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Hooks and observability — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/hooks"
      title="Hooks and observability"
      titleKo="훅과 관측성"
      summary="Lifecycle events that handlers subscribe to. How observe, react, decide, and act stack on one event."
      summaryKo="핸들러가 구독하는 라이프사이클 이벤트입니다. 하나의 이벤트 위에 observe, react, decide, act가 어떻게 쌓이는지 설명합니다."
    >
      <Bi
        ko={
          <>
            <p>
              HookSystem(<code>core/hooks/system.py</code>)은 런타임의 모든 의미
              있는 경계에서 이벤트를 발화하는 단일 버스입니다.{" "}
              <code>HookEvent</code> enum은 정확히 62개의 라이프사이클 이벤트를
              정의합니다. 새 동작은 루프 코드를 고치는 대신 이 이벤트들 위에
              핸들러로 쌓입니다.
            </p>

            <h2>하나의 이벤트, 네 가지 쌓기</h2>
            <p>
              같은 이벤트라도 핸들러가 무엇을 하느냐에 따라 네 층위로
              쌓입니다.
            </p>
            <table>
              <thead>
                <tr><th>층위</th><th>호출 방식</th><th>의미</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Observe</td>
                  <td><code>trigger()</code></td>
                  <td>fire-and-forget 관찰. 핸들러 오류는 로깅 후 격리됩니다</td>
                </tr>
                <tr>
                  <td>React</td>
                  <td><code>trigger()</code> 구독 핸들러</td>
                  <td>이벤트를 계기로 부수 작업을 실행 (알림, 저널, 메트릭)</td>
                </tr>
                <tr>
                  <td>Decide</td>
                  <td><code>trigger_with_result()</code></td>
                  <td>핸들러 반환값을 호출자가 수집해 전략을 결정 (예: <code>CONTEXT_OVERFLOW_ACTION</code>)</td>
                </tr>
                <tr>
                  <td>Act</td>
                  <td><code>trigger_interceptor()</code></td>
                  <td>핸들러가 실행 자체를 차단하거나 수정 (인터셉터 패턴)</td>
                </tr>
              </tbody>
            </table>
            <p>비동기 변형으로 <code>trigger_async</code>가 있습니다.</p>

            <h2>이벤트 카테고리</h2>
            <p>62개 이벤트는 enum 안의 섹션 주석으로 분류됩니다. 대표만 추리면 이렇습니다.</p>
            <table>
              <thead>
                <tr><th>카테고리</th><th>대표 이벤트</th></tr>
              </thead>
              <tbody>
                <tr><td>agentic 턴 / 세션</td><td><code>TURN_COMPLETED</code>, <code>SESSION_STARTED</code>, <code>SESSION_ENDED</code></td></tr>
                <tr><td>LLM 호출</td><td><code>LLM_CALL_STARTED/ENDED/FAILED/RETRIED</code>, <code>ADAPTER_DISPATCH_ATTEMPT</code>, <code>MODEL_SWITCHED</code></td></tr>
                <tr><td>도구 실행 / 승인</td><td><code>TOOL_EXEC_STARTED/ENDED/FAILED</code>, <code>TOOL_RESULT_TRANSFORM</code>, <code>TOOL_APPROVAL_REQUESTED/GRANTED/DENIED</code>, <code>TOOL_RECOVERY_ATTEMPTED/SUCCEEDED/FAILED</code></td></tr>
                <tr><td>컨텍스트 / 오프로드</td><td><code>CONTEXT_CRITICAL</code>, <code>CONTEXT_OVERFLOW_ACTION</code>, <code>TOOL_RESULT_OFFLOADED</code></td></tr>
                <tr><td>프롬프트 / 메모리</td><td><code>PROMPT_ASSEMBLED</code>, <code>PROGRAM_MD_UNREADABLE</code>, <code>MEMORY_SAVED</code>, <code>RULE_CREATED/UPDATED/DELETED</code></td></tr>
                <tr><td>비용 / 인터셉터</td><td><code>USER_INPUT_RECEIVED</code>, <code>COST_WARNING</code>, <code>COST_LIMIT_EXCEEDED</code>, <code>EXECUTION_CANCELLED</code></td></tr>
                <tr><td>서브에이전트 / 핸드오프</td><td><code>SUBAGENT_STARTED/COMPLETED/FAILED</code>, <code>HANDOFF_TRIGGERED/COMPLETED/FAILED</code></td></tr>
                <tr><td>자기개선 루프</td><td><code>MUTATION_PROPOSED/APPLIED/REJECTED/REVERTED</code>, <code>BASELINE_PROMOTED</code>, <code>SELF_IMPROVING_AUTO_TRIGGER_*</code></td></tr>
                <tr><td>인프라</td><td><code>TRIGGER_FIRED</code>, <code>CONFIG_RELOADED</code>, <code>SHUTDOWN_STARTED</code>, <code>MCP_SERVER_CONNECTED/FAILED</code></td></tr>
              </tbody>
            </table>

            <h2>등록</h2>
            <pre>{`from core.hooks.system import HookSystem, HookEvent

hooks.register(
    HookEvent.TURN_COMPLETED,
    my_handler,
    name="my-plugin",
    priority=100,   # 낮을수록 먼저 실행, 안정 정렬
)
hooks.register_prefix("*", mirror_everything)  # 와일드카드 구독`}</pre>

            <h2>부트스트랩 등록이 필수</h2>
            <p>
              핸들러가 존재한다는 사실과 핸들러가 발화한다는 사실은 다릅니다.
              프로덕션 핸들러는 전부{" "}
              <code>core/wiring/bootstrap.py</code>에서 등록됩니다. 거기 없는
              핸들러는 코드로 존재해도 영원히 호출되지 않습니다. 이 규칙은
              저장소의 wiring 검증 인바리언트로 핀 고정되어 있습니다.
            </p>
            <p>
              부트스트랩에는 priority 50의 <code>&quot;*&quot;</code> prefix
              핸들러가 하나 있어, 모든 트리거를 활성 RunTranscript의 activity
              log 행으로 미러링합니다. 훅 버스 자체가 관측 파이프라인의
              입구입니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>핸들러를 만들었는데 한 번도 안 불림</td>
                  <td>부트스트랩 미등록</td>
                  <td><code>core/wiring/bootstrap.py</code>에 등록을 추가합니다</td>
                </tr>
                <tr>
                  <td>핸들러 실행 순서가 뒤섞임</td>
                  <td>priority 미지정 (기본 100)</td>
                  <td>순서가 중요하면 명시적 priority를 부여합니다. 낮은 값이 먼저입니다</td>
                </tr>
                <tr>
                  <td>observe 핸들러의 예외가 보이지 않음</td>
                  <td><code>trigger()</code>는 오류를 격리하고 로깅만 합니다</td>
                  <td>로그를 확인합니다. 흐름을 막아야 하는 로직이면 인터셉터로 옮깁니다</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/guides/register-hook">훅 핸들러 등록 가이드</a>. 손으로 따라가는 절차.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>. 이벤트가 발화되는 본진.</li>
              <li><a href="/geode/docs/harness/lifecycle">하네스 라이프사이클</a>. serve 데몬에서의 이벤트 흐름.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The HookSystem (<code>core/hooks/system.py</code>) is the single
              bus that fires events at every meaningful boundary of the runtime.
              The <code>HookEvent</code> enum defines exactly 62 lifecycle
              events. New behaviour stacks onto these events as handlers instead
              of editing loop code.
            </p>

            <h2>One event, four ways to stack</h2>
            <p>
              The same event supports four levels of involvement, depending on
              what the handler does.
            </p>
            <table>
              <thead>
                <tr><th>Level</th><th>Call form</th><th>Meaning</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Observe</td>
                  <td><code>trigger()</code></td>
                  <td>Fire-and-forget observation; handler errors are logged and isolated</td>
                </tr>
                <tr>
                  <td>React</td>
                  <td>a <code>trigger()</code> subscriber</td>
                  <td>Run side work off the event (notifications, journal, metrics)</td>
                </tr>
                <tr>
                  <td>Decide</td>
                  <td><code>trigger_with_result()</code></td>
                  <td>The caller collects handler return values to pick a strategy (e.g. <code>CONTEXT_OVERFLOW_ACTION</code>)</td>
                </tr>
                <tr>
                  <td>Act</td>
                  <td><code>trigger_interceptor()</code></td>
                  <td>Handlers can block or modify the execution itself (interceptor pattern)</td>
                </tr>
              </tbody>
            </table>
            <p>An async variant, <code>trigger_async</code>, also exists.</p>

            <h2>Event categories</h2>
            <p>The 62 events are grouped by section comments inside the enum. The highlights:</p>
            <table>
              <thead>
                <tr><th>Category</th><th>Representative events</th></tr>
              </thead>
              <tbody>
                <tr><td>Agentic turn / session</td><td><code>TURN_COMPLETED</code>, <code>SESSION_STARTED</code>, <code>SESSION_ENDED</code></td></tr>
                <tr><td>LLM calls</td><td><code>LLM_CALL_STARTED/ENDED/FAILED/RETRIED</code>, <code>ADAPTER_DISPATCH_ATTEMPT</code>, <code>MODEL_SWITCHED</code></td></tr>
                <tr><td>Tool execution / approval</td><td><code>TOOL_EXEC_STARTED/ENDED/FAILED</code>, <code>TOOL_RESULT_TRANSFORM</code>, <code>TOOL_APPROVAL_REQUESTED/GRANTED/DENIED</code>, <code>TOOL_RECOVERY_ATTEMPTED/SUCCEEDED/FAILED</code></td></tr>
                <tr><td>Context / offload</td><td><code>CONTEXT_CRITICAL</code>, <code>CONTEXT_OVERFLOW_ACTION</code>, <code>TOOL_RESULT_OFFLOADED</code></td></tr>
                <tr><td>Prompt / memory</td><td><code>PROMPT_ASSEMBLED</code>, <code>PROGRAM_MD_UNREADABLE</code>, <code>MEMORY_SAVED</code>, <code>RULE_CREATED/UPDATED/DELETED</code></td></tr>
                <tr><td>Cost / interceptors</td><td><code>USER_INPUT_RECEIVED</code>, <code>COST_WARNING</code>, <code>COST_LIMIT_EXCEEDED</code>, <code>EXECUTION_CANCELLED</code></td></tr>
                <tr><td>Sub-agents / handoff</td><td><code>SUBAGENT_STARTED/COMPLETED/FAILED</code>, <code>HANDOFF_TRIGGERED/COMPLETED/FAILED</code></td></tr>
                <tr><td>Self-improving loop</td><td><code>MUTATION_PROPOSED/APPLIED/REJECTED/REVERTED</code>, <code>BASELINE_PROMOTED</code>, <code>SELF_IMPROVING_AUTO_TRIGGER_*</code></td></tr>
                <tr><td>Infrastructure</td><td><code>TRIGGER_FIRED</code>, <code>CONFIG_RELOADED</code>, <code>SHUTDOWN_STARTED</code>, <code>MCP_SERVER_CONNECTED/FAILED</code></td></tr>
              </tbody>
            </table>

            <h2>Registration</h2>
            <pre>{`from core.hooks.system import HookSystem, HookEvent

hooks.register(
    HookEvent.TURN_COMPLETED,
    my_handler,
    name="my-plugin",
    priority=100,   # lower runs first, stable sort
)
hooks.register_prefix("*", mirror_everything)  # wildcard subscription`}</pre>

            <h2>Bootstrap registration is mandatory</h2>
            <p>
              A handler existing and a handler firing are two different facts.
              Every production handler is registered in{" "}
              <code>core/wiring/bootstrap.py</code>. A handler that is not wired
              there exists in code but is never called. This rule is pinned as a
              wiring-verification invariant of the repo.
            </p>
            <p>
              Bootstrap also installs one <code>&quot;*&quot;</code> prefix
              handler at priority 50 that mirrors every trigger into the active
              RunTranscript as an activity-log row. The hook bus itself is the
              entrance of the observability pipeline.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>You wrote a handler and it never fires</td>
                  <td>Not registered in bootstrap</td>
                  <td>Add the registration in <code>core/wiring/bootstrap.py</code></td>
                </tr>
                <tr>
                  <td>Handlers run in a surprising order</td>
                  <td>No explicit priority (default 100)</td>
                  <td>Assign explicit priorities where order matters; lower runs first</td>
                </tr>
                <tr>
                  <td>Exceptions in an observe handler are invisible</td>
                  <td><code>trigger()</code> isolates errors and only logs them</td>
                  <td>Check the logs; move flow-blocking logic to an interceptor</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/guides/register-hook">Register a hook handler</a>. The hands-on walkthrough.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>. Where most events originate.</li>
              <li><a href="/geode/docs/harness/lifecycle">Harness lifecycle</a>. Event flow inside the serve daemon.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
