import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Add an LLM adapter — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="guides/llm-adapter"
      title="Add an LLM adapter"
      titleKo="LLM 어댑터 추가"
      summary="Add a provider through the immutable adapter registry and package entry-point discovery."
      summaryKo="불변 어댑터 레지스트리와 패키지 진입점 검색으로 프로바이더를 추가하는 방법입니다."
    >
      <Bi
        ko={
          <>
            <p>
              어댑터는 하나의 <code>(provider, source)</code> 조합을 실제 호출로
              바꾸는 계층입니다. PAYG API 키 호출이든, OAuth 구독 호출이든,
              설치된 외부 어댑터든 전부 같은 프로토콜을 따릅니다. 새 백엔드를
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
    UsageSummary,
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
        )`}</pre>
            <p>
              스트리밍과 introspection은 필수가 아닙니다. 지원하는 표면만{" "}
              <code>StreamingCapable</code>,{" "}
              <code>EnvironmentDiagnosticCapable</code>,{" "}
              <code>ModelListingCapable</code>,{" "}
              <code>QuotaInspectionCapable</code>,{" "}
              <code>CredentialDetectionCapable</code> 구조를 만족시키면 됩니다.
              지원하지 않는 메서드를 빈 값이나 <code>None</code> stub으로 만들지
              마십시오.
            </p>

            <h2>2. 레지스트리에 등록합니다</h2>
            <p>
              어댑터는 <code>core/llm/adapters/registry.py</code>가 발행한 불변
              generation snapshot으로 조회됩니다. 내장 어댑터는 명시적 factory
              목록에서 생성합니다. 외부 패키지는 전역 dict를 직접 수정하지 않고{" "}
              <code>geode.llm_adapters</code> 패키지 진입점에 factory를
              선언합니다. 진입점 이름은 factory가 반환한 canonical adapter name과
              같아야 합니다. <code>resolve_for(provider, source)</code>는{" "}
              <code>(provider, source)</code> 쌍이 정확히 하나의 어댑터에
              매칭되도록 강제하므로, 같은 쌍을 둘 등록하면 invariant 위반으로
              곧바로 실패합니다.
            </p>
            <pre>{`# acme-geode-adapter/pyproject.toml
[project.entry-points."geode.llm_adapters"]
acme-payg = "acme_geode:create_adapter"

# acme_geode/__init__.py
def create_adapter():
    return AcmePaygAdapter()`}</pre>
            <p>
              진입점 이름과 배포 패키지 metadata는 실행 없이 먼저 열거됩니다.
              GEODE는 이름 충돌을 해결한 다음
              <a href="/geode/docs/config/basics">확장 신뢰 정책</a>의
              <code>llm-adapter:acme-payg</code> 승인을 확인하고 나서야
              <code>entry_point.load()</code>를 호출합니다. 승인이 없으면 validation
              report에 <code>REJECTED</code>로 남고 factory는 import되지 않습니다.
              factory는 기존처럼 인자 없이 만들거나, 정확히 하나의
              <code>context</code> 인자를 받아 불변 확장 ID와 승인된 포트를 확인할
              수 있습니다. 다른 signature는 session 시작 전에 실패합니다.
            </p>
            <p>
              기존 factory는 보수적인 호환 composition을 자동으로 얻습니다.
              실제 인증 선택과 API shape를 선언하려면 반환 객체에 불변
              <code>ProviderSpec</code>을 추가하십시오. 이 값은
              <code>ProviderProfile</code>, <code>CredentialRoute</code>,
              <code>TransportSpec</code>으로 나뉘며 secret이나 SDK client를
              담지 않습니다. 선언한 provider/source/billing/capability가
              adapter 호환 속성과 다르면 session 시작 전에 등록이 실패합니다.
            </p>
            <pre>{`# acme_geode/__init__.py
from core.llm.registry import (
    AdapterBillingType, CredentialRoute, ProviderProfile,
    ProviderSpec, TransportSpec,
)

