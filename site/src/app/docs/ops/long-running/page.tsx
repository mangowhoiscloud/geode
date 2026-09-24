import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Long-running safety — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/long-running"
      title="Long-running safety"
      titleKo="장기 실행 안전"
      summary="Round, time, and cost guards plus the context overflow ladder. How a long run ends honestly."
      summaryKo="라운드, 시간, 비용 가드와 컨텍스트 오버플로 사다리입니다. 긴 실행이 어떻게 정직하게 끝나는지 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              긴 실행의 위험은 셋입니다. 끝나지 않는 루프, 넘치는 컨텍스트,
              불어나는 비용. AgenticLoop는 매 라운드 진입 시점에 가드를 검사하고,
              걸리면 이유가 적힌{" "}
              <code>termination_reason</code>으로 끝납니다
              (<code>core/agent/loop/agent_loop.py</code>).
            </p>

            <h2>라운드 진입 가드</h2>
            <table>
              <thead>
                <tr><th>가드</th><th>기준</th><th>종료 이유</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>라운드 상한</td>
                  <td><code>max_rounds &gt; 0</code>일 때만. 0은 무제한이며 대화형 기본값입니다.</td>
                  <td><code>max_rounds</code></td>
                </tr>
                <tr>
                  <td>실행 time budget</td>
                  <td><code>time_budget_s &gt; 0</code>일 때 wall-clock 검사. 게이트웨이 120초, 스케줄러 300초가 모드 기본값입니다.</td>
                  <td><code>time_budget_expired</code></td>
                </tr>
                <tr>
                  <td>세션 budget</td>
                  <td>세션 전체 기본 2시간 (<code>core/agent/budget.py</code>). 임계 도달 전 <code>HANDOFF_TRIGGERED</code> 훅이 한 번 발화해 인수인계 기회를 줍니다.</td>
                  <td><code>session_time_budget_expired</code></td>
                </tr>
                <tr>
                  <td>비용 budget</td>
                  <td><code>cost_budget &gt; 0</code>이면 80%에서 1회 경고, 도달 시 종료. 세션 비용은 token tracker 누적치입니다.</td>
                  <td><code>cost_budget_exceeded</code></td>
                </tr>
              </tbody>
            </table>
            <p>
              마무리 단계(<code>force_text</code>)에서는 적응형 컴퓨트가
              걸립니다. max_tokens를 컨텍스트 윈도의 0.5%(하한 4096)로 줄이고
              thinking을 끄고 effort를 낮춰, 마지막 응답이 예산을 더 태우지
              않게 합니다.
            </p>

            <h2>컨텍스트 오버플로 사다리</h2>
            <p>
              공통 요청 경로는 미들웨어 뒤의 모델·공급자·source·출력 예비분으로
              예산을 정합니다. 원래 대화에 대한 유지보수는 한 번만 수행하고,
              최종 적합성 검사는 읽기 전용입니다. 미들웨어가 대화를 교체하면
              원래 세션을 대신 요약하지 않습니다.
            </p>
            <ul>
              <li>경고: 윈도 티어에 따라 유효 입력 예산의 50%·70%·80%.</li>
              <li>임계: 유효 입력 예산의 90%.</li>
              <li>200K: soft 로컬 유지보수 선호이며, 모든 경로의 서버 상한이 아닙니다.</li>
              <li>실제 입력 거절: 로컬 추정과 별개로 제한된 복구를 시도하고 다음 요청에서 다시 확인합니다.</li>
            </ul>
            <p>
              지원되는 Anthropic 모델의 자동 threshold compaction은 유지합니다.
              지원되지 않는 알려진 모델은 호환 이력에서 클라이언트 요약을 사용할
              수 있습니다. native compaction 블록이 있는 이력은 일반 텍스트
              교체나 강제 정리로 손상시키지 않습니다. API의 한도를 구독이나
              OpenRouter 경로의 허용량으로 가정하지 않습니다.
            </p>
            <p>
              전략은 <code>ContextWindowManager</code>가 소유합니다.
              <code>PreCompact</code>는 보존 개수와 soft 유예만 결정하고,
              <code>CONTEXT_CRITICAL</code>은 관측 이벤트입니다.
              <code>CONTEXT_OVERFLOW_ACTION</code>은 전략을 선택하지 않습니다.
              복구할 수 없으면 <code>context_exhausted</code>로 끝내고 추가 모델
              호출 없이 안내합니다. 모든 진입점의 세션 자동 초기화를 뜻하지는
              않습니다. 이력 보호와 저장 경계는
              <a href="/geode/docs/runtime/context">컨텍스트 조립</a>을 참고합니다.
            </p>

            <h2>도구 결과 오프로딩</h2>
            <p>
              임계값을 넘는 도구 결과는 컨텍스트에 그대로 쌓이지 않습니다.{" "}
              <code>.geode/tool-offload/&#123;session_id&#125;/</code>에
              저장되고 컨텍스트에는 요약과 <code>ref_id</code>만 남으며,
              필요하면 <code>recall_tool_result(ref_id)</code>로 다시 불러옵니다
              (<code>core/orchestration/tool_offload.py</code>). 임계값은{" "}
              <code>tool_offload_threshold</code> 설정이고 0이면 꺼집니다.
              오프로드 시 <code>TOOL_RESULT_OFFLOADED</code> 훅이 발화합니다.
            </p>

            <h2>서브에이전트 경계</h2>
            <p>
              위임된 작업도 같은 규율을 따릅니다. 깊이 1 강제(재귀 금지),
              세션당 15개 상한, 타임아웃 기본 600초
              (<code>GEODE_SUBAGENT_TIMEOUT_S</code>, 10초에서 3600초로 clamp)
              입니다 (<code>core/agent/sub_agent.py</code>).
            </p>

            <h2>운영 점검</h2>
            <pre>{`> /status        # 데몬, 모델, MCP 상태
> /cost          # 세션 + 월간 비용
> /context       # 조립된 컨텍스트 계층 확인`}</pre>
            <p>
              실행이 어디서 어떻게 끝났는지는{" "}
              <a href="/geode/docs/guides/debug-stuck-run">멈춘 실행 디버깅</a>의
              session history와 SQL event timeline 절차로 추적합니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/ops/cost">비용 모니터링</a>. budget의 설정과 ledger.</li>
              <li><a href="/geode/docs/runtime/context">컨텍스트 조립</a>. 윈도가 채워지는 쪽의 구조.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>. 종료 경로 전체 목록.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              A long run has three risks: a loop that never ends, a context
              that overflows, and a bill that keeps growing. The AgenticLoop
              checks its guards at every round entry, and when one trips, the
              run ends with a named <code>termination_reason</code>{" "}
              (<code>core/agent/loop/agent_loop.py</code>).
            </p>

            <h2>Round-entry guards</h2>
            <table>
              <thead>
                <tr><th>Guard</th><th>Criterion</th><th>Termination reason</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Round cap</td>
                  <td>Only when <code>max_rounds &gt; 0</code>; 0 means unlimited and is the interactive default.</td>
                  <td><code>max_rounds</code></td>
                </tr>
                <tr>
                  <td>Run time budget</td>
                  <td>Wall-clock check when <code>time_budget_s &gt; 0</code>. Mode defaults: 120s on the gateway, 300s for scheduled jobs.</td>
                  <td><code>time_budget_expired</code></td>
                </tr>
                <tr>
                  <td>Session budget</td>
                  <td>2 hours per session by default (<code>core/agent/budget.py</code>). Before the hard stop, <code>HANDOFF_TRIGGERED</code> fires once to allow a handoff.</td>
                  <td><code>session_time_budget_expired</code></td>
                </tr>
                <tr>
                  <td>Cost budget</td>
                  <td>With <code>cost_budget &gt; 0</code>: one warning at 80%, termination at the budget. Session cost comes from the token tracker accumulator.</td>
                  <td><code>cost_budget_exceeded</code></td>
                </tr>
              </tbody>
            </table>
            <p>
              On wrap-up (<code>force_text</code>) adaptive compute kicks in:
              max_tokens clamps to 0.5% of the context window (floor 4096),
              thinking turns off, effort drops, so the final answer cannot burn
              more budget.
            </p>

            <h2>The context overflow ladder</h2>
            <p>
              Shared request preparation resolves the effective model, provider,
              source and output reserve after middleware. Caller-history
              maintenance runs once and the final fit check is read-only.
              A middleware-owned conversation replacement cannot trigger
              summarization of the original session.
            </p>
            <ul>
              <li>Warning: 50%, 70% or 80% of the effective input budget by window tier.</li>
              <li>Critical: 90% of the effective input budget.</li>
              <li>200K: a soft local maintenance preference, not every route&apos;s server cap.</li>
              <li>Actual input rejection: bounded recovery independent of the local estimate, then a new request check.</li>
            </ul>
            <p>
              Supported Anthropic models retain automatic threshold compaction.
              Known models without it can use client summaries on compatible
              histories. Native compaction blocks guard against generic text
              replacement and pruning. API limits do not establish subscription
              or OpenRouter route allowances.
            </p>
            <p>
              <code>ContextWindowManager</code> owns strategy selection.
              <code>PreCompact</code> controls only the retained count and soft
              deferral; <code>CONTEXT_CRITICAL</code> is observation.
              <code>CONTEXT_OVERFLOW_ACTION</code> does not select a strategy.
              Unrecoverable context ends as <code>context_exhausted</code> with a
              local notice and no additional model call. It does not imply an
              automatic session reset at every entry point.
              See <a href="/geode/docs/runtime/context">Context assembly</a> for
              history protection and persistence boundaries.
            </p>

            <h2>Tool-result offloading</h2>
            <p>
              Oversized tool results never pile into the context. They persist
              to <code>.geode/tool-offload/&#123;session_id&#125;/</code> and
              the context keeps only a summary plus a <code>ref_id</code>;{" "}
              <code>recall_tool_result(ref_id)</code> fetches the full result back
              (<code>core/orchestration/tool_offload.py</code>). The knob is{" "}
              <code>tool_offload_threshold</code>; 0 disables it. Each offload
              fires the <code>TOOL_RESULT_OFFLOADED</code> hook.
            </p>

            <h2>Sub-agent boundaries</h2>
            <p>
              Delegated work follows the same discipline: depth 1 enforced (no
              recursion), 15 sub-agents per session, and a 600-second default
              timeout (<code>GEODE_SUBAGENT_TIMEOUT_S</code>, clamped to 10
              through 3600 seconds) in <code>core/agent/sub_agent.py</code>.
            </p>

            <h2>Operating checks</h2>
            <pre>{`> /status        # daemon, model, MCP state
> /cost          # session + monthly spend
> /context       # the assembled context tiers`}</pre>
            <p>
              To trace where and why a run ended, follow the session-history and
              runtime-event procedure in{" "}
              <a href="/geode/docs/guides/debug-stuck-run">Debug a stuck run</a>.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/ops/cost">Cost monitoring</a>. Budgets and the ledger.</li>
              <li><a href="/geode/docs/runtime/context">Context assembly</a>. The side that fills the window.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>. The full list of termination paths.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
