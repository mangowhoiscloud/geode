"""Contract tests for scripts/build_publication_bundle.py."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest
import yaml
from core.paths import AUTORESEARCH_STATE_DIR
from evals.petri.judge_dims import BUILTIN_DIM_SETS, DEFAULT_DIM_SET
from evals.seed_generation.orchestrator import _TASK_PREFIX_TO_PHASE
from evolve.scaffold_search import gate
from evolve.scaffold_search.gate import _VALID_PROMOTE_POLICIES
from evolve.scaffold_search.ledger import _BASELINE_REGISTRY_KIND, RESULTS_TSV_HEADER
from evolve.scaffold_search.loop.mutate.policies import _KIND_TO_PATH
from evolve.scaffold_search.loop.observe import statistical_power
from evolve.scaffold_search.loop.observe.role_provenance import source_to_lane
from scripts import build_publication_bundle as bundle
from scripts.architecture_baseline import OUTPUT_FILE as ARCHITECTURE_BASELINE_FILE
from scripts.git_command import run_git

_COMMIT = "0" * 40
_EPOCH = 1_790_000_000
_REQUIRED = {
    "pyproject.toml": '[project]\nname = "geode"\nversion = "9.9.9"\n',
    "CHANGELOG.md": "# Changelog\n",
    "docs/eval/index.json": '{"runs": []}\n',
    ARCHITECTURE_BASELINE_FILE.relative_to(bundle.REPO_ROOT).as_posix(): "{}\n",
}
_HUB = {
    "docs/self-improving/petri-bundle/logs/a.eval": "eval-a",
    "docs/self-improving/petri-bundle/logs/listing.json": "{}\n",
    "docs/self-improving/petri-bundle/seeds/listing.json": '{"runs": []}\n',
    "docs/self-improving/petri-bundle/seeds/run-1/state.json": "{}\n",
    "docs/self-improving/seed-generation/bundle/logs/b.eval": "eval-b",
    "docs/self-improving/autoresearch/baseline/transcripts.json": "[]\n",
    "docs/self-improving/run-2606-demo.md": "# run\n",
    "evolve/scaffold_search/state/mutations.jsonl": "{}\n",
    "evolve/scaffold_search/state/policies/tool-policy.json": "{}\n",
    "evolve/scaffold_search/state/published/baseline.json": '{"stale": false}\n',
    "evolve/scaffold_search/state/published/campaign-progress.json": '{"cycles": []}\n',
    "docs/audits/eval-logs/MANIFEST.jsonl": "{}\n",
    "docs/audits/eval-logs/x.summary.yaml": "dims: {}\n",
    "evals/petri/seeds_gen1/seed.md": "---\nreferences: []\n---\n",
}
_RENDERED = {
    "docs/self-improving/petri-bundle/seeds/index.html": "<html>",
    "docs/self-improving/petri-bundle/seeds/run-1/report.html": "<html>",
    "docs/self-improving/petri-bundle/seeds/run-1/page.html.template": "{{ x }}",
    "docs/self-improving/petri-bundle/seeds/run-1/assets/viewer.js": "js",
    "docs/self-improving/petri-bundle/seeds/.DS_Store": "junk",
    "docs/self-improving/petri-bundle/logs/index.html": "<html>",
    "docs/self-improving/index.html": "<html>",
    "docs/self-improving/index.html.template": "{{ x }}",
}


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    result = run_git(["-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root)
    assert result.returncode == 0, result.stderr


def _commit(root: Path, epoch: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit everything with a fixed committer date (git reads it from the env)."""
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{epoch} +0000")
    monkeypatch.setenv("GIT_AUTHOR_DATE", f"@{epoch} +0000")
    if not (root / ".git").exists():
        _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "fixture")


def _build(root: Path) -> bundle.BuiltBundle:
    return bundle.build_bundle(root, source_commit=_COMMIT, source_date_epoch=_EPOCH)


def _members(archive: bytes) -> list[tuple[tarfile.TarInfo, bytes]]:
    out: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for info in tar.getmembers():
            handle = tar.extractfile(info)
            assert handle is not None
            out.append((info, handle.read()))
    return out


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    _write(root, {**_REQUIRED, **_HUB, **_RENDERED})
    _commit(root, _EPOCH - 86_400, monkeypatch)
    return root


def test_rebuild_with_different_mtimes_is_byte_identical(repo: Path, tmp_path: Path) -> None:
    first = _build(repo)
    files = sorted(p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts)
    for index, path in enumerate(files):
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
    second = _build(repo)

    assert second.archive == first.archive
    archive_a, manifest_a = bundle.write_bundle(first, tmp_path / "a")
    archive_b, manifest_b = bundle.write_bundle(second, tmp_path / "b")
    assert archive_a.name == archive_b.name == first.archive_name
    assert archive_a.name == f"geode-publication-{hashlib.sha256(first.archive).hexdigest()}.tar.gz"
    assert archive_a.read_bytes() == archive_b.read_bytes()
    assert manifest_a.read_bytes() == manifest_b.read_bytes() == first.manifest_bytes


