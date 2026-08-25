import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Seed pipeline — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/seed-pipeline"
      title="Seed pipeline"
      titleKo="Seed 파이프라인"
      summary="The plugin that regenerates the seed corpus each generation. Picker, orchestrator, manifest, cost preview, and frontier-band survivor selection."
      summaryKo="세대마다 seed 코퍼스를 다시 만드는 플러그인입니다. picker, orchestrator, manifest, cost preview와 frontier-band 생존자 선택을 다룹니다."
    >
      <Bi
        ko={
          <>
            <h2>구성</h2>
            <p>
              <code>evals/seed_generation/</code>이 자기개선 루프의 세대마다
              새 Petri seed 묶음을 만듭니다. 입력은 직전 세대의 baseline과
              audit 결과, 출력은 다음 세대의 seed 파일과 git-tracked 번들
              스냅샷입니다. CLI 진입점은 <code>geode-eval audit-seeds</code>입니다.
            </p>
            <table>
              <thead>
                <tr><th>모듈</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr><td><code>picker.py</code></td><td>다음 런이 겨눌 target dimension 선택</td></tr>
                <tr><td><code>orchestrator.py</code></td><td>9-역할 phase 그래프 실행 (<a href="/geode/docs/capabilities/co-scientist">Seed Scenario Generation</a>)</td></tr>
                <tr><td><code>manifest.py</code></td><td>seed 파일 × dimension × 예산 manifest</td></tr>
                <tr><td><code>cost_preview.py</code></td><td>실행 전 비용 추정. confirm 프롬프트의 근거</td></tr>
                <tr><td><code>pre_flight.py</code></td><td>자격, 쿼터, 의존성 사전 점검</td></tr>
                <tr><td><code>tournament.py</code></td><td>Elo 토너먼트 + 생존자 선택</td></tr>
                <tr><td><code>checkpointer.py</code> / <code>resume.py</code></td><td>phase별 체크포인트와 재개</td></tr>
                <tr><td><code>bundle_sync.py</code></td><td>완료 런을 <code>docs/self-improving/petri-bundle/seeds/&lt;run_id&gt;/</code>로 동기화</td></tr>
              </tbody>
            </table>
            <p>
              <code>geode-eval audit-seeds generate</code>는 picker → cost preview →
              pre-flight → confirm → pipeline 순서로 진행하고,{" "}
              <code>geode-eval audit-seeds resume</code>이 체크포인트에서 이어
              갑니다.
            </p>
            <figure>
              <img
                src="/geode/diagrams/seed-pipeline-run.svg"
                alt="Seed pipeline 런 흐름. geode-eval audit-seeds가 picker, cost preview와 confirm, pre-flight를 지나 9-역할 파이프라인으로 들어가고, frontier-band 생존자 선택을 거쳐 cycle-input 풀과 번들로 나뉘며, meta-review priors가 다음 런의 picker로 되돌아간다"
              />
              <figcaption>
                한 런의 진행. 좌측 사다리(picker, cost preview, pre-flight)를
                지나 9-역할 파이프라인이 돌고, 생존자는 frontier-band 선택을 거쳐
                cycle-input 풀과 공개 번들로 갈라집니다. held-out 벤치는 점선
                아래에서 변이되지 않고, meta-review의 prior만 다음 런의
                picker로 돌아갑니다.
              </figcaption>
            </figure>

            <h2>생존자 선택: frontier-band가 기본</h2>
            <p>
              기본 선택은 pilot 실측 난이도가 약 50% 판별 대역에 가까운 후보를
              고르는 <code>frontier</code>입니다. 너무 쉬운 seed와
              항상 실패하는 불공정 seed를 함께 피하고, pilot 근거가 없으면 Elo로
              결정적으로 폴백합니다
              (<code>evals/seed_generation/tournament.py</code>의{" "}
              <code>DEFAULT_SURVIVOR_SELECTION</code>).
            </p>
            <pre>{`norm = (pilot dim_means[target_dim] - 1) / 9
frontier_reward = 1 - 2 * abs(norm - 0.5)`}</pre>
            <ul>
              <li>reward는 중간 판별 대역에서 1, Petri 척도의 양 끝에서 0입니다.</li>
              <li>pilot 신호가 없으면 기존 Elo 순위로 폴백합니다.</li>
              <li>
                조정값: <code>GEODE_SEED_SURVIVOR_SELECTION</code>
                (<code>frontier</code> / <code>blend</code> / <code>elo</code> /{" "}
                <code>difficulty</code>). 이전 scalarized 정책은 <code>blend</code>로
                복원하며, 그 가중치는{" "}
                <code>GEODE_SEED_BLEND_ELO_WEIGHT</code> /{" "}
                <code>GEODE_SEED_BLEND_DIFFICULTY_WEIGHT</code> (기본 각 1.0).
              </li>
            </ul>

            <h2>seed pool로의 연결</h2>
            <p>
              생존자는 런 번들에 남는 것으로 끝나지 않습니다. Closed-Loop가 실제로
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
              <li><a href="/geode/docs/capabilities/autoresearch">Closed-Loop</a>. 이 seed들이 측정에 쓰이는 곳.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Shape</h2>
            <p>
              <code>evals/seed_generation/</code> builds a fresh batch of
              Petri seeds for each generation of the self-improving loop. Input
              is the prior generation&apos;s baseline and audit results; output
              is the next generation&apos;s seed files plus a git-tracked
              bundle snapshot. The CLI entry is{" "}
              <code>geode-eval audit-seeds</code>.
            </p>
            <table>
              <thead>
                <tr><th>Module</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr><td><code>picker.py</code></td><td>Selects the target dimension the next run aims at</td></tr>
                <tr><td><code>orchestrator.py</code></td><td>Runs the nine-role phase graph (<a href="/geode/docs/capabilities/co-scientist">Seed Scenario Generation</a>)</td></tr>
                <tr><td><code>manifest.py</code></td><td>Seed file by dimension by budget manifest</td></tr>
                <tr><td><code>cost_preview.py</code></td><td>Pre-run cost estimate behind the confirm prompt</td></tr>
                <tr><td><code>pre_flight.py</code></td><td>Credential, quota, and dependency checks</td></tr>
                <tr><td><code>tournament.py</code></td><td>Elo tournament plus survivor selection</td></tr>
                <tr><td><code>checkpointer.py</code> / <code>resume.py</code></td><td>Per-phase checkpoints and resume</td></tr>
                <tr><td><code>bundle_sync.py</code></td><td>Mirrors finished runs into <code>docs/self-improving/petri-bundle/seeds/&lt;run_id&gt;/</code></td></tr>
              </tbody>
            </table>
            <p>
              <code>geode-eval audit-seeds generate</code> proceeds picker, cost
              preview, pre-flight, confirm, then the pipeline;{" "}
              <code>geode-eval audit-seeds resume</code> continues from checkpoints.
            </p>
            <figure>
              <img
                src="/geode/diagrams/seed-pipeline-run.svg"
                alt="Seed pipeline run flow: geode-eval audit-seeds passes picker, cost preview and confirm, pre-flight, enters the nine-role pipeline, then frontier-band survivor selection splits into the cycle-input pool and the published bundle, with meta-review priors looping back to the picker"
              />
              <figcaption>
                One run, end to end. The left ladder (picker, cost preview,
                pre-flight) leads into the nine-role pipeline; survivors pass
                frontier-band selection and split into the cycle-input pool and
                the published bundle. The held-out bench stays below the
                dashed line, never mutated; only meta-review priors loop back
                to the next run&apos;s picker.
              </figcaption>
            </figure>

            <h2>Survivor selection: frontier band by default</h2>
            <p>
              The default <code>frontier</code> mode keeps candidates near the
              pilot&apos;s 50% discrimination band, avoiding both easy seeds and
              unfair always-failing seeds. It falls back deterministically to
              Elo when pilot evidence is unavailable ({" "}
              <code>DEFAULT_SURVIVOR_SELECTION</code> in{" "}
              <code>evals/seed_generation/tournament.py</code>).
            </p>
            <pre>{`norm = (pilot dim_means[target_dim] - 1) / 9
frontier_reward = 1 - 2 * abs(norm - 0.5)`}</pre>
            <ul>
              <li>The reward is 1 at the midpoint and 0 at either Petri-scale extreme.</li>
              <li>Missing pilot evidence falls back to the existing Elo order.</li>
              <li>
                Knobs: <code>GEODE_SEED_SURVIVOR_SELECTION</code>
                (<code>frontier</code> / <code>blend</code> / <code>elo</code> /{" "}
                <code>difficulty</code>). Set <code>blend</code> to restore the
                prior scalarised policy; its weights remain{" "}
                <code>GEODE_SEED_BLEND_ELO_WEIGHT</code> /{" "}
                <code>GEODE_SEED_BLEND_DIFFICULTY_WEIGHT</code> (each 1.0 by
                default).
              </li>
            </ul>

            <h2>Into the seed pools</h2>
            <p>
              Survivors do not stop at the run bundle. The Closed-Loop reads
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
              <li><a href="/geode/docs/capabilities/autoresearch">Closed-Loop</a>. Where these seeds get used for measurement.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
