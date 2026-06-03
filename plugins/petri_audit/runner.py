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
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.llm.token_tracker import MODEL_PRICING

from plugins.petri_audit.judge_dims import DEFAULT_DIM_SET, resolve_dim_set
from plugins.petri_audit.models import (
    is_oauth_routed,
    to_inspect_model,
    to_inspect_target,
)

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TOKEN_ASSUMPTIONS",
    "SPLIT_TOKEN_ASSUMPTIONS",
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

    N4 calibration (2026-05-11) — N6-followup + N7' + N8 the 9-sample
    aggregate (4 anthropic + 5 openai) shaped the new defaults:

    | role | per-sample tokens (mean) | per-turn baseline |
    |------|--------------------------|-------------------|
    | auditor (sonnet/gpt-5.4-mini) | in≈3K, out≈1.5K | 0.3K / 0.15K × max_turns |
    | target (opus / gpt-5.4) | 9 calls × max_turns | amplifier 1 (1 call/turn) |
    | judge | in≈3K, out≈1.4K (1 call/sample) | judge_calls_per_sample |

    Old defaults treated judge as ``calls_per_turn`` × max_turns which
    over-estimated 5×: inspect-petri's ``audit_judge`` runs once per
    sample on the full transcript. The new ``judge_calls_per_sample``
    field encodes that. ``geode_amplifier`` was 5 (target × 5 sub-LLM
    calls); the live runs show 1 call/turn × max_turns is closer.

    Estimator landing zone after N4: live cost is 30-100% of estimate
    (vs the pre-N4 8-38%). Still conservative on the high side so a
    real run under the estimate stays the common case.
    """

    auditor_in_per_turn: int = 500
    auditor_out_per_turn: int = 400
    target_in_per_turn: int = 1_500
    target_out_per_turn: int = 1_500
    #: Per-call judge tokens. A3 (2026-05-14) split mode reduces these per
    #: call (smaller rubric subset) but multiplies the call count — net
    #: cost is +2.16× per sample (see judge-split-design.md § 6). Caller
    #: sets ``judge_calls_per_sample=5`` and trims per-call tokens (e.g.
    #: judge_in 6_000→3_500, judge_out 2_000→580 avg) when running with
    #: --judge-mode split.
    judge_in_per_sample: int = 6_000
    judge_out_per_sample: int = 2_000
    geode_amplifier: int = 1
    #: 1 in legacy mode (single mega-judge call), 5 in A3 split mode.
    #: See plugins/petri_audit/judge_dims/geode_judge_subset_split.yaml
    #: for the 5-group definition; runtime orchestration is staged behind
    #: cli_audit.py --judge-mode split (legacy is default until upstream
    #: inspect-petri supports group-aware audit_judge).
    judge_calls_per_sample: float = 1.0

    # B (cache cost reflection) — anthropic / openai 모두 cache_read 가
    # 90% 할인 (`pa.cache_read = pa.input × 0.1` in
    # core/llm/token_tracker.py:126). 이전 estimator 는 ``pa.input``
    # 만 사용해 anthropic / openai 의 cache-heavy stack 에서 5-15× over.
    #
    # 본 비율은 N6-followup + N8 의 실측 (auditor cache_ratio 88-94%,
    # judge 33-48%) 의 conservative side. 가능하면 estimator 가 over-
    # estimate side 에 머물도록 ratio 를 실측보다 살짝 낮게 잡음.
    auditor_cache_read_ratio: float = 0.85
    target_cache_read_ratio: float = 0.0  # GEODE tracker 0 records 라 미관측, 보수적 0
    judge_cache_read_ratio: float = 0.45


DEFAULT_TOKEN_ASSUMPTIONS = TokenAssumptions()

#: A3 (2026-05-14) split-mode token assumptions. 5 judge calls per sample
#: with scoped rubrics — input drops from 6K (full 19-dim split rubric;
#: PR-0 context-management 3 dims stay legacy-only) to 3.5K per call
#: (one group's rubric), output averages 580 tokens (~19 dims total
#: spread across 5 calls, ~3.8 dims × 150 tokens each). Net cost per
#: sample: $0.0346 (vs legacy $0.016), +$1.40 on a 75-sample N=5 batch.
#: See docs/audits/2026-05-13-petri-a3-judge-split-design.md § 6.2.
SPLIT_TOKEN_ASSUMPTIONS = TokenAssumptions(
    judge_in_per_sample=3_500,
    judge_out_per_sample=580,
    judge_calls_per_sample=5.0,
)


@dataclass
class AuditReport:
    """Outcome of a ``run_audit`` invocation.

    Always populated; ``returncode``/``stdout``/``stderr`` are blank for
    ``dry_run=True`` or when the user aborts at the confirm prompt.

    ``same_provider_bias_chip`` (PR #8, 2026-05-14): non-empty when
    auditor + target + judge all share a provider root. Reports must
    render this chip so reviewers see that any finding has the
    −10..−22 % self-preference disadvantage applied — see
    :mod:`plugins.petri_audit.bias` for the polarity table and
    ``docs/audits/2026-05-14-petri-same-provider-bias.md``.
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
    same_provider_bias_chip: str = ""

    #: Where the live ``.eval`` was archived (raw + summary). Populated
    #: when ``auto_archive=True`` and the inspect_ai run produced a
    #: ``Log: …`` line. ``None`` for dry-run / aborted / archive failure
    #: (failure is recorded as a note, never raised — archive is a
    #: best-effort safety net, not a blocker for the audit result).
    archived_raw: str | None = None
    archived_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.command),
            "estimated_usd": self.estimated_usd,
            "estimated_krw": self.estimated_krw,
            "dry_run": self.dry_run,
            "aborted": self.aborted,
            "returncode": self.returncode,
            "notes": self.notes,
            "archived_raw": self.archived_raw,
            "archived_summary": self.archived_summary,
        }


