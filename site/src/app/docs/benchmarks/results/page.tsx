import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { BENCHMARK_GROUPS, type BenchmarkMeasurement } from "@/data/geode/benchmark-measurements";

export const metadata = { title: "Benchmark measurements — GEODE Docs" };

function Status({ status }: { status: BenchmarkMeasurement["status"] }) {
  const label = status === "complete" ? "complete" : status;
  return <code>{label}</code>;
}

function MeasurementDetails({ run }: { run: BenchmarkMeasurement }) {
  return (
    <details id={run.id}>
      <summary>
        <strong>{run.title}</strong> · {run.measuredAt} · {run.model} · {run.source} · {run.effort}
      </summary>
      <table>
        <tbody>
          <tr><td>Status</td><td><Status status={run.status} /></td></tr>
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

function Groups() {
  return (
    <>
      {BENCHMARK_GROUPS.map((group) => (
        <section key={group.id}>
          <h2>{group.title}</h2>
          <p>{group.summary}</p>
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
          <h3>Run list</h3>
          {group.measurements.map((run) => <MeasurementDetails key={run.id} run={run} />)}
        </section>
      ))}
    </>
  );
}

function SchemaTable() {
  return (
    <table>
      <thead>
        <tr>
          <th>Field</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr><td><code>measuredAt</code></td><td>Measurement date/time and timezone when available</td></tr>
        <tr><td><code>model</code></td><td>Exact model label used by the GEODE route</td></tr>
        <tr><td><code>provider</code></td><td>Provider adapter label, such as <code>openai-codex</code> or <code>openai</code></td></tr>
        <tr><td><code>source</code></td><td>Authentication route: <code>subscription</code>, <code>api</code>, <code>local</code>, or another explicit source</td></tr>
        <tr><td><code>effort</code></td><td>Reasoning effort or split agent/user effort</td></tr>
        <tr><td><code>route</code></td><td>Harness adapter path, for example GEODE MCPMark adapter or tau2 <code>geode_agent</code> + <code>geode_user</code></td></tr>
        <tr><td><code>harness</code></td><td>Benchmark repository revision or package version</td></tr>
        <tr><td><code>artifact</code></td><td>Raw result path used for post-hoc audit</td></tr>
      </tbody>
    </table>
  );
}

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/results"
      title="Benchmark measurements"
      titleKo="Benchmark measurements"
      summary="Grouped GEODE benchmark measurement ledger for MCPMark and Tau2, with clickable run records and model-route metadata."
      summaryKo="MCPMark와 Tau2를 그룹으로 묶은 GEODE benchmark 실측 ledger입니다. 각 run은 클릭해서 model route metadata와 산출물을 확인합니다."
    >
      <Bi
        ko={
          <>
            <p>
              이 페이지는 benchmark를 길게 나열하지 않고 <code>MCPMark</code>와{" "}
              <code>Tau2</code> 그룹 아래에 모든 실측 run을 쌓는 표준 ledger입니다.
              각 run은 측정 시기, model, provider, source, effort, route,
              harness revision, artifact path를 같은 규격으로 기록합니다.
            </p>
            <h2>Run record schema</h2>
            <SchemaTable />
            <Groups />
          </>
        }
        en={
          <>
            <p>
              This page avoids a long flat benchmark list. It groups every
              measured run under <code>MCPMark</code> or <code>Tau2</code> and
              records the measured time, model, provider, source, effort, route,
              harness revision, and artifact path with one schema.
            </p>
            <h2>Run Record Schema</h2>
            <SchemaTable />
            <Groups />
          </>
        }
      />
    </DocsShell>
  );
}
