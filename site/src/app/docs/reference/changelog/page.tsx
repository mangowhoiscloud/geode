import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Changelog — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/changelog"
      title="Changelog"
      titleKo="변경 이력"
      summary="Selected version highlights. The authoritative changelog is CHANGELOG.md in the repository."
      summaryKo="선별된 버전 하이라이트. 정본 changelog는 저장소의 CHANGELOG.md입니다."
    >
      <Bi
        ko={
          <>
            <p>이 페이지는 v0.95 기준 최근 큰 변경만 선별 정리한 highlight reel입니다. 정본은 repo의 <code>CHANGELOG.md</code>.</p>

            <h2>v0.95.0. 2026-05-12</h2>
            <ul>
              <li><strong>Anthropic agentic_call streaming.</strong> <code>messages.stream()</code> async 컨텍스트로 전환. 토큰 트래커는 동일.</li>
              <li><strong>GLM context window 정정.</strong> 200_000 flat → 정확 202_752. <code>tests/test_glm_context_window.py</code> 회귀 가드.</li>
            </ul>

            <h2>v0.94.0. 2026-05-12</h2>
            <ul>
              <li><strong>OpenAI HTML data-URL 가드.</strong> HTML을 <code>data:text/html;base64,...</code>로 emit하는 패턴 차단. raw <code>&lt;!DOCTYPE html&gt;</code> 강제.</li>
              <li><strong>Cross-provider <code>tool_choice</code> 정규화.</strong> 4 프로바이더의 다른 스키마를 통일.</li>
              <li><strong>OpenAI <code>prompt_cache_key</code> auto-derivation.</strong> 프로젝트 식별자 기반.</li>
              <li><strong>GLM thinking 게이트.</strong> <code>thinking.type=&quot;off&quot;|&quot;none&quot;</code>으로 비활성 가능.</li>
            </ul>

            <h2>v0.93.x. 2026-05-12</h2>
            <ul>
              <li><strong>GEODE_PERSONA opt-in 도입.</strong> 시스템 프롬프트의 GEODE 정체성 블록을 환경 변수로 토글.</li>
              <li><strong>audit-mode strip.</strong> Petri audit 실행 시 GEODE 정체성을 자동 strip해 vanilla LLM과 비교 가능한 transcript 생성.</li>
              <li><strong>XML sandwich.</strong> 9 프롬프트 파일에서 16 marker를 XML 경계로 변환. <code>&lt;dynamic_context&gt;</code> 사용.</li>
            </ul>

            <h2>v0.92.0. 2026-05-11</h2>
            <ul>
              <li><strong>4-layer observability.</strong> <code>core.audit.diagnostics</code> 추가로 hook/RunLog/audit/Petri 4 lens 완성.</li>
              <li><strong>Petri × GEODE 통합 시작.</strong> wrapped agent로 자가 misalignment 측정. 자세히: <a href="/docs/petri/overview">Petri Overview</a>.</li>
              <li><strong>Diagnostics 인프라.</strong> per-call assertion record (cache_read/write, cost_breakdown, latency).</li>
            </ul>

            <h2>v0.91.0. 2026-05-11</h2>
            <ul>
              <li><strong>Petri scenarios v1.</strong> 13 GEODE-specific seeds 7 카테고리. <a href="/docs/petri/scenarios">Petri Scenarios</a>.</li>
            </ul>

            <h2>v0.90.0. 2026-05-11</h2>
            <ul>
              <li><strong>Auto-escalation 제거.</strong> AgenticLoop의 자동 escalate 종료를 제거. 모델이 직접 <code>model_action_required</code> 또는 <code>user_clarification_needed</code> emit해야 종료.</li>
              <li><strong>Token tracker dual-record 수정.</strong> codex/glm의 50-64% duplicate 카운팅이 해소.</li>
            </ul>

            <h2>v0.89.x. 2026-05-09</h2>
            <ul>
              <li><strong>LangSmith 100% 제거.</strong> 의존성과 트레이싱 모듈 전부 삭제. 자체 hook + RunLog가 대체. <a href="/docs/verification/observability">Observability</a>.</li>
              <li><strong>SDK lazy loading 3-step.</strong> pydantic + asyncio + importlib.metadata + 14 type-only + 11 late-binding.</li>
            </ul>

            <h2>v0.85.0 ~ v0.89.x. Cold-start 압축</h2>
            <ul>
              <li>SDK lazy loading arc 누적. cold start −258ms, warm −86% (~33ms). modules 341 → 167 (−174).</li>
              <li>v0.87.0 <code>core.lifecycle</code> → <code>core.wiring</code> rename.</li>
              <li>v0.85.0 env_io extract. cli/startup split.</li>
            </ul>

            <h2>v0.66 ~ v0.84. <code>geode audit</code> CLI 도입</h2>
            <ul>
              <li><code>plugins/petri_audit/cli_audit.py</code>의 Typer 래퍼로 audit가 1차 인터페이스화.</li>
              <li><code>--unrestricted</code>, <code>--dim-set</code>, <code>--seed-select</code>, <code>--target-tools</code> 4 옵션.</li>
              <li><code>~/.geode/usage/*.jsonl</code> usage ledger.</li>
            </ul>

            <h2>v0.65.0. 2026-05-02 (이전 highlights)</h2>
            <ul>
              <li>Anthropic 4-breakpoint 프롬프트 캐시. <code>apply_messages_cache_control()</code>이 직전 3개 non-system 메시지에 ephemeral 마커.</li>
              <li><code>manage_login</code> verdict shadowing 수정.</li>
            </ul>

            <h2>v0.64.0. 2026-04-29 (이전)</h2>
            <ul>
              <li><strong>플러그인 네임스페이스 분리.</strong> <code>core/domains/game_ip/</code> → <code>plugins/game_ip/</code>.</li>
            </ul>

            <h2>v0.63.0 ~ v0.50.x (이전)</h2>
            <ul>
              <li>v0.63 라이프사이클 명령어 도입. <code>/stop</code>, <code>/clean</code>, <code>/uninstall</code>, <code>/status</code>.</li>
              <li>v0.62 라이브 테스트 하네스 (<code>-m live</code>).</li>
              <li>v0.60 R3-mini PAYG OpenAI Responses 등가.</li>
              <li>v0.56 Anthropic adaptive thinking <code>xhigh</code> (Opus 4.7).</li>
              <li>v0.50.x Karpathy P4 ratchet 도입. 20 <code>_PINNED_HASHES</code>. <a href="/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>.</li>
            </ul>

            <h2>정본</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code>가 진리원입니다.
              이 페이지는 프로젝트 진화의 형태를 보고 싶은 독자를 위한 선별 highlight입니다.
            </p>
          </>
        }
        en={
          <>
            <p>A curated highlight reel of recent large changes, current to v0.95. The authoritative source is the repository's <code>CHANGELOG.md</code>.</p>

            <h2>v0.95.0. 2026-05-12</h2>
            <ul>
              <li><strong>Anthropic agentic_call streaming.</strong> Switched to <code>messages.stream()</code> async context. Token tracker unchanged.</li>
              <li><strong>GLM context window correction.</strong> Flat 200_000 to the exact 202_752. <code>tests/test_glm_context_window.py</code> guards regression.</li>
            </ul>

            <h2>v0.94.0. 2026-05-12</h2>
            <ul>
              <li><strong>OpenAI HTML data-URL guard.</strong> Blocks the pattern where HTML is emitted as <code>data:text/html;base64,...</code>. Raw <code>&lt;!DOCTYPE html&gt;</code> is enforced.</li>
              <li><strong>Cross-provider <code>tool_choice</code> normalization.</strong> Unifies the four providers' different schemas.</li>
              <li><strong>OpenAI <code>prompt_cache_key</code> auto-derivation.</strong> From the project identifier.</li>
              <li><strong>GLM thinking gate.</strong> <code>thinking.type=&quot;off&quot;|&quot;none&quot;</code> disables thinking.</li>
            </ul>

            <h2>v0.93.x. 2026-05-12</h2>
            <ul>
              <li><strong>GEODE_PERSONA opt-in.</strong> The GEODE identity block in the system prompt is now toggled by an env var or config flag.</li>
              <li><strong>audit-mode strip.</strong> When running a Petri audit, GEODE identity is stripped automatically so the transcript is comparable to a vanilla LLM.</li>
              <li><strong>XML sandwich.</strong> 16 markers across 9 prompt files converted to XML boundaries. <code>&lt;dynamic_context&gt;</code> in use.</li>
            </ul>

            <h2>v0.92.0. 2026-05-11</h2>
            <ul>
              <li><strong>4-layer observability.</strong> Adding <code>core.audit.diagnostics</code> completes the four-lens stack: hook, RunLog, audit, Petri.</li>
              <li><strong>Petri × GEODE integration.</strong> Self-measurement of misalignment via a wrapped agent. Details: <a href="/docs/petri/overview">Petri Overview</a>.</li>
              <li><strong>Diagnostics infrastructure.</strong> Per-call assertion records (cache_read/write, cost_breakdown, latency).</li>
            </ul>

            <h2>v0.91.0. 2026-05-11</h2>
            <ul>
              <li><strong>Petri scenarios v1.</strong> 13 GEODE-specific seeds across 7 categories. See <a href="/docs/petri/scenarios">Petri Scenarios</a>.</li>
            </ul>

            <h2>v0.90.0. 2026-05-11</h2>
            <ul>
              <li><strong>Auto-escalation removed.</strong> AgenticLoop no longer escalates automatically; the model itself must emit <code>model_action_required</code> or <code>user_clarification_needed</code> to terminate.</li>
              <li><strong>Token-tracker dual-record fix.</strong> Resolved 50-64 percent duplicate counting on codex / glm.</li>
            </ul>

            <h2>v0.89.x. 2026-05-09</h2>
            <ul>
              <li><strong>LangSmith removed completely.</strong> Dependency and tracing module deleted. Native hook + RunLog replace it. See <a href="/docs/verification/observability">Observability</a>.</li>
              <li><strong>SDK lazy loading, 3-step.</strong> pydantic + asyncio + importlib.metadata + 14 type-only + 11 late-binding.</li>
            </ul>

            <h2>v0.85.0 to v0.89.x. Cold-start compression</h2>
            <ul>
              <li>Cumulative SDK lazy-loading arc. Cold start dropped 258ms, warm down 86 percent (~33ms). Modules 341 to 167 (−174).</li>
              <li>v0.87.0 <code>core.lifecycle</code> renamed to <code>core.wiring</code>.</li>
              <li>v0.85.0 env_io extract. cli / startup split.</li>
            </ul>

            <h2>v0.66 to v0.84. <code>geode audit</code> CLI</h2>
            <ul>
              <li>The Typer wrapper at <code>plugins/petri_audit/cli_audit.py</code> makes audit a first-class CLI.</li>
              <li>Four options: <code>--unrestricted</code>, <code>--dim-set</code>, <code>--seed-select</code>, <code>--target-tools</code>.</li>
              <li>Usage ledger at <code>~/.geode/usage/*.jsonl</code>.</li>
            </ul>

            <h2>v0.65.0. 2026-05-02 (earlier highlights)</h2>
            <ul>
              <li>Anthropic 4-breakpoint prompt cache. <code>apply_messages_cache_control()</code> rolls ephemeral markers across the last three non-system messages.</li>
              <li><code>manage_login</code> verdict shadowing fix.</li>
            </ul>

            <h2>v0.64.0. 2026-04-29 (earlier)</h2>
            <ul>
              <li><strong>Plugin namespace split.</strong> <code>core/domains/game_ip/</code> to <code>plugins/game_ip/</code>.</li>
            </ul>

            <h2>v0.63.0 to v0.50.x (earlier)</h2>
            <ul>
              <li>v0.63 lifecycle commands: <code>/stop</code>, <code>/clean</code>, <code>/uninstall</code>, <code>/status</code>.</li>
              <li>v0.62 live test harness (<code>-m live</code>).</li>
              <li>v0.60 R3-mini PAYG OpenAI Responses parity.</li>
              <li>v0.56 Anthropic adaptive thinking <code>xhigh</code> (Opus 4.7).</li>
              <li>v0.50.x Karpathy P4 ratchet introduced. 20 <code>_PINNED_HASHES</code>. See <a href="/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>.</li>
            </ul>

            <h2>Authoritative source</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code> is the source of truth. This page is a
              curated highlight reel for readers who want the shape of the project's evolution rather than the
              per-feature granularity.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
