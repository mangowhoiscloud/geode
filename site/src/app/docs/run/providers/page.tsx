import Image from "next/image";
import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Configure Providers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/providers"
      title="Configure providers"
      titleKo="프로바이더 설정"
      summary="Four explicit provider routes, where keys and behavior settings live, and how the effective model is resolved."
      summaryKo="4개 명시적 프로바이더 경로, 키와 동작 설정의 위치, 실효 모델 결정 순서."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 Anthropic, OpenAI(ChatGPT 구독 OAuth 레인 포함), OpenRouter,
              GLM 네 프로바이더 경로를 명시적으로 라우팅합니다. 이 페이지는 키와 설정이 어디에
              저장되는지, 모델이 어떤 순서로 결정되는지, 막혔을 때 어떻게
              디버깅하는지 다룹니다.
            </p>

            <h2>4개 명시적 프로바이더 경로</h2>
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
                  <td><code>claude-opus-5-5</code> (보조 <code>claude-sonnet-5</code>, 저비용 <code>claude-haiku-4-5-20251001</code>)</td>
                  <td><code>claude-</code> 접두사</td>
                  <td><code>ANTHROPIC_API_KEY</code></td>
                </tr>
                <tr>
                  <td>OpenAI / Codex</td>
                  <td><code>gpt-6-sol</code></td>
                  <td><code>gpt-</code>, <code>o3-</code>, <code>o4-</code> 접두사. <code>-codex</code> 접미사는 기존 provider 별칭으로 해석하며, 실제 API 키 또는 구독 경로는 선택한 자격 소스를 따릅니다. 모델별 지원·퇴역은 소스마다 다르고, 카탈로그 등록은 계정 접근 증거가 아닙니다.</td>
                  <td>ChatGPT 구독 OAuth(<code>~/.codex/auth.json</code>) 또는 <code>OPENAI_API_KEY</code></td>
                </tr>
                <tr>
                  <td>OpenRouter</td>
                  <td><code>openrouter/openrouter/free</code>, <code>openrouter/openrouter/auto</code> 또는 정확한 catalogue id</td>
                  <td><code>openrouter/&lt;publisher&gt;/&lt;model&gt;</code>. 외부 namespace 하나를 제거해 OpenRouter에 전달</td>
                  <td><code>OPENROUTER_API_KEY</code>. 크레딧 기반 PAYG이며 direct provider와 동치 폴백하지 않습니다.</td>
                </tr>
                <tr>
                  <td>GLM (ZhipuAI)</td>
                  <td><code>glm-5.3</code> (무료 티어 <code>glm-4.7-flash</code>)</td>
                  <td><code>glm-</code> 접두사</td>
                  <td><code>ZAI_API_KEY</code>. PAYG API 경로입니다. 현재 Coding Plan 정책에서 GEODE 사용 자격은 확인되지 않아 구독 실행을 차단합니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              (프로바이더, 자격 소스) 조합마다 어댑터가 하나씩 등록됩니다
              (<code>core/llm/adapters/</code>). <code>geode adapters list</code>로
              현재 등록 상태, API transport, billing, 자격 환경을 확인할 수 있습니다.
            </p>
            <p>
              OpenRouter는 OpenAI의 별칭이 아니라 별도 inference router입니다.{" "}
              <code>/login add</code>로 키를 등록하고{" "}
              <code>/model openrouter/anthropic/claude-sonnet-4</code>처럼 정확한
              참조를 선택합니다. 응답의 <code>usage.cost</code>가 예산·사용량
              기록의 권위이고, 반환 모델·선택 provider·routing attempt는 bounded
              LLM-call event에 남습니다. <code>free</code>/<code>auto</code>는 동적
              경로이므로 고정 모델 공식 평가에 사용하지 않습니다.
            </p>

            <p>활성 모델과 별칭, 문맥·출력 한도, API 요율은 <a href="https://github.com/mangowhoiscloud/geode/blob/develop/docs/research/provider-refresh-20260924.md">2026-09-24 공급자 조사</a>에서 원문 출처와 함께 확인할 수 있습니다. API 달러 요율과 Codex·Coding Plan의 크레딧은 별개이며, 카탈로그 갱신이 실제 계정 수락이나 청구 검증을 뜻하지 않습니다.</p>

            <h2>소스별 모델 지원 종료</h2>
            <p>
              2026-09-24 확인: Codex의 ChatGPT 로그인 경로에서
              <code>gpt-5.2</code>·<code>gpt-5.3-codex</code>는 폐기되었고,
              <code>gpt-5.4</code>·<code>gpt-5.4-mini</code>는 8월 31일 지원이
              끝났습니다. 이 경로의 선택·요청은 차단하지만 유효한 API 사용과
              과거 요금·평가 기록은 보존합니다. <code>gpt-5.5</code>의 구독
              퇴역 예정일은 10월 14일입니다. 신규 구독 선택지에서는 빼되 기존 명시적 설정을 이미 퇴역한 것으로 처리하지 않습니다.
              근거는 <a href="https://learn.chatgpt.com/docs/models#deprecated-codex-models">공식 Codex 모델 안내</a>입니다.
            </p>
            <p>
              Anthropic 공식 API에서도 지원이 끝난 Opus 4.1·Opus 4·Sonnet 4와
              이전 세대를 네트워크 요청 전에 거절합니다. 현재 지원되는 4.5 이상
              모델은 유지하며, 이 퇴역 일정을 OpenRouter 등 다른 운영사의 경로에
              일괄 적용하지 않으며 실제 클라이언트의 endpoint를 확인합니다. <a href="https://platform.claude.com/docs/en/about-claude/model-deprecations">공식 모델 수명주기</a>를
              2026-09-24에 확인했으며, 계정별 실제 접근 권한은 별도 검증 대상입니다.
            </p>
            <h2>키와 설정이 사는 곳</h2>
            <p>역할이 파일별로 분리되어 있습니다. 키와 프로필은 로컬 비밀 파일, 동작은 config.toml에 둡니다.</p>
            <table>
              <thead>
                <tr><th>파일</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>~/.geode/.env</code></td>
                  <td>시크릿 전용 평문 파일(<code>0600</code>). <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>OPENROUTER_API_KEY</code>, <code>ZAI_API_KEY</code>. 전역 파일이 권위를 가지며 프로젝트 <code>.env</code>는 빠진 값만 채웁니다.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/auth.toml</code></td>
                  <td>Plan/Profile 메타데이터와 GEODE가 관리하는 자격증명 평문 파일(<code>0600</code>). 외부 CLI가 관리하는 자격증명은 복제하지 않습니다.</td>
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
              이 두 비밀 파일은 Git에서 제외되고 읽기·쓰기 때 소유자 전용 권한을
              강제하지만 OS Keychain은 아닙니다. 같은 사용자 권한으로 실행되는
              프로세스까지 격리하지는 못하므로 공유·비신뢰 호스트에서는 환경
              주입 또는 전용 secret manager를 사용합니다. Google Workspace OAuth의
              OS keyring 저장소는 이 LLM API-key 경로와 별개입니다.
            </p>
            <p>
              모델, effort, 로그인 소스를 .env에 적는 방식은 폐기되었습니다.
              예전 버전이 남긴 .env의 모델 줄은 <code>/model</code>이 toml에
              쓰면서 자동으로 지우고 &quot;removed stale ... from .env&quot;
              안내를 출력합니다.
            </p>

            <h2>실행 중 세션과 새 세션의 기본값</h2>
            <p>
              저장한 모델·effort·인증 설정은 새 세션의 기본값입니다. 실행 중인 세션은
              승인된 모델·effort·API/구독 소스를 보존합니다. 연결된 CLI의{" "}
              <code>/login source</code>는 해당 세션의 적용 응답을 받은 뒤 기본값을
              저장하며, 연결되지 않은 명령은 새 세션의 기본값만 바꿉니다.
            </p>
            <p>
              명시적 로그인 소스와 <code>forced_login_method</code>가 충돌하면 거절합니다.
              모델별 plan 순서와 계정 선택은 SDK 요청에도 적용됩니다. 선택한 소스의
              계정을 사용할 수 없어도 다른 과금 소스로 자동 전환하지 않습니다.
              <code>/login use</code>와 <code>/login route</code>는 같은 소스 안에서
              다음 요청의 계정을 바꿀 수 있으며, 실행 중 세션의 소스를 바꾸지는 않습니다.
            </p>

            <h2>모델 결정 순서</h2>
            <p>위가 아래를 가립니다. 첫 번째로 값이 설정된 레이어가 이깁니다.</p>
            <pre>{`1. CLI 인자
2. env 레이어 (os.environ + project .env + global .env)
3. 프로젝트 .geode/config.toml
4. 전역 ~/.geode/config.toml
5. 라우팅 기본값 (core/config/routing.toml)`}</pre>
            <figure>
              <Image
                width={741}
                height={579}
                src="/geode/diagrams/model-resolution.svg"
                alt="Model resolution ladder: CLI argument, env layer, project config.toml, global config.toml, then the routing default; the first layer with a value wins"
              />
              <figcaption>값이 설정된 첫 레이어가 이깁니다. 어느 레이어가 이겼는지는 geode config explain model이 보여줍니다.</figcaption>
            </figure>
            <p>
              데몬은 시작할 때 모델 계열 env 키를 의도적으로 버리므로
              (<code>BEHAVIOR_ENV_KEYS</code>, <code>core/config/env_io.py</code>),
              새 세션은 유효한 설정에서 시작합니다. 기존 세션은 승인된 선택을 유지합니다.
              셸에서 직접 export한
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
              한 줄을 먼저 띄웁니다. 전환 검증은 항상 실효 설정을 보여 주는{" "}
              <code>geode about</code>을 기준으로 합니다.
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

            <h2>재시도 경계</h2>
            <p>
              <code>llm_max_retries</code>는 최초 호출을 포함한 모델별 총 시도
              횟수입니다(기본 3). 메인 에이전트 루프, 보조 호출, scaffold-search
              mutator가 같은 설정을 사용하지만 각 논리 호출은 별도 예산을 가집니다.
              SDK 자체 재시도는 0으로 두어 두 계층의 횟수가 곱해지지 않게 합니다.
            </p>
            <p>
              연결 실패, timeout, 408/409, 일시적 429, 5xx만 jitter backoff로
              재시도합니다. <code>retry-after-ms</code>와 숫자/HTTP-date 형식의
              <code>Retry-After</code>를 존중하되 60초를 넘는 대기는 즉시
              사용자에게 돌려줍니다. 인증·잘못된 요청·결제 소진과 이미 출력이
              보인 stream 중단은 재호출하지 않습니다.
            </p>
            <p>
              이 호출 예산은 도구 재실행 권한이 아닙니다. 로컬 부작용은 durable
              effect receipt로 완료 여부를 확인하고, MCP 재접속은 서버가
              <code>readOnlyHint</code> 또는 <code>idempotentHint</code>를 선언한
              도구만 재호출합니다. scaffold-search의 <code>--mc</code>는
              반복적/무효 후보의 의미적 재제안 횟수이며 네트워크 재시도가 아닙니다.
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
                  <td>데몬은 시작 시 모델 계열 env 키를 버리는 것이 기본입니다. <code>geode stop</code>으로 해당 데몬을 종료한 뒤 <code>geode serve</code>로 시작합니다. 데몬 모델을 env로 일부러 고정하려면 <code>GEODE_SERVE_KEEP_MODEL_ENV=1</code>을 설정합니다.</td>
                </tr>
                <tr>
                  <td>GLM Coding Plan 실행 차단</td>
                  <td>공식 지원 도구로 사용 범위 제한</td>
                  <td>기존 구독 프로필은 보존합니다. API를 쓰려면 PAYG 소스를 명시적으로 선택합니다. GEODE는 과금 소스를 자동 전환하지 않습니다.</td>
                </tr>
                <tr>
                  <td>저장된 구독 모델을 선택할 수 없음</td>
                  <td>해당 소스에서 지원이 종료되었거나 폐기됨</td>
                  <td>현재 지원되는 모델을 명시적으로 다시 선택합니다. GEODE는 다른 모델이나 PAYG로 자동 전환하지 않습니다. API 지원과 구독 지원은 별개입니다.</td>
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
              GEODE exposes four explicit provider routes: Anthropic, OpenAI
              (including the ChatGPT subscription OAuth lane), OpenRouter, and GLM. This page covers where keys and
              settings live, the order the effective model resolves in, and how
              to debug when a change does not take.
            </p>

            <h2>Four explicit provider routes</h2>
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
                  <td><code>claude-opus-5-5</code> (secondary <code>claude-sonnet-5</code>, budget <code>claude-haiku-4-5-20251001</code>)</td>
                  <td><code>claude-</code> prefix</td>
                  <td><code>ANTHROPIC_API_KEY</code></td>
                </tr>
                <tr>
                  <td>OpenAI / Codex</td>
                  <td><code>gpt-6-sol</code></td>
                  <td><code>gpt-</code>, <code>o3-</code>, <code>o4-</code> prefixes. The <code>-codex</code> suffix retains a legacy provider alias; the actual route follows the selected API-key or subscription source. Support and retirement are source-specific; catalog presence does not establish account access.</td>
                  <td>ChatGPT subscription OAuth (<code>~/.codex/auth.json</code>) or <code>OPENAI_API_KEY</code></td>
                </tr>
                <tr>
                  <td>OpenRouter</td>
                  <td><code>openrouter/openrouter/free</code>, <code>openrouter/openrouter/auto</code>, or an exact catalogue id</td>
                  <td><code>openrouter/&lt;publisher&gt;/&lt;model&gt;</code>; GEODE strips one outer namespace before sending the request</td>
                  <td><code>OPENROUTER_API_KEY</code>. Credit-backed PAYG; never equivalent-fallbacks to a direct provider.</td>
                </tr>
                <tr>
                  <td>GLM (ZhipuAI)</td>
                  <td><code>glm-5.3</code> (free tier <code>glm-4.7-flash</code>)</td>
                  <td><code>glm-</code> prefix</td>
                  <td><code>ZAI_API_KEY</code>. PAYG API route. GEODE admission under the current Coding Plan policy is unestablished, so subscription execution is blocked.</td>
                </tr>
              </tbody>
            </table>
            <p>
              One adapter is registered per (provider, credential source) pair
              (<code>core/llm/adapters/</code>). <code>geode adapters list</code>
              shows each registered API transport, billing route, and credential
              status.
            </p>
            <p>
              OpenRouter is a distinct inference router, not an OpenAI alias. Add
              its key with <code>/login add</code>, then select an exact reference
              such as <code>/model openrouter/anthropic/claude-sonnet-4</code>.
              Response <code>usage.cost</code> is authoritative for budgets and
              usage records; returned model, selected provider, and routing attempt
              are retained in the bounded LLM-call event. Dynamic{" "}
              <code>free</code>/<code>auto</code> routes are not fixed-model official
              evaluation targets.
            </p>

            <p>See the <a href="https://github.com/mangowhoiscloud/geode/blob/develop/docs/research/provider-refresh-20260924.md">2026-09-24 provider audit</a> for active models, aliases, context/output limits and API tariffs with primary sources. API dollar prices and subscription credits are separate; a catalogue refresh does not establish live account acceptance or billed charges.</p>

            <h2>Source-specific model retirement</h2>
            <p>
              Checked 2026-09-24: on the ChatGPT-sign-in Codex route,
              <code>gpt-5.2</code> and <code>gpt-5.3-codex</code> are deprecated;
              <code>gpt-5.4</code> and <code>gpt-5.4-mini</code> retired on August 31.
              GEODE blocks selection and requests on that source while retaining
              valid API routes and historical pricing/evaluation records.
              <code>gpt-5.5</code> is scheduled to retire on October 14, so it is
              not retired yet. It is omitted from new subscription choices while existing explicit settings remain readable and executable until that boundary. See the <a href="https://learn.chatgpt.com/docs/models#deprecated-codex-models">official Codex model guidance</a>.
            </p>
            <p>
              The official Anthropic API similarly rejects confirmed retired Opus
              4.1, Opus 4, Sonnet 4, and older families before network submission.
              Active 4.5+ models remain available. These dates do not govern
              independently operated routes such as OpenRouter; admission checks
              the actual client endpoint. The{" "}
              <a href="https://platform.claude.com/docs/en/about-claude/model-deprecations">official model lifecycle</a>{" "}
              was checked on 2026-09-24; account entitlement still requires its
              own verification.
            </p>
            <h2>Where keys and settings live</h2>
            <p>Roles are split by file. Keys and profiles live in local secret files; behavior lives in config.toml.</p>
            <table>
              <thead>
                <tr><th>File</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>~/.geode/.env</code></td>
                  <td>Secrets-only plaintext file (<code>0600</code>). <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>OPENROUTER_API_KEY</code>, <code>ZAI_API_KEY</code>. The global file is authoritative; a project <code>.env</code> only fills missing values.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/auth.toml</code></td>
                  <td>Plan/Profile metadata and GEODE-managed credentials in an owner-only plaintext file (<code>0600</code>). Credentials owned by external CLIs are not copied.</td>
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
              Both secret files are Git-ignored and forced to owner-only mode
              when read or written, but they are not OS Keychain storage. They
              do not isolate a process already running as the same user; use
              environment injection or a dedicated secret manager on shared or
              untrusted hosts. The Google Workspace OAuth keyring is a separate
              path from these LLM API keys.
            </p>
            <p>
              Writing the model, effort, or login source to .env is retired.
              When an older release left a model line in .env, the
              <code>/model</code> picker removes it as it writes the toml and
              prints a &quot;removed stale ... from .env&quot; notice.
            </p>

            <h2>Live sessions and future defaults</h2>
            <p>
              Saved model, effort and credential settings seed new sessions. A live
              session keeps its admitted model, effort and API/subscription source.
              A connected <code>/login source</code> command requires the session&apos;s
              applied acknowledgment before saving defaults; a disconnected command
              changes defaults for future sessions only.
            </p>
            <p>
              An explicit credential source conflicting with <code>forced_login_method</code>
              is rejected. Model plan order and account selection also govern SDK
              requests. An unavailable account never authorizes switching billing sources.
              <code>/login use</code> and <code>/login route</code> can change the next
              account within the selected source, while the live source remains fixed.
            </p>

            <h2>Model resolution order</h2>
            <p>Higher masks lower. The first layer with a value wins.</p>
            <pre>{`1. CLI arguments
2. env layer (os.environ + project .env + global .env)
3. project .geode/config.toml
4. global ~/.geode/config.toml
5. routing default (core/config/routing.toml)`}</pre>
            <figure>
              <Image
                width={741}
                height={579}
                src="/geode/diagrams/model-resolution.svg"
                alt="Model resolution ladder: CLI argument, env layer, project config.toml, global config.toml, then the routing default; the first layer with a value wins"
              />
              <figcaption>The first layer with a value wins; geode config explain model shows which one did.</figcaption>
            </figure>
            <p>
              The serve daemon deliberately drops model-pick env keys at startup
              (<code>BEHAVIOR_ENV_KEYS</code>, <code>core/config/env_io.py</code>),
              so new sessions start from effective settings. Existing sessions retain
              their admitted choices. A <code>GEODE_MODEL</code> you export by hand stays a power-user
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

            <h2>Retry boundaries</h2>
            <p>
              <code>llm_max_retries</code> is the total attempts per model,
              including the initial call (default 3). The main agent loop,
              auxiliary calls, and scaffold-search mutator read the same setting,
              while each logical call keeps its own budget. SDK retries stay at
              zero so two retry layers cannot multiply the attempt count.
            </p>
            <p>
              Only connection failures, timeouts, 408/409, transient 429, and
              5xx responses use jittered backoff. GEODE honors
              <code>retry-after-ms</code> and numeric/HTTP-date
              <code>Retry-After</code>, but surfaces waits above 60 seconds instead
              of silently blocking. Authentication, invalid requests, depleted
              billing, and a stream failure after visible output are not replayed.
            </p>
            <p>
              This call budget does not authorize tool replay. Local effects use
              durable effect receipts to distinguish committed from uncertain
              work; MCP reconnect retries only tools declaring
              <code>readOnlyHint</code> or <code>idempotentHint</code>.
              Scaffold-search <code>--mc</code> counts semantic re-proposals of
              repetitive/invalid candidates, not network retries.
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
                  <td>A model env var got pinned into the daemon’s environment</td>
                  <td>Dropping model env keys at daemon startup is the default. Stop the managed daemon with <code>geode stop</code>, then start it with <code>geode serve</code>. To pin the daemon’s model via env on purpose, set <code>GEODE_SERVE_KEEP_MODEL_ENV=1</code>.</td>
                </tr>
                <tr>
                  <td>GLM Coding Plan execution blocked</td>
                  <td>Use restricted to officially supported tools</td>
                  <td>Existing subscription profiles are preserved. Select PAYG explicitly for API use; GEODE never switches billing sources automatically.</td>
                </tr>
                <tr>
                  <td>A saved subscription model is unavailable</td>
                  <td>Support on that source ended or was deprecated</td>
                  <td>Explicitly choose a currently supported model. GEODE does not switch models or move to PAYG automatically. API and subscription support are separate contracts.</td>
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
