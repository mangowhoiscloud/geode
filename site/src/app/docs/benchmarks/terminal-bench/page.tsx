import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { RunLogLink } from "@/components/geode-docs/benchmark-run-ledger";
import evidence from "@/data/geode/landing-evidence.json";
import "./terminal-bench.css";

export const metadata = { title: "Terminal-Bench 2.1 · GEODE Docs" };

const paired = evidence.paired;
const astra = evidence.astra;
const signed = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
const rate = (passes: number) => (passes / paired.commonTrials) * 100;

const REPLAY_REVISION = "52b7d0eab37ec9122492ec51d77e1502d5b9e085";
const OBSERVABILITY_REVISION = "d277607f3a179f191ad24b1497c0934beb9d2470";
const PAIRED_RUN = "terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z";

function PairedReplay({ ko }: { ko: boolean }) {
  return (
    <section aria-labelledby="paired-execution-replay">
      <h2 id="paired-execution-replay">{ko ? "Sol 비교 실행을 다시 읽는 Replay" : "Replay the Sol paired execution"}</h2>
      <p>{ko
        ? "아래 기록은 Astra smoke와 별개인 2026-08-27~09-02 UTC의 Sol/max 비교 실행입니다. GEODE revision b549f3e의 OpenAI subscription 경로와 native Codex를 Harbor 0.22.0에서 실행했습니다. 동결 full-suite primary는 측정 불가이며, 공식 leaderboard 결과가 아닙니다."
        : "This is the separate August 27–September 2 UTC Sol/max comparison, not the separate Astra smoke. Harbor 0.22.0 ran GEODE revision b549f3e and native Codex through the OpenAI subscription route. The frozen full-suite primary is not measurable; this is not an official leaderboard result."}</p>
      <p>{ko
        ? "Pair 001~445는 89 tasks × 5 repetitions입니다. 각 쌍의 왼쪽은 GEODE, 오른쪽은 Codex이며, task·반복·arm 하나가 cell입니다. 재생하면 새 tool event가 아래에 나타나고 이전 기록은 위로 올라갑니다. 상단의 arm 정보는 고정됩니다."
        : "Pairs 001–445 represent 89 tasks × 5 repetitions. GEODE is on the left, Codex on the right; one task, repetition and arm form a cell. New tool events appear at the bottom and older lines move upward while arm metadata stays fixed."}</p>
      <p><a href={`/geode/benchmarks/terminal-bench/replay/?lang=${ko ? "ko" : "en"}`} target="_blank" rel="noopener noreferrer">
        {ko ? "445쌍 Replay 열기" : "Open the 445-pair replay"}
      </a></p>
      <table>
        <thead><tr><th>{ko ? "관찰 범위" : "Evidence coverage"}</th><th>GEODE</th><th>Codex</th><th>{ko ? "합계" : "Total"}</th></tr></thead>
        <tbody>
          <tr><td>ATIF-derived tool events</td><td>407</td><td>428</td><td>835</td></tr>
          <tr><td>Receipt only</td><td>28</td><td>7</td><td>35</td></tr>
          <tr><td>{ko ? "실행 전 제외" : "Not executed"}</td><td>10</td><td>10</td><td>20</td></tr>
          <tr><td>{ko ? "계획된 cells" : "Intended cells"}</td><td>445</td><td>445</td><td>890</td></tr>
        </tbody>
      </table>
      <p>{ko
        ? "16,244개 tool 호출의 순서를 재구성했습니다. 공개판은 tool·프로그램 종류, payload 크기, 해시와 시각만 표시합니다. command/output 본문, 모델 메시지와 provider reasoning은 공개하지 않습니다. 원본 UTC를 보존하고 KST로 표시하며, 5 events/s는 편집 속도입니다. 좌우는 tool-event 순서로 정렬했으며 실제 동시 실행이나 wall-time 정렬이 아닙니다."
        : "The view reconstructs 16,244 tool calls. It exposes tool/program labels, payload sizes, hashes and timestamps, not command/output bodies, model messages or provider reasoning. UTC sources are displayed in KST. Five events per second is editorial pacing; event-index alignment does not imply concurrent execution or wall-time synchronization."}</p>
      <p>{ko
        ? "35개 receipt-only cell에는 terminal 내용을 만들어 넣지 않았습니다. bn-fit-modify와 tune-mjcf의 20개 cell은 arm64 호스트에서 amd64 oracle/verifier가 정상 완료되지 않아 모델 호출 전에 대칭 제외했습니다. 별도로 미해소 native 인프라 무효가 6개 남았습니다. 공통 유효 429쌍의 secondary 결과는 GEODE 339/429, Codex 331/429이며, 이를 전체 suite 우위로 일반화하지 않습니다."
        : "No terminal content is invented for 35 receipt-only cells. Twenty cells from bn-fit-modify and tune-mjcf were symmetrically excluded before model calls because their amd64 oracle/verifier did not complete normally on the arm64 host. Six native infrastructure-invalid cells remain unresolved. The 429 common valid pairs give secondary results of 339/429 for GEODE and 331/429 for Codex, not a general full-suite superiority claim."}</p>
      <p>{ko
        ? "화면의 raw verifier와 selected reward는 구분해서 읽어야 합니다. 동결 규칙상 canonical timeout과 safety refusal은 selected zero이며, raw verifier가 1인 18개 cell도 여기에 포함됩니다. 점수의 근거는 Harbor result/verifier와 frozen attempt ledger·analysis입니다. 이 화면은 원본 PTY나 새로운 점수 판정기가 아닙니다."
        : "Read raw verifier and selected reward separately. Frozen rules assign selected zero to canonical timeouts and safety refusals, including 18 cells with raw verifier reward one. Harbor result/verifier, the frozen attempt ledger and analysis own scoring. This view is neither raw PTY footage nor a new scorer."}</p>
      <p><RunLogLink path={`${PAIRED_RUN}/recording/replay-v19-20260905`} revision={REPLAY_REVISION} label="Replay source · coverage · SHA-256 receipts" />{" · "}
        <RunLogLink path={PAIRED_RUN} revision={paired.commit} label="Frozen run · attempts · analysis" />
      </p>
      <h3>{ko ? "보존된 원본에서 복구한 실행 지표" : "Execution metrics recovered from preserved evidence"}</h3>
      <p>{ko
        ? "호출별 usage를 GEODE 401셀·4,709건, Codex 418셀·12,214건에서 복구하고 Harbor trial 합계와 대조했습니다. GEODE cache 필드 648건은 미기록 상태인 null로 보존합니다. Cached input은 input에 포함되며, 확인된 부분합을 전체 cache 값으로 표시하지 않습니다. Usage event는 ATIF tool step과 다른 단위이므로 재생 위치와 연동하지 않습니다."
        : "Call-level usage was recovered and reconciled with Harbor trial totals for 401 GEODE cells / 4,709 events and 418 Codex cells / 12,214 events. The 648 missing GEODE cache fields remain null. Cached input is part of input; an observed subtotal is not presented as a complete total. Usage events are distinct from ATIF tool steps and are not synchronized to playback."}</p>
      <p>{ko
        ? "Replay의 지표 항목을 펼치면 호출별 input·output·cache, environment setup·agent setup·execution·verifier 경과 시간, 완료된 shell command의 exit code 집계를 볼 수 있습니다. Nonzero exit는 tool 오류율이 아닙니다. 실제 CPU 사용률·peak RAM·subscription 청구액은 미계측이며, producer 비용 추정치는 청구액과 구분합니다. 원본 점수와 제외 규칙은 바뀌지 않았습니다."
        : "Expand the replay metrics to inspect per-call input, output and cache, phase elapsed times, and completed shell-command exit summaries. Nonzero exit is not a tool error rate. Actual CPU utilization, peak RAM and subscription billing are unmeasured; producer cost estimates are labeled separately. Original scores and exclusions remain unchanged."}</p>
      <p><RunLogLink path={`${PAIRED_RUN}/recording/research-v20`} revision={OBSERVABILITY_REVISION} label="Recovered observability · method · source hashes" /></p>
      <p className="text-sm text-[var(--ink-3)]">{ko
        ? "Next.js·React·TypeScript 페이지에서 재생합니다. Pinned commit의 metadata JSON을 SHA-256으로 검증한 뒤 표시하며, 검증 실패 시 재생을 차단합니다. 외부 HTML이나 스크립트를 실행하지 않습니다. 기존 .html 주소는 새 경로로 연결됩니다. Private viewer는 공개하지 않습니다."
        : "Playback runs in a native Next.js, React and TypeScript page. Metadata JSON from a pinned commit is SHA-256 verified before rendering; failure blocks playback. No external HTML or script is executed. The legacy .html URL redirects to the new route. The private viewer remains unpublished."}</p>
    </section>
  );
}

