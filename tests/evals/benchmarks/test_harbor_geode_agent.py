from __future__ import annotations

import asyncio
from types import SimpleNamespace

from evals.platforms.harbor import HarborExecTool


class _Environment:
    def __init__(self) -> None:
        self.call: dict[str, object] = {}

    async def exec(self, **kwargs: object) -> SimpleNamespace:
        self.call = kwargs
        return SimpleNamespace(stdout="ok\n", stderr="", return_code=0)


def test_harbor_exec_tool_preserves_environment_result() -> None:
    environment = _Environment()
    result = asyncio.run(
        HarborExecTool(environment).aexecute(
            command="pwd",
            cwd="/root",
            timeout_seconds=7,
        )
    )
    assert environment.call == {"command": "pwd", "cwd": "/root", "timeout_sec": 7}
    assert result == {"result": "ok\n", "stderr": "", "return_code": 0}
