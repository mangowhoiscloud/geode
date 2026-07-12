import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Configure Providers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/providers"
      title="Configure providers"
      titleKo="프로바이더 설정"
      summary="Three-provider routing, where keys and behavior settings live, and how the effective model is resolved."
      summaryKo="3-프로바이더 라우팅, 키와 동작 설정이 사는 곳, 실효 모델이 결정되는 순서."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 Anthropic, OpenAI(ChatGPT 구독 OAuth 레인 포함), GLM 세
              프로바이더로 라우팅합니다. 이 페이지는 키와 설정이 어디에
              저장되는지, 모델이 어떤 순서로 결정되는지, 막혔을 때 어떻게
              디버깅하는지 다룹니다.
            </p>

            <h2>3-프로바이더 라우팅</h2>
            <p>
              모델 id의 접두사가 프로바이더를 결정합니다. 라우팅 SoT는 배포
              매니페스트 <code>core/config/routing.toml</code>이고,
              <code>~/.geode/routing.toml</code>이 섹션 단위로 덮어씁니다.
            </p>
            <table>
              <thead>
                <tr><th>프로바이더</th><th>기본 모델</th><th>라우팅 규칙</th><th>인증 레인</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic</td>
                  <td><code>claude-opus-4-8</code> (보조 <code>claude-sonnet-4-6</code>, 저비용 <code>claude-haiku-4-5-20251001</code>)</td>
                  <td><code>claude-</code> 접두사</td>
                  <td>구독 OAuth(claude CLI keychain) 또는 <code>ANTHROPIC_API_KEY</code></td>
                </tr>
                <tr>
                  <td>OpenAI / Codex</td>
                  <td><code>gpt-5.5</code></td>
                  <td><code>gpt-</code>, <code>o3-</code>, <code>o4-</code> 접두사. 단 <code>gpt-5.5</code>, <code>gpt-5.5-pro</code>와 <code>-codex</code> 계열 접미사는 Codex OAuth 백엔드로만 라우팅. <code>gpt-5.6-sol/terra/luna</code>는 듀얼 레인 — 로그인 상태(API 키 ↔ 구독 OAuth)가 백엔드를 결정</td>
                  <td>ChatGPT 구독 OAuth(<code>~/.codex/auth.json</code>) 또는 <code>OPENAI_API_KEY</code></td>
                </tr>
                <tr>
                  <td>GLM (ZhipuAI)</td>
                  <td><code>glm-5.2</code> (무료 티어 <code>glm-4.7-flash</code>)</td>
                  <td><code>glm-</code> 접두사</td>
                  <td><code>ZAI_API_KEY</code>. Coding Plan과 PAYG 엔드포인트가 분리되어 있습니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              (프로바이더, 자격 소스) 조합마다 어댑터가 하나씩 등록됩니다
              (<code>core/llm/adapters/</code>). <code>geode adapters list</code>로
              현재 등록 상태와 자격 환경을 확인할 수 있습니다.
            </p>

            <h2>키와 설정이 사는 곳</h2>
            <p>역할이 파일별로 분리되어 있습니다. 키는 .env, 동작은 config.toml입니다.</p>
            <table>
              <thead>
                <tr><th>파일</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>~/.geode/.env</code></td>
                  <td>시크릿 전용. <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>ZAI_API_KEY</code>. 프로젝트 <code>.env</code>가 있으면 그쪽이 이깁니다.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/config.toml</code></td>
                  <td>전역 동작 설정. 모델 선택, effort, 로그인 소스가 여기 저장됩니다.</td>
                </tr>
                <tr>
                  <td><code>.geode/config.toml</code></td>
                  <td>프로젝트별 덮어쓰기. <code>/model</code>의 기본 저장 위치입니다.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/routing.toml</code></td>
                  <td>라우팅 매니페스트 덮어쓰기. 폴백 체인 옵트인도 여기서 합니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              모델, effort, 로그인 소스를 .env에 적는 방식은 폐기되었습니다.
              예전 버전이 남긴 .env의 모델 줄은 <code>/model</code>이 toml에
              쓰면서 자동으로 지우고 &quot;removed stale ... from .env&quot;
              안내를 출력합니다.
            </p>

            <h2>모델 결정 순서</h2>
            <p>위가 아래를 가립니다. 첫 번째로 값이 설정된 레이어가 이깁니다.</p>
            <pre>{`1. CLI 인자
2. env 레이어 (os.environ + project .env + global .env)
3. 프로젝트 .geode/config.toml
4. 전역 ~/.geode/config.toml
5. 라우팅 기본값 (core/config/routing.toml)`}</pre>
            <figure>
              <img
                src="/geode/diagrams/model-resolution.svg"
                alt="Model resolution ladder: CLI argument, env layer, project config.toml, global config.toml, then the routing default; the first layer with a value wins"
              />
              <figcaption>값이 설정된 첫 레이어가 이깁니다. 어느 레이어가 이겼는지는 geode config explain model이 보여줍니다.</figcaption>
            </figure>
            <p>
              데몬은 시작할 때 모델 계열 env 키를 의도적으로 버리므로
              (<code>BEHAVIOR_ENV_KEYS</code>, <code>core/config/env_io.py</code>),
              세션마다 toml의 선택이 항상 이깁니다. 셸에서 직접 export한
              <code>GEODE_MODEL</code>은 그 세션 한정의 파워유저 오버라이드입니다.
            </p>

            <h2>디버깅 플로우: geode config explain</h2>
            <p>
              &quot;설정을 바꿨는데 안 먹힌다&quot;의 표준 진단은
              <code>geode config explain model</code>입니다. 레이어별 후보 값과
              파일 경로를 표로 보여주고, 이기는 레이어 하나에 WINNER, 가려진
              레이어에 masked를 표시합니다.
            </p>
            <pre>{`geode config explain model    # 어느 레이어가 이기는지
geode about                   # 실효(EFFECTIVE) 모델 + 프로바이더`}</pre>
            <p>
              <code>geode about</code>은 실제로 적용 중인 값을 보여주는
              화면입니다. env 레이어가 toml의 선택을 가리고 있으면 경고
              한 줄을 먼저 띄웁니다. 전환 검증은 config 파일 내용이 아니라
              항상 <code>geode about</code> 기준으로 합니다.
            </p>

            <h2>폴백 정책: 기본은 비어 있음</h2>
            <p>
              <code>routing.toml</code>의 <code>[model.fallbacks]</code>는 기본
              출하 상태가 전부 빈 목록입니다. 기본 모델이 실패하면 GEODE는
              조용히 다른 모델로 바꾸지 않고 즉시 실패를 올립니다
              (<code>core/llm/errors.py</code>의 fast-fail 단락). 사용자가
              <code>/model</code>로 직접 고르는 것이 의도된 복구 경로입니다.
              폴백 체인이 필요하면 <code>~/.geode/routing.toml</code>에서
              옵트인합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>모델을 바꿨는데 그대로</td>
                  <td>상위 레이어(보통 옛 .env 줄 또는 셸 export)가 가림</td>
                  <td><code>geode config explain model</code>로 WINNER 레이어를 찾아 그 줄을 고치거나 지웁니다.</td>
                </tr>
                <tr>
                  <td>데몬만 옛 모델로 응답</td>
                  <td>데몬 환경에 모델 env가 박제됨</td>
                  <td>데몬은 시작 시 모델 계열 env 키를 버리는 것이 기본입니다. <code>pkill -f &quot;geode serve&quot;</code> 후 재시작합니다. 데몬 모델을 env로 일부러 고정하려면 <code>GEODE_SERVE_KEEP_MODEL_ENV=1</code>이 탈출구입니다.</td>
                </tr>
                <tr>
                  <td>GLM 구독인데 미터링 과금</td>
                  <td>Coding Plan 키가 PAYG 엔드포인트로 나감</td>
                  <td>Coding Plan 엔드포인트(<code>api.z.ai/api/coding/paas/v4</code>)와 PAYG(<code>api.z.ai/api/paas/v4</code>)는 다릅니다. 어느 쪽으로 나가는지 확인합니다.</td>
                </tr>
                <tr>
                  <td><code>gpt-5.5</code>가 API 키로 안 됨</td>
                  <td>codex 전용 모델</td>
                  <td><code>gpt-5.5</code>와 <code>gpt-5.5-pro</code>는 ChatGPT 구독 OAuth 레인으로만 라우팅됩니다(<code>gpt-5.6</code> 계열은 API 키로도 동작). <code>/login openai</code>로 로그인합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>설정 레퍼런스</h2>
            <ul>
              <li><a href="/geode/docs/config/basics">설정 기초</a>. 레이어 모델 전체.</li>
              <li><a href="/geode/docs/config/reference">config.toml 레퍼런스</a>. 키 전수 목록.</li>
              <li><a href="/geode/docs/runtime/auth">인증과 OAuth</a>. 프로파일과 회전.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM 라우팅</a>. 어댑터 레이어 내부.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE routes across three providers: Anthropic, OpenAI (including
              the ChatGPT subscription OAuth lane), and GLM. This page covers where keys and
              settings live, the order the effective model resolves in, and how
              to debug when a change does not take.
            </p>

            <h2>Three-provider routing</h2>
            <p>
              The model id prefix decides the provider. The routing SoT is the
              shipped manifest <code>core/config/routing.toml</code>, overridden
              section by section from <code>~/.geode/routing.toml</code>.
            </p>
            <table>
              <thead>
                <tr><th>Provider</th><th>Default models</th><th>Routing rule</th><th>Auth lanes</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Anthropic</td>
                  <td><code>claude-opus-4-8</code> (secondary <code>claude-sonnet-4-6</code>, budget <code>claude-haiku-4-5-20251001</code>)</td>
                  <td><code>claude-</code> prefix</td>
                  <td>Subscription OAuth (claude CLI keychain) or <code>ANTHROPIC_API_KEY</code></td>
                </tr>
                <tr>
                  <td>OpenAI / Codex</td>
                  <td><code>gpt-5.5</code></td>
                  <td><code>gpt-</code>, <code>o3-</code>, <code>o4-</code> prefixes. Exception: <code>gpt-5.5</code>, <code>gpt-5.5-pro</code>, and <code>-codex</code> suffixed models route only to the Codex OAuth backend. <code>gpt-5.6-sol/terra/luna</code> are dual-lane — login state (API key ↔ subscription OAuth) picks the backend</td>
                  <td>ChatGPT subscription OAuth (<code>~/.codex/auth.json</code>) or <code>OPENAI_API_KEY</code></td>
                </tr>
                <tr>
                  <td>GLM (ZhipuAI)</td>
                  <td><code>glm-5.2</code> (free tier <code>glm-4.7-flash</code>)</td>
                  <td><code>glm-</code> prefix</td>
                  <td><code>ZAI_API_KEY</code>. Coding Plan and PAYG endpoints are separate.</td>
                </tr>
              </tbody>
            </table>
            <p>
              One adapter is registered per (provider, credential source) pair
              (<code>core/llm/adapters/</code>). <code>geode adapters list</code>
              shows what is registered and whether its credentials are present.
            </p>

            <h2>Where keys and settings live</h2>
            <p>Roles are split by file. Keys in .env, behavior in config.toml.</p>
            <table>
              <thead>
                <tr><th>File</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>~/.geode/.env</code></td>
                  <td>Secrets only. <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>ZAI_API_KEY</code>. A project-level <code>.env</code> beats the global one.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/config.toml</code></td>
                  <td>Durable global behavior. Model choice, effort, and login source persist here.</td>
                </tr>
                <tr>
                  <td><code>.geode/config.toml</code></td>
                  <td>Per-project overrides. The default write target of <code>/model</code>.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/routing.toml</code></td>
                  <td>Routing-manifest overrides, including fallback-chain opt-in.</td>
                </tr>
              </tbody>
            </table>
            <p>
              Writing the model, effort, or login source to .env is retired.
              When an older release left a model line in .env, the
              <code>/model</code> picker removes it as it writes the toml and
              prints a &quot;removed stale ... from .env&quot; notice.
            </p>

            <h2>Model resolution order</h2>
            <p>Higher masks lower. The first layer with a value wins.</p>
            <pre>{`1. CLI arguments
2. env layer (os.environ + project .env + global .env)
3. project .geode/config.toml
4. global ~/.geode/config.toml
5. routing default (core/config/routing.toml)`}</pre>
            <figure>
              <img
                src="/geode/diagrams/model-resolution.svg"
                alt="Model resolution ladder: CLI argument, env layer, project config.toml, global config.toml, then the routing default; the first layer with a value wins"
              />
              <figcaption>The first layer with a value wins; geode config explain model shows which one did.</figcaption>
            </figure>
            <p>
              The serve daemon deliberately drops model-pick env keys at startup
              (<code>BEHAVIOR_ENV_KEYS</code>, <code>core/config/env_io.py</code>),
              so the toml choice wins for every daemon session. A
              <code>GEODE_MODEL</code> you export by hand stays a power-user
              override for that shell session.
            </p>

            <h2>The debugging flow: geode config explain</h2>
            <p>
              The standard diagnosis for &quot;I changed the config but nothing
              moved&quot; is <code>geode config explain model</code>. It prints
              a per-layer candidate table with file paths, marks exactly one
              layer WINNER, and marks every set lower layer masked.
            </p>
            <pre>{`geode config explain model    # which layer wins, and from which file
geode about                   # the EFFECTIVE model + provider`}</pre>
            <p>
              <code>geode about</code> shows the values actually in effect, and
              it leads with a one-line warning whenever an env layer masks a
              toml pick. Verify switches against <code>geode about</code>, never
              against config file contents.
            </p>

            <h2>Fallback policy: ships empty</h2>
            <p>
              <code>[model.fallbacks]</code> in <code>routing.toml</code> ships
              with every chain empty. When the primary model fails, GEODE does
              not silently swap models; it raises immediately (the fast-fail
              short-circuit in <code>core/llm/errors.py</code>), and picking a
              model in <code>/model</code> is the intended recovery. If you want
              a fallback chain, opt in by editing
              <code>~/.geode/routing.toml</code>.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Switched models, nothing changed</td>
                  <td>A higher layer masks the change (usually an old .env line or a shell export)</td>
                  <td>Run <code>geode config explain model</code>, find the WINNER layer, edit or remove its line.</td>
                </tr>
                <tr>
                  <td>Only the daemon answers with the old model</td>
                  <td>A model env var got pinned into the daemon's environment</td>
                  <td>Dropping model env keys at daemon startup is the default. <code>pkill -f &quot;geode serve&quot;</code> and restart. To pin the daemon's model via env on purpose, <code>GEODE_SERVE_KEEP_MODEL_ENV=1</code> is the escape hatch.</td>
                </tr>
                <tr>
                  <td>GLM subscription, yet metered billing</td>
                  <td>A Coding Plan key went out over the PAYG endpoint</td>
                  <td>The Coding Plan endpoint (<code>api.z.ai/api/coding/paas/v4</code>) and PAYG (<code>api.z.ai/api/paas/v4</code>) differ. Check which one your traffic uses.</td>
                </tr>
                <tr>
                  <td><code>gpt-5.5</code> fails on an API key</td>
                  <td>Codex-only model</td>
                  <td><code>gpt-5.5</code> and <code>gpt-5.5-pro</code> route only through the ChatGPT subscription OAuth lane (the <code>gpt-5.6</code> family also works on an API key). Log in with <code>/login openai</code>.</td>
                </tr>
              </tbody>
            </table>

            <h2>Configuration reference</h2>
            <ul>
              <li><a href="/geode/docs/config/basics">Configuration basics</a>. The full layer model.</li>
              <li><a href="/geode/docs/config/reference">config.toml reference</a>. Every key.</li>
              <li><a href="/geode/docs/runtime/auth">Auth and OAuth</a>. Profiles and rotation.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM routing</a>. Inside the adapter layer.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
