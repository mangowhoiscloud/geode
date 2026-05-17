import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Configure Providers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/providers"
      title="Configure Providers"
      titleKo="프로바이더 설정"
      summary="Anthropic, OpenAI, Codex, GLM. Where keys go, what fallback chain you get."
      summaryKo="Anthropic, OpenAI, Codex, GLM. 키를 어디에 두고 어떤 폴백 체인이 동작하는지."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 4 프로바이더 키를 GEODE에 등록하는 방법과, 키 조합이 만들어내는 폴백 체인을 보여줍니다.</p>

            <h2>키 위치</h2>
            <p>다음 두 곳 중 한 곳에 두면 GEODE가 자동으로 인식합니다.</p>
            <ul>
              <li>환경 변수: <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>GLM_API_KEY</code></li>
              <li>설정 파일: <code>~/.geode/config.toml</code></li>
            </ul>

            <h2>폴백 체인</h2>
            <p>폴백 체인은 <code>core/config/routing.toml</code>의 shipped manifest와 <code>~/.geode/routing.toml</code> 사용자 override가 결정합니다.</p>
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>기본 모델</th>
                  <th>Fallback</th>
                  <th>인증</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic</td>
                  <td><code>claude-opus-4-7</code></td>
                  <td><code>claude-opus-4-7</code> → <code>claude-sonnet-4-6</code></td>
                  <td><code>ANTHROPIC_API_KEY</code> 또는 Claude Code keychain</td>
                </tr>
                <tr>
                  <td>OpenAI</td>
                  <td><code>gpt-5.5</code></td>
                  <td><code>gpt-5.5</code> → <code>gpt-5.4</code></td>
                  <td><code>OPENAI_API_KEY</code></td>
                </tr>
                <tr>
                  <td>Codex OAuth</td>
                  <td><code>gpt-5.5</code></td>
                  <td><code>gpt-5.5</code> → <code>gpt-5.3-codex</code></td>
                  <td>ChatGPT/Codex OAuth session</td>
                </tr>
                <tr>
                  <td>GLM</td>
                  <td><code>glm-5.1</code></td>
                  <td><code>glm-5.1</code> → <code>glm-5</code></td>
                  <td><code>ZAI_API_KEY</code></td>
                </tr>
              </tbody>
            </table>

            <h2>검증</h2>
            <pre>{`uv run geode "확인용 한 줄"`}</pre>
            <p>위 명령이 정상 응답하면 키가 잡힌 것입니다.</p>
          </>
        }
        en={
          <>
            <p>This guide registers your provider keys with GEODE and shows the fallback chains each combination unlocks.</p>

            <h2>Where keys go</h2>
            <p>GEODE picks up keys from either location automatically.</p>
            <ul>
              <li>Environment variables: <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>GLM_API_KEY</code></li>
              <li>Config file: <code>~/.geode/config.toml</code></li>
            </ul>

            <h2>Fallback chains</h2>
            <p>Fallback chains are selected from the shipped <code>core/config/routing.toml</code> manifest plus your <code>~/.geode/routing.toml</code> overrides.</p>
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Default model</th>
                  <th>Fallback</th>
                  <th>Auth</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic</td>
                  <td><code>claude-opus-4-7</code></td>
                  <td><code>claude-opus-4-7</code> → <code>claude-sonnet-4-6</code></td>
                  <td><code>ANTHROPIC_API_KEY</code> or Claude Code keychain</td>
                </tr>
                <tr>
                  <td>OpenAI</td>
                  <td><code>gpt-5.5</code></td>
                  <td><code>gpt-5.5</code> → <code>gpt-5.4</code></td>
                  <td><code>OPENAI_API_KEY</code></td>
                </tr>
                <tr>
                  <td>Codex OAuth</td>
                  <td><code>gpt-5.5</code></td>
                  <td><code>gpt-5.5</code> → <code>gpt-5.3-codex</code></td>
                  <td>ChatGPT/Codex OAuth session</td>
                </tr>
                <tr>
                  <td>GLM</td>
                  <td><code>glm-5.1</code></td>
                  <td><code>glm-5.1</code> → <code>glm-5</code></td>
                  <td><code>ZAI_API_KEY</code></td>
                </tr>
              </tbody>
            </table>

            <h2>Verify</h2>
            <pre>{`uv run geode "hello"`}</pre>
            <p>If GEODE responds, your keys are wired up.</p>
          </>
        }
      />
    </DocsShell>
  );
}
