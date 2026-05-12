import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Orchestration — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/orchestration"
      title="Orchestration"
      summary="LangGraph StateGraph composition. Pipelines, conditional edges, Send API parallelism, reducers."
    >
      <h2>What this layer owns</h2>
      <p>
        Where the agentic loop is a generic while-tool-use primitive,
        orchestration is the structured graph layer for domain-specific
        pipelines. Game IP analysis, multi-agent verification, parallel
        analyst fan-out — these all live as StateGraphs here.
      </p>

      <h2>Files</h2>
      <ul>
        <li><code>core/orchestration/</code> — 17 modules</li>
        <li><code>core/graph.py</code> — top-level StateGraph builder entry</li>
        <li><code>core/state.py</code> — <code>GeodeState</code> TypedDict (the state shape every node receives)</li>
      </ul>

      <h2>Pipeline shape</h2>
      <pre>{`User input
    │
    ▼
Router (decompose)
    │
    ▼
[ Send API parallel fan-out ]
    │
    ├─► Analyst × N (parallel, identical state)
    │
    ▼
[ Reducer merge results ]
    │
    ▼
Evaluator → BiasBuster → Synthesizer
    │
    ▼
Output`}</pre>

      <h2>Send API parallelism</h2>
      <p>
        LangGraph&apos;s <code>Send</code> primitive lets a single node
        dispatch multiple parallel branches with isolated state. GEODE uses
        it for the analyst fan-out (4 parallel game-IP analysts in the
        plugin pipeline).
      </p>

      <h2>Conditional edges</h2>
      <p>
        Routing decisions sit on edges, not in nodes. The <code>verification</code> node
        either advances to <code>synthesizer</code> on pass or loops back
        to the failing analyst on fail.
      </p>

      <h2>Reducers</h2>
      <p>
        State fields that accumulate across parallel branches (analyst
        findings, error logs) are merged via reducers — typed functions
        that take the previous value and the new value and return the
        combined value. <code>core/state.py</code> declares per-field
        reducer types.
      </p>
    </DocsShell>
  );
}
