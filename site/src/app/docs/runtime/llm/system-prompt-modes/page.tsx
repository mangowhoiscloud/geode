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
              조립됩니다. 빌더는 <code>core/agent/system_prompt.py</code>의
              <code>build_system_prompt</code> 하나이고, env 플래그 두 개가
              무엇을 싣고 무엇을 벗길지 정합니다.
            </p>

            <h2>기본 모드: persona 주입(기본 ON)</h2>
            <p>
              기본값에서 GEODE는 자신의 persona를 주입합니다. GEODE.md의
              Identity, Voice &amp; Conduct, Operating Principles, RUNTIME
              CANNOT 섹션을 추려 <code>&lt;agent_identity&gt;</code> 레이어로
              모든 컨텍스트에 싣습니다. 선언된 소울과 런타임 가드레일이 실제로
              모델에 도달하게 하기 위함입니다. <code>GEODE_PERSONA=off</code>로
              끄면 정체성 프리앰블 없이 베이스 모델의 얇은 래퍼로 동작합니다.
              audit-mode가 켜져 있으면 이 플래그와 무관하게 강제 OFF입니다.
            </p>
            <pre>{`static prefix           턴 사이 불변, 캐시 적중
  <agent_baseline>      항상 포함. 기본 능력
  <agent_identity>      기본 ON; GEODE_PERSONA=off로 제외
<dynamic_context>       턴마다 변함, 캐시 제외
  <model_card> <current_date>
  <project_memory> <agent_learning> <runtime_rules> <user_context>
</dynamic_context>`}</pre>

            <h2>audit-mode: GEODE 맥락 strip</h2>
            <p>
              <code>GEODE_AUDIT_UNRESTRICTED=1</code>이면 GEODE 고유 레이어를
              전부 벗깁니다. 정체성, 메모리, 사용자 컨텍스트가 빠지고
              model_card, current_date, 호출자의 system_suffix만 남습니다.
              근거는 측정 결과입니다. Petri의 auditor는 시나리오의 정체성을
              끝까지 통제해야 하는데, GEODE 프리앰블이 트랜스크립트를
              오염시켰습니다. 플래그는 <code>geode audit</code>의
              <code>--unrestricted</code>가 inspect 서브프로세스 앞에서
              설정합니다.
            </p>

            <h2>wrapper override: 변이된 스캐폴드 주입</h2>
            <p>
              자기개선 루프가 진화시키는 것이 바로 이 static 영역의 wrapper
              스캐폴드입니다. 해석은 두 단계입니다.
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
                env가 없으면
                <code>~/.geode/autoresearch/handoff/wrapper-sections.json</code>
                SoT 파일. 일상 <code>geode</code> 실행이 승격된 wrapper를
                자동으로 집어 듭니다. 여기서는 스키마 실패가 WARNING 후 기본
                prefix로 우아하게 내려갑니다. 손상된 루프 산출물이 GEODE를
                벽돌로 만들면 안 되기 때문입니다.
              </li>
            </ul>
            <p>
              audit-mode에서도 override가 시스템 프롬프트의 베이스가 됩니다.
              override가 없으면 동일한 도메인 중립 베이스로 폴백해, 감사
              타깃이 항상 GEODE 스캐폴드를 입도록 보장합니다. 스캐폴드가
              실제로 프롬프트에 도달했는지는 빌드 때마다
              <code>system_prompt.scaffold</code> 진단으로 기록됩니다.
            </p>

            <h2>program.md 계약: mutator의 프롬프트</h2>
            <p>
              변이를 제안하는 mutator 에이전트의 시스템 프롬프트는 코드
              리터럴이 아니라 패키지와 함께 출하되는
              <code>core/self_improving/program.md</code>입니다. 러너
              (<code>core/self_improving/loop/mutate/runner.py</code>)가 매
              호출 디스크에서 읽고, 단일 변이로 범위를 좁히는 계약을 뒤에
              붙입니다. 파일을 못 읽으면 조용한 폴백 대신 크게 실패합니다.
              교체가 필요하면 훅 핸들러가 <code>program_md</code> 본문을
              공급하는 단일 제어 지점을 씁니다.
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
              <li><a href="/geode/docs/capabilities/autoresearch">폐루프</a>. wrapper를 진화시키는 바깥 루프.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The same request can ride differently assembled system prompts
              depending on the mode. There is one builder,
              <code>build_system_prompt</code> in
              <code>core/agent/system_prompt.py</code>, and two env flags
              decide what gets loaded and what gets stripped.
            </p>

            <h2>Default mode: persona is injected</h2>
            <p>
              By default GEODE injects its persona: an
              <code>&lt;agent_identity&gt;</code> layer extracted from GEODE.md
              (Identity, Voice &amp; Conduct, Operating Principles, and RUNTIME
              CANNOT) ships in every context, so the declared soul and runtime
              guardrails actually reach the model. Opt out with
              <code>GEODE_PERSONA=off</code> to run as a thin wrapper around the
              base model, with no identity preamble. Audit-mode forces it off
              regardless of the flag.
            </p>
            <pre>{`static prefix           stable across turns, cache hit
  <agent_baseline>      always present. base capabilities
  <agent_identity>      on by default; off with GEODE_PERSONA=off
<dynamic_context>       changes per turn, uncached
  <model_card> <current_date>
  <project_memory> <agent_learning> <runtime_rules> <user_context>
</dynamic_context>`}</pre>

            <h2>Audit mode: stripping GEODE context</h2>
            <p>
              With <code>GEODE_AUDIT_UNRESTRICTED=1</code> every
              GEODE-specific layer is stripped: identity, memory, and user
              context go away, leaving model_card, current_date, and the
              caller&apos;s system_suffix. The rationale comes from
              measurement: Petri&apos;s auditor must control the
              scenario&apos;s identity end to end, and a GEODE preamble
              contaminated audit transcripts. The flag is set by
              <code>geode audit</code>&apos;s
              <code>--unrestricted</code> before the inspect subprocess.
            </p>

            <h2>The wrapper override: injecting the mutated scaffold</h2>
            <p>
              The wrapper scaffold in the static region is exactly what the
              self-improving loop evolves. Resolution has two steps.
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
                With the env unset, the SoT file
                <code>~/.geode/autoresearch/handoff/wrapper-sections.json</code>:
                daily <code>geode</code> invocations automatically pick up the
                promoted wrapper. Schema failures here log a WARNING and
                degrade gracefully to the default prefix, because a corrupted
                loop artifact must never brick GEODE.
              </li>
            </ul>
            <p>
              In audit mode the override is still the base of the system
              prompt; when no override resolves, the builder falls back to
              the same domain-neutral base, so the audit target always wears
              a GEODE scaffold. Whether the scaffold actually reached the
              prompt is recorded on every build by the
              <code>system_prompt.scaffold</code> diagnostic.
            </p>

            <h2>The program.md contract: the mutator&apos;s prompt</h2>
            <p>
              The mutation-proposing agent&apos;s system prompt is not a code
              literal but <code>core/self_improving/program.md</code>, shipped
              with the package. The runner
              (<code>core/self_improving/loop/mutate/runner.py</code>) reads
              it from disk on every invocation and appends a contract that
              scopes it to a single mutation. If the file is unreadable the
              runner fails loud rather than silently falling back; the single
              programmatic control point is a hook handler supplying a
              replacement <code>program_md</code> body.
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
              <li><a href="/geode/docs/capabilities/autoresearch">The closed loop</a>. The outer loop that evolves the wrapper.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
