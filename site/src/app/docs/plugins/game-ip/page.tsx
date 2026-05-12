import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Game IP Plugin — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="plugins/game-ip"
      title="Game IP Plugin"
      summary="Closed-domain plugin for evaluating Game/IP market potential. 4 Analysts + 3 Evaluators + Synthesizer + BiasBuster, 14-axis PSM scoring."
    >
      <h2>Pipeline shape</h2>
      <pre>{`Input: { ip_name }
   │
   ▼
load_ip_profile  (from MonoLake / fixtures)
   │
   ├─► Analyst × 4 (parallel)
   │     game_mechanics    →   findings + 1-5 score
   │     player_experience →   findings + 1-5 score
   │     growth_potential  →   findings + 1-5 score
   │     discovery         →   findings + 1-5 score
   │
   ▼
Evaluator × 3 (parallel)
   quality_judge      → 8 axes (a, b, c, b1, c1, c2, m, n)
   hidden_value       → 3 axes
   community_momentum → 3 axes
   │
   ▼
BiasBuster (6 bias checks)
   confirmation, recency, anchoring, position, verbosity, self-enhancement
   │
   ▼
Synthesizer (cause-locked narrative)
   │
   ▼
Output: tier (S/A/B/C/D) + score (0-100) + cause + recommendation`}</pre>

      <h2>Fixtures</h2>
      <table>
        <thead><tr><th>IP</th><th>Tier</th><th>Score</th><th>Cause</th></tr></thead>
        <tbody>
          <tr><td>Berserk</td><td><strong>S</strong></td><td>81.2</td><td>conversion_failure</td></tr>
          <tr><td>Cowboy Bebop</td><td><strong>A</strong></td><td>68.4</td><td>undermarketed</td></tr>
          <tr><td>Ghost in the Shell</td><td><strong>B</strong></td><td>51.7</td><td>discovery_failure</td></tr>
        </tbody>
      </table>

      <h2>Configuration SSOT</h2>
      <p>
        <code>plugins/game_ip/config/evaluator_axes.yaml</code> is the single
        source of truth for:
      </p>
      <ul>
        <li><strong>4 analyst directives</strong> — domain-specific focus per analyst type</li>
        <li><strong>3 evaluator axis sets</strong> — quality_judge (8), hidden_value (3), community_momentum (3)</li>
        <li><strong>Korean rubrics</strong> — 1-5 anchor descriptions per axis</li>
        <li><strong>Composite formulas</strong> — e.g. <code>(axes_sum - 8) / 32 * 100</code> for quality_judge</li>
        <li><strong>Prospect axes</strong> — for non-gamified IPs (novels, films)</li>
      </ul>
      <p>
        These three top-level keys are hashed into{" "}
        <code>EVALUATOR_AXES</code>, <code>PROSPECT_EVALUATOR_AXES</code>,{" "}
        and <code>ANALYST_SPECIFIC</code> entries in{" "}
        <code>PROMPT_VERSIONS</code>. See{" "}
        <a href="/geode/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>.
      </p>

      <h2>Plugin contract</h2>
      <p>
        The plugin implements the <code>DomainPort</code> protocol from{" "}
        <code>core/domains/port.py</code>:
      </p>
      <ul>
        <li><code>get_pipeline()</code> — returns the LangGraph StateGraph</li>
        <li><code>get_valid_axes_map()</code> — exposes axis keys per evaluator</li>
        <li><code>load_ip_profile(ip_name)</code> — domain data lookup</li>
      </ul>
      <p>
        The loader at <code>core/domains/loader.py</code> discovers plugins
        in the <code>plugins/</code> namespace at startup.
      </p>

      <h2>CLI</h2>
      <pre>{`# Dry-run (no LLM calls, returns fixture-based result)
uv run geode analyze "Cowboy Bebop" --dry-run

# Full run (requires API keys)
uv run geode analyze "Berserk" --verbose`}</pre>
    </DocsShell>
  );
}
