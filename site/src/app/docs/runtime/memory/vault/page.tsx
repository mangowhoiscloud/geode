import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Vault — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/memory/vault"
      title="Vault"
      titleKo="Vault"
      summary="Where the agent puts its work. Reports, research, application drafts — not memory, but artifacts."
      summaryKo="에이전트가 작업물을 두는 곳. 리포트, 리서치, 지원 초안. 메모리가 아니라 산출물입니다."
    >
      <Bi
        ko={
          <>
            <h2>Memory와 Vault</h2>
            <p>
              5계층 <a href="/geode/docs/runtime/memory/5-tier">메모리 시스템</a>은
              에이전트가 매 턴 <em>읽는</em> 컨텍스트를 담습니다. Vault는 에이전트가{" "}
              <em>생산한</em> 산출물을 담습니다. 둘은 별개의 라이프사이클을 가집니다.
            </p>
            <table>
              <thead><tr><th>측면</th><th>Memory</th><th>Vault</th></tr></thead>
              <tbody>
                <tr><td>매 턴 읽는가?</td><td>예 (ContextAssembler를 통해)</td><td>아니오</td></tr>
                <tr><td>형식</td><td>압축 요약</td><td>전체 산출물 (markdown, PDF 등)</td></tr>
                <tr><td>크기 예산</td><td>타이트 (4K chars warning)</td><td>디스크 전용, 인컨텍스트 예산 없음</td></tr>
                <tr><td>자동 분류</td><td>티어별로</td><td><code>classify_artifact()</code>가 목적별로</td></tr>
              </tbody>
            </table>

            <h2>경로</h2>
            <p>
              <code>classify_artifact()</code>는 산출물 메타데이터 (파일명, 태그,
              내용 sniffing)를 읽고 다음 중 하나로 라우팅합니다.
            </p>
            <ul>
              <li><code>~/.geode/vault/profile/</code>. 사용자에 관한 것 (이력서 초안, 학습 노트).</li>
              <li><code>~/.geode/vault/research/</code>. 생산된 리서치 (브리프, 비교 자료).</li>
              <li><code>~/.geode/vault/applications/</code>. 외부용 초안 (커버레터, 제안서).</li>
              <li><code>~/.geode/vault/general/</code>. 그 외 모든 것.</li>
            </ul>

            <h2>왜 위치를 분리하는가</h2>
            <p>
              산출물을 메모리에 섞으면 LLM 컨텍스트가 매 턴 전체 문서 내용을 끌어
              오게 됩니다. 예산 살인범입니다. 메모리를 vault에 섞으면 마이크로
              요약 더미에서 사용자의 실제 결과물을 찾기 어렵습니다. 분리하면 각자
              자기 보존 정책을 따를 수 있습니다.
            </p>

            <h2>열린 질문</h2>
            <p>
              vault 산출물을 시맨틱 검색용으로 자동 인덱싱해야 할까요? 현재 검색은
              경로 기반입니다 (사용자는 자기가 무엇을 어디에 만들었는지 압니다).
              산출물이 100개를 넘어서면 수동 경로 방식이 무너지기 시작하고 벡터
              인덱스가 유용해집니다. 임계치는 아직 도달하지 않았습니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Memory vs Vault</h2>
            <p>
              The 5-tier <a href="/geode/docs/runtime/memory/5-tier">memory system</a>{" "}
              holds context the agent <em>reads</em> on every turn. The vault
              holds artifacts the agent <em>produced</em>. They have separate
              lifecycles:
            </p>
            <table>
              <thead><tr><th>Aspect</th><th>Memory</th><th>Vault</th></tr></thead>
              <tbody>
                <tr><td>Read on every turn?</td><td>Yes (via ContextAssembler)</td><td>No</td></tr>
                <tr><td>Format</td><td>Compressed summaries</td><td>Full artifacts (markdown, PDFs, ...)</td></tr>
                <tr><td>Size budget</td><td>Tight (4K chars warning)</td><td>Disk-only, no in-context budget</td></tr>
                <tr><td>Auto-classified</td><td>By tier</td><td>By <code>classify_artifact()</code> purpose</td></tr>
              </tbody>
            </table>

            <h2>Routes</h2>
            <p>
              <code>classify_artifact()</code> reads the artifact metadata
              (filename, tags, content sniffing) and routes to one of:
            </p>
            <ul>
              <li><code>~/.geode/vault/profile/</code> — about the user (resume drafts, learning notes)</li>
              <li><code>~/.geode/vault/research/</code> — produced research (briefs, comparisons)</li>
              <li><code>~/.geode/vault/applications/</code> — drafts for external use (cover letters, proposals)</li>
              <li><code>~/.geode/vault/general/</code> — anything else</li>
            </ul>

            <h2>Why a separate location</h2>
            <p>
              Mixing artifacts into memory makes the LLM context pull in
              full-document content on every turn — a budget killer. Mixing
              memory into the vault makes it hard to find the user&apos;s actual
              work products amongst micro-summaries. Separation lets each follow
              its own retention policy.
            </p>

            <h2>Open question</h2>
            <p>
              Should vault artifacts be auto-indexed for semantic search? Today
              retrieval is path-based (the user knows what they made and where).
              At ~100+ artifacts the manual path approach starts to break down,
              and a vector index becomes useful. Threshold not yet hit.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
