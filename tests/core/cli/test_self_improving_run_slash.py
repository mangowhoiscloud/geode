"""PR-OPS-2a — invariants for ``/self-improving run`` slash + the
``SelfImprovingLoopRunner.propose`` / ``apply_proposal`` split.

Pins:
- propose() returns a Proposal but does NOT write to the SoT
- apply_proposal(propose()) is observationally equivalent to run_once()
- /self-improving run wires the dispatcher (parses flags, calls
  propose/apply_proposal, records y/N/abort, runs N iterations)
- --dry-run skips apply
- --target-kind filter rejects non-matching proposals
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# propose() / apply_proposal() split — runner.py
# ---------------------------------------------------------------------------


def _stub_llm_response(mutation_dict: dict[str, Any]) -> str:
    """JSON-shape LLM response the parser accepts."""
    return json.dumps(mutation_dict)


def _build_test_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    target_section: str = "role.intro",
    new_value: str = "You are improved.",
    target_kind: str = "prompt",
) -> Any:
    """Construct a SelfImprovingLoopRunner with a canned LLM response
    and a tmp_path-redirected audit log + SoT."""
    from core.self_improving.loop.mutate import runner as runner_mod

    audit_path = tmp_path / "state" / "mutations.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _fake_llm(_sys: str, _user: str) -> str:
        return _stub_llm_response(
            {
                "target_section": target_section,
                "new_value": new_value,
                "rationale": "test rationale",
                "target_kind": target_kind,
            }
        )

    def _fake_context() -> Any:
        from core.self_improving.loop.mutate.runner import RunnerContext

        return RunnerContext(current_sections={"role.intro": "You are baseline."})

    monkeypatch.setattr(runner_mod, "build_runner_context", _fake_context)

    # Redirect prompt SoT writer + reader for the test.
    sections_path = tmp_path / "sot" / "wrapper-sections.json"
    sections_path.parent.mkdir(parents=True, exist_ok=True)

    def _fake_write(sections: dict[str, str]) -> None:
        sections_path.write_text(json.dumps(sections), encoding="utf-8")

    monkeypatch.setattr("core.self_improving.train.write_wrapper_prompt_sections", _fake_write)

    return runner_mod.SelfImprovingLoopRunner(
        llm_call=_fake_llm,
        commit_enabled=False,
        rerun_enabled=False,
        audit_log_path=audit_path,
    )


def test_propose_returns_proposal_with_unmutated_target_sections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """propose() must build context + parse mutation + load SoT WITHOUT
    writing. The target_sections dict and original_sections dict carry
    the same key/value pairs at this point."""
    runner = _build_test_runner(monkeypatch, tmp_path)
    proposal = runner.propose()
    assert proposal.mutation.target_section == "role.intro"
    assert proposal.mutation.new_value == "You are improved."
    # original_sections is the pre-write snapshot
    assert proposal.original_sections == {"role.intro": "You are baseline."}
    # target_sections starts equal to original
    assert proposal.target_sections == proposal.original_sections
    # IDs must differ — apply_mutation mutates target_sections in place
    assert proposal.target_sections is not proposal.original_sections


def test_propose_does_not_write_sot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """propose() must NOT touch the SoT — write path runs only in
    apply_proposal."""
    runner = _build_test_runner(monkeypatch, tmp_path)
    sections_path = tmp_path / "sot" / "wrapper-sections.json"
    assert not sections_path.exists()
    runner.propose()
    assert not sections_path.exists(), "propose() must not write SoT"


def test_propose_does_not_write_audit_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = _build_test_runner(monkeypatch, tmp_path)
    audit_path = tmp_path / "state" / "mutations.jsonl"
    assert not audit_path.exists()
    runner.propose()
    assert not audit_path.exists(), "propose() must not write audit log"


def test_apply_proposal_writes_sot_and_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """apply_proposal() writes the SoT, then the audit log."""
    runner = _build_test_runner(monkeypatch, tmp_path)
    proposal = runner.propose()
    sections_path = tmp_path / "sot" / "wrapper-sections.json"
    audit_path = tmp_path / "state" / "mutations.jsonl"
    assert not sections_path.exists()
    assert not audit_path.exists()
    mutation = runner.apply_proposal(proposal)
    assert sections_path.exists(), "apply_proposal must write SoT"
    assert audit_path.exists(), "apply_proposal must write audit log"
    assert mutation.target_section == "role.intro"


def test_run_once_equals_propose_plus_apply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The backward-compat wrapper composes propose + apply_proposal.
    Both end states must match."""
    runner = _build_test_runner(monkeypatch, tmp_path)
    mutation = runner.run_once()
    assert mutation.target_section == "role.intro"
    sections_path = tmp_path / "sot" / "wrapper-sections.json"
    audit_path = tmp_path / "state" / "mutations.jsonl"
    assert sections_path.exists()
    assert audit_path.exists()


