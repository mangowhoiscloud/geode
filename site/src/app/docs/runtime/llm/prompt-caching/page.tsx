import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Prompt Caching — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-caching"
      title="Prompt Caching"
      titleKo="프롬프트 캐싱"
      summary="Anthropic ephemeral caching with a STATIC/DYNAMIC boundary, applied at two call sites: the agentic adapter and the router's non-agentic helpers."
      summaryKo="STATIC/DYNAMIC 경계로 구분되는 Anthropic ephemeral 캐싱. agentic 어댑터와 router의 non-agentic 헬퍼, 두 호출 지점에 적용됩니다."
    >
      <Bi
        ko={
          <>
            <h2>경계 마커</h2>
            <p>
              <code>core/agent/system_prompt.py:35</code>에 정의되어 있습니다. v0.93부터 9개 prompt 파일의 16개 marker가 XML 래퍼로 전환됩니다.
              경계 자체는 동일 sentinel 문자열이지만, marker가 노출되는 영역은 <code>&lt;dynamic_context&gt;</code> XML 안으로 캡슐화됩니다.
            </p>
            <pre>{`PROMPT_CACHE_BOUNDARY = "__GEODE_PROMPT_CACHE_BOUNDARY__"

# v0.93+ XML 래퍼 (system prompt 안에서)
... STATIC 영역 ...
__GEODE_PROMPT_CACHE_BOUNDARY__
<dynamic_context>
... DYNAMIC 영역 ...
</dynamic_context>`}</pre>
            <p>
              <code>build_system_prompt()</code>이 이 marker를 두 섹션 사이에 삽입합니다.
              audit-mode는 dynamic 블록을 strip합니다 (<a href="/docs/runtime/llm/system-prompt-modes">System Prompt Modes</a> 참조).
            </p>
            <ul>
              <li>
                <strong>STATIC</strong> (마커 이전). router 템플릿,{" "}
                <code>GEODE.md</code> 의 아이덴티티. 턴 간 안정적.
              </li>
              <li>
                <strong>DYNAMIC</strong> (마커 이후). 현재 날짜, 모델 카드,
                프로젝트 메모리 (G2-G4), 사용자 컨텍스트. 매 턴 변경됨.
              </li>
            </ul>

            <h2>어댑터의 분할 방식</h2>
            <p>
              <code>core/llm/providers/anthropic.py:476-495</code>의 agentic
              어댑터.
            </p>
            <pre>{`from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY

if PROMPT_CACHE_BOUNDARY in system:
    static_part, dynamic_part = system.split(PROMPT_CACHE_BOUNDARY, 1)
    sys_blocks = [
        {"type": "text", "text": static_part.rstrip(),
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_part.lstrip()},
    ]
else:
    sys_blocks = [
        {"type": "text", "text": system,
         "cache_control": {"type": "ephemeral"}},
    ]`}</pre>
            <p>
              STATIC 블록은 캐시 마커를 받지만 DYNAMIC 블록은 받지 않습니다.
              Anthropic은 STATIC 프리픽스를 서버 측에서 캐싱하며, 5분 TTL 안의
              후속 턴은 DYNAMIC 접미부와 새 user 메시지에 대해서만 과금됩니다.
            </p>

            <h2>Non-agentic 호출 지점</h2>
            <p>
              <code>core/llm/router.py</code>의 네 호출 지점 (라인 481, 582, 749,
              901)은 더 단순한 헬퍼 <code>system_with_cache(system)</code>를 써서
              system prompt 전체를 단일 ephemeral 블록으로 감쌉니다. 이들은
              STATIC/DYNAMIC 구조화 system prompt를 조립하지 않는 non-agentic LLM
              호출 (단발 prompt, 평가 호출) 입니다.
            </p>

            <h2>캐시되는 것, 캐시되지 않는 것</h2>
            <table>
              <thead>
                <tr><th>대상</th><th>캐시 여부</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic system prompt . STATIC 섹션</td>
                  <td>Yes (ephemeral)</td>
                </tr>
                <tr>
                  <td>Anthropic system prompt . DYNAMIC 섹션</td>
                  <td>No (매 턴 변경)</td>
                </tr>
                <tr>
                  <td>Anthropic non-agentic system prompt (전체)</td>
                  <td>Yes (단일 ephemeral 블록)</td>
                </tr>
                <tr>
                  <td>Anthropic <code>messages</code> 배열</td>
                  <td>Yes. 최근 3개 non-system 메시지 (PR #864, 헬퍼 <code>anthropic.py:175</code>, 호출 <code>:501</code>)</td>
                </tr>
                <tr>
                  <td>OpenAI / Codex system prompt</td>
                  <td>GEODE 측 명시 wiring 없음 (OpenAI가 서버 측에서 자동 캐싱)</td>
                </tr>
                <tr>
                  <td>GLM system prompt</td>
                  <td>프로바이더 관리</td>
                </tr>
              </tbody>
            </table>

            <h2>messages history 캐싱 (PR #864)</h2>
            <p>
              Anthropic은 요청당 최대 4개의 캐시 breakpoint를 허용합니다. 어댑터는{" "}
              <code>messages.create</code> 직전에{" "}
              <code>apply_messages_cache_control(messages)</code>를 적용해 최근 3개
              non-system 메시지의 마지막 content 블록에{" "}
              <code>cache_control: ephemeral</code>을 붙입니다. 위의 system 블록과
              합치면 4개 슬롯을 모두 채워 롤링 히스토리가 캐시됩니다.
            </p>
            <pre>{`# core/llm/providers/anthropic.py:175 (helper) and :501 (call site)
cached_messages = apply_messages_cache_control(messages)
create_kwargs = {
    "system": sys_blocks,
    "messages": cached_messages,
    ...
}`}</pre>
            <p>
              헬퍼는 비-변형 (얕은 복사된 새 리스트 반환) 이며,{" "}
              <code>str</code>과 <code>list[block]</code> content를 모두 처리하고
              빈 리스트 content는 조용히 건너뜁니다. 19개 케이스가{" "}
              <code>tests/test_anthropic_messages_cache.py</code>에서 검증됩니다.
            </p>

            <h2>캐시 무효화</h2>
            <p>
              캐시 키는 캐시된 블록의 바이트 단위 콘텐츠와 모델 ID입니다. STATIC
              섹션의 어떤 변경 (예. 업데이트된 <code>GEODE.md</code> 아이덴티티,
              새 IP 예제 목록, router 템플릿 수정) 도 캐시를 무효화하며, 후속 턴이
              다시 캐시에 적중하기 전에 한 번의 전체 요청 비용을 지불해야 합니다.
            </p>
            <p>
              이것이 prompt drift 감지 (
              <a href="/geode/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>) 와
              prompt 캐싱이 설계상 긴밀하게 결합된 이유입니다. 조용한 prompt 변경은
              조용한 캐시 무효화로 이어지며, 해시 잠금장치는 그런 변경을 의식적인
              단계로 강제합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>The boundary marker</h2>
            <p>
              <code>core/agent/system_prompt.py:35</code> defines:
            </p>
            <pre>{`PROMPT_CACHE_BOUNDARY = "__GEODE_PROMPT_CACHE_BOUNDARY__"`}</pre>
            <p>
              <code>build_system_prompt()</code> inserts this marker between two
              sections:
            </p>
            <ul>
              <li>
                <strong>STATIC</strong> (before the marker): router template,
                identity from <code>GEODE.md</code>. Stable across turns.
              </li>
              <li>
                <strong>DYNAMIC</strong> (after the marker): current date, model
                card, project memory (G2-G4), user context. Changes per turn.
              </li>
            </ul>

            <h2>How the adapter splits</h2>
            <p>
              <code>core/llm/providers/anthropic.py:476-495</code> in the agentic
              adapter:
            </p>
            <pre>{`from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY

if PROMPT_CACHE_BOUNDARY in system:
    static_part, dynamic_part = system.split(PROMPT_CACHE_BOUNDARY, 1)
    sys_blocks = [
        {"type": "text", "text": static_part.rstrip(),
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_part.lstrip()},
    ]
else:
    sys_blocks = [
        {"type": "text", "text": system,
         "cache_control": {"type": "ephemeral"}},
    ]`}</pre>
            <p>
              The static block gets the cache marker; the dynamic block does not.
              Anthropic then caches the static prefix server-side, and subsequent
              turns within the 5-minute TTL pay only for the dynamic suffix and
              the new user message.
            </p>

            <h2>Non-agentic call sites</h2>
            <p>
              Four call sites in <code>core/llm/router.py</code> (lines 481, 582,
              749, 901) use the simpler helper{" "}
              <code>system_with_cache(system)</code> that wraps the entire system
              prompt as a single ephemeral block. These are the {" "}
              non-agentic LLM calls (single-shot prompts, evaluation calls) that
              do not assemble a STATIC/DYNAMIC structured system prompt.
            </p>

            <h2>What is cached, what is not</h2>
            <table>
              <thead>
                <tr><th>Surface</th><th>Cached</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic system prompt — STATIC section</td>
                  <td>Yes (ephemeral)</td>
                </tr>
                <tr>
                  <td>Anthropic system prompt — DYNAMIC section</td>
                  <td>No (changes per turn)</td>
                </tr>
                <tr>
                  <td>Anthropic non-agentic system prompt (full)</td>
                  <td>Yes (single ephemeral block)</td>
                </tr>
                <tr>
                  <td>Anthropic <code>messages</code> array</td>
                  <td>Yes — last 3 non-system messages (PR #864, helper at <code>anthropic.py:175</code>, call at <code>:501</code>)</td>
                </tr>
                <tr>
                  <td>OpenAI / Codex system prompt</td>
                  <td>No explicit GEODE wiring (OpenAI auto-caches server-side)</td>
                </tr>
                <tr>
                  <td>GLM system prompt</td>
                  <td>Provider-managed</td>
                </tr>
              </tbody>
            </table>

            <h2>Messages history caching (PR #864)</h2>
            <p>
              Anthropic allows up to four cache breakpoints per request. The
              adapter applies <code>apply_messages_cache_control(messages)</code>{" "}
              right before <code>messages.create</code>, attaching{" "}
              <code>cache_control: ephemeral</code> to the last three non-system
              messages&apos; final content block. Combined with the system block
              above, that fills all four slots and caches the rolling history.
            </p>
            <pre>{`# core/llm/providers/anthropic.py:175 (helper) and :501 (call site)
cached_messages = apply_messages_cache_control(messages)
create_kwargs = {
    "system": sys_blocks,
    "messages": cached_messages,
    ...
}`}</pre>
            <p>
              Helper is non-mutating (returns a new list with shallow copies),
              handles <code>str</code> and <code>list[block]</code> content, and
              skips empty-list content silently. Tested in{" "}
              <code>tests/test_anthropic_messages_cache.py</code> (19 cases).
            </p>

            <h2>Cache invalidation</h2>
            <p>
              The cache key is the byte-for-byte content of the cached block plus
              the model ID. Any change to the static section — e.g. an updated{" "}
              <code>GEODE.md</code> identity, a new IP example list, a router
              template revision — invalidates the cache and pays one full request
              before subsequent turns hit again.
            </p>
            <p>
              This is why prompt drift detection (
              <a href="/geode/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>)
              and prompt caching are tightly coupled in the design: a silent prompt
              change would silently invalidate the cache, and the hash ratchet
              forces such changes to be conscious.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
