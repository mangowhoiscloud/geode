"""Tests for the 2026-05-25 attribution wiring (W1-W4).

Covers the closed loop completion from
``docs/plans/2026-05-25-attribution-wiring-gap-fill.md`` §5:

* **W1** — ``expected_dim`` is requested by the mutator prompt and
  warned-on-empty by ``parse_mutation``.
* **W2** — the ``compute_attribution`` caller hook in
  ``core/self_improving/train.py`` fires when ``GEODE_SIL_*`` env triplet is
  set, and skips otherwise (legacy --promote preserved).
* **W3** — ``audit_run_id`` propagates from ``apply_proposal`` through
  ``Mutation.to_audit_row`` and the autoresearch subprocess env.
* **W4** — ``ApplyRecord`` / ``AttributionRecord`` Pydantic schemas
  freeze the mutations.jsonl row shape; ``extra="allow"`` keeps legacy
  dict rows readable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from core.self_improving.loop.attribution import (
    AttributionRecord,
    append_attribution_log,
)
from core.self_improving.loop.runner import (
    _MUTATION_CONTRACT_SUFFIX,
    ApplyRecord,
    Mutation,
    _run_autoresearch_subprocess,
    append_audit_log,
    parse_mutation,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# W1 — mutator prompt + parse_mutation
# ---------------------------------------------------------------------------


class TestW1ExpectedDimPromptAndParse:
    def test_mutation_contract_suffix_requests_expected_dim(self) -> None:
        """The mutator prompt must explicitly request ``expected_dim`` so
        PR-5 attribution can compute observed vs expected delta.

        Regression guard for the closed-loop wiring — without this the
        LLM has no reason to populate ``expected_dim`` and attribution
        scores degrade to 0.0 silently.
        """
        assert '"expected_dim"' in _MUTATION_CONTRACT_SUFFIX
        assert "expected delta" in _MUTATION_CONTRACT_SUFFIX
        assert (
            "PR-5 attribution" in _MUTATION_CONTRACT_SUFFIX
            or "attribution" in _MUTATION_CONTRACT_SUFFIX
        )

    def test_parse_mutation_warns_on_empty_expected_dim(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """W1: missing ``expected_dim`` is a silent dead-loop signal —
        ``parse_mutation`` must surface it via WARNING log so operators
        can spot mutators that drop the commitment."""
        raw = json.dumps(
            {
                "target_section": "thinking_visibility",
                "new_value": "Surface your reasoning.",
                "rationale": "operator request",
                # expected_dim intentionally omitted
            }
        )
        with caplog.at_level(logging.WARNING, logger="core.self_improving.loop.runner"):
            mutation = parse_mutation(raw)
        assert mutation.expected_dim == {}
        assert any("empty expected_dim" in record.getMessage() for record in caplog.records)

    def test_parse_mutation_no_warning_when_expected_dim_populated(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """W1 negative case — populated ``expected_dim`` must NOT warn."""
        raw = json.dumps(
            {
                "target_section": "thinking_visibility",
                "new_value": "Surface your reasoning.",
                "rationale": "operator request",
                "expected_dim": {"helpfulness": 0.1},
            }
        )
        with caplog.at_level(logging.WARNING, logger="core.self_improving.loop.runner"):
            mutation = parse_mutation(raw)
        assert mutation.expected_dim == {"helpfulness": 0.1}
        assert not any("empty expected_dim" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# W2 — subprocess env propagation
# ---------------------------------------------------------------------------


class TestW2SubprocessEnvPropagation:
    def test_run_autoresearch_subprocess_sets_sil_env_when_triplet_supplied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """W2: when ``audit_run_id`` + ``mutation_id`` are supplied,
        env triplet must propagate to subprocess. Captures the env dict
        passed to subprocess.run via monkeypatch instead of actually
        spawning."""
        captured: dict[str, str] = {}

        def fake_run(argv: list[str], *args: object, **kwargs: object) -> object:
            env = kwargs.get("env") or {}
            captured.update({k: v for k, v in env.items() if k.startswith("GEODE_SIL_")})

            class _Fake:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Fake()

        monkeypatch.setattr(
            "core.self_improving.loop.runner.subprocess.run",
            fake_run,
        )
        _run_autoresearch_subprocess(
            repo_root=tmp_path,
            dry_run=True,
            audit_run_id="audit-abc123",
            mutation_id="mut-xyz789",
            expected_dim={"safety": 0.3, "helpfulness": -0.05},
        )
        assert captured["GEODE_SIL_AUDIT_RUN_ID"] == "audit-abc123"
        assert captured["GEODE_SIL_MUTATION_ID"] == "mut-xyz789"
        # JSON encoded — parse and compare for stability against key order
        parsed = json.loads(captured["GEODE_SIL_EXPECTED_DIM"])
        assert parsed == {"safety": 0.3, "helpfulness": -0.05}

    def test_run_autoresearch_subprocess_skips_env_when_triplet_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """W2 negative — legacy --promote / standalone audit (no
        attribution context) must NOT inject the env triplet."""
        captured: dict[str, str] = {}

        def fake_run(argv: list[str], *args: object, **kwargs: object) -> object:
            env = kwargs.get("env") or {}
            captured.update({k: v for k, v in env.items() if k.startswith("GEODE_SIL_")})

            class _Fake:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Fake()

        monkeypatch.setattr(
            "core.self_improving.loop.runner.subprocess.run",
            fake_run,
        )
        _run_autoresearch_subprocess(repo_root=tmp_path, dry_run=True)
        assert "GEODE_SIL_AUDIT_RUN_ID" not in captured
        assert "GEODE_SIL_MUTATION_ID" not in captured
        assert "GEODE_SIL_EXPECTED_DIM" not in captured

    def test_run_autoresearch_subprocess_sets_rollback_condition_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """PR-SIL-MULTIOBJ A2 — ``rollback_condition`` propagates to the
        subprocess env so train.py's secondary gate can evaluate it."""
        captured: dict[str, str] = {}

        def fake_run(argv: list[str], *args: object, **kwargs: object) -> object:
            env = kwargs.get("env") or {}
            captured.update({k: v for k, v in env.items() if k.startswith("GEODE_SIL_")})

            class _Fake:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Fake()

        monkeypatch.setattr("core.self_improving.loop.runner.subprocess.run", fake_run)
        _run_autoresearch_subprocess(
            repo_root=tmp_path,
            dry_run=True,
            rollback_condition="critical dim regresses by more than 0.5",
        )
        assert captured["GEODE_SIL_ROLLBACK_CONDITION"] == "critical dim regresses by more than 0.5"

    def test_run_autoresearch_subprocess_skips_rollback_condition_when_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Empty rollback_condition ⇒ env unset ⇒ train.py skips the gate."""
        captured: dict[str, str] = {}

        def fake_run(argv: list[str], *args: object, **kwargs: object) -> object:
            env = kwargs.get("env") or {}
            captured.update({k: v for k, v in env.items() if k.startswith("GEODE_SIL_")})

            class _Fake:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Fake()

        monkeypatch.setattr("core.self_improving.loop.runner.subprocess.run", fake_run)
        _run_autoresearch_subprocess(repo_root=tmp_path, dry_run=True, rollback_condition="")
        assert "GEODE_SIL_ROLLBACK_CONDITION" not in captured


# ---------------------------------------------------------------------------
# W3 — audit_run_id field on apply row
# ---------------------------------------------------------------------------


class TestW3AuditRunIdField:
    def test_apply_row_includes_audit_run_id_when_supplied(
        self,
        tmp_path: Path,
    ) -> None:
        """W3: ``append_audit_log(audit_run_id="...")`` writes a row
        with ``audit_run_id`` populated. Within-ledger correlation id
        (NOT a Petri eval archive path — that link is a follow-up PR;
        see plan §11)."""
        log_path = tmp_path / "mutations.jsonl"
        mutation = Mutation(
            target_section="role",
            new_value="You are GEODE.",
            rationale="test",
            expected_dim={"safety": 0.1},
        )
        append_audit_log(
            mutation,
            previous_value="",
            log_path=log_path,
            audit_run_id="audit-test-run-id",
        )
        rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["audit_run_id"] == "audit-test-run-id"
        assert rows[0]["mutation_id"] == mutation.mutation_id
        assert rows[0]["expected_dim"] == {"safety": 0.1}

    def test_apply_row_omits_audit_run_id_when_blank(
        self,
        tmp_path: Path,
    ) -> None:
        """W3 backward compat — legacy --promote / manual run produces
        no audit_run_id column. Legacy reader stays graceful."""
        log_path = tmp_path / "mutations.jsonl"
        mutation = Mutation(
            target_section="role",
            new_value="You are GEODE.",
            rationale="test",
        )
        append_audit_log(mutation, previous_value="", log_path=log_path)
        row = json.loads(log_path.read_text().splitlines()[0])
        assert "audit_run_id" not in row


# ---------------------------------------------------------------------------
# W4 — Pydantic schema freeze
# ---------------------------------------------------------------------------


class TestW4PydanticSchemaFreeze:
    def test_apply_record_roundtrip(self) -> None:
        """W4: ApplyRecord schema accepts a complete apply row and
        survives roundtrip without information loss."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied",
            "mutation_id": "mut-abc",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "old",
            "new_value": "new",
            "rationale": "test",
            "target_dim": "helpfulness",
            "expected_dim": {"helpfulness": 0.2},
            "rollback_condition": "any dim drops > 0.5",
            "baseline_fitness": 0.42,
            "audit_run_id": "audit-xyz",
        }
        record = ApplyRecord.model_validate(row)
        dumped = record.model_dump(exclude_none=True)
        # All supplied fields round-trip
        for key, value in row.items():
            assert dumped[key] == value

    def test_attribution_record_roundtrip(self) -> None:
        """W4: AttributionRecord schema accepts a complete attribution
        row including W3 ``audit_run_id`` + PR-E confidence trajectory."""
        payload = {
            "ts": 1716638500.0,
            "kind": "attribution",
            "mutation_id": "mut-abc",
            "observed_dim": {"helpfulness": 0.15},
            "ci95": {"helpfulness": 0.08},
            "significant": {"helpfulness": True},
            "attribution_score": 0.15,
            "missing_baseline": False,
            "confidence_trajectory": [0.7, 0.8, 0.75],
            "confidence_stability": 0.95,
            "fitness_before": 0.40,
            "fitness_after": 0.42,
            "fitness_delta": 0.02,
            "audit_run_id": "audit-xyz",
        }
        record = AttributionRecord.model_validate(payload)
        dumped = record.model_dump(exclude_none=True)
        for key, value in payload.items():
            assert dumped[key] == value

    def test_apply_record_rejects_wrong_kind(self) -> None:
        """W4: schema enforces ``kind="applied"`` literal — drift fails
        fast at the writer boundary so a stray ``attribution`` row
        cannot leak into the apply lane."""
        bad = {
            "ts": 1716638400.0,
            "kind": "attribution",  # wrong kind
            "mutation_id": "mut-abc",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
        }
        with pytest.raises(ValidationError):
            ApplyRecord.model_validate(bad)

    def test_legacy_dict_row_with_extra_fields_passes(
        self,
        tmp_path: Path,
    ) -> None:
        """W4 backward compat — legacy mutations.jsonl rows may carry
        keys this PR doesn't model (e.g. a future field). ``extra="allow"``
        keeps validation green so historical rows stay readable."""
        future_field_row = {
            "ts": 1716638400.0,
            "kind": "applied",
            "mutation_id": "mut-legacy",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
            "rationale": "",
            "future_feature_flag": "experimental",  # unknown
        }
        record = ApplyRecord.model_validate(future_field_row)
        assert record.mutation_id == "mut-legacy"

    def test_append_attribution_log_validates_payload(
        self,
        tmp_path: Path,
    ) -> None:
        """W4: append_attribution_log runs the Pydantic validator before
        write so invalid payloads never reach disk."""
        log_path = tmp_path / "mutations.jsonl"
        bad_payload = {
            "ts": "not-a-float",  # invalid type
            "kind": "attribution",
            "mutation_id": "mut-x",
        }
        with pytest.raises(ValidationError):
            append_attribution_log(bad_payload, log_path=log_path)
        assert not log_path.exists()


