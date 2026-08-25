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

function Tau2Report({ ko }: { ko: boolean }) {
  const profiles = ko
    ? [
        ["Suite-native", "0.820", "228 / 278 · pass¹ · tau2==1.0.0", "historical k=1"],
        ["GEODE-user", "200 / 278", "0.7194 · dual-runtime", "별도 진단 profile"],
        ["Runtime-faithful", "99 missing", "quota-contaminated work", "aggregate 권한 없음"],
      ]
    : [
        ["Suite-native", "0.820", "228 / 278 · pass¹ · tau2==1.0.0", "Historical k=1"],
        ["GEODE-user", "200 / 278", "0.7194 · dual-runtime", "Separate diagnostic profile"],
        ["Runtime-faithful", "99 missing", "quota-contaminated work", "No aggregate authority"],
      ];
  const lineage = ko
    ? [
        ["2026-07-03", "Native score", "results.json이 task reward와 headline을 소유"],
        ["2026-07-31", "Trajectory @1", "turn/call/result exact join과 orphan 수를 공개"],
        ["2026-08-03", "Full cycle", "278개 task의 dual-runtime profile을 분리 측정"],
        ["2026-08-04", "Attempt lineage", "retry·quota·selection을 남기고 오염 행을 미실행 작업으로 분류"],
        ["2026-08-14", "Frozen preflight", "모델 호출 전에 task·route·budget 정합성을 검사"],
      ]
    : [
        ["2026-07-03", "Native score", "results.json owns task rewards and the headline"],
        ["2026-07-31", "Trajectory @1", "Published exact turn/call/result joins and orphan counts"],
        ["2026-08-03", "Full cycle", "Measured all 278 tasks under a distinct dual-runtime profile"],
        ["2026-08-04", "Attempt lineage", "Recorded retry, quota, and selection; classified contaminated rows as missing work"],
        ["2026-08-14", "Frozen preflight", "Checked task, route, and budget identity before model calls"],
      ];
  const authority = ["Task + user route", "Native reward", "Trajectory behavior", "Attempt validity", "Published claim"];

  return (
    <section aria-labelledby="tau2-report" className="mb-14">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--rule)] pb-3">
        <div>
          <p className="!m-0 font-mono text-[10px] uppercase tracking-[0.2em] text-[var(--ink-3)]">
            {ko ? "대화형 정책 실행" : "Conversational policy execution"}
          </p>
          <h2 id="tau2-report" className="!mb-0 !mt-1">
            {ko ? "세 실행 profile을 분리해 읽습니다" : "Read three execution profiles separately"}
          </h2>
        </div>
        <a href="https://taubench.com/" className="text-xs">τ-bench leaderboard ↗</a>
      </div>

      <div className="grid gap-x-8 gap-y-6 py-6 md:grid-cols-3">
        {profiles.map(([label, value, scope, authorityLabel], index) => (
          <div key={label} className={`border-t border-[var(--rule-soft)] pt-4 ${index > 0 ? "md:border-l md:pl-6" : ""}`}>
            <p className="!m-0 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ink-3)]">{label}</p>
            <p className="!my-2 font-serif-docs text-3xl font-black text-[var(--ink)]">{value}</p>
            <p className="!m-0 text-sm text-[var(--ink-2)]">{scope}</p>
            <p className="!mt-2 font-mono text-[10px] uppercase tracking-wider text-[var(--section-accent)]">{authorityLabel}</p>
          </div>
        ))}
      </div>

      <div className="border-y border-[var(--rule-soft)] py-5">
        <p className="!mb-3 !mt-0 font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          {ko ? "증거 권한의 흐름" : "Evidence authority path"}
        </p>
        <div role="list" className="grid gap-2 sm:grid-cols-5">
          {authority.map((label, index) => (
            <div role="listitem" key={label} className="relative bg-[var(--paper-2)] px-3 py-3 text-sm">
              <span className="mr-2 font-mono text-[10px] text-[var(--ink-3)]">{index + 1}</span>
              {label}
            </div>
          ))}
        </div>
        <p className="!mb-0 !mt-3 text-sm text-[var(--ink-2)]">
          {ko
            ? "reward는 성공을, trajectory는 행동을, attempt manifest는 실행의 유효성을 설명합니다. 세 기록의 권한은 서로 독립적입니다."
            : "Reward explains success, trajectory explains behavior, and the attempt manifest explains run validity. Each record keeps its own authority."}
        </p>
      </div>

      <div className="mt-8">
        <h3>{ko ? "측정 기록의 발전" : "Measurement record evolution"}</h3>
        <div role="list">
          {lineage.map(([date, stage, detail]) => (
            <div role="listitem" key={date} className="grid gap-1 border-b border-[var(--rule-soft)] py-4 md:grid-cols-[7rem_10rem_1fr] md:gap-4">
              <time className="font-mono text-xs text-[var(--ink-3)]">{date}</time>
              <strong className="text-sm">{stage}</strong>
              <span className="text-sm text-[var(--ink-2)]">{detail}</span>
            </div>
          ))}
        </div>
        <p className="!mb-0 !mt-4 text-sm text-[var(--ink-2)]">
          {ko
            ? "공식 τ-bench 표면은 도메인, Standard·Custom·Legacy, pass^k와 실행 visualizer를 분리합니다. GEODE도 profile identity를 고정한 행만 비교하고, 나머지는 진단 계보에 둡니다."
            : "The official τ-bench surface separates domains, Standard·Custom·Legacy, pass^k, and a run visualizer. GEODE likewise compares only rows with matching profile identity and keeps the rest in diagnostic lineage."}
        </p>
      </div>
    </section>
  );
}

