"""Fail-closed merge admission with synthetic GitHub responses; never live mutations."""

from __future__ import annotations

import copy
import json
import subprocess
from typing import Any

import pytest
from scripts import merge_pr


def _evidence(head: str = "a" * 40, base: str = "b" * 40) -> dict[str, Any]:
    runs = [
        {
            "id": index,
            "name": name,
            "status": "completed",
            "conclusion": "success",
            "app": {"id": merge_pr.CHECK_APP_ID},
            "head_sha": head,
            "details_url": f"https://github.com/{merge_pr.REPOSITORY}/actions/runs/1/job/{index}",
        }
        for index, name in enumerate(merge_pr.REQUIRED_CHECKS, 100)
    ]
    return {
        "pr": {
            "state": "open",
            "draft": False,
            "merged": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "merge_commit_sha": "c" * 40,
            "head": {"ref": "codex/topic", "sha": head, "repo": {"full_name": merge_pr.REPOSITORY}},
            "base": {"ref": "develop", "sha": base, "repo": {"full_name": merge_pr.REPOSITORY}},
        },
        "base": {"commit": {"sha": base}},
        "protection": {
            "required_status_checks": {
                "strict": True,
                "contexts": list(merge_pr.REQUIRED_CHECKS),
                "checks": [
                    {"context": name, "app_id": merge_pr.CHECK_APP_ID}
                    for name in merge_pr.REQUIRED_CHECKS
                ],
            },
            "enforce_admins": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "required_pull_request_reviews": {"required_approving_review_count": 0},
        },
        "checks": {"total_count": len(runs), "check_runs": runs},
        "required": {
            "checks": [
                {"name": row["name"], "state": "SUCCESS", "link": row["details_url"]}
                for row in runs
            ]
        },
        "view": {
            "headRefOid": head,
            "baseRefOid": base,
            "baseRefName": "develop",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [
                {
                    "name": row["name"],
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "detailsUrl": row["details_url"],
                }
                for row in runs
            ],
        },
    }


class _GitHub:
    def __init__(self, *snapshots: dict[str, Any]) -> None:
        self.snapshots = snapshots
        self.current = snapshots[0]
        self.reads = 0
        self.mutations: list[list[str]] = []
        self.result: dict[str, Any] = {"merged": True, "sha": "d" * 40}
        self.readback_failure = False

    def __call__(self, arguments: list[str]) -> dict[str, Any]:
        if arguments[:2] == ["pr", "checks"]:
            assert arguments[arguments.index("--repo") + 1] == merge_pr.REPOSITORY
            assert arguments[-5:] == [
                "--required",
                "--json",
                "name,state,link",
                "--jq",
                "{checks: .}",
            ]
            return copy.deepcopy(self.current["required"])
        if arguments[:2] == ["pr", "view"]:
            assert arguments[arguments.index("--repo") + 1] == merge_pr.REPOSITORY
            return copy.deepcopy(self.current["view"])
        assert arguments[:2] == ["api", "--method"]
        method, endpoint = arguments[2:4]
        assert endpoint.startswith(f"repos/{merge_pr.REPOSITORY}/")
        if method == "PUT":
            assert endpoint.endswith("/pulls/3319/merge")
            self.mutations.append(arguments)
            return self.result
        assert method == "GET"
        if endpoint.endswith("/pulls/3319"):
            if self.mutations:
                if self.readback_failure:
                    raise merge_pr.MergeGuardError("readback unavailable")
                return self.current["pr"] | {
                    "merged": True,
                    "state": "closed",
                    "merge_commit_sha": "d" * 40,
                }
            self.current = self.snapshots[min(self.reads, len(self.snapshots) - 1)]
            self.reads += 1
            return copy.deepcopy(self.current["pr"])
        if endpoint.endswith("/protection"):
            return copy.deepcopy(self.current["protection"])
        if "/branches/" in endpoint:
            return copy.deepcopy(self.current["base"])
        assert endpoint.endswith("/check-runs?filter=latest&per_page=100")
        return copy.deepcopy(self.current["checks"])


def test_default_is_read_only_and_merge_is_exactly_once(monkeypatch, capsys) -> None:
    github = _GitHub(_evidence())
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["decision"] == "ready"
    assert len(receipt["checks"]) == 10
    assert github.mutations == []
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "merged"
    assert github.reads == 3  # one read-only snapshot plus two fresh pre-merge snapshots
    assert len(github.mutations) == 1
    assert github.mutations[0][-4:] == ["-f", "merge_method=squash", "-f", f"sha={'a' * 40}"]


