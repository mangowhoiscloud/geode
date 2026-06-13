import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "LLM routing — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/providers"
      title="LLM routing"
      titleKo="LLM 라우팅"
      summary="Provider selection and model resolution. Fallback chains ship empty by default; fatal errors fast-fail instead of retrying."
      summaryKo="프로바이더 선택과 모델 해석입니다. 폴백 체인은 기본 비활성으로 출하되고, 치명 오류는 재시도 없이 빠르게 실패합니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 세 프로바이더를 라우팅합니다. Anthropic, OpenAI(+ChatGPT 구독),
              GLM입니다. 이 페이지는 모델이 어떻게 결정되고, 호출이 어느
              어댑터로 가며, 실패했을 때 무엇이 일어나는지 정리합니다.
            </p>

            <h2>구성 요소</h2>
            <table>
              <thead>
                <tr><th>구성</th><th>코드</th></tr>
              </thead>
              <tbody>
                <tr><td>프로바이더 구현</td><td><code>core/llm/providers/anthropic.py</code>, <code>openai.py</code>, <code>codex.py</code>, <code>glm.py</code></td></tr>
                <tr><td>라우터</td><td><code>core/llm/router/</code> (text / json / parsed / streaming / tools 호출 표면)</td></tr>
                <tr><td>어댑터 레지스트리</td><td><code>core/llm/adapters/registry.py</code>의 <code>bootstrap_builtins()</code>. PAYG, 구독 OAuth, CLI 레인을 어댑터로 등록</td></tr>
                <tr><td>라우팅 매니페스트</td><td><code>core/config/routing.toml</code> (+ <code>~/.geode/routing.toml</code> 사용자 오버라이드). 모델 id prefix로 프로바이더 결정</td></tr>
              </tbody>
            </table>
            <p>
              서브프로세스 워커는 부모의 wiring 컨테이너를 거치지 않으므로{" "}
              <code>bootstrap_builtins()</code>를 명시적으로 호출해야 합니다.
              빈 레지스트리는 <code>AdapterNotFoundError</code>로 끝납니다.
            </p>

            <h2>모델 해석 우선순위</h2>
            <p>강한 쪽이 이깁니다.</p>
            <pre>{`CLI 인자
  > env (os.environ + .env)
    > 프로젝트 .geode/config.toml
      > 글로벌 ~/.geode/config.toml
        > routing.toml 기본값`}</pre>
            <p>
              어느 레이어가 이기는지는 <code>geode config explain model</code>이
              레이어별 후보와 함께 보여줍니다. 실효 모델 확인은 항상{" "}
              <code>geode about</code>입니다. config.toml만 보고 판단하면 상위
              env 레이어에 가려진 값을 놓칩니다.
            </p>

            <h2>폴백 체인은 비어서 출하됩니다</h2>
            <p>
              <code>[model.fallbacks]</code>는 기본값이 전부 빈 목록입니다.
              primary 모델이 실패하면 GEODE는 다른 모델로 몰래 갈아타지
              않습니다. 쿼터 소진이면 <code>BillingError</code>를, 일시 오류면
              마지막 예외를 그대로 올리고, 다음 모델은 사용자가{" "}
              <code>/model</code>로 직접 고릅니다. 자동 폴백을 원하면{" "}
              <code>~/.geode/routing.toml</code>의 체인을 채워 옵트인합니다.
              체인 실행기는 <code>core/llm/router/calls/_failover.py</code>의{" "}
              <code>call_with_failover</code>입니다.
            </p>
            <p>
              조용한 cross-provider 자동 전환은 의도적으로 삭제된 기능입니다.
              관측 불가능한 폴백은 어느 모델이 답했는지에 대한 신뢰를
              무너뜨립니다.
            </p>

            <h2>재시도와 fast-fail</h2>
            <p>
              재시도는 <code>core/llm/fallback.py</code>의{" "}
              <code>retry_with_backoff_generic</code>이 담당합니다. 상태를 가진
              CircuitBreaker 클래스는 없습니다. 대신{" "}
              <code>core/llm/errors.py</code>의 두 판정 함수가 재시도를
              단락(short-circuit)시킵니다.
            </p>
            <table>
              <thead>
                <tr><th>판정</th><th>대상</th><th>효과</th></tr>
              </thead>
              <tbody>
                <tr><td><code>is_billing_fatal</code></td><td>결제, 쿼터 소진</td><td>재시도 없이 즉시 실패</td></tr>
                <tr><td><code>is_request_fatal</code></td><td>400류 요청 오류</td><td>같은 요청을 다시 보내봤자 같은 결과이므로 즉시 실패</td></tr>
              </tbody>
            </table>

            <h2>모델별 동작 차이</h2>
            <p>
              모델 패밀리별 능력 앵커는{" "}
              <code>core/llm/model_capabilities.py</code>에 있습니다. 한 가지가
              운영에서 특히 중요합니다. Fable 5는 안전 거절을 HTTP 200의{" "}
              <code>stop_reason: &quot;refusal&quot;</code>로 보내며, Anthropic
              프로바이더의 <code>normalize_anthropic</code>이{" "}
              <code>stop_details</code>를 보존하고 루프가{" "}
              <code>model_refusal</code> 종료로 매핑합니다. 자세한 동작은{" "}
              <a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>의
              종료 경로 절을 참고합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>모델을 바꿨는데 효과가 없음</td>
                  <td>상위 레이어(env)가 가리는 중</td>
                  <td><code>geode config explain model</code>로 이기는 레이어를 찾고 <code>geode about</code>으로 실효값을 확인합니다</td>
                </tr>
                <tr>
                  <td>primary 실패 시 다른 모델로 안 넘어감</td>
                  <td>폴백 체인이 기본값(빈 목록)</td>
                  <td>의도된 동작입니다. <code>/model</code>로 전환하거나 <code>~/.geode/routing.toml</code>에서 옵트인합니다</td>
                </tr>
                <tr>
                  <td>서브프로세스에서 <code>AdapterNotFoundError</code></td>
                  <td><code>bootstrap_builtins()</code> 미호출</td>
                  <td>워커 진입점에서 명시적으로 호출합니다</td>
                </tr>
                <tr>
                  <td>400 오류가 재시도 없이 바로 실패</td>
                  <td><code>is_request_fatal</code> fast-fail</td>
                  <td>의도된 동작입니다. 요청 자체(스키마, 크기)를 고칩니다</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/run/providers">프로바이더 설정 가이드</a>. 자격과 경로 선택.</li>
              <li><a href="/geode/docs/runtime/auth">인증</a>. OAuth, API 키, CLI 레인.</li>
              <li><a href="/geode/docs/guides/llm-adapter">어댑터 추가 가이드</a>. 새 모델, 새 레인 붙이기.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE routes across three providers: Anthropic, OpenAI (+ChatGPT subscription),
              and GLM. This page covers how the model gets resolved, which
              adapter a call lands on, and what happens on failure.
            </p>

            <h2>The pieces</h2>
            <table>
              <thead>
                <tr><th>Piece</th><th>Code</th></tr>
              </thead>
              <tbody>
                <tr><td>Provider implementations</td><td><code>core/llm/providers/anthropic.py</code>, <code>openai.py</code>, <code>codex.py</code>, <code>glm.py</code></td></tr>
                <tr><td>Router</td><td><code>core/llm/router/</code> (text / json / parsed / streaming / tools call surfaces)</td></tr>
                <tr><td>Adapter registry</td><td><code>bootstrap_builtins()</code> in <code>core/llm/adapters/registry.py</code>; registers PAYG, subscription OAuth, and CLI lanes as adapters</td></tr>
                <tr><td>Routing manifest</td><td><code>core/config/routing.toml</code> (+ user override <code>~/.geode/routing.toml</code>); provider resolved by model-id prefix</td></tr>
              </tbody>
            </table>
            <p>
              Subprocess workers do not pass through the parent&apos;s wiring
              container, so they must call <code>bootstrap_builtins()</code>{" "}
              explicitly. An empty registry ends in{" "}
              <code>AdapterNotFoundError</code>.
            </p>

            <h2>Model resolution precedence</h2>
            <p>The stronger layer wins.</p>
            <pre>{`CLI argument
  > env (os.environ + .env)
    > project .geode/config.toml
      > global ~/.geode/config.toml
        > routing.toml default`}</pre>
            <p>
              <code>geode config explain model</code> shows every layer&apos;s
              candidate and which one wins. The effective model is always
              verified with <code>geode about</code>; reading config.toml alone
              misses values masked by a higher env layer.
            </p>

            <h2>Fallback chains ship empty</h2>
            <p>
              <code>[model.fallbacks]</code> defaults to empty lists everywhere.
              When the primary model fails, GEODE does not silently swap models.
              Quota exhaustion raises <code>BillingError</code>; transient
              failures re-raise the last exception; the user picks the next
              model with <code>/model</code>. To opt in to automatic fallback,
              fill the chains in <code>~/.geode/routing.toml</code>. The chain
              executor is <code>call_with_failover</code> in{" "}
              <code>core/llm/router/calls/_failover.py</code>.
            </p>
            <p>
              Silent cross-provider auto-swap was deliberately removed. An
              unobservable fallback destroys trust in which model actually
              answered.
            </p>

            <h2>Retry and fast-fail</h2>
            <p>
              Retries run through <code>retry_with_backoff_generic</code> in{" "}
              <code>core/llm/fallback.py</code>. There is no stateful
              CircuitBreaker class. Instead, two predicates in{" "}
              <code>core/llm/errors.py</code> short-circuit the retry loop.
            </p>
            <table>
              <thead>
                <tr><th>Predicate</th><th>Covers</th><th>Effect</th></tr>
              </thead>
              <tbody>
                <tr><td><code>is_billing_fatal</code></td><td>Billing, quota exhaustion</td><td>Fail immediately, no retry</td></tr>
                <tr><td><code>is_request_fatal</code></td><td>400-class request errors</td><td>Resending the same request yields the same result, so fail immediately</td></tr>
              </tbody>
            </table>

            <h2>Per-model behaviour</h2>
            <p>
              Model-family capability anchors live in{" "}
              <code>core/llm/model_capabilities.py</code>. One matters most in
              operation: Fable 5 delivers safety refusals as HTTP 200 with{" "}
              <code>stop_reason: &quot;refusal&quot;</code>;{" "}
              <code>normalize_anthropic</code> in the Anthropic provider
              preserves <code>stop_details</code>, and the loop maps it to a{" "}
              <code>model_refusal</code> termination. See the termination-path
              section of{" "}
              <a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Switching models has no effect</td>
                  <td>A higher (env) layer masks the change</td>
                  <td>Find the winning layer with <code>geode config explain model</code>; verify with <code>geode about</code></td>
                </tr>
                <tr>
                  <td>No automatic switch when the primary fails</td>
                  <td>Fallback chains default to empty</td>
                  <td>Intended; switch with <code>/model</code> or opt in via <code>~/.geode/routing.toml</code></td>
                </tr>
                <tr>
                  <td><code>AdapterNotFoundError</code> in a subprocess</td>
                  <td><code>bootstrap_builtins()</code> was never called</td>
                  <td>Call it explicitly at the worker entry point</td>
                </tr>
                <tr>
                  <td>A 400 error fails immediately without retries</td>
                  <td>The <code>is_request_fatal</code> fast-fail</td>
                  <td>Intended; fix the request itself (schema, size)</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/run/providers">Provider setup guide</a>. Credentials and path selection.</li>
              <li><a href="/geode/docs/runtime/auth">Authentication</a>. OAuth, API keys, CLI lanes.</li>
              <li><a href="/geode/docs/guides/llm-adapter">Add an LLM adapter</a>. Attaching a new model or lane.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
