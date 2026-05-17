"""Thin re-export — keeps ``core.cli.commands.petri`` importable for the
slash dispatcher while the actual implementation lives in the plugin
package (:mod:`plugins.petri_audit.cli`).

Following the pattern of other plugin-backed commands so the audit
extra (``[audit]``) stays the boundary — the slash dispatcher only
imports this shim, and the heavy dependencies (TerminalMenu, manifest
loader) are deferred until the first invocation.
"""

from __future__ import annotations

__all__ = ["cmd_petri"]


def cmd_petri(args: str) -> None:
    """Defer to :func:`plugins.petri_audit.cli.cmd_petri`."""
    from plugins.petri_audit.cli import cmd_petri as _impl

    _impl(args)
