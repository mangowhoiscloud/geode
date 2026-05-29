import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why a Self-Hosting Harness — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/self-hosting"
      title="Why a Self-Hosting Harness"
      titleKo="왜 self-hosting 하네스인가"
      summary="The runtime and the build line share primitives. Why that mattered."
      summaryKo="런타임과 빌드 라인이 같은 기본 단위를 공유하는 이유."
    >
      <Bi
        ko={
          <>
            <p><strong>Why:</strong> GEODE가 운영체제급 자율 에이전트 하네스라고 주장하려면, 그 주장이 어딘가에서 검증돼야 합니다. 가장 강한 검증은 <em>그 하네스가 자기 자신을 빌드할 수 있는가</em>입니다. self-hosting compiler 개념의 직접 이식입니다.</p>

            <h2>Self-hosting compiler 개념</h2>
            <p>컴파일러 분야에서 self-hosting은 자기 자신을 컴파일하는 컴파일러를 가리킵니다. Rust·Go·TypeScript 모두 self-hosting입니다. 의미: 컴파일러 코드를 그 컴파일러 자체로 빌드할 수 있다 → 도구가 충분히 견고하다는 강한 증거.</p>

            <h2>GEODE에서의 의미</h2>
            <p>GEODE가 출시되는 자율 에이전트의 출력 안정성을 보장하는 방식과, GEODE를 빌드하는 라인(scaffold)이 빌드 안정성을 보장하는 방식이 <em>같은 기본 단위</em>를 공유합니다.</p>

            <table>
              <thead><tr><th>패턴</th><th>Artifact (출시되는 OS)</th><th>Line (그것을 빌드하는 라인)</th></tr></thead>
              <tbody>
                <tr><td>Hash ratchet</td><td>프롬프트 해시 핀</td><td>CI 5단계 게이트</td></tr>
                <tr><td>Layered memory</td><td>5계층 ContextAssembler</td><td>4계층 CLAUDE.md (managed → user → project → local)</td></tr>
                <tr><td>Hooks</td><td>runtime 이벤트</td><td>scaffold skills</td></tr>
                <tr><td>Declarative guardrails</td><td>G1-G4 verification</td><td>CANNOT/CAN 규칙</td></tr>
                <tr><td>Loop + termination</td><td>while(tool_use), 50 라운드 cap, 종료 경로</td><td>8-Step workflow</td></tr>
              </tbody>
            </table>

            <h2>왜 중요한가</h2>
            <p>같은 규율이 두 스코프에서 동일하게 작동한다는 사실은 GEODE의 설계가 <em>비유적 추상화</em>가 아니라 <em>실제 운영 가능한 패턴</em>임을 보여줍니다. 위 표 하나가 그 자기일치의 전부입니다.</p>

            <h2>비교: 다른 에이전트 시스템</h2>
            <ul>
              <li>Claude Code, Cursor, Aider: 사용자 도구. 자기 자신을 빌드하지는 않음.</li>
              <li>GEODE: 자기 자신을 빌드하는 첫 LLM 에이전트 하네스 (확인된 범위 내).</li>
            </ul>

            <p className="text-white/40 text-sm"><em>참조:</em> portfolio §3 Recursion + wiki/concepts/geode-scaffold-production.md</p>
          </>
        }
        en={
          <>
            <p><strong>Why:</strong> for GEODE to claim it is an OS-grade autonomous agent harness, the claim must be testable somewhere. The strongest test is whether the harness can build itself. This is a direct adaptation of the self-hosting compiler concept.</p>

            <h2>Self-hosting compilers</h2>
            <p>In compilers, self-hosting means a compiler that compiles itself. Rust, Go, and TypeScript are all self-hosting. The meaning: the compiler's source code can be built by the compiler itself, which is strong evidence the tool is robust enough.</p>

            <h2>What it means for GEODE</h2>
            <p>The way GEODE keeps the shipped autonomous agent's output stable, and the way the line that builds GEODE keeps the build stable, share <em>the same primitives</em>.</p>

            <table>
              <thead><tr><th>Pattern</th><th>Artifact (the OS that ships)</th><th>Line (the line that builds it)</th></tr></thead>
              <tbody>
                <tr><td>Hash ratchet</td><td>prompt-hash pins</td><td>5-stage CI gate</td></tr>
                <tr><td>Layered memory</td><td>5-tier ContextAssembler</td><td>4-tier CLAUDE.md (managed → user → project → local)</td></tr>
                <tr><td>Hooks</td><td>runtime events</td><td>scaffold skills</td></tr>
                <tr><td>Declarative guardrails</td><td>G1-G4 verification</td><td>CANNOT/CAN rules</td></tr>
                <tr><td>Loop + termination</td><td>while(tool_use), 50-round cap, termination paths</td><td>8-step workflow</td></tr>
              </tbody>
            </table>

            <h2>Why it matters</h2>
            <p>The fact that the same discipline operates identically at two scopes shows GEODE's design is not a <em>metaphor</em> but a <em>workable pattern</em>. A single table is the entirety of that self-consistency.</p>

            <h2>Compared to other agent systems</h2>
            <ul>
              <li>Claude Code, Cursor, Aider: user tools. None builds itself.</li>
              <li>GEODE: the first LLM agent harness that builds itself (within the scope checked).</li>
            </ul>

            <p className="text-white/40 text-sm"><em>See:</em> portfolio §3 Recursion plus wiki/concepts/geode-scaffold-production.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
