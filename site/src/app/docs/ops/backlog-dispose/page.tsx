import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Backlog disposal — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/backlog-dispose"
      title="Backlog disposal"
      titleKo="백로그 처분"
      summary="Retiring an idea with a paper trail instead of a silent delete: the progress board, the dated disposition audit, and the re-review trigger."
      summaryKo="조용한 삭제 대신 흔적을 남기며 아이디어를 정리합니다. 진행 보드, 날짜 박힌 처분 감사 문서, 재검토 트리거를 다룹니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 처분 기록인가</h2>
            <p>
              백로그 항목을 그냥 지우면 &quot;이거 검토했었나?&quot;라는 정보가
              사라집니다. 여섯 달 뒤 같은 아이디어가 다시 제안될 때 같은 조사를
              반복하게 됩니다. 처분(disposition)은 항목을 활성 백로그에서 빼되,
              왜 보류했는지와 언제 다시 봐야 하는지를 디스크에 남기는
              패턴입니다.
            </p>

            <h2>두 개의 표면</h2>
            <table>
              <thead><tr><th>표면</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><code>docs/progress.md</code></td><td>진행 보드. Backlog, In Progress, In Review, Done 네 열을 main에서만 갱신합니다. 항목은 이슈나 태스크 ID에 1:1로 대응합니다</td></tr>
                <tr><td><code>docs/audits/YYYY-MM-DD-backlog-dispositions.md</code></td><td>처분 감사 문서. 보류로 결론 난 항목들의 근거를 날짜 박힌 파일 하나에 묶습니다. 예: <code>docs/audits/2026-05-18-backlog-dispositions.md</code></td></tr>
              </tbody>
            </table>

            <h2>처분 문서의 형식</h2>
            <p>
              항목마다 네 절을 채웁니다. 핵심은 마지막 절입니다. 처분은 영구
              폐기가 아니라 조건부 보류이고, 조건이 명시되어야 합니다.
            </p>
            <pre>{`## #<번호> — <항목 제목>

### Finding        실측 결과 (grep, 코드 인용, 측정값)
### 분석           왜 지금 하지 않는가
### Disposition    결론 한 줄 (No action / Defer 등)
### 재검토 trigger  무엇이 바뀌면 다시 올리는가

## Summary         항목 | Disposition | Trigger 수 표`}</pre>
            <p>
              Finding 절이 처분의 무게를 만듭니다. 추측이 아니라 grep 출력과
              코드 경로가 들어가야, 나중에 다시 읽는 사람이 당시의 판단을
              재검증할 수 있습니다.
            </p>

            <h2>처분이 아닌 것</h2>
            <ul>
              <li>다른 PR이 같은 문제를 해결했다면 처분 문서가 아니라 보드의 Done으로 갑니다. 해결은 처분이 아닙니다.</li>
              <li>구현이 결정된 항목은 In Progress로 갑니다. 처분은 &quot;지금 하지 않는다&quot;에만 씁니다.</li>
              <li>재검토 trigger 없는 처분은 조용한 삭제와 같습니다. trigger를 못 쓰겠다면 처분이 아니라 거절이고, 거절도 근거와 함께 적습니다.</li>
            </ul>

            <h2>실패 모드</h2>
            <table>
              <thead><tr><th>증상</th><th>원인</th><th>해법</th></tr></thead>
              <tbody>
                <tr><td>같은 아이디어가 반복 제안됨</td><td>처분이 보드에서만 지워지고 감사 문서가 없음</td><td>처분 문서를 만들고 보드 항목에서 링크합니다.</td></tr>
                <tr><td>처분 문서가 안 읽힘</td><td>재검토 trigger가 모호함</td><td>trigger를 관측 가능한 사건으로 적습니다. &quot;사용자가 X를 결정하면&quot;, &quot;Y가 import되기 시작하면&quot;.</td></tr>
                <tr><td>feature 브랜치에서 보드 갱신</td><td>추적 문서는 main 전용</td><td>보드 갱신은 main에서만 합니다. 단일 SoT 규칙입니다.</td></tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/ops/release-pypi-lifecycle">릴리스와 PyPI 라이프사이클</a>. Done 이후의 출하 경로.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Why a disposition record</h2>
            <p>
              Deleting a backlog item silently loses the &quot;did we already
              evaluate this?&quot; signal. Six months later the same idea
              returns and the same investigation repeats. A disposition removes
              the item from the active backlog while leaving why it was shelved,
              and when to look again, on disk.
            </p>

            <h2>The two surfaces</h2>
            <table>
              <thead><tr><th>Surface</th><th>Role</th></tr></thead>
              <tbody>
                <tr><td><code>docs/progress.md</code></td><td>The progress board: Backlog, In Progress, In Review, Done, updated from main only. Items map 1:1 to an issue or task ID</td></tr>
                <tr><td><code>docs/audits/YYYY-MM-DD-backlog-dispositions.md</code></td><td>The disposition audit: one dated file bundling the evidence for items concluded as shelved. Example: <code>docs/audits/2026-05-18-backlog-dispositions.md</code></td></tr>
              </tbody>
            </table>

            <h2>The disposition format</h2>
            <p>
              Each item fills four sections. The last one is the point: a
              disposition is a conditional shelf, not a permanent discard, and
              the condition must be written down.
            </p>
            <pre>{`## #<id> — <item title>

### Finding              measured evidence (grep output, code paths, numbers)
### Analysis             why not now
### Disposition          one-line conclusion (No action / Defer / ...)
### Re-review trigger    what change puts it back on the board

## Summary               item | disposition | trigger count table`}</pre>
            <p>
              The Finding section carries the weight. It holds grep output and
              code paths, not guesses, so a later reader can re-verify the
              judgment as it stood.
            </p>

            <h2>What a disposition is not</h2>
            <ul>
              <li>If another PR solved the same problem, the item goes to Done on the board. Resolution is not disposal.</li>
              <li>If the item is decided for implementation, it goes to In Progress. Disposal is only for &quot;not now&quot;.</li>
              <li>A disposition without a re-review trigger equals a silent delete. If no trigger can be written, it is a rejection, and rejections also get their evidence written down.</li>
            </ul>

            <h2>Failure modes</h2>
            <table>
              <thead><tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr></thead>
              <tbody>
                <tr><td>The same idea keeps coming back</td><td>The item was erased from the board with no audit file</td><td>Write the disposition file and link it from the board entry.</td></tr>
                <tr><td>Dispositions never get re-read</td><td>The re-review trigger is vague</td><td>Write triggers as observable events: &quot;when the user decides X&quot;, &quot;when Y starts being imported&quot;.</td></tr>
                <tr><td>Board edited from a feature branch</td><td>Tracking documents are main-only</td><td>Update the board from main only; single source of truth.</td></tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/ops/release-pypi-lifecycle">Release and PyPI lifecycle</a>. The shipping path after Done.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