#: Allowed values for ``--target-tools``. Mirror inspect-petri's
#: ``audit(target_tools=…)`` literal so a future inspect-petri version
#: bump surfaces here as a typing error rather than a silent acceptance.
TARGET_TOOLS_VALUES = ("synthetic", "fixed", "none")


def build_command(
    *,
    judge: str,
    auditor: str,
    target: str,
    seeds: int,
    max_turns: int,
    tags: str | None,
    cache: bool,
    dim_set: str | None = DEFAULT_DIM_SET,
    seed_select: str | None = None,
    target_tools: str = "none",
    reveal_reasoning: bool = False,
) -> list[str]:
    """Assemble the ``inspect eval`` command line.

    All model identifiers are passed through ``to_inspect_model`` /
    ``to_inspect_target`` first by the caller — this function expects
    inspect_ai-shaped ids (``provider/model``).

    ``dim_set`` selects the judge-dimension set:
    ``"subset"`` → ``-T judge_dimensions=<built-in YAML>`` (22 dims).
    ``"full"`` / ``None`` → flag omitted; inspect-petri's default 38.
    Anything else → resolved to a path string. The path's existence is
    checked at build time + the YAML's bare-string dim names are validated
    as a subset of inspect-petri's default 38 (when [audit] extra is
    installed) so a typo fails fast here instead of inside the audit.
    Inline ``JudgeDimension`` dict entries (used by the PR-0
    context-management dims) are passed through unchanged.

    ``seed_select`` selects seed scenarios (forwarded to ``-T
    seed_instructions=<value>`` verbatim). Inspect-petri accepts
    ``id:<id>[,<id>...]`` for explicit seed ids, ``tags:<tag>[,<tag>]``
    for tag-based selection, a directory of ``.md`` files, or a
    YAML/file path. Mutually exclusive with ``tags``. Path-shaped
    values are checked for existence at build time; ``id:`` / ``tags:``
    prefixes are passed through unchanged.

    ``target_tools`` controls which tool-creation tools the auditor
    receives. ``"synthetic"`` (inspect-petri default) gives the
    auditor ``create_tool`` / ``remove_tool`` / ``send_tool_call_result``;
    ``"fixed"`` only ``send_tool_call_result``; ``"none"`` (our
    default) is conversation-only mode. Note: GEODE's audit target
    owns its own tool registry, so ``synthetic``/``fixed`` lets the
    auditor *fabricate* tool results — useful for capability dim
    studies, harmful for behaviour-control comparisons.
    """
    if tags and seed_select:
        raise ValueError(
            "Pass either ``tags`` (legacy shortcut for seed_instructions="
            "tags:<tag>) or ``seed_select`` (full id:/tags:/path form), "
            "not both — inspect-petri honours only one seed_instructions value."
        )
    if target_tools not in TARGET_TOOLS_VALUES:
        raise ValueError(
            f"target_tools must be one of {TARGET_TOOLS_VALUES}, got {target_tools!r}. "
            "See inspect-petri/_task/audit.py:audit() docstring."
        )

    resolved_dims = resolve_dim_set(dim_set)
    _validate_dim_path(resolved_dims)
    _validate_seed_select_path(seed_select)

    cmd: list[str] = ["inspect", "eval", "inspect_petri/audit"]

    # PR-OL-AUDIT-BURST-FIX (2026-05-22) FIX-1+2 — serialise inspect_ai's
    # per-provider connection pool (default 10) and per-sample
    # parallelism (default also 10) down to 1 each. Matches Paperclip's
    # empirical "1 active subprocess at a time, serial-turn loop"
    # pattern that keeps Anthropic Max OAuth's ~5 req/sec soft limit
    # honoured. Without these flags inspect_ai bursts 30 concurrent
    # POST /v1/messages (auditor + judge + target × 10) → instant 429
    # storm → 769s retry-after backoff → 17-min timeout with 0 samples.
    #
    # Cost: audit wall time scales linearly with sample count instead
    # of fan-out parallel. Trade: actually completing > 0 samples.
    # Operators with a multi-account pool (future AccountPool sprint)
    # can lift these caps; the single-OAuth default stays at 1.
    #
    # An operator on a higher-limit lane (PAYG api_key, or a multi-account
    # pool) lifts these via GEODE_AUDIT_MAX_CONNECTIONS / _MAX_SAMPLES. A
    # missing or non-integer value falls back to 1 (graceful boundary), so
    # the single-OAuth path is byte-identical to the original behaviour.
    def _cap(env_name: str) -> int:
        try:
            return max(1, int(os.environ.get(env_name, "1")))
        except (TypeError, ValueError):
            return 1

    cmd.extend(["--max-connections", str(_cap("GEODE_AUDIT_MAX_CONNECTIONS"))])
    cmd.extend(["--max-samples", str(_cap("GEODE_AUDIT_MAX_SAMPLES"))])
    if seeds > 0:
        cmd.extend(["--limit", str(seeds)])
    cmd.extend(["--model-role", f"auditor={auditor}"])
    cmd.extend(["--model-role", f"target={target}"])
    cmd.extend(["--model-role", f"judge={judge}"])
    cmd.extend(["-T", f"max_turns={max_turns}"])
    cmd.extend(["-T", f"target_tools={target_tools}"])
    if seed_select:
        # PR 0 — when seed_select is a hierarchical tree (tier/dim/...),
        # flatten to a content-addressed symlink stage so inspect-petri's
        # flat ``directory.glob("*.md")`` loader sees every seed.
        # PR-PETRI-SINGLE-SEED-STAGING (2026-06-03) — a single candidate ``.md``
        # is staged as ``seeds`` distinct-named copies (passed via ``samples``)
        # so it delivers ``seeds`` real rollouts instead of being splitlines-
        # shredded into empty seeds (project_seedgen_pilot_seed_delivery_bug).
        from plugins.petri_audit.seed_tree import flatten_for_inspect_petri

        resolved_seed_path = flatten_for_inspect_petri(seed_select, samples=seeds)
        cmd.extend(["-T", f"seed_instructions={resolved_seed_path}"])
    elif tags:
        cmd.extend(["-T", f"seed_instructions=tags:{tags}"])
    if cache:
        cmd.extend(["-T", "cache=true"])
    if resolved_dims is not None:
        cmd.extend(["-T", f"judge_dimensions={resolved_dims}"])
    # Booster A (2026-05-12) — decision-log reveal under audit-mode.
    # inspect_ai's anthropic adapter (model/_providers/anthropic.py:805-807)
    # only emits ``thinking={type:"adaptive", display:"summarized"}`` when
    # ``--reasoning-effort`` is set. Without it the target/auditor/judge
    # thinking blocks arrive empty (Opus 4.7 default ``display="omitted"``)
    # and the archive's ModelEvent.output has 0 reasoning content — the
    # "why behaved" signal alignment audits are meant to capture. The
    # ``--reasoning-history all`` flag keeps reasoning blocks in the chat
    # history rather than stripping them between turns.
    if reveal_reasoning:
        cmd.extend(["--reasoning-effort", "high"])
        cmd.extend(["--reasoning-history", "all"])
    return cmd


