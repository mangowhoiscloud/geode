import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "LangSmith (removed) — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/langsmith"
      title="LangSmith (removed v0.89.0)"
      titleKo="LangSmith (v0.89.0에서 제거됨)"
      summary="LangSmith integration was removed in v0.89.0. Use hooks plus RunLog plus Petri audit instead."
      summaryKo="LangSmith 통합은 v0.89.0에서 제거되었습니다. hook + RunLog + Petri audit으로 대체됩니다."
    >
      <Bi
        ko={
          <>
            <div style={{ padding: "12px 16px", border: "1px solid #E89B5740", background: "#E89B5710", borderRadius: 6, marginBottom: 24 }}>
              <strong>Deprecated:</strong> 이 페이지는 history 보존용입니다. GEODE v0.89.0에서 LangSmith 의존성과 트레이싱 모듈이
              완전 제거되었습니다. 현재 관측은 <a href="/docs/ops/observability">hooks + RunLog + Petri audit</a> 3-layer로 수행합니다.
            </div>

            <h2>왜 제거되었나</h2>
            <ul>
              <li>외부 SaaS 의존성 제거 (provider lock-in 방지).</li>
              <li>관측 데이터를 GEODE 내부에서 직접 보유하려는 방향 (RunLog).</li>
              <li>LangSmith 트레이싱은 import-time cost가 컸음. cold-start lazy loading arc (v0.85~v0.89)와 충돌.</li>
            </ul>

            <h2>대체 경로</h2>
            <table>
              <thead><tr><th>이전 (LangSmith)</th><th>현재 (GEODE 자체)</th></tr></thead>
              <tbody>
                <tr><td>LLM 호출 trace</td><td><a href="/docs/harness/hooks"><code>LLM_CALL_START</code>·<code>LLM_CALL_END</code> hook</a></td></tr>
                <tr><td>도구 호출 trace</td><td><code>TOOL_EXEC_START</code>·<code>TOOL_EXEC_END</code> hook</td></tr>
                <tr><td>run 단위 시각화</td><td><code>~/.geode/runlog/</code> JSONL + inspect viewer</td></tr>
                <tr><td>외부 dashboard</td><td>(없음) wiki/blog에서 자체 분석</td></tr>
                <tr><td>alignment audit</td><td><a href="/docs/petri/overview">Petri × GEODE</a> (Anthropic Alignment Science framework)</td></tr>
              </tbody>
            </table>

            <h2>관련 출처</h2>
            <ul>
              <li>v0.89.0 CHANGELOG: "LangSmith 100% 제거"</li>
              <li>현 관측 stack: <a href="/docs/ops/observability">Observability</a></li>
              <li>Petri 통합: <a href="/docs/petri/overview">Petri × GEODE Integration</a></li>
            </ul>
          </>
        }
        en={
          <>
            <div style={{ padding: "12px 16px", border: "1px solid #E89B5740", background: "#E89B5710", borderRadius: 6, marginBottom: 24 }}>
              <strong>Deprecated:</strong> this page exists for historical context. GEODE v0.89.0 removed the LangSmith
              dependency and tracing module entirely. Current observability uses the
              <a href="/docs/ops/observability"> hooks + RunLog + Petri audit </a> three-layer stack instead.
            </div>

            <h2>Why we removed it</h2>
            <ul>
              <li>Drop external SaaS dependency (avoid provider lock-in).</li>
              <li>Keep observability data inside GEODE itself (RunLog).</li>
              <li>LangSmith tracing had a noticeable import-time cost, which conflicted with the cold-start lazy-loading
                arc across v0.85 to v0.89.</li>
            </ul>

            <h2>Replacement path</h2>
            <table>
              <thead><tr><th>Before (LangSmith)</th><th>After (GEODE-native)</th></tr></thead>
              <tbody>
                <tr><td>LLM call trace</td><td><a href="/docs/harness/hooks"><code>LLM_CALL_START</code> / <code>LLM_CALL_END</code> hooks</a></td></tr>
                <tr><td>Tool call trace</td><td><code>TOOL_EXEC_START</code> / <code>TOOL_EXEC_END</code> hooks</td></tr>
                <tr><td>Per-run visualization</td><td><code>~/.geode/runlog/</code> JSONL plus inspect viewer</td></tr>
                <tr><td>External dashboard</td><td>(none) self-analysis via wiki / blog</td></tr>
                <tr><td>Alignment audit</td><td><a href="/docs/petri/overview">Petri × GEODE</a> (Anthropic Alignment Science framework)</td></tr>
              </tbody>
            </table>

            <h2>Related sources</h2>
            <ul>
              <li>v0.89.0 CHANGELOG: "LangSmith 100% removed".</li>
              <li>Current observability stack: <a href="/docs/ops/observability">Observability</a>.</li>
              <li>Petri integration: <a href="/docs/petri/overview">Petri × GEODE Integration</a>.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
