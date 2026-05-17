"""Domain pipeline compatibility boundary.

GEODE no longer ships the Game IP analysis pipeline in core. The former
``geode analyze`` execution path now belongs in an external domain
plugin/repository.
"""

from __future__ import annotations

from typing import Any


def _removed_pipeline_error() -> RuntimeError:
    return RuntimeError(
        "The bundled Game IP analysis pipeline was removed from GEODE core. "
        "Install the external domain package and use its CLI entrypoint."
    )


def _run_analysis(*args: Any, **kwargs: Any) -> Any:
    raise _removed_pipeline_error()


def _build_initial_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise _removed_pipeline_error()


def _execute_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    raise _removed_pipeline_error()


async def _execute_pipeline_streaming(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    raise _removed_pipeline_error()


def _render_result(*args: Any, **kwargs: Any) -> None:
    raise _removed_pipeline_error()


def _render_verification(*args: Any, **kwargs: Any) -> None:
    raise _removed_pipeline_error()


def _resolve_ip_name(raw: str) -> str:
    return raw.strip()
