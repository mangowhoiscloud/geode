import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Scheduler — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/scheduler"
      title="Scheduler"
      summary="Natural-language + cron-based task scheduling. Six modules in core/scheduler/, deterministic jitter, calendar bridge."
    >
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

    </DocsShell>
  );
}
