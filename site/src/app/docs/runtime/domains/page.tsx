import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Domain Plugins — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/domains"
      title="Domain Plugins"
      summary="DomainPort protocol + plugin loader. Closed domains (game_ip) plug into the agentic core via a stable interface; future domains add files, not patches."
    >
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
    </DocsShell>
  );
}
