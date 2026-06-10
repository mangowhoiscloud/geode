"""Bug class B2 + B3 + B8 — slash command location invariants.

OAuth device-code prompt 가 IPC 모드에서 안 보이던 v0.51 버그의 근본
원인은 ``cmd_login`` 이 thin (slash) 와 daemon (manage_login tool) 양쪽에서
호출되면서 IPC writer 가용성이 달랐던 것. v0.52 phase 3 에서 도입한
``core.cli.routing.COMMAND_REGISTRY`` 가 location 을 명시하고 이 테스트가
다음을 강제한다:

  - 모든 등록 명령이 정확히 1 개 RunLocation 을 가진다.
  - THIN 명령의 핸들러는 IPC writer 의존이 없다 (daemon side ``capture_output()``
    이 swallowing 할 출력을 만들지 않는다).
  - 새 슬래시 명령을 추가할 때 registry 등록을 깜빡하면 lookup 이 None 을
    반환 → REPL 분기에서 명시적으로 처리되어야 함.
"""

from __future__ import annotations

import inspect
from importlib import import_module

from core.cli.routing import COMMAND_REGISTRY, CommandSpec, RunLocation, lookup


def test_every_registered_command_has_valid_location() -> None:
    for name, spec in COMMAND_REGISTRY.items():
        assert isinstance(spec, CommandSpec), name
        assert isinstance(spec.location, RunLocation), name
        assert spec.name == name


def test_aliases_resolve_to_canonical() -> None:
    for spec in COMMAND_REGISTRY.values():
        for alias in spec.aliases:
            resolved = lookup(alias)
            assert resolved is not None
            assert resolved.name == spec.name


def test_thin_commands_handler_paths_are_importable() -> None:
    """THIN 명령의 handler_path 가 실제 import 가능해야 — typo 즉시 잡음."""
    for name, spec in COMMAND_REGISTRY.items():
        if spec.location is not RunLocation.THIN:
            continue
        if not spec.handler_path:
            continue  # legacy entries before phase 4 may omit
        module_path, attr = spec.handler_path.split(":")
        mod = import_module(module_path)
        assert hasattr(mod, attr), f"{name}: {spec.handler_path} not importable"


def test_thin_commands_do_not_depend_on_ipc_writer() -> None:
    """THIN 명령 핸들러 소스에 _ipc_writer_local 의존이 없어야 한다.

    THIN 명령은 CLI 프로세스 안에서 직접 실행되므로 IPC writer 가 None.
    emit_* 함수의 fallback path (console.print) 를 사용한다. _ipc_writer_local
    을 명시적으로 참조하면 daemon-side 동작을 가정한 코드가 섞여 있다는 신호.
    """
    for name, spec in COMMAND_REGISTRY.items():
        if spec.location is not RunLocation.THIN:
            continue
        if not spec.handler_path:
            continue
        module_path, attr = spec.handler_path.split(":")
        mod = import_module(module_path)
        handler = getattr(mod, attr)
        try:
            src = inspect.getsource(handler)
        except (OSError, TypeError):
            continue
        # `_ipc_writer_local.writer = ...` 같은 *직접 set* 은 thin 에서 의미 없음
        assert "_ipc_writer_local.writer =" not in src, (
            f"{name} (THIN handler) sets _ipc_writer_local.writer — "
            "this only makes sense in daemon-side code"
        )


def test_all_known_commands_appear_in_command_map() -> None:
    """COMMAND_MAP (legacy dispatch) 와 COMMAND_REGISTRY 가 동기화되어야.

    Phase 6 에서 COMMAND_MAP 폐기 예정이지만 그때까지는 누락 방지.
    """
    from core.cli.commands import COMMAND_MAP

    legacy_slashes = {k for k in COMMAND_MAP if k.startswith("/")}
    registered = set(COMMAND_REGISTRY.keys())
    # 모든 registry 항목이 legacy 에도 있어야 (역방향은 phase 4-6 에서 채워짐)
    missing_from_legacy = registered - legacy_slashes
    assert not missing_from_legacy, (
        f"COMMAND_REGISTRY 의 다음 명령이 COMMAND_MAP 에 없음: {missing_from_legacy}"
    )


def test_login_routes_to_thin() -> None:
    """OAuth flow 가 thin 에서 실행되어야 한다 — 핵심 invariant."""
    spec = lookup("/login")
    assert spec is not None
    assert spec.location is RunLocation.THIN, (
        "/login MUST be THIN — daemon-side execution swallows OAuth device-code "
        "prompt via capture_output(). This was bug class B1/B3 (v0.51)."
    )
    assert spec.needs_tty, "/login OAuth wizard requires terminal"
