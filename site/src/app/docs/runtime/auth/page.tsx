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
                <tr><td><code>/login google</code></td><td>Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts용 Google Workspace OAuth. 사용자가 만든 Desktop 앱 클라이언트를 가져오며 LLM 프로바이더 자격과 분리됩니다.</td></tr>
                <tr><td><code>/login add</code></td><td>자격 추가. 키 모양(<code>sk-ant-</code>, <code>sk-proj-</code>, GLM {`{id}.{secret}`})으로 프로바이더를 추정합니다.</td></tr>
                <tr><td><code>/login use</code> / <code>remove</code></td><td>프로파일 선택과 제거.</td></tr>
                <tr><td><code>/login route</code></td><td>프로바이더와 플랜 라우팅 확인.</td></tr>
                <tr><td><code>/login quota</code></td><td>구독 쿼터 상태.</td></tr>
                <tr><td><code>/login source &lt;provider&gt; &lt;type&gt;</code></td><td>자격 소스 영속화. config.toml <code>[llm]</code>에 기록.</td></tr>
              </tbody>
            </table>

            <h2>Google Workspace</h2>
            <p>
              uv나 GitHub에서 설치한 사용자도 중앙 GEODE OAuth 앱 없이 자신의
              Google Cloud Desktop 클라이언트로 연결할 수 있습니다. 권장 진입점은
              <code>/login google</code>입니다. 첫 연결에서는 client JSON 경로와
              필요한 서비스 번들을 명시적으로 고릅니다. 자동화하려면 다음처럼
              한 줄로 지정할 수 있습니다.
            </p>
            <pre>{`/login google --client-json ~/Downloads/client_secret.json \\
  --services gmail-send,calendar-read,workspace-files

/login google services
/login google status
/login google use user@example.com
/login google --new-account --services calendar-read
/login google --services calendar-read --replace-services
/login google logout user@example.com`}</pre>
            <p>
              인증은 시스템 브라우저, 임의의 <code>127.0.0.1</code> 포트,
              Authorization Code + PKCE S256 + state 검증을 씁니다. Google이
              Desktop 앱의 incremental auth를 지원하지 않으므로 서비스를 더할
              때는 대상 활성 계정의 기존 번들과 새 번들의 합집합으로 재동의합니다.
              브라우저에서 다른 계정을 고르면 저장하지 않고 실패하며, 두 번째
              계정은 <code>--new-account</code>로 연결합니다.
              권한을 줄일 때는 유지할 전체 번들과 <code>--replace-services</code>를
              함께 지정합니다.
              <code>gmail-read</code>는 Restricted scope라 기본 권장 묶음에
              포함되지 않습니다. Drive·Docs·Sheets는 전체 Drive 대신
              non-sensitive <code>drive.file</code>로 GEODE가 만들거나 파일별로
              허용된 항목만 다룹니다.
            </p>
            <table>
              <thead><tr><th>저장소</th><th>내용</th></tr></thead>
              <tbody>
                <tr><td>OS keyring<br/><code>geode.google.oauth</code></td><td>refresh token, client secret, 계정 이메일과 표시 이름. 안전한 백엔드가 없으면 로그인은 실패하며 평문 fallback은 없습니다.</td></tr>
                <tr><td><code>~/.geode/google/accounts.json</code></td><td>schema version, 단조 증가 revision, 활성 account id, client/project id, 서비스 번들, 실제 granted scopes, 상태와 시각만. 프로세스 간 <code>.accounts.lock</code> 뒤 atomic write, 디렉터리 0700·파일 0600.</td></tr>
                <tr><td>프로세스 메모리</td><td>짧은 수명의 access token과 expiry. 데몬 auth reload와 logout 때 폐기.</td></tr>
                <tr><td>세션 영속 저장소</td><td>Workspace 도구의 원문 입력·결과는 JSON·SQLite·도구 로그에 저장하지 않고 호출 ID가 붙은 <code>_personal_data_omitted</code> 표식으로 치환합니다. API 오류 상세도 영속 telemetry·회전 로그에서 생략하고, 개인 도구가 포함된 batch는 별도 reflection provider 호출을 건너뜁니다. 사용자가 직접 쓴 대화문과 모델이 대화문으로 작성한 요약은 일반 세션 보존 정책을 따릅니다.</td></tr>
              </tbody>
            </table>
            <p>
              Workspace 읽기 결과는 선택한 LLM 프로바이더로 전달될 수 있으므로
              매 도구 호출 직전에 개인 데이터 disclosure와 affirmative consent가
              뜹니다. 이 승인은 always-allow할 수 없고 headless·서브에이전트에서는
              닫힌 채로 거부됩니다. Gmail 전송과 Drive/Docs/Sheets/Tasks/Calendar
              변경도 같은 비캐시형 매 호출 승인을 거쳐 HITL 0·권한 건너뛰기로
              우회할 수 없습니다. 자세한 스키마와 Hermes 비교는 설계 기록
              <code>docs/architecture/google-workspace-oauth.md</code>에 있습니다.
            </p>

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
                <tr><td><code>/login google</code></td><td>Google Workspace OAuth for Gmail, Calendar, Drive, Docs, Sheets, Tasks, and Contacts. Imports a user-owned Desktop app client and stays separate from LLM-provider credentials.</td></tr>
                <tr><td><code>/login add</code></td><td>Add a credential. The provider is sniffed from the key shape (<code>sk-ant-</code>, <code>sk-proj-</code>, GLM {`{id}.{secret}`}).</td></tr>
                <tr><td><code>/login use</code> / <code>remove</code></td><td>Select and remove profiles.</td></tr>
                <tr><td><code>/login route</code></td><td>Inspect provider and plan routing.</td></tr>
                <tr><td><code>/login quota</code></td><td>Subscription quota state.</td></tr>
                <tr><td><code>/login source &lt;provider&gt; &lt;type&gt;</code></td><td>Persist the credential source into config.toml <code>[llm]</code>.</td></tr>
              </tbody>
            </table>

            <h2>Google Workspace</h2>
            <p>
              Users installing from uv or GitHub can connect with their own
              Google Cloud Desktop client; GEODE does not need a central OAuth
              app. The recommended entry point is <code>/login google</code>.
              On the first connection it explicitly asks for the client JSON
              path and the service bundles needed. For a scripted choice:
            </p>
            <pre>{`/login google --client-json ~/Downloads/client_secret.json \\
  --services gmail-send,calendar-read,workspace-files

/login google services
/login google status
/login google use user@example.com
/login google --new-account --services calendar-read
/login google --services calendar-read --replace-services
/login google logout user@example.com`}</pre>
            <p>
              Authentication uses the system browser, a random
              <code>127.0.0.1</code> port, Authorization Code + PKCE S256, and
              state validation. Google does not support incremental auth for
              Desktop apps, so adding a service reauthorizes the union of old
              and new bundles for the targeted active account. GEODE refuses
              to save a different browser identity; connect a second identity
              with <code>--new-account</code>. To narrow a grant, provide the
              complete bundle set to keep together with
              <code>--replace-services</code>.
              <code>gmail-read</code> is a Restricted scope and
              is excluded from the recommended set. Drive, Docs, and Sheets use
              the non-sensitive <code>drive.file</code> scope instead of whole-
              Drive access, limiting GEODE to files it creates or that are
              individually granted to the app.
            </p>
            <table>
              <thead><tr><th>Store</th><th>Contents</th></tr></thead>
              <tbody>
                <tr><td>OS keyring<br/><code>geode.google.oauth</code></td><td>Refresh token, client secret, account email, and display name. Login fails when no secure backend exists; there is no plaintext fallback.</td></tr>
                <tr><td><code>~/.geode/google/accounts.json</code></td><td>Schema version, monotonic revision, active account id, client/project ids, service bundles, actual granted scopes, status, and timestamps only. Atomic write behind a cross-process <code>.accounts.lock</code>; directory 0700 and file 0600.</td></tr>
                <tr><td>Process memory</td><td>Short-lived access token and expiry, cleared on daemon auth reload and logout.</td></tr>
                <tr><td>Durable session stores</td><td>Raw Workspace tool inputs and results are replaced in JSON, SQLite, and tool logs by a call-linked <code>_personal_data_omitted</code> marker. API error details are also omitted from durable telemetry and rotating logs, and batches containing a personal tool skip any separate reflection provider. User-authored conversation text and assistant summaries written as ordinary conversation follow the general session-retention policy.</td></tr>
              </tbody>
            </table>
            <p>
              Because Workspace read results may be sent to the selected LLM
              provider, every read invocation is immediately preceded by a
              personal-data disclosure and affirmative consent. It cannot be
              always-allowed and fails closed in headless and sub-agent
              sessions. Gmail sends and Drive/Docs/Sheets/Tasks/Calendar
              mutations use the same non-cacheable per-invocation gate; HITL 0
              and skip-permissions cannot bypass it. The full schema and Hermes
              comparison are in the architecture record
              <code>docs/architecture/google-workspace-oauth.md</code>.
            </p>

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
