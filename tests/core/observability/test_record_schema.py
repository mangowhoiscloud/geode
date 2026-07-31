"""Packaged record schemas are valid Draft 2020-12 contracts."""

import pytest
from core.observability.record_schema import SCHEMA_FILES, load_record_schema, validate_record
from jsonschema import Draft202012Validator


def test_every_packaged_record_schema_is_valid() -> None:
    assert set(SCHEMA_FILES) == {
        "geode.session-event@1",
        "geode.run-event@1",
        "geode.trajectory@1",
        "geode.trajectory-release@1",
    }
    for schema_id in SCHEMA_FILES:
        schema = load_record_schema(schema_id)
        Draft202012Validator.check_schema(schema)


def test_trajectory_timestamp_format_is_enforced() -> None:
    with pytest.raises(ValueError, match="captured_at"):
        validate_record(
            {
                "schema_id": "geode.trajectory@1",
                "schema_version": 1,
                "trajectory_id": "t-invalid-time",
                "captured_at": "not-a-time",
                "source": {"harness": "test", "session": "s-1"},
                "events": [],
                "outcome": {},
                "integrity": {
                    "record_count": 0,
                    "complete": False,
                    "incompleteness": ["test"],
                    "quality": {
                        "event_id_unique": True,
                        "ordinal_contiguous": True,
                        "correlation": {},
                        "tool_pairing": {},
                        "payload_issue_events": 0,
                    },
                },
                "privacy": {},
                "provenance": {},
            }
        )
