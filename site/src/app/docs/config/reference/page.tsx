import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "config.toml reference — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="config/reference"
      title="config.toml reference"
      titleKo="config.toml 레퍼런스"
      summary="The exhaustive key reference: Settings fields with their toml mappings, the routing.toml manifest, and the self-improving loop sections."
      summaryKo="전체 키 레퍼런스입니다. toml 매핑이 붙은 Settings 필드, routing.toml 매니페스트, self-improving 루프 섹션을 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              이 페이지는 설정 키의 단일 목록입니다. 키가 어디서 어떤 순서로
              읽히는지는 <a href="/geode/docs/config/basics">설정 기초</a>가
              다룹니다. 키는 세 무리로 나뉩니다. Settings 필드
              (<code>core/config/_settings.py</code>), 라우팅 매니페스트
              (<code>core/config/routing.toml</code>), self-improving 루프
              섹션(<code>core/config/self_improving.py</code>).
            </p>
            <p>
              모든 Settings 필드는 <code>GEODE_</code> 접두사를 붙인 env
              변수로 덮을 수 있습니다. <code>model</code>은
              <code>GEODE_MODEL</code>, <code>agentic_effort</code>는
              <code>GEODE_AGENTIC_EFFORT</code>가 됩니다. toml 키 열이 비어
              있으면 그 필드는 env 또는 코드 기본값으로만 설정합니다. toml
              매핑의 SoT는 <code>core/config/__init__.py</code>의
              <code>_TOML_TO_SETTINGS</code>이고, 매핑에 없는 toml 키는
              조용히 무시됩니다.
            </p>

            <h2>Settings: toml 매핑 필드</h2>

            <h3>[llm]</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>toml 키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>model</code></td><td><code>llm.primary_model</code></td><td>str = <code>&quot;claude-opus-4-8&quot;</code></td><td>기본 모델. 기본값은 routing.toml의 anthropic 기본값을 따라갑니다.</td></tr>
                <tr><td><code>act_model</code></td><td><code>llm.act_model</code></td><td>str = <code>&quot;&quot;</code></td><td>액션 루프 모델. 비우면 <code>model</code>로 폴백합니다.</td></tr>
                <tr><td><code>judge_model</code></td><td><code>llm.judge_model</code></td><td>str = <code>&quot;&quot;</code></td><td>턴 단위 verify judge 모델. 비우면 <code>model</code>로 폴백합니다.</td></tr>
                <tr><td><code>learning_extract_model</code></td><td><code>llm.learning_extract_model</code></td><td>str = <code>&quot;glm-4.7-flash&quot;</code></td><td>learning 추출 훅용 무료 티어 GLM 모델.</td></tr>
                <tr><td><code>anthropic_credential_source</code></td><td><code>llm.anthropic_credential_source</code></td><td>str = <code>&quot;auto&quot;</code></td><td>Anthropic 자격 경로. <code>CredentialSource</code> 값 + <code>oauth</code> 별칭 + <code>none</code>.</td></tr>
                <tr><td><code>openai_credential_source</code></td><td><code>llm.openai_credential_source</code></td><td>str = <code>&quot;auto&quot;</code></td><td>OpenAI 자격 경로. 같은 검증을 거칩니다.</td></tr>
              </tbody>
            </table>

            <h3>[agentic]</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>toml 키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>agentic_effort</code></td><td><code>agentic.effort</code></td><td>str = <code>&quot;high&quot;</code></td><td><code>low</code>/<code>medium</code>/<code>high</code>/<code>max</code>/<code>xhigh</code>. Anthropic <code>output_config.effort</code>, OpenAI <code>reasoning.effort</code>로 전달됩니다. xhigh는 Opus 4.7 이상과 Fable 5 전용.</td></tr>
                <tr><td><code>agentic_loop_time_budget</code></td><td><code>agentic.time_budget</code></td><td>float = 0.0</td><td>벽시계 초 단위 예산. 0이면 무제한.</td></tr>
                <tr><td><code>agentic_thinking_budget</code></td><td><code>agentic.thinking_budget</code></td><td>int = 0</td><td>레거시 thinking 토큰 예산. 0이면 비활성.</td></tr>
              </tbody>
            </table>

            <h3>[replan]</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>toml 키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>replan_enabled</code></td><td><code>replan.enabled</code></td><td>bool = true</td><td>리플랜 활성화.</td></tr>
                <tr><td><code>replan_interval</code></td><td><code>replan.interval</code></td><td>int = 5</td><td>리플랜 주기. 0이면 주기 비활성.</td></tr>
                <tr><td><code>replan_max_attempts</code></td><td><code>replan.max_attempts</code></td><td>int = 3</td><td>리플랜 시도 상한.</td></tr>
              </tbody>
            </table>

            <h3>[cognitive]</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>toml 키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>cognitive_reflection_enabled</code></td><td><code>cognitive.reflection_enabled</code></td><td>bool = true</td><td>인지 리플렉션 활성화.</td></tr>
                <tr><td><code>cognitive_reflection_model</code></td><td><code>cognitive.reflection_model</code></td><td>str = <code>&quot;&quot;</code></td><td>비워두면 현재 agentic loop 모델/소스를 상속하고, 값이 있으면 별도 reflection 모델로 사용한다.</td></tr>
                <tr><td><code>cognitive_reflection_max_tokens</code></td><td><code>cognitive.reflection_max_tokens</code></td><td>int = 512</td><td>리플렉션 출력 토큰 상한.</td></tr>
                <tr><td><code>cognitive_reflection_interval</code></td><td><code>cognitive.reflection_interval</code></td><td>int = 1</td><td>몇 라운드마다 리플렉션할지. 1이면 매 라운드.</td></tr>
              </tbody>
            </table>

            <h3>[sandbox]</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>toml 키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>sandbox_max_file_size_bytes</code></td><td><code>sandbox.max_file_size_bytes</code></td><td>int = 262144</td><td>파일 읽기 바이트 상한.</td></tr>
                <tr><td><code>sandbox_max_read_tokens</code></td><td><code>sandbox.max_read_tokens</code></td><td>int = 25000</td><td>읽기 결과 토큰 상한.</td></tr>
                <tr><td><code>sandbox_max_glob_results</code></td><td><code>sandbox.max_glob_results</code></td><td>int = 100</td><td>glob 결과 개수 상한.</td></tr>
                <tr><td><code>sandbox_max_grep_results</code></td><td><code>sandbox.max_grep_results</code></td><td>int = 50</td><td>grep 결과 개수 상한.</td></tr>
                <tr><td><code>sandbox_max_grep_line_chars</code></td><td><code>sandbox.max_grep_line_chars</code></td><td>int = 200</td><td>grep 라인 문자 상한.</td></tr>
              </tbody>
            </table>

            <h3>[output]</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>toml 키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>verbose</code></td><td><code>output.verbose</code></td><td>bool = false</td><td>상세 출력. <code>/verbose</code>로 세션 중 토글합니다.</td></tr>
              </tbody>
            </table>

            <h2>Settings: env 전용 필드</h2>
            <p>
              아래 무리는 toml 매핑이 없습니다. <code>GEODE_*</code> env
              변수나 <code>.env</code>로만 설정합니다.
            </p>

            <h3>시크릿과 프로바이더</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>anthropic_api_key</code> / <code>openai_api_key</code> / <code>zai_api_key</code></td><td>str = <code>&quot;&quot;</code></td><td><code>ANTHROPIC_API_KEY</code> / <code>OPENAI_API_KEY</code> / <code>ZAI_API_KEY</code>로 별칭됩니다. 시크릿이므로 <code>.env</code> 층에 둡니다.</td></tr>
                <tr><td><code>ensemble_mode</code></td><td>str = <code>&quot;single&quot;</code></td><td><code>single</code> 또는 <code>cross</code> 멀티 LLM 모드.</td></tr>
                <tr><td><code>forced_login_method</code></td><td>dict = {`{}`}</td><td>프로바이더별 인증 방식 강제(<code>{`{"openai": "apikey"}`}</code>). 기본은 구독 우선.</td></tr>
              </tbody>
            </table>

            <h3>Temperature (0.0-2.0)</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>temperature_agent_loop</code></td><td>1.0</td><td>에이전트 루프 호출.</td></tr>
                <tr><td><code>temperature_reflection</code></td><td>1.0</td><td>리플렉션 호출.</td></tr>
                <tr><td><code>temperature_verification</code></td><td>0.0</td><td>verify 호출. cross-LLM 합의를 위한 결정성.</td></tr>
                <tr><td><code>temperature_commentary</code></td><td>1.0</td><td>커멘터리 호출.</td></tr>
                <tr><td><code>temperature_self_improving_mutation</code></td><td>1.0</td><td>변이 제안 호출.</td></tr>
              </tbody>
            </table>

            <h3>서브에이전트</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>max_subagent_depth</code></td><td>1</td><td>중첩 위임 깊이 상한.</td></tr>
                <tr><td><code>max_total_subagents</code></td><td>15</td><td>총 서브에이전트 상한.</td></tr>
                <tr><td><code>subagent_max_rounds</code></td><td>0</td><td>서브에이전트 라운드 상한. 0이면 무제한.</td></tr>
                <tr><td><code>subagent_max_tokens</code></td><td>32768</td><td>서브에이전트 출력 토큰 상한.</td></tr>
              </tbody>
            </table>

            <h3>토큰 가드와 오프로딩</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>max_tool_result_tokens</code></td><td>25000</td><td>도구 결과 토큰 상한. 0이면 무제한.</td></tr>
                <tr><td><code>tool_offload_threshold</code></td><td>15000</td><td>이 토큰을 넘는 결과는 디스크로 오프로드됩니다. 0이면 비활성.</td></tr>
                <tr><td><code>tool_offload_ttl_hours</code></td><td>4.0</td><td>오프로드 보관 시간.</td></tr>
                <tr><td><code>observation_mask_keep_rounds</code></td><td>3</td><td>관측 마스킹 전 유지 라운드.</td></tr>
                <tr><td><code>compact_keep_recent</code></td><td>10</td><td>컴팩션 시 보존할 최근 메시지 수.</td></tr>
              </tbody>
            </table>

            <h3>스케줄러와 트리거</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>trigger_scheduler_interval_s</code></td><td>60.0</td><td>트리거 스케줄러 폴 간격.</td></tr>
                <tr><td><code>scheduler_interval_s</code></td><td>1.0</td><td>스케줄러 틱 간격.</td></tr>
                <tr><td><code>scheduler_auto_start</code></td><td>true</td><td>serve와 함께 스케줄러 자동 시작.</td></tr>
                <tr><td><code>scheduler_jitter_enabled</code></td><td>true</td><td>예약 실행에 지터 적용.</td></tr>
                <tr><td><code>scheduler_max_jitter_ms</code></td><td>900000.0</td><td>지터 상한. 15분입니다.</td></tr>
              </tbody>
            </table>

            <h3>메모리와 세션</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>session_ttl_hours</code></td><td>4.0</td><td>세션 보존 시간.</td></tr>
                <tr><td><code>session_storage_dir</code></td><td><code>&quot;&quot;</code></td><td>세션 저장 디렉터리. 비우면 인메모리.</td></tr>
                <tr><td><code>organization_fixture_dir</code></td><td><code>&quot;&quot;</code></td><td>조직 메모리 픽스처 경로.</td></tr>
                <tr><td><code>user_profile_dir</code></td><td><code>&quot;&quot;</code></td><td>비우면 <code>~/.geode/user_profile</code>.</td></tr>
                <tr><td><code>checkpoint_db</code></td><td><code>&quot;geode_checkpoints.db&quot;</code></td><td>체크포인트 DB 파일명.</td></tr>
              </tbody>
            </table>

            <h3>게이트웨이, 알림, 웹훅</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>gateway_enabled</code></td><td>false</td><td>메신저 게이트웨이. <code>geode serve</code>의 전제 조건입니다.</td></tr>
                <tr><td><code>gateway_poll_interval_s</code></td><td>3.0</td><td>게이트웨이 폴 간격.</td></tr>
                <tr><td><code>gateway_max_concurrent</code></td><td>4</td><td>동시 처리 상한.</td></tr>
                <tr><td><code>notification_channel</code></td><td><code>&quot;slack&quot;</code></td><td>알림 채널 종류.</td></tr>
                <tr><td><code>notification_recipient</code></td><td><code>&quot;#geode-alerts&quot;</code></td><td>알림 수신처.</td></tr>
                <tr><td><code>webhook_enabled</code></td><td>false</td><td>웹훅 HTTP 엔드포인트.</td></tr>
                <tr><td><code>webhook_port</code></td><td>8765</td><td>웹훅 포트.</td></tr>
              </tbody>
            </table>

            <h3>HITL, 플랜, 비용, 데스크탑</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>hitl_level</code></td><td>2</td><td>2면 모두 확인, 1이면 쓰기만 확인, 0이면 자율.</td></tr>
                <tr><td><code>plan_auto_execute</code></td><td>false</td><td>플랜 자동 실행.</td></tr>
                <tr><td><code>cost_limit_usd</code></td><td>0.0</td><td>비용 상한. 0이면 무제한, 80%에서 경고.</td></tr>
                <tr><td><code>computer_use_enabled</code></td><td>true</td><td>데스크탑 자동화 도구.</td></tr>
              </tbody>
            </table>

            <h3>LLM 커넥션 풀</h3>
            <table>
              <thead>
                <tr><th>필드</th><th>기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>llm_max_connections</code></td><td>20</td><td>최대 연결 수.</td></tr>
                <tr><td><code>llm_max_keepalive_connections</code></td><td>5</td><td>keepalive 연결 상한.</td></tr>
                <tr><td><code>llm_keepalive_expiry</code></td><td>30.0</td><td>keepalive 만료 초.</td></tr>
                <tr><td><code>llm_connect_timeout</code></td><td>5.0</td><td>연결 타임아웃.</td></tr>
                <tr><td><code>llm_read_timeout</code></td><td>300.0</td><td>읽기 타임아웃.</td></tr>
                <tr><td><code>llm_write_timeout</code></td><td>30.0</td><td>쓰기 타임아웃.</td></tr>
                <tr><td><code>llm_pool_timeout</code></td><td>10.0</td><td>풀 대기 타임아웃.</td></tr>
                <tr><td><code>llm_retry_base_delay</code></td><td>2.0</td><td>재시도 기본 지연.</td></tr>
                <tr><td><code>llm_retry_max_delay</code></td><td>30.0</td><td>재시도 최대 지연.</td></tr>
                <tr><td><code>llm_max_retries</code></td><td>3</td><td>재시도 횟수.</td></tr>
                <tr><td><code>llm_max_fallback_cost_ratio</code></td><td>0.0</td><td>폴백 비용 비율 상한. 0이면 무제한.</td></tr>
              </tbody>
            </table>

            <h2>routing.toml</h2>
            <p>
              출하본은 <code>core/config/routing.toml</code>이고, 사용자
              override <code>~/.geode/routing.toml</code>이 섹션 단위로
              병합됩니다(<code>core/config/routing_manifest.py</code>).
            </p>
            <table>
              <thead>
                <tr><th>섹션</th><th>키</th><th>내용</th></tr>
              </thead>
              <tbody>
                <tr><td><code>[model.defaults]</code></td><td><code>anthropic</code>, <code>anthropic_secondary</code>, <code>anthropic_budget</code>, <code>openai</code>, <code>codex</code>, <code>glm</code></td><td><code>claude-opus-4-8</code> / <code>claude-sonnet-4-6</code> / <code>claude-haiku-4-5-20251001</code> / <code>gpt-5.5</code> / <code>gpt-5.5</code> / <code>glm-5.2</code>. <code>core.config.ANTHROPIC_PRIMARY</code> 등으로 export됩니다.</td></tr>
                <tr><td><code>[model.fallbacks]</code></td><td>프로바이더별 리스트 4개</td><td>기본은 전부 빈 리스트입니다. 같은 프로바이더 묵시적 폴백 체인은 출하되지 않고, 기본 모델 실패는 예외를 던지며 사용자가 <code>/model</code>로 고릅니다. 폴백은 <code>~/.geode/routing.toml</code>에서 옵트인합니다.</td></tr>
                <tr><td><code>[routing.prefixes]</code></td><td><code>claude-</code>, <code>glm-</code>, <code>gpt-</code>, <code>o3-</code>, <code>o3</code>, <code>o4-</code>, <code>o4-mini</code>, <code>gemini-</code>, <code>deepseek-</code>, <code>llama-</code>, <code>qwen-</code>, <code>qwen3</code></td><td>모델 id 접두사를 프로바이더로 매핑합니다. 첫 매치가 이깁니다.</td></tr>
                <tr><td><code>[routing]</code></td><td><code>codex_only_models</code>, <code>codex_suffixes</code>, <code>fallback_provider</code></td><td><code>gpt-5.5</code>/<code>gpt-5.5-pro</code>는 접두사보다 먼저 검사되어 openai-codex로 라우팅됩니다. <code>-codex</code>/<code>-codex-max</code>/<code>-codex-mini</code> 접미사도 codex. 미해석 시 <code>openai</code>.</td></tr>
                <tr><td><code>[nodes]</code></td><td><code>analyst</code>, <code>evaluator</code>, <code>scoring</code>, <code>synthesizer</code></td><td>파이프라인 노드 모델. 전부 <code>claude-opus-4-8</code> 고정이라 노드가 REPL 모델을 상속하지 않습니다. 조회 순서는 프로젝트 <code>.geode/routing.toml</code>, 매니페스트, 없으면 <code>settings.model</code>.</td></tr>
                <tr><td><code>[credentials.patterns]</code></td><td><code>sk-ant-</code>, <code>sk-proj-</code>, <code>sk-</code></td><td>키 모양에서 프로바이더를 추정합니다. GLM 키({`{id}.{secret}`} 모양)는 <code>core.config.env_io.is_glm_key</code>가 감지합니다.</td></tr>
                <tr><td><code>[credentials.env_vars]</code></td><td>3개</td><td>anthropic은 <code>ANTHROPIC_API_KEY</code>, openai는 <code>OPENAI_API_KEY</code>, glm은 <code>ZAI_API_KEY</code>.</td></tr>
                <tr><td><code>[credentials.keychain]</code></td><td>1개</td><td>anthropic은 <code>&quot;Claude Code-credentials&quot;</code>(macOS). 프로세스 단위 override는 <code>GEODE_&lt;PROVIDER&gt;_KEYCHAIN_SERVICE</code>.</td></tr>
              </tbody>
            </table>

            <h2>[self_improving_loop.*]</h2>
            <p>
              <code>~/.geode/config.toml</code>(또는
              <code>GEODE_CONFIG_TOML</code>)에서
              <code>load_self_improving_loop_config</code>가 읽습니다.
              Settings와 분리된 별도 로더입니다. 옵트인 기능이라 lazy하게
              두어 cold start를 가볍게 유지합니다. 파일이나 섹션이 없으면
              전부 기본값으로 동작하고, 섹션이 있는데 키가 틀리면 큰 소리로
              ValueError를 냅니다(<code>extra=&quot;forbid&quot;</code>).
            </p>

            <h3>[self_improving_loop]</h3>
            <table>
              <thead>
                <tr><th>키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>fallback_to_payg</code></td><td>bool = false</td><td>구독 소진 시 소스 해석이 <code>api_key</code>로 흘러내릴 수 있는지.</td></tr>
                <tr><td><code>openai_source</code></td><td>None</td><td><code>&quot;openai-codex&quot;</code> 또는 <code>&quot;api_key&quot;</code>만 허용. autoresearch의 source, target.source, mutator.source로 팬아웃되는 단일 노브. 충돌 시 UserWarning과 함께 이 키가 권위입니다.</td></tr>
                <tr><td><code>warn_threshold</code></td><td>float = 0.5</td><td>예산 경고 임계.</td></tr>
                <tr><td><code>abort_threshold</code></td><td>float = 0.9</td><td>중단 임계. warn보다 커야 합니다.</td></tr>
              </tbody>
            </table>

            <h3>[self_improving_loop.autoresearch]</h3>
            <table>
              <thead>
                <tr><th>키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>budget_minutes</code></td><td>int = 5 (1-600)</td><td>사이클 시간 예산.</td></tr>
                <tr><td><code>mutator_feedback_window</code></td><td>int = 20 (0-200)</td><td>변이 제안에 주는 최근 이력 창.</td></tr>
                <tr><td><code>mutator_dedup_window</code></td><td>int = 20</td><td>중복 변이 검사 창.</td></tr>
                <tr><td><code>mutator_dedup_threshold</code></td><td>float = 0.85</td><td>중복 판정 유사도.</td></tr>
                <tr><td><code>anchor_confidence_mode</code></td><td>bool = false</td><td>anchor 신뢰도 모드.</td></tr>
                <tr><td><code>source</code></td><td><code>claude-cli</code></td><td>역할 공통 기본 자격 소스.</td></tr>
                <tr><td><code>seed_limit</code></td><td>int = 10 (5-1000)</td><td>감사당 seed 수.</td></tr>
                <tr><td><code>seed_select</code></td><td><code>&quot;plugins/petri_audit/seeds&quot;</code></td><td>공진화 seed 풀 경로.</td></tr>
                <tr><td><code>held_out_bench</code></td><td>None</td><td>고정 자 역할의 frozen seed 디렉터리.</td></tr>
                <tr><td><code>promote_policy</code></td><td><code>&quot;gate&quot;</code></td><td><code>gate</code> / <code>random</code> / <code>never</code>.</td></tr>
                <tr><td><code>promote_policy_seed</code></td><td>int = 0</td><td>random 정책의 시드.</td></tr>
                <tr><td><code>replicate</code></td><td>int = 1 (1-20)</td><td>감사 반복 횟수.</td></tr>
                <tr><td><code>target_effect_size</code></td><td>float = 0.02</td><td>승격에 요구하는 효과 크기.</td></tr>
                <tr><td><code>dim_set</code></td><td><code>&quot;subset&quot;</code></td><td>측정 dim 세트.</td></tr>
                <tr><td><code>max_turns</code></td><td>int = 10 (1-200)</td><td>감사당 턴 상한.</td></tr>
                <tr><td><code>target_model</code> / <code>judge_model</code></td><td>deprecated</td><td>no-op 슬롯. 역할 서브섹션을 쓰세요.</td></tr>
              </tbody>
            </table>
            <p>
              역할 서브섹션
              <code>[self_improving_loop.autoresearch.target|judge|auditor]</code>는
              <code>model</code>(기본 <code>&quot;&quot;</code>)과
              <code>source</code>(기본 <code>claude-cli</code>)를 받고,
              mutator 서브섹션은 <code>default_model</code>(None이면
              <code>Settings.model</code> 상속),
              <code>source</code>(<code>auto</code>),
              <code>max_tokens</code>(1024)를 받습니다. 레거시
              <code>[self_improving_loop.petri.*]</code>와
              <code>[self_improving_loop.mutator]</code>는 DeprecationWarning과
              함께 자동 이전됩니다. <code>geode audit</code>의 역할 해석
              순서는 argv, 역할 서브섹션, 매니페스트 기본값 순입니다.
            </p>
            <p>
              env 사이드 채널이 키 몇 개에 붙어 있습니다.
              <code>GEODE_HELD_OUT_BENCH</code>,
              <code>GEODE_PROMOTE_POLICY</code>,
              <code>GEODE_AUDIT_REPLICATE</code>,
              <code>GEODE_TARGET_EFFECT_SIZE</code>이고 각각
              <code>AUTORESEARCH_*</code> 별칭을 동반합니다. 해석 순서는 env,
              CLI 플래그, config 필드, 기본값 순입니다.
            </p>

            <h3>[self_improving_loop.seed_generation]</h3>
            <table>
              <thead>
                <tr><th>키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>candidates_default</code></td><td>int = 15 (1-100)</td><td>세대당 후보 수 기본값.</td></tr>
                <tr><td><code>default_gen_tag</code></td><td><code>&quot;gen1&quot;</code></td><td>기본 세대 태그.</td></tr>
                <tr><td><code>roles</code></td><td>dict</td><td>역할별 서브섹션마다 <code>model</code>, <code>source</code>, <code>num_turns</code>(0 또는 2-6), <code>max_papers</code>(0-20), <code>queries_per_run</code>(1-10).</td></tr>
              </tbody>
            </table>

            <h3>[self_improving_loop.scheduler]</h3>
            <table>
              <thead>
                <tr><th>키</th><th>타입 / 기본값</th><th>용도</th></tr>
              </thead>
              <tbody>
                <tr><td><code>enabled</code></td><td>bool = false</td><td>auto-trigger 옵트인.</td></tr>
                <tr><td><code>cron</code></td><td><code>&quot;0 */6 * * *&quot;</code></td><td>발화 cron.</td></tr>
                <tr><td><code>min_interval_minutes</code></td><td>int = 60 (1-1440)</td><td>최소 발화 간격.</td></tr>
                <tr><td><code>max_generation</code></td><td>int = 0</td><td>세대 상한. 0이면 무제한.</td></tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/config/basics">설정 기초</a>. 층과 해석 순서.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">아우터 루프 설정</a>. self-improving 섹션의 동작 맥락.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM 라우팅</a>. routing.toml의 소비처.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              This page is the single inventory of configuration keys. For
              where keys live and in what order they resolve, read
              <a href="/geode/docs/config/basics"> Configuration basics</a>.
              The keys fall into three groups: Settings fields
              (<code>core/config/_settings.py</code>), the routing manifest
              (<code>core/config/routing.toml</code>), and the self-improving
              loop sections (<code>core/config/self_improving.py</code>).
            </p>
            <p>
              Every Settings field can be overridden by an env var with the
              <code>GEODE_</code> prefix: <code>model</code> becomes
              <code>GEODE_MODEL</code>, <code>agentic_effort</code> becomes
              <code>GEODE_AGENTIC_EFFORT</code>. An empty toml-key column
              means the field is env-or-default only. The mapping SoT is
              <code>_TOML_TO_SETTINGS</code> in
              <code>core/config/__init__.py</code>; unmapped TOML keys are
              silently ignored.
            </p>

            <h2>Settings: toml-mapped fields</h2>

            <h3>[llm]</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>toml key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>model</code></td><td><code>llm.primary_model</code></td><td>str = <code>&quot;claude-opus-4-8&quot;</code></td><td>Primary model. The default mirrors the anthropic default in routing.toml.</td></tr>
                <tr><td><code>act_model</code></td><td><code>llm.act_model</code></td><td>str = <code>&quot;&quot;</code></td><td>Action-loop model. Empty falls back to <code>model</code>.</td></tr>
                <tr><td><code>judge_model</code></td><td><code>llm.judge_model</code></td><td>str = <code>&quot;&quot;</code></td><td>Per-turn verify judge model. Empty falls back to <code>model</code>.</td></tr>
                <tr><td><code>learning_extract_model</code></td><td><code>llm.learning_extract_model</code></td><td>str = <code>&quot;glm-4.7-flash&quot;</code></td><td>Free-tier GLM model for the learning-extract hook.</td></tr>
                <tr><td><code>anthropic_credential_source</code></td><td><code>llm.anthropic_credential_source</code></td><td>str = <code>&quot;auto&quot;</code></td><td>Anthropic credential lane. Validated against <code>CredentialSource</code> plus the <code>oauth</code> alias and the <code>none</code> sentinel.</td></tr>
                <tr><td><code>openai_credential_source</code></td><td><code>llm.openai_credential_source</code></td><td>str = <code>&quot;auto&quot;</code></td><td>OpenAI credential lane. Same validation.</td></tr>
              </tbody>
            </table>

            <h3>[agentic]</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>toml key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>agentic_effort</code></td><td><code>agentic.effort</code></td><td>str = <code>&quot;high&quot;</code></td><td><code>low</code>/<code>medium</code>/<code>high</code>/<code>max</code>/<code>xhigh</code>, forwarded as Anthropic <code>output_config.effort</code> or OpenAI <code>reasoning.effort</code>. xhigh is Opus 4.7+ and Fable 5 only.</td></tr>
                <tr><td><code>agentic_loop_time_budget</code></td><td><code>agentic.time_budget</code></td><td>float = 0.0</td><td>Wall-clock seconds. 0 means no limit.</td></tr>
                <tr><td><code>agentic_thinking_budget</code></td><td><code>agentic.thinking_budget</code></td><td>int = 0</td><td>Legacy thinking-token budget. 0 disables.</td></tr>
              </tbody>
            </table>

            <h3>[replan]</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>toml key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>replan_enabled</code></td><td><code>replan.enabled</code></td><td>bool = true</td><td>Enable replanning.</td></tr>
                <tr><td><code>replan_interval</code></td><td><code>replan.interval</code></td><td>int = 5</td><td>Replan cadence. 0 turns the cadence off.</td></tr>
                <tr><td><code>replan_max_attempts</code></td><td><code>replan.max_attempts</code></td><td>int = 3</td><td>Replan attempt cap.</td></tr>
              </tbody>
            </table>

            <h3>[cognitive]</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>toml key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>cognitive_reflection_enabled</code></td><td><code>cognitive.reflection_enabled</code></td><td>bool = true</td><td>Enable cognitive reflection.</td></tr>
                <tr><td><code>cognitive_reflection_model</code></td><td><code>cognitive.reflection_model</code></td><td>str = <code>&quot;&quot;</code></td><td>Empty inherits the active agentic loop model/source; a value sets a separate reflection model.</td></tr>
                <tr><td><code>cognitive_reflection_max_tokens</code></td><td><code>cognitive.reflection_max_tokens</code></td><td>int = 512</td><td>Reflection output cap.</td></tr>
                <tr><td><code>cognitive_reflection_interval</code></td><td><code>cognitive.reflection_interval</code></td><td>int = 1</td><td>Reflect every N rounds. 1 means every round.</td></tr>
              </tbody>
            </table>

            <h3>[sandbox]</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>toml key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>sandbox_max_file_size_bytes</code></td><td><code>sandbox.max_file_size_bytes</code></td><td>int = 262144</td><td>File-read byte cap.</td></tr>
                <tr><td><code>sandbox_max_read_tokens</code></td><td><code>sandbox.max_read_tokens</code></td><td>int = 25000</td><td>Read-result token cap.</td></tr>
                <tr><td><code>sandbox_max_glob_results</code></td><td><code>sandbox.max_glob_results</code></td><td>int = 100</td><td>Glob result cap.</td></tr>
                <tr><td><code>sandbox_max_grep_results</code></td><td><code>sandbox.max_grep_results</code></td><td>int = 50</td><td>Grep result cap.</td></tr>
                <tr><td><code>sandbox_max_grep_line_chars</code></td><td><code>sandbox.max_grep_line_chars</code></td><td>int = 200</td><td>Grep line-length cap.</td></tr>
              </tbody>
            </table>

            <h3>[output]</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>toml key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>verbose</code></td><td><code>output.verbose</code></td><td>bool = false</td><td>Verbose output. Toggle in-session with <code>/verbose</code>.</td></tr>
              </tbody>
            </table>

            <h2>Settings: env-only fields</h2>
            <p>
              The groups below carry no toml mapping. Configure them through
              <code>GEODE_*</code> env vars or <code>.env</code>.
            </p>

            <h3>Secrets and providers</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>anthropic_api_key</code> / <code>openai_api_key</code> / <code>zai_api_key</code></td><td>str = <code>&quot;&quot;</code></td><td>Aliased to <code>ANTHROPIC_API_KEY</code> / <code>OPENAI_API_KEY</code> / <code>ZAI_API_KEY</code>. Secrets, so they live on the <code>.env</code> layer.</td></tr>
                <tr><td><code>ensemble_mode</code></td><td>str = <code>&quot;single&quot;</code></td><td><code>single</code> or <code>cross</code> multi-LLM mode.</td></tr>
                <tr><td><code>forced_login_method</code></td><td>dict = {`{}`}</td><td>Per-provider auth-mode escape hatch (<code>{`{"openai": "apikey"}`}</code>). Subscription preferred by default.</td></tr>
              </tbody>
            </table>

            <h3>Temperature (0.0-2.0)</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>temperature_agent_loop</code></td><td>1.0</td><td>Agent-loop calls.</td></tr>
                <tr><td><code>temperature_reflection</code></td><td>1.0</td><td>Reflection calls.</td></tr>
                <tr><td><code>temperature_verification</code></td><td>0.0</td><td>Verify calls. Determinism for cross-LLM agreement.</td></tr>
                <tr><td><code>temperature_commentary</code></td><td>1.0</td><td>Commentary calls.</td></tr>
                <tr><td><code>temperature_self_improving_mutation</code></td><td>1.0</td><td>Mutation-proposal calls.</td></tr>
              </tbody>
            </table>

            <h3>Sub-agents</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>max_subagent_depth</code></td><td>1</td><td>Nested delegation depth cap.</td></tr>
                <tr><td><code>max_total_subagents</code></td><td>15</td><td>Total sub-agent cap.</td></tr>
                <tr><td><code>subagent_max_rounds</code></td><td>0</td><td>Sub-agent round cap. 0 means unlimited.</td></tr>
                <tr><td><code>subagent_max_tokens</code></td><td>32768</td><td>Sub-agent output token cap.</td></tr>
              </tbody>
            </table>

            <h3>Token guards and offloading</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>max_tool_result_tokens</code></td><td>25000</td><td>Tool-result token cap. 0 means no limit.</td></tr>
                <tr><td><code>tool_offload_threshold</code></td><td>15000</td><td>Results above this many tokens are offloaded to disk. 0 disables.</td></tr>
                <tr><td><code>tool_offload_ttl_hours</code></td><td>4.0</td><td>Offload retention.</td></tr>
                <tr><td><code>observation_mask_keep_rounds</code></td><td>3</td><td>Rounds kept before observation masking.</td></tr>
                <tr><td><code>compact_keep_recent</code></td><td>10</td><td>Recent messages preserved on compaction.</td></tr>
              </tbody>
            </table>

            <h3>Scheduler and triggers</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>trigger_scheduler_interval_s</code></td><td>60.0</td><td>Trigger-scheduler poll interval.</td></tr>
                <tr><td><code>scheduler_interval_s</code></td><td>1.0</td><td>Scheduler tick interval.</td></tr>
                <tr><td><code>scheduler_auto_start</code></td><td>true</td><td>Start the scheduler with serve.</td></tr>
                <tr><td><code>scheduler_jitter_enabled</code></td><td>true</td><td>Apply jitter to scheduled runs.</td></tr>
                <tr><td><code>scheduler_max_jitter_ms</code></td><td>900000.0</td><td>Jitter cap (15 minutes).</td></tr>
              </tbody>
            </table>

            <h3>Memory and sessions</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>session_ttl_hours</code></td><td>4.0</td><td>Session retention.</td></tr>
                <tr><td><code>session_storage_dir</code></td><td><code>&quot;&quot;</code></td><td>Session storage dir. Empty means in-memory.</td></tr>
                <tr><td><code>organization_fixture_dir</code></td><td><code>&quot;&quot;</code></td><td>Organization-memory fixture path.</td></tr>
                <tr><td><code>user_profile_dir</code></td><td><code>&quot;&quot;</code></td><td>Empty means <code>~/.geode/user_profile</code>.</td></tr>
                <tr><td><code>checkpoint_db</code></td><td><code>&quot;geode_checkpoints.db&quot;</code></td><td>Checkpoint DB filename.</td></tr>
              </tbody>
            </table>

            <h3>Gateway, notification, webhook</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>gateway_enabled</code></td><td>false</td><td>Messaging gateway. Precondition for <code>geode serve</code>.</td></tr>
                <tr><td><code>gateway_poll_interval_s</code></td><td>3.0</td><td>Gateway poll interval.</td></tr>
                <tr><td><code>gateway_max_concurrent</code></td><td>4</td><td>Concurrency cap.</td></tr>
                <tr><td><code>notification_channel</code></td><td><code>&quot;slack&quot;</code></td><td>Notification channel kind.</td></tr>
                <tr><td><code>notification_recipient</code></td><td><code>&quot;#geode-alerts&quot;</code></td><td>Notification recipient.</td></tr>
                <tr><td><code>webhook_enabled</code></td><td>false</td><td>Webhook HTTP endpoint.</td></tr>
                <tr><td><code>webhook_port</code></td><td>8765</td><td>Webhook port.</td></tr>
              </tbody>
            </table>

            <h3>HITL, plan, cost, desktop</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>hitl_level</code></td><td>2</td><td>2 = ask everything, 1 = write-only, 0 = autonomous.</td></tr>
                <tr><td><code>plan_auto_execute</code></td><td>false</td><td>Auto-execute plans.</td></tr>
                <tr><td><code>cost_limit_usd</code></td><td>0.0</td><td>Cost cap. 0 means no limit; warns at 80%.</td></tr>
                <tr><td><code>computer_use_enabled</code></td><td>true</td><td>Desktop automation tool.</td></tr>
              </tbody>
            </table>

            <h3>LLM connection pool</h3>
            <table>
              <thead>
                <tr><th>Field</th><th>Default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>llm_max_connections</code></td><td>20</td><td>Connection cap.</td></tr>
                <tr><td><code>llm_max_keepalive_connections</code></td><td>5</td><td>Keepalive connection cap.</td></tr>
                <tr><td><code>llm_keepalive_expiry</code></td><td>30.0</td><td>Keepalive expiry seconds.</td></tr>
                <tr><td><code>llm_connect_timeout</code></td><td>5.0</td><td>Connect timeout.</td></tr>
                <tr><td><code>llm_read_timeout</code></td><td>300.0</td><td>Read timeout.</td></tr>
                <tr><td><code>llm_write_timeout</code></td><td>30.0</td><td>Write timeout.</td></tr>
                <tr><td><code>llm_pool_timeout</code></td><td>10.0</td><td>Pool wait timeout.</td></tr>
                <tr><td><code>llm_retry_base_delay</code></td><td>2.0</td><td>Retry base delay.</td></tr>
                <tr><td><code>llm_retry_max_delay</code></td><td>30.0</td><td>Retry max delay.</td></tr>
                <tr><td><code>llm_max_retries</code></td><td>3</td><td>Retry count.</td></tr>
                <tr><td><code>llm_max_fallback_cost_ratio</code></td><td>0.0</td><td>Fallback cost-ratio cap. 0 means unlimited.</td></tr>
              </tbody>
            </table>

            <h2>routing.toml</h2>
            <p>
              The shipped manifest is <code>core/config/routing.toml</code>;
              the user override <code>~/.geode/routing.toml</code> merges over
              it section by section
              (<code>core/config/routing_manifest.py</code>).
            </p>
            <table>
              <thead>
                <tr><th>Section</th><th>Keys</th><th>Content</th></tr>
              </thead>
              <tbody>
                <tr><td><code>[model.defaults]</code></td><td><code>anthropic</code>, <code>anthropic_secondary</code>, <code>anthropic_budget</code>, <code>openai</code>, <code>codex</code>, <code>glm</code></td><td><code>claude-opus-4-8</code> / <code>claude-sonnet-4-6</code> / <code>claude-haiku-4-5-20251001</code> / <code>gpt-5.5</code> / <code>gpt-5.5</code> / <code>glm-5.2</code>. Exported as <code>core.config.ANTHROPIC_PRIMARY</code> and friends.</td></tr>
                <tr><td><code>[model.fallbacks]</code></td><td>4 per-provider lists</td><td>All empty by default: no silent same-provider fallback chain ships. A primary failure raises and the user picks via <code>/model</code>. Opt in by editing <code>~/.geode/routing.toml</code>.</td></tr>
                <tr><td><code>[routing.prefixes]</code></td><td><code>claude-</code>, <code>glm-</code>, <code>gpt-</code>, <code>o3-</code>, <code>o3</code>, <code>o4-</code>, <code>o4-mini</code>, <code>gemini-</code>, <code>deepseek-</code>, <code>llama-</code>, <code>qwen-</code>, <code>qwen3</code></td><td>Model-id prefix to provider. First match wins.</td></tr>
                <tr><td><code>[routing]</code></td><td><code>codex_only_models</code>, <code>codex_suffixes</code>, <code>fallback_provider</code></td><td><code>gpt-5.5</code>/<code>gpt-5.5-pro</code> are checked before prefixes and route to openai-codex; the <code>-codex</code>/<code>-codex-max</code>/<code>-codex-mini</code> suffixes too. Unresolved ids fall to <code>openai</code>.</td></tr>
                <tr><td><code>[nodes]</code></td><td><code>analyst</code>, <code>evaluator</code>, <code>scoring</code>, <code>synthesizer</code></td><td>Pipeline-node models, all pinned to <code>claude-opus-4-8</code>, so nodes never inherit the REPL model. Lookup: project <code>.geode/routing.toml</code>, then the manifest, else <code>settings.model</code>.</td></tr>
                <tr><td><code>[credentials.patterns]</code></td><td><code>sk-ant-</code>, <code>sk-proj-</code>, <code>sk-</code></td><td>Key shape to provider. GLM keys ({`{id}.{secret}`} shape) are sniffed by <code>core.config.env_io.is_glm_key</code>.</td></tr>
                <tr><td><code>[credentials.env_vars]</code></td><td>3</td><td>anthropic to <code>ANTHROPIC_API_KEY</code>, openai to <code>OPENAI_API_KEY</code>, glm to <code>ZAI_API_KEY</code>.</td></tr>
                <tr><td><code>[credentials.keychain]</code></td><td>1</td><td>anthropic to <code>&quot;Claude Code-credentials&quot;</code> (macOS). Per-process override: <code>GEODE_&lt;PROVIDER&gt;_KEYCHAIN_SERVICE</code>.</td></tr>
              </tbody>
            </table>

            <h2>[self_improving_loop.*]</h2>
            <p>
              Read from <code>~/.geode/config.toml</code> (or
              <code>GEODE_CONFIG_TOML</code>) by
              <code>load_self_improving_loop_config</code>. A separate loader
              from Settings by design: the feature is opt-in and lazy, which
              keeps cold start light. A missing file or section yields a
              fully-defaulted config; a present but invalid section raises a
              loud ValueError (<code>extra=&quot;forbid&quot;</code>).
            </p>

            <h3>[self_improving_loop]</h3>
            <table>
              <thead>
                <tr><th>Key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>fallback_to_payg</code></td><td>bool = false</td><td>Whether source resolvers may fall through to <code>api_key</code> on subscription exhaustion.</td></tr>
                <tr><td><code>openai_source</code></td><td>None</td><td>Only <code>&quot;openai-codex&quot;</code> or <code>&quot;api_key&quot;</code>. A single knob fanning out to the autoresearch source, target.source, and mutator.source; authoritative with a UserWarning on conflict.</td></tr>
                <tr><td><code>warn_threshold</code></td><td>float = 0.5</td><td>Budget warning threshold.</td></tr>
                <tr><td><code>abort_threshold</code></td><td>float = 0.9</td><td>Abort threshold. Must exceed warn.</td></tr>
              </tbody>
            </table>

            <h3>[self_improving_loop.autoresearch]</h3>
            <table>
              <thead>
                <tr><th>Key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>budget_minutes</code></td><td>int = 5 (1-600)</td><td>Per-cycle time budget.</td></tr>
                <tr><td><code>mutator_feedback_window</code></td><td>int = 20 (0-200)</td><td>Recent-history window fed to mutation proposals.</td></tr>
                <tr><td><code>mutator_dedup_window</code></td><td>int = 20</td><td>Duplicate-mutation check window.</td></tr>
                <tr><td><code>mutator_dedup_threshold</code></td><td>float = 0.85</td><td>Duplicate similarity threshold.</td></tr>
                <tr><td><code>anchor_confidence_mode</code></td><td>bool = false</td><td>Anchor confidence mode.</td></tr>
                <tr><td><code>source</code></td><td><code>claude-cli</code></td><td>Default credential source shared by the roles.</td></tr>
                <tr><td><code>seed_limit</code></td><td>int = 10 (5-1000)</td><td>Seeds per audit.</td></tr>
                <tr><td><code>seed_select</code></td><td><code>&quot;plugins/petri_audit/seeds&quot;</code></td><td>Co-evolving seed pool path.</td></tr>
                <tr><td><code>held_out_bench</code></td><td>None</td><td>Frozen fixed-ruler seed dir.</td></tr>
                <tr><td><code>promote_policy</code></td><td><code>&quot;gate&quot;</code></td><td><code>gate</code> / <code>random</code> / <code>never</code>.</td></tr>
                <tr><td><code>promote_policy_seed</code></td><td>int = 0</td><td>Seed for the random policy.</td></tr>
                <tr><td><code>replicate</code></td><td>int = 1 (1-20)</td><td>Audit replications.</td></tr>
                <tr><td><code>target_effect_size</code></td><td>float = 0.02</td><td>Effect size required to promote.</td></tr>
                <tr><td><code>dim_set</code></td><td><code>&quot;subset&quot;</code></td><td>Measured dim set.</td></tr>
                <tr><td><code>max_turns</code></td><td>int = 10 (1-200)</td><td>Turn cap per audit.</td></tr>
                <tr><td><code>target_model</code> / <code>judge_model</code></td><td>deprecated</td><td>No-op slots. Use the role sub-sections.</td></tr>
              </tbody>
            </table>
            <p>
              The role sub-sections
              <code>[self_improving_loop.autoresearch.target|judge|auditor]</code>
              take <code>model</code> (default <code>&quot;&quot;</code>) and
              <code>source</code> (default <code>claude-cli</code>); the
              mutator sub-section takes <code>default_model</code> (None
              inherits <code>Settings.model</code>), <code>source</code>
              (<code>auto</code>), and <code>max_tokens</code> (1024). Legacy
              <code>[self_improving_loop.petri.*]</code> and
              <code>[self_improving_loop.mutator]</code> auto-migrate with a
              DeprecationWarning. Role resolution in <code>geode audit</code>:
              argv, then the role sub-section, then the manifest default.
            </p>
            <p>
              A few keys carry env side-channels:
              <code>GEODE_HELD_OUT_BENCH</code>,
              <code>GEODE_PROMOTE_POLICY</code>,
              <code>GEODE_AUDIT_REPLICATE</code>, and
              <code>GEODE_TARGET_EFFECT_SIZE</code>, each with an
              <code>AUTORESEARCH_*</code> alias. Resolution order: env, then
              CLI flag, then config field, then default.
            </p>

            <h3>[self_improving_loop.seed_generation]</h3>
            <table>
              <thead>
                <tr><th>Key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>candidates_default</code></td><td>int = 15 (1-100)</td><td>Default candidates per generation.</td></tr>
                <tr><td><code>default_gen_tag</code></td><td><code>&quot;gen1&quot;</code></td><td>Default generation tag.</td></tr>
                <tr><td><code>roles</code></td><td>dict</td><td>Each role sub-section takes <code>model</code>, <code>source</code>, <code>num_turns</code> (0 or 2-6), <code>max_papers</code> (0-20), <code>queries_per_run</code> (1-10).</td></tr>
              </tbody>
            </table>

            <h3>[self_improving_loop.scheduler]</h3>
            <table>
              <thead>
                <tr><th>Key</th><th>Type / default</th><th>Purpose</th></tr>
              </thead>
              <tbody>
                <tr><td><code>enabled</code></td><td>bool = false</td><td>Auto-trigger opt-in.</td></tr>
                <tr><td><code>cron</code></td><td><code>&quot;0 */6 * * *&quot;</code></td><td>Firing cron.</td></tr>
                <tr><td><code>min_interval_minutes</code></td><td>int = 60 (1-1440)</td><td>Minimum firing interval.</td></tr>
                <tr><td><code>max_generation</code></td><td>int = 0</td><td>Generation cap. 0 means unbounded.</td></tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/config/basics">Configuration basics</a>. The layers and resolution order.</li>
              <li><a href="/geode/docs/capabilities/outer-loop">Outer-loop configuration</a>. The behavioral context of the self-improving sections.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM routing</a>. Where routing.toml is consumed.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
