import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Agentic Loop — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="architecture/agentic-loop"
      title="Agentic Loop"
      titleKo="Agentic 루프"
      summary="GEODE's core execution primitive. while(tool_use) with error recovery, convergence detection, and multi-intent decomposition."
      summaryKo="GEODE 실행의 기본 단위. 오류 복구, 수렴 감지, 멀티 인텐트 분해를 갖춘 while(tool_use)."
    >
      <Bi
        ko={
          <>
            <h2>기본 단위</h2>
            <p>
              <code>core/agent/loop.py:162 class AgenticLoop</code>에 정의된
              AgenticLoop는 매 턴을 구동하는 엔진입니다. 의도적으로 단순하게
              유지되어 있습니다.
            </p>
            <pre>{`response = call_llm(messages, tools)
while response.has_tool_use:
    for tool_call in response.tool_calls:
        result = execute(tool_call)
        messages.append(result)
    response = call_llm(messages, tools)
return response.text`}</pre>
            <p>
              복잡성은 다른 곳에 있습니다. 프롬프트 어셈블러, 도구 레지스트리,
              검증 가드레일, 훅 시스템이 그것입니다. 루프 자체는 얇게 유지됩니다.
            </p>

            <h2>세 가지 컨트롤러</h2>
            <p>루프는 세 가지 책임을 전용 클래스에 위임합니다.</p>
            <ul>
              <li>
                <strong>ToolCallProcessor</strong>. 도구 호출 순서를 정하고, 중복을
                제거하며, 도구별 pre/post 훅을 적용합니다.
              </li>
              <li>
                <strong>ErrorRecoveryStrategy</strong>. 도구가 실패했을 때 재시도
                또는 명시적 종료 신호 (<code>model_action_required</code>,{" "}
                <code>user_clarification_needed</code>) 로 분기합니다. v0.90.0에서
                auto-escalation이 제거되었습니다. 모델이 직접 종료 신호를 emit해야
                루프가 빠져나갑니다.
              </li>
              <li>
                <strong>ConvergenceDetector</strong>. 진전 없이 동일 도구를 동일
                인자로 N번 반복하는 루프를 감지하여 중단시킵니다.
              </li>
            </ul>

            <h2>멀티 인텐트 분해</h2>
            <p>
              루프는 "X를 분석하고 Y와 비교해줘"같은 복합 사용자 요청을 받습니다.
              디컴포저(<code>decomposer.md</code>)는 첫 라운드 전에 요청을 도구
              호출 시퀀스로 분해합니다.
            </p>

            <h2>시스템 프롬프트 구성</h2>
            <p>
              루프 시작 전에 <code>core/agent/system_prompt.py</code>의{" "}
              <code>build_system_prompt()</code>가 STATIC/DYNAMIC 경계
              마커(<code>__GEODE_PROMPT_CACHE_BOUNDARY__</code>)와 함께 시스템
              프롬프트를 조립합니다. Anthropic 어댑터는 이 마커를 기준으로 프롬프트
              캐싱을 위해 분할합니다. <a href="/geode/docs/runtime/llm/prompt-caching">프롬프트 캐싱</a>을
              참고하세요.
            </p>

            <h2>훅 통합</h2>
            <p>루프는 의미 있는 경계마다 라이프사이클 이벤트를 발화합니다.</p>
            <ul>
              <li><code>SESSION_START</code>, <code>SESSION_END</code></li>
              <li><code>TURN_COMPLETE</code></li>
              <li><code>LLM_CALL_START</code>, <code>LLM_CALL_END</code>, <code>LLM_CALL_FAILED</code>, <code>LLM_CALL_RETRY</code></li>
              <li><code>TOOL_EXEC_START</code>, <code>TOOL_EXEC_END</code>, <code>TOOL_EXEC_FAILED</code></li>
              <li><code>TOOL_APPROVAL_REQUEST</code>, <code>TOOL_APPROVAL_GRANTED</code>, <code>TOOL_APPROVAL_DENIED</code></li>
              <li><code>CONTEXT_OVERFLOW</code>, <code>CONTEXT_RESET</code></li>
            </ul>

            <h2>왜 얇은 루프인가</h2>
            <p>
              루프의 얇음은 의도적입니다. 시스템에서 가장 많이 테스트되고 가장 적게
              바뀌는 코드입니다. 새로운 동작은 루프 안이 아니라 도구, 훅, 가드레일로
              들어갑니다. 이렇게 해야 핵심 실행 경로가 예측 가능하고 테스트 가능한
              상태로 유지됩니다.
            </p>
          </>
        }
        en={
          <>
            <h2>The primitive</h2>
            <p>
              AgenticLoop, defined at{" "}
              <code>core/agent/loop.py:162 class AgenticLoop</code>, is the engine
              that runs every turn. It is intentionally simple:
            </p>
            <pre>{`response = call_llm(messages, tools)
while response.has_tool_use:
    for tool_call in response.tool_calls:
        result = execute(tool_call)
        messages.append(result)
    response = call_llm(messages, tools)
return response.text`}</pre>
            <p>
              The complexity lives elsewhere — in the prompt assembler, the tool
              registry, the verification guardrails, and the hook system. The loop
              itself stays thin.
            </p>

            <h2>Three controllers</h2>
            <p>The loop delegates three responsibilities to dedicated classes:</p>
            <ul>
              <li>
                <strong>ToolCallProcessor</strong> — orders tool calls, deduplicates,
                and applies tool-specific pre/post hooks.
              </li>
              <li>
                <strong>ErrorRecoveryStrategy</strong> — on tool failure, either
                retries or yields one of two explicit termination signals
                (<code>model_action_required</code>, <code>user_clarification_needed</code>).
                Auto-escalation was removed in v0.90.0; the loop now exits only
                when the model itself emits a termination signal.
              </li>
              <li>
                <strong>ConvergenceDetector</strong> — watches for loops that are
                spinning without progress (same tool with same args N times) and
                interrupts.
              </li>
            </ul>

            <h2>Multi-intent decomposition</h2>
            <p>
              The loop accepts compound user requests like &ldquo;analyze X and
              compare with Y&rdquo;. The decomposer (<code>decomposer.md</code>)
              breaks the request into a sequence of tool calls before the first
              round.
            </p>

            <h2>System prompt construction</h2>
            <p>
              Before the loop starts, <code>build_system_prompt()</code> in{" "}
              <code>core/agent/system_prompt.py</code> assembles the system prompt
              with a STATIC/DYNAMIC boundary marker (<code>__GEODE_PROMPT_CACHE_BOUNDARY__</code>).
              The Anthropic adapter splits at this marker for prompt caching. See{" "}
              <a href="/geode/docs/runtime/llm/prompt-caching">Prompt Caching</a>.
            </p>

            <h2>Hook integration</h2>
            <p>
              The loop fires lifecycle events at every meaningful boundary:
            </p>
            <ul>
              <li><code>SESSION_START</code>, <code>SESSION_END</code></li>
              <li><code>TURN_COMPLETE</code></li>
              <li><code>LLM_CALL_START</code>, <code>LLM_CALL_END</code>, <code>LLM_CALL_FAILED</code>, <code>LLM_CALL_RETRY</code></li>
              <li><code>TOOL_EXEC_START</code>, <code>TOOL_EXEC_END</code>, <code>TOOL_EXEC_FAILED</code></li>
              <li><code>TOOL_APPROVAL_REQUEST</code>, <code>TOOL_APPROVAL_GRANTED</code>, <code>TOOL_APPROVAL_DENIED</code></li>
              <li><code>CONTEXT_OVERFLOW</code>, <code>CONTEXT_RESET</code></li>
            </ul>

            <h2>Why a thin loop</h2>
            <p>
              The loop&apos;s thinness is deliberate. It is the most-tested,
              least-changed code in the system. New behaviour does not go inside
              the loop — it goes into a tool, a hook, or a guardrail. This keeps
              the core execution path predictable and testable.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
