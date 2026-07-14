"""``geode session`` CLI surface tests — list + export.

Fixtures go through the real ``SessionCheckpoint.save()`` API (state.json +
SQLite ``sessions.db`` mirror) so both the index-backed list path and the
DB-first ``load()`` path in export are exercised end-to-end. The sub-app is
invoked directly (no full ``core.cli`` bootstrap needed per test).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from core.cli.typer_session import session_app
from core.memory.session_checkpoint import SessionCheckpoint, SessionState
from typer.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _default_messages() -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": "compare <script>alert(1)</script> options"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking that up."},
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "web_search",
                    "input": {"query": "geode"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "search result body"}
            ],
        },
        {"role": "assistant", "content": "Done — <b>bold</b> answer."},
    ]


def _save_session(
    base: Path,
    session_id: str,
    *,
    messages: list[dict[str, Any]] | None = None,
    user_input: str = "compare options",
    status: str = "paused",
) -> None:
    checkpoint = SessionCheckpoint(base)
    state = SessionState(
        session_id=session_id,
        round_idx=3,
        model="claude-fable-5",
        provider="anthropic",
        status=status,
        messages=messages if messages is not None else _default_messages(),
        user_input=user_input,
    )
    checkpoint.save(state)


# ---------------------------------------------------------------------------
# geode session list
# ---------------------------------------------------------------------------


def test_list_shows_sessions_from_index(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-alpha", user_input="first request text")
    _save_session(tmp_path, "sess-beta", user_input="second request text")
    assert (tmp_path / "sessions.db").exists()  # index path is the one exercised

    result = runner.invoke(session_app, ["list", "--sessions-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "SESSION_ID" in result.output
    assert "sess-alpha" in result.output
    assert "sess-beta" in result.output
    assert "claude-fable-5" in result.output
    assert "paused" in result.output
    assert "first request text" in result.output
    assert "2 session(s)" in result.output


def test_list_falls_back_to_directory_scan_when_db_missing(
    runner: CliRunner, tmp_path: Path
) -> None:
    _save_session(tmp_path, "sess-scan", user_input="scanned session")
    for db_file in tmp_path.glob("sessions.db*"):
        db_file.unlink()

    result = runner.invoke(session_app, ["list", "--sessions-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "sess-scan" in result.output
    assert "scanned session" in result.output


def test_list_empty_dir(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(session_app, ["list", "--sessions-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "No sessions found" in result.output


def test_list_truncates_long_user_input(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-long", user_input="x" * 300)
    result = runner.invoke(session_app, ["list", "--sessions-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "x" * 300 not in result.output
    assert "x" * 59 + "…" in result.output


# ---------------------------------------------------------------------------
# geode session export — html
# ---------------------------------------------------------------------------


def test_export_html_escapes_content_and_labels_roles(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-html")
    out = tmp_path / "export" / "session.html"

    result = runner.invoke(
        session_app,
        ["export", "sess-html", "--sessions-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert str(out.resolve()) in result.output

    doc = out.read_text(encoding="utf-8")
    # Raw markup from message content must never survive unescaped.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in doc
    assert "<script>alert(1)</script>" not in doc
    assert "&lt;b&gt;bold&lt;/b&gt;" in doc
    # Uppercase text role labels.
    assert ">USER<" in doc
    assert ">ASSISTANT<" in doc
    # Tool call + result rendered as labeled monospace blocks.
    assert "TOOL CALL web_search" in doc
    assert "TOOL RESULT" in doc
    assert "search result body" in doc
    assert "&quot;query&quot;: &quot;geode&quot;" in doc
    # Header metadata.
    assert "claude-fable-5" in doc
    assert "anthropic" in doc
    assert "sess-html" in doc


def test_export_default_out_name_html(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-default")
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        result = runner.invoke(
            session_app, ["export", "sess-default", "--sessions-dir", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert (Path(cwd) / "geode-session-sess-default.html").exists()


# ---------------------------------------------------------------------------
# geode session export — md
# ---------------------------------------------------------------------------


def test_export_md_variant(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-md")
    out = tmp_path / "session.md"

    result = runner.invoke(
        session_app,
        ["export", "sess-md", "--sessions-dir", str(tmp_path), "--fmt", "md", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output

    doc = out.read_text(encoding="utf-8")
    assert doc.startswith("# GEODE session sess-md")
    assert "\nUSER\n" in doc
    assert "\nASSISTANT\n" in doc
    assert "TOOL CALL web_search" in doc
    assert "````" in doc
    assert "search result body" in doc
    assert "<div" not in doc


def test_export_rejects_unknown_fmt(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-fmt")
    result = runner.invoke(
        session_app,
        ["export", "sess-fmt", "--sessions-dir", str(tmp_path), "--fmt", "pdf"],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# id resolution + edge cases
# ---------------------------------------------------------------------------


def test_export_unknown_id_exits_1(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-known")
    result = runner.invoke(session_app, ["export", "nope", "--sessions-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No session matching" in result.output


def test_export_ambiguous_prefix_lists_candidates(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-aa-one")
    _save_session(tmp_path, "sess-aa-two")
    result = runner.invoke(session_app, ["export", "sess-aa", "--sessions-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "Ambiguous" in result.output
    assert "sess-aa-one" in result.output
    assert "sess-aa-two" in result.output


def test_export_unique_prefix_resolves(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-unique-abcdef")
    _save_session(tmp_path, "other-session")
    out = tmp_path / "resolved.html"
    result = runner.invoke(
        session_app,
        ["export", "sess-uni", "--sessions-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "sess-unique-abcdef" in out.read_text(encoding="utf-8")


def test_export_zero_message_session(runner: CliRunner, tmp_path: Path) -> None:
    _save_session(tmp_path, "sess-empty", messages=[], user_input="never ran")
    out = tmp_path / "empty.html"
    result = runner.invoke(
        session_app,
        ["export", "sess-empty", "--sessions-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    doc = out.read_text(encoding="utf-8")
    assert "No messages recorded" in doc
    assert "sess-empty" in doc


def test_export_redacts_api_keys(runner: CliRunner, tmp_path: Path) -> None:
    secret = "sk-ant-" + "a" * 24
    _save_session(
        tmp_path,
        "sess-secret",
        messages=[{"role": "user", "content": f"my key is {secret}"}],
    )
    out = tmp_path / "secret.html"
    result = runner.invoke(
        session_app,
        ["export", "sess-secret", "--sessions-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    doc = out.read_text(encoding="utf-8")
    assert secret not in doc
    assert "[REDACTED]" in doc


# ---------------------------------------------------------------------------
# wiring — sub-app registered on the main Typer app
# ---------------------------------------------------------------------------


def test_session_group_registered_on_main_app(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["session", "--help"])
    assert result.exit_code == 0, result.output
    assert "list" in result.output
    assert "export" in result.output
