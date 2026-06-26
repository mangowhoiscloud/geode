import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Seed pipeline — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/seed-pipeline"
      title="Seed pipeline"
      titleKo="Seed 파이프라인"
      summary="The plugin that regenerates the seed corpus each generation. Picker, orchestrator, manifest, cost preview, and the blend survivor selection."
      summaryKo="세대마다 seed 코퍼스를 다시 만드는 플러그인입니다. picker, orchestrator, manifest, cost preview와 blend 생존자 선택을 다룹니다."
    >
      <Bi
        ko={
          <>
            <h2>구성</h2>
            <p>
              <code>plugins/seed_generation/</code>이 자기개선 루프의 세대마다
              새 Petri seed 묶음을 만듭니다. 입력은 직전 세대의 baseline과
              audit 결과, 출력은 다음 세대의 seed 파일과 git-tracked 번들
              스냅샷입니다. CLI 진입점은 <code>geode audit-seeds</code>(슬래시{" "}
              <code>/audit-seeds</code>)입니다.
            </p>
            <table>
              <thead>
                <tr><th>모듈</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr><td><code>picker.py</code></td><td>다음 런이 겨눌 target dimension 선택</td></tr>
                <tr><td><code>orchestrator.py</code></td><td>9-역할 phase 그래프 실행 (<a href="/geode/docs/capabilities/co-scientist">Co-scientist seed 생성</a>)</td></tr>
                <tr><td><code>manifest.py</code></td><td>seed 파일 × dimension × 예산 manifest</td></tr>
                <tr><td><code>cost_preview.py</code></td><td>실행 전 비용 추정. confirm 프롬프트의 근거</td></tr>
                <tr><td><code>pre_flight.py</code></td><td>자격, 쿼터, 의존성 사전 점검</td></tr>
                <tr><td><code>tournament.py</code></td><td>Elo 토너먼트 + 생존자 선택</td></tr>
                <tr><td><code>checkpointer.py</code> / <code>resume.py</code></td><td>phase별 체크포인트와 재개</td></tr>
                <tr><td><code>bundle_sync.py</code></td><td>완료 런을 <code>docs/self-improving/petri-bundle/seeds/&lt;run_id&gt;/</code>로 동기화</td></tr>
              </tbody>
            </table>
            <p>
              <code>geode audit-seeds generate</code>는 picker → cost preview →
              pre-flight → confirm → pipeline 순서로 진행하고,{" "}
              <code>geode audit-seeds resume</code>이 체크포인트에서 이어
              갑니다.
            </p>

            <h2>생존자 선택: blend가 기본</h2>
            <p>
              왜 Elo 단독이 아닌가. Elo는 judge 패널의 선호를 재지만, 루프가
              원하는 seed는 &quot;target이 어려워하는&quot; seed입니다. pilot 실측이 주는
              난이도 신호를 버리면 선택이 스타일 선호로 기웁니다. 그래서 기본
              선택 모드는 <code>blend</code>입니다
              (<code>plugins/seed_generation/tournament.py</code>의{" "}
              <code>DEFAULT_SURVIVOR_SELECTION</code>).
            </p>
            <pre>{`final = elo_weight * z(elo)
      + diff_weight * confidence * z(difficulty)

difficulty = pilot dim_means[target_dim]   # 높을수록 target에게 어려움
confidence = pilot stderr 기반 가중치      # 노이즈가 크면 자동 감쇠`}</pre>
            <ul>
              <li>z-score는 rating이 있는 후보들 사이에서 계산합니다.</li>
              <li>
                후보 단위 점진적 약화: pilot이 깨졌거나 stderr가 없으면 그
                후보는 순수 Elo로 평가됩니다. 깨진 pilot이 선택을 Elo보다
                나쁘게 만들 수는 없습니다.
              </li>
              <li>
                조정값: <code>GEODE_SEED_SURVIVOR_SELECTION</code>
                (<code>elo</code> / <code>difficulty</code> / <code>blend</code>),{" "}
                <code>GEODE_SEED_BLEND_ELO_WEIGHT</code> /{" "}
                <code>GEODE_SEED_BLEND_DIFFICULTY_WEIGHT</code> (기본 각 1.0).
              </li>
            </ul>

            <h2>seed pool로의 연결</h2>
            <p>
              생존자는 런 번들에 남는 것으로 끝나지 않습니다. 폐루프가 실제로
              읽는 곳은 두 풀입니다.
            </p>
            <ul>
              <li>
                <code>state/seed-pools/cycle-input</code>. 사이클 입력 풀.{" "}
                <code>geode seeds assemble</code>이 최신 seed-generation 런들의
                검증된 생존자에서 결정적으로 조립합니다 (기본 <code>--out</code>이
                이 풀입니다).
              </li>
              <li>
                <code>state/seed-pools/held-out</code>. 버전 고정 held-out
                벤치마크. arm 간 비교의 기준자로 쓰며 사이클 입력과 섞지
                않습니다.
              </li>
            </ul>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/petri/seeds">Seed 생성 런</a>. 공개된 런별 대시보드.</li>
              <li><a href="/geode/docs/capabilities/autoresearch">폐루프</a>. 이 seed들이 측정에 쓰이는 곳.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Shape</h2>
            <p>
              <code>plugins/seed_generation/</code> builds a fresh batch of
              Petri seeds for each generation of the self-improving loop. Input
              is the prior generation&apos;s baseline and audit results; output
              is the next generation&apos;s seed files plus a git-tracked
              bundle snapshot. The CLI entry is{" "}
              <code>geode audit-seeds</code> (slash form{" "}
              <code>/audit-seeds</code>).
            </p>
            <table>
              <thead>
                <tr><th>Module</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr><td><code>picker.py</code></td><td>Selects the target dimension the next run aims at</td></tr>
                <tr><td><code>orchestrator.py</code></td><td>Runs the nine-role phase graph (<a href="/geode/docs/capabilities/co-scientist">Co-scientist seed generation</a>)</td></tr>
                <tr><td><code>manifest.py</code></td><td>Seed file by dimension by budget manifest</td></tr>
                <tr><td><code>cost_preview.py</code></td><td>Pre-run cost estimate behind the confirm prompt</td></tr>
                <tr><td><code>pre_flight.py</code></td><td>Credential, quota, and dependency checks</td></tr>
                <tr><td><code>tournament.py</code></td><td>Elo tournament plus survivor selection</td></tr>
                <tr><td><code>checkpointer.py</code> / <code>resume.py</code></td><td>Per-phase checkpoints and resume</td></tr>
                <tr><td><code>bundle_sync.py</code></td><td>Mirrors finished runs into <code>docs/self-improving/petri-bundle/seeds/&lt;run_id&gt;/</code></td></tr>
              </tbody>
            </table>
            <p>
              <code>geode audit-seeds generate</code> proceeds picker, cost
              preview, pre-flight, confirm, then the pipeline;{" "}
              <code>geode audit-seeds resume</code> continues from checkpoints.
            </p>

            <h2>Survivor selection: blend by default</h2>
            <p>
              Why not pure Elo? Elo measures judge-panel preference, but the
              loop wants seeds the target finds hard. Throwing away the
              difficulty signal from the pilot&apos;s real measurement tilts
              selection toward style preference. So the default mode is{" "}
              <code>blend</code> (<code>DEFAULT_SURVIVOR_SELECTION</code> in{" "}
              <code>plugins/seed_generation/tournament.py</code>).
            </p>
            <pre>{`final = elo_weight * z(elo)
      + diff_weight * confidence * z(difficulty)

difficulty = pilot dim_means[target_dim]   # higher = harder for the target
confidence = weight from pilot stderr      # noisy pilots are damped`}</pre>
            <ul>
              <li>z-scores are computed across the rated candidates.</li>
              <li>
                Per-candidate graceful degrade: a candidate with a broken pilot
                or no stderr is scored on pure Elo. A broken pilot can never
                make selection worse than Elo.
              </li>
              <li>
                Knobs: <code>GEODE_SEED_SURVIVOR_SELECTION</code>
                (<code>elo</code> / <code>difficulty</code> /{" "}
                <code>blend</code>), and{" "}
                <code>GEODE_SEED_BLEND_ELO_WEIGHT</code> /{" "}
                <code>GEODE_SEED_BLEND_DIFFICULTY_WEIGHT</code> (each 1.0 by
                default).
              </li>
            </ul>

            <h2>Into the seed pools</h2>
            <p>
              Survivors do not stop at the run bundle. The closed loop reads
              from two pools.
            </p>
            <ul>
              <li>
                <code>state/seed-pools/cycle-input</code>. The cycle-input
                pool. <code>geode seeds assemble</code> assembles it
                deterministically from validated survivors of the latest
                seed-generation runs (the default <code>--out</code> is this
                pool).
              </li>
              <li>
                <code>state/seed-pools/held-out</code>. The version-frozen
                held-out bench, used as the ruler for cross-arm comparison and
                never mixed into cycle input.
              </li>
            </ul>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/petri/seeds">Seed-generation runs</a>. The published per-run dashboard.</li>
              <li><a href="/geode/docs/capabilities/autoresearch">The closed loop</a>. Where these seeds get used for measurement.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
