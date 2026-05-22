"""Proximity agent — Phase B (dedup) of the seed generation.

Per ADR-001 paper §3 Proximity + ADR-003 — 3-track dedup over the
candidate batch + (optional) existing pool. Majority vote (2 of 3
tracks marking a candidate for removal) drops the candidate.

Tracks:

1. **Embedding similarity** — cosine ≥ ``EMBED_SIMILARITY_THRESHOLD``
   via ``core.tools.text_embed`` against either a sibling candidate or
   a pool member.
2. **Lexical n-gram** — 5-gram Jaccard ≥ ``LEXICAL_JACCARD_THRESHOLD``.
3. **Semantic role** — both candidates share ≥ 1 target dim in their
   Reflection's ``target_dims_actual`` (from S3's state.reflections).

Per ADR-003 the agent's manifest entry has ``kind = "embedding"``, so
the orchestrator (S6.5 picker) does NOT route Proximity through Petri's
adapter table — embeddings come from the `text_embed` tool directly,
with the OpenAI PAYG credential resolved at call time.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity** — `text_embed.embed_texts` stub in tests returns
  vectors aligned 1:1 with input order (matches production contract).
  Test cases include duplicate-by-embedding, duplicate-by-lexical,
  duplicate-by-role, and unanimous-no-duplicate.
- **P7 Caller-Callee Contract** — Proximity consumes
  ``state.candidates`` (Generator output schema with ``path``) +
  ``state.reflections`` (Critic output schema with
  ``target_dims_actual``). Both are explicitly documented.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# CSP-6 (2026-05-22) — the Jaccard primitives moved to
# ``core/text/similarity.py`` so the Evolver's anti-convergence guard
# can reuse them without reaching into a sibling plugin. The module-
# level ``_shingles`` / ``_jaccard`` symbols below stay as thin
# compatibility shims so this file's existing call sites (and any
# external importer that referenced the private names) keep working.
from core.text.similarity import jaccard_similarity as _jaccard
from core.text.similarity import shingles as _shingles_impl

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.orchestrator import PipelineState

log = logging.getLogger(__name__)

__all__ = [
    "EMBED_SIMILARITY_THRESHOLD",
    "GRAPH_WEIGHT_EMBED",
    "GRAPH_WEIGHT_LEXICAL",
    "LEXICAL_JACCARD_THRESHOLD",
    "PARTIAL_SURVIVE_FLOOR",
    "Proximity",
]


EMBED_SIMILARITY_THRESHOLD = 0.85
LEXICAL_JACCARD_THRESHOLD = 0.40
NGRAM_SIZE = 5
MAJORITY_VOTE_THRESHOLD = 2  # of 3 tracks

# PR-Π2 — partial-survive floor. When the 2-of-3 dedup vote would drop
# every candidate (Generator emitted a fully homogeneous batch), the
# phase keeps the K most-diverse candidates (lowest average proximity
# in the graph) instead of aborting the pipeline. Co-Scientist §3.3.4
# guarantees spread automatically because its proximity graph is the
# Ranker's input; GEODE's pre-Π2 behaviour was a hard abort, which let
# a single bad Generator batch kill the whole run. K=3 is enough for
# the Ranker (S6) to schedule ≥ C(3, 2) = 3 matches.
PARTIAL_SURVIVE_FLOOR = 3

# PR-Π1 — proximity graph composite-score weights. The graph emitted to
# ``state.proximity_graph`` is the weighted sum of the embedding cosine
# (already in [0, 1] when both vectors are normalised) and the lexical
# 5-gram Jaccard (in [0, 1] by construction). Role overlap is a binary
# signal (used for the dedup vote but not the graph score) so it stays
# out of the weight. Weights sum to 1.0 so the graph value is itself
# in [0, 1] — 1.0 = identical, 0.0 = maximally distant. Co-Scientist
# §3.3.4 "proximity graph for generated hypotheses" downstream-consumed
# by the Ranker (PR-Π1 §B).
GRAPH_WEIGHT_EMBED: float = 0.6
GRAPH_WEIGHT_LEXICAL: float = 0.4


class Proximity(BaseSeedAgent):
    """3-track dedup over candidate batch + optional pool.

    The agent does NOT spawn sub-agents — Proximity is a pure-Python
    + tool-call phase. Embedding cost is the only LLM-adjacent expense;
    lexical and role tracks are local.
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        source: str = "api_key",
        manifest_role: dict[str, object] | None = None,
        embed_client: Any | None = None,
    ) -> None:
        super().__init__(
            role="proximity",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        # Optional pre-built OpenAI client for test injection.
        self._embed_client = embed_client

    def execute(self, state: PipelineState) -> SeedAgentResult:
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message="Proximity requires state.candidates to be non-empty",
            )

        # 1. Load candidate texts (read from disk paths).
        candidate_texts = self._load_candidate_texts(state)
        if not candidate_texts:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="io",
                error_message="all candidate files unreadable",
            )

        # 2. Load optional pool texts.
        pool_texts = self._load_pool_texts(state)

        # 3. Compute per-track duplicate votes + pair-wise similarity scores.
        # PR-Π3 — the embedding track conditions on ``state.target_dim`` so
        # the same candidate text against two different research goals
        # produces different vectors. Co-Scientist §3.3.4 calls this
        # "calculates similarity ... taking into account the specific
        # research goal". Lexical / role tracks stay goal-agnostic — role
        # already encodes the dim, and lexical 5-gram similarity is
        # surface-form only.
        embed_dupes, embed_scores = self._embedding_track(
            candidate_texts, pool_texts, target_dim=state.target_dim
        )
        lexical_dupes, lexical_scores = self._lexical_track(candidate_texts, pool_texts)
        role_dupes = self._role_track(state)

        # 3b. PR-Π1 — emit the proximity graph into state. Sparse over
        # candidate-candidate pairs only (pool members aren't tracked
        # in the graph since the Ranker only schedules matches between
        # surviving candidates). Pairs with neither track signal default
        # to 0.0 (maximally distant) when consumers query missing keys.
        graph: dict[tuple[str, str], float] = {}
        for pair in set(embed_scores) | set(lexical_scores):
            graph[pair] = GRAPH_WEIGHT_EMBED * embed_scores.get(
                pair, 0.0
            ) + GRAPH_WEIGHT_LEXICAL * lexical_scores.get(pair, 0.0)
        state.proximity_graph.update(graph)

        # 4. Majority vote.
        removed: list[str] = []
        survivors: list[dict[str, Any]] = []
        for cand in state.candidates:
            cid = cand["id"]
            votes = sum(1 for marks in (embed_dupes, lexical_dupes, role_dupes) if cid in marks)
            if votes >= MAJORITY_VOTE_THRESHOLD:
                removed.append(cid)
            else:
                survivors.append(cand)

        if not survivors:
            # PR-Π2 — partial-survive fallback (was: hard abort). The
            # Generator emitted a fully homogeneous batch; rather than
            # killing the whole pipeline, keep the ``PARTIAL_SURVIVE_FLOOR``
            # most-diverse candidates (lowest average proximity in the
            # graph) so the Ranker / Evolution can still observe at least
            # one round. Downstream phases see a smaller-than-requested
            # batch but the run completes; the operator gets a WARN log
            # + a structured ``proximity_all_duplicates_fallback`` journal
            # event so the degraded path is never silent.
            survivors = self._partial_survive(state.candidates, graph)
            log.warning(
                "seed-generation proximity: all-duplicates fallback — "
                "partial-survive with %d most-diverse candidates "
                "(was: hard abort). embed=%d lexical=%d role=%d",
                len(survivors),
                len(embed_dupes),
                len(lexical_dupes),
                len(role_dupes),
            )
            self._emit_fallback_event(
                original_count=len(state.candidates),
                survivor_count=len(survivors),
                embed_dupes=len(embed_dupes),
                lexical_dupes=len(lexical_dupes),
                role_dupes=len(role_dupes),
            )

        if removed:
            log.info(
                "seed-generation proximity: dropped %d of %d candidates "
                "(embed=%d lexical=%d role=%d)",
                len(removed),
                len(state.candidates),
                len(embed_dupes),
                len(lexical_dupes),
                len(role_dupes),
            )

        # The orchestrator's state.merge uses extend() for list keys, so
        # returning a NEW candidates list here would duplicate. Mutate
        # state directly + return a marker dict the orchestrator merges
        # without re-extending.
        state.candidates = survivors
        return SeedAgentResult(
            role=self.role,
            output={
                # Empty list — survivors are already mutated in-place above.
                # Returning a non-empty list would re-extend state.candidates.
            },
        )

    # ────────────────────────────────────────────────────────────────────
    # PR-Π2 — partial-survive fallback
    # ────────────────────────────────────────────────────────────────────

    def _partial_survive(
        self,
        candidates: list[dict[str, Any]],
        graph: dict[tuple[str, str], float],
    ) -> list[dict[str, Any]]:
        """Return the K most-diverse candidates from ``candidates``.

        Diversity score per candidate = mean of its proximity-graph
        weights (lower = more diverse). Candidates without any graph
        entry default to 0.0 (treated as maximally distant, sorted to
        the front). Ties broken by candidate id (lexicographic) for
        deterministic survival under the same proximity profile.

        K = :data:`PARTIAL_SURVIVE_FLOOR` (3 — enough for the Ranker to
        schedule ≥ 3 matches). When ``len(candidates) <= K`` every
        candidate survives (no point dropping when the batch is already
        smaller than the floor).
        """
        cids = [c["id"] for c in candidates]
        if len(cids) <= PARTIAL_SURVIVE_FLOOR:
            return list(candidates)

        sums = dict.fromkeys(cids, 0.0)
        counts = dict.fromkeys(cids, 0)
        for (a, b), score in graph.items():
            for cid in (a, b):
                if cid in sums:
                    sums[cid] += score
                    counts[cid] += 1
        avg_prox = {cid: (sums[cid] / counts[cid]) if counts[cid] > 0 else 0.0 for cid in cids}
        ranked = sorted(cids, key=lambda cid: (avg_prox[cid], cid))
        keep = set(ranked[:PARTIAL_SURVIVE_FLOOR])
        return [c for c in candidates if c["id"] in keep]

    def _emit_fallback_event(
        self,
        *,
        original_count: int,
        survivor_count: int,
        embed_dupes: int,
        lexical_dupes: int,
        role_dupes: int,
    ) -> None:
        """Emit a ``proximity_all_duplicates_fallback`` warn event when active.

        No-op outside an :func:`session_journal_scope`. Failure to emit
        is swallowed (observability must never break the run it
        observes) — the WARN log line above the call site is the
        backup signal.
        """
        try:
            from core.observability import current_session_journal

            journal = current_session_journal()
            if journal is None:
                return
            journal.append(
                "proximity_all_duplicates_fallback",
                level="warn",
                payload={
                    "original_count": original_count,
                    "survivor_count": survivor_count,
                    "embed_dupes": embed_dupes,
                    "lexical_dupes": lexical_dupes,
                    "role_dupes": role_dupes,
                },
            )
        except Exception:  # pragma: no cover - defensive
            log.debug("proximity: fallback journal emit failed", exc_info=True)

    # ────────────────────────────────────────────────────────────────────
    # Track 1 — embedding similarity
    # ────────────────────────────────────────────────────────────────────

    def _embedding_track(
        self,
        candidate_texts: dict[str, str],
        pool_texts: list[str],
        *,
        target_dim: str = "",
    ) -> tuple[set[str], dict[tuple[str, str], float]]:
        """Mark candidates whose embedding cosine vs sibling/pool ≥ 0.85.

        Returns ``(dupes, scores)`` where ``scores`` is the candidate-
        candidate cosine map (sorted ``(a, b)`` key, value in ``[0, 1]``).
        ``scores`` is populated for every candidate-candidate pair the
        embedding call succeeded for — used by the caller to build
        :attr:`PipelineState.proximity_graph`. Pool-comparison cosines
        are not in the graph since the Ranker only ever schedules
        candidate-vs-candidate matches.

        PR-Π3 — ``target_dim`` is prepended as ``[goal: <dim>] \\n`` to
        every embedding input when non-empty. Co-Scientist §3.3.4
        specifies similarity should "take into account the specific
        research goal"; the prefix conditions the embedding output so
        the same candidate text against two different research goals
        produces different vectors. When ``target_dim`` is empty (legacy
        call sites or tests that don't populate ``state.target_dim``)
        the prefix is dropped and behavior is byte-identical to the
        pre-Π3 path.

        On embedding-tool failure: both return values are empty (caller
        falls back to the 2-track lexical + role dedup vote).
        """
        from core.tools.text_embed import cosine_similarity, embed_texts

        cids = list(candidate_texts)
        cand_inputs = [_goal_condition(candidate_texts[c], target_dim) for c in cids]
        pool_inputs = [_goal_condition(t, target_dim) for t in pool_texts]
        all_texts = cand_inputs + pool_inputs
        try:
            vectors = embed_texts(all_texts, client=self._embed_client)
        except Exception:
            log.warning(
                "seed-generation proximity: embedding track failed (continuing "
                "with 2-track fallback)",
                exc_info=True,
            )
            return set(), {}
        cand_vectors = vectors[: len(cids)]
        pool_vectors = vectors[len(cids) :]
        dupes: set[str] = set()
        scores: dict[tuple[str, str], float] = {}
        # Pairwise within candidates.
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                cos = cosine_similarity(cand_vectors[i], cand_vectors[j])
                scores[_pair_key(cids[i], cids[j])] = cos
                if cos >= EMBED_SIMILARITY_THRESHOLD:
                    # Mark the LATER candidate as duplicate (keep first).
                    dupes.add(cids[j])
        # Each candidate vs every pool member.
        for i, ci in enumerate(cids):
            for pv in pool_vectors:
                if cosine_similarity(cand_vectors[i], pv) >= EMBED_SIMILARITY_THRESHOLD:
                    dupes.add(ci)
                    break  # one pool match is enough
        return dupes, scores

    # ────────────────────────────────────────────────────────────────────
    # Track 2 — lexical 5-gram Jaccard
    # ────────────────────────────────────────────────────────────────────

    def _lexical_track(
        self,
        candidate_texts: dict[str, str],
        pool_texts: list[str],
    ) -> tuple[set[str], dict[tuple[str, str], float]]:
        """Mark candidates with 5-gram Jaccard ≥ 0.40 against sibling/pool.

        Returns ``(dupes, scores)`` — same contract as
        :meth:`_embedding_track` but for the lexical track. ``scores``
        covers every candidate-candidate pair (Jaccard never fails like
        an embedding API does, so the map is dense).
        """
        cids = list(candidate_texts)
        cand_shingles = {c: _shingles(candidate_texts[c]) for c in cids}
        pool_shingles = [_shingles(t) for t in pool_texts]
        dupes: set[str] = set()
        scores: dict[tuple[str, str], float] = {}
        for i, ci in enumerate(cids):
            for j in range(i + 1, len(cids)):
                jac = _jaccard(cand_shingles[ci], cand_shingles[cids[j]])
                scores[_pair_key(ci, cids[j])] = jac
                if jac >= LEXICAL_JACCARD_THRESHOLD:
                    dupes.add(cids[j])
        for ci in cids:
            for ps in pool_shingles:
                if _jaccard(cand_shingles[ci], ps) >= LEXICAL_JACCARD_THRESHOLD:
                    dupes.add(ci)
                    break
        return dupes, scores

    # ────────────────────────────────────────────────────────────────────
    # Track 3 — semantic role (Reflection's target_dims_actual)
    # ────────────────────────────────────────────────────────────────────

    def _role_track(self, state: PipelineState) -> set[str]:
        """Mark candidates whose target_dims_actual overlap with another's."""
        if not state.reflections:
            return set()  # no critic output → cannot vote
        # Build dim_set for each candidate from its reflection.
        cand_dims: dict[str, set[str]] = {}
        for cand in state.candidates:
            cid = cand["id"]
            critique = state.reflections.get(cid, {})
            dims_raw = critique.get("target_dims_actual") or []
            cand_dims[cid] = set(dims_raw) if isinstance(dims_raw, list) else set()
        cids = list(cand_dims)
        dupes: set[str] = set()
        for i, ci in enumerate(cids):
            if not cand_dims[ci]:
                continue
            for j in range(i + 1, len(cids)):
                cj = cids[j]
                if cand_dims[ci] & cand_dims[cj]:
                    # Mark the LATER one (matches embedding track semantics).
                    dupes.add(cj)
        return dupes

    # ────────────────────────────────────────────────────────────────────
    # I/O helpers
    # ────────────────────────────────────────────────────────────────────

    def _load_candidate_texts(self, state: PipelineState) -> dict[str, str]:
        """Read each candidate's file body into ``{candidate_id: text}``.

        Missing/unreadable files are skipped with WARNING; the affected
        candidates lose the embedding + lexical tracks (semantic-role
        track may still apply if Reflection ran).
        """
        out: dict[str, str] = {}
        for cand in state.candidates:
            cid = cand["id"]
            path = cand.get("path")
            if not path:
                log.warning("proximity: candidate %r has no path; skipped", cid)
                continue
            try:
                out[cid] = Path(path).read_text(encoding="utf-8")
            except OSError as exc:
                log.warning("proximity: candidate %r unreadable (%s)", cid, exc)
        return out

    def _load_pool_texts(self, state: PipelineState) -> list[str]:
        """Read every `.md` file under ``state.pool_path_in`` (if set).

        Returns empty list when no pool is configured — the dedup is then
        candidate-batch-only (no cross-pool deduplication).
        """
        if state.pool_path_in is None:
            return []
        pool_dir = Path(state.pool_path_in)
        if not pool_dir.is_dir():
            log.warning(
                "proximity: pool_path_in %r is not a directory; skipped",
                str(pool_dir),
            )
            return []
        texts: list[str] = []
        for md in sorted(pool_dir.glob("*.md")):
            try:
                texts.append(md.read_text(encoding="utf-8"))
            except OSError as exc:
                log.warning("proximity: pool file %s unreadable (%s)", md, exc)
        return texts


