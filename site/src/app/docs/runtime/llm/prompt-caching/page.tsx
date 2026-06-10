import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Prompt caching — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-caching"
      title="Prompt caching"
      titleKo="프롬프트 캐싱"
      summary="The static/dynamic boundary, rolling message breakpoints, and the append-only system reminder that keeps the prefix cacheable."
      summaryKo="static/dynamic 경계, 롤링 메시지 breakpoint, 그리고 prefix를 캐시 가능하게 유지하는 append 전용 system reminder를 다룹니다."
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
              옵트인 identity), 마커 뒤는 턴마다 변합니다(model card, 날짜,
              메모리 레이어, 사용자 컨텍스트).
            </p>
            <p>
              Anthropic 어댑터(<code>core/llm/providers/anthropic.py</code>)가
              이 마커에서 시스템 문자열을 갈라 static 블록에
              <code>{`cache_control: {"type": "ephemeral"}`}</code>을 붙입니다.
              dynamic 쪽은 캐시 없이 나갑니다. static이 비어 있으면(audit
              모드에서 레이어를 벗긴 경우) 빈 텍스트 블록에 cache_control을
              붙이는 400 오류를 피해 dynamic 쪽을 단일 캐시 블록으로
              승격합니다.
            </p>

            <h2>롤링 메시지 breakpoint</h2>
            <p>
              Anthropic은 요청당 cache_control breakpoint를 4개까지
              허용합니다. 시스템 블록이 1-2개를 쓰고, 나머지는
              <code>apply_messages_cache_control</code>이 대화 이력의 마지막
              메시지들에 붙입니다. 몇 개를 붙일지(0-3)는 cache-policy
              SoT(<code>core/llm/cache_policy.py</code>)가 정하고 기본값은
              3입니다. breakpoint가 많을수록 긴 멀티턴 루프의 적중률이
              오르지만, 캐시된 블록마다 적중 여부와 무관하게 쓰기 오버헤드가
              붙습니다. 짧은 작업이라면 낮추는 쪽이 맞습니다.
            </p>
            <p>
              비용 산식은 단가표 기준으로 cache write가 input의 1.25배, cache
              read가 input의 0.1배입니다
              (<code>core/llm/pricing_loader.py</code>).
            </p>

            <h2>system reminder는 append 전용</h2>
            <p>
              멀티턴 강화용 <code>&lt;system-reminder&gt;</code> 블록
              (<code>core/agent/system_injection.py</code>)에는 캐시 계약이
              걸려 있습니다. 이전 설계는 reminder를 <code>messages[0]</code>에
              넣고 라운드마다 다시 썼습니다. 메시지는 시스템 블록 뒤에
              렌더되므로 이력 prefix 전체가 매 라운드 다시 키잉되고, 롤링
              breakpoint는 한 번도 적중하지 못했습니다. 현재 계약은
              두 가지입니다.
            </p>
            <ul>
              <li>
                <code>append_system_reminder</code>는 새 리스트를 반환합니다.
                호출자의 이력 리스트는 그대로이므로 reminder가 저장된
                대화 컨텍스트에 stale한 중간 prefix 바이트로 남지 않습니다.
              </li>
              <li>
                라운드 인덱스와 날짜 같은 턴별 변량은 마지막 안정 이력 블록
                뒤에 붙습니다. 매 라운드 캐시에서 빠지는 것은 reminder
                자신뿐입니다.
              </li>
            </ul>
            <p>
              가드 테스트는
              <code>tests/core/agent/test_system_injection.py</code>의
              TestCacheContract입니다.
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
                  <td>breakpoint 쓰기 오버헤드가 적중 이득을 초과</td>
                  <td>cache-policy SoT에서 <code>messages_breakpoints</code>를 낮춥니다.</td>
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
              opt-in identity); everything after changes per turn (model
              card, date, memory layers, user context).
            </p>
            <p>
              The Anthropic adapter
              (<code>core/llm/providers/anthropic.py</code>) splits the
              system string at the marker and attaches
              <code>{`cache_control: {"type": "ephemeral"}`}</code> to the
              static block; the dynamic side ships uncached. When the static
              side is empty (audit mode with layers stripped), the dynamic
              side is promoted to the single cacheable block to avoid the
              400 for cache_control on an empty text block.
            </p>

            <h2>Rolling message breakpoints</h2>
            <p>
              Anthropic allows up to 4 cache_control breakpoints per request.
              The system blocks spend 1-2; the rest go on the trailing
              conversation messages via
              <code>apply_messages_cache_control</code>. How many (0-3) comes
              from the cache-policy SoT
              (<code>core/llm/cache_policy.py</code>), default 3. More
              breakpoints raise the hit rate on long multi-turn loops, but
              each cached block carries a write overhead whether the call
              hits or misses; for short tasks, fewer is the right call.
            </p>
            <p>
              On the pricing table, a cache write costs 1.25 times input and
              a cache read 0.1 times input
              (<code>core/llm/pricing_loader.py</code>).
            </p>

            <h2>The system reminder is append-only</h2>
            <p>
              The multi-turn <code>&lt;system-reminder&gt;</code> block
              (<code>core/agent/system_injection.py</code>) carries an
              explicit cache contract. The previous design inserted the
              reminder at <code>messages[0]</code> and rewrote it per round;
              since messages render after the system blocks, that re-keyed
              the entire history prefix every round and the rolling
              breakpoints could never hit. The current contract:
            </p>
            <ul>
              <li>
                <code>append_system_reminder</code> returns a new list. The
                caller&apos;s history list is never modified, so the reminder
                cannot persist into the stored conversation context as stale
                mid-prefix bytes.
              </li>
              <li>
                Per-round variance (round index, date) lands after the last
                stable history block. Only the reminder itself is uncached
                each round.
              </li>
            </ul>
            <p>
              The guard is TestCacheContract in
              <code>tests/core/agent/test_system_injection.py</code>.
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
                  <td>Breakpoint write overhead exceeds the hit savings</td>
                  <td>Lower <code>messages_breakpoints</code> in the cache-policy SoT.</td>
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
