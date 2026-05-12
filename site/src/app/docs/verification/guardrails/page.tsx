import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Guardrails G1-G4 — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/guardrails"
      title="Guardrails G1-G4"
      summary="Four progressive checks on LLM output. Schema, Range, Grounding, Coherence. Fail-fast, ladder-shaped."
    >
      <h2>The ladder</h2>
      <pre>{`G1 Schema      — does the JSON parse and match the type?
   ↓ pass
G2 Range       — are numeric scores in [1,5], probabilities in [0,1]?
   ↓ pass
G3 Grounding   — is each finding backed by evidence in the input?
   ↓ pass
G4 Coherence   — do the findings imply the score?
   ↓ pass
output accepted`}</pre>
      <p>
        Each gate is cheaper than the next. G1 is a Pydantic validation. G2
        is a numeric check. G3 calls a verifier LLM that re-reads the input
        and confirms each cited fact. G4 calls a verifier LLM that asks
        whether the score follows from the findings. We do not pay for G4
        if G1 already failed.
      </p>

      <h2>The verification engine</h2>
      <p>
        <code>core/verification/engine.py</code> orchestrates the ladder.
        <code>core/verification/guardrails.py</code> defines the
        <code>GuardrailType</code> enum and the per-type validators.
      </p>

      <h2>What a failure does</h2>
      <p>
        Failure fires <code>VERIFICATION_FAIL</code> hook, which the
        AgenticLoop&apos;s <code>ErrorRecoveryStrategy</code> can catch. The
        default recovery prompts the model with a structured re-ask:
      </p>
      <ul>
        <li>What rule was violated</li>
        <li>The exact failing field</li>
        <li>An expected shape (without giving the answer away)</li>
      </ul>
      <p>
        Up to N retries (configurable). Beyond that, the analyst output is
        marked <code>analyst_failed</code> and the synthesizer skips that
        contributor.
      </p>

      <h2>What guardrails do not cover</h2>
      <p>
        Guardrails check the <em>shape</em> and <em>defensibility</em> of an
        output. They do not check for bias — that is{" "}
        <a href="/geode/docs/verification/biasbuster">BiasBuster</a> — and
        they do not check the cross-LLM consistency that{" "}
        <code>cross_llm.md</code> templates provide via independent
        re-scoring.
      </p>

      <h2>Cause classification (synthesizer-locked)</h2>
      <p>
        After verification, a separate decision tree classifies the cause
        (one of six: <code>conversion_failure</code>,{" "}
        <code>undermarketed</code>, <code>discovery_failure</code>,{" "}
        <code>genre_mismatch</code>, <code>technical_debt</code>,{" "}
        <code>none</code>) and the synthesizer is forbidden from
        re-classifying — it can only narrate. This separation prevents the
        narrative from inventing a cause that contradicts the evidence.
      </p>
    </DocsShell>
  );
}