def purge_inspect_cache() -> bool:
    """Clear inspect_ai's generate trajectory cache before a fresh run.

    PR-SIL-MULTIOBJ A3 (2026-05-29) — the closed loop's audits run with
    the trajectory cache OFF (no ``-T cache=true``; see ``cli_audit.py``
    default), but a *residual* cache from an earlier ``geode audit
    --cache`` run, or from a partially-failed audit on the same host,
    can still be hit: the cache key is ``(model config, input messages,
    base_url, tools, expiry, scopes, epoch)``, so a stale trajectory for
    an identical seed replays its recorded score and silently corrupts a
    mutation-vs-baseline comparison. Calling this before a fresh baseline
    extraction or a cycle batch removes that residue.

    Uses inspect_ai's own ``cache_clear`` as the single source of truth
    for the cache location — the path (``cache_path()``) is platform- and
    config-dependent, so it is **not** hardcoded here. Graceful: when the
    ``[audit]`` extra is absent (default ``uv sync``), logs and returns
    ``False`` rather than raising, so non-audit callers are unaffected.

    Returns ``True`` when the purge completed (cache now empty, whether or
    not it had content), ``False`` when inspect_ai is unavailable or the
    clear raised.
    """
    try:
        from inspect_ai.model import cache_clear, cache_path
    except ImportError:
        log.warning(
            "purge_inspect_cache: inspect_ai not installed ([audit] extra) — skipping cache purge"
        )
        return False
    try:
        target = cache_path()
        cleared = cache_clear()
    except Exception as exc:  # pragma: no cover — defensive (inspect_ai internals)
        log.warning("purge_inspect_cache: cache_clear failed — %s", exc)
        return False
    log.info(
        "purge_inspect_cache: cleared inspect_ai generate cache at %s (cache_clear=%s)",
        target,
        cleared,
    )
    return True


