"""CLI-specific argument parsing helpers.

The four IO/key utilities (``mask_key``, ``upsert_env``, ``upsert_config_toml``,
``is_glm_key``) used to live here too; v0.85.0 moved them to
``core/utils/env_io.py`` so non-CLI layers (e.g. ``core/lifecycle``) can use
them without crossing the CLI boundary. ``parse_dry_run_flag`` stays here
because it is genuinely CLI-specific — it parses CLI argument strings.
"""

from __future__ import annotations


def parse_dry_run_flag(args: str) -> tuple[bool, str]:
    """Extract --dry-run / --dry_run flag from CLI args.

    Returns ``(has_flag, cleaned_args)`` where ``cleaned_args`` has the
    flag removed and is stripped of surrounding whitespace.
    """
    has_flag = "--dry-run" in args or "--dry_run" in args
    cleaned = args.replace("--dry-run", "").replace("--dry_run", "").strip()
    return has_flag, cleaned
