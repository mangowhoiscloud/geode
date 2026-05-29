import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Configuration basics — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="config/basics"
      title="Configuration basics"
      titleKo="설정 기초"
      summary="Where configuration lives, how it loads, and how overrides resolve."
      summaryKo="설정이 어디에 있고, 어떻게 로드되고, override가 어떻게 결정되는지 설명합니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 이 페이지를 먼저 읽나</h2>
            <p>
              GEODE는 코드를 고치지 않고 동작을 바꿀 수 있어야 합니다. 모델, 예산,
              메신저 바인딩 같은 값은 설정에서 옵니다. 그래서 키 하나하나를 외우기
              전에, 설정이 어디에 살고 어떤 순서로 합쳐지는지부터 잡아야 합니다.
              전체 키 목록은 <a href="/geode/docs/config/reference">config.toml 레퍼런스</a>에
              있습니다. 이 페이지는 그 레퍼런스를 읽기 위한 지도입니다.
            </p>

            <h2>설정이 사는 곳</h2>
            <p>
              GEODE는 네 곳에서 설정을 읽습니다. 같은 키가 여러 곳에 있으면, 더 가까운
              곳이 이깁니다.
            </p>
            <ul>
              <li><strong>CLI 인자</strong>. 한 번의 실행에만 적용됩니다.</li>
              <li><strong>환경 변수와 <code>.env</code></strong>. 모든 변수는 <code>GEODE_</code> 접두사를 씁니다. 예를 들어 <code>GEODE_MODEL</code>이 <code>model</code> 키를 덮습니다. <code>.env</code> 파일은 현재 디렉터리의 <code>.env</code>와 <code>~/.geode/.env</code> 두 곳에서 읽습니다.</li>
              <li><strong>프로젝트 TOML</strong>. <code>.geode/config.toml</code>. 워크스페이스마다 다른 설정을 둘 때 씁니다.</li>
              <li><strong>전역 TOML</strong>. <code>~/.geode/config.toml</code>. 모든 프로젝트에 공통으로 적용할 기본값입니다.</li>
            </ul>
            <p>
              어느 파일도 필수가 아닙니다. 넷 다 없으면 GEODE는 코드 안의 기본값으로
              동작합니다.
            </p>

            <h2>해석 순서</h2>
            <p>
              우선순위는 높은 것부터 낮은 것까지 다음과 같습니다.
            </p>
            <pre>{`CLI 인자
  > 환경 변수 / .env (GEODE_*)
    > 프로젝트 .geode/config.toml
      > 전역 ~/.geode/config.toml
        > 코드 기본값`}</pre>
            <p>
              읽는 방식이 두 갈래라는 점이 중요합니다. 환경 변수와 <code>.env</code>는
              설정 객체를 만들 때 곧바로 로드됩니다. TOML 값은 그 뒤에 얹히되,
              <strong>환경 변수로 이미 정해진 키는 건너뜁니다</strong>. 그래서 환경
              변수가 항상 TOML보다 셉니다. 환경 변수로 모델을 고정해 두면 <code>config.toml</code>의
              모델 값은 무시됩니다.
            </p>
            <p>
              TOML에서 코드가 모르는 키는 조용히 무시됩니다. 매핑된 키만 적용되므로,
              오타가 난 키는 효과 없이 지나갑니다. 레퍼런스에 적힌 이름을 그대로
              쓰세요.
            </p>

            <h2>로드 시점</h2>
            <p>
              설정은 싱글턴입니다. 처음 누군가 설정을 요청할 때 한 번 만들어지고,
              그 뒤로는 같은 객체가 재사용됩니다. 무거운 의존성을 미루기 위해 이렇게
              지연 로드합니다. 디스크가 바뀌면 <code>reload_settings_from_disk()</code>가
              <code>.env</code>와 <code>config.toml</code>을 다시 읽어 살아 있는 싱글턴을
              제자리에서 갱신합니다. <code>geode serve</code> 데몬이 세션 경계에서 이
              경로를 타기 때문에, CLI에서 모델을 바꿔도 데몬이 디스크와 다시 맞춰집니다.
            </p>

            <h2>config.toml 첫 모양</h2>
            <p>
              값은 영역별 테이블로 묶입니다. 바꾸고 싶은 줄의 주석만 풀면 됩니다.
            </p>
            <pre>{`[llm]
primary_model = "claude-opus-4-7"
secondary_model = "gpt-5.4"

[pipeline]
confidence_threshold = 0.7
max_iterations = 5

[gateway]
time_budget_s = 300

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C12345"
auto_respond = true`}</pre>
            <p>
              <code>[[gateway.bindings.rules]]</code>는 메신저 채널 하나를 세션으로
              라우팅하는 규칙입니다. <code>channel_id</code>가 비면 그 규칙은 안전을 위해
              건너뜁니다. 빈 id는 모든 채널을 받는 위험한 catch-all이 되기 때문입니다.
              바인딩을 더 다루려면{" "}
              <a href="/geode/docs/guides/binding">바인딩 설정</a> 가이드를 보세요.
            </p>

            <h2>다음으로</h2>
            <ul>
              <li><a href="/geode/docs/config/reference">config.toml 레퍼런스</a>. 영역별 전체 키.</li>
              <li><a href="/geode/docs/run/providers">프로바이더 설정</a>. 키를 어디에 두는지.</li>
              <li><a href="/geode/docs/runtime/auth">인증과 OAuth</a>. 자격 증명 소스.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Why read this first</h2>
            <p>
              GEODE has to change behaviour without editing code. Values like the
              model, the budgets, and messaging bindings all come from
              configuration. So before memorising individual keys, get the shape
              right. Where configuration lives, and in what order the sources
              merge. The full key list is in the{" "}
              <a href="/geode/docs/config/reference">config.toml reference</a>.
              This page is the map for reading that reference.
            </p>

            <h2>Where configuration lives</h2>
            <p>
              GEODE reads configuration from four places. When the same key
              appears in more than one, the closer source wins.
            </p>
            <ul>
              <li><strong>CLI arguments</strong>. Apply to a single run.</li>
              <li><strong>Environment variables and <code>.env</code></strong>. Every variable uses the <code>GEODE_</code> prefix. For example, <code>GEODE_MODEL</code> overrides the <code>model</code> key. The <code>.env</code> file is read from both the current directory <code>.env</code> and <code>~/.geode/.env</code>.</li>
              <li><strong>Project TOML</strong>. <code>.geode/config.toml</code>. Use it when a workspace needs settings different from the rest.</li>
              <li><strong>Global TOML</strong>. <code>~/.geode/config.toml</code>. Defaults shared across every project.</li>
            </ul>
            <p>
              None of these files is required. With all four absent, GEODE runs on
              its code defaults.
            </p>

            <h2>How overrides resolve</h2>
            <p>
              Priority runs from highest to lowest as follows.
            </p>
            <pre>{`CLI arguments
  > environment variables / .env (GEODE_*)
    > project .geode/config.toml
      > global ~/.geode/config.toml
        > code defaults`}</pre>
            <p>
              The read happens in two passes, and that matters. Environment
              variables and <code>.env</code> load first, when the settings object
              is built. TOML values are layered on afterwards, but{" "}
              <strong>any key already set by an environment variable is skipped</strong>.
              That is why an environment variable always beats TOML. Pin the model
              through an environment variable and the model value in{" "}
              <code>config.toml</code> is ignored.
            </p>
            <p>
              A TOML key the code does not recognise is silently ignored. Only
              mapped keys are applied, so a typo passes through with no effect.
              Use the names exactly as the reference spells them.
            </p>

            <h2>When it loads</h2>
            <p>
              Settings are a singleton. They are built once on first request and
              the same object is reused after that. The load is lazy to defer
              heavy dependencies. When the disk changes,{" "}
              <code>reload_settings_from_disk()</code> re-reads <code>.env</code>{" "}
              and <code>config.toml</code> and refreshes the live singleton in
              place. The <code>geode serve</code> daemon takes this path at a
              session boundary, so changing the model from the CLI brings the
              daemon back in sync with disk.
            </p>

            <h2>A first config.toml</h2>
            <p>
              Values are grouped into per-area tables. Uncomment only the lines
              you want to change.
            </p>
            <pre>{`[llm]
primary_model = "claude-opus-4-7"
secondary_model = "gpt-5.4"

[pipeline]
confidence_threshold = 0.7
max_iterations = 5

[gateway]
time_budget_s = 300

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C12345"
auto_respond = true`}</pre>
            <p>
              <code>[[gateway.bindings.rules]]</code> is a rule that routes one
              messaging channel to a session. A rule with an empty{" "}
              <code>channel_id</code> is skipped for safety, since an empty id
              would be an unsafe catch-all that accepts every channel. For more
              on bindings, see the{" "}
              <a href="/geode/docs/guides/binding">Configure a binding</a> guide.
            </p>

            <h2>Where to go next</h2>
            <ul>
              <li><a href="/geode/docs/config/reference">config.toml reference</a>. Every key, grouped by area.</li>
              <li><a href="/geode/docs/run/providers">Configure providers</a>. Where keys go.</li>
              <li><a href="/geode/docs/runtime/auth">Auth and OAuth</a>. Credential sources.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
