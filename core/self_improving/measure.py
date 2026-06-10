"""Audit execution — subprocess command/env assembly, run, result normalisation.

S-5 (2026-06-11) — extracted verbatim from ``core/self_improving/train.py``
(the autoresearch-원형 복원: train.py keeps only the mutation surface +
fixed-budget loop; the measurement gear lives here). Behavior 0-diff —
pinned by the dry-run equivalence test. Mode A agents MUST NOT modify
this module (program.md contract); the tunables stay on train.py and are
read lazily via ``_train()`` so test monkeypatches on the train module
namespace keep working.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.self_improving import fitness as fitness_spec

if TYPE_CHECKING:
    pass

from core.paths import AUTORESEARCH_STATE_DIR as STATE_DIR
from core.paths import LATEST_PETRI_EVAL

log = logging.getLogger(__name__)


def _train():
    """Lazy accessor for the train module's tunables/mutation surface.

    Module-level mutual import would hit the partially-initialized-module
    trap (train imports this module at top level); call-time import is
    safe and preserves ``monkeypatch.setattr(train, ...)`` semantics.
    """
    from core.self_improving import train as _t

    return _t


RUN_TRANSCRIPT_PATH_ENV = "GEODE_RUN_TRANSCRIPT_PATH"

RUN_WORKER_ID_ENV = "GEODE_RUN_WORKER_ID"


def _emit_journal(
    session_id: str,
    gen_tag: str,
    event: str,
    *,
    level: str = "info",
    payload: dict[str, object] | None = None,
) -> None:
    """Emit one RunTranscript event for this audit run.

    P0b — autoresearch event coverage (docs/audits/2026-05-19-
    self-improving-loop-observability-gap.md §4). Centralises the
    RunTranscript lazy-import + payload SoT contract (P0a §6: journal
    events MUST NOT duplicate sessions.jsonl canonical fields). No-op
    when ``session_id`` / ``gen_tag`` are empty (run_audit called from
    tests without them) or when ``core.observability`` is unavailable
    in the import context.

    S6 (async-first transcript isolation, 2026-06-03) — when this process is a
    concurrent campaign worker, ``GEODE_RUN_TRANSCRIPT_PATH`` redirects the
    RunTranscript to an ISOLATED per-worker jsonl (so N concurrent workers never
    race-append the shared home-dir transcript) and ``GEODE_RUN_WORKER_ID``
    stamps ``worker_id`` into every event payload (so the campaign's post-gather
    merge is attributable). Both env vars are absent for the sync standalone
    ``geode audit`` path + the sequential GATE arm — the default home-dir path is
    used and no ``worker_id`` is added, so that behaviour is unchanged.
    """
    if not session_id or not gen_tag:
        return
    try:
        from core.self_improving.loop.run_transcript import RunTranscript
    except ImportError:
        return
    worker_id = os.environ.get(RUN_WORKER_ID_ENV, "").strip()
    emit_payload = dict(payload or {})
    if worker_id:
        emit_payload["worker_id"] = worker_id
    transcript_path: Path | None = None
    raw_path = os.environ.get(RUN_TRANSCRIPT_PATH_ENV, "").strip()
    if raw_path:
        try:
            transcript_path = Path(raw_path)
        except (TypeError, ValueError):
            # Graceful boundary: a malformed env value must NOT crash the audit —
            # fall back to the default home-dir path (the worker simply loses its
            # isolation rather than failing the whole concurrent fan-out).
            transcript_path = None
    RunTranscript(
        session_id=session_id,
        gen_tag=gen_tag,
        component="autoresearch",
        path=transcript_path,
    ).append(event, level=level, payload=emit_payload)


def _hyperparam_int(overrides: dict[str, str], key: str, fallback: int) -> int:
    """Cast a hyperparam SoT value to int, fall back on missing / bad value.

    Mutator's ``parse_mutation`` already validated integer-castability +
    bounds, so the cast normally succeeds. The fallback path covers two
    edge cases:

    1. Operator hand-edited ``hyperparam.json`` to an invalid value
       (typo, wrong type); we don't want the audit subprocess to crash
       — log + use the cfg default.
    2. Key absent from SoT (mutator hasn't touched it yet, or the
       SoT is the post-init default with only a subset of keys);
       cfg default is the right answer.
    """
    raw = overrides.get(key)
    if raw is None:
        return fallback
    try:
        return int(raw)
    except (TypeError, ValueError):
        log.warning(
            "hyperparam SoT %r=%r is not int-castable; falling back to %r",
            key,
            raw,
            fallback,
        )
        return fallback


def _load_hyperparam_overrides() -> dict[str, str]:
    """PR-HYPERPARAM-WIRE (2026-05-28) — read the hyperparam mutation
    SoT and return the override dict, or ``{}`` on absence / parse failure.

    Resolution order matches the other policy SoTs:
      1. ``GEODE_HYPERPARAM_OVERRIDE`` env var (set by the audit subprocess)
      2. ``GLOBAL_HYPERPARAM_POLICY_PATH``
         (``state/autoresearch/policies/hyperparam.json``)

    Return value is a flat ``dict[str, str]`` — same shape as the SoT
    JSON. Caller is responsible for type-casting + bounds validation
    (mutator already validated at parse_mutation; this is the
    runtime-consumer side).

    Returns ``{}`` (graceful) if the file is missing or unreadable so
    the closed-loop default still flows through. Bounds violations
    that survived ``parse_mutation`` / ``apply_mutation`` 's two-layer
    guard would surface as ``ValueError`` from inspect-petri itself
    (its ``max_turns`` solver arg is a positive int).
    """
    env_path = os.environ.get("GEODE_HYPERPARAM_OVERRIDE")
    if env_path:
        path = Path(env_path)
    else:
        from core.paths import GLOBAL_HYPERPARAM_POLICY_PATH

        path = GLOBAL_HYPERPARAM_POLICY_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(k, str)}


def _effective_dim_set() -> str:
    """The dim_set the audit actually runs with — a hyperparam override wins over
    the config default, mirroring the audit-argv precedence below.

    Shared by the audit dispatch AND the baseline-epoch stamping so the stamped
    ``dim_set`` is the one the baseline was MEASURED on, never a stale config
    default (else a ``full``-override run would be stamped ``subset`` and merge
    into a non-comparable epoch).
    """
    cfg = _train()._get_autoresearch_config()
    overrides = _load_hyperparam_overrides()
    return str(overrides.get("dim_set") or getattr(cfg, "dim_set", _train().DIM_SET_NAME))


def _build_audit_command() -> list[str]:
    """Construct the ``geode audit`` subprocess argv.

    Single-SoT (2026-05-22) — the audit role models come from
    ``[self_improving_loop.petri.<role>]`` in ``~/.geode/config.toml``
    via the binding registry inside ``run_audit``. This builder never
    pins ``--target`` / ``--judge`` / ``--auditor`` on the argv;
    omission is the signal the runner uses to consult the per-role
    config. Operators who need an autoresearch-only model edit
    ``[petri.<role>].model`` (the same line standalone
    ``geode audit`` consults), removing the duplicate-SoT layer that
    the previous ``[autoresearch].target_model`` / ``.judge_model``
    fields created.

    Other hyperparameters (``cfg.source``, ``cfg.seed_limit``,
    ``cfg.dim_set``, ``cfg.max_turns``, ``cfg.seed_select``) still
    flow through this builder because they're autoresearch-specific
    (not per-role) — the ``--use-oauth`` flag fires whenever
    ``cfg.source`` is anything other than ``"api_key"``.

    PR-HYPERPARAM-WIRE (2026-05-28) — ``cfg.{seed_limit, dim_set,
    max_turns}`` are now overridable by the mutation SoT at
    ``state/autoresearch/policies/hyperparam.json``. Resolution
    precedence (highest wins): mutation SoT value → autoresearch
    config default. The mutator-proposed values went through
    ``parse_mutation`` 's bounds guard, so by the time they reach
    this argv builder the integer cast is already safe; we still
    fall back to the config default on missing key or stringified
    value that fails int() (defensive — bounds guard is the primary
    layer, this is just so a malformed SoT doesn't crash the closed
    loop). ``reflection_depth`` is NOT wired here — it's a GEODE
    runtime knob (AgenticLoop reflection-iteration cap), not an
    inspect-petri argv, and lands in a follow-up PR.
    """
    cfg = _train()._get_autoresearch_config()
    overrides = _load_hyperparam_overrides()
    effective_seed_limit = _hyperparam_int(overrides, "seed_limit", cfg.seed_limit)
    effective_dim_set = _effective_dim_set()
    effective_max_turns = _hyperparam_int(overrides, "max_turns", cfg.max_turns)
    geode_bin = shutil.which("geode")
    argv = [geode_bin, "audit"] if geode_bin is not None else ["uv", "run", "geode", "audit"]
    argv += [
        "--seed-select",
        _train()._resolve_seed_select(),
        "--seeds",
        str(effective_seed_limit),
        "--dim-set",
        effective_dim_set,
        "--max-turns",
        str(effective_max_turns),
        "--live",
        "--yes",
    ]
    # PR-OL-AUDIT-BURST-FIX (2026-05-22) FIX-1+2 — burst caps are
    # plumbed via ``plugins/petri_audit/runner.py::build_command``
    # (the actual ``inspect eval`` command assembly site). The
    # ``geode audit`` Typer wrapper does NOT accept these flags
    # directly — see plugins/petri_audit/cli_audit.py for the surface.
    # This argv stays unchanged; the inspect_ai connection / sample
    # caps live one layer down.
    if getattr(cfg, "source", "auto") != "api_key":
        argv.append("--use-oauth")
    return argv


def _audit_sampling_params_as_sent() -> dict[str, Any]:
    """The generation params GEODE ACTUALLY sends for the audit (E5 reproducibility pin).

    Records WHAT WAS SENT for auditability — NOT a determinism contract. GEODE's
    audit dispatch is a ``geode audit`` subprocess (:func:`_build_audit_command`)
    that controls only a SUBSET of generation params: ``max_turns`` / ``seeds`` /
    ``dim_set`` / ``source``, and the inspect_ai connection caps
    (``max_connections=1`` / ``max_samples=1``, pinned in
    ``plugins/petri_audit/runner.py:build_command``). These are the resolved
    EFFECTIVE values (mutation-SoT override → config), identical to what
    ``_build_audit_command`` puts on the argv.

    The per-token sampling knobs (``temperature`` / ``top_p`` / ``max_tokens``) are
    NOT pinned by GEODE — they fall to the inspect_ai + provider (claude-cli /
    codex-cli OAuth) defaults — so they are recorded as
    :data:`~core.self_improving.loop.run_provenance.SAMPLING_UNPINNED` rather than a
    fabricated value. This is the honest "GEODE did not set this" record; a future
    PR that pins these knobs (and a ctx7-verified backend-determinism live test)
    would write the real numbers here.
    """
    from core.self_improving.loop.run_provenance import SAMPLING_UNPINNED

    cfg = _train()._get_autoresearch_config()
    overrides = _load_hyperparam_overrides()
    return {
        # GEODE-pinned audit-dispatch params (the resolved effective values).
        "max_turns": _hyperparam_int(overrides, "max_turns", cfg.max_turns),
        "seeds": _hyperparam_int(overrides, "seed_limit", cfg.seed_limit),
        "dim_set": _effective_dim_set(),
        "source": getattr(cfg, "source", "auto"),
        "max_connections": 1,
        "max_samples": 1,
        # Per-token knobs GEODE does not pin → backend default (UNVERIFIED for
        # deterministic replay; see run_provenance module docstring + ctx7 note).
        "temperature": SAMPLING_UNPINNED,
        "top_p": SAMPLING_UNPINNED,
        "max_tokens": SAMPLING_UNPINNED,
    }


def _applied_diff_for_mutation(mutation_id: str) -> tuple[str | None, str | None, str | None]:
    """The scaffold mutation APPLIED this cycle, as a reproducible reference (E5 pin).

    Returns ``(target_section, new_value, target_kind)`` for the
    ``kind="applied"`` row in ``mutations.jsonl`` whose ``mutation_id`` matches the
    cycle's applied mutation — the EXACT content the apply step committed. The
    caller hashes ``new_value`` (``applied_diff_hash``) + records the section + kind
    so the row carries the diff reference without joining the apply row.

    ``("", "", "")``-shaped graceful return — all ``None`` — when ``mutation_id`` is
    empty (manual / no-mutation cycle) or no matching apply row exists (a fresh
    ledger, or the apply row hasn't been written yet). Never raises: a reader-side
    failure must not break the ledger write.
    """
    if not mutation_id:
        return None, None, None
    try:
        from core.self_improving.loop.mutations_reader import read_recent_applies

        for record in reversed(read_recent_applies(n=200)):
            if record.mutation_id == mutation_id:
                return record.target_section, record.new_value, record.target_kind
    except Exception:  # pragma: no cover — defensive; pin simply omitted on failure
        log.warning(
            "self-improving-loop applied-diff lookup failed for mutation %s",
            mutation_id,
            exc_info=True,
        )
    return None, None, None


def _dump_wrapper_override() -> Path:
    """Write the *current* mutation target dict to the runtime-consumed JSON.

    PR-AUDIT-SCAFFOLD-WIRE (2026-05-31) — reads the SoT live via
    :func:`_train().load_wrapper_prompt_sections` rather than the module-load-time
    :data:`_train().WRAPPER_PROMPT_SECTIONS` snapshot. The closed-loop normally
    re-invokes ``core.self_improving.train`` in a fresh subprocess per cycle (so the
    snapshot and the SoT agree), but a same-interpreter caller that mutates
    ``wrapper-sections.json`` and then calls ``run_audit`` would otherwise dump
    the stale pre-mutation scaffold — the audit subprocess would then evaluate
    the OLD scaffold, silently breaking the mutation→fitness causal link. The
    live read makes the dumped override match whatever is on disk right now.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    override = STATE_DIR / "wrapper-override.json"
    override.write_text(
        json.dumps(_train().load_wrapper_prompt_sections(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return override


def _resolve_audit_timeout_sec() -> int:
    """Default per-audit subprocess timeout (seconds).

    ``budget_minutes * 60`` plus a 120s grace — the in-process timeout
    :func:`run_audit` passes to ``subprocess.run``. In the async campaign
    the hang bound is enforced one level UP: each worker is a separate
    ``train.py`` subprocess that the orchestrator kills via
    ``asyncio.wait_for(..., timeout=per_audit_timeout)`` (a TIGHT bound), so a
    hung audit is reaped within seconds of overrun instead of holding for this
    full operator-overridable budget.

    ``budget_minutes`` is operator-supplied config; coerce it through
    ``int`` and fall back to the module ``_train().BUDGET_MINUTES`` default if it is
    non-numeric (graceful boundary at the schema-typed cast).
    """
    raw_budget = _train()._get_autoresearch_config().budget_minutes
    try:
        budget_minutes = int(raw_budget)
    except (TypeError, ValueError):
        budget_minutes = int(_train().BUDGET_MINUTES)
    return budget_minutes * 60 + 120


def _build_audit_env(override_path: Path) -> dict[str, str]:
    """Build the audit subprocess environment (wrapper override + 5-axis SoT).

    Factored out of :func:`run_audit` as a focused, testable helper so the
    strict-mode SoT propagation lives in ONE place. Starts from
    ``os.environ.copy()`` and layers the
    ``GEODE_WRAPPER_OVERRIDE`` path plus every policy-SoT
    ``*_OVERRIDE`` / ``*_STRICT`` pair that has a file on disk.
    """
    env = os.environ.copy()
    env["GEODE_WRAPPER_OVERRIDE"] = str(override_path)
    # ADR-012 S0a/S0b (2026-05-21) — audit subprocess 가 mutation 적용된
    # 5축 SoT 를 strict mode 로 읽도록 env 강제. SoT 파일이 존재할 때만
    # env 를 set 해서 subprocess 가 strict mode 로 동작 (파일 부재 시
    # RuntimeError); SoT 파일이 없으면 env 미설정으로 subprocess 가
    # graceful no-op 경로 (현재 default behaviour 보존). 즉 strict-fail
    # 은 "SoT 가 디스크에 있는데도 subprocess 가 못 읽는 경우" 만 발화 —
    # mutation 이 진행 중인 audit 의 quota 절약 목적.
    from core.paths import (
        GLOBAL_AGENT_CONTRACTS_PATH,
        GLOBAL_CACHE_POLICY_PATH,
        GLOBAL_DECOMPOSITION_POLICY_PATH,
        GLOBAL_FEW_SHOT_POOL_PATH,
        GLOBAL_HEURISTICS_PATH,
        GLOBAL_HYPERPARAM_POLICY_PATH,
        GLOBAL_IN_CONTEXT_SLOTS_PATH,
        GLOBAL_PROVIDER_ROUTING_PATH,
        GLOBAL_REFLECTION_POLICY_PATH,
        GLOBAL_SKILL_CATALOG_PATH,
        GLOBAL_STYLE_GUIDE_PATH,
        GLOBAL_TOOL_DESCRIPTIONS_PATH,
        GLOBAL_TOOL_POLICY_PATH,
    )

    # PR-BACKFILL-SOT (2026-05-21) — audit subprocess sets both _OVERRIDE
    # (path) and _STRICT=1 (fail-fast flag). With the 3-layer SoT chain
    # (env → operator-local → in-repo), env path defaults to graceful for
    # operator daily use; audit explicitly opts into strict for mutation
    # cycle fidelity.
    if GLOBAL_TOOL_POLICY_PATH.is_file():
        env["GEODE_TOOL_POLICY_OVERRIDE"] = str(GLOBAL_TOOL_POLICY_PATH)
        env["GEODE_TOOL_POLICY_STRICT"] = "1"
    if GLOBAL_REFLECTION_POLICY_PATH.is_file():
        env["GEODE_REFLECTION_POLICY_OVERRIDE"] = str(GLOBAL_REFLECTION_POLICY_PATH)
        env["GEODE_REFLECTION_POLICY_STRICT"] = "1"
    if GLOBAL_DECOMPOSITION_POLICY_PATH.is_file():
        env["GEODE_DECOMPOSITION_POLICY_OVERRIDE"] = str(GLOBAL_DECOMPOSITION_POLICY_PATH)
        env["GEODE_DECOMPOSITION_POLICY_STRICT"] = "1"
    # PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27, Codex MCP review fix-up)
    # — three resolution rules together close the dual-SoT drift:
    # (1) honour any env override the caller already set (preserves
    #     ``_run_autoresearch_subprocess`` or an operator already set),
    # (2) when the operator-local file exists, use it (matches the
    #     runtime reader's 3-layer resolution at
    #     ``core/agent/tool_descriptions_policy.py``),
    # (3) fall back to in-repo when neither is set.
    # Matches ``core.self_improving.loop.policies:policy_path`` so
    # mutator R/W + audit R + sibling audit all converge on the same
    # file. Codex MCP review of PR-TOOL-DESCRIPTIONS-MUTATE caught
    # rule (1) — without preserving the caller's env, group sampling's
    # temp SoT would be silently replaced.
    from core.paths import OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH

    if "GEODE_TOOL_DESCRIPTIONS_OVERRIDE" not in env:
        if OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH.is_file():
            env["GEODE_TOOL_DESCRIPTIONS_OVERRIDE"] = str(OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH)
            env["GEODE_TOOL_DESCRIPTIONS_STRICT"] = "1"
        elif GLOBAL_TOOL_DESCRIPTIONS_PATH.is_file():
            env["GEODE_TOOL_DESCRIPTIONS_OVERRIDE"] = str(GLOBAL_TOOL_DESCRIPTIONS_PATH)
            env["GEODE_TOOL_DESCRIPTIONS_STRICT"] = "1"
    if GLOBAL_SKILL_CATALOG_PATH.is_file():
        env["GEODE_SKILL_CATALOG_OVERRIDE"] = str(GLOBAL_SKILL_CATALOG_PATH)
        env["GEODE_SKILL_CATALOG_STRICT"] = "1"
    if GLOBAL_STYLE_GUIDE_PATH.is_file():
        env["GEODE_STYLE_GUIDE_OVERRIDE"] = str(GLOBAL_STYLE_GUIDE_PATH)
        env["GEODE_STYLE_GUIDE_STRICT"] = "1"
    if GLOBAL_PROVIDER_ROUTING_PATH.is_file():
        env["GEODE_PROVIDER_ROUTING_OVERRIDE"] = str(GLOBAL_PROVIDER_ROUTING_PATH)
        env["GEODE_PROVIDER_ROUTING_STRICT"] = "1"
    if GLOBAL_CACHE_POLICY_PATH.is_file():
        env["GEODE_CACHE_POLICY_OVERRIDE"] = str(GLOBAL_CACHE_POLICY_PATH)
        env["GEODE_CACHE_POLICY_STRICT"] = "1"
    if GLOBAL_HEURISTICS_PATH.is_file():
        env["GEODE_HEURISTICS_OVERRIDE"] = str(GLOBAL_HEURISTICS_PATH)
        env["GEODE_HEURISTICS_STRICT"] = "1"
    if GLOBAL_IN_CONTEXT_SLOTS_PATH.is_file():
        env["GEODE_IN_CONTEXT_SLOTS_OVERRIDE"] = str(GLOBAL_IN_CONTEXT_SLOTS_PATH)
        env["GEODE_IN_CONTEXT_SLOTS_STRICT"] = "1"
    if GLOBAL_AGENT_CONTRACTS_PATH.is_file():
        env["GEODE_AGENT_CONTRACTS_OVERRIDE"] = str(GLOBAL_AGENT_CONTRACTS_PATH)
        env["GEODE_AGENT_CONTRACTS_STRICT"] = "1"
    if GLOBAL_FEW_SHOT_POOL_PATH.is_file():
        env["GEODE_FEW_SHOT_POOL_OVERRIDE"] = str(GLOBAL_FEW_SHOT_POOL_PATH)
        env["GEODE_FEW_SHOT_POOL_STRICT"] = "1"
    # PR-HYPERPARAM-FOUNDATION (2026-05-28) — hyperparam SoT path
    # propagation. PR-2 lands the env literal so the sibling-SoT env-map
    # invariant test passes against the 8-kind TARGET_KINDS. The actual
    # consumption — ``plugins/petri_audit/runner.py:build_command``
    # reading the SoT and translating each key to an inspect-petri
    # ``-T`` flag — lands in PR-3 (PR-HYPERPARAM-WIRE). Until then the
    # env var is set but no reader inside the audit subprocess loads it;
    # this is a deliberate 2-PR seam (foundation → wire-through) to
    # keep each PR's scope small.
    if GLOBAL_HYPERPARAM_POLICY_PATH.is_file():
        env["GEODE_HYPERPARAM_OVERRIDE"] = str(GLOBAL_HYPERPARAM_POLICY_PATH)
        env["GEODE_HYPERPARAM_STRICT"] = "1"
    return env


def run_audit(
    dry_run: bool,
    *,
    session_id: str = "",
    gen_tag: str = "",
) -> tuple[
    dict[str, float],
    dict[str, float],
    float,
    float,
    dict[str, int],
    dict[str, str],
    list[dict[str, float]],
    list[dict[str, Any]],
]:
    """Invoke a single audit.

    Returns ``(dim_means, dim_stderr, audit_seconds, total_seconds,
    sample_count, measurement_modality, per_sample, contract_results)``.

    PR-CONTRACT-EVAL (2026-06-03) — the 8th element ``contract_results`` is the
    deterministic tool-call contract ledger
    (``core.audit.contracts.extract_contract_results``) read from this audit's
    ``.eval`` archive. The caller threads it into the promote-gate veto
    (``_hard_contract_violations`` → ``_should_promote(contract_veto=…)``).
    Empty list on dry-run / archive-missing / no-inspect_ai.

    PR-MARGIN-FITNESS-SCALE (2026-05-30) — the 7th element ``per_sample``
    is the sample-indexed dim-value rows (``list[{dim: value}]``) emitted
    by ``dim_extractor``. The caller feeds it to
    :func:`_fitness_stderr_bootstrap` to estimate the fitness-scale stderr
    (gold standard, captures inter-dim correlation) for the promote
    margin. Empty list on dry-run / stdout-only fallback (older subprocess
    builds without the ``per_sample`` key) → the gate falls back to the
    per-dim-independent MC estimate.

    PR-2 of petri-schema-v2 (2026-05-23) — pass through the per-dim
    ``sample_count`` and ``measurement_modality`` fields that
    ``core/audit/dim_extractor.extract_dim_aggregates`` now emits in
    the subprocess stdout summary (PR-1 of the cascade). The caller
    routes them into ``_write_baseline`` so the v2 schema's
    ``raw.sample_count`` + ``raw.measurement_modality`` namespaces
    are populated.

    G2.fix (2026-05-20) — the evidence return slot was dropped: petri's
    ``.eval`` archive (linked through ``~/.geode/petri/logs/latest.eval``)
    is now the single SoT for per-dim evidence. Downstream readers call
    ``extract_evidence`` on the archive on demand instead of receiving a
    promoted-baseline snapshot.

    ``dry_run=True`` skips the subprocess and emits a baseline-flavoured set
    of dim means so the loop scaffolding can be smoke-tested without touching
    LLM quota / API credits. dry-run returns empty ``dim_stderr``,
    ``sample_count``, and ``measurement_modality`` so the stability axis
    falls back to the placeholder constant and the v2 schema records
    no provenance for synthesized data.

    ``session_id`` / ``gen_tag`` are forwarded for RunTranscript emission
    (P0b — wrapper_override_dumped / subprocess_started / subprocess_finished
    / subprocess_timeout events). Both default to empty so unit tests that
    call ``run_audit(dry_run=...)`` directly stay unchanged — emission is
    skipped when either is empty.
    """
    started = time.time()
    override_path = _dump_wrapper_override()
    _emit_journal(
        session_id,
        gen_tag,
        "wrapper_override_dumped",
        payload={"path": str(override_path)},
    )

    if dry_run:
        dim_means = {
            "broken_tool_use": 3.4,
            "input_hallucination": 3.7,
            "overrefusal": 1.0,
            "eval_awareness": 1.0,
            "unprompted_sycophancy": 1.0,
        }
        audit_seconds = 0.0
        total_seconds = time.time() - started
        # dry-run synthesises numeric fitness only — no real .eval is
        # produced so there's nothing for downstream readers to extract
        # evidence from; that's fine, they'll fall through to "no signal".
        # ``sample_count`` and ``measurement_modality`` are empty for the
        # same reason: synthesised numbers have no provenance. ``per_sample``
        # is empty — dry-run has no real per-sample rows to bootstrap from.
        # ``contract_results`` is empty — no real ``.eval`` is produced, so
        # there are no tool-call contracts to evaluate (PR-CONTRACT-EVAL).
        return dim_means, {}, audit_seconds, total_seconds, {}, {}, [], []

    if not _train().WRAPPER_OVERRIDE_HOOK_READY:
        raise RuntimeError(
            "real audit disabled: GEODE_WRAPPER_OVERRIDE is not consumed by core/ yet; "
            "use --dry-run until the runtime hook lands"
        )

    # OL-P2 (2026-05-22) — opt-in quota gate. When the operator-level
    # quota banner is in aborted state (either via credential-resolver
    # trip or via auto-trip on `abort_threshold` breach), refuse to
    # spawn the audit subprocess at all. Cost saving > audit usefulness
    # when quota is exhausted. Graceful: if no banner is installed
    # (non-REPL execution, e.g., CI run), the gate is a no-op.
    try:
        from core.cli.quota_banner import QuotaAbortError, current_banner

        banner = current_banner()
        if banner is not None:
            banner.enforce_or_raise()
    except QuotaAbortError as exc:
        raise RuntimeError(f"autoresearch audit aborted: quota gate tripped — {exc}") from exc
    except ImportError:
        # core.cli is not present in some packaged distros; silent skip.
        pass

    argv = _build_audit_command()
    env = _build_audit_env(override_path)
    timeout_sec = _resolve_audit_timeout_sec()

    _emit_journal(
        session_id,
        gen_tag,
        "subprocess_started",
        payload={"argv_len": len(argv), "timeout_sec": timeout_sec},
    )

    # PR-OL-AUDIT-BURST-FIX (2026-05-22) FIX-3 — inter-process audit
    # lane. Prevents two `geode audit` subprocesses from overlapping
    # on the host (cron-driven + manual collision, REPL + scheduled,
    # etc.). Lane=1 also matches Anthropic Max OAuth's "interactive
    # coding" rate budget when the operator is also using their host
    # Claude Code session.
    from core.orchestration.audit_lane import acquire_audit_lane

    audit_started = time.time()
    lane_key = session_id or "anonymous-audit"
    try:
        with acquire_audit_lane(lane_key):
            try:
                proc = subprocess.run(  # noqa: S603  # nosec B603 — argv built from module constants + shutil.which
                    argv,
                    env=env,
                    cwd=str(_train().REPO_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                _emit_journal(
                    session_id,
                    gen_tag,
                    "subprocess_timeout",
                    level="error",
                    payload={"timeout_sec": timeout_sec},
                )
                raise
    except TimeoutError as exc:
        # Audit lane itself timed out (another audit hogged the lane).
        _emit_journal(
            session_id,
            gen_tag,
            "audit_lane_timeout",
            level="error",
            payload={"reason": str(exc)},
        )
        raise RuntimeError(f"audit lane busy beyond timeout: {exc}") from exc
    audit_seconds = time.time() - audit_started

    return _finalize_audit_result(
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        audit_seconds=audit_seconds,
        started=started,
        session_id=session_id,
        gen_tag=gen_tag,
    )


def _finalize_audit_result(
    *,
    stdout: str,
    stderr: str,
    returncode: int,
    audit_seconds: float,
    started: float,
    session_id: str,
    gen_tag: str,
) -> tuple[
    dict[str, float],
    dict[str, float],
    float,
    float,
    dict[str, int],
    dict[str, str],
    list[dict[str, float]],
    list[dict[str, Any]],
]:
    """Audit post-processing, factored out of :func:`run_audit`.

    Captures everything from the ``subprocess_finished`` event onward as a
    focused, testable helper: the ``subprocess_finished`` journal event, the
    ``_train().RUN_LOG`` write, the
    non-zero-exit ``subprocess_failed`` event + ``RuntimeError`` raise, and the
    eval-log archive extraction (with stdout-JSON fallback). Returns the SAME
    8-tuple both callers expose:
    ``(dim_means, dim_stderr, audit_seconds, total_seconds, sample_count,
    measurement_modality, per_sample, contract_results)``.

    PR-CONTRACT-EVAL (2026-06-03) — the 8th element ``contract_results`` is the
    deterministic tool-call contract ledger
    (``core.audit.contracts.extract_contract_results``), read from the SAME
    ``.eval`` archive the dim aggregates come from. ``[]`` on dry-run /
    archive-missing / no-inspect_ai (graceful no-op).
    """
    _emit_journal(
        session_id,
        gen_tag,
        "subprocess_finished",
        payload={
            "exit_code": returncode,
            "audit_seconds": round(audit_seconds, 3),
        },
    )

    log_text = stdout + "\n--- stderr ---\n" + stderr
    _train().RUN_LOG.write_text(log_text, encoding="utf-8")

    if returncode != 0:
        # PR-MINIMAL-4 (2026-05-21) — non-zero subprocess exit emits an
        # explicit ``subprocess_failed`` event before raising. The
        # earlier ``subprocess_finished`` event carries ``exit_code``
        # but downstream consumers grouping by event name need a
        # *failure-specific* event to alert on; the top-level
        # ``audit_failed`` catches the ``RuntimeError`` but loses the
        # subprocess-specific context (exit_code, run_log path).
        _emit_journal(
            session_id,
            gen_tag,
            "subprocess_failed",
            level="error",
            payload={
                "exit_code": returncode,
                "run_log": str(_train().RUN_LOG),
                "stderr_tail": stderr.splitlines()[-5:] if stderr else [],
            },
        )
        raise RuntimeError(f"audit subprocess exit={returncode}; see {_train().RUN_LOG}")

    # PR-TRAIN-EVAL-ARCHIVE-FALLBACK (2026-05-27) — primary path: read
    # ``dim_means`` / ``dim_stderr`` / provenance directly from the
    # ``.eval`` archive via ``core.audit.dim_extractor``. The audit
    # subprocess's stdout JSON line was the legacy carrier of these
    # aggregates, but any inspect_ai sample-side ``TypeError`` (e.g.
    # ``Object of type Summary is not JSON serializable``) corrupts
    # that final summary line and the parser raises while the eval
    # archive itself is intact. Reading the archive directly makes
    # the closed-loop robust to stdout corruption — the eval archive
    # has been the canonical SoT for downstream readers since PR-G2
    # (2026-05-20) anyway.
    #
    # Fall-through to the stdout JSON when the archive is missing or
    # the extractor itself fails (defense in depth — preserves the
    # legacy code path for environments where the archive symlink
    # isn't wired, e.g. some test fixtures).
    dim_means: dict[str, float] = {}
    dim_stderr: dict[str, float] = {}
    sample_count: dict[str, int] = {}
    measurement_modality: dict[str, str] = {}
    per_sample: list[dict[str, float]] = []
    # PR-CONTRACT-EVAL (2026-06-03) — deterministic tool-call contract ledger,
    # read from the SAME archive as the dim aggregates. Graceful ``[]`` when the
    # archive is absent / unreadable / inspect_ai missing (the extractor never
    # raises). A NON-empty ledger feeds the promote-gate veto downstream.
    contract_results: list[dict[str, Any]] = []

    # Per-worker isolation (Codex MCP HIGH): prefer THIS audit's OWN eval, parsed
    # from its stdout ``Log: <path>.eval`` line, over the global ``latest.eval``
    # symlink. Concurrent async-campaign workers share that symlink (it is
    # GEODE_HOME-keyed, NOT the per-worker ``GEODE_STATE_ROOT``), so a sibling audit
    # finishing between this audit and this read would point it at the WRONG eval.
    # The ``Log:`` filename is unique per audit, so it is unambiguously this one's;
    # the global pointer is the fallback only when no ``Log:`` line was emitted.
    archive_path_str = _eval_path_from_stdout(stdout, stderr) or _resolve_eval_archive_path()
    archive_extracted = False
    if archive_path_str:
        try:
            from core.audit.dim_extractor import extract_dim_aggregates

            agg = extract_dim_aggregates(Path(archive_path_str))
            dim_means = {k: float(v) for k, v in agg.get("dim_means", {}).items()}
            dim_stderr = {k: float(v) for k, v in agg.get("dim_stderr", {}).items()}
            sample_count = {k: int(v) for k, v in agg.get("sample_count", {}).items()}
            measurement_modality = {
                k: str(v) for k, v in agg.get("measurement_modality", {}).items()
            }
            # PR-MARGIN-FITNESS-SCALE — sample-indexed rows for the
            # bootstrap fitness-stderr (gold-standard margin estimate).
            per_sample = [
                {k: float(v) for k, v in row.items()} for row in agg.get("per_sample", [])
            ]
            archive_extracted = bool(dim_means)
        except Exception as exc:
            log.warning(
                "eval archive extract failed at %s (%s); falling back to stdout JSON",
                archive_path_str,
                exc,
                exc_info=True,
            )
        # PR-CONTRACT-EVAL (2026-06-03) — read the contract ledger from the same
        # archive. Independent of the dim-aggregate try-block above so a
        # dim-extract failure does not suppress the contract verdict (and vice
        # versa); the extractor is itself graceful (returns ``[]``, never raises).
        try:
            from core.audit.contracts import extract_contract_results

            contract_results = extract_contract_results(Path(archive_path_str))
        except Exception as exc:
            log.warning(
                "contract extract failed at %s (%s); contract ledger empty",
                archive_path_str,
                exc,
                exc_info=True,
            )

    if not archive_extracted:
        summary_line = next(
            (line for line in reversed(stdout.splitlines()) if line.strip().startswith("{")),
            None,
        )
        if summary_line is None:
            raise RuntimeError(f"audit output missing summary JSON; see {_train().RUN_LOG}")
        summary = json.loads(summary_line)
        dim_means = {k: float(v) for k, v in summary.get("dim_means", {}).items()}
        dim_stderr = {k: float(v) for k, v in summary.get("dim_stderr", {}).items()}
        # PR-2 (2026-05-23) — pass through PR-1 dim_extractor provenance.
        # Older subprocess builds without PR-1 omit these keys; default to
        # empty dicts so callers can detect "no provenance" without crashing.
        sample_count = {k: int(v) for k, v in summary.get("sample_count", {}).items()}
        measurement_modality = {
            k: str(v) for k, v in summary.get("measurement_modality", {}).items()
        }
        # PR-MARGIN-FITNESS-SCALE — per-sample rows from stdout summary when
        # present (older subprocess builds omit the key → empty list → the
        # promote gate falls back to the per-dim-independent MC estimate).
        per_sample = [
            {k: float(v) for k, v in row.items()} for row in summary.get("per_sample", [])
        ]
    total_seconds = time.time() - started
    return (
        dim_means,
        dim_stderr,
        audit_seconds,
        total_seconds,
        sample_count,
        measurement_modality,
        per_sample,
        contract_results,
    )


PETRI_RUBRIC_VERSION = "v3-22dim-PR0"

LATEST_EVAL_SYMLINK = LATEST_PETRI_EVAL  # PR-CLEANUP-D2 anchor alias


def _resolve_eval_archive_path() -> str | None:
    """Return the symlink target of ``latest.eval`` or ``None``.

    PR-2 (2026-05-23) — recorded in baseline.json v2's ``raw.eval_archive``
    so a future replay step can locate the exact archive the promotion
    was scored against. ``None`` when the symlink is missing (dry-run,
    pre-PR-0 install, manual cleanup).
    """
    try:
        if LATEST_EVAL_SYMLINK.is_symlink():
            return str(LATEST_EVAL_SYMLINK.readlink())
        if LATEST_EVAL_SYMLINK.is_file():
            return str(LATEST_EVAL_SYMLINK)
    except OSError:
        return None
    return None


def _eval_path_from_stdout(stdout: str, stderr: str) -> str | None:
    """This audit's OWN ``.eval`` path, parsed from its ``Log: <path>`` line.

    inspect_ai prints exactly one ``Log: logs/<ISO>_audit_<id>.eval`` line per run
    (on stdout, sometimes stderr). That filename is unique per audit, so it is
    race-free across concurrent async-campaign workers — unlike the shared global
    ``latest.eval`` symlink :func:`_resolve_eval_archive_path` reads. A relative
    path is resolved against ``_train().REPO_ROOT`` (the audit subprocess's ``cwd``). Returns
    ``None`` when no ``Log:`` line is present (cancel / error before the writer
    flushed) or the resolved file does not exist, so the caller falls back to the
    legacy global pointer.

    The regex is inlined (not imported from ``plugins.petri_audit.runner``) to keep
    ``core`` free of a ``core → plugins`` import-contract violation.
    """
    pattern = re.compile(r"Log:\s+(\S+\.eval)\b")
    for stream in (stdout, stderr):
        if not stream:
            continue
        match = pattern.search(stream)
        if not match:
            continue
        candidate = Path(match.group(1))
        if not candidate.is_absolute():
            candidate = _train().REPO_ROOT / candidate
        if candidate.exists():
            return str(candidate)
    return None


def score_held_out_bench(
    bench_path: str,
    *,
    dry_run: bool = False,
    session_id: str = "",
    gen_tag: str = "",
    anchor_confidence_mode: bool = False,
) -> tuple[float, dict[str, float], str]:
    """Measure fitness on the VERSION-FROZEN held-out bench — the fixed ruler.

    E2 (2026-05-30). ``bench_path`` is a directory (or selector) of frozen seeds
    that the mutator / seed-generation loop NEVER touches, so the fitness it
    yields is comparable ACROSS generations (unlike the co-evolving
    ``seed_select`` pool, whose fitness is only a within-generation ranking
    signal). This is the value that forms the *evidence curve*.

    Returns ``(held_out_fitness, held_out_dim_means, held_out_bench_id)`` where:

    - ``held_out_fitness`` is the SAME 0-1 :func:`fitness_spec.compute_fitness` the promote
      gate uses (``baseline_means=None`` → the fresh-anchor intrinsic aggregate,
      matching ``_append_baseline_registry_row``'s ``intrinsic_fitness``; no
      cross-baseline critical-floor comparison, which would be spurious against a
      frozen ruler that is by construction a *different* seed set from the
      promoted baseline's pool). The ``anchor_confidence_mode`` flag the gate runs
      under is threaded through so the held-out curve and the baselines it is
      compared against share ONE fitness formula path — when the mode is on, the
      anchor-confidence multiplier applies the same way it does to ``current_raw``:
      the held-out's OWN ``fitness_spec.ANCHOR_DIMS`` subset is passed as ``anchor_means``
      alongside the flag (passing the flag without the subset would silently no-op
      the multiplier, leaving the curve on the mode-off formula). ``baseline_means``
      stays ``None`` (the held-out has no prior baseline → the fresh-anchor
      intrinsic, no cross-baseline floor) and ``admire_means`` is ``None`` (the
      held-out audit produces no admire signal — ``run_audit`` returns dims only).
    - ``held_out_dim_means`` is the per-dim aggregate on the Petri 1-10
      concerning-behaviour scale (lower-is-better dims), straight from
      :func:`run_audit`.
    - ``held_out_bench_id`` is ``seed_pool_content_hash(bench_path)`` — the
      content-addressed identity of the frozen bench, so two runs on the same
      frozen set always carry the same id regardless of mtime / absolute path,
      and a silent edit to the "frozen" set is detectable as an id change.

    The audit runs by overriding ``AUTORESEARCH_SEED_SELECT`` to ``bench_path``
    for the duration of this call only (restored in a ``finally`` so the live
    co-evolving resolution is never left mutated). The override is the same lever
    ``_build_audit_command`` → ``_train()._resolve_seed_select`` already honours, so no new
    argv plumbing is introduced. ``dry_run=True`` produces the synthetic dim set
    (no quota spent) so the wiring is unit-testable.

    CADENCE / WIRING (E2-wire, 2026-05-30): this entry point IS dispatched from
    the live cycle in :func:`main`, once per cycle, gated on
    ``_train()._resolve_held_out_bench()`` being set and ``not dry_run`` (a configured
    bench → score; ``None`` → skip, zero cost, backward-compatible). The operator
    chose EVERY-cycle cadence so the fixed-ruler fitness-vs-generation curve is
    captured every generation; the result is recorded into the per-cycle
    attribution row (``mutations.jsonl`` — the curve SoT) AND, on a promote, the
    baseline registry row.
    """
    from core.self_improving.loop.baseline_epoch import seed_pool_content_hash

    held_out_bench_id = seed_pool_content_hash(bench_path)
    _prior_override = os.environ.get("AUTORESEARCH_SEED_SELECT")
    os.environ["AUTORESEARCH_SEED_SELECT"] = bench_path
    try:
        (
            held_out_dim_means,
            held_out_dim_stderr,
            _audit_seconds,
            _total_seconds,
            _sample_count,
            held_out_modality,
            _per_sample,
            _contract_results,
        ) = run_audit(dry_run, session_id=session_id, gen_tag=gen_tag)
    finally:
        if _prior_override is None:
            os.environ.pop("AUTORESEARCH_SEED_SELECT", None)
        else:
            os.environ["AUTORESEARCH_SEED_SELECT"] = _prior_override
    # Same fitness formula path as the gate's ``current_raw`` (train.py
    # ``_should_promote``) — so the held-out curve and the baselines it is
    # compared against share ONE fitness definition: ``baseline_means=None``
    # (fresh-anchor intrinsic, no cross-baseline floor), modality threaded for the
    # analytics-weight scale, the SHARED ``anchor_confidence_mode`` flag, the
    # held-out's OWN ``fitness_spec.ANCHOR_DIMS`` subset as ``anchor_means`` (the gate extracts
    # the same subset from its current dims — passing ``anchor_confidence_mode``
    # without it would silently no-op the multiplier, leaving the curve on the
    # mode-off formula), and ``admire_means=None`` (the held-out audit emits no
    # admire signal — ``run_audit`` returns dims only).
    held_out_anchor = {
        dim: held_out_dim_means[dim]
        for dim in fitness_spec.ANCHOR_DIMS
        if dim in held_out_dim_means
    }
    held_out_fitness = fitness_spec.compute_fitness(
        held_out_dim_means,
        held_out_dim_stderr,
        baseline_means=None,
        measurement_modality=held_out_modality or None,
        anchor_means=held_out_anchor or None,
        anchor_confidence_mode=anchor_confidence_mode,
        admire_means=None,
    )
    return float(held_out_fitness), held_out_dim_means, held_out_bench_id
