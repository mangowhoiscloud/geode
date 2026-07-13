import json
from pathlib import Path

import pytest
from scripts.eval.publish_crucible_artifacts import (
    REDACTED_HOME,
    mask_text_file,
    mask_tree,
    stage_run,
)


def _run(tmp_path: Path) -> Path:
    run = tmp_path / "tau2-telecom-gpt54-train-20260713-r99"
    (run / "state" / "attempts" / "0001-abc").mkdir(parents=True)
    (run / "prepare").mkdir()
    (run / "config.json").write_text(
        json.dumps({"repository": "/Users/alice/workspace/geode"}), encoding="utf-8"
    )
    (run / "loop-r99.log").write_text("cwd /Users/alice/workspace\n", encoding="utf-8")
    (run / "prepare" / "power.json").write_text(json.dumps({"passes": True}), encoding="utf-8")
    (run / "state" / "summary.json").write_text(json.dumps({"invalids": 1}), encoding="utf-8")
    (run / "state" / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
    (run / "state" / "attempts" / "0001-abc" / "error.json").write_text("{}", encoding="utf-8")
    # reproducible-cache + sealed that must NOT be staged
    (run / "state" / "attempts" / "0001-abc" / "evaluation-x").mkdir()
    (run / "state" / "attempts" / "0001-abc" / "evaluation-x" / "transcript.jsonl").write_text(
        "/Users/alice secret trace\n", encoding="utf-8"
    )
    (run / "sealed.pack.json").write_text(json.dumps({"tasks": ["hidden"]}), encoding="utf-8")
    return run


def test_mask_is_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"p": "/Users/alice/x"}), encoding="utf-8")
    assert mask_text_file(f, user="alice") is True
    assert "/Users/alice" not in f.read_text(encoding="utf-8")
    assert REDACTED_HOME in f.read_text(encoding="utf-8")
    # second pass changes nothing
    assert mask_text_file(f, user="alice") is False


def test_mask_preserves_json_validity(tmp_path: Path) -> None:
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"repo": "/Users/alice/workspace/geode"}), encoding="utf-8")
    mask_text_file(f, user="alice")
    assert json.loads(f.read_text(encoding="utf-8"))["repo"] == "/Users/REDACTED/workspace/geode"


def test_stage_allowlists_and_masks_omitting_cache_and_sealed(tmp_path: Path) -> None:
    run = _run(tmp_path)
    dest = tmp_path / "campaigns"
    report = stage_run(run, dest, user="alice")
    staged = set(report["files"])
    assert "config.json" in staged
    assert "state/summary.json" in staged
    assert "prepare/power.json" in staged
    # cache and sealed are omitted (not in the allowlist)
    assert not any("evaluation-x" in p for p in staged)
    assert not any("sealed" in p for p in staged)
    # no cache dir copied
    assert not (dest / run.name / "state" / "attempts" / "0001-abc" / "evaluation-x").exists()
    # masked on the way in
    assert "/Users/alice" not in (dest / run.name / "config.json").read_text(encoding="utf-8")


def test_stage_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    run = _run(tmp_path)
    dest = tmp_path / "campaigns"
    stage_run(run, dest, user="alice")
    with pytest.raises(SystemExit, match="append-only"):
        stage_run(run, dest, user="alice")


def test_mask_tree_skips_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x.json").write_text("/Users/alice", encoding="utf-8")
    (tmp_path / "y.json").write_text("/Users/alice", encoding="utf-8")
    assert mask_tree(tmp_path, user="alice") == 1
    assert (tmp_path / ".git" / "x.json").read_text(encoding="utf-8") == "/Users/alice"
