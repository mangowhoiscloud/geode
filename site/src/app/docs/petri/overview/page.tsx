import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Petri × GEODE Integration — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/overview"
      title="Petri × GEODE Integration"
      titleKo="Petri × GEODE 통합"
      summary="Anthropic Alignment Science's framework, wrapped over GEODE's agent. 173 seeds, 38 judge dimensions."
      summaryKo="Anthropic Alignment Science의 프레임워크를 GEODE 에이전트 위에 얹음. 173 seeds, 38 judge 차원."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 자기 자신의 misalignment 위험을 측정하기 위해 Petri framework를 wrapped agent로 통합합니다.
              Petri (<strong>Parallel Exploration Tool for Risky Interactions</strong>)는 Anthropic Alignment
              Science가 만든 alignment audit framework로, <a href="https://inspect.aisi.org.uk/">inspect_ai</a> (UK AISI)
              위에 build 되었고 <a href="https://meridianlabs.ai">Meridian Labs</a>가 <code>inspect_petri</code> v3 (MIT) 로 maintain합니다.
            </p>

            <h2>세 가지 모델 역할</h2>
            <table>
              <thead><tr><th>Role</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><strong>Auditor</strong></td><td>Target을 misalign 방향으로 유도하는 적대적 agent</td></tr>
                <tr><td><strong>Target</strong></td><td>측정 대상. GEODE wrapped agent 또는 vanilla LLM</td></tr>
                <tr><td><strong>Judge</strong></td><td>Transcript를 38 dimension으로 평가하는 평가자</td></tr>
              </tbody>
            </table>

            <h2>기본 패키지</h2>
            <ul>
              <li><strong>173</strong> default seeds. 시나리오 카탈로그.</li>
              <li><strong>38</strong> judge dimensions. 위험 차원별 점수.</li>
              <li>3-role 호출 (auditor, target, judge 각자 모델 선택 가능).</li>
            </ul>

            <p>실행 명령 예시:</p>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=<m> target=<m> judge=<m>`}</pre>

            <h2>Inspect transcript viewer v3</h2>
            <p>
              2026-05-07 <em>Introducing Petri 3</em> (출처: meridianlabs.ai)에서 Inspect transcript viewer가
              Petri를 네이티브 지원하기 시작했습니다. GEODE의 audit run 결과는 동일한 viewer로 확인할 수 있습니다.
            </p>

            <h2>GEODE에서의 위치</h2>
            <ul>
              <li>코드: <code>plugins/petri_audit/</code> (runner, judge_dims, schema, audit mode)</li>
              <li>최신 audit bundle: <a href="/self-improving/petri-bundle/">/geode/self-improving/petri-bundle/</a> 외부 viewer</li>
              <li>CHANGELOG entry: v0.92.0+ 에서 Petri × GEODE 통합 (PR #1024 등)</li>
            </ul>

            <h2>왜 통합했나</h2>
            <p>
              GEODE는 LLM 위에 얹은 자율 에이전트입니다. 그것이 misalignment를 일으킬 수 있는지 정량적으로 측정할 방법이 필요했고,
              Petri가 그 방법을 제공합니다. wrapper 위에서 측정함으로써 LLM 단독이 아니라 GEODE-as-deployed의 행동을 평가합니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              GEODE integrates the Petri framework as a wrapped agent to measure its own misalignment risk.
              Petri (<strong>Parallel Exploration Tool for Risky Interactions</strong>) is an alignment audit
              framework built by Anthropic Alignment Science, sitting on top of <a href="https://inspect.aisi.org.uk/">inspect_ai</a> (UK AISI)
              and maintained by <a href="https://meridianlabs.ai">Meridian Labs</a> as <code>inspect_petri</code> v3 (MIT).
            </p>

            <h2>Three model roles</h2>
            <table>
              <thead><tr><th>Role</th><th>What it does</th></tr></thead>
              <tbody>
                <tr><td><strong>Auditor</strong></td><td>Adversarial agent that steers the target toward misalignment.</td></tr>
                <tr><td><strong>Target</strong></td><td>The system under test. GEODE wrapped agent or a vanilla LLM.</td></tr>
                <tr><td><strong>Judge</strong></td><td>Scores the transcript on 38 dimensions.</td></tr>
              </tbody>
            </table>

            <h2>What ships</h2>
            <ul>
              <li><strong>173</strong> default seeds. The scenario catalog.</li>
              <li><strong>38</strong> judge dimensions. Risk axes scored independently.</li>
              <li>3-role invocation (auditor, target, judge are independently model-selectable).</li>
            </ul>

            <p>Run command:</p>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=<m> target=<m> judge=<m>`}</pre>

            <h2>Inspect transcript viewer v3</h2>
            <p>
              In <em>Introducing Petri 3</em> (2026-05-07, meridianlabs.ai), the Inspect transcript viewer
              began supporting Petri natively. GEODE audit runs render in the same viewer.
            </p>

            <h2>Where this lives in GEODE</h2>
            <ul>
              <li>Code: <code>plugins/petri_audit/</code> (runner, judge_dims, schema, audit mode)</li>
              <li>Latest bundle: <a href="/self-improving/petri-bundle/">/geode/self-improving/petri-bundle/</a> external viewer</li>
              <li>CHANGELOG entries: Petri × GEODE integration since v0.92.0 (PR #1024 et al.)</li>
            </ul>

            <h2>Why we wired it in</h2>
            <p>
              GEODE is an autonomous agent layered over an LLM. We needed a quantitative way to ask whether
              that wrapping could cause misalignment, and Petri provides one. Measuring on the wrapper lets us
              evaluate the behavior of GEODE-as-deployed, not the LLM in isolation.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
