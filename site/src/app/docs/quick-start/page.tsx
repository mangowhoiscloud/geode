import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Quick Start — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="quick-start"
      title="Quick Start"
      titleKo="빠른 시작"
      summary="Install, configure, and run GEODE in five minutes."
      summaryKo="5분 안에 GEODE를 설치하고 설정한 뒤 실행합니다."
    >
      <Bi
        ko={
          <>
            <h2>요구사항</h2>
            <ul>
              <li>Python 3.12 이상</li>
              <li><code>uv</code> 패키지 매니저 (<a href="https://docs.astral.sh/uv/">설치 안내</a>)</li>
              <li>최소 한 개의 프로바이더 API 키 (Anthropic, OpenAI 또는 GLM)</li>
            </ul>

            <h2>설치</h2>
            <pre>{`git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync
uv tool install -e .`}</pre>

            <h2>설정</h2>
            <p>
              프로바이더 API 키는 <code>~/.geode/config.toml</code> 또는 환경 변수에
              지정합니다. 활성화하려는 폴백 체인에 따라 필요한 키가 달라집니다.
            </p>
            <pre>{`export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GLM_API_KEY=...           # optional, third fallback chain
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 # optional, with [obs] extra`}</pre>

            <h2>실행</h2>
            <pre>{`# Interactive REPL
geode

# One-shot natural language
geode "summarize the latest AI research trends"

# Daemon mode (long-running, IPC-served)
geode serve`}</pre>

            <h2>방금 일어난 일</h2>
            <p>
              <code>geode</code>를 실행하면 thin CLI가 serve daemon에 연결되고,
              자연어 요청은 AgenticLoop를 통해 tool/MCP/skill 경로로 처리됩니다.
            </p>
            <ol>
              <li>serve daemon 자동 기동 또는 기존 daemon 재사용</li>
              <li>프로젝트/사용자 memory, MCP, skill registry 초기화</li>
              <li>LLM provider routing과 tool registry 연결</li>
              <li>대화 세션과 실행 로그를 지속 저장</li>
            </ol>

            <h2>다음 단계</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">4-계층 스택</a>. 코드베이스가 어떻게 구성되어 있는지 확인합니다.</li>
              <li><a href="/geode/docs/architecture/system-index">시스템 색인</a>. 모든 서브시스템과 파일 경로를 정리합니다.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">프롬프트 시스템</a>. 프롬프트 어셈블리 파이프라인을 살펴봅니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Requirements</h2>
            <ul>
              <li>Python 3.12+</li>
              <li><code>uv</code> package manager (<a href="https://docs.astral.sh/uv/">install</a>)</li>
              <li>At least one provider API key (Anthropic, OpenAI, or GLM)</li>
            </ul>

            <h2>Install</h2>
            <pre>{`git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync
uv tool install -e .`}</pre>

            <h2>Configure</h2>
            <p>
              Provider API keys go into <code>~/.geode/config.toml</code> or
              environment variables. The keys you need depend on which fallback
              chain you want active:
            </p>
            <pre>{`export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GLM_API_KEY=...           # optional, third fallback chain
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 # optional, with [obs] extra`}</pre>

            <h2>Run</h2>
            <pre>{`# Interactive REPL
geode

# One-shot natural language
geode "summarize the latest AI research trends"

# Daemon mode (long-running, IPC-served)
geode serve`}</pre>

            <h2>What just happened</h2>
            <p>
              Running <code>geode</code> connects the thin CLI to the serve daemon,
              then natural-language requests flow through AgenticLoop, tools,
              MCP, and skills.
            </p>
            <ol>
              <li>Auto-start or reuse the serve daemon</li>
              <li>Initialize project/user memory, MCP, and the skill registry</li>
              <li>Wire LLM provider routing and the tool registry</li>
              <li>Persist conversation state and execution logs</li>
            </ol>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">4-Layer Stack</a> — how the codebase is organized</li>
              <li><a href="/geode/docs/architecture/system-index">System Index</a> — every subsystem with file paths</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a> — the prompt assembly pipeline</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
