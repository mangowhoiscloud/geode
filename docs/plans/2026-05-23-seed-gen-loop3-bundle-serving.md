# Phase 2 SoT — Loop 3 (literature paper-analysis) + petri-bundle serving

> **Status**: Plan-only — no implementation yet. Becomes SoT for the next PR
> cycle after PR #1504 (Phase 1 — Loop 2 debate-turn) merges.
>
> **Scope locked**: seed-generation Loop 3 internal loop + petri-bundle
> literature-serving pipeline. **Out of scope**: `mutations.jsonl` /
> `baseline.json` evidence schema realign — that lives in the parallel
> petri-autoresearch schema-realignment session and Phase 2 reads whatever
> shape that session settles on. This doc only commits to the
> seed-generation surface + the Pages publish surface.

## 1. Background — the 3-loop port

| Loop | Upstream | GEODE status |
|---|---|---|
| 1 — outer iteration | `generator.py:172-223` LangGraph cycle | ✅ already on develop |
| 2 — debate-turn | `nodes/generation/debate.py:71-147` | ✅ Phase 1 (PR #1504) |
| **3 — per-paper analysis** | `nodes/literature_review.py:840-873` | **❌ this Phase 2** |

Upstream's Loop 3 is the parallel per-paper LLM analysis step inside the
`literature_review` node — 1 LLM call per paper, fan-out via
`asyncio.gather`, terminated by `len(papers_with_content)` count. GEODE has
**no `literature_review` node at all**; the only `literature`-shaped
surface today is `baseline_reader.py` reading in-tree autoresearch state.

Phase 2's job: add a real `LiteratureReview` agent that runs the 4-phase
upstream pipeline (query_gen → paper_fetch → per-paper analysis →
synthesis), records each fetched paper as a git-tracked snapshot, and
makes the snapshots first-class citizens of the petri-bundle publish
surface.

## 2. Decision summary (from 2026-05-23 user session)

| # | Decision | Locked |
|---|---|---|
| Q | Evidence source — external vs self-history? | **External paper fetch** (option 2) |
| Q | Closed-loop preservation? | **Snapshot freeze** — fetched papers persisted to git-tracked `docs/petri-bundle/literature/` so audit replay remains reproducible |
| Q | Paper body in repo? | **Abstract + metadata + content_hash only** (full body lives at `~/.geode/petri-bundle/literature/` outside repo) |
| Q | `cited_by` reverse index — build step vs lazy viewer? | **Static build step** (`scripts/build_literature_listing.py`) |
| Q | Bundle layout — flat vs nested? | **`docs/petri-bundle/literature/`** mirrors `docs/petri-bundle/logs/` (Pages workflow same publish path) |
| Q | Schema migration for `mutations.jsonl` / `baseline.json`? | **Deferred** to petri-autoresearch realign session — Phase 2 reads, does not write to those |

## 3. New agent — `LiteratureReview`

```
plugins/seed_generation/agents/
├── literature_review.py     ← NEW — 4-phase internal pipeline (~250 LOC)
└── literature_review.md     ← NEW — system prompt
```

### 3.1 Phase ordering — insertion point

Add to `orchestrator.py:_PHASE_ORDER`:

```python
_PHASE_ORDER = (
    "supervisor",
    "literature_review",   # ← NEW — runs once after supervisor, before generator
    "generator",
    "proximity",
    "critic",
    "pilot",
    "ranker",
    "evolver",
    "meta_reviewer",
)
```

**NOT** in `_ITERATION_PHASE_ORDER` — literature_review runs **once per
seed-generation run** (iteration 0 only); subsequent iteration cycles
re-use the same `articles_with_reasoning` block (paper is constant
within a run).

### 3.2 Internal 4-phase pipeline

Inside `LiteratureReview.aexecute`:

```
Phase 1 — query_gen
  · 1 LLM call: target_dim + supervisor_guidance → 3-5 search queries
  · output: state.literature_review_queries: list[str]

Phase 2 — paper_fetch
  · for each query: arxiv_search(query, max_results=3)
  · dedup by arxiv_id across queries
  · for each unique arxiv_id:
      - check snapshot cache (docs/petri-bundle/literature/<id>-*.json)
      - if cached AND content_hash matches: skip fetch
      - else: paper_fetch_arxiv(arxiv_id) → freeze_paper_snapshot
  · output: state.literature_snapshots: dict[arxiv_id, snapshot_path]

Phase 3 — per_paper_analysis  ← THE LOOP 3 (paper Algorithm 1)
  · asyncio.gather(_analyze_paper(arxiv_id, target_dim) for arxiv_id in fetched)
  · per-paper LLM call: abstract + target_dim → {grounding_score, relevant_quote, gap_addressed}
  · output: state.paper_insights: dict[arxiv_id, insight]

Phase 4 — synthesis
  · 1 LLM call: paper_insights + target_dim → articles_with_reasoning block
  · output: state.articles_with_reasoning: str (markdown block, consumed by Generator/Critic/Evolver prompts)
```

LLM call total per run: `1 (query_gen) + N_papers (analysis) + 1 (synthesis)`.
Default `N_papers ≤ 9` (3 queries × 3 results) → typically 11 LLM calls per
literature_review phase. Cap via config (`max_papers`).

### 3.3 Cache hit path — no LLM calls

When all 9 papers are cache-hit (content_hash unchanged from prior run):
- Phase 1: 1 LLM call (query_gen) — but queries are deterministic on
  `(target_dim, supervisor_guidance_hash)`, so we can also cache the query
  set → 0 LLM calls
- Phase 2: 0 LLM calls (cache hits skip arxiv_search + paper_fetch)
- Phase 3: 0 LLM calls (insights cached on `(arxiv_id, target_dim)`)
- Phase 4: 1 LLM call (synthesis) — or also cache on insight hash

So a re-run with no new papers ≈ 1-2 LLM calls. Cheap.

### 3.4 Failure modes

| Failure | Behavior |
|---|---|
| arxiv API down | Use cached snapshots from prior runs (closed-loop survival) |
| All papers fail to fetch | `articles_with_reasoning = ""`, downstream agents fall through to non-literature prompts (same as bootstrap pre-Phase-2 run) |
| LLM rate limit during analysis | Partial — successful insights make it to synthesis, failed papers logged but not blocking |
| Snapshot write fails (disk full / permission) | Fail the phase; meta_reviewer flagged as "no literature evidence this run" |

## 4. Snapshot storage

### 4.1 File layout

```
docs/petri-bundle/literature/
├── 2502.18864-2026-05-23T1530Z.json
├── 2412.13371-2026-05-22T0700Z.json
├── ...
└── listing.json                     ← built by scripts/build_literature_listing.py
```

External SoT for full body (not in repo):

```
~/.geode/petri-bundle/literature/
└── 2502.18864-2026-05-23T1530Z/
    ├── abstract.txt                 ← duplicated for offline read
    ├── pdf_url.txt                  ← arxiv pdf URL only
    └── raw_response.json            ← arxiv API raw response (debug)
```

### 4.2 Snapshot file schema

```json
{
  "arxiv_id": "2502.18864",
  "title": "Petri: probing alignment dimensions",
  "abstract": "...",
  "authors": ["..."],
  "categories": ["cs.AI", "cs.CL"],
  "published_at": "2025-02-26",
  "retrieved_at": "2026-05-23T15:30:00+00:00",
  "content_hash": "sha256:a4f2...b91c",
  "arxiv_url": "https://arxiv.org/abs/2502.18864",
  "pdf_url": "https://arxiv.org/pdf/2502.18864.pdf",
  "external_body_path": "~/.geode/petri-bundle/literature/2502.18864-2026-05-23T1530Z/",
  "cited_by": {}
}
```

`cited_by` is populated by the build step (§6), not by the snapshot writer.

### 4.3 `content_hash` semantics

SHA256 over the **normalized abstract text** (lower-cased, stripped). This
is the cache key — if the abstract changes (arxiv updates), the snapshot
re-fetches. Title / category changes alone don't invalidate (those are
metadata, not evidence content).

