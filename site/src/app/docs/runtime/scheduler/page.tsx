import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Scheduler internals — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/scheduler"
      title="Scheduler internals"
      titleKo="스케줄러 내부"
      summary="How scheduled jobs are parsed, persisted, and fired."
      summaryKo="예약된 작업이 파싱되고 저장되고 발화되는 경로를 따라갑니다."
    >
      <Bi
        ko={
          <>
            <p>
              스케줄러는 자연어 일정 표현을 <code>ScheduledJob</code>으로 바꾸고,
              디스크에 영속화하고, serve 데몬의 루프에서 발화하는 세 단계로
              움직입니다. 코드는 <code>core/scheduler/</code> 아래 평면 구조입니다.
            </p>

            <h2>파싱: 규칙 기반, LLM 없음</h2>
            <p>
              <code>NLScheduleParser</code>
              (<code>core/scheduler/nl_scheduler.py</code>)가 일정 표현을
              해석합니다. 패턴 매칭만 쓰고 LLM을 호출하지 않으므로 결과가
              결정적이고 비용이 없습니다. 결과는 세 가지{" "}
              <code>ScheduleKind</code>(<code>core/scheduler/models.py</code>)
              중 하나입니다.
            </p>
            <table>
              <thead>
                <tr><th>kind</th><th>의미</th><th>필드</th></tr>
              </thead>
              <tbody>
                <tr><td><code>every</code></td><td>고정 간격 반복</td><td><code>every_ms</code></td></tr>
                <tr><td><code>cron</code></td><td>cron 표현식 매칭</td><td><code>cron_expr</code> (분 시 일 월 요일, 요일 0=일요일)</td></tr>
                <tr><td><code>at</code></td><td>1회 실행</td><td>실행 시각</td></tr>
              </tbody>
            </table>
            <p>
              cron 매칭은 <code>core/scheduler/triggers.py</code>의 최소
              구현 <code>CronParser</code>가 담당합니다. 5필드 형식이고 요일은
              cron 표준 관례(0=일요일)를 따릅니다. 트리거 타입은 manual,
              scheduled(cron), event-driven(HookSystem 이벤트 구독) 셋입니다.
            </p>

            <h2>영속화</h2>
            <p>
              <code>SchedulerService</code>(<code>core/scheduler/service.py</code>)가
              작업 목록을 <code>.geode/scheduled_tasks.json</code>에 저장합니다.
              쓰기는 임시 파일 작성 후 <code>os.replace</code>로 원자적으로
              바꾸고, 같은 디렉터리의 <code>scheduled_tasks.lock</code>으로
              다중 프로세스 경합을 막습니다(<code>core/scheduler/lock.py</code>).
              데몬 시작 시 저장된 작업을 다시 읽고, 꺼져 있던 동안 놓친 발화를
              복구합니다.
            </p>

            <h2>발화</h2>
            <p>
              serve 데몬의 비동기 루프가 매 주기 스케줄러 큐를 drain합니다
              (<code>core/cli/typer_serve.py</code>). 발화 시각에는 결정적
              jitter가 더해집니다.
            </p>
            <pre>{`# core/scheduler/jitter.py
frac   = sha256(job_id)[:4] / 2^32          # [0, 1) 고정값
jitter = min(frac * interval * 0.1, 15min)  # 전방 오프셋
fire_at = nominal + jitter`}</pre>
            <p>
              같은 작업은 재시작 후에도 항상 같은 오프셋에 발화하고, 같은 정각을
              공유하는 다른 작업들은 시간상 분산됩니다. 발화된 작업의 액션
              프롬프트는 SCHEDULER 모드 세션(wall-clock 300초 상한, headless
              도구 차단)으로 실행되고, 트리거 시점에{" "}
              <code>HookEvent.TRIGGER_FIRED</code>가 발화됩니다
              (<code>core/scheduler/triggers.py</code>).
            </p>

            <h2>설정 손잡이</h2>
            <table>
              <thead>
                <tr><th>Settings 필드</th><th>기본값</th><th>의미</th></tr>
              </thead>
              <tbody>
                <tr><td><code>scheduler_auto_start</code></td><td><code>true</code></td><td>데몬 부팅 시 스케줄러 자동 시작</td></tr>
                <tr><td><code>scheduler_interval_s</code></td><td><code>1.0</code></td><td>발화 검사 주기</td></tr>
                <tr><td><code>scheduler_jitter_enabled</code></td><td><code>true</code></td><td>jitter on/off</td></tr>
                <tr><td><code>scheduler_max_jitter_ms</code></td><td><code>900000</code></td><td>jitter 상한 15분</td></tr>
              </tbody>
            </table>
            <p>
              전체 필드는 <code>core/config/_settings.py</code>가 SoT입니다.
            </p>

            <h2>보조 모듈</h2>
            <ul>
              <li><code>core/scheduler/calendar_bridge.py</code>. 캘린더 어댑터(<code>core/mcp/apple_calendar_adapter.py</code>, <code>core/mcp/google_calendar_adapter.py</code>)의 이벤트를 스케줄 소스로 연결합니다.</li>
              <li><code>core/scheduler/predefined.py</code>. <code>/schedule</code> 목록에 참고용으로 표시되는 템플릿입니다. 활성 작업이 아닙니다.</li>
              <li><code>core/scheduler/timezone.py</code>, <code>core/scheduler/serialization.py</code>. 시간대 정규화와 JSON 직렬화.</li>
            </ul>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>발화가 전혀 없음</td>
                  <td>데몬 정지 또는 <code>scheduler_auto_start=false</code></td>
                  <td><code>pgrep -f &quot;geode serve&quot;</code> 확인 후 데몬을 띄우고 설정을 점검합니다.</td>
                </tr>
                <tr>
                  <td>요일 cron이 하루 어긋남</td>
                  <td>요일 관례 혼동</td>
                  <td>이 파서는 0=일요일입니다. 월요일은 1입니다.</td>
                </tr>
                <tr>
                  <td>작업 파일이 깨짐</td>
                  <td>외부에서 JSON을 직접 편집</td>
                  <td><code>.geode/scheduled_tasks.json</code>은 손으로 고치지 말고 <code>/schedule</code>로 관리합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/run/schedule">작업 예약</a>. 사용자 관점의 예약 방법.</li>
              <li><a href="/geode/docs/harness/lifecycle">라이프사이클</a>. 스케줄러가 데몬 안에서 시작되고 정리되는 순서.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The scheduler moves in three steps: parse a natural-language
              schedule into a <code>ScheduledJob</code>, persist it to disk, and
              fire it from the serve daemon&apos;s loop. The code lives flat
              under <code>core/scheduler/</code>.
            </p>

            <h2>Parsing: rule-based, no LLM</h2>
            <p>
              <code>NLScheduleParser</code>
              (<code>core/scheduler/nl_scheduler.py</code>) interprets schedule
              expressions with pattern matching alone. No LLM call, so parsing
              is deterministic and free. The result is one of three{" "}
              <code>ScheduleKind</code> values
              (<code>core/scheduler/models.py</code>).
            </p>
            <table>
              <thead>
                <tr><th>kind</th><th>Meaning</th><th>Field</th></tr>
              </thead>
              <tbody>
                <tr><td><code>every</code></td><td>Fixed-interval repeat</td><td><code>every_ms</code></td></tr>
                <tr><td><code>cron</code></td><td>Cron expression match</td><td><code>cron_expr</code> (minute hour day month weekday, 0=Sunday)</td></tr>
                <tr><td><code>at</code></td><td>One-shot</td><td>fire time</td></tr>
              </tbody>
            </table>
            <p>
              Cron matching is the minimal <code>CronParser</code> in{" "}
              <code>core/scheduler/triggers.py</code>: five fields, weekday in
              the standard cron convention (0=Sunday). Trigger types are manual,
              scheduled (cron), and event-driven (a HookSystem subscription).
            </p>

            <h2>Persistence</h2>
            <p>
              <code>SchedulerService</code> (<code>core/scheduler/service.py</code>)
              stores the job list at <code>.geode/scheduled_tasks.json</code>.
              Writes go to a temp file and land via <code>os.replace</code>, and
              a <code>scheduled_tasks.lock</code> in the same directory guards
              against multi-process races (<code>core/scheduler/lock.py</code>).
              On daemon start the service reloads saved jobs and recovers fires
              missed while it was down.
            </p>

            <h2>Firing</h2>
            <p>
              The serve daemon&apos;s async loop drains the scheduler queue on
              every tick (<code>core/cli/typer_serve.py</code>). Fire times
              carry a deterministic jitter.
            </p>
            <pre>{`# core/scheduler/jitter.py
frac   = sha256(job_id)[:4] / 2^32          # fixed value in [0, 1)
jitter = min(frac * interval * 0.1, 15min)  # forward offset
fire_at = nominal + jitter`}</pre>
            <p>
              The same job fires at the same offset across restarts, while jobs
              sharing a nominal time spread out. A fired job&apos;s action
              prompt runs as a SCHEDULER-mode session (300-second wall-clock
              cap, headless tool denial), and{" "}
              <code>HookEvent.TRIGGER_FIRED</code> fires at trigger time
              (<code>core/scheduler/triggers.py</code>).
            </p>

            <h2>Configuration knobs</h2>
            <table>
              <thead>
                <tr><th>Settings field</th><th>Default</th><th>Meaning</th></tr>
              </thead>
              <tbody>
                <tr><td><code>scheduler_auto_start</code></td><td><code>true</code></td><td>Start the scheduler on daemon boot</td></tr>
                <tr><td><code>scheduler_interval_s</code></td><td><code>1.0</code></td><td>Fire-check tick</td></tr>
                <tr><td><code>scheduler_jitter_enabled</code></td><td><code>true</code></td><td>Jitter on/off</td></tr>
                <tr><td><code>scheduler_max_jitter_ms</code></td><td><code>900000</code></td><td>15-minute jitter cap</td></tr>
              </tbody>
            </table>
            <p>
              The full field list lives in <code>core/config/_settings.py</code>.
            </p>

            <h2>Supporting modules</h2>
            <ul>
              <li><code>core/scheduler/calendar_bridge.py</code>. Connects calendar adapters (<code>core/mcp/apple_calendar_adapter.py</code>, <code>core/mcp/google_calendar_adapter.py</code>) as schedule sources.</li>
              <li><code>core/scheduler/predefined.py</code>. Templates shown in the <code>/schedule</code> list for reference. They are not active jobs.</li>
              <li><code>core/scheduler/timezone.py</code>, <code>core/scheduler/serialization.py</code>. Timezone normalization and JSON round-tripping.</li>
            </ul>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Nothing ever fires</td>
                  <td>Daemon down, or <code>scheduler_auto_start=false</code></td>
                  <td>Check <code>pgrep -f &quot;geode serve&quot;</code>, start the daemon, review the setting.</td>
                </tr>
                <tr>
                  <td>Weekday cron is off by one day</td>
                  <td>Weekday convention confusion</td>
                  <td>This parser uses 0=Sunday; Monday is 1.</td>
                </tr>
                <tr>
                  <td>The jobs file is corrupted</td>
                  <td>Hand-edited JSON</td>
                  <td>Manage <code>.geode/scheduled_tasks.json</code> through <code>/schedule</code>, not by hand.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/run/schedule">Schedule tasks</a>. The user-facing side.</li>
              <li><a href="/geode/docs/harness/lifecycle">Lifecycle</a>. Where the scheduler starts and drains inside the daemon.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
