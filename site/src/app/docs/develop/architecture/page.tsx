import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Architecture deep-dive — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="develop/architecture"
      title="Architecture deep-dive"
      titleKo="아키텍처 심화"
      summary="The subsystem map and a recommended reading order, retold as data-flow traces."
      summaryKo="서브시스템 지도와 추천 읽기 순서를 데이터 흐름 추적으로 풀어냅니다."
    >
      <Bi
        ko={
          <>
            <h2>이 페이지의 쓰임</h2>
            <p>
              코드베이스에 처음 들어오는 사람을 위한 지도입니다. 모든
              서브시스템을 경로와 함께 평면으로 나열한{" "}
              <a href="/geode/docs/architecture/system-index">시스템 색인</a>이
              카탈로그라면, 이 페이지는 경로입니다. 무엇부터 읽을지, 요청 하나가
              코드를 실제로 어떻게 지나는지 보여 줍니다.
            </p>

            <h2>서브시스템 지도</h2>
            <p>
              프로덕션 코드는 두 패키지입니다. <code>core/</code>는 범용 자율
              에이전트 런타임이고, <code>plugins/</code>는 1차 보조
              플러그인(petri_audit, seed_generation)입니다. <code>core/</code>의
              서브시스템은 5계층 스택에 정렬됩니다.
            </p>
            <pre>{`Self-Improving  core/self_improving/  train.py + measure/fitness/gate/ledger + loop/{mutate,observe,inject}
Agent           core/agent/           AgenticLoop(while tool_use), sub_agent, system_prompt
Harness         core/cli/             thin CLI + commands/ + IPC 클라이언트
                core/server/          serve 데몬. ipc_server(CLIPoller) + supervised(메신저 폴러)
                core/messaging/       바인딩 기반 게이트웨이 라우팅
                core/hooks/           라이프사이클 이벤트 (HookSystem)
                core/orchestration/   LaneQueue, TaskGraph, compaction, tool offload
                core/scheduler/       cron/이벤트 트리거 + 예약 작업
                core/wiring/          부트스트랩 주입 (container, bootstrap, scheduling)
                core/ui/              터미널 렌더 (event_renderer, latex)
Runtime         core/tools/           도구 레지스트리 + deferred loading + PolicyChain
                core/mcp/             MCP 클라이언트 (manager, stdio_client)
                core/memory/          5-tier 컨텍스트 + 세션 저장소
                core/skills/          스킬 레지스트리
                core/llm/prompts/     프롬프트 템플릿 + 해시 핀
                core/audit/           감사 결과 추출 (dim_extractor)
                core/observability/   run log, session metrics, OTLP
                core/config/          Settings + 레이어 해석 (explain)
                core/auth/            OAuth, 프로필, 쿨다운
Model           core/llm/             라우터 + 어댑터 레지스트리
                core/llm/providers/   Anthropic / OpenAI / Codex / GLM`}</pre>
            <p>
              최상위에는 진입 모듈이 몇 개 있습니다.{" "}
              <code>core/runtime.py</code>의 <code>GeodeRuntime</code>이
              부트스트랩이고, <code>core/paths.py</code>가 모든 디렉터리 경로를
              한곳에서 해석하며, <code>core/mcp_server.py</code>가{" "}
              <code>geode-mcp</code> 진입점입니다. 계층 경계가 왜 이렇게
              그어졌는지는{" "}
              <a href="/geode/docs/explanation/4-layer">왜 5계층인가</a>에
              있습니다.
            </p>

            <h2>추천 읽기 순서</h2>
            <ol>
              <li><a href="/geode/docs/concepts/two-loops">두 개의 루프</a>. 나머지 문서가 기대는 멘탈 모델입니다. 여기서 시작하세요.</li>
              <li><a href="/geode/docs/architecture/overview">5계층 스택</a>. 각 계층이 무엇을 맡고 책임이 어디서 끝나는지.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">안쪽 에이전틱 루프</a>. while(tool_use) 기본 단위와 턴이 끝나는 경로들.</li>
              <li><a href="/geode/docs/runtime/context">컨텍스트 조립</a>. 매 LLM 호출의 컨텍스트가 만들어지는 곳.</li>
              <li><a href="/geode/docs/runtime/orchestration">서브에이전트 오케스트레이션</a>. 격리된 병렬 레인과 완료 시 병합.</li>
              <li><a href="/geode/docs/harness/hooks">훅과 관측성</a>. 한 이벤트 위에 쌓이는 observe와 act.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">아우터 루프</a>. 변이, 감사, 게이트, 승격으로 이어지는 자기개선 사이클.</li>
            </ol>
            <p>
              운영과 설정이 목적이라면{" "}
              <a href="/geode/docs/config/basics">설정 기초</a>와{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve와 게이트웨이</a>로
              가세요.
            </p>

            <h2>흐름 추적 하나. 대화형 요청</h2>
            <pre>{`geode  (thin REPL, core/cli/)
   │  자유 텍스트 → IPCClient.send_prompt  (~/.geode/cli.sock)
   ▼
CLIPoller  (core/server/ipc_server/poller.py)  ── session + global 레인 획득
   ▼
AgenticLoop  (core/agent/loop/agent_loop.py)
   ▼  매 라운드
시스템 프롬프트 + 컨텍스트 조립  (core/agent/system_prompt.py + core/memory/)
   ▼
LLM 호출  (core/llm/router/ → core/llm/providers/)
   ▼
도구 요청?  ── 예 → core/tools/ 실행 → 결과 관찰 → 다음 라운드
   │
   └ 아니오 → 답변 스트리밍 (core/ui/event_renderer.py)`}</pre>
            <p>
              thin CLI는 직접 일하지 않습니다. IPC로 <code>geode serve</code>{" "}
              데몬에 붙고, 데몬 안의 단일 <code>GeodeRuntime</code>이 작업을
              실행합니다. 라운드마다 메모리 계층과 프롬프트 레이어가 컨텍스트로
              합쳐지고, 라우터가 어댑터를 고르고, 모델이 도구를 요청하면
              레지스트리가 실행합니다. 턴이 끝나는 경로들은{" "}
              <a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>에
              있습니다.
            </p>

            <h2>흐름 추적 둘. 자기개선 사이클</h2>
            <pre>{`auto-trigger 또는 운영자  (core/wiring/scheduling.py → loop/auto_trigger.py)
   ▼
변이 제안 + 적용  (core/self_improving/loop/mutate/runner.py, 7 behaviour kinds)
   ▼
Petri 감사 서브프로세스  (measure.py → geode audit → plugins/petri_audit/)
   │  GEODE_WRAPPER_OVERRIDE로 변이된 스캐폴드를 주입한 같은 AgenticLoop를 측정
   ▼
fitness 계산  (fitness.py, 22-dim 판정 → 스칼라)
   ▼
margin 게이트  (gate.py)
   ├ 통과 → 승격. baseline.json 갱신 + baseline_archive.jsonl append  (ledger.py)
   └ 실패 → 되돌림. SoT를 변이 전으로 복원`}</pre>
            <p>
              두 루프는 코드를 공유하되 기록으로 만납니다. 감사는 안쪽 루프와
              같은 <code>AgenticLoop</code>를 측정 대상으로 돌리고, 게이트를
              통과한 변이만 승격되어 git 추적 원장에 계보로 남습니다. 가중치
              갱신은 어디에도 없습니다. 전체 흐름은{" "}
              <a href="/geode/docs/capabilities/outer-loop">아우터 루프</a>,
              측정 프레임워크는{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>에 있습니다.
            </p>

            <h2>더 깊이</h2>
            <ul>
              <li><a href="/geode/docs/architecture/system-index">시스템 색인</a>. 모든 서브시스템과 경로의 평면 카탈로그.</li>
              <li><a href="/geode/docs/explanation/4-layer">왜 5계층인가</a>. 경계가 그 자리에 있는 이유.</li>
              <li><a href="/geode/docs/explanation/self-hosting">왜 self-hosting 하네스인가</a>. 런타임과 빌드 라인이 기본 단위를 공유하는 이유.</li>
              <li><a href="/geode/docs/explanation/ratchet">왜 ratchet 규율인가</a>. drift를 막는 형태.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>What this page is for</h2>
            <p>
              A map for someone arriving at the codebase for the first time. The{" "}
              <a href="/geode/docs/architecture/system-index">System index</a>{" "}
              is the catalog that lists every subsystem flat with its path; this
              page is the path. It shows what to read first and how one request
              actually flows through the code.
            </p>

            <h2>Subsystem map</h2>
            <p>
              Production code splits into two packages: <code>core/</code> is
              the general-purpose autonomous agent runtime, and{" "}
              <code>plugins/</code> holds the first-party plugins (petri_audit,
              seed_generation). The subsystems inside <code>core/</code> line up
              with the five-layer stack.
            </p>
            <pre>{`Self-Improving  core/self_improving/  train.py + measure/fitness/gate/ledger + loop/{mutate,observe,inject}
Agent           core/agent/           AgenticLoop (while tool_use), sub_agent, system_prompt
Harness         core/cli/             thin CLI + commands/ + IPC client
                core/server/          serve daemon: ipc_server (CLIPoller) + supervised (messenger pollers)
                core/messaging/       binding-based gateway routing
                core/hooks/           lifecycle events (HookSystem)
                core/orchestration/   LaneQueue, TaskGraph, compaction, tool offload
                core/scheduler/       cron/event triggers + scheduled jobs
                core/wiring/          bootstrap injection (container, bootstrap, scheduling)
                core/ui/              terminal rendering (event_renderer, latex)
Runtime         core/tools/           tool registry + deferred loading + PolicyChain
                core/mcp/             MCP client (manager, stdio_client)
                core/memory/          5-tier context + session stores
                core/skills/          skill registry
                core/llm/prompts/     prompt templates + hash pins
                core/audit/           audit-result extraction (dim_extractor)
                core/observability/   run log, session metrics, OTLP
                core/config/          Settings + layer resolution (explain)
                core/auth/            OAuth, profiles, cooldown
Model           core/llm/             router + adapter registry
                core/llm/providers/   Anthropic / OpenAI / Codex / GLM`}</pre>
            <p>
              A few entry modules sit at the top level:{" "}
              <code>GeodeRuntime</code> in <code>core/runtime.py</code> is the
              bootstrap, <code>core/paths.py</code> resolves every directory
              path in one place, and <code>core/mcp_server.py</code> is the{" "}
              <code>geode-mcp</code> entry point. For why the layer boundaries
              fall where they do, see{" "}
              <a href="/geode/docs/explanation/4-layer">Why five layers</a>.
            </p>

            <h2>Recommended reading order</h2>
            <ol>
              <li><a href="/geode/docs/concepts/two-loops">The two loops</a>. The mental model the rest of the docs build on. Start here.</li>
              <li><a href="/geode/docs/architecture/overview">The five-layer stack</a>. What each layer owns and where its responsibility ends.</li>
              <li><a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>. The while(tool_use) primitive and the paths that end a turn.</li>
              <li><a href="/geode/docs/runtime/context">Context assembly</a>. Where each LLM call&apos;s context is built.</li>
              <li><a href="/geode/docs/runtime/orchestration">Sub-agent orchestration</a>. Isolated parallel lanes and merge on completion.</li>
              <li><a href="/geode/docs/harness/hooks">Hooks and observability</a>. How observe and act stack on one event.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">The outer loop</a>. The self-improving cycle through mutate, audit, gate, promote.</li>
            </ol>
            <p>
              If operating and configuring is the goal, go instead to{" "}
              <a href="/geode/docs/config/basics">Configuration basics</a> and{" "}
              <a href="/geode/docs/harness/serve-gateway">Serve and gateway</a>.
            </p>

            <h2>Trace one. An interactive request</h2>
            <pre>{`geode  (thin REPL, core/cli/)
   │  free text → IPCClient.send_prompt  (~/.geode/cli.sock)
   ▼
CLIPoller  (core/server/ipc_server/poller.py)  ── acquires session + global lanes
   ▼
AgenticLoop  (core/agent/loop/agent_loop.py)
   ▼  each round
system prompt + context assembly  (core/agent/system_prompt.py + core/memory/)
   ▼
LLM call  (core/llm/router/ → core/llm/providers/)
   ▼
tool requested?  ── yes → run core/tools/ → observe result → next round
   │
   └ no → stream the answer  (core/ui/event_renderer.py)`}</pre>
            <p>
              The thin CLI does no work itself. It connects over IPC to the{" "}
              <code>geode serve</code> daemon, and the single{" "}
              <code>GeodeRuntime</code> inside the daemon runs the task. Each
              round, the memory tiers and prompt layers merge into a context,
              the router picks an adapter, and when the model requests a tool
              the registry runs it. The paths that end a turn are detailed in{" "}
              <a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>.
            </p>

            <h2>Trace two. A self-improving cycle</h2>
            <pre>{`auto-trigger or operator  (core/wiring/scheduling.py → loop/auto_trigger.py)
   ▼
propose + apply a mutation  (core/self_improving/loop/mutate/runner.py, 7 behaviour kinds)
   ▼
Petri audit subprocess  (measure.py → geode audit → plugins/petri_audit/)
   │  measures the same AgenticLoop with the mutated scaffold injected
   │  via GEODE_WRAPPER_OVERRIDE
   ▼
fitness  (fitness.py: 22-dim judge scores → one scalar)
   ▼
margin gate  (gate.py)
   ├ pass → promote: update baseline.json + append baseline_archive.jsonl  (ledger.py)
   └ fail → revert: restore the SoT to its pre-mutation value`}</pre>
            <p>
              The two loops share code but meet through a record. The audit runs
              the same <code>AgenticLoop</code> as the thing being measured, and
              only gate-passing mutations are promoted, leaving their lineage in
              git-tracked ledgers. There is no weight update anywhere. The full{/* canon-ok: negation */}
              flow is in{" "}
              <a href="/geode/docs/capabilities/outer-loop">The outer loop</a>;
              the measurement framework is in{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>.
            </p>

            <h2>Going deeper</h2>
            <ul>
              <li><a href="/geode/docs/architecture/system-index">System index</a>. The flat catalog of every subsystem with its path.</li>
              <li><a href="/geode/docs/explanation/4-layer">Why five layers</a>. Why the boundaries fall where they do.</li>
              <li><a href="/geode/docs/explanation/self-hosting">Why a self-hosting harness</a>. Why the runtime and the build line share primitives.</li>
              <li><a href="/geode/docs/explanation/ratchet">Why ratchet discipline</a>. The shape that prevents drift.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
