import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Computer use — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/computer-use"
      title="Computer use"
      titleKo="컴퓨터 사용"
      summary="Desktop automation through a Python or macOS-helper driver, with coordinate scaling, postconditions, and fail-closed remote access."
      summaryKo="Python 또는 macOS helper driver로 데스크탑을 조작하며 좌표 스케일링, 사후조건, 기본 차단 원격 접근을 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              컴퓨터 사용은 모델이 스크린샷으로 화면을 보고 클릭, 타이핑,
              스크롤을 지시하는 기능입니다. GEODE의 구현은{" "}
              <code>core/tools/computer_use.py</code>의{" "}
              <code>ComputerUseHarness</code> 하나이며 host backend는 pyautogui
              또는 macOS helper입니다.
              매 동작 후 base64 JPEG 스크린샷을 돌려주어 모델이 결과를
              관찰합니다.
            </p>

            <h2>동작 방식</h2>
            <pre>{`LLM ── tool_use("computer", action, 좌표/텍스트) ──→ handle_computer
                                                     (core/cli/tool_handlers/single_tool.py)
                                                          │ asyncio.to_thread
                                                          ▼
                                              ComputerUseHarness._execute_sync
                                                          │ pyautogui / macOS helper
                                                          ▼
LLM ←──────── { result, action, screenshot(base64 JPEG) } ◄┘`}</pre>
            <p>
              디스패치 테이블은 프로바이더 중립입니다. Anthropic 어휘
              (<code>left_click</code>, <code>triple_click</code>,{" "}
              <code>cursor_position</code>)와 OpenAI 어휘
              (<code>keypress</code>)를 같은 핸들러로 받습니다. 지원 동작은{" "}
              <code>screenshot</code>, <code>click</code>,{" "}
              <code>double_click</code>, <code>type</code>, <code>key</code>,{" "}
              <code>scroll</code>, <code>move</code>, <code>drag</code>,{" "}
              <code>wait</code>와 클릭 변형들입니다. 모르는 action은 지원 목록과
              함께 오류로 돌아갑니다.
            </p>
            <p>
              좌표는 타깃 공간과 실제 화면 사이를 양방향 스케일링합니다. 모델은{" "}
              <code>display_width_px=1280, display_height_px=800</code> 기준으로
              좌표를 내고, 하네스가 실제 해상도로 변환합니다.
            </p>

            <h2>구조를 먼저 읽고, 스크린샷은 나중에</h2>
            <p>
              화면에 무엇이 있는지 알아내는 데 스크린샷이 유일한 방법은
              아닙니다. 스텝마다 1280x800 JPEG(약 1.5k 토큰)를 보내고 모델이
              좌표를 눈대중하는 대신, 접근성 트리나 DOM처럼 구조가 있는 표면은
              텍스트로 더 싸고 정확하게 읽힙니다. GEODE는 이 두 표면을 각각
              도구로 노출합니다.
            </p>
            <ul>
              <li>
                <code>ui_probe</code>(<code>core/tools/ui_probe.py</code>).
                macOS 접근성(AX) 트리를 role, title, value, 사각형 텍스트로
                반환합니다. 여기서 AX는 Apple의 접근성(Accessibility)
                프레임워크(<code>AXUIElement</code> 등 <code>AX</code> 접두어
                API)를 가리킵니다. 네이티브 macOS 앱에서 스크린샷보다 저렴하고
                신뢰도 높은 첫 단계입니다. 소프트 의존 pyobjc(<code>[desktop]</code>{" "}
                extra), OS 접근성 권한이 필요합니다. AX 판독은 라이브 검증됨
                (2026-07-04). AX 좌표에서 클릭 좌표로의 매핑 캘리브레이션은
                아직 미검증이며 사각형은 <code>coord_space=ax_points</code>로
                표기됩니다.
              </li>
              <li>
                <code>browser_scan</code> / <code>browser_execute_js</code>
                (<code>core/tools/browser_tools.py</code>). CDP로 운영자의 실제
                Chrome에 붙어 로그인 세션, 쿠키, 핑거프린트를 그대로 두고 웹을
                지각하고 조작합니다. 로그인 벽, SPA, CAPTCHA가 사람이 쓸 때처럼
                동작합니다. <code>web_fetch</code>(헤드리스 GET, JS 없음)나 픽셀
                클릭과 달리 브라우저 작업은 실제 DOM 판독과 JS 실행으로
                처리합니다. Chrome을 <code>--remote-debugging-port=9222</code>로
                실행하면 됩니다. CDP 라운드트립은 라이브 검증됨(2026-07-04).
              </li>
            </ul>
            <p>
              먼저 접근성 트리나 DOM으로 구조를 읽고, 그것이 없거나 부족한
              화면(게임, 직접 그린 캔버스)에서만 픽셀 하네스로 내려갑니다.
            </p>

            <h2>활성화</h2>
            <p>
              게이트는 <code>is_computer_use_enabled()</code>
              (<code>core/llm/providers/anthropic.py</code>) 하나입니다. 설정{" "}
              <code>computer_use_enabled</code>(<code>core/config/_settings.py</code>)가
              켜져 있고 선택한 실행 경로가 준비되어 있어야 true입니다. sandbox
              경로는 host pyautogui가 필요 없고, helper 경로는 설치된 helper를,
              python 경로는 pyautogui를 요구합니다.
            </p>
            <pre>{`[computer_use]
enabled = true
env = "host"
driver = "helper"
# helper_path = "/absolute/path/to/geode-computer-helper"`}</pre>
            <p>
              프로바이더가 native computer surface를 지원하면 그 경로를 쓰고,
              ChatGPT subscription처럼 native surface를 받지 않는 backend에는
              같은 하네스를 normal function tool <code>computer_use</code>로
              노출합니다.
            </p>

            <h2>안전</h2>
            <p>
              <code>computer</code>는 <code>core/agent/safety.py</code>의{" "}
              <code>DANGEROUS_TOOLS</code>에 속합니다. <code>run_bash</code>와
              같은 등급으로, 대화형 세션에서는 human-in-the-loop 승인을 요구하고
              서브에이전트 자동 승인 대상에서 제외됩니다. 승인 UI가 없는 DAEMON
              세션은 기본 차단되며 제한된 gateway에서{" "}
              <code>[gateway] allow_computer_use = true</code>를 명시했을 때만
              executor가 두 computer-use surface의 실행을 허용합니다. 옵션이
              꺼져 있으면 provider-visible schema가 있더라도 dispatch 전에
              거부합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr><td>도구 목록에 <code>computer</code>가 없음</td><td>설정이 꺼졌거나 선택한 driver가 준비되지 않음</td><td><code>computer_use_enabled</code>와 pyautogui/helper 설치 상태를 확인합니다.</td></tr>
                <tr><td><code>move</code>가 Accessibility 오류</td><td>OS가 입력 이벤트를 거부했거나 helper 권한이 없음</td><td>활성 driver/helper에 Accessibility 권한을 주고 <code>geode doctor</code>를 다시 실행합니다.</td></tr>
                <tr><td>동작이 오류로 반환</td><td>지원하지 않는 action 이름</td><td>오류 응답의 <code>supported_actions</code> 목록을 확인합니다.</td></tr>
                <tr><td>클릭 위치가 어긋남</td><td>타깃 공간과 화면 해상도 불일치</td><td>스케일링은 자동입니다. 멀티 디스플레이 구성에서는 활성 디스플레이 기준임을 감안합니다.</td></tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>. 도구 레지스트리와 승인 흐름.</li>
              <li><a href="/geode/docs/harness/lifecycle">정책과 라이프사이클</a>. DANGEROUS 분류가 사는 곳.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Computer use lets the model see the screen through screenshots and
              direct clicks, typing, and scrolling. GEODE&apos;s implementation
              is a single <code>ComputerUseHarness</code> in{" "}
              <code>core/tools/computer_use.py</code>, backed on the host by
              pyautogui or the macOS helper.
              Every action returns a base64 JPEG screenshot so the model
              observes the result.
            </p>

            <h2>How it runs</h2>
            <pre>{`LLM ── tool_use("computer", action, coords/text) ──→ handle_computer
                                                     (core/cli/tool_handlers/single_tool.py)
                                                          │ asyncio.to_thread
                                                          ▼
                                              ComputerUseHarness._execute_sync
                                                          │ pyautogui / macOS helper
                                                          ▼
LLM ←──────── { result, action, screenshot(base64 JPEG) } ◄┘`}</pre>
            <p>
              The dispatch table is provider-neutral: it accepts the Anthropic
              vocabulary (<code>left_click</code>, <code>triple_click</code>,{" "}
              <code>cursor_position</code>) and the OpenAI vocabulary
              (<code>keypress</code>) through the same handler. Supported
              actions: <code>screenshot</code>, <code>click</code>,{" "}
              <code>double_click</code>, <code>type</code>, <code>key</code>,{" "}
              <code>scroll</code>, <code>move</code>, <code>drag</code>,{" "}
              <code>wait</code>, plus the click variants. Unknown actions return
              an error with the supported list.
            </p>
            <p>
              Coordinates scale both ways between the target space and the real
              screen: the model addresses a{" "}
              <code>display_width_px=1280, display_height_px=800</code> canvas,
              and the harness converts to the actual resolution.
            </p>

            <h2>Read structure first, screenshot later</h2>
            <p>
              A screenshot is not the only way to learn what is on screen.
              Instead of shipping a 1280x800 JPEG (about 1.5k tokens) each step
              and having the model eyeball coordinates, structured surfaces like
              the accessibility tree or the DOM read more cheaply and precisely
              as text. GEODE exposes each of those surfaces as a tool.
            </p>
            <ul>
              <li>
                <code>ui_probe</code> (<code>core/tools/ui_probe.py</code>).
                Returns a native macOS app&apos;s accessibility (AX) tree as
                text (role, title, value, rectangle). AX here is Apple&apos;s
                macOS Accessibility framework (the <code>AX</code>-prefixed UI
                API such as <code>AXUIElement</code>). It is a cheaper, more
                reliable first step than a screenshot for native macOS apps.
                pyobjc is a soft dependency (<code>[desktop]</code> extra) and
                the OS Accessibility permission is required. The AX readout is
                live-verified (2026-07-04). Mapping an AX rectangle to a click
                coordinate is not yet calibrated, so rectangles are tagged{" "}
                <code>coord_space=ax_points</code>.
              </li>
              <li>
                <code>browser_scan</code> / <code>browser_execute_js</code>
                (<code>core/tools/browser_tools.py</code>). Attach to the
                operator&apos;s real Chrome over CDP and perceive or drive the
                web with the login session, cookies, and fingerprint intact.
                Login walls, SPAs, and CAPTCHA behave as they do for a human.
                Unlike <code>web_fetch</code> (headless GET, no JS) or pixel
                clicking, browser work runs against the live DOM and executes
                JS. Launch Chrome with{" "}
                <code>--remote-debugging-port=9222</code>. The CDP round-trip is
                live-verified (2026-07-04).
              </li>
            </ul>
            <p>
              Read structure from the accessibility tree or the DOM first, and
              drop to the pixel harness only for screens that lack it (games,
              custom-drawn canvases).
            </p>

            <h2>Activation</h2>
            <p>
              The gate is one function: <code>is_computer_use_enabled()</code>{" "}
              in <code>core/llm/providers/anthropic.py</code>. It is true when
              the <code>computer_use_enabled</code> setting
              (<code>core/config/_settings.py</code>) is on and the selected
              execution path is ready. Sandbox mode needs no host pyautogui;
              helper mode requires an installed helper, and python mode
              requires pyautogui.
            </p>
            <pre>{`[computer_use]
enabled = true
env = "host"
driver = "helper"
# helper_path = "/absolute/path/to/geode-computer-helper"`}</pre>
            <p>
              Providers use their native computer surface when supported.
              Backends that do not accept it, including the ChatGPT subscription
              route, receive the same harness as the normal{" "}
              <code>computer_use</code> function tool.
            </p>

            <h2>Safety</h2>
            <p>
              <code>computer</code> belongs to <code>DANGEROUS_TOOLS</code> in{" "}
              <code>core/agent/safety.py</code>, the same class as{" "}
              <code>run_bash</code>: interactive sessions require
              human-in-the-loop approval, and sub-agent auto-approval excludes
              it. DAEMON sessions have no approval UI and deny it by default;
              a restricted gateway must set{" "}
              <code>[gateway] allow_computer_use = true</code> before the
              executor permits either computer-use surface. While it is off,
              execution is rejected before dispatch even if a provider-visible
              schema is present.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr><td><code>computer</code> missing from the tool list</td><td>The setting is off or the selected driver is unavailable</td><td>Check <code>computer_use_enabled</code> and the pyautogui/helper installation.</td></tr>
                <tr><td><code>move</code> returns an Accessibility error</td><td>The OS rejected the event or the helper lacks permission</td><td>Grant Accessibility to the active driver/helper and rerun <code>geode doctor</code>.</td></tr>
                <tr><td>An action returns an error</td><td>Unsupported action name</td><td>Check the <code>supported_actions</code> list in the error response.</td></tr>
                <tr><td>Clicks land off-target</td><td>Target-space vs screen-resolution mismatch</td><td>Scaling is automatic; on multi-display setups it works against the active display.</td></tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>. The tool registry and approval flow.</li>
              <li><a href="/geode/docs/harness/lifecycle">Policy and lifecycle</a>. Where the DANGEROUS classification lives.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