def test_proposal_in_runner_all_exports() -> None:
    """``Proposal`` must be exported alongside ``Mutation`` /
    ``SelfImprovingLoopRunner`` so external callers can type-annotate
    against it."""
    from core.self_improving.loop.mutate import runner

    assert "Proposal" in runner.__all__


# ---------------------------------------------------------------------------
# /self-improving run — flag parser
# ---------------------------------------------------------------------------


def test_parse_run_opts_defaults() -> None:
    from core.cli.commands.self_improving import _parse_run_opts

    flags = _parse_run_opts([])
    assert flags == {"dry_run": False, "iterations": 1, "target_kind": ""}


def test_parse_run_opts_dry_run() -> None:
    from core.cli.commands.self_improving import _parse_run_opts

    flags = _parse_run_opts(["--dry-run"])
    assert flags is not None
    assert flags["dry_run"] is True


@pytest.mark.parametrize(
    "tok_seq, expected_n",
    [(["--n", "5"], 5), (["--n=3"], 3), (["--n", "10"], 10)],
)
def test_parse_run_opts_iterations(tok_seq: list[str], expected_n: int) -> None:
    from core.cli.commands.self_improving import _parse_run_opts

    flags = _parse_run_opts(tok_seq)
    assert flags is not None
    assert flags["iterations"] == expected_n


