import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Skill Registry — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/skills"
      title="Skill Registry"
      titleKo="스킬 레지스트리"
      summary="Runtime SkillRegistry. 5-tier discovery, report templates, frontmatter + markdown convention."
      summaryKo="런타임 SkillRegistry. 5-tier discovery, 리포트 템플릿, frontmatter + markdown 규약."
    >
      <Bi
        ko={
          <>
            <p>이 페이지는 GEODE 런타임의 SkillRegistry와 scaffold 측 <code>.claude/skills/</code>의 차이, 그리고 v0.71+에서 패키지화된 <code>core/skills/reports/</code> 구조를 정리합니다.</p>

            <h2>두 종류의 스킬</h2>
            <table>
              <thead><tr><th>구분</th><th>위치</th><th>역할</th><th>발견 시점</th></tr></thead>
              <tbody>
                <tr><td><strong>Runtime skills</strong></td><td><code>core/skills/</code></td><td>실행 중인 GEODE 에이전트가 호출하는 능력 (예: report 템플릿)</td><td>bootstrap에서 SkillRegistry가 로드</td></tr>
                <tr><td><strong>Scaffold skills</strong></td><td><code>.claude/skills/</code></td><td>GEODE를 빌드할 때 Claude Code가 사용하는 능력 (예: code review, gitflow)</td><td>Claude Code session 시작 시 자동</td></tr>
              </tbody>
            </table>

            <h2>SkillRegistry 구현 (core/skills/skill_registry.py)</h2>
            <p>
              <code>SkillRegistry</code>는 5계층 우선순위에 따라 디렉토리를 walk하며 <code>SKILL.md</code> 파일을 발견합니다.
              파일은 frontmatter (YAML) + markdown 본문으로 구성됩니다.
            </p>
            <pre>{`---
name: my-skill
description: 한 줄로 무엇을 하는 스킬인지
trigger_keywords: [keyword1, keyword2]
priority: 100
---

(본문 markdown. 에이전트가 system prompt L3에 주입함)`}</pre>

            <h2>5계층 발견 (lower wins on conflict)</h2>
            <ol>
              <li><strong>bundled</strong> — 코드와 함께 배포 (<code>core/skills/</code> 또는 plugin). bootstrap.</li>
              <li><strong>org</strong> — 조직 공유 (<code>~/.geode/org/skills/</code>). 다수 프로젝트 공통.</li>
              <li><strong>user</strong> — 사용자 (<code>~/.geode/skills/</code>). 개인 설정.</li>
              <li><strong>project</strong> — 현 프로젝트 (<code>./.geode/skills/</code>). cwd 기반.</li>
              <li><strong>session</strong> — 1회용 (실행 중 동적 추가). 가장 높은 우선순위.</li>
            </ol>
            <p>같은 <code>name</code>의 스킬이 여러 계층에 있으면 위쪽이 이깁니다. session ▸ project ▸ user ▸ org ▸ bundled.</p>

            <h2>Reports 패키지 (v0.71+)</h2>
            <p>
              <code>core/skills/reports/</code>는 분석 출력의 template을 모듈로 패키지화한 것입니다.
              각 모듈은 특정 출력 형식의 schema + 어셈블 로직을 갖습니다.
            </p>
            <table>
              <thead><tr><th>모듈</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><code>cross_llm.py</code></td><td>Cross-LLM 교차 검증 출력.</td></tr>
                <tr><td><code>generator.py</code></td><td>구조화된 산출물을 조합한 최종 보고서 생성.</td></tr>
                <tr><td><code>models.py</code></td><td>공유 데이터 모델 (Pydantic).</td></tr>
              </tbody>
            </table>

            <h2>발화되는 hook 이벤트</h2>
            <ul>
              <li><code>SESSION_START</code> 시 SkillRegistry 로드.</li>
              <li>스킬이 매칭되어 system prompt에 주입되면 <code>PROMPT_ASSEMBLED</code> payload의 <code>fragments_used</code>에 포함.</li>
            </ul>

            <h2>스킬 작성 (3 step)</h2>
            <ol>
              <li>적절한 tier 디렉토리에 <code>SKILL.md</code> 생성 (예: <code>~/.geode/skills/my-skill/SKILL.md</code>).</li>
              <li>frontmatter에 <code>name</code>, <code>description</code>, <code>trigger_keywords</code> 작성.</li>
              <li>본문 markdown 작성 (보통 200-500단어).</li>
            </ol>
            <p>등록 시점: 다음 bootstrap 또는 session 재시작 시 자동 인식.</p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>참조:</em> <a href="/geode/docs/runtime/context">Context System</a> (5-layer prompt assembly에서 skill이 L3로 주입),
              wiki/concepts/geode-prompt-assembly.md, portfolio §3 Recursion (scaffold 측 skill discovery와 mirror).
            </p>
          </>
        }
        en={
          <>
            <p>This page documents the runtime SkillRegistry vs the scaffold-side <code>.claude/skills/</code>, and the v0.71+ <code>core/skills/reports/</code> package layout.</p>

            <h2>Two kinds of skills</h2>
            <table>
              <thead><tr><th>Kind</th><th>Location</th><th>Role</th><th>Discovery</th></tr></thead>
              <tbody>
                <tr><td><strong>Runtime skills</strong></td><td><code>core/skills/</code></td><td>Capabilities the running GEODE agent invokes (e.g. report templates).</td><td>SkillRegistry loads at bootstrap.</td></tr>
                <tr><td><strong>Scaffold skills</strong></td><td><code>.claude/skills/</code></td><td>Capabilities Claude Code uses while building GEODE (code review, gitflow, etc.).</td><td>Auto-discovered at Claude Code session start.</td></tr>
              </tbody>
            </table>

            <h2>SkillRegistry implementation (core/skills/skill_registry.py)</h2>
            <p>
              <code>SkillRegistry</code> walks five priority directories looking for <code>SKILL.md</code> files. Each
              file is YAML frontmatter plus markdown body.
            </p>
            <pre>{`---
name: my-skill
description: One sentence describing what the skill does
trigger_keywords: [keyword1, keyword2]
priority: 100
---

(Markdown body — injected into system prompt at L3)`}</pre>

            <h2>5-tier discovery (lower wins on conflict)</h2>
            <ol>
              <li><strong>bundled</strong> — shipped with the code (<code>core/skills/</code> or plugin). Bootstrap.</li>
              <li><strong>org</strong> — org-shared (<code>~/.geode/org/skills/</code>). Common across multiple projects.</li>
              <li><strong>user</strong> — user-level (<code>~/.geode/skills/</code>). Personal.</li>
              <li><strong>project</strong> — current project (<code>./.geode/skills/</code>). cwd-based.</li>
              <li><strong>session</strong> — one-shot (added at runtime). Highest priority.</li>
            </ol>
            <p>When the same <code>name</code> exists in multiple tiers, the lower (higher-priority) entry wins. session ▸ project ▸ user ▸ org ▸ bundled.</p>

            <h2>Reports package (since v0.71)</h2>
            <p>
              <code>core/skills/reports/</code> packages analysis-output templates as modules. Each module owns a
              specific output format's schema plus assembly logic.
            </p>
            <table>
              <thead><tr><th>Module</th><th>Role</th></tr></thead>
              <tbody>
                <tr><td><code>cross_llm.py</code></td><td>Cross-LLM verification output.</td></tr>
                <tr><td><code>generator.py</code></td><td>Composes structured artifacts into the final report.</td></tr>
                <tr><td><code>models.py</code></td><td>Shared data models (Pydantic).</td></tr>
              </tbody>
            </table>

            <h2>Hooks fired</h2>
            <ul>
              <li>On <code>SESSION_START</code> the SkillRegistry loads.</li>
              <li>When a skill matches and is injected into the system prompt, the <code>PROMPT_ASSEMBLED</code> payload includes its name in <code>fragments_used</code>.</li>
            </ul>

            <h2>Authoring a skill (3 steps)</h2>
            <ol>
              <li>Create <code>SKILL.md</code> in the appropriate tier directory (e.g. <code>~/.geode/skills/my-skill/SKILL.md</code>).</li>
              <li>Add <code>name</code>, <code>description</code>, <code>trigger_keywords</code> to the frontmatter.</li>
              <li>Write the markdown body (usually 200-500 words).</li>
            </ol>
            <p>The skill is picked up at the next bootstrap or session restart.</p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>See:</em> <a href="/geode/docs/runtime/context">Context System</a> (the skill is injected at L3 of the
              5-layer prompt assembly), wiki/concepts/geode-prompt-assembly.md, portfolio §3 Recursion (mirror of
              scaffold-side skill discovery).
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
