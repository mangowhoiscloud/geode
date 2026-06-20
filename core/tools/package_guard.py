"""Slopsquatting guard — block bash installs of packages that do not exist.

LLMs hallucinate package names (~20% of recommended packages do not exist; 43%
repeat the same fake name). Attackers pre-register those names with malware
("slopsquatting"). This guard parses pip/uv/npm install commands, checks each
bare registry name against PyPI/npm, and blocks ONLY on a definitive 404.
Fail-open everywhere else (network error, non-404, private index, scoped/complex
names, guard disabled) — "could not verify" is never proof of malice and must
not break legitimate installs.
"""

from __future__ import annotations

import logging
import re
import shlex

import httpx

log = logging.getLogger(__name__)

# install verbs per package manager front-end
_INSTALL_RE = re.compile(
    r"^(?:pip|pip3|uv|npm|pnpm|yarn)\b",
)

# Leading ``VAR=value`` env assignment (peeled off, e.g. ``PIP_INDEX_URL=x pip``).
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# A custom index/registry flag means the real install source is NOT public
# PyPI/npm, so a public-registry 404 is not definitive — skip the whole segment
# (fail-open) rather than false-block a private-index install.
_CUSTOM_INDEX_FLAGS = frozenset({"--index-url", "--extra-index-url", "-i", "--registry"})
_CUSTOM_INDEX_PREFIXES = ("--index-url=", "--extra-index-url=", "--registry=")

# A bare registry name: starts alphanumeric, then name chars only. Anything with
# a slash, scope-@, URL scheme, or VCS marker is handled by the skip rules below.
_BARE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Split a requirement spec at the first version/extras/url marker so only the
# bare distribution name remains (e.g. ``requests==2.31`` → ``requests``).
_VERSION_SPLIT_RE = re.compile(r"[<>=!~\[@]")

# Shell control operators that separate sub-commands. Split on these FIRST so a
# compound command (``echo hi && pip install <fake>``) is parsed per-segment and
# cannot bypass the guard, and operator tokens (``&&``/``pip``/``install``) are
# never mistaken for package names. ``||`` before ``|`` in the alternation.
_SEGMENT_RE = re.compile(r"&&|\|\||[;|\n]")


def _strip_version(arg: str) -> str:
    """Return the bare distribution name, stripping version/extras specifiers."""
    return _VERSION_SPLIT_RE.split(arg, maxsplit=1)[0].strip()


def parse_install_packages(command: str) -> list[tuple[str, str]]:
    """Parse an install command into ``[(registry, name)]`` pairs.

    Splits the command on shell control operators (``&&``/``||``/``;``/``|``/
    newline) and parses each segment for ``pip|pip3|uv|npm|pnpm|yarn (pip )?
    (install|add) <args>``. Each arg is filtered: flags, local paths, URLs, VCS
    refs, and npm scoped names are skipped (fail-open); version specifiers are
    stripped; only names matching a bare registry-name pattern are kept. Returns
    an empty list for any command with no recognised install segment.
    """
    packages: list[tuple[str, str]] = []
    for segment in _SEGMENT_RE.split(command):
        packages.extend(_parse_segment(segment))
    return packages


def _parse_segment(segment: str) -> list[tuple[str, str]]:
    """Parse a single shell sub-command (no control operators) for install pkgs."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return []
    # Peel leading env-var assignments + ``env``/``sudo`` wrappers so prefixed
    # installs (``FOO=bar pip install ...``, ``env pip install ...``) are still
    # recognised. (``sudo`` is separately blocked by BashTool.validate.) But an
    # index/registry-setting env var (``PIP_INDEX_URL=...``, ``UV_INDEX_URL=...``,
    # ``npm_config_registry=...``) points the install at a non-public source, so
    # a public 404 is not definitive → skip the segment (fail-open).
    while tokens and (tokens[0] in ("env", "sudo") or _ENV_ASSIGN_RE.match(tokens[0])):
        tok = tokens[0]
        if "=" in tok:
            name = tok.split("=", 1)[0].upper()
            if "INDEX" in name or "REGISTRY" in name:
                return []
        tokens = tokens[1:]
    if not tokens:
        return []

    front = tokens[0]
    rest = tokens[1:]
    # ``python -m pip install ...`` / ``python3 -m pip install ...``
    if front in ("python", "python3") and rest[:2] == ["-m", "pip"]:
        registry = "pypi"
        rest = rest[2:]
    elif _INSTALL_RE.match(front):
        registry = "npm" if front in ("npm", "pnpm", "yarn") else "pypi"
        # ``uv pip install`` / ``uv add`` — peel a leading ``pip`` sub-command.
        if rest and rest[0] == "pip":
            registry = "pypi"
            rest = rest[1:]
    else:
        return []

    if not rest:
        return []
    verb = rest[0]
    if verb not in ("install", "add"):
        return []
    args = rest[1:]

    # Custom index/registry → the install source is not public PyPI/npm, so a
    # public 404 is not definitive. Fail-open: skip the whole segment.
    if any(a in _CUSTOM_INDEX_FLAGS or a.startswith(_CUSTOM_INDEX_PREFIXES) for a in args):
        return []

    packages: list[tuple[str, str]] = []
    for arg in args:
        if not arg or arg.startswith("-"):
            continue  # flag
        if arg[0] in (".", "/", "~"):
            continue  # local path
        if "://" in arg or arg.startswith("git+"):
            continue  # URL / VCS
        if arg.startswith("@"):
            continue  # npm scoped name — fail-open
        name = _strip_version(arg)
        if not name or not _BARE_NAME_RE.match(name):
            continue
        packages.append((registry, name))
    return packages


async def _exists(client: httpx.AsyncClient, registry: str, name: str) -> bool | None:
    """Return True if the package exists, False on a definitive 404, None if
    existence could not be determined (network error, non-404 status)."""
    url = (
        f"https://pypi.org/pypi/{name}/json"
        if registry == "pypi"
        else f"https://registry.npmjs.org/{name}"
    )
    try:
        resp = await client.get(url)
    except Exception:
        return None  # fail-open: could not verify
    if resp.status_code == 404:
        return False
    if 200 <= resp.status_code < 300:
        return True
    return None  # any other status → could not verify


async def check_install_command(command: str, *, timeout: float = 5.0) -> str | None:
    """Return a block-reason string if any parsed package is a definitive 404
    on its registry, else ``None``.

    Fail-open everywhere: guard disabled, no parseable packages, network error,
    non-404 status, or a private index all return ``None`` so legitimate
    installs are never broken.
    """
    from core.config import settings

    if not settings.package_install_guard:
        return None

    packages = parse_install_packages(command)
    if not packages:
        return None

    missing: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for registry, name in packages:
                exists = await _exists(client, registry, name)
                if exists is False:
                    missing.append(name)
    except Exception:
        return None  # fail-open

    if not missing:
        return None
    return (
        "Refusing install: package(s) not found on registry (possible "
        f"hallucinated/slopsquatted name): {', '.join(missing)}. "
        "Verify the name before installing."
    )
