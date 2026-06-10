import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Sub-agent orchestration — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/orchestration"
      title="Sub-agent orchestration"
      titleKo="서브에이전트 오케스트레이션"
      summary="Spawning isolated sub-agents in parallel lanes, with snapshotted memory and merge on completion."
      summaryKo="격리된 서브에이전트를 병렬 레인에서 띄웁니다. 메모리를 스냅샷으로 넘기고 완료 시 병합합니다."
    >
      <Bi
        ko={
          <>
            <p>
              부모 에이전트가 <code>delegate_task</code>를 호출하면{" "}
              <code>core/agent/sub_agent.py</code>의{" "}
              <code>SubAgentManager</code>가 격리된 서브에이전트를 띄웁니다.
              실행은 <code>core/orchestration/isolated_execution.py</code>의{" "}
              <code>IsolatedRunner</code>가 맡고, 작업 간 의존성은 TaskGraph
              (<code>core/orchestration/task_system.py</code>)가 추적합니다.
              스폰과 종료마다 <code>SUBAGENT_STARTED</code> /{" "}
              <code>SUBAGENT_COMPLETED</code> / <code>SUBAGENT_FAILED</code> 훅이
              발화하고, 부모 세션 키가 있으면 Spawn+Announce로 진행 상황을
              알립니다.
            </p>

            <h2>한도</h2>
            <table>
              <thead>
                <tr><th>노브</th><th>기본값</th><th>비고</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>max_depth</code></td>
                  <td>1</td>
                  <td>서브에이전트는 다시 서브에이전트를 띄울 수 없습니다. 깊이 가드가 오류 결과를 반환합니다</td>
                </tr>
                <tr>
                  <td><code>max_total_subagents</code></td>
                  <td>15</td>
                  <td>세션당 상한 (<code>core/config/_settings.py</code>)</td>
                </tr>
                <tr>
                  <td><code>timeout_s</code></td>
                  <td>600초</td>
                  <td><code>GEODE_SUBAGENT_TIMEOUT_S</code> env로 조절, [10, 3600]으로 clamp</td>
                </tr>
                <tr>
                  <td><code>time_budget_s</code></td>
                  <td>0 (꺼짐)</td>
                  <td>선택적 wall-clock 예산</td>
                </tr>
                <tr>
                  <td><code>denied_tools</code> / <code>working_dirs</code></td>
                  <td>비어 있음</td>
                  <td>도구 차단 목록과 샌드박스 작업 디렉터리 추가</td>
                </tr>
              </tbody>
            </table>

            <h2>레인: 동시성의 단위</h2>
            <p>
              모든 실행 경로는 <code>core/orchestration/lane_queue.py</code>의
              레인을 통과합니다. SessionLane이 같은 세션 키를 직렬화하고(다른
              키는 병렬), 그 다음 글로벌 레인이 전체 동시성을 잡습니다.
            </p>
            <table>
              <thead>
                <tr><th>레인</th><th>동시성</th><th>비고</th></tr>
              </thead>
              <tbody>
                <tr><td><code>global</code></td><td>max_concurrent=50</td><td>프로덕션 기본값 (<code>core/wiring/container.py</code>)</td></tr>
                <tr><td><code>gateway</code></td><td>설정값</td><td>메신저 인바운드</td></tr>
                <tr><td><code>claude-cli-subagent</code> / <code>codex-cli-subagent</code></td><td>레인별 설정</td><td>CLI 구독 레인 보호</td></tr>
                <tr><td><code>seed-generation</code></td><td>레인별 설정</td><td>시드 파이프라인</td></tr>
              </tbody>
            </table>
            <p>
              SessionLane은 세션 키 256개까지 유지하고 유휴 키를 정리합니다.
            </p>

            <h2>메모리 격리 규칙</h2>
            <ol>
              <li>부모 메모리는 읽기 전용 스냅샷으로 상속됩니다.</li>
              <li>서브에이전트의 쓰기는 task_id 범위 버퍼로 갑니다. 공유 메모리를 직접 수정하지 않습니다.</li>
              <li>완료 후 부모는 요약만 병합합니다.</li>
            </ol>
            <p>
              결과적으로 두 에이전트가 공유 메모리에 동시에 쓰는 일이
              구조적으로 불가능합니다.
            </p>

            <h2>도구와 능력의 상속</h2>
            <p>
              서브에이전트는 부모와 같은 도구, MCP, 스킬, 메모리 스냅샷을
              받되, 도구 표면은 선언된 툴킷으로 좁혀집니다. frontmatter의{" "}
              <code>toolkit:</code> 이름이 먼저, 레거시 <code>tools:</code>{" "}
              목록이 다음, 둘 다 없으면 읽기 전용 <code>_default</code>입니다.
              자세한 해석 규칙은{" "}
              <a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>을
              참고합니다.
            </p>

            <h2>결과와 오류 분류</h2>
            <p>
              <code>SubAgentResult.status</code>는 ok / error / timeout /
              partial 중 하나입니다. 사용량 롤업(prompt_tokens,
              completion_tokens, usd_spent)이 결과에 실리며, 구독이나 CLI
              레인으로 라우팅된 호출은 0으로 기록됩니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>서브에이전트가 또 위임하려다 실패</td>
                  <td><code>max_depth=1</code> 가드</td>
                  <td>의도된 동작입니다. 위임 구조를 부모에서 평탄화합니다</td>
                </tr>
                <tr>
                  <td>10분쯤에서 timeout 상태로 종료</td>
                  <td>기본 <code>timeout_s=600</code></td>
                  <td><code>GEODE_SUBAGENT_TIMEOUT_S</code>를 올립니다 (상한 3600)</td>
                </tr>
                <tr>
                  <td>서브에이전트의 메모와 기록이 부모에 안 보임</td>
                  <td>요약만 병합하는 격리 규칙</td>
                  <td>남겨야 할 내용은 서브에이전트의 최종 요약에 포함시킵니다</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>. 툴킷 매니페스트와 해석 순서.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>. 위임을 시작하는 쪽.</li>
              <li><a href="/geode/docs/harness/serve-gateway">serve와 게이트웨이</a>. 레인이 보호하는 데몬.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              When the parent agent calls <code>delegate_task</code>,{" "}
              <code>SubAgentManager</code> in{" "}
              <code>core/agent/sub_agent.py</code> spawns an isolated sub-agent.
              Execution runs through <code>IsolatedRunner</code>{" "}
              (<code>core/orchestration/isolated_execution.py</code>), and
              dependencies between tasks are tracked by the TaskGraph
              (<code>core/orchestration/task_system.py</code>). Every spawn and
              exit fires <code>SUBAGENT_STARTED</code> /{" "}
              <code>SUBAGENT_COMPLETED</code> / <code>SUBAGENT_FAILED</code>{" "}
              hooks, and with a parent session key set, progress is announced
              back (Spawn+Announce).
            </p>

            <h2>Limits</h2>
            <table>
              <thead>
                <tr><th>Knob</th><th>Default</th><th>Notes</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>max_depth</code></td>
                  <td>1</td>
                  <td>Sub-agents cannot spawn sub-agents; the depth guard returns an error result</td>
                </tr>
                <tr>
                  <td><code>max_total_subagents</code></td>
                  <td>15</td>
                  <td>Per-session cap (<code>core/config/_settings.py</code>)</td>
                </tr>
                <tr>
                  <td><code>timeout_s</code></td>
                  <td>600 s</td>
                  <td>Tunable via the <code>GEODE_SUBAGENT_TIMEOUT_S</code> env, clamped to [10, 3600]</td>
                </tr>
                <tr>
                  <td><code>time_budget_s</code></td>
                  <td>0 (off)</td>
                  <td>Optional wall-clock budget</td>
                </tr>
                <tr>
                  <td><code>denied_tools</code> / <code>working_dirs</code></td>
                  <td>empty</td>
                  <td>Tool denylist and additional sandbox working directories</td>
                </tr>
              </tbody>
            </table>

            <h2>Lanes: the unit of concurrency</h2>
            <p>
              Every execution path passes through the lanes in{" "}
              <code>core/orchestration/lane_queue.py</code>: a SessionLane
              serializes work on the same session key (different keys run in
              parallel), then the global lane caps total concurrency.
            </p>
            <table>
              <thead>
                <tr><th>Lane</th><th>Concurrency</th><th>Notes</th></tr>
              </thead>
              <tbody>
                <tr><td><code>global</code></td><td>max_concurrent=50</td><td>Production default (<code>core/wiring/container.py</code>)</td></tr>
                <tr><td><code>gateway</code></td><td>settings-driven</td><td>Messenger inbound</td></tr>
                <tr><td><code>claude-cli-subagent</code> / <code>codex-cli-subagent</code></td><td>per-lane</td><td>Protects CLI subscription lanes</td></tr>
                <tr><td><code>seed-generation</code></td><td>per-lane</td><td>The seed pipeline</td></tr>
              </tbody>
            </table>
            <p>
              The SessionLane holds up to 256 session keys and evicts idle ones.
            </p>

            <h2>Memory isolation rules</h2>
            <ol>
              <li>Parent memory is inherited as a read-only snapshot.</li>
              <li>Sub-agent writes go to a task_id-scoped buffer; shared memory is never modified directly.</li>
              <li>After completion, the parent merges only the summary.</li>
            </ol>
            <p>
              As a result, two agents writing shared memory at the same time is
              structurally impossible.
            </p>

            <h2>What sub-agents inherit</h2>
            <p>
              A sub-agent receives the parent&apos;s tools, MCP connections,
              skills, and memory snapshot, with the tool surface narrowed to its
              declared toolkit: the frontmatter <code>toolkit:</code> name first,
              a legacy <code>tools:</code> list second, and the read-only{" "}
              <code>_default</code> when neither exists. Resolution details are
              in <a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>.
            </p>

            <h2>Results and error taxonomy</h2>
            <p>
              <code>SubAgentResult.status</code> is one of ok / error / timeout /
              partial. Usage rollups (prompt_tokens, completion_tokens,
              usd_spent) ride along on the result; calls routed through
              subscription or CLI lanes record 0.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>A sub-agent fails when it tries to delegate again</td>
                  <td>The <code>max_depth=1</code> guard</td>
                  <td>Intended; flatten the delegation structure in the parent</td>
                </tr>
                <tr>
                  <td>Runs end in timeout around ten minutes</td>
                  <td>The default <code>timeout_s=600</code></td>
                  <td>Raise <code>GEODE_SUBAGENT_TIMEOUT_S</code> (ceiling 3600)</td>
                </tr>
                <tr>
                  <td>Sub-agent notes never appear in the parent</td>
                  <td>The summary-only merge rule</td>
                  <td>Put anything that must survive into the sub-agent&apos;s final summary</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>. The toolkit manifest and resolution order.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>. The side that initiates delegation.</li>
              <li><a href="/geode/docs/harness/serve-gateway">Serve and the gateway</a>. The daemon the lanes protect.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
