import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why a Solo Author — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/solo"
      title="Why a Solo Author"
      titleKo="왜 단독 저자인가"
      summary="What ratchet-driven release lets one person hold together. Trade-offs."
      summaryKo="ratchet-driven release가 한 명이 끌고 갈 수 있게 해주는 것. 트레이드오프."
    >
      <Bi
        ko={
          <>
            <p><strong>Why:</strong> GEODE는 한 명이 14개월 동안 빌드한 결과입니다. 이게 가능한 이유와 그 한계를 정리합니다.</p>

            <h2>가능한 이유</h2>
            <ol>
              <li><strong>Ratchet driven release</strong>: 매번 push할 때 5단계 CI + 프롬프트 해시 ratchet이 잡습니다. 무회귀가 보장되니 다음 릴리스에 집중할 수 있습니다.</li>
              <li><strong>스캐폴드가 빌드 동반자 역할</strong>: Claude Code + 41개 scaffold skills가 review·refactor·docs sync를 도와줍니다. 사람 동료 없이도 두 번째 시선이 있습니다.</li>
              <li><strong>4-계층 분리</strong>: 도메인 추가가 어댑터 1개 추가로 끝나므로, 새 도메인을 위해 코어를 손대지 않습니다.</li>
              <li><strong>Self-hosting</strong>: 같은 패턴이 두 스코프에 적용되므로 머릿속에 들고 있어야 할 패턴 수가 적습니다.</li>
            </ol>

            <h2>트레이드오프</h2>
            <table>
              <thead><tr><th>잃은 것</th><th>이유</th></tr></thead>
              <tbody>
                <tr><td>병렬 개발 속도</td><td>한 명이라 동시에 한 가지만 진행.</td></tr>
                <tr><td>도메인 깊이</td><td>각 도메인 전문가 부재. Game IP·Migration 두 사례로 일반화 가능성만 검증.</td></tr>
                <tr><td>외부 신뢰 신호</td><td>대규모 사용자 베이스 없음. ratchet과 self-hosting이 그 대체.</td></tr>
                <tr><td>긴급 대응</td><td>혼자라 on-call 부담. 그래서 자동화·관측에 투자.</td></tr>
              </tbody>
            </table>

            <h2>적합한 사용 시나리오</h2>
            <ul>
              <li>한 명 또는 소수가 운영하는 자율 에이전트 시스템</li>
              <li>도메인 추가 빈도는 낮고 깊이는 깊은 경우</li>
              <li>외부 인용 가능한 ratchet · self-hosting 패턴을 채택하고 싶은 경우</li>
            </ul>

            <p className="text-white/40 text-sm"><em>참조:</em> portfolio Hero + wiki/concepts/geode-scaffold-production.md</p>
          </>
        }
        en={
          <>
            <p><strong>Why:</strong> GEODE was built by one person over 14 months. This page explains how that is possible and where the limits are.</p>

            <h2>What makes it possible</h2>
            <ol>
              <li><strong>Ratchet-driven release</strong>: every push runs a 5-stage CI plus the prompt-hash ratchet. With no-regression guaranteed, focus can move to the next release.</li>
              <li><strong>Scaffold as build partner</strong>: Claude Code plus 41 scaffold skills handle review, refactor, and docs sync. A second set of eyes without a second person.</li>
              <li><strong>4-layer separation</strong>: adding a domain means adding one adapter, never touching the core.</li>
              <li><strong>Self-hosting</strong>: the same pattern applies to two scopes, so the number of patterns to keep in your head stays small.</li>
            </ol>

            <h2>Trade-offs</h2>
            <table>
              <thead><tr><th>What is given up</th><th>Why</th></tr></thead>
              <tbody>
                <tr><td>Parallel velocity</td><td>One person, one thing at a time.</td></tr>
                <tr><td>Domain depth</td><td>No domain expert per area. Game IP and Migration only validate generalizability.</td></tr>
                <tr><td>External trust signals</td><td>No large user base. Ratchet and self-hosting are the substitutes.</td></tr>
                <tr><td>Incident response</td><td>Solo on-call. The compensating investment is automation and observability.</td></tr>
              </tbody>
            </table>

            <h2>Where this fits</h2>
            <ul>
              <li>Autonomous agent systems operated by one or a few people.</li>
              <li>Domains added rarely, each one deep.</li>
              <li>Teams wanting to adopt ratchet and self-hosting patterns with a citable reference.</li>
            </ul>

            <p className="text-white/40 text-sm"><em>See:</em> portfolio Hero plus wiki/concepts/geode-scaffold-production.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
