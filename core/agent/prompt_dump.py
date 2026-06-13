"""Assembled-system-prompt dump — the P0 of the prompt-refactor sprint.

PR-PROMPT-DUMP (2026-06-13). The prompt the model actually receives is a
7-layer composition (wrapper/generic prefix + math + style guide +
heuristics + persona, then model card + model guidance + platform hint +
date + G2/G3/G4 memory + user context, then the agentic suffix) that had
never been inspectable as ONE artifact — every prior audit looked at the
layers in isolation. This module reproduces the AgenticLoop's final
system prompt without a loop instance and reports its structure, so the
rubric audit (P1) and the rewrite (P2) work against the real thing.

Fidelity contract (mirrors ``core/agent/loop/_context.build_system_prompt``):

* base = ``core.agent.system_prompt.build_system_prompt(model)`` with the
  surface pinned through ``GEODE_SURFACE_TYPE``;
* the ``{skill_context}`` placeholder collapses to the same empty-state
  marker the loop uses when no skill registry is attached;
* ``AGENTIC_SUFFIX`` rides inside the base's static zone since
  PR-PROMPT-P2A (no loop-level append on the default path).

Two loop inputs are caller-supplied and therefore NOT reproduced — the
per-spawn ``_system_prompt_override`` (AgentDefinition) and the
``_system_suffix`` (e.g. the Petri seed scenario). The dump covers the
default operator path.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.agent.system_prompt import build_system_prompt
from core.paths import GLOBAL_DIAGNOSTICS_DIR

SKILL_EMPTY_MARKER = '<available_skills status="empty" />'

DUMP_SURFACES: tuple[str, ...] = (
    "cli",
    "serve_repl",
    "slack",
    "cron",
    "worktree",
    "mcp_remote",
)

_OPENING_TAG_RE = re.compile(r"<([a-z][a-z0-9_]*)(?:\s[^>]*)?>")


@dataclass(frozen=True)
class PromptDumpRow:
    """Structure summary for one (model, surface) cell."""

    model: str
    surface: str
    chars: int
    est_tokens: int
    tag_sequence: tuple[str, ...]
    duplicate_tags: tuple[str, ...]
    path: Path


def assemble_full_prompt(model: str, surface: str) -> str:
    """Reproduce the loop's final system prompt for *model* on *surface*."""
    import os

    previous_surface = os.environ.get("GEODE_SURFACE_TYPE")
    os.environ["GEODE_SURFACE_TYPE"] = surface
    try:
        base = build_system_prompt(model=model)
    finally:
        if previous_surface is None:
            os.environ.pop("GEODE_SURFACE_TYPE", None)
        else:
            os.environ["GEODE_SURFACE_TYPE"] = previous_surface
    # PR-PROMPT-P2A — the base now carries AGENTIC_SUFFIX in its static
    # zone (before <dynamic_context>); appending again would duplicate it.
    return base.replace("{skill_context}", SKILL_EMPTY_MARKER)


def analyze_prompt(prompt: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (opening-tag sequence, tags opened more than once).

    Duplicate openings are the cheap drift signal: the same XML section
    arriving from two assembly layers (e.g. a memory block injected twice)
    shows up here before anyone reads 20KB of prompt by eye.
    """
    tags = tuple(m.group(1) for m in _OPENING_TAG_RE.finditer(prompt))
    counts = Counter(tags)
    duplicates = tuple(sorted(t for t, n in counts.items() if n > 1))
    return tags, duplicates


def measure_tokens_anthropic(prompt: str) -> int | None:
    """Real token count via the Anthropic count_tokens endpoint (free).

    Returns None when no Anthropic credential is available — callers fall
    back to the chars//4 estimate and label it as such. The Anthropic
    tokenizer is used as the single reference ruler across all dumped
    models (cross-vendor counts differ; one ruler keeps deltas comparable).
    """
    from core.config import settings

    api_key = getattr(settings, "anthropic_api_key", "")
    if not api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        from core.config import ANTHROPIC_PRIMARY

        counted = client.messages.count_tokens(
            model=ANTHROPIC_PRIMARY,
            system=prompt,
            messages=[{"role": "user", "content": "."}],
        )
        return int(counted.input_tokens)
    except Exception:  # network/credential failure → estimate fallback
        return None


def dump_matrix(
    models: tuple[str, ...],
    surfaces: tuple[str, ...] = DUMP_SURFACES,
    *,
    out_dir: Path | None = None,
    measure: bool = False,
) -> list[PromptDumpRow]:
    """Dump every (model, surface) cell to disk and return summary rows."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target_dir = out_dir or (GLOBAL_DIAGNOSTICS_DIR / "prompt-dump" / timestamp)
    target_dir.mkdir(parents=True, exist_ok=True)

    rows: list[PromptDumpRow] = []
    for model in models:
        for surface in surfaces:
            prompt = assemble_full_prompt(model, surface)
            tags, duplicates = analyze_prompt(prompt)
            measured = measure_tokens_anthropic(prompt) if measure else None
            est_tokens = measured if measured is not None else len(prompt) // 4
            cell_path = target_dir / f"{model}--{surface}.md"
            cell_path.write_text(prompt, encoding="utf-8")
            rows.append(
                PromptDumpRow(
                    model=model,
                    surface=surface,
                    chars=len(prompt),
                    est_tokens=est_tokens,
                    tag_sequence=tags,
                    duplicate_tags=duplicates,
                    path=cell_path,
                )
            )
    return rows
