import { Bi, DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "GEO visibility — GEODE Docs" };

const measureCommand = `uv run python scripts/eval/geo_visibility.py \\
  --run-spec <run-dir>/run-spec.json \\
  --workload <run-dir>/workload.json \\
  --native-results <run-dir>/native-results.json \\
  --verifier-results <run-dir>/verifier-results.json \\
  --out <run-dir>/geo-vector.json`;

const verifyCommand = `uv run python scripts/eval/geo_verify.py \\
  --workload <run-dir>/workload.json \\
  --native-results <run-dir>/native-results.json \\
  --rubric <run-dir>/verifier-rubric.json \\
  --out <run-dir>/verifier-results.json`;

const collectCommand = `uv run python scripts/eval/geo_collect.py \\
  --run-spec <run-dir>/run-spec.json \\
  --workload <run-dir>/workload.json \\
  --site-preflight <run-dir>/site-preflight.json \\
  --link-audit <run-dir>/link-audit.json \\
  --host-preflight <run-dir>/host-preflight.json \\
  --out <run-dir>/native-results.json`;

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
              <code>preflight → offline_measure → live_observe → experiment</code>의
              앞 단계가 뒤 단계를 대신하지 못하며, 측정하지 못한 값은 0이 아니라
              <code>not_measured</code>로 남습니다.
            </p>
            <p>
              질의 실행 1회가 관측치 1개입니다. live profile은 6개 root ×
              (원문 1개 + paraphrase 3개) × K=5, 즉 120개 관측치를 만듭니다.
              C는 이 120개 전체를 분모로 쓰지만, R·P·A·Q는 해당 증거가 실제로
              존재하는 관측치나 claim만 각자의 분모로 사용합니다.
            </p>
            <VectorTable ko />

            <h2>실행 계약</h2>
            <ol>
              <li>6개 root마다 root query 1개와 paraphrase 3개, 총 24개 문자열을 고정합니다.</li>
              <li><code>run-spec.json</code>이 workload SHA-256과 모델을 동결하고, live는 동일 surface의 별도 operator approval receipt와 정확히 K=5를 요구합니다.</li>
              <li>24×K 각 셀은 하나의 native receipt로 돌아가며 검색 활성화, retrieval, citation의 JSON Pointer가 원본과 일치해야 합니다.</li>
              <li>absorption과 quality는 별도 verifier receipt·producer/version·digest-bound rubric이 없으면 측정값으로 인정하지 않습니다.</li>
              <li>Q는 verifier가 선언한 전체 target-linked claim 수와 실제 감사 행 수가 같아야 계산합니다.</li>
              <li>v1은 Q 중 claim support만 측정하므로, 모든 영수증이 있어도 Q 전체는 <code>partial</code>입니다.</li>
            </ol>
            <pre><code>{collectCommand}</code></pre>
            <pre><code>{verifyCommand}</code></pre>
            <pre><code>{measureCommand}</code></pre>

            <h2>현재 경계</h2>
            <p>
              로컬 export·sitemap·self-canonical·noindex·내부 링크만 확인한 F는
              <code>partial</code>입니다. 동일 URL 집합에 대한 공개 호스트의 HTTP·HTML·
              canonical·robots 영수증까지 결합돼야 <code>measured</code>가 됩니다.
              A/Q는 별도 source-aware verifier, O는 관측 기간이 끝난 1차 analytics
              영수증 없이는 측정하지 않습니다.
            </p>
            <p>
              native outcome, verifier 판단, GEODE trajectory, analysis와 publication
              manifest는 서로 다른 권한입니다. Inspect가 실행하지 않은 slash run을
              <code>.eval</code>로 포장하지도 않습니다.
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
              An earlier <code>preflight → offline_measure → live_observe → experiment</code>
              phase cannot prove a later one. An absent measurement remains
              <code>not_measured</code>, never zero.
            </p>
            <p>
              One query run is one observation. The live profile produces 6 roots ×
              (one original + three paraphrases) × K=5, or 120 observations.
              C uses all 120 as its denominator; R, P, A, and Q use only the
              observations or claims for which that stage&apos;s evidence exists.
            </p>
            <VectorTable ko={false} />

            <h2>Execution contract</h2>
            <ol>
              <li>Freeze one root query and three paraphrases for each of six roots: 24 exact strings.</li>
              <li><code>run-spec.json</code> freezes the workload SHA-256 and model; live runs require a separate operator approval receipt for the same surface and exactly K=5.</li>
              <li>Every cell in the 24×K matrix resolves to one native receipt; JSON Pointers for search activation, retrieval, and citations must match the source bytes.</li>
              <li>Absorption and quality remain unmeasured without a separate verifier receipt, producer/version, and digest-bound rubric.</li>
              <li>Q is computed only when the verifier-declared target-linked claim universe matches the audited rows.</li>
              <li>v1 measures only claim support within Q, so the broader Q stage remains <code>partial</code> even with complete receipts.</li>
            </ol>
            <pre><code>{collectCommand}</code></pre>
            <pre><code>{verifyCommand}</code></pre>
            <pre><code>{measureCommand}</code></pre>

            <h2>Current boundary</h2>
            <p>
              Local export, sitemap, self-canonical, noindex, and internal-link
              evidence leaves F <code>partial</code>. It becomes <code>measured</code>
              only after a public-host receipt binds the same URL set and passes
              HTTP, HTML, canonical, and robots checks. A/Q need a separate
              source-aware verifier; O needs a completed first-party analytics window.
            </p>
            <p>
              Native outcome, verifier judgement, GEODE trajectory, analysis, and
              publication manifest retain separate authority. A slash run is not
              repackaged as <code>.eval</code> unless Inspect produced it.
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
