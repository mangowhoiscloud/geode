import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Observability — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/observability"
      title="Observability"
      titleKo="관측성"
      summary="Hooks, RunLog, audit diagnostics, Petri audits. Four lenses, one runtime."
      summaryKo="훅, RunLog, audit diagnostics, Petri 감사. 네 가지 렌즈, 하나의 런타임."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE를 운영할 때 사용하는 4개의 관측 렌즈를 정리합니다. v0.92.0에서 <code>core.audit.diagnostics</code>가 추가되어 3개에서 4개로 확장되었습니다.</p>

            <h2>4 렌즈</h2>
            <table>
              <thead><tr><th>렌즈</th><th>대상</th><th>위치</th><th>도입</th></tr></thead>
              <tbody>
                <tr><td><strong>Hooks (58 events / 14 groups)</strong></td><td>실시간 lifecycle 이벤트. 도구 호출·LLM 콜·세션 시작/종료 등.</td><td><a href="/docs/harness/hooks">Hook System</a></td><td>core</td></tr>
                <tr><td><strong>RunLog</strong></td><td>run 단위 trace. agent 추론·tool call·결과를 시계열로 보관.</td><td><code>~/.geode/runlog/</code></td><td>core</td></tr>
                <tr><td><strong>Audit diagnostics</strong></td><td>per-call assertion. 호출별로 input/output/cost/cache 메타를 기록해 audit 재현 가능하게.</td><td><code>core.audit.diagnostics</code></td><td>v0.92.0</td></tr>
                <tr><td><strong>Petri Audit</strong></td><td>misalignment risk. 17 dim (default <code>geode_5axes</code>) 또는 38 dim (<code>--dim-set full</code>) × N seeds 격자.</td><td><a href="/docs/petri/overview">Petri Integration</a></td><td>v0.92.0+</td></tr>
              </tbody>
            </table>

            <h2>어떤 렌즈를 언제 쓰나</h2>
            <ul>
              <li><strong>"왜 이 도구가 호출됐지?"</strong> → Hooks + RunLog</li>
              <li><strong>"비용이 어디서 나갔지?"</strong> → <code>LLM_CALL_END</code> hook 집계 + <code>~/.geode/usage/*.jsonl</code> ledger</li>
              <li><strong>"이 호출이 어떻게 cache를 썼지?"</strong> → audit diagnostics (cache_read/cache_write 필드)</li>
              <li><strong>"이 에이전트가 안전한가?"</strong> → Petri audit</li>
            </ul>

            <h2>비용 ledger (v0.66+)</h2>
            <p>
              <code>~/.geode/usage/&lt;date&gt;.jsonl</code>에 LLM 호출 단위 비용/토큰/캐시 메타가 append-only로 기록됩니다.
              v0.90.0에서 token tracker dual-record 버그가 수정되어 codex/glm 50-64% duplicate 카운팅이 해소되었습니다.
            </p>
            <pre>{`$ geode history --last 24h
$ jq . ~/.geode/usage/2026-05-12.jsonl | head`}</pre>

            <h2>외부 시각화</h2>
            <p>현재 GEODE는 LangSmith 의존을 제거했습니다 (v0.89.0). 자체 관측 stack (위 4 렌즈)이 1차. 외부 dashboard 필요시 RunLog JSONL을 inspect viewer 또는 OpenTelemetry 어댑터로 export.</p>

            <p className="text-white/40 text-sm"><em>참조:</em> <a href="/docs/runtime/llm/langsmith">LangSmith (removed)</a>, <a href="/docs/petri/run">Run an Audit</a>, <a href="/docs/ops/cost">Cost Monitoring</a></p>
          </>
        }
        en={
          <>
            <p>This guide lists the four observability lenses available when operating GEODE. <code>core.audit.diagnostics</code> was added in v0.92.0, taking the stack from three lenses to four.</p>

            <h2>Four lenses</h2>
            <table>
              <thead><tr><th>Lens</th><th>What it sees</th><th>Where</th><th>Since</th></tr></thead>
              <tbody>
                <tr><td><strong>Hooks (58 events / 14 groups)</strong></td><td>Real-time lifecycle events: tool calls, LLM calls, session starts/ends.</td><td><a href="/docs/harness/hooks">Hook System</a></td><td>core</td></tr>
                <tr><td><strong>RunLog</strong></td><td>Per-run trace: agent reasoning, tool calls, results, in time order.</td><td><code>~/.geode/runlog/</code></td><td>core</td></tr>
                <tr><td><strong>Audit diagnostics</strong></td><td>Per-call assertion record: input, output, cost, cache metadata, so audits replay.</td><td><code>core.audit.diagnostics</code></td><td>v0.92.0</td></tr>
                <tr><td><strong>Petri Audit</strong></td><td>Misalignment risk. 17 dims (default <code>geode_5axes</code>) or 38 dims (<code>--dim-set full</code>) by N seeds.</td><td><a href="/docs/petri/overview">Petri Integration</a></td><td>v0.92.0+</td></tr>
              </tbody>
            </table>

            <h2>Which lens for which question</h2>
            <ul>
              <li><strong>"Why was this tool called?"</strong> → Hooks plus RunLog.</li>
              <li><strong>"Where did the cost go?"</strong> → <code>LLM_CALL_END</code> aggregate plus <code>~/.geode/usage/*.jsonl</code> ledger.</li>
              <li><strong>"How did this call use the cache?"</strong> → audit diagnostics (cache_read / cache_write fields).</li>
              <li><strong>"Is this agent safe?"</strong> → Run a Petri audit.</li>
            </ul>

            <h2>Cost ledger (v0.66+)</h2>
            <p>
              <code>~/.geode/usage/&lt;date&gt;.jsonl</code> appends per-call cost, tokens, and cache metadata.
              v0.90.0 fixed a token-tracker dual-record bug that had been over-counting codex/glm by 50-64%.
            </p>
            <pre>{`$ geode history --last 24h
$ jq . ~/.geode/usage/2026-05-12.jsonl | head`}</pre>

            <h2>External visualization</h2>
            <p>GEODE dropped the LangSmith dependency in v0.89.0. The native four-lens stack is primary. For external dashboards, export the RunLog JSONL via the inspect viewer or an OpenTelemetry adapter.</p>

            <p className="text-white/40 text-sm"><em>See:</em> <a href="/docs/runtime/llm/langsmith">LangSmith (removed)</a>, <a href="/docs/petri/run">Run an Audit</a>, <a href="/docs/ops/cost">Cost Monitoring</a>.</p>
          </>
        }
      />
    </DocsShell>
  );
}
