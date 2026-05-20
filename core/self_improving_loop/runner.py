"""Program.md-driven self-improving loop runner.

PR-G5b (2026-05-20). The runner is intentionally thin — every
component it composes already has its own PR + tests:

* ``baseline_reader.load_baseline()`` (G3) — typed BaselineSnapshot.
* ``baseline_reader.load_latest_meta_review()`` (G4) — MetaReviewSnapshot.
* ``autoresearch.train.load_wrapper_prompt_sections()`` (G5a) — SoT load.
* ``autoresearch.train.write_wrapper_prompt_sections()`` (G5a) — SoT write.

What the runner adds:

1. **Context bundling** — fetch the three snapshots into a single
   :class:`RunnerContext` dataclass.
2. **Prompt rendering** — pack the context into the program.md system
   prompt + a structured user message asking for ONE mutation.
3. **LLM dispatch** — call the injected ``llm_call`` callable; the
   default binding reads ``[self_improving_loop.mutator]`` from
   ``~/.geode/config.toml`` and dispatches through
   ``core.llm.router.call_with_failover``.
4. **Response parsing** — extract a :class:`Mutation` from the LLM's
   JSON, validate against the SoT schema.
5. **Apply + audit log** — call ``write_wrapper_prompt_sections`` and
   append the mutation to the git-tracked audit jsonl
   (``autoresearch/state/mutations.jsonl``).
6. **Optional re-run** — when ``rerun=True`` (default ``False`` to
   keep dry-runs cheap), spawn ``autoresearch/train.py`` so the next
   baseline reflects the new wrapper.

Test strategy:

* Unit tests inject a mock ``llm_call`` returning a canned JSON dict.
* No test touches real ``~/.geode/`` — all paths are monkeypatched.
* The autoresearch re-run is wrapped in ``_run_autoresearch_subprocess``
  so tests can monkeypatch the subprocess entirely.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR

log = logging.getLogger(__name__)

__all__ = [
    "MUTATION_AUDIT_LOG_PATH",
    "Mutation",
    "RunnerContext",
    "SelfImprovingLoopRunner",
    "apply_mutation",
    "build_runner_context",
    "parse_mutation",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mutation:
    """One LLM-proposed wrapper-section edit.

    Schema mirrors the LLM response contract (see :func:`_build_user_prompt`).
    ``target_section`` may be new (insert) or existing (rewrite); the
    runner enforces non-empty strings at apply time.
    """

    target_section: str
    new_value: str
    rationale: str
    target_dim: str = ""
    """The regression dim the mutation is aimed at — informational, may
    be empty when the LLM declines to commit to one."""

    def to_audit_row(
        self,
        *,
        previous_value: str,
        timestamp: float | None = None,
        baseline_fitness: float | None = None,
    ) -> dict[str, Any]:
        """Render the mutation as one audit-log row."""
        return {
            "ts": timestamp if timestamp is not None else time.time(),
            "target_section": self.target_section,
            "previous_value": previous_value,
            "new_value": self.new_value,
            "rationale": self.rationale,
            "target_dim": self.target_dim,
            "baseline_fitness": baseline_fitness,
        }


@dataclass
class RunnerContext:
    """Inputs gathered from G2-G4 readers + autoresearch state.

    Held as a plain dataclass (not frozen) so the runner can carry
    additional debug fields without breaking the call site contract.
    """

    baseline_snapshot: Any = None
    meta_review_snapshot: Any = None
    current_sections: dict[str, str] = field(default_factory=dict)
    target_dim: str = ""
    """The dim the runner will focus the mutation on. Picked from
    baseline via ``pick_regression_target_dim`` when present."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


MUTATION_AUDIT_LOG_PATH = (
    Path(__file__).resolve().parents[2] / "autoresearch" / "state" / "mutations.jsonl"
)
"""Git-tracked audit log of every applied mutation.

Lives in-repo (not in ``~/.geode``) because the audit log IS the
git-as-optimiser ledger — each row is committed so the lineage of
wrapper-prompt evolution is replayable from ``git log``. The SoT file
(``~/.geode/self-improving-loop/wrapper-sections.json``) only ever
holds the *current* state; this log holds the *history*.
"""


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------