def _validate_dim_path(resolved: Any) -> None:
    """Validate a resolved ``--dim-set`` value (path-like).

    Raises ``ValueError`` when the path does not exist, ``FileNotFoundError``
    semantics intentionally elevated to ValueError so the CLI surfaces
    the same class of error for every kind of bad input. When the
    [audit] extra is installed and the path is a YAML, also load the
    file and check that every bare-string name is a subset of
    inspect-petri's default 38 dim set (covers 결함 K).

    ``None`` (= ``--dim-set full``) is a no-op. The built-in YAML path
    (``geode_judge_subset.yaml``) is shipped with this package so its
    existence is also enforced — a missing built-in is a deployment
    bug worth surfacing the same way as a typo'd custom path.
    """
    if resolved is None:
        return
    p = Path(str(resolved))
    if not p.exists():
        raise ValueError(
            f"--dim-set resolved to a path that does not exist: {p}. "
            f"Check the path or use ``--dim-set full`` to fall back to "
            f"inspect-petri's default 38 dim set."
        )
    # Best-effort subset validation when the [audit] extra is installed.
    # Skipped on default ``uv sync`` so the runner module keeps loading
    # without inspect_ai. Callers running an actual audit will already
    # have the extra installed (the inspect CLI lives in it).
    if p.suffix.lower() not in {".yaml", ".yml"}:
        return
    try:
        from inspect_petri._judge.dimensions import load_dimensions
    except ImportError:
        return
    try:
        import yaml
    except ImportError:  # pragma: no cover — yaml is a dep of [audit]
        return
    with p.open(encoding="utf-8") as f:
        names = yaml.safe_load(f)
    if not isinstance(names, list):
        # Custom YAMLs may also list ``JudgeDimension`` dicts; we only
        # validate the simple ``[<name>, <name>, ...]`` shape because
        # the dict form is already a self-contained spec.
        return
    defaults = {d.name for d in load_dimensions()}
    unknown = [n for n in names if isinstance(n, str) and n not in defaults]
    if unknown:
        raise ValueError(
            f"--dim-set YAML at {p} contains unknown dimension(s): {unknown}. "
            f"Allowed bare-string names are inspect-petri's default 38 "
            f"(see inspect_petri/_judge/dimensions/*.md); GEODE-specific "
            f"dims must use the inline ``JudgeDimension`` dict form."
        )


