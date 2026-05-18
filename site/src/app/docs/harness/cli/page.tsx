import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "CLI & Slash Commands — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/cli"
      title="CLI & Slash Commands"
      titleKo="CLI와 슬래시 명령"
      summary="Thin client → IPC → serve daemon. 57 modules, 28 slash commands. Auto-starts the daemon on first call."
      summaryKo="Thin 클라이언트에서 IPC를 거쳐 serve 데몬으로. 57개 모듈, 28개 슬래시 명령. 첫 호출 시 데몬을 자동 기동합니다."
    >
      <Bi
        ko={
          <>
            <h2>2-프로세스 아키텍처</h2>
            <pre>{`User
  │
  ▼
geode CLI  (thin client, ~57 modules)
  │
  │  IPC (unix socket / stdio)
  ▼
geode serve  (daemon, hosts AgenticLoop + state)
  │
  ▼
LLM provider`}</pre>
            <p>
              Thin CLI는 시작 지연을 낮게 유지해 일회성 명령이 즉각적으로 느껴지게
              합니다. 데몬은 장기 상태 (AgenticLoop 컨텍스트, MCP 서버 프로세스,
              스케줄러)를 보유하므로 <code>/resume</code>이나 멀티턴 흐름이 매번
              부트스트랩을 다시 할 필요가 없습니다.
            </p>

            <h2>자동 기동</h2>
            <p>
              첫 <code>geode</code> 호출 시 데몬이 실행되어 있지 않으면 CLI가
              데몬을 spawn하고 프록시 역할을 합니다. <code>geode serve</code>가
              명시적 기동이고, <code>/stop</code>이 깨끗하게 종료합니다.
            </p>

            <h2>최상위 명령</h2>
            <pre>{`geode                                      # interactive REPL
geode "summarize the latest AI research"   # NL one-shot
geode serve                                # start daemon
geode version                              # version
geode skill list / skill view / skill manage`}</pre>

            <h2>슬래시 명령 (REPL)</h2>
            <table>
              <thead><tr><th>명령</th><th>효과</th></tr></thead>
              <tbody>
                <tr><td><code>/login</code></td><td>인증 대시보드. Plans, Profiles, Routing. 서브커맨드: <code>oauth &lt;provider&gt;</code>, <code>set-key &lt;plan-id&gt; &lt;key&gt;</code>, <code>use &lt;plan-id&gt;</code>, <code>route</code>, <code>quota</code>. LLM 에이전트 대응: <code>manage_login</code> 도구.</td></tr>
                <tr><td><code>/model &lt;name&gt;</code></td><td>활성 모델 전환. <code>MODEL_SWITCHED</code> 훅 발화 + 시스템 프롬프트 재빌드.</td></tr>
                <tr><td><code>/skip</code></td><td>현재 대기 중인 도구 호출 스킵 (HITL 승인 중 사용).</td></tr>
                <tr><td><code>/resume</code></td><td>마지막 세션의 메시지 이력과 상태 복원.</td></tr>
                <tr><td><code>/clear</code></td><td>인프로세스 컨텍스트 리셋. 영속 저장 없음.</td></tr>
                <tr><td><code>/stop</code></td><td>데몬 정지. 설정 시 세션 저장.</td></tr>
                <tr><td><code>/clean</code></td><td>임시 산출물 제거 (캐시, IPC 소켓).</td></tr>
                <tr><td><code>/uninstall</code></td><td>GEODE 상태 디렉터리 제거 (확인 후).</td></tr>
                <tr><td><code>/status</code></td><td>데몬, 모델, MCP 서버, 훅 상태 표시.</td></tr>
                <tr><td><code>/help</code></td><td>인라인 도움말.</td></tr>
              </tbody>
            </table>

            <h2><code>manage_login</code> 에이전틱 도구</h2>
            <p>
              <code>/login</code>의 에이전틱 대응물입니다. 서브커맨드는 슬래시
              명령과 거울처럼 대응하고, 반환값은 구조화된 스냅샷
              (<code>plans</code>, <code>profiles</code>, <code>routing</code>)입니다.
              에이전트가 인증 상태를 스스로 진단하고 사용자에게 왕복하지 않은 채
              교정 단계를 제시할 수 있게 합니다.
            </p>

            <h2>파일</h2>
            <ul>
              <li><code>core/cli/commands.py:41</code>. <code>ModelProfile</code>과 슬래시 명령 디스패치.</li>
              <li><code>core/cli/agentic_loop.py</code>. REPL 부트스트랩과 AgenticLoop 배선.</li>
              <li><code>core/cli/result_cache.py</code>. 콘텐츠 해시 기반 24시간 TTL 캐시.</li>
              <li><code>core/cli/effort_picker.py</code>. 대화형 effort 선택기.</li>
            </ul>

            <h2>Bash 통합</h2>
            <p>
              <code>geode-exec</code>는 현재 셸에서 일회성 에이전트 명령을
              실행하며, 출력은 일반 Unix 도구처럼 캡처됩니다. cron이나 스크립팅에
              유용합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Two-process architecture</h2>
            <pre>{`User
  │
  ▼
geode CLI  (thin client, ~57 modules)
  │
  │  IPC (unix socket / stdio)
  ▼
geode serve  (daemon, hosts AgenticLoop + state)
  │
  ▼
LLM provider`}</pre>
            <p>
              The thin CLI keeps startup latency low and makes one-shot commands
              feel instant. The daemon owns the long-lived state (AgenticLoop
              context, MCP server processes, scheduler) so that{" "}
              <code>/resume</code> and multi-turn flows do not have to re-bootstrap.
            </p>

            <h2>Auto-start</h2>
            <p>
              On first <code>geode</code> invocation if the daemon is not running,
              the CLI spawns it and proxies. <code>geode serve</code> is the
              explicit start; <code>/stop</code> shuts it down cleanly.
            </p>

            <h2>Top-level commands</h2>
            <pre>{`geode                                      # interactive REPL
geode "summarize the latest AI research"   # NL one-shot
geode serve                                # start daemon
geode version                              # version
geode skill list / skill view / skill manage`}</pre>

            <h2>Slash commands (REPL)</h2>
            <table>
              <thead><tr><th>Command</th><th>Effect</th></tr></thead>
              <tbody>
                <tr><td><code>/login</code></td><td>Auth dashboard — Plans, Profiles, Routing. Subcommands: <code>oauth &lt;provider&gt;</code>, <code>set-key &lt;plan-id&gt; &lt;key&gt;</code>, <code>use &lt;plan-id&gt;</code>, <code>route</code>, <code>quota</code>. LLM-agentic counterpart: <code>manage_login</code> tool.</td></tr>
                <tr><td><code>/model &lt;name&gt;</code></td><td>Switch active model. Triggers <code>MODEL_SWITCHED</code> hook + system-prompt rebuild.</td></tr>
                <tr><td><code>/skip</code></td><td>Skip the current pending tool call (used during HITL approval).</td></tr>
                <tr><td><code>/resume</code></td><td>Restore the last session&apos;s message history + state.</td></tr>
                <tr><td><code>/clear</code></td><td>Reset in-process context. Persists nothing.</td></tr>
                <tr><td><code>/stop</code></td><td>Halt the daemon. Saves session if configured.</td></tr>
                <tr><td><code>/clean</code></td><td>Remove temp artifacts (cache, IPC sockets).</td></tr>
                <tr><td><code>/uninstall</code></td><td>Remove GEODE state directories (with confirmation).</td></tr>
                <tr><td><code>/status</code></td><td>Show daemon, model, MCP server, hook status.</td></tr>
                <tr><td><code>/help</code></td><td>Inline help.</td></tr>
              </tbody>
            </table>

            <h2><code>manage_login</code> agentic tool</h2>
            <p>
              The agentic counterpart of <code>/login</code>. Subcommands mirror the slash command, and
              the return is a structured snapshot — <code>plans</code>, <code>profiles</code>,
              <code>routing</code> — so the agent can self-diagnose auth state and surface remediation
              steps without a round trip to the user.
            </p>

            <h2>Files</h2>
            <ul>
              <li><code>core/cli/commands.py:41</code> — <code>ModelProfile</code> + slash command dispatch</li>
              <li><code>core/cli/agentic_loop.py</code> — REPL bootstrap + AgenticLoop wiring</li>
              <li><code>core/cli/result_cache.py</code> — 24h TTL cache with content hash</li>
              <li><code>core/cli/effort_picker.py</code> — interactive effort selector</li>
            </ul>

            <h2>Bash integration</h2>
            <p>
              <code>geode-exec</code> runs a one-shot agent command in the current
              shell, capturing output as a normal Unix tool. Useful for cron and
              scripting.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
