import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "OAuth Token Rotation — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/oauth"
      title="OAuth Token Rotation"
      titleKo="OAuth 토큰 회전"
      summary="Anthropic ToS, Codex flow, refresh policy."
      summaryKo="Anthropic ToS, Codex 플로우, 갱신 정책."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 OAuth 기반 인증을 사용하는 경우의 토큰 갱신 정책을 정리합니다.</p>

            <h2>중요한 정책</h2>
            <p>
              <strong>Anthropic Claude Pro/Max OAuth 토큰은 third-party harness에서 사용 불가</strong>입니다 (2026-01-09 ToS).
              GEODE는 해당 토큰을 읽지 않습니다. 대신 Anthropic API 키 (Console)를 사용하세요.
            </p>

            <h2>Codex OAuth (gpt-5.5 구독)</h2>
            <pre>{`# 토큰 등록 (CLI 대화형)
codex login

# 토큰 위치
~/.codex/auth.json`}</pre>

            <h2>자동 갱신</h2>
            <p>GEODE는 만료 임박을 감지하면 refresh token으로 자동 갱신. 실패 시 <code>OAUTH_REFRESH_FAILED</code> hook 발생.</p>

            <h2>수동 재인증</h2>
            <pre>{`codex login  # 새 토큰 발급
geode /clean # 캐시 비우기
geode serve & # 재기동`}</pre>

            <p className="text-white/40 text-sm"><em>참조:</em> wiki/concepts/geode-oauth-policy.md, <a href="/docs/runtime/auth">Auth and OAuth reference</a></p>
          </>
        }
        en={
          <>
            <p>This guide documents the token refresh policy for OAuth-based providers.</p>

            <h2>Policy reminder</h2>
            <p>
              <strong>Anthropic Claude Pro/Max OAuth tokens cannot be used by third-party harnesses</strong> (per the 2026-01-09 ToS).
              GEODE does not read them. Use an Anthropic API key (Console) instead.
            </p>

            <h2>Codex OAuth (gpt-5.5 subscription)</h2>
            <pre>{`# Register the token (interactive CLI)
codex login

# Token location
~/.codex/auth.json`}</pre>

            <h2>Auto-refresh</h2>
            <p>GEODE auto-refreshes using the refresh token when expiry is near. On failure, the <code>OAUTH_REFRESH_FAILED</code> hook fires.</p>

            <h2>Manual re-auth</h2>
            <pre>{`codex login  # issue a new token
geode /clean # clear caches
geode serve & # restart`}</pre>

            <p className="text-white/40 text-sm"><em>See:</em> wiki/concepts/geode-oauth-policy.md, <a href="/docs/runtime/auth">Auth and OAuth reference</a>.</p>
          </>
        }
      />
    </DocsShell>
  );
}
