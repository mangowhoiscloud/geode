"""Evaluation catalog, preregistration, lineage, and analysis contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from scripts.eval import contract


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _workload_hash(workload_ids: list[str]) -> str:
    canonical = json.dumps(workload_ids, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _run_spec() -> dict[str, object]:
    workload_ids = ["task-1"]
    return {
        "schema_id": "geode.eval-run-spec@1",
        "schema_version": 1,
        "run_id": "tau2-smoke-test",
        "created_at": "2026-08-09T00:00:00Z",
        "preregistration": {
            "mode": "prospective",
            "status": "frozen",
            "frozen_at": "2026-08-09T00:00:00Z",
            "live_test_approved": False,
            "operator": "test",
        },
        "study": {
            "research_question": "Does the frozen smoke profile produce valid evidence?",
            "research_gap": "The smoke profile has not yet produced contract-valid evidence.",
            "hypothesis": "One valid task will preserve one selected attempt and score.",
            "primary_metric": {
                "name": "accuracy",
                "unit": "ratio",
                "direction": "maximize",
                "aggregation": "passed tasks divided by attempted valid tasks",
                "denominator": 1,
            },
            "decision_rule": "Record a diagnostic pass only when the native verifier passes.",
            "invalidation_rule": "Authentication or reset failure makes the attempt invalid.",
            "analysis_plan": "Report numerator and denominator for all selected valid attempts.",
        },
        "reproduction": {
            "geode": {"revision": "a" * 40, "branch": "test", "dirty": False},
            "harness": {"name": "fixture", "source": "local", "revision": "1"},
            "model": {
                "provider": "none",
                "label": "fixture",
                "route": "none",
                "reasoning": "none",
            },
            "environment": {
                "platform": "test",
                "architecture": "arm64",
                "reset_strategy": "fresh fixture per test",
                "initial_state_ref": "sha256:fixture",
            },
            "execution": {
                "command_redacted": "fixture --task task-1",
                "ordered_workload_ids": workload_ids,
                "workload_ids_sha256": _workload_hash(workload_ids),
                "repetitions": 1,
                "seed_schedule": [7],
                "max_concurrency": 1,
                "timeout_seconds": 30,
                "budget": {"kind": "wall-time", "limit": 30, "unit": "seconds"},
            },
            "comparison": {
                "claim_class": "smoke",
                "comparator": None,
                "comparability": "not-comparable",
                "promotion_authority": "none",
            },
        },
        "artifacts": {
            "native_results": "native.json",
            "trajectory": "trajectory.json",
            "verifier_receipts": "receipt.json",
            "attempts": "attempts.jsonl",
            "analysis": "analysis.json",
            "publication_manifest": None,
        },
        "privacy": {
            "classification": "internal",
            "redaction_boundary": "Fixture contains no identity, prompt, or credential payload.",
        },
    }


def _evidence(path: Path, *, kind: str, content: str) -> dict[str, str]:
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    return {
        "kind": kind,
        "path": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _attempt(run_dir: Path) -> dict[str, object]:
    return {
        "schema_id": "geode.eval-attempt@1",
        "schema_version": 1,
        "run_id": "tau2-smoke-test",
        "attempt_id": "attempt-0",
        "parent_attempt_id": None,
        "sequence": 0,
        "timing": {
            "status": "exact",
            "started_at": "2026-08-09T00:01:00Z",
            "finished_at": "2026-08-09T00:02:00Z",
            "source_ref": None,
        },
        "validity": "valid",
        "outcome": "passed",
        "change": {"surface": "baseline", "description": "frozen baseline"},
        "expected_effect": "The native verifier should pass the fixture.",
        "observed_result": "The native verifier passed the fixture.",
        "failure_class": None,
        "error_ref": None,
        "evidence_refs": [
            _evidence(
                run_dir / "native.json",
                kind="native-result",
                content=json.dumps({"score": {"value": 1.0, "numerator": 1, "denominator": 1}}),
            ),
            _evidence(
                run_dir / "receipt.json",
                kind="verifier-receipt",
                content="receipt\n",
            ),
        ],
        "selected_for_analysis": True,
    }


def _analysis(
    run_spec_path: Path,
    attempts_path: Path,
    attempt: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_id": "geode.eval-analysis@1",
        "schema_version": 1,
        "run_id": "tau2-smoke-test",
        "analyzed_at": "2026-08-09T00:03:00Z",
        "run_spec_sha256": contract._sha256(run_spec_path),
        "attempts_sha256": contract._sha256(attempts_path),
        "selected_attempt_ids": ["attempt-0"],
        "answer": "The fixture produced one valid, verifier-backed selected attempt.",
        "metrics": [
            {
                "name": "accuracy",
                "value": 1.0,
                "numerator": 1,
                "denominator": 1,
                "unit": "ratio",
                "source_ref": "native.json",
                "source_locator": {
                    "value": "/score/value",
                    "numerator": "/score/numerator",
                    "denominator": "/score/denominator",
                },
            }
        ],
        "decision": {
            "outcome": "diagnostic-only",
            "hypothesis_status": "supported",
            "rationale": "The native verifier passed the only preregistered workload.",
        },
        "limitations": ["One fixture is not a suite headline."],
        "evidence_refs": attempt["evidence_refs"],
    }


def test_eval_schemas_are_valid_draft_2020_12() -> None:
    for filename in (
        contract.CATALOG_SCHEMA,
        contract.RUN_SPEC_SCHEMA,
        contract.ATTEMPT_SCHEMA,
        contract.ANALYSIS_SCHEMA,
    ):
        Draft202012Validator.check_schema(contract._load_schema(filename))


def test_committed_eval_catalog_is_current_and_routes_every_document() -> None:
    expected = json.dumps(contract.build_catalog(), indent=2, ensure_ascii=False) + "\n"

    assert contract.INDEX_PATH.read_text(encoding="utf-8") == expected
    assert contract.build_catalog()["document_count"] == len(list(contract.EVAL_DIR.glob("*.md")))


def test_cross_host_skill_alias_has_one_physical_source() -> None:
    canonical = contract.REPO_ROOT / ".agents" / "skills" / "geode-eval"
    claude_alias = contract.REPO_ROOT / ".claude" / "skills" / "geode-eval"

    assert claude_alias.is_symlink()
    assert claude_alias.resolve() == canonical.resolve()
    assert (claude_alias / "SKILL.md").samefile(canonical / "SKILL.md")


def test_run_spec_validates_reproduction_hash_and_seed_cardinality(tmp_path: Path) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    _write_json(path, payload)

    assert contract.validate_run_spec(path)["run_id"] == "tau2-smoke-test"

    reproduction = payload["reproduction"]
    assert isinstance(reproduction, dict)
    execution = reproduction["execution"]
    assert isinstance(execution, dict)
    execution["seed_schedule"] = [7, 8]
    _write_json(path, payload)
    with pytest.raises(ValueError, match="seed_schedule length"):
        contract.validate_run_spec(path)


@pytest.mark.parametrize(
    "raw, message",
    [
        ('{"schema_id":"x","schema_id":"y"}', "duplicate JSON key"),
        ('{"value":NaN}', "non-finite JSON number"),
    ],
)
def test_contract_json_rejects_ambiguous_or_non_standard_values(
    tmp_path: Path,
    raw: str,
    message: str,
) -> None:
    path = tmp_path / "ambiguous.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        contract.validate_run_spec(path)


def test_retrospective_run_spec_cannot_claim_promotion_authority(tmp_path: Path) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    preregistration = payload["preregistration"]
    reproduction = payload["reproduction"]
    assert isinstance(preregistration, dict)
    assert isinstance(reproduction, dict)
    comparison = reproduction["comparison"]
    assert isinstance(comparison, dict)
    preregistration["mode"] = "retrospective"
    comparison["promotion_authority"] = "suite-native"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="retrospective run specs cannot carry"):
        contract.validate_run_spec(path)


def test_promotion_authority_requires_matching_claim_and_direct_comparator(
    tmp_path: Path,
) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    reproduction = payload["reproduction"]
    assert isinstance(reproduction, dict)
    comparison = reproduction["comparison"]
    assert isinstance(comparison, dict)
    comparison["promotion_authority"] = "release-gate"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="requires claim_class=regression"):
        contract.validate_run_spec(path)

    comparison["claim_class"] = "regression"
    _write_json(path, payload)
    with pytest.raises(ValueError, match="direct, named comparator"):
        contract.validate_run_spec(path)

    comparison["comparator"] = "   "
    comparison["comparability"] = "direct"
    _write_json(path, payload)
    with pytest.raises(ValueError, match="direct, named comparator"):
        contract.validate_run_spec(path)


def test_authority_bearing_claim_requires_its_matching_authority(tmp_path: Path) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    reproduction = payload["reproduction"]
    assert isinstance(reproduction, dict)
    comparison = reproduction["comparison"]
    assert isinstance(comparison, dict)
    comparison.update(
        {
            "claim_class": "paired-runtime",
            "comparator": "matched native runtime",
            "comparability": "direct",
        }
    )
    _write_json(path, payload)

    with pytest.raises(ValueError, match="requires promotion_authority=paired-runtime"):
        contract.validate_run_spec(path)


def test_public_run_spec_rejects_machine_local_paths(tmp_path: Path) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    privacy = payload["privacy"]
    reproduction = payload["reproduction"]
    assert isinstance(privacy, dict)
    assert isinstance(reproduction, dict)
    execution = reproduction["execution"]
    assert isinstance(execution, dict)
    privacy["classification"] = "public"
    execution["command_redacted"] = "runner --output /Users/alice/private/run.json"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="machine-local path"):
        contract.validate_run_spec(path)


@pytest.mark.parametrize(
    "machine_path",
    [
        "/root/private/run.json",
        "/private/var/run.json",
        "/mnt/customer/run.json",
        "~/private/run.json",
        "~alice/private/run.json",
        "C:/Users/alice/private/run.json",
        r"C:\Users\alice\private\run.json",
        r"D:\builds\private\run.json",
    ],
)
def test_public_run_spec_rejects_cross_platform_home_paths(
    tmp_path: Path,
    machine_path: str,
) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    privacy = payload["privacy"]
    reproduction = payload["reproduction"]
    assert isinstance(privacy, dict)
    assert isinstance(reproduction, dict)
    execution = reproduction["execution"]
    assert isinstance(execution, dict)
    privacy["classification"] = "public"
    execution["command_redacted"] = f"runner --output={machine_path}"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="machine-local path"):
        contract.validate_run_spec(path)


def test_public_run_spec_allows_https_urls_and_public_site_routes(tmp_path: Path) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    privacy = payload["privacy"]
    assert isinstance(privacy, dict)
    privacy["classification"] = "public"
    privacy["redaction_boundary"] = (
        "Publish https://example.com/result at /docs/benchmarks/tau2, /geode, and /portfolio"
    )
    _write_json(path, payload)

    contract.validate_run_spec(path)


def test_public_run_spec_rejects_route_shaped_machine_path_in_command(tmp_path: Path) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    privacy = payload["privacy"]
    reproduction = payload["reproduction"]
    assert isinstance(privacy, dict)
    assert isinstance(reproduction, dict)
    execution = reproduction["execution"]
    assert isinstance(execution, dict)
    privacy["classification"] = "public"
    execution["command_redacted"] = "runner --output=/docs/private/result.json"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="machine-local path"):
        contract.validate_run_spec(path)


def test_run_spec_artifact_destinations_are_relative(tmp_path: Path) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, dict)
    artifacts["native_results"] = str((tmp_path / "native.json").resolve())
    _write_json(path, payload)

    with pytest.raises(ValueError, match="portable POSIX relative path"):
        contract.validate_run_spec(path)


@pytest.mark.parametrize(
    "reference",
    [
        "file:/etc/passwd",
        "s3:bucket/key",
        r"\\server\share\result.json",
        r"\rooted\result.json",
        r"nested\result.json",
    ],
)
def test_run_spec_artifacts_reject_uri_and_windows_root_forms(
    tmp_path: Path,
    reference: str,
) -> None:
    path = tmp_path / "run-spec.json"
    payload = _run_spec()
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, dict)
    artifacts["native_results"] = reference
    _write_json(path, payload)

    with pytest.raises(ValueError, match="portable POSIX relative path"):
        contract.validate_run_spec(path)


def test_exact_timing_rejects_unknown_rfc3339_offset(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    attempt = _attempt(tmp_path)
    timing = attempt["timing"]
    assert isinstance(timing, dict)
    timing["started_at"] = "2026-08-09T00:01:00-00:00"
    timing["finished_at"] = "2026-08-09T00:02:00-00:00"
    path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not exact timing"):
        contract.validate_attempts(path)


def test_attempts_require_append_order_and_existing_parent(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    child = _attempt(tmp_path)
    child.update(
        {
            "attempt_id": "attempt-1",
            "parent_attempt_id": "attempt-0",
            "sequence": 0,
        }
    )
    path.write_text(json.dumps(child) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="parent attempt must appear before child"):
        contract.validate_attempts(path)


def test_attempts_preserve_source_naive_timing_without_inventing_timezone(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    attempt = _attempt(tmp_path)
    attempt["timing"] = {
        "status": "source-naive",
        "started_at": "2026-07-03T12:00:00",
        "finished_at": "2026-07-03T12:05:00",
        "source_ref": "native.json#/simulations",
    }
    attempt["outcome"] = "mixed"
    path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")

    assert contract.validate_attempts(path)[0]["timing"]["status"] == "source-naive"


@pytest.mark.parametrize("field", ["source_ref", "error_ref"])
def test_attempt_provenance_references_must_be_digest_bound(
    tmp_path: Path,
    field: str,
) -> None:
    path = tmp_path / "attempts.jsonl"
    attempt = _attempt(tmp_path)
    if field == "source_ref":
        attempt["timing"] = {
            "status": "source-naive",
            "started_at": "2026-07-03T12:00:00",
            "finished_at": "2026-07-03T12:05:00",
            "source_ref": "unbound.json#/time",
        }
    else:
        attempt.update(
            {
                "outcome": "failed",
                "failure_class": "semantic-verifier-failure",
                "error_ref": "unbound.json#/error",
            }
        )
    path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="provenance reference is not digest-bound"):
        contract.validate_attempts(path)


def test_attempts_can_state_that_timing_and_its_source_are_unknown(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    attempt = _attempt(tmp_path)
    attempt["timing"] = {
        "status": "unknown",
        "started_at": None,
        "finished_at": None,
        "source_ref": None,
    }
    path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")

    assert contract.validate_attempts(path)[0]["timing"]["status"] == "unknown"


@pytest.mark.parametrize(
    "timing",
    [
        {
            "status": "source-naive",
            "started_at": "2026-07-03T12:00:00Z",
            "finished_at": "2026-07-03T12:05:00Z",
            "source_ref": "native.json",
        },
        {
            "status": "unknown",
            "started_at": "2026-07-03T12:00:00Z",
            "finished_at": "2026-07-03T12:05:00Z",
            "source_ref": "native.json",
        },
    ],
)
def test_attempt_timing_status_rejects_incompatible_timestamp_shapes(
    tmp_path: Path,
    timing: dict[str, object],
) -> None:
    path = tmp_path / "attempts.jsonl"
    attempt = _attempt(tmp_path)
    attempt["timing"] = timing
    path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="validation failed"):
        contract.validate_attempts(path)


def test_valid_semantic_failure_preserves_failure_provenance(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    attempt = _attempt(tmp_path)
    attempt.update(
        {
            "outcome": "failed",
            "failure_class": "semantic-verifier-failure",
            "error_ref": "receipt.json#/failure",
        }
    )
    path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")

    assert contract.validate_attempts(path)[0]["failure_class"] == "semantic-verifier-failure"


def test_invalid_attempts_cannot_claim_semantic_failure(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    attempt = _attempt(tmp_path)
    attempt.update(
        {
            "validity": "invalid",
            "outcome": "failed",
            "failure_class": "environment-reset",
            "error_ref": "error.log",
        }
    )
    path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="'unknown' was expected"):
        contract.validate_attempts(path)


def test_analysis_is_bound_to_spec_attempts_selection_and_primary_metric(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    _write_json(analysis_path, analysis)

    contract.validate_analysis(
        analysis_path,
        run_spec_path=run_spec_path,
        attempts_path=attempts_path,
    )

    decision = analysis["decision"]
    assert isinstance(decision, dict)
    decision["outcome"] = "promote"
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="requires explicit promotion authority"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )

    decision["outcome"] = "reject"
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="requires explicit promotion authority"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )

    decision["outcome"] = "diagnostic-only"
    metrics = analysis["metrics"]
    assert isinstance(metrics, list)
    primary = metrics[0]
    assert isinstance(primary, dict)
    primary["unit"] = "dollars"
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="unit does not match"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )

    primary["unit"] = "ratio"
    primary["value"] = 0.5
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="metric value does not match metric source"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )

    primary["value"] = 1.0
    primary["numerator"] = 100
    primary["denominator"] = 100
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="metric numerator does not match metric source"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )

    primary["numerator"] = 1
    primary["denominator"] = 1
    primary["source_ref"] = "unbound.json"
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="provenance reference is not digest-bound"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )

    primary["source_ref"] = "native.json"
    analysis["attempts_sha256"] = "0" * 64
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="attempts_sha256 does not match"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_primary_metric_denominator_matches_frozen_spec(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    run_spec = _run_spec()
    study = run_spec["study"]
    assert isinstance(study, dict)
    primary_spec = study["primary_metric"]
    assert isinstance(primary_spec, dict)
    primary_spec["unit"] = "score-per-task"
    primary_spec["denominator"] = 2
    _write_json(run_spec_path, run_spec)
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    metrics = analysis["metrics"]
    assert isinstance(metrics, list)
    primary = metrics[0]
    assert isinstance(primary, dict)
    primary["unit"] = "score-per-task"
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="denominator does not match frozen spec"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_target_metric_allows_signed_delta_but_maximize_does_not(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    native_path = tmp_path / "native.json"
    run_spec = _run_spec()
    primary_spec = run_spec["study"]["primary_metric"]
    assert isinstance(primary_spec, dict)
    primary_spec["direction"] = "target"
    _write_json(run_spec_path, run_spec)
    attempt = _attempt(tmp_path)
    native = {"score": {"value": -1.0, "numerator": -1, "denominator": 1}}
    _write_json(native_path, native)
    attempt["evidence_refs"][0]["sha256"] = contract._sha256(native_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    primary = analysis["metrics"][0]
    primary.update(native["score"])
    _write_json(analysis_path, analysis)

    contract.validate_analysis(
        analysis_path,
        run_spec_path=run_spec_path,
        attempts_path=attempts_path,
    )

    primary_spec["direction"] = "maximize"
    _write_json(run_spec_path, run_spec)
    analysis["run_spec_sha256"] = contract._sha256(run_spec_path)
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="numerator is outside its denominator"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


@pytest.mark.parametrize("field", ["value", "numerator", "denominator"])
def test_primary_metric_rejects_boolean_native_values(tmp_path: Path, field: str) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    native_path = tmp_path / "native.json"
    native = {"score": {"value": 1.0, "numerator": 1, "denominator": 1}}
    native["score"][field] = True
    _write_json(native_path, native)
    evidence_refs = attempt["evidence_refs"]
    assert isinstance(evidence_refs, list)
    native_ref = evidence_refs[0]
    assert isinstance(native_ref, dict)
    native_ref["sha256"] = contract._sha256(native_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    _write_json(analysis_path, _analysis(run_spec_path, attempts_path, attempt))

    with pytest.raises(ValueError, match=f"metric {field} does not match metric source"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_secondary_metric_can_use_digest_bound_non_json_evidence(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    metrics = analysis["metrics"]
    assert isinstance(metrics, list)
    metrics.append(
        {
            "name": "verifier-note",
            "value": "pass",
            "numerator": None,
            "denominator": None,
            "unit": "categorical",
            "source_ref": "receipt.json",
            "source_locator": None,
        }
    )
    _write_json(analysis_path, analysis)

    contract.validate_analysis(
        analysis_path,
        run_spec_path=run_spec_path,
        attempts_path=attempts_path,
    )


def test_primary_metric_json_pointer_must_resolve(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    metrics = analysis["metrics"]
    assert isinstance(metrics, list)
    primary = metrics[0]
    assert isinstance(primary, dict)
    locator = primary["source_locator"]
    assert isinstance(locator, dict)
    locator["numerator"] = "/score/missing"
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="metric source locator does not resolve"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_primary_metric_requires_native_result_source(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    evidence_refs = attempt["evidence_refs"]
    assert isinstance(evidence_refs, list)
    native = evidence_refs[0]
    assert isinstance(native, dict)
    native["kind"] = "other"
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    _write_json(analysis_path, _analysis(run_spec_path, attempts_path, attempt))

    with pytest.raises(ValueError, match="primary metric source must be native-result"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_primary_metric_source_must_belong_to_selected_attempt(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    alternate = _evidence(
        tmp_path / "alternate.json",
        kind="native-result",
        content=json.dumps({"score": {"value": 1.0, "numerator": 1, "denominator": 1}}),
    )
    evidence_refs = analysis["evidence_refs"]
    assert isinstance(evidence_refs, list)
    evidence_refs.append(alternate)
    metrics = analysis["metrics"]
    assert isinstance(metrics, list)
    primary = metrics[0]
    assert isinstance(primary, dict)
    primary["source_ref"] = "alternate.json"
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="provenance reference is not digest-bound"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_analysis_rejects_changed_evidence_bytes(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    _write_json(analysis_path, _analysis(run_spec_path, attempts_path, attempt))
    (tmp_path / "native.json").write_text("replaced\n", encoding="utf-8")

    with pytest.raises(ValueError, match="evidence SHA-256 does not match"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_analysis_must_retain_all_selected_attempt_evidence(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    evidence_refs = analysis["evidence_refs"]
    assert isinstance(evidence_refs, list)
    analysis["evidence_refs"] = evidence_refs[:1]
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="retain every selected attempt evidence digest"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_prospective_analysis_rejects_attempt_started_before_freeze(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    run_spec = _run_spec()
    preregistration = run_spec["preregistration"]
    assert isinstance(preregistration, dict)
    preregistration["frozen_at"] = "2026-08-09T00:01:30Z"
    _write_json(run_spec_path, run_spec)
    attempt = _attempt(tmp_path)
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    _write_json(analysis_path, _analysis(run_spec_path, attempts_path, attempt))

    with pytest.raises(ValueError, match="started before the spec was frozen"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_invalid_selected_attempt_cannot_drive_rejection(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    _write_json(run_spec_path, _run_spec())
    attempt = _attempt(tmp_path)
    attempt.update(
        {
            "validity": "invalid",
            "outcome": "unknown",
            "failure_class": "environment-reset",
            "error_ref": "receipt.json#/error",
        }
    )
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    decision = analysis["decision"]
    assert isinstance(decision, dict)
    decision.update({"outcome": "reject", "hypothesis_status": "not-supported"})
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="cannot drive promotion or rejection"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )


def test_invalid_selected_attempt_cannot_publish_primary_score(tmp_path: Path) -> None:
    run_spec_path = tmp_path / "run-spec.json"
    attempts_path = tmp_path / "attempts.jsonl"
    analysis_path = tmp_path / "analysis.json"
    run_spec = _run_spec()
    preregistration = run_spec["preregistration"]
    assert isinstance(preregistration, dict)
    preregistration["mode"] = "retrospective"
    _write_json(run_spec_path, run_spec)
    attempt = _attempt(tmp_path)
    attempt.update(
        {
            "validity": "invalid",
            "outcome": "unknown",
            "failure_class": "environment-reset",
            "error_ref": "receipt.json#/error",
        }
    )
    attempts_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    analysis = _analysis(run_spec_path, attempts_path, attempt)
    decision = analysis["decision"]
    assert isinstance(decision, dict)
    decision.update({"outcome": "inconclusive", "hypothesis_status": "invalidated"})
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="cannot publish a primary score"):
        contract.validate_analysis(
            analysis_path,
            run_spec_path=run_spec_path,
            attempts_path=attempts_path,
        )

    metrics = analysis["metrics"]
    assert isinstance(metrics, list)
    primary = metrics[0]
    assert isinstance(primary, dict)
    primary.update(
        {
            "value": "not-measurable",
            "numerator": None,
            "denominator": None,
            "source_locator": None,
        }
    )
    _write_json(analysis_path, analysis)
    contract.validate_analysis(
        analysis_path,
        run_spec_path=run_spec_path,
        attempts_path=attempts_path,
    )


def test_templates_are_valid_json_but_rejected_until_filled() -> None:
    template = contract.EVAL_DIR / "eval-run-spec.template.json"

    assert isinstance(json.loads(template.read_text(encoding="utf-8")), dict)
    with pytest.raises(ValueError, match="unresolved template placeholders"):
        contract.validate_run_spec(template)
