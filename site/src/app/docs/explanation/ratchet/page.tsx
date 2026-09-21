import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Why ratchet discipline — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="explanation/ratchet"
      title="Why ratchet discipline"
      titleKo="왜 ratchet 규율인가"
      summary="One-way locks against drift: pinned prompt hashes, coverage floors, and delete-protection gates."
      summaryKo="drift를 막는 단방향 잠금장치입니다. 프롬프트 해시 핀, coverage 하한, 삭제 보호 게이트를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 ratchet은 선언한 불변조건을 위반한 변경을 차단합니다.
              프롬프트 해시와 테스트 coverage 같은 검사 대상은 보호하지만,
              관측하지 않은 모든 작업의 품질까지 보장하지는 않습니다.
              <a href="/geode/docs/explanation/rsi-roadmap">RSI 로드맵</a>에서도
              회귀 방지 장치와 개선 성능의 실측을 구분합니다.
            </p>

            <h2>Ratchet이란</h2>
            <p>
              기계의 ratchet은 한 방향으로만 돌고 반대 방향으로는 잠깁니다.
              소프트웨어에서는 품질 지표를 한 방향으로만 움직이게 하는 게이트를
              뜻합니다. coverage가 설정 하한 아래로 내려가거나 프롬프트
              해시가 바뀌면 빌드가 실패하는 식입니다.
            </p>

            <h2>GEODE의 ratchet들</h2>
            <table>
              <thead><tr><th>Ratchet</th><th>잠그는 것</th><th>코드</th></tr></thead>
              <tbody>
                <tr><td>프롬프트 해시 핀</td><td>핵심 프롬프트의 SHA-256[:12]. 변경하려면 명시적 재핀 커밋이 필요하고, CI Type 잡이 <code>verify_prompt_integrity</code>로 단언</td><td><code>core/llm/prompts/__init__.py</code> (<code>_PINNED_HASHES</code>)</td></tr>
                <tr><td>테스트 coverage 하한</td><td>전체 행동 테스트가 통과해도 coverage가 75% 아래면 CI Test 잡 실패</td><td><code>pyproject.toml</code> (<code>fail_under</code>)</td></tr>
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
              실리는 의도하지 않은 변경을 감지하지 못합니다. 두 검사는 서로
              다른 불변조건을 지킵니다. 같은 구조가 후보 탐색에도 있습니다. margin
              게이트를 통과한 변이만 승격되고, 실패한 변이는 되돌려집니다
              (<code>evolve/scaffold_search/gate.py</code>). 게이트는 champion
              chain에 채택 기준을 적용하는 ratchet입니다. 평가 밖의 성능은 별도 검증이 필요합니다.
            </p>

            <h2>비용</h2>
            <p>
              의도된 변경마다 한 단계를 더 지불합니다. 프롬프트를 고치면 재핀
              커밋, 번들을 정리하면 바닥 조정 PR. 그 대가는 의도하지 않은
              변경 중 선언된 검사로 탐지한 것을 CI에서 차단할 수 있다는 것입니다.
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
              GEODE ratchets block changes that violate declared invariants.
              They protect checked properties such as prompt hashes and coverage,
              not quality on every unobserved task. The
              <a href="/geode/docs/explanation/rsi-roadmap?lang=en"> RSI roadmap</a>
              separates regression controls from measured improvement.
            </p>

            <h2>What &quot;ratchet&quot; means</h2>
            <p>
              A mechanical ratchet turns one way and locks the other. In
              software it means a gate that prevents a protected quality signal
              from moving backward: coverage falls below its configured floor,
              or a prompt hash changes, and the build fails.
            </p>

            <h2>GEODE&apos;s ratchets</h2>
            <table>
              <thead><tr><th>Ratchet</th><th>What it locks</th><th>Code</th></tr></thead>
              <tbody>
                <tr><td>Prompt hash pins</td><td>SHA-256[:12] of the core prompts. Changing one requires an explicit re-pin commit, asserted in the CI Type job via <code>verify_prompt_integrity</code></td><td><code>core/llm/prompts/__init__.py</code> (<code>_PINNED_HASHES</code>)</td></tr>
                <tr><td>Test coverage floor</td><td>The CI Test job fails below 75% coverage even when the behavior suite passes</td><td><code>pyproject.toml</code> (<code>fail_under</code>)</td></tr>
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
              catch an unintended prompt change with unchanged code. The checks
              protect different invariants. Candidate search uses the same pattern:
              only gate-passing mutations promote, and
              failures revert (<code>evolve/scaffold_search/gate.py</code>). The
              gate applies an acceptance rule to the champion chain. Performance
              outside that evaluation still needs a separate test.
            </p>

            <h2>The cost</h2>
            <p>
              Every intentional change pays one extra step: fix a prompt, write
              a re-pin commit; prune the bundle, adjust the floor in a PR. In
              exchange, CI can block violations detected by its declared checks.
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
