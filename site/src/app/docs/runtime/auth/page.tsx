import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Auth & OAuth — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/auth"
      title="Auth & OAuth"
      titleKo="인증과 OAuth"
      summary="core/auth/. profile rotator, OAuth flows, credential resolution. Anthropic OAuth disabled per ToS; OpenAI Codex Plus active."
      summaryKo="core/auth/. 프로파일 로테이터, OAuth 플로우, 자격 증명 해석. Anthropic OAuth는 ToS에 따라 비활성. OpenAI Codex Plus는 활성."
    >
      <Bi
        ko={
          <>
            <h2>두 가지 경로</h2>
            <ol>
              <li><strong>API 키</strong>. 환경 변수 또는 <code>~/.geode/config.toml</code>. 항상 사용 가능.</li>
              <li><strong>OAuth (구독)</strong>. OpenAI Codex Plus용. 대화형 로그인 흐름으로 트리거.</li>
            </ol>

            <h2>Anthropic OAuth. 비활성</h2>
            <p>
              Anthropic의 ToS는 비-애플리케이션 계정에 대한 OAuth 기반 프로그래밍
              접근을 금지합니다. GEODE는 이 경로를 명시적으로 비활성화합니다.
              Anthropic 사용자는 API 키를 사용해야 합니다.
            </p>

            <h2>프로파일 로테이터</h2>
            <p>
              여러 OpenAI/GLM 자격 증명 프로파일이 공존할 수 있습니다. 프로파일
              로테이터는 호출마다 프로파일을 선택하며, rate-limit이나 인증 실패
              시 회전시킵니다. 이것이 폴백 체인이 프로바이더 경계를 안전하게
              넘나들 수 있게 해주는 토대입니다.
            </p>

            <h2>자격 증명 해석</h2>
            <pre>{`# core/llm/credentials.py
def resolve_provider_key(provider: str, fallback: str | None = None) -> str:
    """OAuth-preferred resolution.

    Order: ProfileRotator (active OAuth profile) →
           settings.<provider>_api_key →
           fallback param →
           empty string."""`}</pre>

            <h2>파일</h2>
            <ul>
              <li><code>core/auth/</code>. 프로파일 로테이터 + OAuth 플로우.</li>
              <li><code>core/llm/credentials.py</code>. 프로바이더 키 해석.</li>
              <li><code>core/cli/auth_commands.py</code>. login/logout/status 슬래시 명령.</li>
            </ul>

            <h2>저장</h2>
            <p>
              OAuth 토큰은 파일 모드 600으로{" "}
              <code>~/.geode/auth/profiles/&lt;name&gt;.json</code>에 저장됩니다.
              리프레시 토큰은 만료 시 회전되며, 401을 포착해 재시도 전에 강제
              갱신하는 책임은 로테이터에 있습니다.
            </p>
          </>
        }
        en={
          <>
            <h2>The two paths</h2>
            <ol>
              <li><strong>API key</strong> — env vars or <code>~/.geode/config.toml</code>. Always available.</li>
              <li><strong>OAuth (subscription)</strong> — for OpenAI Codex Plus. Triggered by interactive login flow.</li>
            </ol>

            <h2>Anthropic OAuth — disabled</h2>
            <p>
              Anthropic&apos;s ToS prohibits OAuth-based programmatic access for
              non-application accounts. GEODE explicitly disables this path. Users
              on Anthropic must use API keys.
            </p>

            <h2>Profile rotator</h2>
            <p>
              Multiple OpenAI/GLM credential profiles can coexist. The profile
              rotator picks a profile per call, rotating on rate-limit or auth
              failures. This is the foundation that lets fallback chains span
              provider boundaries safely.
            </p>

            <h2>Credential resolution</h2>
            <pre>{`# core/llm/credentials.py
def resolve_provider_key(provider: str, fallback: str | None = None) -> str:
    """OAuth-preferred resolution.

    Order: ProfileRotator (active OAuth profile) →
           settings.<provider>_api_key →
           fallback param →
           empty string."""`}</pre>

            <h2>Files</h2>
            <ul>
              <li><code>core/auth/</code>. profile rotator + OAuth flows</li>
              <li><code>core/llm/credentials.py</code> — provider key resolution</li>
              <li><code>core/cli/auth_commands.py</code> — login/logout/status slash commands</li>
            </ul>

            <h2>Storage</h2>
            <p>
              OAuth tokens land in <code>~/.geode/auth/profiles/&lt;name&gt;.json</code>{" "}
              with file-mode 600. Refresh tokens are rotated on expiry; the
              rotator is responsible for catching 401s and forcing refresh
              before retry.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
