"""Seed-debate turn recorder — Loop 2 (debate-turn) of the seed-generation 3-loop port.

Background
==========

open-coscientist (`nodes/generation/debate.py:71-147`) runs an
**N-turn debate** inside each hypothesis-generation call: debater A
→ debater B → debater A → ... until N turns elapse, then the LLM
synthesizes the final hypothesis. Each turn is a separate LLM call
that sees the cumulative transcript.

GEODE's port (`plugins/seed_generation/agents/generator.py`) had no
analogue — each candidate was a single-shot LLM call. PR-CSP-13
adds this debate cycle via **sub-agent internal multi-turn**: each
candidate sub-agent runs an N-turn debate inside its AgenticLoop's
tool_use cycle. This tool is the turn recorder + dispatcher signal:
the LLM calls it once per turn, the tool persists the turn to a
sidecar JSONL file and returns either "continue" (more turns
remaining) or "synthesize" (turn budget exhausted, write the final
seed now).

Why a tool (not a prompt-only instruction)
------------------------------------------

A prompt-only "do N turns then write the seed" would have no
guarantee of N actual turns — the LLM could shortcut to synthesis
on turn 1. The tool's `next_action` return value is the dispatcher
that makes the turn count load-bearing: synthesis is blocked
until the tool returns `"synthesize"`.

Sidecar layout
==============

For each candidate the tool writes JSONL turns to
``<output_path:.md → .debate.jsonl>`` (so the sidecar lives next to
the seed file the sub-agent ultimately writes). One line per turn::

    {"turn": 1, "speaker": "A", "content": "...", "ts": "2026-05-23T..."}
    {"turn": 2, "speaker": "B", "content": "...", "ts": "..."}
    ...

The Generator agent reads the sidecar after the sub-agent returns
and merges it into ``PipelineState.debate_transcripts[candidate_id]``
so downstream phases (meta_reviewer) can inspect the debate.

Bounds + safety
===============

- ``turn`` must be in ``[1, max_turns]``. Out-of-range → error result
  so the LLM cannot silently skip turns.
- **Sequential turn enforcement** (Codex MCP HIGH fix-up): each call
  reads the sidecar first and refuses ``turn != prior_count + 1``.
  Otherwise the LLM could call once with ``turn=max_turns`` and
  receive ``next_action="synthesize"`` immediately, collapsing the
  N-turn budget into a single round.
- ``max_turns`` must be in ``[2, 6]``. Lower bound forces the loop
  to mean something; upper bound caps cost per candidate.
- Sidecar path must end ``.debate.jsonl``, live in a ``candidates/``
  directory, AND match the ``output_path`` argument (transformed
  ``.md`` → ``.debate.jsonl``) — refuses arbitrary disk writes by
  tying the sidecar to a specific candidate file path the
  orchestrator chose. The LLM cannot redirect via path traversal:
  resolved + symlink-safe path must remain rooted under the
  GEODE runtime dir (``~/.geode`` / ``GEODE_HOME``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["SeedDebateTurnTool"]


_MIN_TURNS = 2
_MAX_TURNS = 6
_SIDECAR_SUFFIX = ".debate.jsonl"


class SeedDebateTurnTool:
    """Record one debate turn + signal continue/synthesize."""

    @property
    def name(self) -> str:
        return "seed_debate_turn"

    @property
    def description(self) -> str:
        return (
            "Record one turn of the multi-turn debate while drafting a Petri "
            "audit seed. Call this once per turn with the speaker label and "
            "content. The tool persists the turn to a sidecar JSONL file next "
            "to the seed candidate file and returns next_action='continue' "
            "until max_turns is reached, then 'synthesize' — at which point "
            "stop debating and write the final seed body via write_file. "
            "Required when max_turns >= 2 (the seed_generator system prompt "
            "tells you the budget); ignored when max_turns == 0 (single-shot)."
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Required async entry — sync body via to_thread (matches the
        seed_pool_search pattern; debate-turn does only local JSONL append)."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        try:
            turn = int(kwargs["turn"])
            speaker = str(kwargs["speaker"]).strip()
            content = str(kwargs["content"]).strip()
            sidecar_path = str(kwargs["sidecar_path"]).strip()
            output_path = str(kwargs["output_path"]).strip()
            max_turns = int(kwargs["max_turns"])
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "result": {
                    "ok": False,
                    "error": f"missing or malformed arg: {exc}",
                    "next_action": "abort",
                }
            }

        if max_turns < _MIN_TURNS or max_turns > _MAX_TURNS:
            return {
                "result": {
                    "ok": False,
                    "error": (
                        f"max_turns={max_turns} out of bounds; "
                        f"must be in [{_MIN_TURNS}, {_MAX_TURNS}]"
                    ),
                    "next_action": "abort",
                }
            }
        if turn < 1 or turn > max_turns:
            return {
                "result": {
                    "ok": False,
                    "error": (f"turn={turn} out of bounds; must be in [1, max_turns={max_turns}]"),
                    "next_action": "abort",
                }
            }
        if not speaker:
            return {
                "result": {
                    "ok": False,
                    "error": "speaker must be non-empty (e.g. 'A', 'B', 'critic')",
                    "next_action": "abort",
                }
            }
        if not content:
            return {
                "result": {
                    "ok": False,
                    "error": "content must be non-empty",
                    "next_action": "abort",
                }
            }
        if not output_path.endswith(".md"):
            return {
                "result": {
                    "ok": False,
                    "error": (
                        f"output_path must end with '.md' (the candidate seed file); "
                        f"got {output_path!r}"
                    ),
                    "next_action": "abort",
                }
            }
        expected_sidecar = output_path[: -len(".md")] + _SIDECAR_SUFFIX
        if sidecar_path != expected_sidecar:
            return {
                "result": {
                    "ok": False,
                    "error": (
                        "sidecar_path must be the candidate output_path with "
                        "'.md' replaced by '.debate.jsonl' (Codex MCP HIGH fix); "
                        f"expected {expected_sidecar!r}, got {sidecar_path!r}"
                    ),
                    "next_action": "abort",
                }
            }

        sidecar = Path(sidecar_path)
        if not sidecar.name.endswith(_SIDECAR_SUFFIX):
            return {
                "result": {
                    "ok": False,
                    "error": (
                        f"sidecar_path must end with '{_SIDECAR_SUFFIX}'; got {sidecar.name!r}"
                    ),
                    "next_action": "abort",
                }
            }
        if sidecar.parent.name != "candidates":
            return {
                "result": {
                    "ok": False,
                    "error": (
                        "sidecar_path parent must be a 'candidates/' directory "
                        "(the seed-generation run layout); got "
                        f"{sidecar.parent.name!r}"
                    ),
                    "next_action": "abort",
                }
            }
        # Containment: resolved sidecar must remain rooted under the
        # GEODE runtime dir so an LLM-injected ``..`` path can't escape
        # into arbitrary disk. ``Path.resolve(strict=False)`` follows
        # symlinks where present + canonicalises ``..``.
        try:
            from core.paths import GEODE_HOME

            resolved = sidecar.resolve(strict=False)
            geode_root = GEODE_HOME.resolve(strict=False)
            if geode_root not in resolved.parents and resolved != geode_root:
                return {
                    "result": {
                        "ok": False,
                        "error": (
                            f"sidecar_path {sidecar_path!r} resolves outside the GEODE "
                            f"runtime root ({geode_root}); refusing write"
                        ),
                        "next_action": "abort",
                    }
                }
        except ImportError:  # pragma: no cover — defensive fallback
            pass

        # Sequential turn enforcement (Codex MCP HIGH fix): the LLM
        # must not skip turns. The N-th call requires exactly N-1
        # prior rows on disk. This makes the budget load-bearing
        # against the tool_executor batching multiple tool_use blocks
        # in one model response.
        prior_count = 0
        if sidecar.exists():
            try:
                prior_count = sum(
                    1 for line in sidecar.read_text(encoding="utf-8").splitlines() if line.strip()
                )
            except OSError as exc:
                log.warning(
                    "seed_debate_turn: failed to read existing sidecar %s: %s", sidecar, exc
                )
        if turn != prior_count + 1:
            return {
                "result": {
                    "ok": False,
                    "error": (
                        f"turn={turn} would skip the sequential debate budget; "
                        f"prior_count={prior_count}, expected turn={prior_count + 1}"
                    ),
                    "next_action": "abort",
                }
            }

        try:
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "turn": turn,
                "speaker": speaker,
                "content": content,
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            with sidecar.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("seed_debate_turn: failed to append turn %d to %s: %s", turn, sidecar, exc)
            return {
                "result": {
                    "ok": False,
                    "error": f"failed to write sidecar: {exc}",
                    "next_action": "abort",
                }
            }

        next_action = "synthesize" if turn >= max_turns else "continue"
        return {
            "result": {
                "ok": True,
                "turn": turn,
                "max_turns": max_turns,
                "sidecar_path": str(sidecar),
                "next_action": next_action,
                "note": (
                    "Continue with the next debate turn."
                    if next_action == "continue"
                    else (
                        "Turn budget exhausted. Synthesize the final seed and "
                        "write it via write_file to the candidate file path."
                    )
                ),
            }
        }
