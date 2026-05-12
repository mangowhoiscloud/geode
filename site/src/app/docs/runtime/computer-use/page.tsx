import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Computer Use — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/computer-use"
      title="Computer Use"
      titleKo="컴퓨터 사용"
      summary="Provider-agnostic desktop automation. PyAutoGUI backend, screenshot + click + type primitives, opt-in via tool registry."
      summaryKo="프로바이더 독립 데스크탑 자동화. PyAutoGUI 백엔드, screenshot + click + type 기본 동작, 도구 레지스트리를 통한 opt-in 활성화."
    >
      <Bi
        ko={
          <>
            <h2>두 백엔드, 하나의 인터페이스</h2>
            <p>
              Anthropic의 computer-use API와 OpenAI의 computer-use 베타는 비슷한
              기본 동작을 가진 서로 다른 프로토콜입니다. GEODE는 둘 모두를 단일
              도구 정의 (<code>computer</code>) 뒤로 감싸고, 활성 모델에 따라 적절한
              프로바이더 백엔드로 라우팅합니다.
            </p>

            <h2>기본 동작</h2>
            <ul>
              <li><strong>screenshot</strong>. 활성 디스플레이 캡처</li>
              <li><strong>click</strong>. (x, y) 좌표에서 마우스 클릭</li>
              <li><strong>type</strong>. 키보드 입력</li>
              <li><strong>key</strong>. 수정자 + 키 (Cmd+Tab 등)</li>
              <li><strong>scroll</strong>. 방향 + 양</li>
              <li><strong>cursor_position</strong>. 현재 위치 읽기</li>
            </ul>

            <h2>활성화</h2>
            <p>
              computer-use 도구는{" "}
              <code>is_computer_use_enabled()</code>를 통한 opt-in 방식입니다.
              config 플래그와 활성 프로바이더의 지원 여부로 게이트됩니다. 활성화되면
              Anthropic agentic 어댑터가{" "}
              <code>core/llm/providers/anthropic.py</code>에서{" "}
              <code>_COMPUTER_USE_TOOL</code>을 도구 목록에 주입합니다.
            </p>

            <h2>안전성</h2>
            <p>
              모든 <code>click</code>과 <code>type</code> 동작은 기본적으로{" "}
              <code>TOOL_APPROVAL_REQUEST</code>를 발생시킵니다. HITL 게이트는 세션
              단위 (<code>--no-approve</code>) 또는 도구 단위로 완화할 수 있지만,
              기본값은 데스크탑에 부수 효과를 일으키는 모든 동작에 대해 human-in-the-loop
              입니다.
            </p>

            <h2>파일</h2>
            <ul>
              <li><code>core/tools/computer_use.py</code>. 기본 동작 구현</li>
              <li><code>core/llm/providers/anthropic.py</code>. <code>_COMPUTER_USE_TOOL</code> 정의 + 주입</li>
              <li><code>core/llm/providers/openai.py</code>. OpenAI 베타 경로</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Two backends, one interface</h2>
            <p>
              Anthropic&apos;s computer-use API and OpenAI&apos;s computer-use
              beta are different protocols with similar primitives. GEODE
              wraps both behind a single tool definition (
              <code>computer</code>) and routes to the appropriate provider
              backend based on the active model.
            </p>

            <h2>Primitives</h2>
            <ul>
              <li><strong>screenshot</strong> — capture the active display</li>
              <li><strong>click</strong> — mouse click at (x, y)</li>
              <li><strong>type</strong> — keyboard input</li>
              <li><strong>key</strong> — modifier + key (Cmd+Tab, etc.)</li>
              <li><strong>scroll</strong> — direction + amount</li>
              <li><strong>cursor_position</strong> — read current</li>
            </ul>

            <h2>Activation</h2>
            <p>
              The computer-use tool is opt-in via{" "}
              <code>is_computer_use_enabled()</code> — gated by config flag and
              the active provider supporting it. When enabled, the Anthropic
              agentic adapter injects <code>_COMPUTER_USE_TOOL</code> into the
              tool list at <code>core/llm/providers/anthropic.py</code>.
            </p>

            <h2>Safety</h2>
            <p>
              Every <code>click</code> and <code>type</code> action fires{" "}
              <code>TOOL_APPROVAL_REQUEST</code> by default. The HITL gate can be
              relaxed per session (<code>--no-approve</code>) or per-tool, but
              the default is human-in-the-loop for any side-effect on the
              desktop.
            </p>

            <h2>Files</h2>
            <ul>
              <li><code>core/tools/computer_use.py</code> — primitive implementations</li>
              <li><code>core/llm/providers/anthropic.py</code> — <code>_COMPUTER_USE_TOOL</code> definition + injection</li>
              <li><code>core/llm/providers/openai.py</code> — OpenAI beta path</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
