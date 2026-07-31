"""Load and validate GEODE's packaged record schemas."""

from __future__ import annotations

import json
from datetime import date, datetime
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "geode.session-event@1": "session-event.schema.json",
    "geode.run-event@1": "run-event.schema.json",
    "geode.trajectory@1": "trajectory.schema.json",
    "geode.trajectory-release@1": "trajectory-release.schema.json",
}


def load_record_schema(schema_id: str) -> dict[str, Any]:
    """Load one packaged schema by its stable record id."""
    filename = SCHEMA_FILES.get(schema_id)
    if filename is None:
        raise ValueError(f"unknown GEODE record schema: {schema_id!r}")
    resource = files("core.observability.schemas").joinpath(filename)
    loaded = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"record schema {schema_id!r} is not a JSON object")
    return loaded


def validate_record(record: dict[str, Any], *, schema_id: str | None = None) -> None:
    """Raise ``ValueError`` with stable paths when a record violates its schema."""
    resolved = schema_id or str(record.get("schema_id") or "")
    _validate_temporal_formats(record, resolved)
    validator = Draft202012Validator(
        load_record_schema(resolved),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(record), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    details = "; ".join(
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors[:8]
    )
    raise ValueError(f"{resolved} validation failed: {details}")


def _validate_temporal_formats(record: dict[str, Any], schema_id: str) -> None:
    """Enforce formats unavailable in minimal jsonschema installations."""
    if schema_id not in {"geode.trajectory@1", "geode.trajectory-release@1"}:
        return
    fields = (
        ("published_at",)
        if schema_id == "geode.trajectory-release@1"
        else (
            "captured_at",
            "published_at",
        )
    )
    for field in fields:
        value = record.get(field)
        if value is None or not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{schema_id} validation failed: {field}: invalid date-time") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{schema_id} validation failed: {field}: timezone is required")
    observed_on = record.get("observed_on")
    if isinstance(observed_on, str):
        try:
            parsed_date = date.fromisoformat(observed_on)
        except ValueError as exc:
            raise ValueError(f"{schema_id} validation failed: observed_on: invalid date") from exc
        if parsed_date.isoformat() != observed_on:
            raise ValueError(f"{schema_id} validation failed: observed_on: invalid date")


__all__ = ["SCHEMA_FILES", "load_record_schema", "validate_record"]
