import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "How GEODE runs a task — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="overview/how-it-runs"
      title="How GEODE runs a task"
      titleKo="GEODE가 작업을 처리하는 흐름"
      summary="One request, traced end to end. The same core serves a CLI task, a gateway message, a scheduled run, and a geode-mcp call."
      summaryKo="요청 하나가 처음부터 끝까지 어떻게 흐르는지 따라갑니다. CLI 작업, 게이트웨이 메시지, 예약 실행, geode-mcp 호출이 모두 같은 코어를 지납니다."
    >
      <Bi
        ko={
          <>
            <h2>요청 하나를 끝까지 따라가기</h2>
            <p>
              모듈 목록을 외우는 것보다 요청 하나가 흐르는 길을 한 번 따라가는
              쪽이 구조를 빨리 익힙니다. 이 페이지는 터미널에 입력한 자유 텍스트
              한 줄이 답이 되어 돌아오기까지의 전 구간을 추적합니다. 입구가
              달라져도(메신저, 스케줄러, MCP) 코어는 같으므로, 이 추적 하나면
              나머지 입구도 읽힙니다.
            </p>

            <h2>thin CLI에서 데몬까지</h2>
            <p>
              <code>geode</code>를 실행하면 thin CLI가 뜹니다. CLI 프로세스는
              모델을 직접 호출하지 않습니다. 대신 Unix 도메인 소켓{" "}
              <code>~/.geode/cli.sock</code>(경로 상수는 <code>core/paths.py</code>)
              으로 serve 데몬에 요청을 넘깁니다. 프로토콜은 줄 단위 JSON입니다.
              데몬이 떠 있지 않으면 <code>core/cli/ipc_client.py</code>의
              자동 시작 로직이 백그라운드에서 데몬을 띄운 뒤 연결합니다.
            </p>
            <p>
              왜 두 프로세스로 나누었을까요. MCP 서버 연결, 스킬 레지스트리, 훅,
              메모리 같은 무거운 상태를 데몬 한 곳에 두면 매 호출마다 새로 켤
              필요가 없기 때문입니다. CLI는 입력과 렌더링만 맡는 얇은 클라이언트로
              남습니다. 자유 텍스트는 이 대화형 화면 안에서만 받습니다.{" "}
              <code>geode &quot;요청&quot;</code> 형태의 셸 원샷은 지원하지
              않습니다.
            </p>

            <h2>데몬 안에서 일어나는 일</h2>
            <figure>
              <img
                src="/geode/diagrams/request-flow.svg"
                alt="Request flow: thin CLI over the Unix socket to the daemon's CLIPoller, through the lanes into AgenticLoop and its tools, with events streaming back over the same socket"
              />
              <figcaption>요청 하나의 전 구간. 이벤트는 같은 소켓을 타고 thin CLI로 돌아옵니다.</figcaption>
            </figure>
            <p>
              소켓 건너편에서 요청을 받는 것은{" "}
              <code>core/server/ipc_server/poller.py</code>의 CLIPoller입니다.
              CLIPoller는 요청마다 세션 레인과 글로벌 레인을 차례로 획득합니다.
              같은 세션의 요청은 직렬로, 다른 세션은 병렬로 흐르게 만드는
              동시성 제어입니다(<code>core/orchestration/lane_queue.py</code>).
              레인을 잡으면 요청은 AgenticLoop
              (<code>core/agent/loop/agent_loop.py</code>)에 들어갑니다.
            </p>
            <p>
              AgenticLoop는 <code>while stop_reason == &quot;tool_use&quot;</code>{" "}
              루프입니다. 매 라운드마다 라운드 상한, 시간 예산, 비용 예산 같은
              가드를 먼저 확인하고, 컨텍스트 오버플로를 점검한 뒤
              (<code>core/agent/context_manager.py</code>), 모델을 호출합니다.
              모델이 도구를 요청하면 도구를 실행하고 결과를 대화에 붙여 다음
              라운드로 갑니다. 도구는 네이티브 도구
              (<code>core/tools/registry.py</code>), 연결된 MCP 서버의 도구
              (<code>core/mcp/manager.py</code>), 스킬이 한 호출 표면에서
              섞입니다. 도구 수가 많으면 일부만 미리 싣고 나머지는 검색해서
              가져오는 deferred loading이 동작합니다(
              <a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>).
            </p>
            <p>
              실행 중 생기는 이벤트(도구 시작, 토큰 스트림, 라운드 전환)는 같은
              소켓으로 즉시 돌려보내고, thin CLI가{" "}
              <code>core/ui/event_renderer.py</code>로 화면에 그립니다. 답이
              완성되기 전에도 진행 상황이 보이는 이유입니다.
            </p>

            <h2>루프가 끝나는 길</h2>
            <p>
              루프는 한 가지 방식으로만 끝나지 않습니다. 종료 사유는{" "}
              <code>AgenticResult.termination_reason</code>
              (<code>core/agent/loop/models.py</code>)에 기록됩니다. 대표적인
              경로는 다음과 같습니다.
            </p>
            <table>
              <thead>
                <tr><th>종료 사유</th><th>의미</th></tr>
              </thead>
              <tbody>
                <tr><td><code>natural</code></td><td>모델이 도구 요청 없이 텍스트로 답을 마쳤습니다.</td></tr>
                <tr><td><code>max_rounds</code></td><td>라운드 상한에 닿았습니다. 마지막 라운드는 텍스트 마무리를 강제합니다.</td></tr>
                <tr><td><code>time_budget_expired</code></td><td>벽시계 시간 예산이 소진됐습니다.</td></tr>
                <tr><td><code>cost_budget_exceeded</code></td><td>세션 비용이 예산에 닿았습니다. 80% 지점에서 한 번 경고합니다.</td></tr>
                <tr><td><code>context_exhausted</code></td><td>압축과 정리 후에도 컨텍스트가 임계 상태입니다.</td></tr>
                <tr><td><code>model_refusal</code></td><td>모델 안전 분류기가 응답을 거절했습니다. HTTP 200으로 오는 <code>stop_reason: &quot;refusal&quot;</code>을 잡아 거절 사유 카테고리를 포함한 정직한 메시지로 종료합니다.</td></tr>
                <tr><td><code>user_clarification_needed</code></td><td>도구 없이 긴 출력만 반복되는 과사고를 감지하면 멈추고 사용자에게 묻습니다.</td></tr>
                <tr><td><code>llm_error</code></td><td>재시도로 회복하지 못한 모델 호출 오류입니다.</td></tr>
              </tbody>
            </table>
            <p>
              어느 경로로 끝나든 결과는 종료 사유와 함께 소켓으로 돌아갑니다.
              조용한 실패 대신 이유가 남는 설계입니다.
            </p>

            <h2>같은 코어, 다른 입구</h2>
            <p>
              위 추적에서 입구만 바꾸면 GEODE의 나머지 호출 경로가 됩니다.
              네 입구 모두 같은 AgenticLoop, 같은 메모리, 훅, LLM 라우터를
              지납니다.
            </p>
            <table>
              <thead>
                <tr><th>입구</th><th>코어까지의 길</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>CLI 자유 텍스트</td>
                  <td>thin CLI, <code>cli.sock</code>, CLIPoller. 이 페이지의 추적 그대로입니다.</td>
                </tr>
                <tr>
                  <td>메신저 메시지</td>
                  <td>Slack Socket Mode 또는 Discord/Telegram poller(<code>core/server/supervised/</code>)가 메시지를 받고, binding(<code>core/messaging/binding.py</code>)이 세션으로 라우팅한 뒤 같은 레인과 루프를 지납니다.</td>
                </tr>
                <tr>
                  <td>예약 실행</td>
                  <td>데몬 안의 스케줄러(<code>core/scheduler/service.py</code>)가 예약 시각에 같은 코어로 작업을 트리거합니다.</td>
                </tr>
                <tr>
                  <td>geode-mcp <code>run_agent</code></td>
                  <td>다른 에이전트(예: Claude Code)가 MCP 도구로 GEODE를 부릅니다. <code>core/mcp_server.py</code>가 <code>run_agentic_oneshot</code>(<code>core/cli/bootstrap.py</code>)으로 한 번의 agentic 실행을 돌리고 텍스트, 라운드 수, 종료 사유를 돌려줍니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음 단계</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">5-계층 스택</a>. 이 흐름이 지나는 계층들의 책임 경계입니다.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>. 한 라운드의 정확한 의미론입니다.</li>
              <li><a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>. 메신저 입구의 운영 가이드입니다.</li>
              <li><a href="/geode/docs/concepts/two-loops">두 개의 루프</a>. 이 코어를 바깥에서 개선하는 루프와의 관계입니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>One request, traced to the end</h2>
            <p>
              Following one request all the way through teaches the architecture
              faster than memorizing a module list. This page traces a single
              line of free text from the terminal until the answer comes back.
              The entrances vary (messenger, scheduler, MCP), but the core is
              the same, so this one trace reads for every entrance.
            </p>

            <h2>From the thin CLI to the daemon</h2>
            <p>
              Running <code>geode</code> starts the thin CLI. The CLI process
              never calls the model itself. It hands the request to the serve
              daemon over a Unix domain socket at{" "}
              <code>~/.geode/cli.sock</code> (the path constant lives in{" "}
              <code>core/paths.py</code>). The protocol is line-delimited JSON.
              If no daemon is running, the auto-start logic in{" "}
              <code>core/cli/ipc_client.py</code> launches one in the
              background, then connects.
            </p>
            <p>
              Why two processes? Heavy state, MCP server connections, the skill
              registry, hooks, and memory, lives in one daemon so it never has
              to start fresh per call. The CLI stays a thin client that only
              handles input and rendering. Free text is accepted only inside
              this interactive screen. A shell one-shot like{" "}
              <code>geode &quot;prompt&quot;</code> is not supported.
            </p>

            <h2>Inside the daemon</h2>
            <figure>
              <img
                src="/geode/diagrams/request-flow.svg"
                alt="Request flow: thin CLI over the Unix socket to the daemon's CLIPoller, through the lanes into AgenticLoop and its tools, with events streaming back over the same socket"
              />
              <figcaption>One request end to end; events return to the thin CLI over the same socket.</figcaption>
            </figure>
            <p>
              On the far side of the socket, the CLIPoller in{" "}
              <code>core/server/ipc_server/poller.py</code> receives the
              request. For each request it acquires the session lane and then
              the global lane: requests in the same session run serially,
              different sessions run in parallel
              (<code>core/orchestration/lane_queue.py</code>). With the lanes
              held, the request enters AgenticLoop
              (<code>core/agent/loop/agent_loop.py</code>).
            </p>
            <p>
              AgenticLoop is a{" "}
              <code>while stop_reason == &quot;tool_use&quot;</code> loop. Each
              round first checks its guards, the round cap, the time budget,
              the cost budget, then checks for context overflow
              (<code>core/agent/context_manager.py</code>), then calls the
              model. When the model asks for tools, the loop executes them,
              appends the results to the conversation, and starts the next
              round. Tools blend three sources behind one call surface: native
              tools (<code>core/tools/registry.py</code>), tools from connected
              MCP servers (<code>core/mcp/manager.py</code>), and skills. With
              many tools available, deferred loading keeps a small set eager
              and fetches the rest on demand (
              <a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>).
            </p>
            <p>
              Events produced along the way (tool start, token stream, round
              transitions) stream back over the same socket immediately, and
              the thin CLI renders them with{" "}
              <code>core/ui/event_renderer.py</code>. That is why progress is
              visible before the answer completes.
            </p>

            <h2>How the loop ends</h2>
            <p>
              The loop has more than one exit. The reason is recorded on{" "}
              <code>AgenticResult.termination_reason</code>{" "}
              (<code>core/agent/loop/models.py</code>). The main paths:
            </p>
            <table>
              <thead>
                <tr><th>Termination reason</th><th>Meaning</th></tr>
              </thead>
              <tbody>
                <tr><td><code>natural</code></td><td>The model finished with text and no tool request.</td></tr>
                <tr><td><code>max_rounds</code></td><td>The round cap was reached. The final round forces a text wrap-up.</td></tr>
                <tr><td><code>time_budget_expired</code></td><td>The wall-clock budget ran out.</td></tr>
                <tr><td><code>cost_budget_exceeded</code></td><td>Session cost reached the budget. A single warning fires at 80%.</td></tr>
                <tr><td><code>context_exhausted</code></td><td>The context stayed critical even after compaction and pruning.</td></tr>
                <tr><td><code>model_refusal</code></td><td>The model&apos;s safety classifiers declined. The loop captures <code>stop_reason: &quot;refusal&quot;</code> arriving as HTTP 200 and ends with an honest message that includes the refusal category.</td></tr>
                <tr><td><code>user_clarification_needed</code></td><td>Overthinking detection: repeated long text-only rounds stop the loop and ask the user instead of spinning.</td></tr>
                <tr><td><code>llm_error</code></td><td>A model-call error that retries could not recover.</td></tr>
              </tbody>
            </table>
            <p>
              Whichever path ends the run, the result returns over the socket
              with its reason attached. A reason on record, instead of a silent
              failure.
            </p>

            <h2>Same core, other entrances</h2>
            <p>
              Swap the entrance in the trace above and you get the rest of
              GEODE&apos;s call paths. All four pass through the same
              AgenticLoop, the same memory, hooks, and LLM router.
            </p>
            <table>
              <thead>
                <tr><th>Entrance</th><th>Path to the core</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>CLI free text</td>
                  <td>Thin CLI, <code>cli.sock</code>, CLIPoller. Exactly the trace on this page.</td>
                </tr>
                <tr>
                  <td>Messenger message</td>
                  <td>Slack Socket Mode or a Discord/Telegram poller (<code>core/server/supervised/</code>) receives the message, the binding (<code>core/messaging/binding.py</code>) routes it to a session, and it flows through the same lanes and loop.</td>
                </tr>
                <tr>
                  <td>Scheduled run</td>
                  <td>The scheduler inside the daemon (<code>core/scheduler/service.py</code>) triggers work into the same core at the scheduled time.</td>
                </tr>
                <tr>
                  <td>geode-mcp <code>run_agent</code></td>
                  <td>Another agent (Claude Code, for example) calls GEODE as an MCP tool. <code>core/mcp_server.py</code> runs one agentic one-shot via <code>run_agentic_oneshot</code> (<code>core/cli/bootstrap.py</code>) and returns the text, round count, and termination reason.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">The 5-layer stack</a>. The responsibility boundaries this flow passes through.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>. The exact semantics of one round.</li>
              <li><a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>. The operating guide for the messenger entrance.</li>
              <li><a href="/geode/docs/concepts/two-loops">The two loops</a>. How an outer loop improves this core from outside.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