def _validate_seed_select_path(seed_select: str | None) -> None:
    """Path-shaped ``--seed-select`` values must exist at build time.

    ``id:<...>`` / ``tags:<...>`` are command strings, not paths — pass
    through unchanged. Anything that looks like a filesystem path
    (contains ``/`` or ends in ``.md``/``.yaml``/``.json``) is checked
    for existence so a typo fails fast here.
    """
    if not seed_select:
        return
    if seed_select.startswith(("id:", "tags:")):
        return
    # Heuristic: looks like a path
    path_extensions = (".md", ".yaml", ".yml", ".json", ".jsonl", ".csv")
    looks_like_path = (
        "/" in seed_select
        or seed_select.startswith("~")
        or any(seed_select.lower().endswith(ext) for ext in path_extensions)
    )
    if not looks_like_path:
        return
    p = Path(seed_select).expanduser()
    if not p.exists():
        raise ValueError(
            f"--seed-select resolved to a path that does not exist: {p}. "
            f"Use ``id:<seed-id>``, ``tags:<tag>``, or an existing dir/file."
        )


def estimate_cost_usd(
    *,
    judge: str,
    auditor: str,
    target: str | None,
    seeds: int,
    max_turns: int,
    assumptions: TokenAssumptions = DEFAULT_TOKEN_ASSUMPTIONS,
    judge_oauth: bool = False,
    auditor_oauth: bool = False,
) -> float:
    """Estimate USD cost from MODEL_PRICING + per-turn token assumptions.

    Inputs are GEODE catalog ids (``claude-sonnet-4-6``,
    ``gpt-5.5``, ``glm-5``). Strings containing ``/`` are unwrapped to
    the trailing segment so a raw inspect_ai id (``anthropic/claude-…``)
    or a target with the ``geode/`` prefix still resolves. Returns NaN
    when any of the three roles has no pricing entry — caller surfaces
    that as ``estimate unavailable`` rather than a fake number.

    ``target`` may be ``None`` / empty when the caller did not pin a
    base model — in that case we fall back to ``settings.model`` so
    the estimate still reflects the model GEODE will actually use.

    **PR #6 (2026-05-14) — OAuth zeroing**: when ``judge_oauth`` /
    ``auditor_oauth`` is True (caller already classified the role as
    Codex subscription OAuth-routed via ``is_oauth_routed``), the per-token
    contribution for that role is set to zero. Subscription quota is
    not billed per token; the only cost is the user's monthly subscription
    fee, which is out of band for this estimator.
    """

    def _basename(model_id: str) -> str:
        return model_id.rsplit("/", 1)[-1]

    target_name = target or ""
    if not target_name or _basename(target_name) == "default":
        try:
            from core.config import settings

            target_name = settings.model or ""
        except Exception:  # pragma: no cover — settings import edge
            target_name = ""

    pa = MODEL_PRICING.get(_basename(auditor)) if auditor else None
    pt = MODEL_PRICING.get(_basename(target_name)) if target_name else None
    pj = MODEL_PRICING.get(_basename(judge)) if judge else None
    if pa is None or pt is None or pj is None:
        return math.nan

    # N4 calibration: auditor + target are per-turn, judge is per-sample.
    # Pre-N4 estimator multiplied judge by max_turns × judge_calls_per_turn
    # which over-estimated 5× (inspect-petri's audit_judge fires once per
    # sample on the full transcript, not per turn).
    #
    # B (cache cost reflection) — input tokens 의 일부가 prompt cache
    # read (90% 할인) 로 청구된다는 사실을 반영. ``effective_in_price``
    # = (1 - r) × full_input_price + r × cache_read_price 로 계산.
    # ``r=0`` 은 기존 (pre-B) 행동.
    auditor_eff_in = _effective_in_price(pa, assumptions.auditor_cache_read_ratio)
    target_eff_in = _effective_in_price(pt, assumptions.target_cache_read_ratio)
    judge_eff_in = _effective_in_price(pj, assumptions.judge_cache_read_ratio)

    if auditor_oauth:
        auditor_per_turn = 0.0
    else:
        auditor_per_turn = (
            auditor_eff_in * assumptions.auditor_in_per_turn
            + pa.output * assumptions.auditor_out_per_turn
        )
    target_per_turn = (
        target_eff_in * assumptions.target_in_per_turn + pt.output * assumptions.target_out_per_turn
    ) * assumptions.geode_amplifier
    per_sample_turn_cost = (auditor_per_turn + target_per_turn) * max_turns
    if judge_oauth:
        judge_per_sample = 0.0
    else:
        judge_per_sample = assumptions.judge_calls_per_sample * (
            judge_eff_in * assumptions.judge_in_per_sample
            + pj.output * assumptions.judge_out_per_sample
        )
    per_sample = per_sample_turn_cost + judge_per_sample
    return seeds * per_sample


