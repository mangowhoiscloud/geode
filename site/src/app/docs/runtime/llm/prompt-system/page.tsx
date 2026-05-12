"use client";

import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-system"
      title="Prompt System"
      titleKo="프롬프트 시스템"
      summary="GEODE's prompt subsystem: 5 layers, 17 templates, 3 axes datasets, 20 pinned hashes, ephemeral cache, and an append-only assembler."
      summaryKo="GEODE 프롬프트 서브시스템: 5계층, 17개 템플릿, 3개 axes 데이터, 20개 pin 해시, ephemeral 캐시, append-only 어셈블러."
    >
      <h2>{<Bi ko="5계층" en="Five layers" />}</h2>
      <pre>{`1. Templates Layer       core/llm/prompts/*.md           — 17 base + extended sections
2. Axes Layer            plugins/game_ip/config/         — 14 evaluation axes + 4 analyst directives
                          evaluator_axes.yaml
3. Hash Versioning       core/llm/prompts/__init__.py    — SHA-256[:12] x 20 pinned entries
4. Assembly              core/llm/prompt_assembler.py    — base + skill + memory + bootstrap
                                                          (6 phases, append-only by default)
5. Skill Injection       core/skills/skill_registry.py   — frontmatter + body, 5-tier discovery`}</pre>

      <Bi
        ko={
          <>
            <h2>SOT (Source of Truth)</h2>
            <p>
              프롬프트 텍스트는 마크다운 파일(<code>analyst.md</code>,{" "}
              <code>evaluator.md</code>, <code>synthesizer.md</code>,{" "}
              <code>biasbuster.md</code>, <code>router.md</code>,{" "}
              <code>cross_llm.md</code>, <code>commentary.md</code> 등) 과 하나의
              YAML 파일(<code>evaluator_axes.yaml</code>) 에 살고 있습니다.
            </p>
            <p>
              import 시점에 <code>core/llm/prompts/__init__.py</code> 가 각 템플릿을
              Python 상수(<code>ANALYST_SYSTEM</code>, <code>EVALUATOR_SYSTEM</code> 등)
              로 읽고, SHA-256[:12] 해시를 계산해 <code>PROMPT_VERSIONS</code> 레지스트리에
              노출합니다.
            </p>

            <h2>드리프트 감지</h2>
            <p>
              병렬 딕셔너리 <code>_PINNED_HASHES</code> 는 20개 항목 각각의 기대 해시를
              유지합니다. <code>verify_prompt_integrity()</code> 가 라이브 해시와 핀
              해시를 비교해 드리프트 리스트를 반환합니다. CI 는 이 함수를{" "}
              <code>raise_on_drift=True</code> 로 호출하므로 어떤 불일치도 빌드를 깨뜨립니다.
            </p>
            <p>
              의도적 프롬프트 변경 시의 재핀 워크플로는{" "}
              <a href="/geode/docs/runtime/llm/prompt-hashing">프롬프트 해싱</a> 참조.
            </p>

            <h2>조립</h2>
            <p>
              파이프라인 노드는 템플릿에 직접 <code>.format()</code> 을 호출하지 않습니다.
              <code>PromptAssembler.assemble()</code> 을 호출해 6단계를 실행합니다:
            </p>
            <ol>
              <li>오버라이드 (기본은 append-only)</li>
              <li>스킬 주입 (priority 정렬, 최대 3개, body 캡 500자)</li>
              <li>메모리 컨텍스트 (<code>_llm_summary</code> 우선, 폴백 경로)</li>
              <li>부트스트랩 추가 명령 (최대 5개, 각 100자)</li>
              <li>예산 관찰성 (4000자 초과 시 경고)</li>
              <li>해시 + Hook 발행 (<code>PROMPT_ASSEMBLED</code> 이벤트)</li>
            </ol>
            <p>
              결과는 <code>frozen=True</code> 인 불변 <code>AssembledPrompt</code>
              dataclass — 빌드 후에는 어떤 코드 경로도 수정할 수 없습니다.
            </p>

            <h2>캐싱</h2>
            <p>
              Anthropic 의 경우, <code>core/agent/system_prompt.py</code> 의{" "}
              <code>build_system_prompt()</code> 가 정적 섹션 (라우터 템플릿 + 정체성)
              과 동적 섹션 (날짜, 모델 카드, 메모리) 사이에 경계 마커
              (<code>__GEODE_PROMPT_CACHE_BOUNDARY__</code>) 를 삽입합니다. Anthropic
              어댑터가 이 마커에서 분할해 정적 블록에만{" "}
              <code>cache_control: ephemeral</code> 을 적용합니다. 자세한 내용은{" "}
              <a href="/geode/docs/runtime/llm/prompt-caching">프롬프트 캐싱</a>{" "}
              참조.
            </p>

            <h2>관찰성</h2>
            <p>
              <code>PROMPT_ASSEMBLED</code> hook 이벤트는 메타데이터만 전달합니다 —
              노드명, 역할 타입, base 와 assembled 해시, fragment 목록, 그리고
              조건부 필드인 <code>skill_hashes</code> 와{" "}
              <code>truncation_events</code>. 원본 프롬프트 텍스트는 payload 에
              포함되지 않으므로 외부 관찰자(LangSmith, 커스텀 hook 핸들러) 는
              이 채널을 통해 프롬프트 내용을 보지 못합니다.
            </p>
            <p>
              LangSmith 통합은 <code>LANGCHAIN_TRACING_V2=true</code> + API key 로
              opt-in 됩니다. 활성화 시 <code>core/llm/router.py</code> 의 5개 LLM
              호출 지점이 <code>@maybe_traceable</code> 로 래핑됩니다.
            </p>

            <h2>이 설계의 이유</h2>
            <ul>
              <li>
                <strong>외부 마크다운</strong> 은 프롬프트를 1급 버전 관리 산출물로
                만듭니다. 프롬프트 변경에 대한 <code>git diff</code> 가 명확합니다.
              </li>
              <li>
                <strong>해시 ratchet</strong> 은 프롬프트 변경을 보이지 않는 편집에서
                의식적으로 리뷰 가능한 코드 변경(re-pin 필요) 으로 전환합니다.
              </li>
              <li>
                <strong>Frozen 결과</strong> 는 어셈블과 LLM 호출 사이의 우발적 변조를
                방지합니다.
              </li>
              <li>
                <strong>Append-only override</strong> 는 prompt-injection 채널 (env, config,
                untrusted state) 이 시스템 프롬프트를 통째로 교체하지 못하게 막습니다.
              </li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Source of truth</h2>
            <p>
              Prompt text lives in markdown files (<code>analyst.md</code>,{" "}
              <code>evaluator.md</code>, <code>synthesizer.md</code>,{" "}
              <code>biasbuster.md</code>, <code>router.md</code>,{" "}
              <code>cross_llm.md</code>, <code>commentary.md</code>, etc.) and one
              YAML file (<code>evaluator_axes.yaml</code>) that holds the structured
              evaluation rubrics.
            </p>
            <p>
              At import time, <code>core/llm/prompts/__init__.py</code> reads each
              template into a Python constant (<code>ANALYST_SYSTEM</code>,{" "}
              <code>EVALUATOR_SYSTEM</code>, etc.), computes its SHA-256[:12] hash,
              and exposes the registry as <code>PROMPT_VERSIONS</code>.
            </p>

            <h2>Drift detection</h2>
            <p>
              A parallel dictionary, <code>_PINNED_HASHES</code>, holds the expected
              hash for each of the 20 entries. The function{" "}
              <code>verify_prompt_integrity()</code> compares live hashes against
              pinned hashes and returns a list of drifts. CI calls this with{" "}
              <code>raise_on_drift=True</code>, breaking the build on any mismatch.
            </p>
            <p>
              See <a href="/geode/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>{" "}
              for the re-pin workflow when prompts are intentionally changed.
            </p>

            <h2>Assembly</h2>
            <p>
              Pipeline nodes do not call <code>.format()</code> on templates
              directly. They call <code>PromptAssembler.assemble()</code> which
              runs six phases:
            </p>
            <ol>
              <li>Override (append-only by default)</li>
              <li>Skill injection (priority sort, max 3, body cap 500 chars)</li>
              <li>Memory context (<code>_llm_summary</code> primary, fallback path)</li>
              <li>Bootstrap extras (max 5 instructions, 100 chars each)</li>
              <li>Budget observability (warn at 4000 chars)</li>
              <li>Hash + Hook fire (<code>PROMPT_ASSEMBLED</code> event)</li>
            </ol>
            <p>
              The result is an immutable <code>AssembledPrompt</code> dataclass with{" "}
              <code>frozen=True</code> — once built, no code path can modify it.
            </p>

            <h2>Caching</h2>
            <p>
              For Anthropic, <code>build_system_prompt()</code> in{" "}
              <code>core/agent/system_prompt.py</code> inserts a boundary marker (
              <code>__GEODE_PROMPT_CACHE_BOUNDARY__</code>) between the static
              section (router template + identity) and the dynamic section (date,
              model card, memory). The Anthropic adapter splits at this marker and
              applies <code>cache_control: ephemeral</code> to the static block
              only. See <a href="/geode/docs/runtime/llm/prompt-caching">Prompt Caching</a>.
            </p>

            <h2>Observability</h2>
            <p>
              The <code>PROMPT_ASSEMBLED</code> hook event carries metadata only —
              node name, role type, base and assembled hashes, fragment list, and
              conditional fields like <code>skill_hashes</code> and{" "}
              <code>truncation_events</code>. The original prompt text is not in
              the payload, so external observers (LangSmith, custom hook handlers)
              do not see prompt content through this channel.
            </p>
            <p>
              LangSmith integration is opt-in via <code>LANGCHAIN_TRACING_V2=true</code>{" "}
              and an API key. When enabled, five LLM call sites in{" "}
              <code>core/llm/router.py</code> are wrapped with{" "}
              <code>@maybe_traceable</code>.
            </p>

            <h2>Why this design</h2>
            <ul>
              <li>
                <strong>External markdown</strong> makes prompts a first-class
                versioned artifact. <code>git diff</code> on a prompt change is
                unambiguous.
              </li>
              <li>
                <strong>Hash ratchet</strong> turns prompt changes from invisible
                edits into mandatory, reviewable code changes (re-pin required).
              </li>
              <li>
                <strong>Frozen result</strong> prevents accidental mutation between
                assembly and LLM call.
              </li>
              <li>
                <strong>Append-only override</strong> blocks prompt-injection
                channels (env, config, untrusted state) from replacing the system
                prompt entirely.
              </li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
