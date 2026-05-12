import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "5-Tier Context — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/memory/5-tier"
      title="5-Tier Context"
      titleKo="5계층 컨텍스트"
      summary="From raw session log to a single LLM-ready summary. Five tiers, hierarchical override, budget-aware compression."
      summaryKo="raw 세션 로그에서 LLM에 즉시 투입 가능한 단일 요약까지. 5계층, 계층 override, 예산 인식 압축."
    >
      <Bi
        ko={
          <>
            <h2>다섯 개의 계층</h2>
            <pre>{`Tier 0    GEODE.md         — agent identity + constraints (G1)
Tier 0.5  User Profile     — role, expertise, learned patterns
Tier 1    Organization     — cross-project shared data
Tier 2    Project          — .geode/memory/PROJECT.md (50 insights, LRU)
Tier 3    Session          — in-memory conversation`}</pre>
            <p>
              같은 key가 양쪽에 나타나면 아래 계층이 위 계층을 override 합니다.{" "}
              <code>ContextAssembler</code>가 가정하는 예산 분할은 대략 다음과 같습니다.
            </p>
            <ul>
              <li>SOUL (Tier 0). 10%</li>
              <li>Organization (Tier 1). 25%</li>
              <li>Project (Tier 2). 25%</li>
              <li>Session (Tier 3). 40%</li>
            </ul>

            <h2>어셈블러</h2>
            <p>
              <code>core/memory/context.py:46 class ContextAssembler</code>가
              원본 멀티 티어 상태를 가져와 단일 <code>_llm_summary</code> 문자열을
              만들고, prompt 어셈블러가 이를 어셈블리 파이프라인의 Phase 3에서{" "}
              <em>Memory Context</em>로 주입합니다.{" "}
              <a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a> 참조.
            </p>

            <h2>각 계층의 위치</h2>
            <table>
              <thead><tr><th>티어</th><th>경로</th><th>라이프사이클</th></tr></thead>
              <tbody>
                <tr><td>0 GEODE.md</td><td>repo 루트</td><td>세션 시작 시 읽음</td></tr>
                <tr><td>0.5 User Profile</td><td><code>~/.geode/user_profile/</code></td><td>auto-learn 훅으로 갱신</td></tr>
                <tr><td>1 Organization</td><td><code>~/.geode/organization/</code></td><td>프로젝트 간 공유, 수동 큐레이션</td></tr>
                <tr><td>2 Project</td><td><code>.geode/memory/PROJECT.md</code></td><td>LRU 50 insight, 영속</td></tr>
                <tr><td>3 Session</td><td>인-프로세스</td><td>세션 종료 시 소실 (<code>/resume</code>으로 영속화 가능)</td></tr>
              </tbody>
            </table>

            <h2>양방향 학습 (G3 슬롯)</h2>
            <p>
              <strong>교정</strong> ("X를 하지 마") 과 <strong>검증</strong>
              ("그래, X가 맞았어") 가 모두 기록됩니다.{" "}
              <code>~/.geode/user_profile/learned.md</code>가 단일 출처입니다.
              auto-learn 훅이 사용자 피드백을 감시하고 Claude Code 메모리 시스템과
              동일한 형식으로 append 합니다.
            </p>

            <h2>Vault. 에이전트 산출물</h2>
            <p>
              세션 동안 에이전트가 생산한 리포트, 리서치 노트, 지원서 초안은
              메모리 티어가 아니라 <em>vault</em>로 들어갑니다.{" "}
              <code>classify_artifact()</code>가 용도에 따라 라우팅합니다.
            </p>
            <ul>
              <li><code>profile/</code>. 사용자에 관한 것</li>
              <li><code>research/</code>. 생산된 리서치</li>
              <li><code>applications/</code>. 초안 (이력서, 자기소개서)</li>
              <li><code>general/</code>. 그 외 모든 것</li>
            </ul>

            <h2>열린 질문</h2>
            <p>
              200줄짜리 PROJECT.md 대비 RAG가 필요한 시점은 언제인가? 오늘 프로젝트
              티어는 in-context에 충분히 작게 들어옵니다. 임계점은 500-1000 insight
              어딘가이며, 그 지점에서 LRU 절단이 유용한 상태를 잃기 시작하고
              벡터 스토어가 복잡도 비용을 정당화할 수 있게 됩니다.
            </p>
          </>
        }
        en={
          <>
            <h2>The five tiers</h2>
            <pre>{`Tier 0    GEODE.md         — agent identity + constraints (G1)
Tier 0.5  User Profile     — role, expertise, learned patterns
Tier 1    Organization     — cross-project shared data
Tier 2    Project          — .geode/memory/PROJECT.md (50 insights, LRU)
Tier 3    Session          — in-memory conversation`}</pre>
            <p>
              Lower tiers override higher when the same key appears in both. The
              budget split assumed by <code>ContextAssembler</code> is approximately:
            </p>
            <ul>
              <li>SOUL (Tier 0): 10%</li>
              <li>Organization (Tier 1): 25%</li>
              <li>Project (Tier 2): 25%</li>
              <li>Session (Tier 3): 40%</li>
            </ul>

            <h2>The assembler</h2>
            <p>
              <code>core/memory/context.py:46 class ContextAssembler</code> takes
              the raw multi-tier state and produces a single{" "}
              <code>_llm_summary</code> string that the prompt assembler injects
              as <em>Memory Context</em> in Phase 3 of the assembly pipeline. See{" "}
              <a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a>.
            </p>

            <h2>Where each tier lives</h2>
            <table>
              <thead><tr><th>Tier</th><th>Path</th><th>Lifecycle</th></tr></thead>
              <tbody>
                <tr><td>0 GEODE.md</td><td>Repo root</td><td>Read at session start</td></tr>
                <tr><td>0.5 User Profile</td><td><code>~/.geode/user_profile/</code></td><td>Updated by auto-learn hook</td></tr>
                <tr><td>1 Organization</td><td><code>~/.geode/organization/</code></td><td>Cross-project, manually curated</td></tr>
                <tr><td>2 Project</td><td><code>.geode/memory/PROJECT.md</code></td><td>LRU 50 insights, persisted</td></tr>
                <tr><td>3 Session</td><td>In-process</td><td>Lost on session end (or persisted via <code>/resume</code>)</td></tr>
              </tbody>
            </table>

            <h2>Bidirectional learning (G3 slot)</h2>
            <p>
              Both <strong>corrections</strong> ("don&apos;t do X") and{" "}
              <strong>validations</strong> ("yes, X was right") are recorded.{" "}
              <code>~/.geode/user_profile/learned.md</code> is the single source.
              Auto-learn hooks watch user feedback and append in the same format
              used by Claude Code&apos;s memory system.
            </p>

            <h2>Vault — agent artifacts</h2>
            <p>
              Reports, research notes, application drafts the agent produces
              during a session land in the <em>vault</em>, not in the memory
              tiers. <code>classify_artifact()</code> routes by purpose:
            </p>
            <ul>
              <li><code>profile/</code> — about the user</li>
              <li><code>research/</code> — produced research</li>
              <li><code>applications/</code> — drafts (resumes, cover letters)</li>
              <li><code>general/</code> — anything else</li>
            </ul>

            <h2>Open question</h2>
            <p>
              When does RAG become necessary versus a 200-line PROJECT.md? Today
              the project tier is small enough to fit in-context. The threshold
              is somewhere around 500-1000 insights, at which point the LRU
              truncation starts losing useful state and a vector store becomes
              worth the complexity.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
