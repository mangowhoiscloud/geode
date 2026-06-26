import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Petri × GEODE — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/overview"
      title="Petri × GEODE"
      titleKo="Petri × GEODE"
      summary="Anthropic Alignment Science's evaluation framework, wrapped over the GEODE agent as the loop's measurement layer."
      summaryKo="Anthropic Alignment Science의 평가 프레임워크를 GEODE 에이전트 위에 얹어 루프의 측정 계층으로 씁니다."
    >
      <Bi
        ko={
          <>
            <p>
              자기개선 루프에서 Petri는 측정 계층입니다. 스캐폴드 변이가
              실제로 더 안전한 에이전트를 만드는지는 주장이 아니라 적대적
              감사로 판정해야 하므로, GEODE는 Petri를 wrapped agent로
              통합했습니다. Petri(Parallel Exploration Tool for Risky
              Interactions)는 Anthropic Alignment Science가 만든 alignment
              audit 프레임워크로, <a href="https://inspect.aisi.org.uk/">inspect_ai</a>(UK
              AISI) 위에 구현되며 <a href="https://meridianlabs.ai">Meridian
              Labs</a>가 <code>inspect_petri</code>(MIT)로 유지합니다.
            </p>

            <h2>세 가지 모델 역할</h2>
            <table>
              <thead><tr><th>역할</th><th>하는 일</th></tr></thead>
              <tbody>
                <tr><td><strong>Auditor</strong></td><td>target을 misalign 방향으로 유도하는 적대적 에이전트</td></tr>
                <tr><td><strong>Target</strong></td><td>측정 대상. GEODE wrapped agent 또는 vanilla LLM</td></tr>
                <tr><td><strong>Judge</strong></td><td>transcript를 차원별로 채점하는 평가자</td></tr>
              </tbody>
            </table>

            <h2>실행 흐름</h2>
            <p>
              <code>geode audit</code>(Typer)과 <code>/audit</code>(슬래시)은
              모두 <code>plugins/petri_audit/cli_audit.py</code>로 들어와{" "}
              <code>plugins/petri_audit/runner.py</code>의{" "}
              <code>run_audit</code>이 inspect-petri 서브프로세스를 돌립니다.
              끝난 <code>.eval</code> 아카이브는 워크트리 밖{" "}
              <code>~/.geode/petri/logs/</code>에 보존되고, 커밋 가능한 요약
              YAML이 <code>docs/audits/eval-logs/</code>에 남습니다.
            </p>
            <p>
              루프가 소비하는 출력은 stdout의 마지막 비어 있지 않은 줄
              하나입니다. <code>core/audit/dim_extractor.py</code>의{" "}
              <code>extract_dim_aggregates</code>가 <code>.eval</code>{" "}
              아카이브에서 차원별 judge 점수를 집계해{" "}
              <code>{`{"dim_means": {...}, "dim_stderr": {...}}`}</code> JSON으로
              내보내고, 루프의 <code>measure.py</code>가 그 줄을 파싱합니다.
              stderr는 평균의 표준오차입니다. 표본이 1개면 0이 되는데, 이
              0은 &quot;완벽한 안정성&quot;이 아니라 &quot;안정성 신호
              없음&quot;으로 읽어야 합니다.
            </p>

            <h2>audit-mode: 스캐폴드만 측정하기</h2>
            <p>
              측정이 운영자의 로컬 맥락에 오염되면 비교가 성립하지 않습니다.
              두 장치가 이를 막습니다.
            </p>
            <ul>
              <li>
                <strong>가드레일 전환</strong>
                (<code>plugins/petri_audit/audit_mode.py</code>). 한 번의 런에
                한해 HITL 승인을 끄고 dry-run을 강제하는 등 영구 정책을
                건드리지 않고 감사용 상태로 전환합니다. 활성화는{" "}
                <code>geode audit --unrestricted</code>,{" "}
                <code>GEODE_AUDIT_UNRESTRICTED=1</code>, 또는{" "}
                <code>.geode/audit-mode.toml</code>입니다.
              </li>
              <li>
                <strong>시스템 프롬프트 strip</strong>
                (<code>core/agent/system_prompt.py</code>의{" "}
                <code>_audit_mode_active</code>). audit-mode에서는 메모리 계층
                같은 GEODE 고유 로컬 컨텍스트를 시스템 프롬프트에서 제거해,
                Petri가 운영자의 환경이 아니라 측정 대상 스캐폴드를 재게
                합니다.
              </li>
            </ul>
            <p>
              비교 하네스는 같은 seed를 두 번 돌립니다.{" "}
              <code>target=geode/&lt;model&gt;</code>(audit-mode 적용 wrapped
              agent)과 <code>target=anthropic/&lt;model&gt;</code>(GEODE wrapper
              없는 vanilla)입니다. 둘의 차이가 스캐폴드의 기여분입니다.
            </p>

            <h2>역할 경계</h2>
            <p>
              무엇을 측정하는가(루브릭, judge, <code>dim_extractor</code>
              출력)는 Petri 쪽이 소유합니다. 측정이 어떻게 선택 신호로
              쌓이는가(티어, 가중치, 게이트)는 루프의 train 단계와 fitness가
              소유합니다. 원시 측정을 다시 구현하는 코드 경로는 없습니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/petri/run">감사 실행</a>. 플래그와 기본값.</li>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>. 22-dim 루브릭과 18-dim fitness universe.</li>
              <li><a href="/geode/self-improving/petri-bundle/">번들 뷰어</a>. 최신 공개 transcript.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              In the self-improving loop, Petri is the measurement layer.
              Whether a scaffold mutation actually produces a safer agent must
              be settled by adversarial audit, not by assertion, so GEODE
              integrates Petri over itself as a wrapped agent. Petri (Parallel
              Exploration Tool for Risky Interactions) is an alignment-audit
              framework built by Anthropic Alignment Science, implemented on{" "}
              <a href="https://inspect.aisi.org.uk/">inspect_ai</a> (UK AISI)
              and maintained by{" "}
              <a href="https://meridianlabs.ai">Meridian Labs</a> as{" "}
              <code>inspect_petri</code> (MIT).
            </p>

            <h2>Three model roles</h2>
            <table>
              <thead><tr><th>Role</th><th>What it does</th></tr></thead>
              <tbody>
                <tr><td><strong>Auditor</strong></td><td>Adversarial agent that steers the target toward misalignment.</td></tr>
                <tr><td><strong>Target</strong></td><td>The system under test. GEODE wrapped agent or a vanilla LLM.</td></tr>
                <tr><td><strong>Judge</strong></td><td>Scores the transcript per dimension.</td></tr>
              </tbody>
            </table>

            <h2>Execution flow</h2>
            <p>
              <code>geode audit</code> (Typer) and <code>/audit</code> (slash)
              both enter <code>plugins/petri_audit/cli_audit.py</code>, and{" "}
              <code>run_audit</code> in{" "}
              <code>plugins/petri_audit/runner.py</code> drives the
              inspect-petri subprocess. The finished <code>.eval</code> archive
              is preserved outside the worktree at{" "}
              <code>~/.geode/petri/logs/</code>, with a committable summary
              YAML under <code>docs/audits/eval-logs/</code>.
            </p>
            <p>
              The loop consumes exactly one line of output: the last non-empty
              stdout line. <code>extract_dim_aggregates</code> in{" "}
              <code>core/audit/dim_extractor.py</code> aggregates per-dimension
              judge scores from the <code>.eval</code> archive and emits a JSON
              dict <code>{`{"dim_means": {...}, "dim_stderr": {...}}`}</code>,
              which the loop&apos;s <code>measure.py</code> parses. The stderr
              is the standard error of the mean; with a single sample it is
              zero, which reads as &quot;no stability signal&quot;, not
              &quot;perfect stability&quot;.
            </p>

            <h2>Audit-mode: measure the scaffold, not the operator</h2>
            <p>
              If the measurement absorbs the operator&apos;s local context, the
              comparison stops meaning anything. Two mechanisms prevent that.
            </p>
            <ul>
              <li>
                <strong>Guardrail switch</strong>
                (<code>plugins/petri_audit/audit_mode.py</code>). For one run
                only, it disables HITL approval and forces dry-run, without
                touching persistent user policy. Activated by{" "}
                <code>geode audit --unrestricted</code>,{" "}
                <code>GEODE_AUDIT_UNRESTRICTED=1</code>, or{" "}
                <code>.geode/audit-mode.toml</code>.
              </li>
              <li>
                <strong>System-prompt strip</strong>
                (<code>_audit_mode_active</code> in{" "}
                <code>core/agent/system_prompt.py</code>). Under audit-mode,
                GEODE-specific local context such as the memory hierarchy is
                stripped from the system prompt, so Petri measures the scaffold
                under test rather than the operator&apos;s environment.
              </li>
            </ul>
            <p>
              The comparison harness runs each seed twice:{" "}
              <code>target=geode/&lt;model&gt;</code> (the wrapped agent with
              audit-mode applied) versus{" "}
              <code>target=anthropic/&lt;model&gt;</code> (vanilla, no GEODE
              wrapper). The delta is the scaffold&apos;s contribution.
            </p>

            <h2>The role boundary</h2>
            <p>
              Petri owns what gets measured: the rubric, the judge, and the{" "}
              <code>dim_extractor</code> output. The loop&apos;s train and
              fitness own how measurement accrues into a selection signal:
              tiers, weights, the gate. No code path re-implements raw
              measurement.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/petri/run">Run an audit</a>. Flags and defaults.</li>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a>. The 22-dim rubric and the 18-dim fitness universe.</li>
              <li><a href="/geode/self-improving/petri-bundle/">Bundle viewer</a>. The latest published transcripts.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
