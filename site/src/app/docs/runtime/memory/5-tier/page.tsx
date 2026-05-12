import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "5-Tier Context — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/memory/5-tier"
      title="5-Tier Context"
      summary="From raw session log to a single LLM-ready summary. Five tiers, hierarchical override, budget-aware compression."
    >
      <h2>The five tiers</h2>
      <pre>{`Tier 0    GEODE.md         — agent identity + constraints (G1)
Tier 0.5  User Profile     — role, expertise, learned patterns
Tier 1    Organization     — cross-project shared data
Tier 2    Project          — .geode/memory/PROJECT.md (50 insights, LRU)
Tier 3    Session          — in-memory conversation`}</pre>
      <p>
        Lower tiers override higher when the same key appears in both. The
        budget split assumed by <code>ContextAssembler</code> is approximately:
      </p>
      <ul>
        <li>SOUL (Tier 0): 10%</li>
        <li>Organization (Tier 1): 25%</li>
        <li>Project (Tier 2): 25%</li>
        <li>Session (Tier 3): 40%</li>
      </ul>

      <h2>The assembler</h2>
      <p>
        <code>core/memory/context.py:46 class ContextAssembler</code> takes
        the raw multi-tier state and produces a single{" "}
        <code>_llm_summary</code> string that the prompt assembler injects
        as <em>Memory Context</em> in Phase 3 of the assembly pipeline. See{" "}
        <a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a>.
      </p>

      <h2>Where each tier lives</h2>
      <table>
        <thead><tr><th>Tier</th><th>Path</th><th>Lifecycle</th></tr></thead>
        <tbody>
          <tr><td>0 GEODE.md</td><td>Repo root</td><td>Read at session start</td></tr>
          <tr><td>0.5 User Profile</td><td><code>~/.geode/user_profile/</code></td><td>Updated by auto-learn hook</td></tr>
          <tr><td>1 Organization</td><td><code>~/.geode/organization/</code></td><td>Cross-project, manually curated</td></tr>
          <tr><td>2 Project</td><td><code>.geode/memory/PROJECT.md</code></td><td>LRU 50 insights, persisted</td></tr>
          <tr><td>3 Session</td><td>In-process</td><td>Lost on session end (or persisted via <code>/resume</code>)</td></tr>
        </tbody>
      </table>

      <h2>Bidirectional learning (G3 slot)</h2>
      <p>
        Both <strong>corrections</strong> ("don&apos;t do X") and{" "}
        <strong>validations</strong> ("yes, X was right") are recorded.{" "}
        <code>~/.geode/user_profile/learned.md</code> is the single source.
        Auto-learn hooks watch user feedback and append in the same format
        used by Claude Code&apos;s memory system.
      </p>

      <h2>Vault — agent artifacts</h2>
      <p>
        Reports, research notes, application drafts the agent produces
        during a session land in the <em>vault</em>, not in the memory
        tiers. <code>classify_artifact()</code> routes by purpose:
      </p>
      <ul>
        <li><code>profile/</code> — about the user</li>
        <li><code>research/</code> — produced research</li>
        <li><code>applications/</code> — drafts (resumes, cover letters)</li>
        <li><code>general/</code> — anything else</li>
      </ul>

      <h2>Open question</h2>
      <p>
        When does RAG become necessary versus a 200-line PROJECT.md? Today
        the project tier is small enough to fit in-context. The threshold
        is somewhere around 500-1000 insights, at which point the LRU
        truncation starts losing useful state and a vector store becomes
        worth the complexity.
      </p>
    </DocsShell>
  );
}
