"""Render the GEODE Homebrew formula from immutable release metadata.

The renderer prepares a Homebrew/core candidate from a published GEODE release.
It refuses tag auto-tarballs, incomplete resources, and version-mismatched sdist
URLs so a formula cannot look valid while pointing at the wrong build.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PYTHON_FORMULA_RE = re.compile(r"^python@\d+\.\d+$")
_RESOURCE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _validate_version(version: str) -> str:
    if not _VERSION_RE.fullmatch(version):
        raise SystemExit(f"invalid version: {version!r}")
    return version


def _validate_sha256(digest: str) -> str:
    if not _SHA256_RE.fullmatch(digest):
        raise SystemExit("sdist sha256 must be a lowercase 64-character hex digest")
    return digest


def _validate_sdist_url(version: str, url: str) -> str:
    expected = (
        "https://github.com/mangowhoiscloud/geode/releases/download/"
        f"v{version}/geode_agent-{version}.tar.gz"
    )
    if url != expected:
        raise SystemExit(f"sdist URL must be the immutable GitHub release asset: {expected}")
    return url


def _validate_python_formula(formula: str) -> str:
    if not _PYTHON_FORMULA_RE.fullmatch(formula):
        raise SystemExit(f"invalid Homebrew Python formula: {formula!r}")
    return formula


def extract_resource_stanzas(formula: str) -> str:
    """Extract top-level Python ``resource`` blocks from a formula."""

    blocks: list[str] = []
    current: list[str] = []
    in_resource = False
    for line in formula.splitlines():
        if not in_resource and line.startswith('  resource "') and line.endswith(" do"):
            current = [line]
            in_resource = True
            continue
        if not in_resource:
            continue
        current.append(line)
        if line == "  end":
            blocks.append("\n".join(current))
            current = []
            in_resource = False
    if in_resource:
        raise SystemExit("unterminated resource block in Homebrew formula")
    if not blocks:
        raise SystemExit("Homebrew formula contains no Python resource blocks")
    return "\n\n".join(blocks) + "\n"


def _validate_resources(text: str) -> str:
    resources = text.strip("\n")
    if not resources.strip():
        raise SystemExit("Python dependency resource stanzas are required")
    blocks = extract_resource_stanzas(resources)
    names: set[str] = set()
    for block in blocks.split("\n\n"):
        lines = block.splitlines()
        if len(lines) != 4:
            raise SystemExit("each Homebrew resource must contain only name, URL, SHA-256, and end")

        header = re.fullmatch(r'  resource "([^"]+)" do', lines[0])
        if header is None or not _RESOURCE_NAME_RE.fullmatch(header.group(1)):
            raise SystemExit("each Homebrew resource must use a valid package name")
        name = header.group(1)
        if name in names:
            raise SystemExit(f"duplicate Homebrew resource: {name}")
        names.add(name)

        url_match = re.fullmatch(r'    url "([^"]+)"', lines[1])
        if url_match is None:
            raise SystemExit("each Homebrew resource must contain one canonical URL")
        url = urlsplit(url_match.group(1))
        if (
            url.scheme != "https"
            or url.netloc != "files.pythonhosted.org"
            or not url.path.startswith("/packages/")
            or url.query
            or url.fragment
        ):
            raise SystemExit(
                "each Homebrew resource must use a canonical files.pythonhosted.org URL"
            )

        sha_match = re.fullmatch(r'    sha256 "([0-9a-f]+)"', lines[2])
        if sha_match is None or not _SHA256_RE.fullmatch(sha_match.group(1)):
            raise SystemExit("each Homebrew resource must pin a lowercase SHA-256")
        if lines[3] != "  end":
            raise SystemExit("each Homebrew resource must end after its SHA-256")
    return blocks


def _read_resources(path: Path, *, from_formula: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"empty resources file: {path}")
    if from_formula:
        text = extract_resource_stanzas(text)
    return _validate_resources(text)


def render_formula(
    *,
    version: str,
    sdist_url: str,
    sdist_sha256: str,
    python_formula: str,
    resources: str,
    template: Path,
) -> str:
    body = template.read_text(encoding="utf-8")
    replacements = {
        "{{VERSION}}": _validate_version(version),
        "{{SDIST_URL}}": _validate_sdist_url(version, sdist_url),
        "{{SDIST_SHA256}}": _validate_sha256(sdist_sha256),
        "{{PYTHON_FORMULA}}": _validate_python_formula(python_formula),
        "{{RESOURCE_STANZAS}}": _validate_resources(resources).rstrip(),
    }
    for marker, value in replacements.items():
        body = body.replace(marker, value)
    unresolved = sorted(set(re.findall(r"{{[A-Z0-9_]+}}", body)))
    if unresolved:
        raise SystemExit(f"unresolved template markers: {', '.join(unresolved)}")
    return body.rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sdist-url", required=True)
    parser.add_argument("--sdist-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    resource_source = parser.add_mutually_exclusive_group(required=True)
    resource_source.add_argument(
        "--resources-file",
        type=Path,
        help="File containing only Homebrew Python resource blocks",
    )
    resource_source.add_argument(
        "--resources-from-formula",
        type=Path,
        help="Existing formula whose Python resource blocks should be reused",
    )
    parser.add_argument("--python-formula", default="python@3.12")
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("packaging/homebrew/geode-agent.rb.in"),
    )
    args = parser.parse_args()

    resource_path = args.resources_file or args.resources_from_formula
    if resource_path is None:  # argparse enforces the mutually exclusive group
        raise SystemExit("a Homebrew resource source is required")

    rendered = render_formula(
        version=args.version,
        sdist_url=args.sdist_url,
        sdist_sha256=args.sdist_sha256,
        python_formula=args.python_formula,
        resources=_read_resources(
            resource_path,
            from_formula=args.resources_from_formula is not None,
        ),
        template=args.template,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
