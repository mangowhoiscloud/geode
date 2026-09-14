#!/usr/bin/env python3
"""Inspect GEODE merge admission; only an explicit --merge may mutate GitHub."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from typing import Any

from scripts.resolve_architecture_roadmap_trust import (
    SYNC_BRANCH_PREFIX,
    RoadmapTrustError,
    require_sync_parents,
)

REPOSITORY = "mangowhoiscloud/geode"
CHECK_APP_ID = 15368
REQUIRED_WORKFLOWS = {
    ".github/workflows/ci.yml": (
        "Detect changes",
        "Lint & Format",
        "Type Check",
        "Test",
        "Security Scan",
        "Gate",
    ),
    ".github/workflows/install-smoke.yml": (
        "ubuntu-latest — install / update / uninstall",
        "macos-latest — install / update / uninstall",
    ),
    ".github/workflows/pages.yml": (
        "Render lint (markdown + YAML + JSON)",
        "Build (Next.js static export)",
    ),
}
REQUIRED_CHECKS = tuple(name for names in REQUIRED_WORKFLOWS.values() for name in names)


class MergeGuardError(ValueError):
    """Missing, stale, or non-success evidence forbids the requested merge."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MergeGuardError(reason)


def _sha(value: Any) -> str:
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
        "invalid commit identity",
    )
    return str(value)


def _gh(arguments: list[str]) -> dict[str, Any]:
    executable = shutil.which("gh")
    _require(executable is not None, "gh is unavailable")
    try:
        result = subprocess.run(  # noqa: S603 - fixed CLI, argv only; never a shell
            [str(executable), *arguments], capture_output=True, text=True, timeout=60, check=False
        )
        _require(result.returncode == 0, "GitHub lookup or mutation failed; inspect remotely")
        value = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MergeGuardError("GitHub response unavailable or invalid; inspect remotely") from exc
    _require(isinstance(value, dict), "GitHub response is not an object")
    return dict(value)


def _api(path: str, *, fields: tuple[str, ...] = ()) -> dict[str, Any]:
    method = "PUT" if fields else "GET"
    return _gh(["api", "--method", method, f"repos/{REPOSITORY}/{path}", *fields])


def _identity(pr: dict[str, Any]) -> dict[str, Any]:
    _require(
        pr["state"] == "open" and pr["draft"] is False and pr["merged"] is False,
        "PR must be open and non-draft",
    )
    head, base = pr["head"], pr["base"]
    _require(
        head["repo"]["full_name"] == base["repo"]["full_name"] == REPOSITORY,
        "fork or repository mismatch",
    )
    flow = (head["ref"], base["ref"])
    if flow in {("main", "develop"), ("develop", "main")} or (
        base["ref"] == "develop" and head["ref"].startswith(SYNC_BRANCH_PREFIX)
    ):
        method = "merge"
    else:
        _require(
            base["ref"] == "develop"
            and head["ref"] not in {"main", "develop"}
            and not head["ref"].startswith("sync/"),
            "unsupported protected-branch flow",
        )
        method = "squash"
    return {
        "head_ref": head["ref"],
        "head_sha": _sha(head["sha"]),
        "base_ref": base["ref"],
        "base_sha": _sha(base["sha"]),
        "method": method,
        "test_merge_sha": _sha(pr["merge_commit_sha"]),
    }


