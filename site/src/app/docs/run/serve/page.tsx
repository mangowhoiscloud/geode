import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Run as Daemon — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/serve"
      title="Run as Daemon"
      titleKo="데몬으로 실행"
      summary="Start serve, restart, stop. Thin CLI on top of an IPC-served runtime."
      summaryKo="serve 시작·재시작·종료. IPC 데몬 위에 thin CLI."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE를 백그라운드 데몬으로 띄워, thin CLI가 IPC로 붙는 운영 모드를 설정합니다.</p>

            <h2>시작</h2>
            <pre>{`uv run geode serve &`}</pre>
            <p>처음 <code>geode</code> 명령을 치면 자동으로 daemon이 부팅됩니다. 별도 호출은 명시 운영 때만 필요합니다.</p>

            <h2>재시작</h2>
            <pre>{`# 1) 기존 데몬 종료
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')

# 2a) PyPI 설치라면 CLI 패키지 업데이트
uv tool upgrade geode-agent
geode serve &

# 2b) 소스 체크아웃 설치라면 의존성 + editable CLI 갱신
uv sync
uv tool install -e . --force
geode serve &`}</pre>

            <h2>종료</h2>
            <ul>
              <li>graceful: <code>geode /stop</code></li>
              <li>강제: <code>kill -9 &lt;pid&gt;</code> (마지막 수단)</li>
            </ul>

            <h2>상태 확인</h2>
            <pre>{`geode /status     # 헬스 + 활성 세션 목록
geode /model      # 현재 활성 모델
geode /clean      # 캐시 비우기`}</pre>

            <p className="text-white/40 text-sm"><em>참조:</em> <a href="/geode/docs/harness/lifecycle">Lifecycle reference</a>, wiki/concepts/geode-lifecycle-commands.md</p>
          </>
        }
        en={
          <>
            <p>This guide starts GEODE as a background daemon, with the thin CLI attaching over IPC.</p>

            <h2>Start</h2>
            <pre>{`uv run geode serve &`}</pre>
            <p>The first <code>geode</code> invocation auto-boots the daemon. Explicit serve is only for operational restarts.</p>

            <h2>Restart</h2>
            <pre>{`# 1) Kill the running daemon
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')

# 2a) For a PyPI install, upgrade the CLI package
uv tool upgrade geode-agent
geode serve &

# 2b) For a source checkout, refresh dependencies + editable CLI
uv sync
uv tool install -e . --force
geode serve &`}</pre>

            <h2>Stop</h2>
            <ul>
              <li>Graceful: <code>geode /stop</code></li>
              <li>Hard: <code>kill -9 &lt;pid&gt;</code> (last resort)</li>
            </ul>

            <h2>Status</h2>
            <pre>{`geode /status     # health + active session list
geode /model      # current active model
geode /clean      # clear caches`}</pre>

            <p className="text-white/40 text-sm"><em>See:</em> <a href="/geode/docs/harness/lifecycle">Lifecycle reference</a>, wiki/concepts/geode-lifecycle-commands.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
