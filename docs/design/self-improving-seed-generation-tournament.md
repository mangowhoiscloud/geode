---
title: DESIGN.md · `/seed-generation/<run_id>/tournament/` (Ranker matches)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/seed-generation/<run_id>/tournament/`

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Render every ranker match in the run with its full 3-voter panel
outcome: which candidate, which voters (model + provider chip), each
voter's vote (A / B / tie) + rationale + duration, and the Elo
before→after delta per match.

PR-SEEDS-HIRES P2 (2026-05-26). Closes the operator directive: "rank
에서 각 매치들은 어떤 결과를 거쳤는지".

## 2. Source data

`tournament.json` (PR-SEEDS-HIRES P1, written by
`Ranker._persist_tournament_log`). Schema:

```json
{
  "run_id": "...",
  "gen_tag": "...",
  "voter_panel": [
    {"voter_id": "...", "voter_model": "...", "voter_provider": "..."}
  ],
  "matches": [
    {
      "match_id": "m1",
      "candidate_a": "c-001",
      "candidate_b": "c-002",
      "winner": "A" | "B" | "tie" | null,
      "quorum_lost": false,
      "votes": [
        {
          "voter_id": "...",
          "voter_model": "...",
          "voter_provider": "...",
          "vote": "A" | "B" | "tie" | null,
          "rationale": "...",
          "duration_ms": 0.0,
          "parse_error": null
        }
      ],
      "elo_before": {"a": 1000.0, "b": 1000.0},
      "elo_after":  {"a": 1020.0, "b":  980.0},
      "elo_delta_a": 20.0,
      "elo_delta_b": -20.0
    }
  ]
}
```

## 3. URL layout

- `/geode/self-improving/seed-generation/<run_id>/tournament/`

## 4. Layout

Top: a single muted line listing the voter panel chips.

Body: one `<section class="page-sub match">` per match:

- `<h3>` — `Match <match_id> — winner: <span class="bucket
  seedgen">A|B|tie|quorum lost</span>`
- `<p class="muted">` — Elo before→after for both candidates with
  `Δ` deltas
- `<table class="records votes">` — 3 rows (one per voter), 4 cols:
  voter / vote chip (`bucket.win-a`/`.win-b`/`.tie`) / rationale /
  duration

Quorum-lost matches render with `winner = "quorum lost"`, deltas
zero, and the partial-voter rows still rendered so the operator can
see why quorum failed (e.g. `parse_error="invalid_winner_label"`).

## 5. Frontier inspiration

- **inspect_ai SPA** per-sample scores breakdown — our 3-voter table
  is the same "panel members vote" pattern, statically
- **Co-scientist** ranking debate_pair output — voter rationale per
  match is the same "what did each judge say" affordance

## 6. E2E pin

- `test_pr2_tournament_renders_three_voter_panel` — ≥3 match
  sections + ≥3 vote tables + Elo label + A/B/tie coverage in fixture

## 7. Non-goals

- Match graph / bracket visualisation — flat list works fine for
  current scale (15-candidate run = 105 unordered pairs but pruned to
  ~12-30 actual matches). Defer until a run produces > 50 matches.
