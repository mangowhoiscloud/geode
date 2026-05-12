import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Vault — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/memory/vault"
      title="Vault"
      summary="Where the agent puts its work. Reports, research, application drafts — not memory, but artifacts."
    >
      <h2>Memory vs Vault</h2>
      <p>
        The 5-tier <a href="/geode/docs/runtime/memory/5-tier">memory system</a>{" "}
        holds context the agent <em>reads</em> on every turn. The vault
        holds artifacts the agent <em>produced</em>. They have separate
        lifecycles:
      </p>
      <table>
        <thead><tr><th>Aspect</th><th>Memory</th><th>Vault</th></tr></thead>
        <tbody>
          <tr><td>Read on every turn?</td><td>Yes (via ContextAssembler)</td><td>No</td></tr>
          <tr><td>Format</td><td>Compressed summaries</td><td>Full artifacts (markdown, PDFs, ...)</td></tr>
          <tr><td>Size budget</td><td>Tight (4K chars warning)</td><td>Disk-only, no in-context budget</td></tr>
          <tr><td>Auto-classified</td><td>By tier</td><td>By <code>classify_artifact()</code> purpose</td></tr>
        </tbody>
      </table>

      <h2>Routes</h2>
      <p>
        <code>classify_artifact()</code> reads the artifact metadata
        (filename, tags, content sniffing) and routes to one of:
      </p>
      <ul>
        <li><code>~/.geode/vault/profile/</code> — about the user (resume drafts, learning notes)</li>
        <li><code>~/.geode/vault/research/</code> — produced research (briefs, comparisons)</li>
        <li><code>~/.geode/vault/applications/</code> — drafts for external use (cover letters, proposals)</li>
        <li><code>~/.geode/vault/general/</code> — anything else</li>
      </ul>

      <h2>Why a separate location</h2>
      <p>
        Mixing artifacts into memory makes the LLM context pull in
        full-document content on every turn — a budget killer. Mixing
        memory into the vault makes it hard to find the user&apos;s actual
        work products amongst micro-summaries. Separation lets each follow
        its own retention policy.
      </p>

      <h2>Open question</h2>
      <p>
        Should vault artifacts be auto-indexed for semantic search? Today
        retrieval is path-based (the user knows what they made and where).
        At ~100+ artifacts the manual path approach starts to break down,
        and a vector index becomes useful. Threshold not yet hit.
      </p>
    </DocsShell>
  );
}
