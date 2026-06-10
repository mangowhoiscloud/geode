import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Petri Bundle Isolation — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/petri-bundle-isolation"
      title="Petri Bundle Isolation"
      titleKo="Petri 번들 격리"
      summary="Operator reference for the petri-publish.yml workflow + validator + hygiene ratchet that keep the alignment audit bundle live even when the site build fails."
      summaryKo="petri-publish.yml workflow + validator + hygiene ratchet 의 운영자 reference. site 빌드 실패와 무관하게 alignment audit 번들이 살아 있도록 보장."
    >
      <Bi
        ko={
          <>
            <h2>왜 격리되어 있나</h2>
            <p>
              `pages.yml` 한 워크플로우에 site + petri-bundle 이 묶여 있으면, site Next.js 빌드 실패가 petri-bundle 배포까지 끌어내립니다. PR #1314 로 ratchet 을 분리: petri 변경은 site 와 무관한 별도 워크플로우에서 검증, site 빌드 실패는 petri 의 deploy 를 막지 못함.
            </p>

            <h2>구성 요소</h2>
            <table>
              <thead><tr><th>파일</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><code>.github/workflows/petri-publish.yml</code></td><td>전용 PR-gate + 매일 cron. docs/self-improving/petri-bundle/** + validator + hygiene 변경 시 가동</td></tr>
                <tr><td><code>.github/workflows/pages.yml</code></td><td>validator 호출을 npm install/build 직전 으로 이동. 빌드 비용 낭비 차단</td></tr>
                <tr><td><code>scripts/validate_petri_bundle.py</code></td><td>zip 내부 header.json.results 까지 검증 (results=None / empty scores / empty metrics 거부)</td></tr>
                <tr><td><code>scripts/check_repo_hygiene.py</code></td><td>PETRI_EVAL_FLOOR=9 삭제 보호 ratchet</td></tr>
                <tr><td><code>zipfile-zstd</code> dev dep</td><td>Python 3.12-3.13 의 zstd shim. 3.14+ 에서는 no-op</td></tr>
              </tbody>
            </table>

            <h2>운영자 트리거</h2>
            <pre>{`# 로컬 검증
uv run python scripts/validate_petri_bundle.py
uv run python scripts/check_repo_hygiene.py

# 수동 workflow 실행
gh workflow run petri-publish.yml --ref main

# 직전 회귀 점검
gh run list --workflow=petri-publish.yml --limit=10`}</pre>

            <h2>알려진 trigger 패턴</h2>
            <p>
              `inspect_ai #1747` 의 `formatPrettyDecimal(g.metrics[i].value)` TypeError. 원인은 header.json 의 results=None / scores[] 빈 배열 / metrics 빈 dict. validator 는 위 세 케이스를 PR-gate 에서 차단합니다. 직전 사례: PR #1129 partial archive, PR #1130 error archive.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>참조</em>: PR #1314, `tests/test_validate_petri_bundle.py` (13 tests).</p>
          </>
        }
        en={
          <>
            <h2>Why isolation</h2>
            <p>
              When site + petri-bundle share `pages.yml`, a Next.js site failure drags the bundle down with it. PR #1314 split the ratchet: a petri change is validated in its own workflow, and a site build failure can no longer block the bundle deploy.
            </p>

            <h2>The moving parts</h2>
            <table>
              <thead><tr><th>file</th><th>role</th></tr></thead>
              <tbody>
                <tr><td><code>.github/workflows/petri-publish.yml</code></td><td>dedicated PR gate + daily cron. fires on docs/self-improving/petri-bundle/**, validator, hygiene</td></tr>
                <tr><td><code>.github/workflows/pages.yml</code></td><td>validator now runs before npm install/build, so a broken bundle aborts cheaply</td></tr>
                <tr><td><code>scripts/validate_petri_bundle.py</code></td><td>opens each .eval zip and rejects results=None, empty scores, empty metrics</td></tr>
                <tr><td><code>scripts/check_repo_hygiene.py</code></td><td>PETRI_EVAL_FLOOR=9 delete-protection ratchet</td></tr>
                <tr><td><code>zipfile-zstd</code> dev dep</td><td>zstd shim for Python 3.12-3.13. a no-op on 3.14+</td></tr>
              </tbody>
            </table>

            <h2>Operator levers</h2>
            <pre>{`# local check
uv run python scripts/validate_petri_bundle.py
uv run python scripts/check_repo_hygiene.py

# kick the workflow manually
gh workflow run petri-publish.yml --ref main

# inspect recent runs
gh run list --workflow=petri-publish.yml --limit=10`}</pre>

            <h2>Known failure pattern</h2>
            <p>
              `inspect_ai #1747`'s `formatPrettyDecimal(g.metrics[i].value)` TypeError. Trigger: header.json with results=None, an empty scores[], or empty metrics. The validator rejects all three at the PR gate. Prior cases: PR #1129 partial archive, PR #1130 error archive.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>References</em>: PR #1314, `tests/test_validate_petri_bundle.py` (13 tests).</p>
          </>
        }
      />
    </DocsShell>
  );
}
