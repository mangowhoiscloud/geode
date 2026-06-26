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

            <h2>웹 탐색과 위임 규칙</h2>
            <p>
              일반 웹 탐색은 <code>general_web_search</code>와
              <code>read_web_page</code>가 담당합니다. 단, 런타임 가드레일이
              하나 있습니다. 한 턴에 이 도구들을 3회 이상 직접 호출하지 않고,
              <code>delegate_task</code>로 서브에이전트에 위임합니다(GEODE.md
              RUNTIME CANNOT). 검색 결과가 부모 컨텍스트를 폭발시키는 것을 막고,
              서브에이전트는 <code>web_research</code> 툴킷
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
                  <td><code>core/mcp_server.py</code></td>
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

            <h2>Web exploration and the delegation rule</h2>
            <p>
              General web exploration runs through
              <code>general_web_search</code> and <code>read_web_page</code>,
              with one runtime guardrail: never call them three or more times
              directly in a single turn. Delegate to a sub-agent via
              <code>delegate_task</code> instead (GEODE.md RUNTIME CANNOT).
              That keeps search results from exploding the parent context; the
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
                  <td><code>core/mcp_server.py</code></td>
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
