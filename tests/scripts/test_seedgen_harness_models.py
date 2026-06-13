"""Guard: seed-gen table chips reflect the run's REAL models, not a hardcode.

A seed-gen run is multi-model (a Claude drafter/evolver + gpt-5.5 critics). The
hub formerly hardcoded a single ``claude-cli/claude-opus-4-7`` chip in every
seedgen row/detail, so a run executed with opus-4-8 + gpt-5.5 was mislabeled as
"Claude Code" on the wrong version, hiding the Codex half (operator report:
``payg:opus-4-8`` / ``payg:gpt-5-5`` runs shown as "claude code"). The fix
derives ``harness_models`` from each run's ``sub_agents/*/`` and renders one
chip per actual model.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_seeds_listing import _build_row, _run_harness_models
from scripts.build_self_improving_hub import seedgen_harness_chips


def _make_subagent(parent: Path, name: str, model: str, provider: str, *, cli: bool) -> None:
    agent = parent / "sub_agents" / name
    agent.mkdir(parents=True)
    (agent / "dialogue.jsonl").write_text(
        json.dumps({"event": "session_start", "model": model, "provider": provider}) + "\n",
        encoding="utf-8",
    )
    session: dict[str, object] = {}
    if cli:
        session["claude_cli_session_id"] = "sess-abc"
    (agent / "session.json").write_text(json.dumps(session), encoding="utf-8")


def test_run_harness_models_derives_distinct_multi_model(tmp_path: Path) -> None:
    run = tmp_path / "gen-x-broken_tool_use"
    run.mkdir()
    # Claude drafter via Claude Code CLI + gpt-5.5 critics via codex + a PAYG lane
    _make_subagent(run, "evolve-0", "claude-opus-4-8", "anthropic", cli=True)
    _make_subagent(run, "critic-0", "gpt-5.5", "openai-codex", cli=False)
    _make_subagent(run, "critic-1", "gpt-5.5", "openai-codex", cli=False)  # dup collapses
    _make_subagent(run, "draft-0", "claude-opus-4-8", "anthropic", cli=False)

    models = _run_harness_models(run)

    # cli → claude-cli prefix; bare provider otherwise; duplicates collapse.
    # (Order is deterministic by sub-agent dir name; assert the SET so the
    # guard doesn't pin to fake fixture dir-naming.)
    assert set(models) == {
        "claude-cli/claude-opus-4-8",
        "openai-codex/gpt-5.5",
        "anthropic/claude-opus-4-8",
    }
    assert len(models) == 3  # the gpt-5.5 duplicate collapsed


def test_no_subagents_returns_empty(tmp_path: Path) -> None:
    run = tmp_path / "gen-empty"
    run.mkdir()
    assert _run_harness_models(run) == []


def test_build_row_includes_harness_models(tmp_path: Path) -> None:
    run = tmp_path / "gen-y-broken_tool_use"
    run.mkdir()
    (run / "state.json").write_text(
        json.dumps({"run_id": "gen-y", "gen_tag": "gen-y", "target_dim": "broken_tool_use"}),
        encoding="utf-8",
    )
    _make_subagent(run, "critic-0", "gpt-5.5", "openai-codex", cli=False)
    row = _build_row(run)
    assert row is not None
    assert row["harness_models"] == ["openai-codex/gpt-5.5"]


def test_chips_render_real_models_not_hardcoded_claude_code() -> None:
    html = seedgen_harness_chips(
        ["claude-cli/claude-opus-4-8", "openai-codex/gpt-5.5", "anthropic/claude-opus-4-8"]
    )
    # the actual models appear...
    assert "claude-opus-4-8" in html
    assert "gpt-5.5" in html
    # ...with the right chips: Claude Code (cli), Codex (codex), PAYG (anthropic)
    assert "Claude Code" in html
    assert "Codex" in html
    assert "PAYG" in html
    # regression: the former hardcoded wrong version must NOT appear
    assert "claude-opus-4-7" not in html


def test_chips_empty_degrades_to_muted_dot() -> None:
    assert seedgen_harness_chips([]) == '<span class="muted">.</span>'
