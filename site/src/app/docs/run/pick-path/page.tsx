import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Pick a Path — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/pick-path"
      title="Pick a path"
      titleKo="경로 선택"
      summary="Subscription OAuth, API key, or the budget lane. A decision table for picking your credential path."
      summaryKo="구독 OAuth, API 키, 저비용 경로. 자격 경로를 고르는 결정 표입니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE를 돌리려면 프로바이더 자격이 하나 필요합니다. 이 페이지는
              네 가지 자격 경로를 비교하고, 본인 상황에 맞는 가장 빠른 길을
              안내합니다.
            </p>

            <h2>네 가지 경로</h2>
            <table>
              <thead>
                <tr><th>경로</th><th>자격</th><th>등록 방법</th><th>적합한 상황</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>1. ChatGPT 구독 OAuth</td>
                  <td>ChatGPT Plus 구독 (Codex CLI 토큰)</td>
                  <td><code>geode setup</code>이 <code>~/.codex/auth.json</code>을 자동 감지합니다. 없으면 <code>/login openai</code>로 device-code 로그인.</td>
                  <td>이미 ChatGPT를 결제 중이고 API 키를 따로 만들기 싫을 때. <code>gpt-5.5</code>는 이 경로로만 라우팅됩니다.</td>
                </tr>
                <tr>
                  <td>2. Anthropic 구독 OAuth</td>
                  <td>Claude 구독 (claude CLI 자격)</td>
                  <td><code>/login anthropic</code>. macOS keychain의 Claude Code 자격을 읽습니다.</td>
                  <td>Claude 구독이 있고 <code>claude-opus-4-8</code> 계열을 기본으로 쓰고 싶을 때.</td>
                </tr>
                <tr>
                  <td>3. PAYG API 키</td>
                  <td><code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>ZAI_API_KEY</code></td>
                  <td><code>~/.geode/.env</code>에 키만 적습니다. <code>geode setup</code> 또는 <code>/login add</code>가 대신 적어줍니다.</td>
                  <td>토큰 단위로 비용을 직접 통제하고 싶을 때. 팀 계정과 CI에도 맞습니다.</td>
                </tr>
                <tr>
                  <td>4. 저비용 GLM 경로</td>
                  <td><code>ZAI_API_KEY</code> (GLM)</td>
                  <td>같은 방식으로 <code>~/.geode/.env</code>에 등록합니다.</td>
                  <td>거의 무료로 먼저 체험할 때. <code>glm-4.7-flash</code>는 한시 무료 티어입니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              <code>~/.geode/.env</code>는 시크릿 전용 파일입니다. 모델 선택
              같은 동작 설정은 <code>~/.geode/config.toml</code>에 저장되며,
              .env에 모델을 적는 방식은 더 이상 쓰지 않습니다.
            </p>

            <h2>가장 빠른 길 찾기</h2>
            <table>
              <thead>
                <tr><th>원하는 것</th><th>이렇게 합니다</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>이미 ChatGPT Plus를 결제 중입니다</td>
                  <td><code>geode setup</code>. <code>~/.codex/auth.json</code>이 있으면 API 키를 묻기 전에 먼저 잡습니다.</td>
                </tr>
                <tr>
                  <td>Claude 구독으로 쓰고 싶습니다</td>
                  <td><code>geode</code> 안에서 <code>/login anthropic</code>을 실행합니다.</td>
                </tr>
                <tr>
                  <td>API 키로 비용을 직접 통제하고 싶습니다</td>
                  <td><code>~/.geode/.env</code>에 키를 넣고 <a href="/geode/docs/ops/cost">비용 모니터링</a>으로 예산을 겁니다.</td>
                </tr>
                <tr>
                  <td>거의 무료로 먼저 체험하고 싶습니다</td>
                  <td>GLM 키(<code>ZAI_API_KEY</code>)를 등록하고 <code>/model</code>에서 <code>glm-4.7-flash</code>를 고릅니다.</td>
                </tr>
                <tr>
                  <td>특정 프로바이더를 OAuth 대신 키로 강제하고 싶습니다</td>
                  <td><code>/login source &lt;provider&gt; api_key</code>. 선택은 <code>config.toml</code>에만 저장됩니다.</td>
                </tr>
                <tr>
                  <td>지금 뭐가 잡혀 있는지 확인하고 싶습니다</td>
                  <td><code>geode about</code>. 실효 모델, 프로바이더, 자격 프로파일 수를 한 화면에 보여줍니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>자격 소스 값</h2>
            <p>
              프로바이더별 자격 소스는 <code>core/config/credential_source.py</code>의
              네 값 중 하나입니다.
            </p>
            <table>
              <thead>
                <tr><th>값</th><th>의미</th></tr>
              </thead>
              <tbody>
                <tr><td><code>auto</code></td><td>기본값. OAuth를 먼저 시도하고, PAYG 전환은 설정으로 게이트됩니다.</td></tr>
                <tr><td><code>api_key</code></td><td>PAYG API 키만 사용합니다.</td></tr>
                <tr><td><code>claude-cli</code></td><td>claude CLI의 Anthropic 구독 OAuth를 사용합니다.</td></tr>
                <tr><td><code>openai-codex</code></td><td>Codex CLI의 ChatGPT 구독 OAuth를 사용합니다.</td></tr>
              </tbody>
            </table>

            <h2>예시</h2>
            <pre>{`geode setup              # 자격 감지 + 등록 마법사
geode                    # 대화 시작

> /login                 # 자격 대시보드
> /login openai          # ChatGPT 구독 OAuth 로그인
> /login anthropic       # Claude 구독 OAuth 로그인
> /login source openai api_key   # OpenAI를 키 경로로 고정

geode about              # 실효 모델 + 자격 상태 확인`}</pre>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>setup이 ChatGPT OAuth를 못 찾음</td>
                  <td><code>~/.codex/auth.json</code> 없음</td>
                  <td>Codex CLI로 먼저 로그인하거나 <code>/login openai</code>의 device-code 플로우를 씁니다. 후자는 <code>~/.geode/auth.toml</code>에 저장됩니다.</td>
                </tr>
                <tr>
                  <td>키를 넣었는데 모델이 안 바뀜</td>
                  <td>.env는 시크릿 전용, 모델은 별개 설정</td>
                  <td><code>/model</code>로 고릅니다. 안 먹으면 <code>geode config explain model</code>로 어느 레이어가 이기는지 봅니다.</td>
                </tr>
                <tr>
                  <td>GLM 구독인데 미터링 과금</td>
                  <td>Coding Plan 키가 PAYG 엔드포인트로 나감</td>
                  <td>GLM은 Coding Plan과 PAYG 엔드포인트가 다릅니다. <a href="/geode/docs/run/providers">프로바이더 설정</a>의 GLM 절을 확인합니다.</td>
                </tr>
                <tr>
                  <td>응답이 비거나 401</td>
                  <td>OAuth 만료 또는 무효 키</td>
                  <td><code>geode doctor</code>로 점검하고 <code>/login</code>으로 갱신합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음 단계</h2>
            <ul>
              <li><a href="/geode/docs/run/providers">프로바이더 설정</a>. 라우팅, 모델 우선순위, 폴백 정책.</li>
              <li><a href="/geode/docs/config/basics">설정 기초</a>. 설정 레이어와 결정 순서.</li>
              <li><a href="/geode/docs/runtime/auth">인증과 OAuth</a>. 프로파일 회전과 쿨다운.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE needs one provider credential to run. This page compares the
              four credential paths and points you to the fastest one for your
              situation.
            </p>

            <h2>The four paths</h2>
            <table>
              <thead>
                <tr><th>Path</th><th>Credential</th><th>How to register</th><th>When it fits</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>1. ChatGPT subscription OAuth</td>
                  <td>ChatGPT Plus subscription (Codex CLI token)</td>
                  <td><code>geode setup</code> auto-detects <code>~/.codex/auth.json</code>. Without it, <code>/login openai</code> runs a device-code login.</td>
                  <td>You already pay for ChatGPT and do not want a separate API key. <code>gpt-5.5</code> routes only through this lane.</td>
                </tr>
                <tr>
                  <td>2. Anthropic subscription OAuth</td>
                  <td>Claude subscription (claude CLI credential)</td>
                  <td><code>/login anthropic</code>. Reads the Claude Code credential from the macOS keychain.</td>
                  <td>You hold a Claude subscription and want <code>claude-opus-4-8</code> models as the default.</td>
                </tr>
                <tr>
                  <td>3. PAYG API keys</td>
                  <td><code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>ZAI_API_KEY</code></td>
                  <td>Keys go in <code>~/.geode/.env</code>, written for you by <code>geode setup</code> or <code>/login add</code>.</td>
                  <td>You want per-token cost control. Also the right fit for team accounts and CI.</td>
                </tr>
                <tr>
                  <td>4. Budget GLM lane</td>
                  <td><code>ZAI_API_KEY</code> (GLM)</td>
                  <td>Same mechanism, a key in <code>~/.geode/.env</code>.</td>
                  <td>Trying GEODE at near-zero cost. <code>glm-4.7-flash</code> is a limited-time free tier.</td>
                </tr>
              </tbody>
            </table>
            <p>
              <code>~/.geode/.env</code> is a secrets-only file. Behavior
              settings such as the model choice persist in
              <code>~/.geode/config.toml</code>; putting a model in .env is no
              longer how persistence works.
            </p>

            <h2>Fastest path by goal</h2>
            <table>
              <thead>
                <tr><th>I want</th><th>Do this</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>I already pay for ChatGPT Plus</td>
                  <td>Run <code>geode setup</code>. It detects <code>~/.codex/auth.json</code> before asking for API keys.</td>
                </tr>
                <tr>
                  <td>I want to use my Claude subscription</td>
                  <td>Run <code>/login anthropic</code> inside <code>geode</code>.</td>
                </tr>
                <tr>
                  <td>I want per-token cost control with API keys</td>
                  <td>Put keys in <code>~/.geode/.env</code> and set budgets in <a href="/geode/docs/ops/cost">Cost monitoring</a>.</td>
                </tr>
                <tr>
                  <td>I want a near-free trial first</td>
                  <td>Register a GLM key (<code>ZAI_API_KEY</code>) and pick <code>glm-4.7-flash</code> in <code>/model</code>.</td>
                </tr>
                <tr>
                  <td>I want to force a provider onto keys instead of OAuth</td>
                  <td><code>/login source &lt;provider&gt; api_key</code>. The choice persists in <code>config.toml</code> only.</td>
                </tr>
                <tr>
                  <td>I want to see what is wired up right now</td>
                  <td><code>geode about</code>. Effective model, provider, and credential profile count on one screen.</td>
                </tr>
              </tbody>
            </table>

            <h2>Credential source values</h2>
            <p>
              Each provider’s credential source is one of four values from
              <code>core/config/credential_source.py</code>.
            </p>
            <table>
              <thead>
                <tr><th>Value</th><th>Meaning</th></tr>
              </thead>
              <tbody>
                <tr><td><code>auto</code></td><td>Default. Tries OAuth first; falling through to PAYG is gated by configuration.</td></tr>
                <tr><td><code>api_key</code></td><td>PAYG API key only.</td></tr>
                <tr><td><code>claude-cli</code></td><td>Anthropic subscription OAuth via the claude CLI.</td></tr>
                <tr><td><code>openai-codex</code></td><td>ChatGPT subscription OAuth via the Codex CLI.</td></tr>
              </tbody>
            </table>

            <h2>Example</h2>
            <pre>{`geode setup              # credential detection + setup wizard
geode                    # start chatting

> /login                 # credentials dashboard
> /login openai          # ChatGPT subscription OAuth
> /login anthropic       # Claude subscription OAuth
> /login source openai api_key   # pin OpenAI to the key lane

geode about              # effective model + credential state`}</pre>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>setup does not find ChatGPT OAuth</td>
                  <td>No <code>~/.codex/auth.json</code></td>
                  <td>Log in with the Codex CLI first, or use the <code>/login openai</code> device-code flow. The latter stores into <code>~/.geode/auth.toml</code>.</td>
                </tr>
                <tr>
                  <td>Added a key but the model did not change</td>
                  <td>.env holds secrets only; the model is a separate setting</td>
                  <td>Pick the model in <code>/model</code>. If it still will not move, run <code>geode config explain model</code> to see which layer wins.</td>
                </tr>
                <tr>
                  <td>GLM subscription, yet metered billing</td>
                  <td>A Coding Plan key went out over the PAYG endpoint</td>
                  <td>GLM has separate Coding Plan and PAYG endpoints. See the GLM section in <a href="/geode/docs/run/providers">Configure providers</a>.</td>
                </tr>
                <tr>
                  <td>Empty replies or 401</td>
                  <td>Expired OAuth or invalid key</td>
                  <td>Check with <code>geode doctor</code>, refresh with <code>/login</code>.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/run/providers">Configure providers</a>. Routing, model precedence, fallback policy.</li>
              <li><a href="/geode/docs/config/basics">Configuration basics</a>. Config layers and resolution order.</li>
              <li><a href="/geode/docs/runtime/auth">Auth and OAuth</a>. Profile rotation and cooldown.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