def _select_workflows(pr: dict[str, Any], evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runs = evidence["workflow_runs"]
    _require(
        type(evidence["total_count"]) is int and evidence["total_count"] == len(runs),
        "workflow enumeration is incomplete",
    )
    selected = {}
    for path in REQUIRED_WORKFLOWS:
        candidates = [run for run in runs if run["path"] == path]
        _require(bool(candidates), "required PR workflow is missing")
        _require(
            all(type(run["run_number"]) is int and run["run_number"] > 0 for run in candidates)
            and len({run["workflow_id"] for run in candidates}) == 1
            and len({run["run_number"] for run in candidates}) == len(candidates),
            "workflow identity or ordering is ambiguous",
        )
        # Select the newest execution before inspecting success: no old-green fallback.
        run = max(candidates, key=lambda row: row["run_number"])
        _require(
            run["event"] == "pull_request"
            and run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPOSITORY
            and run["head_sha"] == pr["head"]["sha"]
            and run["head_branch"] == pr["head"]["ref"],
            "workflow event, repository or head mismatch",
        )
        linked = [row for row in run["pull_requests"] if row["number"] == pr["number"]]
        _require(
            len(linked) == 1
            and all(
                linked[0][side][key] == pr[side][key]
                for side in ("head", "base")
                for key in ("sha", "ref")
            ),
            "workflow PR association is stale or missing",
        )
        _require(
            run["status"] == "completed" and run["conclusion"] == "success",
            "latest PR workflow is not successful",
        )
        _require(
            all(
                type(run[key]) is int and run[key] > 0
                for key in ("id", "workflow_id", "check_suite_id")
            ),
            "invalid workflow run or suite identity",
        )
        selected[path] = run
    return selected


def validate_snapshot(
    pr: dict[str, Any],
    base: dict[str, Any],
    protection: dict[str, Any],
    checks: dict[str, Any],
    view: dict[str, Any],
    workflows: dict[str, Any],
    sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure admission predicate; job success never overrides missing server policy."""
    identity = _identity(pr)
    if identity["head_ref"].startswith(SYNC_BRANCH_PREFIX):
        if sync is None:
            raise MergeGuardError("sync graph evidence is missing")
        _require(_sha(sync["sha"]) == identity["head_sha"], "sync head changed")
        identity["main_sha"] = _sha(sync["main_sha"])
        try:
            require_sync_parents(
                tuple(_sha(parent["sha"]) for parent in sync["parents"]),
                identity["base_sha"],
                identity["main_sha"],
            )
        except RoadmapTrustError as exc:
            raise MergeGuardError(str(exc)) from exc
    _require(
        pr["mergeable"] is True and pr["mergeable_state"] == "clean", "PR mergeability is not clean"
    )
    _require(_sha(base["commit"]["sha"]) == identity["base_sha"], "base branch changed")
    _require(
        view["headRefOid"] == identity["head_sha"]
        and view["baseRefOid"] == identity["base_sha"]
        and view["baseRefName"] == identity["base_ref"]
        and view["mergeable"] == "MERGEABLE"
        and view["mergeStateStatus"] == "CLEAN",
        "current PR rollup identity or mergeability changed",
    )
    policy = protection["required_status_checks"]
    _require(
        policy["strict"] is True and protection["enforce_admins"]["enabled"] is True,
        "strict checks and administrator enforcement are required",
    )
    _require(
        protection["allow_force_pushes"]["enabled"] is False
        and protection["allow_deletions"]["enabled"] is False,
        "protected branch permits force push or deletion",
    )
    reviews = protection["required_pull_request_reviews"]
    _require(isinstance(reviews, dict), "pull requests are not required")
    _require(
        not any(reviews.get("bypass_pull_request_allowances", {}).values()),
        "pull-request bypass allowances are forbidden",
    )
    required = policy["checks"]
    _require(
        len(required) == len(REQUIRED_CHECKS)
        and {row["context"] for row in required} == set(REQUIRED_CHECKS)
        and all(type(row["app_id"]) is int and row["app_id"] == CHECK_APP_ID for row in required),
        "required check policy differs from the fixed policy",
    )
    _require(set(policy["contexts"]) == set(REQUIRED_CHECKS), "required contexts differ")
    runs = checks["check_runs"]
    _require(
        type(checks["total_count"]) is int and checks["total_count"] == len(runs),
        "check enumeration is incomplete",
    )
    selected = _select_workflows(pr, workflows)
    admitted = {}
    for name in REQUIRED_CHECKS:
        workflow = next(
            selected[path] for path, names in REQUIRED_WORKFLOWS.items() if name in names
        )
        matching = [
            row
            for row in runs
            if row.get("name") == name and row["check_suite"]["id"] == workflow["check_suite_id"]
        ]
        _require(len(matching) == 1, "required check missing or ambiguous in selected PR workflow")
        run = matching[0]
        rolled = [
            row
            for row in view["statusCheckRollup"]
            if row.get("name") == name and row.get("detailsUrl") == run["details_url"]
        ]
        _require(len(rolled) == 1, "required PR check missing or ambiguous in rollup")
        current = rolled[0]
        _require(
            type(run["app"]["id"]) is int
            and run["app"]["id"] == CHECK_APP_ID
            and run["head_sha"] == identity["head_sha"],
            "check source or revision mismatch",
        )
        _require(
            run["status"] == "completed"
            and run["conclusion"] == "success"
            and current["status"] == "COMPLETED"
            and current["conclusion"] == "SUCCESS",
            "required check is not successful",
        )
        _require(
            type(run["id"]) is int
            and run["id"] > 0
            and current["detailsUrl"] == run["details_url"]
            and isinstance(run["details_url"], str)
            and run["details_url"]
            == (f"https://github.com/{REPOSITORY}/actions/runs/{workflow['id']}/job/{run['id']}"),
            "current PR check-run association is unverified",
        )
        admitted[name] = run["id"]
    return identity | {
        "checks": admitted,
        "workflow_runs": {path: run["id"] for path, run in selected.items()},
        "decision": "ready",
    }


def _snapshot(number: int, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    pr = _api(f"pulls/{number}")
    identity = _identity(pr)
    if receipt is not None:
        receipt.update(identity)  # Identity remains inspectable even when later admission fails.
    base = _api(f"branches/{identity['base_ref']}")
    protection = _api(f"branches/{identity['base_ref']}/protection")
    checks = _api(f"commits/{identity['head_sha']}/check-runs?filter=latest&per_page=100")
    workflows = _api(
        f"actions/runs?event=pull_request&head_sha={identity['head_sha']}&per_page=100"
    )
    view = _gh(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            REPOSITORY,
            "--json",
            "headRefOid,baseRefName,baseRefOid,mergeable,mergeStateStatus,statusCheckRollup",
        ]
    )
    sync = None
    if identity["head_ref"].startswith(SYNC_BRANCH_PREFIX):
        sync = _api(f"commits/{identity['head_sha']}")
        sync["main_sha"] = _api("branches/main")["commit"]["sha"]
    return validate_snapshot(pr, base, protection, checks, view, workflows, sync)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--repo", choices=(REPOSITORY,), default=REPOSITORY)
    parser.add_argument(
        "--merge", action="store_true", help="explicitly authorize one guarded merge"
    )
    args = parser.parse_args(argv)
    receipt: dict[str, Any] = {
        "repo": REPOSITORY,
        "pr": args.pr,
        "decision": "blocked",
        "head_sha": None,
        "base_sha": None,
        "checks": {},
    }
    try:
        _require(args.pr > 0, "PR number must be positive")
        receipt.update(_snapshot(args.pr, receipt))
        if args.merge:
            fresh = _snapshot(args.pr)
            _require(
                all(receipt[key] == value for key, value in fresh.items()),
                "admission snapshot changed before merge",
            )
            # Server-side strict protection closes the remaining base-race window.
            receipt["decision"] = "merge_outcome_unknown"
            result = _api(
                f"pulls/{args.pr}/merge",
                fields=(
                    "-f",
                    f"merge_method={receipt['method']}",
                    "-f",
                    f"sha={receipt['head_sha']}",
                ),
            )
            _require(result.get("merged") is True, "GitHub did not confirm a merge")
            merged_sha = _sha(result["sha"])
            after = _api(f"pulls/{args.pr}")
            _require(
                after["merged"] is True
                and after["state"] == "closed"
                and after["head"]["sha"] == receipt["head_sha"]
                and after["base"]["ref"] == receipt["base_ref"]
                and after["merge_commit_sha"] == merged_sha,
                "merge readback is unverified",
            )
            receipt.update(decision="merged", merge_sha=merged_sha)
    except (MergeGuardError, KeyError, TypeError, AttributeError) as exc:
        if receipt["decision"] != "merge_outcome_unknown":
            receipt["decision"] = "blocked"
        receipt["reason"] = (
            str(exc) if isinstance(exc, MergeGuardError) else "invalid evidence shape"
        )
        print(json.dumps(receipt, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
