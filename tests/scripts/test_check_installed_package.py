from __future__ import annotations

from scripts import check_installed_package as installed


def test_core_module_names_come_only_from_installed_kernel_python_files() -> None:
    paths = frozenset(
        {
            "core/__init__.py",
            "core/agent/__init__.py",
            "core/agent/loop.py",
            "core/tools/definitions.json",
            "geode_product/cli.py",
        }
    )

    assert installed._core_module_names(paths) == ("core", "core.agent", "core.agent.loop")


def test_kernel_runtime_constructs_defaults_and_shuts_down() -> None:
    installed._check_kernel_runtime()


def test_main_preserves_full_mode_and_dispatches_kernel_mode(monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(installed, "_check_full_package", lambda: called.append("full"))
    monkeypatch.setattr(installed, "_check_kernel_package", lambda: called.append("kernel"))

    installed.main([])
    installed.main(["--kernel-only"])

    assert called == ["full", "kernel"]
