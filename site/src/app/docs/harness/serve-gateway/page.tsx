import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Serve Gateway — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/serve-gateway"
      title="Serve Gateway"
      titleKo="Serve 게이트웨이"
      summary="Operations guide for the geode serve daemon's messaging gateway: Slack, Discord, Telegram pollers, binding routing, lane queue."
      summaryKo="geode serve 데몬의 메신저 게이트웨이 운영 가이드. Slack, Discord, Telegram poller, binding 라우팅, lane queue."
    >
      <Bi
        ko={
          <>
            <h2>3 poller</h2>
            <pre>{`core/server/supervised/
├── slack_poller.py       # Slack RTM + slash command
├── discord_poller.py     # Discord slash command
├── telegram_poller.py    # Telegram bot API
├── webhook_handler.py    # generic webhook fanout
└── poller_base.py        # shared lifecycle`}</pre>

            <h2>Binding</h2>
            <p>
              <code>core/channels/binding.py</code> 가 channel × user × thread 의 3-tuple key 로 session 을 라우팅합니다. config.toml 의 <code>[gateway.&lt;provider&gt;]</code> 섹션이 binding 패턴 (예: <code>channels = [&quot;#geode&quot;]</code>) 을 정의.
            </p>

            <h2>Lane queue</h2>
            <p>
              한 channel 안에서 동시 요청이 와도 lane 단위로 직렬화. OpenClaw Lane Queue 패턴을 따라 retry / fairness / quota 가 lane 별로 적용됩니다.
            </p>

            <h2>운영</h2>
            <pre>{`# 시작 + 백그라운드
geode serve &

# 상태 확인
geode status

# 재시작 (config 변경 후)
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')
geode serve &

# poller 디버깅
GEODE_POLLER_DEBUG=1 geode serve`}</pre>

            <h2>설정 + 운영 스킬</h2>
            <p>
              운영 디테일 (반응 동작, 폴러 상태, OAuth 갱신) 은 `.claude/skills/geode-serve` 스킬 에서 다룹니다. 자세한 binding pattern + failover 는 `.claude/skills/openclaw-patterns`.
            </p>

            <p className="text-white/40 text-sm"><em>참조</em>: `core/server/supervised/*.py`, `.claude/skills/geode-serve`.</p>
          </>
        }
        en={
          <>
            <h2>The three pollers</h2>
            <pre>{`core/server/supervised/
├── slack_poller.py       # Slack RTM + slash command
├── discord_poller.py     # Discord slash command
├── telegram_poller.py    # Telegram bot API
├── webhook_handler.py    # generic webhook fanout
└── poller_base.py        # shared lifecycle`}</pre>

            <h2>Binding</h2>
            <p>
              <code>core/channels/binding.py</code> routes a session by the (channel, user, thread) triple. The <code>[gateway.&lt;provider&gt;]</code> section in <code>config.toml</code> defines the binding pattern, e.g. <code>channels = [&quot;#geode&quot;]</code>.
            </p>

            <h2>Lane queue</h2>
            <p>
              Concurrent requests in the same channel serialize per lane. Retry, fairness, and quota apply per lane, following the OpenClaw Lane Queue pattern.
            </p>

            <h2>Operations</h2>
            <pre>{`# start in background
geode serve &

# check status
geode status

# restart after config change
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')
geode serve &

# poller debug
GEODE_POLLER_DEBUG=1 geode serve`}</pre>

            <h2>Operations skills</h2>
            <p>
              Day-to-day operational concerns (reaction behaviour, poller health, OAuth refresh) live in the `.claude/skills/geode-serve` skill. Binding patterns and failover live in `.claude/skills/openclaw-patterns`.
            </p>

            <p className="text-white/40 text-sm"><em>References</em>: `core/server/supervised/*.py`, `.claude/skills/geode-serve`.</p>
          </>
        }
      />
    </DocsShell>
  );
}
