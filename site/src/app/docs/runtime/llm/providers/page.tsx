import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Providers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/providers"
      title="Providers"
      summary="Three fallback chains, four adapters, nine models. Provider-agnostic LLM router with explicit chain ordering."
    >
      <h2>The four adapters</h2>
      <table>
        <thead><tr><th>File</th><th>Provider</th><th>Models in chain</th></tr></thead>
        <tbody>
          <tr><td><code>core/llm/providers/anthropic.py</code></td><td>Anthropic</td><td>Opus 4.7 → Opus 4.6 → Sonnet 4.6 → Haiku 4.5</td></tr>
          <tr><td><code>core/llm/providers/openai.py</code></td><td>OpenAI Responses</td><td>gpt-5.5 → gpt-5.4 → gpt-5.4-mini → gpt-5-mini</td></tr>
          <tr><td><code>core/llm/providers/codex.py</code></td><td>Codex Plus (subscription)</td><td>OpenAI models via Codex routing</td></tr>
          <tr><td><code>core/llm/providers/glm.py</code></td><td>Zhipu GLM</td><td>GLM-4.5+ (with <code>thinking</code> field)</td></tr>
        </tbody>
      </table>

      <h2>Fallback chains</h2>
      <p>
        Defined in <code>core/config.py</code>:
      </p>
      <pre>{`ANTHROPIC_FALLBACK_CHAIN = ["claude-opus-4-7", "claude-opus-4-6",
                            "claude-sonnet-4-6", "claude-haiku-4-5"]
OPENAI_FALLBACK_CHAIN    = ["gpt-5.5", "gpt-5.4",
                            "gpt-5.4-mini", "gpt-5-mini"]
GLM_FALLBACK_CHAIN       = ["glm-4.6-plus", "glm-4.5-plus"]`}</pre>
      <p>
        Each adapter&apos;s <code>retry_with_backoff()</code> walks the chain
        on retryable errors (rate limit, server error). Non-retryable errors
        (auth failure, billing) propagate immediately as{" "}
        <code>BillingError</code> or <code>AuthError</code>.
      </p>

      <h2>Adaptive thinking depth</h2>
      <p>
        The <code>effort</code> parameter (5 levels:{" "}
        <code>low</code>, <code>medium</code>, <code>high</code>,{" "}
        <code>max</code>, <code>xhigh</code>) is provider-specific but exposed
        uniformly:
      </p>
      <ul>
        <li><strong>Anthropic</strong> — <code>output_config.effort=&quot;xhigh&quot;</code> for Opus 4.7 (Opus 4.6 / Sonnet 4.6 reject xhigh, downgrade to <code>max</code>)</li>
        <li><strong>OpenAI Responses</strong> — <code>reasoning.effort</code> field on gpt-5.x</li>
        <li><strong>Codex</strong> — <code>codex_reasoning_items</code> sidecar (encrypted reasoning replay across turns)</li>
        <li><strong>GLM</strong> — <code>extra_body={"{thinking: {type: enabled, clear_thinking: false}}"}</code></li>
      </ul>

      <h2>Caching</h2>
      <ul>
        <li><strong>Anthropic</strong> — `cache_control: ephemeral` on system block (STATIC/DYNAMIC split via <code>__GEODE_PROMPT_CACHE_BOUNDARY__</code>) plus <code>apply_messages_cache_control()</code> on the last 3 non-system messages (PR #864). See <a href="/geode/docs/runtime/llm/prompt-caching">Prompt Caching</a>.</li>
        <li><strong>OpenAI</strong> — server-side automatic prompt caching (no GEODE wiring required).</li>
        <li><strong>GLM / Codex</strong> — provider-managed.</li>
      </ul>

      <h2>Circuit breakers</h2>
      <p>
        Each adapter owns a module-level <code>CircuitBreaker</code> instance
        (<code>core/llm/fallback.py</code>). After repeated failures the
        breaker opens and the chain rotates, giving the next provider a
        chance instead of hammering the failing one. <code>record_success()</code>{" "}
        on a successful call resets the breaker.
      </p>

      <h2>OAuth (Anthropic disabled, OpenAI Codex active)</h2>
      <p>
        Per Anthropic ToS, OAuth login on Anthropic is disabled — use API
        keys only. OpenAI Codex Plus subscription auth is available; see{" "}
        <em>Operations · OAuth</em> when filled.
      </p>

    </DocsShell>
  );
}
