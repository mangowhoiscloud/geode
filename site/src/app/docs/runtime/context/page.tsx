import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Context assembly — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/context"
      title="Context assembly"
      titleKo="컨텍스트 조립"
      summary="Every LLM call's context is built here. Memory tiers plus prompt layers, under a token budget."
      summaryKo="모든 LLM 호출의 컨텍스트가 여기서 만들어집니다. 메모리 계층과 프롬프트 레이어를 토큰 예산 안에서 합칩니다."
    >
      <Bi
        ko={
          <>
            <p>
              LLM 호출 하나에 들어가는 컨텍스트는 세 재료로 만들어집니다. 메모리
              계층의 요약, 레이어로 조립된 시스템 프롬프트, 그리고 대화
              히스토리입니다. 이 페이지는 세 재료가 토큰 예산 안에서 어떻게
              합쳐지고, 예산을 넘으면 무엇이 양보하는지 정리합니다.
            </p>

            <h2>재료 1: 메모리 계층</h2>
            <p>
              <code>core/memory/context.py</code>의 <code>ContextAssembler</code>가
              5계층 메모리를 병합하고, LLM에 넣을 <code>_llm_summary</code>를
              만듭니다. 병합은 Identity, User Profile, Organization, Project,
              Session 순서로 흐르고, 더 구체적인 계층이 앞 계층을 덮습니다.
            </p>
            <table>
              <thead>
                <tr><th>계층</th><th>요약 예산</th></tr>
              </thead>
              <tbody>
                <tr><td>Identity (SOUL.md)</td><td>10%</td></tr>
                <tr><td>User Profile</td><td>있으면 앞부분 예산에 짧게 포함</td></tr>
                <tr><td>Organization</td><td>25%</td></tr>
                <tr><td>Project</td><td>25%</td></tr>
                <tr><td>Session</td><td>나머지. 최신 항목부터 채웁니다</td></tr>
              </tbody>
            </table>
            <p>
              계층 병합 뒤에는 프로젝트 타입, 최근 실행 기록, 프로젝트 저널,
              Vault 요약 같은 보강 블록이 붙습니다. 계층 자체의 구조와 override 규칙은{" "}
              <a href="/geode/docs/runtime/memory/5-tier">메모리 계층</a>에서
              다룹니다.
            </p>

            <h2>재료 2: 시스템 프롬프트 레이어</h2>
            <p>
              <code>core/agent/system_prompt.py</code>의{" "}
              <code>build_system_prompt(model)</code>이 캐시 가능한 정적
              prefix와 턴마다 바뀌는 동적 섹션(<code>&lt;dynamic_context&gt;</code>)을
              경계 마커로 나눠
              조립합니다. 레이어 구성과 모드는{" "}
              <a href="/geode/docs/runtime/llm/prompt-system">프롬프트 조립</a>,
              캐시 동작은{" "}
              <a href="/geode/docs/runtime/llm/prompt-caching">프롬프트 캐싱</a>을
              참고합니다.
            </p>

            <h2>오버플로 처리: 누가 양보하는가</h2>
            <p>
              루프는 매 라운드 진입 시{" "}
              <code>core/agent/context_manager.py</code>의{" "}
              <code>ContextWindowManager</code>에 오버플로 점검을 위임합니다.
              임계값은 고정된 80/95가 아니라{" "}
              <code>core/orchestration/context_budget.py</code>의{" "}
              <code>resolve_context_budget_policy</code>가 모델의 컨텍스트
              윈도에 맞춰 계산합니다. 반환된 <code>ContextBudgetPolicy</code>가
              세 티어 중 하나를 고릅니다.
            </p>
            <table>
              <thead>
                <tr><th>티어</th><th>윈도 범위</th><th>경고 임계</th><th>임계</th></tr>
              </thead>
              <tbody>
                <tr><td>small</td><td>≤ 256K</td><td>50%</td><td>90%</td></tr>
                <tr><td>standard</td><td>≤ 512K</td><td>70%</td><td>90%</td></tr>
                <tr><td>large</td><td>&gt; 512K</td><td>80%</td><td>90%</td></tr>
              </tbody>
            </table>
            <p>
              퍼센트는 raw 윈도가 아니라 <em>유효 프롬프트 예산</em>
              (<code>effective_prompt_budget_tokens</code> = 윈도에서 출력
              예비분 약 20K를 뺀 값) 기준입니다. 실제 대응은 프로바이더에 따라
              갈립니다.
            </p>
            <ul>
              <li>
                <strong>Anthropic</strong>. 경고 수준 압력은 서버 측 context
                management가 처리하므로 클라이언트는 개입하지 않습니다. 임계
                수준에서만 클라이언트가 비상 정리(prune)를 수행합니다.
              </li>
              <li>
                <strong>OpenAI / GLM</strong>. 서버 측 압축이 없어 클라이언트가
                3단계 압력 대응을 순차 실행합니다. (1) 값싼 도구 압축 — 오래된
                관측 마스킹(<code>mask_stale_observations</code>)과 큰 도구
                결과 요약(<code>summarize_tool_results</code>, LLM 호출 없음),
                (2) 구조화 LLM 압축(<code>compact_conversation</code>),
                (3) 압축으로 부족하거나 실패하면 적응형
                정리(<code>adaptive_prune</code>).
              </li>
            </ul>
            <ul>
              <li>
                컨텍스트 윈도가 200K를 넘는 모델에는 별도로 절대 200K 토큰
                천장(<code>absolute_ceiling_tokens</code>)이 걸립니다. 퍼센트
                임계와 무관하게 rate-limit 풀 분리를 피하려는 조치로, 도구 결과
                요약 후 필요하면 압축을 강제합니다.
              </li>
              <li>
                전략 선택은 <code>CONTEXT_OVERFLOW_ACTION</code> 훅 핸들러에
                위임되고, 등록된 핸들러가 없으면 해석된 policy가 폴백입니다.
                임계 상태에서는 <code>CONTEXT_CRITICAL</code> 훅이 발화합니다.
              </li>
              <li>
                정리 후에도 임계 상태면 루프는{" "}
                <code>context_exhausted</code>로 종료하고, 사용자 언어에 맞춘
                안내문을 생성해 돌려줍니다 (<code>core/agent/loop/models.py</code>).
              </li>
              <li>
                API가 400으로 컨텍스트 오버플로를 알리면 공격적 복구를 시도한 뒤
                재시도하고, 실패하면 역시 <code>context_exhausted</code>입니다.
              </li>
            </ul>
            <p>
              압축 장비는 <code>core/orchestration/compaction.py</code>와{" "}
              <code>core/orchestration/context_monitor.py</code>에 있고, 티어
              경계와 임계 상수는 <code>core/orchestration/context_budget.py</code>가
              SoT입니다. 모델별 컨텍스트 윈도 값은{" "}
              <code>core/llm/token_tracker.py</code>의{" "}
              <code>MODEL_CONTEXT_WINDOW</code>가 SoT입니다
              (<code>core/llm/model_pricing.toml</code>이 뒷받침).
            </p>

            <h2>대형 도구 결과: 오프로드</h2>
            <p>
              도구 결과가 5000 토큰 임계값을 넘으면{" "}
              <code>core/orchestration/tool_offload.py</code>의{" "}
              <code>ToolResultOffloadStore</code>가 결과를 디스크
              (<code>.geode/tool-offload/</code> 아래 세션 디렉터리)로 내리고,
              컨텍스트에는 요약과 <code>ref_id</code>만 남깁니다. 모델은 필요할
              때 <code>recall_tool_result(ref_id)</code> 경로로 원본을 다시 가져옵니다. 오프로드
              시 <code>TOOL_RESULT_OFFLOADED</code> 훅이 발화합니다.
            </p>

            <h2>장기 컨텍스트 아티팩트: dreaming</h2>
            <p>
              메시지 트랜스크립트와 별개로, 프로젝트별{" "}
              <code>sessions.db</code>(SQLite)에는 <code>context_artifacts</code>{" "}
              행이 쌓입니다. 합성된 장기 컨텍스트 기록으로, 턴 경로 밖에서
              만들어집니다. <code>core/memory/dreaming.py</code>의{" "}
              <code>DreamingService</code>가 <code>TURN_COMPLETED</code> 훅에서
              백그라운드로 동작합니다(best-effort — 포그라운드 턴을 절대 막지
              않습니다). 트랜스크립트를 증거로 삼아 지속 사실, 결정, 미해결 작업,
              낡은 리스크, 유용한 recall 질의, 인용을 정해진 헤딩으로 요약하고,{" "}
              <code>dream</code> 종류의 아티팩트로 되씁니다.{" "}
              <code>source_end_seq</code> 기준으로 멱등이라 새 메시지가 없으면
              건너뛰고, LLM을 못 쓰면 LLM 없는 로컬 요약으로 폴백합니다.
            </p>
            <p>
              주입은 경계가 있습니다. <code>ContextAssembler</code>의{" "}
              <code>_inject_long_context_artifacts</code>가 최신{" "}
              <code>compaction_summary</code>/<code>dream</code> 아티팩트 최대
              3개를 각 500자로 잘라 <code>_long_context_summary</code>로 넣습니다.{" "}
              <code>session_search</code> 도구는 <code>include_artifacts=true</code>
              (선택적 <code>artifact_kinds</code> 필터)로 FTS5 메시지 검색과 함께
              이 합성 아티팩트도 뒤집니다.
            </p>

            <h2>캐시를 깨지 않는 주입</h2>
            <p>
              현재 날짜와 라운드 번호 같은 턴별 정보는{" "}
              <code>core/agent/system_injection.py</code>의{" "}
              <code>append_system_reminder</code>가 요청별 복사본의{" "}
              <strong>마지막</strong> 메시지로 덧붙입니다. 공유 히스토리는
              변형되지 않으므로 메시지 prefix가 라운드 간 바이트 단위로
              안정적이고, Anthropic과 OpenAI의 prefix 캐싱이 적중합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>긴 세션에서 <code>context_exhausted</code> 종료</td>
                  <td>압축 후에도 히스토리가 임계 상태</td>
                  <td>새 세션을 열거나 <code>/compact</code>로 미리 압축합니다</td>
                </tr>
                <tr>
                  <td>도구 결과가 요약으로만 보임</td>
                  <td>5000 토큰 임계값을 넘어 오프로드됨</td>
                  <td>정상 동작입니다. <code>recall_tool_result(ref_id)</code>로 원본을 조회합니다</td>
                </tr>
                <tr>
                  <td>캐시 적중률이 갑자기 하락</td>
                  <td>히스토리 앞부분을 변형하는 커스텀 주입</td>
                  <td>주입은 append 방식만 사용합니다 (<code>append_system_reminder</code> 패턴)</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/memory/5-tier">메모리 계층</a>. 요약의 재료가 되는 5계층.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">프롬프트 조립</a>. 시스템 프롬프트 레이어의 SoT.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-caching">프롬프트 캐싱</a>. 정적/동적 경계가 만드는 비용 절감.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The context for one LLM call is built from three ingredients: a
              summary of the memory tiers, a layered system prompt, and the
              conversation history. This page covers how the three combine under
              a token budget, and what yields when the budget is exceeded.
            </p>

            <h2>Ingredient 1: memory tiers</h2>
            <p>
              <code>ContextAssembler</code> in <code>core/memory/context.py</code>{" "}
              merges the five memory tiers and builds the <code>_llm_summary</code>{" "}
              that prompt consumers read. Merge order is Identity, User
              Profile, Organization, Project, then Session; more specific
              tiers override earlier ones.
            </p>
            <table>
              <thead>
                <tr><th>Tier</th><th>Summary budget</th></tr>
              </thead>
              <tbody>
                <tr><td>Identity (SOUL.md)</td><td>10%</td></tr>
                <tr><td>User Profile</td><td>Included briefly when present</td></tr>
                <tr><td>Organization</td><td>25%</td></tr>
                <tr><td>Project</td><td>25%</td></tr>
                <tr><td>Session</td><td>The remainder, filled most-recent-first</td></tr>
              </tbody>
            </table>
            <p>
              After the tier merge, project type, recent run history, project
              journal, and Vault summaries can add compact reinforcement blocks.
              The tier structure and override rules live in{" "}
              <a href="/geode/docs/runtime/memory/5-tier">Memory tiers</a>.
            </p>

            <h2>Ingredient 2: system prompt layers</h2>
            <p>
              <code>build_system_prompt(model)</code> in{" "}
              <code>core/agent/system_prompt.py</code> assembles a cacheable
              static prefix and a per-turn dynamic section
              (<code>&lt;dynamic_context&gt;</code>) split by a boundary marker.
              Layer composition and modes are in{" "}
              <a href="/geode/docs/runtime/llm/prompt-system">Prompt assembly</a>;
              cache behaviour is in{" "}
              <a href="/geode/docs/runtime/llm/prompt-caching">Prompt caching</a>.
            </p>

            <h2>Overflow handling: what yields</h2>
            <p>
              At each round entry the loop delegates the overflow check to{" "}
              <code>ContextWindowManager</code> in{" "}
              <code>core/agent/context_manager.py</code>. Thresholds are not a
              fixed 80/95: <code>resolve_context_budget_policy</code> in{" "}
              <code>core/orchestration/context_budget.py</code> sizes a{" "}
              <code>ContextBudgetPolicy</code> to the model’s context window and
              picks one of three tiers.
            </p>
            <table>
              <thead>
                <tr><th>Tier</th><th>Window range</th><th>Warning</th><th>Critical</th></tr>
              </thead>
              <tbody>
                <tr><td>small</td><td>≤ 256K</td><td>50%</td><td>90%</td></tr>
                <tr><td>standard</td><td>≤ 512K</td><td>70%</td><td>90%</td></tr>
                <tr><td>large</td><td>&gt; 512K</td><td>80%</td><td>90%</td></tr>
              </tbody>
            </table>
            <p>
              The percentages are taken against the <em>effective prompt
              budget</em> (<code>effective_prompt_budget_tokens</code> = window
              minus a ~20K output reserve), not the raw window. The response
              itself is provider-aware.
            </p>
            <ul>
              <li>
                <strong>Anthropic</strong>. Warning-level pressure is handled by
                server-side context management, so the client stays out. Only at
                critical pressure does the client step in with an emergency
                prune.
              </li>
              <li>
                <strong>OpenAI / GLM</strong>. No server-side compaction, so the
                client runs a three-stage escalation under pressure.
                (1) Cheap tool compression — mask stale observations
                (<code>mask_stale_observations</code>) and summarize large tool
                results (<code>summarize_tool_results</code>), no LLM call;
                (2) structured LLM compaction (<code>compact_conversation</code>);
                (3) adaptive prune (<code>adaptive_prune</code>) when compaction
                is not enough or fails.
              </li>
            </ul>
            <ul>
              <li>
                For models whose window exceeds 200K, a separate absolute
                200K-token ceiling (<code>absolute_ceiling_tokens</code>)
                applies. Independent of the percentage thresholds, it avoids
                rate-limit pool separation by summarizing tool results and then
                compacting if needed.
              </li>
              <li>
                Strategy resolution is delegated to a{" "}
                <code>CONTEXT_OVERFLOW_ACTION</code> hook handler; when none is
                registered, the resolved policy is the fallback. A{" "}
                <code>CONTEXT_CRITICAL</code> hook fires on critical pressure.
              </li>
              <li>
                If the context is still critical after pruning, the loop returns{" "}
                <code>context_exhausted</code> with a language-matched notice
                (<code>core/agent/loop/models.py</code>).
              </li>
              <li>
                A 400-class API error flagged as context overflow triggers
                aggressive recovery and a retry; failure ends in{" "}
                <code>context_exhausted</code> too.
              </li>
            </ul>
            <p>
              The compaction machinery lives in{" "}
              <code>core/orchestration/compaction.py</code> and{" "}
              <code>core/orchestration/context_monitor.py</code>; the tier
              boundaries and thresholds are owned by{" "}
              <code>core/orchestration/context_budget.py</code>. Per-model
              context windows come from <code>MODEL_CONTEXT_WINDOW</code> in{" "}
              <code>core/llm/token_tracker.py</code>, backed by{" "}
              <code>core/llm/model_pricing.toml</code>.
            </p>

            <h2>Large tool results: offload</h2>
            <p>
              When a tool result exceeds the 5000-token threshold,{" "}
              <code>ToolResultOffloadStore</code> in{" "}
              <code>core/orchestration/tool_offload.py</code> persists it to disk
              (a per-session directory under <code>.geode/tool-offload/</code>)
              and leaves only a summary plus a <code>ref_id</code> in context.
              The model re-fetches the original with{" "}
              <code>recall_tool_result(ref_id)</code> when needed. Each offload fires the{" "}
              <code>TOOL_RESULT_OFFLOADED</code> hook.
            </p>

            <h2>Long-context artifacts: dreaming</h2>
            <p>
              Separate from the message transcript, the per-project{" "}
              <code>sessions.db</code> (SQLite) accumulates{" "}
              <code>context_artifacts</code> rows — synthesized long-context
              records built off the turn path. <code>DreamingService</code> in{" "}
              <code>core/memory/dreaming.py</code> runs on the{" "}
              <code>TURN_COMPLETED</code> hook in the background (best-effort; it
              never blocks the foreground turn). Using the transcript as
              evidence, it synthesizes durable facts, decisions, unresolved
              tasks, stale risks, useful recall queries, and citations under
              fixed headings, and writes them back as a <code>dream</code>{" "}
              artifact. It is idempotent by <code>source_end_seq</code> (skips
              when there is nothing new) and falls back to a local, LLM-free
              summary when no LLM is available.
            </p>
            <p>
              Injection is bounded. <code>_inject_long_context_artifacts</code>{" "}
              in <code>ContextAssembler</code> pulls the latest three{" "}
              <code>compaction_summary</code>/<code>dream</code> artifacts,
              truncates each to 500 chars, and feeds them as{" "}
              <code>_long_context_summary</code>. The <code>session_search</code>
              {" "}tool surfaces them too: with{" "}
              <code>include_artifacts=true</code> (and an optional{" "}
              <code>artifact_kinds</code> filter) it searches these synthesized
              artifacts alongside the FTS5 message hits.
            </p>

            <h2>Injection that does not break caching</h2>
            <p>
              Per-turn information such as the current date and round number is
              appended by <code>append_system_reminder</code>{" "}
              (<code>core/agent/system_injection.py</code>) as the{" "}
              <strong>last</strong> message of a per-request copy. The shared
              history is never mutated, so the message prefix stays byte-stable
              across rounds and Anthropic and OpenAI prefix caching can hit.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Long sessions end with <code>context_exhausted</code></td>
                  <td>History remains critical even after compaction</td>
                  <td>Start a fresh session, or compact early with <code>/compact</code></td>
                </tr>
                <tr>
                  <td>A tool result shows up only as a summary</td>
                  <td>It crossed the 5000-token threshold and was offloaded</td>
                  <td>Working as intended; fetch the original with <code>recall_tool_result(ref_id)</code></td>
                </tr>
                <tr>
                  <td>Cache hit rate suddenly drops</td>
                  <td>A custom injection mutates the front of the history</td>
                  <td>Only inject by appending (the <code>append_system_reminder</code> pattern)</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/memory/5-tier">Memory tiers</a>. The five tiers that feed the summary.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">Prompt assembly</a>. The source of truth for system-prompt layers.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-caching">Prompt caching</a>. The savings the static/dynamic boundary buys.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
