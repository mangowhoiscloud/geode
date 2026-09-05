"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ARTIFACT_COMMIT, DATA_SHA256, DATA_URL, EVIDENCE_URL, OBSERVABILITY_COMMIT, OBSERVABILITY_SHA256, OBSERVABILITY_URL, eventCount, loadObservability, loadReplay, nextFrame, pairFromSearch, statusLabel, timeKst } from "./replay-data";
import type { Cell, Observability, Playback, ReplayData } from "./replay-data";
import styles from "./replay.module.css";

function Metrics({ value, ko }: { value: Observability; ko: boolean }) {
  const { usage, phases, commands, cost } = value;
  const number = (n: number | null) => n === null ? (ko ? "미기록" : "Unknown") : n.toLocaleString("en-US");
  const labels = {
    environment_setup: "Environment setup", agent_setup: "Agent setup",
    agent_execution: "Agent execution", verifier: "Verifier",
  };
  return <details className={styles.metrics} data-observability={value.cell}>
    <summary>{ko ? "호출별 토큰 · 시간 · 명령 결과" : "Call tokens · timing · command results"}</summary>
    <p>{usage.status === "verified-call-usage"
      ? (ko ? `${usage.events.length}개 usage event를 원본 trial 합계와 대조했습니다.` : `${usage.events.length} usage events reconciled against trial totals.`)
      : (usage.status === "not-run" ? (ko ? "실행 전 제외 · usage 없음" : "Not executed · no usage") : (ko ? "호출별 usage를 복구하지 못했습니다." : "Call-level usage unavailable."))}</p>
    <dl className={styles.numbers}>
      <dt>Input tokens</dt><dd>{number(usage.input_tokens)}</dd>
      <dt>Output tokens</dt><dd>{number(usage.output_tokens)}</dd>
      <dt>Cached input</dt><dd>{number(usage.cached_input_tokens)}</dd>
      {usage.cache_missing_events > 0 && <><dt>{ko ? "확인된 cache 부분합" : "Observed cache subtotal"}</dt><dd>{number(usage.observed_cached_tokens)}</dd>
        <dt>{ko ? "Cache 미기록 calls" : "Calls missing cache"}</dt><dd>{usage.cache_missing_events}</dd></>}
    </dl>
    <p>{ko ? "Cached input은 input에 포함됩니다. 미기록은 0이 아닙니다. Usage event와 위 ATIF tool event의 대응은 확인되지 않았습니다." : "Cached input is included in input. Unknown is not zero. Usage events are not mapped to the ATIF tool events above."}</p>
    {usage.events.length > 0 && <details>
      <summary>{ko ? "호출별 usage 기록" : "Per-call usage records"}</summary>
      <div className={styles.tableScroll} tabIndex={0} aria-label={ko ? "호출별 토큰 표" : "Per-call token table"}>
        <table><caption>{ko ? "원본 usage event 순서 · tool step 아님" : "Source usage-event order · not tool steps"}</caption>
          <thead><tr><th scope="col">Call</th><th scope="col">KST</th><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Cache</th></tr></thead>
          <tbody>{usage.events.map(event => <tr key={event.index}><th scope="row">{event.index}</th>
            <td><time dateTime={event.timestamp_utc}>{timeKst(event.timestamp_utc)}</time></td>
            <td>{number(event.input_tokens)}</td><td>{number(event.output_tokens)}</td><td>{number(event.cached_input_tokens)}</td></tr>)}</tbody>
        </table>
      </div>
    </details>}
    <h4>{ko ? "단계별 경과 시간" : "Phase elapsed time"}</h4>
    <dl className={styles.numbers}>{Object.entries(phases).map(([key, phase]) => <div key={key}>
      <dt>{labels[key as keyof typeof labels]}</dt><dd title={phase.started_at && phase.finished_at ? `${phase.started_at} → ${phase.finished_at}` : phase.status}>
        {phase.seconds === null ? phase.status : `${phase.seconds.toFixed(1)} s`}</dd>
    </div>)}</dl>
    <p>{ko ? "UTC 시작·종료 시각의 차이입니다. 단계 사이의 간격과 teardown은 별도이며, CPU 사용 시간은 아닙니다." : "Differences of UTC start/end timestamps. Inter-phase gaps and teardown are separate; these are not CPU times."}</p>
    <h4>{ko ? "완료된 shell command" : "Completed shell commands"}</h4>
    <p>{number(commands.completed)} completed / {number(commands.nonzero)} nonzero exit</p>
    <p>{ko ? "Nonzero exit는 검사·탐색의 정상 결과일 수도 있습니다. Tool 호출 오류율이나 benchmark 실패율이 아닙니다." : "Nonzero exits may be expected checks or probes. They are not tool invocation errors or benchmark failure rates."}</p>
    <details><summary>{ko ? "비용과 실사용량의 한계" : "Cost and utilization limits"}</summary>
      <p>{ko ? "Producer 추정치" : "Producer estimate"}: {cost.reported_estimate_usd === null ? number(null) : `$${cost.reported_estimate_usd.toFixed(4)}`}. {ko ? "가격 revision 미기록 · subscription 청구액 아님" : "Pricing revision unrecorded · not subscription billing"}.</p>
      <p>{ko ? "실제 청구액·CPU 사용률·peak RAM은 미계측입니다." : "Actual billing, CPU utilization and peak RAM are unmeasured."}</p>
    </details>
  </details>;
}

