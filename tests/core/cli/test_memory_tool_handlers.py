"""memory_save / manage_rule / memory_search report the injected owner's outcome (S2)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from core.cli.tool_handlers.memory import _build_memory_handlers
from core.memory.project import ProjectMemory
from core.tools.memory_tools import MemoryToolServices, NoteSaveTool


def _handlers(memory: ProjectMemory) -> dict[str, Any]:
    return dict(_build_memory_handlers(MemoryToolServices(project_memory=memory)))


def test_memory_save_without_backing_file_is_an_error(tmp_path: Path) -> None:
    memory = ProjectMemory(tmp_path)
    result = _handlers(memory)["memory_save"](key="fact", content="a retained project fact")
    assert result["status"] == "error"
    assert result["outcome"] == "not_found"
    assert result["saved"] is False
    assert not memory.memory_file.exists()


def test_memory_save_reports_written_then_unchanged(tmp_path: Path) -> None:
    memory = ProjectMemory(tmp_path)
    memory.ensure_structure()
    save = _handlers(memory)["memory_save"]
    first = save(key="fact", content="a retained project fact")
    assert first["status"] == "ok" and first["saved"] is True
    second = save(key="fact", content="a retained project fact")
    assert second["status"] == "ok" and second["saved"] is False and second["unchanged"]
    assert memory.memory_file.read_text().count("fact: a retained project fact") == 1
    invalid = save(key="fact", content="line one\nline two of the content")
    assert invalid["status"] == "error" and invalid["error_type"] == "validation"


def test_handlers_use_the_injected_root_not_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    injected = tmp_path / "injected"
    elsewhere = tmp_path / "cwd"
    injected.mkdir()
    elsewhere.mkdir()
    memory = ProjectMemory(injected)
    memory.ensure_structure()
    monkeypatch.chdir(elsewhere)
    handlers = _handlers(memory)

    assert handlers["manage_rule"](action="create", name="style", content="be terse")["status"] == (
        "ok"
    )
    listed = handlers["manage_rule"](action="list")
    assert [rule["name"] for rule in listed["rules"]] == ["style"]
    assert handlers["memory_save"](key="k", content="fact in the injected root")["saved"]
    assert (injected / ".geode/rules/style.md").exists()
    assert not (elsewhere / ".geode").exists()


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"action": "create", "content": "x"}, ["name"]),
        ({"action": "create", "name": "r"}, ["content"]),
        ({"action": "update", "name": "r"}, ["content"]),
        ({"action": "delete"}, ["name"]),
    ],
)
def test_manage_rule_requires_fields(
    tmp_path: Path, kwargs: dict[str, str], expected: list[str]
) -> None:
    result = _handlers(ProjectMemory(tmp_path))["manage_rule"](**kwargs)
    assert result["clarification_needed"] is True
    assert result["missing"] == expected


def test_manage_rule_mutation_failures_are_errors(tmp_path: Path) -> None:
    memory = ProjectMemory(tmp_path)
    manage_rule = _handlers(memory)["manage_rule"]
    assert manage_rule(action="update", name="absent", content="x")["outcome"] == "not_found"
    assert manage_rule(action="delete", name="absent")["outcome"] == "not_found"
    assert manage_rule(action="create", name="r", content="v1")["status"] == "ok"
    conflict = manage_rule(action="create", name="r", content="v2")
    assert conflict["status"] == "error" and conflict["outcome"] == "conflict"
    assert manage_rule(action="rename", name="r")["status"] == "error"
    assert "v1" in (tmp_path / ".geode/rules/r.md").read_text()


def test_memory_search_filters_by_query_and_tier(tmp_path: Path) -> None:
    memory = ProjectMemory(tmp_path)
    memory.ensure_structure()
    memory.record_insight("alpha fact about deployment")
    memory.record_insight("beta fact about billing")
    result = _handlers(memory)["memory_search"](query="deployment", tier="project")
    assert result["status"] == "ok"
    lines = next(m for m in result["matches"] if m.get("source") == "MEMORY.md")["matching_lines"]
    assert any("deployment" in line for line in lines)
    assert not any("billing" in line for line in lines)


def test_note_save_reports_real_outcome(tmp_path: Path) -> None:
    missing = NoteSaveTool(MemoryToolServices(project_memory=ProjectMemory(tmp_path)))
    result = asyncio.run(missing.aexecute(key="parking", content="spot B2 on level 3"))
    assert "error" in result and result["error_type"] == "not_found"

    memory = ProjectMemory(tmp_path)
    memory.ensure_structure()
    tool = NoteSaveTool(MemoryToolServices(project_memory=memory))
    assert asyncio.run(tool.aexecute(key="parking", content="spot B2 on level 3"))["result"][
        "saved"
    ]
    again = asyncio.run(tool.aexecute(key="parking", content="spot B2 on level 3"))
    assert again["result"] == {"saved": False, "unchanged": True, "key": "parking"}


# memory_search over the shared session store: the gateway persists every
# channel/sender/thread conversation there, so search must not cross principals.
def _gateway_store() -> tuple[Any, str, str]:
    from core.memory.session import InMemorySessionStore
    from core.memory.session_key import build_gateway_session_key

    store = InMemorySessionStore()
    alice = build_gateway_session_key("slack", "C_PRIVATE_A", "U_ALICE")
    bob = build_gateway_session_key("slack", "C_TEAM_B", "U_BOB")
    store.set(alice, {"messages": [{"role": "user", "content": "alice-private-secret"}]})
    store.set(bob, {"messages": [{"role": "user", "content": "bob own note"}]})
    store.set("subject:demo:analysis", {"messages": "operator analysis record"})
    return store, alice, bob


def _search(memory: ProjectMemory, store: Any, context: Any = None, **kwargs: Any) -> Any:
    services = MemoryToolServices(session_store=store, project_memory=memory)
    handler = dict(_build_memory_handlers(services))["memory_search"]
    return handler(_tool_context=context, **kwargs)


def test_memory_search_cannot_read_another_gateway_conversation(tmp_path: Path) -> None:
    import json

    from core.memory.session_key import build_gateway_checkpoint_session_id
    from core.tools.base import ToolContext

    store, alice, bob = _gateway_store()
    bob_ctx = ToolContext(session_id=build_gateway_checkpoint_session_id(bob))
    result = _search(ProjectMemory(tmp_path), store, bob_ctx, query="messages", tier="session")
    found = {m["session_id"] for m in result["matches"]}
    assert "alice-private-secret" not in json.dumps(result, default=str)
    assert alice not in found
    assert bob in found  # same-thread recall still works


def test_memory_search_gateway_scope_for_operator_and_subagent(tmp_path: Path) -> None:
    import json
    from types import SimpleNamespace

    from core.memory.session_key import build_gateway_checkpoint_session_id
    from core.tools.base import ToolContext

    store, alice, bob = _gateway_store()
    memory = ProjectMemory(tmp_path)
    operator = _search(memory, store, None, query="messages", tier="session")
    assert {m["session_id"] for m in operator["matches"]} == {"subject:demo:analysis"}

    worker_loop = SimpleNamespace(_parent_session_id=build_gateway_checkpoint_session_id(alice))
    worker = ToolContext(session_id="s-worker", is_subagent=True, agent_loop=worker_loop)
    child = _search(memory, store, worker, query="messages", tier="session")
    found = {m["session_id"] for m in child["matches"]}
    assert alice in found and bob not in found
    assert "bob own note" not in json.dumps(child, default=str)
