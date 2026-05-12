import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Run an Audit — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/run"
      title="Run an Audit"
      titleKo="감사 실행"
      summary="inspect eval inspect_petri/audit. Choose model roles, seeds, and turn budget."
      summaryKo="inspect eval inspect_petri/audit. 모델 역할, seeds, turn 예산 선택."
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

            <h2>최소 실행 명령</h2>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=anthropic/claude-haiku-4-5 \\
  --model-role target=geode/claude-opus-4-7 \\
  --model-role judge=anthropic/claude-haiku-4-5 \\
  --seed-select id:001,002,003 \\
  --max-turns 10`}</pre>

            <h2>옵션 정리</h2>
            <table>
              <thead><tr><th>옵션</th><th>의미</th><th>권장 값</th></tr></thead>
              <tbody>
                <tr><td><code>--model-role</code></td><td>3 역할 각자 모델 지정</td><td>auditor/judge는 같은 모델 가능</td></tr>
                <tr><td><code>--seed-select</code></td><td>173 seeds 중 일부만</td><td>첫 run은 3-5개</td></tr>
                <tr><td><code>--max-turns</code></td><td>대화 turn 상한</td><td>10 (cost cap), 30 (full)</td></tr>
                <tr><td><code>--log-dir</code></td><td>transcript 저장 위치</td><td>기본 <code>./logs/</code></td></tr>
              </tbody>
            </table>

            <h2>결과 보기</h2>
            <p>
              결과 transcript는 <code>./logs/</code>에 저장됩니다. Inspect transcript viewer로 확인:
            </p>
            <pre>{`inspect view ./logs/<run-id>.eval`}</pre>
            <p>
              퍼블리시된 GEODE audit bundle은 <a href="/petri-bundle/">/geode/petri-bundle/</a>에서 바로 볼 수 있습니다.
            </p>

            <h2>다음 단계</h2>
            <ul>
              <li>점수 의미: <a href="/docs/petri/judge-dimensions">38 Judge 차원</a></li>
              <li>관측 분석: <a href="/docs/ops/observability">관측성</a></li>
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

            <h2>Minimal command</h2>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=anthropic/claude-haiku-4-5 \\
  --model-role target=geode/claude-opus-4-7 \\
  --model-role judge=anthropic/claude-haiku-4-5 \\
  --seed-select id:001,002,003 \\
  --max-turns 10`}</pre>

            <h2>Options reference</h2>
            <table>
              <thead><tr><th>Option</th><th>Meaning</th><th>Recommended</th></tr></thead>
              <tbody>
                <tr><td><code>--model-role</code></td><td>Model for each of the three roles.</td><td>Auditor and judge can share a model.</td></tr>
                <tr><td><code>--seed-select</code></td><td>Subset of the 173 seeds.</td><td>3-5 for the first run.</td></tr>
                <tr><td><code>--max-turns</code></td><td>Per-conversation turn cap.</td><td>10 (cost cap), 30 (full).</td></tr>
                <tr><td><code>--log-dir</code></td><td>Where transcripts land.</td><td>Default <code>./logs/</code></td></tr>
              </tbody>
            </table>

            <h2>Reading the results</h2>
            <p>
              Transcripts land in <code>./logs/</code>. View with the Inspect transcript viewer:
            </p>
            <pre>{`inspect view ./logs/<run-id>.eval`}</pre>
            <p>
              The published GEODE audit bundle is browsable at <a href="/petri-bundle/">/geode/petri-bundle/</a>.
            </p>

            <h2>Next</h2>
            <ul>
              <li>What the scores mean: <a href="/docs/petri/judge-dimensions">38 Judge Dimensions</a></li>
              <li>Bigger picture: <a href="/docs/ops/observability">Observability</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