function Arm({ cell, metrics, step, done, playing, ko }: {
  cell: Cell; metrics: Observability; step: number; done: boolean; playing: boolean; ko: boolean;
}) {
  const log = useRef<HTMLDivElement>(null);
  const events = cell.events.slice(0, step);
  const name = cell.arm === "geode" ? "GEODE" : "Codex";
  useEffect(() => {
    const element = log.current;
    element?.scrollTo({
      top: element.scrollHeight,
      behavior: playing && !matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "instant",
    });
  }, [cell.cell, step, playing]);
  const kind = { "atif-derived-private": "ATIF-derived", "receipt-event": "Receipt only", "exclusion-card": "Not executed" }[cell.replay_kind];
  return (
    <section className={styles.arm} data-arm={cell.arm} aria-label={name}>
      <div className={styles.metadata}>
        <h3>{name}</h3>
        <p className={styles.status}>Cell {cell.cell} / {done ? statusLabel(cell, ko) : (ko ? "기록 재생" : "Evidence playback")}</p>
        <p>{kind} / {events.length}/{cell.events.length} tool calls</p>
        <p>{cell.timing ? <>Trial start <time dateTime={cell.timing.started_at ?? undefined}>{timeKst(cell.timing.started_at)}</time></> : (ko ? "실행 전 대칭 제외" : "Prospective symmetric exclusion")}</p>
        <p>Trial wall {cell.wall_seconds?.toFixed(1) ?? "n/a"} s <span>{ko ? "(전체 trial 경과 시간)" : "(full trial elapsed time)"}</span></p>
        <p>Raw verifier {cell.raw_verifier_reward ?? "n/a"} / selected {cell.selected_reward ?? "n/a"}</p>
      </div>
      <div ref={log} className={styles.log} tabIndex={0} aria-label={name + " event log"}>
        <div>
          {events.length ? events.map((event, index) => (
            <div className={styles.event} key={index}>
              <p><span className={styles.ordinal}>{String(index + 1).padStart(3, "0")}</span> {event.tool} <span className={styles.program}>{event.program}</span></p>
              <p><time dateTime={event.timestamp_utc}>{timeKst(event.timestamp_utc)}</time></p>
              <p>{event.output_chars.toLocaleString("en-US")} chars / {event.output_lines} lines <span>observation payload</span></p>
            </div>
          )) : <p className={styles.empty}>{cell.events.length
            ? (ko ? "재생하면 보존된 tool event가 아래에서부터 표시됩니다." : "Play to reveal preserved tool events from the bottom.")
            : (ko ? "Terminal 내용을 복원하지 않았습니다. 결과 또는 제외 receipt만 있습니다." : "No terminal reconstruction. Only result or exclusion receipts exist.")}</p>}
        </div>
      </div>
      <Metrics value={metrics} ko={ko} />
      <details className={styles.lineage}>
        <summary>{ko ? "Attempt 계보와 근거" : "Attempt lineage and evidence"}</summary>
        {cell.lineage.length ? cell.lineage.map(row => <p key={row.attempt_id}>{row.attempt_id}<br />{row.validity} / {row.outcome}</p>) : <p>{ko ? "모델 호출 전 제외" : "Excluded before model calls"}</p>}
        {cell.trajectory_sha256 && <p>ATIF SHA-256<br /><code>{cell.trajectory_sha256}</code></p>}
      </details>
    </section>
  );
}

