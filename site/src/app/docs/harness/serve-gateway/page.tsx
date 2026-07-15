import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Serve and gateway — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/serve-gateway"
      title="Serve and gateway"
      titleKo="Serve와 게이트웨이"
      summary="Operating the serve daemon's messaging gateway. Receivers, binding routing, lane queue."
      summaryKo="serve 데몬의 메신저 게이트웨이를 운영합니다. receiver, binding 라우팅, lane queue를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              게이트웨이는 serve 데몬 안에서 메신저 메시지를 받아 GEODE 실행으로
              넘기는 라우터입니다. Slack Socket Mode와 플랫폼 poller가 메시지를
              받고, binding이 어느 채널을 받을지 결정하며, lane queue가 동시성을
              제한합니다. 라우팅에는 LLM 대신 정적 규칙만 씁니다.
            </p>

            <h2>동작 구조</h2>
            <figure>
              <img
                src="/geode/diagrams/gateway-routing.svg"
                alt="Gateway routing: Slack Socket Mode and Discord or Telegram pollers feed the ChannelManager binding match; unmatched messages are ignored, matched ones pass the LaneQueue into AgenticLoop in DAEMON mode"
              />
              <figcaption>binding에 일치한 메시지만 레인을 거쳐 루프에 닿습니다. 불일치는 무시됩니다.</figcaption>
            </figure>
            <table>
              <thead>
                <tr><th>구성 요소</th><th>역할</th><th>코드</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>메신저 receiver</td>
                  <td>Slack은 Socket Mode push를 ACK 후 처리합니다. Discord와 Telegram은 주기적으로 조회합니다. 공통 스레드 수명주기는 BasePoller가 가집니다.</td>
                  <td><code>core/server/supervised/</code></td>
                </tr>
                <tr>
                  <td>ChannelManager</td>
                  <td>binding 규칙으로 인바운드 메시지를 라우팅합니다. channel과 channel_id가 정확히 일치해야 통과합니다.</td>
                  <td><code>core/messaging/binding.py</code></td>
                </tr>
                <tr>
                  <td>LaneQueue</td>
                  <td>세션 키 단위 직렬화와 전역 동시성 상한입니다. 모든 실행 경로가 SessionLane과 global lane을 차례로 통과합니다.</td>
                  <td><code>core/orchestration/lane_queue.py</code></td>
                </tr>
                <tr>
                  <td>CLIPoller</td>
                  <td>thin CLI의 IPC 요청을 받는 데몬 쪽 서버입니다. 메신저 receiver와 같은 lane 규칙을 따릅니다.</td>
                  <td><code>core/server/ipc_server/poller.py</code></td>
                </tr>
              </tbody>
            </table>
            <p>
              데몬 모드 세션은 headless이므로 승인을 받을 사용자가 없습니다.
              그래서 <code>run_bash</code>와 <code>delegate_task</code>는
              게이트웨이 경로에서 차단됩니다
              (<code>core/server/supervised/services.py</code>).
            </p>

            <h2>시작과 종료</h2>
            <p>
              <code>geode serve</code>는 <code>gateway_enabled</code>가 꺼져
              있으면 시작을 거부합니다. <code>~/.geode/.env</code>에{" "}
              <code>GEODE_GATEWAY_ENABLED=true</code>를 추가해야 합니다. 대화만
              한다면 serve를 직접 띄울 필요가 없습니다. bare <code>geode</code>가
              데몬을 자동으로 시작합니다.
            </p>
            <pre>{`# 게이트웨이 켜기
echo 'GEODE_GATEWAY_ENABLED=true' >> ~/.geode/.env
geode serve            # 포그라운드, --poll은 poll 기반 receiver 주기

# 살아 있는지 확인
pgrep -f "geode serve"

# 재시작 (설정 변경 후)
pkill -f "geode serve"
geode serve &`}</pre>
            <p>
              종료는 단계적입니다. <code>SHUTDOWN_STARTED</code> 훅 발화, 신규
              연결 차단, 활성 세션 30초 drain, 스케줄러 저장과 정지, MCP 종료,
              게이트웨이 정지 순서입니다 (<code>core/cli/typer_serve.py</code>).
            </p>

            <h2>binding 설정</h2>
            <p>
              어느 채널이 GEODE를 깨울 수 있는지는 binding 규칙이 결정합니다.
              규칙 작성법은 <a href="/geode/docs/guides/binding">바인딩 설정
              가이드</a>에서 다루고, 형식만 요약하면 이렇습니다.
            </p>
            <pre>{`# .geode/config.toml
[gateway]
pollers = ["slack"]          # 띄울 receiver 등록명
time_budget_s = 120          # 메시지당 wall-clock 기본값

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"     # 필수. 비어 있으면 규칙이 건너뜀
require_mention = true`}</pre>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>geode serve</code>가 즉시 종료</td>
                  <td><code>gateway_enabled</code> 꺼짐</td>
                  <td><code>GEODE_GATEWAY_ENABLED=true</code>를 <code>~/.geode/.env</code>에 추가합니다.</td>
                </tr>
                <tr>
                  <td>메시지에 반응이 없음</td>
                  <td>binding 불일치, 앱 토큰 누락, 또는 채널 멤버십 없음</td>
                  <td><code>geode doctor slack</code>으로 점검하고, 출력된 링크의 채널에서 <code>/invite @geode</code>를 실행합니다.</td>
                </tr>
                <tr>
                  <td>배너 모델과 응답 모델이 다름</td>
                  <td>데몬이 둘 이상 떠서 소켓을 두고 경합</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>로 전부 내린 뒤 하나만 다시 띄웁니다. <code>ps aux | grep</code>은 경로가 잘려 빈 결과가 나오므로 <code>pgrep -f</code>를 씁니다.</td>
                </tr>
                <tr>
                  <td>같은 채널 요청이 밀림</td>
                  <td>같은 세션 키는 의도적으로 직렬화</td>
                  <td>정상 동작입니다. 다른 스레드나 채널로 보내면 병렬로 처리됩니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              데몬 로그는 <code>~/.geode/logs/serve.log</code>에 10MB 단위 5개
              파일로 로테이션됩니다
              (<code>core/observability/logging_config.py</code>).
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/run/messaging">메신저 연동</a>. 플랫폼별 토큰과 설정.</li>
              <li><a href="/geode/docs/guides/binding">바인딩 설정</a>. 규칙 작성과 검증.</li>
              <li><a href="/geode/docs/harness/lifecycle">라이프사이클</a>. 데몬의 부트와 종료 순서.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The gateway is the router inside the serve daemon that turns
              messenger traffic into GEODE runs. Slack Socket Mode and
              platform pollers receive messages, bindings decide which
              channels are allowed, and the lane queue bounds concurrency.
              Routing uses static rules only, never an LLM.
            </p>

            <h2>How it works</h2>
            <figure>
              <img
                src="/geode/diagrams/gateway-routing.svg"
                alt="Gateway routing: Slack Socket Mode and Discord or Telegram pollers feed the ChannelManager binding match; unmatched messages are ignored, matched ones pass the LaneQueue into AgenticLoop in DAEMON mode"
              />
              <figcaption>Only a message that matches a binding passes the lanes into the loop; the rest are ignored.</figcaption>
            </figure>
            <table>
              <thead>
                <tr><th>Component</th><th>Role</th><th>Code</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Messaging receivers</td>
                  <td>Slack ACKs pushed Socket Mode events before processing. Discord and Telegram poll. BasePoller owns the shared thread lifecycle.</td>
                  <td><code>core/server/supervised/</code></td>
                </tr>
                <tr>
                  <td>ChannelManager</td>
                  <td>Routes inbound messages by binding rules. A message passes only on an exact channel plus channel_id match.</td>
                  <td><code>core/messaging/binding.py</code></td>
                </tr>
                <tr>
                  <td>LaneQueue</td>
                  <td>Per-session-key serialization plus a global concurrency cap. Every execution path acquires the SessionLane, then the global lane.</td>
                  <td><code>core/orchestration/lane_queue.py</code></td>
                </tr>
                <tr>
                  <td>CLIPoller</td>
                  <td>The daemon-side server for thin-CLI IPC requests. It follows the same lane rules as the messaging receivers.</td>
                  <td><code>core/server/ipc_server/poller.py</code></td>
                </tr>
              </tbody>
            </table>
            <p>
              Daemon-mode sessions are headless, so there is no user to approve
              anything. <code>run_bash</code> and <code>delegate_task</code> are
              therefore denied on the gateway path
              (<code>core/server/supervised/services.py</code>).
            </p>

            <h2>Start and stop</h2>
            <p>
              <code>geode serve</code> refuses to start while{" "}
              <code>gateway_enabled</code> is off. Add{" "}
              <code>GEODE_GATEWAY_ENABLED=true</code> to{" "}
              <code>~/.geode/.env</code>. For chat only you never start serve
              yourself; bare <code>geode</code> auto-starts the daemon.
            </p>
            <pre>{`# enable the gateway
echo 'GEODE_GATEWAY_ENABLED=true' >> ~/.geode/.env
geode serve            # foreground; --poll tunes poll-based receivers

# is it alive?
pgrep -f "geode serve"

# restart after a config change
pkill -f "geode serve"
geode serve &`}</pre>
            <p>
              Shutdown is staged: fire the <code>SHUTDOWN_STARTED</code> hook,
              stop accepting connections, drain active sessions for up to 30
              seconds, save and stop the scheduler, shut down MCP, then stop the
              gateway (<code>core/cli/typer_serve.py</code>).
            </p>

            <h2>Binding configuration</h2>
            <p>
              Binding rules decide which channels can wake GEODE. The{" "}
              <a href="/geode/docs/guides/binding">binding guide</a> covers rule
              authoring; the shape in brief:
            </p>
            <pre>{`# .geode/config.toml
[gateway]
pollers = ["slack"]          # receiver registration names
time_budget_s = 120          # default wall-clock per message

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"     # required; an empty id skips the rule
require_mention = true`}</pre>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>geode serve</code> exits immediately</td>
                  <td><code>gateway_enabled</code> is off</td>
                  <td>Add <code>GEODE_GATEWAY_ENABLED=true</code> to <code>~/.geode/.env</code>.</td>
                </tr>
                <tr>
                  <td>No reaction to messages</td>
                  <td>Binding mismatch, missing app token, or missing channel membership</td>
                  <td>Run <code>geode doctor slack</code>, open its channel link, and run <code>/invite @geode</code>.</td>
                </tr>
                <tr>
                  <td>Banner model differs from the answering model</td>
                  <td>Multiple daemons fighting over the socket</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>, then start exactly one. Use <code>pgrep -f</code>, not <code>ps aux | grep</code>; ps truncates the long path and matches nothing.</td>
                </tr>
                <tr>
                  <td>Requests in one channel queue up</td>
                  <td>Same session key serializes by design</td>
                  <td>Expected. Different threads or channels run in parallel.</td>
                </tr>
              </tbody>
            </table>
            <p>
              Daemon logs rotate at <code>~/.geode/logs/serve.log</code>, five
              files of 10MB each
              (<code>core/observability/logging_config.py</code>).
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/run/messaging">Messaging integrations</a>. Per-platform tokens and setup.</li>
              <li><a href="/geode/docs/guides/binding">Configure a binding</a>. Rule authoring and verification.</li>
              <li><a href="/geode/docs/harness/lifecycle">Lifecycle</a>. The daemon&apos;s boot and shutdown order.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
