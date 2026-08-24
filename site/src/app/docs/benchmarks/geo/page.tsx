import { Bi, DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "GEO visibility — GEODE Docs" };

const measureCommand = `uv run python scripts/eval/geo_visibility.py \\
  --run-spec <run-dir>/run-spec.json \\
  --workload <run-dir>/workload.json \\
  --native-results <run-dir>/native-results.json \\
  --verifier-results <run-dir>/verifier-results.json \\
  --outcome <run-dir>/outcome.json \\
  --out <run-dir>/geo-vector.json`;

const verifyCommand = `uv run python scripts/eval/geo_verify.py \\
  --workload <run-dir>/workload.json \\
  --native-results <run-dir>/native-results.json \\
  --rubric <run-dir>/verifier-rubric.json \\
  --adapter <verifier-adapter> \\
  --model <verifier-model> \\
  --effort medium \\
  --claim-adapter <claim-extractor-adapter> \\
  --claim-model <claim-extractor-model> \\
  --claim-effort low \\
  --producer-version <version-or-revision> \\
  --out <run-dir>/verifier-results.json`;

const collectCommand = `uv run python scripts/eval/geo_collect.py \\
  --run-spec <run-dir>/run-spec.json \\
  --workload <run-dir>/workload.json \\
  --site-preflight <run-dir>/site-preflight.json \\
  --link-audit <run-dir>/link-audit.json \\
  --host-preflight <run-dir>/host-preflight.json \\
  --out <run-dir>/native-results.json`;

const bundleCommand = `uv run python scripts/eval/contract.py validate-run-bundle \\
  <run-dir>/run-spec.json`;

function VectorTable({ ko }: { ko: boolean }) {
  const rows = [
    ["F", ko ? "각 preflight 조건을 통과한 URL" : "URLs passing each preflight check", ko ? "감사 대상 URL" : "audited target URLs"],
    ["R", ko ? "target URL이 retrieval 목록에 나온 실행" : "runs whose retrieval list contains a target URL", ko ? "retrieval 목록을 노출한 24×K 실행" : "24×K runs exposing a retrieval list"],
    ["C", ko ? "target URL을 인용한 실행" : "runs citing a target URL", ko ? "전체 24×K 질의 실행" : "all 24×K query runs"],
    ["P", ko ? "target 인용의 visible_rank가 3 이하인 실행" : "target-cited runs with visible_rank ≤ 3", ko ? "target URL을 인용한 실행" : "target-cited runs"],
    ["A", ko ? "verifier가 target 내용 사용을 확인한 실행" : "runs where a verifier confirms target use", ko ? "A 판정이 있는 target 인용 실행" : "target-cited runs with an A verdict"],
    ["Q", ko ? "source support가 확인된 target 연결 claim" : "supported target-linked claims", ko ? "verifier가 선언하고 빠짐없이 감사한 target 연결 claim" : "verifier-declared target-linked claims audited in full"],
    ["O", ko ? "관측된 referral·engagement·conversion" : "observed referrals, engagement, or conversions", ko ? "측정 가능한 1차 impression·referral·session" : "eligible first-party impressions, referrals, or sessions"],
  ];
  return (
    <table>
      <thead><tr><th>Stage</th><th>{ko ? "분자: 무엇을 세는가" : "Numerator: what is counted"}</th><th>{ko ? "분모: 어떤 집합에서 보는가" : "Denominator: eligible population"}</th></tr></thead>
      <tbody>{rows.map(([stage, numerator, denominator]) => <tr key={stage}><td><code>{stage}</code></td><td>{numerator}</td><td>{denominator}</td></tr>)}</tbody>
    </table>
  );
}

