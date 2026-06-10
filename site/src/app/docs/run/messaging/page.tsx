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
              메신저 연동은 serve 데몬의 게이트웨이가 담당합니다. 플랫폼별
              poller가 메시지를 끌어오고, binding 규칙에 맞는 채널만 GEODE
              실행으로 흘러갑니다. 연동에 필요한 것은 셋입니다. 봇 토큰, 게이트웨이
              활성화, binding 규칙입니다.
            </p>

            <h2>지원 채널</h2>
            <table>
              <thead>
                <tr><th>채널</th><th>토큰 환경 변수</th><th>Poller</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Slack</td>
                  <td><code>SLACK_BOT_TOKEN</code></td>
                  <td><code>core/server/supervised/slack_poller.py</code></td>
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
              토큰은 시크릿이므로 <code>~/.geode/.env</code>에 둡니다. poller는
              해당 환경 변수가 비어 있으면 자신을 미설정 상태로 보고합니다
              (<code>core/server/supervised/poller_base.py</code>).
            </p>

            <h2>Slack 연동 절차</h2>
            <pre>{`# 1) 토큰을 시크릿 레이어에 저장
echo 'SLACK_BOT_TOKEN=xoxb-...' >> ~/.geode/.env
echo 'GEODE_GATEWAY_ENABLED=true' >> ~/.geode/.env

# 2) binding 규칙 선언 (.geode/config.toml)
#    channel_id가 없는 규칙은 안전상 건너뜁니다
[gateway]
pollers = ["slack"]

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"
require_mention = true

# 3) 데몬 재시작
pkill -f "geode serve"
geode serve &

# 4) 점검
geode doctor slack`}</pre>
            <p>
              binding 필드 각각의 의미와 검증 방법은{" "}
              <a href="/geode/docs/guides/binding">바인딩 설정 가이드</a>에
              있습니다. Discord와 Telegram도 같은 구조입니다. 토큰 환경 변수와{" "}
              <code>pollers</code> 목록, <code>channel</code> 값만 바뀝니다.
            </p>

            <h2>메시지가 실행되는 방식</h2>
            <p>
              매칭된 메시지는 channel, channel_id, 발신자, 스레드로 세션 키를
              만들어 같은 스레드의 대화가 하나의 세션으로 이어집니다
              (<code>core/memory/session_key.py</code>). 실행은 DAEMON 모드라
              승인 프롬프트가 없고, 그래서 <code>run_bash</code>와{" "}
              <code>delegate_task</code>는 차단됩니다. 메시지당 wall-clock
              예산은 binding의 <code>time_budget_s</code>가 정하며 기본 120초입니다
              (<code>core/messaging/models.py</code>).
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
                  <td><code>SLACK_BOT_TOKEN</code>이 .env에 없음</td>
                  <td><code>~/.geode/.env</code>에 추가하고 데몬을 재시작합니다.</td>
                </tr>
                <tr>
                  <td>멘션 없는 메시지에 응답하지 않음</td>
                  <td><code>require_mention = true</code></td>
                  <td>의도된 동작입니다. 모든 메시지에 반응하게 하려면 false로 둡니다.</td>
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
              <li><a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>. poller와 lane의 동작 구조.</li>
              <li><a href="/geode/docs/guides/binding">바인딩 설정</a>. 규칙 필드와 리로드.</li>
              <li><a href="/geode/docs/run/schedule">작업 예약</a>. 메신저로 결과를 받는 정기 작업.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Messaging runs through the serve daemon&apos;s gateway. A
              per-platform poller pulls messages in, and only channels matching
              a binding rule flow into GEODE execution. Three things are
              required: a bot token, the gateway flag, and a binding rule.
            </p>

            <h2>Supported channels</h2>
            <table>
              <thead>
                <tr><th>Channel</th><th>Token env var</th><th>Poller</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Slack</td>
                  <td><code>SLACK_BOT_TOKEN</code></td>
                  <td><code>core/server/supervised/slack_poller.py</code></td>
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
              A poller reports itself unconfigured while its env var is empty
              (<code>core/server/supervised/poller_base.py</code>).
            </p>

            <h2>Wiring Slack</h2>
            <pre>{`# 1) put the token on the secrets layer
echo 'SLACK_BOT_TOKEN=xoxb-...' >> ~/.geode/.env
echo 'GEODE_GATEWAY_ENABLED=true' >> ~/.geode/.env

# 2) declare a binding (.geode/config.toml)
#    a rule without channel_id is skipped for safety
[gateway]
pollers = ["slack"]

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"
require_mention = true

# 3) restart the daemon
pkill -f "geode serve"
geode serve &

# 4) check
geode doctor slack`}</pre>
            <p>
              Field semantics and verification live in the{" "}
              <a href="/geode/docs/guides/binding">binding guide</a>. Discord
              and Telegram follow the same shape; only the token env var, the{" "}
              <code>pollers</code> list, and the <code>channel</code> value
              change.
            </p>

            <h2>How a message executes</h2>
            <p>
              A matched message builds a session key from channel, channel_id,
              sender, and thread, so a thread&apos;s conversation continues as
              one session (<code>core/memory/session_key.py</code>). Execution
              runs in DAEMON mode with no approval prompt, which is why{" "}
              <code>run_bash</code> and <code>delegate_task</code> are denied.
              The per-message wall-clock budget comes from the binding&apos;s{" "}
              <code>time_budget_s</code>, 120 seconds by default
              (<code>core/messaging/models.py</code>).
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
                  <td><code>SLACK_BOT_TOKEN</code> absent from .env</td>
                  <td>Add it to <code>~/.geode/.env</code> and restart the daemon.</td>
                </tr>
                <tr>
                  <td>No reply unless mentioned</td>
                  <td><code>require_mention = true</code></td>
                  <td>Intended. Set it to false to react to every message.</td>
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
              <li><a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>. How pollers and lanes fit together.</li>
              <li><a href="/geode/docs/guides/binding">Configure a binding</a>. Rule fields and reload.</li>
              <li><a href="/geode/docs/run/schedule">Schedule tasks</a>. Recurring work delivered to a messenger.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