# ---------------------------------------------------------------------------
# Cross-ref invariant — mutation_id join
# ---------------------------------------------------------------------------


class TestMutationIdJoin:
    def test_apply_and_attribution_share_mutation_id(
        self,
        tmp_path: Path,
    ) -> None:
        """The whole point of the wiring: apply row + attribution row
        in the same mutations.jsonl can be joined by ``mutation_id``."""
        log_path = tmp_path / "mutations.jsonl"
        mutation = Mutation(
            target_section="role",
            new_value="You are GEODE.",
            rationale="test",
            expected_dim={"safety": 0.1},
        )
        append_audit_log(
            mutation,
            previous_value="",
            log_path=log_path,
            audit_run_id="audit-join-test",
        )
        # Attribution side — payload mimics what compute_attribution
        # would produce when called from train.py's W2 hook.
        attribution_payload = {
            "ts": 1716638500.0,
            "kind": "attribution",
            "mutation_id": mutation.mutation_id,  # same id
            "observed_dim": {"safety": 0.05},
            "ci95": {"safety": 0.02},
            "significant": {"safety": True},
            "attribution_score": 0.05,
            "missing_baseline": False,
            "confidence_trajectory": [],
            "confidence_stability": None,
            "audit_run_id": "audit-join-test",
        }
        append_attribution_log(attribution_payload, log_path=log_path)

        rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert len(rows) == 2
        apply_row = next(r for r in rows if r["kind"] == "applied")
        attribution_row = next(r for r in rows if r["kind"] == "attribution")
        assert apply_row["mutation_id"] == attribution_row["mutation_id"]
        assert apply_row["audit_run_id"] == attribution_row["audit_run_id"]
