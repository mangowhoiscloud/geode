#!/usr/bin/env python3
"""Generate GEODE's evaluation catalog and validate evaluation sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "docs" / "eval"
SCHEMA_DIR = EVAL_DIR / "schemas"
INDEX_PATH = EVAL_DIR / "index.json"

CATALOG_SCHEMA = "catalog.schema.json"
RUN_SPEC_SCHEMA = "run-spec.schema.json"
ATTEMPT_SCHEMA = "attempt.schema.json"
ANALYSIS_SCHEMA = "analysis.schema.json"
PUBLICATION_SCHEMA = "publication.schema.json"
MEASUREMENT_SCHEMAS = {"geode.geo-vector@1": "geo-vector.schema.json"}

PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
WINDOWS_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")
PARENT_SEGMENT_RE = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")
POSIX_ABSOLUTE_TOKEN_RE = re.compile(r"(?:^|[\s='\"(=])(?P<path>/(?!/)[^\s'\"),;]+)")
WINDOWS_ABSOLUTE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]")
UNC_TOKEN_RE = re.compile(r"(?:^|[\s='\"(=])(?:\\\\|//)[^\s'\"),;]+")
HOME_TOKEN_RE = re.compile(r"(?:^|[\s='\"(=])~(?:[A-Za-z0-9._-]+)?[\\/]")
PUBLIC_ROUTE_PREFIXES = ("/docs/", "/geode/", "/portfolio/")
PUBLIC_ROUTES = frozenset({"/about", "/docs", "/geode", "/portfolio"})
PUBLIC_ROUTE_TEXT_KEYS = frozenset({"redaction_boundary"})
FRONTMATTER_KEYS = {
    "eval_id",
    "eval_family",
    "eval_kind",
    "eval_status",
    "eval_authority",
    "eval_summary",
    "eval_triggers",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json_loads(raw: str, *, label: str) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(f"{label}: non-finite JSON number is not allowed: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label}: duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)


def _load_json_object(path: Path) -> dict[str, Any]:
    loaded = _strict_json_loads(path.read_text(encoding="utf-8"), label=str(path))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return loaded


def _load_schema(filename: str) -> dict[str, Any]:
    return _load_json_object(SCHEMA_DIR / filename)


def _validate_schema(payload: dict[str, Any], filename: str, *, label: str) -> None:
    validator = Draft202012Validator(
        _load_schema(filename),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    details = "; ".join(
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors[:8]
    )
    raise ValueError(f"{label} validation failed: {details}")


def _reject_placeholders(path: Path) -> None:
    matches = sorted(set(PLACEHOLDER_RE.findall(path.read_text(encoding="utf-8"))))
    if matches:
        preview = ", ".join(matches[:4])
        raise ValueError(f"{path}: unresolved template placeholders: {preview}")


def _parse_datetime(value: object) -> datetime:
    rendered = str(value)
    if rendered.endswith("-00:00"):
        raise ValueError("unknown RFC 3339 offset -00:00 is not exact timing")
    return datetime.fromisoformat(rendered.replace("Z", "+00:00"))


def _contains_machine_local_path(value: object, *, parent_key: str | None = None) -> bool:
    if parent_key == "source_locator":
        return False
    if isinstance(value, str):
        posix_paths = [match.group("path") for match in POSIX_ABSOLUTE_TOKEN_RE.finditer(value)]
        allow_public_route = parent_key in PUBLIC_ROUTE_TEXT_KEYS
        unsafe_posix = any(
            not (
                allow_public_route
                and (path in PUBLIC_ROUTES or path.startswith(PUBLIC_ROUTE_PREFIXES))
            )
            for path in posix_paths
        )
        return unsafe_posix or any(
            pattern.search(value) is not None
            for pattern in (WINDOWS_ABSOLUTE_TOKEN_RE, UNC_TOKEN_RE, HOME_TOKEN_RE)
        )
    if isinstance(value, dict):
        return any(
            _contains_machine_local_path(item, parent_key=str(key)) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_machine_local_path(item, parent_key=parent_key) for item in value)
    return False


def _validate_relative_reference(value: str, *, label: str) -> None:
    candidate = Path(value)
    if (
        URI_RE.match(value)
        or WINDOWS_ABSOLUTE_RE.match(value)
        or candidate.is_absolute()
        or PARENT_SEGMENT_RE.search(value)
        or "\\" in value
    ):
        raise ValueError(f"{label}: reference must be a portable POSIX relative path: {value}")


def _validate_bound_reference(
    value: str,
    *,
    evidence: set[tuple[str, str, str]],
    label: str,
) -> tuple[str, str, str]:
    evidence_path, _, _fragment = value.partition("#")
    if not evidence_path:
        raise ValueError(f"{label}: provenance reference is missing its evidence path")
    _validate_relative_reference(evidence_path, label=label)
    matches = [identity for identity in evidence if identity[1] == evidence_path]
    if not matches:
        raise ValueError(f"{label}: provenance reference is not digest-bound: {value}")
    return matches[0]


def _resolve_json_pointer(payload: object, pointer: str, *, label: str) -> object:
    if not pointer.startswith("/"):
        raise ValueError(f"{label}: metric source locator must be an RFC 6901 JSON Pointer")
    current = payload
    for raw_token in pointer.removeprefix("/").split("/"):
        if re.search(r"~(?:[^01]|$)", raw_token):
            raise ValueError(f"{label}: invalid JSON Pointer escape in {pointer!r}")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"{label}: metric source locator does not resolve: {pointer}")
    return current


def _metric_values_match(expected: object, observed: object) -> bool:
    if isinstance(expected, bool) or isinstance(observed, bool):
        return False
    numeric = (int, float)
    if (
        isinstance(expected, numeric)
        and not isinstance(expected, bool)
        and isinstance(observed, numeric)
        and not isinstance(observed, bool)
    ):
        return math.isclose(float(expected), float(observed), rel_tol=1e-9, abs_tol=1e-12)
    return expected == observed


def _validate_metric_source(
    sidecar_path: Path,
    metric: dict[str, Any],
    *,
    evidence: set[tuple[str, str, str]],
    require_authoritative: bool,
) -> tuple[str, object | None]:
    source_ref = str(metric["source_ref"])
    if "#" in source_ref:
        raise ValueError(f"{sidecar_path}: metric source_ref cannot contain a locator fragment")
    kind, evidence_path, _digest = _validate_bound_reference(
        source_ref, evidence=evidence, label=str(sidecar_path)
    )
    locator = metric["source_locator"]
    if locator is None:
        unavailable = (
            metric["value"] == "not-measurable"
            and metric["numerator"] is None
            and metric["denominator"] is None
        )
        if require_authoritative and not unavailable:
            raise ValueError(f"{sidecar_path}: measured metric requires source locators")
        return kind, None
    if require_authoritative and kind not in {"native-result", "measurement"}:
        raise ValueError(
            f"{sidecar_path}: primary metric source must be native-result or measurement evidence"
        )
    source_path = sidecar_path.parent / evidence_path
    source_payload = _strict_json_loads(
        source_path.read_text(encoding="utf-8"), label=str(source_path)
    )
    for field in ("value", "numerator", "denominator"):
        if locator[field] is None:
            if field != "value":
                raise ValueError(f"{sidecar_path}: metric {field} locator cannot be null")
            continue
        observed = _resolve_json_pointer(
            source_payload, str(locator[field]), label=str(sidecar_path)
        )
        if not _metric_values_match(metric[field], observed):
            raise ValueError(f"{sidecar_path}: metric {field} does not match metric source")
    return kind, source_payload


def _validate_measurement_binding(
    sidecar_path: Path,
    measurement: object,
    *,
    run_id: str,
    run_spec_sha256: str,
    evidence: set[tuple[str, str, str]],
) -> None:
    if not isinstance(measurement, dict):
        raise ValueError(f"{sidecar_path}: measurement evidence must be a JSON object")
    schema_id = str(measurement.get("schema_id") or "")
    schema = MEASUREMENT_SCHEMAS.get(schema_id)
    if schema is None:
        raise ValueError(f"{sidecar_path}: unsupported measurement schema: {schema_id!r}")
    _validate_schema(measurement, schema, label=str(sidecar_path))
    if measurement["run_id"] != run_id or measurement["run_spec_sha256"] != run_spec_sha256:
        raise ValueError(f"{sidecar_path}: measurement does not bind this run spec")
    native_digests = {digest for kind, _path, digest in evidence if kind == "native-result"}
    if measurement["native_results_sha256"] not in native_digests:
        raise ValueError(f"{sidecar_path}: measurement does not bind selected native evidence")
    verifier_digest = measurement.get("verifier_results_sha256")
    verifier_digests = {digest for kind, _path, digest in evidence if kind == "verifier-receipt"}
    if verifier_digest is not None and verifier_digest not in verifier_digests:
        raise ValueError(f"{sidecar_path}: measurement verifier is not selected evidence")
    outcome_context = measurement.get("outcome_context")
    if isinstance(outcome_context, dict):
        identity = (
            "outcome-receipt",
            str(outcome_context.get("path") or ""),
            str(outcome_context.get("sha256") or ""),
        )
        if identity not in evidence:
            raise ValueError(f"{sidecar_path}: measurement outcome is not selected evidence")


def _validate_evidence_refs(
    sidecar_path: Path,
    refs: list[dict[str, Any]],
) -> set[tuple[str, str, str]]:
    base = sidecar_path.parent.resolve()
    identities: set[tuple[str, str, str]] = set()
    paths: set[str] = set()
    for ref in refs:
        value = str(ref["path"])
        _validate_relative_reference(value, label=str(sidecar_path))
        if value in paths:
            raise ValueError(f"{sidecar_path}: duplicate evidence path: {value}")
        target = (base / value).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            message = f"{sidecar_path}: evidence path escapes the run directory: {value}"
            raise ValueError(message) from exc
        if not target.is_file():
            raise ValueError(f"{sidecar_path}: evidence file does not exist: {value}")
        digest = str(ref["sha256"])
        if _sha256(target) != digest:
            raise ValueError(f"{sidecar_path}: evidence SHA-256 does not match: {value}")
        paths.add(value)
        identities.add((str(ref["kind"]), value, digest))
    return identities


def _frontmatter(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path}: missing YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"{path}: unterminated YAML frontmatter") from exc
    loaded: object = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")
    missing = sorted(FRONTMATTER_KEYS - loaded.keys())
    if missing:
        raise ValueError(f"{path}: missing eval frontmatter keys: {', '.join(missing)}")
    return {str(key): value for key, value in loaded.items()}


def _title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    raise ValueError(f"{path}: missing H1 title")


def _relative_contracts(path: Path, values: object) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"{path}: eval_contracts must be a list of repo-relative paths")
    contracts = sorted(set(values))
    for contract in contracts:
        contract_path = Path(contract)
        if contract_path.is_absolute() or ".." in contract_path.parts:
            raise ValueError(f"{path}: invalid contract path: {contract}")
        if not (REPO_ROOT / contract_path).is_file():
            raise ValueError(f"{path}: missing contract path: {contract}")
    return contracts


def build_catalog() -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    canonical_families: set[str] = set()
    for path in sorted(EVAL_DIR.glob("*.md")):
        meta = _frontmatter(path)
        document_id = str(meta["eval_id"])
        family = str(meta["eval_family"])
        status = str(meta["eval_status"])
        if document_id in seen_ids:
            raise ValueError(f"{path}: duplicate eval_id: {document_id}")
        seen_ids.add(document_id)
        if status == "canonical":
            if family in canonical_families:
                raise ValueError(f"{path}: multiple canonical documents for family: {family}")
            canonical_families.add(family)

        triggers = meta["eval_triggers"]
        if not isinstance(triggers, list) or not all(isinstance(item, str) for item in triggers):
            raise ValueError(f"{path}: eval_triggers must be a list of strings")

        entry: dict[str, Any] = {
            "id": document_id,
            "family": family,
            "title": _title(path),
            "kind": str(meta["eval_kind"]),
            "status": status,
            "authority": str(meta["eval_authority"]),
            "path": str(path.relative_to(REPO_ROOT)),
            "summary": str(meta["eval_summary"]),
            "sha256": _sha256(path),
            "triggers": sorted(set(triggers)),
            "contracts": _relative_contracts(path, meta.get("eval_contracts")),
        }
        latest_release = meta.get("eval_latest_valid_release")
        if latest_release is not None:
            entry["latest_valid_release"] = str(latest_release)
        documents.append(entry)

    catalog = {
        "schema_id": "geode.eval-catalog@1",
        "schema_version": 1,
        "entrypoint": "docs/eval/README.md",
        "skill": ".agents/skills/geode-eval/SKILL.md",
        "contracts": {
            "run_spec": "docs/eval/schemas/run-spec.schema.json",
            "attempt": "docs/eval/schemas/attempt.schema.json",
            "analysis": "docs/eval/schemas/analysis.schema.json",
            "publication": "docs/eval/schemas/publication.schema.json",
            "trajectory": "core/observability/schemas/trajectory.schema.json",
            "trajectory_release": "core/observability/schemas/trajectory-release.schema.json",
        },
        "document_count": len(documents),
        "documents": sorted(documents, key=lambda item: str(item["id"])),
    }
    _validate_schema(catalog, CATALOG_SCHEMA, label="evaluation catalog")
    if not any(item["path"] == "docs/eval/README.md" for item in documents):
        raise ValueError("evaluation catalog is missing its README entrypoint")
    return catalog


def write_or_check_catalog(*, write: bool) -> None:
    rendered = json.dumps(build_catalog(), indent=2, ensure_ascii=False) + "\n"
    if write:
        INDEX_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {INDEX_PATH.relative_to(REPO_ROOT)}")
        return
    if not INDEX_PATH.is_file():
        raise ValueError(f"missing generated catalog: {INDEX_PATH}")
    if INDEX_PATH.read_text(encoding="utf-8") != rendered:
        raise ValueError(
            "docs/eval/index.json is stale; run "
            "`uv run python scripts/eval/contract.py catalog --write`"
        )
    print(f"catalog OK: {len(build_catalog()['documents'])} documents")


def validate_run_spec(path: Path) -> dict[str, Any]:
    _reject_placeholders(path)
    payload = _load_json_object(path)
    _validate_schema(payload, RUN_SPEC_SCHEMA, label=str(path))
    execution = payload["reproduction"]["execution"]
    repetitions = execution["repetitions"]
    seeds = execution["seed_schedule"]
    if len(seeds) != repetitions:
        raise ValueError(f"{path}: seed_schedule length must equal repetitions")
    workload_ids = execution["ordered_workload_ids"]
    canonical_ids = json.dumps(workload_ids, ensure_ascii=False, separators=(",", ":"))
    expected_hash = hashlib.sha256(canonical_ids.encode("utf-8")).hexdigest()
    if execution["workload_ids_sha256"] != expected_hash:
        raise ValueError(f"{path}: workload_ids_sha256 does not match ordered_workload_ids")
    preregistration = payload["preregistration"]
    if _parse_datetime(payload["created_at"]) > _parse_datetime(preregistration["frozen_at"]):
        raise ValueError(f"{path}: frozen_at cannot precede created_at")

    comparison = payload["reproduction"]["comparison"]
    authority = str(comparison["promotion_authority"])
    if preregistration["mode"] == "retrospective" and authority != "none":
        raise ValueError(f"{path}: retrospective run specs cannot carry promotion authority")
    authority_claims = {
        "suite-native": "suite-headline",
        "paired-runtime": "paired-runtime",
        "release-gate": "regression",
    }
    claim_authorities = {claim: owner for owner, claim in authority_claims.items()}
    claim_class = str(comparison["claim_class"])
    if authority != "none":
        expected_claim = authority_claims[authority]
        if claim_class != expected_claim:
            raise ValueError(f"{path}: {authority} authority requires claim_class={expected_claim}")
        comparator = comparison["comparator"]
        named_comparator = isinstance(comparator, str) and bool(comparator.strip())
        if comparison["comparability"] != "direct" or not named_comparator:
            raise ValueError(f"{path}: promotion authority requires a direct, named comparator")
    elif claim_class in claim_authorities:
        expected_authority = claim_authorities[claim_class]
        raise ValueError(
            f"{path}: claim_class={claim_class} requires promotion_authority={expected_authority}"
        )

    for artifact_name, reference in payload["artifacts"].items():
        if reference is not None:
            _validate_relative_reference(str(reference), label=f"{path}:{artifact_name}")
    if payload["privacy"]["classification"] == "public" and _contains_machine_local_path(payload):
        raise ValueError(f"{path}: public run spec contains a machine-local path")
    return payload


def _load_attempts(path: Path) -> list[dict[str, Any]]:
    _reject_placeholders(path)
    attempts: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        loaded = _strict_json_loads(raw_line, label=f"{path}:{line_number}")
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        attempt = {str(key): value for key, value in loaded.items()}
        _validate_schema(attempt, ATTEMPT_SCHEMA, label=f"{path}:{line_number}")
        attempts.append(attempt)
    if not attempts:
        raise ValueError(f"{path}: attempts JSONL is empty")
    return attempts


def validate_attempts(path: Path) -> list[dict[str, Any]]:
    attempts = _load_attempts(path)
    run_ids = {str(attempt["run_id"]) for attempt in attempts}
    if len(run_ids) != 1:
        raise ValueError(f"{path}: attempts must belong to exactly one run_id")
    seen: set[str] = set()
    for expected_sequence, attempt in enumerate(attempts):
        attempt_id = str(attempt["attempt_id"])
        if attempt_id in seen:
            raise ValueError(f"{path}: duplicate attempt_id: {attempt_id}")
        if attempt["sequence"] != expected_sequence:
            raise ValueError(f"{path}: attempt sequences must be contiguous from zero")
        parent = attempt["parent_attempt_id"]
        if parent is not None and parent not in seen:
            raise ValueError(f"{path}: parent attempt must appear before child: {parent}")
        timing = attempt["timing"]
        if timing["status"] in {"exact", "source-naive"}:
            started = _parse_datetime(timing["started_at"])
            finished = _parse_datetime(timing["finished_at"])
            if finished < started:
                raise ValueError(f"{path}: attempt {attempt_id} finishes before it starts")
        evidence = _validate_evidence_refs(path, attempt["evidence_refs"])
        if timing["source_ref"] is not None:
            _validate_bound_reference(str(timing["source_ref"]), evidence=evidence, label=str(path))
        if attempt["error_ref"] is not None:
            _validate_bound_reference(str(attempt["error_ref"]), evidence=evidence, label=str(path))
        seen.add(attempt_id)
    return attempts


def validate_analysis(path: Path, *, run_spec_path: Path, attempts_path: Path) -> None:
    _reject_placeholders(path)
    analysis = _load_json_object(path)
    _validate_schema(analysis, ANALYSIS_SCHEMA, label=str(path))
    run_spec = validate_run_spec(run_spec_path)
    attempts = validate_attempts(attempts_path)

    run_id = str(run_spec["run_id"])
    if analysis["run_id"] != run_id or any(attempt["run_id"] != run_id for attempt in attempts):
        raise ValueError("run spec, attempts, and analysis must share one run_id")
    if analysis["run_spec_sha256"] != _sha256(run_spec_path):
        raise ValueError(f"{path}: run_spec_sha256 does not match the frozen run spec")
    if analysis["attempts_sha256"] != _sha256(attempts_path):
        raise ValueError(f"{path}: attempts_sha256 does not match attempts JSONL")

    frozen_at = _parse_datetime(run_spec["preregistration"]["frozen_at"])
    analyzed_at = _parse_datetime(analysis["analyzed_at"])
    if analyzed_at < frozen_at:
        raise ValueError(f"{path}: analysis cannot predate the frozen run spec")
    if run_spec["preregistration"]["mode"] == "prospective":
        for attempt in attempts:
            timing = attempt["timing"]
            if timing["status"] != "exact":
                raise ValueError(f"{path}: prospective attempts require exact timing")
            if _parse_datetime(timing["started_at"]) < frozen_at:
                raise ValueError(f"{path}: prospective attempt started before the spec was frozen")
    exact_finished = [
        _parse_datetime(attempt["timing"]["finished_at"])
        for attempt in attempts
        if attempt["timing"]["status"] == "exact"
    ]
    if exact_finished and analyzed_at < max(exact_finished):
        raise ValueError(f"{path}: analysis predates an exact attempt completion")
    if run_spec["privacy"]["classification"] == "public" and _contains_machine_local_path(
        {"attempts": attempts, "analysis": analysis}
    ):
        message = f"{path}: public evaluation sidecars contain a machine-local path"
        raise ValueError(message)

    selected = {
        str(attempt["attempt_id"]) for attempt in attempts if attempt["selected_for_analysis"]
    }
    requested = set(analysis["selected_attempt_ids"])
    if requested != selected:
        raise ValueError(f"{path}: selected_attempt_ids must match selected attempts JSONL rows")
    selected_rows = [attempt for attempt in attempts if str(attempt["attempt_id"]) in requested]
    invalid_selected = any(attempt["validity"] != "valid" for attempt in selected_rows)
    if invalid_selected:
        if analysis["decision"]["outcome"] in {"promote", "reject"}:
            raise ValueError(f"{path}: invalid attempts cannot drive promotion or rejection")
        if analysis["decision"]["hypothesis_status"] not in {"invalidated", "mixed"}:
            raise ValueError(f"{path}: invalid selected attempts must remain invalidated or mixed")
    if analysis["decision"]["outcome"] in {"promote", "reject"}:
        authority = run_spec["reproduction"]["comparison"]["promotion_authority"]
        if authority == "none":
            raise ValueError(
                f"{path}: promotion or rejection requires explicit promotion authority"
            )

    selected_evidence = {
        (str(ref["kind"]), str(ref["path"]), str(ref["sha256"]))
        for attempt in selected_rows
        for ref in attempt["evidence_refs"]
    }
    analysis_evidence = _validate_evidence_refs(path, analysis["evidence_refs"])
    if not selected_evidence.issubset(analysis_evidence):
        raise ValueError(f"{path}: analysis must retain every selected attempt evidence digest")

    primary_spec = run_spec["study"]["primary_metric"]
    primary_metric = str(primary_spec["name"])
    metric_names = [str(metric["name"]) for metric in analysis["metrics"]]
    if len(metric_names) != len(set(metric_names)):
        raise ValueError(f"{path}: analysis metric names must be unique")
    if primary_metric not in metric_names:
        raise ValueError(f"{path}: analysis is missing primary metric {primary_metric!r}")
    primary_source: tuple[str, object | None] | None = None
    for metric in analysis["metrics"]:
        is_primary = str(metric["name"]) == primary_metric
        numerator = metric["numerator"]
        if not is_primary and isinstance(numerator, (int, float)) and numerator < 0:
            raise ValueError(f"{path}: secondary metric numerator cannot be negative")
        source = _validate_metric_source(
            path,
            metric,
            evidence=selected_evidence if is_primary else analysis_evidence,
            require_authoritative=is_primary,
        )
        if is_primary:
            primary_source = source
    primary = next(metric for metric in analysis["metrics"] if metric["name"] == primary_metric)
    if primary_source is not None and primary_source[0] == "measurement":
        _validate_measurement_binding(
            path,
            primary_source[1],
            run_id=run_id,
            run_spec_sha256=_sha256(run_spec_path),
            evidence=selected_evidence,
        )
    if primary["unit"] != primary_spec["unit"]:
        raise ValueError(f"{path}: primary metric unit does not match the frozen run spec")
    if invalid_selected:
        unavailable = (
            primary["value"] == "not-measurable"
            and primary["numerator"] is None
            and primary["denominator"] is None
        )
        if not unavailable:
            raise ValueError(f"{path}: invalid selected attempts cannot publish a primary score")
    else:
        values = (primary["value"], primary["numerator"], primary["denominator"])
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            message = f"{path}: primary metric requires numeric value, numerator, denominator"
            raise ValueError(message)
        expected_value = float(primary["numerator"]) / float(primary["denominator"])
        normalized_unit = primary["unit"].lower()
        expected_denominator = primary_spec["denominator"]
        if float(primary["denominator"]) != float(expected_denominator):
            raise ValueError(f"{path}: primary metric denominator does not match frozen spec")
        numerator = float(primary["numerator"])
        denominator = float(primary["denominator"])
        if primary_spec["direction"] != "target" and numerator < 0:
            raise ValueError(f"{path}: primary metric numerator cannot be negative")
        if normalized_unit in {"ratio", "percent", "percentage", "%"}:
            lower_bound = -denominator if primary_spec["direction"] == "target" else 0
            if not lower_bound <= numerator <= denominator:
                raise ValueError(f"{path}: primary metric numerator is outside its denominator")
        if normalized_unit in {"percent", "percentage", "%"}:
            expected_value *= 100
        if not math.isclose(float(primary["value"]), expected_value, rel_tol=1e-4, abs_tol=5e-7):
            raise ValueError(f"{path}: primary metric value does not match numerator/denominator")


_RUN_ARTIFACT_KINDS = {
    "native_results": "native-result",
    "measurement_results": "measurement",
    "trajectory": "trajectory",
    "verifier_receipts": "verifier-receipt",
    "outcome_receipts": "outcome-receipt",
}


def _resolve_run_artifact(run_spec_path: Path, reference: str, *, label: str) -> Path:
    _validate_relative_reference(reference, label=label)
    base = run_spec_path.parent.resolve()
    target = (base / reference).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"{label}: artifact path escapes the run directory")
    if not target.is_file():
        raise ValueError(f"{label}: artifact file does not exist: {reference}")
    return target


def validate_run_bundle(run_spec_path: Path) -> dict[str, Any]:
    """Validate one run's sidecars and cross-authority digest joins."""
    run_spec_path = run_spec_path.resolve()
    run_spec = validate_run_spec(run_spec_path)
    artifacts = run_spec["artifacts"]
    attempts_path = _resolve_run_artifact(
        run_spec_path,
        str(artifacts["attempts"]),
        label=f"{run_spec_path}:attempts",
    )
    analysis_path = _resolve_run_artifact(
        run_spec_path,
        str(artifacts["analysis"]),
        label=f"{run_spec_path}:analysis",
    )
    attempts = validate_attempts(attempts_path)
    validate_analysis(
        analysis_path,
        run_spec_path=run_spec_path,
        attempts_path=attempts_path,
    )
    relative_evidence = {
        (str(ref["kind"]), str(ref["path"]), str(ref["sha256"]))
        for attempt in attempts
        for ref in attempt["evidence_refs"]
    }
    evidence = {
        (
            kind,
            (attempts_path.parent / path).resolve(),
            digest,
        )
        for kind, path, digest in relative_evidence
    }
    declared: dict[str, Path] = {}
    trajectory_release_files: set[Path] = set()
    measurement_payload: dict[str, Any] | None = None
    for name, kind in _RUN_ARTIFACT_KINDS.items():
        reference = artifacts.get(name)
        if reference is None:
            if any(evidence_kind == kind for evidence_kind, _path, _digest in evidence):
                raise ValueError(
                    f"{run_spec_path}: {kind} evidence is not declared in run-spec artifacts"
                )
            continue
        target = _resolve_run_artifact(
            run_spec_path,
            str(reference),
            label=f"{run_spec_path}:{name}",
        )
        identity = (kind, target, _sha256(target))
        if identity not in evidence:
            raise ValueError(f"{run_spec_path}: {name} is not digest-bound by attempts")
        declared[name] = target

        if name == "measurement_results":
            measurement = _load_json_object(target)
            measurement_payload = measurement
            _validate_measurement_binding(
                target,
                measurement,
                run_id=str(run_spec["run_id"]),
                run_spec_sha256=_sha256(run_spec_path),
                evidence=relative_evidence,
            )
        elif name == "trajectory":
            trajectory = _load_json_object(target)
            schema_id = str(trajectory.get("schema_id") or "")
            if schema_id == "geode.trajectory@1":
                from core.observability.record_schema import validate_record
                from core.observability.trajectory import verify_trajectory_integrity

                validate_record(trajectory, schema_id=schema_id)
                verify_trajectory_integrity(trajectory)
            elif schema_id == "geode.trajectory-release@1" and target.name == "manifest.json":
                from core.observability.trajectory_release import verify_trajectory_release

                release = verify_trajectory_release(
                    target.parent,
                    expected_manifest_sha256=_sha256(target),
                )
                if release["release_scope"] != run_spec["run_id"]:
                    raise ValueError(
                        f"{run_spec_path}: trajectory release scope does not match run"
                    )
                trajectory_release_files = {
                    (target.parent / str(row["path"])).resolve() for row in release["files"]
                }
            else:
                raise ValueError(f"{run_spec_path}: unsupported trajectory artifact {schema_id!r}")

    if measurement_payload is not None:
        verifier_path = declared.get("verifier_receipts")
        verifier_digest = measurement_payload.get("verifier_results_sha256")
        if verifier_path is not None and verifier_digest != _sha256(verifier_path):
            raise ValueError(f"{run_spec_path}: measurement omits the declared verifier result")
        outcome_path = declared.get("outcome_receipts")
        if outcome_path is not None:
            outcome_context = measurement_payload.get("outcome_context")
            expected_context = {
                "path": str(artifacts["outcome_receipts"]),
                "sha256": _sha256(outcome_path),
            }
            if outcome_context != expected_context:
                raise ValueError(f"{run_spec_path}: measurement omits the declared outcome receipt")

    publication_status = None
    publication_ref = artifacts.get("publication_manifest")
    if publication_ref is not None:
        publication_path = _resolve_run_artifact(
            run_spec_path,
            str(publication_ref),
            label=f"{run_spec_path}:publication_manifest",
        )
        publication = validate_publication(publication_path)
        if publication["run_id"] != run_spec["run_id"]:
            raise ValueError(f"{run_spec_path}: publication run_id does not match run spec")
        if publication["geode"]["revision"] != run_spec["reproduction"]["geode"]["revision"]:
            raise ValueError(f"{run_spec_path}: publication GEODE revision does not match run spec")
        publication_sources = set()
        for entry in publication["entries"]:
            local_path = str(entry["local_path"])
            candidates = (publication_path.parent / local_path, REPO_ROOT / local_path)
            publication_sources.add(next(path.resolve() for path in candidates if path.is_file()))
        required_sources = {
            run_spec_path,
            attempts_path,
            analysis_path,
            *declared.values(),
            *trajectory_release_files,
        }
        missing = sorted(str(path) for path in required_sources - publication_sources)
        if missing:
            raise ValueError(
                f"{run_spec_path}: publication does not classify every run artifact: {missing[0]}"
            )
        publication_status = publication["publication"]["status"]

    return {
        "run_id": run_spec["run_id"],
        "attempts": len(attempts),
        "declared_artifacts": sorted(declared),
        "publication_status": publication_status,
    }


