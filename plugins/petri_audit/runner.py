"""Petri audit runner — single entry point for CLI / slash / tool paths.

Wraps the ``inspect eval inspect_petri/audit`` subprocess so the three
GEODE entry points (``geode audit`` Typer command, ``/audit`` slash,
``petri_audit`` tool) all funnel through one cost-estimating, confirm-
gating function.

Live LLM authorisation: ``run_audit`` triggers paid LLM calls when
``dry_run`` is False. Default behaviour is ``dry_run=True`` so the
common case (CLI inspection, tests, NL exploration) prints the
constructed command without spending. Set ``yes=True`` to skip the
confirm prompt — meant for the EXPENSIVE_TOOLS-gated tool path where
the safety gate has already received user consent.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from core.llm.token_tracker import MODEL_PRICING

from plugins.petri_audit.models import to_inspect_model, to_inspect_target

log = logging.getLogger(__name__)

__all__ = [
    "AuditReport",
    "TokenAssumptions",
    "build_command",
    "confirm_or_abort",
    "estimate_cost_usd",
    "format_cost",
    "run_audit",
]

#: PoC FX rate. Real-time conversion is overkill while the cost gate
#: itself is a coarse < 5K KRW heuristic; bump as needed.
USD_TO_KRW: int = 1_400


@dataclass(frozen=True)
class TokenAssumptions:
    """Per-turn token budget used by the cost estimator.

    Calibrated to be conservative on the high side so a real audit
    landing under the estimate is the common case. Values to revisit
    after the first P3-b-2 live run produces actual numbers.
    """

    auditor_in: int = 2_000
    auditor_out: int = 800
    target_in: int = 1_500
    target_out: int = 600
    judge_in: int = 4_000
    judge_out: int = 200
    geode_amplifier: int = 5
    judge_calls_per_turn: float = 0.5


DEFAULT_TOKEN_ASSUMPTIONS = TokenAssumptions()


@dataclass
class AuditReport:
    """Outcome of a ``run_audit`` invocation.

    Always populated; ``returncode``/``stdout``/``stderr`` are blank for
    ``dry_run=True`` or when the user aborts at the confirm prompt.
    """

    command: list[str]
    estimated_usd: float
    estimated_krw: int
    dry_run: bool
    aborted: bool = False
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.command),
            "estimated_usd": self.estimated_usd,
            "estimated_krw": self.estimated_krw,
            "dry_run": self.dry_run,
            "aborted": self.aborted,
            "returncode": self.returncode,
            "notes": self.notes,
        }


def build_command(
    *,
    judge: str,
    auditor: str,
    target: str,
    seeds: int,
    max_turns: int,
    tags: str | None,
    cache: bool,
) -> list[str]:
    """Assemble the ``inspect eval`` command line.

    All model identifiers are passed through ``to_inspect_model`` /
    ``to_inspect_target`` first by the caller — this function expects
    inspect_ai-shaped ids (``provider/model``).
    """
    cmd: list[str] = ["inspect", "eval", "inspect_petri/audit"]
    if seeds > 0:
        cmd.extend(["--limit", str(seeds)])
    cmd.extend(["--model-role", f"auditor={auditor}"])
    cmd.extend(["--model-role", f"target={target}"])
    cmd.extend(["--model-role", f"judge={judge}"])
    cmd.extend(["-T", f"max_turns={max_turns}"])
    cmd.extend(["-T", "target_tools=none"])
    if tags:
        cmd.extend(["-T", f"seed_instructions=tags:{tags}"])
    if cache:
        cmd.extend(["-T", "cache=true"])
    return cmd


def estimate_cost_usd(
    *,
    judge: str,
    auditor: str,
    target: str,
    seeds: int,
    max_turns: int,
    assumptions: TokenAssumptions = DEFAULT_TOKEN_ASSUMPTIONS,
) -> float:
    """Estimate USD cost from MODEL_PRICING + per-turn token assumptions.

    Inputs are GEODE catalog ids (``claude-sonnet-4-6``,
    ``gpt-5.5``, ``glm-5``). Strings containing ``/`` are unwrapped to
    the trailing segment so a raw inspect_ai id (``anthropic/claude-…``)
    or a target with the ``geode/`` prefix still resolves. Returns NaN
    when any of the three roles has no pricing entry — caller surfaces
    that as ``estimate unavailable`` rather than a fake number.
    """

    def _basename(model_id: str) -> str:
        return model_id.rsplit("/", 1)[-1]

    pa = MODEL_PRICING.get(_basename(auditor))
    pt = MODEL_PRICING.get(_basename(target))
    pj = MODEL_PRICING.get(_basename(judge))
    if pa is None or pt is None or pj is None:
        return math.nan

    auditor_cost = pa.input * assumptions.auditor_in + pa.output * assumptions.auditor_out
    target_cost = (
        pt.input * assumptions.target_in + pt.output * assumptions.target_out
    ) * assumptions.geode_amplifier
    judge_cost = assumptions.judge_calls_per_turn * (
        pj.input * assumptions.judge_in + pj.output * assumptions.judge_out
    )
    per_turn = auditor_cost + target_cost + judge_cost
    return seeds * max_turns * per_turn


def format_cost(estimated_usd: float) -> tuple[str, int]:
    """Format USD estimate + KRW conversion. Returns ``(label, krw_int)``.

    NaN renders as ``"unavailable"`` and ``krw=0`` so call sites can
    branch on a sentinel rather than parsing the label.
    """
    if math.isnan(estimated_usd):
        return "unavailable (unknown model pricing)", 0
    krw = int(estimated_usd * USD_TO_KRW)
    return f"~${estimated_usd:.2f} (~{krw:,} KRW @ 1USD={USD_TO_KRW}KRW)", krw


def confirm_or_abort(cost_label: str, *, yes: bool) -> bool:
    """Show a [y/N] prompt unless ``yes`` skips it.

    Returns True on consent, False on abort. ``yes=True`` is reserved
    for the EXPENSIVE_TOOLS path where the safety gate has already
    received user consent — never enable it from the Typer/slash
    surface unless the user explicitly passed ``--yes``.
    """
    if yes:
        return True
    from core.ui.console import console

    prompt = (
        f"  [bold yellow]Petri audit — live LLM calls "
        f"(~{cost_label}). Proceed?[/bold yellow] [y/N] "
    )
    response = console.input(prompt).strip().lower()
    return response in ("y", "yes")


def run_audit(
    *,
    judge: str,
    auditor: str,
    target: str,
    seeds: int = 1,
    max_turns: int = 10,
    tags: str | None = None,
    cache: bool = True,
    dry_run: bool = True,
    yes: bool = False,
    assumptions: TokenAssumptions = DEFAULT_TOKEN_ASSUMPTIONS,
) -> AuditReport:
    """Run a Petri audit (or print the command in ``dry_run``).

    See module docstring for the live-call authorisation policy. The
    three GEODE entry points (``geode audit``, ``/audit``,
    ``petri_audit`` tool) call this directly and only differ in how
    they report the resulting :class:`AuditReport`.
    """
    inspect_auditor = to_inspect_model(auditor)
    inspect_judge = to_inspect_model(judge)
    inspect_target = to_inspect_target(target)
    cmd = build_command(
        judge=inspect_judge,
        auditor=inspect_auditor,
        target=inspect_target,
        seeds=seeds,
        max_turns=max_turns,
        tags=tags,
        cache=cache,
    )
    estimated_usd = estimate_cost_usd(
        judge=judge,
        auditor=auditor,
        target=target,
        seeds=seeds,
        max_turns=max_turns,
        assumptions=assumptions,
    )
    cost_label, estimated_krw = format_cost(estimated_usd)
    notes: list[str] = []

    if dry_run:
        notes.append("dry-run: subprocess not executed")
        return AuditReport(
            command=cmd,
            estimated_usd=estimated_usd,
            estimated_krw=estimated_krw,
            dry_run=True,
            notes=notes,
        )

    if shutil.which("inspect") is None:
        notes.append(
            "`inspect` CLI not found on PATH — install the [audit] extra: `uv sync --extra audit`."
        )
        return AuditReport(
            command=cmd,
            estimated_usd=estimated_usd,
            estimated_krw=estimated_krw,
            dry_run=False,
            aborted=True,
            notes=notes,
        )

    if not confirm_or_abort(cost_label, yes=yes):
        notes.append("aborted at confirm prompt")
        return AuditReport(
            command=cmd,
            estimated_usd=estimated_usd,
            estimated_krw=estimated_krw,
            dry_run=False,
            aborted=True,
            notes=notes,
        )

    log.info("Petri audit subprocess: %s", " ".join(cmd))
    # ``cmd`` is built solely from validated model ids + numeric flags by
    # build_command — no shell metacharacters or untrusted user strings.
    proc = subprocess.run(  # noqa: S603 — fixed-shape argv, no untrusted input
        cmd,
        text=True,
        capture_output=True,
        check=False,
    )
    return AuditReport(
        command=cmd,
        estimated_usd=estimated_usd,
        estimated_krw=estimated_krw,
        dry_run=False,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        notes=notes,
    )
