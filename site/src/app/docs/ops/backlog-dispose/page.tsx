import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Backlog Disposal — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/backlog-dispose"
      title="Backlog Disposal"
      titleKo="백로그 처분"
      summary="How to retire ideas without losing context. The dispose path keeps a paper trail (why dropped, what replaced it) instead of silent delete."
      summaryKo="아이디어를 잃지 않고 정리하는 경로. 조용한 삭제 대신 dispose 흔적 (왜 폐기 + 무엇이 대체) 을 남깁니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 dispose 인가</h2>
            <p>
              backlog 의 항목을 단순 삭제하면 6 개월 후 동일한 아이디어가 다시 제안될 때 "이거 검토 했었나?" 라는 정보가 사라집니다. dispose 는 항목을 active backlog 에서 빼되, "왜 폐기했는가" 와 "무엇이 대체했는가" 를 남기는 패턴.
            </p>

            <h2>3 종 dispose 결정</h2>
            <ul>
              <li><strong>obsoleted_by</strong>. 다른 PR 이 같은 문제를 다른 방식으로 해결</li>
              <li><strong>scope_reject</strong>. GEODE 의 범위 밖 (plugin / 외부 시스템 대상)</li>
              <li><strong>insufficient_value</strong>. 구현 가능하나 비용 대비 효용 부족</li>
            </ul>

            <h2>흔적 저장 위치</h2>
            <pre>{`docs/audits/_disposed/YYYY-MM-DD-<slug>.md
  ---
  disposed_at: 2026-05-18
  decision: obsoleted_by | scope_reject | insufficient_value
  replaced_by: <PR# or commit SHA>     # obsoleted_by 일 때
  evidence: <transcript link or audit>
  ---

  원안 요약 + 폐기 이유 본문`}</pre>

            <h2>관련 PR + skill</h2>
            <ul>
              <li>feature/backlog-dispose (#1270) — 본 패턴의 도입 PR</li>
              <li>`.claude/skills/codebase-audit` — dead code + dispose 결정 보조</li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm"><em>참조</em>: PR #1270, `docs/audits/_disposed/` (있는 경우).</p>
          </>
        }
        en={
          <>
            <h2>Why dispose</h2>
            <p>
              Deleting a backlog item silently loses the "did we already evaluate this?" signal. Six months later, the same idea returns, and there is no record of why it was rejected. Dispose removes the item from the active list but leaves the why and the replacement on disk.
            </p>

            <h2>Three disposal decisions</h2>
            <ul>
              <li><strong>obsoleted_by</strong>. another PR solved the same problem a different way</li>
              <li><strong>scope_reject</strong>. outside GEODE's boundary (lives in a plugin or external system)</li>
              <li><strong>insufficient_value</strong>. implementable but the cost/benefit does not justify it</li>
            </ul>

            <h2>Where the paper trail lives</h2>
            <pre>{`docs/audits/_disposed/YYYY-MM-DD-<slug>.md
  ---
  disposed_at: 2026-05-18
  decision: obsoleted_by | scope_reject | insufficient_value
  replaced_by: <PR# or commit SHA>     # for obsoleted_by
  evidence: <transcript link or audit>
  ---

  Original proposal summary + reason for disposal`}</pre>

            <h2>Related PR and skill</h2>
            <ul>
              <li>feature/backlog-dispose (#1270) introduced the pattern</li>
              <li>`.claude/skills/codebase-audit` covers dead-code + dispose decisions</li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm"><em>References</em>: PR #1270, `docs/audits/_disposed/` (when present).</p>
          </>
        }
      />
    </DocsShell>
  );
}
