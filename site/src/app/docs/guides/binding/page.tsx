import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Configure a binding — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="guides/binding"
      title="Configure a binding"
      titleKo="바인딩 설정"
      summary="Route a messaging channel to a session lane with its own model and policy."
      summaryKo="메신저 채널을 자체 모델과 정책을 가진 세션 레인으로 라우팅하는 방법입니다."
    >
      <Bi
        ko={
          <>
            <p>
              바인딩은 들어오는 메신저 메시지를 GEODE 처리로 보내는 정적 규칙입니다.
              라우팅에 LLM을 쓰지 않습니다. 채널과 채널 ID가 정확히 일치하는
              메시지만 실행으로 흘러가고, 바인딩 없는 채널의 메시지는 무시됩니다.
              그래서 바인딩은 "어느 채널이 GEODE를 깨울 수 있는가"의 화이트리스트
              역할을 합니다.
            </p>

            <h2>1. config.toml에 바인딩을 선언합니다</h2>
            <p>
              바인딩은 프로젝트의 <code>.geode/config.toml</code>{" "}
              <code>[gateway]</code> 섹션에서 선언합니다.{" "}
              <code>ChannelManager.load_bindings_from_config</code>(
              <code>core/integrations/messaging/binding.py</code>)이 이 형식을
              읽습니다. 각 규칙은 <code>channel</code>과 <code>channel_id</code>가
              필수입니다. <code>channel_id</code>가 비어 있으면 그 규칙은
              건너뜁니다. 빈 ID는 모든 채널에 응답하는 위험한 catch-all이 되기
              때문입니다.
            </p>
            <pre>{`# .geode/config.toml
[gateway]
pollers = ["slack"]
time_budget_s = 120        # gateway-level default per message

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"
auto_respond = true
require_mention = true
allowed_tools = ["memory_search", "web_fetch"]
time_budget_s = 90`}</pre>
            <p>
              각 규칙은 자체 정책 손잡이를 가집니다.{" "}
              <code>require_mention</code>은 GEODE가 멘션됐을 때만 응답하게 하고,{" "}
              <code>allowed_tools</code>는 그 채널에서 허용할 도구를 제한하며(빈
              리스트는 전체 허용),{" "}
              <code>time_budget_s</code>는 메시지당 wall-clock 예산을 지정합니다.
              규칙에 없으면 gateway 레벨 기본값으로 떨어집니다. 이 필드들은{" "}
              <code>ChannelBinding</code>(
              <code>core/integrations/messaging/models.py</code>)의 dataclass
              필드와 일대일로 대응합니다.
            </p>

            <h2>2. 세션 레인으로 라우팅됩니다</h2>
            <p>
              메시지가 바인딩에 매칭되면{" "}
              <code>ChannelManager.aroute_message</code>가{" "}
              <code>build_gateway_session_key(channel, channel_id, sender_id,
              thread_id)</code>로 thread 단위 세션 키를 만듭니다. 같은 스레드의
              메시지는 같은 키로 묶여 컨텍스트가 격리됩니다. 실행은 SessionLane →
              gateway Lane → global Lane 순서로 레인 큐를 거치므로, 같은 세션의
              메시지는 직렬화되고 동시성은 워크로드별 상한으로 제어됩니다.{" "}
              <code>allowed_tools</code>가 설정돼 있으면 그 힌트가 컨텐츠 앞에
              붙어 AgenticLoop로 전달됩니다.
            </p>

            <h2>3. 리로드합니다</h2>
            <p>
              바인딩은 두 시점에 로드됩니다. serve 부팅 시 한 번
              (<code>core/wiring/adapters.py</code>에서{" "}
              <code>load_bindings_from_config(toml_config)</code> 호출), 그리고{" "}
              <code>config.toml</code>이 바뀔 때마다입니다.{" "}
              <code>ConfigWatcher</code>가 파일 변경을 감지해{" "}
              <code>load_bindings_from_config</code>를 다시 부르므로 serve를
              재시작하지 않아도 새 바인딩이 적용됩니다. 리로드 시 기존 바인딩
              리스트는 비워지고 config의 규칙으로 다시 채워집니다.
            </p>

            <h2>확인</h2>
            <p>
              바인딩이 실제로 로드됐는지 활성 gateway에서 확인합니다.
            </p>
            <pre>{`uv run python -c "
import tomllib
from pathlib import Path
from core.integrations.messaging.binding import ChannelManager

cfg = tomllib.loads(Path('.geode/config.toml').read_text())
m = ChannelManager()
n = m.load_bindings_from_config(cfg)
print('loaded', n, 'bindings')
for b in m.list_bindings():
    print(b)
"`}</pre>
            <p>
              로드된 바인딩 수와 각 규칙의 <code>channel</code> /{" "}
              <code>channel_id</code> / <code>auto_respond</code> /{" "}
              <code>time_budget_s</code>가 출력되면 라우팅이 그 채널을 인식할 수
              있습니다. 실제 메시지 라우팅과 poller 운영은 serve gateway 페이지를
              참고하세요.
            </p>

            <p className="text-white/40 text-sm">
              <em>참조:</em>{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve gateway</a>,{" "}
              <a href="/geode/docs/run/messaging">Messaging</a>.
            </p>
          </>
        }
        en={
          <>
            <p>
              A binding is a static rule that routes an inbound messaging message
              into GEODE processing. No LLM is used for routing. Only messages whose
              channel and channel ID match exactly flow through to execution;
              messages from unbound channels are ignored. A binding therefore acts
              as the allowlist for which channels can wake GEODE.
            </p>

            <h2>1. Declare the binding in config.toml</h2>
            <p>
              Bindings are declared in the <code>[gateway]</code> section of the
              project's <code>.geode/config.toml</code>.{" "}
              <code>ChannelManager.load_bindings_from_config</code> in{" "}
              <code>core/integrations/messaging/binding.py</code> reads this format.
              Each rule requires <code>channel</code> and <code>channel_id</code>.
              A rule with an empty <code>channel_id</code> is skipped, because an
              empty ID would create an unsafe catch-all that responds in every
              channel.
            </p>
            <pre>{`# .geode/config.toml
[gateway]
pollers = ["slack"]
time_budget_s = 120        # gateway-level default per message

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ABCDEF1"
auto_respond = true
require_mention = true
allowed_tools = ["memory_search", "web_fetch"]
time_budget_s = 90`}</pre>
            <p>
              Each rule carries its own policy knobs.{" "}
              <code>require_mention</code> makes GEODE respond only when mentioned,{" "}
              <code>allowed_tools</code> restricts which tools are permitted in that
              channel (an empty list means all tools), and{" "}
              <code>time_budget_s</code> sets the per-message wall-clock budget,
              falling back to the gateway-level default when omitted. These fields
              map one-to-one to the dataclass fields on{" "}
              <code>ChannelBinding</code> in{" "}
              <code>core/integrations/messaging/models.py</code>.
            </p>

            <h2>2. It routes to a session lane</h2>
            <p>
              When a message matches a binding,{" "}
              <code>ChannelManager.aroute_message</code> builds a thread-scoped
              session key with{" "}
              <code>build_gateway_session_key(channel, channel_id, sender_id,
              thread_id)</code>. Messages in the same thread share the key, so
              context stays isolated. Execution passes through the lane queue in the
              order SessionLane to gateway Lane to global Lane, so messages in the
              same session serialize while concurrency is bounded per workload. When{" "}
              <code>allowed_tools</code> is set, that hint is prepended to the
              content before it reaches the AgenticLoop.
            </p>

            <h2>3. Reload</h2>
            <p>
              Bindings load at two points: once at serve boot (the call to{" "}
              <code>load_bindings_from_config(toml_config)</code> in{" "}
              <code>core/wiring/adapters.py</code>) and again whenever{" "}
              <code>config.toml</code> changes. A <code>ConfigWatcher</code> detects
              the file change and re-invokes <code>load_bindings_from_config</code>,
              so new bindings apply without restarting serve. On reload the existing
              binding list is cleared and refilled from the config rules.
            </p>

            <h2>Verify</h2>
            <p>Confirm the bindings actually loaded from an active gateway.</p>
            <pre>{`uv run python -c "
import tomllib
from pathlib import Path
from core.integrations.messaging.binding import ChannelManager

cfg = tomllib.loads(Path('.geode/config.toml').read_text())
m = ChannelManager()
n = m.load_bindings_from_config(cfg)
print('loaded', n, 'bindings')
for b in m.list_bindings():
    print(b)
"`}</pre>
            <p>
              When the loaded count and each rule's <code>channel</code> /{" "}
              <code>channel_id</code> / <code>auto_respond</code> /{" "}
              <code>time_budget_s</code> print, routing can recognize that channel.
              For live message routing and poller operations, see the serve gateway
              page.
            </p>

            <p className="text-white/40 text-sm">
              <em>See:</em>{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve gateway</a>,{" "}
              <a href="/geode/docs/run/messaging">Messaging</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