## 5. New tool — `freeze_paper_snapshot`

A new delegated tool for the LiteratureReview agent's sub-agents to call
when they want to commit a fetched paper to the snapshot store.

```
core/tools/literature_snapshot.py
└── FreezePaperSnapshotTool
    ├── name: "freeze_paper_snapshot"
    ├── args: arxiv_id, abstract, title, authors, categories,
    │         published_at, pdf_url, raw_response
    └── returns: {snapshot_path, content_hash, cache_hit}
```

Bounds + safety (Codex MCP HIGH guard, derived from Phase 1 lessons):

- `arxiv_id` must match `^\d{4}\.\d{4,5}(v\d+)?$` (arxiv pattern)
- `snapshot_path` derived inside the tool — LLM can't pass arbitrary path
- Resolved path must remain under `<repo_root>/docs/petri-bundle/literature/`
- Atomic write (tmp + rename) so a crashed editor never leaves partial json

Tool also handles cache-hit short-circuit: if a snapshot for
`<arxiv_id>` already exists with matching `content_hash`, return its path
without re-writing.

## 6. Build step — `scripts/build_literature_listing.py`

Runs from `pages.yml` workflow (Pages build step) and locally via
`uv run python scripts/build_literature_listing.py`.

### 6.1 Algorithm

```
1. Scan docs/petri-bundle/literature/*.json (skip listing.json).
2. For each snapshot:
   - Validate schema (jsonschema)
   - Build short row: {arxiv_id, title, retrieved_at, content_hash_short,
     categories, url}
3. Scan autoresearch/state/mutations.jsonl (if present):
   - For each mutation row, check evidence array for {kind:
     "literature_snapshot", arxiv_id}
   - Build reverse index: arxiv_id → [{gen_tag, mutation_id, run_id}]
4. Scan plugins/petri_audit/seeds_gen*/**/*.md (or wherever post-gen
   seeds live):
   - Parse frontmatter `references:` list (already CSP-3 spec)
   - For each arxiv_id in references, add (seed_id, target_dim) to
     reverse index
5. Merge reverse index into listing.json rows:
   - row["cited_by_count"] = len(reverse_index[arxiv_id])
   - row["cited_by"] = grouped by source (mutations / seeds)
6. Write docs/petri-bundle/literature/listing.json (atomic).
```

