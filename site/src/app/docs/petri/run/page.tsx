import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Run an Audit — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/run"
      title="Run an Audit"
      titleKo="감사 실행"
      summary="geode audit (primary) or inspect eval (raw). Choose model roles, dim set, seeds, and turn budget."
      summaryKo="geode audit (1차 명령) 또는 inspect eval (raw). 모델 역할, dim set, seeds, turn 예산 선택."
    >
      <Bi
        ko={
          <>
            <p>
              이 가이드는 Petri × GEODE audit를 한 번 끝까지 돌리는 절차입니다. 5분 안에 첫 결과를 봅니다.
            </p>

            <h2>준비물</h2>
            <ul>
              <li>GEODE가 설치되어 있고, <code>plugins/petri_audit</code>가 활성화돼 있어야 합니다.</li>
              <li>Auditor·Target·Judge에 쓸 LLM 키 (같은 키 3중 사용 가능, 보통 더 작은 모델 추천).</li>
              <li>비용 가드: 첫 run은 seed 3개·turn 10·Haiku로 묶어 5,000 KRW 이내가 권장.</li>
            </ul>

            <h2>1차 명령: <code>geode audit</code> (v0.66+)</h2>
            <p>
              GEODE는 <code>plugins/petri_audit/cli_audit.py</code>의 Typer 래퍼를 통해 audit를 실행하는 게 1차 인터페이스입니다.
              본 명령은 모델/seed/dim 옵션을 인자로 받고, audit-mode strip을 자동 적용하며, 결과를 <code>~/.geode/diagnostics/petri/</code>에 저장합니다.
            </p>
            <pre>{`geode audit \\
  --auditor anthropic/claude-haiku-4-5 \\
  --target  geode/claude-opus-4-7 \\
  --judge   anthropic/claude-haiku-4-5 \\
  --dim-set geode_5axes \\
  --seed-select id:001,002,003 \\
  --max-turns 10`}</pre>

            <h2>옵션</h2>
            <table>
              <thead><tr><th>옵션</th><th>의미</th><th>기본 / 권장</th></tr></thead>
              <tbody>
                <tr><td><code>--auditor</code> · <code>--target</code> · <code>--judge</code></td><td>3 역할 각자 모델 지정.</td><td>auditor/judge는 같은 모델 가능. target은 보통 <code>geode/&lt;model&gt;</code>.</td></tr>
                <tr><td><code>--dim-set</code></td><td>판정 차원 세트. <code>geode_5axes</code> (17 dim) 또는 <code>full</code> (38 dim).</td><td>기본 <code>geode_5axes</code>. cost↓ 하면서 GEODE 관점 5축 (refusal/honesty/power/manipulation/harm) 커버.</td></tr>
                <tr><td><code>--seed-select</code></td><td>173 seeds 중 일부만.</td><td>첫 run은 3-5개.</td></tr>
                <tr><td><code>--max-turns</code></td><td>대화 turn 상한.</td><td>10 (cost cap), 30 (full).</td></tr>
                <tr><td><code>--target-tools</code></td><td>target에 허용된 도구 화이트리스트.</td><td>비워두면 전체 도구.</td></tr>
                <tr><td><code>--unrestricted</code></td><td>cost cap 해제 (full audit).</td><td>일반적으로 off.</td></tr>
              </tbody>
            </table>

            <h2>대체 명령: <code>inspect eval</code> (raw)</h2>
            <p>
              Petri framework 자체의 raw 명령. GEODE wrapper를 우회하므로 비교 baseline (vanilla LLM)을 측정할 때 사용합니다.
            </p>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=anthropic/claude-haiku-4-5 \\
  --model-role target=geode/claude-opus-4-7 \\
  --model-role judge=anthropic/claude-haiku-4-5 \\
  --seed-select id:001,002,003 \\
  --max-turns 10`}</pre>

            <h2>결과 보기</h2>
            <p>
              결과 transcript는 <code>~/.geode/diagnostics/petri/&lt;run-id&gt;/</code> 또는 <code>./logs/</code>에 저장됩니다. Inspect transcript viewer로 확인:
            </p>
            <pre>{`inspect view ~/.geode/diagnostics/petri/<run-id>/`}</pre>
            <p>
              퍼블리시된 GEODE audit bundle은 <a href="/petri-bundle/">/geode/petri-bundle/</a>에서 바로 볼 수 있습니다.
            </p>

            <h2>다음 단계</h2>
            <ul>
              <li>점수 의미: <a href="/docs/petri/judge-dimensions">17/38 Judge 차원</a></li>
              <li>관측 분석: <a href="/docs/verification/observability">관측성</a></li>
              <li>비용: <a href="/docs/ops/cost">비용 모니터링</a></li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              This guide runs a single Petri × GEODE audit end to end. First result in five minutes.
            </p>

            <h2>Prerequisites</h2>
            <ul>
              <li>GEODE installed with <code>plugins/petri_audit</code> active.</li>
              <li>LLM keys for auditor, target, and judge (one key for all three is fine; usually smaller models are recommended).</li>
              <li>Cost cap: first run should stay under ~5,000 KRW with 3 seeds, 10 turns, Haiku.</li>
            </ul>

            <h2>Primary command: <code>geode audit</code> (since v0.66)</h2>
            <p>
              The primary interface is the Typer wrapper at <code>plugins/petri_audit/cli_audit.py</code>. It accepts
              model, seed, and dim options as arguments, applies audit-mode strip automatically, and writes results
              to <code>~/.geode/diagnostics/petri/</code>.
            </p>
            <pre>{`geode audit \\
  --auditor anthropic/claude-haiku-4-5 \\
  --target  geode/claude-opus-4-7 \\
  --judge   anthropic/claude-haiku-4-5 \\
  --dim-set geode_5axes \\
  --seed-select id:001,002,003 \\
  --max-turns 10`}</pre>

            <h2>Options</h2>
            <table>
              <thead><tr><th>Option</th><th>Meaning</th><th>Default / recommended</th></tr></thead>
              <tbody>
                <tr><td><code>--auditor</code> · <code>--target</code> · <code>--judge</code></td><td>Model per role.</td><td>Auditor and judge may share. Target is usually <code>geode/&lt;model&gt;</code>.</td></tr>
                <tr><td><code>--dim-set</code></td><td>Judge dimension set. <code>geode_5axes</code> (17 dims) or <code>full</code> (38 dims).</td><td>Default <code>geode_5axes</code>. Lower cost while covering the 5 GEODE-relevant axes (refusal, honesty, power, manipulation, harm).</td></tr>
                <tr><td><code>--seed-select</code></td><td>Subset of the 173 seeds.</td><td>3-5 for the first run.</td></tr>
                <tr><td><code>--max-turns</code></td><td>Per-conversation turn cap.</td><td>10 (cost cap), 30 (full).</td></tr>
                <tr><td><code>--target-tools</code></td><td>Whitelist of tools the target may call.</td><td>Empty means all tools.</td></tr>
                <tr><td><code>--unrestricted</code></td><td>Lifts the cost cap (full audit).</td><td>Off by default.</td></tr>
              </tbody>
            </table>

            <h2>Alternative command: <code>inspect eval</code> (raw)</h2>
            <p>
              The raw Petri-framework command. Bypasses the GEODE wrapper; use it when measuring a comparison baseline
              (vanilla LLM).
            </p>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=anthropic/claude-haiku-4-5 \\
  --model-role target=geode/claude-opus-4-7 \\
  --model-role judge=anthropic/claude-haiku-4-5 \\
  --seed-select id:001,002,003 \\
  --max-turns 10`}</pre>

            <h2>Reading the results</h2>
            <p>
              Transcripts land in <code>~/.geode/diagnostics/petri/&lt;run-id&gt;/</code> or <code>./logs/</code>. View with the Inspect transcript viewer:
            </p>
            <pre>{`inspect view ~/.geode/diagnostics/petri/<run-id>/`}</pre>
            <p>
              The published GEODE audit bundle is browsable at <a href="/petri-bundle/">/geode/petri-bundle/</a>.
            </p>

            <h2>Next</h2>
            <ul>
              <li>What the scores mean: <a href="/docs/petri/judge-dimensions">17/38 Judge Dimensions</a></li>
              <li>Bigger picture: <a href="/docs/verification/observability">Observability</a></li>
              <li>Cost: <a href="/docs/ops/cost">Cost Monitoring</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
