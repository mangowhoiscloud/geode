from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("harbor.environments.docker.docker")

from evals.platforms.harbor_docker import GeodeHarborDockerEnvironment
from harbor.environments.docker import COMPOSE_NO_NETWORK_PATH
from harbor.environments.docker.docker import DockerEnvironment
from harbor.environments.factory import EnvironmentFactory
from harbor.models.task.config import EnvironmentConfig, NetworkPolicy
from harbor.models.trial.config import EnvironmentConfig as TrialEnvironmentConfig
from harbor.models.trial.paths import TrialPaths


@pytest.fixture
def native_kwargs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    def forbidden_probe() -> bool:
        pytest.fail("static offline/public setup must not execute a Docker probe")

    monkeypatch.setattr(
        DockerEnvironment, "_egress_control_kernel_support", staticmethod(forbidden_probe)
    )
    return {
        "environment_dir": tmp_path,
        "environment_name": "offline-verifier",
        "session_id": "offline-verifier-test",
        "trial_paths": TrialPaths(trial_dir=tmp_path / "trial"),
        "task_env_config": EnvironmentConfig(docker_image="python:3.12-slim"),
    }


def test_native_factory_enforces_static_offline_compose(native_kwargs: dict[str, Any]) -> None:
    policy = NetworkPolicy(network_mode="no-network")
    env = EnvironmentFactory.create_environment_from_config(
        TrialEnvironmentConfig(
            import_path="evals.platforms.harbor_docker:GeodeHarborDockerEnvironment"
        ),
        **native_kwargs,
        network_policy=policy,
        phase_network_policies=[policy],
    )
    assert isinstance(env, GeodeHarborDockerEnvironment)
    assert env.capabilities.disable_internet is True
    assert env.capabilities.dynamic_network_policy is False
    assert env.capabilities.network_allowlist is False
    assert env._docker_compose_paths[-1] == COMPOSE_NO_NETWORK_PATH
    assert "network_mode: none" in COMPOSE_NO_NETWORK_PATH.read_text()
    env.validate_network_policy_support(policy)
    asyncio.run(env.set_network_policy(policy))


def test_public_agent_path_preserves_native_capabilities(native_kwargs: dict[str, Any]) -> None:
    native = DockerEnvironment(**native_kwargs)
    adapter = GeodeHarborDockerEnvironment(**native_kwargs)
    assert adapter.capabilities == native.capabilities
    assert adapter._docker_compose_paths == native._docker_compose_paths
    assert COMPOSE_NO_NETWORK_PATH not in adapter._docker_compose_paths


@pytest.mark.parametrize("mode", ["public", "allowlist"])
def test_static_offline_rejects_phase_changes(native_kwargs: dict[str, Any], mode: str) -> None:
    with pytest.raises(ValueError, match="cannot change"):
        GeodeHarborDockerEnvironment(
            **native_kwargs,
            network_policy=NetworkPolicy(network_mode="no-network"),
            phase_network_policies=[NetworkPolicy(network_mode=mode)],
        )


@pytest.mark.parametrize("mode", ["public", "allowlist"])
def test_static_offline_rejects_runtime_relaxation(
    native_kwargs: dict[str, Any], mode: str
) -> None:
    env = GeodeHarborDockerEnvironment(
        **native_kwargs, network_policy=NetworkPolicy(network_mode="no-network")
    )
    with pytest.raises(ValueError):
        asyncio.run(env.set_network_policy(NetworkPolicy(network_mode=mode)))
    with pytest.raises(ValueError, match="cannot be relaxed"):
        asyncio.run(env._apply_network_policy(NetworkPolicy(network_mode=mode)))


@pytest.mark.parametrize("custom_compose", ["task", "extra"])
def test_static_offline_rejects_uncovered_services(
    native_kwargs: dict[str, Any], custom_compose: str
) -> None:
    path = native_kwargs["environment_dir"] / "docker-compose.yaml"
    if custom_compose == "task":
        path.write_text("services: {}")
    else:
        native_kwargs["extra_docker_compose"] = [path]
    with pytest.raises(ValueError, match="single-container"):
        GeodeHarborDockerEnvironment(
            **native_kwargs, network_policy=NetworkPolicy(network_mode="no-network")
        )


def test_static_offline_rejects_windows(native_kwargs: dict[str, Any]) -> None:
    native_kwargs["task_env_config"] = EnvironmentConfig(docker_image="windows-test", os="windows")
    with pytest.raises(ValueError, match="Windows containers"):
        GeodeHarborDockerEnvironment(
            **native_kwargs, network_policy=NetworkPolicy(network_mode="no-network")
        )


def test_public_to_offline_requires_native_egress_support(
    native_kwargs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        DockerEnvironment, "_egress_control_kernel_support", staticmethod(lambda: False)
    )
    with pytest.raises(ValueError, match="not supported"):
        GeodeHarborDockerEnvironment(
            **native_kwargs,
            network_policy=NetworkPolicy(network_mode="public"),
            phase_network_policies=[NetworkPolicy(network_mode="no-network")],
        )
