"use client";

import Link from "next/link";
import { DocsShell } from "@/components/geode-docs/docs-shell";
import { LoopMap } from "@/components/geode/loop-map";
import { t, useLocale } from "@/components/geode/locale-context";

const source = "https://github.com/mangowhoiscloud/geode/blob/1933aef1355a8678dc2a1f730eb2ecadf900d6b4";
const campaign = "https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/23e3428fc69af1577ab0545be707e37489b5e126/crucible/runs/campaigns";

export default function ResearchOverview() {
  const locale = useLocale();
  const ko = locale === "ko";
  const doc = (slug: string) => `/docs/${slug}?lang=${locale}`;
  return (
    <DocsShell slug="research/overview" title="Harness, experiments, and evidence" titleKo="하네스, 실험, 그리고 근거"
      summary="What GEODE runs, what it searches, and what the evidence can establish."
      summaryKo="GEODE가 실행하는 것과 탐색하는 것, 실제 근거로 확인할 수 있는 범위를 구분합니다.">
      <p>{t(locale,
        "GEODE의 본체는 자율 수행 에이전트 하네스입니다. 모델이 도구 관측을 읽고 다음 행동을 선택하며, 실행 예산과 승인 정책, 종료 경로가 작업을 통제합니다. self-hosted는 이 하네스를 운영하는 방식입니다.",
        "GEODE is an Autonomous Agent Harness. The model reads tool observations and chooses its next action; budgets, approval policies, and termination paths govern execution. Self-hosted describes how this harness is operated.")}</p>
      <p>{t(locale,
        "그 바깥의 Experimental Loop에서는 실행 정책 후보와 평가 시나리오, 판정 방법을 연구합니다. 일반 작업마다 자동으로 자기개선이 실행된다는 뜻은 아닙니다. 아래에서는 구현된 경로, 실험에서 관측된 결과, 아직 입증하지 못한 효과를 구분합니다.",
        "The outer Experimental Loop studies candidate execution policies, evaluation scenarios, and judgment methods. It does not imply automatic self-improvement on every task. The sections below distinguish implemented paths, experimental observations, and effects that remain unproven.")}</p>
      <LoopMap locale={locale} />
      <nav className="research-contents" aria-label={ko ? "연구 질문" : "Research questions"}>
        <a href="#scaffold">Scaffold Search</a><a href="#seeds">Seed Scenario Generation</a><a href="#sil">SIL</a><a href="#jev">Jev</a><a href="#related-work">{ko ? "SelfSearch·DGM" : "SelfSearch and DGM"}</a>
      </nav>

      <section id="scaffold" className="research-study">
        <p className="research-state">{ko ? "구현 + 제한된 판정 기록" : "Implementation + bounded decision records"}</p>
        <h2>Scaffold Search</h2>
        <p className="research-question">{t(locale, "모델 가중치를 바꾸지 않고, 작업을 수행하는 정책을 바꿀 수 있을까?", "Can execution policies change without updating model weights?")}</p>
        <h3>{ko ? "설계" : "Design"}</h3>
        <p>{t(locale, "프롬프트·행동 정책 후보를 변형하고 Petri 감사와 게이트를 통해 로컬 baseline의 채택 또는 복원을 결정합니다. 별도 Crucible 경로는 동결된 계약, paired 평가, private 탐색 ref, 독립된 sealed 평가를 분리합니다. 평가 신호와 채택 규칙은 각 경로의 계약에 따릅니다.", "Prompt and behavior-policy candidates are mutated, then Petri audits and gates decide local baseline acceptance or reversion. The separate Crucible path uses frozen contracts, paired evaluation, a private search ref, and independent sealed evaluation. Each path owns its evaluation signal and acceptance rules.")}</p>
        <h3>{ko ? "관측: 채택과 검증은 다른 판정" : "Observation: selection and validation are different decisions"}</h3>
        <ol className="research-verdict-flow" aria-label={ko ? "r14의 보존된 판정 순서" : "Preserved r14 decision sequence"}>
          <li><strong>Train: KEEP</strong><span>{ko ? "탐색 후보 채택" : "Candidate accepted in search"}</span></li>
          <li><strong>Sealed: REJECT</strong><span>{ko ? "독립 검증에서 거절" : "Rejected by sealed evaluation"}</span></li>
          <li><strong>Release: none</strong><span>{ko ? "배포 권한 없음" : "No release authority"}</span></li>
        </ol>
        <p>{t(locale, "r14에는 train KEEP 1건과 sealed REJECT가 보존되어 있습니다. r35는 coverage·인프라 결함으로 INVALID이며 평균은 null, paired rows는 0이고 탐색 head는 유지됩니다. 무효 측정을 성능 0으로 바꾸지 않습니다.", "r14 preserves one train KEEP and a sealed REJECT. r35 is INVALID because of coverage and infrastructure defects: means are null, paired rows are zero, and the search head is unchanged. Invalid measurement is not a performance score of zero.")}</p>
        <p className="research-limit"><strong>{ko ? "근거의 한계. " : "Evidence limits. "}</strong>{t(locale, "r14는 6 tasks × 1 trial, 88.5% bootstrap 및 이전 입력·후보 재사용 조건의 기록입니다. 공개 config의 재계산 해시와 prereg train_config 해시가 일치하지 않으며 원인은 미확정입니다. 보존된 판정의 사례로 제시하며, 전체 증거 사슬의 무결성 재인증이나 재현된 성능 개선을 뜻하지 않습니다.", "r14 used 6 tasks × 1 trial, an 88.5% bootstrap setting, and reused prior inputs/candidates. The recomputed public config hash differs from the preregistered train_config hash; the cause is unresolved. These are preserved decision records, not a recertification of the full evidence chain or a reproduced performance improvement.")}</p>
        <ul className="research-sources">
          <li><Link href={doc("capabilities/autoresearch")}>{ko ? "Scaffold Search 설계" : "Scaffold Search design"}</Link>{" / "}<Link href={doc("capabilities/outer-loop")}>{ko ? "Crucible 계약" : "Crucible contract"}</Link></li>
          <li><a href={`${campaign}/tau2-telecom-gpt54-train-20260711-r14/state/attempts/0001-f6263c713f19/verdict.json`}>r14 train verdict</a>{" / "}<a href={`${campaign}/tau2-telecom-gpt54-train-20260711-r14/sealed-state/decision.json`}>r14 sealed decision</a></li>
          <li><a href={`${campaign}/tau2-telecom-gpt54-train-20260711-r14/config.json`}>r14 public config</a>{" / "}<a href={`${campaign}/tau2-telecom-gpt54-train-20260711-r14/sealed-preregistration.json`}>r14 preregistration</a></li>
          <li><a href={`${campaign}/tau2-telecom-gpt54-train-20260713-r35/state/attempts/0001-5bf6ea7a7361/verdict.json`}>r35 INVALID verdict</a>{" / "}<a href={`${campaign}/tau2-telecom-gpt54-train-20260713-r35/state/summary.json`}>r35 summary</a></li>
        </ul>
      </section>

      <section id="seeds" className="research-study">
        <p className="research-state">{ko ? "구현 + 생성 산출물" : "Implementation + generated artifacts"}</p>
        <h2>Seed Scenario Generation</h2>
        <p className="research-question">{t(locale, "기존 평가가 놓치는 행동을 어떻게 시험할까?", "How can we test behavior that existing evaluations miss?")}</p>
        <h3>{ko ? "설계" : "Design"}</h3>
        <p>{t(locale, "후보 생성 → 비평 → pilot → 순위·생존자 선택 → 다음 세대의 흐름으로 평가 입력을 탐색합니다. seed는 에이전트를 시험하는 시나리오이며, scaffold 변경과는 다른 산출물입니다.", "Search evaluation inputs through generation, critique, pilots, ranking and survivor selection, then the next generation. A seed is a scenario used to test an agent; it is a different artifact from a scaffold change.")}</p>
        <h3>{ko ? "관측과 한계" : "Observations and limits"}</h3>
        <p>{t(locale, "공개 Seed 생성 런에서 후보, 생존자, 토큰, meta-review와 다음 세대 prior를 확인할 수 있습니다. 대시보드의 정상·부분 상태는 산출물의 존재를 설명합니다. seed 생성이 에이전트 성능을 높였다는 실험 판정은 아닙니다.", "The published seed runs expose candidates, survivors, tokens, meta-review, and next-generation priors. Complete/partial dashboard states describe available artifacts. They are not experimental verdicts that seed generation improved agent performance.")}</p>
        <ul className="research-sources">
          <li><Link href={doc("capabilities/co-scientist")}>{ko ? "생성 루프 설계" : "Generation-loop design"}</Link>{" / "}<Link href={doc("capabilities/seed-pipeline")}>{ko ? "Seed 파이프라인" : "Seed pipeline"}</Link></li>
          <li><Link href={`${doc("petri/seeds")}#run-frontier-2612-bt-broken_tool_use`}>{ko ? "도구 오용 시나리오의 생성 기록" : "A tool-use scenario generation record"}</Link></li>
          <li><a href={`${source}/evals/seed_generation/orchestrator.py`}>{ko ? "구현: phase 실행과 재개" : "Source: phase execution and resume"}</a></li>
        </ul>
      </section>

      <section id="sil" className="research-study">
        <p className="research-state">{ko ? "연결 경로 구현 / 개선 효과 미검증" : "Integration implemented / improvement unproven"}</p>
        <h2>SIL · Self-Improving Loop</h2>
        <p className="research-question">{t(locale, "실행에서 발견한 실패를 다음 scaffold 후보에 연결할 수 있을까?", "Can an observed failure inform the next scaffold candidate?")}</p>
        <h3>{ko ? "설계" : "Design"}</h3>
        <p>{t(locale, "SIL은 Scaffold Search를 연결하는 구현 흐름입니다. SelfImprovingLoopRunner는 제안과 적용을 분리하고, 허용된 변경 표면과 검증·복원 경로를 갖습니다. 재측정은 명시적 opt-in이므로 일반 실행이 곧 자동 탐색은 아닙니다. SIL의 선택적 held-out 측정은 실패해도 주기 판정을 중단하지 않는 관측 경로이며, Crucible의 sealed 검증과 다릅니다.", "SIL is an implementation flow connecting Scaffold Search. SelfImprovingLoopRunner separates proposal from application, with allowed mutation surfaces and validation/reversion paths. Remeasurement is an explicit opt-in; an ordinary run is not automatic search. Optional SIL held-out measurement is observational and its failure does not stop the primary cycle decision; it is distinct from Crucible sealed validation.")}</p>
        <h3>{ko ? "관측과 한계" : "Observations and limits"}</h3>
        <p>{t(locale, "현재 공개 results.jsonl은 session_id만 있는 3행입니다. 이 기록으로 변이 수, 승격 수, 지속적 개선을 재계산할 수 없습니다. 코드로 확인한 연결 경로와 실행으로 입증한 개선 효과를 구분합니다.", "The current public results.jsonl contains three session_id-only rows. It cannot establish mutation counts, promotion counts, or sustained improvement. An implemented integration path and an empirically demonstrated improvement are different claims.")}</p>
        <ul className="research-sources">
          <li><a href={`${source}/evolve/scaffold_search/loop/mutate/runner.py`}>SelfImprovingLoopRunner</a>{" / "}<a href={`${source}/evolve/scaffold_search/gate.py`}>{ko ? "채택·복원 게이트" : "Acceptance and reversion gate"}</a></li>
          <li><a href={`${source}/evolve/scaffold_search/train.py#L1054`}>{ko ? "SIL held-out 관측 경계" : "SIL held-out observation boundary"}</a></li>
          <li><a href={`${source}/evolve/scaffold_search/state/results.jsonl`}>{ko ? "공개 세션 ledger" : "Published session ledger"}</a></li>
          <li><Link href={doc("explanation/rsi-roadmap")}>{ko ? "다음 검증 과제" : "Next verification questions"}</Link></li>
        </ul>
      </section>

      <section id="jev" className="research-study">
        <p className="research-state">{ko ? "실험 결과 공개 / 과제별 한계" : "Published study / task-specific limits"}</p>
        <h2>Jev · System 1 offloading</h2>
        <p className="research-question">{t(locale, "작은 판정기에 어떤 결정을 맡길 수 있을까?", "Which decisions can be offloaded to a small judge?")}</p>
        <h3>{ko ? "설계" : "Design"}</h3>
        <p>{t(locale, "Jev 연구는 유한 선택지의 판단을 분리해 판정 정확도, 오류 선별, 호출 지연, 실제 과제 완료를 측정했습니다. 생성 모델의 결과, 내부 완료 판정, 외부 과제 verifier는 서로 다른 권한입니다.", "The Jev study isolates finite-choice judgments to measure accuracy, error selection, call latency, and actual task completion. Generation, internal completion judgment, and external task verification have different authorities.")}</p>
        <h3>{ko ? "관측: 맞는 후보를 보류한 경우" : "Observation: correct candidates held back"}</h3>
        <p>{t(locale, "E8 사후 분석의 4개 원천·완성된 11쌍에서, Jev Noul 판정 arm의 최종 후보는 과제 oracle을 11/11 통과했지만 근거 부족으로 모두 보류되어 native strict 전달은 0/11이었습니다. 두 arm의 생성·수리는 Astra가 수행했습니다. 판정의 속도나 후보의 정답만으로 실제 전달 성공을 대신할 수 없습니다.", "In the E8 post-hoc analysis of 11 complete pairs from four sources, final candidates in the Jev Noul arm passed the task oracle 11/11, but all were held for insufficient evidence: native strict delivery was 0/11. Astra generated and repaired in both arms. Judge speed and candidate correctness do not establish successful delivery.")}</p>
        <p className="research-limit"><strong>{ko ? "해석의 한계. " : "Interpretation limits. "}</strong>{t(locale, "중단 뒤 선택한 표본에 대한 관측입니다. 일반화, 신뢰구간, 인과적 우열 주장을 붙이지 않습니다. v3 본실험과 이전 M4–M6 파일럿의 분모도 합치지 않습니다.", "This is an observation on a sample selected after the stop. It carries no generalization, confidence interval, or causal superiority claim. The v3 study and earlier M4–M6 pilots also retain separate denominators.")}</p>
        <ul className="research-sources">
          <li><Link href={`${doc("verification/evaluation")}#jev-v3-study`}>{ko ? "v3 결과·판정 기준·공개 근거" : "v3 results, judgment criteria, and evidence"}</Link></li>
          <li><a href={`/geode/resaerch/jev-system1-offloading/?lang=${locale}`}>{ko ? "Jev 연구 리더와 한국어 PDF" : "Jev research reader and English PDF"}</a></li>
          <li><a href="https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/3bcf4044eb5c2411dd48122d672aef72a83fb30e/reports/e2e-validation/jev-v3-20260927/analyses/u8n-observed-pairs-20260928/README.md">E8 {ko ? "관측 해석" : "observed-pair analysis"}</a></li>
        </ul>
      </section>

      <section id="related-work" className="research-study">
        <h2>{ko ? "Self-search의 연구 좌표" : "Positioning self-search"}</h2>
        <p>{t(locale, "여기서 self-search는 에이전트 주변 구현을 탐색하는 연구 방향입니다. 고유 방법명 SelfSearch와 동일시하지 않습니다. 아래 논문은 방법의 차이를 읽기 위한 비교 대상이며 GEODE의 기존 실험을 재현으로 소급하지 않습니다.", "Here, self-search describes research into searching agent implementations. It is not a claim to implement the method named SelfSearch. These papers provide a methodological comparison; GEODE's earlier experiments are not retrospectively labeled reproductions.")}</p>
        <div className="research-comparison">
          <article><h3>GEODE</h3><p>{t(locale, "가중치를 바꾸지 않는 scaffold·정책 탐색. Petri 감사 또는 benchmark/proxy 피드백과 명시된 게이트가 선택에 관여합니다. 탐색 채택과 sealed 판정, 릴리즈 권한을 분리합니다.", "Scaffold/policy search with fixed weights. Petri audits or benchmark/proxy feedback and explicit gates guide selection. Search acceptance, sealed verdicts, and release authority remain separate.")}</p></article>
          <article><h3><a href="https://arxiv.org/html/2609.37968v2">SelfSearch</a></h3><p>{t(locale, "Yang·Kong·Jo, SNU, v2 (2026-09-30). 고정 모델로 자기수정 episode 기록을 활용하며 검색 중 downstream 과제나 reward를 쓰지 않습니다. downstream 평가와 선택은 검색 밖에서 수행합니다. GEODE에 직접 영향을 주었다거나 같은 방법을 구현했다는 주장은 아닙니다.", "Yang, Kong, and Jo, SNU, v2 (2026-09-30). Uses self-modification episode records with fixed models, without downstream tasks or rewards during search. Downstream evaluation and selection occur outside search. This is not a claim of direct influence on GEODE or method equivalence.")}</p></article>
          <article><h3><a href="https://arxiv.org/abs/2505.22954">Darwin Gödel Machine</a></h3><p>{t(locale, "코딩 에이전트의 구현을 수정하고 코딩 평가로 변화를 측정하는 탐색 계보입니다. GEODE의 로컬 후보 선택이나 SelfSearch의 reward-free 검색과 실험 조건·방법이 같다는 뜻은 아닙니다.", "A lineage of searching coding-agent implementations and empirically evaluating modifications on coding tasks. Its method and experimental conditions are not interchangeable with GEODE's local candidate selection or SelfSearch's reward-free search.")}</p></article>
        </div>
      </section>
    </DocsShell>
  );
}
