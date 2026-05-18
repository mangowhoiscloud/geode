import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Providers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/providers"
      title="Providers"
      titleKo="프로바이더"
      summary="Three fallback chains, four adapters, 14 models. Provider-agnostic LLM router with explicit chain ordering. Five v0.94+ guards: HTML data-URL, tool_choice normalization, prompt_cache_key, GLM thinking gate, agentic_call streaming."
      summaryKo="3개의 폴백 체인, 4개의 어댑터, 14개의 모델. 명시적 체인 순서를 갖는 프로바이더 독립 LLM router. v0.94+ 가드 5종 추가: HTML data-URL, tool_choice 정규화, prompt_cache_key, GLM thinking 게이트, agentic_call 스트리밍."
    >
      <Bi
        ko={
          <>
            <h2>네 개의 어댑터</h2>
            <table>
              <thead><tr><th>파일</th><th>프로바이더</th><th>체인 내 모델</th></tr></thead>
              <tbody>
                <tr><td><code>core/llm/providers/anthropic.py</code></td><td>Anthropic</td><td>Opus 4.7 → Opus 4.6 → Sonnet 4.6 → Haiku 4.5</td></tr>
                <tr><td><code>core/llm/providers/openai.py</code></td><td>OpenAI Responses</td><td>gpt-5.5 → gpt-5.4 → gpt-5.4-mini → gpt-5-mini</td></tr>
                <tr><td><code>core/llm/providers/codex.py</code></td><td>Codex Plus (구독)</td><td>Codex 라우팅을 통한 OpenAI 모델</td></tr>
                <tr><td><code>core/llm/providers/glm.py</code></td><td>Zhipu GLM</td><td>GLM-5.1 → GLM-5 → GLM-5-turbo → GLM-4.7 → GLM-4.7-flash. context 202_752 토큰.</td></tr>
              </tbody>
            </table>

            <h2>폴백 체인</h2>
            <p>
              <code>core/config.py</code>에 정의되어 있습니다.
            </p>
            <pre>{`ANTHROPIC_FALLBACK_CHAIN = ["claude-opus-4-7", "claude-opus-4-6",
                            "claude-sonnet-4-6", "claude-haiku-4-5"]
OPENAI_FALLBACK_CHAIN    = ["gpt-5.5", "gpt-5.4",
                            "gpt-5.4-mini", "gpt-5-mini"]
GLM_FALLBACK_CHAIN       = ["glm-5.1", "glm-5", "glm-5-turbo",
                            "glm-4.7", "glm-4.7-flash"]`}</pre>
            <p>
              각 어댑터의 <code>retry_with_backoff()</code>는 재시도 가능한 오류 (rate
              limit, 서버 오류) 에 대해 체인을 따라 내려갑니다. 재시도 불가능한 오류
              (인증 실패, 결제) 는 <code>BillingError</code> 또는{" "}
              <code>AuthError</code>로 즉시 전파됩니다.
            </p>

            <h2>적응형 사고 깊이</h2>
            <p>
              <code>effort</code> 파라미터 (5단계.{" "}
              <code>low</code>, <code>medium</code>, <code>high</code>,{" "}
              <code>max</code>, <code>xhigh</code>) 는 프로바이더별로 다르지만
              균일하게 노출됩니다.
            </p>
            <ul>
              <li><strong>Anthropic</strong>. Opus 4.7에 대해 <code>output_config.effort=&quot;xhigh&quot;</code> (Opus 4.6 / Sonnet 4.6은 xhigh를 거부하고 <code>max</code>로 다운그레이드)</li>
              <li><strong>OpenAI Responses</strong>. gpt-5.x의 <code>reasoning.effort</code> 필드</li>
              <li><strong>Codex</strong>. <code>codex_reasoning_items</code> 사이드카 (턴 간 암호화된 reasoning 재생)</li>
              <li><strong>GLM</strong>. <code>extra_body={"{thinking: {type: enabled, clear_thinking: false}}"}</code></li>
            </ul>

            <h2>캐싱</h2>
            <ul>
              <li><strong>Anthropic</strong>. system 블록에 `cache_control: ephemeral` (<code>__GEODE_PROMPT_CACHE_BOUNDARY__</code>를 통한 STATIC/DYNAMIC 분할) 과 최근 3개 non-system 메시지에 대한 <code>apply_messages_cache_control()</code> (PR #864). <a href="/geode/docs/runtime/llm/prompt-caching">Prompt Caching</a> 참조.</li>
              <li><strong>OpenAI</strong>. 서버 측 자동 prompt 캐싱 (GEODE wiring 불필요).</li>
              <li><strong>GLM / Codex</strong>. 프로바이더 관리.</li>
            </ul>

            <h2>회로 차단기</h2>
            <p>
              각 어댑터는 모듈 수준의 <code>CircuitBreaker</code> 인스턴스를 보유합니다
              (<code>core/llm/fallback.py</code>). 반복적인 실패가 발생하면 차단기가
              열리고 체인이 회전합니다. 실패하는 프로바이더를 두드리는 대신 다음
              프로바이더에게 기회가 가는 셈입니다. 성공한 호출에서{" "}
              <code>record_success()</code>가 차단기를 재설정합니다.
            </p>

            <h2>v0.94+ 추가된 가드</h2>
            <ul>
              <li><strong>OpenAI HTML data-URL 가드</strong> (v0.94). OpenAI/Codex가 HTML을 <code>data:text/html;base64,...</code> 단일 URL로 emit하는 패턴 차단. <code>core/llm/postprocess/html_output.py</code>로 raw <code>&lt;!DOCTYPE html&gt;</code> 강제.</li>
              <li><strong>Cross-provider <code>tool_choice</code> 정규화</strong> (v0.94). 4 프로바이더가 각자 다른 형식의 tool_choice를 받는 문제를 통일된 GEODE 측 schema로 변환.</li>
              <li><strong>OpenAI <code>prompt_cache_key</code> derivation</strong> (v0.94). 프로젝트 식별자 기반 prompt 캐시 키 자동 도출.</li>
              <li><strong>GLM thinking 게이트</strong> (v0.94). <code>thinking.type=&quot;off&quot;|&quot;none&quot;</code>로 thinking 비활성 가능. cost 절감용.</li>
              <li><strong>Anthropic <code>agentic_call</code> streaming</strong> (v0.95). <code>messages.stream()</code> async 컨텍스트로 변환. 토큰 트래커는 동일.</li>
              <li><strong>GLM context window 정정</strong> (v0.95). 200_000 flat → 정확값 202_752. <code>tests/test_glm_context_window.py</code> 회귀 방지.</li>
            </ul>

            <h2>OAuth (Anthropic 비활성, OpenAI Codex 활성)</h2>
            <p>
              Anthropic ToS에 따라 Anthropic OAuth 로그인은 비활성 상태입니다. API
              키만 사용합니다. OpenAI Codex Plus 구독 인증은 사용 가능합니다.{" "}
              <em>Operations · OAuth</em> 가 채워지면 그곳을 참조하세요.
            </p>
          </>
        }
        en={
          <>
            <h2>The four adapters</h2>
            <table>
              <thead><tr><th>File</th><th>Provider</th><th>Models in chain</th></tr></thead>
              <tbody>
                <tr><td><code>core/llm/providers/anthropic.py</code></td><td>Anthropic</td><td>Opus 4.7 → Opus 4.6 → Sonnet 4.6 → Haiku 4.5</td></tr>
                <tr><td><code>core/llm/providers/openai.py</code></td><td>OpenAI Responses</td><td>gpt-5.5 → gpt-5.4 → gpt-5.4-mini → gpt-5-mini</td></tr>
                <tr><td><code>core/llm/providers/codex.py</code></td><td>Codex Plus (subscription)</td><td>OpenAI models via Codex routing</td></tr>
                <tr><td><code>core/llm/providers/glm.py</code></td><td>Zhipu GLM</td><td>GLM-5.1 → GLM-5 → GLM-5-turbo → GLM-4.7 → GLM-4.7-flash. context 202_752 tokens.</td></tr>
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
GLM_FALLBACK_CHAIN       = ["glm-5.1", "glm-5", "glm-5-turbo",
                            "glm-4.7", "glm-4.7-flash"]`}</pre>
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

            <h2>v0.94+ guards</h2>
            <ul>
              <li><strong>OpenAI HTML data-URL guard</strong> (v0.94). Blocks the pattern where OpenAI/Codex emits HTML as a single <code>data:text/html;base64,...</code> URL. <code>core/llm/postprocess/html_output.py</code> forces raw <code>&lt;!DOCTYPE html&gt;</code>.</li>
              <li><strong>Cross-provider <code>tool_choice</code> normalization</strong> (v0.94). Four providers each accept a different tool_choice shape; GEODE normalizes to one schema.</li>
              <li><strong>OpenAI <code>prompt_cache_key</code> derivation</strong> (v0.94). Project-identifier based cache key auto-derived.</li>
              <li><strong>GLM thinking gate</strong> (v0.94). <code>thinking.type=&quot;off&quot;|&quot;none&quot;</code> disables thinking; cost saver.</li>
              <li><strong>Anthropic <code>agentic_call</code> streaming</strong> (v0.95). Switched to <code>messages.stream()</code> async context; token tracker unchanged.</li>
              <li><strong>GLM context window correction</strong> (v0.95). Flat 200_000 to the exact 202_752; <code>tests/test_glm_context_window.py</code> guards regression.</li>
            </ul>

            <h2>OAuth (Anthropic disabled, OpenAI Codex active)</h2>
            <p>
              Per Anthropic ToS, OAuth login on Anthropic is disabled — use API
              keys only. OpenAI Codex Plus subscription auth is available; see{" "}
              <em>Operations · OAuth</em> when filled.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