ACME_SPEC = ProviderSpec(
    profile=ProviderProfile("acme", "acme", "Acme", "acme"),
    credential=CredentialRoute(
        source="payg", account_provider="acme", selector="plugin",
        auth_type="bearer", billing_type=AdapterBillingType.API,
    ),
    transport=TransportSpec(
        id="acme-responses", api="acme-responses",
        default_base_url="https://api.acme.example/v1",
    ),
)

class AcmeComposedAdapter(AcmePaygAdapter):
    provider_spec = ACME_SPEC

def create_adapter():
    return AcmeComposedAdapter()`}</pre>
            <p>
              서브프로세스(워커·audit)는 부모의 wiring 컨테이너를 거치지 않으므로{" "}
              <code>bootstrap_builtins()</code>를 명시 호출해야 합니다. 안 그러면
              레지스트리가 비어 <code>AdapterNotFoundError</code>가 납니다. 이 호출은
              내장 factory와 지원 진입점을 함께 검색하며, generation과 validation
              report가 붙은 snapshot을 반환합니다. 새 세션은 현재 snapshot을
              캡처하고, 이미 실행 중인 세션은 reload 뒤에도 기존 generation을
              유지합니다. canonical ID 충돌은 기본적으로 실패합니다. 의도적인
              교체만 <code>AdapterOverride</code>로 승자 origin, priority, trust
              decision을 명시해 <code>reload_adapters()</code>에 전달합니다.
            </p>

            <h2>3. 라우팅과 폴백 체인을 연결합니다</h2>
            <p>
              <code>core.config._resolve_provider(model)</code>이 모델 이름을
              프로바이더로 해석하고, adapter dispatch가 credential metadata로
              source를 결정합니다. 등록된 Plan은 별도의 routing target으로
              endpoint와 credential을 선택합니다. 모델 접두사와 프로바이더의 매핑은{" "}
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
              기본 경로는 실패를 그대로 드러냅니다. 새 어댑터의 모델을 폴백
              후보로 쓰려면 <code>~/.geode/routing.toml</code>에서
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
from core.llm.adapters.registry import bootstrap_builtins
from core.llm.adapters import EnvironmentDiagnosticCapable
snapshot = bootstrap_builtins()
a = snapshot.resolve_for('acme', 'payg')
print(snapshot.generation, snapshot.report.origins)
print(a.name, a.provider, a.source)
if isinstance(a, EnvironmentDiagnosticCapable):
    print(a.test_environment().ok)
"`}</pre>
            <p>
              어댑터 이름이 출력되면 라우팅이 그 쌍을 찾을 수 있습니다.{" "}
              환경 진단 capability를 구현했다면 <code>test_environment().ok</code>도
              자격증명 상태를 정직하게 보고합니다.
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
              calls, OAuth subscription calls, and installed external adapters all
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
    UsageSummary,
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
        )`}</pre>
            <p>
              Streaming and introspection are optional. Implement only the
              structural capabilities you support: <code>StreamingCapable</code>,{" "}
              <code>EnvironmentDiagnosticCapable</code>,{" "}
              <code>ModelListingCapable</code>, <code>QuotaInspectionCapable</code>,
              or <code>CredentialDetectionCapable</code>. Do not add empty or{" "}
              <code>None</code> stubs for unsupported surfaces.
            </p>

            <h2>2. Register it in the registry</h2>
            <p>
              Adapters are looked up through immutable generation snapshots
              published by <code>core/llm/adapters/registry.py</code>. Built-ins
              come from an explicit factory list. External packages do not mutate
              a global dictionary; they expose a factory through the{" "}
              <code>geode.llm_adapters</code> package entry-point group. The entry
              point name must equal the returned adapter&apos;s canonical name.{" "}
              <code>resolve_for(provider, source)</code> enforces that a{" "}
              <code>(provider, source)</code> pair matches exactly one adapter, so
              registering two for the same pair fails loudly as an invariant
              violation.
            </p>
            <pre>{`# acme-geode-adapter/pyproject.toml