### 6.2 Idempotency

Re-running with no new snapshots produces byte-identical listing.json
(deterministic ordering: by `arxiv_id` then `retrieved_at`).

### 6.3 Cross-ref data — what shape we depend on

| Source | Field | If schema changes |
|---|---|---|
| `mutations.jsonl` | `row["evidence"][i]["arxiv_id"]` | Build step defensive — `.get("arxiv_id")` with fallback to skipping the row. **The petri-autoresearch session decides the final shape**; this build step uses a TODO sentinel until that shape lands. |
| seed `.md` frontmatter | `references: [arxiv_id, ...]` | Already spec'd in CSP-3 (`agents/generator.md`); no change. |

When petri-autoresearch ships the realigned schema, the build step gets
one ~5-line change. Phase 2 doesn't block on it.

## 7. Bundle UI — 3 surfaces

### 7.1 Landing page (`docs/petri-bundle/index.html`)

Existing audit-log section stays. Add a literature card:

```html
<section class="bundle-card">
  <h2>📚 Literature snapshots</h2>
  <p class="count">43 snapshots · cited by 28 mutations · 12 seeds</p>
  <a href="literature/">Browse →</a>
</section>
```

### 7.2 Literature index (`docs/petri-bundle/literature/index.html`)

NEW — Next.js static export page. Reads `listing.json` at build time.

Sortable / filterable table:

```
─────────────────────────────────────────────────────
Literature snapshots (43)
Filter:  [All] [cs.AI] [cs.CL] [cs.LG]
Sort:    [retrieved_at ↓] [cited_by ↓]  [title ↑]
─────────────────────────────────────────────────────
arxiv_id   | title                             | retrieved   | cited_by | cat
2502.18864 | Petri: probing alignment dims     | 2026-05-23  | 4        | cs.AI, cs.CL
2412.13371 | Sycophancy in LLM agents          | 2026-05-22  | 5        | cs.CL
...
```

