import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Publish a trajectory — GEODE Docs" };

const exportCommand = `geode session export-trajectory session-123 \\
  --out trajectory-local.json \\
  --sil-eval run.eval \\
  --digest-content`;

const reviewRecord = `{
  "reviewer": "release owner or review team",
  "reviewed_at": "2026-08-01T12:00:00Z",
  "method": "allowlist review plus secret and identity scan",
  "scope": "campaign-2026-08-01",
  "attestation": "Only the declared normalized trajectories are approved."
}`;

const stageCommand = `geode session stage-trajectory-release trajectory-public.json \\
  --destination /tmp/geode-trajectory-releases \\
  --source sil \\
  --scope campaign-2026-08-01 \\
  --privacy-review privacy-review.json \\
  --source-artifact run.eval=/absolute/path/to/run.eval \\
  --allow-replay-incomplete`;

const verifyCommand = `geode session verify-trajectory-release <release-dir> \\
  --expected-manifest-sha256 <digest-recorded-before-copy>`;

export default function Page() {
  return (
    <DocsShell
      slug="guides/publish-trajectory"
      title="Publish a trajectory"
      titleKo="Trajectory 게시"
      summary="Export canonical session history, review a public candidate, stage an immutable release, and verify the exact bytes read back from the artifact repository."
      summaryKo="정본 session history를 export하고, 공개 후보를 검토한 뒤 immutable release로 staging하고 artifact 저장소에서 다시 읽은 바이트를 검증합니다."
    >
      <Bi
        ko={
          <>
            <p>
              이 절차는 로컬 실행 기록을 공개 증거로 승격합니다. 게시 대상은
              append-only Git/PR 저장소인{" "}
              <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts">
                geode-eval-artifacts
              </a>
              입니다. 전체 artifact 트리를 복사하지 않고 검토된 trajectory release
              디렉터리 하나만 게시합니다.
            </p>

            <h2>1. SQLite 정본에서 export</h2>
            <pre>{exportCommand}</pre>
            <p>
              <code>--sil-eval</code>은 Inspect <code>.eval</code>의 SHA-256을
              <code>evidence_refs</code>와 <code>artifact_digests</code>에 연결합니다.
              <code>--digest-content</code>는 비허용 payload body를 digest로 바꾸므로
              결과가 scope-complete여도 replay-incomplete일 수 있습니다. SIL
              실행에서만 <code>--sil-eval</code>을 지정합니다.
            </p>
            <p>
              이 명령의 결과는 <code>privacy.review_state=local</code>인 로컬
              artifact입니다. staging 명령은 이를 자동으로 승인하지 않습니다.
            </p>

            <h2>2. 별도의 공개 후보 검토</h2>
            <table>
              <thead><tr><th>산출물</th><th>역할</th><th>규칙</th></tr></thead>
              <tbody>
                <tr><td><code>trajectory-local.json</code></td><td>로컬 export</td><td>보존하며 직접 공개하지 않음</td></tr>
                <tr><td><code>trajectory-public.json</code></td><td>allowlist 기반 공개 후보</td><td>공개 바이트를 검토한 뒤 <code>privacy.review_state=reviewed</code>로 표시</td></tr>
                <tr><td><code>privacy-review.json</code></td><td>release 범위 attestation</td><td><code>scope</code>가 CLI <code>--scope</code>와 정확히 같아야 함</td></tr>
              </tbody>
            </table>
            <p>
              공개 후보에서 로컬 경로, 사용자 식별자, credential, raw prompt/tool
              body를 검토합니다. sealed Crucible pack, 선택 row identity, selection
              salt, 환경 파일은 공개 후보에 넣지 않습니다. 검토는 실제 공개
              바이트를 대상으로 하며 <code>review_state</code> 값만 바꾸는 행위를
              허용하지 않습니다.
            </p>
            <pre>{reviewRecord}</pre>
            <p>
              staging은 이 다섯 필드를 canonicalize한 뒤
              <code>record_sha256</code>을 계산합니다. trajectory 자체의 privacy review와
              release 범위 review 둘 다 필요합니다.
            </p>

            <h2>3. 공개 release staging</h2>
            <pre>{stageCommand}</pre>
            <table>
              <thead><tr><th>게이트</th><th>조건</th></tr></thead>
              <tbody>
                <tr><td>Scope</td><td>모든 trajectory의 <code>scope_complete=true</code></td></tr>
                <tr><td>Replay</td><td>기본 <code>replay_complete=true</code>; private body digest인 검토본만 <code>--allow-replay-incomplete</code></td></tr>
                <tr><td>Source bytes</td><td>모든 <code>artifact_digests.path</code>에 대응하는 <code>--source-artifact REF=PATH</code>와 SHA-256 일치</td></tr>
                <tr><td>Identity</td><td>trajectory ID와 release 경로가 고유하며 기존 디렉터리를 덮어쓰지 않음</td></tr>
                <tr><td>Privacy</td><td>reviewed 상태, 구조화 attestation, secret/identity scan 0건</td></tr>
              </tbody>
            </table>
            <p>
              <code>--allow-replay-incomplete</code>는 scope 누락을 허용하지 않습니다.
              source artifact는 digest 검증에만 사용되며 자동으로 공개 디렉터리에
              복사되지 않습니다.
            </p>

            <h2>4. 로컬 검증과 append-only PR</h2>
            <p>
              새 release의 <code>manifest.json</code> SHA-256을 staging 디렉터리 밖에
              기록한 뒤 검증합니다.
            </p>
            <pre>{verifyCommand}</pre>
            <ol>
              <li><code>geode-eval-artifacts</code>의 새 branch/worktree를 만듭니다.</li>
              <li>content-addressed release 디렉터리 하나만 복사합니다.</li>
              <li>PR에서 manifest, 공개 바이트, privacy attestation을 리뷰합니다.</li>
              <li>병합 후 exact merge commit에서 release를 새 디렉터리로 다시 읽습니다.</li>
              <li>복사 전에 기록한 manifest SHA-256으로 같은 검증 명령을 다시 실행합니다.</li>
              <li>점수·문서에는 merge commit의 blob/tree 링크를 기록합니다.</li>
            </ol>
            <p>
              staging 디렉터리를 한 번 더 읽는 것은 remote read-back 증거가 아닙니다.
              병합된 원격 바이트를 독립적으로 내려받아야 합니다.
            </p>

            <h2>5. SIL·Crucible authority</h2>
            <p>
              모든 external reference는 <code>kind</code>, <code>schema_id</code>,
              <code>authority</code>, <code>reference</code>를 가지며 파일을 가리키면
              <code>path</code>와 <code>sha256</code>을 함께 둡니다.
            </p>
            <table>
              <thead><tr><th>Reference</th><th>생성 조건</th><th>정본</th></tr></thead>
              <tbody>
                <tr><td><code>sil_eval</code> / <code>inspect_ai.eval@native</code></td><td><code>export-trajectory --sil-eval</code></td><td>Inspect <code>.eval</code> score와 SIL mutation/attribution ledger</td></tr>
                <tr><td><code>native_receipt</code> / <code>tau2.results@native</code></td><td>tau2 결과 export마다</td><td>tau2 <code>results.json</code></td></tr>
                <tr><td><code>crucible_evidence</code></td><td>frozen contract ID와 identity preflight가 모두 존재할 때만</td><td><code>crucible.evidence.v3</code>, experiment contract, executable verifier</td></tr>
              </tbody>
            </table>
            <p>
              GEODE release manifest는 verdict를 소유하거나 candidate를 승격하지 않습니다.
              외부 루프는 <code>PostVerify</code>의 typed
              <code>evidence_refs</code>로 이 정본들을 연결하고 accept/revise/escalate만
              결정합니다.
            </p>

            <h2>Schema 정본</h2>
            <ul>
              <li><a href="https://github.com/mangowhoiscloud/geode/blob/main/core/observability/schemas/trajectory.schema.json"><code>geode.trajectory@1</code></a></li>
              <li><a href="https://github.com/mangowhoiscloud/geode/blob/main/core/observability/schemas/trajectory-release.schema.json"><code>geode.trajectory-release@1</code></a></li>
            </ul>

            <h2>실패 시 확인</h2>
            <ul>
              <li><strong>not scope-complete:</strong> missing correlation, ordinal gap, orphan tool result를 먼저 수정합니다.</li>
              <li><strong>not replay-complete:</strong> 실제 privacy reduction인지 확인한 뒤에만 명시적 waiver를 사용합니다.</li>
              <li><strong>source digest mismatch:</strong> trajectory가 참조한 원본 바이트를 매핑합니다.</li>
              <li><strong>privacy scan failed:</strong> finding을 지운 새 public candidate를 만들며 기존 release를 덮어쓰지 않습니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              This workflow promotes a local execution record into public
              evidence. The destination is not JFrog Artifactory; it is the
              append-only Git/PR repository{" "}
              <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts">
                geode-eval-artifacts
              </a>
              . Publish one reviewed trajectory release directory, never the
              entire artifact tree.
            </p>

            <h2>1. Export from canonical SQLite</h2>
            <pre>{exportCommand}</pre>
            <p>
              <code>--sil-eval</code> binds the Inspect <code>.eval</code> SHA-256
              through both <code>evidence_refs</code> and
              <code>artifact_digests</code>. <code>--digest-content</code> replaces
              non-allowlisted payload bodies with digests, so the result can be
              scope-complete but replay-incomplete. Omit <code>--sil-eval</code> for
              non-SIL runs.
            </p>
            <p>
              This command produces a local artifact with
              <code>privacy.review_state=local</code>. The staging command does not
              approve it automatically.
            </p>

            <h2>2. Review a separate public candidate</h2>
            <table>
              <thead><tr><th>Artifact</th><th>Role</th><th>Rule</th></tr></thead>
              <tbody>
                <tr><td><code>trajectory-local.json</code></td><td>Local export</td><td>Retain it; do not publish it directly</td></tr>
                <tr><td><code>trajectory-public.json</code></td><td>Allowlisted public candidate</td><td>Review the exact public bytes, then mark <code>privacy.review_state=reviewed</code></td></tr>
                <tr><td><code>privacy-review.json</code></td><td>Release-scope attestation</td><td><code>scope</code> must exactly equal CLI <code>--scope</code></td></tr>
              </tbody>
            </table>
            <p>
              Review local paths, personal identifiers, credentials, and raw
              prompt/tool bodies in the public candidate. Never include sealed
              Crucible packs, selected-row identities, selection salts, or
              environment files. Changing <code>review_state</code> is not a
              substitute for performing the review.
            </p>
            <pre>{reviewRecord}</pre>
            <p>
              Staging canonicalizes these five fields and computes
              <code>record_sha256</code>. Both the trajectory-level privacy review
              and the release-scope review are required.
            </p>

            <h2>3. Stage the public release</h2>
            <pre>{stageCommand}</pre>
            <table>
              <thead><tr><th>Gate</th><th>Condition</th></tr></thead>
              <tbody>
                <tr><td>Scope</td><td>Every trajectory has <code>scope_complete=true</code></td></tr>
                <tr><td>Replay</td><td><code>replay_complete=true</code> by default; only reviewed private-body digests use <code>--allow-replay-incomplete</code></td></tr>
                <tr><td>Source bytes</td><td>Every <code>artifact_digests.path</code> has a matching <code>--source-artifact REF=PATH</code> whose SHA-256 matches</td></tr>
                <tr><td>Identity</td><td>Trajectory IDs and release paths are unique; existing directories are never overwritten</td></tr>
                <tr><td>Privacy</td><td>Reviewed state, structured attestation, and zero secret/identity scan findings</td></tr>
              </tbody>
            </table>
            <p>
              <code>--allow-replay-incomplete</code> never waives missing scope.
              Source artifacts are used to verify digests and are not copied into
              the public directory automatically.
            </p>

            <h2>4. Verify locally and open an append-only PR</h2>
            <p>
              Record the new release&apos;s <code>manifest.json</code> SHA-256 outside
              the staging directory, then verify it.
            </p>
            <pre>{verifyCommand}</pre>
            <ol>
              <li>Create a fresh <code>geode-eval-artifacts</code> branch/worktree.</li>
              <li>Copy only the content-addressed release directory.</li>
              <li>Review the manifest, public bytes, and privacy attestation in a PR.</li>
              <li>After merge, read the release back from the exact merge commit into a fresh directory.</li>
              <li>Run the same verification with the manifest SHA-256 recorded before copying.</li>
              <li>Pin merge-commit blob/tree links in scores and docs.</li>
            </ol>
            <p>
              Re-reading the staging directory is not remote read-back evidence.
              Download the merged remote bytes independently.
            </p>

            <h2>5. SIL and Crucible authority</h2>
            <p>
              Every external reference carries <code>kind</code>,
              <code>schema_id</code>, <code>authority</code>, and
              <code>reference</code>; file-backed references also carry
              <code>path</code> and <code>sha256</code>.
            </p>
            <table>
              <thead><tr><th>Reference</th><th>Creation condition</th><th>Authority</th></tr></thead>
              <tbody>
                <tr><td><code>sil_eval</code> / <code>inspect_ai.eval@native</code></td><td><code>export-trajectory --sil-eval</code></td><td>Inspect <code>.eval</code> scores and SIL mutation/attribution ledgers</td></tr>
                <tr><td><code>native_receipt</code> / <code>tau2.results@native</code></td><td>Every tau2 results export</td><td>tau2 <code>results.json</code></td></tr>
                <tr><td><code>crucible_evidence</code></td><td>Only with both a frozen contract ID and identity preflight</td><td><code>crucible.evidence.v3</code>, the experiment contract, and executable verifier</td></tr>
              </tbody>
            </table>
            <p>
              A GEODE release manifest owns neither a verdict nor candidate
              promotion. An outer loop joins these authorities through typed
              <code>evidence_refs</code> on <code>PostVerify</code> and decides only
              accept, revise, or escalate.
            </p>

            <h2>Authoritative schemas</h2>
            <ul>
              <li><a href="https://github.com/mangowhoiscloud/geode/blob/main/core/observability/schemas/trajectory.schema.json"><code>geode.trajectory@1</code></a></li>
              <li><a href="https://github.com/mangowhoiscloud/geode/blob/main/core/observability/schemas/trajectory-release.schema.json"><code>geode.trajectory-release@1</code></a></li>
            </ul>

            <h2>When a gate fails</h2>
            <ul>
              <li><strong>not scope-complete:</strong> fix missing correlation, ordinal gaps, or orphan tool results first.</li>
              <li><strong>not replay-complete:</strong> use an explicit waiver only after confirming a deliberate privacy reduction.</li>
              <li><strong>source digest mismatch:</strong> map the source bytes referenced by the trajectory, not a transformed public copy.</li>
              <li><strong>privacy scan failed:</strong> create a new cleaned public candidate; never overwrite an existing release.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
