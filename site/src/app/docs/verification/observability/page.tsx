import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Observability — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/observability"
      title="Observability"
      titleKo="관측성"
      summary="Four native lenses: hooks, RunLog, audit diagnostics, Petri. Vendor-free since v0.89.0."
      summaryKo="자체 4-lens 스택: 훅, RunLog, audit diagnostics, Petri. v0.89.0 이후 vendor-free 관측성."
    >
      <Bi
        ko={
          <>
            <p>
              <strong>Reference:</strong> GEODE는 v0.89.0에서 외부 SaaS tracing 의존을 제거하고 4개의 자체 관측 렌즈로 전환했습니다.
              각 렌즈는 다른 시간 단위와 grain을 가지며, 서로 보완합니다. 한 호출의 lifecycle 전체가 4 렌즈에 모두 기록되도록 설계.
            </p>

            <h2>4-Lens 구조</h2>
            <table>
              <thead><tr><th>렌즈</th><th>관측 단위</th><th>grain</th><th>위치</th><th>도입</th></tr></thead>
              <tbody>
                <tr><td><strong>Hooks</strong></td><td>이벤트 (81개)</td><td>micro (μs to ms)</td><td><code>core/hooks/system.py</code></td><td>core</td></tr>
                <tr><td><strong>RunLog</strong></td><td>run (LLM 호출 1회)</td><td>medium (s)</td><td><code>~/.geode/runlog/</code> JSONL</td><td>core</td></tr>
                <tr><td><strong>Audit diagnostics</strong></td><td>call (input/output/cost)</td><td>per-call (assertion-grade)</td><td><code>core.audit.diagnostics</code></td><td>v0.92.0</td></tr>
                <tr><td><strong>Petri Audit</strong></td><td>scenario (N seeds × M turns)</td><td>session (min to hour)</td><td><a href="/geode/docs/petri/overview">Petri × GEODE</a></td><td>v0.92.0+</td></tr>
              </tbody>
            </table>

            <h2>렌즈 1. Hook 시스템</h2>
            <p>
              가장 빠른 grain. 모든 lifecycle 이벤트가 발화되고, 14 카테고리로 그룹화됩니다.
              listener는 <code>trigger</code> (fire-and-forget) / <code>trigger_with_result</code> (결과 수집) / <code>trigger_interceptor</code> (intercept 가능) 셋 중 하나로 등록.
            </p>
            <table>
              <thead><tr><th>카테고리</th><th>이벤트 개수</th><th>대표 이벤트</th></tr></thead>
              <tbody>
                <tr><td>pipeline</td><td>3</td><td>PIPELINE_START, PIPELINE_END, PIPELINE_ERROR</td></tr>
                <tr><td>node</td><td>4</td><td>NODE_ENTER, NODE_EXIT, NODE_ERROR, NODE_RETRY</td></tr>
                <tr><td>analysis</td><td>3</td><td>ANALYST_START, ANALYST_COMPLETE, ANALYST_FAILED</td></tr>
                <tr><td>verification</td><td>2</td><td>VERIFICATION_PASS, VERIFICATION_FAIL</td></tr>
                <tr><td>automation</td><td>5</td><td>DRIFT_DETECTED, MODEL_PROMOTED, OUTCOME_COLLECTED, EXPERT_VOTE_CAST, FEEDBACK_PHASE_CHANGED</td></tr>
                <tr><td>memory</td><td>4</td><td>MEMORY_SAVED, RULE_CREATED, RULE_UPDATED, RULE_DELETED</td></tr>
                <tr><td>tool</td><td>8</td><td>TOOL_EXEC_START/END/FAILED, TOOL_RECOVERY_START/END, TOOL_APPROVAL_REQUEST/GRANTED/DENIED</td></tr>
                <tr><td>session</td><td>2</td><td>SESSION_START, SESSION_END</td></tr>
                <tr><td>model</td><td>1</td><td>MODEL_SWITCHED</td></tr>
                <tr><td>llm</td><td>4</td><td>LLM_CALL_START, LLM_CALL_END, LLM_CALL_FAILED, LLM_CALL_RETRY</td></tr>
                <tr><td>approval</td><td>2</td><td>APPROVAL_REQUEST, APPROVAL_GRANTED</td></tr>
                <tr><td>context</td><td>2</td><td>CONTEXT_OVERFLOW, CONTEXT_RESET</td></tr>
                <tr><td>prompt</td><td>1</td><td>PROMPT_ASSEMBLED</td></tr>
                <tr><td>(reserved)</td><td>17</td><td>plugin-specific, 도메인 어댑터가 추가</td></tr>
              </tbody>
            </table>
            <p>
              자세히: <a href="/geode/docs/harness/hooks">Hook System</a>.
            </p>

            <h2>렌즈 2. RunLog</h2>
            <p>
              한 LLM 호출 (run) 단위로 input/output/tool call/reasoning을 시계열로 보관합니다. JSONL 한 파일이 한 run.
            </p>
            <pre>{`# 위치
~/.geode/runlog/<YYYY-MM-DD>/<run-id>.jsonl

# 한 줄 record
{"ts": "...", "kind": "llm_call_start", "model": "claude-opus-4-7", "input_tokens": 1284, ...}
{"ts": "...", "kind": "tool_exec_start", "name": "search_subjects", ...}
{"ts": "...", "kind": "tool_exec_end", "name": "search_subjects", "duration_ms": 312, ...}
{"ts": "...", "kind": "llm_call_end", "output_tokens": 482, "cache_read_tokens": 28000, ...}
{"ts": "...", "kind": "run_end", "total_cost_usd": 0.0127, ...}`}</pre>
            <p>
              <code>inspect view ~/.geode/runlog/...</code>로 transcript viewer에서 재생 가능.
              <code>kind</code> 종류는 hook 이벤트와 1대1 대응.
            </p>

            <h2>렌즈 3. Audit Diagnostics (v0.92.0+)</h2>
            <p>
              Petri audit가 require하는 per-call assertion 데이터. cache_read/cache_write 메타 + input/output hash + provider response 원본 + cost decomposition.
              한 호출의 모든 결정 가능 데이터를 재현 가능한 형태로 저장.
            </p>
            <pre>{`# core/audit/diagnostics.py
@dataclass
class CallDiagnostic:
    run_id: str
    call_seq: int                       # run 안에서 N번째 호출
    provider: str                       # anthropic / openai / glm / codex
    model: str                          # claude-opus-4-7 등
    input_hash: str                     # SHA-256[:12] of input
    output_hash: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int              # 캐시 hit
    cache_write_tokens: int             # 캐시 write
    reasoning_tokens: int | None        # extended thinking
    cost_usd: float
    cost_breakdown: dict                # {input, output, cache_read, cache_write, reasoning}
    latency_ms: int
    audit_mode: bool                    # Petri audit 여부`}</pre>
            <p>
              v0.92.0 도입. v0.93+ Petri audit-mode가 이 데이터를 1차 사료로 활용해 시나리오의 재현성을 보장합니다.
            </p>

            <h2>렌즈 4. Petri Audit</h2>
            <p>
              세션 단위 grain. N seeds × M turns의 격자로 misalignment risk를 측정. Auditor(적대) · Target(GEODE) · Judge 3-role 구성.
            </p>
            <ul>
              <li>전체 통합: <a href="/geode/docs/petri/overview">Petri × GEODE Integration</a></li>
              <li>시나리오: <a href="/geode/docs/petri/scenarios">Petri Scenarios</a> (173 default + 13 GEODE-specific)</li>
              <li>실행: <a href="/geode/docs/petri/run">Petri Run</a></li>
              <li>차원: <a href="/geode/docs/petri/judge-dimensions">17/38 Judge 차원</a></li>
            </ul>

            <h2>Usage Ledger (v0.66+)</h2>
            <p>
              비용 추적 전용 append-only ledger. <code>~/.geode/usage/&lt;date&gt;.jsonl</code>에 LLM 호출 단위로 token 분해와 cost가 기록됩니다.
              v0.90.0에서 token tracker dual-record 버그를 수정해 codex/glm의 50-64% duplicate 카운팅이 해소되었습니다.
            </p>
            <pre>{`$ geode history --last 24h
$ jq '.cost_usd | add' ~/.geode/usage/2026-05-12.jsonl  # 합계
$ jq -c 'select(.cache_read_tokens > 0)' ~/.geode/usage/2026-05-12.jsonl  # 캐시 hit만`}</pre>

            <h2>어떤 렌즈를 언제 쓰나</h2>
            <table>
              <thead><tr><th>질문</th><th>1차 렌즈</th><th>보조</th></tr></thead>
              <tbody>
                <tr><td>왜 이 도구가 호출됐지?</td><td>RunLog (run 단위 trace)</td><td>Hook <code>TOOL_EXEC_*</code></td></tr>
                <tr><td>비용이 어디로 갔지?</td><td>Usage ledger</td><td>Hook <code>LLM_CALL_END</code> 집계</td></tr>
                <tr><td>이 호출이 캐시를 어떻게 썼지?</td><td>Audit diagnostics (cache_read/write)</td><td>RunLog</td></tr>
                <tr><td>같은 입력이 재현되나?</td><td>Audit diagnostics (input_hash)</td><td>RunLog 비교</td></tr>
                <tr><td>이 에이전트가 안전한가?</td><td>Petri audit (시나리오)</td><td>Hook <code>VERIFICATION_FAIL</code></td></tr>
                <tr><td>긴 세션에서 어디서 막혔지?</td><td>Hook <code>CONTEXT_OVERFLOW</code></td><td>RunLog timeline</td></tr>
              </tbody>
            </table>

            <h2>외부 어댑터</h2>
            <p>
              자체 stack이 1차지만, 외부 dashboard로 export 필요시 두 가지 경로가 있습니다.
            </p>
            <ul>
              <li><strong>OpenTelemetry</strong>. Hook listener를 OTel exporter로 wrapping해 Tempo/Jaeger/Grafana로 흘림.</li>
              <li><strong>inspect viewer</strong>. RunLog JSONL을 그대로 inspect 명령에 입력해 transcript UI로 본다 (Petri 결과와 동일 viewer).</li>
            </ul>

            <h2>왜 자체 스택인가</h2>
            <ul>
              <li>외부 SaaS lock-in 제거.</li>
              <li>관측 데이터를 GEODE 내부에서 직접 소유 (RunLog).</li>
              <li>외부 tracing SDK의 import-time cost가 cold-start lazy loading arc (v0.85-89)와 충돌.</li>
            </ul>
            <p>
              v0.89.0에서 외부 tracing 의존성 + 별도 tracing 모듈을 제거했습니다. 이 페이지 4 렌즈가 정식 관측 경로입니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              <strong>Reference:</strong> in v0.89.0 GEODE removed its external SaaS tracing dependency and switched to four native
              observability lenses. Each lens has a different time grain and is complementary; the full lifecycle of a
              single call is captured across all four.
            </p>

            <h2>The 4-lens structure</h2>
            <table>
              <thead><tr><th>Lens</th><th>Unit</th><th>Grain</th><th>Where</th><th>Since</th></tr></thead>
              <tbody>
                <tr><td><strong>Hooks</strong></td><td>events (81)</td><td>micro (μs to ms)</td><td><code>core/hooks/system.py</code></td><td>core</td></tr>
                <tr><td><strong>RunLog</strong></td><td>run (one LLM call)</td><td>medium (seconds)</td><td><code>~/.geode/runlog/</code> JSONL</td><td>core</td></tr>
                <tr><td><strong>Audit diagnostics</strong></td><td>call (input/output/cost)</td><td>per-call assertion-grade</td><td><code>core.audit.diagnostics</code></td><td>v0.92.0</td></tr>
                <tr><td><strong>Petri Audit</strong></td><td>scenario (N seeds × M turns)</td><td>session (minutes to hours)</td><td><a href="/geode/docs/petri/overview">Petri × GEODE</a></td><td>v0.92.0+</td></tr>
              </tbody>
            </table>

            <h2>Lens 1. Hook system</h2>
            <p>
              The fastest grain. Every lifecycle event fires; events are grouped into 14 categories.
              Listeners register via one of three trigger modes: <code>trigger</code> (fire-and-forget),
              <code>trigger_with_result</code> (collect handler return values), or <code>trigger_interceptor</code> (can block or modify the event).
            </p>
            <table>
              <thead><tr><th>Category</th><th>Events</th><th>Examples</th></tr></thead>
              <tbody>
                <tr><td>pipeline</td><td>3</td><td>PIPELINE_START, PIPELINE_END, PIPELINE_ERROR</td></tr>
                <tr><td>node</td><td>4</td><td>NODE_ENTER, NODE_EXIT, NODE_ERROR, NODE_RETRY</td></tr>
                <tr><td>analysis</td><td>3</td><td>ANALYST_START, ANALYST_COMPLETE, ANALYST_FAILED</td></tr>
                <tr><td>verification</td><td>2</td><td>VERIFICATION_PASS, VERIFICATION_FAIL</td></tr>
                <tr><td>automation</td><td>5</td><td>DRIFT_DETECTED, MODEL_PROMOTED, OUTCOME_COLLECTED, EXPERT_VOTE_CAST, FEEDBACK_PHASE_CHANGED</td></tr>
                <tr><td>memory</td><td>4</td><td>MEMORY_SAVED, RULE_CREATED, RULE_UPDATED, RULE_DELETED</td></tr>
                <tr><td>tool</td><td>8</td><td>TOOL_EXEC_START/END/FAILED, TOOL_RECOVERY_START/END, TOOL_APPROVAL_REQUEST/GRANTED/DENIED</td></tr>
                <tr><td>session</td><td>2</td><td>SESSION_START, SESSION_END</td></tr>
                <tr><td>model</td><td>1</td><td>MODEL_SWITCHED</td></tr>
                <tr><td>llm</td><td>4</td><td>LLM_CALL_START, LLM_CALL_END, LLM_CALL_FAILED, LLM_CALL_RETRY</td></tr>
                <tr><td>approval</td><td>2</td><td>APPROVAL_REQUEST, APPROVAL_GRANTED</td></tr>
                <tr><td>context</td><td>2</td><td>CONTEXT_OVERFLOW, CONTEXT_RESET</td></tr>
                <tr><td>prompt</td><td>1</td><td>PROMPT_ASSEMBLED</td></tr>
                <tr><td>(reserved)</td><td>17</td><td>plugin-specific, added by external packages</td></tr>
              </tbody>
            </table>
            <p>
              Details: <a href="/geode/docs/harness/hooks">Hook System</a>.
            </p>

            <h2>Lens 2. RunLog</h2>
            <p>
              Per LLM call (one run), captures input, output, tool calls, and reasoning as a time series.
              One JSONL file per run.
            </p>
            <pre>{`# Location
~/.geode/runlog/<YYYY-MM-DD>/<run-id>.jsonl

# A single record
{"ts": "...", "kind": "llm_call_start", "model": "claude-opus-4-7", "input_tokens": 1284, ...}
{"ts": "...", "kind": "tool_exec_start", "name": "search_subjects", ...}
{"ts": "...", "kind": "tool_exec_end", "name": "search_subjects", "duration_ms": 312, ...}
{"ts": "...", "kind": "llm_call_end", "output_tokens": 482, "cache_read_tokens": 28000, ...}
{"ts": "...", "kind": "run_end", "total_cost_usd": 0.0127, ...}`}</pre>
            <p>
              Replay through the transcript viewer with <code>inspect view ~/.geode/runlog/...</code>.
              The <code>kind</code> values map 1-to-1 to hook events.
            </p>

            <h2>Lens 3. Audit Diagnostics (since v0.92.0)</h2>
            <p>
              The per-call assertion data Petri audits require. Cache read/write meta, input/output hash, original
              provider response, and cost decomposition. Every decision-relevant data point for a single call is stored
              in a reproducible form.
            </p>
            <pre>{`# core/audit/diagnostics.py
@dataclass
class CallDiagnostic:
    run_id: str
    call_seq: int                       # N-th call within the run
    provider: str                       # anthropic / openai / glm / codex
    model: str                          # e.g. claude-opus-4-7
    input_hash: str                     # SHA-256[:12] of input
    output_hash: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int              # cache hit
    cache_write_tokens: int             # cache write
    reasoning_tokens: int | None        # extended thinking
    cost_usd: float
    cost_breakdown: dict                # {input, output, cache_read, cache_write, reasoning}
    latency_ms: int
    audit_mode: bool                    # whether Petri audit is active`}</pre>
            <p>
              Introduced in v0.92.0. From v0.93 the Petri audit-mode uses this as the primary source to keep scenarios
              reproducible.
            </p>

            <h2>Lens 4. Petri Audit</h2>
            <p>
              Session-level grain. An N seeds by M turns grid measures misalignment risk. Three roles: Auditor
              (adversarial), Target (GEODE), Judge.
            </p>
            <ul>
              <li>Integration: <a href="/geode/docs/petri/overview">Petri × GEODE Integration</a></li>
              <li>Scenarios: <a href="/geode/docs/petri/scenarios">Petri Scenarios</a> (173 default plus 13 GEODE-specific)</li>
              <li>Run: <a href="/geode/docs/petri/run">Petri Run</a></li>
              <li>Dimensions: <a href="/geode/docs/petri/judge-dimensions">17 / 38 Judge Dimensions</a></li>
            </ul>

            <h2>Usage Ledger (since v0.66)</h2>
            <p>
              The append-only ledger dedicated to cost tracking. Per LLM call, tokens are broken out and cost is
              recorded at <code>~/.geode/usage/&lt;date&gt;.jsonl</code>.
              v0.90.0 fixed a token-tracker dual-record bug that had inflated codex/glm by 50-64 percent.
            </p>
            <pre>{`$ geode history --last 24h
$ jq '.cost_usd | add' ~/.geode/usage/2026-05-12.jsonl  # total
$ jq -c 'select(.cache_read_tokens > 0)' ~/.geode/usage/2026-05-12.jsonl  # cache hits only`}</pre>

            <h2>Which lens for which question</h2>
            <table>
              <thead><tr><th>Question</th><th>Primary lens</th><th>Backup</th></tr></thead>
              <tbody>
                <tr><td>Why was this tool called?</td><td>RunLog (run-level trace)</td><td>Hooks <code>TOOL_EXEC_*</code></td></tr>
                <tr><td>Where did the cost go?</td><td>Usage ledger</td><td>Hook <code>LLM_CALL_END</code> aggregate</td></tr>
                <tr><td>How did this call use the cache?</td><td>Audit diagnostics (cache_read/write)</td><td>RunLog</td></tr>
                <tr><td>Is this input reproducible?</td><td>Audit diagnostics (input_hash)</td><td>RunLog comparison</td></tr>
                <tr><td>Is this agent safe?</td><td>Petri audit (scenarios)</td><td>Hook <code>VERIFICATION_FAIL</code></td></tr>
                <tr><td>Where did a long session stall?</td><td>Hook <code>CONTEXT_OVERFLOW</code></td><td>RunLog timeline</td></tr>
              </tbody>
            </table>

            <h2>External adapters</h2>
            <p>
              The native stack is primary, but two export paths exist when an external dashboard is needed.
            </p>
            <ul>
              <li><strong>OpenTelemetry</strong>. Wrap a hook listener in an OTel exporter to push to Tempo, Jaeger, or Grafana.</li>
              <li><strong>inspect viewer</strong>. Feed RunLog JSONL straight into <code>inspect</code> to see the transcript UI (same viewer as Petri).</li>
            </ul>

            <h2>Why native observability</h2>
            <ul>
              <li>Drop external SaaS lock-in.</li>
              <li>Keep observability data inside GEODE itself (RunLog).</li>
              <li>External tracing SDK import-time cost conflicted with the cold-start lazy-loading arc across v0.85 to v0.89.</li>
            </ul>
            <p>
              In v0.89.0 the external tracing dependency and tracing module were removed. The four lenses on this page
              are the official observability path.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