def test_archive_headers_are_normalised(repo: Path) -> None:
    built = _build(repo)

    assert built.archive[:3] == b"\x1f\x8b\x08"
    assert built.archive[3] == 0  # no FNAME/FEXTRA/FCOMMENT
    assert built.archive[4:8] == b"\x00\x00\x00\x00"  # gzip mtime
    members = _members(built.archive)
    names = [info.name for info, _ in members]
    assert names[0] == bundle.MANIFEST_NAME
    assert names[1:] == sorted(names[1:])
    for info, _ in members:
        assert info.isreg()
        assert (info.mode, info.uid, info.gid, info.uname, info.gname) == (0o644, 0, 0, "", "")
        assert info.mtime == _EPOCH


def test_manifest_records_every_archived_file_hash(repo: Path) -> None:
    built = _build(repo)
    members = {info.name: data for info, data in _members(built.archive)}

    assert members.pop(bundle.MANIFEST_NAME) == built.manifest_bytes
    manifest = json.loads(built.manifest_bytes)
    files = manifest["files"]
    assert [f["path"] for f in files] == sorted(members)
    for record in files:
        data = members[record["path"]]
        assert record["bytes"] == len(data)
        assert record["sha256"] == hashlib.sha256(data).hexdigest()
    lines = "".join(f"{f['sha256']} {f['bytes']} {f['path']}\n" for f in files)
    assert manifest["tree_sha256"] == hashlib.sha256(lines.encode()).hexdigest()
    assert manifest["file_count"] == len(files)
    assert manifest["total_bytes"] == sum(f["bytes"] for f in files)
    assert manifest["schema"] == "geode-publication-bundle"
    assert (manifest["schema_version"], manifest["layout_version"]) == (1, 1)
    assert manifest["geode_version"] == "9.9.9"
    assert manifest["source_commit"] == _COMMIT
    assert manifest["generated_at"] == "2026-09-21T14:13:20Z"
    assert members["hub/run-2606-demo.md"] == b"# run\n"
    assert "hub/state/policies/tool-policy.json" in members
    assert "hub/seed-candidates/seeds_gen1/seed.md" in members


def test_rendered_pages_templates_and_viewer_assets_are_excluded(repo: Path) -> None:
    paths = [f["path"] for f in _build(repo).manifest["files"]]

    assert not [p for p in paths if p.endswith((".html", ".template"))]
    assert not [p for p in paths if "/assets/" in p or "/." in p]
    assert "hub/petri-bundle/seeds/run-1/state.json" in paths


def test_missing_optional_inputs_are_listed_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, _REQUIRED)
    _commit(tmp_path, _EPOCH, monkeypatch)

    manifest = _build(tmp_path).manifest

    assert [f["path"] for f in manifest["files"]] == [
        "architecture/architecture-baseline.json",
        "changelog/CHANGELOG.md",
        "eval/index.json",
    ]
    expected_absent = sorted(
        f"{source.source_dir}/{pattern}"
        for source in bundle.BUNDLE_SOURCES
        if not source.required
        for pattern in source.patterns
    )
    assert manifest["optional_absent"] == expected_absent


def test_missing_required_input_fails(repo: Path) -> None:
    (repo / "docs" / "eval" / "index.json").unlink()

    with pytest.raises(bundle.BundleInputError, match=r"docs/eval/index\.json"):
        _build(repo)


def test_symlinked_input_fails(repo: Path) -> None:
    link = repo / "docs" / "self-improving" / "petri-bundle" / "logs" / "linked.eval"
    link.symlink_to(repo / "CHANGELOG.md")

    with pytest.raises(bundle.BundleInputError, match="symlinked"):
        _build(repo)


def test_hub_constants_export_geode_module_values() -> None:
    constants = bundle.collect_hub_constants()
    dim_entries = yaml.safe_load(BUILTIN_DIM_SETS[DEFAULT_DIM_SET].read_text(encoding="utf-8"))

    assert constants["results_tsv_header"] == list(RESULTS_TSV_HEADER)
    assert constants["policy_kind_to_path"] == {
        kind: path.relative_to(AUTORESEARCH_STATE_DIR).as_posix()
        for kind, path in _KIND_TO_PATH.items()
    }
    assert constants["statistical_power"] == {
        "target_effect_size": statistical_power.DEFAULT_TARGET_EFFECT_SIZE,
        "alpha": statistical_power.DEFAULT_ALPHA,
        "power": statistical_power.DEFAULT_POWER,
    }
    assert constants["judge_dimensions"] == {
        "dim_set": DEFAULT_DIM_SET,
        "names": [e["name"] if isinstance(e, dict) else e for e in dim_entries],
    }
    assert constants["promote_policies"] == sorted(_VALID_PROMOTE_POLICIES)
    assert constants["baseline_registry_kind"] == _BASELINE_REGISTRY_KIND
    assert constants["promote_margin"] == {
        "gain_sigma": gate._MARGIN_GAIN_SIGMA,
        "floor": gate._FITNESS_MARGIN_FLOOR_DEFAULT,
        "n1_critical_floor": gate.N1_FITNESS_MARGIN_FLOOR,
        "logic_version": gate.MARGIN_LOGIC_VERSION,
    }
    lanes = constants["credential_source_lanes"]
    assert lanes and all(source_to_lane(source) == lane for source, lane in lanes.items())
    assert constants["task_prefix_phases"] == [list(pair) for pair in _TASK_PREFIX_TO_PHASE]


