import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Auto-trigger sidecar — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/automation"
      title="Auto-trigger sidecar"
      titleKo="자동 트리거 사이드카"
      summary="The cron-scheduled sidecar that fires the self-improving loop without an operator: lock, interval gate, hook telemetry, and the outer-bundle viewer."
      summaryKo="운영자 없이 자기개선 루프를 cron으로 발화하는 사이드카입니다. 락, 인터벌 게이트, 훅 텔레메트리, outer-bundle 뷰어를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              자동 트리거는 자기개선 루프의 변이 러너
              (<code>SelfImprovingLoopRunner.run_once</code>)를 스케줄러에 연결해,
              키보드 앞에 운영자가 없어도 루프가 cron 주기로 도는 사이드카입니다.
              구현은 <code>core/self_improving/loop/auto_trigger.py</code>,
              배선은 <code>core/wiring/scheduling.py</code>의{" "}
              <code>build_scheduling</code>입니다.
            </p>
            <p>
              한때 이 자리에 있던 별도 자동화 파이프라인(drift 감지, 모델
              프로모션, 전문가 패널이 있던 <code>core/automation/</code>)은
              v0.99.149에서 삭제되었습니다. 그 체인의 모든 진입점이 emitter가
              사라진 파이프라인 이벤트였고, 부팅마다 만들어지되 일을 하지 않는
              구성물이었기 때문입니다. 지금 남아 있는 자동화는 이 페이지의
              사이드카와 <a href="/geode/docs/runtime/scheduler">스케줄러</a>가
              전부입니다.
            </p>

            <h2>동작 방식</h2>
            <pre>{`[self_improving_loop.scheduler] enabled=true   (~/.geode/config.toml, 기본 off)
        │ cron 발화 (trigger_id: self_improving_loop_auto_trigger)
        ▼
1. fcntl flock  ~/.geode/autoresearch/handoff/auto_trigger.lock
        │ 다른 보유자가 있으면 no-op (INFO 로그)
        ▼
2. 최소 간격 게이트  auto_trigger_last_run.txt
        │ 직전 성공 발화가 min_interval_minutes 안이면 skip
        ▼
3. SelfImprovingLoopRunner.run_once  (mutate → audit → gate)
        │ 소스 디스패치는 [self_improving_loop.mutator].source 상속
        ▼
status dict 반환 (절대 raise하지 않음) + 히스토리 append`}</pre>
            <p>
              세 가지 방어선이 핵심입니다. 락은 cron 발화 둘 또는 cron과 수동
              실행이 같은 SoT 파일을 두고 경합하는 것을 막습니다. fcntl advisory
              lock이라 프로세스가 죽으면 커널이 자동 해제합니다. 인터벌 게이트는
              재시작이나 클록 스큐로 cron이 과발화해도 바닥 주기를 지킵니다.
              타임스탬프는 성공한 발화만 갱신하므로, 설정이 망가져 실패가
              반복되어도 스케줄이 몇 시간씩 잠기지 않습니다. 마지막으로 모든
              결과는 status dict로 돌아옵니다. 한 번의 발화 실패가 스케줄러
              루프를 죽이지 못합니다.
            </p>

            <h2>설정</h2>
            <table>
              <thead>
                <tr><th>키 (<code>[self_improving_loop.scheduler]</code>)</th><th>의미</th></tr>
              </thead>
              <tbody>
                <tr><td><code>enabled</code></td><td>opt-in 스위치. 기본 false면 <code>register_auto_trigger</code>가 no-op입니다</td></tr>
                <tr><td><code>cron</code></td><td>발화 주기 cron 표현식</td></tr>
                <tr><td><code>min_interval_minutes</code></td><td>성공 발화 간 최소 간격</td></tr>
                <tr><td><code>max_generation</code></td><td>누적 발화 세대 상한. 0이면 무제한</td></tr>
              </tbody>
            </table>

            <h2>관측</h2>
            <table>
              <thead>
                <tr><th>표면</th><th>내용</th></tr>
              </thead>
              <tbody>
                <tr><td><code>HookEvent.SELF_IMPROVING_AUTO_TRIGGER_*</code></td><td>발화 결과별 이벤트. <code>FIRED</code>, <code>LOCK_BUSY</code>, <code>INTERVAL_BLOCKED</code>, <code>RUNNER_ERROR</code>, <code>PARSE_ERROR</code>, <code>MAX_GENERATION_REACHED</code> (<code>core/hooks/system.py</code>)</td></tr>
                <tr><td><code>auto_trigger_history.jsonl</code></td><td>발화 기록 append-only 로그 (<code>~/.geode/autoresearch/handoff/</code>)</td></tr>
                <tr><td><code>geode outer-bundle</code></td><td>발화 기록을 <code>mutations.jsonl</code>, <code>baseline.json</code>과 교차해 하나의 타임라인으로 보여 주는 뷰어 (<code>core/cli/outer_bundle.py</code>)</td></tr>
                <tr><td><code>/schedule</code></td><td>등록된 트리거 목록에서 <code>self_improving_loop_auto_trigger</code>로 식별</td></tr>
              </tbody>
            </table>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr><td>cron 시각에 아무 일도 없음</td><td><code>enabled=false</code>(기본)</td><td><code>~/.geode/config.toml</code>의 <code>[self_improving_loop.scheduler]</code>에서 켭니다.</td></tr>
                <tr><td><code>LOCK_BUSY</code>가 반복</td><td>수동 실행이나 캠페인이 락을 보유</td><td>정상 동작입니다. 동시 발화는 의도적으로 no-op입니다.</td></tr>
                <tr><td>발화는 되는데 변이가 없음</td><td><code>MAX_GENERATION_REACHED</code></td><td><code>max_generation</code>을 올리거나 0으로 되돌립니다.</td></tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/capabilities/outer-loop">아우터 루프</a>. 발화된 run_once가 실제로 하는 일.</li>
              <li><a href="/geode/docs/runtime/scheduler">스케줄러</a>. cron 트리거가 사는 곳.</li>
              <li><a href="/geode/docs/harness/cli">CLI 레퍼런스</a>. <code>geode outer-bundle</code>과 <code>/self-improving</code>.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The auto-trigger is the sidecar that connects the self-improving
              loop&apos;s mutation runner
              (<code>SelfImprovingLoopRunner.run_once</code>) to the scheduler,
              so the loop fires on a cron cadence without an operator at the
              keyboard. The implementation is{" "}
              <code>core/self_improving/loop/auto_trigger.py</code>; the wiring
              is <code>build_scheduling</code> in{" "}
              <code>core/wiring/scheduling.py</code>.
            </p>
            <p>
              The separate automation pipeline that once lived here (the{" "}
              <code>core/automation/</code> package with drift detection, model
              promotion, and an expert panel) was deleted in v0.99.149: every
              entry point into that chain was a pipeline event with no remaining
              emitter, so its components were built on every boot and never did
              any work. What remains of automation is this sidecar plus the{" "}
              <a href="/geode/docs/runtime/scheduler">scheduler</a>.
            </p>

            <h2>How a firing runs</h2>
            <pre>{`[self_improving_loop.scheduler] enabled=true   (~/.geode/config.toml, default off)
        │ cron fires (trigger_id: self_improving_loop_auto_trigger)
        ▼
1. fcntl flock  ~/.geode/autoresearch/handoff/auto_trigger.lock
        │ another holder → no-op (logged at INFO)
        ▼
2. min-interval gate  auto_trigger_last_run.txt
        │ last successful firing within min_interval_minutes → skip
        ▼
3. SelfImprovingLoopRunner.run_once  (mutate → audit → gate)
        │ source dispatch inherited from [self_improving_loop.mutator].source
        ▼
returns a status dict (never raises) + appends history`}</pre>
            <p>
              Three defenses matter. The lock keeps two cron firings, or a cron
              firing plus a manual run, from racing on the same SoT files; it is
              an advisory fcntl lock, so a crashed process releases it
              automatically. The interval gate holds a floor cadence even when
              restarts or clock skew make cron over-fire; only successful
              firings update the timestamp, so a flapping config cannot lock the
              schedule out for hours. And every outcome comes back as a status
              dict: one failed firing cannot crash the scheduler loop.
            </p>

            <h2>Configuration</h2>
            <table>
              <thead>
                <tr><th>Key (<code>[self_improving_loop.scheduler]</code>)</th><th>Meaning</th></tr>
              </thead>
              <tbody>
                <tr><td><code>enabled</code></td><td>The opt-in switch. Default false makes <code>register_auto_trigger</code> a no-op</td></tr>
                <tr><td><code>cron</code></td><td>Cron expression for the firing cadence</td></tr>
                <tr><td><code>min_interval_minutes</code></td><td>Minimum gap between successful firings</td></tr>
                <tr><td><code>max_generation</code></td><td>Cap on accumulated fired generations; 0 means unbounded</td></tr>
              </tbody>
            </table>

            <h2>Observing it</h2>
            <table>
              <thead>
                <tr><th>Surface</th><th>What it shows</th></tr>
              </thead>
              <tbody>
                <tr><td><code>HookEvent.SELF_IMPROVING_AUTO_TRIGGER_*</code></td><td>One event per outcome: <code>FIRED</code>, <code>LOCK_BUSY</code>, <code>INTERVAL_BLOCKED</code>, <code>RUNNER_ERROR</code>, <code>PARSE_ERROR</code>, <code>MAX_GENERATION_REACHED</code> (<code>core/hooks/system.py</code>)</td></tr>
                <tr><td><code>auto_trigger_history.jsonl</code></td><td>Append-only firing log under <code>~/.geode/autoresearch/handoff/</code></td></tr>
                <tr><td><code>geode outer-bundle</code></td><td>Crosswalks the firing log with <code>mutations.jsonl</code> and <code>baseline.json</code> into one timeline (<code>core/cli/outer_bundle.py</code>)</td></tr>
                <tr><td><code>/schedule</code></td><td>The trigger appears as <code>self_improving_loop_auto_trigger</code> in the registered list</td></tr>
              </tbody>
            </table>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr><td>Nothing happens at the cron time</td><td><code>enabled=false</code> (the default)</td><td>Turn it on under <code>[self_improving_loop.scheduler]</code> in <code>~/.geode/config.toml</code>.</td></tr>
                <tr><td>Repeated <code>LOCK_BUSY</code></td><td>A manual run or campaign holds the lock</td><td>Working as intended: concurrent firings are deliberate no-ops.</td></tr>
                <tr><td>Firings happen but never mutate</td><td><code>MAX_GENERATION_REACHED</code></td><td>Raise <code>max_generation</code> or set it back to 0.</td></tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/capabilities/outer-loop">The outer loop</a>. What the fired run_once actually does.</li>
              <li><a href="/geode/docs/runtime/scheduler">Scheduler</a>. Where cron triggers live.</li>
              <li><a href="/geode/docs/harness/cli">CLI reference</a>. <code>geode outer-bundle</code> and <code>/self-improving</code>.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
