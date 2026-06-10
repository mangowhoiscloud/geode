import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "The inner agentic loop — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="architecture/agentic-loop"
      title="The inner agentic loop"
      titleKo="안쪽 agentic 루프"
      summary="The while(tool_use) primitive. How a turn runs, and the paths that end it."
      summaryKo="while(tool_use) 기본 단위입니다. 한 턴이 어떻게 돌고, 어떤 경로로 끝나는지 설명합니다."
    >
      <Bi
        ko={
          <>
            <h2>기본 단위</h2>
            <p>
              <code>AgenticLoop</code>는 <code>core/agent/loop/agent_loop.py</code>에
              있습니다. 모든 작업 실행의 엔진이고, 형태는 의도적으로 단순합니다.
              모델이 도구를 요청하는 동안 계속 돕니다.
            </p>
            <pre>{`while stop_reason == "tool_use":
    round-entry guards          # round / time / session / cost budget
    context-overflow check      # compact or prune if needed
    response = call_llm(messages, tools)
    run tool calls -> append assistant msg + tool_results`}</pre>
            <p>
              루프 클래스 본체 옆에 책임별 모듈이 같은 패키지에 나뉘어 있습니다.
              시스템 프롬프트와 컨텍스트 위임은 <code>_context.py</code>, 결과
              모델과 컨텍스트 고갈 처리는 <code>models.py</code>, 모델 전환은{" "}
              <code>_model_switching.py</code>, 서브에이전트 알림은{" "}
              <code>_sub_agent_announce.py</code>입니다. 예전 단일 파일{" "}
              <code>core/agent/loop.py</code>는 더 이상 존재하지 않습니다.
            </p>

            <h2>턴 사이클</h2>
            <p>매 라운드는 같은 순서를 밟습니다.</p>
            <ol>
              <li>라운드 진입 가드. 라운드 수, 시간 예산, 세션 예산, 비용 예산을 확인합니다.</li>
              <li>컨텍스트 오버플로 점검. 임계값을 넘으면 압축하거나 정리합니다. 자세한 동작은 <a href="/geode/docs/runtime/context">컨텍스트 조립</a>을 참고합니다.</li>
              <li>LLM 호출.</li>
              <li>모델이 요청한 도구 실행.</li>
              <li>assistant 메시지와 tool_result를 히스토리에 붙이고 다음 라운드로 진입합니다.</li>
            </ol>

            <h2>라운드 진입 가드</h2>
            <table>
              <thead>
                <tr><th>가드</th><th>조건</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>라운드 한도</td>
                  <td><code>max_rounds &gt; 0</code> (0은 무제한)</td>
                  <td><code>max_rounds</code>로 종료</td>
                </tr>
                <tr>
                  <td>시간 예산</td>
                  <td><code>time_budget_s &gt; 0</code>, wall-clock 기준</td>
                  <td><code>time_budget_expired</code>로 종료</td>
                </tr>
                <tr>
                  <td>세션 예산</td>
                  <td>기본 세션 상한 2시간 (<code>core/agent/budget.py</code>)</td>
                  <td>임계 직전 <code>HANDOFF_TRIGGERED</code> 훅 1회, 만료 시 하드 스톱</td>
                </tr>
                <tr>
                  <td>비용 예산</td>
                  <td><code>cost_budget &gt; 0</code></td>
                  <td>80%에서 1회 경고, 도달 시 <code>cost_budget_exceeded</code></td>
                </tr>
                <tr>
                  <td>overthinking 감지</td>
                  <td>도구 없이 고출력 텍스트 라운드가 연속될 때. 임계값은 컨텍스트 윈도 비례(윈도의 1%, 최소 1024 토큰)</td>
                  <td><code>user_clarification_needed</code>로 멈추고 사용자에게 묻습니다</td>
                </tr>
              </tbody>
            </table>

            <h2>종료 경로</h2>
            <p>
              모든 실행은 <code>AgenticResult.termination_reason</code> 하나로
              끝납니다. SoT는 <code>core/agent/loop/models.py</code>입니다.
            </p>
            <table>
              <thead>
                <tr><th>termination_reason</th><th>의미</th></tr>
              </thead>
              <tbody>
                <tr><td><code>natural</code></td><td>모델이 도구 호출 없이 답을 마침</td></tr>
                <tr><td><code>forced_text</code></td><td>마무리 단계에서 텍스트 응답을 강제함 (adaptive compute: max_tokens 축소, thinking off)</td></tr>
                <tr><td><code>max_rounds</code></td><td>라운드 한도 도달</td></tr>
                <tr><td><code>time_budget_expired</code></td><td>wall-clock 예산 소진</td></tr>
                <tr><td><code>cost_budget_exceeded</code></td><td>세션 비용이 예산에 도달</td></tr>
                <tr><td><code>context_exhausted</code></td><td>압축과 정리 후에도 컨텍스트가 임계 상태</td></tr>
                <tr><td><code>llm_error</code></td><td>복구 불가능한 LLM 호출 실패</td></tr>
                <tr><td><code>model_action_required</code></td><td>모델이 외부 조치를 요구하며 종료 신호를 보냄</td></tr>
                <tr><td><code>user_clarification_needed</code></td><td>모델이 확인을 요청하거나 overthinking 감지가 멈춤</td></tr>
                <tr><td><code>model_refusal</code></td><td>모델이 안전 거절로 응답 (아래 절)</td></tr>
                <tr><td><code>input_blocked</code></td><td>입력이 인터셉터에서 차단됨</td></tr>
                <tr><td><code>billing_error</code></td><td>결제/쿼터 치명 오류</td></tr>
                <tr><td><code>user_cancelled</code></td><td>사용자 취소</td></tr>
                <tr><td><code>convergence_detected</code></td><td>진전 없는 반복 감지</td></tr>
              </tbody>
            </table>
            <p>기본값은 <code>unknown</code>이며, 정상 경로에서는 나타나지 않습니다.</p>

            <h2>model_refusal: 거절을 1급 종료로</h2>
            <p>
              Fable 5의 안전 분류기는 요청을 거절할 때 HTTP 오류가 아니라{" "}
              <strong>HTTP 200</strong>에 <code>stop_reason: &quot;refusal&quot;</code>을
              실어 보냅니다. 본문이 비어 있는 경우도 많습니다. 이를 일반 응답처럼
              다루면 빈 답이 조용히 사용자에게 흘러갑니다.
            </p>
            <p>
              GEODE는 두 지점에서 처리합니다. Anthropic 프로바이더의{" "}
              <code>normalize_anthropic</code>이 응답의 <code>stop_details</code>를
              보존하고, 루프가 이를{" "}
              <code>termination_reason=&quot;model_refusal&quot;</code>로 매핑하며{" "}
              <code>stop_details.category</code>를 포함한 정직한 메시지를
              만듭니다. 같은 경로가 Opus 4.7과 4.8에도 적용됩니다.
            </p>

            <h2>발화되는 훅</h2>
            <p>
              루프는 의미 있는 경계마다 라이프사이클 이벤트를 발화합니다.
              라운드 종료의 <code>TURN_COMPLETED</code>, LLM 호출의{" "}
              <code>LLM_CALL_STARTED</code> / <code>LLM_CALL_ENDED</code> /{" "}
              <code>LLM_CALL_FAILED</code> / <code>LLM_CALL_RETRIED</code>, 도구
              실행의 <code>TOOL_EXEC_STARTED</code> / <code>TOOL_EXEC_ENDED</code> /{" "}
              <code>TOOL_EXEC_FAILED</code>, 승인 게이트의{" "}
              <code>TOOL_APPROVAL_REQUESTED</code> / <code>GRANTED</code> /{" "}
              <code>DENIED</code>, 컨텍스트의 <code>CONTEXT_CRITICAL</code>과{" "}
              <code>CONTEXT_OVERFLOW_ACTION</code>이 대표입니다. 전체 목록과 등록
              방법은 <a href="/geode/docs/harness/hooks">훅과 관측성</a>을
              참고합니다.
            </p>

            <h2>왜 얇은 루프인가</h2>
            <p>
              루프는 의도적으로 얇습니다. 시스템에서 가장 많이 테스트되고 가장
              적게 바뀌는 코드입니다. 새로운 동작은 루프 안이 아니라 도구, 훅,
              가드로 들어갑니다. 그래야 핵심 실행 경로가 예측 가능하고 테스트
              가능한 상태로 유지됩니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/context">컨텍스트 조립</a>. 오버플로 처리와 토큰 예산의 자세한 동작.</li>
              <li><a href="/geode/docs/runtime/orchestration">서브에이전트 오케스트레이션</a>. 루프가 작업을 위임하는 길.</li>
              <li><a href="/geode/docs/concepts/two-loops">두 개의 루프</a>. 이 루프가 큰 그림에서 차지하는 자리.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>The primitive</h2>
            <p>
              <code>AgenticLoop</code> lives in{" "}
              <code>core/agent/loop/agent_loop.py</code>. It is the engine behind
              every task run, and the shape is deliberately simple: keep going
              while the model asks for tools.
            </p>
            <pre>{`while stop_reason == "tool_use":
    round-entry guards          # round / time / session / cost budget
    context-overflow check      # compact or prune if needed
    response = call_llm(messages, tools)
    run tool calls -> append assistant msg + tool_results`}</pre>
            <p>
              Responsibilities are split into sibling modules in the same package:
              system-prompt and context delegation in <code>_context.py</code>,
              the result model and context-exhaustion handling in{" "}
              <code>models.py</code>, model switching in{" "}
              <code>_model_switching.py</code>, sub-agent announcements in{" "}
              <code>_sub_agent_announce.py</code>. The old monolithic{" "}
              <code>core/agent/loop.py</code> no longer exists.
            </p>

            <h2>The turn cycle</h2>
            <p>Every round follows the same order:</p>
            <ol>
              <li>Round-entry guards: round count, time budget, session budget, cost budget.</li>
              <li>Context-overflow check: compact or prune when thresholds are crossed. Details in <a href="/geode/docs/runtime/context">Context assembly</a>.</li>
              <li>Call the LLM.</li>
              <li>Execute the tools the model requested.</li>
              <li>Append the assistant message and tool_results to history, enter the next round.</li>
            </ol>

            <h2>Round-entry guards</h2>
            <table>
              <thead>
                <tr><th>Guard</th><th>Condition</th><th>Behaviour</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Round limit</td>
                  <td><code>max_rounds &gt; 0</code> (0 means unlimited)</td>
                  <td>Terminates with <code>max_rounds</code></td>
                </tr>
                <tr>
                  <td>Time budget</td>
                  <td><code>time_budget_s &gt; 0</code>, wall-clock</td>
                  <td>Terminates with <code>time_budget_expired</code></td>
                </tr>
                <tr>
                  <td>Session budget</td>
                  <td>Default session cap of two hours (<code>core/agent/budget.py</code>)</td>
                  <td>Fires <code>HANDOFF_TRIGGERED</code> once near the threshold, hard stop on expiry</td>
                </tr>
                <tr>
                  <td>Cost budget</td>
                  <td><code>cost_budget &gt; 0</code></td>
                  <td>Warns once at 80%, terminates with <code>cost_budget_exceeded</code> when reached</td>
                </tr>
                <tr>
                  <td>Overthinking detection</td>
                  <td>Consecutive high-output text-only rounds; the threshold is proportional to the context window (1% of the window, floor 1024 tokens)</td>
                  <td>Stops and asks the user via <code>user_clarification_needed</code></td>
                </tr>
              </tbody>
            </table>

            <h2>Termination paths</h2>
            <p>
              Every run ends with exactly one{" "}
              <code>AgenticResult.termination_reason</code>. The source of truth
              is <code>core/agent/loop/models.py</code>.
            </p>
            <table>
              <thead>
                <tr><th>termination_reason</th><th>Meaning</th></tr>
              </thead>
              <tbody>
                <tr><td><code>natural</code></td><td>The model finished its answer with no further tool calls</td></tr>
                <tr><td><code>forced_text</code></td><td>Wrap-up forced a text response (adaptive compute: clamped max_tokens, thinking off)</td></tr>
                <tr><td><code>max_rounds</code></td><td>Round limit reached</td></tr>
                <tr><td><code>time_budget_expired</code></td><td>Wall-clock budget spent</td></tr>
                <tr><td><code>cost_budget_exceeded</code></td><td>Session cost reached the budget</td></tr>
                <tr><td><code>context_exhausted</code></td><td>Context still critical after compaction and pruning</td></tr>
                <tr><td><code>llm_error</code></td><td>Unrecoverable LLM call failure</td></tr>
                <tr><td><code>model_action_required</code></td><td>The model signalled that external action is required</td></tr>
                <tr><td><code>user_clarification_needed</code></td><td>The model asked for confirmation, or overthinking detection stopped the run</td></tr>
                <tr><td><code>model_refusal</code></td><td>The model declined on safety grounds (next section)</td></tr>
                <tr><td><code>input_blocked</code></td><td>Input was blocked by an interceptor</td></tr>
                <tr><td><code>billing_error</code></td><td>Fatal billing or quota error</td></tr>
                <tr><td><code>user_cancelled</code></td><td>Cancelled by the user</td></tr>
                <tr><td><code>convergence_detected</code></td><td>Repetition without progress detected</td></tr>
              </tbody>
            </table>
            <p>The default is <code>unknown</code>; it never appears on a healthy path.</p>

            <h2>model_refusal: refusals as a first-class ending</h2>
            <p>
              Fable 5&apos;s safety classifiers decline a request not with an HTTP
              error but with <strong>HTTP 200</strong> carrying{" "}
              <code>stop_reason: &quot;refusal&quot;</code>, often with empty
              content. Treat that like a normal response and an empty answer
              silently reaches the user.
            </p>
            <p>
              GEODE handles it at two points: <code>normalize_anthropic</code> in
              the Anthropic provider preserves the response&apos;s{" "}
              <code>stop_details</code>, and the loop maps it to{" "}
              <code>termination_reason=&quot;model_refusal&quot;</code> with an
              honest message that includes <code>stop_details.category</code>.
              The same path also covers Opus 4.7 and 4.8.
            </p>

            <h2>Hooks fired</h2>
            <p>
              The loop fires lifecycle events at every meaningful boundary:{" "}
              <code>TURN_COMPLETED</code> at round end,{" "}
              <code>LLM_CALL_STARTED</code> / <code>LLM_CALL_ENDED</code> /{" "}
              <code>LLM_CALL_FAILED</code> / <code>LLM_CALL_RETRIED</code> around
              LLM calls, <code>TOOL_EXEC_STARTED</code> /{" "}
              <code>TOOL_EXEC_ENDED</code> / <code>TOOL_EXEC_FAILED</code> around
              tool execution, <code>TOOL_APPROVAL_REQUESTED</code> /{" "}
              <code>GRANTED</code> / <code>DENIED</code> at the approval gate, and{" "}
              <code>CONTEXT_CRITICAL</code> plus{" "}
              <code>CONTEXT_OVERFLOW_ACTION</code> for context pressure. The full
              list and registration are in{" "}
              <a href="/geode/docs/harness/hooks">Hooks and observability</a>.
            </p>

            <h2>Why a thin loop</h2>
            <p>
              The loop&apos;s thinness is deliberate. It is the most-tested,
              least-changed code in the system. New behaviour does not go inside
              the loop; it goes into a tool, a hook, or a guard. That keeps the
              core execution path predictable and testable.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/context">Context assembly</a>. Overflow handling and token budgets in detail.</li>
              <li><a href="/geode/docs/runtime/orchestration">Sub-agent orchestration</a>. How the loop delegates work.</li>
              <li><a href="/geode/docs/concepts/two-loops">The two loops</a>. Where this loop sits in the bigger picture.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
