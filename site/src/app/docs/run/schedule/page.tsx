import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Schedule Tasks — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/schedule"
      title="Schedule Tasks"
      titleKo="작업 예약"
      summary="Natural language plus cron, with jitter. Daily reports as a single command."
      summaryKo="자연어와 cron, jitter 포함. 일일 리포트를 한 줄 명령으로."
    >
      <Bi
        ko={
          <>
            <p>이 가이드는 GEODE에 반복 작업을 예약하는 두 가지 방식 (자연어 / cron)을 보여줍니다.</p>

            <h2>자연어로 예약</h2>
            <pre>{`uv run geode "매일 아침 9시에 IT 트렌드 요약 보내줘"`}</pre>
            <p>GEODE가 자연어를 파싱해 cron + jitter를 자동으로 설정합니다.</p>

            <h2>명시적 cron</h2>
            <pre>{`uv run geode schedule add \\
  --cron "0 9 * * *" \\
  --jitter 600 \\
  "summarize today's AI news"`}</pre>

            <h2>예약 작업 관리</h2>
            <ul>
              <li>목록: <code>geode schedule list</code></li>
              <li>삭제: <code>geode schedule remove &lt;id&gt;</code></li>
              <li>일시정지: <code>geode schedule pause &lt;id&gt;</code></li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm"><em>참조:</em> <a href="/geode/docs/runtime/scheduler">Scheduler reference</a>, wiki/concepts/geode-lifecycle-commands.md</p>
          </>
        }
        en={
          <>
            <p>This guide schedules recurring tasks in GEODE via natural language or explicit cron.</p>

            <h2>Natural language</h2>
            <pre>{`uv run geode "every weekday at 9am, send me an AI news summary"`}</pre>
            <p>GEODE parses the phrase and sets a cron plus jitter automatically.</p>

            <h2>Explicit cron</h2>
            <pre>{`uv run geode schedule add \\
  --cron "0 9 * * *" \\
  --jitter 600 \\
  "summarize today's AI news"`}</pre>

            <h2>Manage scheduled tasks</h2>
            <ul>
              <li>List: <code>geode schedule list</code></li>
              <li>Remove: <code>geode schedule remove &lt;id&gt;</code></li>
              <li>Pause: <code>geode schedule pause &lt;id&gt;</code></li>
            </ul>

            <p className="text-[var(--ink-3)] text-sm"><em>See:</em> <a href="/geode/docs/runtime/scheduler">Scheduler reference</a>, wiki/concepts/geode-lifecycle-commands.md.</p>
          </>
        }
      />
    </DocsShell>
  );
}
