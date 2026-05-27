# Hub Visualization Fix Plan — cycle 1 data-driven

**Date**: 2026-05-28
**Scope**: `docs/self-improving/seed-generation/<run_id>/` hub pages — bundle MD coverage + per-candidate lineage + ranker visualization + evolver diff
**Source data**: `state/seed-generation/gen1-broken_tool_use/` (cycle 1, 36 min wall-clock, 9/9 phases complete)
**Predecessor mockup**: 3-screen ASCII proposal from earlier this session (All-MD catalog / Lineage 5-station / Evolver Diff)

## Cycle 1 outcome summary

| Metric | Value | Note |
|--------|-------|------|
| wall-clock | **36 min 23 s** | T+0 03:10:20 → T+36 03:46:43 |
| caps (env override) | claude_cli=2 / openai_api=4 / ranker_max_inflight=2 | freeze 미발생, abort guard 미발동 |
| sub_agents | **230** | 1 supervisor + 1 proximity + 15 gen + 15 critic + 15 pilot + 177 ranker voter (118 codex fail + 59 claude ok) + 5 evolve + 1 meta |
| 15 → survivors | **15 → 5** | top-K=5 default |
| evolved | **5 (100% yield on survivors)** | all 5 survivors got an evolved variant |
| usd_spent | $0.0 tracked (subscription) | preview equivalent: $6.34 PAYG |

## ⚠️ Critical finding (out of hub scope — separate issue)

