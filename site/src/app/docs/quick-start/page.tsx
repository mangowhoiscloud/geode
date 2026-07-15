import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Quick Start — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="quick-start"
      title="Quick Start"
      titleKo="빠른 시작"
      summary="Install GEODE, run the setup wizard, and hold your first conversation. Success criteria and a recovery path included."
      summaryKo="GEODE를 설치하고 설정 마법사를 돌린 뒤 첫 대화까지 갑니다. 성공 기준과 복구 절차를 함께 안내합니다."
    >
      <Bi
        ko={
          <>
            <h2>요구사항</h2>
            <ul>
              <li>Python 3.12 이상</li>
              <li><code>uv</code> 패키지 매니저 (<a href="https://docs.astral.sh/uv/">설치 안내</a>)</li>
              <li>프로바이더 자격 1개 이상. ChatGPT Plus 구독(OAuth), Anthropic 구독(OAuth) 또는 API 키 중 하나면 충분합니다.</li>
            </ul>

            <h2>1. 설치</h2>
            <p>
              PyPI 배포명은 <code>geode-agent</code>, 설치되는 명령은
              <code>geode</code>와 <code>geode-mcp</code> 두 개입니다.
            </p>
            <pre>{`uv tool install geode-agent
geode version`}</pre>
            <p>소스 체크아웃으로 개발하려면 이렇게 설치합니다.</p>
            <pre>{`git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync
uv tool install -e . --force`}</pre>

            <h2>2. 설정 마법사</h2>
            <p>
              <code>geode setup</code>이 자격을 잡아줍니다. ChatGPT 구독
              OAuth(<code>~/.codex/auth.json</code>)가 있으면 API 키를 묻기 전에
              먼저 감지합니다. 시크릿은 <code>~/.geode/.env</code>에, 모델 선택
              같은 동작 설정은 <code>~/.geode/config.toml</code>에 저장됩니다.
              .env에 모델을 적는 방식은 더 이상 쓰지 않습니다.
            </p>
            <pre>{`geode setup        # 처음 설정
geode setup -r     # 처음부터 다시`}</pre>

            <h2>3. 첫 대화</h2>
            <p>
              <code>geode</code>를 실행하면 serve 데몬이 자동으로 켜지고 thin
              CLI가 IPC로 붙습니다. 자유 텍스트는 이 대화형 화면 안에서
              입력합니다. 셸에서 <code>geode &quot;요청&quot;</code> 형태의
              원샷은 지원하지 않습니다.
            </p>
            <pre>{`geode

> 오늘 AI 리서치 트렌드를 요약해줘
> /model        # 모델 확인과 전환
> /status       # 데몬, MCP, 키 상태
> /quit`}</pre>

            <h2>성공 기준</h2>
            <ul>
              <li>배너에 버전과 모델이 표시되고 dim한 &quot;session cli-… · connected&quot; 라인이 보입니다.</li>
              <li>자유 텍스트에 에이전트가 도구를 호출하며 답합니다.</li>
              <li><code>geode about</code>의 EFFECTIVE 모델이 의도한 모델과 일치합니다.</li>
            </ul>

            <h2>자주 만나는 실패와 해법</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>모델을 바꿨는데 그대로</td>
                  <td>상위 레이어가 가리는 중</td>
                  <td><code>geode config explain model</code>로 어느 레이어가 이기는지 확인합니다. <code>geode about</code>이 실효값입니다.</td>
                </tr>
                <tr>
                  <td><code>geode serve</code>가 거부</td>
                  <td>gateway 비활성</td>
                  <td><code>~/.geode/.env</code>에 <code>GEODE_GATEWAY_ENABLED=true</code>를 추가합니다. 대화만 하려면 serve를 직접 띄울 필요가 없습니다.</td>
                </tr>
                <tr>
                  <td>응답이 비거나 끊김</td>
                  <td>자격 만료 또는 무효</td>
                  <td><code>geode doctor</code>로 키와 OAuth 상태를 점검하고 <code>/login</code>으로 갱신합니다.</td>
                </tr>
                <tr>
                  <td>배너 모델과 실제 응답 모델이 다름</td>
                  <td>오래된 데몬이 살아 있음</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code> 후 다시 <code>geode</code>를 실행합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>복구 절차</h2>
            <p>망가진 상태에서 알려진 상태로 돌아오는 순서입니다.</p>
            <ol>
              <li><code>geode doctor</code>. 파이썬, PATH, 자격, 데몬을 한 번에 점검합니다.</li>
              <li><code>geode about</code>. 실제로 어떤 모델과 경로가 잡혀 있는지 확인합니다.</li>
              <li><code>geode config explain model</code>. 설정이 어디서 가려지는지 봅니다.</li>
              <li><code>pkill -f &quot;geode serve&quot;</code> 후 재진입. 데몬을 새로 띄웁니다.</li>
              <li><code>geode setup -r</code>. 그래도 안 되면 설정을 처음부터 다시 합니다.</li>
            </ol>

            <h2>업데이트와 삭제</h2>
            <pre>{`geode update                  # uv: 최신 patch; 소스: pull + rebuild
geode update --latest         # uv: minor/major 업데이트를 명시적으로 허용
geode uninstall               # 런타임 데이터 + CLI 제거`}</pre>

            <h2>다음 단계</h2>
            <ul>
              <li><a href="/geode/docs/run/pick-path">경로 선택</a>. 구독, API 키, 무료 경로 중 무엇이 맞는지 고릅니다.</li>
              <li><a href="/geode/docs/concepts/two-loops">두 개의 루프</a>. GEODE의 핵심 멘탈 모델입니다.</li>
              <li><a href="/geode/docs/run/serve">데몬으로 실행</a>. 메신저와 스케줄을 붙이는 길입니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Requirements</h2>
            <ul>
              <li>Python 3.12+</li>
              <li><code>uv</code> package manager (<a href="https://docs.astral.sh/uv/">install</a>)</li>
              <li>One provider credential. A ChatGPT Plus subscription (OAuth), an Anthropic subscription (OAuth), or an API key is enough.</li>
            </ul>

            <h2>1. Install</h2>
            <p>
              The PyPI distribution is <code>geode-agent</code>. It installs two
              commands: <code>geode</code> and <code>geode-mcp</code>.
            </p>
            <pre>{`uv tool install geode-agent
geode version`}</pre>
            <p>To develop from a source checkout:</p>
            <pre>{`git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync
uv tool install -e . --force`}</pre>

            <h2>2. Setup wizard</h2>
            <p>
              <code>geode setup</code> wires your credentials. It detects a
              ChatGPT subscription OAuth (<code>~/.codex/auth.json</code>)
              before asking for API keys. Secrets land in
              <code>~/.geode/.env</code>; behavior settings such as the model
              choice live in <code>~/.geode/config.toml</code>. Putting a model
              in .env is no longer how persistence works.
            </p>
            <pre>{`geode setup        # first-time setup
geode setup -r     # start over`}</pre>

            <h2>3. First conversation</h2>
            <p>
              Running <code>geode</code> auto-starts the serve daemon and
              attaches a thin CLI over IPC. Free text goes inside this
              interactive screen. A shell one-shot like
              <code>geode &quot;prompt&quot;</code> is not supported.
            </p>
            <pre>{`geode

> summarize today's AI research trends
> /model        # inspect and switch models
> /status       # daemon, MCP, credential state
> /quit`}</pre>

            <h2>What success looks like</h2>
            <ul>
              <li>The banner shows the version and model, and a dim &quot;session cli-… · connected&quot; line appears.</li>
              <li>Free text gets an answer that uses tools along the way.</li>
              <li><code>geode about</code> reports the EFFECTIVE model you intended.</li>
            </ul>

            <h2>Common failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Likely cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Switched models but nothing changed</td>
                  <td>A higher layer masks your change</td>
                  <td>Run <code>geode config explain model</code> to see which layer wins. <code>geode about</code> shows the effective value.</td>
                </tr>
                <tr>
                  <td><code>geode serve</code> refuses to start</td>
                  <td>Gateway disabled</td>
                  <td>Add <code>GEODE_GATEWAY_ENABLED=true</code> to <code>~/.geode/.env</code>. For chat only, you never need to start serve yourself.</td>
                </tr>
                <tr>
                  <td>Empty or broken replies</td>
                  <td>Expired or invalid credentials</td>
                  <td>Check keys and OAuth with <code>geode doctor</code>, refresh with <code>/login</code>.</td>
                </tr>
                <tr>
                  <td>Banner model differs from the answering model</td>
                  <td>A stale daemon survived an update</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>, then run <code>geode</code> again.</td>
                </tr>
              </tbody>
            </table>

            <h2>Recovery toolkit</h2>
            <p>The sequence that gets you from a broken state back to a known one.</p>
            <ol>
              <li><code>geode doctor</code>. Python, PATH, credentials, and the daemon in one pass.</li>
              <li><code>geode about</code>. What model and paths are actually in effect.</li>
              <li><code>geode config explain model</code>. Where a setting is being masked.</li>
              <li><code>pkill -f &quot;geode serve&quot;</code>, then re-enter. Fresh daemon.</li>
              <li><code>geode setup -r</code>. If all else fails, redo setup from scratch.</li>
            </ol>

            <h2>Update and uninstall</h2>
            <pre>{`geode update                  # uv: latest patch; source: pull + rebuild
geode update --latest         # uv: explicitly allow minor/major upgrades
geode uninstall               # remove runtime data + installed CLI`}</pre>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/run/pick-path">Pick a path</a>. Subscription, API key, or the free path.</li>
              <li><a href="/geode/docs/concepts/two-loops">The two loops</a>. The mental model the rest of the docs build on.</li>
              <li><a href="/geode/docs/run/serve">Run as a daemon</a>. The road to messaging and schedules.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
