"""Tests for External Trigger Endpoint."""

from core.automation.trigger_endpoint import (
    PayloadTransformer,
    TriggerEndpoint,
    TriggerMapping,
    TriggerRequest,
    TriggerResponse,
)
from core.automation.triggers import (
    TriggerConfig,
    TriggerManager,
    TriggerType,
)

# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_handle_request_valid_auth(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr, auth_token="secret-123")
        request = TriggerRequest(ip_name="Berserk", auth_token="secret-123")
        resp = endpoint.handle_request(request)
        assert resp.success is True
        assert resp.trigger_id != ""

    def test_handle_request_invalid_auth(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr, auth_token="secret-123")
        request = TriggerRequest(ip_name="Berserk", auth_token="wrong-token")
        resp = endpoint.handle_request(request)
        assert resp.success is False
        assert resp.error is not None
        assert "auth" in resp.error.lower()

    def test_handle_request_no_auth_when_not_configured(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)  # no auth_token
        request = TriggerRequest(ip_name="Berserk")
        resp = endpoint.handle_request(request)
        assert resp.success is True

    def test_handle_request_missing_token_when_required(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr, auth_token="secret-123")
        request = TriggerRequest(ip_name="Berserk", auth_token=None)
        resp = endpoint.handle_request(request)
        assert resp.success is False


# ---------------------------------------------------------------------------
# Pipeline trigger
# ---------------------------------------------------------------------------


class TestCreatePipelineTrigger:
    def test_creates_and_fires(self) -> None:
        fired: list[dict[str, object]] = []
        mgr = TriggerManager()

        # Patch register_pipeline_trigger to inject a callback
        original = mgr.register_pipeline_trigger

        def patched_register(
            trigger_id: str,
            ip_name: str,
            **kwargs: object,
        ) -> TriggerConfig:
            return original(
                trigger_id=trigger_id,
                ip_name=ip_name,
                callback=lambda data: fired.append(data),
            )

        mgr.register_pipeline_trigger = patched_register  # type: ignore[assignment]

        endpoint = TriggerEndpoint(mgr)
        resp = endpoint.create_pipeline_trigger("Berserk")
        assert resp.success is True
        assert resp.run_id is not None
        assert resp.trigger_id.startswith("pipe-")
        assert len(fired) == 1
        assert fired[0]["ip_name"] == "Berserk"

    def test_with_metadata(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)
        resp = endpoint.create_pipeline_trigger(
            "Berserk",
            mode="dry_run",
            metadata={"region": "KR"},
        )
        assert resp.success is True


# ---------------------------------------------------------------------------
# PayloadTransformer
# ---------------------------------------------------------------------------


class TestPayloadTransformer:
    def test_flat_keys(self) -> None:
        template = "Analysis for {{ip_name}} from {{source}}"
        result = PayloadTransformer.transform(template, {"ip_name": "Berserk", "source": "slack"})
        assert result == "Analysis for Berserk from slack"

    def test_nested_keys(self) -> None:
        template = "Region: {{meta.region}}, Tier: {{meta.tier}}"
        payload = {"meta": {"region": "KR", "tier": "gold"}}
        result = PayloadTransformer.transform(template, payload)
        assert result == "Region: KR, Tier: gold"

    def test_missing_keys_replaced_empty(self) -> None:
        template = "IP: {{ip_name}}, Missing: {{not_here}}"
        result = PayloadTransformer.transform(template, {"ip_name": "Berserk"})
        assert result == "IP: Berserk, Missing: "

    def test_deeply_nested_missing(self) -> None:
        template = "{{a.b.c}}"
        result = PayloadTransformer.transform(template, {"a": {"b": {}}})
        assert result == ""

    def test_no_placeholders(self) -> None:
        template = "No placeholders here"
        result = PayloadTransformer.transform(template, {"key": "value"})
        assert result == "No placeholders here"


# ---------------------------------------------------------------------------
# TriggerMapping
# ---------------------------------------------------------------------------


