import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "BiasBuster — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/biasbuster"
      title="BiasBuster"
      summary="Six bias detectors run against the analyst panel before the synthesizer. overall_pass=true requires all six false."
    >
      <h2>The six biases</h2>
      <table>
        <thead><tr><th>Bias</th><th>Trigger</th></tr></thead>
        <tbody>
          <tr><td>Confirmation</td><td>All analysts trend in the same direction without sufficient signal divergence</td></tr>
          <tr><td>Recency</td><td>Most recent signal weighted &gt; 50% of the score</td></tr>
          <tr><td>Anchoring</td><td>CV (coefficient of variation) &lt; 0.05 across 4+ analysts</td></tr>
          <tr><td>Position</td><td>First/last evaluator score deviates &gt; 1 std from the rest</td></tr>
          <tr><td>Verbosity</td><td>Score correlates with evidence-paragraph length (threshold tunable per domain)</td></tr>
          <tr><td>Self-enhancement</td><td>Evaluator scores its own previous output favourably</td></tr>
        </tbody>
      </table>

      <h2>The decision rule</h2>
      <p>
        <code>overall_pass = all(flag is False for flag in [confirmation, recency, anchoring, position, verbosity, self_enhancement])</code>
      </p>
      <p>
        Any single bias flagged sends the panel back through a re-scoring
        round with the flagged bias surfaced as a constraint to the
        evaluator prompt.
      </p>

      <h2>The prompt</h2>
      <p>
        <code>core/llm/prompts/biasbuster.md</code> holds the system + user
        templates. They are pinned in <code>_PINNED_HASHES</code> as{" "}
        <code>BIASBUSTER_SYSTEM</code> and <code>BIASBUSTER_USER</code>.
      </p>

      <h2>Why a separate stage</h2>
      <p>
        The evaluators are scored individually and BiasBuster is the only
        step that sees the <em>panel</em>. The 6 detectors are population-
        level statistics on the analyst scores, not individual-output
        checks. Putting them in a separate stage lets the evaluators stay
        oblivious to each other (good for independence) while still getting
        the cross-evaluator sanity check.
      </p>

      <h2>Tunable thresholds</h2>
      <p>
        Numeric thresholds (CV &lt; 0.05, r &gt; 0.7) live in{" "}
        <code>plugins/game_ip/config/evaluator_axes.yaml</code> for the
        Game IP plugin. Other domains define their own.
      </p>
    </DocsShell>
  );
}
