import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Agentic Loop — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="architecture/agentic-loop"
      title="Agentic Loop"
      summary="GEODE's core execution primitive. while(tool_use) with error recovery, convergence detection, and multi-intent decomposition."
    >
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
          <strong>ErrorRecoveryStrategy</strong> — decides what to do when a
          tool fails (retry, escalate, abort) and surfaces a recovery prompt
          to the model.
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
    </DocsShell>
  );
}
