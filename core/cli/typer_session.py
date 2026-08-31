"""CLI subcommand: ``geode session`` — inspect and migrate session records.

Source-of-truth decision
------------------------
``export`` reads exclusively from the session *checkpoint* store
(:class:`core.memory.session_checkpoint.SessionCheckpoint`): ``state.json``
carries the header metadata and ``SessionCheckpoint.load()`` returns the
full conversation (SQLite ``messages`` table SoT, with the ``messages.json``
hot-cache fallback handled inside ``load()`` itself). The transcript JSONL
stream (``core/observability/transcript.py``) is intentionally NOT
consulted: the checkpoint already contains every message including
``tool_use`` / ``tool_result`` blocks, and a single-source render stays
deterministic — no cross-source merge or ordering questions.

``list`` prefers the SQLite index (``<sessions>/sessions.db`` via
:class:`core.memory.session_manager.SessionManager`) and falls back to a
directory scan over ``<sessions>/<id>/state.json`` when the index database
is missing.

``migrate-records`` is the explicit, lossless bridge from deprecated global
JSONL transcripts into ``sessions.db:session_events``. ``export-trajectory``
derives the versioned evaluation artifact from that canonical history.
``stage-trajectory-release`` validates a reviewed allowlist into an immutable,
digest-bound directory ready for an artifact-repository PR.

Redaction: :func:`core.observability.redaction.redact_secrets` is applied to
every exported text body (header fields included), *before* truncation so a
cut-off block can never expose a partial key. That helper is pattern-based
(known API-key shapes only) — arbitrary secrets pasted into a conversation
are NOT detected; treat exports as sensitive before sharing.

UI: dense aligned table / plain uppercase role labels, neutral hairline
rules only. No box-cards, no emoji, no colored accent bars (per
``feedback_no_box_ui_no_emoji``).
"""

from __future__ import annotations

import html as html_mod
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from core.memory.session_checkpoint import SessionState

session_app = typer.Typer(
    name="session",
    help="List, export, and migrate persisted agent sessions.",
    no_args_is_help=True,
    add_completion=False,
)

_INPUT_PREVIEW_CHARS = 60
_HEADER_INPUT_CHARS = 200
_TOOL_BODY_CHARS = 800

_PART_TITLES: dict[str, str] = {
    "tool_use": "TOOL CALL",
    "tool_result": "TOOL RESULT",
    "thinking": "THINKING",
}


@dataclass(frozen=True, slots=True)
class _SessionRow:
    """One row of the ``geode session list`` table."""

    session_id: str
    status: str
    updated_at: float
    rounds: int
    messages: int
    model: str
    user_input: str


@dataclass(frozen=True, slots=True)
class _RenderPart:
    """A renderable fragment of one message (text or monospace block)."""

    kind: str  # "text" | "thinking" | "tool_use" | "tool_result"
    label: str
    body: str


# ---------------------------------------------------------------------------
# Shared resolution helpers
# ---------------------------------------------------------------------------


def _resolve_base_dir(override: str) -> Path:
    if override:
        return Path(override).expanduser()
    from core.paths import resolve_sessions_dir

    return resolve_sessions_dir()


def _iso_local(ts: float) -> str:
    if ts <= 0:
        return "-"
    return datetime.fromtimestamp(ts).isoformat(sep=" ", timespec="seconds")


