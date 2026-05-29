import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Architecture deep-dive — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="develop/architecture"
      title="Architecture deep-dive"
      titleKo="아키텍처 심화"
      summary="The subsystem map and a recommended reading order, retold as data-flow traces."
      summaryKo="서브시스템 지도와 추천 읽기 순서를 데이터 흐름 추적으로 풀어냅니다."
    >
      <Bi
        ko={
          <>
            <h2>이 페이지의 쓰임</h2>
            <p>
              이 페이지는 코드베이스에 처음 들어오는 사람을 위한 지도입니다. 모든
              서브시스템을 파일 경로와 함께 평면으로 나열한{" "}
              <a href="/geode/docs/architecture/system-index">시스템 색인</a>과는
              다릅니다. 색인은 카탈로그입니다. 이 페이지는 경로입니다. 무엇부터
              읽을지, 그리고 코드가 실제로 어떻게 흐르는지 보여 줍니다. 카탈로그가
              필요하면 색인으로 가세요.
            </p>

            <h2>서브시스템 지도</h2>
            <p>
              프로덕션 코드는 두 패키지로 나뉩니다. <code>core/</code>는 일반 목적의
              자율 에이전트 런타임이고, <code>plugins/</code>는 1차 보조 플러그인입니다.
              <code>core/</code> 안의 서브시스템은 4-계층 스택에 맞춰 정렬됩니다.
            </p>
            <pre>{`Agent     core/agent/        while(tool_use) 루프
Harness   core/cli/          thin CLI + serve 데몬 + IPC
          core/hooks/        라이프사이클 이벤트
          core/wiring/       부트스트랩 주입
          core/ui/           터미널 렌더
Runtime   core/llm/          프롬프트 조립 + 프로바이더 라우터
          core/tools/        도구 레지스트리 + 지연 로딩
          core/mcp/          MCP 서버 오케스트레이션
          core/memory/       다계층 컨텍스트
          core/skills/       스킬 디스커버리
          core/orchestration/ StateGraph 파이프라인
          core/scheduler/    예약 작업
          core/verification/ 가드레일 + cross-LLM
          core/integrations/ 메신저 게이트웨이
          core/automation/   드리프트 감지 + 모델 프로모션
          core/self_improving_loop/ 아우터 루프 설정
          core/audit/        Petri 감사 연결
          core/observability/ runlog + 진단
Model     core/llm/providers/ Anthropic / OpenAI / Codex / GLM 어댑터`}</pre>
            <p>
              최상위에는 진입 모듈 몇 개가 있습니다. <code>core/runtime.py</code>의{" "}
              <code>GeodeRuntime</code>이 부트스트랩이고, <code>core/state.py</code>는
              모든 파이프라인 노드가 받는 상태 형상을 선언하며,{" "}
              <code>core/paths.py</code>는 모든 디렉터리 경로를 한곳에서 해석합니다.
              계층 경계가 왜 이렇게 그어졌는지는{" "}
              <a href="/geode/docs/explanation/4-layer">왜 4-계층인가</a>에 있습니다.
            </p>

            <h2>추천 읽기 순서</h2>
            <p>
              코드베이스가 처음이라면 다음 순서가 가장 적은 되돌아감으로 전체 그림을
              줍니다. 멘탈 모델부터 잡고, 안쪽 루프, 그 다음 런타임의 횡단 관심사,
              마지막으로 아우터 루프로 내려갑니다.
            </p>
            <ol>
              <li><a href="/geode/docs/concepts/two-loops">두 개의 루프</a>. 나머지 문서가 기대는 멘탈 모델입니다. 여기서 시작하세요.</li>
              <li><a href="/geode/docs/architecture/overview">4-계층 스택</a>. 각 계층이 무엇을 맡고 책임이 어디서 끝나는지.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>. while(tool_use) 기본 단위와 한 턴이 끝나는 경로들.</li>
              <li><a href="/geode/docs/runtime/context">컨텍스트 조립</a>. 매 LLM 호출의 컨텍스트가 만들어지는 곳.</li>
              <li><a href="/geode/docs/runtime/orchestration">서브에이전트 오케스트레이션</a>. 격리된 병렬 레인과 완료 시 병합.</li>
              <li><a href="/geode/docs/harness/hooks">훅과 관측성</a>. 한 이벤트 위에 쌓이는 observe와 act.</li>
              <li><a href="/geode/docs/capabilities/autoresearch">폐루프</a>. 변형, 감사, 귀속, 승격으로 이어지는 아우터 루프.</li>
            </ol>
            <p>
              운영과 설정이 목적이라면 대신{" "}
              <a href="/geode/docs/config/basics">설정 기초</a>와{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>로
              가세요.
            </p>

            <h2>흐름 추적 하나. CLI 작업</h2>
            <p>
              요청 하나가 코드를 어떻게 지나는지 따라가면 지도가 살아 움직입니다.
              먼저 평범한 CLI 작업입니다.
            </p>
            <pre>{`geode "<작업>"  (thin CLI, core/cli/)
   │  Unix 소켓 IPC
   ▼
GeodeRuntime  (core/runtime.py)  ── core/wiring/ 가 컨텍스트 주입
   ▼
AgenticLoop  (core/agent/loop/agent_loop.py)
   ▼  매 턴마다
컨텍스트 조립  (core/memory/ + core/llm/prompts/)
   ▼
LLM 호출  (core/llm/ 라우터 → core/llm/providers/)
   ▼
도구 호출?  ── 예 → core/tools/ 실행 → 결과 관찰 → 루프
   │
   └ 아니오 → 답변`}</pre>
            <p>
              thin CLI는 직접 일하지 않습니다. IPC로 <code>geode serve</code> 데몬에
              붙고, 데몬 안의 단일 <code>GeodeRuntime</code>이 작업을 실행합니다. 매
              턴마다 메모리 계층과 프롬프트 레이어가 토큰 예산 안에서 컨텍스트로
              합쳐지고, 라우터가 프로바이더를 고르고, 모델이 도구를 요청하면{" "}
              <code>core/tools/</code>가 실행합니다. 끝나는 경로는{" "}
              <a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>에
              자세히 있습니다.
            </p>

            <h2>흐름 추적 둘. 자기개선 실행</h2>
            <p>
              아우터 루프는 같은 코어를 다른 입구로 지납니다.
            </p>
            <pre>{`예약 트리거  (core/scheduler/)
   ▼
정책 변형  (core/self_improving_loop/ 설정 로드)
   ▼
Petri 감사  (core/audit/ → plugins/petri_audit)
   │  같은 AgenticLoop를 측정 대상으로 실행
   ▼
결과 귀속  (차원 점수 → fitness)
   ▼
승격 또는 되돌림  (게이트 통과 시에만 SoT 갱신)`}</pre>
            <p>
              핵심은 두 루프가 코드를 공유하지 않고 기록을 주고받는다는 점입니다.
              감사는 안쪽 루프와 같은 <code>AgenticLoop</code>를 측정 대상으로 돌립니다.
              결과가 게이트를 통과해야만 정식 결과로 승격되고, 실패하면 변형 전으로
              되돌립니다. 전체 흐름은{" "}
              <a href="/geode/docs/capabilities/autoresearch">폐루프</a>에 있고, 측정
              프레임워크는 <a href="/geode/docs/petri/overview">Petri × GEODE</a>에
              있습니다.
            </p>

            <h2>더 깊이</h2>
            <ul>
              <li><a href="/geode/docs/architecture/system-index">시스템 색인</a>. 모든 서브시스템과 파일 경로의 평면 카탈로그.</li>
              <li><a href="/geode/docs/explanation/4-layer">왜 4-계층인가</a>. 경계가 그 자리에 있는 이유.</li>
              <li><a href="/geode/docs/explanation/self-hosting">왜 self-hosting 하네스인가</a>. 런타임과 빌드 라인이 기본 단위를 공유하는 이유.</li>
              <li><a href="/geode/docs/explanation/ratchet">왜 ratchet 규율인가</a>. drift를 막는 형태.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>What this page is for</h2>
            <p>
              This page is a map for someone arriving at the codebase for the
              first time. It is not the{" "}
              <a href="/geode/docs/architecture/system-index">System index</a>,
              which lists every subsystem flat with its file path. The index is a
              catalog. This page is a path. It shows what to read first, and how
              the code actually flows. When you want the catalog, go to the index.
            </p>

            <h2>Subsystem map</h2>
            <p>
              Production code splits into two packages. <code>core/</code> is the
              general-purpose autonomous agent runtime, and <code>plugins/</code>{" "}
              holds first-party auxiliary plugins. The subsystems inside{" "}
              <code>core/</code> line up with the 4-layer stack.
            </p>
            <pre>{`Agent     core/agent/        the while(tool_use) loop
Harness   core/cli/          thin CLI + serve daemon + IPC
          core/hooks/        lifecycle events
          core/wiring/       bootstrap injection
          core/ui/           terminal rendering
Runtime   core/llm/          prompt assembly + provider router
          core/tools/        tool registry + deferred loading
          core/mcp/          MCP server orchestration
          core/memory/       multi-tier context
          core/skills/       skill discovery
          core/orchestration/ StateGraph pipelines
          core/scheduler/    scheduled tasks
          core/verification/ guardrails + cross-LLM
          core/integrations/ messaging gateway
          core/automation/   drift detection + model promotion
          core/self_improving_loop/ outer-loop configuration
          core/audit/        Petri audit wiring
          core/observability/ runlog + diagnostics
Model     core/llm/providers/ Anthropic / OpenAI / Codex / GLM adapters`}</pre>
            <p>
              A few entry modules sit at the top level. <code>GeodeRuntime</code>{" "}
              in <code>core/runtime.py</code> is the bootstrap,{" "}
              <code>core/state.py</code> declares the state shape every pipeline
              node receives, and <code>core/paths.py</code> resolves every
              directory path in one place. For why the layer boundaries fall where
              they do, see{" "}
              <a href="/geode/docs/explanation/4-layer">Why four layers</a>.
            </p>

            <h2>Recommended reading order</h2>
            <p>
              New to the codebase, this order gives the whole picture with the
              least backtracking. Fix the mental model first, then the inner loop,
              then the runtime's cross-cutting machinery, and finally down into
              the outer loop.
            </p>
            <ol>
              <li><a href="/geode/docs/concepts/two-loops">The two loops</a>. The mental model the rest of the docs build on. Start here.</li>
              <li><a href="/geode/docs/architecture/overview">The 4-layer stack</a>. What each layer owns and where its responsibility ends.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>. The while(tool_use) primitive and the paths that end a turn.</li>
              <li><a href="/geode/docs/runtime/context">Context assembly</a>. Where each LLM call's context is built.</li>
              <li><a href="/geode/docs/runtime/orchestration">Sub-agent orchestration</a>. Isolated parallel lanes and merge on completion.</li>
              <li><a href="/geode/docs/harness/hooks">Hooks and observability</a>. How observe and act stack on one event.</li>
              <li><a href="/geode/docs/capabilities/autoresearch">The closed loop</a>. The outer loop through mutate, audit, attribute, promote.</li>
            </ol>
            <p>
              If operating and configuring is the goal, go instead to{" "}
              <a href="/geode/docs/config/basics">Configuration basics</a> and{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>.
            </p>

            <h2>Trace one. A CLI task</h2>
            <p>
              The map comes alive when you follow one request through the code.
              Start with an ordinary CLI task.
            </p>
            <pre>{`geode "<task>"  (thin CLI, core/cli/)
   │  Unix socket IPC
   ▼
GeodeRuntime  (core/runtime.py)  ── core/wiring/ injects context
   ▼
AgenticLoop  (core/agent/loop/agent_loop.py)
   ▼  each turn
context assembly  (core/memory/ + core/llm/prompts/)
   ▼
LLM call  (core/llm/ router → core/llm/providers/)
   ▼
tool calls?  ── yes → run core/tools/ → observe result → loop
   │
   └ no → answer`}</pre>
            <p>
              The thin CLI does no work itself. It connects over IPC to the{" "}
              <code>geode serve</code> daemon, and the single{" "}
              <code>GeodeRuntime</code> inside the daemon runs the task. Each turn,
              the memory tiers and prompt layers merge into a context under a token
              budget, the router picks a provider, and when the model requests a
              tool, <code>core/tools/</code> runs it. The paths that end a turn are
              detailed in{" "}
              <a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>.
            </p>

            <h2>Trace two. A self-improving run</h2>
            <p>
              The outer loop passes through the same core by a different entrance.
            </p>
            <pre>{`scheduled trigger  (core/scheduler/)
   ▼
mutate a policy  (core/self_improving_loop/ loads config)
   ▼
Petri audit  (core/audit/ → plugins/petri_audit)
   │  runs the same AgenticLoop as the thing being measured
   ▼
attribute the result  (dimension scores → fitness)
   ▼
promote or revert  (SoT updates only when the gate passes)`}</pre>
            <p>
              The point is that the two loops share no code, only a record. The
              audit runs the same <code>AgenticLoop</code> as the inner loop, this
              time as the thing being measured. A result is promoted to the canonical
              result only when it passes the gate, and reverts to the pre-mutation
              state when it does not. The full flow is in{" "}
              <a href="/geode/docs/capabilities/autoresearch">The closed loop</a>,
              and the measurement framework is in{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>.
            </p>

            <h2>Going deeper</h2>
            <ul>
              <li><a href="/geode/docs/architecture/system-index">System index</a>. The flat catalog of every subsystem with its file path.</li>
              <li><a href="/geode/docs/explanation/4-layer">Why four layers</a>. Why the boundaries fall where they do.</li>
              <li><a href="/geode/docs/explanation/self-hosting">Why a self-hosting harness</a>. Why the runtime and the build line share primitives.</li>
              <li><a href="/geode/docs/explanation/ratchet">Why ratchet discipline</a>. The shape that prevents drift.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
