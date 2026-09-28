import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { docsPageHref } from "@/lib/geode-docs/navigation";

export const metadata = { title: "Verification and evaluation · GEODE Docs" };

// Artifact PR #46 merge, verified by the September 28, 2026 remote read-back.
const jevV3Packet = "https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/3bcf4044eb5c2411dd48122d672aef72a83fb30e/reports/e2e-validation/jev-v3-20260927";

function EvaluationGuide({ ko }: { ko: boolean }) {
  const docsHref = (slug: string) => `/geode${docsPageHref(slug, ko ? "ko" : "en")}`;
  const authorities = [
    {
      name: ko ? "런타임 턴 검증" : "Runtime turn verification",
      evidence: ko ? "턴 출력, 도구 호출 기록, 설정된 규칙·훅" : "Turn output, tool-call records, configured rules and hooks",
      decision: ko ? "턴을 수락하거나, 제한된 후속 작업을 요청하거나, 외부 검토로 보류합니다. 외부 과제의 정답 판정은 아닙니다." : "Accepts the turn, requests bounded continuation, or holds it for external review. It is not an external task's ground truth.",
    },
    {
      name: ko ? "벤치마크 verifier" : "Benchmark verifier",
      evidence: ko ? "과제가 소유한 테스트와 실행 후 환경 상태" : "Task-owned tests and post-execution environment state",
      decision: ko ? "과제 기준으로 reward를 냅니다. 테스트가 다루는 범위까지만 말해 줍니다." : "Produces reward against the task's criteria, covering only what the tests cover.",
    },
    {
      name: "Petri LLM-as-a-judge",
      evidence: ko ? "감사 transcript와 차원별 rubric" : "Audit transcript and per-dimension rubric",
      decision: ko ? "관찰한 행동을 차원별로 채점합니다. 모델의 판단이며, 상태 검사나 사람의 정답 라벨과는 다릅니다." : "Scores observed behavior per dimension. A model's judgment, not a state check or human ground truth.",
    },
    {
      name: ko ? "아티팩트 무결성 검사" : "Artifact integrity validation",
      evidence: ko ? "스키마, SHA-256, 실행·호출 ID, 기록 범위" : "Schemas, SHA-256, run/call identity, recording scope",
      decision: ko ? "같은 증거를 읽는지, 기록끼리 연결되는지 확인합니다. 통과해도 과제 성공이나 점수를 뜻하지는 않습니다." : "Confirms evidence identity and record joins. Passing says nothing about task success or score.",
    },
  ];
  const runtime = [
    {
      topic: ko ? "판정 엔진" : "Engine",
      rule: ko
        ? "기본은 LLM입니다. /model judgment에서 Jev를 고르면 TypeSafe 또는 OpenRouter 키로 매 라운드와 최종 후보를 판정하고, 키가 없으면 LLM을 계속 씁니다. judge_model로 다른 공급자 모델을 써도 주 실행 경로와 도구 권한은 바뀌지 않습니다."
        : "LLM by default. Selecting Jev with /model judgment judges every round and the final candidate through a TypeSafe or OpenRouter key; without a key the LLM route stays. A judge_model from another provider leaves the root route and tool permissions unchanged.",
    },
    {
      topic: ko ? "출력 계약" : "Output contract",
      rule: ko
        ? "judge는 작업 스키마를 물려받지 않고 passed, score와 observation / lesson / next_check를 반환합니다. 잘못된 JSON·점수, judge 호출 실패는 verification_error(passed=false, score=0, should_retry=false)로 기록하고 구조 검사 통과로 대신하지 않습니다. 이 0은 벤치마크 reward가 아니라 내부 검토 오류 값입니다."
        : "Judges return passed, score and observation / lesson / next_check instead of inheriting the task schema. Malformed JSON or scores and failed judge calls are recorded as verification_error (passed=false, score=0, should_retry=false), never replaced by a structural pass; that zero is an internal review error, not benchmark reward.",
    },
    {
      topic: ko ? "수정 루프" : "Repair loop",
      rule: ko
        ? "Reflection은 도구 결과가 나온 매 라운드와 최종 응답 전에 실행합니다. 수정은 원래 마감 안에서 최대 두 번이며, 남은 시간이 3분의 1(최대 300초) 이하면 첫 후보를 검토에 올립니다. 개인정보(REDACT)·시간·비용 가드는 유지되고, 건너뛴 검토는 통과가 아닙니다."
        : "Reflection runs after each tool-result round and before final delivery. Up to two repairs share the original deadline; once the final third (at most 300 s) remains, the first candidate goes to review. Privacy (REDACT), time and cost guards stay on, and a skipped review is not a pass.",
    },
    {
      topic: ko ? "근거 범위" : "Evidence window",
      rule: ko
        ? "최근 관측 12개를 총 16,000자(필드당 최대 6,000자)로 전달하고 잘린 부분을 표시합니다. 재개한 요청은 이전 턴의 실제 호출·결과 쌍도 포함합니다. 이미지는 별도 창으로 보내고, 후보의 주장·압축 요약·내부 추론은 도구 증거로 쓰지 않습니다."
        : "The latest 12 observations share 16,000 characters (6,000 per field) with truncation marked. Resumed requests include earlier turns' actual call/result pairs. Images travel in a separate window; candidate claims, compaction summaries and internal reasoning never count as tool evidence.",
    },
    {
      topic: ko ? "후보 선택" : "Best-of-N",
      rule: ko
        ? "성공한 후보끼리 상대 평가합니다. 선택이 실패하면 judge_error를 남기고 첫 성공 후보를 쓰는데, 이 대체는 검증 통과가 아닙니다."
        : "Ranks successful candidates against each other. A failed selection records judge_error and falls back to the first successful candidate, which is not a verification pass.",
    },
    {
      topic: ko ? "사용량" : "Usage",
      rule: ko
        ? "judge와 reflection의 토큰·캐시·비용은 TokenTracker와 비용 가드에 한 번 기록하며, 모델이 도구를 거절하거나 잘못 응답해도 관측된 사용량은 남습니다. 공급자가 보고한 비용과 가격표 추정은 실제 청구액이 아닙니다."
        : "Judge and reflection tokens, cache and cost reach TokenTracker and the cost guard once, even when the model declines the tool or returns malformed output. Provider-reported cost and catalog estimates are not invoices.",
    },
    {
      topic: "confidence",
      rule: ko
        ? "CognitiveState의 confidence는 작업 진행에 대한 믿음이며 verifier 점수가 아닙니다. 마지막으로 갱신한 라운드를 함께 저장하고, NaN·무한대는 받지 않습니다."
        : "CognitiveState confidence is a progress belief, not a verifier score. It stores the round of its last update and rejects NaN and infinity.",
    },
  ];
  const jevResults = [
    { unit: "U4", name: ko ? "Score 통제 풀" : "Score, controlled pools", counts: "59/80 · 79/80", delta: "−25.00 pp [−35.23, −16.25]", reading: ko ? "기준 미달" : "Fails its criterion" },
    { unit: "X2", name: ko ? "Mind2Web 후보 선택" : "Mind2Web selection", counts: "196/240 · 226/240", delta: "−12.50 pp [−17.22, −8.04]", reading: ko ? "비열등성 미입증" : "Non-inferiority not shown" },
    { unit: ko ? "의도·대상" : "Intent/target", name: ko ? "설계자가 만든 패널" : "Designer-authored panel", counts: "216/220 · 220/220", delta: ko ? "−5 pp 기준 안" : "Within −5 pp margin", reading: ko ? "기준 충족" : "Meets its margin" },
    { unit: "E7", name: ko ? "같은 12과제, A/B/C × 2회" : "Same 12 tasks, A/B/C × 2", counts: ko ? "72/72 strict" : "72/72 strict", delta: ko ? "C의 judge fallback 0회" : "Zero C judge fallbacks", reading: ko ? "재검토 분기의 효용은 미확인" : "Escalation benefit untested" },
    { unit: "E8", name: ko ? "U8n 주입 후속" : "U8n injection follow-up", counts: ko ? "36셀 중 24셀에서 중단" : "Stopped at 24 of 36 cells", delta: ko ? "주지표 not-measurable" : "Primary not-measurable", reading: ko ? "아래 사후 분석 참고" : "See post-hoc note below" },
  ];

  return (
    <>
      <p>
        {ko
          ? "에이전트의 완료 선언, 과제 테스트 통과, judge의 좋은 평가는 각각 다른 것을 관측합니다. 이 페이지는 GEODE에서 누가 무엇을 근거로 판정하는지, 그 결과를 어디까지 믿을 수 있는지 정리합니다."
          : "An agent declaring completion, a task passing its tests and a judge rating behavior well are three different observations. This page lists who judges what in GEODE, on which evidence, and how far each result can be trusted."}
      </p>

      <h2>{ko ? "누가 무엇을 판정하나" : "Who judges what"}</h2>
      <table>
        <caption>{ko ? "같은 실행도 판정 주체마다 보는 증거와 권한이 다릅니다." : "The same execution reads differently to each authority."}</caption>
        <thead><tr><th scope="col">{ko ? "판정" : "Check"}</th><th scope="col">{ko ? "입력 증거" : "Evidence"}</th><th scope="col">{ko ? "결정과 범위" : "Decision and scope"}</th></tr></thead>
        <tbody>{authorities.map((row) => <tr key={row.name}><th scope="row">{row.name}</th><td>{row.evidence}</td><td>{row.decision}</td></tr>)}</tbody>
      </table>

      <h2>{ko ? "평가 한 번의 구성" : "Anatomy of an eval"}</h2>
      <ol>
        <li>{ko ? "실행 전에 질문, 과제, 모델·경로, 예산, 반복 수, 지표, 제외 규칙을 run-spec에 고정합니다." : "Freeze the question, tasks, model/route, budget, repetitions, metric and exclusion rule in the run spec."}</li>
        <li>{ko ? "시도마다 attempt와 native result를 남기고, trajectory로 행동 기록을 잇습니다." : "Keep every attempt and native result; trajectories link the behavioral record."}</li>
        <li>{ko ? "과제 verifier나 rubric 기반 judge가 점수를 냅니다. 둘 다 쓰면 결과를 따로 기록합니다." : "A task verifier or rubric-based judge scores the run. When both are used, their outputs stay separate."}</li>
        <li>{ko ? "분석은 고정된 선택 규칙으로 분자·분모와 불확실성을 계산하고, 승격은 별도 게이트가 정합니다." : "Analysis applies the frozen selection rule to counts and uncertainty; a separate gate decides promotion."}</li>
      </ol>
      <p>
        {ko
          ? "0에도 종류가 있습니다. 정상 실행 후 틀린 답은 reward 0이지만, 인프라 오류·미실행·누락 라벨은 0이 아닌 별도 상태로 남깁니다. 재시도와 제외는 원래 시도에 연결해 기록합니다."
          : "Not every zero is a failure. A valid wrong answer scores reward 0; infrastructure errors, unexecuted tasks and missing labels are recorded as separate states, and retries and exclusions stay linked to the original attempt."}
        {" "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/eval/data-model.md">{ko ? "평가 데이터 계약" : "Evaluation data contract"}</a>
      </p>

      <h2>{ko ? "런타임 턴 검증" : "Runtime turn verification"}</h2>
      <p>
        <code>core/agent/verify.py</code>{ko ? "의 " : "'s "}<code>llm_judge</code>
        {ko
          ? "가 기본 최종 검증 경로입니다. 코드가 먼저 빈 실행과 운영자 조치 필요 여부를 확인하고, 선택된 LLM 또는 Jev가 완료 근거를 판정합니다. 예전 off·rule_based·reflexion 설정은 경고와 함께 이 경로로 해석합니다. 이 판정은 Petri의 외부 감사 점수와 별개입니다."
          : " is the default final verification path. Code first checks for empty execution and required operator action; the selected LLM or Jev then judges the completion evidence. Legacy off, rule_based and reflexion settings resolve to this path with a warning. These judgments are separate from Petri audit scores."}
      </p>
      <p><small>{ko ? "Unreleased: 판정 엔진 선택과 매 라운드 Reflection은 소스 체크아웃 기준이며, 패키지 배포에는 아직 없습니다." : "Unreleased: engine selection and every-round Reflection describe the source checkout, not a packaged release."}</small></p>
      <table>
        <caption>{ko ? "런타임 판정의 동작 규칙" : "Runtime judgment rules"}</caption>
        <thead><tr><th scope="col">{ko ? "항목" : "Topic"}</th><th scope="col">{ko ? "동작" : "Behavior"}</th></tr></thead>
        <tbody>{runtime.map((row) => <tr key={row.topic}><th scope="row">{row.topic}</th><td>{row.rule}</td></tr>)}</tbody>
      </table>
      <p>
        {ko
          ? "Jev는 생성 모델 선택 목록에 없습니다. 전용 System One API가 텍스트 상태와 유한한 선택지를 받아 분류와 분포를 돌려주고, 이 분포는 confidence나 실행 허가로 쓰이지 않습니다. 이미지가 필요한 근거는 텍스트만으로 통과시키지 않고, 실패한 호출은 다른 엔진의 결과로 메우지 않습니다."
          : "Jev is not an entry in the generative-model picker. Its dedicated System One API takes prepared text state and finite choices and returns a classification with a distribution, which never becomes confidence or execution permission. Evidence that requires images cannot pass a text-only review, and a failed call is not replaced by another engine's result."}
        {" "}<a href="https://docs.typesafe.ai/api">TypeSafe System One</a>{" · "}<a href="https://openrouter.ai/docs/guides/community/typesafe-sdk">OpenRouter System One</a>{" · "}<a href={docsHref("config/reference")}>{ko ? "설정 규약" : "Configuration contract"}</a>
      </p>
      <h3>{ko ? "알려진 한계" : "Known limits"}</h3>
      <ul>
        <li>{ko ? "judge는 후보의 주장보다 근거를 먼저 보고, 풀리지 않는 모호함에는 재검사를 요청하도록 설정돼 있습니다. 그렇다고 오판이 없어지지는 않습니다." : "The judge reads evidence before the candidate's claim and requests a distinguishing check for unresolved ambiguity. That does not eliminate false verdicts."}</li>
        <li>{ko ? "Reflexion은 verdict와 continuation을 기록하지만, 다음 요청이 힌트를 실제로 소비했는지 묶는 digest·event는 아직 없습니다. 성능 개선 효과도 측정되지 않았습니다." : "Reflexion records verdicts and continuations, but nothing yet binds hint consumption in the next request with a digest or event, and no performance benefit has been measured."}</li>
        <li>
          {ko
            ? "2026-09-13 G-code 개발 검증에서 최종 후보의 신규 5회는 모두 공식 verifier를 통과했지만, 내부 judge가 첫 후보를 모두 수락해 수정은 한 번도 일어나지 않았습니다. 앞선 후보의 오수락 사례와 함께 읽어야 합니다."
            : "In the September 13, 2026 G-code development gate, all five fresh trials of the final revision passed the official verifier, but the internal judge accepted every first candidate, so no repair occurred. Read it with the earlier false acceptances."}
          {" "}<a href={`${docsHref("benchmarks/terminal-bench")}#gcode-development-gate`}>{ko ? "G-code 개발 검증 기록" : "G-code development evidence"}</a>
          {" · "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/core/agent/verify.py">{ko ? "턴 검증 구현" : "Turn-verification implementation"}</a>
        </li>
      </ul>
      <details>
        <summary>{ko ? "Judge를 믿기 전에 확인할 것" : "Before trusting a judge"}</summary>
        <ul>
          <li>{ko ? "judge 모델·버전·경로, rubric 원본, 점수 방향, seed, transcript 범위를 고정합니다. 높은 점수가 좋은지는 차원마다 다릅니다." : "Pin the judge model/version/route, rubric, score direction, seeds and transcript scope. Whether higher is better differs by dimension."}</li>
          <li>{ko ? "같은 공급자의 모델을 역할만 나눠 쓰면 독립 평가가 아닙니다. 경고나 보정 계수가 있다고 편향이 사라지지도 않습니다." : "Splitting roles across one provider's models is not independent evaluation, and a warning or correction factor does not remove bias."}</li>
          <li>{ko ? "사람이 judge 점수를 보기 전에 같은 rubric으로 라벨을 달고, 불일치 사례와 차원별 표본 수를 함께 봅니다." : "Have humans label with the same rubric before seeing judge scores, then review disagreements and per-dimension sample counts."}</li>
          <li>{ko ? "audit-agreement 경로로 blind labeling, weighted Cohen’s kappa, ordinal Krippendorff’s alpha를 계산할 수 있습니다. 도구가 있다는 것과 실제 라벨로 신뢰도를 보였다는 것은 다른 일입니다." : "The audit-agreement path computes blind labeling, weighted Cohen's kappa and ordinal Krippendorff's alpha. Having the tool is not the same as showing reliability on real labels."}</li>
        </ul>
        <pre>{`geode-eval audit-agreement --help`}</pre>
        <p><a href={docsHref("petri/judge-dimensions")}>{ko ? "Judge 차원과 해석" : "Judge dimensions and interpretation"}</a>{" · "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/core/audit/judge_agreement.py">{ko ? "사람-judge 일치도 구현" : "Human–judge agreement implementation"}</a></p>
      </details>

      <h2 id="jev-v3-study">{ko ? "Jev v3 본실험" : "Jev v3 study"}</h2>
      <p>{ko
        ? "2026-09-27 본실험은 판정 정확도, 확률과 오류 선별, 호출 지연, 실제 과제 완료를 27개 등록 단위로 나눠 측정했습니다. 앞선 M4–M6 파일럿과는 분모를 합치지 않습니다. 자료는 geode-eval-artifacts PR #46으로 공개했고(2026-09-28 원격 재확인), 아래 링크는 공개 커밋 3bcf4044eb5c2411dd48122d672aef72a83fb30e에 고정돼 있습니다."
        : "The September 27, 2026 study measured judgment accuracy, probability and error ranking, call latency and actual task completion across 27 registered units, without pooling the earlier M4–M6 pilot. The packet was published through geode-eval-artifacts PR #46 (remote read-back on September 28, 2026); the links below are pinned to public commit 3bcf4044eb5c2411dd48122d672aef72a83fb30e."}</p>
      <table>
        <caption>{ko ? "주요 결과. 앞 수치가 Jev, 뒤 수치가 Astra이고 구간은 95% CI입니다." : "Key results. Counts read Jev · Astra; intervals are 95% CIs."}</caption>
        <thead><tr><th scope="col">{ko ? "단위" : "Unit"}</th><th scope="col">{ko ? "대상" : "Scope"}</th><th scope="col">{ko ? "결과" : "Counts"}</th><th scope="col">{ko ? "차이" : "Difference"}</th><th scope="col">{ko ? "해석" : "Reading"}</th></tr></thead>
        <tbody>{jevResults.map((row) => <tr key={row.unit}><th scope="row">{row.unit}</th><td>{row.name}</td><td>{row.counts}</td><td>{row.delta}</td><td>{row.reading}</td></tr>)}</tbody>
      </table>
      <ul>
        <li>{ko ? "U4·X2는 저장된 응답 전체에 수치 파서 교정을 적용한 사후 재채점입니다. 새 모델 호출은 없고 정답·분모·군집·seed·재표집 규칙은 그대로이며, 원래 등록 결과는 따로 보존합니다." : "U4 and X2 are post-hoc rescoring after a numeric-parser correction across the retained responses. No new model calls; labels, denominators, clusters, seeds and resampling stay fixed, and the original preregistered results are kept separately."}</li>
        <li>{ko ? "E8: 원 계획(source5)의 U8n은 선행 gate 실패로 실행되지 않았습니다. 별도 후속(source7)은 U0e admission 2/2를 통과한 뒤 24셀에서 멈췄습니다(A 유효 성공 12, B 유효 전달 실패 11과 주입 증거 오류로 무효 1, 미실행 12)." : "E8: the original plan's U8n (source5) never ran after its prerequisite gate failed. A separate follow-up (source7) passed U0e admission 2/2, then stopped after 24 cells (A: 12 valid successes; B: 11 valid delivery failures and one injection-evidence invalid; 12 never started)."}</li>
        <li>{ko ? "E8 사후 분석(양쪽이 유효한 11쌍, 4개 원천, 두 arm 모두 Astra가 생성·수리): Astra 판정(A)은 11/11을 전달했습니다. Jev Noul 판정(B)은 마지막 후보가 과제 oracle을 11/11 통과했는데도 근거 부족으로 모두 보류해 native strict가 0/11입니다. 맞는 수리 후보를 거부한 셈입니다. 중단 뒤 고른 표본이라 구간이나 일반화는 제시하지 않고, U8n을 더 돌릴 계획은 없습니다." : "E8 post-hoc (11 complete valid pairs, four sources, Astra generating and repairing in both arms): Astra-judged A delivered 11/11. Jev-Noul-judged B held all 11 for missing evidence although its last candidates passed the task oracle 11/11, so its native strict result is 0/11: correct repairs were rejected. The sample was chosen after the stop, so no interval or generalization is reported, and no further U8n run is planned."}</li>
        <li>{ko ? "Noul의 이전 의미 실패, I5의 계약 전달 결함, E6의 무효 중단도 공개 자료에 계보째 남아 있습니다." : "Earlier Noul semantic failures, I5's contract-delivery defect and E6's invalid interruption remain in the packet with their lineage."}</li>
      </ul>
      <ul>
        <li><a href={`${jevV3Packet}/INTERPRETATION.ko.md`}>{ko ? "한국어 결과 해석" : "Korean interpretation"}</a>{" · "}<a href={`${jevV3Packet}/INTERPRETATION.md`}>{ko ? "영문 결과 해석" : "English interpretation"}</a></li>
        <li><a href={`${jevV3Packet}/SCORING.md`}>{ko ? "누가 무엇을 채점하는가" : "Scoring authorities and denominators"}</a>{" · "}<a href={`${jevV3Packet}/units.json`}>{ko ? "27개 단위와 계보별 근거" : "27-unit evidence and lineage index"}</a></li>
        <li><a href={`${jevV3Packet}/REPRODUCE.md`}>{ko ? "무결성 확인·오프라인 재계산·새 실행" : "Integrity checks, offline recomputation and new runs"}</a>{" · "}<a href={`${jevV3Packet}/corrections/numeric-parser-20260928/README.md`}>{ko ? "U4·X2 교정 재채점" : "U4/X2 corrected reanalysis"}</a></li>
        <li><a href={`${jevV3Packet}/analyses/u8n-observed-pairs-20260928/README.md`}>{ko ? "E8 U8n 사후 완성 쌍 분석" : "E8 U8n post-hoc complete-pair analysis"}</a></li>
        <li><a href="https://github.com/mangowhoiscloud/geode/blob/f0a5ce10cdb87e9738ff41e6e09dfbbfbb97a8f2/docs/eval/jev-v3-study-20260927.md">{ko ? "소스·공개 범위 기록" : "Source and disclosure record"}</a>{" · "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/eval/jev-verdict-publication-20260924.md">{ko ? "별도 M4–M6 파일럿" : "Separate M4–M6 pilot"}</a></li>
      </ul>
      <p>{ko
        ? "공개 자료는 투영본 해시와 원 native 해시를 따로 적고, 비공개 추론·인증 정보·머신 식별자·Mind2Web test 본문은 싣지 않았습니다. −10 pp 마진의 업무상 근거와 실제 청구액은 아직 확인되지 않았습니다."
        : "The packet lists projection digests separately from native digests and withholds private reasoning, credentials, machine identities and Mind2Web test text. The business rationale for the −10 pp margin and actual invoices remain unestablished."}</p>

      <h2>{ko ? ".eval 파일" : "The .eval file"}</h2>
      <p>
        {ko
          ? ".eval은 Inspect의 평가 로그 형식이고, Petri는 Inspect 위에서 돌아서 이 형식을 씁니다. 파일이 있거나 상태가 success여도 모든 답이 맞았다는 뜻은 아니니 설정·샘플·메시지·점수를 함께 읽습니다. Harbor 결과 JSON, .eval, GEODE trajectory는 원본대로 두고 실행 ID와 SHA-256으로 잇습니다. 새 judge 라벨은 파생 평가로 따로 남깁니다."
          : ".eval is Inspect's log format, which Petri uses because it runs on Inspect. A file existing, or a status of success, does not mean every answer was right, so read configuration, samples, messages and scores together. Harbor result JSON, .eval logs and GEODE trajectories stay native, joined by run identity and SHA-256. New judge labels are kept as derived evaluations."}
        {" "}<a href="https://inspect.aisi.org.uk/eval-logs.html">{ko ? "Inspect 로그 계약" : "Inspect log contract"}</a>
      </p>

      <h2>{ko ? "Terminal-Bench 결과 읽기" : "Reading the Terminal-Bench results"}</h2>
      <p>
        {ko
          ? "이 사이트의 Sol/max 비교는 과제 verifier와 고정된 결과 선택 규칙으로 계산했으며, Petri judge 점수가 아닙니다. transcript에 LLM judge를 더하려면 별도의 질문·rubric·예산으로 등록하고, 기존 통과율과 섞지 않습니다."
          : "The Sol/max comparison on this site comes from task verifiers and frozen outcome-selection rules, not Petri judge scores. Adding an LLM judge to those transcripts needs its own registered question, rubric and budget, and stays out of the original pass rate."}
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