class TestTriggerMapping:
    def test_source_matching(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)
        mapping = TriggerMapping(
            source="slack",
            template="Slack trigger for {{ip_name}}",
            default_mode="dry_run",
        )
        endpoint.register_mapping(mapping)
        request = TriggerRequest(ip_name="Berserk", source="slack")
        resp = endpoint.handle_request(request)
        assert resp.success is True
        assert resp.message == "Slack trigger for Berserk"

    def test_mapping_auto_register_disabled(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)
        mapping = TriggerMapping(source="ci_cd", auto_register=False)
        endpoint.register_mapping(mapping)
        request = TriggerRequest(ip_name="Berserk", source="ci_cd")
        resp = endpoint.handle_request(request)
        assert resp.success is False
        assert "auto-register" in (resp.error or "").lower()


# ---------------------------------------------------------------------------
# Auto-register
# ---------------------------------------------------------------------------


class TestAutoRegister:
    def test_auto_register_on_first_request(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)
        request = TriggerRequest(ip_name="Berserk", source="api")
        resp = endpoint.handle_request(request)
        assert resp.success is True
        # Trigger should now be registered
        trigger = mgr.get_trigger("ext-api-Berserk")
        assert trigger is not None
        assert trigger.metadata["auto_registered"] is True

    def test_second_request_reuses_trigger(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)
        req1 = TriggerRequest(ip_name="Berserk", source="api")
        req2 = TriggerRequest(ip_name="Berserk", source="api")
        resp1 = endpoint.handle_request(req1)
        resp2 = endpoint.handle_request(req2)
        assert resp1.success is True
        assert resp2.success is True
        assert resp1.trigger_id == resp2.trigger_id


# ---------------------------------------------------------------------------
# Mode validation
# ---------------------------------------------------------------------------


class TestModeValidation:
    def test_valid_modes(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)
        for mode in ("full_pipeline", "dry_run", "evaluation_only"):
            request = TriggerRequest(ip_name="Berserk", mode=mode)
            resp = endpoint.handle_request(request)
            assert resp.success is True, f"Mode '{mode}' should be valid"

    def test_invalid_mode_rejected(self) -> None:
        mgr = TriggerManager()
        endpoint = TriggerEndpoint(mgr)
        request = TriggerRequest(ip_name="Berserk", mode="turbo")
        resp = endpoint.handle_request(request)
        assert resp.success is False
        assert resp.error is not None
        assert "turbo" in resp.error


# ---------------------------------------------------------------------------
# Integration with TriggerManager
# ---------------------------------------------------------------------------


class TestTriggerManagerIntegration:
    def test_fire_and_results(self) -> None:
        fired: list[dict[str, object]] = []
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="ext-api-Berserk",
                trigger_type=TriggerType.WEBHOOK,
                callback=lambda data: fired.append(data),
            )
        )
        endpoint = TriggerEndpoint(mgr)
        request = TriggerRequest(
            ip_name="Berserk",
            trigger_id="ext-api-Berserk",
            source="api",
        )
        resp = endpoint.handle_request(request)
        assert resp.success is True
        assert resp.run_id is not None
        assert len(fired) == 1
        assert fired[0]["ip_name"] == "Berserk"
        assert fired[0]["run_id"] == resp.run_id
        # Verify TriggerManager tracked the result
        results = mgr.get_results("ext-api-Berserk")
        assert len(results) == 1
        assert results[0].success is True

    def test_callback_failure_propagates(self) -> None:
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="fail-trigger",
                trigger_type=TriggerType.WEBHOOK,
                callback=lambda data: (_ for _ in ()).throw(RuntimeError("boom")),
            )
        )
        endpoint = TriggerEndpoint(mgr)
        request = TriggerRequest(ip_name="X", trigger_id="fail-trigger")
        resp = endpoint.handle_request(request)
        assert resp.success is False
        assert resp.error is not None
        assert "boom" in resp.error


# ---------------------------------------------------------------------------
# TriggerResponse structure
# ---------------------------------------------------------------------------


class TestTriggerResponse:
    def test_fields(self) -> None:
        resp = TriggerResponse(
            success=True,
            trigger_id="t-1",
            message="ok",
            run_id="abc123",
        )
        assert resp.success is True
        assert resp.trigger_id == "t-1"
        assert resp.run_id == "abc123"
        assert resp.error is None
