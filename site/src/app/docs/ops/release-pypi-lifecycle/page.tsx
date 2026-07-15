import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Release and PyPI lifecycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/release-pypi-lifecycle"
      title="Release and PyPI lifecycle"
      titleKo="릴리스와 PyPI 라이프사이클"
      summary="The five version locations, GitFlow rotation, verified GitHub and PyPI promotion, Homebrew/core admission, and the rebuild cadence."
      summaryKo="버전 5개 위치, GitFlow 로테이션, 검증된 GitHub·PyPI 승격, Homebrew/core 입성, rebuild 절차를 다룹니다."
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
              <li><strong>MINOR</strong>. 새 기능. 새 도구, 훅, 프로바이더.</li>
              <li><strong>PATCH</strong>. 버그 수정과 내부 리팩토링.</li>
              <li>문서만 바뀌면 버전을 올리지 않습니다.</li>
            </ul>

            <h2>릴리스 흐름</h2>
            <p>
              평소에는 feature가 develop으로 머지됩니다. 릴리스는{" "}
              <code>release/*</code> 브랜치가 버전 스탬프와 CHANGELOG 정리를
              싣고 develop에 먼저 머지된 뒤, develop이 main으로 그대로
              통과합니다. develop이 main보다 뒤처지지 않게 하는 순서입니다.
              어떤 릴리스가 이 로테이션을 건너뛰어 develop이 main보다 뒤처지면{" "}
              <code>.github/workflows/auto-backmerge.yml</code>이 안전망으로
              발화합니다.
            </p>
            <pre>{`# 1. CHANGELOG [Unreleased] → [vX.Y.Z] - YYYY-MM-DD
# 2. 다섯 위치 동시 bump (CHANGELOG / pyproject / CLAUDE.md / README.md / README.ko.md)
# 3. release PR: release/* → develop → main (develop→main PR은 Summary + Verification 축약형 허용)
# 4. 패키지 배포는 main 머지로 자동 발화하지 않음. 아래 워크플로우를 수동 dispatch`}</pre>

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
            </p>

            <h2>Homebrew는 core 입성 절차가 따로 있습니다</h2>
            <p>
              Homebrew는 stable promotion의 일부가 아닙니다. 기존 custom
              배포 저장소는 삭제됐고, namespace가 붙는 설치 명령도 다시
              만들지 않습니다. <code>packaging/homebrew</code>의 formula
              template과 renderer는 immutable GitHub Release sdist를 쓰는{" "}
              <code>geode-agent</code> Homebrew/core 후보만 만듭니다.
            </p>
            <p>
              첫 upstream PR은 Homebrew의 최신 acceptable-formula 정책을
              따릅니다. GEODE가 beta 표기를 벗어나고 외부 사용 및 notability
              조건을 충족하기 전에는 검증된 후보를 fork에만 보관합니다.
              Homebrew/core가 수락한 뒤 공식 formula API와 깨끗한 macOS·Linux
              환경에서 unqualified install, version, formula test, uninstall
              게이트가 모두 통과해야 공개 설치 화면에 Homebrew를 다시 추가할
              수 있습니다. 실제 후보 갱신과 검증 명령은 저장소의{" "}
              <code>packaging/homebrew/README.md</code>에만 둡니다.
            </p>

            <h2>릴리스 후 rebuild</h2>
            <p>
              main 머지 후 로컬 런타임을 새 코드로 올립니다. 두 함정이
              있습니다. 데몬 정지는 <code>pkill -f</code>를 써야 합니다.{" "}
              <code>ps aux | grep</code>은 긴 파이썬 경로가 잘려 데몬을 못 잡고,
              살아남은 옛 데몬이 소켓을 두고 새 데몬과 경합합니다. 그리고{" "}
              <code>[audit]</code> extra가 필수입니다. 빠지면 inspect_ai가 없어
              자기개선 루프의 감사가 측정 대신 실패합니다.
            </p>
            <pre>{`pkill -f "geode serve" || true          # 확인: pgrep -f "geode serve"
uv tool install -e ".[audit]" --force   # [audit] extra 필수 (inspect_ai)
uv sync --extra audit
geode version                            # 버전 일치 확인
geode serve &                            # 데몬 재기동`}</pre>

            <h2>관련 파일</h2>
            <ul>
              <li><code>.github/workflows/release.yml</code>. 수동 검증 + 배포 파이프라인.</li>
              <li><code>.github/workflows/install-smoke.yml</code>. macOS와 Ubuntu의 설치 회귀.</li>
              <li><code>.github/workflows/auto-backmerge.yml</code>. develop 뒤처짐 안전망.</li>
              <li><code>scripts/verify_public_distribution.py</code>. GitHub·PyPI 공개 배포 일치 검증.</li>
              <li><code>packaging/homebrew</code>. Homebrew/core 후보 template과 운영 지침.</li>
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
              <li><strong>MINOR</strong>. New feature: a new tool, hook, or provider.</li>
              <li><strong>PATCH</strong>. Bug fix or internal refactor.</li>
              <li>Docs-only changes do not bump the version.</li>
            </ul>

            <h2>Release flow</h2>
            <p>
              Day to day, features merge into develop. For a release, a{" "}
              <code>release/*</code> branch carries the version stamp and
              CHANGELOG cleanup, merges into develop first, and develop then
              passes straight through to main. That order keeps develop from
              lagging main. If a release ever skips the rotation,{" "}
              <code>.github/workflows/auto-backmerge.yml</code> fires as the
              safety net.
            </p>
            <pre>{`# 1. CHANGELOG [Unreleased] → [vX.Y.Z] - YYYY-MM-DD
# 2. bump all five locations (CHANGELOG / pyproject / CLAUDE.md / README.md / README.ko.md)
# 3. release PR: release/* → develop → main (develop→main PRs may use the
#    abbreviated Summary + Verification body)
# 4. package publishing does NOT fire on the main merge. dispatch the
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
            </p>

            <h2>Homebrew has a separate core-admission path</h2>
            <p>
              Homebrew is not part of the stable-promotion workflow. The former
              custom distribution repository is deleted, and a qualified
              install command must not return. The formula template and
              renderer under <code>packaging/homebrew</code> prepare only a{" "}
              <code>geode-agent</code> Homebrew/core candidate backed by the
              immutable GitHub Release sdist.
            </p>
            <p>
              A first upstream PR must satisfy Homebrew&apos;s current acceptable-
              formula policy. Until GEODE is no longer marked beta and meets
              the external-use and notability requirements, keep the audited
              candidate in the fork. After Homebrew/core accepts it, add
              Homebrew back to the public install UI only after the official
              formula API and clean macOS and Linux install, version, formula-
              test, and uninstall gates pass. Keep the concrete candidate and
              verification commands in the repository-only{" "}
              <code>packaging/homebrew/README.md</code> until then.
            </p>

            <h2>Rebuild after a release</h2>
            <p>
              After the main merge, bring the local runtime up to the new code.
              Two traps. Stop the daemon with <code>pkill -f</code>:{" "}
              <code>ps aux | grep</code> truncates the long Python path, misses
              the daemon, and the stale survivor then fights the new daemon over
              the socket. And the <code>[audit]</code> extra is required;
              without it inspect_ai is missing and the self-improving
              loop&apos;s audits fail instead of measuring.
            </p>
            <pre>{`pkill -f "geode serve" || true          # verify: pgrep -f "geode serve"
uv tool install -e ".[audit]" --force   # the [audit] extra is REQUIRED (inspect_ai)
uv sync --extra audit
geode version                            # confirm the version matches
geode serve &                            # restart the daemon`}</pre>

            <h2>Related files</h2>
            <ul>
              <li><code>.github/workflows/release.yml</code>. The manual validate + publish pipeline.</li>
              <li><code>.github/workflows/install-smoke.yml</code>. Install regression on macOS and Ubuntu.</li>
              <li><code>.github/workflows/auto-backmerge.yml</code>. The develop-lag safety net.</li>
              <li><code>scripts/verify_public_distribution.py</code>. Public GitHub/PyPI parity verification.</li>
              <li><code>packaging/homebrew</code>. Homebrew/core candidate template and operating guide.</li>
              <li><code>CHANGELOG.md</code>. Keep a Changelog + SemVer source of truth.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
