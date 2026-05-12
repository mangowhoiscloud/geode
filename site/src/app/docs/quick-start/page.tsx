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
export LANGCHAIN_TRACING_V2=true # optional, opt-in tracing
export LANGCHAIN_API_KEY=ls_...  # required if tracing enabled`}</pre>

            <h2>실행</h2>
            <pre>{`# Interactive REPL
geode

# One-shot natural language
geode "summarize the latest AI research trends"

# Game IP plugin (dry-run, no API calls — uses fixtures)
geode analyze "Cowboy Bebop" --dry-run
# → A (68.4) — undermarketed

# Game IP plugin (full run, requires API keys)
geode analyze "Berserk" --verbose

# Daemon mode (long-running, IPC-served)
geode serve`}</pre>

            <h2>방금 일어난 일</h2>
            <p>
              <code>geode analyze ... --dry-run</code>을 실행하면 픽스처 세트에서
              모킹된 LLM 응답으로 파이프라인이 모든 단계를 거칩니다.
            </p>
            <ol>
              <li><code>plugins/game_ip/fixtures/</code>에서 IP 프로필 로드</li>
              <li>4개 Analyst를 병렬 실행 (game_mechanics, player_experience, growth_potential, discovery)</li>
              <li>3개 Evaluator가 점수화 (quality_judge, hidden_value, community_momentum)</li>
              <li>BiasBuster가 6종 편향 검사로 검증</li>
              <li>Synthesizer가 원인 잠금형 권고안을 생성</li>
              <li>PSM 점수 산정 (ATT, Z, Gamma)으로 최종 tier 산출</li>
            </ol>

            <h2>다음 단계</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">4-계층 스택</a>. 코드베이스가 어떻게 구성되어 있는지 확인합니다.</li>
              <li><a href="/geode/docs/architecture/system-index">시스템 색인</a>. 모든 서브시스템과 파일 경로를 정리합니다.</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">프롬프트 시스템</a>. 프롬프트 어셈블리 파이프라인을 살펴봅니다.</li>
              <li><a href="/geode/docs/plugins/game-ip">Game IP 플러그인</a>. analyze 명령이 실제로 무엇을 하는지 보여줍니다.</li>
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
export LANGCHAIN_TRACING_V2=true # optional, opt-in tracing
export LANGCHAIN_API_KEY=ls_...  # required if tracing enabled`}</pre>

            <h2>Run</h2>
            <pre>{`# Interactive REPL
geode

# One-shot natural language
geode "summarize the latest AI research trends"

# Game IP plugin (dry-run, no API calls — uses fixtures)
geode analyze "Cowboy Bebop" --dry-run
# → A (68.4) — undermarketed

# Game IP plugin (full run, requires API keys)
geode analyze "Berserk" --verbose

# Daemon mode (long-running, IPC-served)
geode serve`}</pre>

            <h2>What just happened</h2>
            <p>
              On <code>geode analyze ... --dry-run</code> the pipeline went through
              every stage with mocked LLM responses from the fixture set:
            </p>
            <ol>
              <li>Load IP profile from <code>plugins/game_ip/fixtures/</code></li>
              <li>4 Analysts run in parallel (game_mechanics, player_experience, growth_potential, discovery)</li>
              <li>3 Evaluators score (quality_judge, hidden_value, community_momentum)</li>
              <li>BiasBuster validates with 6 bias checks</li>
              <li>Synthesizer produces the cause-locked recommendation</li>
              <li>PSM scoring (ATT, Z, Gamma) projects the final tier</li>
            </ol>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/architecture/overview">4-Layer Stack</a> — how the codebase is organized</li>
              <li><a href="/geode/docs/architecture/system-index">System Index</a> — every subsystem with file paths</li>
              <li><a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a> — the prompt assembly pipeline</li>
              <li><a href="/geode/docs/plugins/game-ip">Game IP Plugin</a> — what the analyze command does</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
