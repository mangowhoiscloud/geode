# Seed-generation 3-loop port — 2026-05-23

## Context

open-coscientist (paper port source) has **3 nested loops** in hypothesis-generation pipeline; GEODE port currently implements only **Loop 1**.

| Loop | Upstream location | GEODE status |
|---|---|---|
| 1 — Outer iteration (`meta_review→evolve→review→ranking→proximity`) | `generator.py:172-223` LangGraph cycle | ✅ Implemented (`orchestrator.py` `_PHASE_ORDER` + `_ITERATION_PHASE_ORDER`) |
| 2 — Debate-turn (intra-generation N-turn debate) | `nodes/generation/debate.py:71-147` | ❌ Missing — single-shot generator |
| 3 — Paper-analysis (intra-literature_review per-paper) | `nodes/literature_review.py:840-873` | ❌ Missing — no literature_review node at all |

## Phase 1 — Loop 2 (debate-turn) port [this PR]

### Architecture decision

**Sub-agent internal multi-turn** via AgenticLoop tool_use cycle. Each candidate sub-agent runs an N-turn debate by repeatedly calling a new `seed_debate_turn` tool; after N turns the tool returns `synthesize` signal and the sub-agent emits its final seed file.

Why this over Generator-class direct calls:
- Keeps existing N-way sub-agent fan-out (`SubAgentManager.adelegate`) unchanged
- AgenticLoop's tool_use cycle is the natural multi-turn driver (no new orchestrator state machine)
- Debate transcript persisted as sidecar file (`<run_dir>/candidates/<id>.debate.jsonl`) — matches the candidate file layout

### Changes

| File | Change |
|---|---|
| `core/tools/seed_debate.py` | NEW — `SeedDebateTurnTool` class. Appends turn to sidecar JSONL, returns `{"next_action": "continue"|"synthesize", "turn": N, "max_turns": M}`. |
| `core/tools/definitions.json` | NEW tool definition for `seed_debate_turn` (turn, speaker, content, candidate_id, max_turns). |
| `core/cli/tool_handlers/delegated.py` | Register `seed_debate_turn` in `_DELEGATED_TOOLS`. |
| `core/tools/toolkits.toml` | Add `seed_debate_turn` to `[toolkits.seed_generation].tools`. |
| `plugins/seed_generation/agents/generator.md` | NEW "Debate protocol" section conditional on `max_turns >= 2` instruction. JSON schema documents the debate sidecar shape. |
| `plugins/seed_generation/agents/generator.py` | `Generator._build_description` injects `max_turns` into the SubTask description so the LLM knows the turn budget. |
| `plugins/seed_generation/orchestrator.py` | `PipelineState.debate_transcripts: dict[candidate_id, list[dict]]` field. Generator reads sidecars after sub-agents return + merges into state. |
| `plugins/seed_generation/seed_generation.plugin.toml` | Optional `[seed_generation.roles.generator].num_turns: int = 0` (0 = no debate / faithful single-shot; ≥2 = active). |
| `plugins/seed_generation/manifest.py` | `SeedRoleSpec.num_turns: int = 0` + validator (must be 0 or in [2..6]). |
| `core/config/self_improving_loop.py` | `SeedGenerationConfig.roles.generator.num_turns` slot for operator override. |
| `tests/plugins/seed_generation/test_debate_loop.py` | NEW — num_turns=0 path (existing single-shot preserved), num_turns=2 path (2 tool calls + synthesis), sidecar shape, state merge. |

### Socratic Gate

| # | Question | Answer |
|---|---|---|
| Q1 | Does it already exist in code? | NO. `grep -rn "debate_transcript\|num_turns\|seed_debate_turn"` returns zero. |
| Q2 | What breaks if we don't? | single-shot generator exposes LLM first-pass bias to downstream phases. Anti-convergence Jaccard (CSP-6) only compares post-hoc — no sampling-time diversity force. |
| Q3 | How do we measure effect? | (a) Proximity dedup ratio (more debate → fewer dups expected), (b) Jaccard distribution shift across batch, (c) dim-coverage breadth in meta_review report. |
| Q4 | Simplest impl? | Sub-agent internal multi-turn via tool_use (~450 LOC). Reuses AgenticLoop. |
| Q5 | 3+ frontier systems? | open-coscientist (debate.py), Claude Code (sub-agent multi-turn), AlphaEval (multi-judge debate), inspect_petri (auditor↔target↔judge multi-turn). |

### Anti-deception checklist

- `num_turns=0` MUST preserve identical single-shot behavior — pin via test that grep-confirms zero `seed_debate_turn` invocations
- `num_turns>=2` MUST persist exactly N+1 turns (N debate + 1 synthesis) in sidecar — pin via assertion on sidecar line count
- Tool MUST refuse turn > max_turns (defensive bounds check + test)
- Sidecar file path MUST be `git check-ignore`-clean (under `<run_dir>` which is `~/.geode/...` — outside repo, NOT a git ledger concern)
- Debate transcript MUST flow to `meta_reviewer` agent as input (read/write parity) — verify via `state.debate_transcripts` access in meta_reviewer

### Verification plan

1. Local gates — ruff / mypy / pytest focused slice
2. Codex MCP `mcp__codex__codex` review on the diff for: tool boundary safety, sidecar IO race, schema correctness, anti-convergence value claim
3. Full pytest suite (`-m "not live"`)
4. CLI smoke — `geode audit-seeds generate --dry-run` (without env keys triggers cred error which is fine for plan validation)

## Phase 2 — Loop 3 (literature paper-analysis) [next session]

Decision locked: **Option 2 + snapshot freeze** — external paper fetch via MCP (PubMed/arXiv) + freeze results in `docs/literature-snapshots/<paper_id>-<retrieved_at>.json` (git-tracked) so audit replay remains reproducible.

Outline (will be expanded in next session):
- NEW `LiteratureReview` agent in `plugins/seed_generation/agents/literature_review.py`
- 4-phase: query_gen → paper_fetch → per_paper_analysis → synthesis (per upstream `literature_review.py`)
- Snapshot writer to `docs/literature-snapshots/`
- `mutations.jsonl` evidence schema extension: `evidence: [{kind: "external_paper_snapshot", path: "docs/literature-snapshots/<id>.json", content_hash}]`
- `baseline.json` schema migration (literature evidence card)
- Orchestrator phase: literature_review insert before generator in `_PHASE_ORDER`
- ~750 LOC

Open questions for Phase 2:
- MCP server choice (pubmed-mcp / arxiv-mcp / generic web fetch)
- Frequency — every outer iteration vs only iteration 0
- Snapshot retention policy (keep all forever vs prune by gen tag)

## Status

- [x] Plan written
- [ ] Phase 1 implementation
- [ ] Phase 1 verification (local + Codex MCP)
- [ ] Phase 1 PR + CI + merge
- [ ] Phase 2 (next session)
