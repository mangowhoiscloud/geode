import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Memory tiers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/memory/5-tier"
      title="Memory tiers"
      titleKo="메모리 계층"
      summary="From a raw session log to a single LLM-ready summary. Hierarchical override, budget-aware compression."
      summaryKo="raw 세션 로그에서 LLM에 바로 넣을 수 있는 요약까지. 계층 override와 예산 인식 압축을 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 기억은 다섯 계층으로 나뉩니다. 위로 갈수록 안정적이고
              아래로 갈수록 구체적입니다. 매 호출 전에{" "}
              <code>core/memory/context.py</code>의 <code>ContextAssembler</code>가
              다섯 계층을 병합해 LLM에 넣을 단일 요약을 만듭니다.
            </p>

            <h2>다섯 계층</h2>
            <table>
              <thead>
                <tr><th>Tier</th><th>이름</th><th>소스</th></tr>
              </thead>
              <tbody>
                <tr><td>0</td><td>Identity</td><td><code>SOUL.md</code></td></tr>
                <tr><td>0.5</td><td>User Profile</td><td><code>core/memory/user_profile.py</code> (FileBasedUserProfile)</td></tr>
                <tr><td>1</td><td>Organization</td><td><code>core/memory/organization.py</code> (MonoLakeOrganizationMemory)</td></tr>
                <tr><td>2</td><td>Project</td><td><code>core/memory/project.py</code> (ProjectMemory)</td></tr>
                <tr><td>3</td><td>Session</td><td>SessionStorePort (<code>core/memory/port.py</code>)</td></tr>
              </tbody>
            </table>
            <p>
              병합 순서가 곧 override 규칙입니다. 같은 내용이 충돌하면 아래
              계층(더 구체적인 쪽)이 위 계층을 덮습니다. 프로젝트 기억이 조직
              기억을, 세션 기억이 프로젝트 기억을 이깁니다.
            </p>

            <h2>예산 인식 압축</h2>
            <p>
              요약은 <code>max_chars</code> 예산 아래로 맞춰집니다. 계층별 비례
              배분은 SOUL 10%, Organization 25%, Project 25%이고 Session이
              나머지를 가져갑니다. 세션 내용은 최신 항목부터 남은 예산에 채워
              넣으므로, 예산이 모자라면 가장 오래된 대화부터 떨어져 나갑니다.
            </p>

            <h2>/recall: 저장 기억 풀</h2>
            <p>
              계층 병합과 별도로, 이름 붙여 저장하는 영속 기억 풀이 있습니다.
              슬래시 명령 <code>/recall</code>(핸들러{" "}
              <code>core/cli/commands/recall.py</code>)로 목록, 조회, 저장을
              합니다.
            </p>
            <table>
              <thead>
                <tr><th>구성요소</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Writer</td>
                  <td><code>core/memory/recall_writer.py</code>의 <code>write_recall_entry</code>가 frontmatter 달린 마크다운을 <code>~/.geode/memory/recall/</code>에 씁니다 (<code>GEODE_MEMORY_RECALL_DIR</code> env로 위치 변경 가능)</td>
                </tr>
                <tr>
                  <td>Reader</td>
                  <td>로더가 <code>~/.geode/memory/recall/*.md</code>를 키워드 겹침과 최근성으로 랭킹해 <code>&lt;memory-recall&gt;</code> 블록으로 시스템 프롬프트 앞에 붙입니다</td>
                </tr>
                <tr>
                  <td>비자동</td>
                  <td>세션 종료 시 자동 저장하지 않습니다. 노이즈와 비용을 막기 위한 의도적 결정으로, 저장은 항상 명시적입니다</td>
                </tr>
              </tbody>
            </table>

            <h2>세션 저장소</h2>
            <table>
              <thead>
                <tr><th>구현</th><th>코드</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>InMemorySessionStore</td>
                  <td><code>core/memory/session.py</code></td>
                  <td>dict + TTL, 선택적 파일 영속화</td>
                </tr>
                <tr>
                  <td>SessionManager (SQLite)</td>
                  <td><code>core/memory/session_manager.py</code></td>
                  <td>프로젝트별 <code>sessions.db</code> (<code>~/.geode/projects/</code> 아래)</td>
                </tr>
                <tr>
                  <td>Episodic</td>
                  <td><code>core/memory/episodic.py</code></td>
                  <td>append-only <code>~/.geode/memory/episodes.jsonl</code></td>
                </tr>
              </tbody>
            </table>

            <h2>sessions.jsonl: 런 메트릭</h2>
            <p>
              자기개선 루프의 매 런은 토큰, 비용, 재시도, 검증 카운터를 행
              하나로 남깁니다. <code>core/observability/session_metrics.py</code>의{" "}
              <code>SessionMetrics.to_session_row()</code>가 행을 만들고,{" "}
              <code>core/self_improving/train.py</code>가 런 단위로 메트릭을
              시드해 세션 인덱스에 합칩니다. 파일 위치는{" "}
              <code>core/self_improving/ledger.py</code>의{" "}
              <code>SESSIONS_INDEX_PATH</code>가 SoT입니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>저장했다고 생각한 기억이 다음 세션에 없음</td>
                  <td>세션 계층은 휘발성이고 recall 풀은 자동 저장되지 않음</td>
                  <td><code>/recall save &lt;name&gt;</code>으로 명시적으로 저장합니다</td>
                </tr>
                <tr>
                  <td>오래된 대화 내용이 요약에서 사라짐</td>
                  <td>세션 예산을 최신 항목부터 채우는 압축 규칙</td>
                  <td>정상 동작입니다. 중요한 결론은 recall 풀이나 프로젝트 기억으로 승격합니다</td>
                </tr>
                <tr>
                  <td>조직 규칙과 프로젝트 규칙이 충돌</td>
                  <td>계층 override가 의도된 동작</td>
                  <td>아래 계층이 이깁니다. 전역으로 강제할 내용은 위 계층에만 둡니다</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/context">컨텍스트 조립</a>. 이 요약이 실제 호출에 합쳐지는 곳.</li>
              <li><a href="/geode/docs/runtime/research">리서치와 탐색</a>. <code>/recall</code>과 검색 표면들.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE&apos;s memory splits into five tiers: more stable toward the
              top, more specific toward the bottom. Before each call,{" "}
              <code>ContextAssembler</code> in <code>core/memory/context.py</code>{" "}
              merges the five tiers into the single summary the LLM receives.
            </p>

            <h2>The five tiers</h2>
            <table>
              <thead>
                <tr><th>Tier</th><th>Name</th><th>Source</th></tr>
              </thead>
              <tbody>
                <tr><td>0</td><td>Identity</td><td><code>SOUL.md</code></td></tr>
                <tr><td>0.5</td><td>User Profile</td><td><code>core/memory/user_profile.py</code> (FileBasedUserProfile)</td></tr>
                <tr><td>1</td><td>Organization</td><td><code>core/memory/organization.py</code> (MonoLakeOrganizationMemory)</td></tr>
                <tr><td>2</td><td>Project</td><td><code>core/memory/project.py</code> (ProjectMemory)</td></tr>
                <tr><td>3</td><td>Session</td><td>SessionStorePort (<code>core/memory/port.py</code>)</td></tr>
              </tbody>
            </table>
            <p>
              The merge order is the override rule. When content conflicts, the
              lower (more specific) tier overrides the higher one: project memory
              beats organization memory, session memory beats project memory.
            </p>

            <h2>Budget-aware compression</h2>
            <p>
              The summary is fitted under a <code>max_chars</code> budget with
              proportional shares: SOUL 10%, Organization 25%, Project 25%, and
              Session takes the remainder. Session content is filled
              most-recent-first into the remaining budget, so when the budget is
              tight, the oldest conversation falls off first.
            </p>

            <h2>/recall: the saved-memory pool</h2>
            <p>
              Separate from tier merging, there is a persistent pool of named
              memories. The <code>/recall</code> slash command (handler{" "}
              <code>core/cli/commands/recall.py</code>) lists, shows, and saves
              entries.
            </p>
            <table>
              <thead>
                <tr><th>Component</th><th>Behaviour</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Writer</td>
                  <td><code>write_recall_entry</code> in <code>core/memory/recall_writer.py</code> writes frontmattered markdown to <code>~/.geode/memory/recall/</code> (relocatable via the <code>GEODE_MEMORY_RECALL_DIR</code> env)</td>
                </tr>
                <tr>
                  <td>Reader</td>
                  <td>A loader walks <code>~/.geode/memory/recall/*.md</code>, ranks by keyword overlap and recency, and prepends a <code>&lt;memory-recall&gt;</code> block to the system prompt</td>
                </tr>
                <tr>
                  <td>Not automatic</td>
                  <td>Nothing is auto-saved on session end. A deliberate decision against noise and cost; saving is always explicit</td>
                </tr>
              </tbody>
            </table>

            <h2>Session stores</h2>
            <table>
              <thead>
                <tr><th>Implementation</th><th>Code</th><th>Use</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>InMemorySessionStore</td>
                  <td><code>core/memory/session.py</code></td>
                  <td>Dict plus TTL, optional file-backed persistence</td>
                </tr>
                <tr>
                  <td>SessionManager (SQLite)</td>
                  <td><code>core/memory/session_manager.py</code></td>
                  <td>Per-project <code>sessions.db</code> under <code>~/.geode/projects/</code></td>
                </tr>
                <tr>
                  <td>Episodic</td>
                  <td><code>core/memory/episodic.py</code></td>
                  <td>Append-only <code>~/.geode/memory/episodes.jsonl</code></td>
                </tr>
              </tbody>
            </table>

            <h2>sessions.jsonl: run metrics</h2>
            <p>
              Every run of the self-improving loop leaves one row of token, cost,
              retry, and verification counters.{" "}
              <code>SessionMetrics.to_session_row()</code> in{" "}
              <code>core/observability/session_metrics.py</code> builds the row,
              and <code>core/self_improving/train.py</code> seeds run-scoped
              metrics and spreads them into the session index. The file location
              is pinned by <code>SESSIONS_INDEX_PATH</code> in{" "}
              <code>core/self_improving/ledger.py</code>.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>A memory you thought was saved is gone next session</td>
                  <td>The session tier is volatile and the recall pool never auto-saves</td>
                  <td>Save explicitly with <code>/recall save &lt;name&gt;</code></td>
                </tr>
                <tr>
                  <td>Older conversation content drops out of the summary</td>
                  <td>The session budget fills most-recent-first</td>
                  <td>Working as intended; promote important conclusions to the recall pool or project memory</td>
                </tr>
                <tr>
                  <td>Organization and project rules conflict</td>
                  <td>Tier override is the intended behaviour</td>
                  <td>The lower tier wins; keep globally-enforced content only in higher tiers</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/context">Context assembly</a>. Where this summary joins the actual call.</li>
              <li><a href="/geode/docs/runtime/research">Research and search</a>. <code>/recall</code> and the search surfaces.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
