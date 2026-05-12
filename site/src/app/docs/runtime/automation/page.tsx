import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Automation (L4.5) — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/automation"
      title="Automation (L4.5 Feedback Loop)"
      summary="Drift detection, model promotion, expert panel voting. The half-layer between agent and runtime that keeps the system improving over time."
    >
      <h2>Why L4.5</h2>
      <p>
        Agents (L4) execute. Runtime (L2) provides infrastructure. L4.5 is
        the meta layer that watches outcomes and rotates the underlying
        runtime — promoting better models, deprecating drifted ones,
        collecting expert feedback.
      </p>

      <h2>Files</h2>
      <ul>
        <li><code>core/automation/model_registry.py:36</code> — <code>class PromotionStage</code> (development, staging, production)</li>
        <li><code>core/automation/feedback_loop.py</code> — phase FSM</li>
        <li><code>core/automation/drift_detector.py</code> — correlation + severity analysis</li>
        <li><code>core/automation/expert_panel.py</code> — junior/senior/principal voting tiers</li>
      </ul>

      <h2>Promotion stages</h2>
      <pre>{`development → staging → production
   ↑              ↑              │
   │              │              ▼
   └──────────────┴──── drift detected → rollback`}</pre>

      <h2>Drift detection</h2>
      <p>
        Drift severity is graded <code>low</code> /{" "}
        <code>medium</code> / <code>high</code> / <code>critical</code>.
        Critical drift on a production model triggers immediate rollback to
        the previous staging snapshot. Lower severity records a metric and
        waits for the expert panel.
      </p>

      <h2>Expert panel voting</h2>
      <p>
        When a model output is contested, a virtual expert panel (junior,
        senior, principal tiers) votes on whether the output should be
        accepted. Votes are weighted by tier and the result feeds back to
        the model registry.
      </p>

      <h2>Hook events fired</h2>
      <ul>
        <li><code>DRIFT_DETECTED</code></li>
        <li><code>MODEL_PROMOTED</code></li>
        <li><code>OUTCOME_COLLECTED</code></li>
        <li><code>EXPERT_VOTE_CAST</code></li>
        <li><code>FEEDBACK_PHASE_CHANGED</code></li>
      </ul>
    </DocsShell>
  );
}
