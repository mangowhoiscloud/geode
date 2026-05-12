import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why Ratchet Discipline — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/ratchet"
      title="Why Ratchet Discipline"
      titleKo="왜 ratchet 규율인가"
      summary="20 pinned prompt hashes. 5-stage CI. The ratchet shape that prevents drift."
      summaryKo="20개 프롬프트 해시 핀. 5단계 CI. drift를 막는 ratchet 형태."
    >
      <Bi
        ko={
          <>
            <p><strong>Why:</strong> LLM 시스템은 작은 프롬프트 변경 하나가 출력 품질을 침식시킬 수 있습니다. GEODE는 이를 막기 위해 두 종류의 ratchet을 씁니다. 둘 다 단방향 잠금장치입니다.</p>

            <h2>Ratchet이란</h2>
            <p>기계의 ratchet은 한 방향으로만 돌고 반대 방향으로는 잠깁니다. 소프트웨어에서는 품질 지표를 한 방향으로만 움직이게 하는 게이트를 의미합니다. 테스트 수가 줄면 빌드 fail, 프롬프트 해시가 바뀌면 빌드 fail 같은 식.</p>

            <h2>GEODE의 두 ratchet</h2>
            <table>
              <thead><tr><th>Ratchet</th><th>잠그는 것</th><th>왜</th></tr></thead>
              <tbody>
                <tr><td><strong>Prompt hash ratchet</strong></td><td>20개 핵심 프롬프트의 해시</td><td>의도치 않은 프롬프트 변경 차단. 변경 시 명시적 재핀 commit 필요.</td></tr>
                <tr><td><strong>CI 5-stage ratchet</strong></td><td>Lint, Type, Test, Security, Docs</td><td>한 단계라도 실패하면 PR merge 금지.</td></tr>
              </tbody>
            </table>

            <h2>출처 인용</h2>
            <p>Andrej Karpathy의 <em>autoresearch</em> 프로젝트에서 정의된 ratchet discipline 패턴을 그대로 가져왔습니다. 자율 ML 실험 루프에서 모델이 자기 코드를 망가뜨리지 않도록 하는 핵심 메커니즘입니다.</p>

            <h2>왜 두 layer 모두 필요한가</h2>
            <p>출력 측 ratchet (프롬프트 해시)만 있으면 빌드 라인 측 회귀를 막을 수 없습니다. 빌드 측 ratchet (CI)만 있으면 LLM의 silent 회귀 (같은 코드 + 다른 프롬프트)를 막을 수 없습니다. 둘이 동시에 있어야 자기일치가 보장됩니다.</p>

            <p className="text-white/40 text-sm"><em>참조:</em> skills/karpathy-patterns, wiki/concepts/geode-prompt-hashing.md</p>
          </>
        }
        en={
          <>
            <p><strong>Why:</strong> in LLM systems, a small prompt edit can quietly erode output quality. GEODE prevents this with two ratchets. Both are one-way locks.</p>

            <h2>What "ratchet" means</h2>
            <p>A mechanical ratchet turns in one direction and locks the other. In software, it means a gate that allows a quality metric to move only one way. Test count decreases? Build fails. Prompt hash changes? Build fails.</p>

            <h2>GEODE's two ratchets</h2>
            <table>
              <thead><tr><th>Ratchet</th><th>What it locks</th><th>Why</th></tr></thead>
              <tbody>
                <tr><td><strong>Prompt hash ratchet</strong></td><td>Hashes of 20 core prompts.</td><td>Blocks unintended prompt edits. Changing requires an explicit re-pin commit.</td></tr>
                <tr><td><strong>CI 5-stage ratchet</strong></td><td>Lint, Type, Test, Security, Docs.</td><td>Any stage red blocks PR merge.</td></tr>
              </tbody>
            </table>

            <h2>Source</h2>
            <p>The ratchet discipline pattern is taken directly from Andrej Karpathy's <em>autoresearch</em> project, where it keeps the autonomous ML experiment loop from breaking its own code.</p>

            <h2>Why both layers are needed</h2>
            <p>Output-side ratchet alone (prompt hash) cannot catch build-line regressions. Build-side ratchet alone (CI) cannot catch silent LLM regressions (same code, different prompt). Both together guarantee self-consistency.</p>

            <p className="text-white/40 text-sm"><em>See:</em> skills/karpathy-patterns, wiki/concepts/geode-prompt-hashing.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