def build_runner_context() -> RunnerContext:
    """Gather baseline + meta-review + current wrapper sections.

    All three lookups are best-effort — a missing baseline or
    meta-review just means the runner has less context to work with;
    the LLM call can still propose a mutation based on the current
    wrapper sections alone. The auto target_dim picker fires only
    when the baseline is present.
    """
    from autoresearch.train import load_wrapper_prompt_sections
    from plugins.seed_generation.baseline_reader import (
        load_baseline,
        load_latest_meta_review,
        pick_regression_target_dim,
    )

    baseline_snapshot = load_baseline()
    meta_review_snapshot = load_latest_meta_review()
    current_sections = load_wrapper_prompt_sections()
    target_dim = ""
    if baseline_snapshot is not None:
        target_dim = pick_regression_target_dim(baseline_snapshot) or ""
    return RunnerContext(
        baseline_snapshot=baseline_snapshot,
        meta_review_snapshot=meta_review_snapshot,
        current_sections=current_sections,
        target_dim=target_dim,
    )


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


_FALLBACK_SYSTEM_PROMPT = (
    "You are the self-improving-loop mutator for GEODE, an autonomous "
    "execution agent. Your job: read the audit baseline, meta-review "
    "priors, and the current WRAPPER_PROMPT_SECTIONS dict, then propose "
    "ONE single-section mutation that should drive the next audit's "
    "fitness up.\n"
    "\n"
    "Constraints:\n"
    "- Change exactly ONE section. Adding a new section counts; "
    "deleting does not.\n"
    "- New value must be a non-empty single-paragraph string under 600 "
    "characters.\n"
    "- Rationale must cite the specific regression evidence or prior "
    "the mutation responds to.\n"
    "- Respond with a single JSON object — NO prose, NO code fences.\n"
    "\n"
    "Response schema:\n"
    "{\n"
    '  "target_section": "<section key>",\n'
    '  "new_value": "<replacement text>",\n'
    '  "rationale": "<= 200 chars, citing the evidence>",\n'
    '  "target_dim": "<dim name the mutation aims at, or empty>"\n'
    "}\n"
)
"""Inline fallback prompt used when ``autoresearch/program.md`` is unreadable.

Kept as a complete, self-contained string so a `program.md` outage (missing
file, OSError) doesn't take the runner offline. Tests that don't need the
program.md content monkeypatch :func:`_load_program_md` to skip the disk read.
"""


_MUTATION_CONTRACT_SUFFIX = (
    "\n\n"
    "## Mutation Contract (runner-specific, on top of program.md)\n"
    "\n"
    "For THIS invocation, ignore the broader autoresearch loop instructions "
    "in program.md and act as a single-shot mutator with these constraints:\n"
    "\n"
    "- Change exactly ONE section of WRAPPER_PROMPT_SECTIONS. Adding a new "
    "section key counts as a change; deleting does NOT (the runner ignores "
    "deletions).\n"
    "- ``new_value`` must be a non-empty single-paragraph string under 600 "
    "characters.\n"
    "- ``rationale`` must cite the specific regression evidence or "
    "meta-review prior that motivates the change.\n"
    "- Respond with a single JSON object — NO surrounding prose, NO code fences.\n"
    "\n"
    "Response schema:\n"
    "{\n"
    '  "target_section": "<section key>",\n'
    '  "new_value": "<replacement text>",\n'
    '  "rationale": "<= 200 chars, citing the evidence>",\n'
    '  "target_dim": "<dim name the mutation aims at, or empty>"\n'
    "}\n"
)
"""Appended to program.md so the runner can scope it to a single mutation step.

program.md (Karpathy P7 — the agent instruction document) describes the
*overall* self-improving loop: branch creation, multi-iteration ratchet,
fitness measurement etc. This runner is a single-shot step inside that loop
that proposes ONE mutation per invocation. The suffix narrows the broader
contract to the JSON output the parser expects.
"""


def _load_program_md() -> str | None:
    """Read ``autoresearch/program.md`` from disk; return ``None`` on failure.

    Resolves the path relative to the runner module so the lookup works in
    worktrees / installs where ``cwd`` doesn't match the repo root.
    Returns ``None`` (not a raised exception) on missing file / OSError so
    the runner can fall back to the inline prompt without breaking the loop.
    Tests monkeypatch this function to inject canned content.
    """
    program_md_path = Path(__file__).resolve().parents[2] / "autoresearch" / "program.md"
    try:
        return program_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning(
            "self-improving-loop runner: could not read %s (%s); using fallback prompt",
            program_md_path,
            exc,
        )
        return None


