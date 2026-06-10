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
              5계층 메모리를 하나의 요약으로 접습니다. <code>max_chars</code>
              예산에 맞출 때 계층별 비례 배분을 씁니다.
            </p>
            <table>
              <thead>
                <tr><th>계층</th><th>예산</th></tr>
              </thead>
              <tbody>
                <tr><td>Identity (SOUL.md)</td><td>10%</td></tr>
                <tr><td>Organization</td><td>25%</td></tr>
                <tr><td>Project</td><td>25%</td></tr>
                <tr><td>Session</td><td>나머지. 최신 항목부터 채웁니다</td></tr>
              </tbody>
            </table>
            <p>
              계층 자체의 구조와 override 규칙은{" "}
              <a href="/geode/docs/runtime/memory/5-tier">메모리 계층</a>에서
              다룹니다.
            </p>

            <h2>재료 2: 시스템 프롬프트 레이어</h2>
            <p>
              <code>core/agent/system_prompt.py</code>의{" "}
              <code>build_system_prompt(model)</code>이 캐시 가능한 정적
              섹션(<code>&lt;static_context&gt;</code>)과 턴마다 바뀌는 동적
              섹션(<code>&lt;dynamic_context&gt;</code>)을 경계 마커로 나눠
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
              전략은 프로바이더별로 다릅니다.
            </p>
            <table>
              <thead>
                <tr><th>프로바이더</th><th>80% 이상</th><th>95% 이상</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic</td>
                  <td>서버 측 압축(context management)이 처리</td>
                  <td>클라이언트가 비상 정리(emergency prune)만 수행</td>
                </tr>
                <tr>
                  <td>OpenAI / GLM</td>
                  <td>클라이언트 LLM 기반 압축</td>
                  <td>비상 정리</td>
                </tr>
              </tbody>
            </table>
            <ul>
              <li>
                컨텍스트 윈도가 200K를 넘는 모델이라도 절대 200K 토큰 천장을
                둡니다. rate-limit 풀 분리를 피하기 위한 조치로, 도구 결과
                요약과 압축을 강제합니다.
              </li>
              <li>
                전략 선택은 <code>CONTEXT_OVERFLOW_ACTION</code> 훅 핸들러에
                위임되고, 등록된 핸들러가 없으면 하드코딩 폴백이 동작합니다.
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
              <code>core/orchestration/context_monitor.py</code>에 있습니다.
              모델별 컨텍스트 윈도 값은 <code>core/llm/token_tracker.py</code>의{" "}
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
              때 <code>recall(ref_id)</code>로 원본을 다시 가져옵니다. 오프로드
              시 <code>TOOL_RESULT_OFFLOADED</code> 훅이 발화합니다.
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
                  <td>정상 동작입니다. <code>recall(ref_id)</code>로 원본을 조회합니다</td>
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
              folds the five memory tiers into one summary. When fitting under{" "}
              <code>max_chars</code> it uses proportional budgets per tier.
            </p>
            <table>
              <thead>
                <tr><th>Tier</th><th>Budget</th></tr>
              </thead>
              <tbody>
                <tr><td>Identity (SOUL.md)</td><td>10%</td></tr>
                <tr><td>Organization</td><td>25%</td></tr>
                <tr><td>Project</td><td>25%</td></tr>
                <tr><td>Session</td><td>The remainder, filled most-recent-first</td></tr>
              </tbody>
            </table>
            <p>
              The tier structure and override rules live in{" "}
              <a href="/geode/docs/runtime/memory/5-tier">Memory tiers</a>.
            </p>

            <h2>Ingredient 2: system prompt layers</h2>
            <p>
              <code>build_system_prompt(model)</code> in{" "}
              <code>core/agent/system_prompt.py</code> assembles a cacheable
              static section (<code>&lt;static_context&gt;</code>) and a per-turn
              dynamic section (<code>&lt;dynamic_context&gt;</code>) split by a
              boundary marker. Layer composition and modes are in{" "}
              <a href="/geode/docs/runtime/llm/prompt-system">Prompt assembly</a>;
              cache behaviour is in{" "}
              <a href="/geode/docs/runtime/llm/prompt-caching">Prompt caching</a>.
            </p>

            <h2>Overflow handling: what yields</h2>
            <p>
              At each round entry the loop delegates the overflow check to{" "}
              <code>ContextWindowManager</code> in{" "}
              <code>core/agent/context_manager.py</code>. The strategy is
              provider-aware.
            </p>
            <table>
              <thead>
                <tr><th>Provider</th><th>At 80%+</th><th>At 95%+</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic</td>
                  <td>Server-side compaction (context management) handles it</td>
                  <td>Client performs an emergency prune only</td>
                </tr>
                <tr>
                  <td>OpenAI / GLM</td>
                  <td>Client-side LLM-based compaction</td>
                  <td>Emergency prune</td>
                </tr>
              </tbody>
            </table>
            <ul>
              <li>
                Even for models whose window exceeds 200K, an absolute 200K-token
                ceiling applies. It avoids rate-limit pool separation by forcing
                tool-result summarization and compaction.
              </li>
              <li>
                Strategy resolution is delegated to a{" "}
                <code>CONTEXT_OVERFLOW_ACTION</code> hook handler, with a
                hardcoded fallback when none is registered. A{" "}
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
              <code>core/orchestration/context_monitor.py</code>. Per-model
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
              <code>recall(ref_id)</code> when needed. Each offload fires the{" "}
              <code>TOOL_RESULT_OFFLOADED</code> hook.
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
                  <td>Working as intended; fetch the original with <code>recall(ref_id)</code></td>
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
