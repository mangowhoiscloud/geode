import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Quick Start — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell slug="quick-start" title="Quick Start" summary="Install, configure, and run GEODE in five minutes.">
      <h2>Requirements</h2>
      <ul>
        <li>Python 3.12+</li>
        <li><code>uv</code> package manager (<a href="https://docs.astral.sh/uv/">install</a>)</li>
        <li>At least one provider API key (Anthropic, OpenAI, or GLM)</li>
      </ul>

      <h2>Install</h2>
      <pre>{`git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync
uv tool install -e .`}</pre>

      <h2>Configure</h2>
      <p>
        Provider API keys go into <code>~/.geode/config.toml</code> or
        environment variables. The keys you need depend on which fallback
        chain you want active:
      </p>
      <pre>{`export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GLM_API_KEY=...           # optional, third fallback chain
export LANGCHAIN_TRACING_V2=true # optional, opt-in tracing
export LANGCHAIN_API_KEY=ls_...  # required if tracing enabled`}</pre>

      <h2>Run</h2>
      <pre>{`# Interactive REPL
geode

# One-shot natural language
geode "summarize the latest AI research trends"

# Game IP plugin (dry-run, no API calls — uses fixtures)
geode analyze "Cowboy Bebop" --dry-run
# → A (68.4) — undermarketed

# Game IP plugin (full run, requires API keys)
geode analyze "Berserk" --verbose

# Daemon mode (long-running, IPC-served)
geode serve`}</pre>

      <h2>What just happened</h2>
      <p>
        On <code>geode analyze ... --dry-run</code> the pipeline went through
        every stage with mocked LLM responses from the fixture set:
      </p>
      <ol>
        <li>Load IP profile from <code>plugins/game_ip/fixtures/</code></li>
        <li>4 Analysts run in parallel (game_mechanics, player_experience, growth_potential, discovery)</li>
        <li>3 Evaluators score (quality_judge, hidden_value, community_momentum)</li>
        <li>BiasBuster validates with 6 bias checks</li>
        <li>Synthesizer produces the cause-locked recommendation</li>
        <li>PSM scoring (ATT, Z, Gamma) projects the final tier</li>
      </ol>

      <h2>Next</h2>
      <ul>
        <li><a href="/geode/docs/architecture/overview">4-Layer Stack</a> — how the codebase is organized</li>
        <li><a href="/geode/docs/architecture/system-index">System Index</a> — every subsystem with file paths</li>
        <li><a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a> — the prompt assembly pipeline</li>
        <li><a href="/geode/docs/plugins/game-ip">Game IP Plugin</a> — what the analyze command does</li>
      </ul>
    </DocsShell>
  );
}
