import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Release and PyPI lifecycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/release-pypi-lifecycle"
      title="Release and PyPI lifecycle"
      titleKo="릴리스와 PyPI 라이프사이클"
      summary="The five version locations, GitFlow rotation, verified GitHub and PyPI promotion, and the rebuild cadence."
      summaryKo="버전 5개 위치, GitFlow 로테이션, 검증된 GitHub·PyPI 승격, rebuild 절차를 다룹니다."
    >
      <Bi
        ko={
          <>
            <h2>버전은 다섯 곳에서 동시에 움직입니다</h2>
            <p>
              버전 문자열은 다섯 곳에 살고, 같은 커밋에서 함께 갱신해야
              합니다. CHANGELOG.md, pyproject.toml, CLAUDE.md, README.md,
              README.ko.md. 사이트 쪽은 <code>npm run sync-stats</code>
              (<code>site/scripts/sync-stats.mjs</code>)가 SoT와 changelog
              데이터를 재생성합니다. 한 곳이라도 어긋나면{" "}
              <code>geode version</code> 출력과 패키지 메타데이터가
              불일치합니다.
            </p>

            <h2>SemVer 기준</h2>
            <ul>
              <li><strong>MAJOR</strong>. 호환성 파괴. CLI 플래그 제거, 공개 API 리네임.</li>
              <li><strong>MINOR</strong>. 운영자가 선언한 마일스톤 전용. deprecation 문자열에 예약된 번호(<code>removed in v…</code>)를 먼저 확인.</li>
              <li><strong>PATCH</strong>. 기본값 — 새 기능·버그 수정·리팩토링 등 일상 릴리스 전부(0.99.x patch-train의 연속).</li>
              <li>문서만 바뀌면 버전을 올리지 않습니다.</li>
            </ul>

            <h2>wheel이 소유하는 설치 경계</h2>
            <p>
              <code>geode-agent</code> wheel은 Python 생태계의 불변 제품
              설치물입니다. 네 개 CLI와 <code>core</code>, <code>evals</code>,{" "}
              <code>evolve</code> 코드, 승인된 builtin skill, 정적 reference
              input을 함께 버전 관리합니다. 실행 중 생성되거나 계속 바뀌는
              데이터는 wheel에 쓰지 않습니다.
            </p>
            <table>
              <thead><tr><th>wheel 안</th><th>wheel 밖</th></tr></thead>
              <tbody>
                <tr><td>런타임·평가·evolve 코드와 console entry point</td><td><code>GEODE_HOME</code>의 상태·로그·생성 helper</td></tr>
                <tr><td>정확히 열거된 builtin skill과 immutable reference input</td><td>rolling ledger, 결과 파일, 사용자·프로젝트 skill</td></tr>
                <tr><td>읽기 전용 helper source</td><td><code>GEODE_EVOLVE_WORKSPACE</code>가 가리키는 실제 Git checkout</td></tr>
              </tbody>
            </table>
            <p>
              따라서 설치된 <code>geode-evolve</code>는 reference input을 읽을
              수 있지만 mutation과 promotion에는 writable GEODE checkout이
              필요합니다. computer-use helper의 생성물은
              <code>GEODE_HOME/helpers/computer-use</code>에 놓입니다. 별도 core,
              eval, evolve wheel은 독립 설치 계약이나 릴리스 주기가 실제로
              생기기 전까지 만들지 않습니다.
            </p>

            <h2>릴리스 흐름</h2>
            <p>
              평소에는 feature가 develop으로 머지됩니다. 릴리스는{" "}
              <code>release/*</code> 브랜치가 버전 스탬프와 CHANGELOG 정리를
              싣고 develop에 먼저 머지된 뒤, develop이 main으로 그대로
              통과합니다. 승격 직전에는 두 원격 브랜치를 fetch하고 내용을
              비교합니다. main에 추적 전용 변경이 있고 충돌이 없으면 현재 main
              head에서 develop로 직접 CI-gated PR을 엽니다. 충돌 해결이 필요할
              때만 현재 develop에서 <code>sync/main-into-develop-*</code> 브랜치를
              만들고 현재 main을 명시적 merge commit으로 병합합니다. 이 sync
              head는 두 원격 tip을 정확한 부모로 가져야 하며 merge 직전에 trust
              resolver를 다시 통과해야 합니다. 자동 backmerge workflow는 없습니다.
            </p>
            <pre>{`# 1. CHANGELOG [Unreleased] → [vX.Y.Z] - YYYY-MM-DD
# 2. 다섯 위치 동시 bump (CHANGELOG / pyproject / CLAUDE.md / README.md / README.ko.md)
# 3. main drift: clean이면 main → develop PR, 충돌 시에만 sync/main-into-develop-*
# 4. release PR: release/* → develop → main (develop→main PR은 Summary + Verification 축약형 허용)
# 5. 패키지 배포는 main 머지로 자동 발화하지 않음. 아래 워크플로우를 수동 dispatch`}</pre>

            <h2>release.yml은 수동 전용입니다</h2>
            <p>
              main 푸시는 CI와 Pages만 돌립니다. 패키지 배포는{" "}
              <code>.github/workflows/release.yml</code>을 workflow_dispatch로
              직접 실행해야 하고, 배포 잡들은 보호된 <code>release</code>{" "}
              환경을 지납니다.
            </p>
            <table>
              <thead><tr><th>입력</th><th>의미</th></tr></thead>
              <tbody>
                <tr><td><code>ref</code> / <code>version</code></td><td>릴리스할 ref와 기대 버전. 메타데이터 불일치는 validate 단계에서 실패</td></tr>
                <tr><td><code>publish_stable</code></td><td>GitHub Release와 PyPI를 한 승격으로 출하 (기본 false)</td></tr>
                <tr><td><code>publish_huggingface_artifacts</code></td><td>버전드 릴리스 번들을 HF dataset repo로 업로드 (기본 false)</td></tr>
              </tbody>
            </table>
            <p>
              validate-build 잡이 lint와 hygiene, 타입 체크, 프롬프트 무결성,
              공식 문서 생성 게이트, 테스트, 런타임 E2E 스모크, twine check를
              모두 통과해야 배포 잡이 시작됩니다. stable promotion은 현재{" "}
              <code>origin/main</code> SHA를 사용하고, 복구 실행에서는 변경되지
              않은 기존 annotated tag target만 허용합니다. 그 뒤 annotated
              tag와 GitHub Release, Trusted Publishing, 공개 PyPI exact-version
              설치 검증을 거칩니다. 마지막 읽기 전용 검증기는 tag target,
              GitHub asset, PyPI 파일, SHA-256이 모두 같은 릴리스인지 확인합니다.
              clean-wheel gate는 설치된 distribution 파일 전체의 digest가 거부된
              evolution mutation 뒤에도 같은지, mutable experiment state가 빠졌는지,
              정확한 builtin-skill allowlist와 설치된 daemon IPC 버전이 맞는지도
              함께 검증합니다.
            </p>

            <h2>릴리스 후 설치 갱신</h2>
            <p>
              PyPI/uv stable 설치는 <code>geode update</code>로 갱신합니다. 기본
              명령은 현재 major/minor의 최신 patch만 허용하고, minor/major는{" "}
              <code>--latest</code>를 명시해야 합니다. updater는 설치 metadata와
              prospective version을 먼저 검증하고, 실행 중 daemon을 package 교체
              전에 중지합니다. stop 실패면 설치를 건드리지 않고, install 실패면
              중지 상태를 유지하며, 성공한 재시작은 CLI와 IPC가 같은 버전일 때만
              완료됩니다.
            </p>
            <pre>{`geode update                  # 최신 호환 patch
geode update --latest         # minor/major를 명시적으로 허용
geode version                 # 공개 버전 확인`}</pre>
            <p>
              저장소에서 작업하는 editable <code>[audit]</code> 개발 설치는 stable
              wheel과 별개입니다. 이 경우에만 daemon을 직접 중지하고 checkout을
              재설치합니다. <code>[audit]</code> extra가 빠지면 inspect_ai 기반
              평가를 실행할 수 없습니다.
            </p>
            <pre>{`pkill -f "geode serve" || true
uv tool install -e ".[audit]" --force --python 3.12
uv sync --extra audit
geode version
geode serve &`}</pre>

            <h2>관련 파일</h2>
            <ul>
              <li><code>.github/workflows/release.yml</code>. 수동 검증 + 배포 파이프라인.</li>
              <li><code>.github/workflows/install-smoke.yml</code>. macOS와 Ubuntu의 설치 회귀.</li>
              <li><code>scripts/resolve_architecture_roadmap_trust.py</code>. 충돌 해결형 main → develop sync의 정확한 부모·출처 검증.</li>
              <li><code>docs/workflow.md</code>. pre-sync와 GitFlow 운영 정본.</li>
              <li><code>scripts/verify_public_distribution.py</code>. GitHub·PyPI 공개 배포 일치 검증.</li>
              <li><code>docs/architecture/immutable-distribution-lifecycle.md</code>. wheel·state·workspace 경계와 frontier 비교 근거.</li>
              <li><code>CHANGELOG.md</code>. Keep a Changelog + SemVer 정본.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>The version moves in five places at once</h2>
            <p>
              The version string must update in five locations in the same
              commit: CHANGELOG.md, pyproject.toml, CLAUDE.md, README.md, and
              README.ko.md. On the site side, <code>npm run sync-stats</code>{" "}
              (<code>site/scripts/sync-stats.mjs</code>) regenerates the SoT and
              changelog data. If any location drifts,{" "}
              <code>geode version</code> and the package metadata disagree.
            </p>

            <h2>SemVer policy</h2>
            <ul>
              <li><strong>MAJOR</strong>. Compatibility break: a CLI flag removed, a public API renamed.</li>
              <li><strong>MINOR</strong>. Operator-declared milestones only. Check numbers pledged in deprecation strings (<code>removed in v…</code>) first.</li>
              <li><strong>PATCH</strong>. The default — every routine release including features, fixes, and refactors (the 0.99.x patch-train, continued).</li>
              <li>Docs-only changes do not bump the version.</li>
            </ul>

            <h2>The wheel&apos;s installation boundary</h2>
            <p>
              The <code>geode-agent</code> wheel is GEODE&apos;s immutable product
              artifact for the Python ecosystem. It versions the four CLIs,
              the <code>core</code>, <code>evals</code>, and <code>evolve</code>{" "}
              packages, approved built-in skills, and static reference inputs.
              Data created or continuously updated at runtime is never written
              into the wheel.
            </p>
            <table>
              <thead><tr><th>Inside the wheel</th><th>Outside the wheel</th></tr></thead>
              <tbody>
                <tr><td>Runtime, evaluation, and evolve code plus console entry points</td><td>State, logs, and generated helpers under <code>GEODE_HOME</code></td></tr>
                <tr><td>Exactly enumerated built-in skills and immutable reference inputs</td><td>Rolling ledgers, results, and user or project skills</td></tr>
                <tr><td>Read-only helper source</td><td>The real Git checkout selected by <code>GEODE_EVOLVE_WORKSPACE</code></td></tr>
              </tbody>
            </table>
            <p>
              An installed <code>geode-evolve</code> may read packaged reference
              inputs, but mutation and promotion require a writable GEODE
              checkout. Computer-use helper output also belongs under{" "}
              <code>GEODE_HOME/helpers/computer-use</code>, never in
              site-packages. Separate core, eval, or evolve wheels remain
              unnecessary until an independent install contract or release
              cadence is measured.
            </p>

            <h2>Release flow</h2>
            <p>
              Day to day, features merge into develop. For a release, a{" "}
              <code>release/*</code> branch carries the version stamp and
              CHANGELOG cleanup, merges into develop first, and develop then
              passes straight through to main. Immediately before promotion,
              fetch and compare both remote branches. If main contains unique
              tracking changes and the sync is conflict-free, open a CI-gated PR
              directly from the current main head to develop. Only when conflict
              resolution is required, create <code>sync/main-into-develop-*</code>
              from current develop and merge current main in an explicit merge
              commit. That sync head must have the two current remote tips as its
              exact parents and rerun the trust resolver immediately before merge.
              There is no automatic backmerge workflow.
            </p>
            <pre>{`# 1. CHANGELOG [Unreleased] → [vX.Y.Z] - YYYY-MM-DD
# 2. bump all five locations (CHANGELOG / pyproject / CLAUDE.md / README.md / README.ko.md)
# 3. main drift: main → develop PR if clean; sync/main-into-develop-* only on conflict
# 4. release PR: release/* → develop → main (develop→main PRs may use the
#    abbreviated Summary + Verification body)
# 5. package publishing does NOT fire on the main merge. dispatch the
#    workflow below manually`}</pre>

            <h2>release.yml is manual-only</h2>
            <p>
              Pushes to main run CI and Pages, nothing else. Publishing requires
              dispatching <code>.github/workflows/release.yml</code> by hand,
              and the publish jobs pass through the protected{" "}
              <code>release</code> environment.
            </p>
            <table>
              <thead><tr><th>Input</th><th>Meaning</th></tr></thead>
              <tbody>
                <tr><td><code>ref</code> / <code>version</code></td><td>The ref to release and the expected version; a metadata mismatch fails validation</td></tr>
                <tr><td><code>publish_stable</code></td><td>Ship GitHub Release and PyPI as one promotion (default false)</td></tr>
                <tr><td><code>publish_huggingface_artifacts</code></td><td>Upload the versioned bundle to an HF dataset repo (default false)</td></tr>
              </tbody>
            </table>
            <p>
              The validate-build job must pass lint and hygiene, type check,
              prompt integrity, the official docs generation gate, tests, the
              runtime E2E smoke, and twine check before any publish job starts.
              A stable promotion uses the current <code>origin/main</code> SHA;
              a repair run accepts only an unchanged existing annotated-tag
              target. It then creates the annotated tag and GitHub Release,
              publishes through PyPI Trusted Publishing, and verifies an
              exact-version install from the public index. A final read-only
              verifier requires the tag target, GitHub assets, PyPI files, and
              SHA-256 digests to describe the same release.
              The clean-wheel gate also proves that every installed
              distribution digest survives a rejected evolution mutation,
              mutable experiment state is absent, the exact builtin-skill
              allowlist is complete, and the installed daemon reports the
              expected IPC version.
            </p>

            <h2>Update an installation after a release</h2>
            <p>
              Update a stable PyPI/uv installation with <code>geode update</code>.
              The default accepts only the latest patch in the current
              major/minor series; <code>--latest</code> explicitly permits a minor
              or major upgrade. The updater validates installation metadata and
              the prospective version first, stops a running daemon before
              replacing package files, leaves the installation untouched when
              stop fails, and leaves the daemon stopped when install fails. A
              successful restart must report the same CLI and IPC version.
            </p>
            <pre>{`geode update                  # latest compatible patch
geode update --latest         # explicitly permit minor/major
geode version                 # verify the public version`}</pre>
            <p>
              An editable <code>[audit]</code> developer install from a repository
              is separate from the stable wheel. Only that path uses a manual
              stop and checkout reinstall. Keep the <code>[audit]</code> extra;
              without it inspect_ai-backed evaluations are unavailable.
            </p>
            <pre>{`pkill -f "geode serve" || true
uv tool install -e ".[audit]" --force --python 3.12
uv sync --extra audit
geode version
geode serve &`}</pre>

            <h2>Related files</h2>
            <ul>
              <li><code>.github/workflows/release.yml</code>. The manual validate + publish pipeline.</li>
              <li><code>.github/workflows/install-smoke.yml</code>. Install regression on macOS and Ubuntu.</li>
              <li><code>scripts/resolve_architecture_roadmap_trust.py</code>. Exact-parent and source validation for conflict-resolved main → develop syncs.</li>
              <li><code>docs/workflow.md</code>. Canonical pre-sync and GitFlow procedure.</li>
              <li><code>scripts/verify_public_distribution.py</code>. Public GitHub/PyPI parity verification.</li>
              <li><code>docs/architecture/immutable-distribution-lifecycle.md</code>. Frontier evidence and the wheel/state/workspace boundary.</li>
              <li><code>CHANGELOG.md</code>. Keep a Changelog + SemVer source of truth.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