def _effective_in_price(price: Any, cache_read_ratio: float) -> float:
    """Blend full input price + cache_read price by the given ratio.

    ``ModelPrice.cache_read`` is populated for both anthropic and
    openai catalogue entries (see core/llm/token_tracker.py). When
    ``cache_read = 0`` (rare — exotic provider), the function silently
    falls back to ``input`` so the estimator does not zero-out the
    auditor / judge cost.
    """
    cr = float(getattr(price, "cache_read", 0.0) or 0.0)
    inp = float(price.input)
    if cr <= 0.0:
        return inp
    ratio = max(0.0, min(1.0, cache_read_ratio))
    return (1.0 - ratio) * inp + ratio * cr


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
    judge: str | None = None,
    auditor: str | None = None,
    target: str | None = None,
    seeds: int = 1,
    max_turns: int = 10,
    tags: str | None = None,
    cache: bool = False,
    dim_set: str | None = DEFAULT_DIM_SET,
    seed_select: str | None = None,
    target_tools: str = "none",
    judge_mode: str = "legacy",
    dry_run: bool = True,
    yes: bool = False,
    auto_archive: bool = True,
    assumptions: TokenAssumptions | None = None,
    use_oauth: bool | None = None,
) -> AuditReport:
    """Run a Petri audit (or print the command in ``dry_run``).

    See module docstring for the live-call authorisation policy. The
    three GEODE entry points (``geode audit``, ``/audit``,
    ``petri_audit`` tool) call this directly and only differ in how
    they report the resulting :class:`AuditReport`.

    ``target=None`` falls back to GEODE's active ``settings.model``
    (drift sync stays active). A pinned target id is sticky for the
    audit's lifetime — see ``plugins/petri_audit/targets/geode_target.py``
    docstring "Model priority" section.

    **PR #6 (2026-05-14) — ``use_oauth``** governs whether gpt-5.x
    judge / auditor ids re-route through the Codex OAuth provider
    (``openai-codex/<model>``):

    - ``None`` (default) → auto-detect via ``_codex_oauth_available``.
    - ``True`` → force OAuth route (token must exist or the audit
      subprocess raises ``EnvironmentVariableError`` at first judge
      call).
    - ``False`` → keep the legacy per-token ``openai/<model>`` map.

    User-pinned raw ids (``openai/gpt-5.5``) bypass the rewrite
    entirely so an operator who deliberately wants per-token billing
    can do so.
    """
    # A3 (2026-05-14) — judge_mode "split" picks the 5-call token budget
    # (SPLIT_TOKEN_ASSUMPTIONS). Actual 5-call orchestration is staged for
    # an upstream inspect-petri PR; legacy mode (single mega-judge call)
    # remains the runtime default. Cost estimate already reflects split
    # when callers ask, so dry-run preview matches the eventual live cost.
    if assumptions is None:
        if judge_mode == "split":
            assumptions = SPLIT_TOKEN_ASSUMPTIONS
        elif judge_mode == "legacy":
            assumptions = DEFAULT_TOKEN_ASSUMPTIONS
        else:
            raise ValueError(f"unknown judge_mode={judge_mode!r}; expected 'legacy' or 'split'")
    # SoT alignment (2026-05-22) — None argv values defer to
    # ``[self_improving_loop.petri.<role>].model`` via the binding
    # registry (which consults operator config first, then the legacy
    # ~/.geode/petri.toml, then the manifest default). Callers that
    # explicitly pin a model still win — the resolved binding only
    # fires when the argv slot was omitted.
    # Manifest + override resolution does NOT need credentials —
    # ``get_binding`` would also resolve them, but we want this path
    # to work in ``dry_run`` mode (CI smoke runs, slash dry-runs,
    # `geode audit` without env keys). Credential resolution happens
    # later, only on the real-run branch.
    # PR-CRED-SOURCE-CENTRALIZE — the per-role ``source`` override
    # (``[self_improving_loop.petri.<role>].source``) for auditor/judge is read
    # *independently* of whether the model axis was supplied via argv, so an
    # explicit ``source = "api_key"`` routes those roles even when the operator
    # pins the model. Previously only ``model`` was read → the per-role source
    # was a silent no-op. None → to_inspect_model's use_oauth/cascade decides.
    from plugins.petri_audit.user_overrides import read_role_override

    auditor_source: str | None = read_role_override("auditor").get("source")
    judge_source: str | None = read_role_override("judge").get("source")
    if auditor is None or judge is None or target is None:
        from plugins.petri_audit.manifest import load_manifest

        manifest = load_manifest()
        for slot, role in (("auditor", "auditor"), ("judge", "judge"), ("target", "target")):
            if slot == "auditor" and auditor is not None:
                continue
            if slot == "judge" and judge is not None:
                continue
            if slot == "target" and target is not None:
                continue
            resolved = (
                read_role_override(role).get("model") or manifest.get_role(role).default_model
            )
            if slot == "auditor":
                auditor = resolved
            elif slot == "judge":
                judge = resolved
            else:
                target = resolved
    assert auditor is not None and judge is not None and target is not None  # narrowed
    inspect_auditor = to_inspect_model(auditor, use_oauth=use_oauth, source=auditor_source)
    inspect_judge = to_inspect_model(judge, use_oauth=use_oauth, source=judge_source)
    inspect_target = to_inspect_target(target)
    # Booster A — when audit-mode is active (GEODE_AUDIT_UNRESTRICTED=1,
    # set by ``cli_audit.audit(--unrestricted)`` before this call), inject
    # ``--reasoning-effort high --reasoning-history all`` so the
    # auditor / target / judge thinking blocks are non-empty in the archive.
    reveal_reasoning = os.environ.get("GEODE_AUDIT_UNRESTRICTED") == "1"
    cmd = build_command(
        judge=inspect_judge,
        auditor=inspect_auditor,
        target=inspect_target,
        seeds=seeds,
        max_turns=max_turns,
        tags=tags,
        cache=cache,
        dim_set=dim_set,
        seed_select=seed_select,
        target_tools=target_tools,
        reveal_reasoning=reveal_reasoning,
    )
    estimated_usd = estimate_cost_usd(
        judge=judge,
        auditor=auditor,
        target=target,
        seeds=seeds,
        max_turns=max_turns,
        assumptions=assumptions,
        judge_oauth=is_oauth_routed(inspect_judge),
        auditor_oauth=is_oauth_routed(inspect_auditor),
    )
    cost_label, estimated_krw = format_cost(estimated_usd)
    notes: list[str] = []

    # PR #8 (2026-05-14) — same-provider bias detection. When auditor +
    # target + judge share a provider root (e.g. all openai-codex/gpt-5.x
    # after the PR #6 OAuth alignment), self-preference inflates favor
    # signals and deflates harm signals on the order of −10..−22 %.
    # Surface a chip on the report so reviewers see the disadvantage is
    # acknowledged; downstream score reduction is in
    # ``plugins.petri_audit.bias.apply_disadvantage``.
    from plugins.petri_audit.bias import detect_same_provider, format_bias_chip

    bias_chip = ""
    if detect_same_provider(inspect_auditor, inspect_target, inspect_judge):
        bias_chip = format_bias_chip()
        notes.append(f"same-provider self-preference: {bias_chip}")

    if dry_run:
        notes.append("dry-run: subprocess not executed")
        return AuditReport(
            command=cmd,
            estimated_usd=estimated_usd,
            estimated_krw=estimated_krw,
            dry_run=True,
            notes=notes,
            same_provider_bias_chip=bias_chip,
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
            same_provider_bias_chip=bias_chip,
        )

    # Anthropic auth policy (2026-05-14): API KEY only. Claude Code
    # OAuth tokens are NOT injected into the subprocess — anthropic
    # alignment audits stay on the ``ANTHROPIC_API_KEY`` path so the
    # provider's TOS for OAuth tokens (no programmatic / batch use)
    # is respected. If the env is missing, the subprocess will surface
    # inspect_ai's standard ``environment_prerequisite_error`` and the
    # operator must export a real API key.
    #
    # 본 정책 + OAuth (OpenAI) 의 사용 가능 / 불가 속성 의 SOT:
    # ``docs/audits/2026-05-14-petri-oauth-constraints.md``.
    # 실 검증 (live audit 의 valid baseline 측정) 은 2026-05-25 이후
    # 의 후속 cycle 의 operator credential 결정 의 의존.
    log.info("Petri audit subprocess: %s", " ".join(cmd))
    # ``cmd`` is built solely from validated model ids + numeric flags by
    # build_command — no shell metacharacters or untrusted user strings.
    proc = subprocess.run(  # noqa: S603 — fixed-shape argv, no untrusted input
        cmd,
        text=True,
        capture_output=True,
        check=False,
    )
    archived_raw, archived_summary = _maybe_auto_archive(
        proc.stdout, proc.stderr, auto_archive=auto_archive, notes=notes
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
        archived_raw=archived_raw,
        archived_summary=archived_summary,
        same_provider_bias_chip=bias_chip,
    )


