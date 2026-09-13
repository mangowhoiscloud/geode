import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { docsPageHref } from "@/lib/geode-docs/navigation";

export const metadata = { title: "Verification and evaluation · GEODE Docs" };

function EvaluationGuide({ ko }: { ko: boolean }) {
  const docsHref = (slug: string) => `/geode${docsPageHref(slug, ko ? "ko" : "en")}`;
  const authorities = [
    {
      name: ko ? "런타임의 턴 검증" : "Runtime turn verification",
      evidence: ko ? "턴 출력, 도구 호출 기록, 설정된 규칙·훅" : "Turn output, tool-call records, configured rules and hooks",
      decision: ko ? "턴을 수락하거나 제한된 후속 작업을 요청하고, 외부 검토를 위해 결과를 보류할 수도 있습니다." : "Accepts the turn, requests bounded continuation, or holds the result for external review.",
      limit: ko ? "외부 과제의 정답 판정이 아닙니다." : "Not an external task's ground-truth verdict.",
    },
    {
      name: ko ? "벤치마크 verifier" : "Benchmark verifier",
      evidence: ko ? "과제가 소유한 테스트와 실행 후 환경 상태" : "Task-owned tests and post-execution environment state",
      decision: ko ? "해당 과제의 기준에 따라 reward를 냅니다." : "Produces reward against that task's criteria.",
      limit: ko ? "테스트 범위를 넘는 안전성·일반 능력은 보장하지 않습니다." : "Does not establish safety or capability beyond test coverage.",
    },
    {
      name: "Petri LLM-as-a-judge",
      evidence: ko ? "감사 transcript와 차원별 rubric" : "Audit transcript and dimension-specific rubric",
      decision: ko ? "관찰한 행동을 차원별로 채점합니다." : "Scores observed behavior by dimension.",
      limit: ko ? "모델의 판단이며 실제 상태 검사나 사람의 정답 라벨과 같지 않습니다." : "A model judgment, not a state check or human ground truth.",
    },
    {
      name: ko ? "아티팩트 무결성 검사" : "Artifact integrity validation",
      evidence: ko ? "스키마, SHA-256, 실행·호출 ID와 기록 범위" : "Schemas, SHA-256, run/call identity, and recording scope",
      decision: ko ? "같은 증거를 읽는지, 기록이 연결되는지 확인합니다." : "Checks evidence identity and record joins.",
      limit: ko ? "무결성 통과는 과제 성공이나 높은 점수를 뜻하지 않습니다." : "Integrity passing is neither task success nor a high score.",
    },
  ];

  return (
    <>
      <p>
        {ko
          ? "에이전트가 끝났다고 말한 것, 과제 테스트를 통과한 것, judge가 행동을 좋게 평가한 것은 서로 다른 관측입니다. GEODE의 결과를 읽을 때도 이 판정들을 하나의 성공 표시로 합치지 않아야 합니다."
          : "An agent declaring completion, a task passing its tests, and a judge rating behavior favorably are different observations. Keep these verdicts separate when interpreting GEODE's results."}
      </p>
      <h2>{ko ? "무엇을, 누가 판정하나요?" : "What is judged, and by whom?"}</h2>
      <table>
        <caption>{ko ? "같은 실행을 보더라도 판정의 범위와 권한은 다릅니다." : "Different authorities can inspect the same execution."}</caption>
        <thead><tr><th scope="col">{ko ? "판정" : "Check"}</th><th scope="col">{ko ? "입력 증거" : "Evidence"}</th><th scope="col">{ko ? "결정과 한계" : "Decision and limit"}</th></tr></thead>
        <tbody>{authorities.map((row) => <tr key={row.name}><th scope="row">{row.name}</th><td>{row.evidence}</td><td>{row.decision} {row.limit}</td></tr>)}</tbody>
      </table>

      <h2>{ko ? "Eval은 판정 하나보다 넓습니다" : "An eval is more than one verdict"}</h2>
      <ol>
        <li>{ko ? "실행 전에 질문, 과제, 모델·경로, 예산, 반복 수, 지표와 제외 규칙을 run-spec에 고정합니다." : "Freeze the question, tasks, model/route, budget, repetitions, metric, and exclusion rule in the run spec."}</li>
        <li>{ko ? "각 시도의 실제 실행은 attempts와 native result에 남기고, trajectory는 행동 기록을 연결합니다." : "Retain each attempt and native result; link behavioral evidence through trajectories."}</li>
        <li>{ko ? "과제 verifier 또는 rubric 기반 judge가 목적에 맞는 점수를 냅니다. 둘을 함께 쓰면 결과도 따로 기록합니다." : "Use a task verifier or rubric-based judge for the question at hand. If both are used, keep their outputs separate."}</li>
        <li>{ko ? "분석은 고정된 선택 규칙으로 분자·분모와 불확실성을 계산합니다. 외부 루프의 승격은 별도의 게이트가 결정합니다." : "Analysis applies the frozen selection rule to counts and uncertainty. A separate outer-loop gate decides promotion."}</li>
      </ol>
      <p>
        {ko
          ? "유효하게 실행했지만 틀린 결과는 reward 0일 수 있습니다. 인프라 오류, 미실행, 누락 라벨은 같은 0이 아닙니다. 재시도와 제외를 숨기지 않고 원래 시도에 연결하며, 누락된 판정을 성공·실패로 추정하지 않습니다."
          : "A valid semantic failure can have reward zero. Infrastructure errors, unexecuted tasks, and missing labels are different states. Retain retry/exclusion lineage and do not infer a verdict from missing evidence."}
        {" "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/eval/data-model.md">{ko ? "평가 데이터 계약" : "Evaluation data contract"}</a>
      </p>

      <h2>{ko ? "Petri의 judge와 런타임 self-judge" : "Petri judging versus runtime self-judging"}</h2>
      <p>
        {ko
          ? "Petri에서는 auditor가 seed에 따라 감사 상황을 탐색하고, target이 응답하며, judge가 transcript를 rubric으로 채점합니다. judge가 과제 환경을 다시 실행해서 정답을 검증하는 구조는 아닙니다."
          : "In Petri, the auditor explores a seed-guided scenario, the target responds, and the judge scores the transcript against a rubric. This is not a rerun of the task environment to verify ground truth."}
        {" "}<a href="https://github.com/meridianlabs-ai/inspect_petri">{ko ? "Petri 공식 설명" : "Petri's documented roles"}</a>
      </p>
      <p>
        <code>core/agent/verify.py</code>{ko ? "의 " : " has a separate "}<code>llm_judge</code>
        {ko
          ? "는 별도의 opt-in 턴 검증 모드입니다. 기본 rule_based는 빈 실행과 운영자 조치 필요 상태를 검사하며 LLM을 호출하지 않습니다. 내부 self-judge는 Petri의 외부 감사 점수가 아닙니다."
          : " opt-in turn-verification mode. The default rule_based checks empty execution and operator-action requirements without an LLM call. The internal self-judge is not a Petri audit score."}
      </p>
      <p>
        {ko
          ? "잘못된 JSON, 필드 타입, 점수와 judge 호출 실패는 verification_error로 기록합니다. passed=false, score=0, should_retry=false이며, rule_based 성공으로 대체하지 않습니다. 이 0은 검토 오류를 나타내는 내부 값이지 벤치마크 reward가 아닙니다."
          : "Malformed JSON, invalid fields or scores, and unavailable judge calls produce verification_error: passed=false, score=0, should_retry=false. Neither LLM mode falls back to structural success. This zero describes an internal verification error, not benchmark reward."}
      </p>
      <p>
        <code>reflexion</code>{ko
          ? "도 opt-in 모드입니다. 원래 요청, 후보, 제한된 최근 tool 결과와 이미 관찰한 이미지를 검토하고 observation / lesson / next_check를 남깁니다. 짧은 응답이나 복구한 tool 오류만으로 후보를 탈락시키지 않습니다. 최초 예산 안에서 최대 두 번 수정합니다. 남은 시간이 전체의 3분의 1(최대 300초) 이하이면 다음 모델 호출에서 첫 후보 검토를 요청합니다. 진행 중인 호출을 이 시점에 강제 중단하지는 않습니다. Judge usage는 기존 TokenTracker에 기록합니다. 최종 벤치 점수는 여전히 외부 verifier가 판정합니다."
          : " is also opt-in. It assesses the request and candidate against bounded recent tool results and already-observed images, returning observation / lesson / next_check. Concise output and recovered tool errors do not veto review. Up to two repairs share the original deadline. Once the final third remains, capped at 300 seconds, the next model call requests the first candidate for review; this does not interrupt an in-flight call. Judge usage uses the existing TokenTracker. The external verifier still owns benchmark reward."}
        {" "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/core/agent/verify.py">{ko ? "현재 턴 검증 구현" : "Current turn-verification implementation"}</a>
      </p>
      <p>{ko
        ? "이미지 근거는 텍스트 tool 기록과 별도로 선택해, 파일 쓰기나 계획 갱신 때문에 밀려나지 않도록 합니다. 이전 시도와 현재 시도의 관측, 전달하지 못한 이미지도 구분합니다. 이전 자료가 여전히 유용할 수는 있지만 수정 후 새로 확인한 증거와 같지는 않습니다."
        : "Image evidence has a separate bounded window, so writes and plan updates do not displace it. Reviews identify prior versus current observations and omitted images. Earlier source material may remain useful, but is not a fresh post-repair check."}</p>
      <p>{ko
        ? "관측 근거를 먼저, 후보의 주장을 마지막에 제시합니다. 동일한 값을 쓰고 다시 읽은 일관성이나 실패한 위임은 독립 검증이 아닙니다. 근거로 해소되지 않는 모호함은 통과시키지 말고, 구별 가능한 재검사를 요청하도록 judge를 구성합니다. 이 지시만으로 오판이 사라졌다고 주장하지 않습니다."
        : "Evidence precedes the candidate claim. Reading back the same written value or making a failed delegation is not independent verification. The judge is instructed to request a distinguishing check for unresolved material ambiguity. These instructions alone do not establish that false verdicts are eliminated."}</p>
      <p>{ko
        ? "Reflexion의 verdict와 continuation 기록은 있지만, 다음 요청에서 힌트를 소비했음을 결속하는 digest/event는 아직 없습니다. 이 기록만으로 힌트 소비까지 전 과정이 실측됐거나 성능 개선 효과가 입증됐다고 주장하지 않습니다."
        : "Reflexion records verdicts and continuation, but does not yet bind hint consumption in the next request with a digest/event. These records do not establish end-to-end measured consumption or a performance benefit."}</p>
      <details>
        <summary>{ko ? "Judge를 믿기 전에 확인할 항목" : "Checks before trusting a judge"}</summary>
        <ul>
          <li>{ko ? "Judge 모델·버전·경로, rubric 원본, 점수 방향, seed와 transcript 범위를 고정합니다. 높은 점수가 좋은지는 차원마다 확인합니다." : "Pin judge model/version/route, rubric, score direction, seeds, and transcript scope. Check polarity per dimension."}</li>
          <li>{ko ? "같은 공급자의 모델을 역할별로 나눴다고 평가가 독립적이라고 단정하지 않습니다. 경고나 보정 계수의 존재만으로 편향이 제거되지는 않습니다." : "Different roles on one provider do not establish independent evaluation. A warning or correction factor does not prove bias removal."}</li>
          <li>{ko ? "사람이 judge 점수를 보기 전에 동일 rubric으로 라벨을 매기고, 불일치 사례와 차원별 표본 수를 함께 봅니다." : "Have humans label against the same rubric before seeing judge scores; inspect disagreements and sample counts by dimension."}</li>
          <li>{ko ? "GEODE에는 blind labeling과 weighted Cohen’s kappa·ordinal Krippendorff’s alpha를 계산하는 audit-agreement 경로가 있습니다. 기능이 있다는 사실과 실제 라벨로 신뢰도를 입증했다는 사실은 구분합니다." : "GEODE's audit-agreement path supports blind labeling, weighted Cohen's kappa, and ordinal Krippendorff's alpha. Available tooling is not evidence of reliability on actual labels."}</li>
        </ul>
        <pre>{`geode-eval audit-agreement --help`}</pre>
        <p><a href={docsHref("petri/judge-dimensions")}>{ko ? "Judge 차원과 해석" : "Judge dimensions and interpretation"}</a>{" · "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/core/audit/judge_agreement.py">{ko ? "사람과 judge의 일치도 구현" : "Human–judge agreement implementation"}</a></p>
      </details>

      <h2>{ko ? ".eval은 Petri 전용 파일이 아닙니다" : ".eval is not exclusive to Petri"}</h2>
      <p>
        {ko
          ? "Eval은 평가 절차를 뜻하고, .eval은 Inspect가 저장하는 평가 로그 형식입니다. Petri는 Inspect 위에서 동작하므로 이 형식을 사용합니다. 모델·실행 설정, 샘플, 메시지와 점수를 함께 읽되, 파일이 존재하거나 실행 상태가 success라고 해서 모든 샘플의 답이 정답이라는 뜻은 아닙니다."
          : "Eval names the evaluation process; .eval is an Inspect log format. Petri uses it because it runs on Inspect. Inspect model/run configuration, samples, messages, and scores together: a file existing or an execution status of success does not mean every answer was correct."}
        {" "}<a href="https://inspect.aisi.org.uk/eval-logs.html">{ko ? "Inspect 로그 계약" : "Inspect log contract"}</a>
      </p>
      <p>
        {ko
          ? "Harbor의 결과 JSON, Inspect의 .eval, GEODE trajectory를 하나의 형식으로 강제 변환하지 않습니다. 각 원본을 보존하고 실행 ID와 SHA-256으로 연결합니다. 새로운 judge 라벨은 별도 파생 평가로 남기며, 공개된 과거 reward나 원본 transcript를 덮어쓰지 않습니다."
          : "Do not force Harbor result JSON, Inspect .eval logs, and GEODE trajectories into one replacement format. Preserve native evidence and join by execution identity and SHA-256. New judge labels belong in derived evaluations, not overwrites of published rewards or transcripts."}
      </p>

      <h2>{ko ? "Terminal-Bench 결과를 읽을 때" : "Reading the Terminal-Bench results"}</h2>
      <p>
        {ko
          ? "이 사이트의 Sol/max 비교는 task verifier와 고정된 결과 선택 규칙으로 읽습니다. Petri judge가 이 성공률을 채점한 것은 아닙니다. 이후 transcript에 LLM judge를 추가하더라도 행동 진단이라는 별도 질문·rubric·예산으로 등록해야 하며, 기존 성공률에 섞지 않습니다."
          : "The Sol/max comparison uses task verifiers and frozen outcome-selection rules, not Petri judge scores. Adding an LLM judge to those transcripts would require a separate behavioral question, rubric, and budget; it must not be blended into the original pass rate."}
      </p>
      <p><a href={docsHref("benchmarks/terminal-bench")}>Terminal-Bench 2.1</a>{" · "}<a href={docsHref("petri/overview")}>Petri × GEODE</a>{" · "}<a href={docsHref("verification/observability")}>{ko ? "관측성과 기록 품질" : "Observability and recording quality"}</a>{" · "}<a href={docsHref("guides/publish-trajectory")}>{ko ? "증거 게시 절차" : "Evidence publication"}</a></p>
    </>
  );
}

export default function Page() {
  return (
    <DocsShell
      slug="verification/evaluation"
      title="Verification and evaluation"
      titleKo="검증과 평가"
      summary="Separate runtime acceptance, task verifiers, LLM judges, and evidence integrity before interpreting a score."
      summaryKo="점수를 해석하기 전에 런타임의 수락, 과제 verifier, LLM judge, 기록 무결성을 구분합니다."
    >
      <Bi ko={<EvaluationGuide ko />} en={<EvaluationGuide ko={false} />} />
    </DocsShell>
  );
}