Each row links to a detail page.

### 7.3 Detail page (`docs/petri-bundle/literature/<arxiv_id>.html`)

Per-snapshot view:

```
2502.18864 — Petri: probing alignment dimensions
─────────────────────────────────────────────────
Authors:       ...
Categories:    cs.AI, cs.CL
Published:     2025-02-26
Retrieved:     2026-05-23T15:30:00+00:00
Content hash:  a4f2...b91c (sha256)
Source:        arxiv.org/abs/2502.18864 ↗

Abstract
────────
[abstract text]

Cited by
────────
Mutations (3)
  ├ gen-2 / mut-abc123  "wrapper-sections sycophancy_guardrail rewrite"
  ├ gen-2 / mut-def456  "tool-policy deny-list update"
  └ gen-3 / mut-789xyz  "reflection.json threshold tune"

Seeds (2)
  ├ gen2-014-abc12345  target_dim=sycophancy
  └ gen3-002-def67890  target_dim=harmful_sysprompt
```

### 7.4 Inline reference in audit `.eval` viewer

Existing audit log viewer at `docs/petri-bundle/logs/index.html` — when
a mutation evidence card cites a paper, the card shows an inline link:

```
Mutation mut-abc123
├ kind: prompt_section_rewrite
├ target: wrapper-sections.json::sycophancy_guardrail
├ evidence:
│  ├ 📊 baseline.json (sycophancy 0.42 → 0.58)
│  └ 📄 literature/2502.18864 (Petri: probing alignment dims) ↗
└ rationale: "Paper §3 ..."
```

Implementation: viewer JS reads mutation `evidence` array, for `kind:
"literature_snapshot"` rows fetches `literature/<arxiv_id>.html` and
renders a card with title + link.

## 8. CI / workflow integration

### 8.1 `.github/workflows/pages.yml`

Insert before Next.js build:

```yaml
- name: Build literature listing
  run: |
    uv run python scripts/build_literature_listing.py
```

### 8.2 `scripts/validate_petri_bundle.py`

Extend the existing audit-log validator to also count literature
snapshots:

```python
log.info("OK: %d audit archive(s), %d literature snapshot(s)", logs, lits)
```

## 9. Operator surface — config knobs

`plugins/seed_generation/seed_generation.plugin.toml`:

```toml
[seed_generation.role.literature_review]
default_model = "claude-sonnet-4-6"
allowed_models = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "gpt-5.5",
    "gpt-5.4",
]
role_contract = "plugins/seed_generation/agents/literature_review.md"

# Phase 2 — per-run literature budget. 0 = skip the phase entirely
# (single-run regression guard for cost-sensitive operators). max_papers
# caps cost when arxiv returns more than expected.
max_papers = 9
queries_per_run = 3
```

Operator override (`~/.geode/config.toml`):

```toml
[self_improving_loop.seed_generation.roles.literature_review]
model = "claude-haiku-4-5"   # cheaper for synthesis
source = "claude-cli"
max_papers = 5
```

`max_papers = 0` short-circuits the agent (no fetch, no LLM) → seed-generation
runs without literature evidence, identical to pre-Phase-2 behavior.

## 10. Test surface

```
tests/plugins/seed_generation/
├── test_literature_review.py    ← NEW — agent unit tests
├── test_literature_snapshot.py  ← NEW — snapshot writer + cache
└── test_build_literature_listing.py  ← NEW — build step + cited_by
```

### 10.1 Test cases (target ~25 tests)

**Agent (`test_literature_review.py`)**:
- max_papers = 0 → phase short-circuits, no LLM calls
- max_papers > 0 → query_gen + fetch + analysis + synthesis all fire
- arxiv fetch error → graceful fallthrough, articles_with_reasoning = ""
- Cache-hit path → 0 fetch calls when snapshot exists with matching hash
- Partial failure (3/9 papers fail) → 6 insights flow to synthesis

**Snapshot writer (`test_literature_snapshot.py`)**:
- Schema validation
- content_hash determinism (same abstract → same hash)
- Atomic write (no partial file on crash)
- Path containment (no writes outside `docs/petri-bundle/literature/`)
- arxiv_id pattern validation

