#!/usr/bin/env python3

r"""check_docs_links — static + optional HTTP audit of every link in the docs site.

Walks ``site/src/`` for every link-shaped string and classifies it:

* **internal /docs/...** → must map to a page slug under ``site/src/app/docs/``.
* **internal /\<other\>...** → must map to a ``page.tsx`` under ``site/src/app/``.
* **anchor #...** → must match an ``id="..."`` somewhere on the page that emits it.
* **external http(s)://...** → reachable (HTTP 200/301/302/304 considered OK).
  Network check is opt-in via ``--http`` because it is slow + flaky on CI.

Build-time copy steps (e.g. ``docs/petri-bundle/`` → ``site/out/petri-bundle/``
done by ``.github/workflows/pages.yml``) are recognised so paths that are
served on the deployed site but absent from ``site/public/`` do not yield
false positives.

Scans these link patterns:

* JSX/TSX attribute       : ``href="..."``                          ``to="..."``
* JSX/TSX expr container  : ``href={"..."}`` ``href={`...`}``       ``src="..."``
* Markdown inside strings : ``[text](url)`` (CHANGELOG entries etc.)

Skips:

* ``mailto:`` / ``tel:`` / ``javascript:``
* template strings whose interpolation cannot be resolved statically
  (these are reported as ``UNRESOLVED`` instead of failed; treat as
  informational so a CI run does not block on dynamic links).

Exit codes:

* 0 — no broken links
* 1 — at least one broken link
* 2 — argparse / IO error

Usage::

    python scripts/check_docs_links.py                # static only
    python scripts/check_docs_links.py --http         # + reachability
    python scripts/check_docs_links.py --base site    # alt site root
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Patterns

# Captures the link string regardless of quote style — single, double, backtick.
# Allows `href={"..."}` and `href={`...`}` JSX expr forms by stripping `{` `}`.
_LINK_PATTERNS = [
    # JSX attribute href / src / to (incl. `{` wrapper for expr)
    re.compile(r"""\b(?:href|src|to)\s*=\s*\{?\s*['"`]([^'"`{}\s]+)['"`]"""),
    # Markdown link inside JS/TS strings — [text](url)
    re.compile(r"""\]\(([^)\s]+)\)"""),
]

_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "blob:")
_NETWORK_OK = {200, 201, 301, 302, 303, 304, 307, 308}


class Link(NamedTuple):
    """One link occurrence in a source file."""

    target: str
    file: Path
    line: int


def discover_links(root: Path) -> list[Link]:
    """Walk *.tsx / *.ts under ``root`` and emit every link-shaped string."""
    out: list[Link] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".tsx", ".ts"}:
            continue
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in _LINK_PATTERNS:
                for match in pattern.finditer(line):
                    target = match.group(1).strip()
                    if not target or target.startswith(_SKIP_SCHEMES):
                        continue
                    if target.endswith("..."):
                        # Changelog/example prose can contain placeholder links
                        # such as `/docs/...`; these are not navigable routes.
                        continue
                    if "${" in target:
                        # interpolated — record as unresolved (reported but
                        # not counted as broken)
                        out.append(Link(target=f"UNRESOLVED:{target}", file=path, line=lineno))
                        continue
                    out.append(Link(target=target, file=path, line=lineno))
    return out


def discover_app_pages(root: Path) -> set[str]:
    """Return the set of route paths reachable under ``site/src/app/``.

    A route is the directory of every `page.tsx` relative to ``app/`` with
    a leading slash. Example: ``site/src/app/docs/runtime/domains/page.tsx``
    → ``/docs/runtime/domains``.
    """
    app = root / "app"
    routes: set[str] = {"/"}  # root layout always serves /
    if not app.exists():
        return routes
    for page in app.rglob("page.tsx"):
        rel = page.parent.relative_to(app)
        slug = "/" + str(rel) if str(rel) != "." else "/"
        routes.add(slug.replace("\\", "/"))
    return routes


def discover_public_assets(public: Path) -> set[str]:
    """Top-level files / dirs inside ``site/public/`` are served at the
    site root. ``site/public/llms.txt`` → ``/llms.txt``."""
    out: set[str] = set()
    if not public.exists():
        return out
    for child in public.iterdir():
        out.add("/" + child.name)
        if child.is_dir():
            out.add("/" + child.name + "/")
    return out


def discover_build_time_copies(repo_root: Path) -> set[str]:
    """Paths that the Pages workflow injects into ``site/out/`` at build time
    so they appear at deploy URL even though they live outside ``site/``.

    Currently the only build-time copy is ``docs/petri-bundle/`` →
    ``site/out/petri-bundle/`` (`.github/workflows/pages.yml` Copy step).
    If more are added later, register them here.
    """
    out: set[str] = set()
    if (repo_root / "docs" / "petri-bundle" / "index.html").exists():
        out.add("/petri-bundle/")
        out.add("/petri-bundle")
    return out


def discover_ids(root: Path) -> dict[str, set[str]]:
    """Return ``{route: set(id_attr_values)}`` so anchor #foo can be
    validated against the page it points to.

    We index every ``id="foo"`` occurrence inside the same `page.tsx` so a
    same-page anchor (#section) resolves against its own page.
    """
    by_route: dict[str, set[str]] = defaultdict(set)
    app = root / "app"
    if not app.exists():
        return by_route
    id_re = re.compile(r"""\bid\s*=\s*['"`]([A-Za-z_][\w-]*)['"`]""")
    for page in app.rglob("page.tsx"):
        rel = page.parent.relative_to(app)
        route = "/" + str(rel) if str(rel) != "." else "/"
        route = route.replace("\\", "/")
        text = page.read_text(encoding="utf-8")
        for match in id_re.finditer(text):
            by_route[route].add(match.group(1))
    return by_route


# ---------------------------------------------------------------------------
# Classification + verdict

# Site is published under this base path on GitHub Pages.
_DEPLOY_BASE = "/geode"


def _strip_basepath(target: str) -> str:
    """Normalise ``/geode/docs/foo`` to ``/docs/foo`` so internal links that
    happen to include the deploy basepath still match the source-side routes.
    """
    if target.startswith(_DEPLOY_BASE + "/"):
        return target[len(_DEPLOY_BASE) :]
    if target == _DEPLOY_BASE:
        return "/"
    return target


def classify_and_check(
    links: list[Link],
    routes: set[str],
    assets: set[str],
    page_ids: dict[str, set[str]],
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(broken_lines, unresolved_lines, external_lines)``."""
    broken: list[str] = []
    unresolved: list[str] = []
    external: list[str] = []

    for link in links:
        target = link.target

        if target.startswith("UNRESOLVED:"):
            unresolved.append(f"  {link.file}:{link.line}  {target}")
            continue

        # External
        if target.startswith(("http://", "https://")):
            external.append(target)
            continue

        # Anchor only — link relative to the file that emits it
        if target.startswith("#"):
            # Compute route from file path
            # site/src/app/<route...>/page.tsx → /<route...>
            parts = link.file.parts
            try:
                app_idx = parts.index("app")
            except ValueError:
                continue
            route_segs = parts[app_idx + 1 : -1]
            route = "/" + "/".join(route_segs) if route_segs else "/"
            anchor = target[1:]
            if anchor and anchor not in page_ids.get(route, set()):
                broken.append(f"  {link.file}:{link.line}  anchor #{anchor} not found on {route}")
            continue

        # Internal absolute paths (incl. /geode/... basepath form)
        if target.startswith("/"):
            norm = _strip_basepath(target.split("#", 1)[0].split("?", 1)[0])
            if not norm:
                continue
            if norm in routes:
                continue
            if norm.endswith("/") and norm[:-1] in routes:
                continue
            if not norm.endswith("/") and (norm + "/") in routes:
                continue
            if norm in assets:
                continue
            if any(norm.startswith(a) for a in assets if a.endswith("/")):
                continue
            broken.append(f"  {link.file}:{link.line}  {target}")
            continue

        # Relative / scheme-less — best-effort, leave alone for now
        unresolved.append(f"  {link.file}:{link.line}  relative {target}")

    return broken, unresolved, external


# ---------------------------------------------------------------------------
# Optional HTTP probe for external links


def http_probe(urls: list[str], timeout: float = 8.0) -> list[str]:
    """Return list of broken external URLs.

    HEAD with GET fallback. Concurrency 8. Skipped if ``requests`` not
    installed; we then return an empty list and print a notice.
    """
    try:
        import requests
    except ImportError:
        print("  (skipping external probe — `pip install requests` to enable)", file=sys.stderr)
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    broken: list[str] = []

    def check(url: str) -> tuple[str, int | None]:
        try:
            r = requests.head(url, allow_redirects=True, timeout=timeout)
            if r.status_code in _NETWORK_OK:
                return url, r.status_code
            r = requests.get(url, allow_redirects=True, timeout=timeout)
            return url, r.status_code
        except Exception:
            return url, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(check, url): url for url in sorted(set(urls))}
        for fut in as_completed(futures):
            url, code = fut.result()
            if code not in _NETWORK_OK:
                broken.append(f"  {url}  →  HTTP {code}")

    return broken


# ---------------------------------------------------------------------------
# CLI


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("site"),
        help="site root (default: site)",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="also probe external https:// URLs (slow + network-dependent)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress unresolved list (keep broken summary only)",
    )
    args = parser.parse_args()

    src = args.base / "src"
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 2

    links = discover_links(src)
    routes = discover_app_pages(src)
    assets = discover_public_assets(args.base / "public")
    assets |= discover_build_time_copies(args.base.parent)
    page_ids = discover_ids(src)

    print(f"Scanned {len(links)} link occurrences in {args.base}/src/")
    print(f"  app routes:    {len(routes)}")
    print(f"  public assets: {len(assets)}")
    print()

    broken, unresolved, external = classify_and_check(links, routes, assets, page_ids)

    if broken:
        print(f"❌ {len(broken)} broken internal link(s):")
        for line in broken:
            print(line)
    else:
        print("✅ no broken internal links")
    print()

    if unresolved and not args.quiet:
        print(f"ℹ️  {len(unresolved)} unresolved (interpolated or relative):")
        for line in unresolved[:20]:
            print(line)
        if len(unresolved) > 20:
            print(f"  ... and {len(unresolved) - 20} more")
        print()

    ext_broken: list[str] = []
    print(f"  external URLs: {len(set(external))}")
    if args.http and external:
        print("Probing external URLs (HEAD with GET fallback)...")
        ext_broken = http_probe(external)
        if ext_broken:
            print(f"❌ {len(ext_broken)} broken external URL(s):")
            for line in ext_broken:
                print(line)
        else:
            print("✅ all external URLs reachable")

    return 1 if broken or ext_broken else 0


if __name__ == "__main__":
    sys.exit(main())
