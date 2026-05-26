---
title: DESIGN.md · `/seed-generation/<run_id>/agents/` (Conversations)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/seed-generation/<run_id>/agents/` + `/agent/<task_id>/`

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Render every conversation every sub-agent had during a seed-generation
run, with turn-by-turn fidelity. The operator can see the exact text
the agent sent to the model and the exact text the model sent back,
per session, per turn.

PR-SEEDS-HIRES P2 (2026-05-26). Closes the operator directive: "에이전트들이
나눈 모든 대화와 절차".

## 2. Source data

- `docs/self-improving/petri-bundle/seeds/<run_id>/sub_agents/<task_id>/`
  - `dialogue.jsonl` — per-turn events (`session_start | user_message
    | assistant_message | session_end`)
  - `session.json` — session metadata (`model`, `provider`,
    `metadata.phase`)
  - `result.json` — structured output `summary`

All three files ship in the bundle via `bundle_sync._sync_subagents`
(PR-SEEDS-HIRES P1, 2026-05-26).

## 3. URL layout

- `/geode/self-improving/seed-generation/<run_id>/agents/` — index
- `/geode/self-improving/seed-generation/<run_id>/agent/<task_id>/` — per-agent detail

## 4. Index layout (dense table)

| Column | Source |
|--------|--------|
| `task_id` | dir name; links to `/agent/<task_id>/` |
| `phase` | `session.json:metadata.phase` (fallback: task_id prefix) |
| `model` | harness chip (Claude Code / Codex / PAYG / GEODE) + raw model code |
| `turns` | count of `user_message` + `assistant_message` events |
| `cost` | `Σ session_end.total_cost` |
| `duration` | `Σ session_end.duration_s` |

Sorted by phase order (supervisor → meta_reviewer), then task_id.

## 5. Detail layout (turn-by-turn)

Top: `<dl class="run-detail-header">` with task_id / phase / model
chip / turns / total cost / duration / result summary + a "← back to
agents" link.

Body: a sequence of `<details class="turn ...">` blocks. One per
event in `dialogue.jsonl`:

- `session_start` — open by default; pre-formatted JSON of the event
- `user_message` — `summary` shows `user — turn N (M chars)`; expanded
  `<pre class="msg">` shows raw text
- `assistant_message` — same as user, with `.assistant` class
- `session_end` — open by default; pre-formatted JSON with cost +
  duration

Each `<details>` carries a CSS class for phase-bucket color (cotton:
reused `--bucket-{petri,seedgen,autoresearch}` — no new tokens).

## 6. Pagination / performance

All `<details>` collapsed by default → page renders ~5 KB regardless
of total turns. For runs with > 50 turns per agent, consider
bucketing into 20-turn `<details>` groups (deferred to PR-SEEDS-HIRES
P2.1 if needed).

## 7. Frontier inspiration

- **Langfuse** typed-observation list — our agent index is the same
  table-of-observations pattern
- **inspect_ai SPA** per-sample messages tree — our agent detail
  uses the same `<details>` collapse pattern, statically

## 8. E2E pins

`tests/test_self_improving_hub_e2e.py`:

- `test_pr2_agents_index_renders` — table + at least 1 row + harness chip
- `test_pr2_agent_detail_paginates_via_details` — ≥3 `<details>` blocks
- `test_pr2_subpages_basepath_safe` — every href `/geode/`-prefixed
- `test_pr2_subpages_no_js_framework` — no `<script>` tags

## 9. Non-goals

- Filtering / search — pure static HTML; operator uses Cmd+F
- Live tailing — see PR-SEEDS-HIRES P3 (`/active/` page)
