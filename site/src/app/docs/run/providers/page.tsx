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
            <p>키 조합에 따라 활성화되는 fallback chain은 <code>core/llm/providers/</code>의 라우터가 결정합니다.</p>
            <p className="text-white/40"><em>TODO: chain 표. Source: wiki/concepts/geode-llm-models.md, wiki/concepts/geode-tool-routing.md</em></p>

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
            <p>The router in <code>core/llm/providers/</code> selects the chain based on which keys are present.</p>
            <p className="text-white/40"><em>TODO: chain table. Source: wiki/concepts/geode-llm-models.md, wiki/concepts/geode-tool-routing.md.</em></p>

            <h2>Verify</h2>
            <pre>{`uv run geode "hello"`}</pre>
            <p>If GEODE responds, your keys are wired up.</p>
          </>
        }
      />
    </DocsShell>
  );
}
