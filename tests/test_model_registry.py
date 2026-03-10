"""Tests for L4.5 Model Registry."""

from pathlib import Path

import pytest
from core.automation.model_registry import (
    VALID_TRANSITIONS,
    ModelRegistry,
    ModelVersion,
    PromotionStage,
    _compute_hash,
)


class TestPromotionStage:
    def test_all_stages(self):
        assert len(PromotionStage) == 5
        assert PromotionStage.DEV.value == "dev"
        assert PromotionStage.PROD.value == "prod"

    def test_valid_transitions(self):
        assert PromotionStage.STAGING in VALID_TRANSITIONS[PromotionStage.DEV]
        assert PromotionStage.PROD in VALID_TRANSITIONS[PromotionStage.CANARY]
        assert VALID_TRANSITIONS[PromotionStage.DEPRECATED] == []


class TestModelVersion:
    def test_to_dict(self):
        v = ModelVersion(version_id="v1.0", prompt_hash="abc123")
        d = v.to_dict()
        assert d["version_id"] == "v1.0"
        assert d["stage"] == "dev"

    def test_from_dict(self):
        d = {"version_id": "v1.0", "stage": "staging", "configs": {"temp": 0.3}}
        v = ModelVersion.from_dict(d)
        assert v.version_id == "v1.0"
        assert v.stage == PromotionStage.STAGING
        assert v.configs["temp"] == 0.3

    def test_round_trip(self):
        v = ModelVersion(
            version_id="v2.0",
            parent="v1.0",
            prompt_hash="hash1",
            configs={"model": "claude-opus-4-6"},
            metrics={"accuracy": 0.95},
        )
        d = v.to_dict()
        v2 = ModelVersion.from_dict(d)
        assert v2.version_id == v.version_id
        assert v2.parent == v.parent
        assert v2.configs == v.configs


class TestModelRegistry:
    def test_register(self):
        reg = ModelRegistry()
        v = reg.register("v1.0", configs={"temp": 0.3})
        assert v.version_id == "v1.0"
        assert v.stage == PromotionStage.DEV

    def test_register_duplicate_raises(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        with pytest.raises(ValueError, match="already registered"):
            reg.register("v1.0")

    def test_promote_dev_to_staging(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        v = reg.promote("v1.0", PromotionStage.STAGING)
        assert v.stage == PromotionStage.STAGING

    def test_promote_invalid_transition(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        with pytest.raises(ValueError, match="Invalid transition"):
            reg.promote("v1.0", PromotionStage.PROD)

    def test_promote_not_found(self):
        reg = ModelRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.promote("nope", PromotionStage.STAGING)

    def test_full_promotion_lifecycle(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        reg.promote("v1.0", PromotionStage.STAGING)
        reg.promote("v1.0", PromotionStage.CANARY)
        reg.promote("v1.0", PromotionStage.PROD)
        assert reg.get_version("v1.0").stage == PromotionStage.PROD

    def test_rollback(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        reg.promote("v1.0", PromotionStage.STAGING)
        v = reg.rollback("v1.0")
        assert v.stage == PromotionStage.DEV

    def test_rollback_from_dev_raises(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        with pytest.raises(ValueError, match="Cannot rollback"):
            reg.rollback("v1.0")

    def test_get_production(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        reg.promote("v1.0", PromotionStage.STAGING)
        reg.promote("v1.0", PromotionStage.CANARY)
        reg.promote("v1.0", PromotionStage.PROD)
        prod = reg.get_production()
        assert prod is not None
        assert prod.version_id == "v1.0"

    def test_get_production_none(self):
        reg = ModelRegistry()
        assert reg.get_production() is None

    def test_list_versions(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        reg.register("v2.0")
        versions = reg.list_versions()
        assert len(versions) == 2

    def test_list_versions_by_stage(self):
        reg = ModelRegistry()
        reg.register("v1.0")
        reg.register("v2.0")
        reg.promote("v1.0", PromotionStage.STAGING)
        staging = reg.list_versions(stage=PromotionStage.STAGING)
        assert len(staging) == 1
        assert staging[0].version_id == "v1.0"

    def test_file_persistence(self, tmp_path: Path):
        reg = ModelRegistry(storage_dir=tmp_path / "models")
        reg.register("v1.0", configs={"temp": 0.3})
        reg.promote("v1.0", PromotionStage.STAGING)

        # Load from disk
        reg2 = ModelRegistry(storage_dir=tmp_path / "models")
        v = reg2.get_version("v1.0")
        assert v is not None
        assert v.stage == PromotionStage.STAGING
        assert v.configs["temp"] == 0.3

    def test_compute_hash(self):
        h = _compute_hash("test data")
        assert len(h) == 16
        assert h == _compute_hash("test data")

    def test_register_with_hashes(self):
        reg = ModelRegistry()
        v = reg.register("v1.0", prompt_text="Hello", rubric_text="World")
        assert v.prompt_hash != ""
        assert v.rubric_hash != ""

    def test_promote_with_validation_gate_pass(self):
        mgr = ModelRegistry()
        v = mgr.register("v1.0.0")
        mgr.promote(v.version_id, PromotionStage.STAGING, validation_fn=lambda v: True)
        assert v.stage == PromotionStage.STAGING

    def test_promote_with_validation_gate_fail(self):
        mgr = ModelRegistry()
        v = mgr.register("v1.0.0")
        with pytest.raises(ValueError, match="Validation gate failed"):
            mgr.promote(v.version_id, PromotionStage.STAGING, validation_fn=lambda v: False)
        assert v.stage == PromotionStage.DEV  # unchanged
