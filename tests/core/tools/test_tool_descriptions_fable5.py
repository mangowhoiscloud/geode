"""Guards for the Fable 5 tool-description pass (PR-TOOL-DESC-FABLE5).

Pins:
- rerun_node stays removed (it was vestigial: the allowed-set was hardcoded
  empty so it always errored, and it referenced pipeline nodes removed in the
  LangGraph purge).
- Sibling-collision pairs carry mutual disambiguation so the model can pick the
  right tool (memory_save/note_save once shared the "remember this" trigger).
- No stale Game-IP / pipeline vocabulary survives in any description.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFINITIONS_PATH = Path(__file__).resolve().parents[3] / "core" / "tools" / "definitions.json"


def _descriptions() -> dict[str, str]:
    tools: list[dict[str, Any]] = json.loads(_DEFINITIONS_PATH.read_text())
    return {t["name"]: t["description"] for t in tools}


def test_rerun_node_removed() -> None:
    assert "rerun_node" not in _descriptions()


def test_sibling_collisions_disambiguated() -> None:
    d = _descriptions()
    # memory_save vs note_save shared the "remember this" trigger — each points at the other.
    assert "note_save" in d["memory_save"]
    assert "memory_save" in d["note_save"]
    # recall siblings cross-reference.
    assert "note_read" in d["memory_search"] or "session_search" in d["memory_search"]
    assert "memory_search" in d["note_read"]
    # plan vs task list.
    assert "create_plan" in d["task_create"]


def test_no_stale_pipeline_vocabulary() -> None:
    blob = "\n".join(_descriptions().values()).lower()
    for stale in ("analysis result", "analysis plan", "pipeline node", "pipeline step"):
        assert stale not in blob, f"stale vocabulary '{stale}' still in a tool description"


def test_all_descriptions_nonempty() -> None:
    assert all(desc.strip() for desc in _descriptions().values())