[project.entry-points."geode.llm_adapters"]
acme-payg = "acme_geode:create_adapter"

# acme_geode/__init__.py
def create_adapter():
    return AcmePaygAdapter()`}</pre>
            <p>
              GEODE enumerates the entry-point name and distribution metadata
              without executing it. It resolves name collisions, checks the
              <code>llm-adapter:acme-payg</code> grant in the
              <a href="/geode/docs/config/basics">extension trust policy</a>,
              and only then calls <code>entry_point.load()</code>. Without that
              grant the validation report records <code>REJECTED</code> and the
              factory is never imported. A factory may keep the legacy
              no-argument signature or accept exactly one <code>context</code>
              parameter to inspect its immutable extension ID and granted ports.
              Any other signature fails before a session starts.
            </p>
            <p>
              The legacy factory receives a conservative compatibility
              composition automatically. To declare the real credential
              selection and API shape, attach an immutable
              <code>ProviderSpec</code> to the returned object. It separates
              <code>ProviderProfile</code>, <code>CredentialRoute</code>, and
              <code>TransportSpec</code> and contains no secret or SDK client.
              Registration fails before a session when its
              provider/source/billing/capabilities disagree with the adapter
              compatibility attributes.
            </p>
            <pre>{`# acme_geode/__init__.py
from core.llm.registry import (
    AdapterBillingType, CredentialRoute, ProviderProfile,
    ProviderSpec, TransportSpec,
)

ACME_SPEC = ProviderSpec(
    profile=ProviderProfile("acme", "acme", "Acme", "acme"),
    credential=CredentialRoute(
        source="payg", account_provider="acme", selector="plugin",
        auth_type="bearer", billing_type=AdapterBillingType.API,
    ),
    transport=TransportSpec(
        id="acme-responses", api="acme-responses",
        default_base_url="https://api.acme.example/v1",
    ),
)

class AcmeComposedAdapter(AcmePaygAdapter):
    provider_spec = ACME_SPEC

def create_adapter():
    return AcmeComposedAdapter()`}</pre>
            <p>
              Subprocesses (worker, audit) do not pass through the parent wiring
              container, so they must call <code>bootstrap_builtins()</code>{" "}
              explicitly. Without it the registry is empty and you get an{" "}
              <code>AdapterNotFoundError</code>. The call discovers built-in
              factories and supported entry points together and returns a snapshot
              with a generation and validation report. New sessions capture the
              current snapshot; a running session retains its generation after a
              reload. Canonical-ID collisions fail by default. An intentional
              replacement must pass an <code>AdapterOverride</code> to{" "}
              <code>reload_adapters()</code> that records the winning origin,
              priority, and trust decision.
            </p>

            <h2>3. Wire routing and the fallback chain</h2>
            <p>
              <code>core.config._resolve_provider(model)</code> resolves a model
              name to a provider, and adapter dispatch resolves the source from
              credential metadata. A registered Plan separately selects the
              routing target&apos;s endpoint and credential. The
              model-prefix-to-provider mapping is
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
              design surfaces failure directly. To use your adapter&apos;s model as
              a fallback candidate, opt in
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
from core.llm.adapters.registry import bootstrap_builtins
from core.llm.adapters import EnvironmentDiagnosticCapable
snapshot = bootstrap_builtins()
a = snapshot.resolve_for('acme', 'payg')
print(snapshot.generation, snapshot.report.origins)
print(a.name, a.provider, a.source)
if isinstance(a, EnvironmentDiagnosticCapable):
    print(a.test_environment().ok)
"`}</pre>
            <p>
              When the adapter name prints, routing can find that pair.{" "}
              If the adapter implements environment diagnostics,{" "}
              <code>test_environment().ok</code> also reports credential state
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