function GcodeDevelopmentGate({ ko }: { ko: boolean }) {
  const record = "https://github.com/mangowhoiscloud/geode/blob/b193a06bf08c85c60487f1e198a73fa1114f8d19/docs/plans/2026-09-13-reflexion-gcode-ratchet.md";
  return (
    <section aria-labelledby="gcode-development-gate">
      <h2 id="gcode-development-gate">{ko ? "후속 개발 검증: 내부 수락과 실제 정답의 간극" : "Development follow-up: acceptance is not correctness"}</h2>
      <p>{ko
        ? "첫 G-code 후보에서는 내부 judge가 5회를 모두 수락했지만, 공식 task verifier를 통과한 실행은 2회였습니다. 파일을 쓰고 다시 읽었다는 사실은 저장 성공만 확인할 뿐, 해석한 내용이 정답이라는 근거가 되지 못했습니다. 이 불일치를 출발점으로 검증 입력과 실행 경로를 고쳤습니다."
        : "The first G-code candidate received five internal judge acceptances, but only two trials passed the official task verifier. Writing and reading back a file established persistence, not a correct interpretation. That disagreement guided changes to verification inputs and execution paths."}</p>
      <p>{ko
        ? "짧은 답이나 복구한 tool 오류를 이유로 후보를 탈락시키던 의미 판정 규칙을 제거했습니다. Reflexion judge에는 관측 근거를 먼저, 후보의 주장을 마지막에 전달하고, 이미 관찰한 이미지가 일반 tool 기록에 밀려나지 않도록 했습니다. 위임 모델의 잘못된 기본값도 고쳤습니다. 검증 호출 실패는 성공으로 대체하지 않으며, 수정 작업은 최초 실행 예산을 공유합니다."
        : "The runtime no longer rejects candidates through short-answer or recovered-tool-error heuristics. The Reflexion judge receives observations before candidate claims, and already-observed images have a separate bounded window. An incorrect delegated-model default was also fixed. Judge failures never become structural passes, and repairs share the original execution budget."}</p>
      <table>
        <caption>{ko ? "후보별 실행 이력. 이전 후보의 성공을 새 후보에 합산하지 않았습니다." : "Candidate history. Passes are never pooled across revisions."}</caption>
        <thead><tr><th scope="col">{ko ? "소스 revision" : "Source revision"}</th><th scope="col">{ko ? "공식 verifier 결과" : "Official verifier outcomes"}</th><th scope="col">{ko ? "판정" : "Decision"}</th></tr></thead>
        <tbody>
          <tr><th scope="row"><code>d1e7420</code></th><td>0, 0, 0, 1, 1</td><td>{ko ? "2/5. 내부 judge의 오수락 3건을 확인했습니다." : "2/5. Three false-positive internal verdicts."}</td></tr>
          <tr><th scope="row"><code>c863c71</code></th><td>1, 0</td><td>{ko ? "사전 등록한 첫 실패 중단 규칙을 적용했습니다. 나머지 3회는 미실행입니다." : "Stopped at the first failure under the prospective rule; three trials were not executed."}</td></tr>
          <tr><th scope="row"><code>815f759</code></th><td>1, 1, 1, 1, 1</td><td>{ko ? "신규 5/5, 무효 0건. 개발 통과 조건을 충족했습니다." : "Fresh 5/5, zero invalid attempts. Development gate passed."}</td></tr>
        </tbody>
      </table>
      <p>{ko
        ? "마지막 5회는 2026-09-13 10:05부터 10:49 UTC까지(19:05부터 19:49 KST까지) 실행했습니다. OpenAI subscription gpt-5.6-sol, actor effort max, Harbor 0.22.0의 full-runtime adapter, agent 한도 900초, 동시성 1, 자동 재시도 0을 고정했습니다. 공식 gcode-to-text 이미지와 verifier는 변경하지 않았습니다."
        : "The final five trials ran on September 13, 2026, from 10:05 to 10:49 UTC (19:05 to 19:49 KST). The frozen configuration used OpenAI subscription gpt-5.6-sol, actor effort max, the full-runtime adapter on Harbor 0.22.0, a 900-second agent limit, concurrency one and zero automatic retries. The official gcode-to-text image and verifier were unchanged."}</p>
      <p>{ko
        ? "관측한 AgenticLoop 호출 87건에는 input 2,264,797, output 58,579, cached-input 946,432 토큰이 기록됐고, 이 세 필드의 누락은 0건입니다. 실제 요청에 이미지를 담았는지도 별도 receipt로 확인했습니다. 이는 기록된 호출 범위의 관측이며, 보조 LLM 호출을 포함한 전체 런타임 비용이나 구독 청구액은 아닙니다."
        : "The 87 recorded AgenticLoop calls contain 2,264,797 input, 58,579 output and 946,432 cached-input tokens, with no missing values in those three fields. Separate receipts confirm image serialization into requests. These observations cover recorded calls, not all auxiliary LLM activity, complete runtime cost or subscription billing."}</p>
      <p><strong>{ko ? "5/5는 개발 조건의 충족이지, repair 효과의 입증은 아닙니다." : "5/5 passes the development gate; it does not prove a repair effect."}</strong>{" "}{ko
        ? "5회 모두 내부 judge가 첫 후보를 수락해 실제 repair는 발생하지 않았습니다. 후보 선정에 사용한 한 과제이며, 새 baseline·native Codex 대조군이나 held-out 평가는 실행하지 않았습니다. 위 full-suite 결과와 제외 규칙, 기존 replay·영상은 그대로입니다."
        : "All five judges accepted candidate attempt zero, so no repair occurred. This is one task used for candidate selection, without a fresh baseline, native Codex control or held-out evaluation. The full-suite results, exclusions and existing replay/film remain unchanged."}</p>
      <details className="tb-details">
        <summary>{ko ? "소스·원본 보존·공개 범위" : "Source, custody and disclosure"}</summary>
        <p><code>terminalbench21-sol-max-reflexion-ratchet-r3-20260913</code>{ko
          ? "의 run-spec, attempts, native result, trajectory, verifier receipt, analysis와 녹화는 로컬 private 원본으로 보존했습니다. 문서 공개와 원본 artifact 공개는 다릅니다. 이번 5회의 공개 artifact 패키지와 갱신 영상은 아직 게시하지 않았습니다."
          : " retains its run spec, attempts, native results, trajectories, verifier receipts, analysis and recordings as local private evidence. Publishing this documentation does not publish those sources. A public artifact package and updated film for these five trials have not been posted."}</p>
        <p>{ko
          ? "중간 후보 c863c71은 감사 중 SQLite SHM 해시가 바뀌어 canonical closure가 보류됐습니다. 해당 admission을 새 해시로 덮어쓰지 않았으며, 별도로 검증을 통과한 마지막 5회와 섞지 않았습니다."
          : "The intermediate c863c71 candidate remains blocked from canonical closure after an audit changed SQLite SHM bytes. Its admission was not rewritten with a new hash, and it was not mixed into the separately validated final five trials."}</p>
        <p><a href={record}>{ko ? "실험 기록·한계·SHA-256" : "Run record, limitations and SHA-256"}</a>{" · "}<a href="https://github.com/mangowhoiscloud/geode/pull/3315">{ko ? "구현과 CI: PR #3315" : "Implementation and CI: PR #3315"}</a></p>
      </details>
    </section>
  );
}

