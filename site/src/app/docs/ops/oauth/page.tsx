import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "OAuth token rotation — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/oauth"
      title="OAuth token rotation"
      titleKo="OAuth 토큰 회전"
      summary="What core/auth actually does at runtime: profile selection, proactive refresh, 401 auto-refresh, and cooldown escalation."
      summaryKo="core/auth가 런타임에 실제로 하는 일입니다. 프로파일 선택, 선제 갱신, 401 자동 갱신, 쿨다운 에스컬레이션을 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              토큰 회전의 코드 홈은 <code>core/auth/</code>입니다.
              프로파일과 플랜의 SoT는 <code>~/.geode/auth.toml</code>
              (<code>core/auth/auth_toml.py</code>,
              <code>core/auth/profiles.py</code>)이고, 호출마다 어느
              프로파일을 쓸지와 언제 갱신할지는
              <code>core/auth/rotation.py</code>의
              <code>ProfileRotator</code>가 정합니다.
            </p>

            <h2>선택과 갱신 규칙</h2>
            <table>
              <thead>
                <tr><th>규칙</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>타입 우선 선택</td>
                  <td>oauth &gt; token &gt; api_key 순으로 고르고, 같은 타입 안에서는 LRU로 돌립니다.</td>
                </tr>
                <tr>
                  <td>선제 갱신</td>
                  <td>관리형(managed) 토큰은 만료 120초 이내면 외부 저장소에서 다시 읽습니다. Hermes의 skew 상수를 그대로 빌렸습니다.</td>
                </tr>
                <tr>
                  <td>401 자동 갱신</td>
                  <td>인증 실패(401/403) 시 쿨다운을 적용하기 전에 한 번 더 다시 읽고, 토큰이 바뀌었으면 오류 카운트를 리셋합니다.</td>
                </tr>
                <tr>
                  <td>쿨다운</td>
                  <td><code>calculate_cooldown_ms</code>가 오류 횟수에 따라 쿨다운을 키웁니다. 키별 상태는 <code>core/auth/cooldown.py</code>의 <code>CooldownTracker</code>가 보관합니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              관리형 토큰의 대표가 Codex입니다. 수명 관리는 Codex CLI가 하고
              GEODE는 <code>~/.codex/auth.json</code>을 읽기만 합니다. 그래서
              &quot;갱신&quot;은 새 토큰 발급이 아니라 외부 저장소 재독입니다.
              발급이 필요하면 <code>codex login</code>을 다시 돌립니다.
            </p>

            <h2>운영 시 알아둘 것</h2>
            <ul>
              <li>
                thin CLI에서 <code>/login</code>을 마치면 데몬이 auth 상태를
                다시 읽습니다. 이 리로드는 추가 전용입니다. 제거된 항목은
                캐시된 싱글톤에서 즉시 빠지지 않으므로, 프로파일을 지운 뒤
                확실히 하려면 데몬을 재시작합니다.
              </li>
              <li>
                Codex의 선제 5시간 스로틀을 우회하려면
                <code>GEODE_CODEX_OAUTH_POLL_DISABLED=1</code>을 켭니다.
                구독 버킷으로 바로 떨어집니다.
              </li>
              <li>
                <code>core/llm/credentials.py</code>의
                <code>resolve_provider_key</code>(OAuth 우선, API 키 폴백)는
                deprecated입니다. 어댑터 레지스트리의 소스별 명시 자격이
                대체이고, v1.0.0 제거 대상입니다.
              </li>
            </ul>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>한 프로파일만 계속 401</td>
                  <td>외부 저장소의 토큰 자체가 만료</td>
                  <td>Codex는 <code>codex login</code>, Anthropic 구독은 Claude Code 재로그인으로 원본 토큰을 갱신합니다.</td>
                </tr>
                <tr>
                  <td>호출이 점점 뜸해짐</td>
                  <td>반복 실패로 쿨다운 에스컬레이션</td>
                  <td>원인 자격을 고치면 성공 콜백이 쿨다운을 리셋합니다.</td>
                </tr>
                <tr>
                  <td>프로파일을 지웠는데 계속 쓰임</td>
                  <td>데몬 리로드가 추가 전용</td>
                  <td>데몬을 재시작합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/auth">인증과 OAuth</a>. 자격 소스와 /login 표면.</li>
              <li><a href="/geode/docs/run/providers">프로바이더 설정</a>. 처음 자격을 붙이는 절차.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Token rotation lives in <code>core/auth/</code>. The SoT for
              profiles and plans is <code>~/.geode/auth.toml</code>
              (<code>core/auth/auth_toml.py</code>,
              <code>core/auth/profiles.py</code>); which profile a call uses,
              and when it refreshes, is decided by <code>ProfileRotator</code>
              in <code>core/auth/rotation.py</code>.
            </p>

            <h2>Selection and refresh rules</h2>
            <table>
              <thead>
                <tr><th>Rule</th><th>Behavior</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Type-priority selection</td>
                  <td>oauth &gt; token &gt; api_key, LRU rotation within a type.</td>
                </tr>
                <tr>
                  <td>Proactive refresh</td>
                  <td>Managed tokens are re-read from external storage when expiry is within 120 seconds. The skew constant is borrowed from Hermes.</td>
                </tr>
                <tr>
                  <td>401 auto-refresh</td>
                  <td>On an auth failure (401/403) the rotator re-reads once before applying cooldown, and resets the error count if the token changed.</td>
                </tr>
                <tr>
                  <td>Cooldown</td>
                  <td><code>calculate_cooldown_ms</code> escalates with the error count. Per-key state is held by <code>CooldownTracker</code> in <code>core/auth/cooldown.py</code>.</td>
                </tr>
              </tbody>
            </table>
            <p>
              Codex is the canonical managed token: Codex CLI owns the
              lifecycle and GEODE only reads <code>~/.codex/auth.json</code>.
              &quot;Refresh&quot; therefore means re-reading external storage,
              not minting a new token. When minting is needed, rerun
              <code>codex login</code>.
            </p>

            <h2>Operational notes</h2>
            <ul>
              <li>
                After <code>/login</code> finishes in the thin CLI, the daemon
                reloads auth state. The reload is additive: removed entries
                are not evicted from the cached singleton, so restart the
                daemon to be sure after deleting a profile.
              </li>
              <li>
                To bypass the pre-emptive 5-hour Codex throttle, set
                <code>GEODE_CODEX_OAUTH_POLL_DISABLED=1</code>. Calls fall
                straight through to the subscription bucket.
              </li>
              <li>
                <code>resolve_provider_key</code> in
                <code>core/llm/credentials.py</code> (OAuth-preferred with an
                API-key fallback) is deprecated in favor of the adapter
                registry&apos;s explicit per-source credentials; removal
                target v1.0.0.
              </li>
            </ul>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>One profile keeps returning 401</td>
                  <td>The token in external storage itself expired</td>
                  <td>Renew the origin token: <code>codex login</code> for Codex, re-login Claude Code for the Anthropic subscription.</td>
                </tr>
                <tr>
                  <td>Calls slow to a trickle</td>
                  <td>Cooldown escalation from repeated failures</td>
                  <td>Fix the failing credential; the success callback resets the cooldown.</td>
                </tr>
                <tr>
                  <td>A removed profile is still used</td>
                  <td>The daemon reload is additive</td>
                  <td>Restart the daemon.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/auth">Auth and OAuth</a>. Credential sources and the /login surface.</li>
              <li><a href="/geode/docs/run/providers">Configure providers</a>. First-time credential setup.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
