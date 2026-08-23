import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "MCP servers — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/tools/mcp"
      title="MCP servers"
      titleKo="MCP 서버"
      summary="Both sides of MCP: the client that attaches external servers (config priority, env expansion, result guard) and geode-mcp, the server GEODE ships."
      summaryKo="MCP의 양면입니다. 외부 서버를 붙이는 클라이언트(설정 우선순위, env 확장, 결과 가드)와 GEODE가 출하하는 서버 geode-mcp를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 MCP의 양쪽에 다 섭니다. 클라이언트로서 외부 MCP 서버의
              도구를 에이전트 도구 목록에 합치고(<code>core/mcp/</code>),
              서버로서 자신의 능력을 다른 MCP 호스트에 노출합니다
              (<code>geode-mcp</code>, <code>geode_product/mcp_server.py</code>).
            </p>

            <h2>클라이언트: 서버 설정과 우선순위</h2>
            <p>
              <code>core/mcp/manager.py</code>의
              <code>MCPServerManager</code>가 세 곳에서 서버 설정을 읽습니다.
              같은 이름이 겹치면 더 가까운 쪽이 이깁니다.
            </p>
            <p>
              manager는 기존 호출 경로를 유지하는 facade입니다. 설정·env는
              <code>config_catalog.py</code>, stdio 연결과 재시작은
              <code>connection_pool.py</code>, 도구 발견·호출·결과 보정은
              <code>tool_runtime.py</code>, signal/atexit 정리는
              <code>lifecycle.py</code>가 각각 소유합니다.
            </p>
            <table>
              <thead>
                <tr><th>우선</th><th>위치</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr><td>1</td><td><code>.geode/config.toml</code>의 <code>[mcp.servers]</code></td><td>프로젝트 override.</td></tr>
                <tr><td>2</td><td><code>~/.geode/config.toml</code>의 <code>[mcp.servers]</code></td><td>전역 사용자 설정.</td></tr>
                <tr><td>3</td><td><code>.claude/mcp_servers.json</code></td><td>레거시 폴백 겸 설치 타깃. 앞 두 층에 없는 이름만 추가됩니다.</td></tr>
              </tbody>
            </table>
            <p>
              서버 env의 <code>${`{VAR}`}</code> 참조는 os.environ을 먼저
              보고, 없으면 <code>.env</code> 값(전역이 프로젝트를 덮음)
              으로 확장됩니다. 필수 env가 빈 값으로 해석된 서버는 연결을
              시도하지 않고 건너뜁니다. 연결과 실패는
              <code>MCP_SERVER_CONNECTED</code> /
              <code>MCP_SERVER_FAILED</code> 훅으로 관측됩니다. 전송은
              stdio입니다(<code>core/mcp/stdio_client.py</code>).
            </p>
            <p>
              stdio 서버 연결이 실패하면 같은 서버는 짧은 시간 동안 실패로
              기억됩니다. 도구 목록을 다시 만들 때 같은 프로세스를 즉시
              재시도해 <code>MCP_SERVER_FAILED</code> 로그를 반복해서 쌓지
              않기 위한 장치입니다. 운영자가 설정을 고쳤거나 서버를 강제로
              재시작하는 경우에는 헬스 체크와 서버 재등록 경로가 이 실패
              캐시를 비우고 다시 연결을 시도합니다.
            </p>

            <h3>실행 신뢰와 broker 경계</h3>
            <p>
              서버 설정은 명령을 찾기 위한 매니페스트일 뿐 승인 자체가 아닙니다.
              아래 <code>mcp:filesystem</code> ID를
              <a href="/geode/docs/config/basics">확장 신뢰 정책</a>에서도
              같은 <code>execution</code>과 capability로 승인해야 합니다.
            </p>
            <pre>{`[mcp.servers.filesystem]
command = "/usr/bin/acme-mcp"
args = ["--workspace", "/work"]
execution = "brokered"
capabilities = ["stdio"]
resource_keys = ["workspace"]

[mcp.servers.filesystem.env]
LOG_LEVEL = "warning"`}</pre>
            <table>
              <thead><tr><th>모드</th><th>실행 계약</th></tr></thead>
              <tbody>
                <tr><td><code>trusted</code></td><td>운영자가 완전히 신뢰한 호환 경로입니다. 기존처럼 sandbox 없이 실행되고 프로세스 환경을 상속합니다.</td></tr>
                <tr><td><code>brokered</code></td><td>기본 거부·네트워크 차단 OS sandbox 안에서 시스템 runtime 읽기와 격리 scratch만 허용하고, 설정에 적힌 env만 전달합니다. 지원되는 <code>sandbox-exec</code> 또는 <code>bwrap</code>가 없으면 실행하지 않습니다.</td></tr>
              </tbody>
            </table>
            <p>
              읽기 전용 여부는 MCP tool annotation의 <code>readOnlyHint</code>로
              판단합니다. 그 외 도구는 config에 하나 이상의 정적
              <code>resource_keys</code>가 있어야 하며, 없으면 dispatch 전에
              거부됩니다. GEODE는 MCP 인자 이름을 보고 resource identity를
              추측하지 않습니다.
            </p>

            <h2>클라이언트: 실행 경로와 가드</h2>
            <p>
              발견된 MCP 도구는 네이티브 도구와 합쳐져 에이전트에
              노출됩니다(<code>core/agent/loop/_tool_factory.py</code>).
              도구 수가 임계값을 넘으면 deferred loading이 켜져
              <code>tool_search</code>로 찾아 로드합니다. 검색 스코어링은
              <code>core/mcp/registry.py</code>에 있습니다.
            </p>
            <ul>
              <li>
                <strong>서버 단위 승인.</strong> 처음 쓰는 서버는 사용자
                확인을 거치고, 승인은 서버 단위로 기억됩니다
                (<code>core/agent/tool_executor/executor.py</code>).
              </li>
              <li>
                <strong>시크릿 마스킹.</strong> 결과의 텍스트 필드는 반환 전에
                <code>redact_secrets</code>를 통과합니다.
              </li>
              <li>
                <strong>결과 크기 가드.</strong> 모든 도구 결과는
                <code>settings.max_tool_result_tokens</code>(기본 25000)를
                넘으면 요약을 보존한 채 잘립니다
                (<code>core/agent/tool_executor/result_token_guard.py</code>).
                MCP 결과도 예외가 아닙니다. 200K 미만 컨텍스트 모델은 창의
                5%로 한 번 더 조여집니다.
              </li>
            </ul>
            <p>
              세션 안에서는 <code>/mcp</code>로 서버 상태, 도구 목록, 추가를
              관리합니다.
            </p>

            <h2>서버: geode-mcp</h2>
            <p>
              <code>geode-mcp</code>는 GEODE의 1급 엔트리 포인트입니다.
              에이전트 원샷(<code>run_agent</code>), 메모리 검색
              (<code>query_memory</code>), 자기개선 루프의 2단계
              propose/apply, 헬스 체크를 MCP 도구로 노출합니다. 저장소
              루트의 <code>.mcp.json</code>이 이 서버를 stdio로 등록해
              출하되므로, 이 프로젝트를 연 Claude Code 세션은 바로 쓸 수
              있습니다. 수동 등록은 한 줄입니다.
            </p>
            <pre>{`claude mcp add geode -- geode-mcp`}</pre>
            <p>
              기본 전송은 stdio입니다. 클라이언트가 프로세스를 직접 띄우는
              로컬 전용 경로입니다. 원격 접근은 <code>--http</code>로
              streamable HTTP 전송을 켭니다.
            </p>
            <pre>{`geode-mcp --http --host 127.0.0.1 --port 8765`}</pre>
            <table>
              <thead>
                <tr><th>바인드</th><th>토큰</th><th>동작</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>loopback</td>
                  <td>없음</td>
                  <td>허용하되 경고 로그. stdio와 같은 신뢰 경계입니다.</td>
                </tr>
                <tr>
                  <td>loopback 아님</td>
                  <td>없음</td>
                  <td>거부, exit code 2. <code>run_agent</code>가 bash와 파일
                  도구까지 닿는 원격 실행 표면이므로 토큰 없는 네트워크
                  바인드는 fail-loud입니다.</td>
                </tr>
                <tr>
                  <td>아무 곳</td>
                  <td><code>GEODE_MCP_TOKEN</code></td>
                  <td>bearer 토큰 인증. 시크릿이므로 C-2 계약대로
                  <code>~/.geode/.env</code>에 둡니다. 기동 시 공유
                  <code>load_env_files</code> 승격이 먼저 돌아 거기 적힌
                  토큰을 찾습니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>서버가 목록에 있는데 도구가 없음</td>
                  <td>필수 env 미해석으로 연결 건너뜀</td>
                  <td><code>/mcp</code>로 상태를 보고, 참조된 <code>${`{VAR}`}</code>를 <code>.env</code>에 채웁니다.</td>
                </tr>
                <tr>
                  <td>서버가 <code>REJECTED</code> 또는 <code>DEGRADED</code></td>
                  <td>정책 누락·불일치, broker sandbox 부재, 명령 또는 env 해석 실패</td>
                  <td>runtime health의 <code>extensions</code>에서 정확한 reason을 확인합니다. brokered 서버를 sandbox 없는 trusted 경로로 자동 하향하지 않습니다.</td>
                </tr>
                <tr>
                  <td>변경 도구가 resource-key 오류로 거부됨</td>
                  <td><code>readOnlyHint</code>가 아닌 도구인데 server config에 <code>resource_keys</code>가 없음</td>
                  <td>실제 변경 대상을 대표하는 보수적 정적 key를 매니페스트에 선언합니다.</td>
                </tr>
                <tr>
                  <td><code>MCP_SERVER_FAILED</code> 로그가 많음</td>
                  <td>서버 명령을 찾지 못하거나 필수 환경이 빠짐. launchd로 띄운 serve는 셸보다 PATH가 좁을 수 있음</td>
                  <td><code>~/.geode/logs/serve.log</code>에서 실패 서버 이름을 보고 <code>command -v npx</code>, <code>command -v codex</code>, <code>command -v uvx</code>가 serve 환경에서도 보이게 맞춥니다. 수정 후 serve를 재시작하면 실패 캐시가 비워집니다.</td>
                </tr>
                <tr>
                  <td>MCP 결과가 잘려서 옴</td>
                  <td>결과 크기 가드 작동</td>
                  <td>정상 동작입니다. 더 좁은 쿼리로 다시 호출하거나 <code>max_tool_result_tokens</code>를 조정합니다.</td>
                </tr>
                <tr>
                  <td><code>geode-mcp --http</code>가 exit 2</td>
                  <td>비 loopback 바인드에 토큰 없음</td>
                  <td><code>GEODE_MCP_TOKEN</code>을 <code>~/.geode/.env</code>나 환경에 설정합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/harness/cli">CLI와 슬래시 명령</a>. geode-mcp 도구 표면의 전체 레퍼런스.</li>
              <li><a href="/geode/docs/runtime/research">리서치·탐색과 llms.txt</a>. 외부 호스트에서 query_memory를 쓰는 맥락.</li>
              <li><a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>. deferred loading의 자세한 동작.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE stands on both sides of MCP. As a client it merges
              external MCP servers&apos; tools into the agent&apos;s tool list
              (<code>core/mcp/</code>); as a server it exposes its own
              capabilities to other MCP hosts (<code>geode-mcp</code>,
              <code>geode_product/mcp_server.py</code>).
            </p>

            <h2>Client: server config and priority</h2>
            <p>
              <code>MCPServerManager</code> in <code>core/mcp/manager.py</code>
              reads server definitions from three places. On a name clash the
              closer layer wins.
            </p>
            <p>
              The manager remains the compatibility facade. Configuration and
              env expansion live in <code>config_catalog.py</code>, stdio
              connection/restart state in <code>connection_pool.py</code>, tool
              discovery/invocation/result normalization in
              <code>tool_runtime.py</code>, and signal/atexit cleanup in
              <code>lifecycle.py</code>.
            </p>
            <table>
              <thead>
                <tr><th>Priority</th><th>Location</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr><td>1</td><td><code>[mcp.servers]</code> in <code>.geode/config.toml</code></td><td>Project override.</td></tr>
                <tr><td>2</td><td><code>[mcp.servers]</code> in <code>~/.geode/config.toml</code></td><td>Global user config.</td></tr>
                <tr><td>3</td><td><code>.claude/mcp_servers.json</code></td><td>Legacy fallback and install target. Only names absent from the two layers above are added.</td></tr>
              </tbody>
            </table>
            <p>
              <code>${`{VAR}`}</code> references in a server&apos;s env are
              expanded against os.environ first, then <code>.env</code> values
              (global authoritative over project). A server whose required env
              resolves empty is skipped without a connection attempt.
              Connections and failures are observable through the
              <code>MCP_SERVER_CONNECTED</code> /
              <code>MCP_SERVER_FAILED</code> hooks. Transport is stdio
              (<code>core/mcp/stdio_client.py</code>).
            </p>
            <p>
              A failed stdio connection is negative-cached briefly per server.
              That prevents tool-list rebuilds from retrying the same broken
              process immediately and spamming <code>MCP_SERVER_FAILED</code>.
              Intentional recovery paths such as health restart or server
              re-registration clear the cache before trying again.
            </p>

            <h3>Execution trust and the broker boundary</h3>
            <p>
              A server definition is a discovery manifest, not an authorization
              by itself. Its <code>mcp:filesystem</code> ID must also be granted
              with the same execution mode and capabilities in the
              <a href="/geode/docs/config/basics">extension trust policy</a>.
            </p>
            <pre>{`[mcp.servers.filesystem]
command = "/usr/bin/acme-mcp"
args = ["--workspace", "/work"]
execution = "brokered"
capabilities = ["stdio"]
resource_keys = ["workspace"]

[mcp.servers.filesystem.env]
LOG_LEVEL = "warning"`}</pre>
            <table>
              <thead><tr><th>Mode</th><th>Execution contract</th></tr></thead>
              <tbody>
                <tr><td><code>trusted</code></td><td>Compatibility path for code the operator fully trusts. It runs unsandboxed and inherits the process environment.</td></tr>
                <tr><td><code>brokered</code></td><td>Runs under a deny-default, no-network OS sandbox with only system runtime reads, isolated scratch, and the configured environment. Without supported <code>sandbox-exec</code> or <code>bwrap</code>, it does not launch.</td></tr>
              </tbody>
            </table>
            <p>
              GEODE treats a tool as read-only only when its MCP annotation has
              <code>readOnlyHint</code>. Every other tool requires at least one
              static <code>resource_keys</code> entry in server config and is
              rejected before dispatch if none exists. GEODE never guesses
              resource identity from MCP argument names.
            </p>

            <h2>Client: execution path and guards</h2>
            <p>
              Discovered MCP tools merge with native tools before reaching
              the agent (<code>core/agent/loop/_tool_factory.py</code>); past
              a tool-count threshold, deferred loading kicks in and tools are
              found via <code>tool_search</code>, with scoring in
              <code>core/mcp/registry.py</code>.
            </p>
            <ul>
              <li>
                <strong>Per-server approval.</strong> A first-use server goes
                through user confirmation, remembered per server
                (<code>core/agent/tool_executor/executor.py</code>).
              </li>
              <li>
                <strong>Secret redaction.</strong> Text fields of every result
                pass through <code>redact_secrets</code> before returning.
              </li>
              <li>
                <strong>Result-size guard.</strong> Any tool result above
                <code>settings.max_tool_result_tokens</code> (default 25000)
                is truncated with its summary preserved
                (<code>core/agent/tool_executor/result_token_guard.py</code>).
                MCP results are no exception. Models with a context window
                under 200K get a tighter per-result cap of 5% of the window.
              </li>
            </ul>
            <p>
              In-session, <code>/mcp</code> manages server status, tool
              listings, and additions.
            </p>

            <h2>Server: geode-mcp</h2>
            <p>
              <code>geode-mcp</code> is a first-class GEODE entry point. It
              exposes an agentic one-shot (<code>run_agent</code>), memory
              search (<code>query_memory</code>), the deliberate two-step
              propose/apply of the self-improving loop, and a health check as
              MCP tools. The repo ships <code>.mcp.json</code> at its root
              registering this server over stdio, so Claude Code sessions
              opened in this project get it for free. Manual registration is
              one line:
            </p>
            <pre>{`claude mcp add geode -- geode-mcp`}</pre>
            <p>
              The default transport is stdio: the client spawns the process,
              local only. For remote access, <code>--http</code> switches to
              the streamable HTTP transport.
            </p>
            <pre>{`geode-mcp --http --host 127.0.0.1 --port 8765`}</pre>
            <table>
              <thead>
                <tr><th>Bind</th><th>Token</th><th>Behavior</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Loopback</td>
                  <td>None</td>
                  <td>Allowed, with a logged warning. Same trust boundary as stdio.</td>
                </tr>
                <tr>
                  <td>Non-loopback</td>
                  <td>None</td>
                  <td>Refused, exit code 2. <code>run_agent</code> reaches
                  GEODE&apos;s full tool surface including bash and file ops,
                  so a tokenless network bind is a remote-execution surface
                  and fails loud.</td>
                </tr>
                <tr>
                  <td>Any</td>
                  <td><code>GEODE_MCP_TOKEN</code></td>
                  <td>Bearer-token auth. It is a secret, so per the C-2
                  contract it lives in <code>~/.geode/.env</code>; the shared
                  <code>load_env_files</code> promotion runs at startup, so a
                  token written there is found.</td>
                </tr>
              </tbody>
            </table>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>A configured server exposes no tools</td>
                  <td>Connection skipped over an unresolved required env</td>
                  <td>Check <code>/mcp</code>, then fill the referenced <code>${`{VAR}`}</code> in <code>.env</code>.</td>
                </tr>
                <tr>
                  <td>A server is <code>REJECTED</code> or <code>DEGRADED</code></td>
                  <td>Missing or mismatched policy, unavailable broker sandbox, or command/env resolution failure</td>
                  <td>Read the exact reason under <code>extensions</code> in runtime health. GEODE never silently downgrades a brokered server to trusted execution.</td>
                </tr>
                <tr>
                  <td>A mutating tool is rejected for missing resource keys</td>
                  <td>The tool lacks <code>readOnlyHint</code> and the server manifest has no <code>resource_keys</code></td>
                  <td>Declare a conservative static key representing the real mutation target.</td>
                </tr>
                <tr>
                  <td>Many <code>MCP_SERVER_FAILED</code> log lines</td>
                  <td>The server command is not visible, or required environment is missing. A launchd-started serve process can have a narrower PATH than your shell.</td>
                  <td>Read <code>~/.geode/logs/serve.log</code> for the failing server name and make <code>command -v npx</code>, <code>command -v codex</code>, and <code>command -v uvx</code> resolve in the serve environment. Restart serve after fixing it; restart clears the failure cache.</td>
                </tr>
                <tr>
                  <td>MCP results arrive truncated</td>
                  <td>The result-size guard fired</td>
                  <td>Working as intended. Re-query narrower, or tune <code>max_tool_result_tokens</code>.</td>
                </tr>
                <tr>
                  <td><code>geode-mcp --http</code> exits with code 2</td>
                  <td>Non-loopback bind without a token</td>
                  <td>Set <code>GEODE_MCP_TOKEN</code> in <code>~/.geode/.env</code> or the environment.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/harness/cli">CLI and slash commands</a>. The full reference for the geode-mcp tool surface.</li>
              <li><a href="/geode/docs/runtime/research">Research, search, and llms.txt</a>. The context for query_memory from external hosts.</li>
              <li><a href="/geode/docs/runtime/tools/protocol">Tools and toolsets</a>. Deferred loading in detail.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