def test_parse_run_opts_iterations_out_of_range(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from core.cli.commands.self_improving import _parse_run_opts

    assert _parse_run_opts(["--n", "0"]) is None
    assert _parse_run_opts(["--n", "11"]) is None
    out = capsys.readouterr().out
    assert "1 ~ 10" in out


@pytest.mark.parametrize(
    "kind",
    # ADR-012 S0d (2026-05-21) — retrieval deprecated. 4 active kinds.
    ["prompt", "tool_policy", "decomposition", "reflection"],
)
def test_parse_run_opts_target_kind_valid(kind: str) -> None:
    from core.cli.commands.self_improving import _parse_run_opts

    flags = _parse_run_opts(["--target-kind", kind])
    assert flags is not None
    assert flags["target_kind"] == kind


def test_parse_run_opts_target_kind_retrieval_rejected_post_s0d() -> None:
    """ADR-012 S0d — retrieval 은 더 이상 valid CLI target_kind 아님."""
    from core.cli.commands.self_improving import _parse_run_opts

    flags = _parse_run_opts(["--target-kind", "retrieval"])
    assert flags is None, "retrieval 은 S0d 후 deprecated — CLI parsing 이 거부해야 함"


def test_parse_run_opts_target_kind_invalid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from core.cli.commands.self_improving import _parse_run_opts

    assert _parse_run_opts(["--target-kind", "nonsense"]) is None
    out = capsys.readouterr().out
    assert "must be one of" in out


def test_parse_run_opts_unknown_flag_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from core.cli.commands.self_improving import _parse_run_opts

    assert _parse_run_opts(["--bogus"]) is None
    out = capsys.readouterr().out
    assert "unknown flag" in out


# ---------------------------------------------------------------------------
# /self-improving run — dispatch + iteration
# ---------------------------------------------------------------------------


def _stub_runner_with_proposal(
    target_kind: str = "prompt",
) -> tuple[Any, Any]:
    """Build a mock SelfImprovingLoopRunner that returns a canned
    proposal and tracks apply_proposal calls."""
    from core.self_improving.loop.mutate.runner import Mutation, Proposal

    mutation = Mutation(
        target_section="role.intro",
        new_value="improved",
        rationale="test",
        target_kind=target_kind,
    )
    proposal = Proposal(
        mutation=mutation,
        target_sections={"role.intro": "baseline"},
        original_sections={"role.intro": "baseline"},
        baseline_fitness=0.7,
    )
    runner = MagicMock()
    runner.audit_log_path = Path("/tmp/dummy.jsonl")  # noqa: S108 — test stub
    runner.propose.return_value = proposal
    runner.apply_proposal.return_value = mutation
    return runner, proposal


def test_cmd_run_dry_run_skips_apply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from core.cli.commands import self_improving

    runner, _ = _stub_runner_with_proposal()
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    self_improving._cmd_run(["--dry-run"])
    runner.propose.assert_called_once()
    runner.apply_proposal.assert_not_called()
    out = capsys.readouterr().out
    assert "--dry-run" in out
    assert "improved" in out


def test_cmd_run_target_kind_filter_skips_mismatched(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--target-kind=tool_policy with an LLM that proposes 'prompt'
    must skip the iteration WITHOUT applying."""
    from core.cli.commands import self_improving

    runner, _ = _stub_runner_with_proposal(target_kind="prompt")
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    self_improving._cmd_run(["--target-kind", "tool_policy"])
    runner.propose.assert_called_once()
    runner.apply_proposal.assert_not_called()
    out = capsys.readouterr().out
    assert "skipping" in out


def test_cmd_run_confirm_y_applies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from core.cli.commands import self_improving

    runner, _ = _stub_runner_with_proposal()
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    monkeypatch.setattr(self_improving, "_prompt_confirmation", lambda _p: "apply")
    self_improving._cmd_run([])
    runner.apply_proposal.assert_called_once()
    out = capsys.readouterr().out
    assert "applied" in out


def test_cmd_run_confirm_n_records_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rejection must NOT call apply_proposal AND must append a
    kind=rejected row to the audit log."""
    from core.cli.commands import self_improving

    runner, _ = _stub_runner_with_proposal()
    audit_path = tmp_path / "mutations.jsonl"
    runner.audit_log_path = audit_path
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    monkeypatch.setattr(self_improving, "_prompt_confirmation", lambda _p: "reject")
    self_improving._cmd_run([])
    runner.apply_proposal.assert_not_called()
    assert audit_path.exists()
    rows = [json.loads(line) for line in audit_path.read_text().splitlines() if line]
    assert any(r["kind"] == "rejected" for r in rows)
    out = capsys.readouterr().out
    assert "rejected" in out


def test_cmd_run_confirm_n_with_default_audit_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Codex MCP catch (2026-05-21 PR #1395): the real ``_build_runner``
    constructs ``SelfImprovingLoopRunner`` without ``audit_log_path``,
    so it defaults to ``None``. ``_record_rejection`` must fall back
    to ``MUTATION_AUDIT_LOG_PATH`` rather than crash on
    ``Path(None)``. Pin the fallback so a refactor that drops it
    surfaces here."""
    from core.cli.commands import self_improving

    runner, _ = _stub_runner_with_proposal()
    runner.audit_log_path = None  # default value the real slash uses
    fake_default = tmp_path / "fallback_mutations.jsonl"
    monkeypatch.setattr(
        "core.self_improving.loop.mutate.runner.MUTATION_AUDIT_LOG_PATH",
        fake_default,
    )
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    monkeypatch.setattr(self_improving, "_prompt_confirmation", lambda _p: "reject")
    self_improving._cmd_run([])
    runner.apply_proposal.assert_not_called()
    assert fake_default.exists(), "rejection must fall back to MUTATION_AUDIT_LOG_PATH"
    out = capsys.readouterr().out
    assert "rejected" in out


def test_cmd_run_abort_breaks_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """User-initiated abort (EOF / Ctrl-D) must stop the iteration loop
    without calling apply_proposal."""
    from core.cli.commands import self_improving

    runner, _ = _stub_runner_with_proposal()
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    monkeypatch.setattr(self_improving, "_prompt_confirmation", lambda _p: "abort")
    self_improving._cmd_run(["--n", "3"])
    # Even though --n=3 was requested, abort breaks after the first
    runner.propose.assert_called_once()
    runner.apply_proposal.assert_not_called()
    out = capsys.readouterr().out
    assert "aborted" in out


def test_cmd_run_propose_failure_breaks_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from core.cli.commands import self_improving

    runner = MagicMock()
    runner.propose.side_effect = ValueError("LLM parse failure")
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    self_improving._cmd_run([])
    out = capsys.readouterr().out
    assert "propose failed" in out
    assert "LLM parse failure" in out


# ---------------------------------------------------------------------------
# Slash dispatch — 'run' routes to _cmd_run
# ---------------------------------------------------------------------------


def test_run_action_dispatches_to_cmd_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.cli.commands import self_improving

    called: list[list[str]] = []
    monkeypatch.setattr(self_improving, "_cmd_run", lambda opts: called.append(opts))
    self_improving.cmd_self_improving("run --dry-run --n 2")
    assert called == [["--dry-run", "--n", "2"]]


def test_deferred_actions_set_now_empty() -> None:
    """PR-PAPERCLIP wired ``config`` to the interactive settings form,
    so the deferred set is now empty. ``run`` / ``history`` /
    ``rollback`` were wired in earlier PRs (OPS-2a / MINIMAL-1)."""
    from core.cli.commands.self_improving import (
        _RUN_DEFAULT_ITERATIONS,
        _RUN_DEFERRED_ACTIONS,
        _RUN_MAX_ITERATIONS,
    )

    assert frozenset() == _RUN_DEFERRED_ACTIONS
    assert _RUN_DEFAULT_ITERATIONS == 1
    assert _RUN_MAX_ITERATIONS == 10
