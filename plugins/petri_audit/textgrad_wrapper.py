"""TextGrad wrapper enforcing **M4** — single-step textual gradient.

The TEP analysis (``arXiv 2601.21064``) shows multi-step textual
gradients (depth ≥ 2) explode token usage 16× and amplify judge bias
non-linearly. GEODE's mitigation (M4 in
``docs/plans/eval-petri-p3b-2-execution.md`` § "D 단계 도입 전 위험
카탈로그") is the simplest one possible: refuse calls with
``depth > 1`` or ``chained=True``.

This wrapper is intentionally thin — it does not duplicate TextGrad's
public API, just gates the depth/chaining knobs and lazy-imports the
underlying library so the cold path is unaffected when ``[reason]`` is
absent. Live calls require an explicit user authorisation per
`CLAUDE.md` → CANNOT → Quality: "No unauthorized live test execution".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "MAX_TEXTGRAD_DEPTH",
    "TextGradError",
    "TextGradResult",
    "apply_textual_gradient",
    "guard_depth",
]

#: Hard ceiling on TextGrad depth. M4 — single-step only.
MAX_TEXTGRAD_DEPTH: int = 1


class TextGradError(RuntimeError):
    """Raised when [reason] is missing or M4 (depth=1) is violated."""


@dataclass
class TextGradResult:
    """Return shape of :func:`apply_textual_gradient`.

    ``original_prompt`` and ``patched_prompt`` are kept side-by-side so
    the caller (eval_dspy_optimize handler) can diff them and route
    through the M2 PR-only flow.
    """

    original_prompt: str
    patched_prompt: str
    judge_rationale: str
    depth: int = 1
    dry_run: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_prompt": self.original_prompt,
            "patched_prompt": self.patched_prompt,
            "judge_rationale": self.judge_rationale,
            "depth": self.depth,
            "dry_run": self.dry_run,
            "notes": list(self.notes),
        }


def guard_depth(depth: int, *, chained: bool = False) -> None:
    """M4 enforcement — reject depth > 1 or any chained-gradient call."""
    if depth < 1:
        raise TextGradError(f"depth must be >= 1; got {depth}")
    if depth > MAX_TEXTGRAD_DEPTH:
        raise TextGradError(
            f"M4 violation — TextGrad depth={depth} exceeds the GEODE "
            f"maximum of {MAX_TEXTGRAD_DEPTH}. Multi-step textual "
            f"gradients explode token usage and amplify judge bias "
            f"(see plan § R3 — TextGrad TEP)."
        )
    if chained:
        raise TextGradError(
            "M4 violation — chained=True is forbidden. Each gradient "
            "application must start from the live prompt, not a "
            "previous patch (see plan § R3)."
        )


def apply_textual_gradient(
    prompt: str,
    judge_rationale: str,
    *,
    depth: int = 1,
    chained: bool = False,
    dry_run: bool = True,
) -> TextGradResult:
    """Run a single-step textual gradient against ``prompt``.

    The TextGrad import is deferred until ``dry_run=False`` so the cold
    path stays clean when the ``[reason]`` extra is absent. ``dry_run``
    returns a structurally-identical report whose ``patched_prompt``
    equals ``prompt``; consumers (the ``eval_dspy_optimize`` handler)
    can rely on the same shape regardless of mode.
    """
    if not prompt:
        raise TextGradError("prompt must not be empty")
    if not judge_rationale:
        raise TextGradError("judge_rationale must not be empty")

    guard_depth(depth, chained=chained)

    if dry_run:
        return TextGradResult(
            original_prompt=prompt,
            patched_prompt=prompt,
            judge_rationale=judge_rationale,
            depth=depth,
            dry_run=True,
            notes=["dry-run: TextGrad not invoked"],
        )

    try:
        import textgrad as tg
    except ImportError as exc:
        raise TextGradError(
            "[reason] extra not installed. Run `uv sync --extra reason` "
            "to install dspy + textgrad + instructor."
        ) from exc

    log.info("TextGrad single-step backward pass starting (depth=%d)", depth)

    try:
        engine = tg.get_engine()
        prompt_var = tg.Variable(
            prompt,
            requires_grad=True,
            role_description="GEODE system prompt under review",
        )
        feedback = tg.Variable(
            judge_rationale,
            requires_grad=False,
            role_description="Petri judge rationale",
        )
        loss = tg.TextLoss(
            "Apply the rationale as a single targeted edit to the prompt; "
            "do not generalise; do not chain edits.",
            engine=engine,
        )
        loss(prompt_var, feedback).backward()
        patched = str(prompt_var.value)
    except Exception as exc:
        raise TextGradError(f"TextGrad backward failed: {exc}") from exc

    return TextGradResult(
        original_prompt=prompt,
        patched_prompt=patched,
        judge_rationale=judge_rationale,
        depth=depth,
        dry_run=False,
        notes=["TextGrad single-step ok"],
    )