function GapTable({ ko }: { ko: boolean }) {
  const rows = ko
    ? [
        ["F · partial", "로컬 78/78 URL과 내부 링크 577/577은 통과했지만, 당시 runner는 공개 sitemap 77/78 실패를 예외로 버려 영수증을 결합하지 못했습니다. 현재 runner는 이를 partial receipt로 보존합니다.", "동일성 비교: 같은 URL digest의 로컬 export ↔ 공개 호스트"],
        ["R/C/P", "Pages는 R 0/120, C 4/120, P 4/4로 측정됐습니다. R은 빈칸이 아니라 관측된 0입니다.", "표면 진단: Pages ↔ GitHub 저장소(R 109/120, C 9/120)"],
        ["A/Q", "A 4/4, Q 43/58이지만 같은 모델의 앞선 반복은 35/54였습니다. Q는 claim support만 포함해 partial입니다.", "판정 보정: 고정 claim 집합의 독립 verifier ↔ 사람 표본 판정"],
        ["O · not_measured", "종료된 Search Console·referral·conversion 관측 기간이 없어 분모 자체를 만들지 않았습니다.", "성과 비교: 같은 기간·질의·엔진의 baseline ↔ treatment"],
        ["Promotion · none", "이번 실행은 진단 계약이며 비교 대상과 변경 arm을 사전 등록하지 않았습니다.", "승격 비교: 동결된 baseline ↔ treatment, 동일 index·budget·window"],
      ]
    : [
        ["F · partial", "All 78 local URLs and 577/577 internal links passed, but the previous runner discarded the deployed 77/78 sitemap failure as an exception. The current runner preserves it as a partial receipt.", "Identity check: local export ↔ public host with the same URL digest"],
        ["R/C/P", "Pages measured R 0/120, C 4/120, and P 4/4. R is an observed zero, not an empty cell.", "Surface diagnostic: Pages ↔ GitHub repository (R 109/120, C 9/120)"],
        ["A/Q", "A was 4/4 and Q was 43/58; an earlier same-model repeat returned 35/54. Q remains partial because it covers claim support only.", "Verdict calibration: independent verifier ↔ human sample over a frozen claim set"],
        ["O · not_measured", "No completed Search Console, referral, or conversion window exists, so no eligible denominator was created.", "Outcome comparison: baseline ↔ treatment with the same window, queries, and engine"],
        ["Promotion · none", "This run is diagnostic; no comparator or intervention arm was preregistered.", "Promotion comparison: frozen baseline ↔ treatment under the same index, budget, and window"],
      ];
  return (
    <table>
      <thead><tr><th>{ko ? "상태" : "State"}</th><th>{ko ? "빈칸이 뜻하는 것" : "What the gap means"}</th><th>{ko ? "필요한 비교군" : "Required comparator"}</th></tr></thead>
      <tbody>{rows.map(([state, meaning, comparator]) => <tr key={state}><td><code>{state}</code></td><td>{meaning}</td><td>{comparator}</td></tr>)}</tbody>
    </table>
  );
}

function ArtifactJoinTable({ ko }: { ko: boolean }) {
  const rows = [
    ["native_results", "native-result", ko ? "provider 원본" : "provider-native outcome"],
    ["measurement_results", "measurement", "geode.geo-vector@1"],
    ["verifier_receipts", "verifier-receipt", ko ? "독립 A/Q 판정" : "independent A/Q judgement"],
    ["outcome_receipts", "outcome-receipt", ko ? "종료된 1차 analytics" : "completed first-party analytics"],
    ["trajectory", "trajectory", "geode.trajectory@1 / release manifest"],
  ];
  return (
    <table>
      <thead><tr><th>run-spec</th><th>attempt kind</th><th>{ko ? "권한" : "Authority"}</th></tr></thead>
      <tbody>{rows.map(([artifact, kind, authority]) => <tr key={artifact}><td><code>{artifact}</code></td><td><code>{kind}</code></td><td>{authority}</td></tr>)}</tbody>
    </table>
  );
}

