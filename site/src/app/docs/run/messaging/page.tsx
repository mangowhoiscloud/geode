import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Messaging integrations — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/messaging"
      title="Messaging integrations"
      titleKo="메신저 연동"
      summary="Connect GEODE to Slack, Discord, or Telegram through gateway adapters."
      summaryKo="게이트웨이 어댑터로 GEODE를 Slack, Discord, Telegram에 연결합니다."
    >
      <Bi
        ko={
          <>
            <p>
              메신저 연동은 serve 데몬의 게이트웨이가 담당합니다. Slack은 Socket
              Mode로 이벤트를 push 받고, Discord와 Telegram은 poller가 메시지를
              가져옵니다. binding 규칙에 맞는 채널만 GEODE 실행으로 흘러갑니다.
            </p>

            <h2>지원 채널</h2>
            <table>
              <thead>
                <tr><th>채널</th><th>토큰 환경 변수</th><th>수신 방식</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Slack</td>
                  <td><code>SLACK_BOT_TOKEN</code> + <code>SLACK_APP_TOKEN</code></td>
                  <td>Socket Mode (push)</td>
                </tr>
                <tr>
                  <td>Discord</td>
                  <td><code>DISCORD_BOT_TOKEN</code></td>
                  <td><code>core/server/supervised/discord_poller.py</code></td>
                </tr>
                <tr>
                  <td>Telegram</td>
                  <td><code>TELEGRAM_BOT_TOKEN</code></td>
                  <td><code>core/server/supervised/telegram_poller.py</code></td>
                </tr>
              </tbody>
            </table>
            <p>
              토큰은 시크릿이므로 <code>~/.geode/.env</code>에 둡니다. Slack의
              <code>xoxb-</code> 봇 토큰은 Web API 발신에, <code>xapp-</code> 앱
              토큰은 Socket Mode 연결에 각각 사용됩니다. 앱 토큰이 없으면 이전
              history polling 경로로 폴백하지만 doctor는 이를 DEGRADED로 표시합니다.
            </p>

            <h2>Slack 연동 절차</h2>
            <p>
              Slack 앱에서 Socket Mode를 켜고, <code>connections:write</code> 범위의
              app-level token을 만듭니다. Bot Token Scopes에는{" "}
              <code>app_mentions:read</code>, <code>chat:write</code>,{" "}
              <code>channels:history</code>, <code>channels:read</code>를 넣고 bot
              event <code>app_mention</code>, <code>message.channels</code>를 구독한 뒤
              앱을 재설치합니다.
            </p>
            <pre>{`# 1) 두 토큰을 시크릿 레이어에 저장
echo 'SLACK_BOT_TOKEN=xoxb-...' >> ~/.geode/.env
echo 'SLACK_APP_TOKEN=xapp-...' >> ~/.geode/.env
echo 'GEODE_GATEWAY_ENABLED=true' >> ~/.geode/.env

# 2) binding 규칙 선언 (.geode/config.toml)
#    channel_id가 없는 규칙은 안전상 건너뜁니다
[gateway]
pollers = ["slack"]
allow_computer_use = false

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"
require_mention = true

# 3) Slack 채널에서 /invite @geode 후 데몬 재시작
pkill -f "geode serve"
geode serve &

# 4) 점검
geode doctor slack`}</pre>
            <p>
              binding 필드 각각의 의미와 검증 방법은{" "}
              <a href="/geode/docs/guides/binding">바인딩 설정 가이드</a>에
              있습니다. <code>geode doctor slack</code>은 앱 토큰, 봇 scope, 각
              binding의 채널 멤버십과 클릭 가능한 채널 링크까지 검사합니다.
            </p>

            <h2>메시지가 실행되는 방식</h2>
            <p>
              매칭된 메시지는 channel, channel_id, 발신자, 스레드로 세션 키를
              만들어 같은 스레드의 대화가 하나의 세션으로 이어집니다
              (<code>core/memory/session_key.py</code>). 실행은 DAEMON 모드라
              승인 프롬프트가 없고, 그래서 <code>run_bash</code>와{" "}
              <code>delegate_task</code>, 원격 desktop control은 기본
              차단됩니다. 메시지당 wall-clock 예산은 binding의{" "}
              <code>time_budget_s</code>가 정하며 기본 120초입니다
              (<code>core/messaging/models.py</code>).
            </p>
            <p>
              <code>require_mention = true</code>여도 새 대화의 첫 메시지만
              GEODE를 멘션하면 됩니다. 첫 메시지의 루트 timestamp가 처음부터
              thread/session/checkpoint 키가 되며, GEODE가 참여한 스레드의 이후
              사람 대댓글은 재멘션 없이 같은 문맥을 이어갑니다. 데몬 재시작
              뒤에도 ACTIVE 또는 PAUSED 체크포인트의 메시지와 상태를 CLI resume
              경로로 복원합니다.
            </p>

            <h2>메신저에서 computer use</h2>
            <p>
              먼저 <code>geode doctor</code>에서{" "}
              <code>computer-use desktop</code>이 정상인지 확인합니다. 그 다음
              멤버십이 제한된 비공개 binding에서만 아래처럼 원격 제어를
              명시적으로 엽니다. 옵션이 꺼져 있으면 provider-visible schema가
              있더라도 DAEMON executor가 <code>computer</code>와{" "}
              <code>computer_use</code>를 dispatch 전에 거부합니다.
            </p>
            <pre>{`[computer_use]
enabled = true
env = "host"
driver = "helper"

[gateway]
allow_computer_use = true`}</pre>
            <p>
              이 옵션은 Slack뿐 아니라 같은 DAEMON 실행 경계를 쓰는 모든
              gateway binding에 적용됩니다. binding을 통과한 모든 발신자가
              desktop action을 요청할 수 있으므로 제한된 채널에서만 사용하세요.
              <code>run_bash</code>, <code>delegate_task</code>,
              personal-workspace 도구, scheduler, MCP <code>run_agent</code> 차단은
              유지됩니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>봇이 아무 채널에도 반응하지 않음</td>
                  <td>binding 규칙 없음 또는 channel_id 불일치</td>
                  <td>바인딩 없는 채널은 무시가 기본값입니다. 규칙의 <code>channel_id</code>를 실제 ID로 맞춥니다.</td>
                </tr>
                <tr>
                  <td><code>geode doctor slack</code>이 토큰 누락 보고</td>
                  <td><code>SLACK_BOT_TOKEN</code> 또는 <code>SLACK_APP_TOKEN</code>이 .env에 없음</td>
                  <td>두 토큰을 <code>~/.geode/.env</code>에 추가하고 데몬을 재시작합니다.</td>
                </tr>
                <tr>
                  <td><code>bot_member=False</code></td>
                  <td>봇이 바운드 채널에 없음</td>
                  <td>doctor가 제시한 채널 링크를 열고 <code>/invite @geode</code>를 실행합니다.</td>
                </tr>
                <tr>
                  <td>새 대화의 멘션 없는 메시지에 응답하지 않음</td>
                  <td><code>require_mention = true</code></td>
                  <td>첫 메시지는 멘션해야 합니다. 한 번 참여한 스레드의 대댓글은 재멘션 없이 이어집니다.</td>
                </tr>
                <tr>
                  <td>응답이 120초 부근에서 끊김</td>
                  <td>메시지당 time budget 도달</td>
                  <td>binding 또는 <code>[gateway]</code>의 <code>time_budget_s</code>를 올립니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>. receiver와 lane의 동작 구조.</li>
              <li><a href="/geode/docs/guides/binding">바인딩 설정</a>. 규칙 필드와 리로드.</li>
              <li><a href="/geode/docs/run/schedule">작업 예약</a>. 메신저로 결과를 받는 정기 작업.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Messaging runs through the serve daemon&apos;s gateway. Slack
              receives pushed events over Socket Mode, while Discord and
              Telegram poll. Only channels matching a binding rule flow into
              GEODE execution.
            </p>

            <h2>Supported channels</h2>
            <table>
              <thead>
                <tr><th>Channel</th><th>Token env var</th><th>Receiver</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Slack</td>
                  <td><code>SLACK_BOT_TOKEN</code> + <code>SLACK_APP_TOKEN</code></td>
                  <td>Socket Mode (push)</td>
                </tr>
                <tr>
                  <td>Discord</td>
                  <td><code>DISCORD_BOT_TOKEN</code></td>
                  <td><code>core/server/supervised/discord_poller.py</code></td>
                </tr>
                <tr>
                  <td>Telegram</td>
                  <td><code>TELEGRAM_BOT_TOKEN</code></td>
                  <td><code>core/server/supervised/telegram_poller.py</code></td>
                </tr>
              </tbody>
            </table>
            <p>
              Tokens are secrets, so they belong in <code>~/.geode/.env</code>.
              Slack uses the <code>xoxb-</code> bot token for outbound Web API
              calls and the <code>xapp-</code> app token for Socket Mode. Without
              the app token, GEODE falls back to history polling and doctor
              reports DEGRADED.
            </p>

            <h2>Wiring Slack</h2>
            <p>
              Enable Socket Mode in the Slack app and create an app-level token
              with <code>connections:write</code>. Add bot scopes{" "}
              <code>app_mentions:read</code>, <code>chat:write</code>,{" "}
              <code>channels:history</code>, and <code>channels:read</code>;
              subscribe to <code>app_mention</code> and{" "}
              <code>message.channels</code>, then reinstall the app.
            </p>
            <pre>{`# 1) put both tokens on the secrets layer
echo 'SLACK_BOT_TOKEN=xoxb-...' >> ~/.geode/.env
echo 'SLACK_APP_TOKEN=xapp-...' >> ~/.geode/.env
echo 'GEODE_GATEWAY_ENABLED=true' >> ~/.geode/.env

# 2) declare a binding (.geode/config.toml)
#    a rule without channel_id is skipped for safety
[gateway]
pollers = ["slack"]
allow_computer_use = false

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"
require_mention = true

# 3) run /invite @geode in Slack, then restart the daemon
pkill -f "geode serve"
geode serve &

# 4) check
geode doctor slack`}</pre>
            <p>
              Field semantics and verification live in the{" "}
              <a href="/geode/docs/guides/binding">binding guide</a>.{" "}
              <code>geode doctor slack</code> validates the app token, bot
              scopes, membership for every binding, and prints clickable
              channel links.
            </p>

            <h2>How a message executes</h2>
            <p>
              A matched message builds a session key from channel, channel_id,
              sender, and thread, so a thread&apos;s conversation continues as
              one session (<code>core/memory/session_key.py</code>). Execution
              runs in DAEMON mode with no approval prompt, which is why{" "}
              <code>run_bash</code>, <code>delegate_task</code>, and remote
              desktop control are denied by default. The per-message wall-clock
              budget comes from the binding&apos;s{" "}
              <code>time_budget_s</code>, 120 seconds by default
              (<code>core/messaging/models.py</code>).
            </p>
            <p>
              Even with <code>require_mention = true</code>, only the first
              message of a new conversation must mention GEODE. Its root
              timestamp becomes the thread/session/checkpoint key from turn
              one, and later human replies in the engaged thread continue the
              same context without another mention. After a daemon restart,
              ACTIVE or PAUSED checkpoint messages and machine state are
              restored through the CLI resume path.
            </p>

            <h2>Computer use from a messenger</h2>
            <p>
              First make <code>geode doctor</code> report a healthy{" "}
              <code>computer-use desktop</code> check. Then opt in only for a
              private, membership-restricted binding. While the option is off,
              the DAEMON executor rejects <code>computer</code> and{" "}
              <code>computer_use</code> before dispatch even if a
              provider-visible schema is present.
            </p>
            <pre>{`[computer_use]
enabled = true
env = "host"
driver = "helper"

[gateway]
allow_computer_use = true`}</pre>
            <p>
              The option applies to every gateway binding that shares the
              DAEMON execution boundary, not only Slack. Every sender admitted
              by a binding can request desktop actions once enabled, so use it
              only with restricted channels. <code>run_bash</code>,{" "}
              <code>delegate_task</code>, personal-workspace tools, scheduler,
              and MCP <code>run_agent</code> remain denied.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>The bot reacts in no channel at all</td>
                  <td>No binding rule, or a channel_id mismatch</td>
                  <td>Unbound channels are ignored by design. Set the rule&apos;s <code>channel_id</code> to the real ID.</td>
                </tr>
                <tr>
                  <td><code>geode doctor slack</code> reports a missing token</td>
                  <td><code>SLACK_BOT_TOKEN</code> or <code>SLACK_APP_TOKEN</code> absent from .env</td>
                  <td>Add both to <code>~/.geode/.env</code> and restart the daemon.</td>
                </tr>
                <tr>
                  <td><code>bot_member=False</code></td>
                  <td>The bot is absent from a bound channel</td>
                  <td>Open the channel link from doctor and run <code>/invite @geode</code>.</td>
                </tr>
                <tr>
                  <td>No reply to an unmentioned new conversation</td>
                  <td><code>require_mention = true</code></td>
                  <td>Mention once to engage the thread; later replies do not need another mention.</td>
                </tr>
                <tr>
                  <td>Replies cut off around 120 seconds</td>
                  <td>Per-message time budget reached</td>
                  <td>Raise <code>time_budget_s</code> on the binding or under <code>[gateway]</code>.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>. How receivers and lanes fit together.</li>
              <li><a href="/geode/docs/guides/binding">Configure a binding</a>. Rule fields and reload.</li>
              <li><a href="/geode/docs/run/schedule">Schedule tasks</a>. Recurring work delivered to a messenger.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
