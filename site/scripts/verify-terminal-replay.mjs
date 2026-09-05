// Execute the actual TypeScript loader/state machine; no extra test dependency.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/app/benchmarks/terminal-bench/replay/replay-data.ts", import.meta.url), "utf8");
async function compile(text) {
  const js = ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  return import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
}
const api = await compile(source);
assert.match(api.DATA_URL, /geode-eval-artifacts\/[a-f0-9]{40}\/terminal-bench\/.+\.json$/);
const cell = { events: [{}, {}] };
const pairs = [{ geode: cell, native: { events: [] } }, { geode: { events: [] }, native: { events: [] } }];
assert.equal(api.eventCount(pairs[0]), 2);
assert.equal(api.eventCount(pairs[1]), 1);
let state = { pair: 0, step: 0, playing: true };
for (let i = 0; i < 5; i++) state = api.nextFrame(state, pairs);
assert.deepEqual(state, { pair: 1, step: 1, playing: false });
assert.equal(api.nextFrame(state, pairs), state);
for (const [query, expected] of [["", 0], ["?pair=445", 444], ["?pair=Infinity", 0], ["?pair=NaN", 0], ["?pair=2.5", 0], ["?pair=-1", 0], ["?pair=999", 444]]) {
  assert.equal(api.pairFromSearch(query), expected);
}
assert.match(api.timeKst("2026-08-27T19:15:00Z"), /28\/08.*04:15:00 KST/);
assert.equal(api.timeKst(null), "Timestamp unavailable");
assert.equal(api.elapsedSeconds(null), "n/a");
assert.equal(api.elapsedSeconds(0), "0.0 s");
assert.equal(api.elapsedSeconds(0.000075), "<0.1 s");
assert.equal(api.elapsedSeconds(31.159), "31.2 s");
assert.equal(api.statusLabel({ status_label: "NOT RUN / 사전 제외" }, false), "NOT RUN / prospective exclusion");
assert.equal(api.statusLabel({ status_label: "INVALID / 인프라 무효" }, false), "INVALID / infrastructure-invalid");
assert.equal(api.statusLabel({ status_label: "NOT RUN / 사전 제외" }, true), "NOT RUN / 사전 제외");
assert.equal(api.statusLabel({ status_label: "ZERO / selected 0" }, false), "ZERO / selected 0");

const fixture = Buffer.from(JSON.stringify({ run_id: api.RUN_ID, pairs: Array(445).fill(pairs[0]) }));
const hash = createHash("sha256").update(fixture).digest("hex");
const fixtureApi = await compile(source.replace(api.DATA_SHA256, hash));
const realFetch = globalThis.fetch;
try {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, api.DATA_URL);
    assert.equal(options.credentials, "omit");
    assert.equal(options.referrerPolicy, "no-referrer");
    assert.ok(options.signal instanceof AbortSignal);
    return new Response(fixture);
  };
  assert.equal((await fixtureApi.loadReplay(new AbortController().signal)).pairs.length, 445);
  await assert.rejects(api.loadReplay(new AbortController().signal), /integrity/);
  globalThis.fetch = async () => new Response(null, { status: 503 });
  await assert.rejects(api.loadReplay(new AbortController().signal), /download/);
  globalThis.fetch = async () => { throw new Error("offline"); };
  await assert.rejects(api.loadReplay(new AbortController().signal), /offline/);
} finally { globalThis.fetch = realFetch; }

const legacy = readFileSync(new URL("../public/benchmarks/terminal-bench/replay.html", import.meta.url), "utf8");
assert.ok(!legacy.includes("iframe") && !legacy.includes("fetch("));
let target;
vm.runInNewContext(legacy.match(/<script>([\s\S]*?)<\/script>/)[1], {
  location: { search: "?pair=445&lang=en", hash: "#evidence", replace: value => { target = value; } },
});
assert.equal(target, "./replay/?pair=445&lang=en#evidence");

