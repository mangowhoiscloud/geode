import { Bi, DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "GEO visibility — GEODE Docs" };

const measureCommand = `uv run python scripts/eval/geo_visibility.py \\
  --run-spec <run-dir>/run-spec.json \\
  --workload <run-dir>/workload.json \\
  --native-results <run-dir>/native-results.json \\
  --out <run-dir>/geo-vector.json`;

function VectorTable({ ko }: { ko: boolean }) {
  const rows = [
    ["F", ko ? "Fetch / index 적격성" : "Fetch / index eligibility", ko ? "감사한 URL" : "audited URLs"],
    ["R", ko ? "검색 포함" : "Retrieval inclusion", ko ? "검색 표면이 노출된 반복 질의" : "repeated queries exposing retrieval"],
    ["C", ko ? "인용 선택" : "Citation selection", ko ? "모든 반복 질의" : "all repeated queries"],
    ["P", ko ? "가시 배치" : "Visible placement", ko ? "target 인용 응답" : "target-cited responses"],
    ["A", ko ? "답변 흡수" : "Answer absorption", ko ? "검증된 target 인용 응답" : "verified target-cited responses"],
    ["Q", ko ? "claim support (품질 부분지표)" : "Claim support (Q submetric)", ko ? "감사한 target 연결 claim" : "audited target-linked claims"],
    ["O", ko ? "1차 outcome" : "First-party outcome", ko ? "적격 impression / referral / session" : "eligible impressions / referrals / sessions"],
  ];
  return (
    <table>
      <thead><tr><th>Stage</th><th>{ko ? "질문" : "Question"}</th><th>{ko ? "분모" : "Denominator"}</th></tr></thead>
      <tbody>{rows.map(([stage, label, denominator]) => <tr key={stage}><td><code>{stage}</code></td><td>{label}</td><td>{denominator}</td></tr>)}</tbody>
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
            <pre><code>{measureCommand}</code></pre>

            <h2>현재 경계</h2>
            <p>
              저장소 CI는 export, sitemap, self-canonical, indexability와 LLM index를
              <code>geode.geo-preflight.v2</code> 영수증으로 확인합니다. R–Q 측정기는
              실행 가능하지만 공개된 live 결과는 아직 없습니다. O는 Search Console,
              referral과 전환 같은 1차 analytics가 들어오기 전까지 측정하지 않습니다.
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
            <pre><code>{measureCommand}</code></pre>

            <h2>Current boundary</h2>
            <p>
              Repository CI checks export, sitemap, self-canonical, indexability,
              and LLM indexes in a <code>geode.geo-preflight.v2</code> receipt. The R–Q
              measurement path is executable, but no public live result exists yet.
              O remains unmeasured until first-party Search Console, referral, or
              conversion evidence is supplied.
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
