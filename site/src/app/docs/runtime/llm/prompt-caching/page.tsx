import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Prompt caching — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-caching"
      title="Prompt caching"
      titleKo="프롬프트 캐싱"
      summary="Stable prefixes, bounded rolling markers, and provider-reported cache usage across request lifecycles."
      summaryKo="정적 프리픽스, 제한된 롤링 마커, 요청 생명주기에 따른 캐시 사용량을 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              프롬프트 캐싱은 prefix 매치입니다. 요청 앞부분이 직전 호출과
              바이트 단위로 같아야 적중합니다. GEODE의 캐싱 설계는 이 한
              문장에서 다 나옵니다. 변하지 않는 것을 앞에, 변하는 것을 뒤에
              두고, 턴마다 바뀌는 조각이 prefix를 다시 키잉하지 못하게
              막습니다.
            </p>

            <h2>static/dynamic 경계</h2>
            <p>
              시스템 프롬프트는 <code>core/agent/system_prompt.py</code>의
              <code>PROMPT_CACHE_BOUNDARY</code>
              마커(<code>&lt;dynamic_context&gt;</code> 여는 태그)로 두 쪽이
              납니다. 마커 앞은 턴 사이 불변(베이스 스캐폴드, 스타일 가이드,
              기본 ON identity), 마커 뒤는 턴마다 변합니다(model card, 날짜,
              메모리 레이어, 사용자 컨텍스트).
            </p>
            <p>
              Anthropic 요청 생성기(<code>core/llm/adapters/_anthropic_common.py</code>)가
              정적 블록에 기본 <code>{`cache_control: {"type": "ephemeral", "ttl": "1h"}`}</code>을
              붙입니다. <code>prompt_cache_extended_ttl=false</code>는 5분 TTL을
              선택합니다. 동적 블록에는 별도 마커를 붙이지 않지만, 뒤쪽 메시지
              마커가 만드는 누적 프리픽스에는 포함됩니다. 정적 영역이 비면 빈
              텍스트 오류를 피해 동적 블록에 5분 마커 하나를 사용합니다.
            </p>

            <h2>OpenAI·Z.AI·OpenRouter의 경계</h2>
            <p>
              OpenAI Platform의 등록된 GPT-5.6·GPT-6 모델은 같은 경계 앞의
              정적 문자열을 developer 메시지의 input_text 블록으로 보내고
              <code>prompt_cache_breakpoint</code>를 붙입니다. 동적 문자열은
              그 뒤에 두며, 대화 이력의 자동 캐싱도 유지합니다. Codex 구독
              경로와 이전 모델은 기존 instructions 및 캐시 키 계약을 유지합니다.
              키가 같다는 사실만으로 적중을 보장하지는 않습니다.
            </p>
            <p>
              Z.AI는 반복 접두부를 자동으로 캐싱하며 별도 캐시 마커를 보내지
              않습니다. OpenRouter의 명시적 Claude·지원 OpenAI 경로에는 해당
              마커를 보존합니다. 논리 세션 ID의 해시로 제공자 선택의 연속성을
              요청하고, 원래 세션 ID는 보내지 않습니다. 사용자가 설정한 제공자
              우선순위는 유지하며, 자동 모델 선택에 특정 제공자 마커를 추측해
              넣지 않습니다.
            </p>
            <p>
              SDK 연결을 닫거나 다시 만들어도 서버의 캐시를 삭제하지 않습니다.
              모델·계정·도구 순서·출력 스키마·추론 설정·정리된 이력이 달라지면
              공유 접두부도 달라질 수 있습니다. 실제 적중은 반환된 사용량으로
              확인하며, 누락된 값과 0을 구분합니다. 정책 근거는 2026-09-24에
              확인한 <a href="https://developers.openai.com/api/docs/guides/prompt-caching">OpenAI</a>,{" "}
              <a href="https://docs.z.ai/guides/capabilities/cache">Z.AI</a>,{" "}
              <a href="https://openrouter.ai/docs/guides/best-practices/prompt-caching">OpenRouter</a>
              공식 문서입니다.
            </p>

            <h2>롤링 메시지 breakpoint</h2>
            <p>
              요청 전체의 도구·시스템·메시지 마커는 최대 4개입니다. 정적 시스템
              블록이 1개를 사용하고, <code>apply_messages_cache_control</code>이
              기존 마커를 보존한 뒤 남은 슬롯에서 기본 최대 3개를 추가합니다.
              <code>cache-policy</code>의 <code>messages_breakpoints</code>는
              추가할 수를 0–3으로 제한합니다. thinking·redacted_thinking과 빈
              텍스트에는 직접 마커를 붙이지 않습니다. 명시적 1시간 마커는 5분
              마커보다 앞에 있어야 하며, 잘못된 입력은 호출 전에 거절합니다.
            </p>
            <p>
              마커 자체에는 별도 요금이 없습니다. Anthropic 표준 API 요율은
              5분 쓰기 1.25배, 1시간 쓰기 2배이며 읽기 할인은 모델별 단가표를
              따릅니다. 잦은 적중은 5분 TTL도 무료로 갱신하므로 1시간의 이득은
              재사용 간격에 달려 있습니다. GEODE는 응답의 1시간 쓰기량을 비용과
              영구 이벤트에 보존합니다. 과거 기록의 TTL 미상은 0으로 바꾸지 않으며,
              그 기록의 추정 비용은 기존 5분 요율을 유지합니다.
            </p>
            <p>
              동적 시스템 내용이 바뀌면 정적 마커까지는 재사용할 수 있지만 뒤쪽
              메시지 프리픽스는 달라집니다. 도구 정의, 모델, thinking·effort 변경,
              컨텍스트 정리도 영향을 줄 수 있습니다. 이는 새 요청의 정확성을
              위한 무효화이며 캐시 적중을 보장하지 않습니다. 공급자가 보유한
              캐시는 로컬 SDK 클라이언트를 닫는 동작과 별개의 수명을 가집니다.
            </p>

            <h2>대화 이력은 실제 turn만 append</h2>
            <p>
              AgenticLoop는 라운드 번호나 날짜를 합성 user message로 만들지
              않습니다. 날짜와 runtime rule은 이미{" "}
              <code>core/agent/system_prompt.py</code>의 동적 시스템 영역에 있고,
              일반적인 대화 라운드는 user, assistant, tool 메시지를 뒤에
              붙여 기존 프리픽스를 유지합니다. 컨텍스트 복구나 명시적 제어
              전환은 이력을 바꿀 수 있으므로 별도로 확인합니다.
            </p>
            <ul>
              <li>
                턴마다 바뀌는 시스템 정보는 메시지 이력에 중복 주입하지
                않습니다.
              </li>
              <li>
                컨텍스트 정리는 공유 이력을 직접 갱신하고, 그 뒤 adapter
                request를 조립합니다.
              </li>
            </ul>
            <p>
              이 계약은 연속 <code>AgenticLoop._call_llm</code> 요청의 실제{" "}
              <code>AdapterCallRequest.messages</code> prefix를 비교하는 회귀
              테스트로 고정합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>cache_read가 늘 0</td>
                  <td>prefix가 매 호출 변함. static 영역에 턴별 값이 새어 들어간 경우</td>
                  <td>턴마다 변하는 값은 경계 마커 뒤로 옮깁니다.</td>
                </tr>
                <tr>
                  <td>짧은 작업의 비용 증가</td>
                  <td>재사용 전에 TTL 만료 또는 프리픽스 변경</td>
                  <td>안정적인 구간과 재사용 간격을 확인하고 필요한 TTL을 선택합니다.</td>
                </tr>
                <tr>
                  <td>400: empty text block에 cache_control</td>
                  <td>빈 static에 breakpoint를 붙이려는 시도</td>
                  <td>어댑터가 dynamic 승격으로 처리합니다. 직접 어댑터를 다룰 때만 해당합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/system-prompt-modes">시스템 프롬프트 모드</a>. static 영역에 무엇이 실리는지.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-hashing">프롬프트 해싱</a>. static 템플릿의 drift 가드.</li>
              <li><a href="/geode/docs/ops/cost">비용 모니터링</a>. 캐시 적중이 보이는 곳.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Prompt caching is a prefix match: the head of the request must
              be byte-identical to the previous call to hit. All of
              GEODE&apos;s caching design follows from that one sentence. Put
              what does not change first, what changes last, and stop
              per-turn fragments from re-keying the prefix.
            </p>

            <h2>The static/dynamic boundary</h2>
            <p>
              The system prompt splits at the
              <code>PROMPT_CACHE_BOUNDARY</code> marker (the opening
              <code>&lt;dynamic_context&gt;</code> tag) defined in
              <code>core/agent/system_prompt.py</code>. Everything before the
              marker is stable across turns (base scaffold, style guide,
              default-on identity); everything after changes per turn (model
              card, date, memory layers, user context).
            </p>
            <p>
              The Anthropic request builder
              (<code>core/llm/adapters/_anthropic_common.py</code>) marks the
              static block with <code>{`cache_control: {"type": "ephemeral", "ttl": "1h"}`}</code>
              by default. <code>prompt_cache_extended_ttl=false</code> selects
              five minutes. The dynamic block has no separate marker, but is
              included in the cumulative prefix of later message markers. An
              empty static section falls back to one five-minute dynamic marker.
            </p>

            <h2>OpenAI, Z.AI and OpenRouter boundaries</h2>
            <p>
              Registered GPT-5.6 and GPT-6 models on OpenAI Platform receive the
              static prefix in a developer input_text block with an explicit
              <code>prompt_cache_breakpoint</code>. The dynamic text follows it;
              implicit conversation caching remains enabled. Codex subscription
              and earlier models retain their existing instructions and cache-key
              contract. A matching key alone does not establish cache reuse.
            </p>
            <p>
              Z.AI caches repeated prefixes automatically without cache markers.
              Explicit Claude and supported OpenAI routes through OpenRouter
              retain their corresponding markers. A hash of the logical session
              ID requests provider affinity without sending the raw ID. Explicit
              provider ordering remains intact; automatic model selection does
              not guess an upstream cache protocol.
            </p>
            <p>
              Closing or recreating an SDK client does not delete a provider cache.
              Model, account, tool order, output schema, reasoning settings and
              compacted history can change the reusable prefix. Observe actual
              reuse through returned usage, preserving missing values separately
              from zero. Policy sources checked on September 24, 2026:{" "}
              <a href="https://developers.openai.com/api/docs/guides/prompt-caching">OpenAI</a>,{" "}
              <a href="https://docs.z.ai/guides/capabilities/cache">Z.AI</a>,{" "}
              <a href="https://openrouter.ai/docs/guides/best-practices/prompt-caching">OpenRouter</a>.
            </p>

            <h2>Rolling message breakpoints</h2>
            <p>
              A request can contain at most four tool, system and message
              markers combined. The static system block uses one;
              <code>apply_messages_cache_control</code> preserves explicit
              markers and adds up to three within the remaining slots.
              <code>messages_breakpoints</code> in the cache policy limits
              additions to 0–3. Thinking, redacted thinking and empty text
              cannot receive direct markers. One-hour markers must precede
              five-minute markers; invalid explicit inputs fail before dispatch.
            </p>
            <p>
              Markers have no independent fee. Standard Anthropic writes cost
              1.25 times input for five minutes and 2 times for one hour; read
              discounts follow the model tariff. Frequent hits refresh the
              five-minute TTL for free, so the longer TTL depends on reuse
              cadence. Provider-reported one-hour writes reach cost estimates
              and durable records. Missing historical TTL splits remain unknown
              and retain the earlier five-minute estimate.
            </p>
            <p>
              Changing dynamic system context preserves the marked static
              prefix but changes the later message prefix. Tool definitions,
              model, thinking/effort changes and context recovery can invalidate
              other prefixes. A correctly rebuilt request does not promise a
              cache hit. Provider retention is independent of closing the local
              SDK client.
            </p>

            <h2>Conversation history appends only real turns</h2>
            <p>
              AgenticLoop no longer synthesizes a user message for the round
              number or current date. Date and runtime rules already live in
              the dynamic system region in
              <code>core/agent/system_prompt.py</code>. Ordinary conversation
              rounds append user, assistant and tool messages. Context recovery
              or explicit control transitions can change this history and must
              be assessed separately.
            </p>
            <ul>
              <li>
                Per-turn system metadata is not duplicated into message
                history.
              </li>
              <li>
                Context recovery updates the shared history before the
                adapter request is assembled.
              </li>
            </ul>
            <p>
              A regression test pins this contract by comparing the actual
              <code>AdapterCallRequest.messages</code> produced by consecutive
              <code>AgenticLoop._call_llm</code> calls.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>cache_read stays at zero</td>
                  <td>The prefix changes per call: a per-turn value leaked into the static region</td>
                  <td>Move anything that varies per turn behind the boundary marker.</td>
                </tr>
                <tr>
                  <td>Costs go up on short tasks</td>
                  <td>The entry expires or the prefix changes before reuse</td>
                  <td>Check prefix stability and reuse cadence before choosing the TTL.</td>
                </tr>
                <tr>
                  <td>400: cache_control on an empty text block</td>
                  <td>Attaching a breakpoint to an empty static block</td>
                  <td>The adapter handles this via dynamic promotion; relevant only when driving the adapter directly.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/system-prompt-modes">System prompt modes</a>. What rides in the static region.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-hashing">Prompt hashing</a>. The drift guard on the static templates.</li>
              <li><a href="/geode/docs/ops/cost">Cost monitoring</a>. Where cache hits become visible.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