export function ReplayPlayer() {
  const [data, setData] = useState<ReplayData | null>(null);
  const [metrics, setMetrics] = useState<Record<number, Observability> | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [ko, setKo] = useState(true);
  const [speed, setSpeed] = useState(5);
  const [state, setState] = useState<Playback>({ pair: 0, step: 0, playing: false });

  useEffect(() => {
    const controller = new AbortController();
    loadReplay(controller.signal).then(async value => {
      const recovered = await loadObservability(controller.signal, value);
      if (controller.signal.aborted) return;
      setState({ pair: pairFromSearch(location.search), step: 0, playing: false });
      setKo(new URLSearchParams(location.search).get("lang") !== "en");
      setData(value);
      setMetrics(recovered);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [attempt]);

  const go = useCallback((pair: number) => {
    const index = Math.max(0, Math.min(444, pair));
    setState(current => ({ ...current, pair: index, step: 0 }));
    const url = new URL(location.href);
    url.searchParams.set("pair", String(index + 1));
    history.replaceState(null, "", url);
  }, []);
  const toggle = useCallback(() => setState(current =>
    data && current.pair === 444 && current.step === eventCount(data.pairs[444]) && !current.playing
      ? { pair: 0, step: 0, playing: true }
      : { ...current, playing: !current.playing }), [data]);

  useEffect(() => {
    if (!data || !state.playing) return;
    const timeout = setTimeout(() => {
      setState(current => nextFrame(current, data.pairs));
    }, state.step === eventCount(data.pairs[state.pair]) ? 1000 : 1000 / speed);
    return () => clearTimeout(timeout);
  }, [data, state, speed]);

  useEffect(() => {
    if (!data) return;
    const url = new URL(location.href);
    url.searchParams.set("pair", String(state.pair + 1));
    url.searchParams.set("lang", ko ? "ko" : "en");
    history.replaceState(null, "", url);
  }, [data, state.pair, ko]);

  useEffect(() => {
    if (!data) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.target instanceof Element && event.target.closest("input,select,button,a,summary,[contenteditable],[tabindex]")) return;
      if (event.code === "Space") { event.preventDefault(); toggle(); }
      if (event.code === "ArrowLeft") { event.preventDefault(); go(state.pair - 1); }
      if (event.code === "ArrowRight") { event.preventDefault(); go(state.pair + 1); }
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [data, go, toggle, state.pair]);

  if (!data || !metrics) return <section className={styles.loading} aria-live="polite">
    <h2>{error ? "Replay를 불러오지 못했습니다." : "공개 기록의 SHA-256을 확인하고 있습니다."}</h2>
    <p>{error ? "Download or integrity check failed. Unverified data will not play." : "Verifying the immutable public metadata. No model calls."}</p>
    {error && <button onClick={() => { setError(false); setAttempt(value => value + 1); }}>다시 시도 / Retry</button>}
    <a href={EVIDENCE_URL}>Artifact source</a>
  </section>;

  const pair = data.pairs[state.pair];
  const max = eventCount(pair);
  return (
    <div lang={ko ? "ko" : "en"} data-pair={state.pair + 1} data-step={state.step} data-verified="true">
      <div className={styles.overview}>
        <p>835 ATIF-derived / 35 receipt-only / 20 not executed</p>
        <div aria-label="Language"><button aria-pressed={ko} onClick={() => setKo(true)}>KO</button><button aria-pressed={!ko} onClick={() => setKo(false)}>EN</button></div>
      </div>
      <nav className={styles.controls} aria-label="Replay controls">
        <button className={styles.play} onClick={toggle} aria-pressed={state.playing}>{state.playing ? (ko ? "일시정지" : "Pause") : (ko ? "재생" : "Play")}</button>
        <button onClick={() => go(state.pair - 1)} disabled={state.pair === 0}>{ko ? "이전" : "Previous"}</button>
        <button onClick={() => go(state.pair + 1)} disabled={state.pair === 444}>{ko ? "다음" : "Next"}</button>
        <select aria-label="Task and repetition" value={state.pair} onChange={event => go(Number(event.target.value))}>
          {data.pairs.map((item, index) => <option key={index} value={index}>{String(index + 1).padStart(3, "0")} {item.task} / r{item.repetition}</option>)}
        </select>
        <label>{ko ? "속도" : "Speed"} <select value={speed} onChange={event => setSpeed(Number(event.target.value))}>{[1, 5, 20].map(rate => <option value={rate} key={rate}>{rate} events/s</option>)}</select></label>
      </nav>
      <div className={styles.pairTitle}><h2>{pair.task}</h2><p>Pair {String(state.pair + 1).padStart(3, "0")} / 445<br />Repetition {pair.repetition} / 5</p></div>
      <div className={styles.seek}><label htmlFor="replay-seek">Tool event</label><input id="replay-seek" type="range" min={0} max={max} value={state.step} onChange={event => setState(current => ({ ...current, step: Number(event.target.value) }))} /><output>{state.step} / {max}</output></div>
      <div className={styles.arms}>
        <Arm cell={pair.geode} metrics={metrics[pair.geode.cell]} step={state.step} done={state.step === max} playing={state.playing} ko={ko} />
        <Arm cell={pair.native} metrics={metrics[pair.native.cell]} step={state.step} done={state.step === max} playing={state.playing} ko={ko} />
      </div>
      <p className={styles.caption}>{ko ? "Tool event 순서로 나란히 재생합니다. 실제 동시 실행이나 wall-time 정렬이 아닙니다." : "Aligned by tool-event index, not concurrent execution or wall time."} UTC source / KST display.</p>
      <details className={styles.boundaries}>
        <summary>{ko ? "재생 범위와 점수 해석" : "Evidence coverage and score interpretation"}</summary>
        <p>{ko ? "89 tasks × 5 repetitions × 2 arms = 890 planned cells입니다. Task와 repetition이 같은 두 cell이 pair입니다. 16,244개 tool 호출의 종류, payload 크기와 시각만 공개합니다. Command/output 원문과 모델 메시지, provider reasoning은 포함하지 않습니다." : "89 tasks × 5 repetitions × 2 arms = 890 planned cells. A pair matches a task and repetition across arms. The view exposes metadata for 16,244 tool calls, not command/output bodies, model messages or provider reasoning."}</p>
        <p>{ko ? "835개 cell은 보존 ATIF에서 재구성했습니다. 35개는 receipt-only이며 terminal 내용을 추정하지 않았습니다. bn-fit-modify와 tune-mjcf의 20개 cell은 arm64 호스트에서 amd64 oracle/verifier가 완료되지 않아 모델 호출 전에 대칭 제외했습니다. 이 화면은 원본 PTY 녹화가 아닙니다." : "835 cells are reconstructed from preserved ATIF. 35 are receipt-only; missing terminal content is not invented. Twenty bn-fit-modify and tune-mjcf cells were symmetrically excluded before model calls after amd64 oracle/verifier failures on the arm64 host. This is not raw PTY footage."}</p>
        <p>{ko ? "Full-suite primary는 측정 불가입니다. 미해소 native 인프라 무효 6개를 제외한 공통 유효 429쌍의 secondary 결과는 GEODE 339/429, Codex 331/429입니다. Raw verifier 1이어도 canonical timeout/refusal 규칙으로 selected 0인 cell이 18개 있습니다. 점수 근거는 Harbor result/verifier와 frozen ledger·analysis입니다. Replay는 채점기가 아닙니다." : "The full-suite primary is not measurable. Excluding six unresolved native infrastructure-invalid cells leaves 429 common valid pairs: GEODE 339/429, Codex 331/429, secondary only. Eighteen cells have raw verifier one but selected zero under frozen timeout/refusal rules. Harbor result/verifier and the frozen ledger/analysis own scoring, not this replay."}</p>
        <p>{ko ? "재생 속도는 편집 시간입니다. 전체 attempt 계보는 보존하며, 이 화면은 cell별 선택된 대표 attempt를 재생합니다. Payload의 lines는 직렬화된 observation 기준이며 stdout의 줄 수와 같다고 보장하지 않습니다." : "Playback speed is editorial. All attempt lineage is preserved; this view plays one representative attempt per cell. Payload lines describe serialized observations, not necessarily stdout lines."}</p>
        <a href={EVIDENCE_URL}>Artifact commit {ARTIFACT_COMMIT.slice(0, 7)}</a>{" / "}<a href={DATA_URL}>Public JSON</a>
        <p className={styles.digest}>SHA-256 <code>{DATA_SHA256}</code></p>
        <p>{ko ? "복구된 호출별 usage: GEODE 401셀·4,709 events / Codex 418셀·12,214 events. GEODE cache 미기록 648건은 null로 남겼습니다. 이 숫자들은 점수나 tool-event 정렬을 변경하지 않습니다." : "Recovered call usage: GEODE 401 cells / 4,709 events; Codex 418 cells / 12,214 events. The 648 missing GEODE cache fields remain null. These diagnostics do not change scoring or tool-event alignment."}</p>
        <a href={OBSERVABILITY_URL}>Observability JSON · {OBSERVABILITY_COMMIT.slice(0, 7)}</a>
        <p className={styles.digest}>SHA-256 <code>{OBSERVABILITY_SHA256}</code></p>
      </details>
      <footer className={styles.caption}>Space: {ko ? "재생·일시정지" : "play/pause"} / ← →: {ko ? "이전·다음 pair" : "previous/next pair"} / {ko ? "새 모델 호출 없음" : "No new model calls"}</footer>
    </div>
  );
}
