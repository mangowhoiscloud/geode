import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Long-running Safety — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/long-running"
      title="Long-running Safety"
      titleKo="장기 실행 안전"
      summary="Token guards, context overflow, sliding window. Graceful drain."
      summaryKo="토큰 가드, 컨텍스트 오버플로, 슬라이딩 윈도. graceful drain."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE를 수 시간 이상 돌릴 때 발생하는 안전 위험과 그 가드 메커니즘을 정리합니다.</p>

            <h2>5 가드</h2>
            <ul>
              <li><strong>200K 절대 토큰 가드</strong> — context가 한계 근처면 graceful drain</li>
              <li><strong>25K MCP 결과 가드</strong> — 한 도구 호출의 단일 결과 cap. HTML → MD 폴백</li>
              <li><strong>200-턴 슬라이딩 윈도</strong> — 가장 오래된 turn부터 압축</li>
              <li><strong>50 라운드 상한</strong> — while(tool_use) loop의 최대 라운드</li>
              <li><strong>5 종료 경로</strong> — natural completion, budget, error, user stop, timeout</li>
            </ul>

            <h2>관련 설정</h2>
            <pre>{`# config.toml
[runtime.budget]
max_tokens = 200000
max_rounds = 50
max_turns = 200`}</pre>

            <h2>관측</h2>
            <ul>
              <li><a href="/docs/harness/hooks"><code>CONTEXT_OVERFLOW</code> hook</a> 으로 발생 감지</li>
              <li>Runlog에 사용량 시계열 기록</li>
            </ul>

            <p className="text-white/40 text-sm"><em>참조:</em> wiki/concepts/geode-long-running-safety.md, wiki/concepts/geode-context-overflow-prevention.md, wiki/concepts/geode-context-guard.md</p>
          </>
        }
        en={
          <>
            <p>This guide lists the safety risks of running GEODE for hours and the guards that mitigate each.</p>

            <h2>Five guards</h2>
            <ul>
              <li><strong>200K absolute token guard</strong>: graceful drain when context approaches the ceiling.</li>
              <li><strong>25K MCP result guard</strong>: per-call result cap with HTML to Markdown fallback.</li>
              <li><strong>200-turn sliding window</strong>: oldest turns are compacted first.</li>
              <li><strong>50-round ceiling</strong>: max rounds of the while(tool_use) loop.</li>
              <li><strong>Five termination paths</strong>: natural completion, budget, error, user stop, timeout.</li>
            </ul>

            <h2>Configuration</h2>
            <pre>{`# config.toml
[runtime.budget]
max_tokens = 200000
max_rounds = 50
max_turns = 200`}</pre>

            <h2>Observability</h2>
            <ul>
              <li><a href="/docs/harness/hooks"><code>CONTEXT_OVERFLOW</code> hook</a> fires on hit.</li>
              <li>Usage time series lands in runlog.</li>
            </ul>

            <p className="text-white/40 text-sm"><em>See:</em> wiki/concepts/geode-long-running-safety.md, wiki/concepts/geode-context-overflow-prevention.md, wiki/concepts/geode-context-guard.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
