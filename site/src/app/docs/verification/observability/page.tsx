import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Observability — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/observability"
      title="Observability"
      titleKo="관측성"
      summary="The lenses on a run. Hooks, run logs, transcripts, session metrics, and the logging switchboard."
      summaryKo="실행을 들여다보는 렌즈들입니다. 훅, run log, 트랜스크립트, 세션 메트릭, 로깅 스위치보드를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE는 외부 tracing SaaS 없이 스스로를 관측합니다. 훅 이벤트가
              1차 신호이고, 자체 렌즈들이 같은 실행을 다른 단위로 봅니다. 전부
              디스크의 JSONL이라 jq로 바로 열립니다.
            </p>

            <h2>렌즈 한눈에</h2>
            <table>
              <thead>
                <tr><th>렌즈</th><th>단위</th><th>위치</th><th>코드</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Hooks</td>
                  <td>라이프사이클 이벤트</td>
                  <td>(인메모리, 아래 렌즈들의 소스)</td>
                  <td><code>core/hooks/system.py</code></td>
                </tr>
                <tr>
                  <td>RunLog</td>
                  <td>세션당 훅 이벤트 시계열</td>
                  <td><code>~/.geode/runs/&lt;session_key&gt;.jsonl</code></td>
                  <td><code>core/observability/run_log.py</code></td>
                </tr>
                <tr>
                  <td>SessionTranscript</td>
                  <td>턴 단위 대화와 도구 호출</td>
                  <td><code>~/.geode/transcripts/&lt;slug&gt;/</code></td>
                  <td><code>core/observability/transcript.py</code></td>
                </tr>
                <tr>
                  <td>SessionMetrics</td>
                  <td>세션 누적 집계 한 행</td>
                  <td>자기개선 루프 홈의 <code>sessions.jsonl</code></td>
                  <td><code>core/observability/session_metrics.py</code></td>
                </tr>
                <tr>
                  <td>Usage ledger</td>
                  <td>LLM 호출당 토큰과 비용</td>
                  <td><code>~/.geode/usage/YYYY-MM.jsonl</code></td>
                  <td><code>core/llm/usage_store.py</code></td>
                </tr>
                <tr>
                  <td>프로세스 로그</td>
                  <td>프로세스별 로테이팅 파일</td>
                  <td><code>~/.geode/logs/</code></td>
                  <td><code>core/observability/logging_config.py</code></td>
                </tr>
              </tbody>
            </table>

            <h2>훅이 렌즈가 되는 방식</h2>
            <p>
              발화 지점의 SoT는 <code>HookEvent</code> enum 64종입니다. LLM 호출,
              도구 실행, 세션 경계, 컨텍스트 오버플로, 모델 전환, 변이
              라이프사이클까지 의미 있는 경계마다 이벤트가 발화합니다. 관측은 이
              위에 와일드카드 구독 두 개로 얹혀 있습니다.
            </p>
            <ul>
              <li>
                run log writer. bootstrap이 <code>register_prefix(&quot;*&quot;, ...)</code>로
                모든 이벤트를 구독해 세션별 <code>RunLogEntry</code>로 적습니다
                (<code>core/wiring/bootstrap.py</code>). 새 HookEvent를 추가하면
                자동으로 run log에 잡힙니다.
              </li>
              <li>
                transcript 미러. 활성 RunTranscript가 있으면 모든 훅 발화가
                activity 행으로 미러됩니다 (<code>core/hooks/system.py</code>,{" "}
                <code>core/observability/activity_registry.py</code>).
              </li>
            </ul>
            <p>
              한때 문서에 있던 PIPELINE_*, NODE_* 류의 자동화 파이프라인
              이벤트는 존재하지 않습니다. enum에 없는 이벤트를 구독하는 코드는
              발화하지 않는 죽은 코드입니다.
            </p>

            <h2>RunLog와 JobRunLog: 하나의 JSONL 규율</h2>
            <p>
              세션 run log와 스케줄러 job run log는 같은 패턴(잠금 append,
              newest-first 읽기, 크기 초과 시 원자적 prune)을 쓰므로 v0.99.159에서
              공통 베이스 <code>JsonlAppendLog</code>로 접혔습니다. 파일은 2MB를
              넘으면 최신 2000줄로 잘립니다.
            </p>
            <pre>{`# ~/.geode/runs/<session_key>.jsonl 한 줄
{"session_key": "...", "event": "llm_call_ended",
 "node": "", "status": "ok", "duration_ms": 4218.0,
 "metadata": {...}, "timestamp": 1780000000.0, "run_id": "..."}`}</pre>
            <p>
              이 파일은 <code>geode adapters stats</code>의 데이터 소스이기도
              합니다. <code>ADAPTER_DISPATCH_ATTEMPT</code> 이벤트를 집계해
              어댑터별 성공률과 p50/p95 지연을 보여줍니다
              (<code>core/cli/commands/adapters.py</code>).
            </p>

            <h2>sessions.jsonl: 실행 한 번이 한 행</h2>
            <p>
              <code>SessionMetrics</code>는 토큰, 비용, 재시도, 검증 카운터를
              세션 단위로 누적하는 Tier 2 집계입니다.{" "}
              <code>to_session_row()</code>가 한 행으로 만들어, 자기개선 루프의
              실행마다 루프 홈(<code>~/.geode/autoresearch/handoff/</code>)의{" "}
              <code>sessions.jsonl</code>에 추가됩니다. v0.99.159 전까지 이
              writer는 production caller가 없었고, S-6에서{" "}
              <code>core/self_improving/train.py</code>가 배선했습니다. 가드는{" "}
              <code>tests/test_s6_observability.py</code>입니다.
            </p>

            <h2>configure_logging: 프로세스 로그 스위치보드</h2>
            <p>
              어느 프로세스든 진입점에서 <code>configure_logging(mode)</code>를
              한 번 부르면 같은 포맷과 stderr 스트림, 모드별 로테이팅 파일을
              받습니다. 알 수 없는 모드는 조용히 무시되지 않고 ValueError로
              실패합니다.
            </p>
            <table>
              <thead>
                <tr><th>mode</th><th>파일</th></tr>
              </thead>
              <tbody>
                <tr><td><code>serve</code></td><td><code>~/.geode/logs/serve.log</code> (10MB × 5)</td></tr>
                <tr><td><code>mcp</code></td><td><code>~/.geode/logs/mcp.log</code></td></tr>
                <tr><td><code>worker</code></td><td><code>~/.geode/logs/worker.log</code></td></tr>
                <tr><td><code>campaign</code></td><td><code>~/.geode/logs/campaign.log</code></td></tr>
                <tr><td><code>cli</code></td><td>파일 없음, 콘솔만</td></tr>
              </tbody>
            </table>

            <h2>어떤 질문에 어떤 렌즈</h2>
            <table>
              <thead>
                <tr><th>질문</th><th>렌즈</th></tr>
              </thead>
              <tbody>
                <tr><td>이 세션에서 무슨 일이 있었나</td><td>SessionTranscript</td></tr>
                <tr><td>실행이 어디서 멈췄나</td><td>RunLog 마지막 줄들 + transcript. 절차는 <a href="/geode/docs/guides/debug-stuck-run">멈춘 실행 디버깅</a></td></tr>
                <tr><td>비용이 어디로 갔나</td><td>Usage ledger, <code>/cost</code>, <code>geode history</code></td></tr>
                <tr><td>어댑터가 얼마나 자주 실패하나</td><td><code>geode adapters stats</code></td></tr>
                <tr><td>루프 실행들의 토큰·검증 추세</td><td>sessions.jsonl</td></tr>
                <tr><td>이 에이전트가 안전하게 행동하나</td><td>Petri 감사. <a href="/geode/docs/petri/overview">Petri × GEODE</a></td></tr>
              </tbody>
            </table>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>run log에 이벤트가 안 쌓임</td>
                  <td>훅 핸들러가 bootstrap에 미등록</td>
                  <td>핸들러 존재와 발화는 다릅니다. <code>core/wiring/bootstrap.py</code> 등록을 확인합니다.</td>
                </tr>
                <tr>
                  <td>옛 로그가 사라짐</td>
                  <td>크기 게이트 prune (2MB 초과 시 최신 2000줄 유지)</td>
                  <td>의도된 동작입니다. 장기 보존이 필요하면 파일을 복사해 둡니다.</td>
                </tr>
                <tr>
                  <td>sessions.jsonl이 비어 있음</td>
                  <td>자기개선 루프를 아직 실행하지 않음</td>
                  <td>이 파일은 루프 실행이 writer입니다. 일반 REPL 세션은 transcript와 run log로 봅니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/harness/hooks">훅과 관측성</a>. 이벤트와 트리거 모드의 구조.</li>
              <li><a href="/geode/docs/ops/cost">비용 모니터링</a>. ledger 렌즈의 깊은 쪽.</li>
              <li><a href="/geode/docs/petri/run">감사 실행</a>. 행동 측정 렌즈.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE observes itself without an external tracing SaaS: hook
              events are the primary signal, and a set of native lenses view the
              same run at different grains. Everything is JSONL on disk, one jq
              away.
            </p>

            <h2>The lenses at a glance</h2>
            <table>
              <thead>
                <tr><th>Lens</th><th>Unit</th><th>Where</th><th>Code</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Hooks</td>
                  <td>Lifecycle events</td>
                  <td>(in memory; the source feeding the rest)</td>
                  <td><code>core/hooks/system.py</code></td>
                </tr>
                <tr>
                  <td>RunLog</td>
                  <td>Per-session hook-event time series</td>
                  <td><code>~/.geode/runs/&lt;session_key&gt;.jsonl</code></td>
                  <td><code>core/observability/run_log.py</code></td>
                </tr>
                <tr>
                  <td>SessionTranscript</td>
                  <td>Per-turn dialogue and tool calls</td>
                  <td><code>~/.geode/transcripts/&lt;slug&gt;/</code></td>
                  <td><code>core/observability/transcript.py</code></td>
                </tr>
                <tr>
                  <td>SessionMetrics</td>
                  <td>One cumulative row per session</td>
                  <td><code>sessions.jsonl</code> in the self-improving loop home</td>
                  <td><code>core/observability/session_metrics.py</code></td>
                </tr>
                <tr>
                  <td>Usage ledger</td>
                  <td>Tokens and cost per LLM call</td>
                  <td><code>~/.geode/usage/YYYY-MM.jsonl</code></td>
                  <td><code>core/llm/usage_store.py</code></td>
                </tr>
                <tr>
                  <td>Process logs</td>
                  <td>Rotating file per process</td>
                  <td><code>~/.geode/logs/</code></td>
                  <td><code>core/observability/logging_config.py</code></td>
                </tr>
              </tbody>
            </table>

            <h2>How hooks become lenses</h2>
            <p>
              The source of truth for emit sites is the 64-member{" "}
              <code>HookEvent</code> enum: LLM call lifecycle, tool execution,
              session boundaries, context overflow, model switches, mutation
              lifecycle. Observation sits on top as two wildcard subscriptions.
            </p>
            <ul>
              <li>
                The run-log writer. Bootstrap subscribes to every event with{" "}
                <code>register_prefix(&quot;*&quot;, ...)</code> and appends a
                per-session <code>RunLogEntry</code>
                (<code>core/wiring/bootstrap.py</code>). A new HookEvent lands
                in the run log automatically.
              </li>
              <li>
                The transcript mirror. When a RunTranscript is active, every
                hook trigger is mirrored as an activity row
                (<code>core/hooks/system.py</code>,{" "}
                <code>core/observability/activity_registry.py</code>).
              </li>
            </ul>
            <p>
              The PIPELINE_* and NODE_* automation events that older docs
              described do not exist. Code subscribing to an event missing from
              the enum is dead code that never fires.
            </p>

            <h2>RunLog and JobRunLog: one JSONL discipline</h2>
            <p>
              The session run log and the scheduler&apos;s job run log used the
              same pattern (locked append, newest-first reads, size-gated atomic
              prune), so v0.99.159 folded both onto a shared{" "}
              <code>JsonlAppendLog</code> base. A file past 2MB is trimmed to
              its newest 2000 lines.
            </p>
            <pre>{`# one line of ~/.geode/runs/<session_key>.jsonl
{"session_key": "...", "event": "llm_call_ended",
 "node": "", "status": "ok", "duration_ms": 4218.0,
 "metadata": {...}, "timestamp": 1780000000.0, "run_id": "..."}`}</pre>
            <p>
              The same files feed <code>geode adapters stats</code>, which
              aggregates <code>ADAPTER_DISPATCH_ATTEMPT</code> events into
              per-adapter outcome counts and p50/p95 latency
              (<code>core/cli/commands/adapters.py</code>).
            </p>

            <h2>sessions.jsonl: one row per run</h2>
            <p>
              <code>SessionMetrics</code> is the Tier 2 aggregate: tokens, cost,
              retry, and verify counters accumulated over a session.{" "}
              <code>to_session_row()</code> flattens it into one row, appended
              to <code>sessions.jsonl</code> in the self-improving loop home
              (<code>~/.geode/autoresearch/handoff/</code>) for every loop run.
              The writer had zero production callers until v0.99.159; S-6 wired
              it from <code>core/self_improving/train.py</code>, pinned by{" "}
              <code>tests/test_s6_observability.py</code>.
            </p>

            <h2>configure_logging: the process log switchboard</h2>
            <p>
              Every process calls <code>configure_logging(mode)</code> once at
              its entry point and receives the same formatter, the stderr
              stream, and a per-mode rotating file. An unknown mode fails with a
              ValueError instead of passing silently.
            </p>
            <table>
              <thead>
                <tr><th>mode</th><th>File</th></tr>
              </thead>
              <tbody>
                <tr><td><code>serve</code></td><td><code>~/.geode/logs/serve.log</code> (10MB times 5)</td></tr>
                <tr><td><code>mcp</code></td><td><code>~/.geode/logs/mcp.log</code></td></tr>
                <tr><td><code>worker</code></td><td><code>~/.geode/logs/worker.log</code></td></tr>
                <tr><td><code>campaign</code></td><td><code>~/.geode/logs/campaign.log</code></td></tr>
                <tr><td><code>cli</code></td><td>no file, console only</td></tr>
              </tbody>
            </table>

            <h2>Which lens for which question</h2>
            <table>
              <thead>
                <tr><th>Question</th><th>Lens</th></tr>
              </thead>
              <tbody>
                <tr><td>What happened in this session?</td><td>SessionTranscript</td></tr>
                <tr><td>Where did the run stall?</td><td>The last RunLog lines plus the transcript; procedure in <a href="/geode/docs/guides/debug-stuck-run">Debug a stuck run</a></td></tr>
                <tr><td>Where did the money go?</td><td>Usage ledger, <code>/cost</code>, <code>geode history</code></td></tr>
                <tr><td>How often does an adapter fail?</td><td><code>geode adapters stats</code></td></tr>
                <tr><td>Token and verify trends across loop runs?</td><td>sessions.jsonl</td></tr>
                <tr><td>Does the agent behave safely?</td><td>The Petri audit; see <a href="/geode/docs/petri/overview">Petri × GEODE</a></td></tr>
              </tbody>
            </table>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>No events accumulate in the run log</td>
                  <td>A hook handler exists but is not registered in bootstrap</td>
                  <td>Existing is not firing. Check the registration in <code>core/wiring/bootstrap.py</code>.</td>
                </tr>
                <tr>
                  <td>Old log lines disappear</td>
                  <td>The size-gated prune (past 2MB, keep the newest 2000 lines)</td>
                  <td>Intended. Copy files aside for long-term retention.</td>
                </tr>
                <tr>
                  <td>sessions.jsonl is empty</td>
                  <td>The self-improving loop has not run yet</td>
                  <td>Loop runs are the writer. For plain REPL sessions, read the transcript and run log instead.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/harness/hooks">Hooks and observability</a>. Events and trigger modes.</li>
              <li><a href="/geode/docs/ops/cost">Cost monitoring</a>. The deep end of the ledger lens.</li>
              <li><a href="/geode/docs/petri/run">Run an audit</a>. The behavioral measurement lens.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