def test_hub_constants_cover_the_generator_mirrors() -> None:
    hub = importlib.import_module("scripts.build_self_improving_hub")
    constants = bundle.collect_hub_constants()

    assert list(hub.AUTORESEARCH_RESULTS_TSV_HEADER) == constants["results_tsv_header"]
    assert {
        kind: Path(path).name for kind, path in constants["policy_kind_to_path"].items()
    } == hub._TARGET_KIND_TO_POLICY_FILE
    assert constants["statistical_power"] == {
        "target_effect_size": hub._POWER_DEFAULT_TARGET_EFFECT_SIZE,
        "alpha": hub._POWER_DEFAULT_ALPHA,
        "power": hub._POWER_DEFAULT_POWER,
    }
    assert set(hub._PILOT_DIM_ABBR) <= set(constants["judge_dimensions"]["names"])
    assert {arm for arm, _label in hub._EVIDENCE_ARMS} == set(constants["promote_policies"])
    assert constants["baseline_registry_kind"] == hub._BASELINE_REGISTRY_ROW_KIND
    assert constants["task_prefix_phases"] == [list(pair) for pair in hub._TASK_PREFIX_TO_PHASE]
    # Chip prefixes that are GEODE credential sources take their lane from GEODE.
    assert {"claude-cli", "openai-codex"} <= set(constants["credential_source_lanes"])
    assert {"claude-cli", "openai-codex"} <= set(hub.HARNESS_MAP)
    margin = constants["promote_margin"]
    rule = hub._render_campaign_margin_rule(None, {})
    assert f"max({margin['gain_sigma']}&middot;" in rule
    assert f"{margin['floor']} floor, {margin['n1_critical_floor']} if baseline N=1" in rule


def test_real_checkout_bundles_raw_hub_data_only() -> None:
    entries, _absent = bundle.collect_entries(bundle.REPO_ROOT)
    paths = {entry.path for entry in entries}

    assert {"changelog/CHANGELOG.md", "eval/index.json"} <= paths
    assert "architecture/architecture-baseline.json" in paths
    assert "hub/petri-bundle/seeds/listing.json" in paths
    assert "hub/state/mutations.jsonl" in paths
    assert "hub/state/published/campaign-progress.json" in paths
    assert not [p for p in paths if p.endswith((".html", ".template")) or "/assets/" in p]


def test_source_date_epoch_env_overrides_commit_time(tmp_path: Path) -> None:
    assert bundle.resolve_source_date_epoch(tmp_path, {"SOURCE_DATE_EPOCH": "42"}) == 42
    with pytest.raises(bundle.BundleInputError, match="non-negative integer"):
        bundle.resolve_source_date_epoch(tmp_path, {"SOURCE_DATE_EPOCH": "-1"})


def test_manifest_records_each_file_last_commit_time(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "docs" / "self-improving" / "run-2606-demo.md").write_text("# edited\n")
    _commit(repo, _EPOCH, monkeypatch)

    files = {f["path"]: f["committed_at"] for f in _build(repo).manifest["files"]}

    assert files["hub/run-2606-demo.md"] == "2026-09-21T14:13:20Z"
    assert files["changelog/CHANGELOG.md"] == "2026-09-20T14:13:20Z"
    assert set(files.values()) == {"2026-09-20T14:13:20Z", "2026-09-21T14:13:20Z"}


def test_shallow_clone_cannot_report_commit_times(repo: Path, tmp_path: Path) -> None:
    shallow = tmp_path / "shallow"
    result = run_git(["clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)])
    assert result.returncode == 0, result.stderr

    with pytest.raises(bundle.BundleInputError, match="shallow clone"):
        _build(shallow)


def test_published_state_snapshot_is_bundled_under_hub_state(repo: Path) -> None:
    manifest = _build(repo).manifest
    paths = {f["path"] for f in manifest["files"]}

    assert {
        "hub/state/published/baseline.json",
        "hub/state/published/campaign-progress.json",
    } <= paths
    assert {
        "evolve/scaffold_search/state/published/gen0-fitness-stderr.json",
        "evolve/scaffold_search/state/published/crucible-attempts.jsonl",
    } <= set(manifest["optional_absent"])


def test_cli_checks_reproducibility_and_rejects_uncommitted_inputs(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bundle, "REPO_ROOT", repo)
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    out = tmp_path / "out"

    assert bundle.main(["--out", str(out), "--check"]) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(list(out.glob("geode-publication-*.tar.gz"))) == 1
    assert len(manifest["source_commit"]) == 40

    (repo / "docs" / "self-improving" / "run-2606-demo.md").write_text("edited\n")
    assert bundle.main(["--check"]) == 2
    assert "not committed at HEAD" in capsys.readouterr().err