@pytest.mark.parametrize(
    "status,conclusion",
    [
        ("in_progress", None),
        ("queued", None),
        ("completed", "failure"),
        ("completed", "skipped"),
        ("completed", "neutral"),
        ("completed", "cancelled"),
        ("completed", "timed_out"),
        ("completed", "action_required"),
    ],
)
def test_non_success_never_merges(monkeypatch, capsys, status, conclusion) -> None:
    data = _evidence()
    data["checks"]["check_runs"][3].update(status=status, conclusion=conclusion)
    github = _GitHub(data)
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["decision"] == "blocked"
    assert receipt["head_sha"] == "a" * 40 and receipt["base_sha"] == "b" * 40
    assert github.mutations == []


@pytest.mark.parametrize(
    "old_state,current_state",
    [("SKIPPED", "SUCCESS"), ("FAILURE", "SUCCESS")]
    + [
        ("SUCCESS", state)
        for state in ("SUCCESS", "FAILURE", "SKIPPED", "CANCELLED", "IN_PROGRESS", "QUEUED")
    ],
)
def test_native_current_check_selection_never_falls_back_to_old_success(
    monkeypatch, capsys, old_state: str, current_state: str
) -> None:
    data = _evidence()
    old = data["checks"]["check_runs"][0]
    old["conclusion"] = old_state.lower()
    data["view"]["statusCheckRollup"][0]["conclusion"] = old_state
    current = old | {
        "id": 1000,
        "details_url": f"https://github.com/{merge_pr.REPOSITORY}/actions/runs/2/job/1000",
        "status": "completed"
        if current_state in {"SUCCESS", "FAILURE", "SKIPPED", "CANCELLED"}
        else current_state.lower(),
        "conclusion": current_state.lower()
        if current_state in {"SUCCESS", "FAILURE", "SKIPPED", "CANCELLED"}
        else None,
    }
    data["checks"]["check_runs"].append(current)
    data["checks"]["total_count"] += 1
    data["view"]["statusCheckRollup"].append(
        {
            "name": current["name"],
            "status": current["status"].upper(),
            "conclusion": current_state if current["conclusion"] else None,
            "detailsUrl": current["details_url"],
        }
    )
    data["required"]["checks"][0].update(state=current_state, link=current["details_url"])
    github = _GitHub(data)
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == (0 if current_state == "SUCCESS" else 1)
    receipt = json.loads(capsys.readouterr().out)
    if current_state == "SUCCESS":
        assert receipt["checks"][current["name"]] == 1000
        assert len(github.mutations) == 1
    else:
        assert receipt["decision"] == "blocked"
        assert github.mutations == []


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unbound_link", "unknown_name"])
def test_native_selection_requires_exact_complete_binding(monkeypatch, capsys, defect: str) -> None:
    data = _evidence()
    selected = data["required"]["checks"]
    if defect == "missing":
        selected.pop()
    elif defect == "duplicate":
        selected.append(selected[0].copy())
    elif defect == "unbound_link":
        selected[0]["link"] += "0"
    else:
        selected[0]["name"] = "untrusted check"
    github = _GitHub(data)
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "blocked"
    assert github.mutations == []


@pytest.mark.parametrize(
    "defect",
    [
        "empty",
        "missing",
        "duplicate",
        "wrong_app",
        "stale_check",
        "rollup_stale",
        "rollup_missing",
        "rollup_pending",
        "truncated",
        "base_stale",
        "draft",
        "closed",
        "fork",
        "wrong_base",
        "sync_branch",
        "unknown_mergeability",
        "unprotected",
        "not_strict",
        "admin_bypass",
        "force_push",
        "deletion",
        "no_pr_requirement",
        "review_bypass",
        "policy_missing",
        "policy_extra",
        "policy_wrong_app",
        "invalid_shape",
    ],
)
def test_invalid_evidence_never_merges(monkeypatch, capsys, defect: str) -> None:
    data = _evidence()
    checks, protection, view = data["checks"], data["protection"], data["view"]
    runs = checks["check_runs"]
    if defect in {"empty", "missing", "duplicate"}:
        runs[:] = [] if defect == "empty" else runs[:-1] if defect == "missing" else runs + runs[:1]
        checks["total_count"] = len(runs)
    elif defect == "wrong_app":
        runs[0]["app"]["id"] = 1
    elif defect == "stale_check":
        runs[0]["head_sha"] = "e" * 40
    elif defect == "rollup_stale":
        view["statusCheckRollup"][0]["detailsUrl"] += "0"
    elif defect == "rollup_missing":
        view["statusCheckRollup"] = []
    elif defect == "rollup_pending":
        view["statusCheckRollup"][0]["status"] = "IN_PROGRESS"
    elif defect == "truncated":
        checks["total_count"] += 1
    elif defect == "base_stale":
        data["base"]["commit"]["sha"] = "e" * 40
    elif defect == "draft":
        data["pr"]["draft"] = True
    elif defect == "closed":
        data["pr"]["state"] = "closed"
    elif defect == "fork":
        data["pr"]["head"]["repo"]["full_name"] = "external/fork"
    elif defect == "wrong_base":
        data["pr"]["base"]["ref"] = "main"
    elif defect == "sync_branch":
        data["pr"]["head"]["ref"] = "sync/main-into-develop-topic"
    elif defect == "unknown_mergeability":
        data["pr"]["mergeable"] = None
    elif defect == "unprotected":
        data["protection"] = {}
    elif defect == "not_strict":
        protection["required_status_checks"]["strict"] = False
    elif defect == "admin_bypass":
        protection["enforce_admins"]["enabled"] = False
    elif defect in {"force_push", "deletion"}:
        protection["allow_force_pushes" if defect == "force_push" else "allow_deletions"][
            "enabled"
        ] = True
    elif defect == "no_pr_requirement":
        protection["required_pull_request_reviews"] = None
    elif defect == "review_bypass":
        protection["required_pull_request_reviews"]["bypass_pull_request_allowances"] = {
            "users": [1]
        }
    elif defect == "policy_missing":
        protection["required_status_checks"]["checks"].pop()
    elif defect == "policy_extra":
        protection["required_status_checks"]["checks"].append(
            {"context": "New gate", "app_id": 15368}
        )
    elif defect == "policy_wrong_app":
        protection["required_status_checks"]["checks"][0]["app_id"] = None
    else:
        data["pr"]["head"] = None
    github = _GitHub(data)
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "blocked"
    assert github.mutations == []


