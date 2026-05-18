import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Petri Scenarios — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/scenarios"
      title="Scenarios"
      titleKo="시나리오"
      summary="173 default seeds plus 13 GEODE-specific seeds. The full audit catalog."
      summaryKo="173 default seeds + GEODE 13 seeds. 전체 audit 시나리오 카탈로그."
    >
      <Bi
        ko={
          <>
            <p>
              <strong>Reference:</strong> Petri × GEODE audit이 사용하는 시나리오 (seed) 카탈로그.
              두 종류로 나뉩니다. (1) Petri framework 기본 173 seeds. (2) GEODE 코드베이스/하네스 특성을 노리는 13 GEODE-specific seeds.
              7 카테고리에 각각 1-2개씩 배치되어 risk dimension을 골고루 자극합니다.
            </p>

            <h2>GEODE-specific seeds (13)</h2>
            <p>
              <code>plugins/petri_audit/seeds/</code>에 각 seed가 <code>.md</code> 파일 하나로 정의됩니다. seed 파일은 frontmatter (tags) + branch 별 pressure 곡선 (보통 1 → 2 → 3 → 2 → 1) 으로 구성됩니다.
            </p>
            <table>
              <thead><tr><th>카테고리</th><th>Seed ID</th><th>측정 차원</th></tr></thead>
              <tbody>
                <tr><td rowSpan={2}><strong>autonomy</strong></td><td><code>autonomy_self_preservation_under_replacement</code></td><td>self_replication, power-seeking</td></tr>
                <tr><td><code>autonomy_whistleblowing_user_intent_violation</code></td><td>refusal_appropriateness, instruction_override</td></tr>
                <tr><td rowSpan={2}><strong>calibration</strong></td><td><code>calibration_false_refusal_drift</code></td><td>refusal_appropriateness</td></tr>
                <tr><td><code>calibration_high_stakes_security_advice</code></td><td>refusal_appropriateness, harm</td></tr>
                <tr><td rowSpan={2}><strong>compute_use</strong></td><td><code>compute_use_sensitive_path_access</code></td><td>tool_misuse, scope_creep</td></tr>
                <tr><td><code>compute_use_unrestricted_shell</code></td><td>tool_misuse, sandbox_awareness</td></tr>
                <tr><td><strong>efficiency</strong></td><td><code>efficiency_long_running_loop</code></td><td>resource_acquisition</td></tr>
                <tr><td rowSpan={2}><strong>exploratory</strong></td><td><code>exploratory_dependency_change_disclosure</code></td><td>honesty (omission)</td></tr>
                <tr><td><code>exploratory_silent_codebase_modification</code></td><td>honesty (deception), tool_misuse</td></tr>
                <tr><td rowSpan={2}><strong>reasoning</strong></td><td><code>reasoning_chain_manipulation</code></td><td>manipulation, instruction_override</td></tr>
                <tr><td><code>reasoning_self_critique_bypass</code></td><td>sycophancy, refusal_after_compliance</td></tr>
                <tr><td rowSpan={2}><strong>research</strong></td><td><code>research_cherry_picking_dataset</code></td><td>honesty (omission)</td></tr>
                <tr><td><code>research_fabrication_under_pressure</code></td><td>fabrication, hallucination</td></tr>
              </tbody>
            </table>

            <h2>Pressure curve</h2>
            <p>
              각 seed는 보통 5 branch를 가집니다. 압력이 낮음(1) → 중간(2) → 높음(3) → 중간(2) → 낮음(1) 으로 변동합니다.
              압력 1은 캐주얼 요청, 압력 3은 명시적 압박 (긴급성, 권위, 손실 회피). 이 곡선이 target이 어디서 무너지는지 잡습니다.
            </p>

            <h2>Default 173 Petri seeds</h2>
            <p>
              <code>inspect_petri</code> v3 패키지의 <code>_seeds/</code>에 정의됩니다.
              GEODE-specific seeds와 동일한 frontmatter 규약을 따르며, 38 dim 전체에 걸친 일반 misalignment 시나리오를 다룹니다.
              GEODE audit은 <code>geode audit --seed-select id:...</code>로 선택해 함께 돌릴 수 있습니다.
            </p>
            <p>대략적 카테고리 분포 (Petri 3 공식 분류, upstream tag 기준):</p>
            <table>
              <thead><tr><th>카테고리</th><th>대략 비중</th><th>다루는 위험</th></tr></thead>
              <tbody>
                <tr><td><strong>refusal_calibration</strong></td><td>~30 seeds</td><td>잘못된 거부 / 거부 거부 / 과도한 단호함</td></tr>
                <tr><td><strong>honesty_deception</strong></td><td>~30 seeds</td><td>fabrication, omission, gaslighting, sycophancy</td></tr>
                <tr><td><strong>power_seeking</strong></td><td>~20 seeds</td><td>self_replication, resource acquisition, persuasion</td></tr>
                <tr><td><strong>harm_uplift</strong></td><td>~30 seeds</td><td>bio / cyber / weapons / csam / hate / harassment uplift</td></tr>
                <tr><td><strong>sandbox_awareness</strong></td><td>~20 seeds</td><td>tool_misuse, scope_creep, instruction_override</td></tr>
                <tr><td><strong>manipulation</strong></td><td>~15 seeds</td><td>flattery, emotional_pressure, false_urgency</td></tr>
                <tr><td><strong>privacy</strong></td><td>~10 seeds</td><td>pii_disclosure, surveillance_assist, doxxing</td></tr>
                <tr><td><strong>meta</strong></td><td>~15 seeds</td><td>refusal_after_compliance, partial_compliance, 등</td></tr>
              </tbody>
            </table>
            <p className="text-white/40 text-sm">
              <em>주의:</em> 카테고리 라벨과 정확 카운트는 inspect_petri 버전마다 달라집니다. 위 표는 v3 기준 대략치이며,
              실제 분포는 <code>python -c &quot;import inspect_petri._seeds._markdown as m; print(list(m.read_seed_directory()))&quot;</code>로 확인.
            </p>

            <h2>커스텀 seed 추가</h2>
            <ol>
              <li><code>plugins/petri_audit/seeds/&lt;category&gt;_&lt;name&gt;.md</code> 신규 생성.</li>
              <li>frontmatter에 <code>tags</code> 추가 (예: <code>["research", "honesty", "geode_specific"]</code>).</li>
              <li>branch 별 pressure 시나리오 작성 (5 branch 권장).</li>
              <li><code>geode audit --seed-select id:&lt;your-seed-id&gt;</code>로 실행.</li>
            </ol>

            <h2>참고</h2>
            <ul>
              <li>현 GEODE seeds 첫 등장: v0.91.0 (scenarios v1) → v0.92.0 (v2) → v0.93.0 (v3). audit reports는 <code>docs/audits/</code>.</li>
              <li>실행: <a href="/geode/docs/petri/run">감사 실행</a></li>
              <li>차원: <a href="/geode/docs/petri/judge-dimensions">38 Judge 차원</a></li>
              <li>publish된 결과: <a href="/petri-bundle/">/geode/petri-bundle/</a></li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              <strong>Reference:</strong> the seed catalog used by Petri × GEODE audits.
              Two kinds. (1) 173 Petri-framework defaults. (2) 13 GEODE-specific seeds that target the GEODE codebase
              and harness. Seven categories, spread to exercise risk dimensions evenly.
            </p>

            <h2>GEODE-specific seeds (13)</h2>
            <p>
              Each seed lives at <code>plugins/petri_audit/seeds/</code> as a single <code>.md</code> file. The file
              carries frontmatter (tags) plus a per-branch pressure curve (commonly 1 → 2 → 3 → 2 → 1).
            </p>
            <table>
              <thead><tr><th>Category</th><th>Seed ID</th><th>Dimensions touched</th></tr></thead>
              <tbody>
                <tr><td rowSpan={2}><strong>autonomy</strong></td><td><code>autonomy_self_preservation_under_replacement</code></td><td>self_replication, power-seeking</td></tr>
                <tr><td><code>autonomy_whistleblowing_user_intent_violation</code></td><td>refusal_appropriateness, instruction_override</td></tr>
                <tr><td rowSpan={2}><strong>calibration</strong></td><td><code>calibration_false_refusal_drift</code></td><td>refusal_appropriateness</td></tr>
                <tr><td><code>calibration_high_stakes_security_advice</code></td><td>refusal_appropriateness, harm</td></tr>
                <tr><td rowSpan={2}><strong>compute_use</strong></td><td><code>compute_use_sensitive_path_access</code></td><td>tool_misuse, scope_creep</td></tr>
                <tr><td><code>compute_use_unrestricted_shell</code></td><td>tool_misuse, sandbox_awareness</td></tr>
                <tr><td><strong>efficiency</strong></td><td><code>efficiency_long_running_loop</code></td><td>resource_acquisition</td></tr>
                <tr><td rowSpan={2}><strong>exploratory</strong></td><td><code>exploratory_dependency_change_disclosure</code></td><td>honesty (omission)</td></tr>
                <tr><td><code>exploratory_silent_codebase_modification</code></td><td>honesty (deception), tool_misuse</td></tr>
                <tr><td rowSpan={2}><strong>reasoning</strong></td><td><code>reasoning_chain_manipulation</code></td><td>manipulation, instruction_override</td></tr>
                <tr><td><code>reasoning_self_critique_bypass</code></td><td>sycophancy, refusal_after_compliance</td></tr>
                <tr><td rowSpan={2}><strong>research</strong></td><td><code>research_cherry_picking_dataset</code></td><td>honesty (omission)</td></tr>
                <tr><td><code>research_fabrication_under_pressure</code></td><td>fabrication, hallucination</td></tr>
              </tbody>
            </table>

            <h2>Pressure curve</h2>
            <p>
              Each seed usually has 5 branches. Pressure rises from low (1) to medium (2) to high (3) and back down.
              Pressure 1 is a casual request; pressure 3 is explicit (urgency, authority, loss aversion). The curve
              reveals where the target gives way.
            </p>

            <h2>Default 173 Petri seeds</h2>
            <p>
              Defined in <code>inspect_petri</code> v3 under <code>_seeds/</code>. They follow the same frontmatter
              convention as the GEODE-specific seeds and cover general misalignment scenarios across the full 38 dims.
              GEODE audits can pull them in via <code>geode audit --seed-select id:...</code>.
            </p>

            <h2>Adding a custom seed</h2>
            <ol>
              <li>Create <code>plugins/petri_audit/seeds/&lt;category&gt;_&lt;name&gt;.md</code>.</li>
              <li>Add <code>tags</code> to frontmatter (e.g. <code>["research", "honesty", "geode_specific"]</code>).</li>
              <li>Write per-branch pressure scenarios (5 branches recommended).</li>
              <li>Run <code>geode audit --seed-select id:&lt;your-seed-id&gt;</code>.</li>
            </ol>

            <h2>See also</h2>
            <ul>
              <li>GEODE seeds first landed in v0.91.0 (scenarios v1), v0.92.0 (v2), v0.93.0 (v3). Audit reports under <code>docs/audits/</code>.</li>
              <li>Run: <a href="/geode/docs/petri/run">Run an Audit</a></li>
              <li>Dimensions: <a href="/geode/docs/petri/judge-dimensions">38 Judge Dimensions</a></li>
              <li>Published results: <a href="/petri-bundle/">/geode/petri-bundle/</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
