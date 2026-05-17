import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Orchestration — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/orchestration"
      title="Orchestration"
      titleKo="오케스트레이션"
      summary="LangGraph StateGraph composition. Pipelines, conditional edges, Send API parallelism, reducers."
      summaryKo="LangGraph StateGraph 조합. 파이프라인, conditional edge, Send API 병렬화, reducer."
    >
      <Bi
        ko={
          <>
            <h2>이 계층이 담당하는 것</h2>
            <p>
              agentic 루프가 일반적인 while-tool-use 기본 단위라면, 오케스트레이션은 도메인 특화
              파이프라인을 위한 구조화된 그래프 계층입니다. 외부 도메인 플러그인의 분석,
              멀티 에이전트 검증, 병렬 fan-out 모두 이곳에서 StateGraph로 연결됩니다.
            </p>

            <h2>파일</h2>
            <ul>
              <li><code>core/orchestration/</code>. 17개 모듈</li>
              <li><code>core/graph.py</code>. 최상위 StateGraph 빌더 진입점</li>
              <li><code>core/state.py</code>. <code>GeodeState</code> TypedDict (모든 노드가 받는 상태 형상)</li>
            </ul>

            <h2>파이프라인 형태</h2>
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
Evaluator → Verify → Synthesizer
    │
    ▼
Output`}</pre>

            <h2>Send API 병렬화</h2>
            <p>
              LangGraph의 <code>Send</code> 기본 단위는 단일 노드가 격리된 상태로 여러 병렬
              브랜치를 dispatch할 수 있게 해 줍니다. GEODE는 이를 analyst fan-out (플러그인
              파이프라인의 analyst 병렬 실행)에 사용합니다.
            </p>

            <h2>Conditional edge</h2>
            <p>
              라우팅 결정은 노드가 아니라 엣지 위에 있습니다. <code>verification</code> 노드는
              통과 시 <code>synthesizer</code>로 진행하고, 실패 시 해당 analyst로 되돌아갑니다.
            </p>

            <h2>Reducer</h2>
            <p>
              병렬 브랜치에 걸쳐 누적되는 state 필드 (analyst 결과, error 로그)는 reducer를 통해
              병합됩니다. 이전 값과 새 값을 받아 결합된 값을 반환하는 타입화된 함수입니다.
              <code>core/state.py</code>가 필드별 reducer 타입을 선언합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>What this layer owns</h2>
            <p>
              Where the agentic loop is a generic while-tool-use primitive,
              orchestration is the structured graph layer for domain-specific
              pipelines. External domain analysis, multi-agent verification,
              and parallel fan-out all connect here as StateGraphs.
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
Evaluator → Verify → Synthesizer
    │
    ▼
Output`}</pre>

            <h2>Send API parallelism</h2>
            <p>
              LangGraph&apos;s <code>Send</code> primitive lets a single node
              dispatch multiple parallel branches with isolated state. GEODE uses
              it for analyst fan-out in external plugin pipelines.
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
          </>
        }
      />
    </DocsShell>
  );
}
