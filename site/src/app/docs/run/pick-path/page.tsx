import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Pick a Path — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/pick-path"
      title="Pick a Path"
      titleKo="경로 선택"
      summary="Subscription, API key, or free path. How to choose for your situation."
      summaryKo="구독, API 키, 무료 경로 중 본인 상황에 맞춰 고르는 법."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE를 어떤 LLM 경로로 돌릴지 5분 안에 결정하도록 돕습니다.</p>

            <h2>세 경로</h2>
            <table>
              <thead><tr><th>경로</th><th>적합한 상황</th><th>주의</th></tr></thead>
              <tbody>
                <tr><td><strong>Path A. 구독 (ChatGPT Plus·Pro·Team·Business·Edu)</strong></td><td>이미 ChatGPT 결제 중. API 키 따로 만들기 싫음.</td><td>gpt-5.5는 구독 전용. Codex CLI 경유. ChatGPT Team은 미지원.</td></tr>
                <tr><td><strong>Path B. API 키</strong></td><td>Anthropic·OpenAI·GLM 키 보유. 비용 통제 중요.</td><td>Anthropic Claude Pro/Max OAuth는 정책상 사용 금지 (2026-01-09 ToS).</td></tr>
                <tr><td><strong>Path C. 무료/오픈</strong></td><td>GLM-4.7-flash 등 무료 티어로 dry-run만.</td><td>품질·rate limit 보장 없음. 학습용으로만.</td></tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/docs/run/providers">프로바이더 설정</a>으로 키를 등록합니다.</li>
              <li>비용 가드는 <a href="/docs/ops/cost">비용 모니터링</a>에서.</li>
            </ul>

            <p className="text-white/40 text-sm"><em>출처:</em> 본 repo README §Path A/B + wiki/concepts/geode-llm-models.md</p>
          </>
        }
        en={
          <>
            <p>This guide helps you choose which LLM path to run GEODE on, in five minutes.</p>

            <h2>Three paths</h2>
            <table>
              <thead><tr><th>Path</th><th>When it fits</th><th>Caveats</th></tr></thead>
              <tbody>
                <tr><td><strong>A. Subscription (ChatGPT Plus/Pro/Team/Business/Edu)</strong></td><td>Already paying ChatGPT. Don't want a separate API key.</td><td>gpt-5.5 is subscription-only via Codex CLI. ChatGPT Team is not supported.</td></tr>
                <tr><td><strong>B. API key</strong></td><td>You hold Anthropic, OpenAI, or GLM keys. Cost control matters.</td><td>Anthropic Claude Pro/Max OAuth is policy-forbidden (2026-01-09 ToS).</td></tr>
                <tr><td><strong>C. Free / open</strong></td><td>GLM-4.7-flash and similar free tiers, dry-run only.</td><td>Quality and rate limits not guaranteed. Learning only.</td></tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li>Register your keys: <a href="/docs/run/providers">Configure Providers</a>.</li>
              <li>Cost guards live in <a href="/docs/ops/cost">Cost Monitoring</a>.</li>
            </ul>

            <p className="text-white/40 text-sm"><em>Source:</em> repo README §Path A/B and wiki/concepts/geode-llm-models.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
