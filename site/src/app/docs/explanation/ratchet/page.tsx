import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why ratchet discipline — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/ratchet"
      title="Why ratchet discipline"
      titleKo="왜 ratchet 규율인가"
      summary="One-way locks against drift: pinned prompt hashes, CI count floors, and the delete-protection gates."
      summaryKo="drift를 막는 단방향 잠금장치입니다. 프롬프트 해시 핀, CI 카운트 바닥, 삭제 보호 게이트를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              LLM 시스템에서는 작은 프롬프트 변경 하나가 출력 품질을 조용히
              침식할 수 있습니다. GEODE는 이를 ratchet으로 막습니다. 전부
              단방향 잠금장치입니다.
            </p>

            <h2>Ratchet이란</h2>
            <p>
              기계의 ratchet은 한 방향으로만 돌고 반대 방향으로는 잠깁니다.
              소프트웨어에서는 품질 지표를 한 방향으로만 움직이게 하는 게이트를
              뜻합니다. 테스트 수가 줄면 빌드가 실패하고, 프롬프트 해시가
              바뀌면 빌드가 실패하는 식입니다.
            </p>

            <h2>GEODE의 ratchet들</h2>
            <table>
              <thead><tr><th>Ratchet</th><th>잠그는 것</th><th>코드</th></tr></thead>
              <tbody>
                <tr><td>프롬프트 해시 핀</td><td>핵심 프롬프트의 SHA-256[:12]. 변경하려면 명시적 재핀 커밋이 필요하고, CI Type 잡이 <code>verify_prompt_integrity</code>로 단언</td><td><code>core/llm/prompts/__init__.py</code> (<code>_PINNED_HASHES</code>)</td></tr>
                <tr><td>최소 테스트 수</td><td>테스트 수가 바닥 아래로 내려가면 CI Test 잡 실패. 조용한 테스트 삭제 차단</td><td><code>.github/workflows/ci.yml</code></td></tr>
                <tr><td>Petri 번들 바닥</td><td>감사 증거 .eval 파일 수의 삭제 보호 바닥</td><td><code>scripts/check_repo_hygiene.py</code> (<code>PETRI_EVAL_FLOOR</code>)</td></tr>
                <tr><td>legacy import ratchet</td><td>해소된 레거시 import 패턴의 재유입 차단</td><td><code>.github/workflows/ci.yml</code> (Lint 잡)</td></tr>
                <tr><td>CI 게이트 자체</td><td>Lint, Type, Test, Security 중 하나라도 빨간불이면 머지 금지</td><td><code>.github/workflows/ci.yml</code></td></tr>
              </tbody>
            </table>

            <h2>출처</h2>
            <p>
              ratchet discipline은 Andrej Karpathy의 <em>autoresearch</em>{" "}
              프로젝트에서 정의된 패턴을 가져왔습니다. 자율 ML 실험 루프에서{/* canon-ok: Karpathy autoresearch 자체가 ML 실험 루프 */}
              모델이 자기 코드를 망가뜨리지 않게 하는 핵심
              메커니즘입니다.
            </p>

            <h2>왜 양쪽 모두 필요한가</h2>
            <p>
              출력 측 ratchet(프롬프트 해시)만 있으면 빌드 라인의 회귀를 막지
              못합니다. 빌드 측 ratchet(CI)만 있으면 같은 코드에 다른 프롬프트가
              실리는 조용한 회귀를 막지 못합니다. 둘이 동시에 있어야 자기일치가
              보장됩니다. 같은 구조가 자기개선 루프에도 있습니다. margin
              게이트를 통과한 변이만 승격되고, 실패한 변이는 되돌려집니다
              (<code>core/self_improving/gate.py</code>). 게이트는 champion
              chain을 한 방향으로만 움직이게 하는 ratchet입니다.
            </p>

            <h2>비용</h2>
            <p>
              의도된 변경마다 한 단계를 더 지불합니다. 프롬프트를 고치면 재핀
              커밋, 번들을 정리하면 바닥 조정 PR. 그 대가는 의도하지 않은
              변경이 출시되지 않는다는 CI 강제 보장입니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/prompt-hashing">프롬프트 해싱</a>. 핀의 동작 상세.</li>
              <li><a href="/geode/docs/reference/petri-bundle-isolation">Petri 번들 격리</a>. 번들 바닥 ratchet의 운영.</li>
              <li><a href="/geode/docs/explanation/self-hosting">왜 self-hosting 하네스인가</a>. 두 스코프에 같은 규율이 있는 이유.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              In LLM systems, one small prompt edit can quietly erode output
              quality. GEODE blocks this with ratchets. All of them are one-way
              locks.
            </p>

            <h2>What &quot;ratchet&quot; means</h2>
            <p>
              A mechanical ratchet turns one way and locks the other. In
              software it means a gate that lets a quality metric move in only
              one direction: test count drops, the build fails; a prompt hash
              changes, the build fails.
            </p>

            <h2>GEODE&apos;s ratchets</h2>
            <table>
              <thead><tr><th>Ratchet</th><th>What it locks</th><th>Code</th></tr></thead>
              <tbody>
                <tr><td>Prompt hash pins</td><td>SHA-256[:12] of the core prompts. Changing one requires an explicit re-pin commit, asserted in the CI Type job via <code>verify_prompt_integrity</code></td><td><code>core/llm/prompts/__init__.py</code> (<code>_PINNED_HASHES</code>)</td></tr>
                <tr><td>Minimum test count</td><td>The CI Test job fails when the test count drops below the floor, blocking silent test deletion</td><td><code>.github/workflows/ci.yml</code></td></tr>
                <tr><td>Petri bundle floor</td><td>A delete-protection floor on the audit-evidence .eval count</td><td><code>scripts/check_repo_hygiene.py</code> (<code>PETRI_EVAL_FLOOR</code>)</td></tr>
                <tr><td>Legacy import ratchet</td><td>Blocks reintroduction of retired legacy import patterns</td><td><code>.github/workflows/ci.yml</code> (Lint job)</td></tr>
                <tr><td>The CI gate itself</td><td>Any red among Lint, Type, Test, Security blocks the merge</td><td><code>.github/workflows/ci.yml</code></td></tr>
              </tbody>
            </table>

            <h2>Source</h2>
            <p>
              The ratchet discipline pattern is taken from Andrej
              Karpathy&apos;s <em>autoresearch</em> project, where it keeps the
              autonomous ML experiment loop from breaking its own{/* canon-ok: describes Karpathy's project, an ML experiment loop */}
              code.
            </p>

            <h2>Why both sides are needed</h2>
            <p>
              An output-side ratchet alone (prompt hashes) cannot catch
              build-line regressions. A build-side ratchet alone (CI) cannot
              catch the silent regression of same code, different prompt. Both
              together guarantee self-consistency. The same shape exists in the
              self-improving loop: only gate-passing mutations promote, and
              failures revert (<code>core/self_improving/gate.py</code>). The
              gate is the ratchet that moves the champion chain in one direction
              only.
            </p>

            <h2>The cost</h2>
            <p>
              Every intentional change pays one extra step: fix a prompt, write
              a re-pin commit; prune the bundle, adjust the floor in a PR. In
              exchange, unintentional changes never ship, enforced by CI.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/llm/prompt-hashing">Prompt hashing</a>. The pins in detail.</li>
              <li><a href="/geode/docs/reference/petri-bundle-isolation">Petri bundle isolation</a>. Operating the bundle-floor ratchet.</li>
              <li><a href="/geode/docs/explanation/self-hosting">Why a self-hosting harness</a>. Why the same discipline exists at two scopes.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