# ────────────────────────────────────────────────────────────────────────
# Shared helpers — module-level so tests can import directly
# ────────────────────────────────────────────────────────────────────────


def _goal_condition(text: str, target_dim: str) -> str:
    """Prepend a research-goal prefix when ``target_dim`` is non-empty.

    PR-Π3 — Co-Scientist §3.3.4 requires similarity to be "taking into
    account the specific research goal". For GEODE the goal is the
    Petri target dim that the audit is being engineered against
    (``state.target_dim``); the prefix shifts the embedding output so
    the same candidate body against two different dims doesn't collapse
    into the same vector. Empty ``target_dim`` returns the text
    unchanged — every pre-Π3 call site keeps byte-identical behavior.
    """
    if not target_dim:
        return text
    return f"[goal: {target_dim}]\n{text}"


def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Sort ``(a, b)`` lexicographically — the proximity graph's canonical key.

    The Ranker / Evolution consumers query ``state.proximity_graph`` by
    ``_pair_key(cid_a, cid_b)``; storing both orderings would double the
    memory + risk drift, so we standardise on ``a < b``.
    """
    return (a, b) if a < b else (b, a)


def _shingles(text: str, n: int = NGRAM_SIZE) -> set[str]:
    """Compatibility shim — defaults to the proximity-module ``NGRAM_SIZE``.

    CSP-6 (2026-05-22) — wraps :func:`core.text.similarity.shingles`
    with the proximity module's default ``n`` so legacy call sites
    that don't pass ``n=`` keep their pre-CSP-6 behaviour.
    """
    return _shingles_impl(text, n=n)
