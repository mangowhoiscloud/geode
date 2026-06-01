import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "The two loops — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="concepts/two-loops"
      title="The two loops"
      titleKo="두 개의 루프"
      summary="The mental model the rest of the docs build on. An inner agentic loop runs one task; an outer loop tunes the system that runs tasks."
      summaryKo="나머지 문서가 기대는 멘탈 모델입니다. 안쪽 agentic 루프가 작업 하나를 처리하고, 바깥쪽 루프가 작업을 처리하는 시스템 자체를 다듬습니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 루프가 둘인가</h2>
            <p>
              GEODE 안에는 서로 맞물린 루프가 둘 있습니다. 둘을 구분하면 나머지
              문서가 한결 읽기 쉬워집니다. 안쪽 루프는 작업 하나를 처리합니다.
              바깥쪽 루프는 그 작업을 처리하는 시스템을 시간이 지나며 다듬습니다.
            </p>
            <p>
              안쪽 루프는 매 요청마다 돕니다. 바깥쪽 루프는 가끔, 예약된 시점에
              돕니다. 둘은 같은 코드를 공유하지 않습니다. 대신 한 가지를 주고받습니다.
              바로 안쪽 루프가 남긴 기록입니다.
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
              바깥쪽 루프가 다루는 대상은 작업이 아니라 시스템 자체입니다. 안쪽
              루프가 어떻게 행동하는지 관측하고, 그 행동을 결정하는 정책을 한 군데
              바꾼 뒤, 바뀐 정책으로 다시 측정합니다. 좋아졌으면 채택하고, 아니면
              되돌립니다.
            </p>
            <ol>
              <li>
                <strong>관측</strong>. Petri 평가가 안쪽 루프의 트랜스크립트를
                차원별로 채점합니다.
              </li>
              <li>
                <strong>변형</strong>. <code>state/autoresearch/policies/</code>의
                정책 파일 하나를 한 번에 한 군데만 바꿉니다.
              </li>
              <li>
                <strong>재감사</strong>. 바뀐 정책으로 다시 Petri 감사를 돌립니다.
              </li>
              <li>
                <strong>귀속</strong>. 점수 변화를 그 변형 탓으로 돌려도 되는지
                판단합니다.
              </li>
              <li>
                <strong>승격 또는 되돌리기</strong>. 차원이 기준을 넘으면{" "}
                <code>state/autoresearch/baseline.json</code>을 갱신하고, 아니면
                정책을 변형 이전으로 되돌립니다.
              </li>
            </ol>
            <p>
              이 흐름의 전체 그림은{" "}
              <a href="/geode/docs/capabilities/autoresearch">폐루프</a>에서, 측정에
              쓰는 평가 프레임워크는{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>에서 다룹니다.
            </p>

            <h2>둘이 맞물리는 방식</h2>
            <p>
              핵심은 두 루프가 직접 호출하지 않는다는 점입니다. 둘은 데이터로
              연결됩니다. 안쪽 루프는 트랜스크립트와 결과를 만들고, 바깥쪽 루프는
              그것을 Petri 감사로 읽어 정책을 바꿉니다. 바뀐 정책은 다음 번 안쪽
              루프가 행동하는 방식을 바꿉니다.
            </p>
            <pre>{`outer loop  (occasional, scheduled)
  observe  -> mutate policy -> re-audit -> attribute -> promote / revert
     ^                |
     |                v
  +-------------------------------------------+
  |  inner loop  (every request)              |
  |    call LLM -> run tools -> observe -> ... |
  |    produces: answer + transcript          |
  +-------------------------------------------+
     |                                    ^
     +-- transcript ----------------------+
         (read by the outer loop's audit)`}</pre>
            <p>
              그래서 정책을 바꾸면 코드를 바꾸지 않아도 안쪽 루프의 행동이
              달라집니다. 정책은 안쪽 루프가 매 호출마다 읽는 파일이고, 바깥쪽
              루프는 그 파일을 쓰는 쪽입니다. 한쪽은 읽고 한쪽은 씁니다. 둘은
              그렇게 한 시스템으로 맞물립니다.
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
              occasionally, at scheduled points. They do not share code. They
              hand one thing back and forth: the record the inner loop leaves
              behind.
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
              The outer loop operates not on a task but on the system itself. It
              observes how the inner loop behaves, changes one policy that governs
              that behaviour, then measures again with the changed policy. If it
              improved, keep it. If not, revert.
            </p>
            <ol>
              <li>
                <strong>Observe</strong>. A Petri evaluation scores the inner
                loop&apos;s transcripts dimension by dimension.
              </li>
              <li>
                <strong>Mutate</strong>. Change one policy file under{" "}
                <code>state/autoresearch/policies/</code>, one place at a time.
              </li>
              <li>
                <strong>Re-audit</strong>. Run the Petri audit again with the
                changed policy.
              </li>
              <li>
                <strong>Attribute</strong>. Decide whether the score change can be
                credited to that mutation.
              </li>
              <li>
                <strong>Promote or revert</strong>. If the dimensions clear the
                bar, update <code>state/autoresearch/baseline.json</code>;
                otherwise revert the policy to its pre-mutation state.
              </li>
            </ol>
            <p>
              For the whole flow end to end, see{" "}
              <a href="/geode/docs/capabilities/autoresearch">The closed loop</a>.
              For the evaluation framework that does the measuring, see{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>.
            </p>

            <h2>How they interlock</h2>
            <p>
              The point is that the two loops never call each other. They connect
              through data. The inner loop produces transcripts and outcomes; the
              outer loop reads them via a Petri audit and changes a policy. The
              changed policy changes how the inner loop behaves next time.
            </p>
            <pre>{`outer loop  (occasional, scheduled)
  observe  -> mutate policy -> re-audit -> attribute -> promote / revert
     ^                |
     |                v
  +-------------------------------------------+
  |  inner loop  (every request)              |
  |    call LLM -> run tools -> observe -> ... |
  |    produces: answer + transcript          |
  +-------------------------------------------+
     |                                    ^
     +-- transcript ----------------------+
         (read by the outer loop's audit)`}</pre>
            <p>
              That is why changing a policy changes the inner loop&apos;s behaviour
              without changing any code. The policy is a file the inner loop reads
              on each call, and the outer loop is the side that writes it. One side
              reads, one side writes. That is how the two interlock into one
              system.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
