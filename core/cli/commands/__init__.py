"""Slash command dispatch package — Tier 3 #9 split of the legacy
``core/cli/commands.py`` (2,441 LOC).

OpenClaw-inspired Binding Router pattern: static command → handler
mapping. The original single-file module was carved into one sub-module
per concern while preserving every public symbol previously imported by
external consumers (CLI bootstrap, tool handlers, plugins, tests). Sub-
modules:

- :mod:`_state` — ``ModelProfile``, ``get_model_profiles``, ``COMMAND_MAP``,
  conversation ContextVar, ``show_help``, ``resolve_action``,
  ``_get_profile_store``
- :mod:`key`      — ``cmd_key`` + auth-state mirroring
- :mod:`model`    — ``/model`` picker + ``_apply_model``
- :mod:`mcp`      — ``/mcp`` server management
- :mod:`skills`   — ``/skills`` + ``/skill`` invoke
- :mod:`cost`     — ``/cost`` dashboard + budget helpers
- :mod:`session`  — ``/resume``, ``/cognitive``, ``/apply``, ``/context``,
  ``/compact``, ``/clear``
- :mod:`tasks`    — ``/tasks`` user task list
- :mod:`trigger`  — ``/trigger`` event/cron manager
- :mod:`login`    — unified ``/login`` (PR #C, 2026-05-17 — replaces ``/auth``)

Names re-exported at the package level keep the legacy import path
(``from core.cli.commands import …``) intact for the 30+ external call
sites identified by the migration audit. ``console``, ``_upsert_env``,
``_mask_key``, ``_is_glm_key``, ``_check_provider_key``,
``_get_cost_budget``, ``_set_cost_budget``, ``_persist_auth_state``,
``_seed_payg_plan_from_key``, ``_mcp_add``, ``_skills_add``,
``get_conversation_context``,
``set_conversation_context``, ``cmd_login`` are addressable on the
package because tests monkey-patch them via the legacy dotted path
``core.cli.commands.<name>``. Each submodule reaches the patched value
through a deferred ``import core.cli.commands as _pkg`` lookup,
mirroring the pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

# Bridge module for /schedule (a separate file at core/cli/commands/schedule.py)
from core.cli.commands.schedule import cmd_schedule as cmd_schedule

# Helpers + Rich console must be addressable at the package level so
# monkeypatched test references (``patch("core.cli.commands.console")``,
# ``patch("core.cli.commands._upsert_env")``, etc.) hit the same object
# the submodules consume through the deferred ``_pkg.X`` lookup.
from core.config.env_io import is_glm_key as _is_glm_key
from core.config.env_io import mask_key as _mask_key
from core.config.env_io import remove_env as remove_env
from core.config.env_io import upsert_env as _upsert_env
from core.ui.console import console as console

from ._state import (
    COMMAND_MAP,
    ModelProfile,
    _conversation_ctx,
    _get_profile_store,
    get_conversation_context,
    get_model_index,
    get_model_profiles,
    resolve_action,
    set_conversation_context,
    show_help,
)
from .cost import _budget_bar, _get_cost_budget, _set_cost_budget, cmd_cost
from .key import _check_provider_key, _persist_auth_state, _seed_payg_plan_from_key, cmd_key
from .login import (
    _login_add_interactive,
    _login_help,
    _login_oauth,
    _login_quota,
    _login_remove,
    _login_route,
    _login_set_key,
    _login_show_status,
    _login_use,
    cmd_login,
)
from .mcp import _mcp_add, cmd_mcp
from .model import _apply_model, _interactive_model_picker, cmd_model
from .petri import cmd_petri
from .session import cmd_apply, cmd_clear, cmd_cognitive, cmd_compact, cmd_context, cmd_resume
from .skills import _skills_add, cmd_skill_invoke, cmd_skills
from .tasks import cmd_tasks
from .trigger import cmd_trigger

__all__ = [
    "COMMAND_MAP",
    "ModelProfile",
    "_apply_model",
    "_budget_bar",
    "_check_provider_key",
    "_conversation_ctx",
    "_get_cost_budget",
    "_get_profile_store",
    "_interactive_model_picker",
    "_is_glm_key",
    "_login_add_interactive",
    "_login_help",
    "_login_oauth",
    "_login_quota",
    "_login_remove",
    "_login_route",
    "_login_set_key",
    "_login_show_status",
    "_login_use",
    "_mask_key",
    "_mcp_add",
    "_persist_auth_state",
    "_seed_payg_plan_from_key",
    "_set_cost_budget",
    "_skills_add",
    "_upsert_env",
    "cmd_apply",
    "cmd_clear",
    "cmd_cognitive",
    "cmd_compact",
    "cmd_context",
    "cmd_cost",
    "cmd_key",
    "cmd_login",
    "cmd_mcp",
    "cmd_model",
    "cmd_petri",
    "cmd_resume",
    "cmd_schedule",
    "cmd_skill_invoke",
    "cmd_skills",
    "cmd_tasks",
    "cmd_trigger",
    "console",
    "get_conversation_context",
    "get_model_index",
    "get_model_profiles",
    "resolve_action",
    "set_conversation_context",
    "show_help",
]
