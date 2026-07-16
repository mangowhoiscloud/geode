import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Connect Google Workspace — GEODE Docs" };

const APIS = [
  ["Gmail 읽기·전송", "Read or send Gmail", "Gmail API"],
  ["Calendar 일정 조회·생성·스케줄러 동기화", "List and create Calendar events; sync the scheduler", "Google Calendar API"],
  ["Drive·Docs·Sheets", "Drive, Docs, and Sheets", "Google Drive API, Google Docs API, Google Sheets API"],
  ["Tasks", "Tasks", "Google Tasks API"],
  ["Contacts", "Contacts", "People API"],
] as const;

const BUNDLES = [
  ["gmail-send", "메일함을 읽지 않고 메일 전송", "Send mail without reading the mailbox", "Sensitive"],
  ["gmail-read", "Gmail 검색·읽기", "Search and read Gmail", "Restricted"],
  ["calendar-read", "계정 소유 캘린더의 일정 읽기", "Read events on calendars owned by the account", "Sensitive"],
  ["calendar-write", "일정 조회·생성과 GEODE 스케줄러 동기화. v1.0.0에는 임의 일정 수정·삭제 도구가 없음", "List and create events, plus GEODE scheduler sync. v1.0.0 has no general event update or delete tool", "Sensitive"],
  ["workspace-files", "GEODE가 만든 Drive·Docs·Sheets 파일. v1.0.0에는 기존 파일용 Google Picker가 없음", "Drive, Docs, and Sheets files created through GEODE. v1.0.0 does not ship a Google Picker for existing files", "Non-sensitive"],
  ["tasks-read", "Google Tasks 읽기", "Read Google Tasks", "Sensitive"],
  ["tasks-write", "Google Tasks 읽기·변경", "Read and change Google Tasks", "Sensitive"],
  ["contacts-read", "People API로 Contacts 읽기", "Read Contacts through the People API", "Sensitive"],
] as const;

const STORAGE = [
  [
    "OS keyring · geode.google.oauth",
    "client secret, refresh token, 계정 이메일, 표시 이름",
    "Client secret, refresh token, account email, display name",
    "메일·일정·파일·태스크·연락처 내용",
    "Mail, event, file, task, or contact content",
  ],
  [
    "~/.geode/google/accounts.json",
    "schema version, 단조 증가 revision, 활성 account id, client/project id, 번들, 실제 승인 scope, secret_ref, 상태·시각",
    "Schema version, monotonic revision, active account id, client/project ids, bundles, actual granted scopes, secret_ref, status, timestamps",
    "토큰, client secret, 이메일, 표시 이름, Workspace 내용",
    "Tokens, client secret, email, display name, Workspace content",
  ],
  [
    "Process memory",
    "짧은 수명의 access token과 expiry",
    "Short-lived access token and expiry",
    "데몬 auth reload와 logout 뒤에는 유지하지 않음",
    "Nothing retained after daemon auth reload or logout",
  ],
  [
    "Durable session/tool stores · SQLite",
    "도구 이름을 담은 _personal_data_omitted 표식. 바깥 호출 행은 call id를 유지",
    "A _personal_data_omitted marker carrying the tool name; the enclosing call row retains the call id",
    "Workspace 도구의 원문 입력·결과",
    "Raw Workspace tool inputs and results",
  ],
] as const;

const PROBLEMS = [
  [
    "access_denied 또는 앱 접근 불가",
    "access_denied or app access blocked",
    "External Testing이라면 로그인 계정을 test user에 추가하고 Audience를 확인합니다.",
    "For External Testing, add the signing-in account as a test user and check Audience.",
  ],
  [
    "약 7일마다 다시 로그인해야 함",
    "You must sign in again about every seven days",
    "External Testing 토큰 수명입니다. 개인 장기 사용이면 정책을 검토한 뒤 In production 전환을 고려합니다.",
    "This is the External Testing token lifetime. For durable personal use, review policy and consider In production.",
  ],
  [
    "API가 비활성이라는 403",
    "403 says an API is disabled",
    "오류에 나온 Gmail, Calendar, Drive, Docs, Sheets, Tasks, People API를 같은 Cloud 프로젝트에서 활성화합니다.",
    "Enable the named Gmail, Calendar, Drive, Docs, Sheets, Tasks, or People API in the same Cloud project.",
  ],
  [
    "필요한 번들이 없다는 안내",
    "GEODE reports a missing bundle",
    "/login google --services <bundle>로 기존 번들에 추가합니다.",
    "Add it with /login google --services <bundle>.",
  ],
  [
    "다른 계정이라는 오류",
    "GEODE reports a different account",
    "현재 계정으로 다시 동의하거나 --new-account를 사용합니다.",
    "Consent with the active identity or use --new-account.",
  ],
  [
    "secure keyring이 없다는 오류",
    "No secure keyring is available",
    "운영체제 자격 저장소를 활성화합니다. 평문 fallback은 지원하지 않습니다.",
    "Enable the OS credential vault. Plaintext fallback is intentionally unsupported.",
  ],
] as const;