**Codex voter (gpt-5.5) failed on 118/118 ranker calls** (`parse_error: voter_call_failed`). 100% of 59 matches lost quorum (only claude-cli's 1 vote landed per match, insufficient for ratification). All 15 candidates' Elo stayed at flat 1000.0, so survivor selection became id-ordered (gen1-000..004 picked) instead of merit-ordered.

**Implication for hub design**: ranker UI MUST surface `quorum_lost` count and per-voter failure rate prominently — otherwise operators see "5 survivors with Elo 1000" and falsely interpret it as a tie when reality is "ranker never produced signal."

**Not in this PR**: investigation of why codex voter parses fail. Tracked separately for the appropriate sprint.

## Data inventory — what's actually written per run

Confirmed from `state/seed-generation/gen1-broken_tool_use/`:

```
candidates/                   15 × <cid>.md         draft MD bodies (YAML frontmatter + markdown body)
candidates_evolved/            5 × <cid>e-<hash>.md evolved MDs (only for survivors)
checkpoints/                   9 × <phase>.json     state_snapshot per phase
elo_log.tsv                                         match-by-match Elo tape
meta_review.json                                    coverage / next_gen_priors / evolution_yield / session_summary
per_phase_costs.json                                {cost_usd, prompt_tokens, completion_tokens, duration_ms, agent_count} per phase
progress.json                                       run-level current_phase + completed_phases + eta
state.json                                          full PipelineState (candidates / pilot_scores / elo_ratings / reflections / survivors / evolved_candidates / meta_review)
sub_agents/                  230 × <task_id>/      dialogue.jsonl + result.json + session.json
survivors/                     5 × <cid>.md         survivor MDs (copy of candidates/<cid>.md for cards)
survivors.json                                      survivor IDs + Elo
tournament.json               59 × match dict       full per-match voter rationale + Elo delta + winner / quorum_lost
transcript.jsonl                                    pipeline-wide turn-by-turn dialogue
```

Bundle mirror at `docs/self-improving/petri-bundle/seeds/gen1-broken_tool_use/` already received 10/13 items (every JSON + sub_agents/ + checkpoints/). **Missing from bundle**: `candidates/` (draft MDs), `candidates_evolved/`, `survivors/`, `elo_log.tsv`. The first three are the heart of the visualization request.

## Mockup ↔ actual delta (per screen)

### Screen 1 — All-MD catalog `/seed-generation/<run_id>/candidates/`

| Mockup column | Reality | Action |
|--------------|---------|--------|
| `critic` band (low/medium/high) | 14 low + 1 medium in cycle 1. Pattern correct | ✅ keep as-is |
| `pilot` top-score | reality is **top-1 dim_mean + dim_name** (not generic score). 2/15 are all-zero (pilot-fail) | ⚠️ split into 2 columns: `pilot_top1_dim` + `pilot_top1_mean`, add `pilot-fail` badge for all-zero rows |
| `ranker` `5W-2L +42` | reality is `quorum_lost` count + winner% + Elo delta | ⚠️ rename to `ranker_status` showing `quorum_lost / matches` ratio when applicable, full WLT only when matches have winner |
| `survived?` | works as-is | ✅ |
| `evolved →` | 5/15 evolved (only survivors). Naming `<parent>e-<hash>` | ✅ link to evolved cid lineage |
| **new: `target_dim hit?`** | 9/15 have top-1 dim = target_dim, 4 drift to adjacent dims | 🆕 add `off-target` chip when top-1 ≠ target_dim |
| **new: `quorum_lost` badge** | 100% in cycle 1 due to codex failure | 🆕 surface at run-level + per-row |

### Screen 2 — Lineage page `/seed-generation/<run_id>/lineage/<cid>/`

Current 4-station (generator / critic / pilot / evolver) extends to **5-station** with ranker.

| Station | Mockup | Reality | Action |
|---------|--------|---------|--------|
| 1. generator | full MD body (raw `<pre>`) | YAML frontmatter + markdown body | ⚠️ separate metadata box (parsed YAML) + render rest with markdown-it-py |
| 2. critic | judge_risk / discrimination / strengths / weaknesses / rewrite_section | exact match in `state.json.reflections[cid]` | ✅ |
| 3. pilot | top-8 dim_means table | top-3 ≥ 2.0 is meaningful, below is noise (1.0 floor) | ⚠️ filter to top-3 OR ≥ 2.0; add eval-fail row for all-zero |
| 4. **ranker (new)** | matches played / W-L-T / Elo delta / per-match table | exact data in `tournament.json` — but `winner=None` + `quorum_lost=True` are dominant in cycle 1 | ⚠️ template handles 3 cases: ratified-winner / tie / quorum_lost (with voter parse_error breakdown) |
| 5. evolver | mutation_axis / rewrite_section / notes | only for 5 survivors; non-survivors get "not evolved (eliminated at ranker)" | ✅ |

**New element — voter rationale expand**: each ranker match row should expand on click to show claude-cli voter's full rationale (cycle 1 sample: ~400-800 chars per vote, rich content). Failed voter rows show `parse_error` reason.

### Screen 3 — Evolver Diff `/seed-generation/<run_id>/lineage/<cid>/diff/`

| Aspect | Mockup | Reality | Action |
|--------|--------|---------|--------|
| side-by-side rendered MD | yes | ✅ both `candidates/<cid>.md` and `candidates_evolved/<cid>e-<hash>.md` exist | ✅ keep |
| diff highlight unit | line-level via difflib | cycle 1 evolver notes describe surgical edits (e.g. "Replace v4.11.3 with v4.12.0-rc2.9c4f7a1") — line-level is right granularity | ✅ |
| `rewrite_section` quote | from evolver checkpoint | matches `state.json.evolved_candidates[].rewrite_section` (e.g. "Make version mismatch less visually salient...") | ✅ render as quote box above diff |
| `notes` | from evolver checkpoint | ~200-400 chars per evolved, ✅ usable as caption | ✅ |
| `mutation_axis` | empty in cycle 1 | data is `—` (not populated by evolver in cycle 1) | ⚠️ template: render `—` cleanly, do not crash on absent |

### New element discovered — meta_review surface

Cycle 1's `meta_review.json` has 7 fields not in any mockup:
- `coverage` (per-dim seed count map)
- `underrepresented_dims` / `overrepresented_dims` (list)
- `next_gen_priors` (recommended target_dims for next cycle)
- `elo_distribution` (min / p50 / p95)
- `evolution_yield` (attempted / successful)
- `session_summary` (multi-paragraph reflective text)

→ run-level index page (already exists) should expose meta_review as a dedicated section. Cycle 1 page already does partially (existing `meta_review.json` table); just verify the fields above all render and the session_summary is full text not truncated.

## Implementation plan

### Step 1 — Bundle: copy all MDs (not just survivors)

**File**: `plugins/seed_generation/bundle_sync.py`

Current behavior (line 169-184): bundle only copies `candidates/<cid>.md` for IDs in `survivors.json`. Extend to copy all three MD types:

```python
# After existing survivor-only copy, additionally:
for subdir in ("candidates", "candidates_evolved", "survivors"):
    src_subdir = src_dir / subdir
    if not src_subdir.is_dir():
        continue
    dst_subdir = bundle_dir / subdir
    dst_subdir.mkdir(parents=True, exist_ok=True)
    for md in src_subdir.glob("*.md"):
        shutil.copy2(md, dst_subdir / md.name)
```

Same mtime-aware logic in `sync_run_incremental` (live 5s loop).

**Storage cost**: 15 draft + 5 evolved + 5 survivor copies ≈ 25 × 2 KB = **50 KB/run**, negligible.

**Test**: `tests/plugins/seed_generation/test_bundle_sync.py` — extend with assertion that all three subdirs land in bundle for a fixture run.

### Step 2 — Hub builder: ranker station + voter rationale

**File**: `scripts/build_self_improving_hub.py`

In `_render_lineage_page_per_cid` (or equivalent), add a new section between `pilot` and `evolver`:

```python
def _render_ranker_station(cid: str, tournament: dict) -> str:
    cid_matches = [m for m in tournament["matches"]
                   if cid in (m["candidate_a"], m["candidate_b"])]
    winners = sum(1 for m in cid_matches if _won(m, cid))
    losses = sum(1 for m in cid_matches if _lost(m, cid))
    ties = sum(1 for m in cid_matches if m["winner"] == "tie")
    quorum_lost = sum(1 for m in cid_matches if m["winner"] is None)
    # ... render to HTML with conditional templates for the 3 cases
```

Each match row expandable (`<details><summary>`) to show:
- voter list with provider chip (codex / claude-cli)
- ratified / parse_error per voter
- rationale text (full, not truncated)
- Elo before/after for both sides

### Step 3 — Hub builder: evolver diff

**File**: `scripts/build_self_improving_hub.py`

New route `lineage/<cid>/diff/index.html`:
- Read `candidates/<cid>.md` + `candidates_evolved/<evolved_cid>.md`
- Use `difflib.HtmlDiff` (stdlib) OR custom side-by-side renderer with line-level marks
- Wrap each side in `<article class="markdown-body">` after `markdown-it-py` parse
- Header shows `rewrite_section` (quote block) + `notes` (caption)

**Choice**: `difflib.HtmlDiff` is the simplest; output already has line-level `+/-/=` markup. Trade-off: not as polished as monaco-diff but no JS bundle required.

### Step 4 — Hub builder: all-MD catalog `/candidates/`

**File**: `scripts/build_self_improving_hub.py`

New route `seed-generation/<run_id>/candidates/index.html`:

```python
def _render_candidates_catalog(state: dict, tournament: dict, run_id: str) -> str:
    candidates = state["candidates"]  # list of 15 cid dicts
    rows = []
    for c in candidates:
        cid = c["id"]
        critic = state["reflections"].get(cid, {})
        pilot = state["pilot_scores"].get(cid, {})
        elo = state["elo_ratings"].get(cid)
        survived = cid in state["survivors"]
        evolved = next((e for e in state["evolved_candidates"] if e["parent_id"] == cid), None)
        rows.append(_row_template(...))
    return _table_template("\n".join(rows))
```

Row schema (one `<tr>` per draft):

| Column | Source | Conditional rendering |
|--------|--------|----------------------|
| cid (linked to lineage) | `candidates[].id` | always |
| critic risk | `reflections[cid].judge_risk` | badge color by risk band |
| pilot top1 | sorted `pilot_scores[cid].dim_means` | `pilot-fail` badge if all-zero |
| target_dim hit | `top1 == state.target_dim` | `off-target` chip with actual top1 |
| ranker W-L | per-cid filter on tournament | `quorum_lost` chip if no winners |
| Elo | `elo_ratings[cid]` | flat 1000.0 → muted |
| survived? | `cid in survivors` | star icon |
| evolved → | `evolved_candidates` join | link to evolved cid + diff page |

Filter chips at top: `[ all ] [ survived ] [ evolved ] [ pilot-ok ] [ off-target ] [ critic-pass ]`.

### Step 5 — Hub builder: meta_review section on run page (verify, may already work)

**File**: `scripts/build_self_improving_hub.py`

Check current `_render_run_page` already includes meta_review. If yes, just verify all 7 fields render after cycle 1. If `session_summary` is being truncated, remove truncation.

## Acceptance criteria

1. **Bundle**: `docs/self-improving/petri-bundle/seeds/gen1-broken_tool_use/{candidates,candidates_evolved,survivors}/` 모두 채워짐 (final sync 후)
2. **Catalog**: `/seed-generation/gen1-broken_tool_use/candidates/` 가 15 row 표 + filter chip 표시. 100% quorum_lost 상황을 chip 으로 visible
3. **Lineage**: 각 5 survivors 의 `lineage/<cid>/index.html` 이 5-station 표시 — 특히 ranker station 이 quorum_lost 케이스 깨끗하게 렌더
4. **Diff**: 5 evolved 각각의 `/lineage/<cid>/diff/index.html` 이 side-by-side rendered MD 표시
5. **No regression**: 기존 lineage page (gen1-redundant_tool_invocation) 가 동일하게 렌더 (회귀 없음)
6. **Test**: bundle_sync 와 hub builder 양쪽에 fixture-driven snapshot test 추가

## Operator decisions (locked 2026-05-28)

| Q | Decision |
|---|----------|
| evolver diff 모드 | **side-by-side** (no toggle in v1) |
| markdown renderer | **marked.js** (client-side; build-time embeds raw MD, page-load renders) |
| ranker quorum_lost 노출 위치 | **run-level banner + per-cid lineage station** |
| codex voter failure 디버깅 | **별도 sprint** — 본 PR 는 시각화만 |

## PR shape

- **Branch**: `feature/hub-visualization-cycle1`
- **Base**: develop
- **Estimated diff**: ~550 lines (350 in `build_self_improving_hub.py`, 60 in `bundle_sync.py`, 40 in `hub.css`, 100 in tests)
- **No version bump** — pure builder/UX work, no public-API change
- **CI gates**: ruff / format / mypy / lint-imports / pytest

## Related artefacts

- Cycle 1 run-dir: `state/seed-generation/gen1-broken_tool_use/`
- Cycle 1 bundle: `docs/self-improving/petri-bundle/seeds/gen1-broken_tool_use/`
- Hub builder: `scripts/build_self_improving_hub.py` (current 835 lines)
- Hub root: `docs/self-improving/index.html` (sidebar + Overview table — unchanged by this PR)
- Predecessor sprint: v0.99.74 / v0.99.75 / v0.99.76 (cap walk-back)