def _extract_eval_log_path(stdout: str, stderr: str) -> str | None:
    """Find the ``Log: <path>`` line inspect_ai prints at end of run.

    inspect_ai's CLI emits exactly one such line per task on stdout
    (or stderr when ``capture_output`` is mixed). The line shape is::

        Log: logs/<ISO-timestamp>_audit_<id>.eval

    or sometimes prefixed with progress whitespace/colour codes. We
    match on ``Log: `` followed by a non-blank token ending in
    ``.eval``. Returns ``None`` when no such line is present (cancel /
    error before the writer flushed).
    """
    import re

    pattern = re.compile(r"Log:\s+(\S+\.eval)\b")
    for stream in (stdout, stderr):
        if not stream:
            continue
        m = pattern.search(stream)
        if m:
            return m.group(1)
    return None


def _maybe_auto_archive(
    stdout: str,
    stderr: str,
    *,
    auto_archive: bool,
    notes: list[str],
) -> tuple[str | None, str | None]:
    """Best-effort: copy raw eval to ``~/.geode/petri/logs/`` + write
    YAML summary. Failure modes (no log line, archive_eval raised) are
    recorded as notes — never raised — so the audit result itself is
    unaffected by archive plumbing.

    Returns ``(raw_path, summary_path)`` strings on success, two
    ``None`` otherwise. Caller stores them on ``AuditReport``.
    """
    if not auto_archive:
        return None, None
    eval_path_str = _extract_eval_log_path(stdout, stderr)
    if eval_path_str is None:
        notes.append("auto-archive skipped: no `Log: …eval` line in subprocess output")
        return None, None
    try:
        from plugins.petri_audit.eval_archive import archive_eval
    except ImportError:  # pragma: no cover — [audit] extra always installed at this branch
        notes.append("auto-archive skipped: [audit] extra not installed")
        return None, None
    try:
        from pathlib import Path

        result = archive_eval(Path(eval_path_str))
    except Exception as exc:  # pragma: no cover — defensive: archive must not fail an audit
        notes.append(f"auto-archive failed: {exc}")
        return None, None
    _import_usage(result.raw_path, notes)
    _append_manifest_line(result.raw_path, result.summary_path, notes)
    return str(result.raw_path), str(result.summary_path)