function ApiTable({ english = false }: { english?: boolean }) {
  return (
    <table>
      <thead><tr><th>{english ? "GEODE feature" : "GEODE 기능"}</th><th>{english ? "APIs to enable" : "활성화할 API"}</th></tr></thead>
      <tbody>
        {APIS.map(([ko, en, apis]) => <tr key={apis}><td>{english ? en : ko}</td><td>{apis}</td></tr>)}
      </tbody>
    </table>
  );
}

function BundleTable({ english = false }: { english?: boolean }) {
  return (
    <table>
      <thead><tr><th>{english ? "Bundle" : "번들"}</th><th>{english ? "Access and tool surface" : "권한과 도구 표면"}</th><th>{english ? "Class" : "분류"}</th></tr></thead>
      <tbody>
        {BUNDLES.map(([bundle, ko, en, risk]) => (
          <tr key={bundle}><td><code>{bundle}</code></td><td>{english ? en : ko}</td><td>{risk}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function StorageTable({ english = false }: { english?: boolean }) {
  return (
    <table>
      <thead><tr><th>{english ? "Layer" : "층"}</th><th>{english ? "Stored" : "저장 정보"}</th><th>{english ? "Never stored there" : "저장하지 않는 정보"}</th></tr></thead>
      <tbody>
        {STORAGE.map(([layer, storedKo, storedEn, omittedKo, omittedEn]) => (
          <tr key={layer}><td><code>{layer}</code></td><td>{english ? storedEn : storedKo}</td><td>{english ? omittedEn : omittedKo}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function ProblemTable({ english = false }: { english?: boolean }) {
  return (
    <table>
      <thead><tr><th>{english ? "Symptom" : "증상"}</th><th>{english ? "Fix" : "해법"}</th></tr></thead>
      <tbody>
        {PROBLEMS.map(([symptomKo, symptomEn, fixKo, fixEn]) => (
          <tr key={symptomEn}><td>{english ? symptomEn : symptomKo}</td><td>{english ? fixEn : fixKo}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Page() {
  return (
    <DocsShell
      slug="run/google-workspace"
      title="Connect Google Workspace"
      titleKo="Google Workspace 연결"
      summary="Create your own Google Desktop OAuth client, connect it with /login google, and understand the scope, storage, and consent boundaries."
      summaryKo="직접 만든 Google Desktop OAuth 클라이언트를 /login google로 연결하고 권한, 저장소, 동의 경계를 확인합니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE v1.0.0부터 uv나 GitHub로 설치한 사용자도 중앙 GEODE OAuth 앱
              없이 자신의 Google Cloud 프로젝트로 Gmail, Calendar, Drive, Docs,
              Sheets, Tasks, Contacts를 연결할 수 있습니다. 권장 진입점은 대화형
              GEODE 화면의 <code>/login google</code>입니다.
            </p>
            <p>
              이 가이드는 개인용 Desktop OAuth 클라이언트를 만드는 최소 경로를
              설명합니다. Google Workspace 조직에서 운영하거나 다른 사용자에게
              공개할 앱이라면 조직 관리자 정책과 Google의 검증 요구사항도 함께
              적용됩니다.
            </p>

            <h2>시작 전에</h2>
            <ul>
              <li>GEODE v1.0.0 이상과 대화형 로컬 터미널</li>
              <li>Google 계정과 직접 관리할 Google Cloud 프로젝트</li>
              <li>macOS Keychain, Windows Credential Locker, Linux Secret Service 중 하나</li>
            </ul>
            <p>
              안전한 OS 키링을 사용할 수 없으면 GEODE는 로그인을 거부합니다.
              refresh token이나 client secret을 평문 파일로 대신 저장하지 않습니다.
            </p>

            <h2>1. 필요한 API 활성화</h2>
            <p>
              Google Cloud 콘솔의 <strong>APIs &amp; Services → Library</strong>에서
              사용할 서비스에 해당하는 API만 활성화합니다. Google의 공식{" "}
              <a href="https://developers.google.com/workspace/guides/enable-apis?hl=ko">API 활성화 가이드</a>도
              같은 순서를 안내합니다.
            </p>
            <ApiTable />

            <h2>2. 동의 화면 구성</h2>
            <p>
              Google Auth platform의 <strong>Branding</strong>,{" "}
              <strong>Audience</strong>, <strong>Data Access</strong>를 채웁니다.
              처음 시험할 때는 Audience를 External의 Testing으로 두고 자신의
              계정을 test user로 추가하는 것이 가장 빠릅니다. 자세한 필드는{" "}
              <a href="https://developers.google.com/workspace/guides/configure-oauth-consent?hl=ko">OAuth 동의 화면 구성</a>을
              따릅니다.
            </p>
            <ul>
              <li><strong>Internal</strong>: Workspace 조직 내부 사용자 전용. 조직 관리자 정책을 따릅니다.</li>
              <li><strong>External · Testing</strong>: 첫 시험에 적합합니다. test user가 필요하고, 기본 프로필 범위를 넘는 승인의 refresh token은 7일 뒤 만료될 수 있습니다.</li>
              <li><strong>External · In production</strong>: 지속 사용 또는 배포용입니다. 개인적으로 아는 100명 미만만 쓰는 앱은 검증 예외 대상이 될 수 있지만, 미검증 경고와 사용자 상한·정책은 그대로 적용됩니다.</li>
            </ul>
            <p>
              정확한 수명 조건은 Google의{" "}
              <a href="https://support.google.com/cloud/answer/15549945?hl=ko">OAuth 앱 게시 상태 도움말</a>,
              개인용 예외 조건은{" "}
              <a href="https://support.google.com/cloud/answer/13464323?hl=ko">앱 검증 요구사항</a>을
              기준으로 확인하십시오.
            </p>
            <p>
              Gmail 읽기의 <code>gmail.readonly</code>는 Restricted scope입니다.
              여러 사람에게 배포하거나 조직 데이터에 접근하면 Google의 앱 검증,
              제한 범위 검토, 보안 평가 요건을 별도로 확인하십시오. 개인용 BYO
              클라이언트라는 사실이 Google API 정책을 없애지는 않습니다.
            </p>

            <h2>3. Desktop 앱 자격 만들기</h2>
            <ol>
              <li>Google Auth platform의 <strong>Clients</strong>로 이동합니다.</li>
              <li><strong>Create client</strong>를 누르고 Application type을 <strong>Desktop app</strong>으로 고릅니다.</li>
              <li>생성 후 JSON을 내려받아 로컬의 안전한 경로에 둡니다.</li>
            </ol>
            <p>
              Web application 자격이나 OOB 복사·붙여넣기 흐름은 사용하지
              않습니다. GEODE는 Google의{" "}
              <a href="https://developers.google.com/identity/protocols/oauth2/native-app">Desktop 앱 OAuth 지침</a>에
              맞춰 시스템 브라우저, 임의의 <code>127.0.0.1</code> 포트, PKCE
              S256, <code>state</code> 검증을 사용합니다. 자격 생성 화면의 세부
              순서는{" "}
              <a href="https://developers.google.com/workspace/guides/create-credentials?hl=ko">Google Workspace 자격 만들기</a>를
              참고하십시오.
            </p>

            <h2>4. GEODE에서 연결</h2>
            <p>
              셸 명령이 아니라 <code>geode</code> 대화형 화면 안에서 실행합니다.
              인자 없는 명령은 JSON 경로와 서비스 선택을 차례로 묻습니다.
            </p>
            <pre>{`geode

> /login google

# 또는 한 번에 한 줄로 지정
> /login google --client-json ~/Downloads/client_secret.json --services gmail-send,calendar-read,workspace-files`}</pre>
            <p>
              <code>recommended</code> 선택은{" "}
              <code>gmail-send,calendar-read,workspace-files</code>입니다. Gmail
              읽기처럼 더 강한 권한은 필요할 때만 별도로 추가하십시오.
            </p>
            <BundleTable />
            <p>
              <code>workspace-files</code>는 전체 Drive 범위가 아니라{" "}
              <code>drive.file</code>을 사용합니다. v1.0.0의 지원 경로는 GEODE가
              만든 파일입니다. 이 scope 자체는 Picker로 사용자가 연 파일도 다룰
              수 있지만, GEODE v1.0.0은 기존 파일을 고르는 Google Picker를
              제공하지 않습니다.
            </p>

            <h2>5. 상태 확인과 계정 관리</h2>
            <pre>{`/login google services
/login google status
/login google use user@example.com
/login google --new-account --services calendar-read
/login google --services calendar-write,tasks-write --replace-services
/login google logout user@example.com`}</pre>
            <p>
              기존 계정에 번들을 추가하면 설치형 앱의 제약 때문에 기존 번들과 새
              번들의 합집합으로 다시 동의합니다. 권한을 줄이려면 남길 전체 번들을
              <code>--replace-services</code>와 함께 지정합니다. 브라우저에서 다른
              Google 계정을 선택하면 GEODE는 저장하지 않고 중단합니다. 두 번째
              계정은 <code>--new-account</code>로 시작하십시오.
            </p>

            <h2>정보가 저장되는 위치</h2>
            <StorageTable />
            <p>
              메타데이터 레지스트리는 0700 디렉터리 안의 0600 파일이며,
              프로세스 락과 <code>.accounts.lock</code>을 잡고 atomic replace합니다.
              손상되거나 모르는 <code>schema_version</code>은 자동 초기화하지 않고
              닫힌 채로 실패합니다. 사용자가 대화창에 직접 쓴 내용과 모델이 일반
              대화문으로 작성한 요약은 GEODE의 통상 세션 보존 정책을 따릅니다.
              영속 tool/session 저장소에는 원문 입력·결과가 복사되지 않습니다.
              별도의 회전형 런타임 로그는 Workspace 결과 payload를 의도적으로
              복사하지 않지만, 제한된 Google API 오류 진단은 남을 수 있으므로
              일반 운영 로그 보존 정책으로 관리하십시오.
              전체 JSON 스키마와 동시성 계약은{" "}
              <a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/architecture/google-workspace-oauth.md">Google Workspace OAuth 설계 기록</a>에
              있습니다.
            </p>

            <h2>매 호출 동의 경계</h2>
            <p>
              Workspace 읽기 결과는 선택한 LLM 프로바이더로 전달될 수 있습니다.
              그래서 GEODE는 개인 데이터가 포함된 읽기와 변경 작업 모두에 대해
              도구 호출 직전에 affirmative consent를 다시 받습니다. 이 승인은
              always-allow로 캐시할 수 없고, headless·서브에이전트에서는 닫힌 채로
              거부되며 HITL 0이나 권한 건너뛰기로 우회할 수 없습니다.
            </p>

            <h2>자주 만나는 문제</h2>
            <ProblemTable />

            <h2>Hermes는 어떻게 풀었나</h2>
            <p>
              Hermes Agent도 사용자 소유 Desktop 클라이언트를 선택하지만, 배포
              단위는 런타임 명령이 아니라 bundled <code>google-workspace</code>
              Skill과 Python 스크립트입니다. 검사한 구현은 고정 localhost 실패
              redirect URL을 사용자가 다시 붙여넣는 분리형 흐름과{" "}
              <code>~/.hermes</code> 아래 client/token JSON을 사용합니다. 쓰기 전
              확인은 Skill 절차가 담당합니다.
            </p>
            <p>
              GEODE는 그 아이디어에서 BYO client, 서비스 중심 설정, PKCE/state,
              revoke를 채택하되 trust boundary를 바꿨습니다. 로컬 thin CLI가 임의
              loopback callback을 직접 받고, 장기 secret은 OS keyring에 두며,
              멀티 계정과 활성 계정을 스키마로 관리하고, 개인 데이터와 mutation
              승인은 executor가 매 호출 강제합니다. 비교 근거는{" "}
              <a href="https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/google-workspace/SKILL.md">Hermes Google Workspace Skill</a>과{" "}
              <a href="https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/google-workspace/scripts/setup.py">setup.py</a>입니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/auth">인증과 OAuth 레퍼런스</a>. 명령과 저장소 계약을 빠르게 찾습니다.</li>
              <li><a href="https://developers.google.com/workspace/workspace-api-user-data-developer-policy">Google Workspace API 사용자 데이터 정책</a>. Agentic 기능에 적용되는 공식 정책입니다.</li>
              <li><a href="https://developers.google.com/workspace/gmail/api/auth/scopes">Gmail API scope</a>. Sensitive와 Restricted 분류를 확인합니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Starting with GEODE v1.0.0, users installing from uv or GitHub
              can connect Gmail, Calendar, Drive, Docs, Sheets, Tasks, and
              Contacts through their own Google Cloud project. GEODE does not
              require a central OAuth app. The recommended entry point is{" "}
              <code>/login google</code> inside the interactive GEODE screen.
            </p>
            <p>
              This guide covers the smallest path for a personal Desktop OAuth
              client. Organization deployments and apps made available to
              other users remain subject to Workspace admin controls and
              Google&apos;s verification requirements.
            </p>

            <h2>Before you start</h2>
            <ul>
              <li>GEODE v1.0.0 or later and an interactive local terminal</li>
              <li>A Google account and a Google Cloud project you control</li>
              <li>macOS Keychain, Windows Credential Locker, or Linux Secret Service</li>
            </ul>
            <p>
              GEODE refuses Google login when no secure OS keyring is available.
              It never falls back to a plaintext refresh-token or client-secret file.
            </p>

            <h2>1. Enable the APIs you need</h2>
            <p>
              Under <strong>APIs &amp; Services → Library</strong> in Google Cloud,
              enable only the APIs for the features you plan to use. Google&apos;s{" "}
              <a href="https://developers.google.com/workspace/guides/enable-apis">enable APIs guide</a> covers
              the same console path.
            </p>
            <ApiTable english />

            <h2>2. Configure the consent screen</h2>
            <p>
              Complete <strong>Branding</strong>, <strong>Audience</strong>, and{" "}
              <strong>Data Access</strong> in Google Auth platform. For an
              initial smoke test, choose External with Testing status and add
              your own account as a test user. Follow Google&apos;s{" "}
              <a href="https://developers.google.com/workspace/guides/configure-oauth-consent">OAuth consent configuration guide</a> for
              the individual fields.
            </p>
            <ul>
              <li><strong>Internal</strong>: users inside one Workspace organization. Admin policy applies.</li>
              <li><strong>External · Testing</strong>: best for a first test. Add test users; refresh tokens for grants beyond basic profile scopes may expire after seven days.</li>
              <li><strong>External · In production</strong>: durable use or distribution. An app used by fewer than 100 personally known users may qualify for a verification exception, but warnings, user caps, and policy still apply.</li>
            </ul>
            <p>
              Confirm the exact lifetime conditions in Google&apos;s{" "}
              <a href="https://support.google.com/cloud/answer/15549945">OAuth app publishing status help</a> and
              the personal-use exception in{" "}
              <a href="https://support.google.com/cloud/answer/13464323">App verification requirements</a>.
            </p>
            <p>
              Gmail&apos;s <code>gmail.readonly</code> is a Restricted scope. If
              you distribute the app or access organization data, separately
              assess Google app verification, restricted-scope review, and
              security-assessment requirements. A personal BYO client does not
              waive Google API policy.
            </p>

            <h2>3. Create Desktop app credentials</h2>
            <ol>
              <li>Open <strong>Clients</strong> in Google Auth platform.</li>
              <li>Select <strong>Create client</strong>, then choose <strong>Desktop app</strong> as the application type.</li>
              <li>Download the JSON and keep it at a safe local path.</li>
            </ol>
            <p>
              Do not choose Web application credentials or an OOB copy/paste
              flow. GEODE follows Google&apos;s{" "}
              <a href="https://developers.google.com/identity/protocols/oauth2/native-app">Desktop OAuth guidance</a>:
              system browser, random <code>127.0.0.1</code> port, PKCE S256,
              and <code>state</code> validation. The exact console steps are in{" "}
              <a href="https://developers.google.com/workspace/guides/create-credentials">Create access credentials</a>.
            </p>

            <h2>4. Connect from GEODE</h2>
            <p>
              Run this inside the <code>geode</code> interactive screen, not as
              a shell command. With no arguments, the command asks for the JSON
              path and service selection in sequence.
            </p>
            <pre>{`geode

> /login google

# or provide the choices together on one line
> /login google --client-json ~/Downloads/client_secret.json --services gmail-send,calendar-read,workspace-files`}</pre>
            <p>
              The <code>recommended</code> selection is{" "}
              <code>gmail-send,calendar-read,workspace-files</code>. Add more
              powerful access such as Gmail read only when a task requires it.
            </p>
            <BundleTable english />
            <p>
              <code>workspace-files</code> uses <code>drive.file</code>, not a
              whole-Drive scope. The supported v1.0.0 path covers files created
              through GEODE. Although the scope can also cover files opened by
              a user through a Picker, GEODE v1.0.0 does not ship a Google
              Picker for selecting existing files.
            </p>

            <h2>5. Inspect and manage accounts</h2>
            <pre>{`/login google services
/login google status
/login google use user@example.com
/login google --new-account --services calendar-read
/login google --services calendar-write,tasks-write --replace-services
/login google logout user@example.com`}</pre>
            <p>
              Adding bundles to an existing account reauthorizes the union of
              its old and new bundles because installed apps do not support
              incremental authorization. To narrow a grant, pass the complete
              set to keep with <code>--replace-services</code>. GEODE refuses
              to save a different identity selected in the browser. Start a
              second identity with <code>--new-account</code>.
            </p>

            <h2>Where information is stored</h2>
            <StorageTable english />
            <p>
              The metadata registry is a mode 0600 file inside a mode 0700
              directory. GEODE takes a process lock and{" "}
              <code>.accounts.lock</code>, then atomically replaces it. Corrupt
              or unknown <code>schema_version</code> values fail closed rather
              than silently resetting. Text typed by the user and an assistant
              summary written into ordinary conversation text still follow the
              normal session-retention policy. Durable tool and session stores
              do not copy raw Workspace inputs or results. Separate rotating
              runtime logs do not intentionally copy Workspace result payloads,
              but may retain bounded Google API error diagnostics; manage them
              under the normal operational-log retention policy. The complete JSON schema and
              concurrency contract are in the{" "}
              <a href="https://github.com/mangowhoiscloud/geode/blob/main/docs/architecture/google-workspace-oauth.md">Google Workspace OAuth architecture record</a>.
            </p>

            <h2>Per-invocation consent boundary</h2>
            <p>
              Workspace read results may be sent to the selected LLM provider.
              GEODE therefore asks for affirmative consent immediately before
              every personal-data read or mutation. The approval cannot be
              cached as always-allow, fails closed in headless and sub-agent
              sessions, and cannot be bypassed by HITL 0 or skip-permissions.
            </p>

            <h2>Common problems</h2>
            <ProblemTable english />

            <h2>How Hermes approaches it</h2>
            <p>
              Hermes Agent also chooses a user-owned Desktop client, but ships
              the integration as a bundled <code>google-workspace</code> Skill
              and Python scripts rather than a first-class runtime command. In
              the inspected implementation, a split flow asks the user to paste
              back a failed fixed-localhost redirect URL, credentials live in
              client/token JSON under <code>~/.hermes</code>, and the Skill
              procedure carries the confirm-before-write rule.
            </p>
            <p>
              GEODE keeps the useful BYO-client, service-oriented setup,
              PKCE/state, and revoke ideas but changes the trust boundary. The
              local thin CLI receives a random loopback callback directly,
              long-lived secrets stay in the OS keyring, a schema manages
              multiple and active accounts, and the executor enforces every
              personal-data and mutation approval. Sources:{" "}
              <a href="https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/google-workspace/SKILL.md">Hermes Google Workspace Skill</a> and{" "}
              <a href="https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/google-workspace/scripts/setup.py">setup.py</a>.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/auth">Auth and OAuth reference</a>. Find the command and storage contract quickly.</li>
              <li><a href="https://developers.google.com/workspace/workspace-api-user-data-developer-policy">Google Workspace API user data policy</a>. Official policy for agentic features.</li>
              <li><a href="https://developers.google.com/workspace/gmail/api/auth/scopes">Gmail API scopes</a>. Sensitive and Restricted classifications.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
