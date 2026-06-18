"""Shared config.toml read-path resolution + section-keyed editing.

Consolidates helpers that were duplicated (PR-DEDUP-CONFIG-TOML):

- ``GEODE_CONFIG_TOML`` → path resolution: ``core/config/self_improving.py``
  (``_resolve_config_path``) and ``core/cli/onboarding.py``
  (``_resolve_config_toml``) carried byte-identical env→GLOBAL logic.
- TOML section splicing: ``core/cli/commands/self_improving.py``
  (``_splice_section`` / ``_persist_section_updates`` / ``_toml_escape``) is the
  general writer; ``core/cli/onboarding.py`` had a single-section copy
  (``_splice_bash_sandbox_mode``) for the one ``[bash_sandbox]`` key.

One home now; both call surfaces import from here.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.paths import GLOBAL_CONFIG_TOML


def resolve_config_toml_path(explicit: Path | str | None = None) -> Path:
    """Resolve which config TOML to read/write.

    Order: ``explicit`` argument → ``GEODE_CONFIG_TOML`` env (``~`` expanded so a
    redirect resolves to the same file the loader reads) → :data:`core.paths.
    GLOBAL_CONFIG_TOML`. The loader (``core/config``) and any writer MUST resolve
    through here so a ``GEODE_CONFIG_TOML`` override keeps read/write parity.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    env = os.environ.get("GEODE_CONFIG_TOML", "").strip()
    return Path(env).expanduser() if env else GLOBAL_CONFIG_TOML


def toml_escape(value: str) -> str:
    """TOML basic-string escape (backslash / quote / control chars)."""
    out: list[str] = []
    for ch in value:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch in ("\b", "\f", "\n", "\r", "\t"):
            out.append({"\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    return "".join(out)


def splice_toml_section(text: str, section: str, updates: dict[str, str]) -> str:
    """Return ``text`` with ``[section]`` carrying every ``updates`` entry.

    String values are written as ``key = "value"`` (escaped). An empty-string
    value (``key == ""``) signals "delete this key": the matching line is dropped
    rather than replaced, and a fresh section never picks up a delete request.
    If the section is missing it is appended; existing keys are replaced in
    place; new keys are inserted at the end of the section block.
    """
    header = f"[{section}]"
    lines = text.splitlines(keepends=False)
    header_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == header:
            header_idx = i
            break
    if header_idx == -1:
        materialised = {k: v for k, v in updates.items() if v != ""}
        if not materialised:
            return text
        block = [header]
        for key, val in materialised.items():
            block.append(f'{key} = "{toml_escape(val)}"')
        suffix = "" if text.endswith("\n") or text == "" else "\n"
        sep = "\n" if text and not text.endswith("\n\n") else ""
        return text + suffix + sep + "\n".join(block) + "\n"
    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end_idx = j
            break
    remaining = dict(updates)
    keep_lines: list[str] = []
    for k in range(header_idx + 1, end_idx):
        line = lines[k]
        matched_key: str | None = None
        for key in list(remaining):
            # Match ``key`` followed by optional whitespace then ``=`` (TOML allows
            # ``key = v`` / ``key=v`` / ``key\t= v``). The trailing ``=`` check keeps
            # prefix-safety so ``default_model`` never matches ``default_model_x``.
            stripped = line.lstrip()
            if stripped.startswith(key) and stripped[len(key) :].lstrip(" \t").startswith("="):
                matched_key = key
                break
        if matched_key is None:
            keep_lines.append(line)
            continue
        val = remaining.pop(matched_key)
        if val == "":
            continue
        keep_lines.append(f'{matched_key} = "{toml_escape(val)}"')
    new_kv_lines = [f'{key} = "{toml_escape(val)}"' for key, val in remaining.items() if val != ""]
    insert_at_keep = len(keep_lines)
    while insert_at_keep > 0 and keep_lines[insert_at_keep - 1].strip() == "":
        insert_at_keep -= 1
    rebuilt = keep_lines[:insert_at_keep] + new_kv_lines + keep_lines[insert_at_keep:]
    out_lines = lines[: header_idx + 1] + rebuilt + lines[end_idx:]
    result = "\n".join(out_lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


def persist_toml_section(section: str, updates: dict[str, str]) -> Path:
    """Splice ``updates`` into ``[section]`` of the resolved config TOML, atomically.

    Resolves the write path through :func:`resolve_config_toml_path` (same helper
    the loader reads) so a ``GEODE_CONFIG_TOML`` override keeps read/write parity.
    Returns the written path. A no-op (empty ``updates``) still returns the path.
    """
    from core.memory.atomic_write import atomic_write_text

    path = resolve_config_toml_path()
    if not updates:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    atomic_write_text(path, splice_toml_section(text, section, updates))
    return path
