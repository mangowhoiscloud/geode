# Experimental — opt-in modules outside the production scaffold

This directory holds working code that is **not wired into the production
runtime**. Modules here pass their own tests in isolation but no
production code (under `core/`) imports from them. They exist as
parking-lot prototypes for features whose product fit hasn't been
validated yet.

> **Default-excluded from quality gates.** `pytest` collects only `tests/`
> per `pyproject.toml:testpaths`; `ruff` lints only `["core", "tests"]`
> per `[tool.ruff] src`; `mypy` runs against `core/` paths supplied on
> the command line. So changes here do **not** block CI, and **do not
> count toward the project test count metric** in `CLAUDE.md`.

## How to opt in

```bash
# Run the experimental tests explicitly
uv run pytest experimental/tests/ -v

# Lint the experimental code (manual)
uv run ruff check experimental/
```

To wire a module into production, move it into `core/` (or wherever it
belongs in the 4-layer stack), update its imports, register any DI
hooks in `core/lifecycle/bootstrap.py`, add an integration test under
`tests/`, and run the full quality gates.

## Current contents (v0.63.0)

### `experimental/memory/` — Semantic retrieval stack
4 modules, ~1.9K lines, 36 tests passing.

| Module | Purpose | Key API |
|--------|---------|---------|
| `embeddings.py` | Pluggable text embedding (OpenAI / local sentence-transformers / no-op fallback) with content-hash caching. | `EmbeddingEngine.embed(text)` |
| `vector_store.py` | Simple cosine-similarity vector store with on-disk persistence. | `SimpleVectorStore.search(query)` |
| `rag_router.py` | Heuristic + vector hybrid query router for RAG retrieval. | `RAGRouter.retrieve(query)` |
| `raptor.py` | RAPTOR (Sarthi et al., ICLR 2024) — recursive abstractive tree built over the vector store; search returns the right abstraction level. | `RAPTORIndex.search(query)` |

**Why deferred (not integrated)**: 0/3 frontier reference codebases
(Hermes, OpenClaw, Claude Code) implement a comparable stack — the
design is academic-source-driven (RAPTOR paper) rather than 3-system
consensus. Integration would need a session-memory consumer
(`AgenticLoop`?) to call `RAPTORIndex.search()` on every prompt, which
is a non-trivial product decision (latency, cost, eviction policy).

### `experimental/orchestration/` — Progressive context compression
1 module, ~320 lines, 14 tests passing.

| Module | Purpose | Key API |
|--------|---------|---------|
| `progressive_compression.py` | 3-zone graduated compression (Zone A verbatim 20% / Zone B summarised 60% / Zone C archived 20%). Cites OpenHands 2025.11 as inspiration. | `ProgressiveCompressor.compress(messages)` |

**Why deferred (not integrated)**: Overlaps in scope with the v0.40.0
200K token guard already in `core/`. Two compression systems would need
a clear responsibility boundary before either lands in production. The
OpenHands citation is also outside the 3-codebase priority order.

## Promotion criteria

Move a module from `experimental/` to `core/` when **all** are true:

1. A concrete production caller exists (not a hypothetical "we might want this").
2. The product trade-off (latency / cost / accuracy / UX impact) is documented.
3. At least 1 of the 3 frontier reference systems (Hermes > OpenClaw > Claude Code) demonstrates the same pattern, OR there is a strong user-direction reason to deviate.
4. An integration test under `tests/` exercises the production call path (not just the module in isolation).

## Removal criteria

Move a module from `experimental/` to deletion when:

- 6+ months elapsed with no production caller and no user pull
- The product question it was prototyping has been resolved another way
- A simpler approach in `core/` covers the same need