def _build_system_prompt() -> str:
    """Compose the system prompt: program.md body + single-mutation contract.

    G5b.fix1.b (2026-05-20) — closes the second of the Codex MCP findings on
    PR-G5b: the runner is now genuinely "program.md-driven" because the
    document is loaded and used at every invocation. When program.md is
    unreadable, the runner falls back to :data:`_FALLBACK_SYSTEM_PROMPT`
    (the previous hardcoded prompt) so the loop never goes offline due to
    a missing/corrupt instruction file.
    """
    program_md = _load_program_md()
    if program_md is None:
        return _FALLBACK_SYSTEM_PROMPT
    return program_md.rstrip() + _MUTATION_CONTRACT_SUFFIX


def _build_user_prompt(ctx: RunnerContext) -> str:
    """Render the per-iteration context as the LLM's user message."""
    from plugins.seed_generation.baseline_reader import (
        format_evidence_block,
        format_priors_block,
    )

    blocks: list[str] = []
    if ctx.baseline_snapshot is not None and ctx.target_dim:
        evidence = format_evidence_block(ctx.baseline_snapshot, ctx.target_dim)
        if evidence:
            blocks.append(evidence)
    if ctx.meta_review_snapshot is not None:
        priors = format_priors_block(ctx.meta_review_snapshot, target_dim=ctx.target_dim)
        if priors:
            blocks.append(priors)
    sections_block = "Current WRAPPER_PROMPT_SECTIONS:\n" + json.dumps(
        ctx.current_sections, indent=2, ensure_ascii=False
    )
    blocks.append(sections_block)
    if ctx.target_dim:
        blocks.append(f"Focus your mutation on improving dim: {ctx.target_dim!r}.")
    blocks.append("Return the JSON mutation object now.")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# LLM call default + response parsing
# ---------------------------------------------------------------------------


LLMCallable = Callable[[str, str], str]
"""Signature: ``llm_call(system_prompt, user_prompt) -> raw response``."""


def _default_llm_call(system_prompt: str, user_prompt: str) -> str:
    """Mutator LLM call routed through ``core.llm.router`` (PR-1 G-A).

    Pre-PR-1 (v0.99.22) this body instantiated ``anthropic.Anthropic()``
    directly and pinned ``model="claude-opus-4-7"`` as a literal —
    paperclip-style abstraction goal: route through the same
    ``call_with_failover`` path every other provider-aware caller uses,
    and read the model id from ``[self_improving_loop.mutator]`` so the
    operator can flip provider/model without editing this file.

    Resolution order:

    1. ``~/.geode/config.toml [self_improving_loop.mutator] default_model``
       (user override).
    2. ``MutatorConfig.default_model`` ship default (``claude-opus-4-7``).

    The model id is routed through ``core.llm.router.call_with_failover``
    so the same credential / provider rotator the agentic loop uses
    also serves the mutator — no second SDK client, no second key
    store.

    Tests inject a mock callable via
    ``SelfImprovingLoopRunner(llm_call=...)`` and skip this code path
    entirely; the lazy SDK imports keep the test cold-start free of
    anthropic.
    """
    import asyncio
    import logging as _logging

    from core.config import _resolve_provider
    from core.config.self_improving_loop import load_self_improving_loop_config
    from core.llm.adapters import resolve_agentic_adapter
    from core.llm.router import call_with_failover

    cfg = load_self_improving_loop_config()
    model = cfg.mutator.default_model
    max_tokens = cfg.mutator.max_tokens
    source = cfg.mutator.source
    role_contract = cfg.mutator.role_contract

    # PR-1 G-A — defensive check kept here even though MutatorConfig's
    # pydantic validator also enforces it: allowed_models is a paperclip-
    # style allow-list (matches petri.role.<X>.allowed_models). A drift
    # between config and validator would fail closed instead of silently
    # calling an unlisted model.
    if cfg.mutator.allowed_models and model not in cfg.mutator.allowed_models:
        raise RuntimeError(
            f"mutator default_model {model!r} is not in MutatorConfig.allowed_models "
            f"{cfg.mutator.allowed_models!r}"
        )

    provider = _resolve_provider(model)
    adapter = resolve_agentic_adapter(provider)

    # PR-1 G-A fix-up — `source` and `role_contract` must affect *something*
    # observable, otherwise they're silent declarative knobs (Codex MCP
    # 2nd-pass review flagged this as a knob-vs-deletion violation). Two
    # surfaces:
    #
    #   (a) telemetry — every mutator call logs (model, provider,
    #       source, role_contract) so a downstream Petri / Inspect
    #       viewer can group runs by operator intent. Same shape as
    #       `core.llm.router._hooks` emit but recorded at the mutator
    #       boundary (the router doesn't know it's serving the mutator
    #       role specifically).
    #
    #   (b) credential-source preference — when the operator picks a
    #       non-`auto` source the runner sets the matching env override
    #       so the petri source resolver (consumed inside the adapter
    #       chain) honours the choice. This stays consistent with the
    #       `forced_login_method` knob (M2) the agentic picker exposes.
    _logging.getLogger("core.self_improving_loop.runner").info(
        "mutator dispatch: model=%s provider=%s source=%s role_contract=%s max_tokens=%d",
        model,
        provider,
        source,
        role_contract,
        max_tokens,
    )
    if source != "auto":
        import os

        os.environ.setdefault("GEODE_MUTATOR_FORCED_SOURCE", source)

    async def _do_call(m: str) -> object:
        return await adapter.agentic_call(
            model=m,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[],
            tool_choice={"type": "auto"},
            max_tokens=max_tokens,
            temperature=0.3,
        )

    # ``call_with_failover`` is the router's async dispatcher (transport
    # layer) — accepts an ordered model list. PR-1 keeps it single-
    # element so the M5 silent-fallback knob default is preserved; an
    # operator who wants the mutator to fall through to alternate models
    # populates ``MutatorConfig.allowed_models`` and the dispatcher's
    # ``models`` list is expanded in a follow-up PR.
    response, _used_model = asyncio.run(call_with_failover([model], _do_call))
    if response is None:
        last_err = getattr(adapter, "last_error", None)
        raise RuntimeError(
            f"mutator LLM call failed (model={model}, provider={provider}): {last_err!r}"
        )

    # Adapter normalises to AgenticResponse — concatenate text blocks.
    text_chunks: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", "")
        if text:
            text_chunks.append(text)
    text = "".join(text_chunks)
    if not text:
        # Empty text is a known anti-pattern surface (``parse_mutation``
        # raises ValueError downstream); callers that catch it can retry,
        # but failing fast here keeps the error message targeted instead
        # of letting JSON parsing carry the blame.
        raise RuntimeError(
            f"mutator LLM call returned empty text "
            f"(model={model}, provider={provider}, used={_used_model!r})"
        )
    return text


