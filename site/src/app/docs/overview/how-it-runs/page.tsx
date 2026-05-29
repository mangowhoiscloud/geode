import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "How GEODE runs a task — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="overview/how-it-runs"
      title="How GEODE runs a task"
      titleKo="GEODE가 작업을 처리하는 흐름"
      summary="One request, traced end to end, three times. A CLI task, a gateway message, and a scheduled self-improving run all reach the same core."
      summaryKo="요청 하나가 처음부터 끝까지 어떻게 흐르는지, 세 번 따라갑니다. CLI 작업, 게이트웨이 메시지, 예약된 자기개선 실행이 모두 같은 코어에 닿습니다."
    >
      <Bi
        ko={
          <>
            <h2>같은 코어, 다른 입구</h2>
            <p>
              GEODE를 부르는 길은 여럿입니다. 터미널에서 명령으로, Slack 메시지로,
              예약된 시각에 스스로. 세 길은 입구만 다릅니다. 안으로 들어오면 모두
              같은 코어를 지납니다. 그 코어가{" "}
              <a href="/geode/docs/concepts/two-loops">안쪽 agentic 루프</a>입니다.
            </p>
            <p>
              모듈 목록을 나열하는 대신, 요청 하나가 흐르는 길을 끝까지 따라가며
              구조를 익히겠습니다. 같은 일을 세 입구로 들어가서 세 번 봅니다.
            </p>

            <h2>1. CLI 작업</h2>
            <p>
              <code>geode &quot;...&quot;</code>를 실행하면 thin CLI가 먼저 뜹니다.
              CLI 자체는 모델을 호출하지 않습니다. 대신 Unix 도메인 소켓으로 serve
              데몬에 작업을 넘깁니다. 데몬이 떠 있지 않으면 백그라운드에서 띄운 뒤
              연결합니다(<code>core/cli/ipc_client.py</code>). 데몬은 작업을
              AgenticLoop에 넘기고, 루프가 도구를 돌려 답을 만든 뒤, 같은 소켓으로
              결과를 돌려보냅니다.
            </p>
            <pre>{`geode "..."  ->  thin CLI
                   |  (Unix socket, line-delimited JSON)
                   v
              serve daemon  ->  AgenticLoop  ->  tools
                   ^                               |
                   +-------- answer ---------------+`}</pre>
            <p>
              데몬을 한 번 띄워 두면 MCP 서버, 스킬, 메모리, 훅을 매번 새로 켤
              필요가 없습니다. CLI는 얇게 유지되고, 무거운 상태는 데몬에 머뭅니다.
            </p>

            <h2>2. 게이트웨이 메시지</h2>
            <p>
              Slack이나 Discord 채널에 올라온 메시지는 다른 입구로 들어옵니다.
              poller(<code>core/server/supervised/</code>)가 채널을 지켜보다가
              새 메시지를 받습니다. binding(<code>core/integrations/messaging/binding.py</code>)이
              그 메시지를 어떤 세션으로 보낼지 라우팅하고, lane queue가 같은 세션의
              요청을 직렬화해 동시성을 제어합니다. 그 안에서 AgenticLoop가 같은
              방식으로 돕니다. 답이 나오면 채널로 회신하고, 필요하면 알림을 보냅니다.
            </p>
            <pre>{`Slack / Discord message
       |
       v
  poller  ->  binding (route)  ->  session lane  ->  AgenticLoop  ->  tools
                                                          |
                                          reply to channel + notification`}</pre>
            <p>
              입구는 CLI와 다르지만, <code>binding.py</code>가 메시지를 넘기는
              곳은 같은 AgenticLoop입니다. serve 데몬과 게이트웨이 운영은{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>에서
              다룹니다.
            </p>

            <h2>3. 예약된 자기개선 실행</h2>
            <p>
              세 번째 입구는 사람이 아니라 스케줄러입니다. 예약된 시각이 되면
              스케줄러(<code>core/scheduler/service.py</code>)가 실행을 트리거합니다.
              이번에는 사용자 작업이 아니라 바깥쪽 루프가 돕니다.{" "}
              <code>autoresearch/train.py</code>가 호출당 감사 한 번을 돌립니다.
              정책 파일 하나를 변형하고, Petri 감사로 측정하고, 점수 변화를 귀속한
              뒤, 기준을 넘으면 baseline을 갱신하고 아니면 정책을 되돌립니다.
            </p>
            <pre>{`scheduled time
       |
       v
  scheduler  ->  autoresearch/train.py
                     |
                     mutate policy -> Petri audit -> attribute -> promote / revert`}</pre>
            <p>
              여기서 측정 대상이 되는 트랜스크립트는 결국 같은 AgenticLoop가 만든
              것입니다. 바깥쪽 루프 전체는{" "}
              <a href="/geode/docs/capabilities/autoresearch">폐루프</a>에서 다룹니다.
            </p>

            <h2>세 흐름이 만나는 곳</h2>
            <p>
              세 입구는 서로 다른 코드로 시작합니다. CLI는 IPC 클라이언트로,
              게이트웨이는 poller와 binding으로, 자기개선 실행은 스케줄러로
              시작합니다. 그러나 셋 다 같은 AgenticLoop와 같은 메모리, 훅, LLM
              라우터, 서브에이전트 오케스트레이션을 지납니다. 입구를 바꿔도 코어는
              하나입니다. 계층이 어떻게 나뉘는지는{" "}
              <a href="/geode/docs/architecture/overview">4-계층 스택</a>에서
              이어집니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Same core, different entrances</h2>
            <p>
              There are several ways to call GEODE. From a terminal as a command,
              from a Slack message, or on its own at a scheduled time. The three
              paths differ only at the entrance. Once inside, they all pass through
              the same core: the{" "}
              <a href="/geode/docs/concepts/two-loops">inner agentic loop</a>.
            </p>
            <p>
              Instead of listing modules, this page learns the architecture by
              following one request to the end. The same work, entered three ways,
              traced three times.
            </p>

            <h2>1. A CLI task</h2>
            <p>
              Running <code>geode &quot;...&quot;</code> starts the thin CLI first.
              The CLI itself does not call the model. It hands the task to the
              serve daemon over a Unix domain socket. If the daemon is not running,
              the CLI starts it in the background, then connects
              (<code>core/cli/ipc_client.py</code>). The daemon passes the task to
              AgenticLoop, the loop runs tools to produce an answer, and the result
              comes back over the same socket.
            </p>
            <pre>{`geode "..."  ->  thin CLI
                   |  (Unix socket, line-delimited JSON)
                   v
              serve daemon  ->  AgenticLoop  ->  tools
                   ^                               |
                   +-------- answer ---------------+`}</pre>
            <p>
              Keeping the daemon up means MCP servers, skills, memory, and hooks
              do not have to start fresh each time. The CLI stays thin; the heavy
              state lives in the daemon.
            </p>

            <h2>2. A gateway message</h2>
            <p>
              A message posted to a Slack or Discord channel enters through a
              different door. A poller (<code>core/server/supervised/</code>)
              watches the channel and picks up new messages. The binding
              (<code>core/integrations/messaging/binding.py</code>) routes that
              message to a session, and a lane queue serializes requests for the
              same session to control concurrency. Inside that lane, AgenticLoop
              runs the same way. When an answer is ready, it replies to the channel
              and, where needed, sends a notification.
            </p>
            <pre>{`Slack / Discord message
       |
       v
  poller  ->  binding (route)  ->  session lane  ->  AgenticLoop  ->  tools
                                                          |
                                          reply to channel + notification`}</pre>
            <p>
              The entrance differs from the CLI, but the place{" "}
              <code>binding.py</code> hands the message to is the same AgenticLoop.
              For operating the serve daemon and its gateway, see{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>.
            </p>

            <h2>3. A scheduled self-improving run</h2>
            <p>
              The third entrance is not a person but the scheduler. At a scheduled
              time the scheduler (<code>core/scheduler/service.py</code>) triggers
              a run. This time it is not a user task but the outer loop that runs.{" "}
              <code>autoresearch/train.py</code> runs one audit per invocation. It
              mutates one policy file, measures with a Petri audit, attributes the
              score change, then updates the baseline if the bar is cleared or
              reverts the policy if not.
            </p>
            <pre>{`scheduled time
       |
       v
  scheduler  ->  autoresearch/train.py
                     |
                     mutate policy -> Petri audit -> attribute -> promote / revert`}</pre>
            <p>
              The transcripts measured here are, in the end, produced by the same
              AgenticLoop. For the outer loop end to end, see{" "}
              <a href="/geode/docs/capabilities/autoresearch">The closed loop</a>.
            </p>

            <h2>Where the three meet</h2>
            <p>
              The three entrances start in different code. The CLI starts in the
              IPC client, the gateway in a poller and a binding, the self-improving
              run in the scheduler. Yet all three pass through the same AgenticLoop
              and the same memory, hooks, LLM router, and sub-agent orchestration.
              Change the entrance and the core stays one. For how the layers
              divide, continue to{" "}
              <a href="/geode/docs/architecture/overview">The 4-layer stack</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
