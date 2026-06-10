import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Petri bundle isolation — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/petri-bundle-isolation"
      title="Petri bundle isolation"
      titleKo="Petri 번들 격리"
      summary="Operator reference for the bundle's dedicated validation workflow, the deep validator, and the delete-protection ratchet. Deploy stays in pages.yml."
      summaryKo="번들 전용 검증 워크플로우, deep validator, 삭제 보호 ratchet의 운영자 레퍼런스입니다. 배포는 pages.yml에 남습니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 분리했나</h2>
            <p>
              감사 번들(<code>docs/self-improving/petri-bundle/</code>)과 docs
              사이트는 같은 Pages 아티팩트로 배포됩니다. 검증까지 한
              워크플로우에 묶여 있으면 site 빌드 결과가 번들 ratchet의 실행
              여부를 좌우합니다. PR #1314가 검증을 분리했습니다. 번들, validator,
              hygiene ratchet을 건드리는 모든 PR에서{" "}
              <code>petri-publish.yml</code>이 무조건 돌고, 매일 cron과 수동
              dispatch로도 돌아갑니다. 이 워크플로우는 배포하지 않습니다. 실제
              Pages 배포는 <code>pages.yml</code>에 남아 아티팩트 소스를 하나로
              유지하고, 깨진 번들은 PR 게이트에서 머지 전에 잡힙니다.
            </p>

            <h2>구성 요소</h2>
            <table>
              <thead><tr><th>파일</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><code>.github/workflows/petri-publish.yml</code></td><td>번들 전용 검증 게이트. <code>docs/self-improving/petri-bundle/**</code>, validator, hygiene, 워크플로우 자신이 바뀌면 가동. 매일 cron + 수동 dispatch. 배포는 하지 않습니다</td></tr>
                <tr><td><code>.github/workflows/pages.yml</code></td><td>실제 배포. validator를 npm install/build 앞에서 실행해 깨진 번들이 빌드 비용을 쓰기 전에 중단. 빌드 후 <code>docs/self-improving/</code>을 <code>site/out/</code>으로 복사</td></tr>
                <tr><td><code>scripts/validate_petri_bundle.py</code></td><td>deep validator. .eval zip을 열어 header의 <code>results</code> 누락, 빈 <code>scores[]</code>, 빈 <code>metrics</code>를 거부</td></tr>
                <tr><td><code>scripts/check_repo_hygiene.py</code></td><td><code>PETRI_EVAL_FLOOR = 9</code> 삭제 보호 ratchet. eval 파일 수가 바닥 아래로 내려가면 실패</td></tr>
                <tr><td><code>zipfile-zstd</code> (dev group)</td><td>Python 3.12와 3.13에서 zstd 압축 .eval을 여는 shim. 3.14+에서는 표준 라이브러리가 처리</td></tr>
              </tbody>
            </table>

            <h2>운영자 트리거</h2>
            <pre>{`# 로컬 검증
uv run python scripts/validate_petri_bundle.py
uv run python scripts/check_repo_hygiene.py

# 수동 workflow 실행
gh workflow run petri-publish.yml --ref main

# 최근 실행 점검
gh run list --workflow=petri-publish.yml --limit=10`}</pre>

            <h2>알려진 실패 패턴</h2>
            <p>
              inspect_ai 뷰어 #1747의{" "}
              <code>formatPrettyDecimal(g.metrics[i].value)</code> TypeError가
              원형입니다. header.json의 <code>results=None</code>, 빈{" "}
              <code>scores[]</code>, 빈 <code>metrics</code> 세 케이스가
              트리거이고, validator가 셋 모두를 PR 게이트에서 차단합니다. 과거
              사례는 PR #1129(partial archive)와 PR #1130(error archive)입니다.
              PR에서는 main 대비 사라진 .eval 파일도 경고로 표면화합니다.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>참조</em>: PR #1314, <code>tests/test_validate_petri_bundle.py</code>.
            </p>
          </>
        }
        en={
          <>
            <h2>Why the split</h2>
            <p>
              The audit bundle (<code>docs/self-improving/petri-bundle/</code>)
              and the docs site deploy as one Pages artifact. With validation
              tied into the same workflow, the site build outcome decided
              whether the bundle ratchet even ran. PR #1314 split the
              validation: <code>petri-publish.yml</code> now runs
              unconditionally on every PR that touches the bundle, the
              validator, or the hygiene ratchet, plus a daily cron and manual
              dispatch. It does not deploy. The actual Pages publish stays in{" "}
              <code>pages.yml</code> to keep a single artifact source; a corrupt
              bundle is caught at the PR gate before merge.
            </p>

            <h2>The moving parts</h2>
            <table>
              <thead><tr><th>File</th><th>Role</th></tr></thead>
              <tbody>
                <tr><td><code>.github/workflows/petri-publish.yml</code></td><td>Dedicated validation gate. Fires on <code>docs/self-improving/petri-bundle/**</code>, the validator, the hygiene script, or itself; daily cron plus manual dispatch. Never deploys</td></tr>
                <tr><td><code>.github/workflows/pages.yml</code></td><td>The actual deploy. Runs the validator before npm install/build so a broken bundle aborts cheaply; copies <code>docs/self-improving/</code> into <code>site/out/</code> after the build</td></tr>
                <tr><td><code>scripts/validate_petri_bundle.py</code></td><td>Deep validator: opens each .eval zip and rejects a missing <code>results</code>, an empty <code>scores[]</code>, and empty <code>metrics</code></td></tr>
                <tr><td><code>scripts/check_repo_hygiene.py</code></td><td><code>PETRI_EVAL_FLOOR = 9</code> delete-protection ratchet; fails when the eval count drops below the floor</td></tr>
                <tr><td><code>zipfile-zstd</code> (dev group)</td><td>Shim for opening zstd-compressed .eval archives on Python 3.12 and 3.13; the standard library handles it on 3.14+</td></tr>
              </tbody>
            </table>

            <h2>Operator levers</h2>
            <pre>{`# local checks
uv run python scripts/validate_petri_bundle.py
uv run python scripts/check_repo_hygiene.py

# kick the workflow manually
gh workflow run petri-publish.yml --ref main

# inspect recent runs
gh run list --workflow=petri-publish.yml --limit=10`}</pre>

            <h2>Known failure pattern</h2>
            <p>
              The archetype is inspect_ai viewer #1747:{" "}
              <code>formatPrettyDecimal(g.metrics[i].value)</code> throws a
              TypeError when header.json carries <code>results=None</code>, an
              empty <code>scores[]</code>, or empty <code>metrics</code>. The
              validator blocks all three at the PR gate. Prior cases: PR #1129
              (partial archive) and PR #1130 (error archive). On PRs, any .eval
              file deleted relative to main is also surfaced as a warning.
            </p>

            <p className="text-[var(--ink-3)] text-sm">
              <em>References</em>: PR #1314, <code>tests/test_validate_petri_bundle.py</code>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