def validate_publication(path: Path) -> dict[str, Any]:
    """Validate one publication manifest and every declared local source byte."""
    _reject_placeholders(path)
    payload = _load_json_object(path)
    _validate_schema(payload, PUBLICATION_SCHEMA, label=str(path))

    repository = payload["artifact_repository"]
    if repository["url"] != "https://github.com/mangowhoiscloud/geode-eval-artifacts":
        raise ValueError(f"{path}: artifact repository URL is not canonical")
    destination_prefix = str(repository["destination_prefix"])
    _validate_relative_reference(destination_prefix, label=str(path))

    local_paths: set[str] = set()
    remote_paths: set[str] = set()
    public_bytes = 0
    public_files = 0
    for entry in payload["entries"]:
        local_path = str(entry["local_path"])
        _validate_relative_reference(local_path, label=str(path))
        if local_path in local_paths:
            raise ValueError(f"{path}: duplicate publication local_path: {local_path}")
        local_paths.add(local_path)

        candidates = (path.parent / local_path, REPO_ROOT / local_path)
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            raise ValueError(f"{path}: publication source file does not exist: {local_path}")
        if source.stat().st_size != entry["bytes"]:
            raise ValueError(f"{path}: publication byte count does not match: {local_path}")
        if _sha256(source) != entry["sha256"]:
            raise ValueError(f"{path}: publication SHA-256 does not match: {local_path}")

        if entry["classification"] != "public":
            continue
        remote_path = str(entry["remote_path"])
        _validate_relative_reference(remote_path, label=str(path))
        if remote_path in remote_paths:
            raise ValueError(f"{path}: duplicate publication remote_path: {remote_path}")
        remote_paths.add(remote_path)
        if destination_prefix != "." and not remote_path.startswith(f"{destination_prefix}/"):
            raise ValueError(f"{path}: public remote_path is outside destination_prefix")
        public_files += 1
        public_bytes += int(entry["bytes"])

    verification = payload["verification"]
    if not verification["source_hashes_verified"]:
        raise ValueError(f"{path}: source_hashes_verified must be true after byte validation")
    if public_files and not (
        verification["local_identity_scrubbed"] and verification["secret_scan_passed"]
    ):
        raise ValueError(f"{path}: public entries require identity and secret review")

    run_record = REPO_ROOT / str(payload["geode"]["run_record"])
    if not run_record.is_file():
        raise ValueError(f"{path}: GEODE run record does not exist")

    publication = payload["publication"]
    if publication["status"] == "published":
        readback = publication["remote_readback"]
        if readback["files_verified"] != public_files:
            raise ValueError(f"{path}: remote read-back file count does not match public entries")
        if readback["bytes_verified"] != public_bytes:
            raise ValueError(f"{path}: remote read-back bytes do not match public entries")
        if _parse_datetime(readback["verified_at"]) < _parse_datetime(publication["published_at"]):
            raise ValueError(f"{path}: remote read-back predates publication")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="generate or check docs/eval/index.json")
    mode = catalog.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")

    run_spec = subparsers.add_parser("validate-run-spec")
    run_spec.add_argument("path", type=Path)

    attempts = subparsers.add_parser("validate-attempts")
    attempts.add_argument("path", type=Path)

    analysis = subparsers.add_parser("validate-analysis")
    analysis.add_argument("path", type=Path)
    analysis.add_argument("--run-spec", type=Path, required=True)
    analysis.add_argument("--attempts", type=Path, required=True)

    publication = subparsers.add_parser("validate-publication")
    publication.add_argument("path", type=Path)

    bundle = subparsers.add_parser("validate-run-bundle")
    bundle.add_argument("run_spec", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "catalog":
            write_or_check_catalog(write=args.write)
        elif args.command == "validate-run-spec":
            validate_run_spec(args.path)
            print(f"run spec OK: {args.path}")
        elif args.command == "validate-attempts":
            attempts = validate_attempts(args.path)
            print(f"attempts OK: {len(attempts)} rows")
        elif args.command == "validate-analysis":
            validate_analysis(args.path, run_spec_path=args.run_spec, attempts_path=args.attempts)
            print(f"analysis OK: {args.path}")
        elif args.command == "validate-publication":
            publication = validate_publication(args.path)
            public = sum(entry["classification"] == "public" for entry in publication["entries"])
            print(f"publication OK: {public} public entries")
        elif args.command == "validate-run-bundle":
            bundle = validate_run_bundle(args.run_spec)
            print(
                "run bundle OK: {run_id} attempts={attempts} artifacts={artifacts}".format(
                    run_id=bundle["run_id"],
                    attempts=bundle["attempts"],
                    artifacts=len(bundle["declared_artifacts"]),
                )
            )
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"eval contract error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
