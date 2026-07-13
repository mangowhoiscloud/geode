import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { BENCHMARK_GROUPS } from "@/data/geode/benchmark-measurements";
import {
  BenchmarkMatrix,
  BenchmarkRunList,
  EvalArtifactsRepoLink,
  RunLogLink,
} from "@/components/geode-docs/benchmark-run-ledger";

export const metadata = { title: "Tau2 — GEODE Docs" };

const group = BENCHMARK_GROUPS.find((g) => g.id === "tau2")!;

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/tau2"
      title="Tau2"
      titleKo="Tau2"
      summary="GEODE's tau2-bench measurements: the native user-simulator track headline, every verifier-backed run record, and links to the raw simulation logs."
      summaryKo="GEODE의 tau2-bench 실측입니다. native user-simulator 트랙 headline, verifier-backed run 기록 전체, 원본 simulation 로그 링크를 담습니다."
    >
      <Bi
        ko={
          <>
            <p>
              tau2-bench는 대화형 tool-use 벤치마크입니다. 에이전트가 시뮬레이션된
              사용자와 대화하며 airline, retail, telecom 도메인의 DB 액션을
              수행하고, verifier가 필수 액션 충족 여부로 reward를 매깁니다. GEODE는
              <code>plugins/benchmark_harness</code>의 공개 어댑터로 참가하며,
              점수는 그 점수를 만든 harness revision, model route, effort에
              고정해서만 게시합니다. 같은 조건의 재실행과만 비교할 수 있습니다.
            </p>

            <h2>Headline: native user-simulator 트랙</h2>
            <p>
              2026-07-03/04 run, GEODE v0.99.269, <code>sierra-research/tau2-bench@1901a30</code>{" "}
              (<code>tau2==1.0.0</code>), agent <code>gpt-5.2</code> PAYG effort{" "}
              <code>high</code>, native <code>user_simulator</code>{" "}
              <code>gpt-4.1-2025-04-14</code> effort <code>medium</code>,{" "}
              <code>max_steps=200</code>.
            </p>
            <BenchmarkMatrix group={group} />
            <p>
              현재 약점은 도구 가용성이 아니라 복합 태스크에서의 필수 액션
              커버리지입니다. Retail 실패는 DB write 부수효과 누락, Telecom 실패는
              MMS, APN, 앱 권한, 로밍 조합에서 필요한 액션 하나가 빠지는 패턴에
              몰립니다.
            </p>

            <h2>Run 기록</h2>
            <p>
              모든 run은 측정 시각, model, provider, source, effort, route, harness
              revision, artifact 경로를 같은 규격으로 기록합니다.
            </p>
            <BenchmarkRunList group={group} />

            <h2>Run 로그</h2>
            <p>
              원본 simulation JSON(태스크별 reward, 액션 체크, 전체 대화 transcript)은{" "}
              <EvalArtifactsRepoLink /> 레포에 무수정 보존됩니다.
            </p>
            <ul>
              <li>
                <RunLogLink path="tau2/simulations" />: GEODE 소유 run의 simulation
                JSON. headline run은 <code>geode-gpt-5-2-high-native-user-*-base-20260703/results.json</code>{" "}
                패턴입니다.
              </li>
            </ul>
            <p>
              run 기록의 artifact 경로는 측정 당시 로컬 harness 경로입니다. 게시된
              사본은 위 레포 경로에서 파일명으로 찾습니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              tau2-bench is a conversational tool-use benchmark: the agent talks to
              a simulated user while performing DB actions across the airline,
              retail, and telecom domains, and a verifier scores each task by
              required-action coverage. GEODE participates through the public
              adapter in <code>plugins/benchmark_harness</code>, and every
              published number is pinned to the harness revision, model route, and
              effort that produced it. Compare only against reruns with the same
              settings.
            </p>

            <h2>Headline: Native User-Simulator Track</h2>
            <p>
              2026-07-03/04 run, GEODE v0.99.269,{" "}
              <code>sierra-research/tau2-bench@1901a30</code> (<code>tau2==1.0.0</code>),
              agent <code>gpt-5.2</code> PAYG at effort <code>high</code>, native{" "}
              <code>user_simulator</code> <code>gpt-4.1-2025-04-14</code> at effort{" "}
              <code>medium</code>, <code>max_steps=200</code>.
            </p>
            <BenchmarkMatrix group={group} />
            <p>
              The current weak spot is not gross tool availability but required
              action coverage under compound tasks: Retail failures often miss
              DB/write side effects, while Telecom failures cluster around
              MMS/APN/app-permission/roaming combinations where one necessary
              action is omitted.
            </p>

            <h2>Run Records</h2>
            <p>
              Every run records the measured time, model, provider, source,
              effort, route, harness revision, and artifact path with one schema.
            </p>
            <BenchmarkRunList group={group} />

            <h2>Run Logs</h2>
            <p>
              The raw simulation JSONs (per-task rewards, action checks, and full
              conversation transcripts) are preserved unmodified in the{" "}
              <EvalArtifactsRepoLink /> repository.
            </p>
            <ul>
              <li>
                <RunLogLink path="tau2/simulations" />: simulation JSONs for
                GEODE-owned runs. The headline runs follow the{" "}
                <code>geode-gpt-5-2-high-native-user-*-base-20260703/results.json</code>{" "}
                pattern.
              </li>
            </ul>
            <p>
              Artifact paths inside the run records are the local harness paths at
              measurement time; the published copies live under the repository
              path above, addressed by file name.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
