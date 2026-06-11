import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "CLI and slash commands — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="harness/cli"
      title="CLI and slash commands"
      titleKo="CLI와 슬래시 명령"
      summary="The complete reference for the geode CLI, the in-session slash commands with their thin-vs-daemon routing, and the geode-mcp server surface."
      summaryKo="geode CLI 전체, 세션 안 슬래시 명령과 thin/daemon 라우팅, geode-mcp 서버 표면까지 한 페이지로 정리한 레퍼런스입니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 진입점은 둘입니다. <code>geode</code>(Typer CLI)와{" "}
              <code>geode-mcp</code>(stdio MCP 서버). 둘 다{" "}
              <code>pyproject.toml</code>의 <code>[project.scripts]</code>에
              선언되어 있고, 각각 <code>core/cli/__init__.py</code>와{" "}
              <code>core/mcp_server.py</code>로 들어갑니다. 이 페이지는 그 두
              표면의 전체 목록입니다.
            </p>
            <p>
              먼저 정직한 한계 둘. 셸 원샷{" "}
              <code>geode &quot;프롬프트&quot;</code>는 지원하지 않습니다.
              인식되지 않는 첫 토큰은 click의 &quot;No such command&quot;
              오류로 끝납니다. 자유 텍스트는 bare <code>geode</code>로 들어간
              대화형 REPL 안에서 입력합니다. 그리고{" "}
              <code>geode serve stop</code> 같은 서브커맨드는 없습니다. 데몬
              정지 로직은 <code>core/cli/commands/lifecycle.py</code>에 있지만
              Typer 표면에 노출되어 있지 않습니다.
            </p>

            <h2>2-프로세스 구조</h2>
            <pre>{`geode (thin CLI)  ── Unix socket IPC (~/.geode/cli.sock) ──→  geode serve (데몬)
  자유 텍스트 → send_prompt 스트리밍                            AgenticLoop, MCP, 스케줄러,
  슬래시 → core/cli/routing.py 가 THIN/daemon 결정              메신저 폴러, CLIPoller`}</pre>
            <p>
              bare <code>geode</code>는 환영 화면을 띄우고 소켓을 조사한 뒤,
              데몬이 없으면 자동 기동합니다(<code>start_serve_if_needed</code>,{" "}
              <code>core/cli/ipc_client.py</code>). 동시 기동 경합은 pidfile
              flock이 막습니다. 그 뒤 thin REPL이 IPC로 붙습니다. 프로토콜은
              줄 단위 JSON이고 서버 쪽 상대는 <code>CLIPoller</code>
              (<code>core/server/ipc_server/poller.py</code>)입니다.
            </p>

            <h2>최상위 명령</h2>
            <table>
              <thead>
                <tr><th>명령</th><th>용도</th><th>주요 옵션</th><th>코드</th></tr>
              </thead>
              <tbody>
                <tr><td><code>geode</code></td><td>환영 화면, 필요 시 serve 자동 기동, thin REPL 진입</td><td><code>--version</code>, <code>--continue</code>, <code>--resume &lt;id&gt;</code></td><td><code>core/cli/__init__.py</code></td></tr>
                <tr><td><code>geode version</code></td><td>버전 출력</td><td>없음</td><td><code>core/cli/typer_commands.py</code></td></tr>
                <tr><td><code>geode about</code></td><td>실행 중인 것의 한 화면 요약. EFFECTIVE 모델, env가 toml을 가리는 경고, 경로, 데몬 소켓 상태</td><td>없음</td><td><code>core/cli/typer_commands.py</code></td></tr>
                <tr><td><code>geode setup</code></td><td>최초 설정 마법사. ChatGPT 구독 OAuth(<code>~/.codex/auth.json</code>)를 API 키보다 먼저 감지</td><td><code>--reset/-r</code></td><td><code>core/cli/onboarding.py</code></td></tr>
                <tr><td><code>geode doctor [target]</code></td><td>진단. 기본 <code>bootstrap</code>은 Python, PATH, 자격, 데몬 점검. <code>slack</code>은 게이트웨이 점검</td><td>positional <code>bootstrap</code> | <code>slack</code></td><td><code>core/cli/doctor_bootstrap.py</code>, <code>core/cli/doctor.py</code></td></tr>
                <tr><td><code>geode update</code></td><td>소스 체크아웃 업데이트와 CLI 재설치. 떠 있던 serve는 재시작</td><td><code>--dry-run</code>, <code>--force/-f</code>, <code>--restart/--no-restart</code></td><td><code>core/cli/commands/lifecycle.py</code></td></tr>
                <tr><td><code>geode uninstall</code></td><td>런타임 데이터와 CLI 제거</td><td><code>--dry-run</code>, <code>--force/-f</code>, <code>--keep-config</code>, <code>--keep-data</code></td><td><code>core/cli/commands/lifecycle.py</code></td></tr>
                <tr><td><code>geode init</code></td><td><code>.geode/</code> 프로젝트 골격 생성. 프로젝트 타입 자동 감지</td><td><code>--force/-f</code></td><td><code>core/cli/typer_init.py</code></td></tr>
                <tr><td><code>geode history</code></td><td>실행 이력과 월간 비용 요약</td><td><code>--limit/-n</code>, <code>--month/-m YYYY-MM</code></td><td><code>core/llm/usage_store.py</code></td></tr>
                <tr><td><code>geode serve</code></td><td>헤드리스 게이트웨이 데몬. 메신저 폴러, 스케줄러, IPC 소켓. <code>gateway_enabled</code> 필요</td><td><code>--poll/-p</code></td><td><code>core/cli/typer_serve.py</code></td></tr>
                <tr><td><code>geode audit</code></td><td>Petri × GEODE 정렬 감사 실행</td><td><code>--judge/-j</code>, <code>--auditor/-a</code>, <code>--target/-t</code>, <code>--seeds/-s</code>, <code>--max-turns/-m</code>, <code>--seed-select</code>, <code>--dim-set</code>, <code>--dry-run/--live</code>, <code>--unrestricted</code>, <code>--cache/--no-cache</code></td><td><code>plugins/petri_audit/cli_audit.py</code></td></tr>
                <tr><td><code>geode petri-archive</code></td><td>petri eval 로그를 워크트리 밖으로 보존하고 YAML 요약 작성</td><td><code>--raw-archive-dir</code>, <code>--summary-dir</code></td><td><code>plugins/petri_audit/cli_audit.py</code></td></tr>
                <tr><td><code>geode outer-bundle</code></td><td>자기개선 루프 활동을 하나의 타임라인으로 묶어 보는 뷰어</td><td><code>--limit</code>, <code>--json</code></td><td><code>core/cli/outer_bundle.py</code></td></tr>
                <tr><td><code>geode reindex</code></td><td>전 프로젝트 sessions.db에서 <code>~/.geode/search/global.db</code> FTS5 인덱스 재구축</td><td><code>--projects-root</code></td><td><code>core/cli/commands/reindex.py</code></td></tr>
                <tr><td><code>geode campaign</code></td><td>3-arm 자기개선 캠페인 드라이버의 thin 포워더</td><td><code>--n</code>, <code>--k</code>, <code>--arms</code>, <code>--dry-run</code></td><td><code>core/self_improving/campaign.py</code></td></tr>
              </tbody>
            </table>

            <h2>서브커맨드 그룹</h2>
            <table>
              <thead>
                <tr><th>그룹</th><th>서브커맨드</th><th>용도</th><th>코드</th></tr>
              </thead>
              <tbody>
                <tr><td><code>geode adapters</code></td><td><code>list</code> / <code>detect-model</code> / <code>stats</code></td><td>등록된 LLM 어댑터(PAYG, 구독, CLI 경로) 점검과 디스패치 통계</td><td><code>core/cli/commands/adapters.py</code></td></tr>
                <tr><td><code>geode skill</code></td><td><code>list</code> / <code>create</code> / <code>remove</code> / <code>show</code></td><td>3단계 스킬 관리. builtin <code>core/skills/</code>, 프로젝트 <code>.geode/skills/</code>, 개인 <code>~/.geode/skills/</code></td><td><code>core/cli/commands/skill.py</code></td></tr>
                <tr><td><code>geode config</code></td><td><code>explain [key]</code> / <code>migrate-petri-toml</code></td><td>설정 레이어별 후보 표. 어느 레이어가 이기고 무엇이 가려졌는지 보여 줍니다</td><td><code>core/cli/commands/config.py</code></td></tr>
                <tr><td><code>geode seeds</code></td><td><code>assemble</code></td><td>cycle-input 시드 풀 조립. repo 체크아웃 전용 래퍼</td><td><code>core/cli/commands/seed_pool.py</code></td></tr>
                <tr><td><code>geode hub</code></td><td><code>build</code></td><td>자기개선 허브 정적 페이지 빌드. repo 체크아웃 전용 래퍼</td><td><code>core/cli/commands/seed_pool.py</code></td></tr>
                <tr><td><code>geode audit-seeds</code></td><td><code>generate</code> / <code>resume</code> / <code>config</code></td><td>타깃 dim 하나에 대한 시드 생성 파이프라인. 페이즈별 체크포인트에서 재개 가능</td><td><code>plugins/seed_generation/cli.py</code></td></tr>
              </tbody>
            </table>
            <p>
              데몬 정지, 상태, 청소는 <code>core/cli/commands/lifecycle.py</code>의{" "}
              <code>stop_serve</code> / <code>show_status</code> /{" "}
              <code>do_clean</code>이 구현하지만, Typer 서브커맨드로는 노출되지
              않습니다. <code>geode update</code>가 stop과 재시작을 수행하고,{" "}
              <code>/status</code>가 데몬과 디스크 사용량 블록을 포함합니다.
              수동 정지는 <code>pkill -f &quot;geode serve&quot;</code>입니다.
            </p>

            <h2>슬래시 명령</h2>
            <p>
              SoT는 <code>core/cli/commands/_state.py</code>의{" "}
              <code>COMMAND_MAP</code>이고, 실행 위치는{" "}
              <code>core/cli/routing.py</code>의 <code>COMMAND_REGISTRY</code>가
              결정합니다. THIN은 CLI 프로세스에서 로컬로 실행되고(터미널과
              브라우저가 붙어 있어야 하는 명령), 나머지는 IPC{" "}
              <code>send_command</code>로 데몬에 전달됩니다.
            </p>
            <table>
              <thead>
                <tr><th>명령</th><th>별칭</th><th>실행 위치</th><th>용도</th><th>핸들러</th></tr>
              </thead>
              <tbody>
                <tr><td><code>/help</code></td><td></td><td>THIN</td><td>대화형 도움말</td><td><code>core/cli/commands/_state.py</code></td></tr>
                <tr><td><code>/login</code></td><td></td><td>THIN</td><td>플랜과 자격 대시보드. <code>openai</code>, <code>anthropic</code>, <code>add</code>, <code>use</code>, <code>route</code>, <code>quota</code>, <code>source</code></td><td><code>core/cli/commands/login.py</code></td></tr>
                <tr><td><code>/key &lt;value&gt;</code></td><td></td><td>THIN</td><td>PAYG API 키 빠른 등록(/login의 legacy 별칭)</td><td><code>core/cli/commands/key.py</code></td></tr>
                <tr><td><code>/model</code></td><td></td><td>THIN</td><td>모델 확인과 전환. Tab으로 역할(primary, reflection, mutator) 순환</td><td><code>core/cli/commands/model.py</code></td></tr>
                <tr><td><code>/audit</code></td><td></td><td>THIN</td><td><code>geode audit</code>의 슬래시 형태</td><td><code>plugins/petri_audit/cli_audit.py</code></td></tr>
                <tr><td><code>/audit-seeds</code></td><td></td><td>THIN</td><td>시드 후보 생성 파이프라인</td><td><code>plugins/seed_generation/cli.py</code></td></tr>
                <tr><td><code>/self-improving</code></td><td><code>/sil</code></td><td>THIN</td><td>자기개선 루프 운영. <code>status</code>, <code>run</code>, <code>history</code>, <code>rollback</code>, <code>config</code>, <code>source</code>, <code>matrix</code></td><td><code>core/cli/commands/self_improving.py</code></td></tr>
                <tr><td><code>/recall</code></td><td></td><td>THIN</td><td>기억 풀 <code>list</code> / <code>show</code> / <code>save</code></td><td><code>core/cli/commands/recall.py</code></td></tr>
                <tr><td><code>/quit</code></td><td><code>/exit</code>, <code>/q</code></td><td>daemon</td><td>세션 비용 요약과 함께 종료</td><td><code>core/cli/dispatcher.py</code></td></tr>
                <tr><td><code>/verbose</code></td><td></td><td>daemon</td><td>verbose 토글</td><td><code>core/cli/dispatcher.py</code></td></tr>
                <tr><td><code>/petri</code></td><td></td><td>daemon</td><td>Petri 역할 × 모델 × 소스 확인과 전환</td><td><code>core/cli/commands/petri.py</code></td></tr>
                <tr><td><code>/schedule</code></td><td><code>/sched</code></td><td>daemon</td><td>예약 자동화 관리</td><td><code>core/cli/commands/schedule.py</code></td></tr>
                <tr><td><code>/trigger</code></td><td></td><td>daemon</td><td>이벤트와 cron 트리거 관리</td><td><code>core/cli/commands/trigger.py</code></td></tr>
                <tr><td><code>/status</code></td><td></td><td>daemon</td><td>모델, 키 상태, MCP 서버, 데몬과 디스크 사용량</td><td><code>core/cli/dispatcher.py</code></td></tr>
                <tr><td><code>/mcp</code></td><td></td><td>daemon</td><td>MCP 서버 상태, 도구, 추가</td><td><code>core/cli/commands/mcp.py</code></td></tr>
                <tr><td><code>/skills</code></td><td></td><td>daemon</td><td>스킬 목록, 추가, 리로드</td><td><code>core/cli/commands/skills.py</code></td></tr>
                <tr><td><code>/skill &lt;name&gt;</code></td><td></td><td>daemon</td><td>스킬 호출. <code>context:fork</code> 서브에이전트 실행 지원</td><td><code>core/cli/commands/skills.py</code></td></tr>
                <tr><td><code>/cost</code></td><td></td><td>daemon</td><td>LLM 비용 대시보드와 예산</td><td><code>core/cli/commands/cost.py</code></td></tr>
                <tr><td><code>/resume</code></td><td></td><td>daemon</td><td>중단된 세션 재개</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/context</code></td><td><code>/ctx</code></td><td>daemon</td><td>조립된 컨텍스트 계층 표시</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/apply</code></td><td></td><td>daemon</td><td>지원서 관리</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/compact</code></td><td></td><td>daemon</td><td>대화 컨텍스트 압축</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/clear</code></td><td></td><td>daemon</td><td>대화 이력 삭제. thin 클라이언트는 IPC 모드에서 <code>--force</code>를 자동 부착</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/tasks</code></td><td><code>/task</code>, <code>/t</code></td><td>daemon</td><td>사용자 태스크 목록</td><td><code>core/cli/commands/tasks.py</code></td></tr>
              </tbody>
            </table>
            <p>
              <code>/login</code>이나 <code>/key</code>가 로컬에서 끝나면 thin
              클라이언트가 데몬에 인증 상태 리로드를 통지합니다. 인자 없는{" "}
              <code>/model</code>은 TTY에서 picker를 로컬로 띄운 뒤 선택 결과만
              데몬에 전달합니다(<code>core/cli/__init__.py</code>).
            </p>
            <p>
              picker 키 계약(<code>core/cli/effort_picker.py</code>): Tab이
              역할 탭(Primary, Reflection, Mutator)을 순환하고 ↑↓가 모델,
              ←→가 effort를 고릅니다. <strong>Space는 포커스된 역할에
              적용하고 picker를 유지</strong>하므로 세 역할을 한 세션에서
              모두 설정할 수 있습니다. Enter는 staged 선택까지 전부 확정하고
              닫으며, Esc는 staged 선택을 포함해 전부 폐기합니다. provider가
              바뀌는 전환은 credential source(payg, subscription)를 새
              provider 기준으로 다시 추론합니다. <code>/login codex</code>{" "}
              직후의 GPT 전환이 구독 쿼터로 라우팅되는 근거입니다.
            </p>

            <h2>geode-mcp 서버</h2>
            <p>
              <code>geode-mcp</code>는 GEODE를 외부 MCP 호스트(Claude Code 등)에
              도구로 노출하는 stdio 서버입니다(<code>core/mcp_server.py</code>).
              repo 루트의 <code>.mcp.json</code>이 이 프로젝트에서 연 Claude
              Code 세션에 자동 등록하고, 수동 등록은{" "}
              <code>claude mcp add geode -- geode-mcp</code>입니다. 도구 설명은{" "}
              <code>core/tools/mcp_tools.json</code>에서 로드합니다.
            </p>
            <table>
              <thead>
                <tr><th>도구</th><th>파라미터</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr><td><code>run_agent</code></td><td><code>prompt</code>, <code>time_budget_s</code></td><td>GEODE 에이전틱 원샷 1회 실행(<code>run_agentic_oneshot</code>, <code>core/cli/bootstrap.py</code>). <code>text</code>, <code>rounds</code>, <code>termination_reason</code> 반환</td></tr>
                <tr><td><code>self_improving_status</code></td><td>없음</td><td>읽기 전용. 승격된 <code>baseline.json</code>(promoted SoT, 최신 측정이 아님)과 최근 <code>mutations.jsonl</code> 행</td></tr>
                <tr><td><code>self_improving_propose</code></td><td>없음</td><td>스캐폴드 변이 1건 제안. 아무것도 쓰지 않고 diff와 rationale만 반환</td></tr>
                <tr><td><code>self_improving_apply</code></td><td><code>mutation_id</code></td><td>2단계 계약의 확인 단계. 같은 서버 세션 안의 보류 제안만 소비하고, 모르는 id는 <code>{`{applied: false}`}</code></td></tr>
                <tr><td><code>query_memory</code></td><td><code>query</code></td><td>GEODE 메모리 계층 검색(<code>core/memory/project.py</code>)</td></tr>
                <tr><td><code>get_health</code></td><td>없음</td><td>버전, 모델, 자격 상태. <code>*_credential_source</code> 필드가 OAuth와 CLI 레인도 정직하게 보고</td></tr>
                <tr><td>리소스 <code>geode://soul</code></td><td>없음</td><td>SOUL.md 내용. 없으면 빈 문자열</td></tr>
              </tbody>
            </table>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr><td><code>geode &quot;...&quot;</code>가 No such command</td><td>원샷 미지원</td><td>bare <code>geode</code>로 REPL에 들어가 자유 텍스트를 입력합니다.</td></tr>
                <tr><td><code>geode serve</code> 기동 거부</td><td><code>gateway_enabled</code> 꺼짐</td><td><code>~/.geode/.env</code>에 <code>GEODE_GATEWAY_ENABLED=true</code>를 추가합니다.</td></tr>
                <tr><td>배너 모델과 응답 모델 불일치</td><td>오래된 데몬 둘 이상이 소켓을 두고 경합</td><td><code>pkill -f &quot;geode serve&quot;</code> 후 재진입합니다. <code>ps aux | grep</code>은 긴 경로가 잘려 못 잡습니다.</td></tr>
                <tr><td><code>geode seeds assemble</code>이 exit 2</td><td>wheel 설치에는 <code>scripts/</code>가 없음</td><td>repo 체크아웃에서 실행합니다.</td></tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/run/serve">데몬으로 실행</a>. serve의 운영 면.</li>
              <li><a href="/geode/docs/runtime/tools/mcp">MCP 서버</a>. 클라이언트 방향(외부 도구 붙이기).</li>
              <li><a href="/geode/docs/config/basics">설정 기초</a>. <code>geode config explain</code>이 읽는 레이어들.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE has two entry points: <code>geode</code> (a Typer CLI) and{" "}
              <code>geode-mcp</code> (a stdio MCP server). Both are declared in{" "}
              <code>pyproject.toml</code> under <code>[project.scripts]</code>{" "}
              and land in <code>core/cli/__init__.py</code> and{" "}
              <code>core/mcp_server.py</code>. This page is the complete
              reference for both surfaces.
            </p>
            <p>
              Two honest limits first. A shell one-shot{" "}
              <code>geode &quot;prompt&quot;</code> is not supported; an
              unrecognized first token ends in click&apos;s &quot;No such
              command&quot; error. Free text goes inside the interactive REPL
              you enter with bare <code>geode</code>. And there is no{" "}
              <code>geode serve stop</code> subcommand: the stop logic exists in{" "}
              <code>core/cli/commands/lifecycle.py</code> but is not exposed on
              the Typer surface.
            </p>

            <h2>Two-process split</h2>
            <pre>{`geode (thin CLI)  ── Unix socket IPC (~/.geode/cli.sock) ──→  geode serve (daemon)
  free text → send_prompt streaming                            AgenticLoop, MCP, scheduler,
  slash → core/cli/routing.py picks THIN vs daemon             messenger pollers, CLIPoller`}</pre>
            <p>
              Bare <code>geode</code> renders the welcome screen, probes the
              socket, and auto-starts the daemon if absent
              (<code>start_serve_if_needed</code> in{" "}
              <code>core/cli/ipc_client.py</code>, with a pidfile flock against
              concurrent starts). The thin REPL then attaches over IPC. The
              protocol is line-delimited JSON; the server-side peer is{" "}
              <code>CLIPoller</code> (<code>core/server/ipc_server/poller.py</code>).
            </p>

            <h2>Top-level commands</h2>
            <table>
              <thead>
                <tr><th>Command</th><th>Purpose</th><th>Key options</th><th>Code</th></tr>
              </thead>
              <tbody>
                <tr><td><code>geode</code></td><td>Welcome screen, auto-start serve if needed, enter the thin REPL</td><td><code>--version</code>, <code>--continue</code>, <code>--resume &lt;id&gt;</code></td><td><code>core/cli/__init__.py</code></td></tr>
                <tr><td><code>geode version</code></td><td>Print the version</td><td>none</td><td><code>core/cli/typer_commands.py</code></td></tr>
                <tr><td><code>geode about</code></td><td>One screen of what is running: EFFECTIVE model, env-masks-toml warning, paths, daemon socket state</td><td>none</td><td><code>core/cli/typer_commands.py</code></td></tr>
                <tr><td><code>geode setup</code></td><td>First-time wizard; detects ChatGPT subscription OAuth (<code>~/.codex/auth.json</code>) before asking for API keys</td><td><code>--reset/-r</code></td><td><code>core/cli/onboarding.py</code></td></tr>
                <tr><td><code>geode doctor [target]</code></td><td>Diagnostics. Default <code>bootstrap</code> checks Python, PATH, credentials, daemon; <code>slack</code> checks the gateway</td><td>positional <code>bootstrap</code> | <code>slack</code></td><td><code>core/cli/doctor_bootstrap.py</code>, <code>core/cli/doctor.py</code></td></tr>
                <tr><td><code>geode update</code></td><td>Update a source checkout and reinstall the CLI; restarts serve if it was running</td><td><code>--dry-run</code>, <code>--force/-f</code>, <code>--restart/--no-restart</code></td><td><code>core/cli/commands/lifecycle.py</code></td></tr>
                <tr><td><code>geode uninstall</code></td><td>Remove runtime data and the installed CLI</td><td><code>--dry-run</code>, <code>--force/-f</code>, <code>--keep-config</code>, <code>--keep-data</code></td><td><code>core/cli/commands/lifecycle.py</code></td></tr>
                <tr><td><code>geode init</code></td><td>Create the <code>.geode/</code> project skeleton; auto-detects the project type</td><td><code>--force/-f</code></td><td><code>core/cli/typer_init.py</code></td></tr>
                <tr><td><code>geode history</code></td><td>Execution history and monthly cost summary</td><td><code>--limit/-n</code>, <code>--month/-m YYYY-MM</code></td><td><code>core/llm/usage_store.py</code></td></tr>
                <tr><td><code>geode serve</code></td><td>Headless gateway daemon: messenger pollers, scheduler, IPC socket. Requires <code>gateway_enabled</code></td><td><code>--poll/-p</code></td><td><code>core/cli/typer_serve.py</code></td></tr>
                <tr><td><code>geode audit</code></td><td>Run a Petri × GEODE alignment audit</td><td><code>--judge/-j</code>, <code>--auditor/-a</code>, <code>--target/-t</code>, <code>--seeds/-s</code>, <code>--max-turns/-m</code>, <code>--seed-select</code>, <code>--dim-set</code>, <code>--dry-run/--live</code>, <code>--unrestricted</code>, <code>--cache/--no-cache</code></td><td><code>plugins/petri_audit/cli_audit.py</code></td></tr>
                <tr><td><code>geode petri-archive</code></td><td>Persist a petri eval log outside the worktree plus a YAML summary</td><td><code>--raw-archive-dir</code>, <code>--summary-dir</code></td><td><code>plugins/petri_audit/cli_audit.py</code></td></tr>
                <tr><td><code>geode outer-bundle</code></td><td>Crosswalk self-improving activity into one timeline</td><td><code>--limit</code>, <code>--json</code></td><td><code>core/cli/outer_bundle.py</code></td></tr>
                <tr><td><code>geode reindex</code></td><td>Rebuild the cross-project FTS5 index at <code>~/.geode/search/global.db</code></td><td><code>--projects-root</code></td><td><code>core/cli/commands/reindex.py</code></td></tr>
                <tr><td><code>geode campaign</code></td><td>Thin forwarder for the 3-arm self-improving campaign driver</td><td><code>--n</code>, <code>--k</code>, <code>--arms</code>, <code>--dry-run</code></td><td><code>core/self_improving/campaign.py</code></td></tr>
              </tbody>
            </table>

            <h2>Subcommand groups</h2>
            <table>
              <thead>
                <tr><th>Group</th><th>Subcommands</th><th>Purpose</th><th>Code</th></tr>
              </thead>
              <tbody>
                <tr><td><code>geode adapters</code></td><td><code>list</code> / <code>detect-model</code> / <code>stats</code></td><td>Inspect registered LLM adapters (PAYG, subscription, CLI lanes) and dispatch statistics</td><td><code>core/cli/commands/adapters.py</code></td></tr>
                <tr><td><code>geode skill</code></td><td><code>list</code> / <code>create</code> / <code>remove</code> / <code>show</code></td><td>Manage skills across three tiers: builtin <code>core/skills/</code>, project <code>.geode/skills/</code>, personal <code>~/.geode/skills/</code></td><td><code>core/cli/commands/skill.py</code></td></tr>
                <tr><td><code>geode config</code></td><td><code>explain [key]</code> / <code>migrate-petri-toml</code></td><td>Per-layer candidate table for a setting: which layer wins, which are masked</td><td><code>core/cli/commands/config.py</code></td></tr>
                <tr><td><code>geode seeds</code></td><td><code>assemble</code></td><td>Assemble the cycle-input seed pool. Repo-checkout-only wrapper</td><td><code>core/cli/commands/seed_pool.py</code></td></tr>
                <tr><td><code>geode hub</code></td><td><code>build</code></td><td>Build the self-improving hub static pages. Repo-checkout-only wrapper</td><td><code>core/cli/commands/seed_pool.py</code></td></tr>
                <tr><td><code>geode audit-seeds</code></td><td><code>generate</code> / <code>resume</code> / <code>config</code></td><td>Seed-generation pipeline for one target dim, resumable from per-phase checkpoints</td><td><code>plugins/seed_generation/cli.py</code></td></tr>
              </tbody>
            </table>
            <p>
              Daemon stop, status, and cleanup live in{" "}
              <code>core/cli/commands/lifecycle.py</code> (<code>stop_serve</code>,{" "}
              <code>show_status</code>, <code>do_clean</code>) but are not Typer
              subcommands. <code>geode update</code> performs stop plus restart,
              and <code>/status</code> includes the daemon and disk-usage block.
              Manual stop is <code>pkill -f &quot;geode serve&quot;</code>.
            </p>

            <h2>Slash commands</h2>
            <p>
              The source of truth is <code>COMMAND_MAP</code> in{" "}
              <code>core/cli/commands/_state.py</code>; execution location is
              decided by <code>COMMAND_REGISTRY</code> in{" "}
              <code>core/cli/routing.py</code>. THIN runs locally in the CLI
              process (commands that need the terminal or a browser); everything
              else is relayed to the daemon via IPC <code>send_command</code>.
            </p>
            <table>
              <thead>
                <tr><th>Command</th><th>Aliases</th><th>Runs in</th><th>Purpose</th><th>Handler</th></tr>
              </thead>
              <tbody>
                <tr><td><code>/help</code></td><td></td><td>THIN</td><td>Interactive-mode help</td><td><code>core/cli/commands/_state.py</code></td></tr>
                <tr><td><code>/login</code></td><td></td><td>THIN</td><td>Plans and credentials dashboard: <code>openai</code>, <code>anthropic</code>, <code>add</code>, <code>use</code>, <code>route</code>, <code>quota</code>, <code>source</code></td><td><code>core/cli/commands/login.py</code></td></tr>
                <tr><td><code>/key &lt;value&gt;</code></td><td></td><td>THIN</td><td>Quick PAYG API key (legacy alias for /login)</td><td><code>core/cli/commands/key.py</code></td></tr>
                <tr><td><code>/model</code></td><td></td><td>THIN</td><td>Show and switch models; Tab cycles agent roles (primary, reflection, mutator)</td><td><code>core/cli/commands/model.py</code></td></tr>
                <tr><td><code>/audit</code></td><td></td><td>THIN</td><td>Slash form of <code>geode audit</code></td><td><code>plugins/petri_audit/cli_audit.py</code></td></tr>
                <tr><td><code>/audit-seeds</code></td><td></td><td>THIN</td><td>Seed candidate generation pipeline</td><td><code>plugins/seed_generation/cli.py</code></td></tr>
                <tr><td><code>/self-improving</code></td><td><code>/sil</code></td><td>THIN</td><td>Self-improving loop ops: <code>status</code>, <code>run</code>, <code>history</code>, <code>rollback</code>, <code>config</code>, <code>source</code>, <code>matrix</code></td><td><code>core/cli/commands/self_improving.py</code></td></tr>
                <tr><td><code>/recall</code></td><td></td><td>THIN</td><td>Memory pool <code>list</code> / <code>show</code> / <code>save</code></td><td><code>core/cli/commands/recall.py</code></td></tr>
                <tr><td><code>/quit</code></td><td><code>/exit</code>, <code>/q</code></td><td>daemon</td><td>Exit with a session cost summary</td><td><code>core/cli/dispatcher.py</code></td></tr>
                <tr><td><code>/verbose</code></td><td></td><td>daemon</td><td>Toggle verbose mode</td><td><code>core/cli/dispatcher.py</code></td></tr>
                <tr><td><code>/petri</code></td><td></td><td>daemon</td><td>Show and switch Petri role × model × source</td><td><code>core/cli/commands/petri.py</code></td></tr>
                <tr><td><code>/schedule</code></td><td><code>/sched</code></td><td>daemon</td><td>Manage scheduled automations</td><td><code>core/cli/commands/schedule.py</code></td></tr>
                <tr><td><code>/trigger</code></td><td></td><td>daemon</td><td>Manage event and cron triggers</td><td><code>core/cli/commands/trigger.py</code></td></tr>
                <tr><td><code>/status</code></td><td></td><td>daemon</td><td>Model, credential state, MCP servers, daemon and disk usage</td><td><code>core/cli/dispatcher.py</code></td></tr>
                <tr><td><code>/mcp</code></td><td></td><td>daemon</td><td>MCP server status, tools, add</td><td><code>core/cli/commands/mcp.py</code></td></tr>
                <tr><td><code>/skills</code></td><td></td><td>daemon</td><td>List, add, reload skills</td><td><code>core/cli/commands/skills.py</code></td></tr>
                <tr><td><code>/skill &lt;name&gt;</code></td><td></td><td>daemon</td><td>Invoke a skill; supports <code>context:fork</code> sub-agent execution</td><td><code>core/cli/commands/skills.py</code></td></tr>
                <tr><td><code>/cost</code></td><td></td><td>daemon</td><td>LLM cost dashboard and budget</td><td><code>core/cli/commands/cost.py</code></td></tr>
                <tr><td><code>/resume</code></td><td></td><td>daemon</td><td>Resume an interrupted session</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/context</code></td><td><code>/ctx</code></td><td>daemon</td><td>Show the assembled context tiers</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/apply</code></td><td></td><td>daemon</td><td>Manage job applications</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/compact</code></td><td></td><td>daemon</td><td>Compact the conversation context</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/clear</code></td><td></td><td>daemon</td><td>Clear history; the thin client auto-appends <code>--force</code> in IPC mode</td><td><code>core/cli/commands/session.py</code></td></tr>
                <tr><td><code>/tasks</code></td><td><code>/task</code>, <code>/t</code></td><td>daemon</td><td>Show the user task list</td><td><code>core/cli/commands/tasks.py</code></td></tr>
              </tbody>
            </table>
            <p>
              After <code>/login</code> or <code>/key</code> finish locally, the
              thin client notifies the daemon to reload auth state.{" "}
              <code>/model</code> with no arguments runs the interactive picker
              locally on a TTY, then relays only the chosen model to the daemon
              (<code>core/cli/__init__.py</code>).
            </p>
            <p>
              Picker key contract (<code>core/cli/effort_picker.py</code>): Tab
              cycles the role tabs (Primary, Reflection, Mutator), ↑↓ pick the
              model, ←→ pick effort. <strong>Space applies the focused row to
              the focused role and keeps the picker open</strong>, so all three
              roles can be set in one session. Enter confirms everything
              (including staged picks) and closes; Esc discards everything,
              staged picks included. A provider-changing switch re-infers the
              credential source (payg, subscription) for the new provider,
              which is why a GPT switch right after <code>/login codex</code>{" "}
              routes through the subscription quota.
            </p>

            <h2>The geode-mcp server</h2>
            <p>
              <code>geode-mcp</code> is the stdio server that exposes GEODE as a
              tool to external MCP hosts such as Claude Code
              (<code>core/mcp_server.py</code>). The repo ships{" "}
              <code>.mcp.json</code> at its root, which registers the server for
              Claude Code sessions opened in this project; manual registration
              is <code>claude mcp add geode -- geode-mcp</code>. Tool
              descriptions load from <code>core/tools/mcp_tools.json</code>.
            </p>
            <table>
              <thead>
                <tr><th>Tool</th><th>Params</th><th>Behavior</th></tr>
              </thead>
              <tbody>
                <tr><td><code>run_agent</code></td><td><code>prompt</code>, <code>time_budget_s</code></td><td>Runs one GEODE agentic one-shot (<code>run_agentic_oneshot</code>, <code>core/cli/bootstrap.py</code>); returns <code>text</code>, <code>rounds</code>, <code>termination_reason</code></td></tr>
                <tr><td><code>self_improving_status</code></td><td>none</td><td>Read-only: the promoted <code>baseline.json</code> (the promoted SoT, not the latest measurement) plus recent <code>mutations.jsonl</code> rows</td></tr>
                <tr><td><code>self_improving_propose</code></td><td>none</td><td>Proposes one scaffold mutation; writes nothing, returns the diff and rationale</td></tr>
                <tr><td><code>self_improving_apply</code></td><td><code>mutation_id</code></td><td>The confirmation step of the deliberate two-step contract; consumes a pending proposal from the same server session, unknown ids return <code>{`{applied: false}`}</code></td></tr>
                <tr><td><code>query_memory</code></td><td><code>query</code></td><td>Search GEODE memory tiers (<code>core/memory/project.py</code>)</td></tr>
                <tr><td><code>get_health</code></td><td>none</td><td>Version, model, credential state; the <code>*_credential_source</code> fields report OAuth and CLI lanes honestly</td></tr>
                <tr><td>resource <code>geode://soul</code></td><td>none</td><td>SOUL.md content, empty string if absent</td></tr>
              </tbody>
            </table>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr><td><code>geode &quot;...&quot;</code> says No such command</td><td>One-shots are not supported</td><td>Enter the REPL with bare <code>geode</code> and type free text there.</td></tr>
                <tr><td><code>geode serve</code> refuses to start</td><td><code>gateway_enabled</code> is off</td><td>Add <code>GEODE_GATEWAY_ENABLED=true</code> to <code>~/.geode/.env</code>.</td></tr>
                <tr><td>Banner model differs from the answering model</td><td>Multiple stale daemons fight over the socket</td><td><code>pkill -f &quot;geode serve&quot;</code>, then re-enter. <code>ps aux | grep</code> truncates the long path and misses them.</td></tr>
                <tr><td><code>geode seeds assemble</code> exits 2</td><td>Wheel installs ship no <code>scripts/</code></td><td>Run from a repo checkout.</td></tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/run/serve">Run as a daemon</a>. The operational side of serve.</li>
              <li><a href="/geode/docs/runtime/tools/mcp">MCP servers</a>. The client direction: attaching external tools.</li>
              <li><a href="/geode/docs/config/basics">Configuration basics</a>. The layers <code>geode config explain</code> reads.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
