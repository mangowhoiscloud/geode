import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Context assembly — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/context"
      title="Context assembly"
      titleKo="컨텍스트 조립"
      summary="The live system-prompt path and the explicit five-tier context facade, under a token budget."
      summaryKo="실제 시스템 프롬프트 경로와 명시적 5계층 context facade를 토큰 예산과 함께 설명합니다."
    >
      <Bi
        ko={
          <>
            <p>
              기본 AgenticLoop의 모델 컨텍스트는 레이어로 조립된 시스템
              프롬프트와 대화 히스토리로 만들어집니다. 이와 별도로
              GeodeRuntime은 명시적 소비자를 위한 5계층 context facade를
              제공합니다. 이 페이지는 두 경계를 구분하고, 토큰 예산을 넘으면
              무엇이 양보하는지 정리합니다.
            </p>

            <h2>명시적 facade: 메모리 계층</h2>
            <p>
              <code>core/memory/context.py</code>의 <code>ContextAssembler</code>가
              5계층 메모리를 병합해 <code>_llm_summary</code>가 포함된 dict를
              만듭니다. 이 경로는 <code>GeodeRuntime.assemble_context()</code>를
              호출할 때만 실행되며 기본 AgenticLoop prompt에는 자동 연결되지
              않습니다. 병합은 Identity, User Profile, Organization, Project,
              Session 순서로 흐릅니다.
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

            <h2>실제 모델 경로: 시스템 프롬프트 레이어</h2>
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

            <h2>오버플로 처리: 요청 경로와 복구</h2>
            <p>
              공통 요청 경로는 미들웨어와 도구 허용 목록 적용 뒤의 모델·공급자·
              source·출력 예비분으로 예산을 정합니다. 요청이 원래 대화를 유지하면{" "}
              <code>ContextWindowManager</code>가 한 번만 유지보수를 수행합니다.
              미들웨어가 대화를 교체했다면 원래 세션을 대신 요약하지 않습니다.
              최종 적합성 검사는 읽기 전용이며, 훅이나 요약을 다시 실행하지 않습니다.
              이 준비 경계는 루트와 보조 모델 호출이 공유합니다.
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
              퍼센트의 기준은 윈도에서 요청의 출력 예비분을 빼고, 알려진 입력
              상한도 적용한 <em>유효 프롬프트 예산</em>입니다. Codex 구독 경로는
              Platform 출력 매개변수를 보내지 않으므로 로컬 계획용 예비분을 씁니다.
              카탈로그 값·클라이언트 기본값·미상 경로 폴백은 실제 계정의 서버 허용량과
              구분합니다. API의 한도를 구독 경로에 그대로 적용하거나 OpenRouter를
              동명의 직접 공급자 모델로 간주하지 않습니다.
            </p>
            <p>
              추정에는 시스템 지침, 실제 도구 스키마, 재전송할 native 내용이
              포함됩니다. 암호화된 내용과 이미지의 크기는 추정치이며 청구 토큰이
              아닙니다. 지원되는 Anthropic PAYG 경로에서는 마지막 성공한 native
              compaction 블록부터 활성 문맥을 추정하되 저장된 재전송 바이트는
              보존합니다. 비어 있거나 실패한 블록은 성공한 압축으로 보지 않습니다.
            </p>
            <ul>
              <li>
                <strong>Anthropic</strong>. 지원 모델의 자동 threshold compaction은
                유지합니다. Tool-result clearing은 별도 지원 목록을 따릅니다.
                알려진 Haiku 4.5·Sonnet 4.5·Opus 4.5처럼 threshold compaction이 없는
                모델은 클라이언트 요약을 사용할 수 있습니다. 수동 압축과 실제
                오버플로 복구도 알려진 모델의 호환 이력에서 가능하지만, native
                compaction 블록이 있거나 모델 계약이 미상이면 텍스트 교체와
                강제 정리를 막습니다. Signed thinking과 도구 호출·결과 쌍을
                임의로 삭제하지 않습니다.
              </li>
              <li>
                <strong>OpenAI / Codex / GLM / OpenRouter</strong>. 현재는 GEODE의
                클라이언트 텍스트 요약 경로입니다. 값싼 관측 마스킹과 도구 결과 축소,
                구조화 요약, 명시적인 hard 경계의 보호된 정리 순으로 처리합니다.
                공개 native API가 있다는 사실만으로 GEODE 연결이나 구독 사용
                권한이 입증되지는 않습니다.
              </li>
              <li>
                <strong>200K</strong>는 로컬의 soft 유지보수 선호입니다.
                모든 공급자의 입력 상한이나 rate-limit 풀 경계가 아니며,
                이를 넘었다는 이유만으로 이력을 강제 삭제하지 않습니다.
              </li>
            </ul>
            <p>
              전략은 컨텍스트 소유자가 결정합니다. <code>PreCompact</code>는{" "}
              <code>keep_recent</code>만 바꾸거나 soft 요약을 유예할 수 있고,
              모델·공급자·trigger·hard는 바꿀 수 없습니다.{" "}
              <code>PostCompact</code>는 이력 교체와 호출자가 제공한 체크포인트
              콜백 뒤에 실행됩니다. <code>persisted</code>는 요약 아티팩트의
              저장 여부이며, 세션 전체가 원자적으로 저장됐다는 뜻은 아닙니다.
              관측 훅은 공급자 허용량이나 복구 전략을 결정하지 않습니다.
            </p>
            <p>
              공급자가 입력 초과를 확인하면 로컬 추정이 낮아도 제한된 복구를
              시도합니다. 메시지 개수가 같아도 내용은 줄어들 수 있으므로 작업
              결과로 진행 여부를 판단하고, 다음 실제 요청의 수락 여부는 별도로
              확인합니다. 복구가 불가능하거나 한도를 소진하면{" "}
              <code>context_exhausted</code>로 끝납니다. 안내문은 추가 모델 호출
              없이 반환하며, 모든 진입점에서 세션이 자동 초기화된다고 주장하지 않습니다.
            </p>
            <p>
              메시지가 30개를 넘었다는 이유만으로 이력을 버리지 않습니다.
              별도의 <code>ConversationContext.max_turns</code> 한도는 유지합니다.
              가장 최근의 명시적 원본 사용자 입력, 인과 관계가 있는 도구 쌍,
              마지막 도구 묶음의 <code>use_skill</code> 결과를 보호합니다.
              soft 요약·저장이 실패하면 입력을 유지하되 앞선 관측 마스킹까지
              되돌리지는 않습니다. 보호된 tail이 여전히 한도를 넘으면 종료할 수
              있으며, 보호가 모델 용량을 늘리지는 않습니다.
            </p>
            <p>
              예산은 <code>core/orchestration/context_budget.py</code>, 경로별
              모델 정보는 <code>core/llm/model_catalog.py</code>, 변환은{" "}
              <code>core/orchestration/compaction.py</code>가 소유합니다.
              이 설명의 9월 25일 변경은 Unreleased입니다. 실제 공급자의 요청 수락과
              사용량은 로컬 회귀 검사와 별도로 검증해야 합니다.
            </p>

            <h2>대형 도구 결과: 오프로드</h2>
            <p>
              모델에 전달할 도구 결과가 기본 15,000 토큰 임계값을 넘으면{" "}
              <code>core/orchestration/tool_offload.py</code>의{" "}
              <code>ToolResultOffloadStore</code>가 결과를 디스크
              (<code>.geode/tool-offload/</code> 아래 세션 디렉터리)로 내리고,
              컨텍스트에는 요약과 <code>ref_id</code>만 남깁니다. 모델은 필요할
              때 <code>recall_tool_result(ref_id)</code> 경로로 원본을 다시 가져옵니다. 오프로드
              시 <code>TOOL_RESULT_OFFLOADED</code> 훅이 발화합니다.
            </p>
            <p>
              MCP의 <code>CallToolResult</code>는 호환성을 위해 같은 값을{" "}
              <code>content</code>와 <code>structuredContent</code>에 함께 담을 수
              있습니다. 원본은 session timeline과 tool log에 receipt로 그대로
              남기고, 모델 경계에서는 structured 값을 우선해 한 표현만 고른 뒤
              오프로드와 25,000-token hard guard를 적용합니다. 따라서 증거는
              보존하면서 중복 JSON을 컨텍스트에 다시 넣지 않습니다.
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

            <h2>캐시를 깨지 않는 이력</h2>
            <p>
              날짜와 runtime rule은 <code>system_prompt.py</code>의 동적
              시스템 영역에 한 번 조립됩니다. 라운드별 reminder message는
              만들지 않으며, 대화 이력에는 실제 user, assistant, tool turn만
              append합니다. 그래서 다음 요청이 이전 요청의 메시지열을 정확한
              prefix로 보존하고 Anthropic·OpenAI 캐시가 재사용할 수 있습니다.
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
                  <td>새 세션을 열거나 <code>/compact</code>로 현재 세션을 요약합니다. <code>--prune</code>일 때만 명시적으로 이력을 정리합니다</td>
                </tr>
                <tr>
                  <td>도구 결과가 요약으로만 보임</td>
                  <td>15,000 토큰 임계값을 넘어 오프로드됨</td>
                  <td>정상 동작입니다. <code>recall_tool_result(ref_id)</code>로 원본을 조회합니다</td>
                </tr>
                <tr>
                  <td>캐시 적중률이 갑자기 하락</td>
                  <td>히스토리 앞부분을 변형하는 커스텀 주입</td>
                  <td>턴별 메타데이터는 시스템 동적 영역에 두고, 대화에는 실제 turn만 append합니다</td>
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
              The default AgenticLoop model context combines a layered system
              prompt with conversation history. Separately, GeodeRuntime exposes
              a five-tier context facade to explicit callers. This page keeps
              those boundaries distinct and explains what yields when the token
              budget is exceeded.
            </p>

            <h2>Explicit facade: memory tiers</h2>
            <p>
              <code>ContextAssembler</code> in <code>core/memory/context.py</code>{" "}
              merges the five memory tiers and builds a dict containing
              <code>_llm_summary</code>. This path runs only through
              <code>GeodeRuntime.assemble_context()</code>; it is not
              automatically connected to the default AgenticLoop prompt. Merge
              order is Identity, User Profile, Organization, Project, then
              Session.
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

            <h2>Live model path: system prompt layers</h2>
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

            <h2>Overflow handling: request routes and recovery</h2>
            <p>
              The shared request path resolves the model, provider, source and
              output reserve after request middleware and tool allowlists.{" "}
              <code>ContextWindowManager</code> performs maintenance once when
              the request retains the caller&apos;s conversation. A middleware-owned
              replacement cannot cause the original session to be summarized.
              The final fit check is read-only: it does not repeat hooks or
              summarization. Root and auxiliary calls share this boundary.
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
              Percentages use the <em>effective prompt budget</em>: the selected
              window minus the requested output reserve, bounded by a known input
              cap. Codex omits the Platform output parameter and uses a local
              planning reserve. Catalogue values, client defaults and unknown-route
              fallbacks do not establish an account&apos;s server allowance.
              API limits do not automatically describe subscriptions, and an
              OpenRouter route is not a same-named direct-provider route.
            </p>
            <p>
              Estimation includes system instructions, actual tool schemas and
              replayed native content. Opaque content and images remain estimates,
              not billed tokens. Supported Anthropic PAYG routes estimate active
              context from the last successful native compaction block while
              preserving stored replay bytes. Empty or failed blocks are not
              successful compactions.
            </p>
            <ul>
              <li>
                <strong>Anthropic</strong>. Automatic threshold compaction remains
                enabled for supported models. Tool-result clearing has a separate
                capability list. Known models without threshold compaction,
                including Haiku 4.5, Sonnet 4.5 and Opus 4.5, can use client summaries.
                Manual and actual-overflow recovery can also summarize compatible
                histories on known models. Unknown model contracts or native
                compaction blocks guard against text replacement and pruning.
                Signed thinking and causal tool pairs must not be discarded.
              </li>
              <li>
                <strong>OpenAI / Codex / GLM / OpenRouter</strong>. Current
                integration uses GEODE&apos;s client text path: cheap observation
                masking and tool-result reduction, structured summarization,
                then protected pruning at explicit hard boundaries.
                A public native API does not establish GEODE integration or
                subscription authorization.
              </li>
              <li>
                <strong>200K</strong> is a soft local maintenance preference.
                It is not a universal provider input cap or rate-limit-pool
                boundary; crossing it alone does not force history deletion.
              </li>
            </ul>
            <p>
              The context owner selects the strategy. <code>PreCompact</code>{" "}
              may change only <code>keep_recent</code> or defer soft summarization;
              model, provider, trigger and hard are read-only.{" "}
              <code>PostCompact</code> follows history replacement and any
              caller-supplied checkpoint callback. <code>persisted</code> means
              the summary artifact was stored, not that the whole session committed
              atomically. Observers do not decide provider allowance or recovery.
            </p>
            <p>
              A classified provider input overflow starts bounded recovery even
              when the local estimate is low. Equal message counts can still
              contain less content, so operation status determines progress.
              Acceptance of the next actual request is separate evidence.
              Unrecoverable or exhausted recovery ends as{" "}
              <code>context_exhausted</code>. A local notice uses no additional
              model call and does not claim every entry point resets its session.
            </p>
            <p>
              Thirty messages alone do not discard history; the separate{" "}
              <code>ConversationContext.max_turns</code> limit remains.
              The latest explicitly marked original user input, causal tool pairs
              and fresh <code>use_skill</code> output are protected.
              A failed soft summary or persistence step retains input, without
              undoing earlier observation masking. The protected tail can still
              exceed the budget: protection does not expand model capacity.
            </p>
            <p>
              Owners are <code>core/orchestration/context_budget.py</code> for
              budgets, <code>core/llm/model_catalog.py</code> for route metadata,
              and <code>core/orchestration/compaction.py</code> for transformation.
              The September 25 changes described here are Unreleased.
              Actual provider acceptance and usage require verification separate
              from local regression tests.
            </p>

            <h2>Large tool results: offload</h2>
            <p>
              When the model-facing tool result exceeds the default
              15,000-token threshold,{" "}
              <code>ToolResultOffloadStore</code> in{" "}
              <code>core/orchestration/tool_offload.py</code> persists it to disk
              (a per-session directory under <code>.geode/tool-offload/</code>)
              and leaves only a summary plus a <code>ref_id</code> in context.
              The model re-fetches the original with{" "}
              <code>recall_tool_result(ref_id)</code> when needed. Each offload fires the{" "}
              <code>TOOL_RESULT_OFFLOADED</code> hook.
            </p>
            <p>
              MCP <code>CallToolResult</code> may repeat one value in both
              <code>content</code> and <code>structuredContent</code> for
              compatibility. The raw envelope stays intact in the session
              timeline and tool log as a receipt. At the model boundary GEODE
              prefers the structured value, selects one representation, then
              applies offload and the 25,000-token hard guard. Evidence is
              preserved without replaying duplicate JSON into context.
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

            <h2>History that does not break caching</h2>
            <p>
              Date and runtime rules are assembled once in the dynamic system
              region in <code>system_prompt.py</code>. There is no per-round
              reminder message; only real user, assistant, and tool turns are
              appended. The next request therefore preserves the previous
              message sequence as an exact prefix for Anthropic and OpenAI
              caching.
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
                  <td>Start a fresh session, or summarize the current session with <code>/compact</code>. Add <code>--prune</code> only when explicitly requesting lossful history reduction</td>
                </tr>
                <tr>
                  <td>A tool result shows up only as a summary</td>
                  <td>It crossed the 15,000-token threshold and was offloaded</td>
                  <td>Working as intended; fetch the original with <code>recall_tool_result(ref_id)</code></td>
                </tr>
                <tr>
                  <td>Cache hit rate suddenly drops</td>
                  <td>A custom injection mutates the front of the history</td>
                  <td>Keep per-turn metadata in the dynamic system region and append only real conversation turns</td>
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
