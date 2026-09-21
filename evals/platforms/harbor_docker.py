"""Opt-in Harbor Docker provider for a statically offline separate verifier."""

from __future__ import annotations

import importlib
import importlib.metadata
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:

    class HarborDockerEnvironment:
        _is_windows_container: bool

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        @staticmethod
        def _requires_egress_control(
            *, startup_network_policy: Any, phase_network_policies: Sequence[Any]
        ) -> bool: ...

        @property
        def capabilities(self) -> Any: ...

        @property
        def _docker_compose_paths(self) -> list[Path]: ...

        async def _apply_network_policy(self, network_policy: Any) -> None: ...

else:
    try:
        HarborDockerEnvironment = importlib.import_module(
            "harbor.environments.docker.docker"
        ).DockerEnvironment
    except ImportError:  # Harbor is an opt-in controller dependency.
        HarborDockerEnvironment = object


class GeodeHarborDockerEnvironment(HarborDockerEnvironment):
    """Keep public agent networking native; enforce static verifier isolation.

    Harbor 0.22's nftables path rejects even static no-network on some Docker
    VMs. Its shipped Compose no-network overlay needs no nftables sidecar.
    Only single-container, permanently offline environments use that overlay;
    phase switching and task-authored Compose remain the native provider's job.
    """

    def __init__(
        self,
        environment_dir: Path,
        *args: Any,
        network_policy: Any = None,
        phase_network_policies: Sequence[Any] = (),
        **kwargs: Any,
    ) -> None:
        try:
            harbor_version = importlib.metadata.version("harbor")
        except importlib.metadata.PackageNotFoundError:
            harbor_version = None
        if harbor_version != "0.22.0":
            raise RuntimeError("native GEODE integration is validated only with harbor==0.22.0")
        self._static_no_network = (
            network_policy is not None and network_policy.network_mode == "no-network"
        )
        if self._static_no_network:
            if any(policy != network_policy for policy in phase_network_policies):
                raise ValueError("static verifier networking cannot change between phases")
            if (environment_dir / "docker-compose.yaml").exists() or kwargs.get(
                "extra_docker_compose"
            ):
                raise ValueError("static verifier networking requires a single-container task")
        super().__init__(
            environment_dir,
            *args,
            network_policy=network_policy,
            phase_network_policies=phase_network_policies,
            **kwargs,
        )

    @staticmethod
    def _requires_egress_control(
        *, startup_network_policy: Any, phase_network_policies: Sequence[Any]
    ) -> bool:
        if startup_network_policy.network_mode == "no-network" and all(
            policy == startup_network_policy for policy in phase_network_policies
        ):
            return False
        return bool(
            HarborDockerEnvironment._requires_egress_control(
                startup_network_policy=startup_network_policy,
                phase_network_policies=phase_network_policies,
            )
        )

    @property
    def capabilities(self) -> Any:
        capabilities = super().capabilities
        if self._static_no_network and not self._is_windows_container:
            return capabilities.model_copy(update={"disable_internet": True})
        return capabilities

    @property
    def _docker_compose_paths(self) -> list[Path]:
        paths = super()._docker_compose_paths
        if self._static_no_network:
            overlay = importlib.import_module("harbor.environments.docker").COMPOSE_NO_NETWORK_PATH
            return [*paths, cast(Path, overlay)]
        return paths

    async def _apply_network_policy(self, network_policy: Any) -> None:
        if self._static_no_network:
            if network_policy.network_mode != "no-network":
                raise ValueError("static verifier networking cannot be relaxed")
            return
        await super()._apply_network_policy(network_policy)
