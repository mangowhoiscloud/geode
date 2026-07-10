import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Troubleshooting — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/troubleshooting"
      title="Troubleshooting"
      titleKo="문제 해결"
      summary="Common failure modes and where to look: process logs, SQLite events, and transcripts."
      summaryKo="흔한 실패 모드와 살펴볼 곳입니다. process log, SQLite event, transcript를 봅니다."
    >
      <Bi
        ko={
          <>
            <p>
              진단은 세 단 사다리입니다. <code>geode doctor</code>가 환경을
              점검하고, <code>geode about</code>이 실효 상태를 보여주고,{" "}
              <code>geode config explain</code>이 설정이 어느 레이어에서
              가려졌는지 밝힙니다. 대부분의 문제는 이 사다리를 위에서 아래로
              내려가면 잡힙니다.
            </p>

            <h2>진단 사다리</h2>
            <pre>{`1. geode doctor               # Python, PATH, 자격, 데몬 상태
2. geode about                # EFFECTIVE 모델, 경로, 소켓, 마스킹 경고
3. geode config explain model # 레이어별 후보와 WINNER
4. pkill -f "geode serve"     # 오래된 데몬 정리 후 재진입
5. geode setup -r             # 그래도 안 되면 설정을 처음부터`}</pre>
            <p>
              <code>geode config explain</code>은 한 설정 키에 대해 os.environ,
              프로젝트 .env, 전역 .env, 프로젝트 config.toml, 전역 config.toml,
              코드 기본값 순서로 후보를 표로 보여주고 어느 레이어가 이기는지
              표시합니다 (<code>core/config/explain.py</code>). 검증은 항상
              실효값 기준입니다. config.toml의 내용이 아니라{" "}
              <code>geode about</code>이 답입니다.
            </p>

            <h2>증상, 원인, 해법</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>모델을 바꿨는데 그대로</td>
                  <td>상위 레이어(.env 잔존 줄, 셸 export)가 toml을 가림</td>
                  <td><code>geode config explain model</code>로 WINNER 레이어를 찾아 그 줄을 지웁니다.</td>
                </tr>
                <tr>
                  <td>배너 모델과 응답 모델이 다름</td>
                  <td>데몬이 둘 이상 떠서 소켓 경합</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code> 후 <code>pgrep -f &quot;geode serve&quot;</code>로 비었는지 확인하고 재진입합니다. <code>ps aux | grep</code>은 긴 경로가 잘려 빈 결과를 줍니다.</td>
                </tr>
                <tr>
                  <td>응답이 비거나 인증 오류</td>
                  <td>자격 만료 또는 무효</td>
                  <td><code>geode doctor</code>가 키와 OAuth 유효성을 점검합니다. <code>/login</code>으로 갱신합니다.</td>
                </tr>
                <tr>
                  <td>응답이 비고 종료 이유가 <code>model_refusal</code></td>
                  <td>모델 안전 분류기가 거절 (HTTP 200, <code>stop_reason: refusal</code>)</td>
                  <td>요청을 바꿔 다시 묻거나 <code>/model</code>로 다른 모델을 씁니다. 카테고리가 메시지에 표시됩니다.</td>
                </tr>
                <tr>
                  <td><code>context_exhausted</code>로 종료</td>
                  <td>prune 후에도 컨텍스트 critical</td>
                  <td><code>/compact</code> 또는 <code>/clear</code> 후 작업을 쪼갭니다. <a href="/geode/docs/ops/long-running">장기 실행 안전</a> 참고.</td>
                </tr>
                <tr>
                  <td>MCP 도구가 안 보임</td>
                  <td>MCP 서버 연결 실패</td>
                  <td><code>/mcp</code>로 서버 상태와 도구 목록을 확인합니다. <code>/status</code>에도 MCP 블록이 있습니다.</td>
                </tr>
                <tr>
                  <td><code>MCP_SERVER_FAILED</code> 로그가 반복됨</td>
                  <td>serve 프로세스에서 MCP 명령(<code>npx</code>, <code>codex</code>, <code>uvx</code>)이나 필수 env를 못 찾음</td>
                  <td><code>~/.geode/logs/serve.log</code>에서 실패 서버 이름을 보고 PATH와 <code>.env</code>를 맞춥니다. 실패한 서버는 짧게 캐시되므로 수정 뒤에는 serve를 재시작합니다.</td>
                </tr>
                <tr>
                  <td>읽기 도구가 너무 자주 호출됨</td>
                  <td><code>read_document</code>, <code>grep_files</code>는 항상 로드되는 핵심 도구. tool cap에 숨은 것이 아님</td>
                  <td>dialogue transcript의 tool call을 보고 질문에 파일 범위, 제외 경로, 원하는 깊이를 명시합니다.</td>
                </tr>
                <tr>
                  <td>메신저 무반응</td>
                  <td>게이트웨이 또는 binding 문제</td>
                  <td><code>geode doctor slack</code>과 <a href="/geode/docs/run/messaging">메신저 연동</a>의 실패 표를 따릅니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>로그 위치</h2>
            <table>
              <thead>
                <tr><th>무엇</th><th>어디</th></tr>
              </thead>
              <tbody>
                <tr><td>serve 데몬 로그 (10MB × 5 로테이션)</td><td><code>~/.geode/logs/serve.log</code></td></tr>
                <tr><td>geode-mcp, 워커, 캠페인 로그</td><td><code>~/.geode/logs/</code></td></tr>
                <tr><td>세션별 lifecycle event</td><td><code>sessions.db:hook_events</code></td></tr>
                <tr><td>세션 transcript (턴 단위 대화)</td><td><code>~/.geode/transcripts/&lt;project-slug&gt;/</code></td></tr>
                <tr><td>비용 ledger</td><td><code>~/.geode/usage/YYYY-MM.jsonl</code></td></tr>
              </tbody>
            </table>
            <p>
              로그 채널 구성은{" "}
              <code>core/observability/logging_config.py</code>의{" "}
              <code>configure_logging(mode)</code>가 SoT입니다.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/guides/debug-stuck-run">멈춘 실행 디버깅</a>. transcript와 SQL event timeline을 읽는 절차.</li>
              <li><a href="/geode/docs/verification/observability">관측성</a>. 어떤 질문에 어떤 렌즈를 쓰는지.</li>
              <li><a href="/geode/docs/config/basics">설정 기초</a>. 레이어와 우선순위의 전체 그림.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Diagnosis is a three-rung ladder: <code>geode doctor</code> checks
              the environment, <code>geode about</code> shows the effective
              state, and <code>geode config explain</code> reveals which layer
              masks a setting. Most problems yield to walking the ladder top to
              bottom.
            </p>

            <h2>The diagnostic ladder</h2>
            <pre>{`1. geode doctor               # Python, PATH, credentials, daemon
2. geode about                # EFFECTIVE model, paths, socket, mask warning
3. geode config explain model # per-layer candidates and the WINNER
4. pkill -f "geode serve"     # clear stale daemons, then re-enter
5. geode setup -r             # last resort: redo setup`}</pre>
            <p>
              <code>geode config explain</code> prints, for one settings key,
              the candidates from os.environ, project .env, global .env, project
              config.toml, global config.toml, and the code default, marking
              exactly one WINNER (<code>core/config/explain.py</code>). Always
              verify against the effective value: <code>geode about</code> is
              the answer, not the contents of config.toml.
            </p>

            <h2>Symptom, cause, fix</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Switched models, nothing changed</td>
                  <td>A higher layer (a stale .env line, a shell export) masks the toml</td>
                  <td>Find the WINNER with <code>geode config explain model</code> and remove its line.</td>
                </tr>
                <tr>
                  <td>Banner model differs from the answering model</td>
                  <td>Multiple daemons fighting over the socket</td>
                  <td><code>pkill -f &quot;geode serve&quot;</code>, confirm empty with <code>pgrep -f &quot;geode serve&quot;</code>, re-enter. <code>ps aux | grep</code> truncates the long path and matches nothing.</td>
                </tr>
                <tr>
                  <td>Empty replies or auth errors</td>
                  <td>Expired or invalid credentials</td>
                  <td><code>geode doctor</code> validates keys and OAuth; refresh with <code>/login</code>.</td>
                </tr>
                <tr>
                  <td>Empty reply ending in <code>model_refusal</code></td>
                  <td>The model&apos;s safety classifier declined (HTTP 200, <code>stop_reason: refusal</code>)</td>
                  <td>Rephrase, or switch with <code>/model</code>. The category appears in the message.</td>
                </tr>
                <tr>
                  <td>Run ends as <code>context_exhausted</code></td>
                  <td>Context still critical after pruning</td>
                  <td><code>/compact</code> or <code>/clear</code>, then split the task. See <a href="/geode/docs/ops/long-running">Long-running safety</a>.</td>
                </tr>
                <tr>
                  <td>MCP tools missing</td>
                  <td>An MCP server failed to connect</td>
                  <td><code>/mcp</code> shows server state and tools; <code>/status</code> carries an MCP block too.</td>
                </tr>
                <tr>
                  <td><code>MCP_SERVER_FAILED</code> repeats in logs</td>
                  <td>The serve process cannot see an MCP command (<code>npx</code>, <code>codex</code>, <code>uvx</code>) or required env</td>
                  <td>Use <code>~/.geode/logs/serve.log</code> to find the server name, then fix PATH and <code>.env</code>. Failed servers are briefly cached, so restart serve after fixing the environment.</td>
                </tr>
                <tr>
                  <td>Read tools fire too often</td>
                  <td><code>read_document</code> and <code>grep_files</code> are always-loaded core tools; this is not the tool cap hiding them</td>
                  <td>Inspect tool calls in the dialogue transcript, then constrain file scope, excluded paths, or desired depth in the prompt.</td>
                </tr>
                <tr>
                  <td>Messenger silence</td>
                  <td>Gateway or binding trouble</td>
                  <td>Run <code>geode doctor slack</code> and follow the failure table in <a href="/geode/docs/run/messaging">Messaging integrations</a>.</td>
                </tr>
              </tbody>
            </table>

            <h2>Where logs live</h2>
            <table>
              <thead>
                <tr><th>What</th><th>Where</th></tr>
              </thead>
              <tbody>
                <tr><td>Serve daemon log (10MB times 5 rotation)</td><td><code>~/.geode/logs/serve.log</code></td></tr>
                <tr><td>geode-mcp, worker, campaign logs</td><td><code>~/.geode/logs/</code></td></tr>
                <tr><td>Per-session lifecycle events</td><td><code>sessions.db:hook_events</code></td></tr>
                <tr><td>Session transcripts (per-turn dialogue)</td><td><code>~/.geode/transcripts/&lt;project-slug&gt;/</code></td></tr>
                <tr><td>Cost ledger</td><td><code>~/.geode/usage/YYYY-MM.jsonl</code></td></tr>
              </tbody>
            </table>
            <p>
              The log channel layout is owned by{" "}
              <code>configure_logging(mode)</code> in{" "}
              <code>core/observability/logging_config.py</code>.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/guides/debug-stuck-run">Debug a stuck run</a>. Reading the transcript and SQL event timeline.</li>
              <li><a href="/geode/docs/verification/observability">Observability</a>. Which lens answers which question.</li>
              <li><a href="/geode/docs/config/basics">Configuration basics</a>. The full layer picture.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
