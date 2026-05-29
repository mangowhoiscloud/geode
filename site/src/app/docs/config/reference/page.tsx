import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "config.toml reference — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="config/reference"
      title="config.toml reference"
      titleKo="config.toml 레퍼런스"
      summary="Every configuration key, grouped by area, marked stable or experimental."
      summaryKo="영역별로 묶은 모든 설정 키입니다. stable과 experimental을 표시합니다."
    >
      <Bi
        ko={
          <>
            <h2>읽는 법</h2>
            <p>
              아래 표는 코드의 설정 모델에서 검증한 키만 담습니다. 각 키는 환경 변수
              <code>GEODE_</code> 접두사로도 설정할 수 있습니다. 예를 들어 <code>model</code>은
              <code>GEODE_MODEL</code>입니다. 일부 키는 <code>config.toml</code>의 점 표기
              경로로만 매핑됩니다. 그 경로는 별도로 적었습니다. 우선순위와 로드 방식은{" "}
              <a href="/geode/docs/config/basics">설정 기초</a>를 먼저 보세요.
            </p>
            <p>
              실험 단계로 표시된 키는 동작이 바뀔 수 있습니다. 빈 문자열 기본값은
              대개 다른 값으로 폴백한다는 뜻입니다. 표의 설명에 폴백 대상을 적었습니다.
            </p>

            <h2>LLM과 모델</h2>
            <p><code>config.toml</code> 경로: <code>[llm]</code> 테이블.</p>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>model</code> (<code>llm.primary_model</code>)</td><td>주 모델. REPL과 agentic 루프가 씁니다.</td><td><code>claude-opus-4-7</code></td></tr>
                <tr><td><code>default_secondary_model</code> (<code>llm.secondary_model</code>)</td><td>Cross-LLM 검증의 2차 모델.</td><td><code>gpt-5.4</code></td></tr>
                <tr><td><code>router_model</code> (<code>llm.router_model</code>)</td><td>라우팅 결정을 내리는 모델.</td><td><code>claude-opus-4-7</code></td></tr>
                <tr><td><code>plan_model</code> (<code>llm.plan_model</code>)</td><td>계획 단계 모델. 빈 값이면 <code>model</code>로 폴백합니다.</td><td>빈 문자열</td></tr>
                <tr><td><code>act_model</code> (<code>llm.act_model</code>)</td><td>행동 루프 모델. 빈 값이면 <code>model</code>로 폴백합니다.</td><td>빈 문자열</td></tr>
                <tr><td><code>judge_model</code> (<code>llm.judge_model</code>)</td><td>턴별 verify 판정 모델. 빈 값이면 <code>model</code>로 폴백합니다.</td><td>빈 문자열</td></tr>
                <tr><td><code>learning_extract_model</code> (<code>llm.learning_extract_model</code>)</td><td>학습 추출 훅이 쓰는 저비용 모델.</td><td><code>glm-4.7-flash</code></td></tr>
                <tr><td><code>agreement_threshold</code></td><td>Cross-LLM 합의 통과 임계값.</td><td><code>0.67</code></td></tr>
                <tr><td><code>forced_login_method</code></td><td>프로바이더별 인증 모드 강제. 예: <code>{`{"openai":"apikey"}`}</code>.</td><td>빈 dict</td></tr>
              </tbody>
            </table>

            <h2>LLM 연결</h2>
            <p>httpx 풀과 재시도. 기본값으로 충분한 고급 키입니다.</p>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>llm_max_connections</code></td><td>풀의 최대 연결 수.</td><td><code>20</code></td></tr>
                <tr><td><code>llm_read_timeout</code></td><td>응답 읽기 타임아웃(초). 1M 컨텍스트를 위해 큽니다.</td><td><code>300.0</code></td></tr>
                <tr><td><code>llm_connect_timeout</code></td><td>TCP 연결 타임아웃(초).</td><td><code>5.0</code></td></tr>
                <tr><td><code>llm_max_retries</code></td><td>모델별 최대 재시도 횟수.</td><td><code>3</code></td></tr>
                <tr><td><code>llm_max_fallback_cost_ratio</code></td><td>폴백 비용 비율 상한. <code>0</code>은 무제한.</td><td><code>0.0</code></td></tr>
              </tbody>
            </table>

            <h2>예산과 비용</h2>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>cost_limit_usd</code></td><td>세션 비용 상한(USD). 80%에서 경고, 100%에서 초과 이벤트. <code>0</code>은 무제한.</td><td><code>0.0</code></td></tr>
                <tr><td><code>agentic_loop_time_budget</code> (<code>agentic.time_budget</code>)</td><td>agentic 루프 벽시계 예산(초). <code>0</code>은 무제한.</td><td><code>0.0</code></td></tr>
                <tr><td><code>agentic_effort</code> (<code>agentic.effort</code>)</td><td>thinking depth. <code>low</code> / <code>medium</code> / <code>high</code> / <code>max</code> / <code>xhigh</code>.</td><td><code>high</code></td></tr>
                <tr><td><code>max_tool_result_tokens</code></td><td>도구 결과 절단 임계 토큰. <code>0</code>은 무제한.</td><td><code>25000</code></td></tr>
                <tr><td><code>tool_offload_threshold</code></td><td>큰 결과를 디스크로 내리는 토큰 임계값. <code>0</code>은 비활성.</td><td><code>15000</code></td></tr>
                <tr><td><code>pipeline_timeout_s</code></td><td>파이프라인 타임아웃(초). <code>0</code>은 무제한.</td><td><code>600.0</code></td></tr>
              </tbody>
            </table>

            <h2>파이프라인과 오케스트레이션</h2>
            <p><code>config.toml</code> 경로: <code>[pipeline]</code> 테이블 (앞 두 키).</p>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>confidence_threshold</code> (<code>pipeline.confidence_threshold</code>)</td><td>이 값 아래면 루프백.</td><td><code>0.7</code></td></tr>
                <tr><td><code>max_iterations</code> (<code>pipeline.max_iterations</code>)</td><td>최대 파이프라인 반복.</td><td><code>5</code></td></tr>
                <tr><td><code>max_subagent_depth</code></td><td>서브에이전트 최대 재귀 깊이.</td><td><code>1</code></td></tr>
                <tr><td><code>max_total_subagents</code></td><td>세션 내 최대 서브에이전트 수.</td><td><code>15</code></td></tr>
                <tr><td><code>subagent_max_tokens</code></td><td>서브에이전트 출력 토큰 제한.</td><td><code>32768</code></td></tr>
                <tr><td><code>ensemble_mode</code></td><td><code>single</code> 또는 <code>cross</code>(다중 LLM).</td><td><code>single</code></td></tr>
              </tbody>
            </table>

            <h2>게이트웨이와 바인딩</h2>
            <p><code>config.toml</code> 경로: <code>[gateway]</code> 테이블과 <code>[[gateway.bindings.rules]]</code> 배열.</p>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>gateway_enabled</code></td><td>인바운드 메시지 게이트웨이 활성. <code>GEODE_GATEWAY_ENABLED=true</code>.</td><td><code>false</code></td></tr>
                <tr><td><code>gateway_poll_interval_s</code></td><td>게이트웨이 폴링 간격(초).</td><td><code>3.0</code></td></tr>
                <tr><td><code>gateway_max_concurrent</code></td><td>동시에 처리하는 게이트웨이 메시지 수.</td><td><code>4</code></td></tr>
                <tr><td><code>gateway.time_budget_s</code></td><td>바인딩이 상속하는 게이트웨이 기본 시간 예산.</td><td>해당 없음</td></tr>
                <tr><td><code>gateway.max_turns</code></td><td>게이트웨이 세션 턴 상한. <code>0</code>은 무제한.</td><td><code>0</code></td></tr>
              </tbody>
            </table>
            <p><code>[[gateway.bindings.rules]]</code> 규칙 하나의 필드:</p>
            <table>
              <thead><tr><th>필드</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>channel</code></td><td>메신저 종류. 예: <code>slack</code>. 필수.</td><td>해당 없음</td></tr>
                <tr><td><code>channel_id</code></td><td>채널 식별자. 비면 그 규칙은 건너뜁니다.</td><td>해당 없음</td></tr>
                <tr><td><code>auto_respond</code></td><td>자동 응답 여부.</td><td><code>true</code></td></tr>
                <tr><td><code>require_mention</code></td><td>멘션이 있을 때만 응답.</td><td><code>false</code></td></tr>
                <tr><td><code>allowed_tools</code></td><td>이 바인딩에서 허용할 도구 목록.</td><td>빈 목록</td></tr>
                <tr><td><code>time_budget_s</code></td><td>이 바인딩의 시간 예산(초). 없으면 게이트웨이 기본값.</td><td>게이트웨이 기본값</td></tr>
              </tbody>
            </table>

            <h2>스케줄러와 자동화</h2>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>scheduler_auto_start</code></td><td>부트 시 스케줄러 자동 시작.</td><td><code>true</code></td></tr>
                <tr><td><code>scheduler_interval_s</code></td><td>스케줄러 체크 간격(초).</td><td><code>1.0</code></td></tr>
                <tr><td><code>scheduler_jitter_enabled</code></td><td>잡별 결정적 jitter 적용.</td><td><code>true</code></td></tr>
                <tr><td><code>scheduler_max_jitter_ms</code></td><td>jitter 상한(밀리초).</td><td><code>900000.0</code></td></tr>
                <tr><td><code>outcome_tracking_enabled</code></td><td>결과 추적 활성 (실험).</td><td><code>true</code></td></tr>
                <tr><td><code>drift_scan_cron</code></td><td>drift 스캔 cron 식 (실험).</td><td><code>0 */6 * * *</code></td></tr>
              </tbody>
            </table>

            <h2>메모리와 세션</h2>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>session_ttl_hours</code></td><td>세션 idle TTL(시간).</td><td><code>4.0</code></td></tr>
                <tr><td><code>session_storage_dir</code></td><td>파일 백업 디렉터리. 비면 메모리만 사용.</td><td>빈 문자열</td></tr>
                <tr><td><code>compact_keep_recent</code></td><td>압축 시 보존할 최근 메시지 수.</td><td><code>10</code></td></tr>
                <tr><td><code>checkpoint_db</code></td><td>체크포인트 DB 파일.</td><td><code>geode_checkpoints.db</code></td></tr>
              </tbody>
            </table>

            <h2>샌드박스 (파일 도구 가드)</h2>
            <p><code>config.toml</code> 경로: <code>[sandbox]</code> 테이블.</p>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>sandbox_max_file_size_bytes</code> (<code>sandbox.max_file_size_bytes</code>)</td><td>읽기 전 파일 크기 가드(바이트).</td><td><code>262144</code></td></tr>
                <tr><td><code>sandbox_max_read_tokens</code> (<code>sandbox.max_read_tokens</code>)</td><td>읽은 뒤 토큰 추정 가드.</td><td><code>25000</code></td></tr>
                <tr><td><code>sandbox_max_glob_results</code> (<code>sandbox.max_glob_results</code>)</td><td>Glob 도구 최대 결과.</td><td><code>100</code></td></tr>
                <tr><td><code>sandbox_max_grep_results</code> (<code>sandbox.max_grep_results</code>)</td><td>Grep 도구 최대 파일 수.</td><td><code>50</code></td></tr>
              </tbody>
            </table>

            <h2>승인과 알림</h2>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>hitl_level</code></td><td>휴먼 인 더 루프 단계. <code>0</code> 자율, <code>1</code> 쓰기만 확인, <code>2</code> 전부 확인.</td><td><code>2</code></td></tr>
                <tr><td><code>plan_auto_execute</code></td><td>계획 자동 실행. <code>GEODE_PLAN_AUTO_EXECUTE=true</code>.</td><td><code>false</code></td></tr>
                <tr><td><code>computer_use_enabled</code></td><td>데스크탑 자동화 활성.</td><td><code>true</code></td></tr>
                <tr><td><code>notification_channel</code></td><td>기본 알림 채널.</td><td><code>slack</code></td></tr>
                <tr><td><code>notification_on_pipeline_error</code></td><td>파이프라인 오류 시 알림.</td><td><code>true</code></td></tr>
                <tr><td><code>webhook_enabled</code></td><td>웹훅 엔드포인트 활성. <code>GEODE_WEBHOOK_ENABLED=true</code>.</td><td><code>false</code></td></tr>
              </tbody>
            </table>

            <h2>자격 증명 소스</h2>
            <table>
              <thead><tr><th>키</th><th>하는 일</th><th>기본값</th></tr></thead>
              <tbody>
                <tr><td><code>anthropic_credential_source</code></td><td>Anthropic 자격 증명 소스. <code>auto</code> / <code>api_key</code> / <code>claude-cli</code> / <code>oauth</code> / <code>none</code>.</td><td><code>auto</code></td></tr>
                <tr><td><code>openai_credential_source</code></td><td>OpenAI 자격 증명 소스. 같은 집합.</td><td><code>auto</code></td></tr>
                <tr><td><code>anthropic_api_key</code></td><td>Anthropic 키. <code>ANTHROPIC_API_KEY</code> 별칭 가능.</td><td>빈 문자열</td></tr>
                <tr><td><code>openai_api_key</code></td><td>OpenAI 키. <code>OPENAI_API_KEY</code> 별칭 가능.</td><td>빈 문자열</td></tr>
                <tr><td><code>zai_api_key</code></td><td>ZhipuAI(GLM) 키. <code>ZAI_API_KEY</code> 별칭 가능.</td><td>빈 문자열</td></tr>
              </tbody>
            </table>

            <h2>참고</h2>
            <p>
              이 목록은 코드의 설정 모델에서 직접 검증한 키만 담습니다. 모델 기본값과
              폴백 체인은 <code>routing.toml</code>이라는 별도 매니페스트에서 오므로 여기
              표에 없습니다. 모델별 라우팅을 바꾸려면{" "}
              <a href="/geode/docs/runtime/llm/providers">LLM 라우팅</a>을 보세요.
              자격 증명 흐름은 <a href="/geode/docs/runtime/auth">인증과 OAuth</a>에
              있습니다.
            </p>
          </>
        }
        en={
          <>
            <h2>How to read this</h2>
            <p>
              The tables below contain only keys verified against the code's
              settings model. Each key can also be set through an environment
              variable with the <code>GEODE_</code> prefix. For example,{" "}
              <code>model</code> is <code>GEODE_MODEL</code>. Some keys are mapped
              only through a dotted <code>config.toml</code> path, which is noted
              alongside the key. For priority and load order, read{" "}
              <a href="/geode/docs/config/basics">Configuration basics</a> first.
            </p>
            <p>
              Keys marked experimental may change behaviour. An empty-string
              default usually means the value falls back to another key, named in
              the description.
            </p>

            <h2>LLM and models</h2>
            <p><code>config.toml</code> path: <code>[llm]</code> table.</p>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>model</code> (<code>llm.primary_model</code>)</td><td>Primary model. Used by the REPL and the agentic loop.</td><td><code>claude-opus-4-7</code></td></tr>
                <tr><td><code>default_secondary_model</code> (<code>llm.secondary_model</code>)</td><td>Secondary model for cross-LLM verification.</td><td><code>gpt-5.4</code></td></tr>
                <tr><td><code>router_model</code> (<code>llm.router_model</code>)</td><td>Model that makes routing decisions.</td><td><code>claude-opus-4-7</code></td></tr>
                <tr><td><code>plan_model</code> (<code>llm.plan_model</code>)</td><td>Planning-step model. Empty falls back to <code>model</code>.</td><td>empty string</td></tr>
                <tr><td><code>act_model</code> (<code>llm.act_model</code>)</td><td>Action-loop model. Empty falls back to <code>model</code>.</td><td>empty string</td></tr>
                <tr><td><code>judge_model</code> (<code>llm.judge_model</code>)</td><td>Per-turn verify judge model. Empty falls back to <code>model</code>.</td><td>empty string</td></tr>
                <tr><td><code>learning_extract_model</code> (<code>llm.learning_extract_model</code>)</td><td>Low-cost model used by the learning-extraction hook.</td><td><code>glm-4.7-flash</code></td></tr>
                <tr><td><code>agreement_threshold</code></td><td>Cross-LLM consensus pass threshold.</td><td><code>0.67</code></td></tr>
                <tr><td><code>forced_login_method</code></td><td>Force the auth mode per provider. For example, <code>{`{"openai":"apikey"}`}</code>.</td><td>empty dict</td></tr>
              </tbody>
            </table>

            <h2>LLM connection</h2>
            <p>httpx pool and retries. Advanced keys that the defaults usually cover.</p>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>llm_max_connections</code></td><td>Maximum connections in the pool.</td><td><code>20</code></td></tr>
                <tr><td><code>llm_read_timeout</code></td><td>Response read timeout in seconds. Large for 1M context.</td><td><code>300.0</code></td></tr>
                <tr><td><code>llm_connect_timeout</code></td><td>TCP connect timeout in seconds.</td><td><code>5.0</code></td></tr>
                <tr><td><code>llm_max_retries</code></td><td>Maximum retry attempts per model.</td><td><code>3</code></td></tr>
                <tr><td><code>llm_max_fallback_cost_ratio</code></td><td>Fallback cost ratio cap. <code>0</code> is unlimited.</td><td><code>0.0</code></td></tr>
              </tbody>
            </table>

            <h2>Budgets and cost</h2>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>cost_limit_usd</code></td><td>Session cost cap in USD. Warns at 80 percent, fires an exceeded event at 100 percent. <code>0</code> is unlimited.</td><td><code>0.0</code></td></tr>
                <tr><td><code>agentic_loop_time_budget</code> (<code>agentic.time_budget</code>)</td><td>Agentic-loop wall-clock budget in seconds. <code>0</code> is unlimited.</td><td><code>0.0</code></td></tr>
                <tr><td><code>agentic_effort</code> (<code>agentic.effort</code>)</td><td>Thinking depth. <code>low</code> / <code>medium</code> / <code>high</code> / <code>max</code> / <code>xhigh</code>.</td><td><code>high</code></td></tr>
                <tr><td><code>max_tool_result_tokens</code></td><td>Tool-result truncation threshold in tokens. <code>0</code> is unlimited.</td><td><code>25000</code></td></tr>
                <tr><td><code>tool_offload_threshold</code></td><td>Token threshold for offloading large results to disk. <code>0</code> disables.</td><td><code>15000</code></td></tr>
                <tr><td><code>pipeline_timeout_s</code></td><td>Pipeline timeout in seconds. <code>0</code> is unlimited.</td><td><code>600.0</code></td></tr>
              </tbody>
            </table>

            <h2>Pipeline and orchestration</h2>
            <p><code>config.toml</code> path: <code>[pipeline]</code> table for the first two keys.</p>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>confidence_threshold</code> (<code>pipeline.confidence_threshold</code>)</td><td>Loop back below this value.</td><td><code>0.7</code></td></tr>
                <tr><td><code>max_iterations</code> (<code>pipeline.max_iterations</code>)</td><td>Maximum pipeline iterations.</td><td><code>5</code></td></tr>
                <tr><td><code>max_subagent_depth</code></td><td>Maximum sub-agent recursion depth.</td><td><code>1</code></td></tr>
                <tr><td><code>max_total_subagents</code></td><td>Maximum sub-agents within a session.</td><td><code>15</code></td></tr>
                <tr><td><code>subagent_max_tokens</code></td><td>Sub-agent output token limit.</td><td><code>32768</code></td></tr>
                <tr><td><code>ensemble_mode</code></td><td><code>single</code> or <code>cross</code> for multi-LLM.</td><td><code>single</code></td></tr>
              </tbody>
            </table>

            <h2>Gateway and bindings</h2>
            <p><code>config.toml</code> path: <code>[gateway]</code> table and the <code>[[gateway.bindings.rules]]</code> array.</p>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>gateway_enabled</code></td><td>Enable the inbound message gateway. <code>GEODE_GATEWAY_ENABLED=true</code>.</td><td><code>false</code></td></tr>
                <tr><td><code>gateway_poll_interval_s</code></td><td>Gateway poll interval in seconds.</td><td><code>3.0</code></td></tr>
                <tr><td><code>gateway_max_concurrent</code></td><td>Gateway messages handled at once.</td><td><code>4</code></td></tr>
                <tr><td><code>gateway.time_budget_s</code></td><td>Gateway default time budget that bindings inherit.</td><td>not set</td></tr>
                <tr><td><code>gateway.max_turns</code></td><td>Gateway session turn cap. <code>0</code> is unlimited.</td><td><code>0</code></td></tr>
              </tbody>
            </table>
            <p>Fields on a single <code>[[gateway.bindings.rules]]</code> rule:</p>
            <table>
              <thead><tr><th>Field</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>channel</code></td><td>Messenger kind, for example <code>slack</code>. Required.</td><td>not set</td></tr>
                <tr><td><code>channel_id</code></td><td>Channel identifier. The rule is skipped when empty.</td><td>not set</td></tr>
                <tr><td><code>auto_respond</code></td><td>Whether to respond automatically.</td><td><code>true</code></td></tr>
                <tr><td><code>require_mention</code></td><td>Respond only when mentioned.</td><td><code>false</code></td></tr>
                <tr><td><code>allowed_tools</code></td><td>Tools allowed for this binding.</td><td>empty list</td></tr>
                <tr><td><code>time_budget_s</code></td><td>Time budget for this binding in seconds. Falls back to the gateway default.</td><td>gateway default</td></tr>
              </tbody>
            </table>

            <h2>Scheduler and automation</h2>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>scheduler_auto_start</code></td><td>Start the scheduler at boot.</td><td><code>true</code></td></tr>
                <tr><td><code>scheduler_interval_s</code></td><td>Scheduler check interval in seconds.</td><td><code>1.0</code></td></tr>
                <tr><td><code>scheduler_jitter_enabled</code></td><td>Apply deterministic per-job jitter.</td><td><code>true</code></td></tr>
                <tr><td><code>scheduler_max_jitter_ms</code></td><td>Jitter cap in milliseconds.</td><td><code>900000.0</code></td></tr>
                <tr><td><code>outcome_tracking_enabled</code></td><td>Enable outcome tracking (experimental).</td><td><code>true</code></td></tr>
                <tr><td><code>drift_scan_cron</code></td><td>Cron expression for the drift scan (experimental).</td><td><code>0 */6 * * *</code></td></tr>
              </tbody>
            </table>

            <h2>Memory and session</h2>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>session_ttl_hours</code></td><td>Session idle TTL in hours.</td><td><code>4.0</code></td></tr>
                <tr><td><code>session_storage_dir</code></td><td>File-backed directory. Empty means in-memory only.</td><td>empty string</td></tr>
                <tr><td><code>compact_keep_recent</code></td><td>Recent messages preserved during compaction.</td><td><code>10</code></td></tr>
                <tr><td><code>checkpoint_db</code></td><td>Checkpoint database file.</td><td><code>geode_checkpoints.db</code></td></tr>
              </tbody>
            </table>

            <h2>Sandbox (file tool guards)</h2>
            <p><code>config.toml</code> path: <code>[sandbox]</code> table.</p>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>sandbox_max_file_size_bytes</code> (<code>sandbox.max_file_size_bytes</code>)</td><td>Pre-read file-size guard in bytes.</td><td><code>262144</code></td></tr>
                <tr><td><code>sandbox_max_read_tokens</code> (<code>sandbox.max_read_tokens</code>)</td><td>Post-read token-estimate guard.</td><td><code>25000</code></td></tr>
                <tr><td><code>sandbox_max_glob_results</code> (<code>sandbox.max_glob_results</code>)</td><td>Glob tool maximum results.</td><td><code>100</code></td></tr>
                <tr><td><code>sandbox_max_grep_results</code> (<code>sandbox.max_grep_results</code>)</td><td>Grep tool maximum files.</td><td><code>50</code></td></tr>
              </tbody>
            </table>

            <h2>Approval and notification</h2>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>hitl_level</code></td><td>Human-in-the-loop level. <code>0</code> autonomous, <code>1</code> writes only, <code>2</code> ask everything.</td><td><code>2</code></td></tr>
                <tr><td><code>plan_auto_execute</code></td><td>Auto-execute a plan. <code>GEODE_PLAN_AUTO_EXECUTE=true</code>.</td><td><code>false</code></td></tr>
                <tr><td><code>computer_use_enabled</code></td><td>Enable desktop automation.</td><td><code>true</code></td></tr>
                <tr><td><code>notification_channel</code></td><td>Default notification channel.</td><td><code>slack</code></td></tr>
                <tr><td><code>notification_on_pipeline_error</code></td><td>Notify on pipeline error.</td><td><code>true</code></td></tr>
                <tr><td><code>webhook_enabled</code></td><td>Enable the webhook endpoint. <code>GEODE_WEBHOOK_ENABLED=true</code>.</td><td><code>false</code></td></tr>
              </tbody>
            </table>

            <h2>Credential sources</h2>
            <table>
              <thead><tr><th>Key</th><th>What it does</th><th>Default</th></tr></thead>
              <tbody>
                <tr><td><code>anthropic_credential_source</code></td><td>Anthropic credential source. <code>auto</code> / <code>api_key</code> / <code>claude-cli</code> / <code>oauth</code> / <code>none</code>.</td><td><code>auto</code></td></tr>
                <tr><td><code>openai_credential_source</code></td><td>OpenAI credential source. Same set.</td><td><code>auto</code></td></tr>
                <tr><td><code>anthropic_api_key</code></td><td>Anthropic key. <code>ANTHROPIC_API_KEY</code> alias accepted.</td><td>empty string</td></tr>
                <tr><td><code>openai_api_key</code></td><td>OpenAI key. <code>OPENAI_API_KEY</code> alias accepted.</td><td>empty string</td></tr>
                <tr><td><code>zai_api_key</code></td><td>ZhipuAI (GLM) key. <code>ZAI_API_KEY</code> alias accepted.</td><td>empty string</td></tr>
              </tbody>
            </table>

            <h2>Note</h2>
            <p>
              This list reflects only keys verified directly against the code's
              settings model. Model defaults and fallback chains come from a
              separate manifest, <code>routing.toml</code>, so they are not in
              these tables. To change per-model routing, see{" "}
              <a href="/geode/docs/runtime/llm/providers">LLM routing</a>. The
              credential flow is covered in{" "}
              <a href="/geode/docs/runtime/auth">Auth and OAuth</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
