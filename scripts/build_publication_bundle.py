#!/usr/bin/env python3
"""Build the deterministic GEODE publication bundle.

GEODE publishes raw documentation and self-improving hub inputs; a downstream
site repository renders them. This script packs those committed inputs into a
content-addressed ``geode-publication-<sha256>.tar.gz`` and writes the same
``manifest.json`` beside it (the archive also carries it at its root). The
contract, layout and versioning rules live in
``docs/architecture/publication-bundle.md``.

Equal inputs produce byte-identical archives: entries are sorted, every tar
header uses a fixed mode/owner and the source date as mtime, and the gzip
header carries no name or timestamp. The source date comes from
``SOURCE_DATE_EPOCH`` when set, otherwise from the HEAD commit time.

Usage::

    uv run python scripts/build_publication_bundle.py --out DIR
    uv run python scripts/build_publication_bundle.py --check            # build twice, compare
    uv run python scripts/build_publication_bundle.py --out DIR --check
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from core.paths import AUTORESEARCH_STATE_DIR, GEODE_REPO_URL, PUBLISHED_STATE_DIR
from evals.petri.judge_dims import DEFAULT_DIM_SET, resolve_dim_set
from evolve.crucible.publication import CRUCIBLE_ATTEMPTS_NAME
from evolve.scaffold_search.gate import _VALID_PROMOTE_POLICIES
from evolve.scaffold_search.ledger import _BASELINE_REGISTRY_KIND, RESULTS_TSV_HEADER
from evolve.scaffold_search.loop.mutate.policies import _KIND_TO_PATH
from evolve.scaffold_search.loop.observe import statistical_power
from evolve.scaffold_search.publication import PUBLISHED_STATE_FILES

from scripts.architecture_baseline import OUTPUT_FILE as ARCHITECTURE_BASELINE_FILE
from scripts.build_literature_listing import LITERATURE_DIR, SEED_GLOB
from scripts.build_seeds_listing import SEEDS_DIR
from scripts.git_command import GitExecutableNotFoundError, run_git

REPO_ROOT = Path(__file__).resolve().parents[1]

BUNDLE_SCHEMA = "geode-publication-bundle"
SCHEMA_VERSION = 1
"""Bump when a manifest field changes meaning or a required field is removed."""
LAYOUT_VERSION = 1
"""Bump when an in-bundle path moves or a source group changes destination."""

MANIFEST_NAME = "manifest.json"
ARCHIVE_PREFIX = "geode-publication-"
ARCHIVE_SUFFIX = ".tar.gz"
_FILE_MODE = 0o644
_GZIP_LEVEL = 9
_SHA1_HEX = re.compile(r"[0-9a-f]{40}")

# Generated pages, templates and vendored viewer bundles are rendered by the
# consuming site; the bundle carries raw data only.
_EXCLUDED_SUFFIXES = frozenset({".html", ".htm", ".template"})
_EXCLUDED_DIR_NAMES = frozenset({"assets"})

_STATE_DIR = AUTORESEARCH_STATE_DIR.relative_to(REPO_ROOT).as_posix()
_PUBLISHED_DIR = PUBLISHED_STATE_DIR.relative_to(AUTORESEARCH_STATE_DIR).as_posix()
_SEED_CANDIDATE_ROOT = "evals/petri"
if not SEED_GLOB.startswith(f"{_SEED_CANDIDATE_ROOT}/"):
    raise RuntimeError(f"literature seed glob moved outside {_SEED_CANDIDATE_ROOT}: {SEED_GLOB}")


class BundleInputError(RuntimeError):
    """A required bundle input is missing, unreadable, or not committed."""


@dataclass(frozen=True)
class BundleSource:
    """One repository input group and its destination inside the bundle."""

    bundle_dir: str
    source_dir: str
    patterns: tuple[str, ...]
    required: bool = False
    exclude_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BundleEntry:
    """One archived file, read once so its hash and archived bytes agree."""

    path: str
    source: str
    data: bytes
    sha256: str


@dataclass(frozen=True)
class BuiltBundle:
    """An in-memory bundle ready to be written."""

    archive: bytes
    archive_sha256: str
    manifest_bytes: bytes
    manifest: dict[str, Any]

    @property
    def archive_name(self) -> str:
        return f"{ARCHIVE_PREFIX}{self.archive_sha256}{ARCHIVE_SUFFIX}"


BUNDLE_SOURCES: tuple[BundleSource, ...] = (
    BundleSource("changelog", ".", ("CHANGELOG.md",), required=True),
    BundleSource("eval", "docs/eval", ("index.json",), required=True),
    BundleSource(
        "architecture",
        ARCHITECTURE_BASELINE_FILE.parent.relative_to(REPO_ROOT).as_posix(),
        (ARCHITECTURE_BASELINE_FILE.name,),
        required=True,
    ),
    BundleSource(
        "hub/petri-bundle/logs",
        "docs/self-improving/petri-bundle/logs",
        ("*.eval", "listing.json"),
    ),
    BundleSource("hub/petri-bundle/seeds", SEEDS_DIR, ("**/*",)),
    BundleSource(
        "hub/petri-bundle/literature",
        LITERATURE_DIR,
        ("*.json",),
        exclude_names=frozenset({"listing.json"}),
    ),
    BundleSource(
        "hub/seed-generation/bundle/logs",
        "docs/self-improving/seed-generation/bundle/logs",
        ("*.eval", "listing.json"),
    ),
    BundleSource(
        "hub/autoresearch/baseline",
        "docs/self-improving/autoresearch/baseline",
        ("transcripts.json",),
    ),
    BundleSource("hub", "docs/self-improving", ("run-*.md",)),
    BundleSource(
        "hub/state",
        _STATE_DIR,
        (
            "mutations.jsonl",
            "results.tsv",
            "results.jsonl",
            "baseline_archive.jsonl",
            "policies/*.json",
            *(
                f"{_PUBLISHED_DIR}/{name}"
                for name in (*PUBLISHED_STATE_FILES, CRUCIBLE_ATTEMPTS_NAME)
            ),
        ),
    ),
    BundleSource(
        "hub/audits/eval-logs", "docs/audits/eval-logs", ("MANIFEST.jsonl", "*.summary.yaml")
    ),
    BundleSource(
        "hub/seed-candidates",
        _SEED_CANDIDATE_ROOT,
        (SEED_GLOB.removeprefix(f"{_SEED_CANDIDATE_ROOT}/"),),
    ),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_excluded(relative: Path) -> bool:
    if any(part.startswith(".") for part in relative.parts):
        return True
    if relative.suffix.lower() in _EXCLUDED_SUFFIXES:
        return True
    return any(part in _EXCLUDED_DIR_NAMES for part in relative.parts[:-1])


def _source_matches(repo_root: Path, source: BundleSource, pattern: str) -> list[tuple[str, Path]]:
    """Return ``(bundle_path, file)`` pairs for one pattern of one source group."""
    root = repo_root / source.source_dir
    if not root.is_dir():
        return []
    matches: list[tuple[str, Path]] = []
    for path in root.glob(pattern):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise BundleInputError(f"symlinked bundle input is not allowed: {path}")
        if not path.is_file() or path.name in source.exclude_names or _is_excluded(relative):
            continue
        matches.append((f"{source.bundle_dir}/{relative.as_posix()}", path))
    return matches


def collect_entries(
    repo_root: Path, sources: Sequence[BundleSource] = BUNDLE_SOURCES
) -> tuple[list[BundleEntry], list[str]]:
    """Read every bundle input; return sorted entries and absent optional patterns."""
    selected: dict[str, Path] = {}
    optional_absent: list[str] = []
    for source in sources:
        for pattern in source.patterns:
            matches = _source_matches(repo_root, source, pattern)
            label = f"{source.source_dir}/{pattern}".removeprefix("./")
            if not matches:
                if source.required:
                    raise BundleInputError(f"required bundle input missing: {label}")
                optional_absent.append(label)
                continue
            for bundle_path, path in matches:
                previous = selected.setdefault(bundle_path, path)
                if previous != path:
                    raise BundleInputError(
                        f"bundle path collision: {bundle_path} <- {previous} and {path}"
                    )
    entries: list[BundleEntry] = []
    for bundle_path in sorted(selected):
        path = selected[bundle_path]
        data = path.read_bytes()
        entries.append(
            BundleEntry(
                path=bundle_path,
                source=path.relative_to(repo_root).as_posix(),
                data=data,
                sha256=_sha256(data),
            )
        )
    return entries, sorted(optional_absent)


def read_geode_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as fh:
        version = tomllib.load(fh).get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise BundleInputError("pyproject.toml has no [project].version")
    return version


def _judge_dimension_names() -> list[str]:
    dim_set = resolve_dim_set(DEFAULT_DIM_SET)
    if not isinstance(dim_set, Path):
        raise BundleInputError(f"default judge dimension set is not a built-in YAML: {dim_set}")
    raw = yaml.safe_load(dim_set.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise BundleInputError(f"judge dimension set is not a list: {dim_set}")
    names: list[str] = []
    for item in raw:
        name = item.get("name") if isinstance(item, Mapping) else item
        if not isinstance(name, str) or not name:
            raise BundleInputError(f"judge dimension entry has no name: {item!r}")
        names.append(name)
    return names


def collect_hub_constants() -> dict[str, Any]:
    """Export the GEODE values the hub generator otherwise mirrors by hand."""
    policy_paths: dict[str, str] = {}
    for kind, path in sorted(_KIND_TO_PATH.items()):
        try:
            policy_paths[kind] = path.relative_to(AUTORESEARCH_STATE_DIR).as_posix()
        except ValueError as exc:
            raise BundleInputError(f"policy path for {kind!r} is outside the state dir") from exc
    return {
        "results_tsv_header": list(RESULTS_TSV_HEADER),
        "policy_kind_to_path": policy_paths,
        "statistical_power": {
            "target_effect_size": statistical_power.DEFAULT_TARGET_EFFECT_SIZE,
            "alpha": statistical_power.DEFAULT_ALPHA,
            "power": statistical_power.DEFAULT_POWER,
        },
        "judge_dimensions": {
            "dim_set": DEFAULT_DIM_SET,
            "names": _judge_dimension_names(),
        },
        "promote_policies": sorted(_VALID_PROMOTE_POLICIES),
        "baseline_registry_kind": _BASELINE_REGISTRY_KIND,
    }


def tree_sha256(entries: Sequence[BundleEntry]) -> str:
    """Hash ``"<sha256> <bytes> <path>\\n"`` lines in sorted path order."""
    lines = "".join(
        f"{entry.sha256} {len(entry.data)} {entry.path}\n"
        for entry in sorted(entries, key=lambda e: e.path)
    )
    return _sha256(lines.encode("utf-8"))


def _iso_utc(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_manifest(
    entries: Sequence[BundleEntry],
    *,
    commit_times: Mapping[str, int],
    optional_absent: Sequence[str],
    geode_version: str,
    source_commit: str,
    source_date_epoch: int,
    hub_constants: Mapping[str, Any],
    sources: Sequence[BundleSource] = BUNDLE_SOURCES,
) -> dict[str, Any]:
    ordered = sorted(entries, key=lambda e: e.path)
    return {
        "schema": BUNDLE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "layout_version": LAYOUT_VERSION,
        "geode_version": geode_version,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "generated_at": _iso_utc(source_date_epoch),
        "repository_url": GEODE_REPO_URL,
        "sources": [
            {
                "bundle_dir": source.bundle_dir,
                "source_dir": source.source_dir,
                "patterns": list(source.patterns),
                "required": source.required,
            }
            for source in sources
        ],
        "optional_absent": list(optional_absent),
        "hub_constants": dict(hub_constants),
        "file_count": len(ordered),
        "total_bytes": sum(len(entry.data) for entry in ordered),
        "tree_sha256": tree_sha256(ordered),
        "files": [
            {
                "path": entry.path,
                "bytes": len(entry.data),
                "sha256": entry.sha256,
                "committed_at": _iso_utc(commit_times[entry.source]),
            }
            for entry in ordered
        ],
    }


def serialize_manifest(manifest: Mapping[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _tar_member(name: str, size: int, mtime: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = mtime
    info.mode = _FILE_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.type = tarfile.REGTYPE
    return info


def render_archive(manifest_bytes: bytes, entries: Sequence[BundleEntry], mtime: int) -> bytes:
    """Return deterministic ``.tar.gz`` bytes: manifest first, then sorted entries."""
    raw = io.BytesIO()
    with (
        gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=_GZIP_LEVEL, mtime=0
        ) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        tar.addfile(
            _tar_member(MANIFEST_NAME, len(manifest_bytes), mtime), io.BytesIO(manifest_bytes)
        )
        for entry in sorted(entries, key=lambda e: e.path):
            tar.addfile(_tar_member(entry.path, len(entry.data), mtime), io.BytesIO(entry.data))
    return raw.getvalue()


def build_bundle(
    repo_root: Path,
    *,
    source_commit: str,
    source_date_epoch: int,
    require_committed: bool = False,
) -> BuiltBundle:
    """Collect inputs and render the bundle in memory.

    ``require_committed`` rejects inputs that are untracked or differ from HEAD,
    so ``source_commit`` really identifies the bundled bytes.
    """
    entries, optional_absent = collect_entries(repo_root)
    if require_committed:
        assert_inputs_committed(repo_root, [entry.source for entry in entries] + ["pyproject.toml"])
    manifest = build_manifest(
        entries,
        commit_times=resolve_commit_times(repo_root, [entry.source for entry in entries]),
        optional_absent=optional_absent,
        geode_version=read_geode_version(repo_root),
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
        hub_constants=collect_hub_constants(),
    )
    manifest_bytes = serialize_manifest(manifest)
    archive = render_archive(manifest_bytes, entries, source_date_epoch)
    return BuiltBundle(
        archive=archive,
        archive_sha256=_sha256(archive),
        manifest_bytes=manifest_bytes,
        manifest=manifest,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_bundle(bundle: BuiltBundle, out_dir: Path) -> tuple[Path, Path]:
    """Write the archive and its sidecar manifest; return both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / bundle.archive_name
    manifest_path = out_dir / MANIFEST_NAME
    _atomic_write(archive_path, bundle.archive)
    _atomic_write(manifest_path, bundle.manifest_bytes)
    return archive_path, manifest_path