export default function GeoBenchmarkPage() {
  return (
    <DocsShell
      slug="benchmarks/geo"
      title="GEO visibility"
      titleKo="GEO 가시성"
      summary="A stage-aware benchmark contract for fetch, retrieval, citation, placement, absorption, quality, and outcome evidence. It deliberately has no aggregate GEO score."
      summaryKo="fetch, retrieval, citation, placement, absorption, quality, outcome 증거를 단계별로 측정하는 벤치마크 계약입니다. 단일 GEO 점수는 만들지 않습니다."
    >
      <Bi
        ko={
          <>
            <h2>무엇을 검증하는가</h2>
            <p>
              GEO는 문장을 다시 쓰는 최적화 점수가 아니라 증거 상태머신입니다.
              <code>preflight → live_observe</code>로 진단하며, 변경 효과를 주장할 때만
              사전 등록된 <code>experiment</code>로 진행합니다. 앞 단계가 뒤 단계를
              대신하지 못하며, 측정하지 못한 값은 0이 아니라
              <code>not_measured</code>로 남습니다.
            </p>
            <p>
              질의 실행 1회가 관측치 1개입니다. live profile은 6개 root ×
              (원문 1개 + paraphrase 3개) × K=5, 즉 120개 관측치를 만듭니다.
              C는 이 120개 전체를 분모로 쓰지만, R·P·A·Q는 해당 증거가 실제로
              존재하는 관측치나 claim만 각자의 분모로 사용합니다.
            </p>
            <VectorTable ko />

            <h2>빈 칸과 비교군</h2>
            <p>
              아래 값은 2026-08-24 로컬 diagnostic receipt를 읽은 결과이며
              공개 성능 주장이나 승격 근거가 아닙니다. <code>0</code>은 관측 결과,
              <code>not_measured</code>는 적격 분모·영수증 부재, <code>partial</code>은
              해당 단계의 일부 하위 지표만 측정했다는 뜻입니다.
            </p>
            <GapTable ko />
            <p>
              GitHub 저장소는 Pages로 권위가 전달되지 않는 위치를 찾는
              <strong>표면 진단 비교군</strong>입니다. 콘텐츠 변경의 효과를 주장하려면
              별도의 <strong>인과 비교군</strong>인 동결 baseline과 treatment가 필요합니다.
            </p>

            <h2>실행 계약</h2>
            <ol>
              <li>6개 root마다 root query 1개와 paraphrase 3개, 총 24개 문자열을 고정합니다.</li>
              <li><code>run-spec.json</code>이 workload SHA-256과 모델을 동결하고, live는 동일 surface의 별도 operator approval receipt와 정확히 K=5를 요구합니다.</li>
              <li>native result는 run-spec digest와 adapter·provider·credential source·model을 함께 고정합니다.</li>
              <li>24×K 각 셀은 하나의 native receipt로 돌아가며 검색 활성화, retrieval, citation의 JSON Pointer가 원본과 일치해야 합니다.</li>
              <li>absorption과 quality는 별도 verifier receipt·producer/version/model·digest-bound rubric이 없으면 측정값으로 인정하지 않습니다.</li>
              <li>Q는 verifier가 선언한 전체 target-linked claim 수와 실제 감사 행 수가 같아야 계산합니다.</li>
              <li>Q의 support 판정은 claim 본문과 source receipt에 실제 존재하는 인용 구간을 함께 남깁니다.</li>
              <li>실패한 public-host preflight도 partial receipt로 보존하며, O는 native 결과를 수정하지 않는 사후 analytics overlay입니다.</li>
              <li>v1은 Q 중 claim support만 측정하므로, 모든 영수증이 있어도 Q 전체는 <code>partial</code>입니다.</li>
            </ol>
            <pre><code>{collectCommand}</code></pre>
            <pre><code>{verifyCommand}</code></pre>
            <pre><code>{measureCommand}</code></pre>

            <h2>데이터·artifact 결합</h2>
            <p>
              vector 안에 trajectory나 원본 receipt를 복제하지 않습니다.
              <code>attempts.jsonl</code>의 한 행이 각 파일을 상대 경로와 SHA-256으로
              결합하고, <code>analysis.json</code>은 <code>measurement</code>의 분자·분모
              JSON Pointer를 읽어 비율을 재계산합니다.
            </p>
            <ArtifactJoinTable ko />
            <p>
              trajectory는 행동 증거이며 점수 정본이 아닙니다. publication manifest는
              선언된 모든 파일을 public 또는 withheld로 분류하고, bundle gate는 schema,
              digest, run ID, trajectory release scope를 한 번에 확인합니다.
            </p>
            <pre><code>{bundleCommand}</code></pre>

            <h2>현재 경계</h2>
            <p>
              로컬 export·sitemap·self-canonical·noindex·내부 링크만 확인한 F는
              <code>partial</code>입니다. 동일 URL 집합에 대한 공개 호스트의 HTTP·HTML·
              canonical·robots 영수증까지 결합돼야 <code>measured</code>가 됩니다.
              A/Q는 별도 source-aware verifier, O는 관측 기간이 끝난 1차 analytics
              영수증 없이는 측정하지 않습니다.
            </p>
            <p>
              현재 구현은 실패한 host preflight도 보존하고, Q의 claim 본문과 실제
              source quote를 검증하며, O를 immutable native result에 사후 결합합니다.
              남은 빈칸은 더미가 아니라 배포·독립 판정·1차 analytics의 실제 증거 부재입니다.
            </p>
            <p>
              native outcome, verifier 판단, GEODE trajectory, analysis와 publication
              manifest는 서로 다른 권한입니다. Inspect가 실행하지 않은 slash run을
              <code>.eval</code>로 포장하지도 않습니다.
            </p>
            <p>
              slash의 typed state는 작업 진행을 위한 advisory projection입니다. 모델이
              기록한 분자나 locator 자체는 벤치마크 권한이 아니며, schema와 digest를
              통과한 native/vector/verifier/outcome bundle만 측정 근거가 됩니다.
            </p>

            <h2>근거</h2>
            <ul>
              <li><a href="https://developers.google.com/search/docs/fundamentals/ai-optimization-guide">Google generative AI optimization guide</a></li>
              <li><a href="https://proceedings.neurips.cc/paper_files/paper/2025/hash/27aa3aeff0f8460a7b43d30fa6c5c032-Abstract-Datasets_and_Benchmarks_Track.html">C-SEO Bench</a></li>
              <li><a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/eval/geo-visibility.md">Canonical GEO evaluation profile</a></li>
            </ul>
          </>
        }
        en={
          <>
            <h2>What it verifies</h2>
            <p>
              GEO is an evidence state machine, not a rewrite-optimization score.
              A diagnostic moves through <code>preflight → live_observe</code>;
              only a preregistered treatment claim continues to <code>experiment</code>.
              An earlier phase cannot prove a later one. An absent measurement remains
              <code>not_measured</code>, never zero.
            </p>
            <p>
              One query run is one observation. The live profile produces 6 roots ×
              (one original + three paraphrases) × K=5, or 120 observations.
              C uses all 120 as its denominator; R, P, A, and Q use only the
              observations or claims for which that stage&apos;s evidence exists.
            </p>
            <VectorTable ko={false} />

            <h2>Empty cells and comparators</h2>
            <p>
              These values describe a local diagnostic receipt from 2026-08-24;
              they are not a public performance or promotion claim. <code>0</code>
              is an observed result, <code>not_measured</code> means no eligible
              denominator or receipt exists, and <code>partial</code> means only a
              submetric of that stage was measured.
            </p>
            <GapTable ko={false} />
            <p>
              The GitHub repository is a <strong>surface diagnostic comparator</strong>
              used to locate an authority-transfer boundary. A content-effect claim
              requires a separate <strong>causal comparator</strong>: frozen baseline
              and treatment arms.
            </p>

            <h2>Execution contract</h2>
            <ol>
              <li>Freeze one root query and three paraphrases for each of six roots: 24 exact strings.</li>
              <li><code>run-spec.json</code> freezes the workload SHA-256 and model; live runs require a separate operator approval receipt for the same surface and exactly K=5.</li>
              <li>The native result binds the run-spec digest plus adapter, provider, credential source, and model.</li>
              <li>Every cell in the 24×K matrix resolves to one native receipt; JSON Pointers for search activation, retrieval, and citations must match the source bytes.</li>
              <li>Absorption and quality remain unmeasured without a separate verifier receipt, producer/version/model, and digest-bound rubric.</li>
              <li>Q is computed only when the verifier-declared target-linked claim universe matches the audited rows.</li>
              <li>Two invalid claim extractions produce a digest-bound failure receipt and leave only that observation&apos;s A/Q unmeasured; transport failure still stops the run.</li>
              <li>Each Q support verdict retains the claim text and an exact quote present in the source receipt.</li>
              <li>Failed public-host checks persist as partial receipts; O is a late analytics overlay that never rewrites native results.</li>
              <li>v1 measures only claim support within Q, so the broader Q stage remains <code>partial</code> even with complete receipts.</li>
            </ol>
            <pre><code>{collectCommand}</code></pre>
            <pre><code>{verifyCommand}</code></pre>
            <pre><code>{measureCommand}</code></pre>

            <h2>Data and artifact joins</h2>
            <p>
              The vector does not copy trajectories or raw receipts. One
              <code>attempts.jsonl</code> row joins each file by relative path and
              SHA-256; <code>analysis.json</code> recomputes ratios from the
              measurement&apos;s numerator and denominator JSON Pointers.
            </p>
            <ArtifactJoinTable ko={false} />
            <p>
              A trajectory is behavior evidence, not score authority. The publication
              manifest classifies every declared file as public or withheld, while the
              bundle gate checks schemas, digests, run ID, and trajectory-release scope.
            </p>
            <pre><code>{bundleCommand}</code></pre>

            <h2>Current boundary</h2>
            <p>
              Local export, sitemap, self-canonical, noindex, and internal-link
              evidence leaves F <code>partial</code>. It becomes <code>measured</code>
              only after a public-host receipt binds the same URL set and passes
              HTTP, HTML, canonical, and robots checks. A/Q need a separate
              source-aware verifier; O needs a completed first-party analytics window.
            </p>
            <p>
              The current implementation preserves failed host preflights, verifies
              each Q claim against an exact source quote, and joins O after the
              immutable native result. Remaining gaps now represent missing deployment,
              independent-judgement, or first-party analytics evidence rather than fillers.
            </p>
            <p>
              Native outcome, verifier judgement, GEODE trajectory, analysis, and
              publication manifest retain separate authority. A slash run is not
              repackaged as <code>.eval</code> unless Inspect produced it.
            </p>
            <p>
              Slash typed state is an advisory workflow projection. Model-authored
              numerators and locators are not benchmark authority; only the schema-
              and digest-validated native/vector/verifier/outcome bundle is evidence.
            </p>

            <h2>Evidence basis</h2>
            <ul>
              <li><a href="https://developers.google.com/search/docs/fundamentals/ai-optimization-guide">Google generative AI optimization guide</a></li>
              <li><a href="https://proceedings.neurips.cc/paper_files/paper/2025/hash/27aa3aeff0f8460a7b43d30fa6c5c032-Abstract-Datasets_and_Benchmarks_Track.html">C-SEO Bench</a></li>
              <li><a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/eval/geo-visibility.md">Canonical GEO evaluation profile</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
