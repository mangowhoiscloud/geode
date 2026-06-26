import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "The 5-layer stack — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="architecture/overview"
      title="The 5-layer stack"
      titleKo="5-계층 스택"
      summary="Model, Runtime, Harness, Agent, Self-Improving. What each layer owns, and where its responsibility ends."
      summaryKo="Model, Runtime, Harness, Agent, Self-Improving. 각 계층이 무엇을 맡고, 책임이 어디서 끝나는지 설명합니다."
    >
      <Bi
        ko={
          <>
            <figure>
              <img
                src="/geode/diagrams/five-layer-stack.svg"
                alt="The GEODE 5-layer stack: SELF-IMPROVING, AGENT, HARNESS, RUNTIME, MODEL, with the components each layer owns"
              />
              <figcaption>5-계층 스택과 각 계층이 소유한 구성 요소.</figcaption>
            </figure>
            <h2>왜 4가 아니라 5인가</h2>
            <p>
              GEODE는 오랫동안 4-계층(Model, Runtime, Harness, Agent)으로
              서술됐습니다. 그런데 자기개선 코드는 그 어디에도 깔끔하게 들어가지
              않았고, 문서 밖에 떠 있었습니다. 실제로 존재하고 별도의 책임을
              갖는 계층이라면 다이어그램에도 있어야 합니다. 그래서 지금의 공식
              스택은 5-계층입니다. 기존의 4-계층 서술은 모두 이 페이지로
              대체됩니다.
            </p>
            <p>
              진입점은 둘입니다. <code>geode</code>(Typer CLI,{" "}
              <code>core/cli</code>)와 <code>geode-mcp</code>(MCP 서버,{" "}
              <code>core/mcp_server.py</code>). 어느 쪽으로 들어와도 요청은
              아래 계층들을 같은 순서로 지납니다. 흐름 관점의 추적은{" "}
              <a href="/geode/docs/overview/how-it-runs">작업 처리 흐름</a>에
              있고, 이 페이지는 경계 관점입니다.
            </p>

            <h2>MODEL. 외부 세계와 닿는 유일한 계층</h2>
            <p>
              모델 계층만 외부 네트워크를 호출합니다. 프로바이더 구현은{" "}
              <code>core/llm/providers/</code>(anthropic, openai, codex, glm)에
              있고, 결제 경로별 어댑터(PAYG, 구독 OAuth, CLI)는{" "}
              <code>core/llm/adapters/registry.py</code>에 등록됩니다. 어떤
              모델이 어떤 프로바이더로 가는지는 라우팅 매니페스트
              (<code>core/config/routing.toml</code>)가 정하고, 호출 표면은{" "}
              <code>core/llm/router/</code>가 통일합니다.
            </p>
            <p>
              폴백 체인은 기본값이 비어 있습니다. 주 모델이 실패하면 자동으로
              다른 프로바이더로 넘어가는 대신 정직하게 실패를 돌려주고, 사용자가{" "}
              <code>/model</code>로 다음 모델을 고릅니다. 체인은{" "}
              <code>~/.geode/routing.toml</code>에서 옵트인으로 켭니다.
            </p>
            <p>
              책임의 끝: 이 계층은 &quot;모델을 호출한다&quot;까지만 압니다.
              언제, 어떤 도구와 함께, 어떤 컨텍스트로 호출할지는 위 계층의
              일입니다.
            </p>

            <h2>RUNTIME. 능력의 창고</h2>
            <p>
              런타임 계층은 에이전트가 쓸 수 있는 능력을 보관하고 제공합니다.
              네이티브 도구 정의와 레지스트리(<code>core/tools/</code>), 도구가
              많을 때 일부만 미리 싣고 나머지는 검색으로 가져오는 deferred loading,
              외부 MCP 서버 연결과 도구 발견(<code>core/mcp/manager.py</code>),
              스킬(<code>core/skills/</code>), 5-계층 메모리
              (<code>core/memory/context.py</code>, Identity부터 Session까지
              아래 계층이 위를 덮어쓰는 병합), 리포트 생성이 여기에 삽니다.
            </p>
            <p>
              책임의 끝: 런타임은 능력을 제공할 뿐, 호출 여부를 결정하지
              않습니다. 도구를 언제 부를지는 모델이, 불러도 되는지는 하네스의
              정책이 정합니다.
            </p>

            <h2>HARNESS. 규율과 관측</h2>
            <p>
              하네스 계층은 실행에 규율을 부과합니다. 동시성은 SessionLane과
              LaneQueue(<code>core/orchestration/lane_queue.py</code>)가
              맡습니다. 같은 세션 키의 요청은 직렬, 다른 키는 병렬입니다. 도구
              접근 권한은 PolicyChain(<code>core/tools/policy.py</code>)이
              프로파일부터 서브에이전트 위임까지 층층이 해석합니다. 서브 작업의
              의존성 그래프는 TaskGraph
              (<code>core/orchestration/task_system.py</code>)가 추적하고,
              라이프사이클 이벤트는 HookSystem(<code>core/hooks/system.py</code>)
              이 발행해 핸들러가 관찰, 개입, 차단할 수 있게 합니다. 핸들러는{" "}
              <code>core/wiring/bootstrap.py</code>에 등록되어야 실제로
              발화합니다.
            </p>
            <p>
              책임의 끝: 하네스는 무엇이 실행되는지에 관심이 없습니다. 어떤
              순서로, 어떤 권한으로, 얼마나 관측 가능하게 실행되는지만
              책임집니다.
            </p>

            <h2>AGENT. 결정하는 계층</h2>
            <p>
              에이전트 계층의 핵심은 단 하나의 primitive,{" "}
              <code>while stop_reason == &quot;tool_use&quot;</code>입니다.
              AgenticLoop(<code>core/agent/loop/agent_loop.py</code>)가 멀티턴
              실행을 주도하고, 프롬프트 조립과 도구 실행과 오류 복구는 아래
              계층에 위임합니다. 병렬 위임은 SubAgentManager
              (<code>core/agent/sub_agent.py</code>)가 맡고, 입구 두 갈래인
              CLIPoller(<code>core/server/ipc_server/poller.py</code>)와
              메신저 게이트웨이(<code>core/messaging/binding.py</code>)도 이
              계층에서 요청을 루프에 연결합니다.
            </p>
            <p>
              책임의 끝: 에이전트는 한 작업을 끝내는 데까지만 책임집니다. 작업을
              처리하는 시스템 자체를 고치는 일은 다음 계층의 몫입니다.
            </p>

            <h2>SELF-IMPROVING. 시스템을 고치는 계층</h2>
            <p>
              맨 위 계층은 아래 네 계층 전체를 피험자로 다룹니다. 루프 드라이버는{" "}
              <code>core/self_improving/train.py</code>입니다. 파일명은 Karpathy
              autoresearch의 3-파일 관습에서 빌린 것으로, 이 안에서 모델 훈련은
              일어나지 않습니다. 갱신 대상은 모델이 아니라 모델을 감싼 스캐폴드,
              곧 시스템 프롬프트 섹션과 behaviour kinds입니다.
            </p>
            <p>
              메커니즘은 선택입니다. 스캐폴드를 변이하고, 적대적 안전 감사
              (Petri)로 측정하고, fitness 스칼라를 margin 게이트에 통과시켜
              이긴 변이만 승격하고 나머지는 되돌립니다. 측정과 판정 장비는{" "}
              <code>measure.py</code>, <code>fitness.py</code>,{" "}
              <code>gate.py</code>, <code>ledger.py</code>에 있고, 런타임 쪽
              배선은 <code>core/self_improving/loop/</code>의 mutate, observe,
              inject 경로가 맡습니다. 전체 루프는{" "}
              <a href="/geode/docs/capabilities/autoresearch">폐루프</a>에서
              다룹니다.
            </p>
            <p>
              책임의 끝: 이 계층은 개별 작업의 답을 만들지 않습니다. 답을 만드는
              시스템의 다음 버전을 고를 뿐입니다.
            </p>

            <h2>경계가 주는 것</h2>
            <p>
              계층 경계는 변경 비용의 지도입니다. 원칙적으로 각 계층은 위 계층을
              건드리지 않고 교체할 수 있습니다.
            </p>
            <table>
              <thead>
                <tr><th>하고 싶은 것</th><th>닿는 계층</th><th>위치</th></tr>
              </thead>
              <tbody>
                <tr><td>프로바이더 추가</td><td>MODEL</td><td><code>core/llm/providers/</code> + <code>core/llm/adapters/registry.py</code></td></tr>
                <tr><td>도구 추가</td><td>RUNTIME</td><td><code>core/tools/definitions.json</code> + 핸들러</td></tr>
                <tr><td>훅 핸들러 추가</td><td>HARNESS</td><td>핸들러 작성 + <code>core/wiring/bootstrap.py</code> 등록</td></tr>
                <tr><td>루프 의미 변경</td><td>AGENT</td><td><code>core/agent/loop/agent_loop.py</code>. 드물고, 리뷰 게이트를 거칩니다.</td></tr>
                <tr><td>변이 대상 추가</td><td>SELF-IMPROVING</td><td><code>core/self_improving/loop/mutate/</code></td></tr>
              </tbody>
            </table>
            <p>
              서브시스템 전체 목록은{" "}
              <a href="/geode/docs/architecture/system-index">시스템 색인</a>,
              두 루프의 관계는{" "}
              <a href="/geode/docs/concepts/two-loops">두 개의 루프</a>에서
              이어집니다.
            </p>
          </>
        }
        en={
          <>
            <figure>
              <img
                src="/geode/diagrams/five-layer-stack.svg"
                alt="The GEODE 5-layer stack: SELF-IMPROVING, AGENT, HARNESS, RUNTIME, MODEL, with the components each layer owns"
              />
              <figcaption>The 5-layer stack and the components each layer owns.</figcaption>
            </figure>
            <h2>Why five, not four</h2>
            <p>
              GEODE was described as a 4-layer stack (Model, Runtime, Harness,
              Agent) for a long time. But the self-improving code never fit
              cleanly into any of the four; it floated outside the diagram. A
              layer that exists and carries its own responsibility belongs in
              the picture. The official stack is therefore five layers, and
              every older 4-layer description is superseded by this page.
            </p>
            <p>
              There are two entry points: <code>geode</code> (the Typer CLI,{" "}
              <code>core/cli</code>) and <code>geode-mcp</code> (the MCP
              server, <code>core/mcp_server.py</code>). Whichever door a
              request enters, it passes the layers below in the same order.{" "}
              <a href="/geode/docs/overview/how-it-runs">How GEODE runs a task</a>{" "}
              traces the flow; this page draws the boundaries.
            </p>

            <h2>MODEL. The only layer that touches the outside world</h2>
            <p>
              Only the model layer makes external network calls. Provider
              implementations live in <code>core/llm/providers/</code>{" "}
              (anthropic, openai, codex, glm); adapters for the billing paths
              (PAYG, subscription OAuth, CLI) register in{" "}
              <code>core/llm/adapters/registry.py</code>. Which model goes to
              which provider is decided by the routing manifest
              (<code>core/config/routing.toml</code>), and{" "}
              <code>core/llm/router/</code> unifies the call surface.
            </p>
            <p>
              Fallback chains ship empty by default. When the primary model
              fails, GEODE returns an honest failure instead of silently
              hopping providers, and the user picks the next model with{" "}
              <code>/model</code>. Chains are opt-in via{" "}
              <code>~/.geode/routing.toml</code>.
            </p>
            <p>
              Where its responsibility ends: this layer only knows how to call
              a model. When to call, with which tools, and with what context
              are decisions made above it.
            </p>

            <h2>RUNTIME. The capability store</h2>
            <p>
              The runtime layer stores and serves the capabilities an agent can
              use. Native tool definitions and the registry
              (<code>core/tools/</code>); deferred loading that keeps a small
              eager set and fetches the rest by search when many tools are
              available; MCP server connection and tool discovery
              (<code>core/mcp/manager.py</code>); skills
              (<code>core/skills/</code>); the 5-tier memory
              (<code>core/memory/context.py</code>, a merge from Identity down
              to Session where lower tiers override higher ones); and report
              generation.
            </p>
            <p>
              Where its responsibility ends: the runtime provides capabilities
              but never decides to invoke them. The model decides when to call
              a tool; the harness policy decides whether it may.
            </p>

            <h2>HARNESS. Discipline and observation</h2>
            <p>
              The harness layer imposes discipline on execution. Concurrency
              belongs to SessionLane and LaneQueue
              (<code>core/orchestration/lane_queue.py</code>): same session key
              runs serial, different keys run parallel. Tool access resolves
              through the PolicyChain (<code>core/tools/policy.py</code>),
              layered from profile down to sub-agent delegation. Sub-task
              dependency graphs are tracked by TaskGraph
              (<code>core/orchestration/task_system.py</code>), and lifecycle
              events are published by the HookSystem
              (<code>core/hooks/system.py</code>) so handlers can observe,
              intervene, or block. A handler only fires once it is registered
              in <code>core/wiring/bootstrap.py</code>.
            </p>
            <p>
              Where its responsibility ends: the harness does not care what
              runs. It owns the order, the permissions, and the observability
              of whatever does.
            </p>

            <h2>AGENT. The layer that decides</h2>
            <p>
              The agent layer owns one primitive:{" "}
              <code>while stop_reason == &quot;tool_use&quot;</code>.
              AgenticLoop (<code>core/agent/loop/agent_loop.py</code>) drives
              multi-turn execution and delegates prompt assembly, tool
              execution, and error recovery downward. Parallel delegation
              belongs to SubAgentManager
              (<code>core/agent/sub_agent.py</code>), and the two front doors,
              CLIPoller (<code>core/server/ipc_server/poller.py</code>) and the
              messaging gateway (<code>core/messaging/binding.py</code>),
              connect requests into the loop from this layer.
            </p>
            <p>
              Where its responsibility ends: the agent is responsible for
              finishing one task. Improving the system that runs tasks belongs
              to the layer above.
            </p>

            <h2>SELF-IMPROVING. The layer that fixes the system</h2>
            <p>
              The top layer treats the four layers below as its test subject.
              The loop driver is <code>core/self_improving/train.py</code>. The
              file name borrows Karpathy autoresearch&apos;s three-file
              convention, and no model training happens inside it. What gets
              updated is never the model but the scaffold around it: the
              system-prompt sections and the behaviour kinds.
            </p>
            <p>
              The mechanism is selection. Mutate the scaffold, measure with an
              adversarial safety audit (Petri), pass the fitness scalar through
              a margin gate, promote the mutation only when it wins, revert
              otherwise. The measurement and verdict machinery lives in{" "}
              <code>measure.py</code>, <code>fitness.py</code>,{" "}
              <code>gate.py</code>, and <code>ledger.py</code>; the runtime
              wiring is mutate, observe, and inject under{" "}
              <code>core/self_improving/loop/</code>. The full loop is covered
              in <a href="/geode/docs/capabilities/autoresearch">The closed loop</a>.
            </p>
            <p>
              Where its responsibility ends: this layer never produces the
              answer to a task. It only selects the next version of the system
              that does.
            </p>

            <h2>What the boundaries buy</h2>
            <p>
              Layer boundaries are a map of change cost. In principle each
              layer can be swapped without touching the layers above it.
            </p>
            <table>
              <thead>
                <tr><th>You want to</th><th>Layer touched</th><th>Where</th></tr>
              </thead>
              <tbody>
                <tr><td>Add a provider</td><td>MODEL</td><td><code>core/llm/providers/</code> + <code>core/llm/adapters/registry.py</code></td></tr>
                <tr><td>Add a tool</td><td>RUNTIME</td><td><code>core/tools/definitions.json</code> + a handler</td></tr>
                <tr><td>Add a hook handler</td><td>HARNESS</td><td>Write the handler + register it in <code>core/wiring/bootstrap.py</code></td></tr>
                <tr><td>Change loop semantics</td><td>AGENT</td><td><code>core/agent/loop/agent_loop.py</code>. Rare, and gated by review.</td></tr>
                <tr><td>Add a mutation target</td><td>SELF-IMPROVING</td><td><code>core/self_improving/loop/mutate/</code></td></tr>
              </tbody>
            </table>
            <p>
              For the full subsystem catalog, see the{" "}
              <a href="/geode/docs/architecture/system-index">System index</a>;
              for how the top layer relates to the rest, see{" "}
              <a href="/geode/docs/concepts/two-loops">The two loops</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
