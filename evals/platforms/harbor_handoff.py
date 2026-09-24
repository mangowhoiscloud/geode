"""Task-scoped decision handoff in Harbor, reusing GEODE's real AgenticLoop."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import logging
import os
import shlex
import signal
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from evals.platforms.harbor_runtime import (
    _INSTALL,
    _LOGS,
    GeodeRuntimeHarborAgent,
    _stop_runtime,
)


def _task(path: Path, digest: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("handoff task digest mismatch")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value)
        not in (
            {"case", "orders", "intervention"},
            {"case", "orders", "intervention", "verification_intervention"},
        )
        or not isinstance(value["case"], dict)
        or not isinstance(value["case"].get("request"), str)
        or not value["case"]["request"]
        or not isinstance(value["case"].get("id"), str)
        or not value["case"]["id"]
        or not isinstance(value["orders"], dict)
        or not value["orders"]
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in value["orders"].items())
        or (value["intervention"] is not None and not isinstance(value["intervention"], dict))
    ):
        raise ValueError("invalid handoff task contract")
    if value["case"].get("profile") is not None:
        from evals.benchmarks.decision_handoff_runtime import validate_inbox_case

        validate_inbox_case(value["case"], value["orders"])
        if value["intervention"] is not None:
            raise ValueError("inbox does not accept a single-request intervention")
    if "verification_intervention" in value:
        from evals.benchmarks.decision_handoff_runtime import validate_verification_intervention

        if not isinstance(value["verification_intervention"], dict):
            raise ValueError("candidate intervention must be an explicit object")
        validate_verification_intervention(value["verification_intervention"], value["case"])
    return value


class GeodeHandoffHarborAgent(GeodeRuntimeHarborAgent):
    """A separate two-tool profile; the native shell profile remains unchanged."""

    @staticmethod
    def name() -> str:
        return "geode-handoff"

    def __init__(
        self,
        *args: Any,
        arm: str,
        case_file: str,
        case_sha256: str,
        typesafe_key_file: str | None = None,
        verification_engine: str | None = None,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("prompt_template_path") or kwargs.get("env") or kwargs.get("extra_env"):
            raise ValueError("handoff profile forbids prompt templates and extra environment")
        super().__init__(*args, **kwargs)
        if (
            arm not in {"a0", "a", "b"}
            or str(self.model_name).removeprefix("geode/") != "gpt-6-astra"
            or self.effort != "xhigh"
            or verification_engine not in {None, "llm", "jev"}
            or self.verify_mode != ("llm_judge" if verification_engine else "rule_based")
            or self.agent_timeout_sec != 180
            or (arm == "b" or verification_engine == "jev") != (typesafe_key_file is not None)
            or (verification_engine is not None and arm != "a0")
        ):
            raise ValueError("handoff model, arm, verifier or credential scope mismatch")
        self.arm = arm
        self.verification_engine = verification_engine
        self.case_file = Path(case_file).resolve(strict=True)
        self.case_sha256 = case_sha256
        self.task = _task(self.case_file, case_sha256)
        if verification_engine is not None and self.task["case"].get("profile") != "inbox":
            raise ValueError("matched verification requires the complete-candidate inbox")
        if arm == "a0" and self.task["intervention"] is not None:
            raise ValueError("unassisted arm cannot have a helper intervention")
        if "verification_intervention" in self.task and verification_engine is None:
            raise ValueError("candidate intervention requires matched verification")
        self.typesafe_key_file = Path(typesafe_key_file) if typesafe_key_file else None
        if self.typesafe_key_file is not None:
            info = self.typesafe_key_file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("TypeSafe secret must be an owner-only regular file")

    async def install(self, environment: Any) -> None:
        await super().install(environment)
        _task(self.case_file, self.case_sha256)
        await environment.upload_file(self.case_file, f"{_INSTALL}/handoff-task.json")
        if self.typesafe_key_file is not None:
            info = self.typesafe_key_file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("TypeSafe secret must be an owner-only regular file")
            await self._upload_credential(
                environment, self.typesafe_key_file, f"{_INSTALL}/typesafe.key"
            )

    def _classify_exec_error(self, command: str, result: Any) -> Any:
        if result.return_code == 124 and " -m evals.platforms.harbor_handoff " in command:
            error = importlib.import_module("harbor.trial.errors").AgentTimeoutError
            return error("Handoff runtime deadline exceeded")
        return super()._classify_exec_error(command, result)

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        from core.memory.atomic_write import atomic_write_json

        if instruction != self.task["case"]["request"]:
            raise ValueError("task instruction differs from frozen handoff request")
        await self.exec_as_agent(
            environment, command=f"test ! -e {_LOGS}/geode-home && mkdir {_LOGS}/geode-home"
        )
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        names = ["lookup_order_status"]
        if self.arm != "a0":
            names.insert(0, "analyze_request")
        atomic_write_json(
            self.logs_dir / "runtime-contract.json",
            {
                "source_revision": self.source_revision,
                "source_sha256": self.source_sha256,
                "runtime": "evals.benchmarks.decision_handoff_runtime:run_arm",
                "profile": "decision-handoff",
                "workload_profile": self.task["case"].get("profile", "single-request"),
                "arm": self.arm,
                "case_sha256": self.case_sha256,
                "case_id": self.task["case"]["id"],
                "intervention": self.task["intervention"],
                **(
                    {"verification_intervention": self.task["verification_intervention"]}
                    if "verification_intervention" in self.task
                    else {}
                ),
                "external_search_loop": False,
                "model": "gpt-6-astra",
                "source": "subscription",
                "effort": "xhigh",
                "verify_mode": self.verify_mode,
                **(
                    {"verification_engine": self.verification_engine}
                    if self.verification_engine
                    else {}
                ),
                "required_tools": names,
                "agent_timeout_sec": self.agent_timeout_sec,
                "profile_scope": "fresh task container; no shell or filesystem tool",
            },
        )
        arguments = [
            f"{_INSTALL}/.venv/bin/python",
            "-m",
            "evals.platforms.harbor_handoff",
            "--arm",
            self.arm,
            "--task",
            f"{_INSTALL}/handoff-task.json",
            "--task-sha256",
            self.case_sha256,
            "--revision",
            self.source_revision,
            "--timeout",
            str(self.agent_timeout_sec),
        ]
        if self.verification_engine is not None:
            arguments.extend(("--verification-engine", self.verification_engine))
        try:
            await self.exec_as_agent(
                environment,
                command=shlex.join(arguments) + f" > {_LOGS}/runtime.log 2>&1",
                env={"GEODE_HOME": f"{_LOGS}/geode-home", "PYTHONFAULTHANDLER": "1"},
            )
        except BaseException as primary:
            stop = asyncio.create_task(
                _stop_runtime(environment, module="evals.platforms.harbor_handoff")
            )
            while not stop.done():
                try:
                    await asyncio.shield(stop)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            try:
                stop.result()
            except BaseException as error:
                primary.add_note("handoff finalization failed: " + type(error).__name__)
                try:
                    path = self.logs_dir / "runtime-contract.json"
                    contract = json.loads(path.read_text())
                    contract["finalization_errors"] = [
                        {"stage": "host_stop_runtime", "error_type": type(error).__name__}
                    ]
                    atomic_write_json(path, contract)
                except BaseException as receipt_error:
                    primary.add_note("handoff receipt failed: " + type(receipt_error).__name__)
            raise


async def _run_handoff(args: argparse.Namespace) -> int:
    verification_engine = getattr(args, "verification_engine", None)
    if args.timeout != 180 or args.arm not in {"a0", "a", "b"}:
        raise ValueError("handoff execution contract mismatch")
    if verification_engine not in {None, "llm", "jev"} or (
        verification_engine and args.arm != "a0"
    ):
        raise ValueError("matched verification engine or arm mismatch")
    if not Path("/.dockerenv").is_file() or os.environ.get("GEODE_HOME") != f"{_LOGS}/geode-home":
        raise RuntimeError("container-local handoff entry point only")
    if any(value for key, value in os.environ.items() if key.endswith("API_KEY")):
        raise RuntimeError("API credentials must not be supplied through the environment")
    os.umask(0o077)
    directory = Path(_LOGS)
    (directory / "runtime.pid").write_text(str(os.getpid()))
    from core.memory.atomic_write import atomic_write_json

    atomic_write_json(
        directory / "runtime-finalized.json", {"exports_complete": False, "status": "bootstrap"}
    )
    event_loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    assert current is not None
    event_loop.add_signal_handler(signal.SIGTERM, current.cancel)
    errors: list[dict[str, str]] = []
    result: dict[str, Any] | None = None
    started = False
    secret_path = Path(f"{_INSTALL}/typesafe.key")
    from evals.platforms.harbor import _summarize_usage

    metadata: dict[str, Any] = {
        "source_revision": args.revision,
        "verify_mode": "llm_judge" if verification_engine else "rule_based",
        **({"verification_engine": verification_engine} if verification_engine else {}),
        "profile": "decision-handoff",
        "arm": args.arm,
        "execution_started": False,
        "error_type": None,
        "finalization_errors": errors,
        "usage": _summarize_usage([]),
        "score_authority": "Harbor task verifier, not runtime receipt",
    }

    @contextmanager
    def stage(name: str) -> Iterator[None]:
        try:
            yield
        except BaseException as error:
            errors.append({"stage": name, "error_type": type(error).__name__})

    execution_stage = "handoff_bootstrap"
    try:
        value = _task(Path(args.task), args.task_sha256)
        if verification_engine and value["case"].get("profile") != "inbox":
            raise ValueError("matched verification requires inbox")
        workspace = Path("/workspace")
        workspace.mkdir(exist_ok=True)
        os.chdir(workspace)
        os.environ["GEODE_VERIFY_MODE"] = metadata["verify_mode"]
        os.environ["GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR"] = "1"
        logging.disable(logging.CRITICAL)
        from core.config import settings
        from pydantic import SecretStr

        from evals.benchmarks.decision_handoff_runtime import run_arm

        settings.llm_max_retries = 1
        settings.cost_limit_usd = 0
        secret = None
        execution_stage = "credential_load"
        if args.arm == "b" or verification_engine == "jev":
            info = secret_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RuntimeError("unsafe TypeSafe credential file")
            secret = SecretStr(secret_path.read_text().strip())
            secret_path.unlink()
            if not secret.get_secret_value():
                raise RuntimeError("TypeSafe credential unavailable")
        elif secret_path.exists():
            raise RuntimeError("TypeSafe credential leaked into non-Jev arm")
        started = True
        metadata["execution_started"] = True
        execution_stage = "handoff_execution"
        result = await run_arm(
            value["case"],
            args.arm,
            directory,
            orders=value["orders"],
            api_key=secret,
            intervention=value["intervention"],
            verification_engine=verification_engine,
            verification_intervention=value.get("verification_intervention"),
        )
    except BaseException as error:
        errors.append({"stage": execution_stage, "error_type": type(error).__name__})
        metadata["error_type"] = type(error).__name__
    finally:
        with stage("credential_cleanup"):
            secret_path.unlink(missing_ok=True)
        with stage("signal_handler_remove"):
            event_loop.remove_signal_handler(signal.SIGTERM)
        if result:
            from core.observability.trajectory import export_trajectory, trajectory_from_sessions

            metadata.update(
                geode_session_id=result["session_id"],
                termination_reason=result["termination_reason"],
                error_type=result["error_type"],
                usage=result["usage"],
            )
            metadata["usage"]["source_snapshot_complete"] = result["source_snapshot_complete"]
            with stage("handoff_result"):
                atomic_write_json(directory / "handoff-result.json", result)
            for policy, filename in (
                ("full", "geode-trajectory.private.json"),
                ("digest", "geode-trajectory.json"),
            ):
                with stage(f"trajectory_{policy}"):
                    trajectory = trajectory_from_sessions(
                        [result["session_id"]],
                        trajectory_id=f"harbor-{result['session_id']}",
                        source={"harness": "harbor", "session": result["session_id"]},
                        db_path=Path(result["db_path"]),
                        outcome=metadata,
                        provenance={"adapter": "evals.platforms.harbor_handoff"},
                        privacy={"review_state": "local"},
                        content_policy=policy,
                    )
                    integrity = trajectory["integrity"]
                    if not result["source_snapshot_complete"]:
                        integrity.update(
                            complete=False, scope_complete=False, replay_complete=False
                        )
                        integrity["scope_incompleteness"].append(
                            "handoff source snapshot incomplete"
                        )
                        integrity["incompleteness"] = list(
                            dict.fromkeys(
                                integrity["scope_incompleteness"]
                                + integrity["replay_incompleteness"]
                            )
                        )
                    export_trajectory(directory / filename, trajectory)
                    if not integrity["scope_complete"]:
                        raise RuntimeError("incomplete handoff trajectory")
                    if policy == "full" and not integrity["replay_complete"]:
                        raise RuntimeError("incomplete handoff replay")
        with stage("runtime_result"):
            atomic_write_json(
                directory / "runtime-result.json",
                {
                    "usage": metadata["usage"],
                    "metadata": metadata,
                    "tool_definitions": result["tool_definitions"] if result else [],
                },
            )
        with stage("runtime_receipt"):
            atomic_write_json(
                directory / "runtime-finalized.json",
                {
                    "exports_complete": bool(
                        result and result["source_snapshot_complete"] and not errors
                    ),
                    "status": "finalized",
                    "execution_started": started,
                    "error_type": metadata["error_type"],
                    "finalization_errors": errors,
                },
            )
    return 1 if errors or not result or not result["valid"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=("a0", "a", "b"))
    parser.add_argument("--task", required=True)
    parser.add_argument("--task-sha256", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--verification-engine", choices=("llm", "jev"))
    args = parser.parse_args()
    if args.timeout != 180:
        parser.error("the handoff runtime contract requires 180 seconds")
    return asyncio.run(_run_handoff(args))


if __name__ == "__main__":
    raise SystemExit(main())
