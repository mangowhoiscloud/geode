"""External Trigger Endpoint — framework-agnostic gateway for pipeline triggers.

Provides a domain-layer component that external systems (Slack, CI/CD, APIs)
can use to trigger pipeline analysis. Designed to be mounted on any ASGI/HTTP
framework without introducing framework dependencies.

Architecture-v6 SS4.5: Automation Layer — External Trigger Gateway.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.automation.triggers import TriggerConfig, TriggerManager, TriggerType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / Response DTOs
# ---------------------------------------------------------------------------

_VALID_MODES = frozenset({"full_pipeline", "dry_run", "evaluation_only"})
_VALID_SOURCES = frozenset({"api", "slack", "ci_cd", "webhook"})


@dataclass
class TriggerRequest:
    """Incoming trigger request from an external system."""

    ip_name: str
    trigger_id: str | None = None
    mode: str = "full_pipeline"
    auth_token: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "api"


@dataclass
class TriggerResponse:
    """Result of processing a trigger request."""

    success: bool
    trigger_id: str
    message: str
    run_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Payload Transformer (mustache-like template resolution)
# ---------------------------------------------------------------------------

# Matches {{key}} or {{nested.key}}
_TEMPLATE_RE = re.compile(r"\{\{([\w.]+)\}\}")


class PayloadTransformer:
    """Resolve mustache-like ``{{key}}`` templates against a payload dict.

    Supports flat keys (``{{ip_name}}``) and dotted nested keys
    (``{{meta.region}}``).  Missing keys are replaced with an empty string.
    """

    @staticmethod
    def _resolve(key: str, payload: dict[str, Any]) -> str:
        """Walk dotted key path and return the resolved string value."""
        parts = key.split(".")
        current: Any = payload
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return ""
            if current is None:
                return ""
        return str(current)

    @classmethod
    def transform(cls, template: str, payload: dict[str, Any]) -> str:
        """Replace all ``{{...}}`` placeholders in *template*."""

        def _replacer(match: re.Match[str]) -> str:
            return cls._resolve(match.group(1), payload)

        return _TEMPLATE_RE.sub(_replacer, template)


# ---------------------------------------------------------------------------
# Trigger Mapping
# ---------------------------------------------------------------------------


@dataclass
class TriggerMapping:
    """Map an external source to trigger defaults."""

    source: str
    template: str | None = None
    default_mode: str = "full_pipeline"
    auto_register: bool = True


# ---------------------------------------------------------------------------
# Trigger Endpoint
# ---------------------------------------------------------------------------


class TriggerEndpoint:
    """Framework-agnostic gateway that routes external requests to TriggerManager.

    Usage::

        endpoint = TriggerEndpoint(trigger_manager, auth_token="secret")
        resp = endpoint.handle_request(TriggerRequest(ip_name="Berserk"))
    """

    def __init__(
        self,
        trigger_manager: TriggerManager,
        *,
        auth_token: str | None = None,
    ) -> None:
        self._manager = trigger_manager
        self._auth_token = auth_token
        self._mappings: dict[str, TriggerMapping] = {}

        # ContextVar initialization — TriggerManager callbacks may invoke
        # pipeline nodes that depend on memory ContextVars (org_memory,
        # project_memory).  Without this, any callback touching LLM tools
        # would find None callables → RuntimeError.
        try:
            from core.memory.organization import MonoLakeOrganizationMemory
            from core.memory.project import ProjectMemory
            from core.tools.memory_tools import set_org_memory, set_project_memory

            set_project_memory(ProjectMemory())
            set_org_memory(MonoLakeOrganizationMemory())
        except Exception:
            log.debug("Memory context initialization skipped", exc_info=True)

    # -- auth ---------------------------------------------------------------

    def validate_auth(self, token: str | None) -> bool:
        """Validate a bearer token.

        If no server-side token is configured, all requests are allowed.
        """
        if self._auth_token is None:
            return True
        if token is None:
            return False
        return token == self._auth_token

    # -- mappings -----------------------------------------------------------

    def register_mapping(self, mapping: TriggerMapping) -> None:
        """Register a source-specific trigger mapping."""
        self._mappings[mapping.source] = mapping

    # -- core ---------------------------------------------------------------

    def handle_request(self, request: TriggerRequest) -> TriggerResponse:
        """Process an incoming trigger request end-to-end.

        1. Validate auth token.
        2. Validate mode.
        3. Resolve trigger (auto-register if mapping allows).
        4. Fire the trigger via TriggerManager.
        """
        # Auth check
        if not self.validate_auth(request.auth_token):
            return TriggerResponse(
                success=False,
                trigger_id=request.trigger_id or "",
                message="Authentication failed",
                error="Invalid or missing auth token",
            )

        # Mode validation
        if request.mode not in _VALID_MODES:
            return TriggerResponse(
                success=False,
                trigger_id=request.trigger_id or "",
                message="Invalid mode",
                error=(
                    f"Mode '{request.mode}' is not valid. "
                    f"Must be one of: {', '.join(sorted(_VALID_MODES))}"
                ),
            )

        # Resolve or create trigger
        trigger_id = request.trigger_id
        if trigger_id is None:
            trigger_id = f"ext-{request.source}-{request.ip_name}"

        config = self._manager.get_trigger(trigger_id)
        if config is None:
            # Check mapping for auto-register
            mapping = self._mappings.get(request.source)
            should_auto = mapping.auto_register if mapping else True
            if should_auto:
                config = self._auto_register(trigger_id, request)
            else:
                return TriggerResponse(
                    success=False,
                    trigger_id=trigger_id,
                    message="Trigger not found and auto-register disabled",
                    error=(
                        f"No trigger '{trigger_id}' and source "
                        f"'{request.source}' disallows auto-register"
                    ),
                )

        # Build execution data
        run_id = uuid.uuid4().hex[:12]
        data: dict[str, Any] = {
            "ip_name": request.ip_name,
            "mode": request.mode,
            "source": request.source,
            "run_id": run_id,
            **request.payload,
        }

        # Resolve message template
        mapping = self._mappings.get(request.source)
        if mapping and mapping.template:
            message = PayloadTransformer.transform(mapping.template, data)
        else:
            message = f"Trigger fired for '{request.ip_name}' from {request.source}"

        # Fire via TriggerManager
        try:
            result = self._manager.fire_manual(trigger_id, data)
        except KeyError as exc:
            return TriggerResponse(
                success=False,
                trigger_id=trigger_id,
                message="Trigger execution failed",
                error=str(exc),
            )

        if result.success:
            return TriggerResponse(
                success=True,
                trigger_id=trigger_id,
                message=message,
                run_id=run_id,
            )

        return TriggerResponse(
            success=False,
            trigger_id=trigger_id,
            message="Trigger callback failed",
            run_id=run_id,
            error=result.error,
        )

    def create_pipeline_trigger(
        self,
        ip_name: str,
        *,
        mode: str = "full_pipeline",
        metadata: dict[str, Any] | None = None,
    ) -> TriggerResponse:
        """Convenience method to create and immediately fire a pipeline trigger."""
        trigger_id = f"pipe-{uuid.uuid4().hex[:8]}"
        extra_meta = metadata or {}

        self._manager.register_pipeline_trigger(
            trigger_id=trigger_id,
            ip_name=ip_name,
        )

        request = TriggerRequest(
            ip_name=ip_name,
            trigger_id=trigger_id,
            mode=mode,
            payload=extra_meta,
            source="api",
        )
        return self.handle_request(request)

    # -- internal -----------------------------------------------------------

    def _auto_register(
        self,
        trigger_id: str,
        request: TriggerRequest,
    ) -> TriggerConfig:
        """Register a WEBHOOK trigger on-the-fly from an external request."""
        config = TriggerConfig(
            trigger_id=trigger_id,
            trigger_type=TriggerType.WEBHOOK,
            name=f"auto:{request.source}:{request.ip_name}",
            webhook_path=f"/trigger/{trigger_id}",
            metadata={
                "ip_name": request.ip_name,
                "source": request.source,
                "auto_registered": True,
            },
        )
        self._manager.register(config)
        log.info("Auto-registered trigger %s for IP '%s'", trigger_id, request.ip_name)
        return config
