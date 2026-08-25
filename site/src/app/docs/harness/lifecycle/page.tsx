import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Lifecycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/lifecycle"
      title="Lifecycle"
      titleKo="라이프사이클"
      summary="Bootstrap, serve, shutdown. The injection order, and the cold-start lazy arc."
      summaryKo="Bootstrap, serve, shutdown. 주입 순서와 cold-start lazy arc를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 두 프로세스로 삽니다. 사용자가 만지는 thin CLI와 모든
              런타임을 소유한 serve 데몬입니다. 데몬이 부트되는 순서,
              호스팅하는 것, 내려가는 순서를 코드 기준으로 따라갑니다.
            </p>

            <h2>부트: thin CLI에서 데몬까지</h2>
            <pre>{`geode (thin CLI)
  │ 1. 소켓 probe: ~/.geode/cli.sock 살아 있나
  │ 2. 없으면 cli.startup.lock flock 잡고
  │    "geode serve"를 detached로 spawn (최대 30초 대기)
  │ 3. client_capability 핸드셰이크 (TTY 여부, 터미널 폭)
  ▼
geode serve (데몬)  ←  하나의 GeodeRuntime이 전부 소유`}</pre>
            <p>
              자동 시작은 <code>start_serve_if_needed</code>
              (<code>core/cli/ipc_client.py</code>)가 담당합니다. pidfile
              flock으로 동시 실행된 thin CLI 여러 개가 데몬을 중복으로 띄우지
              않게 막습니다. 데몬은 시작 직후 상속받은 환경에서 모델 선택류
              behavior 키를 떨어뜨립니다
              (<code>core/cli/bootstrap.py</code>의 <code>load_daemon_env</code>).
              그래서 <code>/model</code>의 toml 쓰기가 데몬 수명 내내 이깁니다.
            </p>

            <h2>주입 순서</h2>
            <p>
              데몬 안에서 <code>GeodeRuntime</code>(<code>core/runtime.py</code>)이
              인프라 싱글톤을 만들고, 구현은 <code>core/wiring/</code>으로
              위임됩니다. 무거운 모듈 트리는 해당 컴포넌트가 실제로 쓰일 때
              lazy하게 로드됩니다.
            </p>
            <table>
              <thead>
                <tr><th>단계</th><th>만드는 것</th><th>코드</th></tr>
              </thead>
              <tbody>
                <tr><td>1</td><td>RuntimeEventBus + SQLite sink + 공개 훅·미들웨어 registry. 프로세스 단위로 한 번 구성됩니다.</td><td><code>core/wiring/bootstrap.py</code>, <code>core/server/supervised/services.py</code></td></tr>
                <tr><td>2</td><td>PolicyChain, ToolRegistry, LaneQueue, 인증 스토어</td><td><code>core/wiring/container.py</code></td></tr>
                <tr><td>3</td><td>TriggerManager + SchedulerService</td><td><code>core/wiring/scheduling.py</code></td></tr>
                <tr><td>4</td><td>MCP, 알림, 캘린더, 게이트웨이 어댑터</td><td><code>core/wiring/adapters.py</code></td></tr>
              </tbody>
            </table>
            <p>
              세션 생성은 <code>SharedServices.create_session(mode)</code>
              (<code>core/server/supervised/services.py</code>) 한 곳으로
              수렴합니다. REPL, IPC, DAEMON, SCHEDULER 네 모드가 같은 배선의
              <code>(ToolExecutor, AgenticLoop)</code> 쌍을 받고, 모드는 HITL
              레벨과 time budget 같은 기본값만 바꿉니다.
            </p>
            <p>
              배선 불변식 하나가 이 단계 전체를 지배합니다. 핸들러가 존재한다고
              발화하지 않습니다. 훅 핸들러는 bootstrap에 등록되어야 하고,
              프로세스 서비스는 그룹형 설정·생성자·<code>ToolContext</code>로
              명시적으로 주입되어야 합니다. ContextVar는 요청 식별, 진단,
              요청 로컬 상태와 캐시에만 사용합니다.
            </p>

            <h2>데몬이 호스팅하는 것</h2>
            <ul>
              <li>CLI IPC 서버 (<code>core/server/ipc_server/poller.py</code>). thin CLI의 자유 텍스트와 슬래시 명령 처리.</li>
              <li>메신저 poller와 게이트웨이 (<code>core/server/supervised/</code>, <code>core/messaging/binding.py</code>).</li>
              <li>SchedulerService. 부팅 시 저장 작업 로드와 놓친 발화 복구, serve 루프에서 drain.</li>
              <li>gateway와 webhook이 모두 활성일 때의 HTTP 엔드포인트.</li>
            </ul>

            <h2>종료 순서</h2>
            <p>
              순서가 곧 안전입니다. 새 요청을 먼저 끊고, 하던 일을 마치게 하고,
              상태를 저장한 뒤 연결을 닫습니다 (<code>core/cli/typer_serve.py</code>).
            </p>
            <pre>{`1. RuntimeEvent.SHUTDOWN_STARTED 발화
2. IPC 소켓 닫기 (신규 클라이언트 차단)
3. 활성 세션 drain (최대 30초)
4. 스케줄러 save + stop
5. MCP 종료
6. 게이트웨이 정지`}</pre>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>업데이트했는데 옛 동작이 계속됨</td>
                  <td>오래된 데몬이 살아남아 소켓을 점유</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code> 후 재진입합니다. <code>geode update</code>로 재시작할 수도 있습니다.</td>
                </tr>
                <tr>
                  <td>외부 채널이 동작하지 않음</td>
                  <td><code>gateway_enabled</code> 꺼짐</td>
                  <td>CLI IPC는 계속 동작합니다. 외부 채널이 필요할 때만 <code>GEODE_GATEWAY_ENABLED=true</code>를 켭니다.</td>
                </tr>
                <tr>
                  <td>기능이 조용히 동작하지 않음</td>
                  <td>핸들러 미등록 또는 서비스 구성 누락</td>
                  <td>bootstrap 등록과 composition root의 명시적 서비스 주입을 확인합니다. <code>core/wiring/bootstrap.py</code>의 <code>get_plugin_status()</code>가 플러그인별 등록 상태를 보고합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/run/serve">데몬으로 실행</a>. 운영 관점의 시작과 정지.</li>
              <li><a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>. 데몬이 호스팅하는 메신저 경로.</li>
              <li><a href="/geode/docs/guides/register-hook">훅 등록</a>. bootstrap 등록이 필수인 이유.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE lives as two processes: the thin CLI you touch and the serve
              daemon that owns the entire runtime. The sections below trace the
              boot order, what the daemon hosts, and the shutdown order,
              grounded in code.
            </p>

            <h2>Boot: from thin CLI to daemon</h2>
            <pre>{`geode (thin CLI)
  │ 1. probe the socket: is ~/.geode/cli.sock alive
  │ 2. if not, take the cli.startup.lock flock and
  │    spawn "geode serve" detached (poll up to 30s)
  │ 3. client_capability handshake (TTY, terminal width)
  ▼
geode serve (daemon)  ←  one GeodeRuntime owns everything`}</pre>
            <p>
              Auto-start is <code>start_serve_if_needed</code>
              (<code>core/cli/ipc_client.py</code>). The pidfile flock keeps
              concurrent thin CLIs from double-spawning the daemon. Right after
              start, the daemon drops model-pick behavior keys from its
              inherited environment (<code>load_daemon_env</code> in{" "}
              <code>core/cli/bootstrap.py</code>), so the toml write behind{" "}
              <code>/model</code> wins for the daemon&apos;s whole lifetime.
            </p>

            <h2>Injection order</h2>
            <p>
              Inside the daemon, <code>GeodeRuntime</code>
              (<code>core/runtime.py</code>) creates the infrastructure
              singletons, with the implementation delegated to{" "}
              <code>core/wiring/</code>. Heavy module trees load lazily, only
              when the matching component actually fires.
            </p>
            <table>
              <thead>
                <tr><th>Stage</th><th>What it builds</th><th>Code</th></tr>
              </thead>
              <tbody>
                <tr><td>1</td><td>RuntimeEventBus, SQLite sink, and process-owned public hook and middleware registries.</td><td><code>core/wiring/bootstrap.py</code>, <code>core/server/supervised/services.py</code></td></tr>
                <tr><td>2</td><td>PolicyChain, ToolRegistry, LaneQueue, auth stores</td><td><code>core/wiring/container.py</code></td></tr>
                <tr><td>3</td><td>TriggerManager + SchedulerService</td><td><code>core/wiring/scheduling.py</code></td></tr>
                <tr><td>4</td><td>MCP, notification, calendar, and gateway adapters</td><td><code>core/wiring/adapters.py</code></td></tr>
              </tbody>
            </table>
            <p>
              Session creation converges on{" "}
              <code>SharedServices.create_session(mode)</code>
              (<code>core/server/supervised/services.py</code>). The four modes,
              REPL, IPC, DAEMON, and SCHEDULER, receive identically wired{" "}
              <code>(ToolExecutor, AgenticLoop)</code> pairs; a mode only
              changes defaults such as the HITL level and the time budget.
            </p>
            <p>
              One wiring invariant rules this whole stage: a handler existing
              does not mean it fires. Hook handlers must register in bootstrap,
              and process services must be injected explicitly through grouped
              configuration, constructors, or <code>ToolContext</code>.
              ContextVars are limited to request identity, diagnostics,
              request-local state, and caches.
            </p>

            <h2>What the daemon hosts</h2>
            <ul>
              <li>The CLI IPC server (<code>core/server/ipc_server/poller.py</code>): free text and slash commands from the thin CLI.</li>
              <li>Messenger pollers and the gateway (<code>core/server/supervised/</code>, <code>core/messaging/binding.py</code>).</li>
              <li>SchedulerService: load saved jobs and recover missed fires on boot, drain in the serve loop.</li>
              <li>An HTTP endpoint when both gateway and webhook are enabled.</li>
            </ul>

            <h2>Shutdown order</h2>
            <p>
              The order is the safety: stop new work first, let current work
              finish, save state, then close connections
              (<code>core/cli/typer_serve.py</code>).
            </p>
            <pre>{`1. fire RuntimeEvent.SHUTDOWN_STARTED
2. close the IPC socket (no new clients)
3. drain active sessions (up to 30s)
4. scheduler save + stop
5. MCP shutdown
6. gateway stop`}</pre>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Old behavior survives an update</td>
                  <td>A stale daemon kept the socket</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>, then re-enter. <code>geode update</code> performs this restart for you.</td>
                </tr>
                <tr>
                  <td>External channels do not work</td>
                  <td><code>gateway_enabled</code> is off</td>
                  <td>CLI IPC keeps working. Set <code>GEODE_GATEWAY_ENABLED=true</code> only when you need external channels.</td>
                </tr>
                <tr>
                  <td>A feature silently does nothing</td>
                  <td>Handler not registered, or service composition missing</td>
                  <td>Check bootstrap registration and explicit service injection at the composition root. <code>get_plugin_status()</code> in <code>core/wiring/bootstrap.py</code> reports per-plugin registration state.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/run/serve">Run as a daemon</a>. Start and stop from the operator&apos;s seat.</li>
              <li><a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>. The messaging path the daemon hosts.</li>
              <li><a href="/geode/docs/guides/register-hook">Register a hook</a>. Why bootstrap registration is mandatory.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
