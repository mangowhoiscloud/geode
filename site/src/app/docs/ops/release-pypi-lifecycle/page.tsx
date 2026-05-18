import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Release + PyPI Lifecycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/release-pypi-lifecycle"
      title="Release + PyPI Lifecycle"
      titleKo="릴리스 + PyPI 라이프사이클"
      summary="From a develop merge to a tagged PyPI release: version bump, CHANGELOG SOT, release.yml, geode-changelog skill, and the rebuild + restart cadence."
      summaryKo="develop 머지 부터 tagged PyPI 릴리스까지. version bump, CHANGELOG SOT, release.yml, geode-changelog 스킬, rebuild + restart 사이클."
    >
      <Bi
        ko={
          <>
            <h2>4 개 location 의 version SOT</h2>
            <p>
              버전은 정확히 4 군데에 동시 업데이트되어야 합니다. CHANGELOG.md, pyproject.toml, CLAUDE.md, README.md. `npm run sync-stats` 가 site SOT 와 changelog ts 까지 5 군데. 한 군데라도 누락되면 `geode version` 출력 과 PyPI tarball 메타데이터가 어긋남.
            </p>

            <h2>SemVer + 적용 기준</h2>
            <ul>
              <li><strong>MAJOR</strong>. 호환성 깨짐 (CLI flag 제거, public API rename)</li>
              <li><strong>MINOR</strong>. 새 기능 (새 tool, 새 hook, 새 provider)</li>
              <li><strong>PATCH</strong>. 버그 수정 / 내부 리팩토링</li>
              <li>문서 only 변경은 버전 bump 없음</li>
            </ul>

            <h2>릴리스 워크플로우</h2>
            <pre>{`# 1. CHANGELOG [Unreleased] -> [vX.Y.Z] — YYYY-MM-DD
# 2. 4 location 동시 bump (CHANGELOG / pyproject / CLAUDE.md / README.md)
# 3. release PR (develop -> main) — develop->main PR 은 Summary + Verification 만
# 4. main 머지 후 .github/workflows/release.yml 가 자동:
#    - python -m build
#    - twine upload --repository pypi
#    - gh release create vX.Y.Z
# 5. 재설치 + 데몬 재기동
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')
uv tool install -e . --force
uv sync
geode version          # confirm
geode serve &`}</pre>

            <h2>관련 워크플로우</h2>
            <ul>
              <li><code>.github/workflows/release.yml</code>. tag → PyPI publish</li>
              <li><code>.github/workflows/install-smoke.yml</code>. macOS + Ubuntu 의 install 회귀 슈트</li>
              <li><code>.claude/skills/geode-changelog</code>. version 결정 + entry 작성 룰</li>
            </ul>

            <p className="text-white/40 text-sm"><em>참조</em>: `CHANGELOG.md`, `.claude/skills/geode-changelog`, `.github/workflows/release.yml`.</p>
          </>
        }
        en={
          <>
            <h2>Version SOT lives in four places</h2>
            <p>
              The version string must update in CHANGELOG.md, pyproject.toml, CLAUDE.md, and README.md in the same commit. `npm run sync-stats` carries it into the site SOT and changelog.ts. If any of these drift, `geode version` and the PyPI tarball metadata disagree.
            </p>

            <h2>SemVer policy</h2>
            <ul>
              <li><strong>MAJOR</strong>. break compatibility (CLI flag removed, public API renamed)</li>
              <li><strong>MINOR</strong>. new feature (new tool, hook, provider)</li>
              <li><strong>PATCH</strong>. bug fix or internal refactor</li>
              <li>docs-only changes do not bump the version</li>
            </ul>

            <h2>Release workflow</h2>
            <pre>{`# 1. CHANGELOG [Unreleased] -> [vX.Y.Z] - YYYY-MM-DD
# 2. bump in all four locations (CHANGELOG / pyproject / CLAUDE.md / README.md)
# 3. open release PR (develop -> main); develop->main PRs may use the
#    abbreviated body (Summary + Verification only)
# 4. on main merge, .github/workflows/release.yml runs:
#    - python -m build
#    - twine upload --repository pypi
#    - gh release create vX.Y.Z
# 5. reinstall locally and restart the daemon
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')
uv tool install -e . --force
uv sync
geode version          # confirm
geode serve &`}</pre>

            <h2>Related workflows</h2>
            <ul>
              <li><code>.github/workflows/release.yml</code>. tag triggers PyPI publish</li>
              <li><code>.github/workflows/install-smoke.yml</code>. macOS + Ubuntu install regression</li>
              <li><code>.claude/skills/geode-changelog</code>. how to decide the bump and write the entry</li>
            </ul>

            <p className="text-white/40 text-sm"><em>References</em>: `CHANGELOG.md`, `.claude/skills/geode-changelog`, `.github/workflows/release.yml`.</p>
          </>
        }
      />
    </DocsShell>
  );
}
