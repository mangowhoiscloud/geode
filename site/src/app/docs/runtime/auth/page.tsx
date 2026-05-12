import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Auth & OAuth — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/auth"
      title="Auth & OAuth"
      summary="14 modules in core/auth/ — profile rotator, OAuth flows, credential resolution. Anthropic OAuth disabled per ToS; OpenAI Codex Plus active."
    >
      <h2>The two paths</h2>
      <ol>
        <li><strong>API key</strong> — env vars or <code>~/.geode/config.toml</code>. Always available.</li>
        <li><strong>OAuth (subscription)</strong> — for OpenAI Codex Plus. Triggered by interactive login flow.</li>
      </ol>

      <h2>Anthropic OAuth — disabled</h2>
      <p>
        Anthropic&apos;s ToS prohibits OAuth-based programmatic access for
        non-application accounts. GEODE explicitly disables this path. Users
        on Anthropic must use API keys.
      </p>

      <h2>Profile rotator</h2>
      <p>
        Multiple OpenAI/GLM credential profiles can coexist. The profile
        rotator picks a profile per call, rotating on rate-limit or auth
        failures. This is the foundation that lets fallback chains span
        provider boundaries safely.
      </p>

      <h2>Credential resolution</h2>
      <pre>{`# core/llm/credentials.py
def resolve_provider_key(provider: str, fallback: str | None = None) -> str:
    """OAuth-preferred resolution.

    Order: ProfileRotator (active OAuth profile) →
           settings.<provider>_api_key →
           fallback param →
           empty string."""`}</pre>

      <h2>Files</h2>
      <ul>
        <li><code>core/auth/</code> — 14 modules</li>
        <li><code>core/llm/credentials.py</code> — provider key resolution</li>
        <li><code>core/cli/auth_commands.py</code> — login/logout/status slash commands</li>
      </ul>

      <h2>Storage</h2>
      <p>
        OAuth tokens land in <code>~/.geode/auth/profiles/&lt;name&gt;.json</code>{" "}
        with file-mode 600. Refresh tokens are rotated on expiry; the
        rotator is responsible for catching 401s and forcing refresh
        before retry.
      </p>
    </DocsShell>
  );
}
