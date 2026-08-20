import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Research, search, and llms.txt — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/research"
      title="Research, search, and llms.txt"
      titleKo="리서치·탐색과 llms.txt"
      summary="How GEODE explores: llms.txt-first documentation research, web search delegation, local FTS search, and the llms.txt this site publishes."
      summaryKo="GEODE의 탐색 방법입니다. llms.txt 우선 문서 리서치, 웹 검색 위임, 로컬 FTS 검색, 그리고 이 사이트가 발행하는 llms.txt를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 탐색은 네 갈래입니다. 외부 문서 사이트, 일반 웹, 자기
              자신의 기억, 그리고 도구 목록 자체. 이 페이지는 네 경로가 각각
              어떤 규칙으로 움직이는지 코드 기준으로 정리합니다.
            </p>

            <h2>문서 사이트 리서치: llms.txt 우선</h2>
            <p>
              개발 도구나 라이브러리 문서를 조사할 때 GEODE는 HTML 내비게이션을
              한 장씩 따라가지 않습니다. 사이트의 <code>/llms.txt</code>를 먼저
              가져옵니다. llmstxt.org 컨벤션을 따르는 사이트는 전체 문서 페이지의
              LLM 친화 인덱스를 그 경로에 발행하기 때문입니다.
            </p>
            <ol>
              <li><code>web_fetch</code>로 <code>/llms.txt</code>를 먼저 조회합니다.</li>
              <li>인덱스에서 관련 링크만 골라 그 페이지들만 가져옵니다.</li>
              <li><code>llms-full.txt</code>(문서 전체를 한 파일로)는 넓은 범위가 정말 필요할 때만 씁니다. 매우 클 수 있습니다.</li>
              <li><code>/llms.txt</code>가 없으면(404 또는 HTML 응답) 해당 사이트로 범위를 좁힌 <code>general_web_search</code>로 폴백합니다.</li>
            </ol>
            <p>
              이 휴리스틱은 코드 분기가 아니라 instruction 레벨로 구현되어
              있습니다. 시스템 프롬프트(<code>core/llm/prompts/router.md</code>의
              &quot;Documentation-site research (llms.txt-first)&quot; 절)와
              <code>web_fetch</code> 도구 설명(<code>core/tools/definitions.json</code>)
              두 표면이 같은 지시를 싣습니다. frontier 하네스들이 수렴한
              방식입니다.
            </p>

            <h2>딥리서치: 독립 축 병렬 수집</h2>
            <p>
              프로젝트의 <code>deep-researcher</code> 스킬은 질문·research gap·
              검증할 claim을 먼저 정하고, 서로 독립인 조사 축만 한 번의
              <code>delegate_task</code> batch로 보냅니다. 부모는 선행조건,
              원문 확인, 모순 판정과 최종 종합을 계속 소유합니다. 자식 실패도
              결과에서 제거하지 않으며, 출처 수 대신 citation entailment,
              최신성, 권위와 상충 근거를 검사합니다.
            </p>
            <p>
              <code>update_plan</code>은 관측된 진행을 표시하는 advisory checklist일
              뿐 실행기가 아닙니다. 런타임이 <code>&lt;plan&gt;</code>을 제공하면
              스킬은 별도 체크리스트를 만들지 않고 그 단계 문구를 그대로 사용합니다.
              결과를 파일이나 memory에 자동 저장하지도 않습니다.
            </p>
            <p>
              짧은 독립 축은 <code>delegate_task</code> batch로 한 번에 회수합니다.
              실행 중 재지시나 대기가 필요한 축만 <code>spawn_agent</code>로 열고,
              mailbox·wait·follow-up·interrupt 제어를 사용합니다. 두 경로 모두
              depth 1이며 재귀 research tree를 만들지 않습니다.
            </p>
            <p>
              자식 프로세스가 정상 종료해도 built-in role의 출력 schema 검증이
              실패하면 <code>SubResult.success=false</code>입니다. batch 성공 수와
              SubagentStop 상태는 실패로 수렴하지만, 검증 오류와 raw excerpt는
              부모가 unresolved gap으로 종합할 수 있게 보존합니다.
            </p>

            <h2>지속 Goal과의 결합</h2>
            <p>
              사용자가 여러 turn에 걸친 지속 목표를 명시한 경우에만
              <code>create_goal</code>을 사용합니다. Goal은 자동 DAG가 아니라
              objective·token budget·누적 사용량·상태를
              <code>sessions.db</code>에 보존하는 제어 봉투입니다. 성공한 turn 뒤
              상태가 active이면 다음 turn을 열고, complete·blocked·budget-limited
              또는 오류에서 멈춥니다. 일반 리서치 요청은 Goal로 자동 승격하지
              않습니다.
            </p>
            <p>
              continuation은 system prompt나 인간 transcript가 아니라 현재 요청에만
              붙는 contextual-user 입력입니다. 같은 text-only 응답이 반복되거나 한
              public call에서 안전 상한에 닿으면 자동 진행만 멈추고 Goal은 active로
              보존합니다. token budget도 provider 호출을 중간 취소하는 hard cap이
              아니라 완료된 turn을 정산해 다음 continuation을 막는 경계이므로 마지막
              turn만큼 초과할 수 있고, 초과분은 사용량에 그대로 기록됩니다.
            </p>
            <p>
              Goal 상태 전이는 canonical session event와 선택적 JSONL projection에
              함께 남지만 objective 원문은 반복 저장하지 않고 digest만 기록합니다.{" "}
              <code>geode serve</code>가 실행 중이고 foreground Lane이 비어 있으면
              active Goal의 동일 checkpoint를 새 generation으로 복원해 내부
              continuation을 시작합니다. PAUSED·terminal·missing/corrupt checkpoint는
              실행하지 않고, 정상 반환된 같은 Goal projection은 상태가 바뀌기
              전까지 다시 admission하지 않습니다. 실행 예외는 1초 host tick에서
              재시도하며 각 admission은 독립된 session metrics를 사용합니다.
            </p>
            <p>
              hosted continuation도 기존 AgenticLoop를 통과하므로 tool loop,
              PostVerify revision, verify-fail replan, usage·evidence·trajectory writer가
              그대로 적용됩니다. 이는 OS-level scheduler나 자동 Plan-and-Execute가
              아니며, 여러 serve process 사이의 exactly-once 외부 부작용도 보장하지
              않습니다. 결과는 별도 inbox로 복제하지 않고 동일 checkpoint와 session
              record에 남으며, 다음 gateway turn이 durable history를 이어받습니다.
              IPC resume는 같은 machine Lane 안에서 checkpoint를 다시 읽고, daemon
              종료는 진행 중인 hosted turn에 30초 drain을 제공합니다.
            </p>
            <p>
              Goal continuation과 실패 보존은
              <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/abad7de44a23cd0756fe1edb5b61a86ed715cc8f/trajectories/geode-agenticloop-goal-deep-research-gpt56-luna-max-2026-08-10-20260809T191233Z-a19174d30764">
                GPT-5.6-Luna/max 행동 trajectory
              </a>로 검증했습니다. 공개본은 38 events와 4/4 tool pair를 보존하고
              private body는 digest로 치환합니다.
            </p>

            <h2>웹 탐색과 위임 규칙</h2>
            <p>
              일반 웹 탐색은 <code>general_web_search</code>와
              <code>web_fetch</code>가 담당합니다. GEODE의 instruction-level 정책은
              한 턴에 이 도구들을 3회 이상 직접 호출하지 않고,
              <code>delegate_task</code>로 서브에이전트에 위임합니다(GEODE.md
              RUNTIME CANNOT). 이는 하드 런타임 차단이 아니라 검색 결과가 부모
              컨텍스트를 폭발시키는 것을 막는 행동 계약입니다. 서브에이전트는
              <code>web_research</code> 툴킷
              (<code>core/tools/toolkits.toml</code>)으로 격리된 컨텍스트에서
              조사를 끝낸 뒤 요약만 돌려줍니다.
            </p>

            <h2>로컬 탐색: 기억과 세션</h2>
            <table>
              <thead>
                <tr><th>표면</th><th>무엇을 찾나</th><th>코드</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>/recall</code></td>
                  <td>저장해 둔 기억 풀의 목록, 조회, 저장</td>
                  <td><code>core/cli/commands/recall.py</code></td>
                </tr>
                <tr>
                  <td><code>geode reindex</code></td>
                  <td>모든 프로젝트의 sessions.db를 모아 <code>~/.geode/search/global.db</code> FTS5 인덱스 재구축</td>
                  <td><code>core/cli/commands/reindex.py</code></td>
                </tr>
                <tr>
                  <td><code>query_memory</code></td>
                  <td>geode-mcp를 붙인 외부 호스트(Claude Code 등)에서 GEODE 메모리 계층 검색</td>
                  <td><code>geode_product/mcp_server.py</code></td>
                </tr>
                <tr>
                  <td><code>recall_tool_result(ref_id)</code></td>
                  <td>임계값을 넘겨 오프로드된 대형 도구 결과 재조회</td>
                  <td><code>core/orchestration/tool_offload.py</code></td>
                </tr>
              </tbody>
            </table>

            <h2>도구 탐색: deferred loading</h2>
            <p>
              도구 목록 자체도 탐색 대상입니다. 네이티브와 MCP 도구를 합친 수가
              임계값을 넘으면 전체 스키마를 다 싣지 않고 <code>tool_search</code>
              메타 도구를 노출해, 에이전트가 필요한 도구를 찾아 그때 로드합니다.
              항상 적재되는 도구는 소수로 고정되어 있습니다
              (<code>core/tools/registry.py</code>의 deferred 경로).
            </p>

            <h2>이 사이트의 llms.txt</h2>
            <p>
              GEODE 문서 사이트도 같은 컨벤션으로 발행합니다. 빌드마다
              <code>sync-stats</code>가 사이트맵에서 재생성합니다.
            </p>
            <ul>
              <li><a href="/geode/llms.txt">/geode/llms.txt</a>. 섹션별 전체 페이지 인덱스.</li>
              <li><a href="/geode/llms-full.txt">/geode/llms-full.txt</a>. 문서 전체를 한 파일로.</li>
            </ul>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>. deferred loading의 자세한 동작.</li>
              <li><a href="/geode/docs/runtime/tools/mcp">MCP 서버</a>. 외부 도구를 붙이는 클라이언트 측.</li>
              <li><a href="/geode/docs/runtime/orchestration">서브에이전트 오케스트레이션</a>. 위임이 실행되는 곳.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE explores along four paths: external documentation sites, the
              open web, its own memory, and the tool catalog itself. This page
              describes the rule each path follows, grounded in code.
            </p>

            <h2>Documentation-site research: llms.txt first</h2>
            <p>
              When researching a developer tool or library, GEODE does not crawl
              HTML navigation page by page. It fetches the site&apos;s
              <code>/llms.txt</code> first. Sites following the llmstxt.org
              convention publish an LLM-readable index of every docs page there.
            </p>
            <ol>
              <li><code>web_fetch</code> the site&apos;s <code>/llms.txt</code> first.</li>
              <li>Pick the relevant links from the index and fetch only those pages.</li>
              <li><code>llms-full.txt</code>, when present, holds the entire docs in one file. Fetch it only when broad coverage is genuinely needed; it can be very large.</li>
              <li>If <code>/llms.txt</code> is absent (404 or an HTML page comes back), fall back to <code>general_web_search</code> scoped to the site.</li>
            </ol>
            <p>
              The heuristic is instruction-level, not a code branch: the system
              prompt (the &quot;Documentation-site research (llms.txt-first)&quot;
              section of <code>core/llm/prompts/router.md</code>) and the
              <code>web_fetch</code> tool description
              (<code>core/tools/definitions.json</code>) carry the same guidance.
              This is the pattern frontier harnesses converged on.
            </p>

            <h2>Deep research: parallel collection over independent axes</h2>
            <p>
              The project&apos;s <code>deep-researcher</code> skill first states the
              question, research gap, and claims to test. It sends only independent
              axes in one <code>delegate_task</code> batch. The parent retains
              prerequisites, primary-source inspection, contradiction decisions,
              and final synthesis. Child failures stay visible, and evidence is
              checked for citation entailment, freshness, authority, and conflicts
              instead of source count alone.
            </p>
            <p>
              <code>update_plan</code> is an advisory checklist for observed progress,
              not an executor. When the runtime supplies a <code>&lt;plan&gt;</code>, the
              skill mirrors those steps instead of creating a second checklist. It
              also does not save the result to files or memory automatically.
            </p>
            <p>
              Short independent axes return through one <code>delegate_task</code>
              batch. Only work that needs steering or waiting uses
              <code>spawn_agent</code> with mailbox, wait, follow-up, and interrupt
              control. Both paths stay at depth one; neither constructs a recursive
              research tree.
            </p>
            <p>
              A normally exited child is still a failed <code>SubResult</code> when
              its built-in role output fails schema validation. Batch success counts
              and SubagentStop agree on that failure, while the validation error and
              raw excerpt remain available to the parent as an unresolved gap.
            </p>

            <h2>Combining research with a persisted Goal</h2>
            <p>
              The skill uses <code>create_goal</code> only when the user explicitly
              asks for a persistent multi-turn objective. A Goal is not an automatic
              DAG: it is a control envelope that stores the objective, optional token
              budget, accumulated usage, and status in <code>sessions.db</code>. An
              active Goal opens another turn after a successful terminal and stops on
              completion, blocking, budget limit, or error. Ordinary research is never
              promoted to a Goal implicitly.
            </p>
            <p>
              Continuation steering is a request-local contextual-user input, not a
              system-prompt clause or a fake human transcript. Repeated identical
              text-only output or the per-call safety ceiling stops only automatic
              progress and leaves the Goal active. The token budget is also a
              completed-turn accounting boundary, not a provider hard cap: the last
              turn can overshoot, and the full overage remains visible in usage.
            </p>
            <p>
              Goal transitions join canonical session events and the optional JSONL
              projection, but repeat only an objective digest rather than the raw
              text. While <code>geode serve</code> is running and foreground lanes
              are idle, it can restore the active Goal&apos;s checkpoint as a new
              generation and start an internal continuation. Paused, terminal,
              missing, or corrupt checkpoints do not launch, and the same Goal
              projection is not admitted again after a returned attempt until its
              state changes. Raised attempts retry on the one-second host tick, and
              every admission receives an isolated session-metrics scope.
            </p>
            <p>
              Hosted continuation still traverses the existing AgenticLoop, including
              the tool loop, PostVerify revision, verify-fail replan, usage, evidence,
              and trajectory writers. It is neither an OS-level scheduler nor an
              automatic Plan-and-Execute engine, and it does not promise exactly-once
              external side effects across multiple serve processes. Results stay in
              the same checkpoint and session record instead of a second inbox; the
              next gateway turn resumes that durable history. IPC resume reloads
              inside the same machine Lane, and daemon shutdown gives an active
              hosted turn a bounded 30-second drain.
            </p>
            <p>
              Goal continuation and child-failure preservation are backed by a
              <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/abad7de44a23cd0756fe1edb5b61a86ed715cc8f/trajectories/geode-agenticloop-goal-deep-research-gpt56-luna-max-2026-08-10-20260809T191233Z-a19174d30764">
                GPT-5.6-Luna/max behavior trajectory release
              </a>. Its public view retains 38 events and 4/4 tool pairs while
              replacing private bodies with digests.
            </p>

            <h2>Web exploration and the delegation rule</h2>
            <p>
              General web exploration runs through
              <code>general_web_search</code> and <code>web_fetch</code>.
              GEODE&apos;s instruction-level policy says not to call them three or more times
              directly in a single turn. Delegate to a sub-agent via
              <code>delegate_task</code> instead (GEODE.md RUNTIME CANNOT).
              This is a behavioral contract, not a hard runtime rejection. It keeps
              search results from exploding the parent context; the
              sub-agent runs with the <code>web_research</code> toolkit
              (<code>core/tools/toolkits.toml</code>) in an isolated context and
              returns only a summary.
            </p>

            <h2>Local search: memory and sessions</h2>
            <table>
              <thead>
                <tr><th>Surface</th><th>What it finds</th><th>Code</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>/recall</code></td>
                  <td>List, show, and save entries in the saved-memory pool</td>
                  <td><code>core/cli/commands/recall.py</code></td>
                </tr>
                <tr>
                  <td><code>geode reindex</code></td>
                  <td>Rebuild the cross-project FTS5 index at <code>~/.geode/search/global.db</code> from every project&apos;s sessions.db</td>
                  <td><code>core/cli/commands/reindex.py</code></td>
                </tr>
                <tr>
                  <td><code>query_memory</code></td>
                  <td>Search GEODE memory tiers from an external MCP host (Claude Code and friends) via geode-mcp</td>
                  <td><code>geode_product/mcp_server.py</code></td>
                </tr>
                <tr>
                  <td><code>recall_tool_result(ref_id)</code></td>
                  <td>Re-fetch a large tool result that was offloaded past the size threshold</td>
                  <td><code>core/orchestration/tool_offload.py</code></td>
                </tr>
              </tbody>
            </table>

            <h2>Tool discovery: deferred loading</h2>
            <p>
              The tool catalog itself is searchable. When the combined count of
              native and MCP tools crosses a threshold, GEODE stops shipping
              every schema up front: it keeps a small always-loaded set eager and
              defers the rest behind the hosted tool_search tool (the official
              defer_loading wiring in
              <code>core/llm/providers/anthropic.py</code>).
            </p>

            <h2>This site&apos;s llms.txt</h2>
            <p>
              The GEODE docs site publishes the same convention. Both files are
              regenerated from the sitemap by <code>sync-stats</code> on every
              build.
            </p>
            <ul>
              <li><a href="/geode/llms.txt">/geode/llms.txt</a>. A curated index of every page, grouped by section.</li>
              <li><a href="/geode/llms-full.txt">/geode/llms-full.txt</a>. The entire docs in one file.</li>
            </ul>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>. Deferred loading in detail.</li>
              <li><a href="/geode/docs/runtime/tools/mcp">MCP servers</a>. The client side that attaches external tools.</li>
              <li><a href="/geode/docs/runtime/orchestration">Sub-agent orchestration</a>. Where delegation actually runs.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
