import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Domain Plugins — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/domains"
      title="Domain Plugins"
      titleKo="도메인 플러그인"
      summary="DomainPort protocol + plugin loader. Closed domains (game_ip) plug into the agentic core via a stable interface; future domains add files, not patches."
      summaryKo="DomainPort 프로토콜과 플러그인 로더. 폐쇄형 도메인 (game_ip)이 안정적인 인터페이스로 agentic 코어에 연결됩니다. 새 도메인은 파일을 추가할 뿐 패치는 필요 없습니다."
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
              <code>core/domains/loader.py</code>는 <code>_DOMAIN_REGISTRY</code>를 보유합니다.
              <code>name → DomainPort</code> 엔트리 딕셔너리입니다. v0.64.0은 단일 엔트리
              <code>game_ip → plugins.game_ip.adapter:GameIPDomain</code>으로 출시됐습니다.
            </p>

            <h2>v0.64.0 분리</h2>
            <p>
              도메인 코드는 <code>core/</code>에서 빠져나왔습니다. 현재 매핑은 다음과 같습니다.
            </p>
            <ul>
              <li><code>core/domains/</code>. 3개 모듈 (port, loader, types). 도메인 무관.</li>
              <li><code>plugins/game_ip/</code>. 13개 모듈 (실제 analyst, evaluator, 스코어링 엔진, 픽스처, config).</li>
            </ul>
            <p>
              예시 도메인은 <a href="/geode/docs/plugins/game-ip">Game IP 플러그인</a>을 참고하세요.
            </p>

            <h2>새 도메인 추가</h2>
            <ol>
              <li><code>plugins/&lt;name&gt;/</code> 생성</li>
              <li><code>plugins/&lt;name&gt;/adapter.py</code>에 <code>DomainPort</code> 계약 구현</li>
              <li>axes, rubric, 공식을 위한 YAML config 추가</li>
              <li><code>core/domains/loader.py:_DOMAIN_REGISTRY</code>에 등록</li>
              <li>픽스처와 테스트 추가</li>
              <li>품질 게이트는 자동 확장 (<code>core/</code>와 <code>plugins/</code> 모두 게이트됨)</li>
            </ol>

            <h2>왜 폐쇄형 프로토콜인가</h2>
            <p>
              개방형 플러그인 프로토콜 (누구나 무엇이든 출시 가능)은 생태계 확장성을 얻는 대신
              안전성을 내어 줍니다. GEODE의 폐쇄형 프로토콜은 모든 도메인이 모노레포에 함께
              출시되므로, 품질 게이트가 코어와 동일한 커버리지 (lint, type, test, E2E 픽스처)를
              제공합니다. 개방형 배포는 두 번째 도메인이 분리를 정당화할 때까지 보류됩니다.
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
              <code>core/domains/loader.py</code> holds <code>_DOMAIN_REGISTRY</code> —
              a dict of <code>name → DomainPort</code> entries. v0.64.0 ships
              with a single entry, <code>game_ip → plugins.game_ip.adapter:GameIPDomain</code>.
            </p>

            <h2>v0.64.0 split</h2>
            <p>
              The domain code moved out of <code>core/</code>. The mapping today:
            </p>
            <ul>
              <li><code>core/domains/</code> — 3 modules: port, loader, types. Domain-agnostic.</li>
              <li><code>plugins/game_ip/</code> — 13 modules: actual analysts, evaluators, scoring engine, fixtures, config.</li>
            </ul>
            <p>
              See <a href="/geode/docs/plugins/game-ip">Game IP Plugin</a> for
              the example domain.
            </p>

            <h2>Adding a new domain</h2>
            <ol>
              <li>Create <code>plugins/&lt;name&gt;/</code></li>
              <li>Implement the <code>DomainPort</code> contract in <code>plugins/&lt;name&gt;/adapter.py</code></li>
              <li>Add a YAML config for axes / rubrics / formulas</li>
              <li>Register in <code>core/domains/loader.py:_DOMAIN_REGISTRY</code></li>
              <li>Add fixtures + tests</li>
              <li>Quality gates extend automatically (<code>core/</code> + <code>plugins/</code> both gated)</li>
            </ol>

            <h2>Why a closed protocol</h2>
            <p>
              Open plugin protocols (anyone can ship anything) trade safety for
              ecosystem reach. GEODE&apos;s closed protocol — every domain ships
              in the monorepo — gives quality gates the same coverage as the core
              (lint, type, tests, E2E fixtures). Open shipping is deferred until
              a second domain motivates the split.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
