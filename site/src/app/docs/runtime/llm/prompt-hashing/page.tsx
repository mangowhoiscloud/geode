import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Prompt Hashing — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-hashing"
      title="Prompt Hashing"
      summary="A SHA-256 hash ratchet (Karpathy P4) that breaks CI on unintended prompt drift. 20 templates pinned, re-pin workflow documented."
    >
      <h2>The two functions</h2>
      <pre>{`# core/llm/prompts/__init__.py
def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]

# core/llm/prompts/axes.py
def _hash_axes(data) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()[:12]`}</pre>
      <p>
        Twelve hex characters = 48 bits. Collision probability is negligible
        for the closed set of 20 prompts; the goal is detection, not
        cryptographic security.
      </p>
      <p>
        The axes hash uses <code>sort_keys=True</code> to make the JSON
        serialization deterministic across YAML parser versions and Python
        dict orderings.
      </p>

      <h2>The 20 pinned entries</h2>
      <pre>{`PROMPT_VERSIONS / _PINNED_HASHES (sorted)

  AGENTIC_SUFFIX             79cef71335e8
  ANALYST_SPECIFIC           5a696a2d5ebb
  ANALYST_SYSTEM             8a325a63b397
  ANALYST_TOOLS_SUFFIX       2961fb31d96f
  ANALYST_USER               e59d00faadd5
  BIASBUSTER_SYSTEM          07987c709fd9
  BIASBUSTER_USER            378be01a6310
  COMMENTARY_SYSTEM          488d8916d958
  COMMENTARY_USER            2024ac4eba69
  CROSS_LLM_DUAL_VERIFY      602669128ae2
  CROSS_LLM_RESCORE          163b08e97d66
  CROSS_LLM_SYSTEM           bf303f600fce
  EVALUATOR_AXES             0d82eb1aa5b4
  EVALUATOR_SYSTEM           e891c0ce27d4
  EVALUATOR_USER             f6d7f955338d
  PROSPECT_EVALUATOR_AXES    a9954477497b
  ROUTER_SYSTEM              a03eef47a293
  SYNTHESIZER_SYSTEM         e01544c0c8d2
  SYNTHESIZER_TOOLS_SUFFIX   c6c65e47e191
  SYNTHESIZER_USER           30d99edc79a5`}</pre>
      <p>
        Both dictionaries have exactly 20 keys; their key sets are equal.
      </p>

      <h2>verify_prompt_integrity</h2>
      <pre>{`def verify_prompt_integrity(*, raise_on_drift: bool = False) -> list[str]:
    drifted = []
    for name, pinned in _PINNED_HASHES.items():
        if computed[name] != pinned:
            drifted.append(f"Prompt drift: {name} pin={pinned} now={computed[name]}")
    if drifted and raise_on_drift:
        raise RuntimeError(...)
    return drifted`}</pre>
      <p>
        The function is invoked by{" "}
        <code>tests/test_karpathy_prompt_hardening.py::TestPromptDriftDetection</code>{" "}
        with both <code>raise_on_drift=False</code> (returns a list, asserted
        empty) and <code>raise_on_drift=True</code> (asserts no exception).
      </p>

      <h2>Re-pin workflow</h2>
      <p>When a prompt is intentionally changed:</p>
      <ol>
        <li>Edit the <code>.md</code> file (e.g. <code>analyst.md</code>).</li>
        <li>
          Compute new hashes:
          <pre>{`uv run python -c "
from core.llm.prompts import PROMPT_VERSIONS as V
import json
print(json.dumps(dict(sorted(V.items())), indent=2))
"`}</pre>
        </li>
        <li>Update the corresponding entry in <code>_PINNED_HASHES</code>.</li>
        <li>Run <code>uv run pytest tests/test_karpathy_prompt_hardening.py</code>.</li>
        <li>Commit prompt change and pin update <strong>together</strong> in one commit.</li>
      </ol>
      <p>
        Splitting the prompt change and the pin update across two commits
        leaves a CI-broken commit in <code>git history</code>. Bisect-friendly
        commits keep the pin and the prompt in lockstep.
      </p>

      <h2>Why ratchet</h2>
      <p>
        The hash ratchet is the GEODE expression of Karpathy&apos;s P4
        principle: once a quality gate is passed, it should never silently
        regress. Prompt changes are easy to make accidentally — a
        merge-conflict resolution, an autoformatter, an IDE rename — and
        their downstream effects on model behaviour are hard to foresee. The
        ratchet forces every prompt change through a conscious step.
      </p>

      <h2>What the ratchet does not cover</h2>
      <ul>
        <li>
          <strong>Skill bodies</strong> in <code>.geode/skills/</code> are
          observed via the <code>PROMPT_ASSEMBLED</code> hook payload but not
          pinned. A prompt-injected skill change is not a CI failure.
        </li>
        <li>
          <strong>Rendered prompts</strong> (after <code>.format()</code>{" "}
          variable substitution) are not hashed. <code>hash_rendered_prompt()</code>{" "}
          exists but has no callers — see{" "}
          <em>geode-prompt-evolution P2 #3</em>.
        </li>
        <li>
          <strong>Disk integrity</strong> is not re-verified at runtime; the
          hash only fires at import time of the package.
        </li>
      </ul>
    </DocsShell>
  );
}
