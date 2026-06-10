import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "The two loops — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="concepts/two-loops"
      title="The two loops"
      titleKo="두 개의 루프"
      summary="The mental model the rest of the docs build on. An inner agentic loop runs a task; an outer loop tunes the system that runs tasks."
      summaryKo="나머지 문서가 기대는 멘탈 모델입니다. 안쪽 agentic 루프가 작업을 처리하고, 바깥쪽 루프가 작업을 처리하는 시스템 자체를 다듬습니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 루프가 둘인가</h2>
            <p>
              GEODE 안에는 서로 맞물린 루프가 둘 있습니다. 둘을 구분하면 나머지
              문서가 한결 읽기 쉬워집니다. 안쪽 루프는 작업 하나를 처리합니다.
              바깥쪽 루프는 그 작업을 처리하는 시스템을 시간을 두고 다듬습니다.
            </p>
            <p>
              안쪽 루프는 매 요청마다 돕니다. 바깥쪽 루프는 가끔, 운영자가 돌릴
              때 돕니다. 둘은 코드를 공유하지 않습니다. 대신 두 가지를
              주고받습니다. 안쪽 루프가 입는 스캐폴드, 그리고 안쪽 루프가 남기는
              기록입니다.
            </p>

            <h2>안쪽: agentic 루프</h2>
            <p>
              안쪽 루프는 작업 하나를 실행하는 기본 단위입니다.{" "}
              <code>core/agent/loop/agent_loop.py</code>의 <code>AgenticLoop</code>가
              그것입니다. 형태는 단순합니다. LLM을 호출하고, 모델이 요청한 도구를
              실행하고, 결과를 관찰하고, 다시 호출합니다. 모델이 더 호출할 도구가
              없거나 종료 신호를 보내면 멈춥니다.
            </p>
            <pre>{`call LLM -> tool calls? -> run tools -> observe -> call LLM ...
                  |
                  +-- no more tool calls -> answer`}</pre>
            <p>
              이 한 번의 실행이 끝나면 두 가지가 남습니다. 사용자에게 줄 결과,
              그리고 무슨 일이 있었는지 기록한 트랜스크립트입니다. 트랜스크립트는
              버려지지 않습니다. 바깥쪽 루프가 읽을 재료가 됩니다.
            </p>
            <p>
              한 턴이 실제로 어떻게 도는지, 어떤 경로로 끝나는지는{" "}
              <a href="/geode/docs/architecture/agentic-loop">안쪽 agentic 루프</a>에서
              자세히 다룹니다.
            </p>

            <h2>바깥쪽: 자기개선 루프</h2>
            <p>
              바깥쪽 루프가 다루는 대상은 작업이 아니라 시스템 자체입니다.
              정확히는 모델을 감싼 <strong>스캐폴드</strong>, 곧 시스템 프롬프트
              섹션(<code>WRAPPER_PROMPT_SECTIONS</code>)과 behaviour kinds입니다.
              모델 가중치와 파라미터는 일절 건드리지 않습니다. 메커니즘은
              선택(selection)입니다. 후보를 만들고, 측정하고, 더 나은 쪽만
              남깁니다.
            </p>
            <ol>
              <li>
                <strong>변이(mutate)</strong>. 스캐폴드의 한 섹션을 한 번에 한
                군데만 바꿉니다 (<code>core/self_improving/loop/mutate</code>).
              </li>
              <li>
                <strong>감사(audit)</strong>. 변이된 스캐폴드를 입은 GEODE를
                Petri 적대적 안전 감사가 차원별로 채점합니다.
              </li>
              <li>
                <strong>fitness</strong>. 차원 점수를 스칼라 하나로 접습니다
                (<code>core/self_improving/fitness.py</code>).
              </li>
              <li>
                <strong>margin 게이트</strong>. 측정 불확실성을 넘는 개선만
                통과시킵니다 (<code>core/self_improving/gate.py</code>).
              </li>
              <li>
                <strong>승격 또는 되돌림</strong>. 통과하면 새 champion으로
                승격하고, 아니면 변이 이전 상태로 되돌립니다. 계보는 git
                champion chain으로 보존됩니다.
              </li>
            </ol>
            <p>
              루프 드라이버는 <code>core/self_improving/train.py</code>입니다.
              파일명은 Karpathy autoresearch의 3-파일 관습을 빌린 것으로, 실제
              training은 일어나지 않습니다. 전체 그림은{" "}
              <a href="/geode/docs/capabilities/autoresearch">자기개선 루프</a>에서,
              측정에 쓰는 평가 프레임워크는{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>에서 다룹니다.
            </p>

            <h2>둘이 맞물리는 방식</h2>
            <p>
              핵심은 두 루프가 직접 호출하지 않는다는 점입니다. 둘은 데이터로
              연결됩니다. 안쪽 루프는 스캐폴드를 입고 행동하며 트랜스크립트를
              만들고, 바깥쪽 루프는 그것을 감사로 읽어 스캐폴드를 바꿉니다.
              바뀐 스캐폴드는 다음 번 안쪽 루프가 행동하는 방식을 바꿉니다.
            </p>
            <pre>{`outer loop  (occasional, operator-run)
  mutate scaffold -> Petri audit -> fitness -> margin gate
        -> promote / revert  (lineage: git champion chain)
     ^                |
     |                v  (new scaffold)
  +-------------------------------------------+
  |  inner loop  (every request)              |
  |    call LLM -> run tools -> observe -> ...|
  |    produces: answer + transcript          |
  +-------------------------------------------+
     |                                    ^
     +-- transcript ----------------------+
         (read by the outer loop's audit)`}</pre>
            <p>
              그래서 스캐폴드를 바꾸면 코드를 바꾸지 않아도 안쪽 루프의 행동이
              달라집니다. 스캐폴드는 안쪽 루프가 입는 옷이고, 바깥쪽 루프는 그
              옷을 고르는 쪽입니다. 한쪽은 입고 한쪽은 고릅니다. 둘은 그렇게 한
              시스템으로 맞물립니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Why there are two loops</h2>
            <p>
              GEODE has two interlocking loops. Telling them apart makes the rest
              of the docs easier to read. The inner loop runs one task. The outer
              loop tunes the system that runs tasks, over time.
            </p>
            <p>
              The inner loop runs on every request. The outer loop runs
              occasionally, when the operator starts it. They do not share code.
              They hand two things back and forth: the scaffold the inner loop
              wears, and the record the inner loop leaves behind.
            </p>

            <h2>Inner: the agentic loop</h2>
            <p>
              The inner loop is the primitive that runs one task. It is{" "}
              <code>AgenticLoop</code> in{" "}
              <code>core/agent/loop/agent_loop.py</code>. The shape is simple. Call
              the LLM, run the tools the model asks for, observe the results, call
              again. It stops when the model has no more tool calls to make, or
              emits a termination signal.
            </p>
            <pre>{`call LLM -> tool calls? -> run tools -> observe -> call LLM ...
                  |
                  +-- no more tool calls -> answer`}</pre>
            <p>
              One run leaves two things behind: the answer for the user, and a
              transcript of what happened. The transcript is not discarded. It is
              the material the outer loop reads.
            </p>
            <p>
              For how a single turn actually runs, and the paths that end it, see{" "}
              <a href="/geode/docs/architecture/agentic-loop">The inner agentic loop</a>.
            </p>

            <h2>Outer: the self-improving loop</h2>
            <p>
              The outer loop operates not on a task but on the system itself.
              Precisely: the <strong>scaffold</strong> wrapped around the model,
              meaning the system-prompt sections
              (<code>WRAPPER_PROMPT_SECTIONS</code>) and the behaviour kinds.
              Model weights and parameters are never touched. The mechanism is
              selection: produce a candidate, measure it, keep only what is
              better.
            </p>
            <ol>
              <li>
                <strong>Mutate</strong>. Change one section of the scaffold, one
                place at a time (<code>core/self_improving/loop/mutate</code>).
              </li>
              <li>
                <strong>Audit</strong>. A Petri adversarial safety audit scores
                GEODE wearing the mutated scaffold, dimension by dimension.
              </li>
              <li>
                <strong>Fitness</strong>. Fold the dimension scores into one
                scalar (<code>core/self_improving/fitness.py</code>).
              </li>
              <li>
                <strong>Margin gate</strong>. Only improvements that clear the
                measurement uncertainty pass
                (<code>core/self_improving/gate.py</code>).
              </li>
              <li>
                <strong>Promote or revert</strong>. A pass promotes the candidate
                to the new champion; a fail reverts the scaffold to its
                pre-mutation state. Lineage is preserved as a git champion chain.
              </li>
            </ol>
            <p>
              The loop driver is <code>core/self_improving/train.py</code>. The
              filename borrows Karpathy autoresearch&apos;s three-file convention;
              no training ever happens. For the whole flow end to end, see{" "}
              <a href="/geode/docs/capabilities/autoresearch">The self-improving loop</a>.
              For the evaluation framework that does the measuring, see{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>.
            </p>

            <h2>How they interlock</h2>
            <p>
              The point is that the two loops never call each other. They connect
              through data. The inner loop acts while wearing the scaffold and
              produces transcripts; the outer loop reads them through an audit and
              changes the scaffold. The changed scaffold changes how the inner
              loop behaves next time.
            </p>
            <pre>{`outer loop  (occasional, operator-run)
  mutate scaffold -> Petri audit -> fitness -> margin gate
        -> promote / revert  (lineage: git champion chain)
     ^                |
     |                v  (new scaffold)
  +-------------------------------------------+
  |  inner loop  (every request)              |
  |    call LLM -> run tools -> observe -> ...|
  |    produces: answer + transcript          |
  +-------------------------------------------+
     |                                    ^
     +-- transcript ----------------------+
         (read by the outer loop's audit)`}</pre>
            <p>
              That is why changing the scaffold changes the inner loop&apos;s
              behaviour without changing any code. The scaffold is what the inner
              loop wears, and the outer loop is the side that picks it. One side
              wears, one side selects. That is how the two interlock into one
              system.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