def _git_stdout(repo_root: Path, args: Sequence[str]) -> str:
    try:
        result = run_git(args, cwd=repo_root)
    except GitExecutableNotFoundError as exc:
        raise BundleInputError("git executable not found") from exc
    if result.returncode != 0:
        raise BundleInputError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve_source_commit(repo_root: Path) -> str:
    commit = _git_stdout(repo_root, ["rev-parse", "HEAD"]).strip()
    if not _SHA1_HEX.fullmatch(commit):
        raise BundleInputError(f"unexpected HEAD commit id: {commit!r}")
    return commit


def resolve_source_date_epoch(repo_root: Path, environ: Mapping[str, str] = os.environ) -> int:
    """``SOURCE_DATE_EPOCH`` when set, otherwise the HEAD commit timestamp."""
    raw = environ.get("SOURCE_DATE_EPOCH", "").strip()
    if not raw:
        raw = _git_stdout(repo_root, ["log", "-1", "--format=%ct", "HEAD"]).strip()
    if not raw.isdigit():
        raise BundleInputError(f"source date epoch is not a non-negative integer: {raw!r}")
    return int(raw)


def resolve_commit_times(repo_root: Path, sources: Sequence[str]) -> dict[str, int]:
    """Latest committer time of each source path; needs full (non-shallow) history."""
    if _git_stdout(repo_root, ["rev-parse", "--is-shallow-repository"]).strip() == "true":
        raise BundleInputError("shallow clone: per-file committed_at needs full git history")
    wanted = set(sources)
    pathspecs = sorted({path.rsplit("/", 1)[0] if "/" in path else path for path in wanted})
    log_args = ["-c", "core.quotepath=off", "log", "--format=@@%ct", "--name-only", "HEAD"]
    output = _git_stdout(repo_root, [*log_args, "--", *pathspecs])
    times: dict[str, int] = {}
    current = 0
    for line in output.splitlines():
        if line.startswith("@@"):
            current = int(line[2:])
        elif line in wanted and current > times.get(line, -1):
            times[line] = current
    missing = sorted(wanted - times.keys())
    if missing:
        raise BundleInputError(
            f"{len(missing)} bundle input(s) have no commit history: {', '.join(missing[:5])}"
        )
    return times


