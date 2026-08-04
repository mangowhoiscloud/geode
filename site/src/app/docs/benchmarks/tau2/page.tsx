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

            <h2>2026-08-04 runtime-faithful 실행 계약</h2>
            <p>
              현재 어댑터는 process-owned <code>RuntimeEventBus</code>, 13개 공개
              hook registry, 4개 trusted middleware join point를 Tau2의 모든
              <code>ToolExecutor</code>와 <code>AgenticLoop</code>에 공유합니다. Tau2가
              실제 환경 tool을 실행하며, GEODE의 projection ACK는
              <code>deferred</code>로 남습니다. 이후 native <code>ToolMessage.id</code>가
              원래 call ID의 유일한 completion/error를 닫습니다. 환경 단계에서 즉시
              종료된 경우에는 native receipt의 마지막 ToolMessage를 결합합니다.
            </p>
            <p>
              native <code>results.json</code>은 계속 점수 정본입니다. 그 digest와
              reward, task/trial, native/runtime termination은
              <code>verification.evidence</code>로 SessionEnd 전에 기록됩니다. 새
              <code>snapshot v4</code>는 runtime revision, assembled prompt/tool schema
              digest, 실제로 exercise된 surface를 담은 runtime profile과 모든
              retry/session/final selection을 담은 attempt manifest를 함께 검증합니다.
              <code>tau2-native-user</code>와 <code>geode-dual-runtime</code> profile은 합산하지
              않습니다. 진단 auto-resume의 이전 process 행은
              <code>resumed_native_unattested</code>로 표시합니다.
            </p>

            <h2>2026-08-03 GPT-5.4 subscription base full cycle</h2>
            <p>
              GEODE <code>22789ee2</code>에서 Airline, Retail, Telecom base
              278개 task를 모두 실행했습니다. agent와 <code>geode_user</code>는
              모두 <code>gpt-5.4</code> subscription / effort{" "}
              <code>high</code>이며, 결과는 <strong>200/278 = 0.7194</strong>
              입니다.
            </p>
            <ul>
              <li>
                Airline <strong>42/50</strong>, Retail <strong>79/114</strong>,
                Telecom <strong>79/114</strong>.
              </li>
              <li>
                Telecom은 service 28/29, mobile-data 30/36, MMS 21/49입니다.
                14개 task가 <code>MAX_STEPS</code>에 도달했고 p95는 957.65초입니다.
              </li>
              <li>
                556개 final parent session을 SQLite 51,985 event와 exact join했고,
                3,964개 tool call/result pair에 orphan은 없습니다.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt54-22789ee2-geode-user-airline-retail-telecom-base-full-20260803T091257Z-13162f7bcff9"
                  revision="86dcbba3d15f1979b71a501780bf66fea4b450b5"
                />:
                privacy-reviewed 3-domain <code>geode.trajectory@1</code> release.
              </li>
            </ul>
            <p>
              이 행은 native <code>user_simulator</code> headline이 아닙니다. Tau2{" "}
              <code>results.json</code>이 점수 정본이고 trajectory는 외부 루프용
              진단 sidecar입니다. 7회 transport retry가 만든 14개 추가 SQLite
              session은 final trajectory parent 밖에 있으며, 공개 release는 이
              lineage와 bounded payload 때문에 <code>replay_complete=false</code>
              입니다. 또한 Tau2 격리 loop는 <code>HookSystem</code> 없이 구성되어
              public <code>hook_events</code>가 0입니다. hook dispatch의 정본은
              별도 13-hook / 4-middleware E2E입니다.
            </p>

            <h2>2026-08-03 v1.0.12 post-release smoke</h2>
            <p>
              공개 배포된 GEODE <code>v1.0.12</code> (<code>f99cea63</code>)에서
              같은 GPT-5.4 subscription / effort <code>high</code> route로 mock과
              Telecom-small 고정 task를 다시 실행했습니다. 결과는 각각{" "}
              <strong>0/1</strong>이며, 실패를 retry하거나 삭제하지 않았습니다.
            </p>
            <ul>
              <li>
                Mock은 13.75초 뒤 <code>USER_STOP</code>했습니다. communication은
                1.0이지만 DB와 required action은 0.0입니다.
              </li>
              <li>
                Telecom은 236.73초와 50 steps 뒤 <code>MAX_STEPS</code>에
                도달했습니다. 반복 진단을 포함한 14개 tool call/result가 모두
                pairing됐지만 native component scoring 전에 종료됐습니다.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt54-v1.0.12-f99cea63-geode-user-mock-telecom-small-20260803T104819Z-fd524ce7a3cb"
                  revision="04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd"
                />:
                234개 event, 16개 exact tool pair, manifest SHA-256{" "}
                <code>fd524ce7a3cb…2288</code>.
              </li>
            </ul>
            <p>
              이 두 건은 배포 경로 회귀 smoke이며 278-task full cycle의 재실행이나
              대체 결과가 아닙니다. route/인증/provider adapter 오류는 없었고,
              실패는 외부 루프가 <code>Stop</code>과 trajectory 완결성을 task
              success로 오인하지 않게 하는 <code>PostVerify</code> 입력 증거입니다.
            </p>

            <h2>2026-08-02 GPT-5.4 subscription cycle</h2>
            <p>
              GEODE <code>afaab52b</code>에서 agent와 <code>geode_user</code>를
              모두 <code>gpt-5.4</code> subscription / effort <code>high</code>로
              실행했습니다. <code>mock/create_task_1</code>은 <strong>0/1</strong>,
              Telecom-small 첫 task는 <strong>1/1</strong>이며, 두 run 모두 route,
              provider, adapter, quota exception 없이 정상 <code>USER_STOP</code>으로
              끝났습니다.
            </p>
            <ul>
              <li>
                Mock: <code>create_task</code>에 요청하지 않은 optional{" "}
                <code>description=&quot;&quot;</code>가 포함돼 exact action/DB 비교가
                실패했습니다.
              </li>
              <li>
                Telecom: DB, <code>toggle_roaming</code>, mobile-data 상태,
                excellent-speed assertion이 모두 통과했습니다.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt54-afaab52b-mock-telecom-small-20260801T173245Z-2dc79cb569f0"
                  revision="f588ce9fd23b9123732b45c4dbe202136691d3fe"
                />:
                두 trajectory, 158개 canonical event, 10개 exact tool pair,
                missing ID/orphan pair 0건.
              </li>
            </ul>
            <p>
              Tau2 <code>results.json</code>이 점수 정본입니다. 이 고정 2개 task는
              native <code>user_simulator</code> headline이 아니며 trajectory는
              correlation/replay sidecar입니다. 원본 snapshot의 runner-default{" "}
              <code>stage=train</code> 표기는 그대로 보존했지만{" "}
              <code>promotion_authority=none</code>이고 학습·승격 권한을 뜻하지
              않습니다.
            </p>

            <h2>2026-07-31 v1.0.11 release 진단</h2>
            <p>
              배포된 GEODE <code>v1.0.11</code> (<code>686ff372</code>)에서
              agent와 simulated user를 모두 <code>gpt-5.6-sol</code>{" "}
              subscription / effort <code>high</code>로 실행했습니다.{" "}
              <code>mock/create_task_1</code>은 <strong>0/1</strong>,
              Telecom-small 첫 task는 <strong>1/1</strong>입니다. 둘 다 정상{" "}
              <code>USER_STOP</code>이며 provider, quota, adapter exception은
              없었습니다.
            </p>
            <ul>
              <li>
                Mock: 이전과 동일하게 <code>create_task</code>가 요청에 없던 optional{" "}
                <code>description=&quot;&quot;</code>를 추가해 exact action/DB
                comparator가 실패했습니다.
              </li>
              <li>
                Telecom: 이전의 premature human transfer가 사라졌습니다.{" "}
                <code>toggle_roaming</code>, DB match, mobile-data 상태,
                excellent-speed assertion이 모두 1.0입니다.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt56-v1.0.11-686ff372-mock-telecom-small-20260731T105713Z-a71155f7006c"
                  revision="16a54f08450db771c02e30c73bdc3867f6282f83"
                />:
                142개 이벤트와 9개 exact tool pair를 담은 두{" "}
                <code>geode.trajectory@1</code>.
              </li>
            </ul>
            <p>
              점수 정본은 여전히 tau2 <code>results.json</code>입니다. Crucible
              snapshot은 두 run을 diagnostic / <code>promotion_authority=none</code>으로
              유지하며, GEODE trajectory는 digest-joined replay sidecar입니다.
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
              <EvalArtifactsRepoLink /> 레포에 로컬 경로와 합성 개인정보를
              마스킹한 공개 copy로 보존됩니다.
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

            <h2>2026-08-04 Runtime-Faithful Execution Contract</h2>
            <p>
              The current adapter shares one process-owned{" "}
              <code>RuntimeEventBus</code>, all 13 public hook registrations, and
              all four trusted middleware join points across every Tau2{" "}
              <code>ToolExecutor</code> and <code>AgenticLoop</code>. Tau2 remains
              the only environment-tool executor. GEODE&apos;s projection ACK stays{" "}
              <code>deferred</code>, and the native <code>ToolMessage.id</code>
              later closes the original call ID with its sole completion or error,
              including a terminal-step result recovered from the native receipt.
            </p>
            <p>
              Native <code>results.json</code> remains score authority. Its digest,
              reward, task/trial, and native/runtime termination are recorded as{" "}
              <code>verification.evidence</code> before SessionEnd. New{" "}
              <code>snapshot v4</code> admission also verifies a runtime profile
              containing revision, assembled prompt/tool-schema digests and actually
              exercised surfaces, plus an attempt manifest covering every retry,
              participant session, and final selection. <code>tau2-native-user</code> and{" "}
              <code>geode-dual-runtime</code> profiles are never pooled. A diagnostic
              auto-resume labels prior-process rows as <code>resumed_native_unattested</code>.
            </p>

            <h2>2026-08-03 GPT-5.4 Subscription Base Full Cycle</h2>
            <p>
              At GEODE <code>22789ee2</code>, the complete Airline, Retail, and
              Telecom base scope ran through <code>gpt-5.4</code> subscription
              at effort <code>high</code> for both the agent and{" "}
              <code>geode_user</code>. The aggregate is{" "}
              <strong>200/278 = 0.7194</strong>.
            </p>
            <ul>
              <li>
                Airline <strong>42/50</strong>, Retail <strong>79/114</strong>,
                and Telecom <strong>79/114</strong>.
              </li>
              <li>
                Telecom splits into service 28/29, mobile data 30/36, and MMS
                21/49. Fourteen tasks reached <code>MAX_STEPS</code>, with a
                957.65-second p95.
              </li>
              <li>
                The SQLite exact join covers 556 final parent sessions and
                51,985 events; all 3,964 tool call/result pairs are complete,
                with zero orphans.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt54-22789ee2-geode-user-airline-retail-telecom-base-full-20260803T091257Z-13162f7bcff9"
                  revision="86dcbba3d15f1979b71a501780bf66fea4b450b5"
                />:
                the privacy-reviewed three-domain{" "}
                <code>geode.trajectory@1</code> release.
              </li>
            </ul>
            <p>
              This row is not the native <code>user_simulator</code> headline.
              Tau2 <code>results.json</code> remains score authority; the
              trajectory is an external-loop diagnostic sidecar. Seven
              transport retries created 14 additional SQLite sessions outside
              the final trajectory parents, so the public release explicitly
              remains <code>replay_complete=false</code>. The isolated Tau2
              loop also runs without a <code>HookSystem</code> and records zero
              public <code>hook_events</code>; the separate 13-hook /
              four-middleware E2E remains hook-dispatch authority.
            </p>

            <h2>2026-08-03 v1.0.12 Post-Release Smoke</h2>
            <p>
              We reran the fixed mock and Telecom-small tasks against the
              public GEODE <code>v1.0.12</code> release (<code>f99cea63</code>)
              through the same GPT-5.4 subscription route at effort{" "}
              <code>high</code>. Both scored <strong>0/1</strong>; neither failure
              was retried or removed.
            </p>
            <ul>
              <li>
                Mock ended with <code>USER_STOP</code> after 13.75 seconds.
                Communication scored 1.0, while the DB and required action
                scored 0.0.
              </li>
              <li>
                Telecom reached <code>MAX_STEPS</code> after 236.73 seconds and
                50 steps. All 14 repeated diagnostic tool calls have one result,
                but the run ended before native component scoring.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt54-v1.0.12-f99cea63-geode-user-mock-telecom-small-20260803T104819Z-fd524ce7a3cb"
                  revision="04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd"
                />:
                234 events, 16 exact tool pairs, manifest SHA-256{" "}
                <code>fd524ce7a3cb…2288</code>.
              </li>
            </ul>
            <p>
              These are post-release route smokes, not a rerun or replacement
              of the 278-task full cycle. There was no route, authentication, or
              provider-adapter failure. The retained failures are direct
              <code>PostVerify</code> evidence that a normal stop or complete
              trajectory is not the same as task success.
            </p>

            <h2>2026-08-02 GPT-5.4 Subscription Cycle</h2>
            <p>
              At GEODE <code>afaab52b</code>, both the agent and{" "}
              <code>geode_user</code> ran through the <code>gpt-5.4</code>{" "}
              subscription route at effort <code>high</code>.{" "}
              <code>mock/create_task_1</code> scored <strong>0/1</strong>; the first
              Telecom-small task scored <strong>1/1</strong>. Both ended normally
              with <code>USER_STOP</code> and no route, provider, adapter, or quota
              exception.
            </p>
            <ul>
              <li>
                Mock: <code>create_task</code> included the unrequested optional{" "}
                <code>description=&quot;&quot;</code>, so the exact action and DB
                comparators failed.
              </li>
              <li>
                Telecom: the DB, <code>toggle_roaming</code>, mobile-data, and
                excellent-speed checks all passed.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt54-afaab52b-mock-telecom-small-20260801T173245Z-2dc79cb569f0"
                  revision="f588ce9fd23b9123732b45c4dbe202136691d3fe"
                />:
                two trajectories, 158 canonical events, ten exact tool pairs,
                and zero missing IDs or orphaned pairs.
              </li>
            </ul>
            <p>
              Tau2 <code>results.json</code> is the score authority. These two
              fixed tasks are not a native <code>user_simulator</code> headline;
              the trajectories are correlation/replay sidecars. The immutable
              snapshots preserve the runner-default <code>stage=train</code>
              label, but <code>promotion_authority=none</code> grants no training
              or promotion authority.
            </p>

            <h2>2026-07-31 v1.0.11 Release Diagnostics</h2>
            <p>
              With the released GEODE <code>v1.0.11</code> (<code>686ff372</code>),
              both the agent and simulated user ran through{" "}
              <code>gpt-5.6-sol</code> subscription at effort <code>high</code>.{" "}
              <code>mock/create_task_1</code> scored <strong>0/1</strong>; the
              first Telecom-small task scored <strong>1/1</strong>. Both ended
              normally with <code>USER_STOP</code>, with no provider, quota, or
              adapter exception.
            </p>
            <ul>
              <li>
                Mock: as before, <code>create_task</code> added the unrequested
                optional <code>description=&quot;&quot;</code>, so the native exact
                action and DB comparators failed.
              </li>
              <li>
                Telecom: the earlier premature human transfer is gone.{" "}
                <code>toggle_roaming</code>, DB match, mobile-data status, and
                excellent-speed assertions all scored 1.0.
              </li>
              <li>
                <RunLogLink
                  path="trajectories/tau2-geode-gpt56-v1.0.11-686ff372-mock-telecom-small-20260731T105713Z-a71155f7006c"
                  revision="16a54f08450db771c02e30c73bdc3867f6282f83"
                />:
                two <code>geode.trajectory@1</code> artifacts with 142 events and
                nine exact tool pairs.
              </li>
            </ul>
            <p>
              Tau2 <code>results.json</code> remains the score authority. The
              Crucible snapshots keep both runs diagnostic with{" "}
              <code>promotion_authority=none</code>; the GEODE trajectory is a
              digest-joined replay sidecar.
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
              conversation transcripts) are preserved as public copies with local
              paths and synthetic personal fields redacted in the{" "}
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
