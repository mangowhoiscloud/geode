import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Add an LLM adapter — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="guides/llm-adapter"
      title="Add an LLM adapter"
      titleKo="LLM 어댑터 추가"
      summary="Add a provider to the router and adapter layer, with a fallback entry."
      summaryKo="라우터와 어댑터 레이어에 프로바이더를 추가하고 폴백 항목을 거는 방법입니다."
    >
      <Bi
        ko={
          <>
            <p>
              어댑터는 하나의 <code>(provider, source)</code> 조합을 실제 호출로
              바꾸는 계층입니다. PAYG API 키 호출이든, OAuth 구독 호출이든,
              로컬 CLI 서브프로세스든 전부 같은 프로토콜을 따릅니다. 새 백엔드를
              붙이는 작업은 어댑터 작성, 레지스트리 등록, 라우팅 연결,
              호출 계약 문서화의 네 단계입니다.
            </p>

            <h2>1. 어댑터를 작성합니다</h2>
            <p>
              어댑터는 <code>core/llm/adapters/base.py</code>의{" "}
              <code>LLMAdapter</code> 프로토콜을 만족하면 됩니다. 최소 요건은
              네 정체성 속성(<code>name</code>, <code>provider</code>,{" "}
              <code>source</code>, <code>billing_type</code>)과 비동기 호출
              메서드 <code>acomplete()</code>입니다. <code>source</code>는{" "}
              <code>CONCRETE_SOURCES</code>(<code>payg</code> /{" "}
              <code>subscription</code> / <code>adapter</code>) 중 하나여야 하고,{" "}
              <code>&quot;auto&quot;</code>는 picker 전용 sentinel이라 어댑터에 박을 수
              없습니다. 요청·응답 셰이핑은 프로토콜이 정의한 provider-agnostic
              타입(<code>AdapterCallRequest</code>,{" "}
              <code>AdapterCallResult</code>)을 어댑터 내부에서 SDK 페이로드로
              번역하는 일입니다. <code>AnthropicPaygAdapter</code>(
              <code>core/llm/adapters/anthropic_payg.py</code>)가 PAYG 경로의
              참조 구현입니다.
            </p>
            <pre>{`# core/llm/adapters/acme_payg.py
from dataclasses import dataclass, field
from typing import Any
from core.llm.adapters.base import (
    SOURCE_PAYG, AdapterBillingType,
    AdapterCallRequest, AdapterCallResult,
    EnvironmentReport, UsageSummary,
)

@dataclass
class AcmePaygAdapter:
    name: str = "acme-payg"
    provider: str = "acme"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    _client: Any = field(default=None, init=False, repr=False)

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        client = self._get_client()
        raw = await client.create(...)  # translate req -> SDK payload
        return AdapterCallResult(
            text=raw.text,
            usage=UsageSummary(input_tokens=..., output_tokens=...),
            stop_reason=raw.stop_reason,
        )

    def test_environment(self) -> EnvironmentReport:
        from core.config import settings
        if not settings.acme_api_key:
            return EnvironmentReport(ok=False, hints=("set ACME_API_KEY",))
        return EnvironmentReport(ok=True)`}</pre>
            <p>
              스트리밍·introspection 메서드(<code>astream</code>,{" "}
              <code>list_models</code>, <code>get_quota_windows</code>,{" "}
              <code>detect_credential</code>)는 프로토콜이 요구하지만, 해당
              표면을 지원하지 않으면 빈 값이나 <code>None</code>을 돌려줘도
              됩니다. 단, <code>test_environment</code>는 항상 정직해야 합니다.
            </p>

            <h2>2. 레지스트리에 등록합니다</h2>
            <p>
              어댑터는 프로세스 전역{" "}
              <code>core/llm/adapters/registry.py</code> 레지스트리로 조회됩니다.
              내장 어댑터는 <code>bootstrap_builtins()</code>에서 등록되므로,
              새 내장 어댑터라면 그 함수의 클래스 튜플에 추가합니다. 외부
              플러그인이면 진입점에서 <code>register_adapter(AcmePaygAdapter())</code>를
              직접 호출합니다. <code>resolve_for(provider, source)</code>는{" "}
              <code>(provider, source)</code> 쌍이 정확히 하나의 어댑터에
              매칭되도록 강제하므로, 같은 쌍을 둘 등록하면 invariant 위반으로
              곧바로 실패합니다.
            </p>
            <pre>{`# core/llm/adapters/registry.py — bootstrap_builtins()
from core.llm.adapters.acme_payg import AcmePaygAdapter

for adapter_cls in (..., AcmePaygAdapter):
    instance = adapter_cls()
    if instance.name in _REGISTRY:
        continue
    register_adapter(instance)`}</pre>
            <p>
              서브프로세스(워커·audit)는 부모의 wiring 컨테이너를 거치지 않으므로{" "}
              <code>bootstrap_builtins()</code>를 명시 호출해야 합니다. 안 그러면
              레지스트리가 비어 <code>AdapterNotFoundError</code>가 납니다.
            </p>

            <h2>3. 라우팅과 폴백 체인을 연결합니다</h2>
            <p>
              <code>core/llm/router/calls/_route.py</code>의{" "}
              <code>_route_provider(model)</code>이 모델 이름을 프로바이더로
              해석합니다. 등록된 Plan이 있으면 그것을 따르고, 없으면{" "}
              <code>core.config</code>의 정적 <code>_resolve_provider</code>로
              떨어집니다. 모델 접두사와 프로바이더의 매핑은{" "}
              <code>core/config/routing.toml</code>의{" "}
              <code>[routing.prefixes]</code>가 SoT이고, 사용자 override는{" "}
              <code>~/.geode/routing.toml</code>입니다. 새 프로바이더의 모델
              접두사를 여기에 추가합니다. 다중 모델 폴백은{" "}
              <code>core/llm/router/calls/_failover.py</code>의{" "}
              <code>call_with_failover(models, call_fn)</code>이 처리합니다.
              모델 체인을 순서대로 시도하며, 재시도 가능한 오류(rate-limit,
              timeout, connection, server)는 백오프 후 다음 모델로 넘어가고,
              인증 오류 같은 비재시도 오류는 즉시 전파됩니다. 단, 폴백 체인은
              기본 출하값이 전부 빈 리스트입니다(<code>[model.fallbacks]</code>).
              조용한 모델 교체 대신 실패를 드러내는 설계이므로, 새 어댑터의
              모델을 폴백 후보로 쓰려면 <code>~/.geode/routing.toml</code>에서
              직접 체인을 켜야 합니다.
            </p>

            <h2>4. 호출 계약을 문서화합니다</h2>
            <p>
              adapter가 등록됐다는 사실과 agentic 기능이 보장된다는 주장은
              다릅니다. 새 경로의 실제 request builder를 확인한 뒤{" "}
              <a href="/geode/docs/runtime/llm/tool-calling">도구 호출</a>과{" "}
              <a href="/geode/docs/runtime/llm/structured-output">구조화 출력</a>{" "}
              표에 provider/source/adapter 경계를 추가합니다.
            </p>
            <table>
              <thead>
                <tr><th>항목</th><th>기록할 내용</th></tr>
              </thead>
              <tbody>
                <tr><td>도구 호출</td><td><code>ToolSpec</code> encoding, <code>tool_choice</code> 변환, 복수 호출, call id와 result replay</td></tr>
                <tr><td>구조화 출력</td><td><code>response_schema</code> wire field, strict 판정, local validation과 retry 범위</td></tr>
                <tr><td>미지원 경계</td><td>필드를 무시하는 경로와 모델별 확인이 필요한 부분을 지원으로 뭉개지 않고 명시</td></tr>
                <tr><td>근거</td><td>공식 provider 문서 또는 source, local request builder, request-shape test, 남은 live test</td></tr>
              </tbody>
            </table>
            <p>
              SDK type에 필드가 있다는 사실만으로 지원을 선언하지 않습니다.
              adapter가 값을 실제 wire payload에 싣는지와, GEODE가 결과를 어떻게
              정규화·검증하는지를 함께 적습니다.
            </p>

            <h2>5. 확인합니다</h2>
            <p>
              <code>(provider, source)</code> 쌍이 정확히 어댑터로 해석되는지
              확인합니다.
            </p>
            <pre>{`uv run python -c "
from core.llm.adapters.registry import bootstrap_builtins, resolve_for
bootstrap_builtins()
a = resolve_for('acme', 'payg')
print(a.name, a.provider, a.source)
print(a.test_environment().ok)
"`}</pre>
            <p>
              어댑터 이름이 출력되면 라우팅이 그 쌍을 찾을 수 있습니다.{" "}
              <code>test_environment().ok</code>는 자격증명 상태를 정직하게
              보고합니다.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>참조:</em>{" "}
              <a href="/geode/docs/runtime/llm/providers">Providers</a>,{" "}
              <a href="/geode/docs/runtime/llm/tool-calling">Tool calling</a>,{" "}
              <a href="/geode/docs/runtime/llm/structured-output">Structured output</a>,{" "}
              <a href="/geode/docs/run/pick-path">Pick a path</a>.
            </p>
          </>
        }
        en={
          <>
            <p>
              An adapter is the layer that turns one{" "}
              <code>(provider, source)</code> pair into a real call. PAYG API-key
              calls, OAuth subscription calls, and local CLI subprocess calls all
              satisfy the same protocol. Adding a backend has four parts: write the
              adapter, register it, wire routing, and document the call contract.
            </p>

            <h2>1. Write the adapter</h2>
            <p>
              An adapter satisfies the <code>LLMAdapter</code> protocol in{" "}
              <code>core/llm/adapters/base.py</code>. The minimum is four identity
              attributes (<code>name</code>, <code>provider</code>,{" "}
              <code>source</code>, <code>billing_type</code>) plus the async call
              method <code>acomplete()</code>. The <code>source</code> must be one
              of <code>CONCRETE_SOURCES</code> (<code>payg</code> /{" "}
              <code>subscription</code> / <code>adapter</code>);{" "}
              <code>&quot;auto&quot;</code> is a picker-only sentinel and cannot be pinned on
              an adapter. Request and response shaping is the work of translating
              the protocol&apos;s provider-agnostic types (<code>AdapterCallRequest</code>,{" "}
              <code>AdapterCallResult</code>) to SDK payloads inside the adapter.{" "}
              <code>AnthropicPaygAdapter</code> in{" "}
              <code>core/llm/adapters/anthropic_payg.py</code> is the reference for
              the PAYG path.
            </p>
            <pre>{`# core/llm/adapters/acme_payg.py
from dataclasses import dataclass, field
from typing import Any
from core.llm.adapters.base import (
    SOURCE_PAYG, AdapterBillingType,
    AdapterCallRequest, AdapterCallResult,
    EnvironmentReport, UsageSummary,
)

@dataclass
class AcmePaygAdapter:
    name: str = "acme-payg"
    provider: str = "acme"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    _client: Any = field(default=None, init=False, repr=False)

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        client = self._get_client()
        raw = await client.create(...)  # translate req -> SDK payload
        return AdapterCallResult(
            text=raw.text,
            usage=UsageSummary(input_tokens=..., output_tokens=...),
            stop_reason=raw.stop_reason,
        )

    def test_environment(self) -> EnvironmentReport:
        from core.config import settings
        if not settings.acme_api_key:
            return EnvironmentReport(ok=False, hints=("set ACME_API_KEY",))
        return EnvironmentReport(ok=True)`}</pre>
            <p>
              The streaming and introspection methods (<code>astream</code>,{" "}
              <code>list_models</code>, <code>get_quota_windows</code>,{" "}
              <code>detect_credential</code>) are required by the protocol but may
              return empty values or <code>None</code> for surfaces you do not
              support. <code>test_environment</code> must always be honest.
            </p>

            <h2>2. Register it in the registry</h2>
            <p>
              Adapters are looked up through the process-global registry in{" "}
              <code>core/llm/adapters/registry.py</code>. Built-in adapters
              register in <code>bootstrap_builtins()</code>, so for a new built-in,
              add the class to that function&apos;s tuple. For an external plugin, call{" "}
              <code>register_adapter(AcmePaygAdapter())</code> from your entry
              point. <code>resolve_for(provider, source)</code> enforces that a{" "}
              <code>(provider, source)</code> pair matches exactly one adapter, so
              registering two for the same pair fails loudly as an invariant
              violation.
            </p>
            <pre>{`# core/llm/adapters/registry.py — bootstrap_builtins()
from core.llm.adapters.acme_payg import AcmePaygAdapter

for adapter_cls in (..., AcmePaygAdapter):
    instance = adapter_cls()
    if instance.name in _REGISTRY:
        continue
    register_adapter(instance)`}</pre>
            <p>
              Subprocesses (worker, audit) do not pass through the parent wiring
              container, so they must call <code>bootstrap_builtins()</code>{" "}
              explicitly. Without it the registry is empty and you get an{" "}
              <code>AdapterNotFoundError</code>.
            </p>

            <h2>3. Wire routing and the fallback chain</h2>
            <p>
              <code>_route_provider(model)</code> in{" "}
              <code>core/llm/router/calls/_route.py</code> resolves a model name to
              a provider. It honors a registered Plan if present, otherwise falls
              back to the static <code>_resolve_provider</code> in{" "}
              <code>core.config</code>. The model-prefix-to-provider mapping is
              owned by <code>[routing.prefixes]</code> in{" "}
              <code>core/config/routing.toml</code>, with the user override at{" "}
              <code>~/.geode/routing.toml</code>; add your provider&apos;s model
              prefix there. Multi-model fallback is handled by{" "}
              <code>call_with_failover(models, call_fn)</code> in{" "}
              <code>core/llm/router/calls/_failover.py</code>. It tries the model
              chain in order; retryable errors (rate-limit, timeout, connection,
              server) back off and move to the next model, while non-retryable
              errors like authentication propagate immediately. Note that
              fallback chains ship empty (<code>[model.fallbacks]</code>): the
              design surfaces failure instead of silently swapping models, so to
              use your adapter&apos;s model as a fallback candidate you opt in
              by editing the chain in <code>~/.geode/routing.toml</code>.
            </p>

            <h2>4. Document the call contract</h2>
            <p>
              Adapter registration does not prove an agentic feature. Inspect
              the request builder, then add the provider/source/adapter boundary
              to <a href="/geode/docs/runtime/llm/tool-calling">Tool calling</a>{" "}
              and <a href="/geode/docs/runtime/llm/structured-output">Structured output</a>.
            </p>
            <table>
              <thead>
                <tr><th>Field</th><th>What to record</th></tr>
              </thead>
              <tbody>
                <tr><td>Tool calling</td><td><code>ToolSpec</code> encoding, <code>tool_choice</code> translation, multiple calls, call ids, and result replay</td></tr>
                <tr><td>Structured output</td><td><code>response_schema</code> wire field, strictness, local validation, and retry boundary</td></tr>
                <tr><td>Unsupported boundary</td><td>State which paths ignore the field and which model claims still need verification</td></tr>
                <tr><td>Evidence</td><td>Official provider docs or source, local request builder, request-shape test, and remaining live test</td></tr>
              </tbody>
            </table>
            <p>
              An SDK field alone is not evidence of support. Record both the
              wire payload the adapter actually builds and how GEODE normalizes
              or validates the result.
            </p>

            <h2>5. Verify</h2>
            <p>
              Confirm the <code>(provider, source)</code> pair resolves to exactly
              your adapter.
            </p>
            <pre>{`uv run python -c "
from core.llm.adapters.registry import bootstrap_builtins, resolve_for
bootstrap_builtins()
a = resolve_for('acme', 'payg')
print(a.name, a.provider, a.source)
print(a.test_environment().ok)
"`}</pre>
            <p>
              When the adapter name prints, routing can find that pair.{" "}
              <code>test_environment().ok</code> reports the credential state
              honestly.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>See:</em>{" "}
              <a href="/geode/docs/runtime/llm/providers">Providers</a>,{" "}
              <a href="/geode/docs/runtime/llm/tool-calling">Tool calling</a>,{" "}
              <a href="/geode/docs/runtime/llm/structured-output">Structured output</a>,{" "}
              <a href="/geode/docs/run/pick-path">Pick a path</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
