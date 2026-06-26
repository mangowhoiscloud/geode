import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why five layers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/4-layer"
      title="Why five layers"
      titleKo="왜 5계층인가"
      summary="Model, Runtime, Harness, Agent, Self-Improving. Where each boundary falls, and why the fifth layer became explicit."
      summaryKo="Model, Runtime, Harness, Agent, Self-Improving. 경계가 어디에 있고, 다섯 번째 계층이 왜 명시적이 되었는지 설명합니다."
    >
      <Bi
        ko={
          <>
            <p>
              Karpathy의 LLM-OS 비유는 LLM을 컴퓨터의 CPU 자리에 둡니다. GEODE는 그
              비유를 운영체제처럼 계층화했고, 지금의 답은 다섯입니다. 각 계층은
              한 가지만 책임집니다.
            </p>

            <h2>다섯 계층</h2>
            <table>
              <thead><tr><th>계층</th><th>OS 비유</th><th>책임</th><th>대표 코드</th></tr></thead>
              <tbody>
                <tr><td><strong>Model</strong></td><td>커널 / CPU</td><td>LLM 자체. 프로바이더 라우팅과 추론</td><td><code>core/llm/providers/</code>, <code>core/llm/router/</code></td></tr>
                <tr><td><strong>Runtime</strong></td><td>시스템콜 + 드라이버</td><td>도구, MCP, 메모리, 스킬. LLM이 외부와 닿는 모든 경로</td><td><code>core/tools/</code>, <code>core/mcp/</code>, <code>core/memory/</code></td></tr>
                <tr><td><strong>Harness</strong></td><td>셸 + init</td><td>CLI, serve, 훅, 게이트웨이, 레인. 사용자와 메신저가 시스템에 닿는 경로</td><td><code>core/cli/</code>, <code>core/server/</code>, <code>core/hooks/</code>, <code>core/orchestration/</code></td></tr>
                <tr><td><strong>Agent</strong></td><td>실행 루프</td><td>while(tool_use). 항상 도는 실행 단위와 서브에이전트</td><td><code>core/agent/loop/</code>, <code>core/agent/sub_agent.py</code></td></tr>
                <tr><td><strong>Self-Improving</strong></td><td>패키지 매니저 + 업데이트 채널</td><td>에이전트가 도는 스캐폴드 자체를 변이하고, 감사로 선택하고, 계보를 보존</td><td><code>core/self_improving/</code></td></tr>
              </tbody>
            </table>

            <h2>왜 다섯 번째 계층이 명시적이 되었나</h2>
            <p>
              S-5 구조 스프린트(v0.99.163) 전까지 GEODE는 4계층으로 서술됐고,
              자기개선 코드는 다이어그램에 자리가 없었습니다. 코드 인구조사
              결과는 반대였습니다. 자기개선 모듈의 절반가량이 4계층 어디에도
              매핑되지 않았습니다. 코드가 아니라 다이어그램이 틀렸던 것입니다.
            </p>
            <p>
              경계의 근거는 의존 방향입니다. 자기개선 계층은 Agent 계층을 측정
              대상으로 호출하지만(감사 서브프로세스가 같은 AgenticLoop를 돌림),
              Agent 계층은 자기개선 계층을 모릅니다. 주입은{" "}
              <code>GEODE_WRAPPER_OVERRIDE</code> 환경 변수와 SoT 파일이라는
              좁은 인터페이스 하나로만 일어납니다
              (<code>core/agent/system_prompt.py</code>가 소비자). 한 방향으로만
              의존하고 인터페이스가 좁으면, 그것은 같은 계층이 아니라 위
              계층입니다.
            </p>
            <p>
              경계는 변경 비용으로도 강제됩니다. <code>program.md</code> 계약상
              자기개선 에이전트는 측정 모듈 4개(<code>measure.py</code>,{" "}
              <code>fitness.py</code>, <code>gate.py</code>,{" "}
              <code>ledger.py</code>)를 수정할 수 없습니다. 측정 장비를 바꾸면
              측정 대상이 아니라 자가 기준이 바뀌기 때문입니다. 이 불변 조건은
              계층이 분리되어 있어야만 선언할 수 있습니다.
            </p>

            <h2>왜 3, 4, 6이 아닌가</h2>
            <ul>
              <li>3계층(Model + Runtime + Agent)이면 훅, 게이트웨이, serve, 레인이 갈 곳이 없습니다.</li>
              <li>4계층은 자기개선 코드를 숨깁니다. 위에 쓴 대로 실측이 반증했습니다.</li>
              <li>6계층(예: Runtime을 Tools와 Memory로 분리)은 그 사이 응집이 강해 분리 비용이 이득을 넘습니다. 도구 결과가 곧 컨텍스트가 되는 구조에서 둘은 함께 움직입니다.</li>
            </ul>

            <h2>경계가 진짜라는 증거</h2>
            <p>
              경계가 장식이 아니라면 교체 실험이 통과해야 합니다. 모델 교체
              (<code>/model</code>)는 Model 계층만 바꿉니다. 메신저 추가는
              Harness의 폴러 하나를 추가합니다. 스캐폴드 변이가 reject되면
              Self-Improving 계층의 되돌림이 SoT를 복원할 뿐, 아래 계층 코드는
              건드리지 않습니다. 세 실험 모두 현재 코드에서 단일 계층
              변경입니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">5계층 스택</a>. 각 계층의 내용물.</li>
              <li><a href="/geode/docs/develop/architecture">아키텍처 심화</a>. 계층을 가로지르는 데이터 흐름.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">아우터 루프</a>. 다섯 번째 계층이 실제로 하는 일.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Karpathy&apos;s LLM-OS analogy puts the LLM where a computer puts
              its CPU. GEODE layers the analogy like an operating system, and
              the current answer is five. Each layer owns exactly one thing.
            </p>

            <h2>The five layers</h2>
            <table>
              <thead><tr><th>Layer</th><th>OS analogue</th><th>Owns</th><th>Representative code</th></tr></thead>
              <tbody>
                <tr><td><strong>Model</strong></td><td>Kernel / CPU</td><td>The LLM itself: provider routing and inference</td><td><code>core/llm/providers/</code>, <code>core/llm/router/</code></td></tr>
                <tr><td><strong>Runtime</strong></td><td>Syscalls + drivers</td><td>Tools, MCP, memory, skills: every path the LLM uses to touch the outside</td><td><code>core/tools/</code>, <code>core/mcp/</code>, <code>core/memory/</code></td></tr>
                <tr><td><strong>Harness</strong></td><td>Shell + init</td><td>CLI, serve, hooks, gateway, lanes: every path users and messengers use to reach the system</td><td><code>core/cli/</code>, <code>core/server/</code>, <code>core/hooks/</code>, <code>core/orchestration/</code></td></tr>
                <tr><td><strong>Agent</strong></td><td>Execution loop</td><td>while(tool_use): the always-running execution unit and sub-agents</td><td><code>core/agent/loop/</code>, <code>core/agent/sub_agent.py</code></td></tr>
                <tr><td><strong>Self-Improving</strong></td><td>Package manager + update channel</td><td>Mutates the scaffold the agent runs on, selects via audits, preserves lineage</td><td><code>core/self_improving/</code></td></tr>
              </tbody>
            </table>

            <h2>Why the fifth layer became explicit</h2>
            <p>
              Until the S-5 structure sprint (v0.99.163), GEODE described itself
              as four layers, and the self-improving code had no place in the
              diagram. A code census said otherwise: roughly half of the
              self-improving modules mapped to none of the four layers. The
              diagram was wrong, not the code.
            </p>
            <p>
              The boundary&apos;s justification is dependency direction. The
              self-improving layer invokes the Agent layer as its measurement
              subject (the audit subprocess runs the same AgenticLoop), but the
              Agent layer knows nothing about the self-improving layer.
              Injection happens through exactly one narrow interface: the{" "}
              <code>GEODE_WRAPPER_OVERRIDE</code> environment variable and an
              SoT file, consumed by <code>core/agent/system_prompt.py</code>.
              One-way dependency plus a narrow interface means a layer above,
              not a sibling.
            </p>
            <p>
              The boundary is also enforced by change cost. By the{" "}
              <code>program.md</code> contract, the self-improving agent must
              not modify the four measurement modules
              (<code>measure.py</code>, <code>fitness.py</code>,{" "}
              <code>gate.py</code>, <code>ledger.py</code>): changing the
              measurement gear changes the yardstick, not the system under
              test. That invariant is only declarable because the layer is
              separate.
            </p>

            <h2>Why not 3, 4, or 6</h2>
            <ul>
              <li>Three layers (Model + Runtime + Agent) leave no room for hooks, gateway, serve, or lanes.</li>
              <li>Four layers hide the self-improving code; the census above falsified that shape.</li>
              <li>Six layers (say, splitting Runtime into Tools and Memory) cost more than they buy: tool results become context, so the two move together.</li>
            </ul>

            <h2>Evidence the boundaries are real</h2>
            <p>
              If a boundary is more than decoration, swap experiments must pass.
              Switching models (<code>/model</code>) touches only the Model
              layer. Adding a messenger adds one poller in the Harness. A
              rejected scaffold mutation triggers a revert in the Self-Improving
              layer that restores the SoT without touching code in the layers
              below. All three are single-layer changes in the current tree.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">The five-layer stack</a>. What each layer contains.</li>
              <li><a href="/geode/docs/develop/architecture">Architecture deep-dive</a>. Data flows across the layers.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">The outer loop</a>. What the fifth layer actually does.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