export default function Page() {
  return (
    <DocsShell
      wide
      slug="benchmarks/tau2"
      title="Tau2"
      titleKo="Tau2"
      summary="GEODE's tau2-bench measurements: the native user-simulator track headline, every verifier-backed run record, and links to the raw simulation logs."
      summaryKo="GEODE의 tau2-bench 실측입니다. native user-simulator 트랙 headline, verifier-backed run 기록 전체, 원본 simulation 로그 링크를 담습니다."
    >
      <Bi
        ko={
          <>
            <Tau2Report ko />
            <p>
              tau2-bench는 대화형 tool-use 벤치마크입니다. 에이전트가 시뮬레이션된
              사용자와 대화하며 airline, retail, telecom 도메인의 DB 액션을
              수행하고, verifier가 필수 액션 충족 여부로 reward를 매깁니다. GEODE는
              <code>evals/benchmarks</code>의 공개 어댑터로 참가하며,
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
              또한 normalized trajectory의 digest 결합을 독립적으로 확인하고
              <code>scope_complete=true</code>를 다시 계산하므로 orphan tool call이
              있는 실행은 승격할 수 없습니다.
              <code>tau2-native-user</code>와 <code>geode-dual-runtime</code> profile은 합산하지
              않습니다. 진단 auto-resume의 이전 process 행은
              <code>resumed_native_unattested</code>로 표시합니다.
            </p>
            <p>
              2026-08-04 full-cycle 시도는 278개 task를 모두 스케줄했지만,
              subscription quota 소진으로 Airline 2개, Retail 16개, Telecom
              81개 등 99개 행이 infrastructure contamination 상태가 됐습니다.
              이 행들은 미실행 작업입니다. 따라서 이 시도에는 aggregate score
              권한이 없습니다. quota 소진 전 Telecom call 6개에서는
              external-yield 순서 결함도 발견했습니다. 현재 runtime은 post-tool
              convergence guard보다 먼저 proposal을 반환하고, admission은 당시의
              scope-incomplete trajectory를 거부합니다. 새 headline은 깨끗한
              재실행 이후에만 게시합니다.
            </p>
            <p>
              개인정보 검토를 통과한 진단 보고서와 세 도메인 companion은{" "}
              <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/40be847f7c12004b1e70673808fa95bfd8646b59/reports/e2e-validation/2026-08-04-gpt54-runtime-faithful-tau2-diagnostic.md">
                <code>geode-eval-artifacts@40be847</code>
              </a>
              에 고정했습니다. 12개 파일 manifest SHA-256은{" "}
              <code>40206ed1…317</code>이며, 이 묶음의 권한은 invalidation
              evidence에 한정됩니다.
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
              별도 진단 profile이며, trajectory는 correlation/replay sidecar입니다.
              원본 snapshot의 runner-default{" "}
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
              현재 약점은 복합 태스크의 필수 액션 커버리지입니다. Retail 실패는
              DB write 부수효과 누락, Telecom 실패는
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
            <Tau2Report ko={false} />
            <p>
              tau2-bench is a conversational tool-use benchmark: the agent talks to
              a simulated user while performing DB actions across the airline,
              retail, and telecom domains, and a verifier scores each task by
              required-action coverage. GEODE participates through the public
              adapter in <code>evals/benchmarks</code>, and every
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
              participant session, and final selection. It independently verifies
              the normalized trajectory&apos;s digest bindings and recomputes{" "}
              <code>scope_complete=true</code>, so an orphaned tool call cannot be
              promoted. <code>tau2-native-user</code> and{" "}
              <code>geode-dual-runtime</code> profiles are never pooled. A diagnostic
              auto-resume labels prior-process rows as <code>resumed_native_unattested</code>.
            </p>
            <p>
              The 2026-08-04 full-cycle attempt reached all 278 scheduled tasks,
              but subscription quota exhaustion contaminated 99 rows: 2 Airline,
              16 Retail, and 81 Telecom. They are missing work, so this attempt
              has no aggregate score authority. Six pre-quota
              Telecom calls also exposed an external-yield ordering defect; the
              runtime now returns those proposals before post-tool convergence
              guards, and admission rejects the captured scope-incomplete
              trajectory. A clean rerun is required before a new headline is
              published.
            </p>
            <p>
              The privacy-reviewed diagnostic report and three-domain companions
              are pinned to{" "}
              <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/40be847f7c12004b1e70673808fa95bfd8646b59/reports/e2e-validation/2026-08-04-gpt54-runtime-faithful-tau2-diagnostic.md">
                <code>geode-eval-artifacts@40be847</code>
              </a>
              . The 12-file manifest SHA-256 is <code>40206ed1…317</code>; this
              bundle carries invalidation-evidence authority only.
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
              This row belongs to a separate dual-runtime profile. Tau2{" "}
              <code>results.json</code> remains score authority; the
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
              These post-release route smokes leave the 278-task full cycle
              unchanged. There was no route, authentication, or
              provider-adapter failure. The retained failures are direct
              <code>PostVerify</code> evidence that task success still requires
              the native verifier.
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
              fixed tasks belong to a diagnostic profile; the trajectories are
              correlation/replay sidecars. The immutable
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
              The current weak spot is required-action coverage under compound
              tasks: Retail failures often miss
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
