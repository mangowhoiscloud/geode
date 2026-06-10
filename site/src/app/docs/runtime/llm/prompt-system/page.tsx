import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Prompt assembly — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-system"
      title="Prompt assembly"
      titleKo="프롬프트 조립"
      summary="How the system prompt is layered and assembled before each call."
      summaryKo="매 호출 전에 시스템 프롬프트가 어떻게 층층이 조립되는지 설명합니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 프롬프트는 두 단으로 관리됩니다. 디스크의 마크다운
              템플릿(버전 관리되고 해시로 핀 고정), 그리고 호출 직전의 레이어
              조립(정적/동적 분리)입니다.
            </p>

            <h2>템플릿: 마크다운이 SoT</h2>
            <p>
              프롬프트 텍스트는 <code>core/llm/prompts/</code>의 마크다운
              파일에 삽니다. 각 파일은 <code>&lt;system&gt;</code>,{" "}
              <code>&lt;user&gt;</code>, <code>&lt;agentic_suffix&gt;</code> 같은
              XML 형태 섹션 태그로 나뉘고, <code>core/llm/prompts/__init__.py</code>의{" "}
              <code>_load_template</code>이 파싱합니다. 현재 살아 있는 템플릿은
              셋입니다.
            </p>
            <table>
              <thead>
                <tr><th>템플릿</th><th>노출 상수</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>router.md</code></td><td><code>ROUTER_SYSTEM</code>, <code>AGENTIC_SUFFIX</code></td><td>메인 에이전트 시스템 프롬프트와 agentic 접미사</td></tr>
                <tr><td><code>commentary.md</code></td><td><code>COMMENTARY_SYSTEM</code>, <code>COMMENTARY_USER</code></td><td>진행 코멘터리</td></tr>
                <tr><td><code>decomposer.md</code></td><td>호출부에서 <code>load_prompt</code></td><td>복합 요청 분해</td></tr>
              </tbody>
            </table>

            <h2>드리프트 감지: 4개의 핀</h2>
            <p>
              import 시점에 각 상수의 sha256[:12] 해시를 계산해{" "}
              <code>PROMPT_VERSIONS</code>에 노출합니다. 핀은 정확히 넷입니다.{" "}
              <code>ROUTER_SYSTEM</code>, <code>AGENTIC_SUFFIX</code>,{" "}
              <code>COMMENTARY_SYSTEM</code>, <code>COMMENTARY_USER</code>.{" "}
              <code>verify_prompt_integrity()</code>가 라이브 해시를{" "}
              <code>_PINNED_HASHES</code>와 비교하고, CI가 이 함수를 게이트로
              씁니다. 프롬프트를 바꾸면 핀을 다시 박아야 하므로, 모든 프롬프트
              변경이 리뷰 가능한 코드 변경이 됩니다. 재핀 워크플로는{" "}
              <a href="/geode/docs/runtime/llm/prompt-hashing">프롬프트 해싱</a>을
              참고합니다.
            </p>
            <p>
              <code>core/llm/prompt_assembler.py</code>는 이제 작은
              스텁입니다. 스킬은 별도 주입 경로 없이{" "}
              <code>core/agent/loop/_context.py</code>의{" "}
              <code>{"{skill_context}"}</code> 블록 한 곳으로만 프롬프트에
              들어갑니다.
            </p>

            <h2>레이어 조립: build_system_prompt</h2>
            <p>
              호출 직전 조립은 <code>core/agent/system_prompt.py</code>의{" "}
              <code>build_system_prompt(model)</code>이 담당합니다. XML 태그로
              구분된 두 구역으로 나뉩니다.
            </p>
            <table>
              <thead>
                <tr><th>구역</th><th>레이어</th><th>특성</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>&lt;static_context&gt;</code></td>
                  <td><code>&lt;agent_baseline&gt;</code> (항상), <code>&lt;agent_identity&gt;</code> (옵트인), 스타일 가이드와 휴리스틱 정책 append</td>
                  <td>턴 간 불변. 캐시 적중 대상</td>
                </tr>
                <tr>
                  <td><code>&lt;dynamic_context&gt;</code></td>
                  <td><code>&lt;model_card&gt;</code>, 모델 패밀리 가이던스 (<code>core/llm/model_guidance.py</code>), 플랫폼 힌트 (<code>core/llm/platform_hints.py</code>), <code>&lt;current_date&gt;</code>, <code>&lt;project_memory&gt;</code>, <code>&lt;agent_learning&gt;</code>, <code>&lt;runtime_rules&gt;</code>, <code>&lt;user_context&gt;</code></td>
                  <td>턴마다 갱신. 캐시 제외</td>
                </tr>
              </tbody>
            </table>
            <p>
              두 구역 사이의 <code>PROMPT_CACHE_BOUNDARY</code> 마커가
              프로바이더 캐싱의 분할점입니다. 자세한 동작은{" "}
              <a href="/geode/docs/runtime/llm/prompt-caching">프롬프트 캐싱</a>을
              참고합니다.
            </p>

            <h2>시스템 프롬프트 모드</h2>
            <table>
              <thead>
                <tr><th>모드</th><th>스위치</th><th>효과</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Persona 옵트인</td>
                  <td><code>GEODE_PERSONA=on</code></td>
                  <td>&quot;You are GEODE&quot; 정체성 주입. 기본은 OFF로, 베이스 모델을 얇게 감싼 상태가 기본값입니다</td>
                </tr>
                <tr>
                  <td>Audit-mode strip</td>
                  <td><code>GEODE_AUDIT_UNRESTRICTED=1</code></td>
                  <td>GEODE 고유 레이어(정체성, 기억, 사용자 컨텍스트)를 전부 벗기고 model_card와 날짜, 호출자 suffix만 남깁니다. persona는 강제 OFF</td>
                </tr>
                <tr>
                  <td>Wrapper override</td>
                  <td><code>GEODE_WRAPPER_OVERRIDE</code> env / audit-mode SoT 파일</td>
                  <td>자기개선 루프가 변이시킨 스캐폴드를 정적 베이스로 삼습니다. 없으면 generic prefix로 폴백해 타깃이 항상 베이스 스캐폴드를 입습니다</td>
                </tr>
              </tbody>
            </table>
            <p>
              상세는{" "}
              <a href="/geode/docs/runtime/llm/system-prompt-modes">시스템 프롬프트 모드</a>를
              참고합니다.
            </p>

            <h2>program.md: 훅 제어 폴백</h2>
            <p>
              자기개선 루프의 변이 러너
              (<code>core/self_improving/loop/mutate/runner.py</code>)는{" "}
              <code>program.md</code>를 읽지 못하면 코드에 박힌 리터럴 미러로
              조용히 대체하지 않습니다. 대신{" "}
              <code>HookEvent.PROGRAM_MD_UNREADABLE</code>을 발화합니다.
              핸들러가 대체 내용을 돌려줄 수 있고, 핸들러가 없으면 러너는
              시끄럽게 실패합니다. 폴백을 데이터 미러가 아니라 코드의 제어
              지점으로 두는 설계입니다. 디스크와 리터럴의 이중 SoT는 반드시
              드리프트합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>CI가 prompt integrity에서 실패</td>
                  <td>템플릿을 바꿨는데 핀을 갱신하지 않음</td>
                  <td>의도된 ratchet입니다. <a href="/geode/docs/runtime/llm/prompt-hashing">재핀 워크플로</a>를 따릅니다</td>
                </tr>
                <tr>
                  <td>에이전트가 GEODE라고 자기소개하지 않음</td>
                  <td>persona 기본값 OFF</td>
                  <td><code>GEODE_PERSONA=on</code>으로 옵트인합니다</td>
                </tr>
                <tr>
                  <td>변이 러너가 <code>PROGRAM_MD_UNREADABLE</code>로 중단</td>
                  <td><code>program.md</code> 경로가 깨졌고 등록된 폴백 핸들러 없음</td>
                  <td>파일을 복구하거나 부트스트랩에 핸들러를 등록합니다. 조용한 폴백은 설계상 없습니다</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/context">컨텍스트 조립</a>. 이 프롬프트가 메모리, 히스토리와 합쳐지는 곳.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-caching">프롬프트 캐싱</a>. 정적/동적 경계의 비용 효과.</li>
              <li><a href="/geode/docs/runtime/skills">스킬</a>. <code>{"{skill_context}"}</code> 블록을 채우는 쪽.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE manages prompts at two levels: markdown templates on disk
              (version-controlled and hash-pinned), and layer assembly right
              before the call (static/dynamic split).
            </p>

            <h2>Templates: markdown is the source of truth</h2>
            <p>
              Prompt text lives in markdown files under{" "}
              <code>core/llm/prompts/</code>. Each file is divided by XML-shaped
              section tags (<code>&lt;system&gt;</code>, <code>&lt;user&gt;</code>,{" "}
              <code>&lt;agentic_suffix&gt;</code>) parsed by{" "}
              <code>_load_template</code> in{" "}
              <code>core/llm/prompts/__init__.py</code>. Three templates are live
              today.
            </p>
            <table>
              <thead>
                <tr><th>Template</th><th>Exposed constants</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>router.md</code></td><td><code>ROUTER_SYSTEM</code>, <code>AGENTIC_SUFFIX</code></td><td>The main agent system prompt and the agentic suffix</td></tr>
                <tr><td><code>commentary.md</code></td><td><code>COMMENTARY_SYSTEM</code>, <code>COMMENTARY_USER</code></td><td>Progress commentary</td></tr>
                <tr><td><code>decomposer.md</code></td><td><code>load_prompt</code> at call sites</td><td>Compound-request decomposition</td></tr>
              </tbody>
            </table>

            <h2>Drift detection: four pins</h2>
            <p>
              At import time each constant&apos;s sha256[:12] hash is computed
              and exposed as <code>PROMPT_VERSIONS</code>. There are exactly four
              pins: <code>ROUTER_SYSTEM</code>, <code>AGENTIC_SUFFIX</code>,{" "}
              <code>COMMENTARY_SYSTEM</code>, <code>COMMENTARY_USER</code>.{" "}
              <code>verify_prompt_integrity()</code> compares live hashes against{" "}
              <code>_PINNED_HASHES</code>, and CI uses it as a gate. Changing a
              prompt requires re-pinning, which turns every prompt change into a
              reviewable code change. The re-pin workflow is in{" "}
              <a href="/geode/docs/runtime/llm/prompt-hashing">Prompt hashing</a>.
            </p>
            <p>
              <code>core/llm/prompt_assembler.py</code> is now a small stub.
              Skills enter the prompt through exactly one route: the{" "}
              <code>{"{skill_context}"}</code> block substituted in{" "}
              <code>core/agent/loop/_context.py</code>.
            </p>

            <h2>Layer assembly: build_system_prompt</h2>
            <p>
              Assembly right before the call is{" "}
              <code>build_system_prompt(model)</code> in{" "}
              <code>core/agent/system_prompt.py</code>. The result is two
              XML-tag-delimited regions.
            </p>
            <table>
              <thead>
                <tr><th>Region</th><th>Layers</th><th>Property</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>&lt;static_context&gt;</code></td>
                  <td><code>&lt;agent_baseline&gt;</code> (always), <code>&lt;agent_identity&gt;</code> (opt-in), style-guide and heuristics policy appends</td>
                  <td>Stable across turns; cache-eligible</td>
                </tr>
                <tr>
                  <td><code>&lt;dynamic_context&gt;</code></td>
                  <td><code>&lt;model_card&gt;</code>, model-family guidance (<code>core/llm/model_guidance.py</code>), platform hint (<code>core/llm/platform_hints.py</code>), <code>&lt;current_date&gt;</code>, <code>&lt;project_memory&gt;</code>, <code>&lt;agent_learning&gt;</code>, <code>&lt;runtime_rules&gt;</code>, <code>&lt;user_context&gt;</code></td>
                  <td>Refreshed per turn; excluded from caching</td>
                </tr>
              </tbody>
            </table>
            <p>
              The <code>PROMPT_CACHE_BOUNDARY</code> marker between the two
              regions is where provider caching splits. Details in{" "}
              <a href="/geode/docs/runtime/llm/prompt-caching">Prompt caching</a>.
            </p>

            <h2>System-prompt modes</h2>
            <table>
              <thead>
                <tr><th>Mode</th><th>Switch</th><th>Effect</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Persona opt-in</td>
                  <td><code>GEODE_PERSONA=on</code></td>
                  <td>Injects the &quot;You are GEODE&quot; identity. Default is OFF: a thin wrapper around the base model</td>
                </tr>
                <tr>
                  <td>Audit-mode strip</td>
                  <td><code>GEODE_AUDIT_UNRESTRICTED=1</code></td>
                  <td>Strips every GEODE-specific layer (identity, memory, user context), leaving model_card, the date, and the caller&apos;s suffix. Forces persona OFF</td>
                </tr>
                <tr>
                  <td>Wrapper override</td>
                  <td><code>GEODE_WRAPPER_OVERRIDE</code> env / the audit-mode SoT file</td>
                  <td>The scaffold mutated by the self-improving loop becomes the static base; falls back to a generic prefix so the target always carries a base scaffold</td>
                </tr>
              </tbody>
            </table>
            <p>
              See{" "}
              <a href="/geode/docs/runtime/llm/system-prompt-modes">System prompt modes</a>{" "}
              for the full treatment.
            </p>

            <h2>program.md: hook-controlled fallback</h2>
            <p>
              The self-improving loop&apos;s mutation runner
              (<code>core/self_improving/loop/mutate/runner.py</code>) does not
              silently substitute a code-embedded literal mirror when{" "}
              <code>program.md</code> is unreadable. It fires{" "}
              <code>HookEvent.PROGRAM_MD_UNREADABLE</code> instead. A handler may
              return replacement content; with no handler, the runner fails
              loudly. Fallback is a control point in code, not a data mirror: a
              dual source of truth between disk and a literal always drifts.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>CI fails on prompt integrity</td>
                  <td>A template changed without updating the pin</td>
                  <td>The intended ratchet; follow the <a href="/geode/docs/runtime/llm/prompt-hashing">re-pin workflow</a></td>
                </tr>
                <tr>
                  <td>The agent never introduces itself as GEODE</td>
                  <td>Persona defaults to OFF</td>
                  <td>Opt in with <code>GEODE_PERSONA=on</code></td>
                </tr>
                <tr>
                  <td>The mutation runner aborts with <code>PROGRAM_MD_UNREADABLE</code></td>
                  <td><code>program.md</code> is unreadable and no fallback handler is registered</td>
                  <td>Restore the file or register a handler in bootstrap; there is no silent fallback by design</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/context">Context assembly</a>. Where this prompt joins memory and history.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-caching">Prompt caching</a>. What the static/dynamic boundary buys.</li>
              <li><a href="/geode/docs/runtime/skills">Skills</a>. The side that fills the <code>{"{skill_context}"}</code> block.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