def _preview(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def _candidate_ids(base: Path) -> list[str]:
    """Session ids present on disk — ``<base>/<id>/state.json`` is the ground
    truth ``SessionCheckpoint.load()`` requires, so resolution keys on it."""
    if not base.exists():
        return []
    return sorted(
        entry.name for entry in base.iterdir() if entry.is_dir() and (entry / "state.json").exists()
    )


def _resolve_session_id(base: Path, query: str) -> str:
    """Resolve an exact session id or a unique prefix. Exits(1) otherwise."""
    ids = _candidate_ids(base)
    if query in ids:
        return query
    matches = [sid for sid in ids if sid.startswith(query)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        typer.echo(f"No session matching {query!r} in {base}. Run `geode session list`.")
        raise typer.Exit(code=1)
    typer.echo(f"Ambiguous session prefix {query!r} — {len(matches)} matches:")
    for sid in matches:
        typer.echo(f"  {sid}")
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# ``geode session list``
# ---------------------------------------------------------------------------


def _rows_from_index(db_path: Path, limit: int) -> list[_SessionRow]:
    from core.memory.session_manager import SessionManager

    mgr = SessionManager(db_path)
    try:
        metas = mgr.list_sessions(limit=limit)
    finally:
        mgr.close()
    return [
        _SessionRow(
            session_id=meta.session_id,
            status=meta.status,
            updated_at=meta.updated_at,
            rounds=meta.round_count,
            messages=meta.message_count,
            model=meta.model,
            user_input=meta.user_input,
        )
        for meta in metas
    ]


def _rows_from_scan(base: Path, limit: int) -> list[_SessionRow]:
    """Directory-scan fallback when ``sessions.db`` is missing.

    Reads ``state.json`` per session; message count comes from the
    ``messages.json`` hot cache when present (the DB that would carry the
    authoritative count is the thing that is absent here).
    """
    rows: list[_SessionRow] = []
    if not base.exists():
        return rows
    for entry in sorted(base.iterdir()):
        state_file = entry / "state.json"
        if not entry.is_dir() or not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        msg_count = 0
        msg_file = entry / "messages.json"
        if msg_file.exists():
            try:
                cached = json.loads(msg_file.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    msg_count = len(cached)
            except (json.JSONDecodeError, OSError):
                msg_count = 0
        updated_raw = data.get("updated_at")
        rounds_raw = data.get("round_idx")
        rows.append(
            _SessionRow(
                session_id=str(data.get("session_id", entry.name)),
                status=str(data.get("status", "")),
                updated_at=(float(updated_raw) if isinstance(updated_raw, (int, float)) else 0.0),
                rounds=int(rounds_raw) if isinstance(rounds_raw, (int, float)) else 0,
                messages=msg_count,
                model=str(data.get("model", "")),
                user_input=str(data.get("user_input", "")),
            )
        )
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[:limit]


@session_app.command("list")
def session_list(
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum number of sessions to show."),
    sessions_dir: str = typer.Option(
        "",
        "--sessions-dir",
        help="Override the sessions directory (defaults to the project sessions dir).",
    ),
) -> None:
    """List persisted sessions (SQLite index, directory-scan fallback)."""
    base = _resolve_base_dir(sessions_dir)
    db_path = base / "sessions.db"
    rows = _rows_from_index(db_path, limit) if db_path.exists() else _rows_from_scan(base, limit)
    if not rows:
        typer.echo(f"No sessions found in {base}.")
        return

    sid_w = max(len("SESSION_ID"), *(len(row.session_id) for row in rows))
    model_w = max(len("MODEL"), *(len(row.model) for row in rows))
    header = (
        f"{'SESSION_ID':<{sid_w}} {'STATUS':<9} {'UPDATED':<19} "
        f"{'ROUNDS':>6} {'MSGS':>5} {'MODEL':<{model_w}} INPUT"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for row in rows:
        typer.echo(
            f"{row.session_id:<{sid_w}} {row.status:<9} {_iso_local(row.updated_at):<19} "
            f"{row.rounds:>6d} {row.messages:>5d} {row.model:<{model_w}} "
            f"{_preview(row.user_input, _INPUT_PREVIEW_CHARS)}"
        )
    typer.echo(f"\n{len(rows)} session(s) in {base}.")


# ---------------------------------------------------------------------------
# Message normalization (shared by both renderers)
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    from core.observability.redaction import redact_secrets

    return redact_secrets(text)


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


def _flatten_result_content(value: Any) -> str:
    """Collapse a ``tool_result`` content payload (str or block list) to text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
            else:
                chunks.append(_to_text(block))
        return "\n".join(chunks)
    return _to_text(value)


def _truncate_block(text: str) -> str:
    if len(text) <= _TOOL_BODY_CHARS:
        return text
    return text[:_TOOL_BODY_CHARS] + f"\n… truncated ({len(text)} chars total)"


def _text_part(role: str, text: str) -> _RenderPart:
    """Plain text body — OpenAI-style ``role: tool`` rows are results, so
    they render as monospace blocks rather than prose."""
    if role == "tool":
        return _RenderPart(kind="tool_result", label="", body=_truncate_block(_clean(text)))
    return _RenderPart(kind="text", label="", body=_clean(text))


def _block_part(kind: str, label: str, raw: str) -> _RenderPart:
    return _RenderPart(kind=kind, label=label, body=_truncate_block(_clean(raw)))


def _message_parts(msg: dict[str, Any]) -> list[_RenderPart]:
    """Normalize one checkpoint message into renderable parts.

    Handles both content shapes ``SessionCheckpoint.load()`` can return:
    a plain string, or an Anthropic-style block list (``text`` /
    ``thinking`` / ``tool_use`` / ``tool_result``). OpenAI-style top-level
    ``tool_calls`` are rendered only when the content is NOT a block list —
    the DB mirror (:meth:`SessionManager._row_to_message`) surfaces both,
    and rendering both would duplicate every tool call.
    """
    parts: list[_RenderPart] = []
    role = str(msg.get("role", ""))
    content = msg.get("content")

    if isinstance(content, str):
        if content.strip():
            parts.append(_text_part(role, content))
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                text = _to_text(block)
                if text.strip():
                    parts.append(_text_part(role, text))
                continue
            btype = block.get("type")
            if btype == "text":
                text = str(block.get("text", ""))
                if text.strip():
                    parts.append(_RenderPart(kind="text", label="", body=_clean(text)))
            elif btype == "thinking":
                parts.append(_block_part("thinking", "", str(block.get("thinking", ""))))
            elif btype == "tool_use":
                name = str(block.get("name", ""))
                parts.append(_block_part("tool_use", name, _to_text(block.get("input"))))
            elif btype == "tool_result":
                label = str(block.get("tool_use_id", ""))
                raw = _flatten_result_content(block.get("content"))
                parts.append(_block_part("tool_result", label, raw))
            else:
                parts.append(_block_part("tool_result", str(btype or ""), _to_text(block)))
    elif content is not None:
        text = _to_text(content)
        if text.strip():
            parts.append(_text_part(role, text))

    if not isinstance(content, list):
        raw_calls = msg.get("tool_calls")
        if isinstance(raw_calls, list):
            for call in raw_calls:
                if not isinstance(call, dict):
                    continue
                fn_raw = call.get("function")
                fn_map: dict[str, Any] = fn_raw if isinstance(fn_raw, dict) else {}
                name = str(fn_map.get("name") or call.get("name") or "")
                args = fn_map.get("arguments", call.get("input"))
                parts.append(_block_part("tool_use", name, _to_text(args)))
    return parts


def _header_rows(state: SessionState) -> list[tuple[str, str]]:
    rows = [
        ("Session", state.session_id),
        ("Model", state.model or "-"),
        ("Provider", state.provider or "-"),
        ("Status", state.status or "-"),
        ("Created", _iso_local(state.created_at)),
        ("Updated", _iso_local(state.updated_at)),
        ("Rounds", str(state.round_idx)),
        ("Messages", str(len(state.messages))),
    ]
    request = _preview(_clean(state.user_input), _HEADER_INPUT_CHARS)
    if request:
        rows.append(("Request", request))
    return rows


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

_HTML_STYLE = """\
body { margin: 0; padding: 2rem 1.25rem; background: #ffffff; color: #1c1c1c;
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 48rem; margin: 0 auto; }
h1 { font-size: 1.15rem; font-weight: 650; margin: 0 0 1rem; }
table.meta { border-collapse: collapse; font-size: 0.85rem; margin: 0 0 1.5rem; }
table.meta th { text-align: left; font-weight: 600; color: #555555;
  padding: 0.1rem 1.5rem 0.1rem 0; vertical-align: top; white-space: nowrap; }
table.meta td { padding: 0.1rem 0; overflow-wrap: anywhere; }
section.msg { border-top: 1px solid #dddddd; padding: 0.85rem 0; }
.role { font-size: 0.72rem; font-weight: 650; letter-spacing: 0.08em; color: #666666;
  margin: 0 0 0.4rem; }
.body { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0 0 0.4rem; }
.tool-label { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em; color: #666666;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0.5rem 0 0.2rem; }
pre.tool { font: 12.5px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #f5f5f4; padding: 0.55rem 0.7rem; margin: 0; overflow-x: auto; }
p.note { color: #666666; font-style: italic; }
"""


def _part_title(part: _RenderPart) -> str:
    title = _PART_TITLES[part.kind]
    if part.label:
        return f"{title} {part.label}"
    return title


def _render_html(state: SessionState) -> str:
    esc = html_mod.escape
    out: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>GEODE session {esc(state.session_id)}</title>",
        f"<style>{_HTML_STYLE}</style>",
        "</head>",
        "<body>",
        "<main>",
        f"<h1>GEODE session {esc(state.session_id)}</h1>",
        '<table class="meta">',
    ]
    for key, value in _header_rows(state):
        out.append(f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>")
    out.append("</table>")

    if not state.messages:
        out.append('<p class="note">No messages recorded for this session.</p>')
    # Runtime defence — checkpoints written by old builds occasionally carry
    # non-dict placeholder entries the declared type doesn't admit (the same
    # defence ``SessionManager.upsert_messages`` applies on the write side).
    raw_messages: list[Any] = state.messages
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "unknown").upper()
        out.append('<section class="msg">')
        out.append(f'<div class="role">{esc(role)}</div>')
        for part in _message_parts(msg):
            if part.kind == "text":
                out.append(f'<div class="body">{esc(part.body)}</div>')
            else:
                out.append(f'<div class="tool-label">{esc(_part_title(part))}</div>')
                out.append(f'<pre class="tool">{esc(part.body)}</pre>')
        out.append("</section>")
    out.extend(["</main>", "</body>", "</html>"])
    return "\n".join(out) + "\n"


def _render_md(state: SessionState) -> str:
    lines: list[str] = [f"# GEODE session {state.session_id}", ""]
    for key, value in _header_rows(state):
        lines.append(f"- {key}: {value}")
    lines.append("")
    if not state.messages:
        lines.extend(["No messages recorded for this session.", ""])
    # Runtime defence — see the matching note in ``_render_html``.
    raw_messages: list[Any] = state.messages
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "unknown").upper()
        lines.extend(["---", "", role, ""])
        for part in _message_parts(msg):
            if part.kind == "text":
                lines.extend([part.body, ""])
            else:
                lines.extend([_part_title(part), "", "````", part.body, "````", ""])
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# ``geode session export``
# ---------------------------------------------------------------------------


@session_app.command("export")
def session_export(
    session_id: str = typer.Argument(..., help="Session id or unique prefix."),
    out: str = typer.Option(
        "", "--out", help="Output file path (default: ./geode-session-<id>.<ext>)."
    ),
    fmt: str = typer.Option("html", "--fmt", help="Output format: html or md."),
    sessions_dir: str = typer.Option(
        "",
        "--sessions-dir",
        help="Override the sessions directory (defaults to the project sessions dir).",
    ),
) -> None:
    """Export a persisted session to a standalone shareable file."""
    fmt_clean = fmt.strip().lower()
    if fmt_clean not in ("html", "md"):
        raise typer.BadParameter("--fmt must be 'html' or 'md'", param_hint="--fmt")

    base = _resolve_base_dir(sessions_dir)
    resolved_id = _resolve_session_id(base, session_id)

    from core.memory.session_checkpoint import SessionCheckpoint

    state = SessionCheckpoint(base).load(resolved_id)
    if state is None:
        typer.echo(f"Session {resolved_id!r} could not be loaded from {base}.")
        raise typer.Exit(code=1)

    document = _render_html(state) if fmt_clean == "html" else _render_md(state)
    out_path = Path(out).expanduser() if out else Path(f"geode-session-{resolved_id}.{fmt_clean}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    typer.echo(str(out_path.resolve()))


@session_app.command("migrate-records")
def session_migrate_records(
    sources: Annotated[
        list[str] | None,
        typer.Option(
            "--source",
            help=(
                "Legacy JSONL file or directory. Repeat for multiple sources; "
                "defaults to the retired global transcript directory."
            ),
        ),
    ] = None,
    session_id: str = typer.Option(
        "",
        "--session-id",
        help="Override the inferred session id (only valid with one source file).",
    ),
    sessions_dir: str = typer.Option(
        "",
        "--sessions-dir",
        help="Override the sessions directory containing sessions.db.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Inspect inputs without writing SQLite."),
) -> None:
    """Import deprecated transcript JSONL into canonical SQLite history."""
    from core.memory.atomic_write import iter_jsonl
    from core.observability.session_timeline import SessionEventStore
    from core.paths import GLOBAL_TRANSCRIPTS_DIR

    requested = [Path(item).expanduser() for item in (sources or [str(GLOBAL_TRANSCRIPTS_DIR)])]
    files: list[Path] = []
    for source in requested:
        if source.is_file():
            files.append(source)
        elif source.is_dir():
            files.extend(sorted(source.rglob("*.jsonl")))
        else:
            typer.echo(f"Missing source: {source}")
            raise typer.Exit(code=1)
    files = list(dict.fromkeys(path.resolve() for path in files))
    if session_id and len(files) != 1:
        raise typer.BadParameter(
            "--session-id requires exactly one resolved source file",
            param_hint="--session-id",
        )
    if not files:
        typer.echo("No legacy JSONL files found.")
        return

    if dry_run:
        rows = sum(1 for path in files for _row in iter_jsonl(path))
        typer.echo(f"Would inspect {len(files)} file(s), {rows} valid JSON object row(s).")
        return

    base = _resolve_base_dir(sessions_dir)
    store = SessionEventStore(base / "sessions.db")
    imported = 0
    for path in files:
        imported += store.import_legacy_jsonl(path, session_id=session_id or None)
    typer.echo(
        f"Recognized {imported} event(s) from {len(files)} file(s) in "
        f"{store.db_path.resolve()}. Duplicate source digests were not reinserted; "
        "sources were not modified."
    )


@session_app.command("effects")
def session_effects(
    session_id: str = typer.Option("", "--session-id", help="Filter by session id."),
    sessions_dir: str = typer.Option(
        "",
        "--sessions-dir",
        help="Override the sessions directory containing sessions.db.",
    ),
) -> None:
    """List unresolved effect receipts without arguments or result bodies."""
    from core.memory.effect_receipts import EffectReceiptStore

    rows = EffectReceiptStore(_resolve_base_dir(sessions_dir) / "sessions.db").list_uncertain(
        session_id=session_id
    )
    if not rows:
        typer.echo("No unresolved effects.")
        return
    typer.echo("OPERATION\tSESSION\tTOOL\tEFFECT\tUPDATED")
    for row in rows:
        typer.echo(
            "\t".join(
                (
                    str(row["operation_id"]),
                    str(row["session_id"]),
                    str(row["tool_name"]),
                    str(row["effect"]),
                    _iso_local(float(row["updated_at"])),
                )
            )
        )


@session_app.command("resolve-effect")
def session_resolve_effect(
    operation_id: str = typer.Argument(..., help="Operation id shown by session effects."),
    outcome: str = typer.Option(
        ...,
        "--outcome",
        help="External verification result: applied or not-applied.",
    ),
    sessions_dir: str = typer.Option(
        "",
        "--sessions-dir",
        help="Override the sessions directory containing sessions.db.",
    ),
) -> None:
    """Resolve an uncertain effect after checking its external sink."""
    normalized = outcome.strip().lower()
    if normalized not in {"applied", "not-applied"}:
        raise typer.BadParameter(
            "expected applied or not-applied",
            param_hint="--outcome",
        )
    from core.memory.effect_receipts import EffectReceiptStore

    resolved = EffectReceiptStore(_resolve_base_dir(sessions_dir) / "sessions.db").resolve(
        operation_id,
        applied=normalized == "applied",
    )
    if not resolved:
        typer.echo(f"Prepared effect {operation_id!r} was not found.")
        raise typer.Exit(code=1)
    typer.echo(f"Resolved {operation_id} as {normalized}.")


@session_app.command("export-trajectory")
def session_export_trajectory(
    session_id: str = typer.Argument(..., help="Canonical session id."),
    out: str = typer.Option(
        "",
        "--out",
        help="Output path (default: ./geode-trajectory-<session>.json).",
    ),
    sessions_dir: str = typer.Option(
        "",
        "--sessions-dir",
        help="Override the sessions directory containing sessions.db.",
    ),
    sil_eval: Annotated[
        list[Path] | None,
        typer.Option(
            "--sil-eval",
            help="Inspect .eval evidence to bind by SHA-256 as SIL authority.",
        ),
    ] = None,
    digest_content: bool = typer.Option(
        False,
        "--digest-content",
        help="Replace non-allowlisted payload bodies with digests.",
    ),
) -> None:
    """Build a validated ``geode.trajectory@1`` artifact from SQLite."""
    from core.observability.trajectory import export_trajectory, trajectory_from_session

    base = _resolve_base_dir(sessions_dir)
    evidence_refs: list[dict[str, Any]] = []
    artifact_digests: list[dict[str, str]] = []
    for eval_path in sil_eval or ():
        resolved = eval_path.expanduser()
        if not resolved.is_file():
            raise typer.BadParameter(f"SIL eval does not exist: {resolved}")
        import hashlib

        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        artifact_digests.append({"path": resolved.name, "sha256": digest})
        evidence_refs.append(
            {
                "kind": "sil_eval",
                "schema_id": "inspect_ai.eval@native",
                "authority": "Inspect AI scored evaluation archive",
                "reference": f"sha256:{digest}",
                "path": resolved.name,
                "sha256": digest,
            }
        )
    trajectory = trajectory_from_session(
        session_id,
        db_path=base / "sessions.db",
        artifact_digests=artifact_digests,
        evidence_refs=evidence_refs,
        content_policy="digest" if digest_content else "full",
    )
    if not trajectory["events"]:
        typer.echo(f"No canonical session events found for {session_id!r}.")
        raise typer.Exit(code=1)
    output = Path(out).expanduser() if out else Path(f"geode-trajectory-{session_id}.json")
    export_trajectory(output, trajectory)
    typer.echo(str(output.resolve()))
    integrity = trajectory["integrity"]
    reasons = list(integrity["incompleteness"])
    typer.echo(
        "records={records} scope_complete={scope} replay_complete={replay} "
        "reasons={reasons}".format(
            records=integrity["record_count"],
            scope=str(bool(integrity["scope_complete"])).lower(),
            replay=str(bool(integrity["replay_complete"])).lower(),
            reasons=json.dumps(reasons, ensure_ascii=False),
        )
    )


@session_app.command("prune-records")
def session_prune_records(
    retention_days: int = typer.Option(
        180,
        "--retention-days",
        min=0,
        help="Delete only explicitly ended sessions older than this many days.",
    ),
    sessions_dir: str = typer.Option(
        "",
        "--sessions-dir",
        help="Override the sessions directory containing sessions.db.",
    ),
) -> None:
    """Prune old terminal history while preserving active/stale sessions."""
    from core.observability.session_timeline import SessionEventStore

    base = _resolve_base_dir(sessions_dir)
    removed = SessionEventStore(base / "sessions.db").prune_terminal_sessions(
        retention_days=retention_days
    )
    typer.echo(f"Pruned {removed} terminal session event row(s).")


@session_app.command("stage-trajectory-release")
def session_stage_trajectory_release(
    trajectories: Annotated[
        list[Path],
        typer.Argument(help="One or more current or dated trajectory JSON files."),
    ],
    destination: Annotated[
        Path,
        typer.Option(
            "--destination",
            help="Local append-only staging root for the release directory.",
        ),
    ],
    release_source: Annotated[
        str,
        typer.Option(
            "--source",
            help="Stable producer name, for example tau2-geode.",
        ),
    ],
    release_scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="Task/model/run scope represented by this release.",
        ),
    ],
    privacy_review: Annotated[
        Path,
        typer.Option(
            "--privacy-review",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help=(
                "JSON review record with reviewer, reviewed_at, method, scope, "
                "and public attestation."
            ),
        ),
    ],
    published_at: Annotated[
        str,
        typer.Option(
            "--published-at",
            help="Optional ISO-8601 UTC publication time.",
        ),
    ] = "",
    supersedes: Annotated[
        str,
        typer.Option(
            "--supersedes",
            help="Optional prior immutable release identifier.",
        ),
    ] = "",
    source_artifact: Annotated[
        list[str] | None,
        typer.Option(
            "--source-artifact",
            help="Digest source mapping as REF=PATH; repeat for every artifact_digests row.",
        ),
    ] = None,
    allow_replay_incomplete: bool = typer.Option(
        False,
        "--allow-replay-incomplete",
        help="Publish reviewed scope-complete artifacts whose private bodies were digested.",
    ),
) -> None:
    """Stage reviewed trajectories behind the public release quality gate."""
    from core.observability.trajectory import normalize_trajectory_artifact
    from core.observability.trajectory_release import stage_trajectory_release

    payloads: dict[str, dict[str, Any]] = {}
    source_artifacts: dict[str, Path] = {}
    try:
        review_payload = json.loads(privacy_review.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"cannot read privacy review {privacy_review}: {exc}") from exc
    if not isinstance(review_payload, dict):
        raise typer.BadParameter("privacy review must be a JSON object")
    for mapping in source_artifact or ():
        reference, separator, raw_path = mapping.partition("=")
        if not separator or not reference or not raw_path:
            raise typer.BadParameter("--source-artifact must use REF=PATH")
        if reference in source_artifacts:
            raise typer.BadParameter(f"duplicate source artifact reference: {reference}")
        source_path = Path(raw_path).expanduser()
        if not source_path.is_file():
            raise typer.BadParameter(f"source artifact does not exist: {source_path}")
        source_artifacts[reference] = source_path
    for path in trajectories:
        source_path = path.expanduser()
        try:
            loaded = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(f"cannot read trajectory {source_path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise typer.BadParameter(f"trajectory must be a JSON object: {source_path}")
        if source_path.name in payloads:
            raise typer.BadParameter(
                f"trajectory basenames must be unique within a release: {source_path.name}"
            )
        payloads[source_path.name] = normalize_trajectory_artifact(loaded)
    try:
        release = stage_trajectory_release(
            destination.expanduser(),
            release_source=release_source,
            release_scope=release_scope,
            trajectories=payloads,
            published_at=published_at or None,
            supersedes=supersedes or None,
            privacy_review=review_payload,
            source_artifacts=source_artifacts,
            require_complete=not allow_replay_incomplete,
        )
    except (FileExistsError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(str(release.resolve()))


@session_app.command("verify-trajectory-release")
def session_verify_trajectory_release(
    release: Annotated[Path, typer.Argument(help="Staged release directory.")],
    expected_manifest_sha256: Annotated[
        str,
        typer.Option(
            "--expected-manifest-sha256",
            help="Independently recorded manifest digest anchor.",
        ),
    ],
) -> None:
    """Recompute every trajectory, manifest aggregate, digest, and scan."""
    from core.observability.trajectory_release import verify_trajectory_release

    try:
        manifest = verify_trajectory_release(
            release.expanduser(),
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            {
                "release": str(release.expanduser().resolve()),
                "quality": manifest["quality"],
                "verified": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


__all__ = ["session_app"]