def parse_mutation(raw: str) -> Mutation:
    """Extract a :class:`Mutation` from the LLM's raw response.

    The model is instructed to emit a bare JSON object, but defensive
    parsing tolerates leading/trailing whitespace and (rarely) a
    surrounding triple-backtick code fence — strip those before json.loads.

    Raises :class:`ValueError` on missing fields or wrong types so the
    runner can catch + log + skip a malformed iteration without
    crashing the whole loop.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty LLM response")
    text = raw.strip()
    if text.startswith("```"):
        # Strip fence: ```json ... ```
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"LLM response must be a JSON object, got {type(payload).__name__}")
    target_section = payload.get("target_section")
    new_value = payload.get("new_value")
    rationale = payload.get("rationale", "")
    target_dim = payload.get("target_dim", "")
    if not isinstance(target_section, str) or not target_section.strip():
        raise ValueError("target_section must be a non-empty string")
    if not isinstance(new_value, str) or not new_value.strip():
        raise ValueError("new_value must be a non-empty string")
    if not isinstance(rationale, str):
        raise ValueError("rationale must be a string")
    if not isinstance(target_dim, str):
        raise ValueError("target_dim must be a string")
    if len(new_value) > 600:
        raise ValueError(f"new_value length {len(new_value)} exceeds 600 char cap")
    return Mutation(
        target_section=target_section.strip(),
        new_value=new_value,
        rationale=rationale.strip(),
        target_dim=target_dim.strip(),
    )


# ---------------------------------------------------------------------------
# Apply + audit log
# ---------------------------------------------------------------------------


def apply_mutation(
    mutation: Mutation,
    *,
    current_sections: dict[str, str] | None = None,
) -> tuple[dict[str, str], str]:
    """Apply a single-section mutation to the SoT.

    Returns ``(new_sections, previous_value)``. ``previous_value`` is
    the string the mutation replaced (empty for insertions) — captured
    so the audit log can record the diff.

    The SoT write is strict: schema failures raise
    :class:`ValueError` via ``write_wrapper_prompt_sections``.
    """
    from autoresearch.train import load_wrapper_prompt_sections, write_wrapper_prompt_sections

    sections = (
        dict(current_sections) if current_sections is not None else load_wrapper_prompt_sections()
    )
    previous_value = sections.get(mutation.target_section, "")
    sections[mutation.target_section] = mutation.new_value
    write_wrapper_prompt_sections(sections)
    return sections, previous_value


def append_audit_log(
    mutation: Mutation,
    *,
    previous_value: str,
    baseline_fitness: float | None = None,
    log_path: Path | None = None,
) -> Path:
    """Append one mutation row to the git-tracked audit jsonl.

    Returns the path of the audit log so the caller can ``git add``
    it. Best-effort — directory is created if missing.
    """
    target = log_path if log_path is not None else MUTATION_AUDIT_LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    row = mutation.to_audit_row(previous_value=previous_value, baseline_fitness=baseline_fitness)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


# ---------------------------------------------------------------------------
# Git commit + autoresearch re-run
# ---------------------------------------------------------------------------


def _git_commit_audit_log(
    log_path: Path,
    *,
    mutation: Mutation,
    runner: subprocess.CompletedProcess[str] | None = None,
) -> bool:
    """Stage + commit the audit log row.

    Returns ``True`` on success, ``False`` when git is unavailable or
    the commit fails. The runner treats commit failure as
    non-blocking: the SoT is already updated in-place, so the loop's
    correctness boundary is the file write, not the git commit.

    ``runner`` is exposed so tests can inject a mock that records the
    argv without running real git.
    """
    try:
        repo_root = log_path.resolve().parents[1]
        subprocess.run(  # noqa: S603  # nosec B603 — argv = audit-log path
            ["git", "add", str(log_path)],  # noqa: S607  # nosec B607 — git in PATH
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
        commit_message = (
            f"self-improving-loop: mutate '{mutation.target_section}'\n\n"
            f"target_dim: {mutation.target_dim or '(unspecified)'}\n"
            f"rationale: {mutation.rationale}\n"
        )
        subprocess.run(  # noqa: S603  # nosec B603 — commit_message from validated Mutation
            ["git", "commit", "-m", commit_message],  # noqa: S607  # nosec B607 — git in PATH
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.warning("self-improving-loop git commit failed: %s", exc)
        return False
    return True


def _run_autoresearch_subprocess(
    *,
    repo_root: Path,
    dry_run: bool,
) -> subprocess.CompletedProcess[str]:
    """Spawn ``autoresearch/train.py`` for the post-mutation audit.

    Default ``dry_run=True`` keeps the loop cheap during development;
    operators flip to ``dry_run=False`` for a real budget-spending
    audit. The subprocess is non-fatal — failures log + return so the
    runner can record the mutation row even when the audit aborts.
    """
    argv = ["uv", "run", "python", "autoresearch/train.py"]
    if dry_run:
        argv.append("--dry-run")
    return subprocess.run(  # noqa: S603  # nosec B603 — argv built from constants
        argv,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class SelfImprovingLoopRunner:
    """Top-level runner — composes context + LLM + apply + audit + re-run.

    Construction parameters:

    * ``llm_call`` — injected callable. Defaults to
      :func:`_default_llm_call` (reads ``MutatorConfig`` + dispatches
      through ``core.llm.router.call_with_failover``); tests pass a mock.
    * ``audit_log_path`` — override for the audit jsonl location
      (tests).
    * ``commit_enabled`` — when ``False``, skip the git step
      (useful for dry-runs / detached HEAD).
    * ``rerun_enabled`` — when ``False`` (default), skip the
      autoresearch re-run. The next ``geode audit`` invocation picks
      up the new SoT automatically; the re-run flag is opt-in so
      operators control quota spend.
    * ``rerun_dry_run`` — when re-run is enabled, default to
      ``--dry-run`` to keep the loop cheap.
    """

    llm_call: LLMCallable = field(default=_default_llm_call)
    audit_log_path: Path | None = None
    commit_enabled: bool = True
    rerun_enabled: bool = False
    rerun_dry_run: bool = True

    def run_once(self) -> Mutation:
        """Execute one mutation iteration and return the applied :class:`Mutation`.

        The function is the single-iteration unit; callers wrap it in
        a loop (or schedule it via ``geode schedule``) when they want
        a multi-round campaign. Each call:

        1. Builds context (baseline + meta-review + current sections).
        2. Calls the LLM with the system + user prompt.
        3. Parses + validates the mutation.
        4. Applies it to the SoT.
        5. Appends + (optionally) commits the audit log row.
        6. (Optionally) re-runs autoresearch.

        Raises :class:`ValueError` on parse / validation failure so
        the caller can decide whether to retry.
        """
        ctx = build_runner_context()
        original_sections = dict(ctx.current_sections)
        user_prompt = _build_user_prompt(ctx)
        raw_response = self.llm_call(_build_system_prompt(), user_prompt)
        mutation = parse_mutation(raw_response)
        _new_sections, previous_value = apply_mutation(
            mutation, current_sections=ctx.current_sections
        )
        # G5b.fix3 (2026-05-20) — atomicity boundary: if the audit log
        # write fails after the SoT mutation lands, the in-disk state is
        # silently divergent (SoT advanced, history missing). Roll the
        # SoT back to ``original_sections`` so the next iteration sees a
        # consistent state. Best-effort: rollback can itself fail (rare
        # filesystem outage); we log + re-raise the original exception
        # so the caller knows the iteration failed.
        try:
            log_path = append_audit_log(
                mutation,
                previous_value=previous_value,
                log_path=self.audit_log_path,
            )
        except OSError as exc:
            self._rollback_sot(original_sections, mutation=mutation, exc=exc)
            raise
        if self.commit_enabled:
            _git_commit_audit_log(log_path, mutation=mutation)
        if self.rerun_enabled:
            repo_root = log_path.resolve().parents[1]
            self._invoke_autoresearch(repo_root)
        self._append_self_improving_loop_index(mutation, previous_value)
        return mutation

    @staticmethod
    def _rollback_sot(
        original_sections: dict[str, str],
        *,
        mutation: Mutation,
        exc: OSError,
    ) -> None:
        """Restore the SoT to ``original_sections`` after a post-apply failure.

        G5b.fix3 — invoked from ``run_once`` when
        :func:`append_audit_log` raises ``OSError`` *after*
        :func:`apply_mutation` has already written the new sections to
        disk. The SoT must be rolled back to the pre-mutation state so
        the loop never persists a mutation that has no audit-log row;
        otherwise the git-as-optimiser ledger and the live state would
        diverge silently.

        Rollback failure is itself logged but never raised in place of
        the original ``exc`` — the caller already has the more useful
        signal (audit-log write failed).
        """
        try:
            from autoresearch.train import write_wrapper_prompt_sections

            write_wrapper_prompt_sections(original_sections)
            log.error(
                "self-improving-loop runner: audit-log write failed (%s); "
                "SoT rolled back to pre-mutation state for section %r",
                exc,
                mutation.target_section,
            )
        except Exception:  # pragma: no cover — defensive
            log.exception(
                "self-improving-loop runner: audit-log write failed (%s) AND "
                "rollback failed — SoT may be in a divergent state for "
                "section %r",
                exc,
                mutation.target_section,
            )

    def _invoke_autoresearch(self, repo_root: Path) -> None:
        """Wrap the autoresearch subprocess so tests can override."""
        try:
            _run_autoresearch_subprocess(repo_root=repo_root, dry_run=self.rerun_dry_run)
        except Exception:  # pragma: no cover — defensive
            log.warning("self-improving-loop autoresearch re-run failed", exc_info=True)

    @staticmethod
    def _append_self_improving_loop_index(mutation: Mutation, previous_value: str) -> None:
        """Best-effort append to the shared session index.

        Lets the existing ``~/.geode/self-improving-loop/sessions.jsonl``
        registry (P1a) carry one row per mutator invocation so external
        consumers can see the mutator alongside seed-generation /
        autoresearch runs.
        """
        index_path = GLOBAL_SELF_IMPROVING_LOOP_DIR / "sessions.jsonl"
        try:
            GLOBAL_SELF_IMPROVING_LOOP_DIR.mkdir(parents=True, exist_ok=True)
            row = {
                "ts": time.time(),
                "component": "self-improving-loop-mutator",
                "target_section": mutation.target_section,
                "target_dim": mutation.target_dim,
                "rationale": mutation.rationale,
                "previous_value_len": len(previous_value),
                "new_value_len": len(mutation.new_value),
            }
            with index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            log.debug("self-improving-loop sessions.jsonl append failed", exc_info=True)
