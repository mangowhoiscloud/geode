"""Render the GEODE Homebrew formula from release artifact metadata.

This script intentionally does not publish to a tap. It renders a formula file
that can be copied into a separate `homebrew-geode` tap after the GitHub release
asset URL and SHA-256 are final.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_version(version: str) -> str:
    if not _VERSION_RE.fullmatch(version):
        raise SystemExit(f"invalid version: {version!r}")
    return version


def _validate_sha256(digest: str) -> str:
    if not _SHA256_RE.fullmatch(digest):
        raise SystemExit("sdist sha256 must be a lowercase 64-character hex digest")
    return digest


def _read_resources(path: Path | None) -> str:
    if path is None:
        return (
            "  # Python dependency resource stanzas are required before publishing.\n"
            "  # Generate them in the tap checkout with:\n"
            "  #   brew update-python-resources --print-only geode\n"
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"empty resources file: {path}")
    return text + "\n"


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
        "{{SDIST_URL}}": sdist_url,
        "{{SDIST_SHA256}}": _validate_sha256(sdist_sha256),
        "{{PYTHON_FORMULA}}": python_formula,
        "{{RESOURCE_STANZAS}}": resources.rstrip(),
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
    parser.add_argument("--resources-file", type=Path)
    parser.add_argument("--python-formula", default="python@3.12")
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("packaging/homebrew/geode.rb.in"),
    )
    args = parser.parse_args()

    rendered = render_formula(
        version=args.version,
        sdist_url=args.sdist_url,
        sdist_sha256=args.sdist_sha256,
        python_formula=args.python_formula,
        resources=_read_resources(args.resources_file),
        template=args.template,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
