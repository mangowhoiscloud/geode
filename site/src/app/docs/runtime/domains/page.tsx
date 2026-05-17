import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Domain Plugins — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/domains"
      title="Domain Plugins"
      titleKo="도메인 플러그인"
      summary="DomainPort protocol + plugin loader. GEODE core ships no built-in analysis domain; external domain packages self-register through the loader."
      summaryKo="DomainPort 프로토콜과 플러그인 로더. GEODE core는 내장 분석 도메인을 포함하지 않으며 외부 도메인 패키지가 로더를 통해 self-register합니다."
    >
      <Bi
        ko={
          <>
            <h2>계약</h2>
            <p>
              <code>core/domains/port.py:18 class DomainPort</code>는 모든 도메인 플러그인이
              구현해야 하는 프로토콜을 정의합니다.
            </p>
            <pre>{`class DomainPort(Protocol):
    name: str
    def get_pipeline(self) -> StateGraph: ...
    def get_valid_axes_map(self) -> dict[str, set[str]]: ...
    def load_ip_profile(self, name: str) -> dict: ...
    def get_analyst_specific(self) -> dict[str, str]: ...`}</pre>

            <h2>로더</h2>
            <p>
              <code>core/domains/loader.py</code>는 runtime registry를 보유합니다.
              외부 도메인 패키지가 import 시점에 <code>name → DomainPort</code>
              엔트리를 등록합니다.
            </p>

            <h2>v0.99.11 분리</h2>
            <p>
              도메인 분석 코드는 GEODE core 배포물에서 빠져나왔습니다. 현재 매핑은 다음과 같습니다.
            </p>
            <ul>
              <li><code>core/domains/</code>. 3개 모듈 (port, loader, types). 도메인 무관.</li>
              <li>외부 도메인 패키지. analyst, evaluator, 스코어링, 픽스처, config를 소유.</li>
            </ul>

            <h2>새 도메인 추가</h2>
            <ol>
              <li>외부 Python 패키지 생성</li>
              <li>패키지의 adapter에 <code>DomainPort</code> 계약 구현</li>
              <li>axes, rubric, 공식을 위한 YAML config 추가</li>
              <li><code>core.domains.loader.register_domain()</code>으로 self-register</li>
              <li>픽스처와 테스트 추가</li>
              <li>외부 패키지 자체 CI에서 domain E2E 검증</li>
            </ol>

            <h2>왜 폐쇄형 프로토콜인가</h2>
            <p>
              개방형 플러그인 프로토콜 (누구나 무엇이든 출시 가능)은 생태계 확장성을 얻는 대신
              안전성을 내어 줍니다. GEODE core는 runtime 계약만 안정적으로 유지하고,
              도메인별 배포/데이터/검증은 각 도메인 패키지가 소유합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>The contract</h2>
            <p>
              <code>core/domains/port.py:18 class DomainPort</code> defines the
              protocol every domain plugin implements:
            </p>
            <pre>{`class DomainPort(Protocol):
    name: str
    def get_pipeline(self) -> StateGraph: ...
    def get_valid_axes_map(self) -> dict[str, set[str]]: ...
    def load_ip_profile(self, name: str) -> dict: ...
    def get_analyst_specific(self) -> dict[str, str]: ...`}</pre>

            <h2>The loader</h2>
            <p>
              <code>core/domains/loader.py</code> holds the runtime registry.
              External domain packages register <code>name → DomainPort</code>
              entries at import time.
            </p>

            <h2>v0.99.11 split</h2>
            <p>
              Domain analysis code moved out of the GEODE core distribution.
              The mapping today:
            </p>
            <ul>
              <li><code>core/domains/</code> — 3 modules: port, loader, types. Domain-agnostic.</li>
              <li>External domain packages own analysts, evaluators, scoring, fixtures, and config.</li>
            </ul>

            <h2>Adding a new domain</h2>
            <ol>
              <li>Create an external Python package</li>
              <li>Implement the <code>DomainPort</code> contract in its adapter</li>
              <li>Add a YAML config for axes / rubrics / formulas</li>
              <li>Self-register with <code>core.domains.loader.register_domain()</code></li>
              <li>Add fixtures + tests</li>
              <li>Run domain E2E in the external package CI</li>
            </ol>

            <h2>Why a closed protocol</h2>
            <p>
              Open plugin protocols (anyone can ship anything) trade safety for
              ecosystem reach. GEODE core keeps only the stable runtime
              contract; each domain package owns its own data, validation, and
              release cadence.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
