import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Skill Registry — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/skills"
      title="Skill Registry"
      titleKo="스킬 레지스트리"
      summary="Runtime skills. Discovery, lifecycle, override."
      summaryKo="런타임 스킬. 발견, 라이프사이클, 오버라이드."
    >
      <Bi
        ko={
          <>
            <p>이 페이지는 GEODE 런타임의 SkillRegistry가 무엇이며 scaffold 측 <code>.claude/skills/</code>와 어떻게 다른지 정리합니다.</p>

            <h2>두 종류의 스킬</h2>
            <table>
              <thead><tr><th>구분</th><th>위치</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><strong>Runtime skills</strong></td><td><code>core/skills/</code></td><td>실행 중인 GEODE 에이전트가 호출하는 능력 (예: report 템플릿).</td></tr>
                <tr><td><strong>Scaffold skills</strong></td><td><code>.claude/skills/</code></td><td>GEODE를 빌드할 때 Claude Code가 사용하는 능력 (예: code review, gitflow).</td></tr>
              </tbody>
            </table>

            <h2>발견 (Discovery)</h2>
            <p>SkillRegistry는 frontmatter + markdown 본문 규약으로 스킬을 발견합니다. 5계층 우선순위:</p>
            <ul>
              <li>bundled (코드와 함께 배포)</li>
              <li>user (<code>~/.geode/skills/</code>)</li>
              <li>project (<code>./.geode/skills/</code>)</li>
              <li>org (조직 공유)</li>
              <li>session (1회용)</li>
            </ul>

            <h2>오버라이드</h2>
            <p>같은 이름의 스킬이 여러 계층에 있으면 우선순위 높은 쪽이 이깁니다 (session &gt; project &gt; user &gt; org &gt; bundled).</p>

            <h2>스킬 작성</h2>
            <p>구체 절차는 <a href="/docs/build/add-tool">도구 추가하기</a>와 동일한 패턴을 따릅니다. <code>SKILL.md</code> 파일 하나가 스킬 1개입니다.</p>

            <p className="text-white/40 text-sm"><em>참조:</em> wiki/concepts/geode-skills.md (TODO), portfolio §3 (recursion 9행 중 3행)</p>
          </>
        }
        en={
          <>
            <p>This page explains what the runtime SkillRegistry is and how it differs from the scaffold-side <code>.claude/skills/</code>.</p>

            <h2>Two kinds of skills</h2>
            <table>
              <thead><tr><th>Kind</th><th>Location</th><th>Role</th></tr></thead>
              <tbody>
                <tr><td><strong>Runtime skills</strong></td><td><code>core/skills/</code></td><td>Capabilities the running GEODE agent invokes (e.g. report templates).</td></tr>
                <tr><td><strong>Scaffold skills</strong></td><td><code>.claude/skills/</code></td><td>Capabilities Claude Code uses while building GEODE (code review, gitflow, etc.).</td></tr>
              </tbody>
            </table>

            <h2>Discovery</h2>
            <p>SkillRegistry discovers skills via the frontmatter + markdown body convention, across five priority tiers:</p>
            <ul>
              <li>bundled (shipped with the code)</li>
              <li>user (<code>~/.geode/skills/</code>)</li>
              <li>project (<code>./.geode/skills/</code>)</li>
              <li>org (org-shared)</li>
              <li>session (one-shot)</li>
            </ul>

            <h2>Override</h2>
            <p>When the same skill name appears in multiple tiers, the higher tier wins (session &gt; project &gt; user &gt; org &gt; bundled).</p>

            <h2>Authoring</h2>
            <p>The mechanical steps mirror <a href="/docs/build/add-tool">Add a Tool</a>. One <code>SKILL.md</code> file equals one skill.</p>

            <p className="text-white/40 text-sm"><em>See:</em> wiki/concepts/geode-skills.md (TODO), portfolio §3 (3 of 9 recursion rows).</p>
          </>
        }
      />
    </DocsShell>
  );
}
