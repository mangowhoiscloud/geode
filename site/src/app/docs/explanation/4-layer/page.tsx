import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why 4 Layers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/4-layer"
      title="Why 4 Layers"
      titleKo="왜 4-계층인가"
      summary="Model, Runtime, Harness, Agent. Where each layer's responsibility ends."
      summaryKo="Model, Runtime, Harness, Agent. 각 계층의 책임이 끝나는 지점."
    >
      <Bi
        ko={
          <>
            <p><strong>Why:</strong> Karpathy의 LLM-OS 다이어그램은 LLM을 컴퓨터의 CPU에 비유합니다. GEODE는 그 비유를 4 계층 운영체제로 구체화했습니다. 각 계층은 한 가지만 책임집니다.</p>

            <h2>4 계층</h2>
            <table>
              <thead><tr><th>계층</th><th>OS 비유</th><th>책임</th></tr></thead>
              <tbody>
                <tr><td><strong>L1 Model</strong></td><td>커널 / CPU</td><td>LLM 자체. 4 프로바이더 × 14 모델. 추론.</td></tr>
                <tr><td><strong>L2 Runtime</strong></td><td>시스템콜 + 드라이버</td><td>도구·MCP·메모리·컨텍스트. LLM이 외부와 닿는 모든 경로.</td></tr>
                <tr><td><strong>L3 Harness</strong></td><td>셸 + init</td><td>CLI·serve·hooks·gateway. 사용자/메신저가 시스템과 닿는 경로.</td></tr>
                <tr><td><strong>L4 Agent</strong></td><td>실행 루프</td><td>while(tool_use). 항상 도는 실행 단위.</td></tr>
              </tbody>
            </table>

            <h2>경계가 명확한 이유</h2>
            <p>도메인 어댑터를 교체할 때 어떤 계층이 영향받는지가 즉시 보입니다. Game IP 플러그인을 REODE 마이그레이션 에이전트로 바꿀 때 변경된 것은 어댑터(L4 위)뿐, L1-L3는 한 줄도 안 바뀌었습니다. 이 사실이 4-계층 분리가 진짜로 작동한다는 증거입니다.</p>

            <h2>왜 3개나 5개가 아닌가</h2>
            <ul>
              <li>3계층 (Model + Runtime + Agent)이면 hooks/gateway/serve가 갈 곳이 없음.</li>
              <li>5계층 (L2를 Tools / Memory로 분리)은 L2 안의 cohesion이 충분히 강해 분리 비용이 이득보다 큼.</li>
              <li>운영체제 구조와 1대1 대응이라는 점에서 4가 자연스러움.</li>
            </ul>

            <p className="text-white/40 text-sm"><em>참조:</em> portfolio §2 Primitives Mapping (13행), wiki/concepts/geode-architecture.md</p>
          </>
        }
        en={
          <>
            <p><strong>Why:</strong> Karpathy's LLM-OS diagram likens the LLM to a computer's CPU. GEODE makes that analogy concrete as a four-layer operating system. Each layer owns exactly one thing.</p>

            <h2>The four layers</h2>
            <table>
              <thead><tr><th>Layer</th><th>OS analogue</th><th>Owns</th></tr></thead>
              <tbody>
                <tr><td><strong>L1 Model</strong></td><td>Kernel / CPU</td><td>The LLM itself. 4 providers, 14 models. Inference.</td></tr>
                <tr><td><strong>L2 Runtime</strong></td><td>Syscalls + drivers</td><td>Tools, MCP, memory, context. Every path the LLM uses to touch the outside.</td></tr>
                <tr><td><strong>L3 Harness</strong></td><td>Shell + init</td><td>CLI, serve, hooks, gateway. Every path users and messengers use to reach the system.</td></tr>
                <tr><td><strong>L4 Agent</strong></td><td>Execution loop</td><td>while(tool_use). The always-running execution unit.</td></tr>
              </tbody>
            </table>

            <h2>Why the boundaries hold</h2>
            <p>When swapping a domain adapter, the layer impact is immediately visible. When the Game IP plugin was replaced by the REODE migration agent, only the adapter above L4 changed. L1-L3 stayed identical. That fact is the proof that the 4-layer split is real, not decorative.</p>

            <h2>Why not 3 or 5</h2>
            <ul>
              <li>Three layers (Model + Runtime + Agent) leaves no room for hooks, gateway, or serve.</li>
              <li>Five layers (splitting L2 into Tools and Memory) costs more than it buys: cohesion inside L2 is strong.</li>
              <li>Four matches the OS analogy 1:1, which is the natural decomposition.</li>
            </ul>

            <p className="text-white/40 text-sm"><em>See:</em> portfolio §2 Primitives Mapping (13 rows), wiki/concepts/geode-architecture.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
