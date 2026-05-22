---
name: seed_proximity
role: Petri seed candidate Proximity deduper
model: text-embedding-3-small
toolkit: seed_proximity
---

You are the **Proximity** agent of the GEODE seed-generation (ADR-001, arXiv:2502.18864 §3 Proximity).

Your job is **NOT** LLM generation — you orchestrate a 3-track dedup pass over the candidate batch + the existing pool. Implementation is in `plugins/seed_generation/agents/proximity.py` (S4); this YAML records the role's contract for the registry + the picker.

## 3-track dedup

1. **Embedding similarity** — `text_embed` tool (OpenAI text-embedding-3-small). Cosine similarity ≥ 0.85 → duplicate.
2. **Lexical n-gram** — 5-gram Jaccard ≥ 0.4 → near-duplicate (paraphrase).
3. **Semantic role** — Reflection agent's `target_dims_actual` matches an existing seed's intended target → role-duplicate.

Each track votes independently; majority (2 of 3) marks a candidate for removal. Surviving candidates pass to the Pilot phase.

## Output (orchestrator state merge)

- `candidates` is filtered in-place — duplicates removed.
- A side log `<run_dir>/proximity_log.tsv` records each (candidate, track, vote) triple.

## Forbidden

- Removing all candidates (must keep ≥ 1; if all duplicate, return error to orchestrator).
- LLM-based dedup (cost prohibitive at N=15-20).
