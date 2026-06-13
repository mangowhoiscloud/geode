import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Auth and OAuth — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/auth"
      title="Auth and OAuth"
      titleKo="인증과 OAuth"
      summary="Credential sources, OAuth profiles behind /login, the Codex token detection, and where API keys live."
      summaryKo="자격 소스, /login 뒤의 OAuth 프로파일, Codex 토큰 감지, API 키가 사는 곳을 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 프로바이더마다 두 종류의 자격을 받습니다. 구독
              OAuth와 PAYG API 키입니다. 어느 쪽을 쓸지는
              <code>CredentialSource</code> 하나로 표현되고, 프로파일과 플랜은
              <code>~/.geode/auth.toml</code>에, API 키는
              <code>~/.geode/.env</code>에 저장됩니다.
            </p>

            <h2>자격 소스</h2>
            <p>
              단일 SoT는 <code>core/config/credential_source.py</code>의
              <code>CredentialSource</code> StrEnum입니다.
            </p>
            <table>
              <thead>
                <tr><th>값</th><th>의미</th></tr>
              </thead>
              <tbody>
                <tr><td><code>auto</code></td><td>매니페스트 순서 해석. OAuth 우선, PAYG는 <code>fallback_to_payg</code>가 켜진 경우에만.</td></tr>
                <tr><td><code>api_key</code></td><td>PAYG API 키.</td></tr>
                <tr><td><code>claude-cli</code></td><td>claude CLI 구독을 통한 Anthropic OAuth.</td></tr>
                <tr><td><code>openai-codex</code></td><td>Codex CLI를 통한 ChatGPT 구독 OAuth.</td></tr>
                <tr><td><code>oauth</code></td><td>레거시 별칭. Settings 검증이 받아줍니다.</td></tr>
                <tr><td><code>none</code></td><td>해당 프로바이더 비활성 센티널.</td></tr>
              </tbody>
            </table>
            <p>
              선택은 <code>[llm] anthropic_credential_source</code> /
              <code>openai_credential_source</code>(기본 <code>auto</code>)에
              저장됩니다. <code>/login source &lt;provider&gt; &lt;type&gt;</code>은
              toml에만 쓰므로 <code>.env</code>를 지워도 선택이 살아남습니다.
              (provider, source) 쌍마다 구체 어댑터가 하나씩 레지스트리에
              등록됩니다(<code>core/llm/adapters/</code>의
              <code>anthropic_payg</code>, <code>anthropic_oauth</code>,
              <code>claude_cli</code>, <code>openai_payg</code>,
              <code>codex_oauth</code>, <code>codex_cli</code>,
              <code>glm_coding_plan</code>, <code>glm_payg</code>).
            </p>

            <h2>/login 대시보드</h2>
            <p>
              세션 안의 <code>/login</code>은 플랜과 자격을 한 화면에서
              관리합니다(<code>core/cli/commands/login.py</code>). thin
              CLI에서 로컬로 실행되고, 끝나면 데몬에 인증 상태 리로드를
              알립니다.
            </p>
            <table>
              <thead>
                <tr><th>서브커맨드</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr><td><code>/login openai</code></td><td>ChatGPT 구독 OAuth 로그인. device-code 플로우는 <code>core/auth/oauth_login.py</code>이고, 결과는 <code>auth.toml</code>에 OAUTH_BORROWED 플랜 + 프로파일 쌍으로 저장됩니다.</td></tr>
                <tr><td><code>/login anthropic</code></td><td>Claude 구독 OAuth. macOS 키체인의 <code>&quot;Claude Code-credentials&quot;</code> 항목을 읽습니다(routing.toml <code>[credentials.keychain]</code>, override는 <code>GEODE_ANTHROPIC_KEYCHAIN_SERVICE</code>).</td></tr>
                <tr><td><code>/login add</code></td><td>자격 추가. 키 모양(<code>sk-ant-</code>, <code>sk-proj-</code>, GLM {`{id}.{secret}`})으로 프로바이더를 추정합니다.</td></tr>
                <tr><td><code>/login use</code> / <code>remove</code></td><td>프로파일 선택과 제거.</td></tr>
                <tr><td><code>/login route</code></td><td>프로바이더와 플랜 라우팅 확인.</td></tr>
                <tr><td><code>/login quota</code></td><td>구독 쿼터 상태.</td></tr>
                <tr><td><code>/login source &lt;provider&gt; &lt;type&gt;</code></td><td>자격 소스 영속화. config.toml <code>[llm]</code>에 기록.</td></tr>
              </tbody>
            </table>

            <h2>Codex 토큰 감지</h2>
            <p>
              ChatGPT Plus 구독 OAuth는 Codex CLI의 토큰 저장소
              <code>~/.codex/auth.json</code>을 읽습니다
              (<code>core/auth/codex_cli_oauth.py</code>). 토큰 수명은 Codex
              CLI가 책임집니다. GEODE는 복사본을 영속화하지 않고 읽기만
              하며, JWT exp로 만료를 판별합니다.
              <code>geode setup</code>도 API 키를 묻기 전에 이 파일을 먼저
              감지합니다.
            </p>

            <h2>PAYG 키</h2>
            <p>
              API 키는 시크릿이므로 <code>~/.geode/.env</code> 층에 삽니다.
              온보딩과 <code>/login</code>의 키 기록이 이 계약을 따릅니다
              (<code>core/config/env_io.py</code>의 <code>upsert_env</code>).
            </p>
            <pre>{`# ~/.geode/.env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
ZAI_API_KEY={id}.{secret}`}</pre>
            <p>
              GLM은 엔드포인트가 둘입니다. Coding Plan(구독 과금)과
              PAYG(종량 과금)이고, Coding Plan 키를 PAYG 경로에 쓰면 구독
              쿼터를 조용히 우회해 종량 과금됩니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>응답이 비거나 401</td>
                  <td>토큰 만료 또는 키 무효</td>
                  <td><code>geode doctor</code>로 자격 상태를 보고 <code>/login</code>으로 갱신합니다. Codex 쪽은 <code>codex login</code>을 다시 실행합니다.</td>
                </tr>
                <tr>
                  <td>소스를 바꿨는데 그대로</td>
                  <td>구버전의 <code>GEODE_*_CREDENTIAL_SOURCE</code> env 줄이 마스크</td>
                  <td><code>geode config explain anthropic_credential_source</code>로 WINNER 층을 확인하고 그 줄을 지웁니다.</td>
                </tr>
                <tr>
                  <td>서브프로세스에서 <code>AdapterNotFoundError</code></td>
                  <td>어댑터 레지스트리는 프로세스 단위인데 부트스트랩 누락</td>
                  <td>워커가 <code>core.llm.adapters.registry.bootstrap_builtins()</code>를 호출하는지 확인합니다.</td>
                </tr>
                <tr>
                  <td>구독이 있는데 PAYG로 과금</td>
                  <td><code>auto</code>가 OAuth를 못 찾고 키로 해석</td>
                  <td><code>/login route</code>와 <code>/login quota</code>로 플랜 상태를 확인하고, 필요하면 소스를 <code>claude-cli</code>/<code>openai-codex</code>로 고정합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/ops/oauth">OAuth 토큰 회전</a>. 갱신과 쿨다운의 런타임 동작.</li>
              <li><a href="/geode/docs/run/providers">프로바이더 설정</a>. 처음 자격을 붙이는 절차.</li>
              <li><a href="/geode/docs/config/basics">설정 기초</a>. 시크릿 층과 해석 사다리.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE accepts two kinds of credentials per provider:
              subscription OAuth and PAYG API keys. The choice is expressed by
              a single <code>CredentialSource</code>; plans and profiles
              persist in <code>~/.geode/auth.toml</code>, API keys in
              <code>~/.geode/.env</code>.
            </p>

            <h2>Credential sources</h2>
            <p>
              The single SoT is the <code>CredentialSource</code> StrEnum in
              <code>core/config/credential_source.py</code>.
            </p>
            <table>
              <thead>
                <tr><th>Value</th><th>Meaning</th></tr>
              </thead>
              <tbody>
                <tr><td><code>auto</code></td><td>Manifest-order resolution. OAuth first; PAYG only when <code>fallback_to_payg</code> allows.</td></tr>
                <tr><td><code>api_key</code></td><td>PAYG API key.</td></tr>
                <tr><td><code>claude-cli</code></td><td>Anthropic OAuth via the claude CLI subscription.</td></tr>
                <tr><td><code>openai-codex</code></td><td>ChatGPT subscription OAuth via the Codex CLI.</td></tr>
                <tr><td><code>oauth</code></td><td>Legacy alias, accepted by Settings validation.</td></tr>
                <tr><td><code>none</code></td><td>Disable sentinel for the provider.</td></tr>
              </tbody>
            </table>
            <p>
              The choice persists as <code>[llm]
              anthropic_credential_source</code> /
              <code>openai_credential_source</code> (default
              <code>auto</code>). <code>/login source &lt;provider&gt;
              &lt;type&gt;</code> writes toml only, so the choice survives a
              <code>.env</code> wipe. Each (provider, source) pair maps to one
              concrete adapter in the registry
              (<code>core/llm/adapters/</code>: <code>anthropic_payg</code>,
              <code>anthropic_oauth</code>, <code>claude_cli</code>,
              <code>openai_payg</code>, <code>codex_oauth</code>,
              <code>codex_cli</code>, <code>glm_coding_plan</code>,
              <code>glm_payg</code>).
            </p>

            <h2>The /login dashboard</h2>
            <p>
              In-session <code>/login</code> manages plans and credentials on
              one screen (<code>core/cli/commands/login.py</code>). It runs
              locally in the thin CLI and notifies the daemon to reload auth
              state when it finishes.
            </p>
            <table>
              <thead>
                <tr><th>Subcommand</th><th>Behavior</th></tr>
              </thead>
              <tbody>
                <tr><td><code>/login openai</code></td><td>ChatGPT subscription OAuth login. The device-code flow lives in <code>core/auth/oauth_login.py</code>; the result lands in <code>auth.toml</code> as an OAUTH_BORROWED plan plus profile pair.</td></tr>
                <tr><td><code>/login anthropic</code></td><td>Claude subscription OAuth. Reads the macOS keychain entry <code>&quot;Claude Code-credentials&quot;</code> (routing.toml <code>[credentials.keychain]</code>; override with <code>GEODE_ANTHROPIC_KEYCHAIN_SERVICE</code>).</td></tr>
                <tr><td><code>/login add</code></td><td>Add a credential. The provider is sniffed from the key shape (<code>sk-ant-</code>, <code>sk-proj-</code>, GLM {`{id}.{secret}`}).</td></tr>
                <tr><td><code>/login use</code> / <code>remove</code></td><td>Select and remove profiles.</td></tr>
                <tr><td><code>/login route</code></td><td>Inspect provider and plan routing.</td></tr>
                <tr><td><code>/login quota</code></td><td>Subscription quota state.</td></tr>
                <tr><td><code>/login source &lt;provider&gt; &lt;type&gt;</code></td><td>Persist the credential source into config.toml <code>[llm]</code>.</td></tr>
              </tbody>
            </table>

            <h2>Codex token detection</h2>
            <p>
              ChatGPT Plus subscription OAuth reads the Codex CLI&apos;s token
              store at <code>~/.codex/auth.json</code>
              (<code>core/auth/codex_cli_oauth.py</code>). This is managed
              credential reuse: Codex CLI owns the token lifecycle; GEODE
              reads without persisting copies and decodes the JWT exp for
              expiry. <code>geode setup</code> also detects this file before
              asking for any API key.
            </p>

            <h2>PAYG keys</h2>
            <p>
              API keys are secrets, so they live on the
              <code>~/.geode/.env</code> layer. Onboarding and
              <code>/login</code> key writes follow this contract
              (<code>upsert_env</code> in <code>core/config/env_io.py</code>).
            </p>
            <pre>{`# ~/.geode/.env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
ZAI_API_KEY={id}.{secret}`}</pre>
            <p>
              GLM has two endpoints: Coding Plan (subscription-billed) and
              PAYG (metered). A Coding Plan key pointed at the PAYG path
              silently bypasses the subscription quota and bills metered.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Empty replies or 401</td>
                  <td>Expired token or invalid key</td>
                  <td>Check credentials with <code>geode doctor</code>, refresh with <code>/login</code>. For Codex, rerun <code>codex login</code>.</td>
                </tr>
                <tr>
                  <td>Source switch does not stick</td>
                  <td>An old <code>GEODE_*_CREDENTIAL_SOURCE</code> env line masks the toml</td>
                  <td>Run <code>geode config explain anthropic_credential_source</code>, find the WINNER layer, remove the line.</td>
                </tr>
                <tr>
                  <td><code>AdapterNotFoundError</code> in a subprocess</td>
                  <td>The adapter registry is per-process and bootstrap was skipped</td>
                  <td>Make sure the worker calls <code>core.llm.adapters.registry.bootstrap_builtins()</code>.</td>
                </tr>
                <tr>
                  <td>Billed PAYG despite a subscription</td>
                  <td><code>auto</code> resolved to a key because OAuth was not found</td>
                  <td>Inspect <code>/login route</code> and <code>/login quota</code>; pin the source to <code>claude-cli</code> or <code>openai-codex</code> if needed.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/ops/oauth">OAuth token rotation</a>. The runtime behavior of refresh and cooldown.</li>
              <li><a href="/geode/docs/run/providers">Configure providers</a>. First-time credential setup.</li>
              <li><a href="/geode/docs/config/basics">Configuration basics</a>. The secrets layer and the resolution ladder.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
