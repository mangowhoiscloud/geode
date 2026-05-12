import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Scheduler — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/scheduler"
      title="Scheduler"
      titleKo="스케줄러"
      summary="Natural-language + cron-based task scheduling. Six modules in core/scheduler/, deterministic jitter, calendar bridge."
      summaryKo="자연어와 cron 기반 작업 스케줄링. core/scheduler/의 6개 모듈, 결정론적 jitter, 캘린더 브리지."
    >
      <Bi
        ko={
          <>
            <h2>역할</h2>
            <p>
              사용자가 <em>&ldquo;매주 월요일 9시에 standup 알림 보내줘&rdquo;</em>라고 말하면
              스케줄러가 이를 파싱하고 정규화하여 반복 작업으로 영속화합니다. 사용자가 선호하면
              cron 표현식을 직접 받기도 합니다.
            </p>

            <h2>파일</h2>
            <ul>
              <li><code>core/scheduler/scheduler.py:76</code>. <code>class ScheduleKind</code> enum (cron, once, calendar)</li>
              <li><code>core/scheduler/nl_scheduler.py</code>. 자연어를 cron으로 변환하는 파서</li>
              <li><code>core/scheduler/calendar_bridge.py</code>. 시스템 캘린더와 스케줄을 연결하는 <code>CalendarSchedulerBridge</code></li>
              <li><code>core/scheduler/jitter.py</code>. task-id 해시 기반 결정론적 ±10% jitter</li>
            </ul>

            <h2>Jitter (thundering herd 방어)</h2>
            <p>
              다수의 작업이 동일한 명목 트리거 시각 (정각)을 공유할 때 모든 cron 플랫폼에서
              thundering herd가 발생합니다. GEODE의 jitter는 결정론적입니다. offset이 task ID
              해시의 함수이므로 같은 작업은 항상 같은 offset에 발화하지만, 같은 윈도 내 다른
              작업들은 시간상 분산됩니다.
            </p>
            <pre>{`# core/scheduler/scheduler.py:_compute_jitter_frac
fraction = (sha256(task_id) % 1000) / 1000
offset = -0.1 + (0.2 * fraction)   # ±10%
fire_at = nominal + offset * period`}</pre>

            <h2>캘린더 브리지</h2>
            <p>
              GEODE는 로컬 캘린더 (<code>core/mcp/apple_calendar_adapter.py</code>를 통한
              Apple Calendar)에서 이벤트를 읽어 스케줄 소스로 취급할 수 있습니다.
              <em>&ldquo;주간 회의 30분 전에 알림&rdquo;</em>은 캘린더 이벤트를 키로 삼는
              파생 스케줄이 됩니다.
            </p>

            <h2>훅 이벤트</h2>
            <ul>
              <li><code>SCHEDULE_FIRED</code>. 작업이 트리거될 때</li>
              <li><code>SCHEDULE_REGISTERED</code>. 새 스케줄이 파싱될 때</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>What it does</h2>
            <p>
              Users say <em>&ldquo;매주 월요일 9시에 standup 알림 보내줘&rdquo;</em>{" "}
              and the scheduler parses, normalises, and persists a recurring task.
              Cron expressions are accepted directly when the user prefers.
            </p>

            <h2>Files</h2>
            <ul>
              <li><code>core/scheduler/scheduler.py:76</code> — <code>class ScheduleKind</code> enum (cron, once, calendar)</li>
              <li><code>core/scheduler/nl_scheduler.py</code> — natural language → cron parser</li>
              <li><code>core/scheduler/calendar_bridge.py</code> — <code>CalendarSchedulerBridge</code> linking system calendars to schedules</li>
              <li><code>core/scheduler/jitter.py</code> — deterministic ±10% jitter via task-id hash</li>
            </ul>

            <h2>Jitter (thundering herd defense)</h2>
            <p>
              When many tasks share the same nominal trigger time (top of the
              hour), every cron platform sees a thundering herd. GEODE&apos;s
              jitter is deterministic: the offset is a function of the task ID
              hash, so the task always fires at the same offset, but different
              tasks in the same window spread out.
            </p>
            <pre>{`# core/scheduler/scheduler.py:_compute_jitter_frac
fraction = (sha256(task_id) % 1000) / 1000
offset = -0.1 + (0.2 * fraction)   # ±10%
fire_at = nominal + offset * period`}</pre>

            <h2>Calendar bridge</h2>
            <p>
              GEODE can read events from local calendars (Apple Calendar via the{" "}
              <code>core/mcp/apple_calendar_adapter.py</code>) and treat them as
              schedule sources. <em>&ldquo;주간 회의 30분 전에 알림&rdquo;</em>{" "}
              becomes a derived schedule keyed off the calendar event.
            </p>

            <h2>Hook events</h2>
            <ul>
              <li><code>SCHEDULE_FIRED</code> — when a task triggers</li>
              <li><code>SCHEDULE_REGISTERED</code> — when a new schedule is parsed</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
