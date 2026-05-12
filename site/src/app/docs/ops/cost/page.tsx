import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Cost Monitoring — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/cost"
      title="Cost Monitoring"
      titleKo="비용 모니터링"
      summary="Per-session and per-day budgets. Usage ledger schema. v0.90 dual-record fix. When to switch models."
      summaryKo="세션·일별 예산. usage ledger 스키마. v0.90 dual-record 수정. 모델 전환 시점."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE의 LLM 호출 비용을 추적하고 예산을 설정하는 방법입니다.</p>

            <h2>비용 추적 경로</h2>
            <ul>
              <li>실시간: <code>LLM_CALL_END</code> hook (per-call 토큰·달러).</li>
              <li>누적 (런타임): <code>geode /status</code> (현재 세션 + 일일).</li>
              <li>append-only ledger: <code>~/.geode/usage/&lt;date&gt;.jsonl</code> (v0.66+ 도입).</li>
              <li>per-call assertion: <code>core.audit.diagnostics.CallDiagnostic</code> (v0.92+, <a href="/docs/verification/observability">Observability</a> 참조).</li>
            </ul>

            <h2>Usage ledger 스키마</h2>
            <pre>{`# ~/.geode/usage/2026-05-12.jsonl 한 줄
{
  "ts": "2026-05-12T10:42:13.482Z",
  "run_id": "r-abc123",
  "call_seq": 4,
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "input_tokens": 1284,
  "output_tokens": 482,
  "cache_read_tokens": 28104,
  "cache_write_tokens": 0,
  "reasoning_tokens": 1872,
  "cost_usd": 0.0127,
  "cost_breakdown": {
    "input": 0.00385,
    "output": 0.00723,
    "cache_read": 0.00084,
    "cache_write": 0,
    "reasoning": 0.00281
  },
  "latency_ms": 4218,
  "audit_mode": false
}`}</pre>

            <h2>v0.90 dual-record 수정</h2>
            <p>
              v0.90.0 이전, codex와 glm 어댑터가 같은 호출을 ledger에 두 번 기록해 token/cost가 50-64% 과잉 카운팅됐습니다.
              <code>token_tracker.dedup_by_call_id()</code> 도입으로 수정. 기존 ledger를 다시 합산하려면 history 명령으로 재집계 가능.
            </p>

            <h2>예산 설정</h2>
            <pre>{`# config.toml
[budget]
per_session_usd = 1.0
per_day_usd = 10.0
on_exceed = "downgrade"  # downgrade | stop | warn`}</pre>

            <h2>모델 다운그레이드 전략</h2>
            <p>예산 초과 임박 시 자동으로 더 싼 모델로 전환합니다.</p>
            <ul>
              <li>Anthropic: opus 4.7 → opus 4.6 → sonnet 4.6 → haiku 4.5</li>
              <li>OpenAI: gpt-5.5 → gpt-5.4 → gpt-5.4-mini → gpt-5-mini</li>
              <li>GLM: glm-5.1 → glm-5 → glm-5-turbo → glm-4.7 → glm-4.7-flash</li>
            </ul>

            <h2>수동 전환</h2>
            <pre>{`geode /model claude-haiku-4-5
geode /model glm-4.7-flash`}</pre>

            <h2>유용한 jq one-liner</h2>
            <pre>{`# 오늘 총 비용
jq -s '[.[] | .cost_usd] | add' ~/.geode/usage/$(date +%F).jsonl

# 모델별 토큰 합계
jq -s 'group_by(.model) | map({model: .[0].model, total: (map(.input_tokens + .output_tokens) | add)})' ~/.geode/usage/$(date +%F).jsonl

# 캐시 hit 호출만
jq -c 'select(.cache_read_tokens > 0)' ~/.geode/usage/$(date +%F).jsonl`}</pre>

            <p className="text-white/40 text-sm"><em>참조:</em> <a href="/docs/verification/observability">Observability</a>, <a href="/docs/runtime/context">Context System (200K guard)</a>, wiki/concepts/geode-context-guard.md.</p>
          </>
        }
        en={
          <>
            <p>This guide tracks GEODE's LLM call costs and sets budgets.</p>

            <h2>Cost paths</h2>
            <ul>
              <li>Real-time: <code>LLM_CALL_END</code> hook (per-call tokens and dollars).</li>
              <li>Cumulative (runtime): <code>geode /status</code> (current session + day).</li>
              <li>Append-only ledger: <code>~/.geode/usage/&lt;date&gt;.jsonl</code> (introduced in v0.66).</li>
              <li>Per-call assertion: <code>core.audit.diagnostics.CallDiagnostic</code> (v0.92+, see <a href="/docs/verification/observability">Observability</a>).</li>
            </ul>

            <h2>Usage ledger schema</h2>
            <pre>{`# A single line in ~/.geode/usage/2026-05-12.jsonl
{
  "ts": "2026-05-12T10:42:13.482Z",
  "run_id": "r-abc123",
  "call_seq": 4,
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "input_tokens": 1284,
  "output_tokens": 482,
  "cache_read_tokens": 28104,
  "cache_write_tokens": 0,
  "reasoning_tokens": 1872,
  "cost_usd": 0.0127,
  "cost_breakdown": {
    "input": 0.00385,
    "output": 0.00723,
    "cache_read": 0.00084,
    "cache_write": 0,
    "reasoning": 0.00281
  },
  "latency_ms": 4218,
  "audit_mode": false
}`}</pre>

            <h2>v0.90 dual-record fix</h2>
            <p>
              Before v0.90.0, the codex and glm adapters recorded the same call twice in the ledger,
              over-counting tokens and cost by 50-64 percent. Adding
              <code> token_tracker.dedup_by_call_id()</code> fixed it. Existing ledgers can be re-aggregated via
              <code>geode history</code>.
            </p>

            <h2>Budget configuration</h2>
            <pre>{`# config.toml
[budget]
per_session_usd = 1.0
per_day_usd = 10.0
on_exceed = "downgrade"  # downgrade | stop | warn`}</pre>

            <h2>Downgrade strategy</h2>
            <p>When the budget is about to be exceeded, GEODE auto-switches to a cheaper model.</p>
            <ul>
              <li>Anthropic: opus 4.7 to opus 4.6 to sonnet 4.6 to haiku 4.5.</li>
              <li>OpenAI: gpt-5.5 to gpt-5.4 to gpt-5.4-mini to gpt-5-mini.</li>
              <li>GLM: glm-5.1 to glm-5 to glm-5-turbo to glm-4.7 to glm-4.7-flash.</li>
            </ul>

            <h2>Manual switch</h2>
            <pre>{`geode /model claude-haiku-4-5
geode /model glm-4.7-flash`}</pre>

            <h2>Useful jq one-liners</h2>
            <pre>{`# Today's total cost
jq -s '[.[] | .cost_usd] | add' ~/.geode/usage/$(date +%F).jsonl

# Token totals by model
jq -s 'group_by(.model) | map({model: .[0].model, total: (map(.input_tokens + .output_tokens) | add)})' ~/.geode/usage/$(date +%F).jsonl

# Cache-hit calls only
jq -c 'select(.cache_read_tokens > 0)' ~/.geode/usage/$(date +%F).jsonl`}</pre>

            <p className="text-white/40 text-sm"><em>See:</em> <a href="/docs/verification/observability">Observability</a>, <a href="/docs/runtime/context">Context System (200K guard)</a>, wiki/concepts/geode-context-guard.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
