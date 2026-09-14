#!/usr/bin/env python3
"""Inspect GEODE merge admission; only an explicit --merge may mutate GitHub."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from typing import Any

REPOSITORY = "mangowhoiscloud/geode"
CHECK_APP_ID = 15368
REQUIRED_CHECKS = (
    "Detect changes",
    "Lint & Format",
    "Type Check",
    "Test",
    "Security Scan",
    "Gate",
    "ubuntu-latest — install / update / uninstall",
    "macos-latest — install / update / uninstall",
    "Render lint (markdown + YAML + JSON)",
    "Build (Next.js static export)",
)


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
    if flow in {("main", "develop"), ("develop", "main")}:
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


def validate_snapshot(
    pr: dict[str, Any],
    base: dict[str, Any],
    protection: dict[str, Any],
    checks: dict[str, Any],
    view: dict[str, Any],
    native_checks: dict[str, Any],
) -> dict[str, Any]:
    """Pure admission predicate; job success never overrides missing server policy."""
    identity = _identity(pr)
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
    selected = native_checks["checks"]
    _require(
        len(selected) == len(REQUIRED_CHECKS)
        and {row["name"] for row in selected} == set(REQUIRED_CHECKS),
        "current required checks are missing or ambiguous",
    )
    admitted = {}
    for name in REQUIRED_CHECKS:
        chosen = next(row for row in selected if row["name"] == name)
        _require(chosen["state"] == "SUCCESS", "current required check is not successful")
        matching = [
            row for row in runs if row.get("name") == name and row["details_url"] == chosen["link"]
        ]
        rolled = [
            row
            for row in view["statusCheckRollup"]
            if row.get("name") == name and row["detailsUrl"] == chosen["link"]
        ]
        _require(len(matching) == len(rolled) == 1, "required check missing or ambiguous")
        run, current = matching[0], rolled[0]
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
            and run["details_url"].startswith(f"https://github.com/{REPOSITORY}/actions/runs/"),
            "current PR check-run association is unverified",
        )
        admitted[name] = run["id"]
    return identity | {"checks": admitted, "decision": "ready"}


def _snapshot(number: int, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    pr = _api(f"pulls/{number}")
    identity = _identity(pr)
    if receipt is not None:
        receipt.update(identity)  # Identity remains inspectable even when later admission fails.
    base = _api(f"branches/{identity['base_ref']}")
    protection = _api(f"branches/{identity['base_ref']}/protection")
    checks = _api(f"commits/{identity['head_sha']}/check-runs?filter=latest&per_page=100")
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
    # Native gh resolves superseded workflow runs. Bind its selection back to
    # exact REST/rollup records; never choose whichever duplicate passed.
    required = _gh(
        [
            "pr",
            "checks",
            str(number),
            "--repo",
            REPOSITORY,
            "--required",
            "--json",
            "name,state,link",
            "--jq",
            "{checks: .}",
        ]
    )
    return validate_snapshot(pr, base, protection, checks, view, required)


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
