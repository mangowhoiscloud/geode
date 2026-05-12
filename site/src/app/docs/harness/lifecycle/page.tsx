import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Lifecycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/lifecycle"
      title="Lifecycle"
      titleKo="라이프사이클"
      summary="Bootstrap, serve, shutdown. core/wiring/ + core/runtime.py drive the daemon's life cycle, handle signal-based termination, and emit lifecycle hook events."
      summaryKo="Bootstrap, serve, shutdown. core/wiring/와 core/runtime.py가 데몬의 수명을 구동하고, 시그널 기반 종료를 처리하며, 라이프사이클 훅 이벤트를 발화합니다."
    >
      <Bi
        ko={
          <>
            <h2>다섯 단계</h2>
            <pre>{`1. Bootstrap     — read config, init paths, register hooks, set ContextVars
2. Wire          — start MCP servers, load tools, discover skills, mount domain plugins
3. Serve         — listen on IPC, accept commands, drive AgenticLoop
4. Drain         — finish pending tool calls, flush queues, close LLM clients
5. Shutdown      — close IPC socket, write session log, exit`}</pre>

            <h2>진입점</h2>
            <table>
              <thead><tr><th>파일</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><code>core/runtime.py</code></td><td>최상위 <code>bootstrap()</code></td></tr>
                <tr><td><code>core/wiring/</code> (5 modules)</td><td>각 단계 구현과 시그널 핸들러</td></tr>
                <tr><td><code>core/server/</code> (10 modules)</td><td>IPC 리스너, 요청 디스패치, 데몬 메인 루프</td></tr>
              </tbody>
            </table>

            <h2>시그널</h2>
            <ul>
              <li><strong>SIGTERM</strong>. graceful drain 후 shutdown.</li>
              <li><strong>SIGINT</strong>. 현재 LLM 호출을 중단 (<code>UserCancelledError</code> 전파). 데몬은 유지.</li>
              <li><strong>SIGHUP</strong>. 설정 재로드 (환경 변수, 모델 레지스트리).</li>
            </ul>

            <h2>Client capability handshake (v0.84+)</h2>
            <p>
              Thin CLI가 IPC로 데몬에 연결되는 즉시 <code>client_capability</code> 메시지를 보냅니다.
              <code>{`{"type": "client_capability", "is_tty": bool, "width": int}`}</code>. 데몬은 이 값을
              사용해 per-thread Rich Console을 구성합니다. non-TTY 클라이언트에선 ANSI escape와
              spinner frame이 자동 suppress 됩니다.
            </p>
            <pre>{`# core/cli/ipc_client.py
def _send_client_capability(self) -> None:
    """Send terminal capability to the daemon."""
    is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    width = shutil.get_terminal_size((80, 24)).columns
    self._send({
        "type": "client_capability",
        "is_tty": is_tty,
        "width": width,
    })

# core/server/ipc_server/poller.py
# receives client_capability and stores it per-connection`}</pre>

            <h2>ContextVar 배선</h2>
            <p>
              Bootstrap은 현재 세션, 현재 모델, 현재 사용자 프로파일, 현재 훅
              시스템에 대한 <code>ContextVar</code> 인스턴스를 설정합니다. 에이전틱
              루프와 도구 핸들러는 인자로 받지 않고 <code>get_*()</code> 액세서로
              읽습니다.
            </p>
            <p>
              CLAUDE.md의 안티 패턴 한 가지. bootstrap에 대응하는{" "}
              <code>set_*()</code>가 없는 <code>get_*()</code> 액세서는 조용히{" "}
              <code>None</code>을 반환하고, 의존 기능은 조용히 degrade 됩니다.
              CLAUDE.md의 Wiring Verification 표가 이를 막는 게이트입니다.
            </p>

            <h2>발화되는 훅 이벤트</h2>
            <ul>
              <li><code>SESSION_START</code>. bootstrap 종료 시점.</li>
              <li><code>SESSION_END</code>. drain 시작 시점.</li>
              <li><code>MODEL_SWITCHED</code>. <code>/model</code> 회전 시점.</li>
              <li><code>CONTEXT_RESET</code>. <code>/clear</code> 실행 시점.</li>
            </ul>

            <h2>Cold start (v0.85~v0.89)</h2>
            <p>
              v0.85 ~ v0.89 동안 다수의 SDK (anthropic, numpy, pydantic, importlib.metadata 등)를 lazy load로 전환했습니다.
              결과: cold start 누적 −258ms, warm cold-start −86% (~33ms). modules 341 → 167 (−174).
              wiring 모듈 (이전 lifecycle)이 lazy import의 1차 게이트 역할을 합니다.
            </p>

            <h2>크래시 복구</h2>
            <p>
              데몬에서 잡히지 않은 예외는 요청 디스패처 최상단에서 포착되고, 전체
              traceback과 함께 로깅되며, 구조화된 오류 프레임이 CLI로 반환됩니다.
              데몬은 살아있고, 실패한 호출만 죽습니다. <code>geode serve</code>를{" "}
              <code>--auto-restart</code>로 실행하면 하드 크래시 시 재spawn 합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Five phases</h2>
            <pre>{`1. Bootstrap     — read config, init paths, register hooks, set ContextVars
2. Wire          — start MCP servers, load tools, discover skills, mount domain plugins
3. Serve         — listen on IPC, accept commands, drive AgenticLoop
4. Drain         — finish pending tool calls, flush queues, close LLM clients
5. Shutdown      — close IPC socket, write session log, exit`}</pre>

            <h2>Entry points</h2>
            <table>
              <thead><tr><th>File</th><th>Role</th></tr></thead>
              <tbody>
                <tr><td><code>core/runtime.py</code></td><td>top-level <code>bootstrap()</code></td></tr>
                <tr><td><code>core/wiring/</code> (5 modules)</td><td>phase implementations + signal handlers</td></tr>
                <tr><td><code>core/server/</code> (10 modules)</td><td>IPC listener, request dispatch, daemon main loop</td></tr>
              </tbody>
            </table>

            <h2>Signals</h2>
            <ul>
              <li><strong>SIGTERM</strong> — graceful drain, then shutdown</li>
              <li><strong>SIGINT</strong> — interrupt current LLM call (<code>UserCancelledError</code> propagates), keep daemon alive</li>
              <li><strong>SIGHUP</strong> — reload config (env vars, model registry)</li>
            </ul>

            <h2>Client capability handshake (since v0.84)</h2>
            <p>
              The thin CLI sends a <code>client_capability</code> message to the daemon immediately on connect:
              <code>{`{"type": "client_capability", "is_tty": bool, "width": int}`}</code>. The daemon
              uses those values to build a per-thread Rich Console, suppressing ANSI escapes and spinner
              frames for non-TTY clients.
            </p>
            <pre>{`# core/cli/ipc_client.py
def _send_client_capability(self) -> None:
    """Send terminal capability to the daemon."""
    is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    width = shutil.get_terminal_size((80, 24)).columns
    self._send({
        "type": "client_capability",
        "is_tty": is_tty,
        "width": width,
    })

# core/server/ipc_server/poller.py
# receives client_capability and stores it per-connection`}</pre>

            <h2>ContextVar wiring</h2>
            <p>
              Bootstrap sets <code>ContextVar</code> instances for current session,
              current model, current user profile, and current hook system. The
              agentic loop and tool handlers read these via <code>get_*()</code>{" "}
              accessors instead of receiving them as arguments.
            </p>
            <p>
              CLAUDE.md anti-pattern: a <code>get_*()</code> accessor without a
              corresponding <code>set_*()</code> in bootstrap silently returns{" "}
              <code>None</code> and the dependent feature degrades silently. The
              Wiring Verification table in CLAUDE.md is the gate against this.
            </p>

            <h2>Hook events fired</h2>
            <ul>
              <li><code>SESSION_START</code> — at the end of bootstrap</li>
              <li><code>SESSION_END</code> — at the start of drain</li>
              <li><code>MODEL_SWITCHED</code> — when <code>/model</code> rotates</li>
              <li><code>CONTEXT_RESET</code> — on <code>/clear</code></li>
            </ul>

            <h2>Cold start (v0.85 to v0.89)</h2>
            <p>
              Across v0.85 to v0.89 a number of SDKs (anthropic, numpy, pydantic, importlib.metadata, etc.) moved to lazy
              loading. Result: cumulative cold start cut by 258ms, warm cold-start cut by 86% (~33ms). Modules
              341 to 167 (−174). The wiring module (formerly lifecycle) is the primary lazy-import gate.
            </p>

            <h2>Crash recovery</h2>
            <p>
              Unhandled exceptions in the daemon are caught at the top of the
              request dispatcher, logged with full traceback, and a structured
              error frame is returned to the CLI. The daemon stays alive — only
              the failing call dies. <code>geode serve</code> with{" "}
              <code>--auto-restart</code> respawns on hard crash.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
