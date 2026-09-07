import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Petri × GEODE — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/overview"
      title="Petri × GEODE"
      titleKo="Petri × GEODE"
      summary="Scenario-based behavioral audits: an auditor probes GEODE, and a separate judge scores the resulting transcript against a rubric."
      summaryKo="Auditor가 시나리오로 GEODE의 행동을 탐색하고, 별도의 Judge가 기록을 루브릭에 따라 채점하는 행동 감사입니다."
    >
      <Bi
        ko={
          <>
            <p>
              Petri는 주어진 시나리오에서 에이전트가 어떻게 행동하는지
              탐색하는 감사 도구입니다. GEODE는 <a href="https://inspect.aisi.org.uk/">Inspect</a> 위의{" "}
              <code>inspect_petri</code>를 통해 자신의 실행 루프를 측정 대상으로
              연결합니다. 점수는 선택한 시나리오와 루브릭에 대한 LLM의
              판단이지, 제품 전체의 안전성 보증이나 실제 작업 성공률은 아닙니다.
              실행 중 검증과 벤치마크 채점의 차이는{" "}
              <a href="/geode/docs/verification/evaluation">검증과 평가</a>에서 먼저 구분합니다.
            </p>

            <h2>세 가지 모델 역할</h2>
            <table>
              <thead><tr><th>역할</th><th>하는 일</th><th>결과의 의미</th></tr></thead>
              <tbody>
                <tr><td><strong>Auditor</strong></td><td>seed의 지시에 따라 대화와 압박 조건을 구성합니다.</td><td>평가 상황을 만드는 역할이며 최종 점수의 주체가 아닙니다.</td></tr>
                <tr><td><strong>Target</strong></td><td><code>geode/&lt;model&gt;</code>로 연결한 GEODE가 응답하고 도구를 사용합니다.</td><td>감사 대상의 행동 기록입니다.</td></tr>
                <tr><td><strong>Judge</strong></td><td>기록을 읽고 차원별 루브릭을 적용합니다.</td><td><code>audit_judge</code>의 차원별 점수입니다. 외부 상태 검사를 대신하지 않습니다.</td></tr>
              </tbody>
            </table>
            <p>
              세 역할은 서로 다른 책임이지, 반드시 다른 모델이나 제공자라는
              뜻은 아닙니다. 비교에서는 실제로 해석된 모델·인증 경로,
              seed·루브릭 버전, turn 한도와 도구 조건을 함께 고정해야 합니다.{" "}
              <code>--target-tools none</code>은 auditor의 합성 도구 경로를
              끄는 기본값이며, GEODE 자체 도구를 모두 끈다는 뜻은 아닙니다.
            </p>

            <h2>실행 흐름</h2>
            <p>
              <code>geode-eval audit</code>는{" "}
              <code>evals/petri/cli_audit.py</code>로 들어와{" "}
              <code>evals/petri/runner.py</code>의{" "}
              <code>run_audit</code>이 inspect-petri 서브프로세스를 돌립니다.{" "}
              <code>.eval</code>은 Petri 전용 점수 형식이 아니라 Inspect의
              평가 로그입니다. 실행 설정, 모델 역할, sample별 기록·점수와
              사용량을 함께 읽어야 합니다. 아카이브가 성공하면 완료 로그는 워크트리 밖{" "}
              <code>~/.geode/petri/logs/</code>에 보존되고, 커밋 가능한 요약
              YAML이 <code>docs/audits/eval-logs/</code>에 남습니다. 원문에는
              민감한 입력·출력이 포함될 수 있으므로 공개 검토는 별도입니다.
              현재 GEODE target adapter는 응답 텍스트와 사용량을 반환합니다.
              외부 감사 로그에 GEODE 내부 도구 호출 전체가 보존됐다고 가정하면
              안 됩니다.
            </p>
            <p>
              scaffold-search의 측정 경로가 소비하는 출력은 stdout의 마지막 비어 있지 않은 줄
              하나입니다. <code>core/audit/dim_extractor.py</code>의{" "}
              <code>extract_dim_aggregates</code>가 <code>.eval</code>{" "}
              아카이브에서 차원별 judge 점수를 집계해{" "}
              <code>{`{"dim_means": {...}, "dim_stderr": {...}}`}</code> JSON으로
              내보내고, 루프의 <code>measure.py</code>가 그 줄을 파싱합니다.
              출력에는 <code>sample_count</code>, <code>measurement_modality</code>,
              sample별 점수도 포함됩니다. stderr는 평균의 표준오차이며,
              표본 1개의 0은 &quot;안정성 신호 없음&quot;입니다. 집계는
              judge의 점수를 다시 계산해 요약할 뿐 정답으로 인증하지 않습니다.
            </p>

            <h2>audit-mode: 조건 변경이지 샌드박스가 아닙니다</h2>
            <p>
              audit-mode는 비교에 영향을 주는 정책과 로컬 맥락을 조정합니다.
              이것만으로 파일시스템·네트워크 격리나 같은 실행 조건이
              보장되지는 않습니다.
            </p>
            <ul>
              <li>
                <strong>가드레일 전환</strong>
                (<code>evals/petri/audit_mode.py</code>). 한 번의 런에
                한해 쓰기·위험·유료 도구 허용과 자동 승인을 활성화할 수
                있습니다. 활성 모드의 기본 <code>force_dry_run</code>은{" "}
                <code>false</code>입니다. 영구 사용자 정책은 바꾸지 않지만
                실제 부작용은 가능하므로, 격리 환경과 승인된 비용 범위에서만
                사용해야 합니다. 활성화는{" "}
                <code>geode-eval audit --unrestricted</code>,{" "}
                <code>GEODE_AUDIT_UNRESTRICTED=1</code>, 또는{" "}
                <code>.geode/audit-mode.toml</code>입니다.
              </li>
              <li>
                <strong>시스템 프롬프트 strip</strong>
                (<code>core/agent/system_prompt.py</code>의{" "}
                <code>_audit_mode_active</code>). audit-mode에서는 메모리 계층
                같은 GEODE 고유 로컬 컨텍스트를 시스템 프롬프트에서 제거해,
                로컬 맥락의 개입을 줄입니다. 제거한 맥락과 남은 도구·정책도
                평가 조건의 일부입니다.
              </li>
            </ul>
            <p>
              일반 감사 명령이 대조군까지 자동 실행하지는 않습니다. 비교가
              필요하면 같은 조건으로 별도 실행을 구성합니다.{" "}
              <code>target=geode/&lt;model&gt;</code>(audit-mode 적용 wrapped
              agent)과 <code>target=anthropic/&lt;model&gt;</code>(GEODE wrapper
              없는 모델)는 한 예입니다. 관측 차이는 해당 구성의 진단 신호이며,
              반복·불확실성·역할 모델을 통제하지 않은 채 스캐폴드의 순수
              기여분으로 단정할 수 없습니다.
            </p>

            <h2>역할 경계</h2>
            <p>
              Petri judge는 루브릭 점수를 만들고, GEODE의 extractor는 그
              점수를 집계합니다. scaffold-search의 fitness와 gate는 집계를
              후보 선택에 사용합니다. 이들은 서로 다른 판단 단계입니다.
              LLM 점수, 별도 계약 검사, 벤치마크 verifier의 결과를 같은
              성공 지표로 합쳐 부르지 않습니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/petri/run">감사 실행</a>. 플래그와 기본값.</li>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>. 22-dim 루브릭과 18-dim fitness universe.</li>
              <li><a href="/geode/self-improving/petri-bundle/">번들 뷰어</a>. 공개된 transcript와 측정 조건.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Petri explores how an agent behaves in selected scenarios.
              GEODE connects its execution loop as a target through{" "}
              <code>inspect_petri</code> on <a href="https://inspect.aisi.org.uk/">Inspect</a>.
              Scores are an LLM&apos;s judgments against a chosen scenario and
              rubric, not a product-wide safety guarantee or a task success
              rate. <a href="/geode/docs/verification/evaluation?lang=en">Verification
              and evaluation</a> distinguishes runtime checks from benchmark scoring.
            </p>

            <h2>Three model roles</h2>
            <table>
              <thead><tr><th>Role</th><th>What it does</th><th>Meaning of its output</th></tr></thead>
              <tbody>
                <tr><td><strong>Auditor</strong></td><td>Builds the interaction and pressure conditions from a seed.</td><td>Creates the test situation; does not own the final score.</td></tr>
                <tr><td><strong>Target</strong></td><td>GEODE responds and uses tools through <code>geode/&lt;model&gt;</code>.</td><td>The behavior under audit.</td></tr>
                <tr><td><strong>Judge</strong></td><td>Reads the record and applies each dimension&apos;s rubric.</td><td>Per-dimension <code>audit_judge</code> scores, not a substitute for external state checks.</td></tr>
              </tbody>
            </table>
            <p>
              These are three responsibilities, not necessarily three different
              models or providers. Freeze the resolved model and credential route
              for each role, seed and rubric revisions, turn limits, and tool
              conditions. The default <code>--target-tools none</code> disables
              the auditor&apos;s synthetic-tool path; it does not disable all
              of GEODE&apos;s own tools.
            </p>

            <h2>Execution flow</h2>
            <p>
              <code>geode-eval audit</code> enters{" "}
              <code>evals/petri/cli_audit.py</code>, and{" "}
              <code>run_audit</code> in{" "}
              <code>evals/petri/runner.py</code> drives the
              inspect-petri subprocess. <code>.eval</code> is an Inspect
              evaluation log, not a Petri-only score format. Read its execution
              configuration, model roles, sample records and scores, and usage
              together. When archival succeeds, the completed log is preserved outside the worktree at{" "}
              <code>~/.geode/petri/logs/</code>, with a committable summary
              YAML under <code>docs/audits/eval-logs/</code>. Raw inputs and
              outputs may be sensitive; publication requires a separate review.
              The current GEODE target adapter returns response text and usage.
              Do not assume the outer audit log contains every internal GEODE
              tool call.
            </p>
            <p>
              The scaffold-search measurement path consumes the last non-empty
              stdout line. <code>extract_dim_aggregates</code> in{" "}
              <code>core/audit/dim_extractor.py</code> aggregates per-dimension
              judge scores from the <code>.eval</code> archive and emits a JSON
              dict <code>{`{"dim_means": {...}, "dim_stderr": {...}}`}</code>,
              which <code>measure.py</code> parses. The output also includes{" "}
              <code>sample_count</code>, <code>measurement_modality</code>,
              and per-sample scores. Stderr is the standard error of the mean;
              zero from one sample means no stability signal. Aggregation
              summarizes the judge&apos;s scores; it does not certify them as truth.
            </p>

            <h2>Audit-mode changes conditions; it is not a sandbox</h2>
            <p>
              Audit-mode adjusts policies and local context that can affect a
              comparison. It does not itself guarantee filesystem or network
              isolation, or identical execution conditions.
            </p>
            <ul>
              <li>
                <strong>Guardrail switch</strong>
                (<code>evals/petri/audit_mode.py</code>). For one run
                only, it can enable writes, dangerous and paid tools, and
                automatic approval. An enabled mode defaults to{" "}
                <code>force_dry_run=false</code>. Persistent user policy is
                unchanged, but real side effects remain possible: use an
                isolated environment and an approved spending scope. Activated by{" "}
                <code>geode-eval audit --unrestricted</code>,{" "}
                <code>GEODE_AUDIT_UNRESTRICTED=1</code>, or{" "}
                <code>.geode/audit-mode.toml</code>.
              </li>
              <li>
                <strong>System-prompt strip</strong>
                (<code>_audit_mode_active</code> in{" "}
                <code>core/agent/system_prompt.py</code>). Under audit-mode,
                GEODE-specific local context such as the memory hierarchy is
                stripped from the system prompt to reduce local-context
                influence. Removed context and retained tools and policies
                remain part of the evaluation conditions.
              </li>
            </ul>
            <p>
              An ordinary audit command does not automatically run a control.
              Configure separate, matched runs when a comparison is needed.
              For example:{" "}
              <code>target=geode/&lt;model&gt;</code> (the wrapped agent with
              audit-mode applied) versus{" "}
              <code>target=anthropic/&lt;model&gt;</code> (vanilla, no GEODE
              wrapper). The observed difference is diagnostic evidence for
              those configurations, not an isolated scaffold effect without
              controlled role models, repetitions, and uncertainty analysis.
            </p>

            <h2>The role boundary</h2>
            <p>
              Petri&apos;s judge produces rubric scores; GEODE&apos;s extractor
              aggregates them; scaffold-search fitness and gates use those
              aggregates to select candidates. These are separate decisions.
              LLM scores, additional contract checks, and benchmark verifier
              results must not be presented as one interchangeable success metric.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/petri/run?lang=en">Run an audit</a>. Flags and defaults.</li>
              <li><a href="/geode/docs/petri/judge-dimensions?lang=en">Judge dimensions</a>. The 22-dim rubric and the 18-dim fitness universe.</li>
              <li><a href="/geode/self-improving/petri-bundle/">Bundle viewer</a>. Published transcripts and measurement conditions.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