// Optional exact public-artifact audit. Normal builds remain offline.
if (process.argv[2]) {
  const bytes = readFileSync(process.argv[2]);
  const data = await api.decodeReplay(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
  const ids = new Set(), pairIds = new Set(), coverage = {};
  let calls = 0, differences = 0;
  for (const pair of data.pairs) {
    assert.equal(typeof pair.task, "string");
    assert.ok(pair.repetition >= 1 && pair.repetition <= 5);
    assert.ok(!pairIds.has(pair.task + pair.repetition)); pairIds.add(pair.task + pair.repetition);
    for (const arm of ["geode", "native"]) {
      const item = pair[arm];
      assert.equal(item.arm, arm); assert.equal(item.repetition, pair.repetition);
      assert.equal(item.task_name, "terminal-bench/" + pair.task);
      assert.ok(Number.isInteger(item.cell) && item.cell >= 1 && item.cell <= 890 && !ids.has(item.cell)); ids.add(item.cell);
      assert.equal(typeof item.status_label, "string");
      coverage[item.replay_kind] = (coverage[item.replay_kind] ?? 0) + 1;
      assert.ok(item.wall_seconds === null || Number.isFinite(item.wall_seconds));
      if (item.timing?.started_at) assert.ok(Number.isFinite(Date.parse(item.timing.started_at)));
      for (const key of ["raw_verifier_reward", "selected_reward"]) assert.ok(item[key] == null || [0, 1].includes(item[key]));
      if (item.raw_verifier_reward === 1 && item.selected_reward === 0) differences++;
      if (item.trajectory_sha256) assert.match(item.trajectory_sha256, /^[a-f0-9]{64}$/);
      for (const row of item.lineage) for (const key of ["attempt_id", "validity", "outcome"]) assert.equal(typeof row[key], "string");
      for (const event of item.events) {
        calls++;
        for (const key of ["tool", "program", "timestamp_utc"]) assert.equal(typeof event[key], "string");
        assert.ok(Number.isFinite(Date.parse(event.timestamp_utc)));
        for (const key of ["step", "output_chars", "output_lines"]) assert.ok(Number.isInteger(event[key]) && event[key] >= 0);
        for (const key of ["command", "output", "message", "reasoning"]) assert.ok(!(key in event));
      }
    }
  }
  assert.equal(ids.size, 890); assert.equal(calls, 16244); assert.equal(differences, 18);
  assert.deepEqual(coverage, { "atif-derived-private": 835, "receipt-event": 35, "exclusion-card": 20 });
  if (process.argv[3]) {
    const raw = readFileSync(process.argv[3]);
    const buffer = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
    const recovered = await api.decodeObservability(buffer, data);
    assert.equal(Object.keys(recovered).length, 890);
    let geodeCalls = 0, nativeCalls = 0, missingCache = 0, notRun = 0;
    for (const cell of Object.values(recovered)) {
      const usage = cell.usage;
      assert.ok(["verified-call-usage", "unavailable", "not-run"].includes(usage.status));
      for (const key of ["input_tokens", "output_tokens", "cached_input_tokens", "observed_cached_tokens"])
        assert.ok(usage[key] === null || (Number.isInteger(usage[key]) && usage[key] >= 0));
      if (usage.status === "not-run") notRun++;
      if (cell.arm === "geode") geodeCalls += usage.events.length; else nativeCalls += usage.events.length;
      const absent = usage.events.filter(event => event.cached_input_tokens === null).length;
      assert.equal(absent, usage.cache_missing_events); missingCache += absent;
      if (absent) assert.equal(usage.cached_input_tokens, null);
      if (usage.events.length) for (const key of ["input_tokens", "output_tokens"])
        assert.equal(usage.events.reduce((sum, event) => sum + event[key], 0), usage[key]);
      for (const event of usage.events) {
        assert.ok(Number.isFinite(Date.parse(event.timestamp_utc)));
        for (const key of ["input_tokens", "output_tokens"]) assert.ok(Number.isInteger(event[key]) && event[key] >= 0);
      }
      assert.deepEqual(Object.keys(cell.phases).sort(), ["agent_execution", "agent_setup", "environment_setup", "verifier"]);
      for (const phase of Object.values(cell.phases)) {
        assert.ok(["observed", "not-run", "not-reached", "incomplete"].includes(phase.status));
        assert.ok(phase.seconds === null || (Number.isFinite(phase.seconds) && phase.seconds >= 0));
      }
      assert.ok(cell.commands.completed === null || Number.isInteger(cell.commands.completed));
      assert.ok(cell.commands.nonzero === null || Number.isInteger(cell.commands.nonzero));
      assert.ok(cell.cost.reported_estimate_usd === null || Number.isFinite(cell.cost.reported_estimate_usd));
      assert.equal(cell.cost.billed_usd, null);
    }
    assert.deepEqual([geodeCalls, nativeCalls, missingCache, notRun], [4709, 12214, 648, 20]);
    await assert.rejects(api.decodeObservability(new ArrayBuffer(0), data), /integrity/);
    const wrongJoin = structuredClone(data); wrongJoin.pairs[0].geode.attempt_id = "wrong";
    await assert.rejects(api.decodeObservability(buffer, wrongJoin), /join/);
    try {
      globalThis.fetch = async () => new Response(raw);
      assert.equal(Object.keys(await api.loadObservability(new AbortController().signal, data)).length, 890);
      globalThis.fetch = async () => new Response(null, { status: 503 });
      await assert.rejects(api.loadObservability(new AbortController().signal, data), /download/);
    } finally { globalThis.fetch = realFetch; }
    console.log("Recovered observability: 890 joins, 16923 call events, null semantics, bad hash/join/download PASS");
  }
  console.log("Pinned artifact: 445 pairs, 890 unique cells, 16244 tool calls, 18 raw/selected differences PASS");
}
console.log("Replay: SHA-256, fetch failures, state transitions, KST, query bounds, legacy redirect PASS");
