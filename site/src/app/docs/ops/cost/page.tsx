import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Cost Monitoring — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/cost"
      title="Cost Monitoring"
      titleKo="비용 모니터링"
      summary="Per-session and per-day budgets. When to switch models."
      summaryKo="세션·일별 예산. 모델 전환 시점."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE의 LLM 호출 비용을 추적하고 예산을 설정하는 방법입니다.</p>

            <h2>비용 추적</h2>
            <p>모든 LLM call은 <code>LLM_CALL_END</code> hook으로 토큰/달러를 보고합니다. <code>geode /status</code>에서 누적 확인.</p>

            <h2>예산 설정</h2>
            <pre>{`# config.toml
[budget]
per_session_usd = 1.0
per_day_usd = 10.0
on_exceed = "downgrade"  # downgrade | stop | warn`}</pre>

            <h2>모델 다운그레이드 전략</h2>
            <p>예산 초과 임박 시 자동으로 더 싼 모델로 전환합니다.</p>
            <ul>
              <li>opus → sonnet → haiku 순</li>
              <li>gpt-5.5 → gpt-5.4 → gpt-5.4-mini</li>
              <li>glm-5 → glm-4.7 → glm-4.7-flash</li>
            </ul>

            <h2>수동 전환</h2>
            <pre>{`geode /model claude-haiku-4-5`}</pre>

            <p className="text-white/40 text-sm"><em>참조:</em> wiki/concepts/geode-context-guard.md, geode-changelog (token guard 도입 history)</p>
          </>
        }
        en={
          <>
            <p>This guide tracks GEODE's LLM call costs and sets budgets.</p>

            <h2>Cost tracking</h2>
            <p>Every LLM call reports tokens and dollars via the <code>LLM_CALL_END</code> hook. Check cumulative in <code>geode /status</code>.</p>

            <h2>Budget configuration</h2>
            <pre>{`# config.toml
[budget]
per_session_usd = 1.0
per_day_usd = 10.0
on_exceed = "downgrade"  # downgrade | stop | warn`}</pre>

            <h2>Downgrade strategy</h2>
            <p>When the budget is about to be exceeded, GEODE auto-switches to a cheaper model.</p>
            <ul>
              <li>opus → sonnet → haiku</li>
              <li>gpt-5.5 → gpt-5.4 → gpt-5.4-mini</li>
              <li>glm-5 → glm-4.7 → glm-4.7-flash</li>
            </ul>

            <h2>Manual switch</h2>
            <pre>{`geode /model claude-haiku-4-5`}</pre>

            <p className="text-white/40 text-sm"><em>See:</em> wiki/concepts/geode-context-guard.md, geode-changelog (token guard history).</p>
          </>
        }
      />
    </DocsShell>
  );
}
