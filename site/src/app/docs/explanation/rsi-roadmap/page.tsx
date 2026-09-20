import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "RSI roadmap and current scope — GEODE Docs" };

const paper = "https://arxiv.org/abs/2609.11873v2";
const source = "https://github.com/mangowhoiscloud/geode/blob/f084075f6ce3f6b8deb1a320e788677fee9a8ae1";

function Roadmap({ ko }: { ko: boolean }) {
  const levels = [
    ["B0", ko ? "작업 내 수정" : "In-task refinement",
      ko ? "AgenticLoop의 도구 호출·결과 관찰과 Reflexion은 현재 작업의 완료를 돕습니다. 이것만으로 다음 작업의 시스템이 개선됐다고 판정하지 않습니다." : "Tool use, observations, and Reflexion help complete the current task. They alone do not establish a better system for later tasks.",
      ko ? "작업 성공과 영속적 변경을 별도 기록합니다." : "Record task success separately from a persistent update."],
    ["L1", ko ? "개선 실행" : "Improvement execution",
      ko ? "구현: 사람이 정한 변경 범위와 평가 규칙 안에서 후보를 실행·검증합니다. PR·CI와 실험의 후보 채택은 별도 경로입니다." : "Implemented: execute and check candidates within externally defined mutation and evaluation rules. PR/CI integration and experimental acceptance remain separate.",
      ko ? "채택된 revision을 다음 실행이 실제 읽었는지 연결합니다." : "Bind the accepted revision to the later run that actually consumes it."],
    ["L2", ko ? "개선 전략" : "Improvement strategy",
      ko ? "제한형 구현: scaffold mutator가 baseline·진단을 읽어 변경을 제안합니다. Crucible은 판정과 실패 피드백을 다음 producer에 전달하고 KEEP에서만 private search head를 전진시킵니다." : "Bounded implementation: the scaffold mutator proposes edits from baseline evidence and diagnosis. Crucible passes decisions and failure feedback to the next producer, advancing its private search head only on KEEP.",
      ko ? "동일 예산·고정 evaluator에서 고정 전략 대조군보다 더 나은 후보를 만드는지 측정합니다." : "Measure candidate quality against a fixed-strategy control under matched budgets and a fixed evaluator."],
    ["L3", ko ? "학습 경험 선택" : "Learning-experience acquisition",
      ko ? "구성요소: seed 생성과 task-pack admission이 있습니다. 시스템이 고른 새 경험이 다음 개선에 기여했다는 end-to-end 증거는 이 감사에서 확인하지 않았습니다." : "Components: seed generation and task-pack admission exist. This audit does not establish that system-selected new experience improves a subsequent round.",
      ko ? "경험 선택 정책과 held-out 과제를 분리하고 선택의 효과를 검증합니다." : "Separate experience selection from held-out tasks and test its contribution."],
    ["L4", ko ? "배포 환경 적응" : "Deployment adaptation",
      ko ? "관측 기반은 구현됐습니다. 운영 기록의 수집·복구를 운영 경험에 따른 자율적 정책 변경과 같은 뜻으로 쓰지 않습니다." : "Observation infrastructure exists. Collecting or recovering production records is not autonomous policy adaptation from deployment experience.",
      ko ? "운영 실패가 검토된 변경으로 이어지고, 이후 독립 작업에 적용되는 경로를 검증합니다." : "Verify how a production failure becomes a reviewed update used by later independent tasks."],
    ["L5", ko ? "개선 메커니즘의 계승" : "Recursive inheritance",
      ko ? "연구 목표: improver·verifier·선택 절차 자체의 변경이 후속 개선을 더 잘 만든다는 증거는 아직 제시하지 않습니다." : "Research target: no claim yet that changing the improver, verifier, or selection procedure produces stronger subsequent improvements.",
      ko ? "변경된 메커니즘의 재사용과 독립 평가 성능을 함께 입증합니다." : "Demonstrate both reuse of the revised mechanism and gains on independent evaluation."],
  ];
  const terms = [
    ["System state / successor", ko ? "채택된 코드·scaffold revision과 이를 이어받는 다음 실행입니다. 세션 기록의 보존만으로 successor 개선을 주장하지 않습니다." : "An accepted code/scaffold revision and the next run inheriting it. Stored session history alone is not evidence of a stronger successor."],
    ["Experience", ko ? "다음 변경의 입력으로 사용된 실패 결과·trajectory·review입니다. 저장만 한 로그와 실제 읽힌 피드백을 구분합니다." : "Failure results, trajectories, and reviews consumed by a later modification. Stored logs and consumed feedback are distinct."],
    ["Target / improver / strategy", ko ? "Target은 수정 대상, improver는 후보 생성자, strategy는 탐색 방법입니다. core는 실행 대상, evals는 측정, evolve는 후보 탐색을 담당합니다." : "Target names the edited object, improver the candidate producer, and strategy the search method. core executes, evals measures, and evolve searches candidates."],
    ["Verifier / acceptance rule", ko ? "Benchmark verifier는 과제 결과를 판정합니다. Crucible decide()는 증거와 채택 규칙으로 후보를 판정합니다. 런타임 self-judge와 CI는 각각 다른 범위를 검사합니다." : "A benchmark verifier judges task outcomes. Crucible decide() applies candidate acceptance rules to evidence. The runtime self-judge and CI check different scopes."],
    ["Improvement / promotion", ko ? "후보가 채택되어 다음 상태에 반영된 경우에 improvement라고 씁니다. KEEP은 실험 내부의 채택이며 main 병합·릴리즈 승인이 아닙니다." : "Use improvement for an accepted candidate inherited by the next state. KEEP is experimental acceptance, not approval to merge main or release."],
    ["Self-hosting / RSI", ko ? "Self-hosting은 자기 저장소 개발에 도구를 사용하는 방식입니다. RSI는 개선 메커니즘까지 변경·계승하는지를 따지는 별도 주장입니다." : "Self-hosting concerns using the tool to develop its own repository. RSI is a separate claim about changing and inheriting improvement mechanisms."],
    ["Ratchet", ko ? "명시된 불변조건과 채택 기준을 지키는 회귀 방지 게이트입니다. 모든 실제 과제의 성능이 항상 오른다는 보장은 아닙니다." : "A regression gate over declared invariants and acceptance criteria, not a guarantee that performance always rises on every real task."],
  ];
  const href = (path: string) => `/geode/docs/${path}${ko ? "" : "?lang=en"}`;

  return (
    <>
      <p>
        {ko
          ? "현재 GEODE는 개선 실행의 검증 경계와 제한형 후보 탐색을 구현했습니다. 다음 목표는 변경을 많이 만드는 것이 아니라, 채택된 변경이 후속 작업과 다음 개선에 실제로 기여했는지 입증하는 것입니다."
          : "GEODE implements controlled improvement execution and bounded candidate search. The next goal is not more edits: it is evidence that accepted changes improve later tasks and later improvement rounds."}
      </p>
      <p>
        {ko ? "기준 문헌: " : "Reference: "}<a href={paper}>Duan et al., The Last AI Built by Humans: Toward Genuine Recursive Self-Improvement</a>
        {ko
          ? " (arXiv:2609.11873v2, 2026-09-15). §1.4·Figure 2와 §2.2·§3의 구분을 설계 가이드로 사용합니다. 2026-09-21의 코드 감사에 따른 프로젝트 자체 해석이며, 논문 저자의 GEODE 평가나 공식 인증이 아닙니다."
          : " (arXiv:2609.11873v2, 2026-09-15). We use §1.4/Figure 2 and §2.2/§3 as a design guide. This is our interpretation of a 2026-09-21 source audit, not an assessment or certification of GEODE by the authors."}
      </p>

      <h2 id="autonomy-roadmap">{ko ? "로드맵: 실행에서 개선 방법의 계승까지" : "Roadmap: from execution to inherited improvement methods"}</h2>
      <p>{ko ? "단계는 개발 완료율이 아니라 AI가 맡는 개선 결정의 범위입니다. 아래의 ‘구현’은 코드 경로를 뜻하며, 자율성 단계 달성이나 성능 향상 실측을 뜻하지 않습니다." : "Levels describe responsibility for improvement, not a completion percentage. Implemented below means a code path exists; it does not certify an autonomy level or a measured gain."}</p>
      <table>
        <thead><tr><th>{ko ? "범위" : "Scope"}</th><th>{ko ? "현재 확인한 위치" : "Current evidence"}</th><th>{ko ? "다음 검증 조건" : "Next evidence needed"}</th></tr></thead>
        <tbody>{levels.map(([level, label, current, next]) => <tr key={level}><th scope="row">{level}<br />{label}</th><td>{current}</td><td>{next}</td></tr>)}</tbody>
      </table>

      <h2 id="terms">{ko ? "용어: 무엇을 바꾸고, 누가 채택하는가" : "Terms: what changes, and who accepts it"}</h2>
      <table>
        <thead><tr><th>{ko ? "표기" : "Term"}</th><th>{ko ? "GEODE에서의 사용 범위" : "Usage in GEODE"}</th></tr></thead>
        <tbody>{terms.map(([term, usage]) => <tr key={term}><th scope="row">{term}</th><td>{usage}</td></tr>)}</tbody>
      </table>
      <p>{ko ? "기존 CLI·설정·schema 이름은 호환성을 위해 유지합니다. self_improving_loop라는 설정 이름 자체가 RSI 달성의 근거가 되지는 않습니다." : "Existing CLI, configuration, and schema names remain compatible. A setting named self_improving_loop does not itself establish RSI."}</p>

      <h2 id="evidence">{ko ? "코드에서 확인되는 계승 경로" : "The inheritance path in code"}</h2>
      <ol>
        <li><a href={`${source}/evolve/scaffold_search/loop/mutate/runner.py`}>Scaffold mutator</a>{ko ? "가 baseline과 review를 후보 변경의 입력으로 읽습니다. apply 기록과 후속 평가의 채택 판정은 다릅니다." : " reads baseline and review evidence as proposal input. An apply record is distinct from subsequent acceptance."}</li>
        <li><a href={`${source}/evolve/crucible/search/supervisor.py`}>Crucible supervisor</a>{ko ? "는 record.json·feedback.json·ledger.jsonl을 남기고 다음 producer에 피드백을 전달합니다. KEEP만 search-ref receipt와 함께 private ref를 갱신합니다." : " writes record.json, feedback.json, and ledger.jsonl, then passes feedback to the next producer. Only KEEP advances the private ref with a search-ref receipt."}</li>
        <li><a href={`${source}/evolve/crucible/promotion.py`}>decide()</a>{ko ? "와 " : " and "}<a href={`${source}/evolve/crucible/attestation/sealed.py`}>sealed evaluation</a>{ko ? "은 고정된 실험 기준과 별도 test 경계를 검사합니다. decide() 판정은 promotion_authority=none, sealed 판정은 release_authority=none을 유지합니다. 어느 쪽도 릴리즈를 승인하지 않습니다." : " enforce experimental criteria and a separate test boundary. The decide() verdict retains promotion_authority=none; the sealed decision retains release_authority=none. Neither authorizes a release."}</li>
      </ol>
      <p>{ko ? "위 링크는 공개 main revision f084075에 고정했습니다. 이 문서 작업에서는 새로운 유료 실험을 실행하지 않았습니다. 측정 성능은 " : "Source links pin public main revision f084075. No new paid experiment was run for this documentation update. For measured performance, use "}<a href={href("benchmarks/terminal-bench")}>Terminal-Bench</a>{ko ? "와 각 실행의 동결 계약·공개 artifact를 확인해야 합니다. 통과율은 RSI 단계를 판정하는 지표가 아닙니다." : " and each run’s frozen contract and published artifacts. Pass rate is not an RSI-level metric."}</p>

      <h2 id="next">{ko ? "다음 실험에서 닫을 질문" : "Questions for the next experiment"}</h2>
      <ol>
        <li>{ko ? "후보의 변경 revision, 판정 receipt, 다음 실행의 입력 revision을 연결해 실제 계승을 확인합니다." : "Link candidate revision, decision receipt, and the next run’s input revision to establish actual inheritance."}</li>
        <li>{ko ? "과제·모델·effort·예산·verifier를 고정하고 고정 전략 대조군과 진단 기반 후보 생성을 비교합니다. 모든 실패·비용을 포함합니다." : "Hold tasks, model, effort, budget, and verifier fixed; compare diagnosis-led candidate generation with a fixed-strategy control, retaining every failure and cost."}</li>
        <li>{ko ? "탐색에 사용하지 않은 과제에서 이득과 회귀를 검사한 뒤 주장 범위를 넓힙니다. evaluator를 바꾸면 별도 epoch로 다룹니다." : "Check gains and regressions on tasks withheld from search before expanding the claim. Treat evaluator changes as a separate epoch."}</li>
      </ol>
      <p>{ko ? "이 문서는 연구 방향과 용어의 기준입니다. 구현 순서·GAP 상태는 저장소의 " : "This page defines research direction and terminology. Implementation order and GAP status remain in the repository’s "}<a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/architecture/extensibility-roadmap.md">extensibility roadmap</a>{ko ? "에서 관리합니다." : "."}</p>

      <h2 id="eco2">{ko ? "Eco²와 같은 기준으로 읽기" : "Read Eco² with the same criteria"}</h2>
      <p>{ko ? "Eco²의 답변 재생성은 작업 내 수정이며, 운영 로그·GitOps·개발 에이전트의 지식 보존은 별도 계층입니다. 이를 자율적인 개선 전략이나 recursive inheritance로 합쳐 부르지 않습니다. Eco²의 eval L1/L2/L3, 인프라 layer, 이 문서의 RSI L1–L5도 서로 다른 축입니다." : "Eco² answer regeneration is task-local refinement. Operational logs, GitOps, and retained developer-agent knowledge are separate layers, not one autonomous improvement strategy. Its eval L1/L2/L3, infrastructure layers, and RSI L1–L5 describe different axes."}</p>
      <p><a href="https://mangowhoiscloud.github.io/eco2/#rsi-roadmap">{ko ? "Eco²의 현재 위치와 로드맵" : "Eco² current scope and roadmap"}</a>{" · "}<a href={href("capabilities/outer-loop")}>{ko ? "Crucible 실행 경계" : "Crucible execution boundaries"}</a></p>
    </>
  );
}

export default function Page() {
  return (
    <DocsShell
      wide
      slug="explanation/rsi-roadmap"
      title="RSI roadmap and current scope"
      titleKo="RSI 로드맵과 현재 구현 범위"
      summary="A source-bound reading of the RSI autonomy roadmap: implemented mechanisms, inherited state, external authority, and the next evidence needed."
      summaryKo="RSI 자율성 로드맵을 코드와 대조합니다. 구현된 메커니즘, 계승되는 상태, 외부 권한과 다음 검증 조건을 구분합니다."
    >
      <Bi ko={<Roadmap ko />} en={<Roadmap ko={false} />} />
    </DocsShell>
  );
}
