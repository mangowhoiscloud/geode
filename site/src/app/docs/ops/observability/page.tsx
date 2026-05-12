import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Observability — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/observability"
      title="Observability"
      titleKo="관측성"
      summary="Hooks, RunLog, Petri audits. Three lenses, one runtime."
      summaryKo="훅, RunLog, Petri 감사. 세 가지 렌즈, 하나의 런타임."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE를 운영할 때 사용하는 3개의 관측 렌즈를 정리합니다.</p>

            <h2>3 렌즈</h2>
            <table>
              <thead><tr><th>렌즈</th><th>대상</th><th>위치</th></tr></thead>
              <tbody>
                <tr><td><strong>Hooks (58 events)</strong></td><td>실시간 lifecycle 이벤트. 도구 호출·LLM 콜·세션 시작/종료 등.</td><td><a href="/docs/harness/hooks">Hook System</a></td></tr>
                <tr><td><strong>RunLog</strong></td><td>run 단위 trace. agent 추론·tool call·결과를 시계열로 보관.</td><td><code>~/.geode/runlog/</code></td></tr>
                <tr><td><strong>Petri Audit</strong></td><td>misalignment risk. 38 dimension × N seeds 격자 점수.</td><td><a href="/docs/petri/overview">Petri Integration</a></td></tr>
              </tbody>
            </table>

            <h2>어떤 렌즈를 언제 쓰나</h2>
            <ul>
              <li><strong>"왜 이 도구가 호출됐지?"</strong> → Hooks + RunLog</li>
              <li><strong>"비용이 어디서 나갔지?"</strong> → Hook <code>LLM_CALL_END</code> 집계</li>
              <li><strong>"이 에이전트가 안전한가?"</strong> → Petri audit</li>
            </ul>

            <h2>외부 시각화</h2>
            <p>현재 GEODE는 LangSmith를 옵션으로 지원합니다 (v0.89+ 이후 기본 비활성). 자체 관측이 우선.</p>

            <p className="text-white/40 text-sm"><em>참조:</em> <a href="/docs/runtime/llm/langsmith">LangSmith reference</a>, <a href="/docs/petri/run">Run an Audit</a></p>
          </>
        }
        en={
          <>
            <p>This guide lists the three observability lenses available when operating GEODE.</p>

            <h2>Three lenses</h2>
            <table>
              <thead><tr><th>Lens</th><th>What it sees</th><th>Where</th></tr></thead>
              <tbody>
                <tr><td><strong>Hooks (58 events)</strong></td><td>Real-time lifecycle events: tool calls, LLM calls, session starts/ends.</td><td><a href="/docs/harness/hooks">Hook System</a></td></tr>
                <tr><td><strong>RunLog</strong></td><td>Per-run trace: agent reasoning, tool calls, results, in time order.</td><td><code>~/.geode/runlog/</code></td></tr>
                <tr><td><strong>Petri Audit</strong></td><td>Misalignment risk: 38-dim by N-seeds score grid.</td><td><a href="/docs/petri/overview">Petri Integration</a></td></tr>
              </tbody>
            </table>

            <h2>Which lens for which question</h2>
            <ul>
              <li><strong>"Why was this tool called?"</strong> → Hooks plus RunLog.</li>
              <li><strong>"Where did the cost go?"</strong> → Aggregate the <code>LLM_CALL_END</code> hook.</li>
              <li><strong>"Is this agent safe?"</strong> → Run a Petri audit.</li>
            </ul>

            <h2>External visualization</h2>
            <p>GEODE supports LangSmith as an opt-in path (default off since v0.89+). Self-instrumentation comes first.</p>

            <p className="text-white/40 text-sm"><em>See:</em> <a href="/docs/runtime/llm/langsmith">LangSmith reference</a>, <a href="/docs/petri/run">Run an Audit</a>.</p>
          </>
        }
      />
    </DocsShell>
  );
}
