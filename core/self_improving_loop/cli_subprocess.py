"""Paperclip pattern — invoke local Claude Code / Codex CLI via subprocess.

Used by the mutator runner when ``MutatorConfig.source`` is
``"claude-cli"`` or ``"openai-codex"``. The dispatch goes through the
operator's existing CLI subscription (Claude Code Max plan / ChatGPT
Plus → Codex CLI) instead of the API-billed providers.

**Why subprocess vs HTTP**: per session decision Q1=b — keep the loop
honest about which channel was billed. The CLI binary owns its own
auth + subscription credentials; we just hand it a prompt and read
stdout. No extra OAuth-token plumbing inside the loop.

**Resolution**:

* Binary path defaults to ``claude`` / ``codex`` on ``$PATH``. Operators
  on non-standard installs override via ``GEODE_CLAUDE_CLI_BIN`` /
  ``GEODE_CODEX_CLI_BIN``.
* Missing binary → :class:`RuntimeError` with an actionable message
  (``brew install …`` / ``npm i -g @anthropic-ai/claude-code``).
* Non-zero exit → :class:`RuntimeError` carrying stderr (truncated).

**Scope**: pure pipe — system + user prompt in, raw stdout text out.
Output parsing (JSON mutation extraction) is the runner's job, same
as for the API path; if the CLI returns extra Markdown / headers,
``parse_mutation`` raises ``ValueError`` and the runner skips the
iteration (existing graceful path).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

__all__ = [
    "CLAUDE_CLI_BIN_ENV",
    "CODEX_CLI_BIN_ENV",
    "CliInvocationError",
    "invoke_claude_cli",
    "invoke_codex_cli",
]

CLAUDE_CLI_BIN_ENV = "GEODE_CLAUDE_CLI_BIN"
CODEX_CLI_BIN_ENV = "GEODE_CODEX_CLI_BIN"

_DEFAULT_CLAUDE_BIN = "claude"
_DEFAULT_CODEX_BIN = "codex"

# Per-call timeout — mutator LLM calls should finish in seconds. A long
# subprocess hang (network stall, interactive prompt waiting on stdin)
# should not block the whole self-improving-loop iteration.
_CLI_TIMEOUT_SEC = 180.0


class CliInvocationError(RuntimeError):
    """Raised when the CLI binary cannot be located or exits non-zero."""


def _resolve_binary(env_var: str, default: str) -> str:
    """Return absolute path to the CLI binary, or raise ``CliInvocationError``.

    Resolution order:
      1. ``$<env_var>`` (operator override) — used verbatim if it points
         to an existing executable.
      2. ``shutil.which(default)`` — first ``default`` (e.g. ``claude``)
         found on ``$PATH``.
    """
    override = os.environ.get(env_var)
    if override:
        if shutil.which(override) is None and not os.path.isfile(override):
            raise CliInvocationError(
                f"{env_var}={override!r} but no executable found there. "
                f"Set {env_var} to the full path of the {default!r} binary."
            )
        return override
    found = shutil.which(default)
    if not found:
        raise CliInvocationError(
            f"{default!r} not found on $PATH. Install Claude Code "
            f"(https://docs.anthropic.com/claude/docs/claude-code) "
            f"or Codex CLI (https://github.com/openai/codex), or set "
            f"{env_var} to point at the binary."
        )
    return found


def _run(binary: str, args: list[str], stdin_text: str) -> str:
    """Execute ``binary`` with ``args``, pipe ``stdin_text``, return stdout.

    Captures stderr separately and includes the first 400 chars in the
    raised error so operators can diagnose without re-running the loop.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — args are constructed from a fixed allowlist
            [binary, *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SEC,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CliInvocationError(f"binary disappeared between resolve and run: {binary}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CliInvocationError(
            f"{binary} timed out after {_CLI_TIMEOUT_SEC}s — "
            "check that the CLI is non-interactive in print mode"
        ) from exc
    if proc.returncode != 0:
        stderr_clip = (proc.stderr or "")[:400]
        raise CliInvocationError(f"{binary} exited {proc.returncode}: {stderr_clip!r}")
    return proc.stdout


def invoke_claude_cli(*, system_prompt: str, user_prompt: str) -> str:
    """Run ``claude --print`` with the given system + user prompts.

    Wire path:
        ``claude --print --output-format text --append-system-prompt <SYS> <USER>``

    The ``--append-system-prompt`` flag prepends the mutator system
    contract to whatever default system prompt Claude Code already
    applies (which is fine — both are operator-intended context). The
    user prompt is the last positional argument; ``--print`` makes
    Claude Code emit one response then exit (non-interactive).

    ``--output-format text`` keeps stdout free of the Markdown framing
    that Claude Code's TUI render layer would otherwise add.

    Concurrency gate (PR-LQ-Phase2, 2026-05-22): the call is wrapped
    in :func:`core.orchestration.claude_cli_lane.acquire_claude_cli_lane`
    so simultaneous mutator invocations + Petri inspect_ai bridge
    spawns share a single bucket-wide cap (default 2 — one slot below
    the public 3-4 burst-limiter floor, leaving room for the
    operator's host Claude Code session). See
    [[project_lanequeue_handoff_2026_05_22]] for Phase 2 rationale +
    Phase 3 OAuth-usage polling integration.
    """
    from core.orchestration.claude_cli_lane import acquire_claude_cli_lane

    binary = _resolve_binary(CLAUDE_CLI_BIN_ENV, _DEFAULT_CLAUDE_BIN)
    args = [
        "--print",
        "--output-format",
        "text",
        "--append-system-prompt",
        system_prompt,
        user_prompt,
    ]
    with acquire_claude_cli_lane(key="self_improving_loop.mutator"):
        out = _run(binary, args, stdin_text="")
    return out.strip()


def invoke_codex_cli(*, system_prompt: str, user_prompt: str) -> str:
    """Run ``codex exec`` with the given system + user prompts.

    Wire path:
        ``codex exec --skip-git-repo-check <COMBINED>``

    Codex CLI's ``exec`` is the non-interactive one-shot mode. The
    combined prompt prepends the system contract as a ``System:``
    header so a single positional argument carries both halves —
    Codex CLI doesn't have a ``--system`` flag equivalent.
    ``--skip-git-repo-check`` lets the mutator run outside a workspace
    tree (the self-improving-loop dispatches from
    ``~/.geode/self-improving-loop/`` paths, not the repo root).
    """
    binary = _resolve_binary(CODEX_CLI_BIN_ENV, _DEFAULT_CODEX_BIN)
    combined = f"System: {system_prompt}\n\nUser: {user_prompt}"
    args = ["exec", "--skip-git-repo-check", combined]
    out = _run(binary, args, stdin_text="")
    return out.strip()
