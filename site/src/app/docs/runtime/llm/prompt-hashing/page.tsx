import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Prompt hashing — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-hashing"
      title="Prompt hashing"
      titleKo="프롬프트 해싱"
      summary="Four pinned prompt hashes that break the build on unintended drift, and the deliberate re-pin workflow."
      summaryKo="의도하지 않은 drift에 빌드를 깨뜨리는 4개의 프롬프트 해시 핀과, 의도된 변경의 re-pin 절차를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              핵심 프롬프트 템플릿은 해시로 핀됩니다. 템플릿이 한 글자라도
              바뀌면 계산된 해시가 핀과 어긋나고 CI가 깨집니다. 프롬프트
              변경을 막으려는 것이 아니라, 변경이 항상 의도된 diff로
              드러나게 하려는 래칫입니다.
            </p>

            <h2>네 개의 핀</h2>
            <p>
              <code>core/llm/prompts/__init__.py</code>가 .md 템플릿
              (<code>router.md</code>, <code>commentary.md</code>)을 로드해
              SHA-256 앞 12자를 <code>PROMPT_VERSIONS</code>로 계산하고,
              하드코딩된 <code>_PINNED_HASHES</code>와 비교합니다.
            </p>
            <table>
              <thead>
                <tr><th>핀</th><th>출처</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr><td><code>ROUTER_SYSTEM</code></td><td><code>core/llm/prompts/router.md</code></td><td>AgenticLoop 시스템 프롬프트의 베이스 템플릿.</td></tr>
                <tr><td><code>AGENTIC_SUFFIX</code></td><td><code>core/llm/prompts/router.md</code></td><td>agentic 모드에서 덧붙는 suffix 절.</td></tr>
                <tr><td><code>COMMENTARY_SYSTEM</code></td><td><code>core/llm/prompts/commentary.md</code></td><td>커멘터리 시스템 프롬프트.</td></tr>
                <tr><td><code>COMMENTARY_USER</code></td><td><code>core/llm/prompts/commentary.md</code></td><td>커멘터리 사용자 템플릿.</td></tr>
              </tbody>
            </table>
            <p>
              비교 함수는 <code>verify_prompt_integrity</code>입니다. 어긋난
              핀의 목록을 반환하고, <code>raise_on_drift=True</code>면 첫
              불일치에서 RuntimeError를 던집니다. CI 테스트가 이 검증을
              게이트로 겁니다.
            </p>

            <h2>왜 빌드를 깨는가</h2>
            <p>
              시스템 프롬프트는 동작을 정의하는 코드입니다. 그런데 일반
              코드와 달리 타입 체커도 테스트도 문구 변화를 잡지 못합니다.
              머지 충돌 해소, 포매터, 선의의 한 줄 수정이 프롬프트를 조용히
              바꾸면 에이전트 동작이 원인 불명으로 흔들립니다. 해시 핀은 그
              모든 경로를 컴파일 오류와 같은 등급으로 끌어올립니다. 자기개선
              루프가 wrapper 스캐폴드를 변이시키는 시스템에서는 더
              중요합니다. 의도된 변이는 SoT 파일로, 의도되지 않은 drift는
              빌드 실패로, 두 경로가 섞이지 않습니다.
            </p>

            <h2>의도된 변경: re-pin 절차</h2>
            <p>
              템플릿을 일부러 고쳤다면 새 해시를 계산해 핀을 갱신하고, 같은
              커밋에 템플릿 diff와 핀 diff가 나란히 실리게 합니다.
            </p>
            <pre>{`python -c "from core.llm.prompts import PROMPT_VERSIONS as V; \\
  print(dict(sorted(V.items())))"
# 출력을 _PINNED_HASHES에 반영`}</pre>
            <p>
              리뷰어는 핀 diff를 보고 &quot;프롬프트가 의도적으로
              바뀌었다&quot;는 사실을 한 줄로 확인합니다.
            </p>

            <h2>경계</h2>
            <p>
              핀 대상은 정적 템플릿이지 렌더된 프롬프트가 아닙니다. 메모리
              레이어, 날짜, wrapper override처럼 런타임에 합성되는 부분은
              해시 범위 밖입니다. 렌더 결과의 재현성 감사가 필요하면
              <code>hash_rendered_prompt</code>가 같은 12자 해시를 렌더된
              문자열에 적용합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>CI에서 &quot;Prompt drift&quot; 실패</td>
                  <td>템플릿 변경이 핀 갱신 없이 들어옴</td>
                  <td>변경이 의도라면 re-pin 절차를 따릅니다. 아니라면 diff를 되돌립니다.</td>
                </tr>
                <tr>
                  <td>핀만 바뀌고 템플릿은 그대로인 PR</td>
                  <td>이전 drift를 핀 갱신으로 덮으려는 시도</td>
                  <td>템플릿 diff 없는 핀 diff는 리뷰에서 거부합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/explanation/ratchet">왜 ratchet 규율인가</a>. 이 가드의 설계 철학.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">프롬프트 조립</a>. 핀된 템플릿이 소비되는 곳.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The core prompt templates are pinned by hash. Change a single
              character and the computed hash diverges from the pin; CI
              breaks. The point is not to forbid prompt changes but to make
              every change show up as a deliberate diff. A ratchet.
            </p>

            <h2>The four pins</h2>
            <p>
              <code>core/llm/prompts/__init__.py</code> loads the .md
              templates (<code>router.md</code>, <code>commentary.md</code>),
              computes the first 12 hex chars of SHA-256 into
              <code>PROMPT_VERSIONS</code>, and compares them against the
              hardcoded <code>_PINNED_HASHES</code>.
            </p>
            <table>
              <thead>
                <tr><th>Pin</th><th>Source</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr><td><code>ROUTER_SYSTEM</code></td><td><code>core/llm/prompts/router.md</code></td><td>Base template of the AgenticLoop system prompt.</td></tr>
                <tr><td><code>AGENTIC_SUFFIX</code></td><td><code>core/llm/prompts/router.md</code></td><td>Suffix section appended in agentic mode.</td></tr>
                <tr><td><code>COMMENTARY_SYSTEM</code></td><td><code>core/llm/prompts/commentary.md</code></td><td>Commentary system prompt.</td></tr>
                <tr><td><code>COMMENTARY_USER</code></td><td><code>core/llm/prompts/commentary.md</code></td><td>Commentary user template.</td></tr>
              </tbody>
            </table>
            <p>
              The comparator is <code>verify_prompt_integrity</code>: it
              returns the list of drifted pins, and with
              <code>raise_on_drift=True</code> raises RuntimeError on the
              first mismatch. A CI test gates on this verification.
            </p>

            <h2>Why break the build</h2>
            <p>
              A system prompt is behavior-defining code, yet neither the type
              checker nor the test suite catches a wording change. A merge
              conflict resolution, a formatter, or a well-meant one-line edit
              can silently alter the prompt and shift agent behavior with no
              traceable cause. The hash pin promotes all of those paths to
              the severity of a compile error. In a system whose
              self-improving loop mutates the wrapper scaffold this matters
              even more: intended mutation flows through the SoT file,
              unintended drift fails the build, and the two paths never mix.
            </p>

            <h2>Deliberate change: the re-pin workflow</h2>
            <p>
              After an intentional template edit, recompute the hashes,
              update the pins, and land the template diff and the pin diff in
              the same commit.
            </p>
            <pre>{`python -c "from core.llm.prompts import PROMPT_VERSIONS as V; \\
  print(dict(sorted(V.items())))"
# copy the output into _PINNED_HASHES`}</pre>
            <p>
              The reviewer reads the pin diff as a one-line attestation that
              the prompt changed on purpose.
            </p>

            <h2>Scope</h2>
            <p>
              The pins cover the static templates, not the rendered prompt.
              Memory layers, the date, and the wrapper override are composed
              at runtime and sit outside the hash. For reproducibility audits
              of rendered output, <code>hash_rendered_prompt</code> applies
              the same 12-char hash to a rendered string.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>CI fails with &quot;Prompt drift&quot;</td>
                  <td>A template change landed without a pin update</td>
                  <td>If the change is intended, follow the re-pin workflow. Otherwise revert the diff.</td>
                </tr>
                <tr>
                  <td>A PR changes pins but not templates</td>
                  <td>An attempt to paper over earlier drift via the pins</td>
                  <td>Reject pin diffs that come without a template diff.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/explanation/ratchet">Why ratchet discipline</a>. The design philosophy behind this guard.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">Prompt assembly</a>. Where the pinned templates are consumed.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
