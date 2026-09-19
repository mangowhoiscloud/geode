import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "System prompt modes — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/system-prompt-modes"
      title="System prompt modes"
      titleKo="시스템 프롬프트 모드"
      summary="The default-on persona injection, the audit-mode strip with the wrapper override, and the program.md contract for the mutator."
      summaryKo="기본 ON persona 주입, wrapper override가 붙는 audit-mode strip, 그리고 mutator의 program.md 계약을 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              같은 요청이라도 시스템 프롬프트는 모드에 따라 다르게
              조립됩니다. <code>core/agent/system_prompt.py</code>의{" "}
              <code>build_system_prompt</code>가 기본 본문을 만들고,{" "}
              <code>core/agent/loop/_context.py</code>가 명시적 에이전트
              override, 스킬 메타데이터와 세션 지침을 결합합니다.
            </p>

            <h2>기본 모드: persona 주입(기본 ON)</h2>
            <p>
              기본값에서 GEODE는 자신의 persona를 주입합니다. GEODE.md의
              Identity, Voice &amp; Conduct, Operating Principles, RUNTIME
              CANNOT 섹션을 추려 <code>&lt;agent_identity&gt;</code> 레이어로
              기본 프롬프트에 싣습니다. 전체 파일 주입과는 구별됩니다.{" "}
              <code>GEODE_PERSONA=off</code>는 이 G1 레이어만 생략하며
              공유 베이스와 도구 사용 규칙은 유지합니다.
              audit-mode가 켜져 있으면 이 플래그와 무관하게 강제 OFF입니다.
            </p>
            <pre>{`static prefix           턴 사이 불변, 캐시 적중
  router/wrapper base + math-output rules
  selected style/heuristic policies
  <agent_identity>      기본 ON; GEODE_PERSONA=off로 제외
  AGENTIC_SUFFIX
<dynamic_context>       턴마다 변함, 캐시 제외
  <model_card>           모델 인자가 있을 때
  model-family guidance + platform hint
  <current_date>         OpenAI GPT 계열에서는 생략
  <project_memory> <agent_learning> <runtime_rules> <user_context>
</dynamic_context>`}</pre>

            <h2>audit-mode: GEODE 맥락 strip</h2>
            <p>
              <code>GEODE_AUDIT_UNRESTRICTED=1</code>이면 G1, 메모리와 사용자
              컨텍스트를 생략합니다. wrapper 또는 generic 베이스, 수식 출력
              규칙과 <code>AGENTIC_SUFFIX</code>는 유지합니다. 동적 영역에는
              모델 인자가 있으면 model_card, 프로바이더 정책에 따라 날짜,
              호출자의 system_suffix가 들어갑니다.
              근거는 측정 결과입니다. Petri의 auditor는 시나리오의 정체성을
              끝까지 통제해야 하는데, GEODE 프리앰블이 트랜스크립트를
              오염시켰습니다. 플래그는 <code>geode-eval audit</code>의
              <code>--unrestricted</code>가 inspect 서브프로세스 앞에서
              설정합니다.
            </p>

            <p>
              Unreleased: 위임 worker에도 <code>GEODE_PERSONA</code>와 호출 시점의
              실제 audit 상태가 전달됩니다. 프로세스 환경값보다 우선한 요청별
              audit 설정도 유지하며, 명시적 에이전트 override의 조립 경로는 바꾸지 않습니다.
            </p>
            <h2>wrapper override: 변이된 스캐폴드 주입</h2>
            <p>
              자기개선 루프가 진화시키는 것이 바로 이 static 영역의 wrapper
              스캐폴드입니다. 런타임 조립부는{" "}
              <code>core/config/runtime_policy_sources.py</code>의 정책 후보를
              빌더에 전달합니다. 기본 후보의 해석은 다음과 같습니다.
            </p>
            <ul>
              <li>
                <code>GEODE_WRAPPER_OVERRIDE</code> env가 가리키는 JSON 파일.
                감사 서브프로세스 훅입니다. 설정되어 있으면 파일이 반드시
                존재하고 파싱돼야 하며, 실패는 fatal입니다. 잘못된 wrapper로
                쿼터를 조용히 태우는 것보다 감사가 중단되는 편이 낫기
                때문입니다.
              </li>
              <li>
                env가 없으면 <code>core.paths.AUTORESEARCH_WRAPPER_SECTIONS_PATH</code>의
                정책 파일을 사용합니다. 소스 체크아웃과 설치 패키지의 참조
                경로는 <code>core/paths.py</code>가 결정합니다. 파일이 없으면
                generic prefix를 사용하고, 읽기·스키마 오류는 WARNING 후
                같은 기본값으로 복구합니다.
              </li>
            </ul>
            <p>
              audit-mode에서도 override가 시스템 프롬프트의 베이스가 됩니다.
              override가 없으면 동일한 도메인 중립 베이스로 폴백해, 감사
              타깃이 항상 GEODE 스캐폴드를 입도록 보장합니다. 스캐폴드가
              실제로 프롬프트에 도달했는지는 빌드 때마다
              <code>system_prompt.scaffold</code> 진단으로 기록됩니다.
              정책 후보 없이 빌더를 직접 호출하면 전역 경로를 탐색하지 않고
              generic prefix를 사용합니다.
            </p>

            <h2>명시적 에이전트 override</h2>
            <p>
              <code>AgenticLoopConfig.system_prompt_override</code>는 wrapper
              교체와 달리 기본 조립 본문 전체를 대체합니다. G1과 model_card가
              없을 수 있지만 스킬 메타데이터, <code>AGENTIC_SUFFIX</code>,
              호출자 suffix는 루프가 별도로 결합합니다. 모델 카드가 없으면
              모델을 추측하지 않습니다. 카탈로그 정보와 계정 접근·실제 청구의
              구분은 <a href="/geode/docs/runtime/llm/prompt-system">프롬프트 조립</a>을
              참고합니다.
            </p>

            <h2>program.md 계약: mutator의 프롬프트</h2>
            <p>
              변이를 제안하는 mutator 에이전트의 시스템 프롬프트는 패키지와
              함께 출하되는 <code>evolve/scaffold_search/program.md</code>입니다. 러너
              (<code>evolve/scaffold_search/loop/mutate/runner.py</code>)가 매
              호출 디스크에서 읽고, 단일 변이로 범위를 좁히는 계약을 뒤에
              붙입니다. 파일을 못 읽으면 크게 실패합니다.
              교체가 필요하면 훅 핸들러가 <code>program_md</code> 본문을
              공급하는 단일 제어 지점을 씁니다.
            </p>
            <p>
              Unreleased: 응답 파싱과 직접 <code>apply_mutation()</code> 호출은
              같은 활성 종류 목록을 검사합니다. 폐기된 <code>retrieval</code>,
              읽기 전용 종류와 알 수 없는 종류는 정책을 읽거나 쓰기 전에 거절합니다.
              과거 증거 읽기와 rollback 경로는 별개로 유지합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>감사가 시작 전에 중단</td>
                  <td><code>GEODE_WRAPPER_OVERRIDE</code> 경로가 없거나 스키마 불일치</td>
                  <td>의도된 fail-loud입니다. 파일 경로와 dict[str, str] 스키마를 고칩니다.</td>
                </tr>
                <tr>
                  <td>승격했는데 일상 실행이 기본 프롬프트</td>
                  <td>SoT 파일 손상으로 복구 폴백</td>
                  <td>로그의 WARNING을 확인하고 <code>wrapper-sections.json</code>을 복구합니다.</td>
                </tr>
                <tr>
                  <td>얇은 래퍼를 원하는데 GEODE가 persona를 주입함</td>
                  <td>persona 기본 ON</td>
                  <td><code>GEODE_PERSONA=off</code>로 끕니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/prompt-system">프롬프트 조립</a>. 레이어 전체 구조.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-caching">프롬프트 캐싱</a>. static/dynamic 경계의 비용 면.</li>
              <li><a href="/geode/docs/capabilities/autoresearch">Closed-Loop</a>. wrapper를 진화시키는 바깥 루프.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The same request can ride differently assembled system prompts
              depending on the mode. <code>build_system_prompt</code> in{" "}
              <code>core/agent/system_prompt.py</code> builds the default body;
              {" "}<code>core/agent/loop/_context.py</code> composes explicit agent
              overrides, skill metadata, and session directives.
            </p>

            <h2>Default mode: persona is injected</h2>
            <p>
              By default GEODE injects its persona: an
              <code>&lt;agent_identity&gt;</code> layer extracted from GEODE.md
              (Identity, Voice &amp; Conduct, Operating Principles, and RUNTIME
              CANNOT) enters the default prompt, not the full file. Setting{" "}
              <code>GEODE_PERSONA=off</code> omits G1 while preserving the shared
              base and tool-use rules. Audit mode forces G1 off regardless of
              the flag.
            </p>
            <pre>{`static prefix           stable across turns, cache hit
  router/wrapper base + math-output rules
  selected style/heuristic policies
  <agent_identity>      on by default; off with GEODE_PERSONA=off
  AGENTIC_SUFFIX
<dynamic_context>       changes per turn, uncached
  <model_card>           when a model argument is supplied
  model-family guidance + platform hint
  <current_date>         omitted for OpenAI GPT-family models
  <project_memory> <agent_learning> <runtime_rules> <user_context>
</dynamic_context>`}</pre>

            <h2>Audit mode: stripping GEODE context</h2>
            <p>
              With <code>GEODE_AUDIT_UNRESTRICTED=1</code>, G1, memory, and user
              context are omitted. The wrapper or generic base, math-output
              rules, and <code>AGENTIC_SUFFIX</code> remain. Dynamic context
              carries model_card when a model is supplied, a provider-gated
              date, and the caller&apos;s system_suffix. The rationale comes from
              measurement: Petri&apos;s auditor must control the
              scenario&apos;s identity end to end, and a GEODE preamble
              contaminated audit transcripts. The flag is set by
              <code>geode-eval audit</code>&apos;s
              <code>--unrestricted</code> before the inspect subprocess.
            </p>

            <p>
              Unreleased: delegated workers inherit <code>GEODE_PERSONA</code> and
              the effective audit state at spawn, including request-local overrides
              of the process environment. Explicit agent overrides keep their
              separate assembly path.
            </p>
            <h2>The wrapper override: injecting the mutated scaffold</h2>
            <p>
              The wrapper scaffold in the static region is exactly what the
              self-improving loop evolves. Runtime composition passes policy
              candidates from <code>core/config/runtime_policy_sources.py</code>
              to the builder. Default candidate resolution is:
            </p>
            <ul>
              <li>
                The JSON file pointed to by
                <code>GEODE_WRAPPER_OVERRIDE</code>: the audit-subprocess
                hook. When set, the file must exist and parse; failures are
                fatal, because aborting the audit beats silently spending
                quota on the wrong wrapper.
              </li>
              <li>
                With the env unset, use the policy file at{" "}
                <code>core.paths.AUTORESEARCH_WRAPPER_SECTIONS_PATH</code>.
                <code>core/paths.py</code> resolves the source-checkout or
                installed-package reference path. A missing file uses the
                generic prefix; read or schema errors log a WARNING and fall
                back to the same default.
              </li>
            </ul>
            <p>
              In audit mode the override is still the base of the system
              prompt; when no override resolves, the builder falls back to
              the same domain-neutral base, so the audit target always wears
              a GEODE scaffold. Whether the scaffold actually reached the
              prompt is recorded on every build by the
              <code>system_prompt.scaffold</code> diagnostic.
              Calling the builder directly without policy candidates uses the
              generic prefix rather than searching global paths.
            </p>

            <h2>Explicit agent override</h2>
            <p>
              Unlike a wrapper replacement,{" "}
              <code>AgenticLoopConfig.system_prompt_override</code> replaces
              the entire default assembly body. G1 and model_card may be absent;
              the loop still composes skill metadata, <code>AGENTIC_SUFFIX</code>,
              and the caller&apos;s suffix separately. A missing card is not
              permission to guess the model. See{" "}
              <a href="/geode/docs/runtime/llm/prompt-system">Prompt assembly</a>{" "}
              for the boundary between catalog metadata, account access, and
              actual billing.
            </p>

            <h2>The program.md contract: the mutator&apos;s prompt</h2>
            <p>
              The mutation-proposing agent&apos;s system prompt is{" "}
              <code>evolve/scaffold_search/program.md</code>, shipped with the
              package. The runner
              (<code>evolve/scaffold_search/loop/mutate/runner.py</code>) reads
              it from disk on every invocation and appends a contract that
              scopes it to a single mutation. If the file is unreadable the
              runner fails loud. The single programmatic control point is a
              hook handler supplying a
              replacement <code>program_md</code> body.
            </p>
            <p>
              Unreleased: response parsing and direct <code>apply_mutation()</code>
              calls check the same active-kind list. Retired <code>retrieval</code>,
              reader-only, and unknown kinds are rejected before policy I/O.
              Historical reads and rollback remain separate and supported.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>An audit aborts before starting</td>
                  <td><code>GEODE_WRAPPER_OVERRIDE</code> path missing or schema mismatch</td>
                  <td>Intended fail-loud. Fix the path and the dict[str, str] schema.</td>
                </tr>
                <tr>
                  <td>Daily runs use the default prompt despite a promotion</td>
                  <td>Graceful fallback from a corrupted SoT file</td>
                  <td>Check the WARNING in the logs and repair <code>wrapper-sections.json</code>.</td>
                </tr>
                <tr>
                  <td>GEODE injects its persona but you want a bare wrapper</td>
                  <td>Persona defaults to on</td>
                  <td>Set <code>GEODE_PERSONA=off</code> for thin-wrapper mode.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/prompt-system">Prompt assembly</a>. The full layer structure.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-caching">Prompt caching</a>. The cost side of the static/dynamic boundary.</li>
              <li><a href="/geode/docs/capabilities/autoresearch">Closed-Loop</a>. The outer loop that evolves the wrapper.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