**Build step (`test_build_literature_listing.py`)**:
- Empty literature dir → empty listing.json
- N snapshots → listing.json with N rows in canonical order
- cited_by population from mutations.jsonl + seed frontmatter
- Missing mutations.jsonl → cited_by empty but listing builds
- Idempotent re-run → byte-identical output

## 11. Phase 2 vs petri-autoresearch schema realign — interface contract

The petri-autoresearch session is realigning `mutations.jsonl` /
`baseline.json` evidence schema. Phase 2's only dependency on the
outcome is **how mutations.jsonl encodes "this mutation cited paper X"**.

Two scenarios:

| petri-autoresearch outcome | Phase 2 impact |
|---|---|
| Evidence is a typed array with `{kind, arxiv_id}` rows | Build step picks up cited_by automatically — preferred. |
| Evidence stays flat (current shape) — paper refs go elsewhere | Build step adds a fallback path; cited_by may be lazy-built from seed frontmatter only. |

Phase 2 ships with the **typed-array** assumption + a defensive parser
that handles the flat shape too. Once petri-autoresearch lands, the
parser collapses to the typed-array branch only.

This is the **only coupling point** between Phase 2 and the parallel
schema work. Everything else (LiteratureReview agent, snapshot writer,
listing build, UI) is independent.

## 12. Open questions (resolve at PR push)

1. **arxiv API auth** — current `core/tools/arxiv.py` uses anonymous arXiv
   API. Rate limit: ~3 req/sec. Phase 2 budget: max_papers=9 over ~3
   queries = ~12 requests per run. Well under rate limit. No auth surface
   needed.
2. **Should `LiteratureReview` consume Supervisor's `phase_guidance`?**
   — Yes. Supervisor already emits `phase_guidance.generation`; add a
   `phase_guidance.literature_review` slot in `supervisor.md` contract.
   Minor change.
3. **Listing.json size cap** — at 1000 snapshots × ~500 bytes/row = 500KB
   listing.json. Acceptable. If this ever grows: paginate.

## 13. Implementation order (PR-CSP-14)

| Step | Description | Est |
|---|---|---|
| 1 | This plan doc finalised + Socratic Gate check | 0 (done) |
| 2 | `core/tools/literature_snapshot.py` + tool registration | 30min |
| 3 | `plugins/seed_generation/literature_snapshot.py` (writer + cache helpers) | 30min |
| 4 | `LiteratureReview` agent (`literature_review.py` + `.md`) | 1h |
| 5 | Orchestrator integration (`_PHASE_ORDER` + state field + serialize) | 30min |
| 6 | `scripts/build_literature_listing.py` + Pages workflow wiring | 45min |
| 7 | `docs/petri-bundle/literature/index.html` + `[arxiv_id].html` Next.js pages | 1h |
| 8 | Inline reference card in audit log viewer | 30min |
| 9 | Tests (~25) | 1.5h |
| 10 | Codex MCP verify + fix-ups | 45min |
| 11 | PR + CI + merge + release | 30min |

Total: ~7-8 hours. Single session feasible if focused.

## 14. Anti-deception checklist

| Item | Pin |
|---|---|
| `max_papers = 0` byte-equivalent to pre-Phase-2 (no LLM calls, no fetch, no state change) | Test |
| Snapshot writes confined to `docs/petri-bundle/literature/` | Test (path containment) |
| `content_hash` deterministic — same abstract → same hash | Test |
| Build step idempotent — re-run produces byte-identical listing.json | Test |
| Phase 2 doesn't break on absent mutations.jsonl (build step + agent) | Test |
| `articles_with_reasoning` empty string → downstream agents fall through (no NoneType errors) | Test |
| Pages workflow includes build step (grep-provable) | Workflow file diff |
| CHANGELOG verb-claim parity — "snapshot freeze" matches snapshot writer; "cited_by index" matches build step | PR description grep |

## 15. Status

- [x] Plan SoT written (this doc)
- [ ] PR-CSP-14 implementation
- [ ] Codex MCP verify
- [ ] PR + CI + merge
