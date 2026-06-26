import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why a self-hosting harness — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/self-hosting"
      title="Why a self-hosting harness"
      titleKo="왜 self-hosting 하네스인가"
      summary="The runtime that ships and the line that builds it share the same primitives. Why that test matters."
      summaryKo="출하되는 런타임과 그것을 빌드하는 라인이 같은 기본 단위를 공유합니다. 그 검증이 왜 중요한지 설명합니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE가 자율 에이전트 하네스라고 주장하려면, 그 주장이 어딘가에서
              검증되어야 합니다. 가장 강한 검증은 그 하네스가 자기 자신을 빌드할
              수 있는가입니다. self-hosting compiler 개념의 직접 이식입니다.
            </p>

            <h2>Self-hosting compiler 개념</h2>
            <p>
              컴파일러에서 self-hosting은 자기 자신을 컴파일하는 컴파일러를
              가리킵니다. Rust, Go, TypeScript가 모두 그렇습니다. 의미는
              하나입니다. 도구가 자기 소스를 감당할 만큼 견고하다는 강한
              증거입니다.
            </p>

            <h2>GEODE에서의 의미</h2>
            <p>
              GEODE 런타임이 출하되는 에이전트의 동작을 안정시키는 방식과,
              GEODE를 빌드하는 라인(scaffold, <code>CLAUDE.md</code>)이 빌드를
              안정시키는 방식이 같은 기본 단위를 공유합니다.
            </p>
            <table>
              <thead><tr><th>패턴</th><th>출하되는 런타임</th><th>그것을 빌드하는 라인</th></tr></thead>
              <tbody>
                <tr><td>해시 ratchet</td><td>프롬프트 해시 핀 (<code>core/llm/prompts/__init__.py</code>의 <code>_PINNED_HASHES</code>)</td><td>CI 게이트. lint, type, test, security + 카운트 바닥 ratchet들</td></tr>
                <tr><td>계층 메모리</td><td>5-tier ContextAssembler (<code>core/memory/context.py</code>)</td><td>다층 CLAUDE.md (프로젝트 + 사용자 메모리)</td></tr>
                <tr><td>훅</td><td>HookSystem 라이프사이클 이벤트 (<code>core/hooks/system.py</code>)</td><td>scaffold skills (트리거 키워드로 발화)</td></tr>
                <tr><td>선언적 가드레일</td><td>RUNTIME CANNOT (GEODE.md) + 6계층 PolicyChain (<code>core/tools/policy.py</code>)</td><td>CANNOT/CAN 규칙 (CLAUDE.md)</td></tr>
                <tr><td>루프 + 종료 경로</td><td>while(tool_use) + 라운드/시간/비용 가드 (<code>core/agent/loop/agent_loop.py</code>)</td><td>8단계 워크플로우 (Board → GAP → Plan → Implement → Verify → Docs → PR → Rebuild)</td></tr>
                <tr><td>선택과 되돌림</td><td>margin 게이트의 promote/revert (<code>core/self_improving/gate.py</code>)</td><td>PR 게이트. CI 실패는 머지되지 않고, 머지된 것만 main에 남음</td></tr>
              </tbody>
            </table>

            <h2>왜 중요한가</h2>
            <p>
              같은 규율이 두 스코프에서 동일하게 작동한다는 사실은 GEODE의
              설계가 비유가 아니라 운영 가능한 패턴임을 보여 줍니다. 런타임에서
              검증된 패턴은 빌드 라인으로, 빌드 라인에서 깨진 패턴은 런타임
              수정으로 되먹임됩니다. 위 표가 그 자기일치의 전부입니다.
            </p>

            <h2>한계</h2>
            <p>
              self-hosting은 GEODE가 사람 없이 자신을 빌드한다는 뜻이 아닙니다.
              빌드 라인의 PR 머지와 릴리스는 운영자 게이트를 지나고, 자기개선
	              루프가 변이하는 것은 코드가 아니라 스캐폴드(시스템 프롬프트 섹션과
	              동작 종류)입니다. 주장의 범위는 기본 단위의 공유까지입니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/explanation/ratchet">왜 ratchet 규율인가</a>. 표의 첫 행을 깊게.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">아우터 루프</a>. 표의 마지막 행을 깊게.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              For GEODE to claim it is an autonomous agent harness, the claim
              must be testable somewhere. The strongest test is whether the
              harness can build itself: a direct adaptation of the self-hosting
              compiler concept.
            </p>

            <h2>Self-hosting compilers</h2>
            <p>
              In compilers, self-hosting means a compiler that compiles itself.
              Rust, Go, and TypeScript all qualify. The meaning is singular:
              strong evidence the tool is robust enough to carry its own source.
            </p>

            <h2>What it means for GEODE</h2>
            <p>
              The way the GEODE runtime keeps the shipped agent&apos;s behavior
              stable, and the way the line that builds GEODE (the scaffold,{" "}
              <code>CLAUDE.md</code>) keeps the build stable, share the same
              primitives.
            </p>
            <table>
              <thead><tr><th>Pattern</th><th>The runtime that ships</th><th>The line that builds it</th></tr></thead>
              <tbody>
                <tr><td>Hash ratchet</td><td>Prompt hash pins (<code>_PINNED_HASHES</code> in <code>core/llm/prompts/__init__.py</code>)</td><td>CI gate: lint, type, test, security plus count-floor ratchets</td></tr>
                <tr><td>Layered memory</td><td>5-tier ContextAssembler (<code>core/memory/context.py</code>)</td><td>Multi-level CLAUDE.md (project + user memory)</td></tr>
                <tr><td>Hooks</td><td>HookSystem lifecycle events (<code>core/hooks/system.py</code>)</td><td>Scaffold skills (fired by trigger keywords)</td></tr>
                <tr><td>Declarative guardrails</td><td>RUNTIME CANNOT (GEODE.md) + 6-layer PolicyChain (<code>core/tools/policy.py</code>)</td><td>CANNOT/CAN rules (CLAUDE.md)</td></tr>
                <tr><td>Loop + termination</td><td>while(tool_use) with round/time/cost guards (<code>core/agent/loop/agent_loop.py</code>)</td><td>The 8-step workflow (Board → GAP → Plan → Implement → Verify → Docs → PR → Rebuild)</td></tr>
                <tr><td>Selection + revert</td><td>Promote/revert at the margin gate (<code>core/self_improving/gate.py</code>)</td><td>The PR gate: red CI never merges, only merged work survives on main</td></tr>
              </tbody>
            </table>

            <h2>Why it matters</h2>
            <p>
              The same discipline operating identically at two scopes shows the
              design is a workable pattern, not a metaphor. Patterns proven in
              the runtime feed the build line; patterns that break in the build
              line feed fixes back into the runtime. The table above is the
              entirety of that self-consistency.
            </p>

            <h2>Limits</h2>
            <p>
              Self-hosting does not mean GEODE builds itself unattended. PR
              merges and releases on the build line pass an operator gate, and
              what the self-improving loop mutates is the scaffold (system
              prompt sections and behaviour kinds), not the code. The claim
              extends exactly as far as shared primitives.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/explanation/ratchet">Why ratchet discipline</a>. The first row of the table, in depth.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">The outer loop</a>. The last row of the table, in depth.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
