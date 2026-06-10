import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Schedule tasks — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="run/schedule"
      title="Schedule tasks"
      titleKo="작업 예약"
      summary="Natural language and cron, with jitter. A daily report as a single command."
      summaryKo="자연어와 cron을 jitter와 함께 씁니다. 일일 리포트를 명령 한 줄로 예약합니다."
    >
      <Bi
        ko={
          <>
            <p>
              예약은 세션 안에서 합니다. 두 입구가 있습니다. 대화 중 자연어로
              부탁하면 에이전트가 <code>schedule_job</code> 도구로 작업을
              만들고, 직접 제어하려면 <code>/schedule</code> 슬래시 명령을
              씁니다. 셸에서 <code>geode &quot;...&quot;</code> 형태의 원샷
              예약은 지원하지 않습니다. 만들어진 작업은 serve 데몬이 발화합니다.
            </p>

            <h2>자연어로 예약</h2>
            <pre>{`geode

> 평일 아침 9시마다 AI 뉴스 요약해서 알려줘`}</pre>
            <p>
              에이전트가 <code>schedule_job</code> 도구
              (<code>core/tools/definitions.json</code>)를 호출해 일정 표현과
              실행할 프롬프트를 분리해 등록합니다. 발화 시각이 되면 그 프롬프트가
              새 에이전틱 실행으로 돌아갑니다.
            </p>

            <h2>/schedule로 직접 관리</h2>
            <p>
              일정 표현과 액션을 각각 따옴표로 감쌉니다. 액션이 없으면 작업이
              만들어지지 않습니다. 발화해도 할 일이 없기 때문입니다
              (<code>core/cli/commands/schedule.py</code>).
            </p>
            <pre>{`> /schedule                          # 작업 목록 + 템플릿
> /schedule create "daily at 9:00" "summarize today's AI news"
> /schedule status <id>
> /schedule disable <id>             # 잠시 끄기
> /schedule enable <id>
> /schedule run <id>                 # 지금 즉시 실행
> /schedule delete <id>`}</pre>
            <p>
              일정 표현은 <code>NLScheduleParser</code>
              (<code>core/scheduler/nl_scheduler.py</code>)가 LLM 호출 없이
              규칙 기반으로 해석합니다.
            </p>
            <table>
              <thead>
                <tr><th>패턴</th><th>예시</th></tr>
              </thead>
              <tbody>
                <tr><td>간격</td><td><code>&quot;every 5 minutes&quot;</code>, <code>&quot;every 2 hours&quot;</code>, <code>&quot;every 30s&quot;</code></td></tr>
                <tr><td>cron형 자연어</td><td><code>&quot;daily at 9:00&quot;</code>, <code>&quot;weekly on monday&quot;</code>, <code>&quot;hourly&quot;</code>, <code>&quot;every weekday at 14:00&quot;</code></td></tr>
                <tr><td>활동 시간대</td><td><code>&quot;every 5m during 09:00-22:00&quot;</code></td></tr>
                <tr><td>작업 이름 지정</td><td><code>&quot;run analysis every 5m&quot;</code> → 이름이 <code>analysis</code></td></tr>
              </tbody>
            </table>

            <h2>jitter와 실행 환경</h2>
            <p>
              같은 정각을 공유하는 작업이 한꺼번에 몰리지 않도록, 발화 시각에
              작업 ID의 sha256에서 유도한 결정적 전방 오프셋이 더해집니다. 같은
              작업은 항상 같은 오프셋, 다른 작업은 흩어집니다. 오프셋 상한은
              간격의 10%와 15분 중 작은 값입니다
              (<code>core/scheduler/jitter.py</code>). 발화된 작업은 SCHEDULER
              모드 세션으로 돌아갑니다. wall-clock 300초 상한이 있고, 승인할
              사용자가 없으므로 <code>run_bash</code>와{" "}
              <code>delegate_task</code>는 차단됩니다
              (<code>core/server/supervised/services.py</code>).
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>예약 시각이 지나도 발화 안 됨</td>
                  <td>serve 데몬이 꺼져 있음</td>
                  <td>스케줄러는 데몬 안에서 돕니다. <code>pgrep -f &quot;geode serve&quot;</code>로 확인하고 <code>geode</code>를 다시 실행합니다.</td>
                </tr>
                <tr>
                  <td>작업이 만들어지지 않음</td>
                  <td>액션 누락 또는 따옴표 없는 인자</td>
                  <td><code>/schedule create &quot;일정&quot; &quot;액션&quot;</code> 두 인자를 모두 따옴표로 감쌉니다.</td>
                </tr>
                <tr>
                  <td>정각보다 몇 분 늦게 발화</td>
                  <td>의도된 jitter</td>
                  <td>정상입니다. thundering herd 방지를 위한 결정적 오프셋입니다.</td>
                </tr>
                <tr>
                  <td>긴 작업이 도중에 끊김</td>
                  <td>SCHEDULER 모드 300초 상한</td>
                  <td>작업을 더 작게 쪼개거나, 긴 조사는 세션에서 직접 실행합니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/runtime/scheduler">스케줄러 내부</a>. 파싱, 영속화, 발화 경로.</li>
              <li><a href="/geode/docs/run/messaging">메신저 연동</a>. 결과를 Slack으로 받기.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Scheduling happens inside a session, through two entry points. Ask in
              natural language and the agent creates the job with the{" "}
              <code>schedule_job</code> tool; for direct control, use the{" "}
              <code>/schedule</code> slash command. A shell one-shot like{" "}
              <code>geode &quot;...&quot;</code> is not supported. Created jobs
              fire inside the serve daemon.
            </p>

            <h2>Natural language</h2>
            <pre>{`geode

> every weekday at 9am, summarize AI news for me`}</pre>
            <p>
              The agent calls the <code>schedule_job</code> tool
              (<code>core/tools/definitions.json</code>), splitting the schedule
              expression from the prompt to run. When the job fires, that prompt
              runs as a fresh agentic execution.
            </p>

            <h2>Direct control with /schedule</h2>
            <p>
              Quote the schedule and the action separately. A job without an
              action is rejected; it would fire and do nothing
              (<code>core/cli/commands/schedule.py</code>).
            </p>
            <pre>{`> /schedule                          # list jobs + templates
> /schedule create "daily at 9:00" "summarize today's AI news"
> /schedule status <id>
> /schedule disable <id>             # pause
> /schedule enable <id>
> /schedule run <id>                 # fire right now
> /schedule delete <id>`}</pre>
            <p>
              Schedule expressions are parsed by <code>NLScheduleParser</code>
              (<code>core/scheduler/nl_scheduler.py</code>), rule-based with no
              LLM call.
            </p>
            <table>
              <thead>
                <tr><th>Pattern</th><th>Examples</th></tr>
              </thead>
              <tbody>
                <tr><td>Intervals</td><td><code>&quot;every 5 minutes&quot;</code>, <code>&quot;every 2 hours&quot;</code>, <code>&quot;every 30s&quot;</code></td></tr>
                <tr><td>Cron-like phrases</td><td><code>&quot;daily at 9:00&quot;</code>, <code>&quot;weekly on monday&quot;</code>, <code>&quot;hourly&quot;</code>, <code>&quot;every weekday at 14:00&quot;</code></td></tr>
                <tr><td>Active hours</td><td><code>&quot;every 5m during 09:00-22:00&quot;</code></td></tr>
                <tr><td>Job naming</td><td><code>&quot;run analysis every 5m&quot;</code> names the job <code>analysis</code></td></tr>
              </tbody>
            </table>

            <h2>Jitter and the execution environment</h2>
            <p>
              To keep jobs sharing the same nominal time from firing at once, a
              deterministic forward offset derived from sha256 of the job ID is
              added to the fire time. The same job always gets the same offset;
              different jobs spread out. The offset is capped at 10% of the
              interval or 15 minutes, whichever is smaller
              (<code>core/scheduler/jitter.py</code>). Fired jobs run as
              SCHEDULER-mode sessions: a 300-second wall-clock cap, and with no
              user present to approve, <code>run_bash</code> and{" "}
              <code>delegate_task</code> are denied
              (<code>core/server/supervised/services.py</code>).
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Nothing fires at the scheduled time</td>
                  <td>The serve daemon is down</td>
                  <td>The scheduler lives inside the daemon. Check with <code>pgrep -f &quot;geode serve&quot;</code> and run <code>geode</code> again.</td>
                </tr>
                <tr>
                  <td>The job is not created</td>
                  <td>Missing action or unquoted arguments</td>
                  <td>Quote both arguments: <code>/schedule create &quot;schedule&quot; &quot;action&quot;</code>.</td>
                </tr>
                <tr>
                  <td>Fires a few minutes late</td>
                  <td>Intentional jitter</td>
                  <td>Expected. A deterministic offset prevents the thundering herd.</td>
                </tr>
                <tr>
                  <td>A long job gets cut off</td>
                  <td>The 300-second SCHEDULER-mode cap</td>
                  <td>Split the work into smaller jobs, or run long research directly in a session.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/runtime/scheduler">Scheduler internals</a>. Parsing, persistence, and the firing path.</li>
              <li><a href="/geode/docs/run/messaging">Messaging integrations</a>. Get results delivered to Slack.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
