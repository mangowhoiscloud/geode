import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "LangSmith — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/langsmith"
      title="LangSmith"
      summary="Opt-in tracing for the five LLM call sites in core/llm/router.py. Zero runtime cost when disabled."
    >
      <h2>Activation</h2>
      <pre>{`export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=ls_...      # or LANGSMITH_API_KEY
export LANGCHAIN_PROJECT=geode       # optional`}</pre>
      <p>
        Both the <code>LANGCHAIN_TRACING_V2=true</code> gate and an API key
        are required. Either alone disables tracing.
      </p>

      <h2>The decorator</h2>
      <pre>{`# core/llm/router.py:151-181
def is_langsmith_enabled() -> bool:
    tracing = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = (
        os.environ.get("LANGCHAIN_API_KEY")
        or os.environ.get("LANGSMITH_API_KEY")
    )
    return tracing and api_key is not None

def maybe_traceable(*, run_type="llm", name=None):
    if is_langsmith_enabled():
        from langsmith import traceable
        return traceable(run_type=run_type, name=name)
    return lambda fn: fn`}</pre>
      <p>
        When LangSmith is inactive the decorator collapses to identity —
        zero runtime cost, no import.
      </p>

      <h2>Wrapped call sites</h2>
      <table>
        <thead><tr><th>Function</th><th>run_type</th></tr></thead>
        <tbody>
          <tr><td><code>call_llm</code></td><td>llm</td></tr>
          <tr><td><code>call_llm_parsed</code></td><td>llm</td></tr>
          <tr><td><code>call_llm_json</code></td><td>llm</td></tr>
          <tr><td><code>call_llm_with_tools</code></td><td>chain</td></tr>
          <tr><td><code>call_llm_streaming</code></td><td>llm</td></tr>
        </tbody>
      </table>

      <h2>What gets traced, what does not</h2>
      <ul>
        <li><strong>Traced</strong>: model input/output messages, token usage, latency, errors.</li>
        <li><strong>Not traced</strong> (separate channel): prompt assembly metadata. The <code>PROMPT_ASSEMBLED</code> hook payload (fragment list, skill hashes, truncation events) is fired locally but does not auto-attach to the LangSmith run. Bridging is on the roadmap (<em>geode-prompt-evolution P2 #4</em>).</li>
      </ul>

      <h2>Log noise control</h2>
      <pre>{`# core/llm/router.py:141-143
logging.getLogger("langsmith").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)`}</pre>
      <p>
        LangSmith&apos;s internal 429 retry logging is escalated from{" "}
        <code>WARNING</code> to <code>ERROR</code> to keep the GEODE stdout
        clean.
      </p>
    </DocsShell>
  );
}
