# Data SoT — `docs/visualizations/`

Every numeric / comparison / mapping shown in a scene is derived from a
markdown SoT document. The scene visualises and the audit verifies parity
with the SoT — never the other direction.

| Scene | SoT document(s) |
|-------|-----------------|
| `geode_hero.py` | `docs/visualizations/geode-hero-storyboard.md` (cold-open + 4-Act + honest Resolution composition), `docs/self-improving/run-2606-broken-tool-use.md` (the Resolution's measured arm table + 18-dim headroom-vs-noise ranking — the curated run report served on the hub), `docs/visualizations/text-overflow-map.md` (overflow site catalogue) |
| `autoresearch_compare.py` + `autoresearch_filewalk.py` | `docs/visualizations/autoresearch-comparison.md` (3-section: 8 verbatim / 7 swap / 11 add, 6-file LoC) |
| `critical_floor.py` | `autoresearch/train.py` — `compute_fitness` (line 692), `_dim_score` (line 627), `_stability_score` (line 635) |

## One-direction sync

When the truth changes (a new dim is added, an LoC is recounted, a comparison
row is reclassified), update the markdown first, then the scene's
module-level constants (`LOC`, `OUTLINE_*`, `HEATMAP`, ...). The scene is
downstream of the markdown.

The reverse direction is forbidden: editing scene constants without
updating the markdown leaves the SoT lying. The same parity guard applies
to CHANGELOG / PR body claims — every verb / adjective in the PR title
("git-tracked", "program.md-driven", "automatic") must be grep-provable in
code. See the `feedback_changelog_implementation_parity` memory for the
broader pattern.

## Inline values are scene-private only

Strings like `"dim_means: {broken_tool_use: 2.5, …}"` that appear only inside
the rendered scene (no SoT counterpart) are fine to keep inline, but they
must still be added to `verify_hero_layout.py::SITES` via `text_string_en` /
`text_string_ko` so the ratchet measures them.

## Reference clones

The Karpathy autoresearch reference clone lives at
`~/workspace/autoresearch/` (commit 228791f) for the `autoresearch_compare`
+ `autoresearch_filewalk` data. The clone is read-only; treat it as a
verification source, never as a write target. LoC counts come from
`wc -l` on the clone's `prepare.py` / `train.py` / `program.md`.
