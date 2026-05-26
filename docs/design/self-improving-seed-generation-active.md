---
title: DESIGN.md · `/seed-generation/active/` (Live runs)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/seed-generation/active/`

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Cross-run live dashboard — list every seed-generation run whose
`progress.json:current_phase != "done"` with current phase / step /
agent / ETA. Hybrid liveness model: static build-time snapshot +
inline JS that polls each run's `progress.json` every 5s.

PR-SEEDS-HIRES P3 (2026-05-26). Closes the operator directive: "활성
런, 런별로 현재 진행중인 에이전트와 스텝".

## 2. Source data

- `docs/self-improving/petri-bundle/seeds/<run_id>/progress.json` —
  per-run heartbeat written by `Pipeline._persist_progress` at every
  phase boundary + sub-agent spawn (PR 1).

## 3. URL layout

- `/geode/self-improving/seed-generation/active/`

## 4. Layout

Top: `<p class="live-indicator">` with a pulsing dot and a short note
about polling cadence.

Body: one `<table class="records active-runs">` with columns:

| Column | Source |
|--------|--------|
| run_id | dir name; links to per-run page |
| phase | `progress.json:current_phase` (rendered as bucket-seedgen chip) |
| step | `progress.json:current_step` (free-text, e.g. "vote 3 of 12") |
| agent | `progress.json:current_agent_task_id` (links to `/agent/<task_id>/`) |
| eta | `progress.json:eta_seconds` formatted |
| updated | `progress.json:last_updated_at` formatted as "Ns/m/h ago" |

Empty state (no active runs): muted paragraph noting the build
timestamp + the meta-refresh + JS-poller cadence.

## 5. Liveness model (hybrid)

- **Static snapshot** — what the page renders at build time. GitHub
  Pages serves this as plain HTML.
- **`<meta http-equiv="refresh" content="60">`** — fallback for
  JS-disabled browsers; the page reloads every 60s and the new
  snapshot reflects whatever the live writer published since.
- **Inline JS poller (~50 lines, ≤ 2 KB, no framework)** —
  `setInterval(poll, 5000)` re-fetches each run's `progress.json`
  and updates the table cells in place. If a `current_phase`
  becomes `"done"`, the row is removed. Failures (404 / network)
  are swallowed silently — the JS-disabled fallback (meta-refresh
  + new build) catches it eventually.

The live writer in PR 1 (`Pipeline._live_sync_loop`, 5s cadence)
publishes the source `progress.json` updates to the bundle dir; the
JS poller reads the same file. End-to-end latency: ~5s writer +
~5s poller = ~10s worst case.

## 6. Cotton discipline

- Inline `<script>` only; no `src="..."`, no ESM `import`. Test
  `test_pr3_active_has_meta_refresh_and_js_poller` enforces `< 2 KB`
  per script tag.
- Zero new color tokens. Uses `--bucket-seedgen` for the pulsing dot
  and chip backgrounds.
- The pulsing dot is a 2-second CSS keyframe animation on opacity
  only — no transform / layout thrash.

## 7. Frontier inspiration

- **Vercel deploy log** — same "live snapshot + polling" pattern,
  scaled down to a static page.
- **Inspect_ai task list** — same "in-progress vs done" filter.

## 8. E2E pins

- `test_pr3_active_runs_lists_in_progress` — in-progress fixture
  appears, done fixtures filtered out.
- `test_pr3_active_has_meta_refresh_and_js_poller` — meta-refresh
  + inline script ≤ 2 KB + no framework imports.

## 9. Non-goals

- WebSocket / SSE — `geode serve` uses stdlib `http.server`, no
  async framework; the polling approach matches operator's
  "소켓을 넣어도 좋아" while staying within the stdlib.
- Cross-machine "all-runs" view — each operator's hub is one machine's
  view; the bundle aggregates only runs from that machine's
  `state/seed-generation/`.