def _append_manifest_line(raw_path: Path, summary_path: Path, notes: list[str]) -> None:
    """Append one MANIFEST.jsonl line for the just-archived eval.

    Same best-effort contract as :func:`_import_usage` — failure is
    recorded as a note, never raised. Idempotent via archive_sha
    (same file written twice → second call is a no-op).
    """
    try:
        from core.audit.manifest import append_manifest

        entry = append_manifest(raw_path, summary_yaml=summary_path)
    except Exception as exc:  # pragma: no cover — defensive
        notes.append(f"manifest-append failed: {exc}")
        return
    if entry is not None:
        notes.append(f"manifest-append: {entry['archive']} indexed")


def _import_usage(raw_path: Path, notes: list[str]) -> None:
    """Append judge / auditor / target rows from the archived ``.eval``
    to ``~/.geode/usage/<YYYY-MM>.jsonl`` (Defect A F-A2 / 2026-05-11).

    Best-effort and decoupled from archive: any failure is recorded as
    a note on the AuditReport, never raised, so a broken bookkeeping
    path cannot fail the audit. Idempotent — re-importing the same
    archive is a no-op.
    """
    try:
        from core.audit.eval_to_jsonl import extract_to_usage_store

        n = extract_to_usage_store(raw_path)
    except Exception as exc:  # pragma: no cover — defensive
        notes.append(f"usage-import failed: {exc}")
        return
    if n > 0:
        notes.append(f"usage-import: {n} row(s) appended to ~/.geode/usage/")
