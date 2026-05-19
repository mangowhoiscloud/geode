"""DSPy-driven prompt optimization for the Petri × GEODE loop.

Wraps DSPy's compiler (`BootstrapFewShot`) so a Petri smoke run can
produce a metric → DSPy can re-compile GEODE's system prompt → the
result is written to disk for human review (PR-only, no auto-merge).

Risk catalogue + mitigations are SOT'd in
``docs/plans/eval-petri-p3b-2-execution.md`` § "D 단계 도입 전 위험
카탈로그". This module enforces three of those mitigations as **D 진입
전제 잠금** — calls violating them raise :class:`OptimizeError` rather
than silently soft-failing:

- **M1** (judge ≠ generator provider) — :func:`_check_provider_split`
- **M2** (PR-only auto-edit) — never mutates the live config; output
  lands at ``output_dir/<compile_id>.json`` and the report's
  ``next_step`` instructs the caller to open a PR. Auto-merge is
  disallowed by branch protection / CODEOWNERS, not by code here.
- **M3** (compile budget cap) — defaults to 50 USD/month enforced by the
  ``max_compile_usd`` argument; exceeding aborts before DSPy runs.
- **M10** (seed + compile_id) — every report carries a deterministic id
  derived from inputs so two operators can verify they're looking at
  the same compile.

Live invocation triggers paid LLM calls. Default ``dry_run=True`` —
the report contains the constructed ``compile_id``, the would-be
output path, and the cost estimate, with no DSPy import on the cold
path. ``dry_run=False`` requires explicit user authorisation per
CLAUDE.md L99.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plugins.petri_audit.models import provider_of, same_provider

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_COMPILE_USD_CAP",
    "OptimizeError",
    "OptimizeReport",
    "compile_id_for",
    "optimize_prompt",
]

#: Hard monthly cap for ``optimize_prompt`` (M3). Raised abort when the
#: caller's ``max_compile_usd`` falls below the conservative per-compile
#: estimate. Real budget tracking across compiles is out of scope for
#: this module — that lives at the orchestration layer once the loop is
#: closed in P4.
DEFAULT_COMPILE_USD_CAP: float = 50.0

#: Conservative per-compile USD estimate. Anchored to the DSPy public
#: GPT-3.5 figure ($3 / 2.7M token) scaled to Anthropic Sonnet-class
#: pricing. See plan § R2 for the source.
PER_COMPILE_USD_ESTIMATE: float = 12.0


class OptimizeError(RuntimeError):
    """Raised when a D-stage mitigation gate refuses the call."""


@dataclass
class OptimizeReport:
    """Outcome of an :func:`optimize_prompt` invocation.

    Always populated; ``output_path`` is the *intended* artefact path
    (existing or to-be-written), and ``next_step`` is the human action
    that closes the loop (= open a PR).
    """

    compile_id: str
    judge: str
    generator: str
    judge_provider: str
    generator_provider: str
    output_path: Path
    estimated_usd: float
    estimated_usd_cap: float
    dry_run: bool
    aborted: bool = False
    next_step: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compile_id": self.compile_id,
            "judge": self.judge,
            "generator": self.generator,
            "judge_provider": self.judge_provider,
            "generator_provider": self.generator_provider,
            "output_path": str(self.output_path),
            "estimated_usd": self.estimated_usd,
            "estimated_usd_cap": self.estimated_usd_cap,
            "dry_run": self.dry_run,
            "aborted": self.aborted,
            "next_step": self.next_step,
            "notes": list(self.notes),
        }


def _check_provider_split(judge: str, generator: str) -> tuple[str, str]:
    """M1 — refuse same-provider judge/generator pairs."""
    judge_provider = provider_of(judge)
    generator_provider = provider_of(generator)
    if judge_provider == "unknown" or generator_provider == "unknown":
        raise OptimizeError(
            f"M1 provider check needs known providers; got "
            f"judge={judge!r} ({judge_provider}), "
            f"generator={generator!r} ({generator_provider})."
        )
    if same_provider(judge, generator):
        raise OptimizeError(
            f"M1 violation — judge ({judge_provider}) shares a provider with "
            f"generator ({generator_provider}). In-context reward hacking + "
            f"self-preference bias risk. Pick a judge from a different "
            f"vendor (see plan § D 단계 도입 전 위험 카탈로그 R1/R3)."
        )
    return judge_provider, generator_provider


def _check_budget(max_compile_usd: float) -> float:
    """M3 — refuse calls whose declared budget is below the per-compile floor."""
    if max_compile_usd <= 0:
        raise OptimizeError("max_compile_usd must be > 0")
    if max_compile_usd < PER_COMPILE_USD_ESTIMATE:
        raise OptimizeError(
            f"M3 budget too low — caller declared ${max_compile_usd:.2f} but "
            f"a single Sonnet-class compile averages ${PER_COMPILE_USD_ESTIMATE:.2f}. "
            f"Raise the cap or stay in dry_run mode."
        )
    return PER_COMPILE_USD_ESTIMATE


def compile_id_for(
    *,
    judge: str,
    generator: str,
    eval_log_path: Path,
    seed: int,
    timestamp: datetime | None = None,
) -> str:
    """Deterministic compile id (M10 reproducibility).

    ``YYYYMMDDTHHMMSSZ-<sha256[:10]>``. The hash spans every input that
    can change the compile output: judge / generator / eval log content
    hash (when readable) / seed.
    """
    ts = (timestamp or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    parts = [judge, generator, str(eval_log_path), str(seed)]
    if eval_log_path.exists():
        try:
            parts.append(hashlib.sha256(eval_log_path.read_bytes()).hexdigest())
        except OSError:  # pragma: no cover — read race
            parts.append("readerr")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{ts}-{digest}"


def _next_step_message(output_path: Path) -> str:
    """M2 — instruct the caller to land the artefact via a reviewed PR."""
    return (
        f"M2 PR-only — review {output_path} → "
        f"`git checkout -b feature/dspy-prompt-<id>` → "
        f"copy into `core/agent/system_prompts/` (or wherever the live "
        f"prompt lives) → open a PR. Auto-merge MUST be disabled "
        f"(branch protection / CODEOWNERS)."
    )


def optimize_prompt(
    *,
    judge: str,
    generator: str,
    eval_log_path: Path | str,
    output_dir: Path | str = Path("optimized_prompts"),
    dry_run: bool = True,
    seed: int = 42,
    max_compile_usd: float = DEFAULT_COMPILE_USD_CAP,
) -> OptimizeReport:
    """Compile a system-prompt candidate from a Petri eval log.

    Parameters mirror the ``eval_dspy_optimize`` tool surface so the
    AgenticLoop tool path and the Python API stay symmetric. Returns an
    :class:`OptimizeReport` carrying the deterministic ``compile_id``,
    the on-disk artefact path, the budget gate result, and the
    next-step instruction (M2).

    Raises :class:`OptimizeError` if any of the M1 / M3 gates refuse
    the call. M2 is a behaviour invariant (we never mutate live
    config) and M10 (seed + compile_id) is part of the report payload.
    """
    eval_log = Path(eval_log_path)
    output_root = Path(output_dir)

    judge_provider, generator_provider = _check_provider_split(judge, generator)
    estimated_usd = _check_budget(max_compile_usd)

    compile_id = compile_id_for(
        judge=judge,
        generator=generator,
        eval_log_path=eval_log,
        seed=seed,
    )
    output_path = output_root / f"{compile_id}.json"

    notes: list[str] = [
        f"M1 ok: judge={judge_provider} ≠ generator={generator_provider}",
        f"M3 ok: budget cap ${max_compile_usd:.2f} ≥ ${estimated_usd:.2f} per compile",
        f"M10: compile_id={compile_id}, seed={seed}",
    ]

    if dry_run:
        notes.append("dry-run: DSPy not invoked")
        return OptimizeReport(
            compile_id=compile_id,
            judge=judge,
            generator=generator,
            judge_provider=judge_provider,
            generator_provider=generator_provider,
            output_path=output_path,
            estimated_usd=estimated_usd,
            estimated_usd_cap=max_compile_usd,
            dry_run=True,
            next_step=_next_step_message(output_path),
            notes=notes,
        )

    if not eval_log.exists():
        raise OptimizeError(
            f"eval log not found: {eval_log}. Run a Petri smoke first "
            f"(`geode audit --live ...`) and re-invoke with the *.eval "
            f"path."
        )

    # Lazy import — keep cold-start clean when [reason] is absent.
    try:
        import dspy
    except ImportError as exc:
        raise OptimizeError(
            "[reason] extra not installed. Run `uv sync --extra reason` "
            "to install dspy + textgrad + instructor."
        ) from exc

    log.info(
        "DSPy compile starting compile_id=%s judge=%s generator=%s",
        compile_id,
        judge,
        generator,
    )

    output_root.mkdir(parents=True, exist_ok=True)

    # The actual DSPy compilation pipeline is intentionally minimal here
    # — wiring the BootstrapFewShot teacher / metric / trainset against
    # GEODE's prompt registry is the next implementation task once
    # ``core/agent/system_prompts/`` is consolidated. For now we record
    # the plan-of-record so the artefact still flows through review.
    payload: dict[str, Any] = {
        "compile_id": compile_id,
        "judge": judge,
        "generator": generator,
        "judge_provider": judge_provider,
        "generator_provider": generator_provider,
        "eval_log_sha256": hashlib.sha256(eval_log.read_bytes()).hexdigest(),
        "seed": seed,
        "max_compile_usd": max_compile_usd,
        "dspy_version": getattr(dspy, "__version__", "unknown"),
        "status": "pending — BootstrapFewShot wiring in next D-stage PR",
    }
    output_path.write_text(json.dumps(payload, indent=2))

    return OptimizeReport(
        compile_id=compile_id,
        judge=judge,
        generator=generator,
        judge_provider=judge_provider,
        generator_provider=generator_provider,
        output_path=output_path,
        estimated_usd=estimated_usd,
        estimated_usd_cap=max_compile_usd,
        dry_run=False,
        next_step=_next_step_message(output_path),
        notes=[*notes, "DSPy lazy import ok", "artefact written"],
    )