function Study({ ko }: { ko: boolean }) {
  const excludedTrials = paired.excludedTasks.length * paired.repetitions;
  const availableTrials = paired.frozenTrialsPerArm - excludedTrials;
  const pooledDelta = rate(paired.geodePasses) - rate(paired.nativePasses);
  const [lower, upper] = paired.taskBootstrap95Pp;
  // One common, symmetric percentage-point axis; no rescaling by runtime.
  const intervalPosition = (value: number) => 40 + ((value + 10) / 20) * 520;
  const sources = [
    { label: "run-spec.json", role: ko ? "질문·고정 조건·제외 규칙" : "Question, fixed conditions, exclusion rules", ...paired.sources.spec },
    { label: "native-results.json", role: ko ? "공통 셀·성공 수·측정 유효성" : "Common cells, pass counts, measurement validity", ...paired.sources.data },
    { label: "analysis.json", role: ko ? "사전 등록 지표의 상태와 결론" : "Preregistered primary status and decision", ...paired.sources.analysis },
    { label: "figures-v6/provenance.json", role: ko ? "작업별 가중치·bootstrap 산식" : "Task weighting and bootstrap calculation", ...paired.sources.statistics },
    { label: ko ? "증거 영상 (한국어/영어)" : "Evidence film (KO/EN)", role: ko ? "실행 절차를 설명하는 파생 자료; 채점 근거 아님" : "Derived explanation of execution; not score authority", ...paired.sources.video },
  ];

  return (
    <div className="terminal-bench-study">
      <p className="tb-question">
        {ko
          ? "같은 모델과 추론 강도를 쓰더라도, 실행을 맡는 런타임이 달라지면 실제 작업 완수율은 어떻게 달라질까요?"
          : "With the model and reasoning effort held fixed, how does the runtime change completion of real terminal tasks?"}
      </p>
      <p>
        {ko ? "이 페이지의 중심은 " : "This study compares "}
        <strong>GPT-5.6 Sol / max effort</strong>
        {ko
          ? "를 사용한 GEODE와 native Codex의 Harbor 짝 비교입니다. 두 실행군을 같은 작업·반복 번호로 맞춰 비교하며, 모델 세대의 우열이나 공식 리더보드 순위를 평가하지 않습니다."
          : " in GEODE and native Codex through Harbor. It matches the two execution arms by task and repetition, rather than comparing model generations or claiming an official leaderboard rank."}
      </p>

      <h2>{ko ? "실험 설계: 공유 조건과 런타임의 차이" : "Study design: shared conditions, different runtimes"}</h2>
      <figure className="tb-protocol">
        <div className="tb-shared">
          <strong>{ko ? "두 실행군이 공유하는 조건" : "Shared by both arms"}</strong>
          <dl>
            <div><dt>{ko ? "모델 / 추론" : "Model / effort"}</dt><dd>{paired.model} / {paired.reasoning}</dd></div>
            <div><dt>{ko ? "접근 경로" : "Route"}</dt><dd>{paired.route}</dd></div>
            <div><dt>{ko ? "실행·채점" : "Execution / scoring"}</dt><dd>{paired.harness} / {ko ? "task 소유 verifier" : "task-owned verifier"}</dd></div>
            <div><dt>{ko ? "동결 범위" : "Frozen workload"}</dt><dd>{paired.frozenTasks} {ko ? "개 작업" : "tasks"} × {paired.repetitions} {ko ? "회 반복 / 실행군" : "repetitions / arm"}</dd></div>
          </dl>
        </div>
        <div className="tb-arms">
          <div><h3>GEODE</h3><p>{ko ? "측정 당시 revision b549f3e의 thin AgenticLoop adapter입니다. custom system_prompt_override와 terminal_exec만 노출한 도구 표면을 사용했습니다. 현재 native/full-runtime 구성의 측정은 별도 실험입니다." : "The measured b549f3e revision used a thin AgenticLoop adapter, a custom system_prompt_override, and a terminal_exec-only tool surface. Measuring today's native/full-runtime configuration is a separate experiment."}</p></div>
          <div><h3>native Codex</h3><p>{paired.comparator}. {ko ? "Codex 고유의 실행 루프와 도구 경로를 대조군으로 둡니다." : "The control retains Codex's own execution loop and tool path."}</p></div>
        </div>
        <div className="tb-pairing">
          <strong>{ko ? "각 실행 결과를 task × repetition으로 결합" : "Join results by task × repetition"}</strong>{" "}
          <span>{ko ? "양쪽이 모두 유효한 셀만 비교하고, 성공 여부는 task verifier가 판정합니다." : "Compare cells valid in both arms; task verifiers determine success."}</span>
        </div>
        <figcaption>
          {ko
            ? "실제 순서는 배치마다 GEODE 다음 native Codex입니다. 두 런타임을 동시에 시작한 실험이 아닙니다. 실행군 내부 concurrency는 8,192 MiB 작업에서 1, 나머지에서 2로 고정했습니다. 반복 측정은 best-of-5 선택이 아닙니다."
            : "Each batch runs GEODE followed by native Codex, not simultaneous starts of both runtimes. Within-arm concurrency is fixed at 1 for 8,192 MiB tasks and 2 otherwise. Repeated measurement is not best-of-five selection."}
        </figcaption>
      </figure>
      <p>
        <a href="https://www.tbench.ai/news/terminal-bench-2-1">Terminal-Bench 2.1</a>
        {ko
          ? "은 격리된 컨테이너에서 실제 terminal 작업을 풀고 외부 verifier로 최종 상태를 검사하는 벤치마크입니다. 비교 대상은 위 두 하네스 구성입니다. prompt, 도구 인터페이스, 컨텍스트 관리의 개별 기여를 분리한 ablation은 아닙니다."
          : " evaluates terminal work in isolated containers against external task verifiers. The comparison is between the two harness configurations above, not an ablation that isolates the contribution of prompts, tool interfaces, or context management."}
        {" "}<a href={paired.sources.spec.url}>{ko ? "동결된 실행 계약" : "Frozen execution contract"}</a>
      </p>

      <p>
        {ko
          ? "여기서 verifier는 과제가 소유한 테스트로 실행 후 상태를 검사합니다. GEODE의 턴 수락이나 Petri의 LLM-as-a-judge 점수가 아닙니다. 기록 무결성도 과제 성공과는 별개입니다."
          : "Here the verifier checks post-execution state using task-owned tests. It is neither GEODE's turn acceptance nor a Petri LLM-as-a-judge score. Recording integrity is also separate from task success."}
        {" "}<a href={`/geode/docs/verification/evaluation${ko ? "" : "?lang=en"}`}>{ko ? "검증과 평가의 역할 구분" : "Verification and evaluation boundaries"}</a>
      </p>

      <h2 id="terminal-bench-result">{ko ? "공통 유효 셀에서 관측한 성공률" : "Observed pass rates on common valid cells"}</h2>
      <p>
        {ko
          ? `두 런타임에서 모두 유효한 ${paired.commonTrials}개 task–repetition 쌍만 비교했습니다. 아래 값은 전체 동결 지표가 아닌 후속 짝 비교 진단입니다.`
          : `The comparison uses ${paired.commonTrials} task–repetition pairs valid in both runtimes. These are secondary paired-runtime diagnostics, not the full frozen primary metric.`}
      </p>
      <table className="tb-results">
        <caption>{ko ? "성공 수 / 공통 유효 실행 수. 막대는 같은 0–100% 축을 사용합니다." : "Passed / common valid trials. Bars share a 0–100% scale."}</caption>
        <thead><tr><th scope="col">{ko ? "런타임" : "Runtime"}</th><th scope="col">{ko ? "성공 / 유효" : "Passed / valid"}</th><th scope="col">{ko ? "성공률" : "Pass rate"}</th></tr></thead>
        <tbody>
          {[
            { name: "GEODE", passes: paired.geodePasses },
            { name: "native Codex", passes: paired.nativePasses },
          ].map(({ name, passes }) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td>{passes} / {paired.commonTrials}</td>
              <td><strong>{rate(passes).toFixed(2)}%</strong><div className="tb-bar" aria-hidden="true"><span data-runtime={name} style={{ width: `${rate(passes)}%` }} /></div><div className="tb-scale" aria-hidden="true"><span>0%</span><span>100%</span></div></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tb-verdict">
        <strong>{ko ? "결론은 미확정입니다." : "The decision is inconclusive."}</strong>{" "}
        {ko
          ? "관측한 차이는 작고 불확실성 구간이 0을 포함합니다. 이 결과만으로 GEODE의 성능 우위를 입증할 수 없습니다."
          : "The observed difference is small and its uncertainty interval includes zero. This result does not establish GEODE's superiority."}
        {" "}<a href={paired.sources.analysis.url}>{ko ? "분석 원본" : "Read the analysis"}</a>
      </p>

      <h2>{ko ? "분모: 실행환경 문제를 어떻게 제외했나" : "Denominator: how infrastructure exclusions work"}</h2>
      <ol className="tb-denominator">
        <li><strong>{paired.frozenTrialsPerArm}</strong>{" "}<span>{ko ? "실행군별 동결 계획" : "Frozen per arm"}</span>{" "}<small>{paired.frozenTasks} × {paired.repetitions}</small></li>
        <li><strong>{availableTrials}</strong>{" "}<span>{ko ? "환경 미지원 작업 제외" : "Environment-available"}</span>{" "}<small>−{excludedTrials} / {paired.excludedTasks.length} {ko ? "개 작업 × 반복" : "tasks × repetitions"}</small></li>
        <li><strong>{paired.commonTrials}</strong>{" "}<span>{ko ? "양쪽 공통 유효 셀" : "Common valid cells"}</span>{" "}<small>−{paired.unresolvedNativeTrials} {ko ? "개 인프라 무효 쌍" : "infrastructure-invalid pairs"}</small></li>
      </ol>
      <p>
        <code>{paired.excludedTasks.join(" / ")}</code>
        {ko
          ? "는 arm64 호스트에서 amd64 verifier를 실행할 수 없어 양쪽에서 대칭 제외했습니다. 남은 native Codex의 인프라 무효 실행은 대응하는 GEODE 결과도 함께 제외했습니다. 좋은 결과만 남기거나 각 런타임에 서로 다른 분모를 쓰지 않습니다."
          : " were excluded symmetrically because their amd64 verifiers could not run on the arm64 host. Remaining infrastructure-invalid native Codex trials also remove their GEODE counterparts. This avoids retaining only favorable outcomes or using a different denominator for each runtime."}
      </p>
      <p>
        <strong>{ko ? "정상 실행 뒤 작업에 실패한 경우는 분모에 남고 reward 0입니다." : "A valid execution that fails the task remains in the denominator with reward 0."}</strong>{" "}
        {ko
          ? `인프라 무효는 모델 실패의 0점으로 바꾸지 않습니다. 다만 제외 후 ${paired.commonTrials}회 결과를 사전 등록한 ${paired.frozenTrialsPerArm}회 지표로 바꿔 부를 수도 없습니다. 전체 primary는 not-measurable 상태를 유지합니다.`
          : `Infrastructure invalidity is not converted into a semantic zero. Conversely, the remaining ${paired.commonTrials} trials cannot replace the preregistered ${paired.frozenTrialsPerArm}-trial metric. The full primary remains not-measurable.`}
        {" "}<a href={paired.sources.data.url}>{ko ? "셀 선택·제외 원본" : "Inspect cell selection and exclusions"}</a>
      </p>

      <h2>{ko ? "불확실성: 반복 실행을 독립 작업처럼 세지 않습니다" : "Uncertainty: repetitions are not independent tasks"}</h2>
      <figure className="tb-uncertainty">
        <div className="tb-interval-heading"><strong>{signed(paired.taskBalancedDeltaPp)} {ko ? "%p" : "pp"}</strong>{" "}<span>{ko ? "작업별 동일 가중치 평균 차이: GEODE − native Codex" : "Task-balanced mean difference: GEODE − native Codex"}</span></div>
        <svg viewBox="0 0 600 118" role="img" aria-labelledby="tb-ci-title tb-ci-description">
          <title id="tb-ci-title">{ko ? "작업 단위 bootstrap 95% 구간" : "95% task-cluster bootstrap interval"}</title>
          <desc id="tb-ci-description">{`${signed(paired.taskBalancedDeltaPp)} pp; 95% interval ${signed(lower)} to ${signed(upper)} pp. ${ko ? "0을 포함합니다." : "Includes zero."}`}</desc>
          <line className="tb-axis" x1="40" x2="560" y1="72" y2="72" />
          <line className="tb-zero" x1={intervalPosition(0)} x2={intervalPosition(0)} y1="16" y2="78" />
          {[-10, -5, 0, 5, 10].map((tick) => <g key={tick}><line className="tb-axis" x1={intervalPosition(tick)} x2={intervalPosition(tick)} y1="68" y2="78" /><text x={intervalPosition(tick)} y="102" textAnchor="middle">{tick > 0 ? `+${tick}` : tick}</text></g>)}
          <line className="tb-ci" x1={intervalPosition(lower)} x2={intervalPosition(upper)} y1="42" y2="42" />
          {[lower, upper].map((bound) => <line key={bound} className="tb-ci" x1={intervalPosition(bound)} x2={intervalPosition(bound)} y1="32" y2="52" />)}
          <circle className="tb-estimate" cx={intervalPosition(paired.taskBalancedDeltaPp)} cy="42" r="6" />
        </svg>
        <figcaption>
          {ko
            ? `단위: %p. 점은 작업별 동일 가중치 추정값, 선은 ${signed(lower)}~${signed(upper)}의 95% task-cluster bootstrap 구간입니다. ${paired.includedTasks}개 작업을 단위로 반복 측정의 묶음을 유지합니다.`
            : `Units: percentage points (pp). The dot is the task-balanced estimate; the line is the 95% task-cluster bootstrap interval, ${signed(lower)} to ${signed(upper)}. Repeated trials remain clustered within ${paired.includedTasks} tasks.`}
        </figcaption>
      </figure>
      <p>
        {ko
          ? `위 성공률을 단순히 뺀 pooled 차이는 ${signed(pooledDelta)}%p입니다. 작업별 유효 반복 수가 같지 않아, 각 작업에 같은 가중치를 준 ${signed(paired.taskBalancedDeltaPp)}%p와 다릅니다. ${paired.repetitions}회 반복은 같은 정책의 변동성을 측정합니다. 한 번이라도 성공했는지를 세는 pass@5나 최상위 답을 고르는 best-of-5가 아닙니다.`
          : `Subtracting the pooled pass rates gives ${signed(pooledDelta)} pp. Because valid repetition counts differ across tasks, this differs from the equally task-weighted ${signed(paired.taskBalancedDeltaPp)} pp estimate. The ${paired.repetitions} repetitions measure one policy's variability; they are not pass@5 or best-of-five answer selection.`}
        {" "}<a href={paired.sources.statistics.url}>{ko ? "통계 산식·출처" : "Statistical method and provenance"}</a>
      </p>

      <PairedReplay ko={ko} />

      <GcodeDevelopmentGate ko={ko} />

      <h2>{ko ? "다음 실험: 점수 확대보다 비교 가능성 복구" : "Next experiment: restore comparability before scaling"}</h2>
      <details className="tb-details">
        <summary>{ko ? "캐시·토큰·비용을 읽을 때의 주의점" : "Reading cache, token, and cost accounting"}</summary>
        <p>
          {ko
            ? "기존 GEODE Harbor 변환부에서 캐시 필드 이름이 맞지 않아, 런타임에 기록된 cache_read_tokens가 결과와 ATIF 출력에서 0으로 표시될 수 있었습니다. 따라서 과거 출력의 캐시 0만으로 캐시가 사용되지 않았다고 판단하지 않습니다. 세션별 원장과 대조한 별도 보정 자료가 필요합니다. 위 replay의 복구 자료는 이 방식으로 공개됐으며, 원본 결과와 성공률은 바꾸지 않습니다."
            : "The earlier GEODE Harbor bridge read a mismatched cache field: runtime cache_read_tokens could become zero in results and ATIF output. A historical zero therefore does not establish that caching was unused. Corrections require a separate session-ledger reconciliation. The recovered replay evidence above follows that process; original results and pass rates remain unchanged."}
        </p>
        <p>
          {ko
            ? "시간 초과로 최종 usage가 없으면 미수집 상태입니다. 완료된 호출에서 복구한 토큰은 관측 하한일 뿐, 실행 전체의 합계가 아닙니다. 입력·캐시 읽기·캐시 쓰기·출력을 같은 계측 범위에서 비교하고, 토큰 단가로 계산한 비용 추정치를 구독 계정의 실제 청구액으로 해석하지 않습니다."
            : "Missing final usage after a timeout is unknown. Tokens recovered from completed calls are an observed lower bound, not a whole-trial total. Compare input, cache reads, cache writes, and output over matched coverage; token-price estimates are not the subscription account's actual bill."}
        </p>
      </details>
      <p>
        {ko
          ? "여러 날에 걸친 구독 경로 실행은 시점, 공급자 용량, 인증 계정의 영향을 런타임 효과와 완전히 분리하지 못합니다. 같은 경로라고 해서 전 기간에 같은 인증 계정을 썼다는 뜻은 아닙니다. Harbor 0.22.0은 공통 seed 제어도 제공하지 않았습니다. 아래는 후속 실험 설계이며 이번 결과에 추가된 측정이 아닙니다."
          : "A subscription-route study spanning several days cannot fully separate timing, provider capacity, and credential-principal effects from runtime effects. The same route does not mean the same credential principal throughout. Harbor 0.22.0 also exposed no shared seed control. The following is a proposed follow-up, not additional measurement in this result."}
      </p>
      <table>
        <thead><tr><th scope="col">{ko ? "질문" : "Question"}</th><th scope="col">{ko ? "다음 개입" : "Next intervention"}</th><th scope="col">{ko ? "필요한 증거" : "Required evidence"}</th></tr></thead>
        <tbody>
          <tr><th scope="row">{ko ? "전체 분모를 회복할 수 있나?" : "Can the full denominator be restored?"}</th><td>{ko ? "verifier와 맞는 실행 아키텍처, 두 실행군의 인증·설치 사전 점검" : "Verifier-compatible architecture and auth/setup preflight for both arms"}</td><td>{ko ? "새 동결 계약, no-model oracle, 양쪽 유효 smoke 후 전체 실행" : "A new frozen contract, no-model oracle, valid smoke in both arms, then the full run"}</td></tr>
          <tr><th scope="row">{ko ? "차이를 만든 런타임 요소는 무엇인가?" : "Which runtime behavior explains a difference?"}</th><td>{ko ? "모델·도구·예산을 고정하고 한 정책만 바꾸는 paired ablation" : "Paired ablation of one policy with model, tools, and budget fixed"}</td><td>{ko ? "task별 결과와 행동·종료·실패 경로의 결속, 별도 held-out 검증" : "Task outcomes joined to action, termination, and failure paths; separate held-out validation"}</td></tr>
          <tr><th scope="row">{ko ? "품질과 실행 비용을 함께 개선했나?" : "Did quality and execution cost improve together?"}</th><td>{ko ? "계정·시점·concurrency를 명시한 반복 블록 설계" : "Repeated blocks with explicit accounts, timing, and concurrency"}</td><td>{ko ? "동일한 비용·시간 계측 범위와 작업 단위 불확실성 보고" : "Matched cost/time instrumentation and task-level uncertainty"}</td></tr>
        </tbody>
      </table>
      <p>
        {ko ? "공식 제출의 " : "The "}<a href="https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/SUBMIT.md">{ko ? "고정 계약" : "pinned official submission contract"}</a>
        {ko
          ? `은 ${paired.frozenTasks}개 작업 × k≥${paired.repetitions}, 오류 실행의 0점 유지, canonical 환경·한도와 maintainer review를 요구합니다. 로컬 진단용 인프라 제외 규칙을 공식 점수에 적용하지 않습니다. 이 자료는 공식 제출·순위·제품 승격 권한을 갖지 않습니다.`
          : ` requires ${paired.frozenTasks} tasks at k≥${paired.repetitions}, errored trials retained as zero, canonical environments and limits, and maintainer review. The local diagnostic exclusion rule does not apply to official scores. This artifact has no official submission, rank, or product-promotion authority.`}
      </p>

      <details className="tb-details">
        <summary>{ko ? "원자료·통계·공개 근거 확인" : "Inspect source data, statistics, and provenance"}</summary>
        <p>{ko ? "공개 스냅샷" : "Public snapshot"}: <code>{paired.commit}</code><br />Run: <code>{paired.runId}</code></p>
        <p>{ko ? "측정한 GEODE revision" : "Measured GEODE revision"}: <code>{paired.geodeRevision}</code><br />Dataset: <code>{paired.dataset}</code><br /><code>{paired.datasetDigest}</code></p>
        <p>{ko ? "이 페이지와 영상은 읽기용 파생 뷰입니다. 성공 여부는 Harbor 결과와 task verifier가, 셀 선택과 해석은 결속된 분석 자료가 소유합니다. 영상 재생만으로 점수를 검증했다고 주장하지 않습니다." : "This page and the film are reading views. Harbor results and task verifiers own success; bound analysis artifacts own cell selection and interpretation. Watching a replay is not score verification."}</p>
        <table className="tb-sources"><thead><tr><th scope="col">{ko ? "자료" : "Artifact"}</th><th scope="col">{ko ? "역할 / SHA-256" : "Role / SHA-256"}</th></tr></thead><tbody>{sources.map((source) => <tr key={source.url}><th scope="row"><a href={source.url}>{source.label}</a></th><td>{source.role}{" "}<code>{source.sha256}</code></td></tr>)}</tbody></table>
      </details>
      <details className="tb-details">
        <summary>{ko ? "별도 기록: GPT-6 Astra 단일 작업 smoke" : "Separate record: GPT-6 Astra single-task smoke"}</summary>
        <p>
          <code>{astra.model}</code> / <code>{astra.reasoning}</code>, GEODE {astra.geodeVersion}, {astra.harness}: <code>{astra.task}</code>.
          {ko
            ? ` ${astra.passedTrials}/${astra.selectedTrials}회 성공, verifier ${astra.verifierPassed}/${astra.verifierTotal}개 통과, retry ${astra.retries}회·fallback ${astra.fallbacks}회입니다. 이 계정에서 실제 작업을 끝낸 경로 증거이며, 위 Sol/max 비교에 합산하지 않습니다.`
            : ` ${astra.passedTrials}/${astra.selectedTrials} trial passed, ${astra.verifierPassed}/${astra.verifierTotal} verifier checks passed, ${astra.retries} retries and ${astra.fallbacks} fallbacks. This is account-scoped task-execution evidence, not an additional observation in the Sol/max comparison.`}
        </p>
        <p>{ko ? `공개 trace는 scope-complete지만 ${astra.trace.omittedPayloadCount}개 payload 본문이 생략되어 replay-incomplete입니다. 전체 suite 성능이나 일반 계정 접근성을 입증하지 않습니다.` : `The public trace is scope-complete but replay-incomplete, with ${astra.trace.omittedPayloadCount} payload bodies withheld. It does not establish full-suite performance or access for other accounts.`}</p>
        <p><a href={astra.sources.analysis.url}>{ko ? "Astra smoke 분석" : "Astra smoke analysis"}</a>{" / "}<a href={astra.sources.verifier.url}>{ko ? "task verifier 결과" : "Task verifier result"}</a></p>
      </details>
    </div>
  );
}

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/terminal-bench"
      title="Terminal-Bench 2.1"
      titleKo="Terminal-Bench 2.1"
      summary="GPT-5.6 Sol at max effort: GEODE and native Codex compared through Harbor, with paired outcomes, infrastructure exclusions, and uncertainty kept explicit."
      summaryKo="GPT-5.6 Sol·max effort로 GEODE와 native Codex를 Harbor에서 비교한 실험입니다. 공통 실행 결과, 인프라 제외, 불확실성을 함께 읽습니다."
    >
      <Bi ko={<Study ko />} en={<Study ko={false} />} />
    </DocsShell>
  );
}
