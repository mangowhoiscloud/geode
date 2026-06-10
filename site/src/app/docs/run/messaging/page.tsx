import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Messaging Integrations — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/messaging"
      title="Messaging Integrations"
      titleKo="메신저 연동"
      summary="Hook GEODE into Slack, Discord, or Telegram via gateway adapters."
      summaryKo="게이트웨이 어댑터로 Slack, Discord, Telegram에 연결."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE의 gateway 어댑터를 통해 Slack·Discord·Telegram 등 메신저에 연결하는 절차입니다.</p>

            <h2>지원 채널</h2>
            <ul>
              <li>Slack (Slash command + thread)</li>
              <li>Discord (slash command)</li>
              <li>Telegram (bot API)</li>
            </ul>

            <h2>Slack 예시</h2>
            <pre>{`# config.toml
[gateway.slack]
bot_token = "xoxb-..."
signing_secret = "..."
channels = ["#geode"]`}</pre>
            <p>설정 후 <code>geode serve</code> 재시작하면 자동 binding 됩니다.</p>

            <h2>커스텀 어댑터</h2>
            <p>새 메신저를 붙이려면 <code>core/gateway/</code>의 base adapter를 구현하세요. 자세한 절차는 <a href="/geode/docs/runtime/tools/protocol">도구 추가하기</a>를 참조.</p>

            <p className="text-[var(--ink-3)] text-sm"><em>참조:</em> wiki/concepts/geode-gateway.md, geode-serve skill</p>
          </>
        }
        en={
          <>
            <p>This guide wires GEODE to messengers (Slack, Discord, Telegram) through gateway adapters.</p>

            <h2>Supported channels</h2>
            <ul>
              <li>Slack (slash command + thread)</li>
              <li>Discord (slash command)</li>
              <li>Telegram (bot API)</li>
            </ul>

            <h2>Slack example</h2>
            <pre>{`# config.toml
[gateway.slack]
bot_token = "xoxb-..."
signing_secret = "..."
channels = ["#geode"]`}</pre>
            <p>After saving, restart <code>geode serve</code> to bind.</p>

            <h2>Custom adapter</h2>
            <p>To support a new messenger, implement the base adapter under <code>core/gateway/</code>. See <a href="/geode/docs/runtime/tools/protocol">Add a Tool</a> for the general pattern.</p>

            <p className="text-[var(--ink-3)] text-sm"><em>See:</em> wiki/concepts/geode-gateway.md, geode-serve skill.</p>
          </>
        }
      />
    </DocsShell>
  );
}
