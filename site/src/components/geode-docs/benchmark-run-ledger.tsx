import type { BenchmarkGroup, BenchmarkMeasurement } from "@/data/geode/benchmark-measurements";

const EVAL_ARTIFACTS_REPO = "https://github.com/mangowhoiscloud/geode-eval-artifacts";

function MeasurementDetails({ run }: { run: BenchmarkMeasurement }) {
  return (
    <details id={run.id}>
      <summary>
        <strong>{run.title}</strong> · {run.measuredAt} · {run.model} · {run.source} · {run.effort}
      </summary>
      <table>
        <tbody>
          <tr><td>Status</td><td><code>{run.status}</code></td></tr>
          <tr><td>Suite/domain</td><td><code>{run.suite}</code></td></tr>
          <tr><td>Model</td><td><code>{run.model}</code></td></tr>
          <tr><td>Provider</td><td><code>{run.provider}</code></td></tr>
          <tr><td>Source</td><td><code>{run.source}</code></td></tr>
          <tr><td>Effort</td><td><code>{run.effort}</code></td></tr>
          <tr><td>Route</td><td>{run.route}</td></tr>
          <tr><td>Harness</td><td><code>{run.harness}</code></td></tr>
          <tr><td>{run.scoreLabel}</td><td><strong>{run.scoreValue}</strong></td></tr>
          <tr><td>Artifact</td><td><code>{run.artifact}</code></td></tr>
        </tbody>
      </table>
      <ul>
        {run.secondary.map((item) => <li key={item}>{item}</li>)}
      </ul>
      <pre><code>{run.command}</code></pre>
      <ul>
        {run.notes.map((note) => <li key={note}>{note}</li>)}
      </ul>
    </details>
  );
}

export function BenchmarkMatrix({ group }: { group: BenchmarkGroup }) {
  return (
    <table>
      <thead>
        <tr>
          {group.matrix.map((cell) => <th key={cell.label}>{cell.label}</th>)}
        </tr>
      </thead>
      <tbody>
        <tr>
          {group.matrix.map((cell) => (
            <td key={cell.label}>
              {cell.measurementId ? (
                <a href={`#${cell.measurementId}`}><strong>{cell.value}</strong></a>
              ) : (
                <span>{cell.value}</span>
              )}
              {cell.note ? <><br /><span className="text-[var(--ink-3)] text-xs">{cell.note}</span></> : null}
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

export function BenchmarkRunList({ group }: { group: BenchmarkGroup }) {
  return (
    <>
      {group.measurements.map((run) => <MeasurementDetails key={run.id} run={run} />)}
    </>
  );
}

export function RunLogLink({ path, label }: { path: string; label?: string }) {
  return (
    <a href={`${EVAL_ARTIFACTS_REPO}/tree/main/${path}`}>
      <code>{label ?? `geode-eval-artifacts/${path}`}</code>
    </a>
  );
}

export function EvalArtifactsRepoLink() {
  return <a href={EVAL_ARTIFACTS_REPO}>geode-eval-artifacts</a>;
}
