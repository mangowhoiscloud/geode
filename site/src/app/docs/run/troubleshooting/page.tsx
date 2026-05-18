import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Troubleshooting — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/troubleshooting"
      title="Troubleshooting"
      titleKo="문제 해결"
      summary="Common failure modes and where to look. Logs, hooks, runlog."
      summaryKo="흔한 실패 모드와 살펴볼 곳. 로그, 훅, runlog."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE를 돌릴 때 자주 만나는 5가지 실패 모드와 1차 진단 위치를 정리합니다.</p>

            <h2>흔한 실패</h2>
            <table>
              <thead><tr><th>증상</th><th>1차 확인</th></tr></thead>
              <tbody>
                <tr><td>"키가 없어요" 에러</td><td><code>echo $ANTHROPIC_API_KEY</code>와 <code>~/.geode/config.toml</code></td></tr>
                <tr><td>"context overflow" 종료</td><td><a href="/geode/docs/ops/long-running">장기 실행 안전</a> 가이드</td></tr>
                <tr><td>"MCP server timeout"</td><td><code>geode /status</code>로 MCP 헬스 확인</td></tr>
                <tr><td>토큰 비용 초과</td><td><a href="/geode/docs/ops/cost">비용 모니터링</a> + <code>geode /model</code>로 다운그레이드</td></tr>
                <tr><td>OAuth 토큰 만료</td><td><a href="/geode/docs/ops/oauth">OAuth 토큰 회전</a></td></tr>
              </tbody>
            </table>

            <h2>로그 위치</h2>
            <ul>
              <li>Runlog: <code>~/.geode/runlog/</code> (run 단위 trace)</li>
              <li>Hooks: <a href="/geode/docs/harness/hooks">Hook System</a> events</li>
              <li>Serve: <code>~/.geode/serve.log</code></li>
            </ul>

            <h2>지원</h2>
            <p>해결이 안 되면 GitHub Issues에 runlog 일부와 함께 등록: <code>github.com/mangowhoiscloud/geode/issues</code></p>
          </>
        }
        en={
          <>
            <p>This guide lists five common failure modes and where to start diagnosing each.</p>

            <h2>Common failures</h2>
            <table>
              <thead><tr><th>Symptom</th><th>First look</th></tr></thead>
              <tbody>
                <tr><td>"missing key" error</td><td><code>echo $ANTHROPIC_API_KEY</code> and <code>~/.geode/config.toml</code></td></tr>
                <tr><td>"context overflow" termination</td><td><a href="/geode/docs/ops/long-running">Long-running Safety</a></td></tr>
                <tr><td>"MCP server timeout"</td><td><code>geode /status</code> for MCP health</td></tr>
                <tr><td>Token cost overrun</td><td><a href="/geode/docs/ops/cost">Cost Monitoring</a> + <code>geode /model</code> to downgrade</td></tr>
                <tr><td>OAuth token expired</td><td><a href="/geode/docs/ops/oauth">OAuth Token Rotation</a></td></tr>
              </tbody>
            </table>

            <h2>Where logs live</h2>
            <ul>
              <li>Runlog: <code>~/.geode/runlog/</code> (per-run traces)</li>
              <li>Hooks: <a href="/geode/docs/harness/hooks">Hook System</a> events</li>
              <li>Serve: <code>~/.geode/serve.log</code></li>
            </ul>

            <h2>Support</h2>
            <p>If you're stuck, file an issue with a runlog excerpt: <code>github.com/mangowhoiscloud/geode/issues</code>.</p>
          </>
        }
      />
    </DocsShell>
  );
}