@pytest.mark.parametrize("drift", ["head", "base", "checks", "protection"])
def test_second_snapshot_drift_never_merges(monkeypatch, drift: str) -> None:
    first, second = _evidence(), _evidence()
    if drift == "head":
        second = _evidence(head="e" * 40)
    elif drift == "base":
        second = _evidence(base="e" * 40)
    elif drift == "checks":
        second["checks"]["check_runs"][0]["conclusion"] = "failure"
    else:
        second["protection"]["enforce_admins"]["enabled"] = False
    github = _GitHub(first, second)
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 1
    assert github.mutations == []


@pytest.mark.parametrize("head,base", [("main", "develop"), ("develop", "main")])
def test_canonical_promotion_uses_merge_method(monkeypatch, head: str, base: str) -> None:
    data = _evidence()
    data["pr"]["head"]["ref"], data["pr"]["base"]["ref"] = head, base
    data["view"]["baseRefName"] = base
    github = _GitHub(data)
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 0
    assert "merge_method=merge" in github.mutations[0]


@pytest.mark.parametrize("failure", ["response", "readback"])
def test_uncertain_merge_is_not_retried_or_reported_success(
    monkeypatch, capsys, failure: str
) -> None:
    github = _GitHub(_evidence())
    if failure == "response":
        github.result = {"merged": False}
    else:
        github.readback_failure = True
    monkeypatch.setattr(merge_pr, "_gh", github)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "merge_outcome_unknown"
    assert len(github.mutations) == 1


@pytest.mark.parametrize("option", ["--admin", "--auto", "--expected-check", "--force"])
def test_cli_has_no_bypass_option(monkeypatch, option: str) -> None:
    github = _GitHub(_evidence())
    monkeypatch.setattr(merge_pr, "_gh", github)
    with pytest.raises(SystemExit, match="2"):
        merge_pr.main(["--pr", "3319", option])
    assert github.reads == 0 and github.mutations == []


def test_lookup_failure_is_bounded_and_never_mutates(monkeypatch, capsys) -> None:
    def failed(_arguments):
        raise merge_pr.MergeGuardError("GitHub response unavailable or invalid; inspect remotely")

    monkeypatch.setattr(merge_pr, "_gh", failed)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "blocked"


@pytest.mark.parametrize("failure", ["exit", "json", "object", "timeout", "executable"])
def test_gh_boundary_hides_raw_errors_and_never_mutates(monkeypatch, capsys, failure: str) -> None:
    calls = []
    monkeypatch.setattr(
        merge_pr.shutil, "which", lambda _name: None if failure == "executable" else "gh"
    )

    def run(arguments, **_kwargs):
        calls.append(arguments)
        assert arguments[1:4] == ["api", "--method", "GET"]
        if failure == "timeout":
            raise subprocess.TimeoutExpired(arguments, 60, output="SECRET_FIXTURE")
        return subprocess.CompletedProcess(
            arguments,
            1 if failure == "exit" else 0,
            stdout="[]" if failure == "object" else "SECRET_FIXTURE",
            stderr="SECRET_FIXTURE",
        )

    monkeypatch.setattr(merge_pr.subprocess, "run", run)
    assert merge_pr.main(["--pr", "3319", "--merge"]) == 1
    output = capsys.readouterr()
    assert "SECRET_FIXTURE" not in output.out + output.err
    assert json.loads(output.out)["decision"] == "blocked"
    assert len(calls) == (0 if failure == "executable" else 1)
