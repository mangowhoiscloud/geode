import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Run an audit — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/run"
      title="Run an audit"
      titleKo="감사 실행"
      summary="geode audit, or inspect eval for the raw path. Choose model roles, dimension set, seeds, and turn budget. Dry-run by default."
      summaryKo="geode audit, 또는 raw 경로인 inspect eval을 씁니다. 모델 역할, 차원 세트, seeds, 턴 예산을 고릅니다. 기본은 dry-run입니다."
    >
      <Bi
        ko={
          <>
            <p>
              Petri × GEODE 감사를 한 번 끝까지 돌리는 절차입니다. 기본값이
              비용을 지키는 쪽으로 설계되어 있어서, 아무 플래그 없이 돌리면
              실제 LLM 호출 없이 dry-run으로 끝납니다. 실측은 명시적으로
              올립니다.
            </p>

            <h2>준비물</h2>
            <ul>
              <li>GEODE 소스 체크아웃과 <code>[audit]</code> extra. <code>uv tool install -e &quot;.[audit]&quot;</code>로 <code>inspect_ai</code>가 함께 설치됩니다.</li>
              <li>auditor, target, judge 세 역할의 자격. 역할 플래그를 생략하면 <code>~/.geode/config.toml</code>의 역할 SoT를 읽습니다.</li>
            </ul>

            <h2>기본 명령</h2>
            <pre>{`# 1) dry-run (기본값). 명령 조립과 seed 해석만 검증
geode audit

# 2) 실측. live로 올리고 audit-mode 가드레일 전환
geode audit --live --unrestricted \\
  --seeds 3 --max-turns 10`}</pre>
            <p>
              같은 인터페이스가 세션 안에서는 <code>/audit</code> 슬래시
              명령입니다. 둘 다{" "}
              <code>plugins/petri_audit/cli_audit.py</code>로 들어갑니다.
            </p>

            <h2>플래그</h2>
            <table>
              <thead><tr><th>플래그</th><th>의미</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>--auditor/-a</code> · <code>--target/-t</code> · <code>--judge/-j</code></td><td>역할별 모델 지정</td><td>생략 시 <code>~/.geode/config.toml</code> 역할 SoT</td></tr>
                <tr><td><code>--dry-run/--live</code></td><td>실제 호출 없이 검증 / 실측</td><td><strong>dry-run</strong></td></tr>
                <tr><td><code>--seeds/-s</code></td><td>seed 수</td><td>1</td></tr>
                <tr><td><code>--seed-select</code></td><td>seed 풀 경로 또는 id 선택</td><td><code>plugins/petri_audit/seeds</code></td></tr>
                <tr><td><code>--max-turns/-m</code></td><td>대화 턴 상한</td><td>10</td></tr>
                <tr><td><code>--dim-set</code></td><td>judge 차원 세트. <code>subset</code>(22-dim 루브릭) 또는 <code>full</code>(upstream 기본 전체)</td><td><code>subset</code></td></tr>
                <tr><td><code>--unrestricted</code></td><td>audit-mode 가드레일 전환 (HITL 해제, 한 런 한정). <code>GEODE_AUDIT_UNRESTRICTED=1</code>과 동일</td><td>off</td></tr>
                <tr><td><code>--cache/--no-cache</code></td><td>inspect_ai trajectory 캐시</td><td><strong>off</strong>. 캐시된 실패 응답이 후속 측정을 오염시키는 것을 막기 위해 기본 비활성</td></tr>
                <tr><td><code>--target-tools</code></td><td><code>real</code> 또는 <code>synthetic</code> 도구 표면</td><td>없음</td></tr>
                <tr><td><code>--tags</code></td><td>런 태깅</td><td>없음</td></tr>
                <tr><td><code>--yes/-y</code></td><td>confirm 생략</td><td>off</td></tr>
                <tr><td><code>--use-oauth/--no-oauth</code></td><td>OAuth 자격 lane 강제</td><td>없음</td></tr>
              </tbody>
            </table>

            <h2>결과 읽기</h2>
            <p>
              런이 끝나면 <code>.eval</code> 아카이브가 워크트리 밖{" "}
              <code>~/.geode/petri/logs/</code>에 남고, stdout 마지막 줄에{" "}
              <code>{`{"dim_means": {...}, "dim_stderr": {...}}`}</code> JSON이
              찍힙니다. 자기개선 루프가 파싱하는 줄이 바로 이것입니다.
            </p>
            <pre>{`# 아카이브 보존 + 커밋 가능한 요약 YAML 생성
geode petri-archive

# transcript를 Inspect 뷰어로
inspect view --log-dir ~/.geode/petri/logs/`}</pre>
            <p>
              publish된 번들은{" "}
              <a href="/geode/self-improving/petri-bundle/">/geode/self-improving/petri-bundle/</a>에서
              바로 볼 수 있습니다.
            </p>

            <h2>raw 경로: <code>inspect eval</code></h2>
            <p>
              Petri 프레임워크의 원시 명령입니다. GEODE wrapper를 우회하므로
              vanilla LLM baseline을 측정할 때 씁니다.
            </p>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=<m> \\
  --model-role target=anthropic/<m> \\
  --model-role judge=<m>`}</pre>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>. 점수의 의미.</li>
              <li><a href="/geode/docs/petri/scenarios">시나리오</a>. seed 풀의 구조.</li>
              <li><a href="/geode/docs/ops/cost">비용 모니터링</a>. 감사 비용 추적.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              This guide runs a Petri × GEODE audit end to end. The defaults
              are designed to protect your budget: with no flags at all,{" "}
              <code>geode audit</code> finishes as a dry-run with no real LLM
              calls. Going live is an explicit step.
            </p>

            <h2>Prerequisites</h2>
            <ul>
              <li>A GEODE source checkout with the <code>[audit]</code> extra: <code>uv tool install -e &quot;.[audit]&quot;</code> brings in <code>inspect_ai</code>.</li>
              <li>Credentials for the auditor, target, and judge roles. Omitted role flags fall back to the role SoT in <code>~/.geode/config.toml</code>.</li>
            </ul>

            <h2>The basic command</h2>
            <pre>{`# 1) dry-run (the default). validates command assembly + seed resolution
geode audit

# 2) real measurement. go live and lift guardrails for the run
geode audit --live --unrestricted \\
  --seeds 3 --max-turns 10`}</pre>
            <p>
              The same interface exists in-session as the <code>/audit</code>{" "}
              slash command. Both enter{" "}
              <code>plugins/petri_audit/cli_audit.py</code>.
            </p>

            <h2>Flags</h2>
            <table>
              <thead><tr><th>Flag</th><th>Meaning</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>--auditor/-a</code> · <code>--target/-t</code> · <code>--judge/-j</code></td><td>Model per role</td><td>Omit to use the role SoT in <code>~/.geode/config.toml</code></td></tr>
                <tr><td><code>--dry-run/--live</code></td><td>Validate without real calls / measure</td><td><strong>dry-run</strong></td></tr>
                <tr><td><code>--seeds/-s</code></td><td>Seed count</td><td>1</td></tr>
                <tr><td><code>--seed-select</code></td><td>Seed pool path or id selection</td><td><code>plugins/petri_audit/seeds</code></td></tr>
                <tr><td><code>--max-turns/-m</code></td><td>Conversation turn cap</td><td>10</td></tr>
                <tr><td><code>--dim-set</code></td><td>Judge dimension set: <code>subset</code> (the 22-dim rubric) or <code>full</code> (the upstream default set)</td><td><code>subset</code></td></tr>
                <tr><td><code>--unrestricted</code></td><td>Audit-mode guardrail lift (HITL off, one run only); same as <code>GEODE_AUDIT_UNRESTRICTED=1</code></td><td>off</td></tr>
                <tr><td><code>--cache/--no-cache</code></td><td>inspect_ai trajectory cache</td><td><strong>off</strong>, so a cached failure response cannot pollute later measurements</td></tr>
                <tr><td><code>--target-tools</code></td><td><code>real</code> or <code>synthetic</code> tool surface</td><td>none</td></tr>
                <tr><td><code>--tags</code></td><td>Tag the run</td><td>none</td></tr>
                <tr><td><code>--yes/-y</code></td><td>Skip the confirm prompt</td><td>off</td></tr>
                <tr><td><code>--use-oauth/--no-oauth</code></td><td>Force the OAuth credential lane</td><td>none</td></tr>
              </tbody>
            </table>

            <h2>Reading the result</h2>
            <p>
              A finished run leaves the <code>.eval</code> archive outside the
              worktree at <code>~/.geode/petri/logs/</code>, and prints a final
              stdout line of JSON:{" "}
              <code>{`{"dim_means": {...}, "dim_stderr": {...}}`}</code>. That
              line is exactly what the self-improving loop parses.
            </p>
            <pre>{`# preserve the archive + write a committable summary YAML
geode petri-archive

# browse the transcript in the Inspect viewer
inspect view --log-dir ~/.geode/petri/logs/`}</pre>
            <p>
              Published bundles are browsable at{" "}
              <a href="/geode/self-improving/petri-bundle/">/geode/self-improving/petri-bundle/</a>.
            </p>

            <h2>The raw path: <code>inspect eval</code></h2>
            <p>
              The raw Petri-framework command. It bypasses the GEODE wrapper,
              which is what you want when measuring a vanilla-LLM baseline.
            </p>
            <pre>{`inspect eval inspect_petri/audit \\
  --model-role auditor=<m> \\
  --model-role target=anthropic/<m> \\
  --model-role judge=<m>`}</pre>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a>. What the scores mean.</li>
              <li><a href="/geode/docs/petri/scenarios">Scenarios</a>. How the seed pool is organized.</li>
              <li><a href="/geode/docs/ops/cost">Cost monitoring</a>. Tracking audit spend.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
