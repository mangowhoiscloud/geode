import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Run as a Daemon — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/serve"
      title="Run as a daemon"
      titleKo="데몬으로 실행"
      summary="What the serve daemon hosts, when you actually need to start it, and the honest stop and status story."
      summaryKo="serve 데몬이 무엇을 띄우는지, 직접 실행이 언제 필요한지, 정직한 종료와 상태 확인 방법."
    >
      <Bi
        ko={
          <>
            <p>
              <code>geode serve</code>는 REPL 없이 도는 헤드리스 게이트웨이
              데몬입니다. 메신저 폴러, 스케줄러, 선택적 웹훅, 그리고 thin
              CLI가 붙는 IPC 소켓을 한 프로세스에서 호스팅합니다.
            </p>

            <h2>데몬이 띄우는 것</h2>
            <table>
              <thead>
                <tr><th>구성 요소</th><th>역할</th><th>코드 경로</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>메신저 폴러</td>
                  <td>Slack, Discord, Telegram 메시지를 폴링해 에이전트 세션으로 라우팅합니다. 폴링 주기는 <code>--poll/-p</code>(기본 3초).</td>
                  <td><code>core/cli/typer_serve.py</code></td>
                </tr>
                <tr>
                  <td>스케줄러</td>
                  <td>예약 작업을 로드하고, 놓친 실행을 복구하고, 주기 실행합니다.</td>
                  <td><code>core/cli/typer_serve.py</code></td>
                </tr>
                <tr>
                  <td>웹훅 (선택)</td>
                  <td><code>webhook_enabled</code>일 때 HTTP 엔드포인트를 엽니다.</td>
                  <td><code>core/server/supervised/webhook_handler.py</code></td>
                </tr>
                <tr>
                  <td>CLI IPC 소켓</td>
                  <td><code>~/.geode/cli.sock</code> Unix 소켓. thin CLI의 자유 텍스트와 슬래시 명령이 여기로 들어옵니다.</td>
                  <td><code>core/server/ipc_server/poller.py</code></td>
                </tr>
              </tbody>
            </table>

            <h2>대부분은 직접 띄울 필요가 없습니다</h2>
            <p>
              <code>geode</code>를 실행하면 소켓을 확인하고, 데몬이 없으면
              백그라운드로 자동 시작한 뒤 IPC로 붙습니다
              (<code>core/cli/ipc_client.py</code>). 대화만 할 거라면
              <code>geode serve</code>를 직접 칠 일이 없습니다. 직접 실행은
              메신저와 스케줄을 명시적으로 운영할 때의 선택지입니다.
            </p>

            <h2>시작 조건: gateway_enabled</h2>
            <p>
              <code>geode serve</code>는 <code>gateway_enabled</code>가 꺼져
              있으면 시작을 거부하고 안내를 출력합니다. 켜려면
              <code>~/.geode/.env</code>에 한 줄을 추가합니다.
            </p>
            <pre>{`# ~/.geode/.env
GEODE_GATEWAY_ENABLED=true`}</pre>
            <pre>{`geode serve              # 포그라운드 실행
geode serve --poll 5     # 폴링 주기 5초`}</pre>

            <h2>종료와 상태: 있는 그대로</h2>
            <p>
              <code>geode serve stop</code> 같은 서브커맨드는 없습니다. 종료는
              프로세스에 직접 시그널을 보냅니다.
            </p>
            <table>
              <thead>
                <tr><th>하고 싶은 것</th><th>명령</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>데몬 종료</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>. <code>ps aux | grep</code>은 긴 파이썬 경로가 잘려 못 잡는 경우가 있으니 <code>pgrep -f</code> 계열을 씁니다.</td>
                </tr>
                <tr>
                  <td>살아 있는지 확인</td>
                  <td><code>pgrep -f &quot;geode serve&quot;</code>, 또는 <code>geode about</code>의 데몬 소켓 상태.</td>
                </tr>
                <tr>
                  <td>상태 자세히</td>
                  <td>REPL 안에서 <code>/status</code>. 데몬, 모델, MCP, 디스크 사용량을 보여줍니다.</td>
                </tr>
                <tr>
                  <td>업데이트 + 재시작</td>
                  <td><code>geode update</code>. 소스 체크아웃을 갱신하고, 데몬이 돌고 있었으면 종료 후 백그라운드로 다시 띄웁니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              SIGTERM을 받으면 데몬은 단계적으로 내려갑니다. 새 요청 수락 중지,
              30초 세션 드레인, 스케줄러 저장과 정지, MCP 종료, 게이트웨이 정지
              순서입니다 (<code>core/cli/typer_serve.py</code>).
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>geode serve</code>가 시작을 거부</td>
                  <td>gateway 비활성</td>
                  <td><code>~/.geode/.env</code>에 <code>GEODE_GATEWAY_ENABLED=true</code>를 추가합니다.</td>
                </tr>
                <tr>
                  <td>배너 모델과 응답 모델이 다름</td>
                  <td>업데이트 전의 오래된 데몬이 살아 있음</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>로 전부 내리고 <code>geode</code>를 다시 실행합니다.</td>
                </tr>
                <tr>
                  <td>동작이 들쭉날쭉, 소켓 충돌</td>
                  <td>데몬 여러 개가 <code>~/.geode/cli.sock</code>을 두고 경합</td>
                  <td><code>pgrep -f &quot;geode serve&quot;</code>로 개수를 확인하고 전부 종료 후 하나만 띄웁니다.</td>
                </tr>
                <tr>
                  <td>/model을 바꿔도 데몬이 옛 모델 유지</td>
                  <td>데몬 환경에 모델 env가 박제됨 (구버전 잔재)</td>
                  <td>데몬은 시작 시 모델 계열 env 키를 버리는 것이 기본입니다. 데몬을 재시작하고, 그래도 안 되면 <code>geode config explain model</code>을 봅니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>설정 레퍼런스</h2>
            <ul>
              <li><a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>. 폴러, 바인딩, lane queue 운영.</li>
              <li><a href="/geode/docs/run/messaging">메신저 연동</a>. Slack, Discord, Telegram 연결.</li>
              <li><a href="/geode/docs/run/schedule">작업 예약</a>. 자연어와 cron 예약.</li>
              <li><a href="/geode/docs/harness/lifecycle">라이프사이클</a>. 부트스트랩과 종료 순서의 내부.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              <code>geode serve</code> is the headless gateway daemon, no REPL
              attached. One process hosts the messaging pollers, the scheduler,
              an optional webhook, and the IPC socket the thin CLI connects to.
            </p>

            <h2>What the daemon hosts</h2>
            <table>
              <thead>
                <tr><th>Component</th><th>Role</th><th>Code path</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Messaging pollers</td>
                  <td>Poll Slack, Discord, and Telegram and route messages into agent sessions. Poll interval via <code>--poll/-p</code> (default 3 seconds).</td>
                  <td><code>core/cli/typer_serve.py</code></td>
                </tr>
                <tr>
                  <td>Scheduler</td>
                  <td>Loads scheduled jobs, recovers missed runs, and fires on cadence.</td>
                  <td><code>core/cli/typer_serve.py</code></td>
                </tr>
                <tr>
                  <td>Webhook (optional)</td>
                  <td>Opens an HTTP endpoint when <code>webhook_enabled</code> is set.</td>
                  <td><code>core/server/supervised/webhook_handler.py</code></td>
                </tr>
                <tr>
                  <td>CLI IPC socket</td>
                  <td>The Unix socket at <code>~/.geode/cli.sock</code>. Free text and slash commands from the thin CLI arrive here.</td>
                  <td><code>core/server/ipc_server/poller.py</code></td>
                </tr>
              </tbody>
            </table>

            <h2>You usually do not start it yourself</h2>
            <p>
              Running bare <code>geode</code> probes the socket, auto-starts the
              daemon in the background if it is absent, and attaches over IPC
              (<code>core/cli/ipc_client.py</code>). For chat, you never need to
              run <code>geode serve</code> manually. Explicit serve is for
              operating messaging and schedules deliberately.
            </p>

            <h2>Start requirement: gateway_enabled</h2>
            <p>
              <code>geode serve</code> refuses to start while
              <code>gateway_enabled</code> is off, and prints the hint. Enable
              it with one line in <code>~/.geode/.env</code>.
            </p>
            <pre>{`# ~/.geode/.env
GEODE_GATEWAY_ENABLED=true`}</pre>
            <pre>{`geode serve              # run in the foreground
geode serve --poll 5     # 5-second poll interval`}</pre>

            <h2>Stop and status, honestly</h2>
            <p>
              There is no <code>geode serve stop</code> subcommand. Stopping
              means signaling the process directly.
            </p>
            <table>
              <thead>
                <tr><th>Goal</th><th>Command</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Stop the daemon</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>. Avoid <code>ps aux | grep</code>; the long Python path can truncate and the grep silently misses. Use <code>pgrep -f</code> style matching.</td>
                </tr>
                <tr>
                  <td>Check it is alive</td>
                  <td><code>pgrep -f &quot;geode serve&quot;</code>, or the daemon socket status in <code>geode about</code>.</td>
                </tr>
                <tr>
                  <td>Detailed status</td>
                  <td><code>/status</code> inside the REPL. Daemon, model, MCP servers, and disk usage.</td>
                </tr>
                <tr>
                  <td>Update + restart</td>
                  <td><code>geode update</code>. Refreshes a source checkout and, if the daemon was running, stops it and restarts it in the background.</td>
                </tr>
              </tbody>
            </table>
            <p>
              On SIGTERM the daemon shuts down in stages: stop accepting new
              requests, drain sessions for up to 30 seconds, save and stop the
              scheduler, shut down MCP, stop the gateway
              (<code>core/cli/typer_serve.py</code>).
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>geode serve</code> refuses to start</td>
                  <td>Gateway disabled</td>
                  <td>Add <code>GEODE_GATEWAY_ENABLED=true</code> to <code>~/.geode/.env</code>.</td>
                </tr>
                <tr>
                  <td>Banner model differs from the answering model</td>
                  <td>A stale daemon from before an update is still alive</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code> to clear them all, then run <code>geode</code> again.</td>
                </tr>
                <tr>
                  <td>Erratic behavior, socket conflicts</td>
                  <td>Multiple daemons fighting over <code>~/.geode/cli.sock</code></td>
                  <td>Count them with <code>pgrep -f &quot;geode serve&quot;</code>, stop them all, start exactly one.</td>
                </tr>
                <tr>
                  <td>/model switch never reaches the daemon</td>
                  <td>A model env var pinned into the daemon’s environment (older releases)</td>
                  <td>Dropping model env keys at daemon startup is the default now. Restart the daemon; if it persists, run <code>geode config explain model</code>.</td>
                </tr>
              </tbody>
            </table>

            <h2>Configuration reference</h2>
            <ul>
              <li><a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>. Pollers, bindings, lane queue operations.</li>
              <li><a href="/geode/docs/run/messaging">Messaging integrations</a>. Connecting Slack, Discord, Telegram.</li>
              <li><a href="/geode/docs/run/schedule">Schedule tasks</a>. Natural language and cron.</li>
              <li><a href="/geode/docs/harness/lifecycle">Lifecycle</a>. Bootstrap and shutdown internals.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
