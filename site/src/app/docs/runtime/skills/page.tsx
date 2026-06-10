import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Skills — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/skills"
      title="Skills"
      titleKo="스킬"
      summary="User-invocable skills, distinct from tools. Discovery, lifecycle, override."
      summaryKo="도구와 구분되는, 사용자가 호출하는 스킬입니다. 발견, 라이프사이클, override를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              스킬은 마크다운으로 적은 절차적 지식입니다. 도구가 모델이
              호출하는 함수라면, 스킬은 사용자가 <code>/skill</code>로
              호출하거나 트리거 키워드로 매칭되는 지시문 묶음입니다. 런타임
              엔진은 <code>core/skills/skills.py</code>입니다.
            </p>

            <h2>3계층 저장소</h2>
            <p>
              스킬은 세 계층에서 발견됩니다 (<code>core/cli/commands/skill.py</code>).
            </p>
            <table>
              <thead>
                <tr><th>계층</th><th>위치</th><th>성격</th></tr>
              </thead>
              <tbody>
                <tr><td>builtin</td><td><code>core/skills/</code> (저장소와 함께 배포)</td><td>코드와 같이 버전 관리</td></tr>
                <tr><td>project</td><td><code>.geode/skills/</code></td><td>팀 공유, git에 커밋</td></tr>
                <tr><td>personal</td><td><code>~/.geode/skills/</code></td><td>개인 로컬 전용</td></tr>
              </tbody>
            </table>
            <p>
              로더(<code>core/skills/skills.py</code>)는 번들 → 개인 → 프로젝트
              순서로 디렉터리를 걷고, 같은 이름이 충돌하면 나중 스코프가
              이깁니다. 프로젝트 스킬이 최우선입니다. GEODE를 개발할 때 Claude
              Code가 쓰는 scaffold 스킬(<code>.claude/skills/</code>)은 이
              런타임 레지스트리와 완전히 별개입니다.
            </p>

            <h2>SKILL.md 형식</h2>
            <pre>{`---
name: my-skill
description: 무엇을 하는 스킬인지. "키워드1", "키워드2" 키워드로 트리거
tools: read_document, grep_files
user-invocable: true
context: fork            # 격리 서브에이전트로 실행 (선택)
argument-hint: "[issue-number]"
---

본문 마크다운. $ARGUMENTS 가 호출 인자로 치환되고,
!\`cmd\` 는 호출 시점에 셸 실행 결과로 치환됩니다.`}</pre>
            <p>
              로딩은 점진적입니다. 시작 시에는 frontmatter 메타데이터만 읽고,
              본문은 호출 시점에 로드합니다. 시스템 프롬프트에는 스킬 카탈로그
              요약이 <code>core/agent/loop/_context.py</code>의{" "}
              <code>{"{skill_context}"}</code> 블록 한 곳으로만 들어갑니다.
            </p>

            <h2>호출</h2>
            <table>
              <thead>
                <tr><th>표면</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>/skill &lt;name&gt; [args]</code></td>
                  <td>스킬 하나를 호출합니다. <code>$ARGUMENTS</code> 치환과 동적 컨텍스트 실행 포함 (<code>core/cli/commands/skills.py</code>)</td>
                </tr>
                <tr>
                  <td><code>context: fork</code> 스킬</td>
                  <td>렌더된 본문을 <code>run_agentic_oneshot</code>(<code>core/cli/bootstrap.py</code>)으로 넘겨 격리된 서브에이전트 원샷으로 실행합니다. geode-mcp의 <code>run_agent</code>와 같은 최소 스택입니다</td>
                </tr>
                <tr>
                  <td><code>/skills</code></td>
                  <td>목록, 추가, 리로드</td>
                </tr>
                <tr>
                  <td><code>geode skill list / create / show / remove</code></td>
                  <td>3계층을 관리하는 CLI. <code>--private</code>로 personal 계층에 생성합니다</td>
                </tr>
              </tbody>
            </table>
            <p>
              frontmatter의 <code>user-invocable: false</code>는 스킬을 배경
              지식으로 돌려 <code>/skills</code> 목록에서 숨깁니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>새로 만든 스킬이 안 보임</td>
                  <td>레지스트리가 아직 옛 카탈로그를 들고 있음</td>
                  <td><code>/skills reload</code> 또는 세션 재시작</td>
                </tr>
                <tr>
                  <td>같은 이름인데 의도한 버전이 안 잡힘</td>
                  <td>스코프 override. 프로젝트가 개인을 이깁니다</td>
                  <td><code>geode skill show &lt;name&gt;</code>으로 어느 계층이 잡혔는지 확인합니다</td>
                </tr>
                <tr>
                  <td>fork 스킬이 메인 대화 컨텍스트를 못 봄</td>
                  <td><code>context: fork</code>는 격리 실행이 목적</td>
                  <td>필요한 내용을 인자로 전달하거나 fork를 빼고 인라인으로 돌립니다</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/prompt-system">프롬프트 조립</a>. <code>{"{skill_context}"}</code> 블록이 들어가는 자리.</li>
              <li><a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>. 스킬과 도구의 경계.</li>
              <li><a href="/geode/docs/runtime/orchestration">서브에이전트 오케스트레이션</a>. fork 실행의 기반.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              A skill is procedural knowledge written in markdown. Where a tool
              is a function the model calls, a skill is an instruction bundle the
              user invokes with <code>/skill</code> or that matches on trigger
              keywords. The runtime engine is{" "}
              <code>core/skills/skills.py</code>.
            </p>

            <h2>Three storage tiers</h2>
            <p>
              Skills are discovered across three tiers
              (<code>core/cli/commands/skill.py</code>).
            </p>
            <table>
              <thead>
                <tr><th>Tier</th><th>Location</th><th>Nature</th></tr>
              </thead>
              <tbody>
                <tr><td>builtin</td><td><code>core/skills/</code> (ships with the repo)</td><td>Versioned with the code</td></tr>
                <tr><td>project</td><td><code>.geode/skills/</code></td><td>Team-shared, committed to git</td></tr>
                <tr><td>personal</td><td><code>~/.geode/skills/</code></td><td>Local-only</td></tr>
              </tbody>
            </table>
            <p>
              The loader (<code>core/skills/skills.py</code>) walks bundled, then
              personal, then project directories; on a name conflict the later
              scope wins, so a project skill takes precedence. The scaffold
              skills Claude Code uses while building GEODE
              (<code>.claude/skills/</code>) are entirely separate from this
              runtime registry.
            </p>

            <h2>The SKILL.md format</h2>
            <pre>{`---
name: my-skill
description: What the skill does, with trigger keywords
tools: read_document, grep_files
user-invocable: true
context: fork            # run in an isolated sub-agent (optional)
argument-hint: "[issue-number]"
---

Markdown body. $ARGUMENTS is substituted with the invocation args,
and !\`cmd\` is replaced with shell output at invocation time.`}</pre>
            <p>
              Loading is progressive: only frontmatter metadata is read at
              startup, and the body loads on invoke. The system prompt receives a
              skill-catalog summary through exactly one route, the{" "}
              <code>{"{skill_context}"}</code> block in{" "}
              <code>core/agent/loop/_context.py</code>.
            </p>

            <h2>Invocation</h2>
            <table>
              <thead>
                <tr><th>Surface</th><th>Behaviour</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>/skill &lt;name&gt; [args]</code></td>
                  <td>Invokes one skill, with <code>$ARGUMENTS</code> substitution and dynamic-context execution (<code>core/cli/commands/skills.py</code>)</td>
                </tr>
                <tr>
                  <td>A <code>context: fork</code> skill</td>
                  <td>The rendered body runs as an isolated sub-agent one-shot via <code>run_agentic_oneshot</code> (<code>core/cli/bootstrap.py</code>), the same minimal stack geode-mcp&apos;s <code>run_agent</code> uses</td>
                </tr>
                <tr>
                  <td><code>/skills</code></td>
                  <td>List, add, reload</td>
                </tr>
                <tr>
                  <td><code>geode skill list / create / show / remove</code></td>
                  <td>The CLI that manages the three tiers; <code>--private</code> creates in the personal tier</td>
                </tr>
              </tbody>
            </table>
            <p>
              Setting <code>user-invocable: false</code> in the frontmatter turns
              a skill into background knowledge and hides it from the{" "}
              <code>/skills</code> list.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>A freshly created skill does not show up</td>
                  <td>The registry still holds the old catalog</td>
                  <td><code>/skills reload</code>, or restart the session</td>
                </tr>
                <tr>
                  <td>The wrong version of a same-named skill is picked</td>
                  <td>Scope override: project beats personal</td>
                  <td>Check which tier resolved with <code>geode skill show &lt;name&gt;</code></td>
                </tr>
                <tr>
                  <td>A fork skill cannot see the main conversation</td>
                  <td><code>context: fork</code> isolates by design</td>
                  <td>Pass what it needs as arguments, or drop fork and run inline</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/prompt-system">Prompt assembly</a>. Where the <code>{"{skill_context}"}</code> block lands.</li>
              <li><a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>. The boundary between skills and tools.</li>
              <li><a href="/geode/docs/runtime/orchestration">Sub-agent orchestration</a>. The substrate fork execution rides on.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
