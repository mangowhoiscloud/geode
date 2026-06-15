import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Configuration basics — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="config/basics"
      title="Configuration basics"
      titleKo="설정 기초"
      summary="File roles after the config unification: .env for secrets, config.toml for behavior, one resolution ladder, and geode config explain as the debugging flow."
      summaryKo="config 통합 이후의 파일 역할입니다. .env는 시크릿, config.toml은 동작 설정, 해석 사다리는 하나, 디버깅은 geode config explain으로 합니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE 설정의 규칙은 한 줄입니다. 시크릿은 <code>.env</code>에,
              동작은 <code>config.toml</code>에 둡니다. 같은 키가 여러 층에
              있으면 더 가까운 층이 이기고, 어느 층이 이겼는지는
              <code>geode config explain</code>이 보여줍니다.
            </p>

            <h2>파일과 역할</h2>
            <table>
              <thead>
                <tr><th>파일</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>~/.geode/.env</code></td>
                  <td>전역 시크릿 층이자 권위를 갖는 시크릿 저장소. API 키와 자격 증명이 들어가고, 온보딩과 <code>/login</code>의 키 기록이 여기로 갑니다.</td>
                </tr>
                <tr>
                  <td>프로젝트 <code>.env</code> (cwd)</td>
                  <td>프로젝트 시크릿 층. 전역에 없는 키만 채우며 전역 키를 덮지 못합니다 (Hermes, 2026-06-15). 시크릿은 전역에 두는 것이 기본입니다.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/config.toml</code></td>
                  <td>전역 동작 설정. <code>[self_improving_loop.*]</code> 섹션도 이 파일에 삽니다.</td>
                </tr>
                <tr>
                  <td><code>.geode/config.toml</code></td>
                  <td>프로젝트 동작 설정. 전역 toml을 덮습니다. <code>/model</code>의 기본 저장 위치입니다.</td>
                </tr>
                <tr>
                  <td><code>core/config/routing.toml</code></td>
                  <td>출하되는 라우팅 매니페스트. 모델 기본값, provider prefix, 자격 패턴. <code>~/.geode/routing.toml</code>이 섹션 단위로 덮습니다.</td>
                </tr>
              </tbody>
            </table>
            <p>
              시크릿 전용 <code>.env</code>는 도구가 지키는 계약입니다.
              <code>/model</code>은 더 이상 <code>GEODE_MODEL</code>을
              <code>.env</code>에 쓰지 않고 <code>config.toml</code>에만
              기록합니다. 과거 릴리스가 남긴 <code>.env</code>의 모델 줄은
              피커가 toml을 쓴 직후 자동으로 지우고 알림을 출력합니다
              (<code>core/config/env_io.py</code>의 <code>remove_env</code>).
              toml 매핑이 없는 env 전용 키
              (<code>GEODE_GATEWAY_ENABLED</code> 등)를 손으로
              <code>.env</code>에 적는 것은 여전히 유효한 운영 방법입니다.
            </p>

            <h2>해석 사다리</h2>
            <p>
              모든 Settings 필드는 같은 사다리를 탑니다. 위가 이깁니다
              (<code>core/config/explain.py</code>의 <code>LAYERS</code>).
            </p>
            <pre>{`1. os.environ            셸 export. 세션 한정 수동 override
2. 전역 .env             ~/.geode/.env (시크릿 권위)
3. 프로젝트 .env          cwd의 .env (전역에 없는 키만 채움)
4. 프로젝트 config.toml   .geode/config.toml
5. 전역 config.toml      ~/.geode/config.toml
6. 코드 기본값`}</pre>
            <p>
              시크릿(<code>.env</code>)과 동작(<code>config.toml</code>)은 전역과
              프로젝트의 우선 방향이 반대입니다. <code>.env</code>는 전역이
              위(권위), <code>config.toml</code>은 프로젝트가 위(프로젝트 튜닝).
              같은 키가 양쪽에 동시에 들어가지 않으므로(시크릿 전용, 동작 전용
              분리, C-2) 사다리는 하나로 충분합니다. v0.99.216 이전에는
              <code>.env</code>도 프로젝트가 위였는데, 빈 프로젝트
              <code>.env</code>가 전역 실키를 가리는 함정이 있어 전역 권위로
              뒤집었습니다 (Hermes 정렬).
            </p>
            <p>
              모델 해석으로 좁히면 같은 사다리가 이렇게 읽힙니다. CLI 인자 &gt;
              env 층(os.environ + .env 파일들) &gt; 프로젝트 toml &gt; 전역
              toml &gt; routing 기본값. env 층이 toml 전부를 이기므로, 잊힌
              <code>.env</code> 줄 하나가 이후의 모든 toml 편집을 가립니다.
              이 구조의 대표 함정입니다.
            </p>
            <p>
              <code>GEODE_CONFIG_TOML</code> env 변수는 전역
              <code>config.toml</code>의 경로를 바꿉니다. C-4부터 메인 설정
              로더(<code>core/config/__init__.py</code>)와 self-improving
              로더(<code>core/config/self_improving.py</code>)가 같은 경로를
              읽습니다. 프로젝트 toml은 그 위에 그대로 얹힙니다.
            </p>

            <h2>geode config explain</h2>
            <p>
              &quot;설정을 바꿨는데 실효값이 안 움직인다&quot;의 표준 진단
              플로우입니다. 키마다 층별 후보 표를 출력하고, 정확히 하나의
              층을 <code>WINNER</code>로, 그 아래 설정된 층을
              <code>masked</code>로 표시합니다. 파일 경로까지 같이 나오므로
              어느 줄을 고치거나 지워야 하는지 바로 보입니다.
            </p>
            <pre>{`geode config explain model     # 키 생략 시 model
geode about                    # 실효 모델 + 마스크 경고 한 줄`}</pre>
            <p>
              검증은 항상 실효값으로 합니다. <code>geode about</code>이
              보여주는 모델이 실제로 호출되는 모델이고, env 층이 toml 선택을
              가리고 있으면 같은 화면에 경고가 뜹니다. config.toml 내용을
              읽는 것으로 검증을 끝내면 안 됩니다.
            </p>

            <h2>리로드 시맨틱</h2>
            <p>
              세션 경계에서 <code>reload_settings_from_disk()</code>가
              <code>.env</code>, <code>GEODE_*</code> env, config.toml을 살아
              있는 싱글톤에 다시 읽어 들입니다. 필드 복사가 실패하면 해당
              필드명을 적은 경고를 남기므로 반쯤 적용된 리로드가 조용히
              지나가지 않습니다. 리로드는
              <code>reload_routing_constants()</code>도 호출해 routing
              매니페스트 캐시를 비우고 <code>core.config</code>의 라우팅
              상수를 다시 묶습니다. 한계도 명시합니다. 모듈 로드 시점에 값을
              복사해 간 importer는 부트 시점 복사본을 계속 들고 있으므로,
              그 경로까지 갱신하려면 프로세스를 재시작해야 합니다.
            </p>

            <h2>데몬과 모델 env 키</h2>
            <p>
              serve 데몬은 시작할 때 상속받은 환경에서 동작(모델 선택) 계열
              env 키를 떨어뜨리고, <code>.env</code> 승격에서도 건너뜁니다
              (<code>core/cli/bootstrap.py</code>의
              <code>load_daemon_env</code>). 데몬 환경에 승격된 모델 키가
              모든 <code>/model</code> 전환보다 오래 살아남던 문제의
              수정입니다. 대상 키 목록은 <code>core/config/env_io.py</code>의
              <code>BEHAVIOR_ENV_KEYS</code>입니다.
            </p>
            <pre>{`GEODE_MODEL  GEODE_PLAN_MODEL  GEODE_ACT_MODEL  GEODE_JUDGE_MODEL
GEODE_COGNITIVE_REFLECTION_MODEL  GEODE_LEARNING_EXTRACT_MODEL
GEODE_AGENTIC_EFFORT
GEODE_ANTHROPIC_CREDENTIAL_SOURCE  GEODE_OPENAI_CREDENTIAL_SOURCE`}</pre>
            <p>
              데몬의 모델을 env로 일부러 고정하고 싶다면
              <code>GEODE_SERVE_KEEP_MODEL_ENV=1</code>을 켭니다. C-4부터 이
              플래그는 프로세스 env뿐 아니라 양쪽 <code>.env</code> 파일에서도
              읽힙니다. 승격 우선순위는 수동 export &gt; 전역 <code>.env</code>
              &gt; 프로젝트 <code>.env</code>이고 (전역이 권위, 프로젝트는 전역에
              없는 키만 채움), 파일은 이미 존재하는 프로세스 env를 덮지 않으며
              빈 값도 덮지 않습니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>/model</code>로 바꿨는데 그대로</td>
                  <td>env 층의 모델 줄이 toml을 마스크</td>
                  <td><code>geode config explain model</code>로 WINNER 층과 파일을 찾고 그 줄을 지웁니다. 최신 버전 피커는 다음 toml 기록 때 자동 정리합니다.</td>
                </tr>
                <tr>
                  <td>thin CLI는 새 모델, 데몬만 옛 모델</td>
                  <td><code>GEODE_SERVE_KEEP_MODEL_ENV=1</code>이 켜져 있거나 C-3 이전 데몬</td>
                  <td>플래그를 끄거나 데몬을 재시작합니다. <code>pkill -f &quot;geode serve&quot;</code> 후 재진입.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/routing.toml</code>을 고쳤는데 반영 안 됨</td>
                  <td>부트 시점 복사본을 든 모듈 경로</td>
                  <td>세션 리로드로 매니페스트 독자는 갱신됩니다. 그래도 남으면 프로세스를 재시작합니다.</td>
                </tr>
                <tr>
                  <td>프로젝트 <code>.env</code>에 둔 시크릿이 안 먹고 전역 값이 이김</td>
                  <td>전역 <code>~/.geode/.env</code>가 같은 키를 가짐. 전역이 권위입니다 (Hermes, 2026-06-15)</td>
                  <td>의도된 동작입니다. 시크릿은 전역에 두고, 프로젝트는 전역에 없는 키만 채웁니다. <code>geode config explain &lt;KEY&gt;</code>로 WINNER 층을 확인하세요.</td>
                </tr>
                <tr>
                  <td><code>GEODE_CONFIG_TOML</code>이 일부 로더에만 적용</td>
                  <td>C-4 이전에는 self-improving 로더만 인식</td>
                  <td>업그레이드합니다. <code>geode config explain</code>이 실제로 읽은 경로를 보고합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/config/reference">config.toml 레퍼런스</a>. 전체 키 목록입니다.</li>
              <li><a href="/geode/docs/runtime/auth">인증과 OAuth</a>. 시크릿 층에 무엇이 들어가는지 다룹니다.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM 라우팅</a>. routing.toml이 소비되는 곳입니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE configuration follows one rule. Secrets live in
              <code>.env</code>, behavior lives in <code>config.toml</code>.
              When the same key exists in several layers, the closer layer
              wins, and <code>geode config explain</code> shows you which one
              won.
            </p>

            <h2>Files and roles</h2>
            <table>
              <thead>
                <tr><th>File</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>~/.geode/.env</code></td>
                  <td>Global secrets layer, the authoritative secret store. API keys and credentials; onboarding and <code>/login</code> write keys here.</td>
                </tr>
                <tr>
                  <td>Project <code>.env</code> (cwd)</td>
                  <td>Project secrets layer. Fills only the keys the global file lacks; it never shadows a global key (Hermes, 2026-06-15). Keep secrets in the global file by default.</td>
                </tr>
                <tr>
                  <td><code>~/.geode/config.toml</code></td>
                  <td>Global behavior settings. Also hosts the <code>[self_improving_loop.*]</code> sections.</td>
                </tr>
                <tr>
                  <td><code>.geode/config.toml</code></td>
                  <td>Project behavior settings. Outranks the global toml. Default write target of <code>/model</code>.</td>
                </tr>
                <tr>
                  <td><code>core/config/routing.toml</code></td>
                  <td>Shipped routing manifest: model defaults, provider prefixes, credential patterns. <code>~/.geode/routing.toml</code> overrides it section by section.</td>
                </tr>
              </tbody>
            </table>
            <p>
              &quot;Secrets-only <code>.env</code>&quot; is a contract the
              tools keep. <code>/model</code> no longer writes
              <code>GEODE_MODEL</code> to <code>.env</code>; it persists to
              <code>config.toml</code> only. Model lines left behind by older
              releases are auto-removed right after the picker&apos;s toml
              write, with a printed notice (<code>remove_env</code> in
              <code>core/config/env_io.py</code>). Hand-writing env-only keys
              that have no toml mapping (<code>GEODE_GATEWAY_ENABLED</code>
              and friends) into <code>.env</code> remains a valid operator
              move.
            </p>

            <h2>The resolution ladder</h2>
            <p>
              Every Settings field rides the same ladder. Higher wins
              (<code>LAYERS</code> in <code>core/config/explain.py</code>).
            </p>
            <pre>{`1. os.environ            shell exports. session-scoped manual override
2. global .env           ~/.geode/.env (authoritative secrets)
3. project .env          .env in the cwd (fills only keys global lacks)
4. project config.toml   .geode/config.toml
5. global config.toml    ~/.geode/config.toml
6. code default`}</pre>
            <p>
              Secrets (<code>.env</code>) and behavior
              (<code>config.toml</code>) order global vs project in opposite
              directions. For <code>.env</code> the global file is higher
              (authoritative); for <code>config.toml</code> the project file is
              higher (project tuning). The same key never appears in both
              layers (secrets-only, behavior-only, C-2), so one ladder is
              enough. Before
              v0.99.216 the <code>.env</code> pair was also project-first, but an
              empty project <code>.env</code> could shadow a real global key, so
              it was flipped to global-authoritative (the Hermes alignment).
            </p>
            <p>
              Narrowed to model resolution, the same ladder reads: CLI args
              &gt; env layer (os.environ plus both .env files) &gt; project
              toml &gt; global toml &gt; routing default. Because the env
              layer outranks every toml, a single forgotten <code>.env</code>
              line masks all future toml edits. That is the classic trap this
              design removes from the tools and leaves only to deliberate
              hands.
            </p>
            <p>
              The <code>GEODE_CONFIG_TOML</code> env var redirects the global
              <code>config.toml</code> path. Since C-4 both the main settings
              loader (<code>core/config/__init__.py</code>) and the
              self-improving loader
              (<code>core/config/self_improving.py</code>) honor it, so the
              variable has one meaning. The project toml still overlays on
              top.
            </p>

            <h2>geode config explain</h2>
            <p>
              The standard diagnosis for &quot;I changed the config but the
              effective value did not move&quot;. For a key it prints a
              per-layer candidate table, marks exactly one layer as
              <code>WINNER</code> and every set lower layer as
              <code>masked</code>, with file paths, so you see exactly which
              line to edit or remove.
            </p>
            <pre>{`geode config explain model     # key defaults to model
geode about                    # effective model + one-line mask warning`}</pre>
            <p>
              Always verify against the effective state. The model
              <code>geode about</code> reports is the model that gets called,
              and the same screen warns when an env layer masks a toml pick.
              Reading config.toml content is not verification.
            </p>

            <h2>Reload semantics</h2>
            <p>
              At session boundaries <code>reload_settings_from_disk()</code>
              re-reads <code>.env</code>, <code>GEODE_*</code> env, and
              config.toml into the live singleton. A per-field copy failure
              logs a warning naming the field, so a half-applied reload never
              passes silently. The reload also calls
              <code>reload_routing_constants()</code>, clearing the
              routing-manifest cache and rebinding the routing constants on
              <code>core.config</code>. The honest limit: importers that
              copied values at module load time still hold boot-time copies.
              Restart the process to refresh those paths.
            </p>

            <h2>The daemon and model env keys</h2>
            <p>
              At startup the serve daemon drops behavior (model-pick) env
              keys from its inherited environment and skips them during
              <code>.env</code> promotion (<code>load_daemon_env</code> in
              <code>core/cli/bootstrap.py</code>). This fixes the failure
              where a model key promoted into the daemon&apos;s environment
              outlived every <code>/model</code> switch. The key list is
              <code>BEHAVIOR_ENV_KEYS</code> in
              <code>core/config/env_io.py</code>.
            </p>
            <pre>{`GEODE_MODEL  GEODE_PLAN_MODEL  GEODE_ACT_MODEL  GEODE_JUDGE_MODEL
GEODE_COGNITIVE_REFLECTION_MODEL  GEODE_LEARNING_EXTRACT_MODEL
GEODE_AGENTIC_EFFORT
GEODE_ANTHROPIC_CREDENTIAL_SOURCE  GEODE_OPENAI_CREDENTIAL_SOURCE`}</pre>
            <p>
              To pin the daemon&apos;s model via env on purpose, set
              <code>GEODE_SERVE_KEEP_MODEL_ENV=1</code>. Since C-4 the flag is
              honored from the process env or from either <code>.env</code>
              file. Promotion precedence is manual exports &gt; global
              <code>.env</code> &gt; project <code>.env</code> (global is
              authoritative; the project file only fills keys global lacks);
              files never clobber pre-existing process env, and empty values
              never clobber anything.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>/model</code> switch does not stick</td>
                  <td>A model line in the env layer masks the toml</td>
                  <td>Run <code>geode config explain model</code>, find the WINNER layer and file, remove the line. Current pickers also auto-clean it on the next toml write.</td>
                </tr>
                <tr>
                  <td>Thin CLI sees the new model, the daemon keeps the old one</td>
                  <td><code>GEODE_SERVE_KEEP_MODEL_ENV=1</code> is set, or a pre-C-3 daemon</td>
                  <td>Unset the flag or restart the daemon: <code>pkill -f &quot;geode serve&quot;</code>, then re-enter.</td>
                </tr>
                <tr>
                  <td>Edits to <code>~/.geode/routing.toml</code> do not land</td>
                  <td>A module path holding a boot-time copy</td>
                  <td>Session reload refreshes manifest readers. If a path still lags, restart the process.</td>
                </tr>
                <tr>
                  <td>A secret set in the project <code>.env</code> is ignored and the global value wins</td>
                  <td>The global <code>~/.geode/.env</code> holds the same key, and global is authoritative (Hermes, 2026-06-15)</td>
                  <td>This is intended. Keep secrets in the global file; the project file only fills keys global lacks. Run <code>geode config explain &lt;KEY&gt;</code> to see the WINNER layer.</td>
                </tr>
                <tr>
                  <td><code>GEODE_CONFIG_TOML</code> only applies to some loaders</td>
                  <td>Before C-4 only the self-improving loader honored it</td>
                  <td>Upgrade. <code>geode config explain</code> reports the path actually read.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/config/reference">config.toml reference</a>. The full key inventory.</li>
              <li><a href="/geode/docs/runtime/auth">Auth and OAuth</a>. What goes into the secrets layer.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM routing</a>. Where routing.toml is consumed.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
