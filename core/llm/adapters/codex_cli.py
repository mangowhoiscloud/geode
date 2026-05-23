"""CodexCliAdapter — local ``codex`` binary subprocess path.

Layer 3 adapter for OpenAI provider, source=adapter. Spawns the local ``codex``
CLI binary (the OpenAI Codex CLI, ChatGPT subscription-billed) and pipes the
prompt through stdin. The binary uses its own subscription quota — no GEODE-
side API key, no profile rotator.

Sibling of :class:`core.llm.adapters.claude_cli.ClaudeCliAdapter`. Maps to
paperclip's ``adapter-codex-local`` package.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from core.llm.adapters._subprocess_common import build_subprocess_stdin
from core.llm.adapters.base import (
    SOURCE_ADAPTER,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    CredentialDetection,
    EnvironmentReport,
    ModelSpec,
    QuotaWindows,
    StreamEvent,
    UsageSummary,
)

log = logging.getLogger(__name__)


# Honoured search paths for the codex binary (highest priority first).
# Matches the discovery order used by the petri-audit codex_cli_provider.
_CODEX_BINARY_HINTS: tuple[str, ...] = (
    "codex",  # PATH lookup
    "/Users/mango/.local/bin/codex",
    "/Applications/cmux.app/Contents/Resources/codex/bin/codex",
)


@dataclass
class CodexCliAdapter:
    """Local ``codex`` CLI subprocess adapter."""

    name: str = "codex-cli"
    provider: str = "openai"
    source: str = SOURCE_ADAPTER
    billing_type: AdapterBillingType = AdapterBillingType.SUBSCRIPTION_INCLUDED
    _last_error: Exception | None = field(default=None, init=False, repr=False)

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        import asyncio

        from core.orchestration.codex_cli_lane import acquire_codex_cli_lane_async

        binary = _resolve_codex_binary()
        if not binary:
            raise RuntimeError(
                "CodexCliAdapter: ``codex`` binary not found on PATH or known hints. "
                "Install the Codex CLI or use the openai-payg / codex-oauth adapter."
            )
        argv = [binary, "exec", "--model", req.model, "--full-auto"]
        stdin_text = build_subprocess_stdin(req)
        lane_key = f"codex-cli:{req.model}"
        async with acquire_codex_cli_lane_async(lane_key):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except (FileNotFoundError, OSError) as exc:
                self._last_error = exc
                raise RuntimeError(f"codex-cli: spawn failed — {exc!r}") from exc
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(stdin_text.encode("utf-8")),
                    timeout=600.0,
                )
            except TimeoutError as exc:
                proc.kill()
                await proc.wait()
                self._last_error = exc
                raise RuntimeError("codex-cli: subprocess timeout after 600s") from exc
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        rc = proc.returncode or 0
        if rc != 0:
            err_excerpt = stderr.strip().splitlines()[-1] if stderr.strip() else "<no stderr>"
            raise RuntimeError(f"codex-cli subprocess exited rc={rc}: {err_excerpt}")
        return AdapterCallResult(
            text=stdout,
            usage=UsageSummary(),
            stop_reason="end_turn",
        )

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        result = await self.acomplete(req)
        if result.text:
            yield StreamEvent(kind="text", payload={"text": result.text})
        yield StreamEvent(kind="stop", payload={"stop_reason": result.stop_reason})

    def test_environment(self) -> EnvironmentReport:
        binary = _resolve_codex_binary()
        if not binary:
            return EnvironmentReport(
                ok=False,
                checks=(("codex_binary", "missing"),),
                hints=(
                    "Install the Codex CLI (https://github.com/openai/codex-cli) "
                    "and ensure it's on PATH.",
                ),
            )
        from pathlib import Path

        auth = Path.home() / ".codex" / "auth.json"
        if not auth.is_file():
            return EnvironmentReport(
                ok=False,
                checks=(
                    ("codex_binary", binary),
                    ("codex_auth", "missing"),
                ),
                hints=("Run ``codex auth login`` to provision the OAuth token.",),
            )
        return EnvironmentReport(
            ok=True,
            checks=(
                ("codex_binary", binary),
                ("codex_auth", str(auth)),
            ),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import CODEX_FALLBACK_CHAIN, CODEX_PRIMARY

        ids = [CODEX_PRIMARY, *CODEX_FALLBACK_CHAIN]
        seen: set[str] = set()
        out: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            out.append(
                ModelSpec(
                    id=mid,
                    label=f"{mid} (via codex-cli)",
                    context_tokens=128_000,
                    supports_thinking=mid.startswith(("o3", "o4")),
                    supports_tools=False,
                )
            )
        return out

    def get_quota_windows(self) -> QuotaWindows | None:
        return None

    def detect_credential(self) -> CredentialDetection | None:
        binary = _resolve_codex_binary()
        if not binary:
            return None
        from core.config import CODEX_PRIMARY

        return CredentialDetection(
            model=CODEX_PRIMARY,
            provider=self.provider,
            source_path=f"{binary} (subscription via ~/.codex/auth.json)",
        )


def _resolve_codex_binary() -> str:
    """Resolve the ``codex`` binary path, honouring known hints + PATH lookup."""
    for hint in _CODEX_BINARY_HINTS:
        path = shutil.which(hint) if "/" not in hint else (hint if _is_exec(hint) else "")
        if path:
            return path
    return ""


def _is_exec(path: str) -> bool:
    import os

    return os.path.isfile(path) and os.access(path, os.X_OK)


__all__ = ["CodexCliAdapter"]