def assert_inputs_committed(repo_root: Path, sources: Sequence[str]) -> None:
    """Fail when a bundled file is untracked or differs from HEAD."""
    # Whole-repository listings keep the argv bounded however large the hub grows.
    paths = sorted(set(sources))
    tracked = set(_git_stdout(repo_root, ["ls-files", "-z"]).split("\0"))
    changed = set(_git_stdout(repo_root, ["diff", "--name-only", "-z", "HEAD"]).split("\0"))
    dirty = sorted(path for path in paths if path not in tracked or path in changed)
    if dirty:
        preview = ", ".join(dirty[:5]) + (" ..." if len(dirty) > 5 else "")
        raise BundleInputError(f"{len(dirty)} bundle input(s) not committed at HEAD: {preview}")


def _build_from_checkout(repo_root: Path) -> BuiltBundle:
    return build_bundle(
        repo_root,
        source_commit=resolve_source_commit(repo_root),
        source_date_epoch=resolve_source_date_epoch(repo_root),
        require_committed=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, help="directory for the archive and manifest.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="build twice and fail unless both archives are byte-identical",
    )
    args = parser.parse_args(argv)
    if args.out is None and not args.check:
        parser.error("--out is required unless --check is given")
    try:
        bundle = _build_from_checkout(REPO_ROOT)
        if args.check and _build_from_checkout(REPO_ROOT).archive != bundle.archive:
            print("publication bundle is not reproducible", file=sys.stderr)
            return 1
    except BundleInputError as exc:
        print(f"publication bundle: {exc}", file=sys.stderr)
        return 2
    if args.out is not None:
        archive_path, _ = write_bundle(bundle, args.out)
        print(archive_path)
    print(
        f"{bundle.archive_name} {len(bundle.archive)} bytes, "
        f"{bundle.manifest['file_count']} files, tree {bundle.manifest['tree_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
